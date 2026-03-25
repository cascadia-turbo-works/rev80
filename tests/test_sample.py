import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc

simsensor = vc.VibeSensor.simulated()


config = vc.AcquisitionSettings()
config.binsize = 2
config.maxfreq = 10000

dc = vc.DataCollector(simsensor, config)
stream: vc.SimulatedSensor | None = dc.stream \
        if isinstance(dc.stream,vc.SimulatedSensor) else None

tone_step = 500
tol = 1e-4


@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_vel(freq):
    """Source=mm/s2 (acceleration), target=mm/s (velocity): verify single integration.

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

    fft, peak = sample.fft('mm/s', config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.display_0p - vel_ampl) < tol


@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_acc(freq):
    """Source=mm/s2, target=mm/s2: passthrough — amplitude preserved."""
    if stream is None:
        return

    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    fft, peak = sample.fft('mm/s2', config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.display_0p - acc_ampl) < tol


# ── Task 2: Modality-aware integration tests ──────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_acc_to_displacement(freq):
    """Source=mm/s2 (acceleration), target=mm (displacement): two integrations.

    For a cosine tone at frequency f with 0-peak acceleration amplitude A:
      displacement 0-peak = A / (2*pi*f)^2
    """
    if stream is None:
        return

    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s2'

    fft, peak = sample.fft('mm', config)

    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_disp = acc_ampl / (2 * np.pi * freq) ** 2

    assert np.abs(row.display_0p - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {row.display_0p:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_vel_to_displacement(freq):
    """Source=mm/s (velocity), target=mm (displacement): one integration.

    For a velocity tone at frequency f with amplitude V:
      displacement 0-peak = V / (2*pi*f)
    """
    if stream is None:
        return

    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s'

    fft, peak = sample.fft('mm', config)
    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_disp = vel_ampl / (2 * np.pi * freq)

    assert np.abs(row.display_0p - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {row.display_0p:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_differentiation_vel_to_acc(freq):
    """Source=mm/s (velocity), target=mm/s2 (acceleration): one derivative.

    For a velocity tone at frequency f with amplitude V:
      acceleration 0-peak = V * (2*pi*f)
    """
    if stream is None:
        return

    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()[0]
    sample.unit = 'mm/s'

    fft, peak = sample.fft('mm/s2', config)
    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_acc = vel_ampl * (2 * np.pi * freq)

    assert np.abs(row.display_0p - expected_acc) < tol, \
        f'At {freq}Hz: expected {expected_acc:.6f}, got {row.display_0p:.6f}'


# ── Task 3: Unit conversion tests ────────────────────────────────────

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
    """Verify that converting source g → target acceleration unit scales FFT amplitudes.

    A 1.0 g 0-peak tone should appear as `factor` in the target unit system.
    Same modality (acceleration → acceleration) so no integration involved.
    """
    if stream is None:
        return

    acc_ampl = 1.0
    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)

    sample = dc.collect_sample()[0]
    sample.unit = 'g'

    # FFT in g (passthrough)
    fft_g, _ = sample.fft('g', config)
    val_g = fft_g.loc[np.abs(fft_g.freq - freq).argmin()].display_0p

    # FFT in target unit (same modality — only amplitude scaling)
    fft_t, _ = sample.fft(target_unit, config)
    val_t = fft_t.loc[np.abs(fft_t.freq - freq).argmin()].display_0p

    ratio = val_t / val_g
    assert np.abs(ratio - factor) < 0.01, \
        f'Unit conversion {freq}Hz g→{target_unit}: expected ratio {factor:.2f}, got {ratio:.2f}'
