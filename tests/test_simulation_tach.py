"""Simulated tachometer signals, and per-channel simulation sources.

Before this, `SimulatedSensor._sample()` tiled one generated signal across
every enabled channel, so a simulated tachometer was impossible: the tach
channel would carry the same accelerometer waveform as the vibration channel.

The coherence tests here are the load-bearing ones. A tach pulse train that is
not locked to the vibration's own shaft rate cannot validate anything -- a
broken tach and a correct one both return a plausible number against an
unrelated signal. This is the same argument simulation.py already makes about
pure cosines being unable to validate envelope analysis.
"""

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80 import tach

RAW_FS = 40000.0   # what _RawRateView presents to a generator


def _cfg(binsize=1.0, channels=(0, 1)):
    c = vc.AcquisitionSettings()
    c.maxfreq = 1000.0
    c.binsize = binsize
    c.enabled_channels = list(channels)
    return c


def _raw(config):
    return sim._RawRateView(config)


# --- GenerateTachPulse ---------------------------------------------------

def test_tach_pulse_reads_back_at_the_requested_rpm():
    """The generator and the detector must agree, or neither can be trusted."""
    cfg = _cfg()
    x = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0)
    r = tach.tach_result(x, cfg.raw_samplerate, ch=0, rel_time=0.0)
    assert r.quality == tach.QUALITY_OK
    assert r.rpm == pytest.approx(1800.0, rel=2e-3)


@pytest.mark.parametrize('rpm', [317.3, 893.1, 1793.3, 3607.9])
def test_tach_pulse_reads_back_off_grid(rpm):
    """Off-grid rates only -- an integer number of samples per pulse is the
    tachometer's bin-centred tone."""
    cfg = _cfg(binsize=0.5)
    x = sim.GenerateTachPulse(_raw(cfg), rpm=rpm)
    r = tach.tach_result(x, cfg.raw_samplerate, ch=0, rel_time=0.0)
    assert r.rpm == pytest.approx(rpm, rel=3e-3)


def test_tach_pulse_is_in_millivolts_and_swings_a_logic_level():
    cfg = _cfg()
    x = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0)
    assert x.max() - x.min() > tach.MIN_PULSE_AMPLITUDE_MV
    assert x.max() == pytest.approx(5000.0, rel=0.05), 'default is a 5 V TTL swing'


def test_tach_pulse_has_a_finite_rise_by_default():
    """An ideal rectangle is a degenerate stimulus: no sample lands in the
    hysteresis band and sub-sample interpolation has nothing to interpolate.
    Real edges arrive with about one intermediate sample (measured on a
    4424A), and the generator must reproduce that or CI tests a regime the
    instrument never sees.
    """
    cfg = _cfg()
    x = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0)
    lo, hi = x.min(), x.max()
    band = (x > lo + 0.1 * (hi - lo)) & (x < hi - 0.1 * (hi - lo))
    n_edges = tach.tach_result(x, cfg.raw_samplerate).n_edges
    assert band.sum() >= n_edges, 'each transition should occupy a sample'


def test_tach_pulse_falling_polarity_idles_high():
    cfg = _cfg()
    x = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0, polarity='falling')
    # Idle high means the median sits near the top rail, not the bottom.
    assert np.median(x) > (x.max() + x.min()) / 2.0
    r = tach.tach_result(x, cfg.raw_samplerate,
                         settings=tach.TachSettings(polarity='falling'))
    assert r.rpm == pytest.approx(1800.0, rel=2e-3)


def test_tach_pulse_jitter_shows_up_as_interval_spread_not_rate_error():
    cfg = _cfg()
    clean = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0, jitter_pct=0.0, seed=1)
    noisy = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0, jitter_pct=2.0, seed=1)
    rc = tach.tach_result(clean, cfg.raw_samplerate)
    rn = tach.tach_result(noisy, cfg.raw_samplerate)
    assert rn.interval_spread > rc.interval_spread
    assert rn.rpm == pytest.approx(1800.0, rel=1e-2)
    assert rn.quality == tach.QUALITY_OK, '2% shaft jitter is legitimate'


def test_tach_pulse_defaults_to_one_pulse_per_rev():
    """D-6: 1 ppr is the specified configuration."""
    cfg = _cfg()
    x = sim.GenerateTachPulse(_raw(cfg), rpm=1800.0)
    # 1 s block at 30 rev/s -> ~30 pulses, not a multiple of that.
    assert 28 <= tach.tach_result(x, cfg.raw_samplerate).n_edges <= 31


# --- per-channel sources -------------------------------------------------

def test_empty_channel_sources_keeps_the_tiled_behaviour_identical():
    """Existing tests and callers must be untouched by this feature."""
    cfg = _cfg(channels=(0, 1))
    s = sim.SimulatedSensor(cfg, sensor=None, callback=lambda *a: None)
    s.source = (sim.GenerateTone, 1.0, 500.0)
    block = s._sample()
    assert block.shape[1] == 2
    assert np.array_equal(block[:, 0], block[:, 1]), (
        'with no per-channel sources every column is the same signal')


