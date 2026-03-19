import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc

devs = vc.VibeSensor.find()
simsensor = devs[0]


config = vc.AcquisitionSettings()
config.binsize = 2
config.maxfreq = 10000
config.units = 'mm'
config.integrate = 'acceleration'   # target: acceleration (passthrough for accel source)

dc = vc.DataCollector(simsensor, config)
stream: vc.SimulatedSensor | None = dc.stream \
        if isinstance(dc.stream,vc.SimulatedSensor) else None

tone_step = 500
tol = 1e-4


@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_vel(freq):
    """Source=acceleration, target=velocity: verify single integration."""
    if stream is None:
        return

    config.integrate = 'velocity'
    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, 2*np.pi*freq*vel_ampl, freq, 0)
    sample = dc.collect_sample()
    fft, peak = sample.fft(config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.display_0p - vel_ampl) < tol


@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_acc(freq):
    """Source=acceleration, target=acceleration: passthrough."""
    if stream is None:
        return

    config.integrate = 'acceleration'
    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()
    fft, peak = sample.fft(config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.display_0p - acc_ampl) < tol


# ── Task 2: Modality-aware integration tests ──────────────────────────

@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_acc_to_displacement(freq):
    """Source=acceleration, target=displacement: two integrations.

    For a cosine tone at frequency f with 0-peak acceleration amplitude A:
      displacement 0-peak = A / (2*pi*f)^2
    """
    if stream is None:
        return

    config.integrate = 'displacement'
    acc_ampl = 1.0

    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()
    fft, peak = sample.fft(config)

    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_disp = acc_ampl / (2 * np.pi * freq) ** 2

    assert np.abs(row.display_0p - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {row.display_0p:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_integration_vel_to_displacement(freq):
    """Source=velocity (simulated), target=displacement: one integration.

    Create a VibeSample with modality='velocity'.
    For a velocity tone at frequency f with amplitude V:
      displacement 0-peak = V / (2*pi*f)
    """
    if stream is None:
        return

    config.integrate = 'displacement'
    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()
    # Override modality to velocity (simulating a velocity sensor)
    sample.modality = 'velocity'

    fft, peak = sample.fft(config)
    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_disp = vel_ampl / (2 * np.pi * freq)

    assert np.abs(row.display_0p - expected_disp) < tol, \
        f'At {freq}Hz: expected {expected_disp:.6f}, got {row.display_0p:.6f}'


@pytest.mark.parametrize('freq', [500, 1000])
def test_differentiation_vel_to_acc(freq):
    """Source=velocity, target=acceleration: one derivative.

    For a velocity tone at frequency f with amplitude V:
      acceleration 0-peak = V * (2*pi*f)
    """
    if stream is None:
        return

    config.integrate = 'acceleration'
    vel_ampl = 1.0

    stream.source = (vc.GenerateTone, vel_ampl, freq, 0)
    sample = dc.collect_sample()
    sample.modality = 'velocity'

    fft, peak = sample.fft(config)
    row = fft.loc[np.abs(fft.freq - freq).argmin()]
    expected_acc = vel_ampl * (2 * np.pi * freq)

    assert np.abs(row.display_0p - expected_acc) < tol, \
        f'At {freq}Hz: expected {expected_acc:.6f}, got {row.display_0p:.6f}'


# ── Task 3: Unit conversion tests ────────────────────────────────────

G_TO_MM = 9.80665 * 1000                # 1 g = 9806.65 mm/s²
G_TO_IN = 9.80665 * 1000 / 25.4         # 1 g = 386.089 in/s²
G_TO_MIL = 9.80665 * 1000 / 25.4 * 1000 # 1 g = 386088.58 mil/s²


@pytest.mark.parametrize('target_unit, factor', [
    ('mm', G_TO_MM),
    ('in', G_TO_IN),
    ('mil', G_TO_MIL),
])
@pytest.mark.parametrize('freq', [500, 1000])
def test_unit_conversion_acc_spectrum(target_unit, factor, freq):
    """Verify that converting source g → target unit scales FFT amplitudes correctly.

    A 1.0 g 0-peak tone should appear as `factor` in the target unit system.
    """
    if stream is None:
        return

    acc_ampl = 1.0
    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)

    # Collect in 'g' (simulated sensor outputs mm but we test via VibeSample directly)
    sample = dc.collect_sample()
    # Override to g source for this test
    sample.unit = 'g'
    sample.modality = 'acceleration'

    # FFT in g
    cfg_g = vc.AcquisitionSettings()
    cfg_g.binsize = config.binsize
    cfg_g.maxfreq = config.maxfreq
    cfg_g.units = 'g'
    cfg_g.integrate = 'acceleration'
    fft_g, _ = sample.fft(cfg_g)
    val_g = fft_g.loc[np.abs(fft_g.freq - freq).argmin()].display_0p

    # FFT in target unit
    cfg_t = vc.AcquisitionSettings()
    cfg_t.binsize = config.binsize
    cfg_t.maxfreq = config.maxfreq
    cfg_t.units = target_unit
    cfg_t.integrate = 'acceleration'
    fft_t, _ = sample.fft(cfg_t)
    val_t = fft_t.loc[np.abs(fft_t.freq - freq).argmin()].display_0p

    ratio = val_t / val_g
    assert np.abs(ratio - factor) < 0.01, \
        f'Unit conversion {freq}Hz: expected ratio {factor:.2f}, got {ratio:.2f}'
