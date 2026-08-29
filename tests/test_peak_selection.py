"""Tests for rev80.peaks — local noise floor estimation and significance gating.

Two kinds of test live here.

**Synthetic ground truth.**  The floor and the tone list are constructed, so
the right answer is known exactly.  These carry the load: they pin the floor
estimator's accuracy, its behaviour at the band edges, and the gate's ability
to separate injected lines from the noise they sit in — including on a
deliberately non-flat floor, which is the case the old amplitude ranking got
wrong.

**Real-corpus regression.**  ``DEVDATA/old castle`` is not tracked (see
.gitignore), so those tests skip unless the corpus is present.  Point
``REV80_CORPUS_DIR`` at it to run them::

    REV80_CORPUS_DIR='/path/to/DEVDATA/old castle' pytest tests/test_peak_selection.py

They encode the field case the whole change exists for: on
``blower 4 - bearing DE.h5`` ch2 the 1034 / 1059 / 1088 Hz bearing sideband
family must survive selection, and the top-of-band ripple at 1947 / 1967 /
1982 Hz must not.
"""

import os
from pathlib import Path

import numpy as np
import pytest
import scipy.signal

from rev80 import peaks as pk

# ---------------------------------------------------------------------------
# Synthetic spectrum construction
# ---------------------------------------------------------------------------

NBINS = 2001
SEED = 20260829


def flat_floor(level=10.0, n=NBINS):
    return np.full(n, float(level))


def sloped_floor(low=8.0, high=56.0, n=NBINS):
    """A 7x floor rise concentrated at the top of the band.

    This is the shape measured on the corpus: on blower 4 ch2 the median local
    floor is 9.0 mV overall but 39.4 mV over the top 110 Hz.  It is the shape
    that breaks absolute-amplitude ranking.
    """
    x = np.arange(n) / (n - 1)
    step = 1.0 / (1.0 + np.exp(-(x - 0.93) / 0.02))
    return low + (high - low) * step


def noise(floor, rng):
    """Single-Welch-segment noise: bin power is exponential about floor**2."""
    return np.sqrt(rng.exponential(scale=np.asarray(floor, dtype=float) ** 2))


def add_tone(spec, floor, tone_bin, snr, half_width=1):
    """Add a hann-shaped line of the given SNR (amplitude ratio) over the floor."""
    amp = snr * floor[tone_bin]
    spec[tone_bin] = np.hypot(spec[tone_bin], amp)
    for d in range(1, half_width + 1):
        flank = amp * 0.5 ** d
        spec[tone_bin - d] = np.hypot(spec[tone_bin - d], flank)
        spec[tone_bin + d] = np.hypot(spec[tone_bin + d], flank)
    return spec


# ---------------------------------------------------------------------------
# median-to-mean correction
# ---------------------------------------------------------------------------

class TestMedianToMeanRatio:

    def test_single_segment_correction_is_ln_two(self):
        """One Welch segment -> exponential bin power -> median = ln2 * mean."""
        assert pk.median_to_mean_ratio(1) == pytest.approx(np.log(2.0), rel=1e-12)

    @pytest.mark.parametrize('n_segments', [1, 2, 4, 8, 16, 64])
    def test_correction_matches_a_monte_carlo_of_averaged_exponentials(self, n_segments):
        """The analytic Gamma median must match simulated averaged bin power."""
        rng = np.random.default_rng(SEED)
        draws = rng.exponential(scale=1.0, size=(200_000, n_segments)).mean(axis=1)
        assert pk.median_to_mean_ratio(n_segments) == pytest.approx(
            float(np.median(draws)), rel=0.01
        )

    def test_correction_rises_toward_one_as_segments_are_averaged(self):
        """Averaging segments makes bin power more symmetric, so median -> mean."""
        ratios = [pk.median_to_mean_ratio(n) for n in (1, 2, 4, 8, 16)]
        assert ratios == sorted(ratios)
        assert ratios[0] < 0.70 < ratios[-1] < 1.0

    def test_ignoring_segment_count_would_bias_the_floor_by_up_to_3_dB(self):
        """Why the correction is not hardcoded to ln2: the error is not small."""
        err_db = 10 * np.log10(pk.median_to_mean_ratio(16) / pk.median_to_mean_ratio(1))
        assert err_db > 1.4


