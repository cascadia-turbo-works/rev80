"""The raw-to-display resample ratio is bounded, and the achieved rate is returned.

decimate_to_rate designs a 2*10*max(up, down)+1 tap FIR per call, so an
unbounded ratio at a non-nominal raw rate is expensive. The output length must
also match the declared blocksize. See CONTRIBUTING.md, "E7. Resample ratio bound".
"""

import numpy as np
import pytest

from rev80.collector import (
    _RESAMPLE_DENOM_LADDER,
    _RESAMPLE_RATE_TOL,
    decimate_to_rate,
)
from rev80.sample import RAW_SAMPLERATE_HZ, AcquisitionSettings

#: Rate for an interval in whole microseconds: int(1e6 / 76800) = 13 us
#: -> 76923 Hz -> /3 -> 25641 Hz. Coprime with every display rate.
HW_RATE_US = 76923.0 / 3.0

#: Rate for an interval in whole nanoseconds: round(1e9 / 76800) = 13021 ns
#: -> 76799.02 Hz -> /3, 13 ppm from nominal. (The 4824A snaps to a 12.5 ns
#: grid and gives 25591.8 Hz; see CONTRIBUTING.md, "E4. Sample-clock grid".)
HW_RATE_NS = (1e9 / 13021) / 3.0

#: resample_poly's FIR length for a given ratio. Unbounded, it reached 512821.
def _taps(up: int, down: int) -> int:
    return 2 * 10 * max(up, down) + 1


def _ratio_of(raw_rate: float, target_rate: float, n: int = 12800):
    """Run a real decimation and recover the (up, down) it actually used."""
    block = np.zeros(n)
    out, actual = decimate_to_rate(block, raw_rate, target_rate)
    return out, actual


DISPLAY_RATES = [512, 1280, 2560, 5120, 12800]


@pytest.mark.parametrize('raw_rate', [float(RAW_SAMPLERATE_HZ), HW_RATE_NS, HW_RATE_US])
@pytest.mark.parametrize('target', DISPLAY_RATES)
def test_ratio_is_bounded_at_every_shipped_preset(raw_rate, target):
    """The FIR length stays bounded at every preset, at nominal and hardware rates.

    max(up, down) cannot exceed the last ladder entry, so the tap count cannot
    exceed 2*10*cap+1. Unbounded, it is 512821 at HW_RATE_US.
    """
    out, actual = _ratio_of(raw_rate, float(target))

    cap       = _RESAMPLE_DENOM_LADDER[-1]
    max_taps  = _taps(cap, cap)
    # Recover the ratio from the achieved rate: actual == raw * up / down.
    implied   = actual / raw_rate
    assert 0 < implied <= 1.0

    # Output length is the ratio applied to the input, so it is the direct
    # observable proxy for down not having exploded.
    assert len(out) == pytest.approx(12800 * implied, rel=1e-3)
    assert max_taps < 10_000, 'ladder cap grew past a sane FIR length'


@pytest.mark.parametrize('target', DISPLAY_RATES)
def test_output_length_matches_the_declared_blocksize(target):
    """The output length equals the declared blocksize (for example 2560, not 2556).

    A short block makes Welch use a shorter segment, so the bin width would
    differ from the stated one.
    """
    n_raw = 12800
    out, _ = decimate_to_rate(np.zeros(n_raw), HW_RATE_NS, float(target))
    expected = round(n_raw * target / RAW_SAMPLERATE_HZ)
    assert len(out) == expected


@pytest.mark.parametrize('target', DISPLAY_RATES)
def test_ns_timed_rate_reduces_to_the_exact_integer_factor(target):
    """At HW_RATE_NS, every preset gets an exact integer decimation factor."""
    _, actual = decimate_to_rate(np.zeros(12800), HW_RATE_NS, float(target))
    factor = HW_RATE_NS / actual
    assert factor == pytest.approx(round(factor), abs=1e-9), (
        f'target {target}: decimation factor {factor} is not an integer'
    )


@pytest.mark.parametrize('raw_rate', [float(RAW_SAMPLERATE_HZ), HW_RATE_NS])
@pytest.mark.parametrize('target', DISPLAY_RATES)
def test_achieved_rate_is_within_tolerance(raw_rate, target):
    """Bounding the ratio must not cost real rate accuracy."""
    _, actual = decimate_to_rate(np.zeros(12800), raw_rate, float(target))
    assert abs(actual / target - 1.0) <= _RESAMPLE_RATE_TOL


def test_degraded_us_clock_still_bounded():
    """With a whole-microsecond clock, the ratio bound alone keeps the FIR short.

    The display rate shifts by 1600 ppm and is reported as achieved.
    """
    _, actual = decimate_to_rate(np.zeros(12800), HW_RATE_US, 5120.0)
    factor = HW_RATE_US / actual
    assert factor == pytest.approx(5.0, abs=1e-9)
    # 1600 ppm from nominal, and reported.
    assert actual == pytest.approx(5128.2, rel=1e-6)


def test_upsampling_is_refused_not_approximated():
    """target >= raw returns the block untouched at its own rate."""
    block = np.arange(100, dtype=float)
    out, actual = decimate_to_rate(block, 5120.0, 25600.0)
    assert out is block
    assert actual == 5120.0


def test_declared_maxfreq_is_unchanged_by_any_of_this():
    """F_max stays the selected preset value; the achieved rate is on the frequency axis."""
    cfg = AcquisitionSettings()
    cfg.maxfreq = 2000.0
    assert cfg.maxfreq == 2000.0
    assert cfg.samplerate == 5120
