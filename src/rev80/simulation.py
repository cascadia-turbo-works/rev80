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
                             seed: int | None = None,
                             shaft_phase: float | None = None) -> np.ndarray:
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
    # An explicit shaft_phase pins the angular reference so a tachometer pulse
    # can be generated at a known point in the same revolution (see
    # GenerateMachineWithTach). Drawn from the same rng when not given, so the
    # default behaviour and its random draw order are unchanged.
    if shaft_phase is None:
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


# ---------------------------------------------------------------------------
# Tachometer
# ---------------------------------------------------------------------------

#: Default rise/fall time of a generated tach edge, in samples. Measured on a
#: 4424A: a real TTL edge arrives at the collector with about one intermediate
#: sample, because the mandatory anti-alias decimation band-limits it after the
#: ADC. An ideal zero-rise rectangle is a *degenerate* stimulus -- no sample
#: lands in the detector's hysteresis band and sub-sample interpolation has
#: nothing to interpolate -- so generating one would have CI exercise a regime
#: the instrument never sees. See rev80.tach's module docstring.
TACH_RISE_SAMPLES: float = 1.5

DEFAULT_TACH_AMPLITUDE_MV: float = 5000.0   # 0-5 V TTL / laser tach output
DEFAULT_TACH_WIDTH_S: float = 200e-6        # comfortably above the ~50 us floor


def GenerateTachPulse(config: AcquisitionSettings,
                      rpm: float = 1800.0,
                      pulses_per_rev: int = 1,
                      width_s: float = DEFAULT_TACH_WIDTH_S,
                      amplitude_mv: float = DEFAULT_TACH_AMPLITUDE_MV,
                      offset_mv: float = 0.0,
                      polarity: str = 'rising',
                      jitter_pct: float = 0.0,
                      phase_s: float = 0.0,
                      rise_samples: float = TACH_RISE_SAMPLES,
                      seed: int | None = None) -> np.ndarray:
    """One block of tachometer signal, in **millivolts**.

    Returns a pulse train idling low (or high, for `polarity='falling'`) with a
    finite rise, matching what a keyphasor or laser tach delivers to
    DataCollector after the acquisition chain's anti-alias filter.

    `pulses_per_rev` defaults to 1 per decision D-6 -- one reflective tape or
    one keyway, which is both the common installation and the accurate one.

    `jitter_pct` perturbs each pulse instant by a fraction of the nominal
    period, modelling real torsional/cyclic shaft variation. It should show up
    in `TachResult.interval_spread`, not as a rate error.
    """
    rng = np.random.default_rng(seed)
    fs = float(config.samplerate)
    n = int(config.blocksize)
    t = np.arange(n) / fs

    pulse_rate = float(rpm) * max(1, int(pulses_per_rev)) / 60.0
    if pulse_rate <= 0:
        return np.full(n, offset_mv, dtype=np.float64)
    period = 1.0 / pulse_rate

    # Pulse instants. Jitter is applied per pulse (not as a cumulative walk):
    # this models cycle-to-cycle shaft variation, which is what an analyst sees
    # as interval spread. Cumulative slip is the defect model's job, not this.
    n_pulses = int(np.ceil(t[-1] / period)) + 2
    starts = (np.arange(n_pulses) * period) + float(phase_s)
    if jitter_pct > 0:
        starts = starts + rng.normal(0.0, jitter_pct / 100.0 * period, n_pulses)

    rise_s = max(rise_samples, 1e-9) / fs
    x = np.zeros(n, dtype=np.float64)
    for s in starts:
        if s > t[-1] + period or s + width_s < 0:
            continue
        # Trapezoid: linear rise, flat top, linear fall. Clipped rather than
        # branched so a pulse straddling the block edge is handled naturally.
        up = np.clip((t - s) / rise_s, 0.0, 1.0)
        down = np.clip((t - s - width_s) / rise_s, 0.0, 1.0)
        x = np.maximum(x, up - down)

    if polarity == 'falling':
        x = 1.0 - x
    return x * float(amplitude_mv) + float(offset_mv)