# ---------------------------------------------------------------------------
# The floor estimator
# ---------------------------------------------------------------------------

class TestLocalNoiseFloor:

    def test_flat_floor_is_recovered_within_a_decibel(self):
        rng = np.random.default_rng(SEED)
        truth = flat_floor(10.0)
        est = pk.local_noise_floor(noise(truth, rng))
        err_db = 20 * np.log10(est / truth)
        assert abs(np.median(err_db)) < 0.5
        assert np.percentile(np.abs(err_db), 95) < 2.0

    def test_non_flat_floor_is_tracked_rather_than_averaged(self):
        """A 7x rise must be followed locally, not smeared into one global level."""
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        est = pk.local_noise_floor(noise(truth, rng))
        err_db = 20 * np.log10(est / truth)
        # away from the transition itself, the estimate tracks the truth
        quiet = slice(100, 1700)
        loud = slice(1930, NBINS)
        assert abs(np.median(err_db[quiet])) < 0.6
        assert abs(np.median(err_db[loud])) < 1.5
        # and it really is a 7x range, not one averaged number
        assert np.median(est[loud]) / np.median(est[quiet]) > 5.0

    def test_strong_lines_barely_lift_the_floor_estimate(self):
        """The median must stay in the noise even under a dense line family.

        It is not perfectly immune, and the residual is worth stating.  Lines
        every 22 bins (the corpus's median gap between significant peaks) each
        occupy 3 bins of a 65-bin window, so 9 of 65 samples are forced high
        and the median moves up a rank or two.  Measured lift, 20 trials:

            line gap    median      p95
             11 bins   +2.12 dB   +3.39 dB
             22 bins   +0.84 dB   +1.80 dB
             44 bins   +0.35 dB   +1.15 dB
             88 bins   +0.13 dB   +0.75 dB

        The bias is upward, i.e. toward *rejecting* lines, so a dense family
        makes the gate slightly conservative rather than credulous.
        """
        rng = np.random.default_rng(SEED)
        truth = flat_floor(10.0)
        clean = noise(truth, rng)
        spiked = clean.copy()
        for b in range(200, 1800, 22):
            add_tone(spiked, truth, b, snr=30.0)
        shift_db = 20 * np.log10(pk.local_noise_floor(spiked)
                                 / pk.local_noise_floor(clean))
        inner = shift_db[200:1800]
        assert np.median(inner) < 1.5
        assert np.percentile(np.abs(inner), 95) < 2.5

    def test_floor_is_not_pulled_down_at_the_band_edges(self):
        """Regression: scipy.signal.medfilt zero-pads, and that fabricates peaks.

        Within +/-width//2 bins of an edge the implicit zeros displace real
        samples out of the lower half of the median window, so the statistic
        slides from the local median toward the local minimum.  Measured on the
        real corpus this reported a floor of 5.68 where the truth was 39.4,
        making an ordinary ripple bin at 1999 Hz look like a 16 dB line.
        """
        half = pk.FLOOR_MEDIAN_WIDTH_BINS // 2
        edge = np.r_[0:half, NBINS - half:NBINS]
        truth = sloped_floor()
        good_err, bad_err = [], []
        # The edge bins share most of their window, so one realisation is
        # effectively one sample; pool several.
        for seed in range(12):
            spec = noise(truth, np.random.default_rng(SEED + seed))
            good = pk.local_noise_floor(spec)
            bad = np.sqrt(scipy.signal.medfilt(spec ** 2, pk.FLOOR_MEDIAN_WIDTH_BINS)
                          / np.log(2.0))
            good_err.append(np.abs(20 * np.log10(good[edge] / truth[edge])))
            bad_err.append(np.abs(20 * np.log10(bad[edge] / truth[edge])))
        good_err = np.concatenate(good_err)
        bad_err = np.concatenate(bad_err)

        assert np.median(good_err) < 1.0
        assert np.median(good_err) < 0.5 * np.median(bad_err)
        # the zero-padded estimate collapses at the very last bins; ours does not
        assert np.max(bad_err) > 10.0
        assert np.max(good_err) < 6.0

    def test_edge_estimate_is_unbiased_not_merely_finite(self):
        """Over many trials the edge bins must not lean low (or high)."""
        biases = []
        for seed in range(30):
            rng = np.random.default_rng(SEED + seed)
            truth = sloped_floor()
            est = pk.local_noise_floor(noise(truth, rng))
            half = pk.FLOOR_MEDIAN_WIDTH_BINS // 2
            edge = np.r_[0:half, NBINS - half:NBINS]
            biases.append(np.mean(20 * np.log10(est[edge] / truth[edge])))
        assert abs(np.mean(biases)) < 0.5

    def test_floor_is_positive_and_the_same_length_as_the_spectrum(self):
        rng = np.random.default_rng(SEED)
        spec = noise(flat_floor(3.0), rng)
        est = pk.local_noise_floor(spec)
        assert est.shape == spec.shape
        assert np.all(est > 0)

    @pytest.mark.parametrize('n', [0, 1, 2, 3, 7])
    def test_short_spectra_do_not_raise(self, n):
        est = pk.local_noise_floor(np.linspace(1.0, 2.0, n))
        assert est.shape == (n,)

    def test_all_zero_spectrum_gives_a_zero_floor(self):
        assert np.all(pk.local_noise_floor(np.zeros(101)) == 0.0)


