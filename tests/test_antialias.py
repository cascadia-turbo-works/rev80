"""Unit tests for rev80.picoscope.antialias_decimate — the R32 regression test.

These tests exercise the module-level antialias_decimate(raw_block, factor)
helper directly: pure numpy/scipy, no hardware and no PicoScopeStream
involved. They encode the field incident this function was written to fix —
a high-frequency tone aliasing into the low-frequency band when raw ADC data
is naively downsampled (array[::factor]) instead of filtered-then-decimated.
"""

import numpy as np
import pytest

from rev80.picoscope import antialias_decimate


def _tone(freq, fs, n, ampl=1.0):
    """A pure real cosine tone sampled at fs for n samples."""
    t = np.arange(n) / fs
    return ampl * np.cos(2 * np.pi * freq * t)


def _fft_mag_at(signal, fs, freq):
    """Magnitude of signal's FFT at the bin nearest `freq` (real FFT)."""
    n = len(signal)
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    bin_idx = int(np.argmin(np.abs(freqs - freq)))
    return np.abs(spectrum[bin_idx]), bin_idx


def _expected_decimated_length(n, factor):
    """scipy.signal.decimate slices the (filtered) signal with [::factor] —
    match that exact slicing semantics rather than assuming n // factor."""
    return len(np.arange(n)[::factor])


# ---------------------------------------------------------------------------
# The core R32 regression case
# ---------------------------------------------------------------------------

class TestAntialiasRegression:
    """target_rate=1000, factor=4, raw_rate=4000 → target Nyquist=500 Hz.

    A tone at 1200 Hz is well above the target Nyquist (500 Hz) but well
    within the raw Nyquist (2000 Hz), so it is legitimately represented in
    the raw block. Naive decimation (picking every 4th raw sample, i.e.
    resampling to 1000 Hz with no anti-alias filter first) folds 1200 Hz
    down to 1200 mod 1000 = 200 Hz — landing squarely in the passband where
    a real low-frequency signal would be expected. antialias_decimate must
    suppress this before decimating.
    """

    TARGET_RATE = 1000
    FACTOR = 4
    RAW_RATE = TARGET_RATE * FACTOR  # 4000 Hz
    ALIAS_FREQ = 1200.0              # raw-rate tone frequency
    ALIASED_TO = 200.0               # where naive decimation folds it to
    N_RAW = 8000                     # 2s @ 4000 Hz -> both freqs land on exact bins

    def test_output_length_matches_scipy_decimate_semantics(self):
        raw_block = _tone(self.ALIAS_FREQ, self.RAW_RATE, self.N_RAW)
        out = antialias_decimate(raw_block, self.FACTOR)
        assert len(out) == _expected_decimated_length(self.N_RAW, self.FACTOR)
        assert len(out) == self.N_RAW // self.FACTOR  # exact division in this case

    def test_aliased_energy_is_suppressed_vs_naive_decimation(self):
        raw_block = _tone(self.ALIAS_FREQ, self.RAW_RATE, self.N_RAW)

        naive = raw_block[::self.FACTOR]
        filtered = antialias_decimate(raw_block, self.FACTOR)

        naive_mag, bin_idx = _fft_mag_at(naive, self.TARGET_RATE, self.ALIASED_TO)
        filtered_mag, _ = _fft_mag_at(filtered, self.TARGET_RATE, self.ALIASED_TO)

        # Sanity: naive decimation really does show a strong alias peak.
        assert naive_mag > 0.25 * (len(naive) / 2)

        # The whole point of antialias_decimate: that same bin must be
        # dramatically attenuated once the AA filter runs before decimation.
        assert filtered_mag * 20 < naive_mag, (
            f'aliased bin {bin_idx} ({self.ALIASED_TO} Hz): '
            f'naive={naive_mag:.3f}, filtered={filtered_mag:.3f}'
        )
        # And in absolute terms, negligible compared to a real signal peak.
        assert filtered_mag < 0.05 * (len(filtered) / 2)


# ---------------------------------------------------------------------------
# factor=1 is a no-op
# ---------------------------------------------------------------------------

