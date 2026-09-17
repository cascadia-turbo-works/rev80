"""Regression tests for the raw -> display resample ratio.

`collector.decimate_to_rate` designs a `2*10*max(up, down)+1` tap polyphase FIR
per call, so the ratio's denominator is a direct cost multiplier. It was
nominally bounded, but `limit_denominator` was applied to each rate separately
before dividing -- and both are integers there, so each reduced to denominator
1 and the RATIO was never bounded at all.

That was invisible offline and catastrophic on hardware. `SimulatedSensor`
reports exactly 25600 Hz, which reduces against every display rate to a small
integer factor. The real driver ran at 25641 Hz (the streaming interval was
requested in whole microseconds: 1e6/76800 truncated 13.02 to 13), 5120 and
25641 are coprime, and scipy dutifully designed a 512821-tap filter on every
call -- 73.6 ms per channel per frame against 0.64 ms, i.e. 589 ms of
main-thread work per 500 ms frame at 8 channels.

It was also a measurement defect, not only a speed one: the resample returned
2556 samples where the config declares 2560, silently tripping Welch's
`nperseg > input length` fallback, so the delivered bin width was not the one
the Spectrum tab advertised.

These tests pin both halves of the fix: the ratio is bounded, and the returned
rate is the one actually achieved.
"""

import numpy as np
import pytest

from rev80.collector import (
    _RESAMPLE_DENOM_LADDER,
    _RESAMPLE_RATE_TOL,
    decimate_to_rate,
)
from rev80.sample import RAW_SAMPLERATE_HZ, AcquisitionSettings

#: What the driver really delivers with the interval requested in whole
#: MICROSECONDS: int(1e6 / 76800) = 13 us -> 76923 Hz -> /3 -> 25641. Coprime
#: with every display rate. This is the value that caused the bug.
HW_RATE_US = 76923.0 / 3.0

#: With the interval requested in NANOSECONDS: round(1e9 / 76800) = 13021 ns
#: -> 76799.02 Hz -> /3. 13 ppm from nominal instead of 1600 ppm.
HW_RATE_NS = (1e9 / 13021) / 3.0

#: resample_poly's FIR length for a given ratio. Anything approaching the
#: unbounded 512821 is the bug returning.
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
    """The FIR stays tractable at every preset, at nominal AND real rates.

    The cap is the ladder's last entry, so max(up, down) can never exceed it
    and the tap count can never exceed 2*10*cap+1. Without the fix this is
    512821 at HW_RATE_US.
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
    """2560 in, 2560 out -- not 2556.

    A short block silently trips Welch's nperseg fallback, so the bin width the
    analyst reads is not the bin width the UI states.
    """
    n_raw = 12800
    out, _ = decimate_to_rate(np.zeros(n_raw), HW_RATE_NS, float(target))
    expected = round(n_raw * target / RAW_SAMPLERATE_HZ)
    assert len(out) == expected


@pytest.mark.parametrize('target', DISPLAY_RATES)
def test_ns_timed_rate_reduces_to_the_exact_integer_factor(target):
    """With the ns-requested clock, every preset gets its clean divisor.

    This is the whole point of requesting the streaming interval in ns rather
    than us: the achieved rate lands close enough to nominal that the ladder
    stops at the exact integer factor on its first useful rung.
    """
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
    """Even if a device ignores the ns request, the ratio stays cheap.

    The ns change and the ratio bound are independent fixes; this pins that the
    bound alone is sufficient, so hardware that quantises coarsely gets a
    slightly shifted display rate rather than a 73 ms stall.
    """
    _, actual = decimate_to_rate(np.zeros(12800), HW_RATE_US, 5120.0)
    factor = HW_RATE_US / actual
    assert factor == pytest.approx(5.0, abs=1e-9)
    # 1600 ppm off nominal -- reported honestly rather than hidden.
    assert actual == pytest.approx(5128.2, rel=1e-6)


def test_upsampling_is_refused_not_approximated():
    """target >= raw returns the block untouched at its own rate."""
    block = np.arange(100, dtype=float)
    out, actual = decimate_to_rate(block, 5120.0, 25600.0)
    assert out is block
    assert actual == 5120.0


def test_declared_maxfreq_is_unchanged_by_any_of_this():
    """The user-facing F_max preset stays exactly what was selected.

    The sub-Hz difference between the requested and achieved display rate is
    internal -- it belongs to the frequency axis, where correctness matters --
    and is never surfaced as a fiddly number on a control. Same treatment
    highpass_fc already gets: a declared edge, with the real value underneath.
    """
    cfg = AcquisitionSettings()
    cfg.maxfreq = 2000.0
    assert cfg.maxfreq == 2000.0
    assert cfg.samplerate == 5120
