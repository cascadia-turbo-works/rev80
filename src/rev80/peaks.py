"""Significance-based spectral peak selection.

Why this module exists
----------------------
The peak table used to be built by ranking every local maximum by absolute
amplitude and reporting a fixed top-N::

    peaks, _ = scipy.signal.find_peaks(spectrum_amp, distance=5)
    peaks    = peaks[np.argsort(-spectrum_amp[peaks])]

``find_peaks`` itself was never the problem.  The ranking was.  The local
noise floor is not flat: across the 60 channel-spectra of the ``old castle``
corpus it varies by up to 7x within a single spectrum.  On
``blower 4 - bearing DE.h5`` ch2 the median local floor is 9.0 mV overall but
39.4 mV over 1890-2000 Hz.  Ranking by absolute amplitude therefore ranks by
*how loud the neighbourhood is*, not by *how much a line stands out*: 6 of
that spectrum's top 12 came from the noisy 110 Hz stretch at the top of the
band, several of them ripple rather than lines (1982 Hz sat 2.2x above its
local floor; 1967 Hz 1.6x).

The diagnostic cost was real.  1034 Hz and 1088 Hz are sidebands at +/-25/29 Hz
around the 1059 Hz carrier -- the bearing-fault signature -- and they ranked
10th and 4th, so at the shipped display count of 6 the sideband family was
broken up and pushed off the table.  The instrument was hiding the fault
evidence behind noise ripple.

The fix has three parts, all of them inside the one ``find_peaks`` call:

1. Estimate the *local* noise floor per bin (:func:`local_noise_floor`).
2. Pass array-valued ``height`` and ``prominence`` derived from that floor, so
   the admission test is "does this line stand out from its own
   neighbourhood", evaluated bin by bin.
3. Report everything that passes instead of a fixed count.  The count becomes
   an output; the user knob becomes a significance threshold in dB.

Ranking is still by descending amplitude.  Significance decides *whether* a
line is reported; amplitude decides *where it sits in the table*, because the
question an analyst asks of the table is "how big is it", and a 0.2 mV line
that happens to sit on a very quiet floor is not the top line of the spectrum.

What was tested and rejected
----------------------------
* ``width=`` does not discriminate.  On the ch2 spectrum above, noise-ripple
  maxima (amplitude < 1.5x floor) have median width 1.87 bins and real lines
  (> 5x floor) 2.10 bins, p10 1.84 -- the distributions overlap almost
  entirely.
* ``threshold=`` compares a sample only with its two immediate neighbours,
  which is far too noisy at these SNRs (corpus median peak/floor is 13.2 dB).
* Summing energy across a peak's bins.  Out of scope by explicit decision:
  the reported amplitude is, and stays, the amplitude of the maximum bin.
"""

import functools

import numpy as np
import scipy.ndimage
import scipy.signal
import scipy.stats

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

#: Width, in bins, of the running median that estimates the local noise floor.
#:
#: Tuned against the corpus rather than argued.  Each ``old castle`` file holds
#: 16 frames of the same machine in the same state, so averaging the 16 power
#: spectra cuts the exponential bin-power variance 16-fold; median-filtering
#: that average with a narrow (31-bin) window then gives a far lower-variance
#: reference floor than any single frame can produce.  Scoring the
#: single-frame estimator against that reference over all 20 files x 3 channels
#: x 4 frames:
#:
#:     width   median |error|   p95 |error|
#:        17       1.522 dB       4.694 dB
#:        31       1.097 dB       3.185 dB
#:        45       1.039 dB       3.074 dB
#:        65       1.085 dB       3.354 dB
#:        91       1.181 dB       3.856 dB
#:       129       1.326 dB       4.553 dB
#:       257       1.705 dB       6.572 dB
#:
#: The optimum is a broad, flat basin from 31 to 65 bins; 45 is the minimum and
#: 65 costs 0.05 dB against it, which is far below the 1.0 dB noise of the
#: estimate itself.  Below 31 the window is too short to average down the
#: exponential bin-power scatter; above 91 it smears real floor structure --
#: the floor on this machinery genuinely changes over tens of bins, so a wide
#: median is answering the wrong question.
#:
#: A synthetic spectrum with a deliberately *smooth* floor prefers 129 bins.
#: That disagreement is the point: the synthetic model was too smooth to be a
#: guide, and the real corpus, which has the structure that matters, is what
#: this constant is set from.
FLOOR_MEDIAN_WIDTH_BINS: int = 65

