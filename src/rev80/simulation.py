import time
import threading
import scipy.fft as fft
import numpy as np

import rev80
from rev80 import AcquisitionSettings

log = rev80.get_logger(__name__)

N_CHANNELS = 2


class _RawRateView:
    """Presents `config` at its raw rate to signal generators.

    The generators read `samplerate`, `blocksize`, `sampleperiod` and
    `time_vec`. This view returns the raw-rate values, so SimulatedSensor
    delivers blocks at `raw_samplerate`, as PicoScopeStream does. All other
    attributes pass through to `config`.
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
    """How many harmonics of `running_rate * bearing_multiple` fit below Nyquist."""
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

    return signal


# ── Bearing-defect model: the four properties GenerateBearingVibration has ──
#   1. An impulse at the defect rate (running rate x a non-integer factor).
#   2. Each impulse rings a housing resonance (default 4 kHz).
#   3. Load-zone amplitude modulation at the shaft rate (+/-1x sidebands).
#   4. Cumulative slip (default 1.5 %), so the defect line is not one bin.
# Defaults: 3600 RPM (60 Hz) shaft, outer-race defect at 5.43x.

DEFAULT_RUNNING_RATE_HZ:  float = 60.0
DEFAULT_BEARING_MULTIPLE: float = 5.43     # non-integer: real bearing geometry
DEFAULT_RESONANCE_HZ:     float = 4000.0
# Q = 8, not the textbook 40: at Q = 40 the severity=1 kurtosis reads 3.08
# against a healthy 3.09. Evidence: CONTRIBUTING.md, "E15. Simulation model
# constants".
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

    `severity=0.0` is the healthy negative control: shaft harmonics and noise,
    no impulses, kurtosis about 3 (1.54 to 3.04 over 40 seeds; 3.86 to 6.12
    at `severity=1.0`). `severity=1.0` is a developed fault. `seed` makes the
    block reproducible. `shaft_phase` fixes the angular reference
    (see GenerateMachineWithTach).
    """
    rng = np.random.default_rng(seed)
    fs = float(config.samplerate)
    n = int(config.blocksize)
    t = np.arange(n) / fs

    # ── Shaft: 1x and harmonics, present healthy or not ───────────────────
    # One independent phase for each harmonic. A shared phase makes the healthy
    # kurtosis unstable. Evidence: CONTRIBUTING.md, "E15. Simulation model
    # constants".
    sig = np.zeros(n, dtype=np.float64)
    # When not given, shaft_phase is the first draw from rng. Moving this draw
    # changes the block that each seed produces.
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
    # Impulse k lands at k/defect_rate plus a random walk of `slip`. Slip is a
    # cumulative phase error, so the smearing increases with harmonic order.
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

#: Default rise/fall time of a generated tach edge, in samples. On a 4424A a
#: real TTL edge has about one intermediate sample. Do not use a zero-rise
#: rectangle: sub-sample interpolation then has nothing to interpolate.
#: Evidence: CONTRIBUTING.md, "E14.3. Interpolation".
TACH_RISE_SAMPLES: float = 1.5

DEFAULT_TACH_AMPLITUDE_MV: float = 5000.0   # 0-5 V TTL / laser tach output
DEFAULT_TACH_WIDTH_S: float = 200e-6        # about 5 samples at 25600 Hz


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

    A pulse train that idles low (high for `polarity='falling'`), with a rise
    of `rise_samples`. `pulses_per_rev` defaults to 1: one pulse per revolution
    is the default and the recommended configuration. `jitter_pct` moves each
    pulse by a random fraction of the period (not cumulative); it must show in
    `TachResult.interval_spread`, not as a rate error.
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

    Returns ``{vib_channel: accel, tach_channel: tach_mv}``. Both channels
    share `running_rate` and one shaft phase, so a test can compare the tach
    speed with the 1x line. The tach rising edge is at the load-zone maximum.
    A tach that is not locked to the vibration shaft validates nothing.
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
    `SimulatedSensor.channel_sources`. Both entries get the same shaft rate.
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
        # The bearing model is the default. The pure-tone generators cannot
        # exercise crest factor, kurtosis or envelope analysis.
        self.source: tuple = (GenerateBearingVibration,)
        # Optional per-channel overrides: {ch: (fn, *args)}. When empty, every
        # enabled channel gets the same copy of one `source` block. A
        # tachometer channel needs an override.
        self.channel_sources: dict[int, tuple] = {}
        self.stream: threading.Thread

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self.stream = threading.Thread(target=self._stream, daemon=True)

    def _sample(self):
        # `source` is (fn, *args). Generate at the raw rate (see _RawRateView).
        args = self.source[1:] if len(self.source)>1 else []
        signal = self.source[0].__call__(_RawRateView(self.config), *args) # type: ignore

        # One column for each enabled channel, and at least one.
        n_ch = max(1, len(self.config.enabled_channels))
        if not self.channel_sources:
            return np.tile(signal, (n_ch, 1)).T

        # Per-channel mode: each enabled channel gets its own block, from its
        # override or from `source`. Channels that use `source` get independent
        # draws, not one shared block.
        raw = _RawRateView(self.config)
        cols = []
        for ch in sorted(self.config.enabled_channels):
            fn, *fn_args = self.channel_sources.get(ch, self.source)
            cols.append(np.asarray(fn(raw, *fn_args), dtype=np.float64))
        return np.column_stack(cols)

    def _stream(self):
        """Acquisition loop, paced at `acquisition_period`.

        On any exception it logs the traceback and sets `_running` to False, so
        `active` (and DataCollector.is_streaming) reports the stop.
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
