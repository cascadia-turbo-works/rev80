"""Linear power averaging of the spectrum over N frames.

Welch runs one segment per frame, so each bin scatters as chi-squared(2);
averaging cuts the scatter as 1/sqrt(N). The average is the N most recent
valid frames up to the frame on display, live and in replay.
"""

from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80.scope_sensor import ScopeSensor

from test_measurement_validity import make_collector, tone
from pipeline_helpers import tick


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


#: Frame period of `averaging_collector`: blocksize / samplerate = 1 / binsize.
#: Averaging uses contiguous frames only, so the feeds step by this period.
FRAME_S = 0.5


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
    """n_averages_effective is clamped to cache_frames, so the stated count is true."""
    c = vc.AcquisitionSettings()
    c.cache_frames = 8
    c.n_averages = 64
    assert c.n_averages_effective == 8


# ===========================================================================
# It actually averages
# ===========================================================================

def test_averaging_reduces_noise_floor_scatter():
    """Averaging 16 frames reduces the floor scatter (about 1/sqrt(N)), not the level."""
    single = averaging_collector(enabled=False)
    avgd = averaging_collector(n=16, enabled=True)

    for i in range(16):
        blk = noisy(single, 300.37, 1.0, seed=i)
        feed(single, blk, rel_time=i * FRAME_S)
        feed(avgd, blk, rel_time=i * FRAME_S)

    r1 = tick(single)[0]
    r16 = tick(avgd)[0]

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
        feed(single, blk, rel_time=i * FRAME_S)
        feed(avgd, blk, rel_time=i * FRAME_S)

    r1 = tick(single)[0]
    r16 = tick(avgd)[0]
    near = np.abs(r1.freq - 300.0) < 6
    assert float(np.max(r16.spectrum[near])) == pytest.approx(
        float(np.max(r1.spectrum[near])), rel=0.15)


def test_averaging_improves_line_to_floor_ratio():
    """The diagnostic benefit, stated as the ratio an analyst actually reads."""
    single = averaging_collector(enabled=False)
    avgd = averaging_collector(n=16, enabled=True)
    for i in range(16):
        blk = noisy(single, 300.0, 0.35, seed=100 + i, noise=1.0)
        feed(single, blk, rel_time=i * FRAME_S)
        feed(avgd, blk, rel_time=i * FRAME_S)

    def snr(r):
        near = np.abs(r.freq - 300.0) < 6
        band = (r.freq > 400) & (r.freq < 900)
        return float(np.max(r.spectrum[near])) / float(np.max(r.spectrum[band]))

    assert snr(tick(avgd)[0]) > 1.5 * snr(tick(single)[0])


def test_disabled_averaging_is_a_true_passthrough():
    dc_off = averaging_collector(enabled=False)
    dc_on = averaging_collector(n=1, enabled=True)
    for i in range(4):
        blk = noisy(dc_off, 300.37, 1.0, seed=i)
        feed(dc_off, blk, rel_time=i * FRAME_S)
        feed(dc_on, blk, rel_time=i * FRAME_S)
    a = tick(dc_off)[0]
    b = tick(dc_on)[0]
    assert np.allclose(a.spectrum, b.spectrum)
    assert a.n_averages == 1 and b.n_averages == 1


# ===========================================================================
# The reported count is the delivered count
# ===========================================================================

def test_reported_count_is_what_was_actually_averaged():
    """Fewer frames than N are available early on. Say so -- do not claim N."""
    dc = averaging_collector(n=16)
    for i in range(5):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    assert tick(dc)[0].n_averages == 5


def test_count_grows_to_the_configured_n_and_stops():
    dc = averaging_collector(n=4)
    seen = []
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
        seen.append(tick(dc)[0].n_averages)
    assert seen == [1, 2, 3, 4, 4, 4, 4, 4]


def test_invalid_frames_are_excluded_and_lower_the_count():
    """Clipped frames are not averaged, and the reported count excludes them.

    A clipped frame reads high, with harmonic distortion."""
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S,
             overflow=(i in (2, 5)))
    r = tick(dc)[0]
    assert r.n_averages == 6