# ---------------------------------------------------------------------------
# distance, derived from the window
# ---------------------------------------------------------------------------

class TestPeakDistance:

    @pytest.mark.parametrize('window,expected', [
        ('boxcar', 3),          # first null +/-1 bin
        ('hann', 5),            # +/-2
        ('hamming', 5),         # +/-2
        ('bartlett', 5),        # +/-2
        ('blackmanharris', 9),  # +/-4
        ('flattop', 11),        # +/-5
    ])
    def test_distance_is_twice_the_measured_first_null_plus_one(self, window, expected):
        assert pk.peak_distance_bins(window) == expected

    def test_unknown_window_falls_back_to_the_hann_like_default(self):
        assert pk.peak_distance_bins('no-such-window') == 5

    def test_first_null_table_matches_the_transformed_windows(self):
        """The table is a measurement; re-measure it rather than trusting it."""
        n, over = 4096, 64
        for name, expected in pk.WINDOW_FIRST_NULL_BINS.items():
            w = scipy.signal.get_window(name, n, fftbins=True)
            mag = np.abs(np.fft.rfft(w, n=n * over))
            mag /= mag[0]
            null = next(i for i in range(1, len(mag) - 1)
                        if mag[i] <= mag[i + 1] and mag[i] < mag[i - 1])
            assert null / over == pytest.approx(expected, abs=0.05), name

    def test_boxcar_lines_three_bins_apart_are_both_reported(self):
        """The old hardcoded distance=5 over-merged boxcar, whose null is +/-1 bin."""
        n, fs = 1024, 1024.0
        t = np.arange(n) / fs
        sig = np.sin(2 * np.pi * 200 * t) + np.sin(2 * np.pi * 203 * t)
        freq, psd = scipy.signal.welch(sig, fs=fs, window='boxcar', nperseg=n,
                                       nfft=n, scaling='spectrum', detrend=False)
        amp = np.sqrt(psd)

        old, _ = scipy.signal.find_peaks(amp, distance=5)
        old = old[amp[old] > 0.1 * amp.max()]
        new = np.sort(pk.select_peaks(amp, window='boxcar'))

        assert len(old) == 1, 'distance=5 merges the two boxcar lines'
        assert sorted(freq[new].tolist()) == [200.0, 203.0]


