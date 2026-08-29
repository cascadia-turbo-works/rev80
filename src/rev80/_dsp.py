"""Windowing helpers for frequency-domain integration / differentiation.

Why these exist
---------------
``process_sample`` converts between acceleration, velocity and displacement
by multiplying the block's rFFT by ``(j*omega)**n`` and transforming back.
The DFT treats the block as periodic, so unless the signal happens to be
exactly periodic in N samples there is a step discontinuity at the wrap
point.  That step's spectrum is broadband and low-frequency-weighted, and
``(j*omega)**n`` with n < 0 amplifies it by 1/omega**|n| — precisely where it
is largest.

Measured on a 1.0 g 0-pk sine, fs=32768, N=16384, displacement overall::

    tone       on-bin?   true RMS      un-windowed    error
    500.0 Hz     yes    7.1645e-08     7.1645e-08     +0.00%
    501.0 Hz     no     7.1359e-08     3.2638e-06   +4473.76%
     61.0 Hz     no     4.8136e-06     2.7466e-05    +470.59%
    120.7 Hz     no     1.2294e-06     1.0793e-05    +777.84%

The on-bin row is why the pre-existing test suite never caught this: it swept
tones only at exact multiples of the bin width.

Two different treatments are needed, because the two consumers want
different things:

* **Scalar overalls** (trend, result card, anomaly detector) want an unbiased
  RMS over the whole record.  A Hann taper plus division by the window's
  power gain ``sqrt(mean(w**2))`` gives that — the standard broadband
  correction.  See :func:`hann_taper`.

* **The displayed waveform** cannot be tapered, because the taper would be
  plainly visible as an amplitude envelope on the trace the user is reading.
  Instead a Tukey window (flat across the middle, cosine-tapered at the
  edges) removes the wrap discontinuity, and only the flat middle is
  returned — overlap-save, discarding the tapered edges.  Inside the flat
  region the window is exactly 1.0, so the samples are undistorted.
  See :func:`tukey_taper` and :func:`tukey_keep_slice`.
"""

import numpy as np
import scipy.signal

# Fraction of the block spanned by the Tukey cosine tapers (half at each end).
# 0.5 keeps the middle 50 % of the record.  Measured waveform peak error for a
# doubly-integrated 61 Hz tone (the hardest case — lowest frequency, two
# integrations) as a function of this value:
#
#     alpha   retained   61 Hz vel   61 Hz disp   501 Hz disp
#      0.00      100 %     +90.22 %   +1149.12 %   +10176.68 %
#      0.05       95 %     +32.75 %    +335.84 %      +18.56 %
#      0.10       90 %      +0.18 %      +7.00 %       +0.85 %
#      0.30       70 %      +0.14 %      +4.22 %       +0.58 %
#      0.50       50 %      +0.10 %      +1.47 %       +0.24 %
#
# 0.5 is the first value that holds every case comfortably inside 2 %.
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

    Bin 0 (DC) is always zeroed.  For integration (n_ord < 0) bin 1 is zeroed
    too: a single time-domain highpass pass cannot stop residual near-DC
    energy from blowing up under 1/f**n, and zeroing an exact FFT bin is
    lossless for every other frequency (confirmed on real hardware, where
    bin 1 otherwise dominated the whole spectrum).
    """
    omega = 2 * np.pi * freq          # fresh array — caller's freq is not mutated
    omega = omega.copy()
    omega[0] = 1.0                    # avoid 0**n_ord; the bin is zeroed below
    transfer = np.power(1j * omega, n_ord)
    transfer[0] = 0.0
    if n_ord < 0:
        transfer[1] = 0.0
    return np.fft.irfft(rfft_vals * transfer, n=n_out)
