"""Tapers, band masks and scalar statistics for the measurement chain.

``(j*omega)**n`` with n < 0 amplifies the wrap step of an off-bin block
(+4474 % in displacement at 501 Hz, un-tapered). Two treatments control it:

* Scalar overalls: Hann taper, then divide by the power gain (`hann_taper`).
* Displayed waveform: Tukey taper, keep only the flat middle
  (`tukey_taper`, `tukey_keep_slice`). The taper is not visible on the trace.

Evidence: CONTRIBUTING.md, "E9. Tapers for integration".
"""

import numpy as np
import scipy.signal

# Fraction of the block in the Tukey cosine tapers (half at each end). 0.5
# keeps the middle 50 % and holds the 61 Hz displacement peak error to +1.47 %.
# Evidence: CONTRIBUTING.md, "E9. Tapers for integration".
WAVEFORM_TUKEY_ALPHA: float = 0.5


def hann_taper(n: int) -> tuple[np.ndarray, float]:
    """Return (periodic Hann window of length n, its RMS power gain).

    Divide a windowed signal's RMS by the returned gain to recover the
    unwindowed broadband RMS.
    """
    w = scipy.signal.windows.hann(n, sym=False)
    return w, float(np.sqrt(np.mean(w ** 2)))


def tukey_taper(n: int, alpha: float = WAVEFORM_TUKEY_ALPHA) -> np.ndarray:
    """Return a periodic Tukey window: flat in the middle, cosine at the edges."""
    return scipy.signal.windows.tukey(n, alpha=alpha, sym=False)


def tukey_keep_slice(n: int, alpha: float = WAVEFORM_TUKEY_ALPHA) -> slice:
    """The slice of a length-n block over which `tukey_taper` is exactly 1.0.

    Samples outside this range are attenuated by the taper and must be
    discarded rather than displayed.
    """
    edge = int(np.ceil(n * alpha / 2.0))
    return slice(edge, n - edge)


def integrate_rfft(rfft_vals: np.ndarray, freq: np.ndarray, n_ord: int,
                   n_out: int) -> np.ndarray:
    """Apply (j*omega)**n_ord to an rFFT and transform back to the time domain.

    Bin 0 (DC) is always zeroed. For integration (n_ord < 0) bin 1 is also
    zeroed: residual near-DC energy goes up as 1/f**n, and on hardware bin 1
    otherwise dominated the spectrum. Zeroing one bin does not change the
    other bins.
    """
    omega = 2 * np.pi * freq          # fresh array — caller's freq is not mutated
    omega = omega.copy()
    omega[0] = 1.0                    # avoid 0**n_ord; the bin is zeroed below
    transfer = np.power(1j * omega, n_ord)
    transfer[0] = 0.0
    if n_ord < 0:
        transfer[1] = 0.0
    return np.fft.irfft(rfft_vals * transfer, n=n_out)


# Passband amplitude tolerance at the declared band edge. ISO 2954 requires
# +/-10 % across the declared band, edges included. A knee on the edge is
# -3 dB (29 % low) there. Evidence: CONTRIBUTING.md, "E8.3. Knee below the
# band edge".
PASSBAND_TOLERANCE: float = 0.9      # -0.915 dB


def butter_knee_for_edge(f_edge: float, order: int,
                         tolerance: float = PASSBAND_TOLERANCE) -> float:
    """-3 dB knee that puts an order-N Butterworth high-pass at `tolerance` on `f_edge`.

    Solves |H(f_edge)| = A for the knee fc:
    ``fc = f_edge * (A**2 / (1 - A**2)) ** (-1 / (2N))``.
    At order 4 and A = 0.9, fc = 0.8342 * f_edge: a 10 Hz edge gives an
    8.34 Hz knee and -0.915 dB at 10 Hz. Returns 0.0 if `f_edge` <= 0.
    Evidence: CONTRIBUTING.md, "E8.3. Knee below the band edge".
    """
    if f_edge <= 0:
        return 0.0
    a2 = float(tolerance) ** 2
    r = a2 / (1.0 - a2)
    return float(f_edge) * r ** (-1.0 / (2 * int(order)))


def band_mask(freq: np.ndarray, fmin: float, fmax: float) -> np.ndarray:
    """Boolean mask selecting the declared band from an rFFT frequency axis.

    Inclusive at both edges, so a bin centre on an edge stays in the band.
    """
    return (freq >= float(fmin)) & (freq <= float(fmax))


def band_rms(rfft_vals: np.ndarray, mask: np.ndarray, n: int) -> float:
    """Exact RMS of the masked band, by Parseval, from an un-tapered rFFT.

    `n` is the time-domain length. A full mask gives ``sqrt(mean(x**2))``.
    DC and, for even n, the Nyquist bin get weight 1; other bins weight 2.
    The edge has -13 dB rectangular-window sidelobes, so the overall uses
    the Hann path instead. Evidence: CONTRIBUTING.md, "E10. Band RMS".
    """
    power = np.abs(rfft_vals) ** 2
    weight = np.full(power.shape, 2.0)
    weight[0] = 1.0
    if n % 2 == 0 and power.shape[0] > 1:
        weight[-1] = 1.0
    total = float(np.sum(power[mask] * weight[mask]))
    return float(np.sqrt(total)) / n


def crest_factor(x: np.ndarray) -> float:
    """Peak divided by RMS.

    Dimensionless: sensitivity, display unit and amplitude mode do not change
    it. A sine gives sqrt(2); Gaussian noise gives about 3 to 4. Returns 0.0
    for an empty or all-zero record.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms <= 0.0:
        return 0.0
    return float(np.max(np.abs(x)) / rms)


def kurtosis(x: np.ndarray) -> float:
    """Fourth standardised moment, not excess kurtosis (Gaussian gives 3.0).

    Condition-monitoring thresholds ("above 4") use this convention. A sine
    gives 1.5. Returns 3.0 for an empty or constant record.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return 3.0
    var = float(np.var(x))
    if var <= 0.0:
        return 3.0
    return float(np.mean((x - np.mean(x)) ** 4) / var ** 2)