# ---------------------------------------------------------------------------
# Selection on synthetic ground truth
# ---------------------------------------------------------------------------

class TestSelectPeaksGroundTruth:

    def test_every_strong_tone_on_a_flat_floor_is_found_and_nothing_else_is(self):
        rng = np.random.default_rng(SEED)
        truth = flat_floor(10.0)
        spec = noise(truth, rng)
        planted = list(range(150, 1900, 97))
        for b in planted:
            add_tone(spec, truth, b, snr=20.0)

        found = set(pk.select_peaks(spec).tolist())
        assert set(planted) <= found
        # A few false alarms are inherent, and small: on pure noise with no
        # tones at all the default gate reports a mean of 0.73 maxima per 2001
        # bins (60 trials, max 3). See test_false_alarm_rate_on_pure_noise.
        false_positives = found - set(planted)
        assert len(false_positives) <= 5, sorted(false_positives)

    def test_tones_on_the_loud_part_of_a_non_flat_floor_are_still_found(self):
        """The case absolute-amplitude ranking gets wrong, in both directions.

        A quiet tone standing 20 dB out of a quiet floor and a loud tone
        standing 20 dB out of a loud floor are equally real.  A tiny ripple on
        the loud floor is not, even though it is far louder than the quiet tone.
        """
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        spec = noise(truth, rng)
        quiet_tone, loud_tone = 400, 1960
        add_tone(spec, truth, quiet_tone, snr=10.0)
        add_tone(spec, truth, loud_tone, snr=10.0)

        found = pk.select_peaks(spec)
        assert quiet_tone in found
        assert loud_tone in found
        # the loud-floor noise is louder in absolute terms than the quiet tone,
        # yet must not be reported
        loud_noise = np.arange(1935, 1995)
        loud_noise = loud_noise[~np.isin(loud_noise, np.arange(loud_tone - 2, loud_tone + 3))]
        assert spec[loud_noise].max() > spec[quiet_tone] * 0.5
        assert not set(loud_noise.tolist()) & set(found.tolist())

    def test_a_shoulder_on_a_broad_hump_is_rejected(self):
        """What prominence buys over height alone.

        Every sample of a broad hump clears a floor-relative height threshold,
        so height alone happily reports the ripple riding on it.  Prominence
        asks how far the trace must descend before it can climb higher.
        """
        n = 1201
        base = np.full(n, 5.0)
        hump = 60.0 * np.exp(-((np.arange(n) - 600) ** 2) / (2 * 40.0 ** 2))
        spec = base + hump
        spec[640] += 1.2                       # a shoulder, not a line
        add_tone(spec, base, 300, snr=20.0)    # a real line, for contrast

        found = pk.select_peaks(spec).tolist()
        assert 300 in found
        assert 640 not in found
        # The hump's own apex is also rejected, and that is intended rather
        # than incidental: with wlen=41 its prominence is 7.05 against a
        # requirement of 144, because a 40-bin-sigma bump is not a spectral
        # line.  The cost is real and worth stating -- a genuinely broad
        # resonance will not appear in the peak table, only in the plot.
        assert 600 not in found

    def test_a_tiny_line_on_a_very_quiet_floor_is_rejected(self):
        """The absolute -40 dB gate.

        Highpass roll-off residue sits on a near-zero floor, so pure
        floor-relative significance ranks it among the top lines in the
        spectrum.  On blower 4 ch2 that promoted the 1 Hz bin (0.21 mV) and the
        14 Hz bin (2.67 mV) to SNR ranks 9 and 6.
        """
        rng = np.random.default_rng(SEED)
        truth = flat_floor(10.0)
        truth[:60] = 0.02                       # highpass roll-off region
        spec = noise(truth, rng)
        add_tone(spec, truth, 900, snr=100.0)   # the dominant line
        add_tone(spec, truth, 30, snr=40.0)     # tiny, but 32 dB over its floor

        found = pk.select_peaks(spec).tolist()
        assert 900 in found
        assert 30 not in found
        assert spec[30] < spec[900] * 10 ** (pk.ABSOLUTE_FLOOR_DB / 20.0)

    def test_peaks_come_back_ranked_by_descending_amplitude(self):
        """Significance decides admission; amplitude decides the table order."""
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        spec = noise(truth, rng)
        for b, snr in ((300, 12.0), (800, 40.0), (1500, 25.0)):
            add_tone(spec, truth, b, snr=snr)
        found = pk.select_peaks(spec)
        amps = spec[found]
        assert np.all(np.diff(amps) <= 0)

    def test_a_line_far_above_a_noisy_floor_outranks_a_louder_one_barely_above_its_own(self):
        """Admission is by significance even when the loud bin wins on amplitude."""
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        spec = noise(truth, rng)
        add_tone(spec, truth, 500, snr=12.0)     # quiet floor, very significant
        found = set(pk.select_peaks(spec).tolist())
        assert 500 in found
        assert spec[500] < np.max(spec[1900:])   # louder bins exist, unreported
        assert not (found & set(range(1900, NBINS)))


