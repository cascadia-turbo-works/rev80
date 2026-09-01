"""The 1x level on a channel result card.

A line at 162.9 Hz means nothing; the same line at 1x means unbalance. This is
the first consumer of shaft speed in the display, and deliberately the
simplest one: no resampling, no interpolation, no new axis type.
"""

import numpy as np
import pytest

import rev80 as vc


def _result(rpm, freq, spectrum):
    n = 8
    return vc.ChannelResult(
        channel=0, unit='in/s', overflow=False, degraded=False,
        time_data=np.zeros(n), time_vec=np.arange(n) / 100.0, samplerate=100.0,
        freq=np.asarray(freq, dtype=float),
        spectrum=np.asarray(spectrum, dtype=float),
        peaks=np.array([], dtype=int), overall=1.0,
        timestamp=None, rel_time=0.0, status='OKAY', rpm=rpm)


def test_no_tach_reading_means_no_1x():
    r = _result(None, [0, 10, 20, 30], [0, 1, 2, 3])
    assert r.one_x_hz is None
    assert r.one_x_amplitude is None


def test_1x_frequency_is_the_shaft_rate():
    r = _result(1800.0, [0, 10, 20, 30], [0, 1, 2, 3])
    assert r.one_x_hz == pytest.approx(30.0)


def test_amplitude_is_the_larger_of_the_two_straddling_bins():
    """1x rarely lands on a bin. Taking the larger of the pair that brackets it
    recovers most of what a strictly-nearest-bin reading would lose to the
    offset, and needs no interpolation.
    """
    freq = [0.0, 10.0, 20.0, 30.0, 40.0]
    spec = [0.0, 1.0, 7.0, 2.0, 0.5]
    r = _result(25.0 * 60.0, freq, spec)       # 25 Hz, between bins 20 and 30
    assert r.one_x_amplitude == 7.0            # max(7.0, 2.0)


def test_amplitude_when_1x_lands_exactly_on_a_bin():
    freq = [0.0, 10.0, 20.0, 30.0]
    spec = [0.0, 1.0, 5.0, 2.0]
    r = _result(20.0 * 60.0, freq, spec)
    assert r.one_x_amplitude == 5.0


def test_1x_above_the_displayed_band_has_no_amplitude():
    """F_max can sit below the shaft rate on a fast machine; reporting the top
    bin would be a wrong number rather than a missing one."""
    r = _result(6000.0, [0, 10, 20, 30], [0, 1, 2, 3])
    assert r.one_x_hz == pytest.approx(100.0)
    assert r.one_x_amplitude is None


def test_1x_below_the_first_bin_has_no_amplitude():
    r = _result(30.0, [10.0, 20.0, 30.0], [1, 2, 3])
    assert r.one_x_amplitude is None


def test_empty_spectrum_is_handled():
    r = _result(1800.0, [], [])
    assert r.one_x_amplitude is None
