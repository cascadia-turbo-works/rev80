import time
import threading
import scipy.fft as fft
import numpy as np

import rev80
from rev80 import AcquisitionSettings

log = rev80.get_logger(__name__)

N_CHANNELS = 2


class _RawRateView:
    """Presents `config` at its raw acquisition rate to signal generators.

    Every generator below reads config.samplerate/blocksize/sampleperiod/
    time_vec to build one block. SimulatedSensor must generate (and report)
    blocks at raw_samplerate/raw_blocksize -- the same rate PicoScopeStream
    delivers and DataCollector.receive_data tags each frame with -- not the
    maxfreq-driven display rate those attributes normally give; otherwise
    the simulated path silently defeats raw-stream retention (envelope
    analysis, HDF5 storage) by handing it already-decimated data. Proxying
    keeps every generator, and the tests that call them directly against a
    real AcquisitionSettings, unchanged.
    """

    def __init__(self, config: AcquisitionSettings):
        self._config = config

    @property
    def samplerate(self):
        return self._config.raw_samplerate

    @property
    def blocksize(self):
        return self._config.raw_blocksize

    @property
    def sampleperiod(self):
        return self._config.raw_sampleperiod

    @property
    def time_vec(self):
        return self._config.raw_time_vec

    def __getattr__(self, name):
        return getattr(self._config, name)


def GenerateTone(config:AcquisitionSettings,
                 ampl:float = 1,
                 freq:float = 500,
                 phase:float = 0):

    # single frequency tone with velocity amplitude
    return ampl * np.cos(2*np.pi*freq * config.time_vec - phase)

def GenerateNoise(config:AcquisitionSettings, ampl:float = 1):
    # normal noise
    return ampl * np.random.randn(config.blocksize)

