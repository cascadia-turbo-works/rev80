"""Significance-based spectral peak selection.

A bin is reported when it stands a set number of dB above its own local noise
floor. The number of peaks is an output, not a setting. Significance decides
whether a line is reported; amplitude decides its rank in the table. The
reported amplitude is the amplitude of the maximum bin, with no energy summed
across bins. Evidence: CONTRIBUTING.md, "E12. Peak selection".
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
#: Set from a recorded-machine corpus (optimum 31 to 65 bins), not from a
#: synthetic floor, which prefers 129 bins. Evidence: CONTRIBUTING.md,
#: "E12.2. Floor width".
FLOOR_MEDIAN_WIDTH_BINS: int = 65

#: Absolute admission floor, in dB relative to the largest bin in the band.
#: It stops high-pass roll-off residue on a quiet floor from passing as a line.
#: Evidence: CONTRIBUTING.md, "E12.1. Method".
ABSOLUTE_FLOOR_DB: float = -40.0

#: Prominence threshold as a fraction of the height threshold. At 9.5 dB this
#: gives height 2.99x floor and prominence 1.99x floor.
PROMINENCE_RATIO: float = 2.0 / 3.0

#: Default significance threshold: amplitude must exceed the local floor by
#: this many dB.  9.5 dB = 2.99x.
DEFAULT_THRESHOLD_DB: float = 9.5

#: Baseline window, in bins, for the prominence search. Always pass ``wlen``
#: with ``prominence``: unbounded, the search can reach an unrelated part of
#: the spectrum. Keep it at 4x ``distance`` or more; 11 bins truncates real
#: prominence. Evidence: CONTRIBUTING.md, "E12.1. Method".
PROMINENCE_WLEN_BINS: int = 41

#: First spectral null of each Welch window the GUI offers, in bins (measured).
#: ``distance`` is ``2 * null + 1``, so the two flanks of one main lobe are
#: never reported as two peaks. Evidence: CONTRIBUTING.md, "E12.4. Window nulls".
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

    Divide a running median of bin power by this ratio to get the mean noise
    power. One segment gives exponential bin power (ratio ``ln 2``);
    `n_segments` segments give ``Gamma(n, 1/n)``:

        segments   1      2      4      8     16
        ratio    0.693  0.839  0.913  0.956  0.978
    """
    n = max(1, int(n_segments))
    if n == 1:
        return float(np.log(2.0))
    return float(scipy.stats.gamma.median(n) / n)


def _running_median(values: np.ndarray, width: int) -> np.ndarray:
    """Running median with a *truncated* window at the two band edges.

    At bin *i* the result is the median of the bins within +/-width//2 of *i*
    that exist. Do not replace it with ``medfilt`` (zero-pad) or edge
    replication. Evidence: CONTRIBUTING.md, "E12.3. Edge handling".
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

    # Edge bins: pad with NaN and take a nanmedian, which is the median of the
    # samples inside the window. tests/test_peak_selection.py asserts that the
    # result is bit-identical to a per-bin np.median loop. Evidence (speed):
    # CONTRIBUTING.md, "E19. GUI render cost".
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
    the amplitude of an average noise bin at each frequency. It is a running
    median of bin power (not amplitude), corrected by
    :func:`median_to_mean_ratio` and converted back to amplitude.
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
    """Minimum separation, in bins, between two reported peaks for `window`."""
    null = WINDOW_FIRST_NULL_BINS.get(str(window).strip().lower(), DEFAULT_FIRST_NULL_BINS)
    return 2 * null + 1


def select_peaks(spectrum_amp: np.ndarray,
                 window: str = 'hann',
                 threshold_db: float = DEFAULT_THRESHOLD_DB,
                 floor: np.ndarray | None = None,
                 n_segments: int = 1,
                 floor_width: int = FLOOR_MEDIAN_WIDTH_BINS) -> np.ndarray:
    """Return the indices of every significant line, ranked by descending amplitude.

    A local maximum is reported when all four are true: it rises `threshold_db`
    above its local floor; it is within :data:`ABSOLUTE_FLOOR_DB` of the
    largest bin; its prominence is at least :data:`PROMINENCE_RATIO` x the
    height threshold; it is the tallest bin within :func:`peak_distance_bins`.
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
    # Rank by amplitude, not by significance: the table answers "how big".
    return np.asarray(found[np.argsort(-spectrum_amp[found])], dtype=int)
