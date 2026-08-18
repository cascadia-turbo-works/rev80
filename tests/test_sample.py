import pytest
import numpy as np
import vibechecker as vc
from vibechecker.scope_sensor import ScopeSensor

tone_step = 500
tol = 1e-4
overall_tol = 0.01   # 1% relative — tight enough to catch the ~22% excess, loose enough for Welch window error


def _peak_amp_at(result: vc.ChannelResult, freq_hz: float) -> float:
    """Return the spectrum amplitude at the bin closest to freq_hz."""
    idx = int(np.abs(result.freq - freq_hz).argmin())
    return float(result.spectrum[idx])


def _make_dc(eu: str = 'mm/s2', sensitivity: float = 1.0,
             target_unit: str = '', amp_mode: str = '0-P'):
    cfg = vc.AcquisitionSettings()
    cfg.binsize = 2
    cfg.maxfreq = 10000
    cfg.highpass_enabled = False
    if target_unit:
        cfg.channel_target_units[0] = target_unit
    cfg.channel_amplitude_modes[0] = amp_mode
    dc_local = vc.DataCollector(vc.VibeSensor.simulated(), cfg)
    dc_local.set_scope_sensor(0, ScopeSensor(name='test', engineering_units=eu, sensitivity=sensitivity))
    return dc_local


# ── Integration tests ────────────────────────────────────────────────

@pytest.mark.parametrize('freq', range(tone_step, 10000, tone_step))
def test_tone_vel(freq):
    """Source=mm/s2 → target=mm/s: single integration.

    Tone amplitude set to 2*pi*freq so that after one integration the
    0-peak velocity amplitude equals 1.0.
    """
    vel_ampl = 1.0
    acc_ampl = 2 * np.pi * freq * vel_ampl

    dc_local = _make_dc(eu='mm/s2', target_unit='mm/s')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

    assert result is not None
    assert np.abs(_peak_amp_at(result, freq) - vel_ampl) < tol
    # For a pure tone, overall (0-P) == tone amplitude (Parseval)
    assert np.abs(result.overall - vel_ampl) < overall_tol * vel_ampl, \
        f'test_tone_vel at {freq}Hz: overall={result.overall:.6f}, expected~{vel_ampl:.6f}'


@pytest.mark.parametrize('freq', range(tone_step, 10000, tone_step))
def test_tone_acc(freq):
    """Source=mm/s2, target=mm/s2: passthrough — amplitude preserved."""
    acc_ampl = 1.0

    dc_local = _make_dc(eu='mm/s2', target_unit='mm/s2')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

    assert result is not None
    assert np.abs(_peak_amp_at(result, freq) - acc_ampl) < tol
    # For a pure tone, overall (0-P) == tone amplitude (Parseval)
    assert np.abs(result.overall - acc_ampl) < overall_tol * acc_ampl, \
        f'test_tone_acc at {freq}Hz: overall={result.overall:.6f}, expected~{acc_ampl:.6f}'


# ── Modality-aware integration tests ─────────────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_acc_to_displacement(freq):
    """Source=mm/s2 → target=mm: two integrations.

    displacement 0-peak = A / (2*pi*f)^2
    """
    acc_ampl = 1.0

    dc_local = _make_dc(eu='mm/s2', target_unit='mm')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

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
    vel_ampl = 1.0

    dc_local = _make_dc(eu='mm/s', target_unit='mm')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

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
    vel_ampl = 1.0

    dc_local = _make_dc(eu='mm/s', target_unit='mm/s2')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

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
    acc_ampl = 1.0

    dc_g = _make_dc(eu='g', target_unit='g')
    dc_t = _make_dc(eu='g', target_unit=target_unit)

    stream_g = dc_g.stream
    stream_t = dc_t.stream
    if not isinstance(stream_g, vc.SimulatedSensor) or not isinstance(stream_t, vc.SimulatedSensor):
        dc_g.disconnect_sensor()
        dc_t.disconnect_sensor()
        return

    stream_g.source = (vc.GenerateTone, acc_ampl, freq, 0)
    stream_t.source = (vc.GenerateTone, acc_ampl, freq, 0)

    sample_g = dc_g.collect_sample()[0]
    sample_t = dc_t.collect_sample()[0]

    result_g = dc_g.process_sample(0, sample_g)
    result_t = dc_t.process_sample(0, sample_t)

    dc_g.disconnect_sensor()
    dc_t.disconnect_sensor()

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
    dc_rms = _make_dc(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS')
    dc_0p  = _make_dc(eu='mm/s2', target_unit='mm/s2', amp_mode='0-P')
    dc_pp  = _make_dc(eu='mm/s2', target_unit='mm/s2', amp_mode='P-P')

    stream_rms = dc_rms.stream
    stream_0p  = dc_0p.stream
    stream_pp  = dc_pp.stream

    if not all(isinstance(s, vc.SimulatedSensor) for s in [stream_rms, stream_0p, stream_pp]):
        for dc in [dc_rms, dc_0p, dc_pp]:
            dc.disconnect_sensor()
        return

    for s in [stream_rms, stream_0p, stream_pp]:
        s.source = (vc.GenerateTone, 1.0, freq, 0)

    sample_rms = dc_rms.collect_sample()[0]
    sample_0p  = dc_0p.collect_sample()[0]
    sample_pp  = dc_pp.collect_sample()[0]

    r_rms = dc_rms.process_sample(0, sample_rms)
    r_0p  = dc_0p.process_sample(0, sample_0p)
    r_pp  = dc_pp.process_sample(0, sample_pp)

    for dc in [dc_rms, dc_0p, dc_pp]:
        dc.disconnect_sensor()

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
    acc_ampl = 2 * np.pi * freq  # → ~1.0 mm/s velocity peak

    dc_local = _make_dc(eu='mm/s2', target_unit='mm/s')
    stream_local = dc_local.stream
    if not isinstance(stream_local, vc.SimulatedSensor):
        dc_local.disconnect_sensor()
        return
    stream_local.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc_local.collect_sample()[0]
    result = dc_local.process_sample(0, sample)
    dc_local.disconnect_sensor()

    assert result is not None

    peak_time = float(np.max(np.abs(result.time_data)))
    expected_vel = acc_ampl / (2 * np.pi * freq)  # = 1.0

    # Must be in the velocity ballpark, NOT at acceleration scale
    assert peak_time < expected_vel * 3.0, \
        f'Time peak {peak_time:.2f} still at acceleration scale (expected ~{expected_vel:.2f})'
    assert peak_time > expected_vel * 0.3, \
        f'Time peak {peak_time:.4f} too small (expected ~{expected_vel:.2f})'
