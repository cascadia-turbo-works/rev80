"""Linear power averaging of the spectrum over N frames.

Welch's method IS linear power averaging -- splitting a record into K
overlapping segments and averaging their periodograms is the same estimator as
averaging K per-frame spectra. Since the F-8 fix set `nperseg = blocksize`,
Welch runs exactly ONE segment per frame, so there was no averaging anywhere in
the chain and `welch_overlap` had nothing to act on.

Each bin of a single-segment estimate is chi-squared(2), with a standard
deviation equal to its own mean. Averaging N frames cuts that scatter as
1/sqrt(N), which is what makes a small line distinguishable from floor
roughness -- it does NOT lower the floor's expected level, only the uncertainty
of it.

The rule tying live and replay together:

    the average is the N most recent VALID frames up to and including the frame
    being displayed.

Live that is the last N received; browsing it is frames[cursor-N+1 .. cursor].
One rule, so stepping forward through a loaded file reproduces what the live
display showed at that moment.
"""

from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80.scope_sensor import ScopeSensor

from test_measurement_validity import make_collector, tone


def feed(dc, block, rel_time=0.0, overflow=False, degraded=False):
    dc.receive_data({
        'status': 'OVERFLOW' if overflow else 'OKAY',
        'overflow_mask': 1 if overflow else 0,
        'rel_time': rel_time, 'timestamp': datetime.now(),
        'unit': ['mV'], 'channels': [0], 'data': np.asarray(block)[:, None],
        'samplerate': dc.config.samplerate, 'degraded': degraded,
    })


def noisy(dc, freq, amp, seed, noise=1.0):
    rng = np.random.default_rng(seed)
    return tone(dc, freq, amp=amp) + noise * rng.standard_normal(dc.config.blocksize)


def averaging_collector(n=8, enabled=True, **kw):
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                        maxfreq=1000, binsize=2.0, **kw)
    dc.config.averaging_enabled = enabled
    dc.config.n_averages = n
    return dc


# ===========================================================================
# Configuration
# ===========================================================================

def test_averaging_is_off_by_default():
    """Turning it on must be a deliberate act -- it changes what the number means."""
    c = vc.AcquisitionSettings()
    assert c.averaging_enabled is False
    assert c.n_averages >= 1


def test_averaging_config_round_trips():
    c = vc.AcquisitionSettings()
    c.averaging_enabled = True
    c.n_averages = 12
    back = vc.AcquisitionSettings.from_dict(c.to_dict())
    assert back.averaging_enabled is True
    assert back.n_averages == 12


def test_n_averages_is_clamped_to_the_ring_cache():
    """You cannot average more frames than are retained.

    Silently averaging fewer than asked is the F-8 failure mode; clamping where
    the limit is known keeps the stated value honest.
    """
    c = vc.AcquisitionSettings()
    c.cache_frames = 8
    c.n_averages = 64
    assert c.n_averages_effective == 8


# ===========================================================================
# It actually averages
# ===========================================================================

def test_averaging_reduces_noise_floor_scatter():
    """The point of the feature. Scatter falls ~1/sqrt(N); the level does not."""
    single = averaging_collector(enabled=False)
    avgd = averaging_collector(n=16, enabled=True)

    for i in range(16):
        blk = noisy(single, 300.37, 1.0, seed=i)
        feed(single, blk, rel_time=i * 1.0)
        feed(avgd, blk, rel_time=i * 1.0)

    r1 = single.process_samples()[0]
    r16 = avgd.process_samples()[0]

    band = (r1.freq > 400) & (r1.freq < 900)      # noise only, no tone
    cv1 = float(np.std(r1.spectrum[band]) / np.mean(r1.spectrum[band]))
    cv16 = float(np.std(r16.spectrum[band]) / np.mean(r16.spectrum[band]))
    assert cv16 < 0.55 * cv1, f'CV {cv1:.3f} -> {cv16:.3f}, expected a clear drop'

    # The expected floor LEVEL is unchanged -- averaging removes uncertainty,
    # not energy. This is the claim people most often get wrong.
    assert np.mean(r16.spectrum[band]) == pytest.approx(
        np.mean(r1.spectrum[band]), rel=0.25)


def test_averaging_leaves_a_coherent_line_alone():
    """A real line is deterministic: averaging must not attenuate it."""
    single = averaging_collector(enabled=False)
    avgd = averaging_collector(n=16, enabled=True)
    for i in range(16):
        blk = noisy(single, 300.0, 1.0, seed=i)
        feed(single, blk, rel_time=i * 1.0)
        feed(avgd, blk, rel_time=i * 1.0)

    r1 = single.process_samples()[0]
    r16 = avgd.process_samples()[0]
    near = np.abs(r1.freq - 300.0) < 6
    assert float(np.max(r16.spectrum[near])) == pytest.approx(
        float(np.max(r1.spectrum[near])), rel=0.15)


