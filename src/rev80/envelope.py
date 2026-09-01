"""Envelope (demodulation) analysis for rolling-element bearing defects.

Why this exists
---------------
A bearing defect does not announce itself as a line at the defect rate. Each
time a rolling element strikes the defect it produces an impulse, and that
impulse rings a structural resonance of the housing -- typically 2-20 kHz, far
above anything the machine does mechanically. In the raw spectrum the defect
energy is therefore smeared across that resonance and sits underneath the 1x and
its harmonics, which are orders of magnitude larger.

What carries the diagnosis is not where the energy is but how it is *modulated*:
the impulses repeat at the defect rate, so the resonance's amplitude envelope
carries a clean line there, with +/-1x sidebands from the load zone. Recovering
that envelope makes a fault visible months before the broadband overall moves.

Every instrument in this class ships this under some name -- CSI PeakVue,
SKF gE, B&K envelope analysis.

The chain
---------
1. Band-pass around the resonance. This is what discards the 1x, and it is the
   step that makes the rest work: demodulating the full-band signal just
   recovers the dominant low-frequency content again.
2. Hilbert magnitude -- the analytic signal's modulus is the instantaneous
   amplitude.
3. Remove the mean. The envelope is strictly positive, so its DC term is large
   and would otherwise dominate bin 0 and leak across the low end.
4. Spectrum of the envelope, over its own much lower F_max: the modulation
   rates of interest are a few hundred Hz at most, however high the carrier is.
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

#: Below this Nyquist frequency, envelope analysis is unlikely to have a real
#: housing resonance (typically 2-20 kHz) to work with at all -- the mandatory
#: anti-alias filter upstream has already removed everything above Nyquist
#: before the data reaches here, so there is nothing a wider demodulation band
#: could recover. suggest_band() will still return *a* band below this line,
#: but it can only be centred on ordinary machine content (1x, gear mesh),
#: which is exactly what demodulation exists to escape -- see the GUI's
#: F_max warning in the Envelope tab.
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

    # 1. Band-pass to the resonance. Zero-phase: group delay would shift the
    #    envelope in time relative to anything else on screen, and unlike the
    #    acquisition high-pass this filter runs on a whole stored record rather
    #    than across streaming block boundaries, so there is no state to carry
    #    and no edge transient to propagate.
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

    The user should not have to know where their housing resonance is to get a
    first look. This searches only the upper part of the usable band -- below
    that is machine content (1x and harmonics), which is exactly what
    demodulation is trying to escape, so a band centred there would be worse
    than useless.

    Returns (low, high) in Hz, always strictly inside the usable band. `fmax`
    defaults to Nyquist but should normally be the declared measurement band's
    upper edge, so the suggestion never reaches into the anti-alias guard
    region where the response is not a measurement.
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
