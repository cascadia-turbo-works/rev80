"""The simulated bearing signal must be able to falsify a bearing diagnostic (M-14).

The old generator was ten pure cosines plus Gaussian white noise. Its kurtosis
is ~3 -- i.e. Gaussian -- it has no impulsiveness, no resonance carrier, no
load-zone modulation and no slip. A real rolling-element defect is an impulse
train exciting a structural resonance, amplitude-modulated at the shaft rate by
the load zone, with 1-2% slip jitter.

That difference is not cosmetic. Every diagnostic this project is adding next --
crest factor, kurtosis, envelope demodulation -- keys on exactly the properties
the old signal lacks, so it could not validate any of them even in principle:
a completely broken envelope analyser and a correct one both return "nothing
here" on ten pure cosines.

These tests pin the properties that make the generator a usable oracle, and the
negative control that makes it a falsifiable one.
"""

import numpy as np
import pytest
import scipy.signal
import scipy.stats

import rev80 as vc
from rev80 import simulation as sim


def settings(maxfreq=10000.0, binsize=2.0):
    c = vc.AcquisitionSettings()
    c.maxfreq = maxfreq
    c.binsize = binsize
    return c


def crest(x: np.ndarray) -> float:
    return float(np.max(np.abs(x)) / np.sqrt(np.mean(x ** 2)))


def envelope_spectrum(x, fs, band):
    """Band-pass, Hilbert magnitude, DC removed, magnitude spectrum."""
    sos = scipy.signal.butter(4, band, btype='bandpass', fs=fs, output='sos')
    env = np.abs(scipy.signal.hilbert(scipy.signal.sosfiltfilt(sos, x)))
    env = env - env.mean()
    w = scipy.signal.windows.hann(len(env), sym=False)
    spec = np.abs(np.fft.rfft(env * w)) / (len(env) * np.mean(w)) * 2
    return np.fft.rfftfreq(len(env), 1 / fs), spec


def peak_near(freq, spec, f0, tol_hz):
    m = np.abs(freq - f0) <= tol_hz
    return float(np.max(spec[m])) if m.any() else 0.0


# ===========================================================================
# The precedence bug
# ===========================================================================

def test_spectral_generator_harmonic_count_is_sane():
    """`freqs[-1] // bearing_multiple*running_rate` binds left to right.

    That is (freqs[-1] // multiple) * rate, not freqs[-1] // (multiple * rate) --
    thousands of iterations instead of a handful, every out-of-range harmonic
    collapsing onto the last bin via argmin. Compare the correct form used on
    the running-speed loop immediately above it.
    """
    cfg = settings()
    n = sim.bearing_harmonic_count(cfg, running_rate=60.0, bearing_multiple=9.23)
    nyquist = cfg.samplerate / 2
    assert 0 < n <= nyquist / (60.0 * 9.23) + 1
    assert n < 100


def test_spectral_generator_does_not_pile_energy_on_the_last_bin():
    """The precedence bug wrote every out-of-range harmonic onto freqs[-1]."""
    cfg = settings()
    sig = sim.GenerateBearingVibration_SpectralMethod(cfg)
    spec = np.abs(np.fft.rfft(sig))
    assert spec[-1] <= 5 * np.median(spec), (
        'last bin dominates -- out-of-range harmonics are collapsing onto it'
    )


# ===========================================================================
# The healthy negative control
# ===========================================================================

SEEDS = (0, 1, 2, 3, 4, 5, 6, 7)


def test_healthy_machine_is_not_impulsive():
    """Severity 0 must not look impulsive.

    Not "kurtosis ~3": a machine whose vibration is dominated by running-speed
    harmonics is genuinely sub-Gaussian, and this signal measures 1.54-3.04
    over 40 seeds (mean 2.18). Gaussian is the ceiling here, not the target.
    What matters for a negative control is that it stays clear of the
    impulsive range -- without a credible healthy case, "the detector fired"
    proves nothing.
    """
    for seed in SEEDS:
        x = sim.GenerateBearingVibration(cfg_default(), severity=0.0, seed=seed)
        k = scipy.stats.kurtosis(x, fisher=False)
        assert k < 3.5, f'seed {seed}: healthy kurtosis {k:.3f}'
        assert crest(x) < 3.2, f'seed {seed}: healthy crest {crest(x):.3f}'


def cfg_default():
    return settings()


def test_healthy_machine_still_shows_its_running_speed():
    """Healthy is not silent -- the 1x and its harmonics remain."""
    cfg = settings()
    x = sim.GenerateBearingVibration(cfg, severity=0.0, running_rate=60.0)
    f = np.fft.rfftfreq(len(x), 1 / cfg.samplerate)
    spec = np.abs(np.fft.rfft(x))
    df = cfg.samplerate / len(x)
    assert peak_near(f, spec, 60.0, 3 * df) > 10 * np.median(spec)