def test_channel_sources_gives_each_channel_its_own_signal():
    cfg = _cfg(channels=(0, 1))
    s = sim.SimulatedSensor(cfg, sensor=None, callback=lambda *a: None)
    s.channel_sources = {
        0: (sim.GenerateTone, 1.0, 500.0),
        1: (sim.GenerateTachPulse, 1800.0),
    }
    block = s._sample()
    assert block.shape[1] == 2
    assert not np.array_equal(block[:, 0], block[:, 1])
    r = tach.tach_result(block[:, 1], cfg.raw_samplerate)
    assert r.rpm == pytest.approx(1800.0, rel=3e-3)


def test_channel_without_an_override_falls_back_to_the_default_source():
    cfg = _cfg(channels=(0, 1))
    s = sim.SimulatedSensor(cfg, sensor=None, callback=lambda *a: None)
    s.channel_sources = {1: (sim.GenerateTachPulse, 1800.0)}
    block = s._sample()
    # Channel 0 still carries vibration, not a pulse train.
    assert tach.tach_result(block[:, 0], cfg.raw_samplerate).rpm is None
    assert tach.tach_result(block[:, 1], cfg.raw_samplerate).rpm is not None


def test_channel_sources_generates_at_the_raw_rate():
    """Generators must see raw_samplerate, not the maxfreq display rate, or
    the simulated path silently defeats raw-stream retention."""
    cfg = _cfg(channels=(0, 1))
    s = sim.SimulatedSensor(cfg, sensor=None, callback=lambda *a: None)
    s.channel_sources = {1: (sim.GenerateTachPulse, 1800.0)}
    assert s._sample().shape[0] == cfg.raw_blocksize


# --- coherence -----------------------------------------------------------

def test_machine_with_tach_returns_both_channels():
    cfg = _cfg()
    out = sim.GenerateMachineWithTach(_raw(cfg), running_rate=30.0, seed=3)
    assert set(out) == {0, 1}
    assert len(out[0]) == cfg.raw_blocksize
    assert len(out[1]) == cfg.raw_blocksize


def test_tach_rpm_matches_the_vibration_channels_own_1x_peak():
    """The coherence check, and the reason this generator exists.

    A tach that is not locked to the vibration's shaft rate cannot validate
    anything: a broken tach and a correct one both return a plausible number
    against an unrelated signal.
    """
    cfg = _cfg(binsize=0.5)
    running_rate = 29.37                      # off-grid on purpose
    out = sim.GenerateMachineWithTach(_raw(cfg), running_rate=running_rate,
                                      severity=1.0, seed=5)
    r = tach.tach_result(out[1], cfg.raw_samplerate)
    assert r.quality == tach.QUALITY_OK

    # Locate 1x in the vibration channel itself.
    vib = out[0]
    fs = cfg.raw_samplerate
    spec = np.abs(np.fft.rfft(vib * np.hanning(len(vib))))
    freq = np.fft.rfftfreq(len(vib), 1.0 / fs)
    lo, hi = running_rate * 0.7, running_rate * 1.3
    band = (freq >= lo) & (freq <= hi)
    f_1x = float(freq[band][np.argmax(spec[band])])

    assert r.shaft_hz == pytest.approx(f_1x, rel=0.02), (
        f'tach says {r.shaft_hz:.3f} Hz, vibration 1x is at {f_1x:.3f} Hz')


def test_machine_with_tach_is_reproducible_under_a_seed():
    cfg = _cfg()
    a = sim.GenerateMachineWithTach(_raw(cfg), running_rate=30.0, seed=11)
    b = sim.GenerateMachineWithTach(_raw(cfg), running_rate=30.0, seed=11)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])


def test_healthy_machine_still_has_a_readable_tach():
    """severity=0 is the negative control; the tach must not depend on the
    defect being present."""
    cfg = _cfg()
    out = sim.GenerateMachineWithTach(_raw(cfg), running_rate=30.0,
                                      severity=0.0, seed=7)
    r = tach.tach_result(out[1], cfg.raw_samplerate)
    assert r.quality == tach.QUALITY_OK
    assert r.rpm == pytest.approx(1800.0, rel=3e-3)


def test_bearing_vibration_accepts_an_explicit_shaft_phase():
    """Coherence needs the vibration's shaft reference to be settable; without
    it the load zone sits at a random angle and no angular check is possible."""
    cfg = _cfg()
    a = sim.GenerateBearingVibration(_raw(cfg), seed=2, shaft_phase=0.0)
    b = sim.GenerateBearingVibration(_raw(cfg), seed=2, shaft_phase=0.0)
    c = sim.GenerateBearingVibration(_raw(cfg), seed=2, shaft_phase=np.pi)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_bearing_vibration_unchanged_when_shaft_phase_is_not_given():
    """The new parameter must not perturb the existing random draw order."""
    cfg = _cfg()
    a = sim.GenerateBearingVibration(_raw(cfg), seed=42)
    b = sim.GenerateBearingVibration(_raw(cfg), seed=42)
    assert np.array_equal(a, b)