#: Absolute admission floor, in dB relative to the largest bin in the band.
#:
#: Purely floor-relative significance promotes highpass roll-off residue: on
#: ch2 of ``blower 4 - bearing DE.h5`` the 1 Hz bin (0.21 mV) and the 14 Hz bin
#: (2.67 mV) sit on a very quiet floor and reach SNR ranks 9 and 6.  They are
#: not lines anybody wants in a bearing report.  The absolute term is nearly
#: free: median gated peak count is 40 at -40 dB against 41 at -50 dB.
ABSOLUTE_FLOOR_DB: float = -40.0

#: Prominence threshold as a fraction of the height threshold.
#:
#: At the default 9.5 dB threshold this yields height = 2.99x floor and
#: prominence = 1.99x floor -- the (3x, 2x) pair the corpus study settled on --
#: and it keeps that relationship as the user moves the threshold.
PROMINENCE_RATIO: float = 2.0 / 3.0

#: Default significance threshold: amplitude must exceed the local floor by
#: this many dB.  9.5 dB = 2.99x.
DEFAULT_THRESHOLD_DB: float = 9.5

#: Baseline window, in bins, for the prominence search.
#:
#: ``wlen`` is REQUIRED whenever ``prominence`` is used.  Unbounded,
#: ``find_peaks`` walks outward from each candidate to the base of the nearest
#: taller neighbour, which on a 2001-bin spectrum can be most of the band away;
#: the resulting "prominence" then measures the distance to an unrelated part
#: of the machine.  Measured on the ch2 top-12, minimum prominence/amplitude:
#: ``wlen=11`` gives 0.366 (real prominence truncated), while 21, 41, 81, 201
#: and unbounded all give an identical 0.561.  Anything from about 4x
#: ``distance`` upward is safe; 41 bounds the cost.
PROMINENCE_WLEN_BINS: int = 41

#: First spectral null of each Welch window the GUI offers, in bins, measured
#: by transforming each window 64x oversampled and walking out to the first
#: local minimum:
#:
#:     boxcar +/-1 | hann, hamming, bartlett +/-2 | blackmanharris +/-4 | flattop +/-5
#:
#: ``distance`` is set to ``2 * null + 1`` so that the two flanks of one line's
#: main lobe can never be reported as two peaks.  The old hardcoded
#: ``distance=5`` was right for hann by coincidence and actively wrong for
#: boxcar, where it merges genuinely distinct lines 2-4 bins apart.
WINDOW_FIRST_NULL_BINS: dict[str, int] = {
    'boxcar':         1,
    'hann':           2,
    'hamming':        2,
    'bartlett':       2,
    'blackmanharris': 4,
    'flattop':        5,
}

#: Fallback for a window not in the table -- hann-like, and the widest of the
#: common cheap windows, so it errs toward merging rather than splitting.
DEFAULT_FIRST_NULL_BINS: int = 2


# --------------------------------------------------------------------------
# Local noise floor
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=32)
def median_to_mean_ratio(n_segments: int) -> float:
    """median/mean of averaged bin power, for `n_segments` Welch segments.

    A single Welch segment gives complex-Gaussian noise, so bin *power* is
    exponentially distributed and its median is ``ln 2`` times its mean --
    the classic 0.693 correction that turns a median filter into a mean-power
    (i.e. noise-floor) estimator.

    That correction is only exact for one segment.  Averaging `n_segments`
    segments gives ``Gamma(n, 1/n)``, whose median/mean ratio climbs toward 1:

        segments   1      2      4      8     16
        ratio    0.693  0.839  0.913  0.956  0.978

    In this application ``nperseg == blocksize`` (see
    ``AcquisitionSettings.nperseg``), so there is exactly one segment and the
    ratio is ``ln 2`` in every shipped preset.  The general form is kept
    because that invariant is a property of the current settings object, not
    of the maths, and getting it wrong would bias the whole floor by up to
    3.1 dB -- silently, and in the direction that admits noise.
    """
    n = max(1, int(n_segments))
    if n == 1:
        return float(np.log(2.0))
    return float(scipy.stats.gamma.median(n) / n)


