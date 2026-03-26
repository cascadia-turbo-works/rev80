import pytest
import numpy as np
import vibechecker as vc

simsensor = vc.VibeSensor.simulated()

config = vc.AcquisitionSettings()
config.binsize = 2
config.maxfreq = 10000

dc = vc.DataCollector(simsensor, config)
stream: vc.SimulatedSensor | None = dc.stream \
        if isinstance(dc.stream, vc.SimulatedSensor) else None

tone_step = 500
tol = 1e-4


def _peak_amp_at(result: vc.ChannelResult, freq_hz: float) -> float:
    """Return the spectrum amplitude at the bin closest to freq_hz."""
    idx = int(np.abs(result.freq - freq_hz).argmin())
    return float(result.spectrum[idx])


# ── Integration tests ────────────────────────────────────────────────

@pytest.mark.parametrize('freq', range(tone_step, int(config.maxfreq), tone_step))
def test_tone_vel(freq):
    """Source=mm/s2 → target=mm/s: single integration.

    Tone amplitude set to 2*pi*freq so that after one integration the
    0-peak velocity amplitude equals 1.0.
    """
    if stream is None:
        return

    vel_ampl = 1.0
    acc_ampl = 2 * np.pi * freq * vel_ampl

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    result = sample.process(0, 'mm/s', config)
    assert result is not None
    assert np.abs(_peak_amp_at(result, freq) - vel_ampl) < tol


@pytest.mark.parametrize('freq', range(tone_step, int(config.maxfreq), tone_step))
def test_tone_acc(freq):
    """Source=mm/s2, target=mm/s2: passthrough — amplitude preserved."""
    if stream is None:
        return

    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    result = sample.process(0, 'mm/s2', config)
    assert result is not None
    assert np.abs(_peak_amp_at(result, freq) - acc_ampl) < tol


