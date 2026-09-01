"""rev80.tach — tachometer channel support: edge detection and shaft speed.

Deliberately free of dearpygui, h5py and DataCollector imports so it can be
unit-tested standalone and reasoned about without the acquisition chain.

Units
-----
Everything here is in **millivolts**, matching `VibeSample.data` and
`VibeSample.unit == 'mV'`. Sensitivity (mV -> EU) is applied downstream in
`DataCollector.process_sample`, and a tachometer channel never goes through
it: a pulse train has no engineering unit, and scaling one by an
accelerometer's mV/g would produce a plausible-looking wrong number.

What is measured, and where
---------------------------
Edge detection runs in `DataCollector.receive_data`, on the raw mV block,
*before* the Butterworth high-pass -- which is skipped entirely for a
tachometer channel. Measured on a 5.00 V pulse train, 1.0 s block, edges at a
2.5 V threshold:

    RPM    width   duty   raw hi/lo (mV)   after HP (mV)   raw edges   HP edges
     300   1 ms    0.5%   5440 / -440      5420 / -1124        6           6
    1800   200us   0.6%   5441 / -465      5442 /  -585       31          31
    1800   5 ms    15%    5440 / -440      5891 / -3390       31         108
    3600   10 ms   60%    5440 / -440      3961 / -5341       61          60

At 15% duty the high-pass overshoot on each falling edge re-crosses the
threshold and an 1800 RPM shaft reads 6270 RPM. The bypass is not an
optimisation.

Timing budget
-------------
Acquisition is fixed at RAW_SAMPLERATE_HZ = 40000, but the driver rounds the
sample interval to 12 us and the true reported rate is **41666.5 Hz** (verified
on a 4424A, serial 12462/0067). Edge quantisation is therefore 24.0 us on
hardware and 25.0 us in CI, and every rate here is taken from the sample's own
`samplerate` rather than the constant -- reaching for the constant reads 4.166%
high on hardware and is exactly right in CI, which is the worst combination a
defect can have.

Measured end to end against an AWG square wave (DC coupled, +/-5 V range,
2 Vpp at 1 V offset, adaptive threshold):

    AWG Hz   true RPM     measured   error RPM   error %   edges   spread
       5        300       299.508      -0.492    -0.164      5     0.0001
      10        600       600.153      +0.153    +0.026     10     0.0001
      30       1800      1800.383      +0.383    +0.021     29     0.0003
      60       3600      3599.818      -0.182    -0.005     57     0.0004
     100       6000      6001.106      +1.106    +0.018     96     0.0010
     170      10200     10204.025      +4.025    +0.040    163     0.0024

Error scales with speed, so the honest claim is **+/-0.2% of reading** at
1 pulse/rev from 300 to 10200 RPM -- not a fixed RPM figure. Line naming (the
use that justifies the feature) needs 0.3%.

Sub-sample interpolation, and when it helps
-------------------------------------------
A keyphasor or TTL tach switches in nanoseconds, and there is no analog
anti-alias filter ahead of the ADC (`RunStreaming` with `RATIO_MODE_NONE` takes
one instantaneous sample every 12 us). So the obvious worry is that an edge
arrives as a hard step -- both straddling samples at the rails, interpolated
fraction constant, estimator silently degenerating to nearest-sample rounding.

Measured on the bench, that is not what arrives. A real captured edge has
**exactly one intermediate sample** (58 samples inside the 10-90% band across
58 transitions of a 30 Hz square), flanked by ~8% Gibbs ringing, and the
interpolated fraction varies over [0.294, 0.707] rather than sitting at a
constant -- i.e. it carries real sub-sample position. Interpolated vs
nearest-sample, same captures:

    pulse rate   samples/period   interpolated   nearest   gain
       30 Hz         1388.9          0.021%      0.008%    0.4x
      200 Hz          208.3          0.038%      0.160%    4.2x
      600 Hz           69.4          0.047%      0.644%   13.8x
     1500 Hz           27.8          0.791%      0.794%    1.0x
     3000 Hz           13.9          0.785%      0.794%    1.0x

Three regimes. Below ~600 Hz pulse rate interpolation is worth 4-14x. Above
about 1000 samples per period it is marginally *worse* than rounding, because
quantisation there is already under 0.07% and dithering averages it away while
interpolation adds its own small systematic error -- both are excellent, the
difference does not matter. Below ~40 samples per period **both** collapse to
~0.8%: the median locks onto the modal integer period (27.778 samples reads as
exactly 28.000) and the compressed [0.29, 0.71] transfer cannot reconstruct the
fraction.

That last regime is a real limit on pulses_per_rev, and it binds sooner than
pulse-width considerations do. Full accuracy wants **>= ~70 samples per pulse,
i.e. a pulse rate at or below ~600 Hz**:

    1 ppr    -> 36000 RPM   (never binds)
    6 ppr    ->  6000 RPM
    60 ppr   ->   600 RPM
    1024 ppr ->    35 RPM   (a high-line encoder is impractical here)

Not isolated: which stage does the band-limiting. `antialias_decimate` is the
only lowpass after the ADC and is the likely cause, but a pure step landing
between two 83 kHz samples would smear symmetrically and carry no sub-sample
information at all, so something upstream contributes as well. The design rests
on the measured effect, not on the attribution.

Consequence for tests: an ideal rectangle is a *degenerate* stimulus here, not
a conservative one. The accuracy tests in tests/test_measurement_validity.py
must push their signals through `antialias_decimate` rather than assert against
synthetic squares, or they measure quantisation and call it accuracy.

Divide-by-zero in the interpolation is unreachable by construction: an edge
requires the previous state to be a decided low, so `y0 <= hi < y1` and the
denominator is strictly positive. Measured minimum across 2880 real edges:
1461.7 mV. The guard in the code is defensive only.

One pulse per revolution (decision D-6)
---------------------------------------
The UI offers no pulses/rev control; every installation is treated as one
reflective tape or one keyway. This is not only the common case, it is the
accurate one. At 1 ppr **every interval is exactly one shaft revolution**, so
the two dominant error sources -- encoder division error and once-per-rev speed
modulation from load zone, misalignment or a reciprocating load -- cancel inside
each interval by construction. Above 1 ppr they cancel only once a whole
revolution has been observed, and extra pulses buy nothing before that (see the
table beside MIN_EDGES). Measured: 0.0013% at 1 ppr from three edges, against
0.091% for a 60-line encoder at any window length.

`pulses_per_rev` and the divide in `estimate_rpm` are retained so the capability
can be restored without rework. A value other than 1 is **honoured and warned
about, never silently clamped**: clamping would report an integer multiple of
the true speed with nothing on screen to say so.

Not built, deliberately: inferring ppr by detecting multi-modal pulse periods.
Unequally spaced reflectors are already reported 'inconsistent' by the
interval_spread test whenever the two gaps differ by more than ~90 degrees of
shaft rotation; a near-evenly-spaced pair reads an exact integer multiple, which
is the most obvious possible error to a technician who knows the machine.

What still binds at 1 ppr is block length. Guaranteeing MIN_EDGES rising edges
regardless of start phase needs a block spanning three periods, so the slowest
measurable shaft is 180/T_block RPM, where T_block = 1/binsize:

    binsize    T_block    slowest shaft
    0.25 Hz     4.00 s        45 RPM
    0.5  Hz     2.00 s        90 RPM
    1    Hz     1.00 s       180 RPM
    2    Hz     0.50 s       360 RPM
    5    Hz     0.20 s       900 RPM
    10   Hz     0.10 s      1800 RPM

At 10 Hz bins nothing below 1800 RPM can be read at all. This is the one case
where a legitimate setup returns no reading, and it is the front end's job to
say so rather than show a blank.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

# Stdlib logger rather than rev80.get_logger, to keep this module importable
# without the package -- the same discipline peaks.py and envelope.py follow.
# The name 'rev80.tach' still inherits the app's logging config.
log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Measured constants
# --------------------------------------------------------------------------

MIN_PULSE_AMPLITUDE_MV: float = 1000.0
# Below this peak-to-peak span in a block the channel is declared to have no
# tach signal and RPM is reported as None -- never as 0.0. "I cannot see a
# tach signal" and "the shaft is stopped" are different facts and lead the
# analyst to different actions.
#
# Measured on a PicoScope 4424A (serial 12462/0067), AWG idle, 40000-sample
# block, DC coupled -- this is what a disconnected or stopped-and-flat input
# actually looks like on this hardware:
#
#     range    noise mV RMS   block span mV   margin to 1000 mV
#     +/-1 V       0.372           2.93            342x
#     +/-2 V       0.514           3.90            256x
#     +/-5 V       0.870           8.35            120x
#     +/-10 V      3.607          28.34             35x
#     +/-20 V      5.091          42.51             23.5x
#
# 1000 mV clears the worst measured span by 23.5x and still sits a factor of
# two below the >= 2 V swing of any real logic-level tach. Without this gate
# an adaptive threshold on pure noise returns ~9100 edges/block -- 547752 RPM.
#
# A span/MAD ratio test was evaluated and rejected: noise sits at ~12.5 and a
# 50%-duty pulse train with 80 mV noise sits at 9.3, i.e. below the noise. The
# ratio test fails on exactly the signal it has to accept.

HYSTERESIS_FRAC: float = 0.10
# Schmitt trigger separation, as a fraction of the block's own span. Wide
# enough to reject noise riding on the switching point, narrow enough that the
# rising threshold stays well inside the pulse.

INTERVAL_SPREAD_MAX: float = 0.25
# max|interval - median interval| / median interval, above which the reading
# is flagged 'inconsistent' -- one miscounted edge, i.e. a sensor problem.
# Measured (1800 RPM, 1.0 s block, 200 reps):
#
#     clean                  p50 0.001   p99 0.001
#     0.5% cycle jitter      p50 0.016   p99 0.025
#     2%   cycle jitter      p50 0.064   p99 0.096   <- worst legitimate case
#     one dropped edge       p50 1.000
#     one spurious edge      p50 0.998
#
# 0.25 sits 2.6x above the worst legitimate shaft jitter and 4x below a single
# miscounted edge, which is the only failure it is trying to name.

SPEED_DRIFT_MAX_PCT: float = 1.0
# Within-block shaft-speed change above which the frame is flagged 'unsteady'.
# Bearing analysis is performed at steady state; a smeared spectrum should be
# rejected, not corrected -- which is why this exists instead of an
# order-resampling path. Measured, bearing tone at 5.43x, 1.0 s block:
#
#     drift over block   peak height   smear @0.25 Hz bins
#        0.1 %             100.6 %          0 bins
#        0.5 %              94.4 %          4 bins
#        1.0 %              93.8 %          9 bins   <- threshold
#        2.0 %              82.6 %         18 bins
#        5.0 %              69.6 %         46 bins
#
# 1.0% keeps peak-height error under ~6% and smear under ~10 bins. A mains-fed
# motor at steady load sits below 0.1%; this fires on VFD ramps and load steps,
# which is exactly the population whose spectra should not be trusted.
#
# NOTE: the only constant in this module still set from simulation rather than
# from the bench. It wants a load step on a real machine to confirm.

MIN_EDGES: int = 3
# Two intervals is the minimum from which a median and a spread both mean
# something -- and at 1 pulse/rev, which is the only value the UI can produce
# (see the module docstring on D-6), three edges is exactly **two whole shaft
# revolutions**. That is why there is no separate minimum-revolutions gate:
# MIN_EDGES already is one.
#
# The distinction matters only above 1 ppr, where a pulse is a fraction of a
# revolution and the two dominant error sources -- encoder division error and
# once-per-rev speed modulation -- do not cancel until a whole revolution has
# been observed. Measured, 60-line encoder, +-0.05 deg division error, 0.5%
# once-per-rev modulation, 40 random start phases:
#
#     revolutions   pulses   mean err   worst err
#        0.05          3      0.580%     1.898%
#        0.25         15      0.344%     0.869%
#        0.50         30      0.260%     0.704%
#        1.00         60      0.091%     0.383%
#        2.00        120      0.091%     0.383%
#       20.0        1200      0.091%     0.383%
#
# Flat from one revolution onward: more pulses buy nothing. The same test at
# 1 ppr gives 0.0013% from three edges -- 70x better than 60 ppr reaches at any
# window length -- because every interval is itself one full revolution, so the
# cancellation is by construction rather than by averaging.

_MIN_EDGES_FOR_DRIFT: int = 5
# Drift compares the median interval of each half of the block, so it needs
# two intervals per half. Below this, drift is reported as 0.0 -- unmeasurable,
# not zero.

QUALITY_OK = 'ok'
QUALITY_NO_SIGNAL = 'no_signal'
QUALITY_TOO_FEW_EDGES = 'too_few_edges'
QUALITY_INCONSISTENT = 'inconsistent'
QUALITY_UNSTEADY = 'unsteady'

POLARITIES = ('rising', 'falling')
THRESHOLD_MODES = ('adaptive', 'fixed')


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TachSettings:
    """Per-channel tachometer calibration.

    Persisted under `channels/{ch}/tach` in the device YAML and in
    `/metadata/channels/{ch}` in HDF5. Everything that changes the reported
    number lives here, so a stored file plus these settings reproduces the
    reading.
    """

    pulses_per_rev: int = 1
    polarity: str = 'rising'
    threshold_mode: str = 'adaptive'
    threshold_mv: float = 2500.0          # used only when mode == 'fixed'
    min_amplitude_mv: float = MIN_PULSE_AMPLITUDE_MV
    hysteresis_frac: float = HYSTERESIS_FRAC

    def to_dict(self) -> dict:
        return {
            'pulses_per_rev':   self.pulses_per_rev,
            'polarity':         self.polarity,
            'threshold_mode':   self.threshold_mode,
            'threshold_mv':     self.threshold_mv,
            'min_amplitude_mv': self.min_amplitude_mv,
            'hysteresis_frac':  self.hysteresis_frac,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'TachSettings':
        """Build from a YAML/HDF5 mapping, coercing types and filling defaults.

        Tolerant by construction: a missing key falls back to the default and a
        string from YAML is coerced. Raising KeyError here is how the sensor
        library was once silently erased (audit X-01).
        """
        def _str(key, default, allowed):
            v = str(d.get(key, default) or default)
            return v if v in allowed else default

        ppr = max(1, int(d.get('pulses_per_rev', 1) or 1))
        if ppr != 1:
            # Honoured, not clamped. Clamping a hand-edited ppr=6 to 1 would
            # report six times the true speed with nothing on screen saying so,
            # which is worse than the unsupported configuration itself.
            log.warning(
                'pulses_per_rev=%d is an unsupported configuration: the UI only '
                'produces 1 pulse/rev, and accuracy above 1 ppr degrades until a '
                'whole revolution has been observed (0.091%% vs 0.0013%%). The '
                'value is being honoured, not clamped.', ppr)

        return cls(
            pulses_per_rev=ppr,
            polarity=_str('polarity', 'rising', POLARITIES),
            threshold_mode=_str('threshold_mode', 'adaptive', THRESHOLD_MODES),
            threshold_mv=float(d.get('threshold_mv', 2500.0)),
            min_amplitude_mv=float(
                d.get('min_amplitude_mv', MIN_PULSE_AMPLITUDE_MV)),
            hysteresis_frac=float(d.get('hysteresis_frac', HYSTERESIS_FRAC)),
        )


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TachResult:
    """One frame's shaft-speed reading.

    Parallel to ChannelResult, but deliberately not one: a tachometer channel
    has no spectrum, no overall, no engineering unit and no crest factor, and
    every consumer that assumes those exist must branch on type rather than
    receive a plausible zero.

    `rpm` is None whenever there is no usable reading. It is never 0.0.
    """

    channel: int
    rpm: float | None
    quality: str
    n_edges: int
    span_mv: float
    interval_spread: float
    speed_drift_pct: float
    pulses_per_rev: int
    samplerate: float
    rel_time: float
    edge_times_s: np.ndarray = field(repr=False)
    # Width of each *complete* pulse in the block -- one whose opening and
    # closing edge both fall inside it. A pulse truncated by the block boundary
    # contributes nothing, because counting its remainder would drag the duty
    # down by an amount that depends only on where the block happened to start.
    pulse_widths_s: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64), repr=False)
    # Mean pulse width as a fraction of the shaft period, 0.0 when no complete
    # pulse was seen. The reflector subtends this fraction of a revolution, so
    # with its physical arc length L the shaft circumference is L/duty and the
    # surface velocity is f*L/duty -- the tape doubles as a diameter
    # measurement (R46). Measures the *active* state, so under 'falling'
    # polarity it is the width of the notch, which is what a keyphasor's key
    # actually subtends.
    duty_cycle: float = 0.0

    @property
    def shaft_hz(self) -> float | None:
        """Shaft rate in Hz, or None when there is no reading."""
        return None if self.rpm is None else self.rpm / 60.0

    @property
    def is_usable(self) -> bool:
        """True when the reading may be relied on for analysis.

        'inconsistent' and 'unsteady' both still carry an rpm -- the median
        survives a miscounted edge, and an accelerating shaft still has a mean
        rate -- but neither should feed a trend, a baseline or an alarm.
        """
        return self.quality == QUALITY_OK


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def detect_pulses(x_mv: np.ndarray,
                  settings: 'TachSettings | None' = None
                  ) -> 'tuple[np.ndarray, np.ndarray]':
    """Return (opening_edges, closing_edges) as fractional sample indices.

    Opening edges are what time the shaft; closing edges exist only to measure
    pulse width, and therefore duty cycle. Both are found from the same Schmitt
    state, so they cannot disagree about where the signal was high.
    """
    rise, fall, _ = _schmitt(x_mv, settings)
    return rise, fall


def detect_edges(x_mv: np.ndarray,
                 settings: 'TachSettings | None' = None) -> np.ndarray:
    """Return sub-sample edge positions, in fractional sample indices.

    Vectorised Schmitt trigger. `samplerate` is deliberately not a parameter:
    this returns indices, and converting them to time is `estimate_rpm`'s job,
    which takes the rate from the sample rather than from a module constant.

    The vectorised form is not merely faster than the obvious loop (measured
    0.090 ms vs 6.1 ms on a 1.0 s block) but more correct: it requires an
    actual crossing, where the loop reports a phantom edge at sample 1 whenever
    a block happens to begin part-way through a pulse.
    """
    return _schmitt(x_mv, settings)[0]


def _schmitt(x_mv: np.ndarray,
             settings: 'TachSettings | None' = None
             ) -> 'tuple[np.ndarray, np.ndarray, float]':
    """Shared Schmitt pass: (opening edges, closing edges, span)."""
    _empty = np.empty(0, dtype=np.float64)
    s = settings or TachSettings()
    x = np.asarray(x_mv, dtype=np.float64)
    if x.size < 2:
        return _empty, _empty, 0.0

    # Polarity is applied here, exactly once, by inverting the signal. Every
    # threshold below is then a rising-edge threshold.
    if s.polarity == 'falling':
        x = -x

    span = float(x.max() - x.min())
    if span < s.min_amplitude_mv:
        return _empty, _empty, span

    if s.threshold_mode == 'fixed':
        mid = float(s.threshold_mv) if s.polarity != 'falling' else -float(s.threshold_mv)
    else:
        mid = (float(x.max()) + float(x.min())) / 2.0
    half = s.hysteresis_frac * span / 2.0
    hi, lo = mid + half, mid - half

    # Three-state Schmitt: +1 above the upper threshold, -1 below the lower,
    # 0 in the band. Forward-filling the band from the last decided state is
    # what gives the hysteresis its memory.
    state = np.zeros(x.size, dtype=np.int8)
    state[x > hi] = 1
    state[x < lo] = -1
    decided = state != 0
    if not decided.any():
        return _empty, _empty, span
    src = np.maximum.accumulate(np.where(decided, np.arange(x.size), 0))
    filled = state[src]
    filled[:int(np.argmax(decided))] = 0     # before the first decided sample

    # An edge is a low->high state transition. A block that opens already high
    # has no preceding low state and so contributes no edge, which is correct:
    # its rising edge happened in the previous block.
    k = np.flatnonzero((filled[1:] == 1) & (filled[:-1] == -1)) + 1
    # Closing edges: the mirror transition, found from the same state array so
    # the two can never disagree about where the signal was high.
    kf = np.flatnonzero((filled[1:] == -1) & (filled[:-1] == 1)) + 1
    if k.size == 0:
        return _empty, _interp(x, kf, lo), span

    # Sub-sample interpolation of the `hi` crossing between k-1 and k. One line
    # of arithmetic, worth 2-9x accuracy at every pulses_per_rev above 1, and
    # it turns a 60-line encoder at 600 RPM from 0.79% error into 0.09%.
    return _interp(x, k, hi), _interp(x, kf, lo), span


def _interp(x: np.ndarray, k: np.ndarray, level: float) -> np.ndarray:
    """Sub-sample position of each threshold crossing at index k."""
    if k.size == 0:
        return np.empty(0, dtype=np.float64)
    y0, y1 = x[k - 1], x[k]
    denom = y1 - y0
    frac = np.where(denom != 0, (level - y0) / np.where(denom != 0, denom, 1.0), 0.0)
    return (k - 1) + np.clip(frac, 0.0, 1.0)


# --------------------------------------------------------------------------
# Estimation
# --------------------------------------------------------------------------

def _interval_stats(intervals: np.ndarray) -> tuple[float, float, float]:
    """Return (median interval, spread, signed drift %) for one block.

    Two statistics, because they name two different failures and one number
    cannot separate them: a miscounted edge is a single outlier, while a speed
    ramp is a monotonic trend that leaves every interval slightly different
    from its neighbour.
    """
    med = float(np.median(intervals))
    if med <= 0:
        return 0.0, 0.0, 0.0
    spread = float(np.max(np.abs(intervals - med)) / med)

    drift = 0.0
    if intervals.size + 1 >= _MIN_EDGES_FOR_DRIFT:
        half = intervals.size // 2
        first = float(np.median(intervals[:half]))
        second = float(np.median(intervals[half:]))
        if second > 0:
            # Intervals shrinking across the block means the shaft sped up, so
            # a positive drift reads as "accelerating".
            drift = 100.0 * (first / second - 1.0)
    return med, spread, drift


def pulse_widths(rise: np.ndarray, fall: np.ndarray,
                 samplerate: float) -> np.ndarray:
    """Widths, in seconds, of pulses whose opening AND closing edge are present.

    A pulse straddling either block boundary is dropped rather than truncated:
    its remainder is a function of where the block happened to start, so
    including it biases duty by an amount that has nothing to do with the
    reflector.
    """
    if rise.size == 0 or fall.size == 0 or samplerate <= 0:
        return np.empty(0, dtype=np.float64)
    # For each opening edge, the first closing edge after it.
    idx = np.searchsorted(fall, rise, side='right')
    ok = idx < fall.size
    return (fall[idx[ok]] - rise[ok]) / float(samplerate)


def estimate_rpm(edge_idx: np.ndarray,
                 samplerate: float,
                 ch: int = 0,
                 rel_time: float = 0.0,
                 settings: 'TachSettings | None' = None,
                 span_mv: float = 0.0,
                 widths_s: 'np.ndarray | None' = None) -> TachResult:
    """Turn edge positions into a shaft speed.

    The estimator is the **median of intervals**, not first-to-last. Measured
    at 1800 RPM over 200 repetitions:

        case                    first-to-last      median-of-intervals
        clean                   -0.02 +/- 0.00     -0.15 +/- 0.00
        0.5% cycle jitter       -0.01 +/- 0.43     -0.05 +/- 1.78
        2%   cycle jitter       +0.04 +/- 1.74     -0.62 +/- 7.42
        one edge dropped       -62.09              -0.15
        one spurious edge      +62.05              -0.15
        three edges dropped   -179.39 +/- 19.42    -0.15

    First-to-last is tighter under torsional jitter and catastrophic under a
    single miscount -- a 3.4% error, which reads as a speed change large enough
    to invalidate everything downstream. Robustness to miscounting is worth
    more than tightness under jitter, because jitter is visible in
    `interval_spread` and a miscount is not.
    """
    s = settings or TachSettings()
    edges = np.asarray(edge_idx, dtype=np.float64)
    fs = float(samplerate)
    edge_times = edges / fs if fs > 0 else np.empty(0, dtype=np.float64)

    widths = (np.empty(0, dtype=np.float64) if widths_s is None
              else np.asarray(widths_s, dtype=np.float64))

    def _result(rpm, quality, spread=0.0, drift=0.0, duty=0.0):
        return TachResult(
            channel=ch, rpm=rpm, quality=quality, n_edges=int(edges.size),
            span_mv=float(span_mv), interval_spread=float(spread),
            speed_drift_pct=float(drift), pulses_per_rev=s.pulses_per_rev,
            samplerate=fs, rel_time=float(rel_time), edge_times_s=edge_times,
            pulse_widths_s=widths, duty_cycle=float(duty),
        )

    # Note this reports 'too_few_edges' and not 'no_signal' even for zero
    # edges: whether there is a signal at all is a question about the block's
    # span, which only tach_result has seen. A healthy 2 V pulse train from a
    # shaft too slow to put MIN_EDGES pulses in one block is not a dead cable,
    # and telling the operator otherwise sends them to the wrong place.
    if edges.size < MIN_EDGES or fs <= 0:
        return _result(None, QUALITY_TOO_FEW_EDGES)

    med, spread, drift = _interval_stats(np.diff(edges) / fs)
    if med <= 0:
        return _result(None, QUALITY_TOO_FEW_EDGES)

    # Duty is the mean complete-pulse width over the pulse period. The period
    # here is the *pulse* period (before the pulses_per_rev divide), because a
    # reflector subtends a fraction of the interval between pulses, not of a
    # revolution, whenever there is more than one per turn.
    duty = float(np.mean(widths) / med) if widths.size else 0.0

    # pulses_per_rev divides here and nowhere else in the module.
    rpm = 60.0 / med / s.pulses_per_rev

    # Drift is computed from per-half medians and so is robust to a single
    # outlier; spread is not. When drift fires, it explains the spread, so it
    # wins -- the machine is changing speed rather than the sensor miscounting.
    if abs(drift) > SPEED_DRIFT_MAX_PCT:
        return _result(rpm, QUALITY_UNSTEADY, spread, drift, duty)
    if spread > INTERVAL_SPREAD_MAX:
        return _result(rpm, QUALITY_INCONSISTENT, spread, drift, duty)
    return _result(rpm, QUALITY_OK, spread, drift, duty)


def tach_result(x_mv: np.ndarray,
                samplerate: float,
                ch: int = 0,
                rel_time: float = 0.0,
                settings: 'TachSettings | None' = None) -> TachResult:
    """Detect edges in one raw mV block and report the shaft speed.

    The whole tachometer path for one frame. `samplerate` is required and must
    come from the sample -- see the module docstring on the 4.166% trap.
    """
    s = settings or TachSettings()
    x = np.asarray(x_mv, dtype=np.float64)
    span = float(x.max() - x.min()) if x.size else 0.0

    # The span gate is answered here, before detection, so that 'no signal'
    # (nothing on the wire) stays distinguishable from 'too few edges' (a good
    # signal on a shaft too slow for this block length). Both give rpm=None,
    # but they send the operator to different places.
    if span < s.min_amplitude_mv:
        return TachResult(
            channel=ch, rpm=None, quality=QUALITY_NO_SIGNAL, n_edges=0,
            span_mv=span, interval_spread=0.0, speed_drift_pct=0.0,
            pulses_per_rev=s.pulses_per_rev, samplerate=float(samplerate),
            rel_time=float(rel_time), edge_times_s=np.empty(0, dtype=np.float64),
        )

    rise, fall = detect_pulses(x, s)
    widths = pulse_widths(rise, fall, samplerate)
    return estimate_rpm(rise, samplerate, ch=ch, rel_time=rel_time,
                        settings=s, span_mv=span, widths_s=widths)
