"""Envelope (demodulation) analysis for rolling-element bearing defects.

The chain:

1. Band-pass around the housing resonance. This step removes the 1x. Without
   it, demodulation recovers the low-frequency content again.
2. Hilbert magnitude: the instantaneous amplitude.
3. Remove the mean, so the DC term does not leak across the low end.
4. Amplitude spectrum of the envelope, up to its own F_max (500 Hz default).

The operator view of the physics is in README.md, "Envelope analysis".
"""

import numpy as np
import scipy.signal

#: Band-pass filter order for the demodulation band (Butterworth, zero-phase,
#: so the effective order is doubled). Steep enough to reject a 1x that can be
#: 40 dB above the resonance, shallow enough to stay numerically stable as SOS
#: at the narrow relative bandwidths a resonance band implies.
BANDPASS_ORDER: int = 4

#: Default upper limit for the envelope spectrum, in Hz. Defect rates and their
#: first few harmonics live below this; going higher just adds empty axis.
DEFAULT_ENVELOPE_FMAX: float = 500.0

#: Fraction of the usable band that `suggest_band` spans. Wide enough to
#: contain a real resonance and the sidebands beside it, narrow enough that the
#: band-pass still rejects the 1x.
SUGGEST_BAND_FRAC: float = 0.25

#: Below this Nyquist frequency a housing resonance (typically 2-20 kHz) is
#: probably not in the record. suggest_band() still returns a band, but it can
#: only sit on machine content. The GUI Envelope tab shows a warning below it.
MIN_USEFUL_NYQUIST_HZ: float = 5000.0


def envelope_spectrum(x: np.ndarray, fs: float, band: tuple[float, float],
                      env_fmax: float = DEFAULT_ENVELOPE_FMAX,
                      detrend: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Amplitude spectrum of the envelope of `x` within `band`.

    Returns (freq, amplitude). Amplitudes are in the same units as `x` and are
    scaled so a sinusoidal modulation of depth d on a carrier of amplitude A
    reads d*A/2 -- i.e. the modulation sideband amplitude, which is what the
    line in an envelope spectrum physically is.

    `band` is (low, high) in Hz and must sit strictly inside (0, fs/2).
    """
    x = np.asarray(x, dtype=np.float64)
    lo, hi = float(band[0]), float(band[1])
    nyq = fs / 2.0
    if not (0.0 < lo < hi < nyq):
        raise ValueError(
            f'demodulation band ({lo:g}, {hi:g}) Hz must satisfy '
            f'0 < low < high < Nyquist ({nyq:g} Hz)'
        )
    if x.size < 16:
        raise ValueError(f'record too short to demodulate: {x.size} samples')

    # 1. Band-pass to the resonance. Zero-phase is correct here: the filter
    #    runs on one whole record, so there is no state to carry across blocks.
    sos = scipy.signal.butter(BANDPASS_ORDER, (lo, hi), btype='bandpass',
                              fs=fs, output='sos')
    banded = scipy.signal.sosfiltfilt(sos, x)

    # 2. Instantaneous amplitude.
    envelope = np.abs(scipy.signal.hilbert(banded))

    # 3. The envelope is strictly positive; its mean is a large DC term that
    #    would dominate bin 0 and leak into the low end where the defect
    #    harmonics live.
    if detrend:
        envelope = envelope - envelope.mean()

    # 4. Spectrum of the envelope. Hann-windowed with coherent-gain correction,
    #    so a line reads its true amplitude rather than a window-dependent one.
    n = envelope.size
    w = scipy.signal.windows.hann(n, sym=False)
    spec = np.abs(np.fft.rfft(envelope * w)) / (n * float(np.mean(w))) * 2.0
    freq = np.fft.rfftfreq(n, 1.0 / fs)

    if env_fmax and env_fmax > 0:
        keep = freq <= float(env_fmax)
        freq, spec = freq[keep], spec[keep]
    return freq, spec


def suggest_band(x: np.ndarray, fs: float, fmax: float | None = None,
                 frac: float = SUGGEST_BAND_FRAC) -> tuple[float, float]:
    """Propose a demodulation band centred on the dominant high-frequency energy.

    Returns (low, high) in Hz, inside the usable band (0, top]. `top` is `fmax`,
    or Nyquist when `fmax` is not given, and never above 0.99 x Nyquist. Pass
    the upper edge of the usable band as `fmax` to keep the band out of the
    anti-alias transition band. The search covers 0.25 x top to top only.
    Evidence: CONTRIBUTING.md, "E13. Envelope band search".
    """
    x = np.asarray(x, dtype=np.float64)
    nyq = fs / 2.0
    top = float(fmax) if fmax else nyq
    top = min(top, nyq * 0.99)

    n = x.size
    w = scipy.signal.windows.hann(n, sym=False)
    power = np.abs(np.fft.rfft(x * w)) ** 2
    freq = np.fft.rfftfreq(n, 1.0 / fs)

    # Search above a quarter of the usable band: resonances live high, machine
    # orders live low.
    search_lo = 0.25 * top
    band_w = frac * top
    m = (freq >= search_lo) & (freq <= top)
    if not m.any():
        return (0.5 * top, 0.9 * top)

    # Smooth over the suggested bandwidth and take the argmax, so the choice is
    # driven by where the *band* energy is, not by a single tall line -- a lone
    # harmonic is not a resonance.
    df = freq[1] - freq[0]
    win = max(3, int(band_w / max(df, 1e-9)) | 1)
    kernel = np.ones(win) / win
    smoothed = np.convolve(power, kernel, mode='same')
    smoothed[~m] = 0.0
    centre = float(freq[int(np.argmax(smoothed))])

    lo = max(centre - band_w / 2.0, 0.02 * top)
    hi = min(centre + band_w / 2.0, top)
    if hi <= lo:                        # degenerate; fall back to the top half
        lo, hi = 0.5 * top, 0.9 * top
    return (float(lo), float(hi))