class TestFalseAlarmRate:

    def test_false_alarm_rate_on_pure_noise_is_under_one_per_spectrum(self):
        """With no lines present at all, the gate must stay quiet.

        Measured over 60 realisations of 2001 bins of pure exponential noise:
        mean 0.73 reported maxima per spectrum, median 1, max 3.
        """
        counts = [len(pk.select_peaks(noise(flat_floor(10.0),
                                            np.random.default_rng(1000 + s))))
                  for s in range(30)]
        assert np.mean(counts) < 2.0
        assert max(counts) <= 5

    def test_the_default_threshold_sits_above_the_false_alarm_knee(self):
        """Why 9.5 dB and not 6 dB.

        On pure noise the reported count per 2001 bins is a cliff, not a slope:

            threshold   mean false alarms
              6.0 dB        37.9
              9.5 dB         0.8
             12.0 dB         0.0
             15.5 dB         0.0

        A 6 dB gate would fill a third of the table with noise.
        """
        def rate(db):
            return np.mean([len(pk.select_peaks(noise(flat_floor(10.0),
                                                      np.random.default_rng(1000 + s)),
                                                threshold_db=db))
                            for s in range(20)])
        assert rate(6.0) > 10.0
        assert rate(pk.DEFAULT_THRESHOLD_DB) < 2.0


class TestSelectPeaksThreshold:

    def test_raising_the_threshold_never_adds_peaks(self):
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        spec = noise(truth, rng)
        for b in range(120, 1900, 53):
            add_tone(spec, truth, b, snr=float(rng.uniform(2.0, 60.0)))
        counts = [len(pk.select_peaks(spec, threshold_db=db))
                  for db in (6.0, 9.5, 12.0, 15.5, 20.0)]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] > counts[-1]

    def test_reported_peaks_all_clear_the_requested_significance(self):
        rng = np.random.default_rng(SEED)
        truth = sloped_floor()
        spec = noise(truth, rng)
        for b in range(120, 1900, 53):
            add_tone(spec, truth, b, snr=float(rng.uniform(2.0, 60.0)))
        for db in (6.0, 9.5, 15.5):
            found = pk.select_peaks(spec, threshold_db=db)
            floor = pk.local_noise_floor(spec)
            sig = pk.significance_db(spec, floor)[found]
            absolute = 20 * np.log10(spec[found] / spec.max())
            # each peak clears the floor-relative gate OR the absolute one
            assert np.all((sig >= db - 1e-9) | (absolute >= pk.ABSOLUTE_FLOOR_DB - 1e-9))

    def test_the_count_is_an_output_not_a_setting(self):
        """Two spectra with different line counts must report different counts."""
        rng = np.random.default_rng(SEED)
        truth = flat_floor(10.0)
        sparse = noise(truth, rng)
        for b in range(200, 1800, 400):
            add_tone(sparse, truth, b, snr=20.0)
        dense = noise(truth, rng)
        for b in range(200, 1800, 40):
            add_tone(dense, truth, b, snr=20.0)
        assert len(pk.select_peaks(dense)) > 3 * len(pk.select_peaks(sparse))