# ── Modality-aware integration tests ─────────────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_acc_to_displacement(freq):
    """Source=mm/s2 → target=mm: two integrations.

    displacement 0-peak = A / (2*pi*f)^2
    """
    if stream is None:
        return

    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    result = sample.process(0, 'mm', config)
    assert result is not None
    expected_disp = acc_ampl / (2 * np.pi * freq) ** 2

    actual = _peak_amp_at(result, freq)
    assert np.abs(actual - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {actual:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_vel_to_displacement(freq):
    """Source=mm/s → target=mm: one integration.

    displacement 0-peak = V / (2*pi*f)
    """
    if stream is None:
        return

    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s'

    result = sample.process(0, 'mm', config)
    assert result is not None
    expected_disp = vel_ampl / (2 * np.pi * freq)

    actual = _peak_amp_at(result, freq)
    assert np.abs(actual - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {actual:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_differentiation_vel_to_acc(freq):
    """Source=mm/s → target=mm/s2: one derivative.

    acceleration 0-peak = V * (2*pi*f)
    """
    if stream is None:
        return

    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s'

    result = sample.process(0, 'mm/s2', config)
    assert result is not None
    expected_acc = vel_ampl * (2 * np.pi * freq)

    actual = _peak_amp_at(result, freq)
    assert np.abs(actual - expected_acc) < tol, \
        f'At {freq}Hz: expected {expected_acc:.6f}, got {actual:.6f}'


# ── Unit conversion tests ────────────────────────────────────────────

G_TO_MM_S2 = 9.80665 * 1000             # 1 g = 9806.65 mm/s²
G_TO_IN_S2 = 9.80665 * 1000 / 25.4      # 1 g = 386.089 in/s²
G_TO_MIL_S2 = 9.80665 * 1000 / 25.4 * 1000  # 1 g = 386088.58 mil/s²


@pytest.mark.parametrize('target_unit, factor', [
    ('mm/s2', G_TO_MM_S2),
    ('in/s2', G_TO_IN_S2),
    ('mil/s2', G_TO_MIL_S2),
])
@pytest.mark.parametrize('freq', [500, 1000])
def test_unit_conversion_acc_spectrum(target_unit, factor, freq):
    """Verify g → target acceleration unit scales spectrum amplitudes.

    Same modality (acceleration → acceleration) so no integration involved.
    """
    if stream is None:
        return

    acc_ampl = 1.0
    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)

    sample = dc.collect_sample()[0]
    sample.unit = 'g'

    result_g = sample.process(0, 'g', config)
    result_t = sample.process(0, target_unit, config)
    assert result_g is not None and result_t is not None

    val_g = _peak_amp_at(result_g, freq)
    val_t = _peak_amp_at(result_t, freq)

    ratio = val_t / val_g
    assert np.abs(ratio - factor) < 0.01, \
        f'Unit conversion {freq}Hz g→{target_unit}: expected ratio {factor:.2f}, got {ratio:.2f}'


# ── Amplitude mode tests ─────────────────────────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_amplitude_modes_ratio(freq):
    """Verify RMS, 0-P, P-P produce correct ratios at a tone frequency."""
    if stream is None:
        return

    stream.source = (vc.GenerateTone, 1.0, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    cfg_rms = vc.AcquisitionSettings()
    cfg_rms.binsize = config.binsize
    cfg_rms.maxfreq = config.maxfreq
    cfg_rms.amplitude_mode = 'RMS'

    cfg_0p = vc.AcquisitionSettings()
    cfg_0p.binsize = config.binsize
    cfg_0p.maxfreq = config.maxfreq
    cfg_0p.amplitude_mode = '0-P'

    cfg_pp = vc.AcquisitionSettings()
    cfg_pp.binsize = config.binsize
    cfg_pp.maxfreq = config.maxfreq
    cfg_pp.amplitude_mode = 'P-P'

    r_rms = sample.process(0, 'mm/s2', cfg_rms)
    r_0p  = sample.process(0, 'mm/s2', cfg_0p)
    r_pp  = sample.process(0, 'mm/s2', cfg_pp)
    assert r_rms is not None and r_0p is not None and r_pp is not None

    v_rms = _peak_amp_at(r_rms, freq)
    v_0p  = _peak_amp_at(r_0p, freq)
    v_pp  = _peak_amp_at(r_pp, freq)

    # 0-P = RMS * sqrt(2)
    assert np.abs(v_0p / v_rms - np.sqrt(2)) < tol, \
        f'0-P/RMS ratio: expected {np.sqrt(2):.4f}, got {v_0p/v_rms:.4f}'
    # P-P = 0-P * 2
    assert np.abs(v_pp / v_0p - 2.0) < tol, \
        f'P-P/0-P ratio: expected 2.0, got {v_pp/v_0p:.4f}'


# ── Cross-modality time series tests ─────────────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_cross_modality_time_series(freq):
    """Verify cross-modality time series uses IFFT integration, not just scaling.

    For acc→vel, the time-domain peak should be within the right order of
    magnitude of A/(2*pi*f), NOT still at the acceleration amplitude.
    Exact match is not expected due to filter transients and spectral leakage
    in the simulated capture pipeline.
    """
    if stream is None:
        return

    acc_ampl = 2 * np.pi * freq  # → ~1.0 mm/s velocity peak
    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    result = sample.process(0, 'mm/s', config)
    assert result is not None

    peak_time = float(np.max(np.abs(result.time_data)))
    expected_vel = acc_ampl / (2 * np.pi * freq)  # = 1.0

    # Must be in the velocity ballpark, NOT at acceleration scale
    assert peak_time < expected_vel * 3.0, \
        f'Time peak {peak_time:.2f} still at acceleration scale (expected ~{expected_vel:.2f})'
    assert peak_time > expected_vel * 0.3, \
        f'Time peak {peak_time:.4f} too small (expected ~{expected_vel:.2f})'
