"""rev80.picoscope._adc_to_mv is bit-identical to picosdk.functions.adc2mV.

The operation order `x * vRange / maxADC` is necessary; `x * (vRange / maxADC)`
rounds differently. See CONTRIBUTING.md, "E3. ADC-to-mV conversion". The tests
skip when the picosdk wrapper is not installed.
"""

import ctypes

import numpy as np
import pytest

from rev80.picoscope import _CHANNEL_INPUT_RANGES_MV, _adc_to_mv

adc2mV = pytest.importorskip('picosdk.functions', reason='picosdk not installed').adc2mV

#: picosdk normalises ADC counts to the signed int16 range regardless of the
#: negotiated resolution, so this is the value _maxADC always holds.
MAX_ADC = 32767

ALL_RANGES = range(len(_CHANNEL_INPUT_RANGES_MV))


def _reference(counts: np.ndarray, rng_idx: int) -> np.ndarray:
    """The vendor conversion, through its real ctypes-buffer interface."""
    buf = (ctypes.c_int16 * len(counts))(*counts.tolist())
    return np.array(adc2mV(buf, rng_idx, ctypes.c_int16(MAX_ADC)), dtype=np.float64)


@pytest.mark.parametrize('rng_idx', ALL_RANGES)
def test_bit_identical_on_random_counts(rng_idx):
    """Every voltage range, 4096 random counts, exact equality."""
    rng    = np.random.default_rng(1234 + rng_idx)
    counts = rng.integers(-32768, 32768, 4096, dtype=np.int16)

    got = _adc_to_mv(counts, rng_idx, MAX_ADC)
    ref = _reference(counts, rng_idx)

    assert np.array_equal(got, ref), (
        f'range {rng_idx} ({_CHANNEL_INPUT_RANGES_MV[rng_idx]} mV): '
        f'max abs diff {np.max(np.abs(got - ref)):.3e}'
    )


@pytest.mark.parametrize('rng_idx', ALL_RANGES)
def test_bit_identical_at_the_extremes(rng_idx):
    """The int16 rails and zero, where a rounding difference would show first.

    -32768 is included deliberately: it has no positive counterpart, so a
    conversion that mishandled the asymmetry would only fail here.
    """
    counts = np.array([-32768, -32767, -1, 0, 1, 32766, 32767], dtype=np.int16)

    got = _adc_to_mv(counts, rng_idx, MAX_ADC)
    ref = _reference(counts, rng_idx)

    assert np.array_equal(got, ref)


def test_full_int16_domain_on_the_shipped_range():
    """Every representable int16 count on the +/-2 V range (index 7)."""
    rng_idx = 7   # +/-2000 mV
    counts  = np.arange(-32768, 32768, dtype=np.int16)

    got = _adc_to_mv(counts, rng_idx, MAX_ADC)
    ref = _reference(counts, rng_idx)

    assert np.array_equal(got, ref)


def test_premultiplied_scale_factor_is_not_equivalent():
    """A pre-divided scale factor, x * (vRange / maxADC), gives different results."""
    rng_idx = 7
    rng     = np.random.default_rng(0)
    counts  = rng.integers(-32768, 32768, 8192, dtype=np.int16)
    v_range = _CHANNEL_INPUT_RANGES_MV[rng_idx]

    correct     = _adc_to_mv(counts, rng_idx, MAX_ADC)
    premultiply = counts.astype(np.float64) * (v_range / MAX_ADC)

    assert np.array_equal(correct, _reference(counts, rng_idx))
    assert not np.array_equal(premultiply, correct)


def test_returns_float64_not_a_list():
    """Downstream writes this straight into a float64 accumulator column."""
    out = _adc_to_mv(np.zeros(8, dtype=np.int16), 7, MAX_ADC)
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float64