class TestSelectPeaksDegenerate:

    @pytest.mark.parametrize('spec', [
        np.zeros(0),
        np.zeros(1),
        np.zeros(2),
        np.zeros(500),
        np.full(500, 3.0),
        np.array([1.0, 2.0, 1.0]),
    ])
    def test_degenerate_spectra_return_an_index_array(self, spec):
        found = pk.select_peaks(spec)
        assert isinstance(found, np.ndarray)
        assert found.dtype.kind == 'i'
        assert np.all(found < len(spec))

    def test_non_finite_maximum_is_refused_rather_than_propagated(self):
        spec = np.full(500, 1.0)
        spec[100] = np.nan
        assert len(pk.select_peaks(spec)) == 0


class TestProminenceWindow:

    def test_prominence_is_measured_locally_not_across_the_whole_band(self):
        """Why wlen is mandatory whenever prominence is used.

        Unbounded, find_peaks walks outward from a candidate until it meets a
        taller sample, and on a 2000-bin spectrum with a monotone background
        that walk can run most of the band before it stops.  The prominence it
        then reports is the drop to an unrelated part of the machine, not to
        the candidate's own base.
        """
        n = 2001
        # A single broad hump spanning the band: 500-bin sigma, no lines at all.
        spec = 1.0 + 40.0 * np.exp(-((np.arange(n) - 1000.0) ** 2) / (2 * 500.0 ** 2))
        _, unbounded = scipy.signal.find_peaks(spec, prominence=0.0)
        _, bounded = scipy.signal.find_peaks(spec, prominence=0.0,
                                             wlen=pk.PROMINENCE_WLEN_BINS)
        # Unbounded, the apex's "prominence" is the drop to the far ends of the
        # band, 34.6 -- it looks like the most prominent feature in the
        # spectrum.  Bounded to +/-20 bins it is 0.032, which is the truth: over
        # a line's width, this hump is flat.
        assert unbounded['prominences'][0] > 100 * bounded['prominences'][0]

    def test_wlen_comfortably_exceeds_the_window_distance(self):
        """A wlen near `distance` truncates real prominence; 4x is the safe floor."""
        for window in pk.WINDOW_FIRST_NULL_BINS:
            distance = pk.peak_distance_bins(window)
            wlen = max(pk.PROMINENCE_WLEN_BINS, 4 * distance + 1)
            assert wlen >= 4 * distance


# ---------------------------------------------------------------------------
# Real-corpus regression — skipped unless DEVDATA/old castle is present
# ---------------------------------------------------------------------------

def _corpus_dir() -> Path | None:
    env = os.environ.get('REV80_CORPUS_DIR')
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[1] / 'DEVDATA' / 'old castle')
    for c in candidates:
        if c.is_dir() and any(c.glob('*.h5')):
            return c
    return None


CORPUS = _corpus_dir()
requires_corpus = pytest.mark.skipif(
    CORPUS is None,
    reason="DEVDATA/old castle is not tracked; set REV80_CORPUS_DIR to run",
)


@pytest.fixture(scope='module')
def blower4_ch2():
    """Newest frame, channel 2 of blower 4 - bearing DE: the bearing-fault case."""
    import rev80
    col = rev80.DataCollector()
    col.load_data(CORPUS / 'blower 4 - bearing DE.h5')
    result = next(r for r in col.process_samples() if r.channel == 2)
    return result