def test_the_displayed_frame_is_included_even_when_invalid():
    """An invalid frame on display is shown with its flag, but is not averaged."""
    dc = averaging_collector(n=8)
    for i in range(4):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    feed(dc, noisy(dc, 300.37, 1.0, seed=99), rel_time=4 * FRAME_S, overflow=True)
    r = tick(dc)[0]
    assert r.overflow is True
    assert r.n_averages == 4      # the four clean predecessors, not the clipped one


# ===========================================================================
# Replay must reproduce live -- the loaded-file contract
# ===========================================================================

def test_browsing_averages_the_frames_preceding_the_cursor():
    """Stepping back through the cache must show what live showed then."""
    dc = averaging_collector(n=4)
    for i in range(10):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)

    live_last = tick(dc)[0].spectrum.copy()

    from types import SimpleNamespace
    dc.sensor = None
    dc.stream = SimpleNamespace(active=False)
    dc._cache_cursor = 0
    assert np.allclose(tick(dc)[0].spectrum, live_last)

    # Three frames back the average must cover frames 4..6, not 7..9.
    dc._cache_cursor = 3
    back = tick(dc)[0]
    assert back.n_averages == 4
    assert not np.allclose(back.spectrum, live_last)


def test_browsing_near_the_start_uses_a_partial_average():
    dc = averaging_collector(n=8)
    for i in range(10):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    from types import SimpleNamespace
    dc.sensor = None
    dc.stream = SimpleNamespace(active=False)
    dc._cache_cursor = 9                      # the oldest frame
    assert tick(dc)[0].n_averages == 1


def test_averaging_survives_the_hdf5_round_trip_and_recomputes(tmp_path):
    """A file saved with averaging off can show an averaged spectrum after load.

    The file holds the raw frames, so averaging is not fixed at capture time.
    """
    dc = averaging_collector(n=1, enabled=False)
    for i in range(8):
        feed(dc, noisy(dc, 300.0, 0.4, seed=i), rel_time=i * FRAME_S)
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
    r = tick(dc2)[0]
    assert r.n_averages == 8


def test_changing_n_after_load_recomputes_without_reloading():
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    wide = tick(dc)[0]
    dc.config.n_averages = 2
    narrow = tick(dc)[0]
    assert wide.n_averages == 8 and narrow.n_averages == 2
    assert not np.allclose(wide.spectrum, narrow.spectrum)


# ===========================================================================
# What must NOT be averaged
# ===========================================================================

def test_overall_is_averaged_with_the_spectrum():
    """The overall is averaged over the same frames as the spectrum."""
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    r = tick(dc)[0]
    singles = []
    for s in list(dc.data['frame_cache'])[-8:]:
        d2 = averaging_collector(enabled=False)
        feed(d2, s[0].data, rel_time=0.0)
        singles.append(tick(d2)[0].overall)
    expected = float(np.sqrt(np.mean(np.square(singles))))
    assert r.overall == pytest.approx(expected, rel=0.02)