def bearing_harmonic_count(config: AcquisitionSettings, running_rate: float,
                           bearing_multiple: float) -> int:
    """How many defect harmonics fit below Nyquist.

    Exists because the inline expression got this wrong:

        int(freqs[-1] // bearing_multiple*running_rate)

    `//` and `*` have equal precedence and bind left to right, so that is
    (freqs[-1] // bearing_multiple) * running_rate -- roughly 5000x too many
    iterations at the default rates. Every harmonic beyond Nyquist then
    collapsed onto the last bin via argmin, piling severity/(k+1) writes onto
    freqs[-1]. Compare the running-speed loop, which had the parenthesisation
    right; a named function makes the two impossible to write differently.
    """
    defect_rate = float(running_rate) * float(bearing_multiple)
    if defect_rate <= 0:
        return 0
    nyquist = config.samplerate / 2.0
    return int(nyquist // defect_rate)


def GenerateBearingVibration_SpectralMethod(config:AcquisitionSettings):
    freqs = fft.rfftfreq(config.blocksize, d=config.sampleperiod)
    spectrum = np.zeros_like(freqs, dtype='complex128')

    # Create exponential noise with random phase
    N0 = 0.03
    NR = 1000
    spectrum +=  N0 * np.exp(-freqs/NR)  * np.exp(np.random.rand(*freqs.shape)*np.pi*2j)

    running = np.zeros_like(freqs) * 1j
    running_rate = 60
    running_level = 1. * np.exp(np.random.rand() * np.pi*2j)
    # running_overtones = 

    for k in range(int(freqs[-1] // running_rate)):
        running[np.argmin(np.abs(freqs-(k+1)*running_rate))] = running_level / (k+1)

    bearing = np.zeros_like(freqs) * 1j
    bearing_multiple = 9.23
    bearing_severity = 0.5 * np.exp(np.random.rand() * np.pi*2j)

    for k in range(bearing_harmonic_count(config, running_rate, bearing_multiple)):
        bearing[np.argmin(np.abs(freqs-(k+1)*running_rate*bearing_multiple))] = bearing_severity / (k+1)

    spectrum = running + bearing + spectrum
    signal = np.array(fft.irfft(spectrum))

    return signal

def GenerateBearingVibration_TemporalMethod(config:AcquisitionSettings):
    # Generate sample data representing rotating equipment with faulty bearing

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    signal = np.zeros_like(config.time_vec)

    signal += GenerateNoise(config, 0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        signal += GenerateTone(config, 1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        signal += GenerateTone(config, bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    # Pacing used to live here, as a time.sleep inside a signal generator. It
    # is now in SimulatedSensor._stream, so every generator is paced the same
    # way and calling one directly (as the tests do) is cheap.
    return signal


# ── Physically realistic bearing-defect model ──────────────────────────────
#
# The two generators above are ten pure cosines plus Gaussian white noise. Their
# kurtosis is ~3 -- Gaussian -- with no impulsiveness, no resonance carrier, no
# modulation sidebands and no slip. That makes them useless as an oracle for
# every diagnostic worth having: crest factor, kurtosis and envelope
# demodulation all key on exactly the properties the signal does not have, so a
# completely broken envelope analyser and a correct one both return "nothing
# here". They are kept for regression coverage of the older paths.
#
# What a real rolling-element defect actually produces:
#
#   1. An impulse each time a rolling element strikes the defect, at the defect
#      rate (BPFO/BPFI = running_rate x a non-integer bearing geometry factor).
#   2. Each impulse rings a STRUCTURAL RESONANCE of the housing, typically
#      2-20 kHz -- far above the running speed. This is why the defect is
#      invisible under the 1x in the raw spectrum but obvious in the envelope
#      of that resonance band, and therefore why envelope analysis exists.
#   3. The impulses are AMPLITUDE-MODULATED at the shaft rate as the defect
#      passes through the load zone, which is what puts +/-1x sidebands around
#      the defect line in the envelope spectrum.
#   4. Rolling elements SLIP by 1-2%, so the impulse train is not exactly
#      periodic. This is why a real defect line is slightly broadened and never
#      resolves to a single bin however fine the resolution.
#
# Defaults are a mid-size induction motor: 3600 rpm (60 Hz), an outer-race
# defect at 5.43x, a 4 kHz housing resonance.

DEFAULT_RUNNING_RATE_HZ:  float = 60.0
DEFAULT_BEARING_MULTIPLE: float = 5.43     # non-integer: real bearing geometry
DEFAULT_RESONANCE_HZ:     float = 4000.0
# Ring-down sharpness. What actually governs impulsiveness is the ratio of the
# ring-down time constant to the impulse interval: tau = Q / (pi * f_res), and
# once tau approaches one impulse period the ring-downs merge into a continuous
# tone and the signal stops being impulsive at all. Measured at the defaults
# (fs 32768, 0.5 s block, defect rate 325.8 Hz, period 3.07 ms, 4 kHz
# resonance), mean of 4 seeds:
#
#      Q   tau_ms  tau/period   kurtosis healthy   kurtosis severity=1
#      3     0.24      0.08              3.09              10.41
#      5     0.40      0.13              3.09               7.21
#      8     0.64      0.21              3.09               5.28
#     10     0.80      0.26              3.09               4.63
#     15     1.19      0.39              3.09               3.81
#     25     1.99      0.65              3.09               3.27
#     40     3.18      1.04              3.09               3.08
#
# Q=40 -- the textbook figure for a lightly damped housing resonance in
# isolation -- makes the fault undetectable by kurtosis, because at this defect
# rate its ring-down is longer than the gap between impulses. Real bearing
# signals damp faster than the bare resonance would, through the load path.
# Q=8 sits at tau/period = 0.21, inside the 10-30% range bearing-simulation
# practice uses, and separates 5.28 from 3.09 clearly enough to drive a
# threshold test.
DEFAULT_RESONANCE_Q:      float = 8.0
DEFAULT_SLIP:             float = 0.015    # 1.5%
DEFAULT_LOAD_ZONE_DEPTH:  float = 0.6      # AM depth at the shaft rate
DEFAULT_NOISE:            float = 0.05


def GenerateBearingVibration(config: AcquisitionSettings,
                             severity: float = 1.0,
                             running_rate: float = DEFAULT_RUNNING_RATE_HZ,
                             bearing_multiple: float = DEFAULT_BEARING_MULTIPLE,
                             resonance_hz: float = DEFAULT_RESONANCE_HZ,
                             resonance_q: float = DEFAULT_RESONANCE_Q,
                             slip: float = DEFAULT_SLIP,
                             load_zone_depth: float = DEFAULT_LOAD_ZONE_DEPTH,
                             noise: float = DEFAULT_NOISE,
                             seed: int | None = None) -> np.ndarray:
    """One block of accelerometer signal from a machine with a bearing defect.

    `severity=0.0` is the healthy negative control: running-speed harmonics and
    noise, no impulses at all, kurtosis ~3. Without a credible healthy case
    "the detector fired" proves nothing, so the same function has to produce
    both. `severity=1.0` is a clearly developed fault.

    `seed` makes a block reproducible so a failing diagnostic test can be
    re-run on the identical waveform.
    """
    rng = np.random.default_rng(seed)
    fs = float(config.samplerate)
    n = int(config.blocksize)
    t = np.arange(n) / fs

    # ── Shaft: 1x and harmonics, present healthy or not ───────────────────
    # Independent phase per harmonic. A single shared phase is both
    # unphysical -- the harmonics of a real machine come from different
    # mechanisms and are not phase-locked to one value -- and unstable as a
    # negative control: it made healthy kurtosis swing 2.03-4.00 across seeds
    # purely on how the five cosines happened to line up, which overlaps the
    # faulted range and would make any threshold test flaky. With independent
    # phases healthy sits at 2.68-3.16 over 40 seeds.
    sig = np.zeros(n, dtype=np.float64)
    shaft_phase = rng.uniform(0, 2 * np.pi)
    for k in range(1, 6):
        f_k = running_rate * k
        if f_k >= fs / 2:
            break
        sig += (1.0 / k) * np.cos(2 * np.pi * f_k * t + rng.uniform(0, 2 * np.pi))

    sig += noise * rng.standard_normal(n)

    if severity <= 0.0:
        return sig

    # ── Defect impulse train, with slip ───────────────────────────────────
    # Impulse k lands at k/defect_rate perturbed by a random walk of `slip`,
    # not at an exactly periodic instant. Independent per-impulse jitter would
    # broaden the line too, but slip is a cumulative phase error, and a random
    # walk is what reproduces the characteristic smearing that worsens with
    # harmonic order.
    defect_rate = running_rate * bearing_multiple
    if defect_rate <= 0 or defect_rate >= fs / 2:
        return sig

    period = 1.0 / defect_rate
    n_imp = int(t[-1] / period) + 1
    nominal = np.arange(n_imp) * period
    if slip > 0:
        walk = np.cumsum(rng.normal(0.0, slip * period, n_imp))
        strikes = nominal + walk
    else:
        strikes = nominal
    strikes = strikes[(strikes >= 0) & (strikes < t[-1])]

    # ── Load-zone amplitude modulation at the shaft rate ──────────────────
    amps = np.ones_like(strikes)
    if load_zone_depth > 0:
        amps = 1.0 + load_zone_depth * np.cos(
            2 * np.pi * running_rate * strikes + shaft_phase
        )
        amps = np.clip(amps, 0.0, None)

    # ── Each strike rings the housing resonance ───────────────────────────
    # Exponentially decaying sinusoid, decay set by Q. Built as a single
    # kernel and placed at each strike, so the cost is O(n_impulses * kernel)
    # rather than O(n_impulses * n).
    decay = np.pi * resonance_hz / max(resonance_q, 1e-6)
    k_len = min(n, int(np.ceil(5.0 / decay * fs)))
    k_t = np.arange(k_len) / fs
    kernel = np.exp(-decay * k_t) * np.sin(2 * np.pi * resonance_hz * k_t)

    impulses = np.zeros(n, dtype=np.float64)
    idx = np.clip((strikes * fs).astype(int), 0, n - 1)
    np.add.at(impulses, idx, amps)
    rung = np.convolve(impulses, kernel)[:n]

    # Scale so severity=1.0 puts the defect at roughly the shaft signal's own
    # RMS -- large enough to diagnose, small enough that it does not simply
    # dominate the waveform the way a synthetic tone would.
    rms = float(np.sqrt(np.mean(rung ** 2)))
    if rms > 0:
        rung *= float(severity) * float(np.sqrt(np.mean(sig ** 2))) / rms

    return sig + rung


class SimulatedSensor:

    def __init__(self, config:AcquisitionSettings, sensor, callback):
        self._running: bool = False

        self.sensor = sensor
        self.config = config
        self.channels = max(1, len(config.enabled_channels))
        self.callback = callback
        # The physically realistic model is the default: the pure-tone
        # generators cannot exercise crest factor, kurtosis or envelope
        # analysis, so an offline run against them would validate nothing.
        # They remain importable, and are still covered by their own tests.
        self.source: tuple = (GenerateBearingVibration,)
        self.stream: threading.Thread

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self.stream = threading.Thread(target=self._stream, daemon=True)

    def _sample(self):
        # HACK: to acomplish FFT units testing
        # Raw rate, not display rate -- see _RawRateView.
        args = self.source[1:] if len(self.source)>1 else []
        signal = self.source[0].__call__(_RawRateView(self.config), *args) # type: ignore

        # One column per enabled channel. This used to be
        # max(len(enabled_channels), N_CHANNELS), which forced a minimum of two
        # columns -- a workaround for VibeSensor.simulated()'s fixed 2-element
        # `scale`. That scale is now fitted to the data (audit S-12), so the
        # floor is unnecessary, and it was actively wrong: a single-channel
        # configuration got a phantom second channel.
        n_ch = max(1, len(self.config.enabled_channels))
        return np.tile(signal, (n_ch, 1)).T

    def _stream(self):
        """Acquisition loop.

        Guarded: an unhandled exception here used to kill the thread while
        `_running` stayed True, so `active` -- and through it
        DataCollector.is_streaming -- reported a healthy stream that would
        never produce another frame (audit S-12). A stream that has stopped
        must say so; silently pretending to run is worse than crashing, because
        nothing downstream can tell the difference from a very quiet machine.
        """
        self._running = True
        try:
            next_due = time.monotonic()
            while self._running:
                self.callback(self._sample(), self.config.raw_blocksize,
                              time.monotonic(), 'OKAY')
                # Emit blocks at the rate real hardware would. Sleeping the
                # remaining time rather than a fixed interval keeps the block
                # rate honest when generation itself is slow.
                next_due += self.config.acquisition_period
                delay = next_due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_due = time.monotonic()
        except Exception:
            log.exception('SimulatedSensor stream thread died')
        finally:
            self._running = False

    def start(self):
        self.stream.start()

    def stop(self):
        self._running = False
        if self.stream.is_alive():
            self.stream.join()
        self.create_stream()

    def abort(self):
        self.stop()

    def close(self):
        pass