# ===========================================================================
# The faulted signal has the properties a bearing diagnostic keys on
# ===========================================================================

def test_defect_is_impulsive():
    """The property the old generator could not produce at any severity.

    Measured 3.86-6.12 over 40 seeds against a healthy 1.54-3.04, so the two
    populations are separated with room to spare. Asserted per seed rather
    than on one draw, so a lucky waveform cannot carry the test.
    """
    for seed in SEEDS:
        x = sim.GenerateBearingVibration(cfg_default(), severity=1.0, seed=seed)
        k = scipy.stats.kurtosis(x, fisher=False)
        assert k > 3.8, f'seed {seed}: faulted kurtosis {k:.3f}'


def test_defect_is_more_impulsive_than_health_on_the_same_waveform():
    """Paired comparison: same seed, severity the only difference.

    Removes the seed-to-seed variance entirely, which is what makes this the
    assertion a diagnostic can actually be built on.
    """
    for seed in SEEDS:
        cfg = cfg_default()
        kh = scipy.stats.kurtosis(
            sim.GenerateBearingVibration(cfg, severity=0.0, seed=seed), fisher=False)
        kf = scipy.stats.kurtosis(
            sim.GenerateBearingVibration(cfg, severity=1.0, seed=seed), fisher=False)
        assert kf > kh + 1.0, f'seed {seed}: healthy {kh:.3f} vs faulted {kf:.3f}'


def test_impulsiveness_rises_with_severity():
    """Monotone enough to drive a threshold test, not just non-zero."""
    for seed in SEEDS:
        cfg = cfg_default()
        ks = [scipy.stats.kurtosis(
                  sim.GenerateBearingVibration(cfg, severity=s, seed=seed),
                  fisher=False)
              for s in (0.0, 0.5, 1.0)]
        assert ks[0] < ks[1] < ks[2], f'seed {seed}: {ks}'


def test_crest_factor_rises_with_severity():
    """Crest factor is the other cheap impulsiveness scalar, so pin it too."""
    for seed in SEEDS:
        cfg = cfg_default()
        cs = [crest(sim.GenerateBearingVibration(cfg, severity=s, seed=seed))
              for s in (0.0, 0.5, 1.0)]
        assert cs[0] < cs[1] < cs[2], f'seed {seed}: {cs}'


def test_defect_energy_sits_on_a_structural_resonance():
    """The defect must excite a high-frequency carrier, not appear as bare lines.

    This is what makes envelope analysis necessary in the first place: the
    impulses are buried under the 1x in the raw spectrum but ring a resonance
    far above it.
    """
    cfg = settings()
    fs = cfg.samplerate
    healthy = sim.GenerateBearingVibration(cfg, severity=0.0, resonance_hz=4000.0)
    faulted = sim.GenerateBearingVibration(cfg, severity=1.0, resonance_hz=4000.0)

    def band_energy(x, lo, hi):
        f = np.fft.rfftfreq(len(x), 1 / fs)
        s = np.abs(np.fft.rfft(x)) ** 2
        return float(np.sum(s[(f >= lo) & (f <= hi)]))

    assert band_energy(faulted, 3000, 5000) > 10 * band_energy(healthy, 3000, 5000)


def test_defect_appears_in_the_envelope_spectrum_at_the_defect_rate():
    """The headline property: a clean BPFO line in the envelope of the resonance."""
    cfg = settings()
    fs = cfg.samplerate
    bpfo = 60.0 * 5.43
    x = sim.GenerateBearingVibration(cfg, severity=1.0, running_rate=60.0,
                                     bearing_multiple=5.43, resonance_hz=4000.0)
    f, spec = envelope_spectrum(x, fs, (3000.0, 5000.0))
    df = fs / len(x)
    line = peak_near(f, spec, bpfo, 4 * df)
    floor = float(np.median(spec[(f > 20) & (f < 1500)]))
    assert line > 8 * floor, f'BPFO line {line:.4g} vs floor {floor:.4g}'


def test_healthy_envelope_has_no_defect_line():
    """The negative control for the test above -- otherwise it proves nothing."""
    cfg = settings()
    fs = cfg.samplerate
    bpfo = 60.0 * 5.43
    x = sim.GenerateBearingVibration(cfg, severity=0.0, running_rate=60.0,
                                     bearing_multiple=5.43, resonance_hz=4000.0)
    f, spec = envelope_spectrum(x, fs, (3000.0, 5000.0))
    df = fs / len(x)
    line = peak_near(f, spec, bpfo, 4 * df)
    floor = float(np.median(spec[(f > 20) & (f < 1500)]))
    assert line < 4 * floor, f'healthy signal shows a BPFO line: {line:.4g}'