def test_impulsiveness_scalars_are_not_averaged():
    """Crest factor and kurtosis are not averaged; they describe the frame on display.

    They exist to catch the frame that is not steady."""
    dc = averaging_collector(n=8)
    rng = np.random.default_rng(0)
    for i in range(7):
        feed(dc, rng.standard_normal(dc.config.blocksize), rel_time=i * FRAME_S)
    spiky = rng.standard_normal(dc.config.blocksize)
    spiky[len(spiky) // 2] = 60.0
    feed(dc, spiky, rel_time=7 * FRAME_S)

    r = tick(dc)[0]
    assert r.n_averages == 8            # the spectrum IS averaged
    assert r.kurtosis > 6.0             # the scalars are not
    assert r.crest_factor > 8.0


# ===========================================================================
# Power domain, not amplitude
# ===========================================================================

def test_the_average_is_taken_in_the_power_domain():
    """The average is sqrt(mean(|X|^2)), not the mean of the magnitudes.

    The difference shows only on the noise floor: a Rayleigh magnitude has mean
    0.886 x sqrt(power), so a magnitude average reads about 11 % low. The test
    asserts against both answers, so the wrong one cannot pass.
    """
    dc = averaging_collector(n=24)

    blocks = []
    for i in range(24):
        rng = np.random.default_rng(500 + i)
        blk = rng.standard_normal(dc.config.blocksize)
        blocks.append(blk)
        feed(dc, blk, rel_time=i * FRAME_S)

    averaged = tick(dc)[0]
    assert averaged.n_averages == 24

    singles = []
    for blk in blocks:
        d = averaging_collector(enabled=False)
        feed(d, blk, rel_time=0.0)
        singles.append(tick(d)[0].spectrum)
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
        feed(dc, blk, rel_time=i * FRAME_S)
    got = tick(dc)[0].overall

    singles = []
    for blk in blocks:
        d = averaging_collector(enabled=False)
        feed(d, blk, rel_time=0.0)
        singles.append(tick(d)[0].overall)

    rms_combined = float(np.sqrt(np.mean(np.square(singles))))
    mean_combined = float(np.mean(singles))
    assert got == pytest.approx(rms_combined, rel=1e-6)
    # Deliberately spread the amplitudes so the two differ measurably.
    assert not np.isclose(got, mean_combined, rtol=0.01)


# ===========================================================================
# Contiguous frames only
# ===========================================================================

def _browse_newest(dc):
    """Results for the newest frame of a stopped collector (browse mode)."""
    dc._cache_cursor = 0
    return tick(dc)[0]


def test_session_captures_are_not_averaged():
    """Captures 600 s apart: an average would span 80 min under one label."""
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 600.0)
    r = _browse_newest(dc)
    assert r.n_averages == 1
    assert r.averaging_gap is True


def test_contiguous_frames_average_to_n():
    dc = averaging_collector(n=8)
    for i in range(8):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * FRAME_S)
    r = _browse_newest(dc)
    assert r.n_averages == 8
    assert r.averaging_gap is False


def test_burst_frames_rebased_to_the_trigger_average_to_n():
    """A burst's rel_times are negative before the trigger; still contiguous."""
    dc = averaging_collector(n=4)
    for i in range(4):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=(i - 2) * FRAME_S)
    assert _browse_newest(dc).n_averages == 4


def test_a_stream_restart_inside_the_window_stops_the_walk():
    dc = averaging_collector(n=8)
    for i in range(5):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=10.0 + i * FRAME_S)
    for i in range(3):                       # new stream: rel_time starts again
        feed(dc, noisy(dc, 300.37, 1.0, seed=50 + i), rel_time=i * FRAME_S)
    r = _browse_newest(dc)
    assert r.n_averages == 3
    assert r.averaging_gap is True


def test_the_gap_limit_is_one_and_a_half_achieved_periods():
    dc = averaging_collector(n=2)
    feed(dc, noisy(dc, 300.37, 1.0, seed=1), rel_time=0.0)
    feed(dc, noisy(dc, 300.37, 1.0, seed=2), rel_time=1.5 * FRAME_S)
    assert _browse_newest(dc).n_averages == 2
    dc = averaging_collector(n=2)
    feed(dc, noisy(dc, 300.37, 1.0, seed=1), rel_time=0.0)
    feed(dc, noisy(dc, 300.37, 1.0, seed=2), rel_time=1.51 * FRAME_S)
    assert _browse_newest(dc).n_averages == 1


def test_count_text_says_why_frames_were_not_averaged():
    pytest.importorskip("dearpygui")
    from rev80.gui_charts import averaging_text
    dc = averaging_collector(n=8)
    for i in range(3):
        feed(dc, noisy(dc, 300.37, 1.0, seed=i), rel_time=i * 600.0)
    r = _browse_newest(dc)
    assert (averaging_text(r.n_averages, 8, r.averaging_gap)
            == "averaging 1 of 8 frames (frames not contiguous)")


def test_count_text_of_a_full_average():
    pytest.importorskip("dearpygui")
    from rev80.gui_charts import averaging_text
    assert averaging_text(8, 8, False) == "averaging 8 frames"
    assert averaging_text(3, 8, False) == "averaging 3 of 8 frames"