def GenerateMachineWithTach(config: AcquisitionSettings,
                            running_rate: float = DEFAULT_RUNNING_RATE_HZ,
                            severity: float = 1.0,
                            vib_channel: int = 0,
                            tach_channel: int = 1,
                            pulses_per_rev: int = 1,
                            seed: int | None = None,
                            **vib_kwargs) -> dict:
    """A vibration channel and a tachometer channel from the *same* shaft.

    Returns ``{vib_channel: accel, tach_channel: tach_mv}``.

    The coherence is the point. A tach pulse train that is not locked to the
    vibration's own shaft rate cannot validate anything -- a broken tachometer
    and a correct one both return a plausible number against an unrelated
    signal. This is the same argument this module already makes about pure
    cosines being unable to validate envelope analysis.

    Both channels share `running_rate` and an explicit shaft phase, so the
    tach's rising edge marks a fixed angular position: the instant the load
    zone is at its maximum. That makes the rate check (tach RPM vs the 1x peak
    in the vibration's own spectrum) possible now, and an angular check
    possible later without regenerating anything.
    """
    rng = np.random.default_rng(seed)
    shaft_phase = float(rng.uniform(0, 2 * np.pi))

    vib = GenerateBearingVibration(
        config, severity=severity, running_rate=running_rate,
        seed=seed, shaft_phase=shaft_phase, **vib_kwargs)

    # The load zone peaks where cos(2*pi*f*t + shaft_phase) == 1, i.e. at
    # t = -shaft_phase / (2*pi*f). Put the first pulse there, modulo one
    # revolution, so the tach edge is the shaft's angular origin.
    period = 1.0 / float(running_rate) if running_rate > 0 else 0.0
    phase_s = float(np.mod(-shaft_phase / (2 * np.pi) * period, period)) if period else 0.0

    tach_mv = GenerateTachPulse(
        config, rpm=running_rate * 60.0, pulses_per_rev=pulses_per_rev,
        phase_s=phase_s, seed=seed)

    return {vib_channel: vib, tach_channel: tach_mv}


def machine_with_tach_sources(running_rate: float = DEFAULT_RUNNING_RATE_HZ,
                              severity: float = 1.0,
                              vib_channel: int = 0,
                              tach_channel: int = 1,
                              seed: int | None = None) -> dict:
    """`channel_sources` entries for a coherent vibration + tachometer pair.

    The streaming counterpart to GenerateMachineWithTach: assign the result to
    `SimulatedSensor.channel_sources`. Exists so that the two rates cannot be
    set independently and drift apart, which is the obvious way to get a
    simulated tach that reads a shaft the vibration channel is not on.
    """
    return {
        vib_channel:  (GenerateBearingVibration, severity, running_rate),
        tach_channel: (GenerateTachPulse, running_rate * 60.0),
    }


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
        # Optional per-channel overrides: {ch: (fn, *args)}. Empty means every
        # enabled channel carries one tiled copy of `source`, which is the
        # historical behaviour and is preserved byte-for-byte. A tachometer
        # channel is impossible without this: tiling would give the tach input
        # the same accelerometer waveform as the vibration input.
        self.channel_sources: dict[int, tuple] = {}
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
        if not self.channel_sources:
            return np.tile(signal, (n_ch, 1)).T

        # Per-channel mode: each enabled channel gets its own generated block,
        # from its override if it has one and from `source` otherwise. Note
        # that channels falling back to `source` are generated independently
        # rather than sharing one draw -- which is both more realistic and
        # unavoidable, since each call advances its own rng.
        raw = _RawRateView(self.config)
        cols = []
        for ch in sorted(self.config.enabled_channels):
            fn, *fn_args = self.channel_sources.get(ch, self.source)
            cols.append(np.asarray(fn(raw, *fn_args), dtype=np.float64))
        return np.column_stack(cols)

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