def test_averaging_improves_line_to_floor_ratio():
    """The diagnostic benefit, stated as the ratio an analyst actually reads."""
    single = averaging_collector(enabled=False)
    avgd = averaging_collector(n=16, enabled=True)
    for i in range(16):
        blk = noisy(single, 300.0, 0.35, seed=100 + i, noise=1.0)
        feed(single, blk, rel_time=i * 1.0)
        feed(avgd, blk, rel_time=i * 1.0)

    def snr(r):
        near = np.abs(r.freq - 300.0) < 6
        band = (r.freq > 400) & (r.freq < 900)
        return float(np.max(r.spectrum[near])) / float(np.max(r.spectrum[band]))

    assert snr(avgd.process_samples()[0]) > 1.5 * snr(single.process_samples()[0])


def test_disabled_averaging_is_a_true_passthrough():
    dc_off = averaging_collector(enabled=False)
    dc_on = averaging_collector(n=1, enabled=True)
    for i in range(4):
        blk = noisy(dc_off, 300.37, 1.0, seed=i)
        feed(dc_off, blk, rel_time=i * 1.0)
        feed(dc_on, blk, rel_time=i * 1.0)
    a = dc_off.process_samples()[0]
    b = dc_on.process_samples()[0]
    assert np.allclose(a.spectrum, b.spectrum)
    assert a.n_averages == 1 and b.n_averages == 1


# ===========================================================================
# The reported count is the delivered count
# ===========================================================================

def test_reported_count_is_what_was_actually_averaged():
    """Fewer frames than N are available early on. Say so -- do not claim N."""
    dc = averaging_collector(n=16)
    for i in range(5):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
    assert dc.process_samples()[0].n_averages == 5


def test_count_grows_to_the_configured_n_and_stops():
    dc = averaging_collector(n=4)
    seen = []
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
        seen.append(dc.process_samples()[0].n_averages)
    assert seen == [1, 2, 3, 4, 4, 4, 4, 4]


def test_invalid_frames_are_excluded_and_lower_the_count():
    """A clipped frame reads high with harmonic distortion; averaging it in
    corrupts the estimate exactly as trending it corrupts the trend (F-5)."""
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0,
             overflow=(i in (2, 5)))
    r = dc.process_samples()[0]
    assert r.n_averages == 6


def test_the_displayed_frame_is_included_even_when_invalid():
    """The current frame is what the user asked to see, flagged. But it must not
    be averaged into an estimate that claims to be clean."""
    dc = averaging_collector(n=8)
    for i in range(4):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
    feed(dc, noisy(dc, 300.37, 1.0, seed=99), rel_time=5.0, overflow=True)
    r = dc.process_samples()[0]
    assert r.overflow is True
    assert r.n_averages == 4      # the four clean predecessors, not the clipped one


# ===========================================================================
# Replay must reproduce live -- the loaded-file contract
# ===========================================================================

def test_browsing_averages_the_frames_preceding_the_cursor():
    """Stepping back through the cache must show what live showed then."""
    dc = averaging_collector(n=4)
    for i in range(10):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)

    live_last = dc.process_samples()[0].spectrum.copy()

    from types import SimpleNamespace
    dc.sensor = None
    dc.stream = SimpleNamespace(active=False)
    dc._cache_cursor = 0
    assert np.allclose(dc.process_samples()[0].spectrum, live_last)

    # Three frames back the average must cover frames 4..6, not 7..9.
    dc._cache_cursor = 3
    back = dc.process_samples()[0]
    assert back.n_averages == 4
    assert not np.allclose(back.spectrum, live_last)


def test_browsing_near_the_start_uses_a_partial_average():
    dc = averaging_collector(n=8)
    for i in range(10):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
    from types import SimpleNamespace
    dc.sensor = None
    dc.stream = SimpleNamespace(active=False)
    dc._cache_cursor = 9                      # the oldest frame
    assert dc.process_samples()[0].n_averages == 1


def test_averaging_survives_the_hdf5_round_trip_and_recomputes(tmp_path):
    """The headline property: nothing is baked in.

    A file captured with averaging off must be able to display an averaged
    spectrum after loading, because the raw frames are all still there.
    """
    dc = averaging_collector(n=1, enabled=False)
    for i in range(8):
        feed(dc, noisy(dc, 300.0, 0.4, seed=i), rel_time=i * 1.0)
    target = tmp_path / 'avg.h5'
    dc.save_data(target)

    dc2 = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                         maxfreq=1000, binsize=2.0)
    dc2.set_scope_sensor(0, ScopeSensor(name='test', engineering_units='mm/s2',
                                        sensitivity=1.0))
    dc2.load_data(target)
    dc2.config.averaging_enabled = True
    dc2.config.n_averages = 8
    dc2._cache_cursor = 0
    r = dc2.process_samples()[0]
    assert r.n_averages == 8