class TestFactorOneNoOp:

    def test_1d_input_unchanged(self):
        x = np.random.randn(256)
        out = antialias_decimate(x, 1)
        assert out.shape == x.shape
        assert np.array_equal(out, x)

    def test_2d_input_unchanged(self):
        x = np.random.randn(256, 3)
        out = antialias_decimate(x, 1)
        assert out.shape == x.shape
        assert np.array_equal(out, x)

    def test_factor_zero_also_treated_as_noop(self):
        """Implementation guards with `factor <= 1`, so 0 (degenerate/unused
        in practice) is a no-op too rather than raising."""
        x = np.random.randn(64)
        out = antialias_decimate(x, 0)
        assert np.array_equal(out, x)


# ---------------------------------------------------------------------------
# Legitimate low-frequency content survives decimation intact
# ---------------------------------------------------------------------------

class TestLegitimateSignalSurvives:

    TARGET_RATE = 1000
    FACTOR = 4
    RAW_RATE = TARGET_RATE * FACTOR
    LOW_FREQ = 100.0   # well below target Nyquist (500 Hz) and the AA cutoff
    N_RAW = 8000

    def test_frequency_location_preserved(self):
        raw_block = _tone(self.LOW_FREQ, self.RAW_RATE, self.N_RAW, ampl=2.0)
        out = antialias_decimate(raw_block, self.FACTOR)

        spectrum = np.fft.rfft(out)
        freqs = np.fft.rfftfreq(len(out), d=1.0 / self.TARGET_RATE)
        peak_freq = freqs[np.argmax(np.abs(spectrum))]

        assert abs(peak_freq - self.LOW_FREQ) < 1.0

    def test_amplitude_preserved_within_tolerance(self):
        ampl = 2.0
        raw_block = _tone(self.LOW_FREQ, self.RAW_RATE, self.N_RAW, ampl=ampl)
        out = antialias_decimate(raw_block, self.FACTOR)

        expected_mag = ampl * len(out) / 2
        mag, _ = _fft_mag_at(out, self.TARGET_RATE, self.LOW_FREQ)

        # Zero-phase FIR filter passband ripple is small; allow 10% tolerance.
        assert mag == pytest.approx(expected_mag, rel=0.10)


# ---------------------------------------------------------------------------
# Multi-channel (N, channels) handling — independent per-column filtering
# ---------------------------------------------------------------------------

class TestMultiChannel:

    TARGET_RATE = 1000
    FACTOR = 4
    RAW_RATE = TARGET_RATE * FACTOR
    N_RAW = 8000

    ALIAS_FREQ = 1200.0   # channel 0: should be suppressed
    ALIASED_TO = 200.0
    LOW_FREQ = 100.0      # channel 1: should survive

    def test_channels_decimated_independently(self):
        ch0 = _tone(self.ALIAS_FREQ, self.RAW_RATE, self.N_RAW)
        ch1 = _tone(self.LOW_FREQ, self.RAW_RATE, self.N_RAW, ampl=2.0)
        raw_block = np.stack([ch0, ch1], axis=1)  # shape (N, 2)
        assert raw_block.shape == (self.N_RAW, 2)

        out = antialias_decimate(raw_block, self.FACTOR)

        expected_len = _expected_decimated_length(self.N_RAW, self.FACTOR)
        assert out.shape == (expected_len, 2)

        # Channel 0: aliased tone must be suppressed.
        naive_ch0 = ch0[::self.FACTOR]
        naive_mag, _ = _fft_mag_at(naive_ch0, self.TARGET_RATE, self.ALIASED_TO)
        filtered_mag, _ = _fft_mag_at(out[:, 0], self.TARGET_RATE, self.ALIASED_TO)
        assert filtered_mag * 20 < naive_mag

        # Channel 1: legitimate low-frequency tone must survive intact.
        expected_mag = 2.0 * out.shape[0] / 2
        mag, _ = _fft_mag_at(out[:, 1], self.TARGET_RATE, self.LOW_FREQ)
        assert mag == pytest.approx(expected_mag, rel=0.10)