def _running_median(values: np.ndarray, width: int) -> np.ndarray:
    """Running median with a *truncated* window at the two band edges.

    ``scipy.signal.medfilt`` zero-pads, and that is not a cosmetic detail.
    Within +/-width//2 bins of an edge the padded zeros progressively displace
    real samples out of the lower half of the window, so the statistic slides
    from the local median toward the local minimum.  Measured on
    ``blower 4 - bearing DE.h5`` ch2, where the true floor over the top of the
    band is 39.4 mV, the zero-padded estimate reads 32.8 at 1995 Hz, 14.9 at
    1999 Hz and 5.68 at 2000 Hz.  The consequence is not a slightly wrong
    number, it is a fabricated detection: 1999 Hz appears to have an SNR of
    6.44 when its true SNR is 2.93, i.e. it is admitted as a strong line when
    it is ordinary ripple.  The bias is one-sided, always downward, and always
    at the band edges -- exactly where the anti-alias transition and the
    highpass roll-off already make the data hardest to read.

    Four repairs were compared on synthetic spectra with a known floor,
    scoring the +/-32 edge bins at width 65 (40 trials):

        edge handling      median |error|   p95 |error|   mean bias
        zero-pad (medfilt)     2.368 dB      11.448 dB     -3.568 dB
        replicate ('nearest')  1.480 dB       5.246 dB     -0.009 dB
        reflect                0.620 dB       1.844 dB     +0.098 dB
        truncated window       0.591 dB       1.829 dB     +0.050 dB

    Plain edge replication removes the bias but not the error: it copies a
    *single* random bin 32 times, and 32 copies of one exponential draw
    dominate a 65-sample median.  Reflection and truncation both reuse 32
    genuinely independent samples and land in the same place.

    Truncation is what this uses: at bin *i* the estimate is simply the median
    of every bin actually within +/-width//2 of it.  It invents no data at all,
    it cannot mirror a strong line back across the edge onto itself, and it
    measured marginally best.  Its only cost is a slightly noisier estimate in
    the last half-window, which is honest -- there really is less evidence
    there.
    """
    n = len(values)
    half = width // 2
    if n == 0:
        return values.astype(float, copy=True)
    if width <= 1 or n <= 1:
        return values.astype(float, copy=True)
    # Interior bins: a full symmetric window. 'nearest' is a placeholder here;
    # every bin it affects is overwritten by the truncated-window block below.
    out = scipy.ndimage.median_filter(values, size=width, mode='nearest')
    edge = min(half, n)
    if edge <= 0:
        return out

    # Edge bins, vectorised. This was a Python loop of `np.median` calls -- one
    # per edge bin, 2*half = 64 of them at the shipped width -- and it was 91%
    # of this function's cost, not the median_filter above. Measured on a
    # 1001-bin spectrum at width 65:
    #
    #     median_filter (interior)      0.047 ms
    #     edge loop, Python             1.161 ms
    #     edge loop, vectorised         0.408 ms
    #     _running_median total         1.274 ms  ->  0.563 ms
    #
    # ~0.8 ms per channel per frame, so 6.6 ms at 8 channels -- one of the
    # smaller findings from the profiling branch, taken because it is free.
    #
    # The statistic is UNCHANGED, and that is the whole constraint: pad with
    # NaN and take a nanmedian, which is exactly the median of the samples
    # genuinely inside the window. Verified bit-identical to the loop it
    # replaces (tests/test_peak_selection.py). The truncation semantics and
    # the measured error table above are untouched -- only the arithmetic's
    # shape changed.
    #
    # 2*half+1, not `width`: the slice being reproduced is [i-half, i+half]
    # INCLUSIVE, which is 2*half+1 samples whatever the parity of width. They
    # coincide for the odd widths local_noise_floor enforces; using width here
    # would still silently shorten every even-width window by one.
    win_len = 2 * half + 1
    idx     = np.concatenate([np.arange(edge), np.arange(max(edge, n - edge), n)])
    padded  = np.full(n + 2 * half, np.nan)
    padded[half:half + n] = values
    windows = np.lib.stride_tricks.sliding_window_view(padded, win_len)
    out[idx] = np.nanmedian(windows[idx], axis=1)
    return out