def test_changing_n_after_load_recomputes_without_reloading():
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
    wide = dc.process_samples()[0]
    dc.config.n_averages = 2
    narrow = dc.process_samples()[0]
    assert wide.n_averages == 8 and narrow.n_averages == 2
    assert not np.allclose(wide.spectrum, narrow.spectrum)


# ===========================================================================
# What must NOT be averaged
# ===========================================================================

def test_overall_is_averaged_with_the_spectrum():
    """The overall and the spectrum sit side by side and must describe the same
    data -- describing different amounts of it is the M-06 mistake again."""
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 1.0)
    r = dc.process_samples()[0]
    singles = []
    for s in list(dc.data['frame_cache'])[-8:]:
        d2 = averaging_collector(enabled=False)
        feed(d2, s[0].data, rel_time=0.0)
        singles.append(d2.process_samples()[0].overall)
    expected = float(np.sqrt(np.mean(np.square(singles))))
    assert r.overall == pytest.approx(expected, rel=0.02)


def test_impulsiveness_scalars_are_not_averaged():
    """Averaging is for steady-state estimation; crest factor and kurtosis
    exist to catch the frame that is NOT steady. Diluting one impulsive frame
    across sixteen would defeat the entire purpose of having them."""
    dc = averaging_collector(n=8)
    rng = np.random.default_rng(0)
    for i in range(7):
        feed(dc, rng.standard_normal(dc.config.blocksize), rel_time=i * 1.0)
    spiky = rng.standard_normal(dc.config.blocksize)
    spiky[len(spiky) // 2] = 60.0
    feed(dc, spiky, rel_time=8.0)

    r = dc.process_samples()[0]
    assert r.n_averages == 8            # the spectrum IS averaged
    assert r.kurtosis > 6.0             # the scalars are not
    assert r.crest_factor > 8.0


# ===========================================================================
# Power domain, not amplitude
# ===========================================================================

def test_the_average_is_taken_in_the_power_domain():
    """Average |X|^2 then sqrt -- never the magnitudes directly.

    This distinction is invisible on a coherent line (a deterministic amplitude
    averages to itself either way) and shows up only on the noise floor, which
    is why it is easy to get wrong and stay green. For complex Gaussian noise
    the power is exponential with mean mu, so the magnitude is Rayleigh with
    mean sqrt(pi*mu/4) = 0.886*sqrt(mu): averaging magnitudes converges about
    11% LOW, and drags every noise-floor bin down with it. It also discards the
    chi-squared statistics that make the 1/sqrt(N) variance reduction
    predictable in the first place.

    Asserted against both candidate answers so the wrong one cannot pass.
    """
    dc = averaging_collector(n=24)

    blocks = []
    for i in range(24):
        rng = np.random.default_rng(500 + i)
        blk = rng.standard_normal(dc.config.blocksize)
        blocks.append(blk)
        feed(dc, blk, rel_time=i * 1.0)

    averaged = dc.process_samples()[0]
    assert averaged.n_averages == 24

    singles = []
    for blk in blocks:
        d = averaging_collector(enabled=False)
        feed(d, blk, rel_time=0.0)
        singles.append(d.process_samples()[0].spectrum)
    singles = np.array(singles)

    power_avg = np.sqrt(np.mean(singles ** 2, axis=0))   # correct
    ampl_avg = np.mean(singles, axis=0)                  # the trap

    band = (averaged.freq > 100) & (averaged.freq < 900)
    assert np.allclose(averaged.spectrum[band], power_avg[band], rtol=1e-9)

    # And the two really are distinguishable here, so the assertion above has
    # teeth: the magnitude average sits ~11% low across the floor.
    ratio = float(np.mean(ampl_avg[band]) / np.mean(power_avg[band]))
    assert 0.82 < ratio < 0.95, f'the two averages differ by only {1 - ratio:.1%}'
    assert not np.allclose(averaged.spectrum[band], ampl_avg[band], rtol=0.02)


def test_averaged_overall_is_combined_in_the_power_domain_too():
    """The overall is an RMS, so frames combine as sqrt(mean of squares)."""
    dc = averaging_collector(n=8)
    blocks = []
    for i in range(8):
        rng = np.random.default_rng(700 + i)
        blk = tone(dc, 300.37, amp=0.5 + 0.4 * i) + rng.standard_normal(dc.config.blocksize)
        blocks.append(blk)
        feed(dc, blk, rel_time=i * 1.0)
    got = dc.process_samples()[0].overall

    singles = []
    for blk in blocks:
        d = averaging_collector(enabled=False)
        feed(d, blk, rel_time=0.0)
        singles.append(d.process_samples()[0].overall)

    rms_combined = float(np.sqrt(np.mean(np.square(singles))))
    mean_combined = float(np.mean(singles))
    assert got == pytest.approx(rms_combined, rel=1e-6)
    # Deliberately spread the amplitudes so the two differ measurably.
    assert not np.isclose(got, mean_combined, rtol=0.01)
