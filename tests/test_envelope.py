"""Envelope / demodulation analysis (the audit's 'blocks stated purpose' gap).

For rolling-element bearings this is *the* diagnostic. A defect's impulses
excite a structural resonance at 2-20 kHz and are amplitude-modulated at the
defect rate. In the raw spectrum that energy is spread across the resonance and
buried under the 1x and its harmonics; in the envelope of the resonance band it
appears as a clean line at the defect rate with +/-1x sidebands, months earlier.
Every instrument in this class makes it a headline feature (CSI PeakVue,
SKF gE, B&K envelope).

The chain is: band-pass around the resonance -> Hilbert magnitude -> remove the
DC term -> spectrum of the envelope, with its own F_max.

Validated against the physically realistic generator, and -- crucially -- with
a healthy negative control on every positive claim. An envelope analyser that
returns a line for everything is worse than none.
"""

import numpy as np
import pytest

import rev80 as vc
from rev80 import envelope as env
from rev80 import simulation as sim


def cfg(maxfreq=10000.0, binsize=2.0):
    c = vc.AcquisitionSettings()
    c.maxfreq = maxfreq
    c.binsize = binsize
    return c


RATE, MULT, RESON = 60.0, 5.43, 4000.0
BPFO = RATE * MULT
SEEDS = (0, 1, 2, 3)


def faulted(c, seed, severity=1.0, **kw):
    return sim.GenerateBearingVibration(
        c, severity=severity, running_rate=RATE, bearing_multiple=MULT,
        resonance_hz=RESON, seed=seed, **kw)


def peak_near(freq, spec, f0, tol):
    m = np.abs(freq - f0) <= tol
    return float(np.max(spec[m])) if m.any() else 0.0


def floor_of(freq, spec, lo=20.0, hi=1500.0):
    m = (freq > lo) & (freq < hi)
    return float(np.median(spec[m]))


# ===========================================================================
# The envelope itself
# ===========================================================================

def test_envelope_of_an_am_tone_recovers_the_modulator():
    """The textbook case, with an analytic answer.

    A carrier at fc amplitude-modulated at fm must give an envelope spectrum
    with a line at fm -- and NOT at fc, which is the whole point.
    """
    fs, n = 10000.0, 8192
    t = np.arange(n) / fs
    fc, fm, depth = 2000.0, 37.0, 0.5
    x = (1 + depth * np.cos(2 * np.pi * fm * t)) * np.sin(2 * np.pi * fc * t + 0.3)

    freq, spec = env.envelope_spectrum(x, fs, band=(1500.0, 2500.0))
    df = fs / n
    assert peak_near(freq, spec, fm, 3 * df) > 20 * floor_of(freq, spec, 5, 500)
    # The carrier must be gone -- it is demodulated away, not retained.
    assert peak_near(freq, spec, fc, 5 * df) < 3 * floor_of(freq, spec, 5, 500)


def test_envelope_modulation_depth_is_recovered():
    """The envelope line's amplitude must track the modulation depth."""
    fs, n = 10000.0, 8192
    t = np.arange(n) / fs
    fc, fm = 2000.0, 37.0
    amps = []
    for depth in (0.2, 0.4, 0.8):
        x = (1 + depth * np.cos(2 * np.pi * fm * t)) * np.sin(2 * np.pi * fc * t + 0.3)
        freq, spec = env.envelope_spectrum(x, fs, band=(1500.0, 2500.0))
        amps.append(peak_near(freq, spec, fm, 3 * fs / n))
    assert amps[0] < amps[1] < amps[2]
    assert amps[2] / amps[0] == pytest.approx(4.0, rel=0.15)


def test_envelope_dc_is_removed():
    """Without removing the mean, bin 0 dwarfs every real line."""
    fs, n = 10000.0, 8192
    t = np.arange(n) / fs
    x = (1 + 0.5 * np.cos(2 * np.pi * 37.0 * t)) * np.sin(2 * np.pi * 2000.0 * t)
    freq, spec = env.envelope_spectrum(x, fs, band=(1500.0, 2500.0))
    assert spec[0] < peak_near(freq, spec, 37.0, 3 * fs / n)


def test_out_of_band_content_does_not_reach_the_envelope():
    """The band-pass must actually isolate the resonance.

    A strong low-frequency tone outside the demodulation band must not appear
    in the envelope spectrum -- otherwise the 1x would dominate it, which is
    precisely the problem envelope analysis exists to escape.
    """
    fs, n = 10000.0, 8192
    t = np.arange(n) / fs
    x = (np.sin(2 * np.pi * 2000.0 * t + 0.3)
         + 20.0 * np.sin(2 * np.pi * 60.0 * t + 0.7))
    freq, spec = env.envelope_spectrum(x, fs, band=(1500.0, 2500.0))
    assert peak_near(freq, spec, 60.0, 3 * fs / n) < 5 * floor_of(freq, spec, 5, 500)