def test_load_zone_modulation_puts_sidebands_around_the_defect_rate():
    """Sidebands at +/-1x around the defect line are the load-zone signature."""
    cfg = settings()
    fs = cfg.samplerate
    rate, mult = 60.0, 5.43
    x = sim.GenerateBearingVibration(cfg, severity=1.0, running_rate=rate,
                                     bearing_multiple=mult, resonance_hz=4000.0,
                                     load_zone_depth=0.8)
    f, spec = envelope_spectrum(x, fs, (3000.0, 5000.0))
    df = fs / len(x)
    floor = float(np.median(spec[(f > 20) & (f < 1500)]))
    upper = peak_near(f, spec, rate * mult + rate, 4 * df)
    lower = peak_near(f, spec, rate * mult - rate, 4 * df)
    assert upper > 3 * floor and lower > 3 * floor, (upper, lower, floor)


def test_slip_jitter_broadens_the_defect_line():
    """1-2% slip is why a real BPFO line is never perfectly sharp.

    With no slip the line is confined to its own bins; with slip it spreads.
    Asserted as a comparison rather than an absolute width, since the absolute
    value depends on block length.
    """
    cfg = settings()
    fs = cfg.samplerate
    rate, mult = 60.0, 5.43
    kw = dict(severity=1.0, running_rate=rate, bearing_multiple=mult,
              resonance_hz=4000.0, load_zone_depth=0.0)

    def sharpness(slip):
        x = sim.GenerateBearingVibration(cfg, slip=slip, **kw)
        f, spec = envelope_spectrum(x, fs, (3000.0, 5000.0))
        df = fs / len(x)
        core = peak_near(f, spec, rate * mult, 2 * df)
        near = peak_near(f, spec, rate * mult + 8 * df, 4 * df)
        return core / max(near, 1e-12)

    assert sharpness(0.0) > sharpness(0.02)


def test_generator_is_reproducible_under_a_seed():
    """Needed so a failing diagnostic test can be re-run on the same waveform."""
    cfg = settings()
    a = sim.GenerateBearingVibration(cfg, severity=1.0, seed=7)
    b = sim.GenerateBearingVibration(cfg, severity=1.0, seed=7)
    c = sim.GenerateBearingVibration(cfg, severity=1.0, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generator_returns_one_block_of_the_configured_length():
    cfg = settings()
    assert len(sim.GenerateBearingVibration(cfg, severity=1.0)) == cfg.blocksize


# ===========================================================================
# S-12 -- SimulatedSensor died silently above two channels
# ===========================================================================

@pytest.mark.parametrize('n_ch', [1, 2, 3, 4])
def test_simulated_sensor_handles_any_channel_count(n_ch):
    """`simulated()` set a 2-element scale while the generator emits one column
    per enabled channel, so 3+ channels raised a broadcast ValueError inside
    _stream -- which had no try/except, so the thread died while _running stayed
    set and is_streaming reported a healthy stream producing nothing, forever.
    """
    cfg = settings(maxfreq=1000.0, binsize=10.0)
    cfg.enabled_channels = list(range(n_ch))
    sensor = vc.VibeSensor.simulated()

    seen = []
    stream = sim.SimulatedSensor(cfg, sensor, lambda *a: seen.append(a))
    stream._sample()                      # must not raise

    got = []
    sensor.callback = lambda samp: got.append(samp)
    sensor._callback(stream._sample(), cfg.blocksize, 0.0, 'OKAY')
    assert got, 'no sample reached the app callback'
    assert got[0]['data'].shape[1] == n_ch


def test_simulated_stream_does_not_report_healthy_after_the_thread_dies():
    """A generator that raises must stop the stream, not leave it lying.

    `is_streaming` reporting True on a dead thread is worse than a crash: the
    UI shows a live acquisition that will never produce another frame.
    """
    cfg = settings(maxfreq=1000.0, binsize=10.0)
    sensor = vc.VibeSensor.simulated()

    def boom(*_a, **_k):
        raise ValueError('generator exploded')

    stream = sim.SimulatedSensor(cfg, sensor, lambda *a: None)
    stream.source = (boom,)
    stream.start()
    for _ in range(200):
        if not stream.active:
            break
        import time as _t
        _t.sleep(0.01)
    assert not stream.active, 'stream still reports active after its thread died'