@requires_corpus
class TestOldCastleRegression:

    def test_bearing_sideband_family_survives_selection(self, blower4_ch2):
        """1034 / 1059 / 1088 Hz are the fault signature: +/-25/29 Hz sidebands.

        Under top-N-by-amplitude they ranked 10th, 1st and 4th, so the default
        6-row table broke the family up and dropped 1034 Hz entirely.
        """
        freq, found = blower4_ch2.freq, blower4_ch2.peaks
        reported = {int(round(freq[i])) for i in found}
        assert {1034, 1059, 1088} <= reported

    def test_top_of_band_ripple_is_excluded(self, blower4_ch2):
        """1947 / 1967 / 1982 Hz are ripple on a 39 mV floor, not lines.

        They reached the old top 12 purely because that stretch of the band is
        loud: they stand only 4.0-7.3 dB out of their own neighbourhood.
        """
        freq, found = blower4_ch2.freq, blower4_ch2.peaks
        reported = {int(round(freq[i])) for i in found}
        assert not ({1947, 1967, 1982} & reported)

    def test_leading_peaks_match_the_reviewed_list(self, blower4_ch2):
        """The list a reviewer signed off on, in amplitude order.

        1999 Hz appeared in the original review at position 6.  It is not here,
        and that is deliberate: it was admitted only because the zero-padded
        median filter under-read the floor beneath it (14.9 mV against a true
        88.3 mV).  With the band-edge fix its true significance is 0.73 dB —
        indistinguishable from its own neighbourhood.  See
        test_floor_is_not_pulled_down_at_the_band_edges.
        """
        freq, found = blower4_ch2.freq, blower4_ch2.peaks
        leading = [int(round(freq[i])) for i in found[:9]]
        assert leading == [1059, 1974, 1901, 1088, 1925, 1034, 570, 1782, 294]

    def test_reported_count_is_plottable(self, blower4_ch2):
        assert 20 <= len(blower4_ch2.peaks) <= 70

    def test_every_reported_peak_clears_its_local_floor(self, blower4_ch2):
        spec = blower4_ch2.spectrum
        floor = pk.local_noise_floor(spec)
        sig = pk.significance_db(spec, floor)[blower4_ch2.peaks]
        absolute = 20 * np.log10(spec[blower4_ch2.peaks] / spec.max())
        assert np.all((sig >= pk.DEFAULT_THRESHOLD_DB - 1e-9)
                      | (absolute >= pk.ABSOLUTE_FLOOR_DB - 1e-9))


@requires_corpus
class TestOldCastleCorpusWide:

    @pytest.fixture(scope='class')
    def spectra(self):
        import rev80
        out = []
        for path in sorted(CORPUS.glob('*.h5')):
            col = rev80.DataCollector()
            col.load_data(path)
            for result in col.process_samples():
                out.append(result)
        return out

    def test_every_channel_spectrum_reports_a_drawable_number_of_peaks(self, spectra):
        counts = np.array([len(r.peaks) for r in spectra])
        assert len(counts) == 60
        assert counts.min() >= 5
        assert counts.max() <= 80
        assert 25 <= np.median(counts) <= 55

    def test_selection_beats_amplitude_ranking_on_local_significance(self, spectra):
        """The headline claim, measured: fewer reported peaks sit in their own noise.

        Old rule, top 10 by absolute amplitude: 6.67% of reported peaks stand
        less than 2x above their local floor.  The gate cannot admit any.
        """
        old_bad, new_bad = [], []
        for r in spectra:
            floor = pk.local_noise_floor(r.spectrum)
            legacy, _ = scipy.signal.find_peaks(r.spectrum, distance=5)
            legacy = legacy[np.argsort(-r.spectrum[legacy])][:10]
            old_bad.append(np.mean(r.spectrum[legacy] / floor[legacy] < 2.0))
            if len(r.peaks):
                new_bad.append(np.mean(r.spectrum[r.peaks] / floor[r.peaks] < 2.0))
        assert np.mean(old_bad) > 0.03
        assert np.mean(new_bad) == 0.0