def test_envelope_spectrum_is_truncated_to_its_own_fmax():
    fs, n = 10000.0, 8192
    x = np.random.default_rng(0).standard_normal(n)
    freq, _ = env.envelope_spectrum(x, fs, band=(1500.0, 2500.0), env_fmax=500.0)
    assert freq[-1] <= 500.0


def test_invalid_band_is_rejected_rather_than_producing_nonsense():
    fs, n = 10000.0, 4096
    x = np.random.default_rng(0).standard_normal(n)
    for band in [(2500.0, 1500.0), (0.0, 1000.0), (1000.0, 6000.0)]:
        with pytest.raises(ValueError):
            env.envelope_spectrum(x, fs, band=band)


# ===========================================================================
# Against the bearing oracle
# ===========================================================================

def test_defect_rate_line_appears_for_a_faulted_bearing():
    c = cfg()
    fs = c.samplerate
    for seed in SEEDS:
        freq, spec = env.envelope_spectrum(
            faulted(c, seed), fs, band=(3000.0, 5000.0))
        df = fs / c.blocksize
        line = peak_near(freq, spec, BPFO, 4 * df)
        assert line > 8 * floor_of(freq, spec), f'seed {seed}: {line:.4g}'


def test_no_defect_line_for_a_healthy_bearing():
    """The negative control. Without it the test above proves nothing."""
    c = cfg()
    fs = c.samplerate
    for seed in SEEDS:
        freq, spec = env.envelope_spectrum(
            faulted(c, seed, severity=0.0), fs, band=(3000.0, 5000.0))
        df = fs / c.blocksize
        line = peak_near(freq, spec, BPFO, 4 * df)
        assert line < 4 * floor_of(freq, spec), f'seed {seed}: {line:.4g}'


def test_defect_line_is_invisible_in_the_raw_spectrum():
    """Justifies the whole feature: if the raw spectrum showed it, this would
    be unnecessary machinery."""
    c = cfg()
    fs = c.samplerate
    x = faulted(c, 0)
    w = np.hanning(len(x))
    raw = np.abs(np.fft.rfft(x * w))
    rf = np.fft.rfftfreq(len(x), 1 / fs)
    df = fs / len(x)
    raw_line = peak_near(rf, raw, BPFO, 4 * df) / float(np.median(raw[(rf > 20) & (rf < 1500)]))

    freq, spec = env.envelope_spectrum(x, fs, band=(3000.0, 5000.0))
    env_line = peak_near(freq, spec, BPFO, 4 * df) / floor_of(freq, spec)

    assert env_line > 3 * raw_line, (
        f'envelope SNR {env_line:.1f} vs raw {raw_line:.1f} -- envelope analysis '
        f'is not buying anything here')


def test_load_zone_sidebands_appear_around_the_defect_line():
    c = cfg()
    fs = c.samplerate
    df = fs / c.blocksize
    freq, spec = env.envelope_spectrum(
        faulted(c, 0, load_zone_depth=0.8), fs, band=(3000.0, 5000.0))
    fl = floor_of(freq, spec)
    assert peak_near(freq, spec, BPFO + RATE, 4 * df) > 3 * fl
    assert peak_near(freq, spec, BPFO - RATE, 4 * df) > 3 * fl


def test_envelope_line_grows_with_severity():
    c = cfg()
    fs = c.samplerate
    df = fs / c.blocksize
    for seed in SEEDS:
        vals = []
        for sev in (0.25, 0.5, 1.0):
            freq, spec = env.envelope_spectrum(
                faulted(c, seed, severity=sev), fs, band=(3000.0, 5000.0))
            vals.append(peak_near(freq, spec, BPFO, 4 * df) / floor_of(freq, spec))
        assert vals[0] < vals[1] < vals[2], f'seed {seed}: {vals}'


# ===========================================================================
# Automatic band selection
# ===========================================================================

def test_auto_band_finds_the_resonance():
    """The user should not have to know where the housing resonance is."""
    c = cfg()
    for seed in SEEDS:
        lo, hi = env.suggest_band(faulted(c, seed), c.samplerate,
                                  fmax=c.band_fmax_resolved)
        assert lo < RESON < hi, f'seed {seed}: suggested ({lo:.0f}, {hi:.0f})'


def test_auto_band_is_usable_without_being_told_the_answer():
    """End to end: suggest a band, then demodulate in it, and still find BPFO."""
    c = cfg()
    fs = c.samplerate
    df = fs / c.blocksize
    for seed in SEEDS:
        x = faulted(c, seed)
        band = env.suggest_band(x, fs, fmax=c.band_fmax_resolved)
        freq, spec = env.envelope_spectrum(x, fs, band=band)
        line = peak_near(freq, spec, BPFO, 4 * df)
        assert line > 6 * floor_of(freq, spec), f'seed {seed}: band {band}'


def test_auto_band_stays_inside_the_measured_band():
    """It must never suggest a band reaching into the anti-alias guard region."""
    c = cfg(maxfreq=5000.0)
    lo, hi = env.suggest_band(faulted(c, 0), c.samplerate,
                              fmax=c.band_fmax_resolved)
    assert 0 < lo < hi <= c.band_fmax_resolved