def local_noise_floor(spectrum_amp: np.ndarray,
                      width: int = FLOOR_MEDIAN_WIDTH_BINS,
                      n_segments: int = 1) -> np.ndarray:
    """Per-bin estimate of the noise floor underlying an amplitude spectrum.

    Returns an array the same length as `spectrum_amp`, in the same units:
    the amplitude an average *noise* bin would have at each frequency.
    Discrete lines sit above it; that ratio is what :func:`select_peaks`
    gates on.

    The estimate is a running median of bin **power** (not amplitude -- the
    median-to-mean correction is a statement about power), converted back to
    amplitude at the end.  A median is used rather than a mean because it is
    the discrete lines themselves that must not contaminate the estimate:
    with the corpus's median 22-bin gap between significant peaks, a 65-bin
    window spans roughly three lines occupying under a fifth of its samples,
    so the median stays firmly in the noise.

    See :data:`FLOOR_MEDIAN_WIDTH_BINS` for how `width` was chosen,
    :func:`_running_median` for the band-edge treatment, and
    :func:`median_to_mean_ratio` for `n_segments`.
    """
    spectrum_amp = np.asarray(spectrum_amp, dtype=float)
    if spectrum_amp.size == 0:
        return spectrum_amp.copy()
    width = int(max(1, min(width, spectrum_amp.size)))
    if width % 2 == 0:
        width -= 1          # median_filter wants an odd, centred window
    width = max(1, width)
    med_power = _running_median(spectrum_amp ** 2, width)
    return np.sqrt(np.maximum(med_power, 0.0) / median_to_mean_ratio(n_segments))


def significance_db(spectrum_amp: np.ndarray, floor: np.ndarray) -> np.ndarray:
    """How far each bin stands above its local noise floor, in dB."""
    spectrum_amp = np.asarray(spectrum_amp, dtype=float)
    floor = np.asarray(floor, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.where(floor > 0, spectrum_amp / np.where(floor > 0, floor, 1.0), np.inf)
    return 20.0 * np.log10(np.maximum(ratio, 1e-30))


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def peak_distance_bins(window: str) -> int:
    """Minimum separation, in bins, between two reported peaks.

    Set from the analysis window's measured first null so that one line's two
    main-lobe flanks can never both be reported.  See
    :data:`WINDOW_FIRST_NULL_BINS`.
    """
    null = WINDOW_FIRST_NULL_BINS.get(str(window).strip().lower(), DEFAULT_FIRST_NULL_BINS)
    return 2 * null + 1


def select_peaks(spectrum_amp: np.ndarray,
                 window: str = 'hann',
                 threshold_db: float = DEFAULT_THRESHOLD_DB,
                 floor: np.ndarray | None = None,
                 n_segments: int = 1,
                 floor_width: int = FLOOR_MEDIAN_WIDTH_BINS) -> np.ndarray:
    """Return the indices of every significant line, ranked by descending amplitude.

    A bin is reported when it is a local maximum that

      * rises `threshold_db` above its own local noise floor, **and**
      * is not more than :data:`ABSOLUTE_FLOOR_DB` below the largest bin in
        the band, **and**
      * has a prominence of at least :data:`PROMINENCE_RATIO` x the height
        threshold, measured within +/-``wlen``/2 bins, **and**
      * is the tallest such bin within :func:`peak_distance_bins`.

    The prominence term is the single most valuable of the four: `height`
    alone still admits shoulders and ripple riding on a broad hump, because
    every sample of that hump clears the same threshold.  Prominence asks how
    far the spectrum must descend before it can climb higher, which is the
    question that separates a line from a bump.

    The count is an *output*, not a setting.  Over the 60 corpus
    channel-spectra the default threshold reports a median of 40 peaks
    (p10 23, p90 50, min 16, max 63).
    """
    spectrum_amp = np.asarray(spectrum_amp, dtype=float)
    if spectrum_amp.size < 3:
        return np.empty(0, dtype=int)
    peak_max = float(np.max(spectrum_amp))
    if not np.isfinite(peak_max) or peak_max <= 0.0:
        return np.empty(0, dtype=int)

    if floor is None:
        floor = local_noise_floor(spectrum_amp, width=floor_width, n_segments=n_segments)
    floor = np.asarray(floor, dtype=float)

    k_height     = 10.0 ** (float(threshold_db) / 20.0)
    absolute_min = peak_max * 10.0 ** (ABSOLUTE_FLOOR_DB / 20.0)
    height       = np.maximum(k_height * floor, absolute_min)
    prominence   = PROMINENCE_RATIO * k_height * floor

    distance = peak_distance_bins(window)
    # wlen must comfortably exceed `distance` or it truncates the prominence
    # search before it can reach a real neighbouring line.
    wlen = max(PROMINENCE_WLEN_BINS, 4 * distance + 1)

    found, _ = scipy.signal.find_peaks(
        spectrum_amp,
        distance=distance,
        height=height,
        prominence=prominence,
        wlen=wlen,
    )
    if found.size == 0:
        return np.empty(0, dtype=int)
    # Rank by amplitude, not by significance: the table answers "how big", and
    # the gate has already answered "is it real".
    return np.asarray(found[np.argsort(-spectrum_amp[found])], dtype=int)
