"""rev80.tach: edge detection and shaft speed for tachometer channels.

All levels are in mV, the unit of `VibeSample.data`. A tachometer channel
never gets a sensitivity or an engineering unit. The module imports no
dearpygui, h5py or `DataCollector`. Call `tach_result` once for each block,
with the achieved rate of the sample. `rpm` is `None`, never 0.0, when there
is no usable reading. Evidence: CONTRIBUTING.md, "E14. Tachometer".
"""

import logging
import math
from dataclasses import dataclass, field

import numpy as np

# Stdlib logger, so that this module imports no other rev80 module. The name
# 'rev80.tach' still gets the logging configuration of the application.
log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Measured constants
# --------------------------------------------------------------------------

MIN_PULSE_AMPLITUDE_MV: float = 1000.0
# A block with a smaller peak-to-peak span has no tach signal: quality
# 'no_signal', rpm None. 23.5x above the largest idle-input span measured
# (42.51 mV at +/-20 V, 4424A). Evidence: CONTRIBUTING.md, "E14.5. Signal floor".

HYSTERESIS_FRAC: float = 0.10
# Schmitt trigger separation, as a fraction of the block's own span. Wide
# enough to reject noise riding on the switching point, narrow enough that the
# rising threshold stays well inside the pulse.

INTERVAL_SPREAD_MAX: float = 0.25
# Above this max|interval - median| / median the quality is 'inconsistent':
# one edge is missing or extra. 2.6x above 2 % cycle jitter, 4x below one
# wrong edge. Evidence: CONTRIBUTING.md, "E14.6. Spread and drift limits".

SPEED_DRIFT_MAX_PCT: float = 1.0
# Above this speed change inside one block the quality is 'unsteady': the
# spectrum is rejected, not order-resampled. Set from simulation only (peak
# height 93.8 % at 1.0 %); PROGRESS R63 verifies it on hardware.
# Evidence: CONTRIBUTING.md, "E14.6. Spread and drift limits".

MIN_REVS: float = 2.0
# Minimum data for a reading, in whole shaft revolutions (not edges). Above
# 1 pulse/rev, division error and once-per-rev modulation cancel only over a
# whole revolution. 2.0 gives two intervals at 1 pulse/rev, and one revolution
# in each half-block for the drift test. Evidence: CONTRIBUTING.md,
# "E14.4. One pulse per revolution and `MIN_REVS`".


def min_edges_for(pulses_per_rev: int) -> int:
    """Rising edges needed to span MIN_REVS whole revolutions.

    N intervals are N/ppr revolutions and need N+1 edges. At 1 pulse/rev
    this returns 3.
    """
    ppr = max(1, int(pulses_per_rev))
    return int(math.ceil(MIN_REVS * ppr)) + 1


def slowest_rpm_for(block_s: float, pulses_per_rev: int = 1) -> float:
    """Slowest shaft speed in RPM that a block of `block_s` seconds can read.

    Valid at any start phase: the block must hold min_edges_for(ppr) whole
    pulse periods. At 1 pulse/rev (tests/test_tach.py checks this table):

        binsize    T_block    slowest shaft
        0.25 Hz     4.00 s        45 RPM
        0.5  Hz     2.00 s        90 RPM
        1    Hz     1.00 s       180 RPM
        2    Hz     0.50 s       360 RPM
        5    Hz     0.20 s       900 RPM
        10   Hz     0.10 s      1800 RPM

    More pulses/rev lower the floor by less than 1.5x (121 RPM at 60 pulses/rev
    and 1 s). Use a longer block (a smaller binsize) to read a slower shaft.
    """
    ppr = max(1, int(pulses_per_rev))
    if block_s <= 0:
        return float('inf')
    return min_edges_for(ppr) * 60.0 / ppr / float(block_s)


MIN_SAMPLES_PER_PULSE: int = 70
# Samples per pulse period. Below this, interpolation cannot recover the edge
# position and the error goes to about 0.8 %. The front ends show a caution
# (not a gate), because only they know the rate and the speed. Evidence:
# CONTRIBUTING.md, "E14.3. Interpolation".

_MIN_EDGES_FOR_DRIFT: int = 5
# Drift compares the median interval of each half of the block, so it needs
# two intervals in each half. Below this, drift is 0.0: not measured, not zero.
# MIN_REVS = 2.0 makes each half span one revolution, so once-per-rev
# modulation does not read as drift.

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

    # One pulse per revolution is the default and the recommended configuration:
    # each interval is then one revolution, and encoder errors cancel.
    pulses_per_rev: int = 1
    polarity: str = 'rising'
    threshold_mode: str = 'adaptive'
    threshold_mv: float = 2500.0          # used only when mode == 'fixed'
    min_amplitude_mv: float = MIN_PULSE_AMPLITUDE_MV
    hysteresis_frac: float = HYSTERESIS_FRAC
    # Arc length in mm of the reflective tape or key that the sensor sees;
    # 0.0 = not measured. Surface velocity v = f*L/duty (tracked as R46 in
    # doc/PROGRESS.md). The sensor spot makes the duty too large; the operator
    # corrects for it when measuring the tape. The code does not correct it.
    reflector_size_mm: float = 0.0

    def to_dict(self) -> dict:
        return {
            'pulses_per_rev':   self.pulses_per_rev,
            'polarity':         self.polarity,
            'threshold_mode':   self.threshold_mode,
            'threshold_mv':     self.threshold_mv,
            'min_amplitude_mv': self.min_amplitude_mv,
            'hysteresis_frac':  self.hysteresis_frac,
            'reflector_size_mm': self.reflector_size_mm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'TachSettings':
        """Build from a YAML/HDF5 mapping, coercing types and filling defaults.

        Never raises on a missing key: the key gets its default. A string from
        YAML is converted. An unknown polarity or threshold mode gets the default.
        """
        def _str(key, default, allowed):
            v = str(d.get(key, default) or default)
            return v if v in allowed else default

        # A ppr above 1 loads without a warning; the front end shows the
        # MIN_SAMPLES_PER_PULSE caution. Zero, a negative or a fraction is a
        # corrupt file. The fallback to 1 changes the speed, so it is logged.
        raw_ppr = d.get('pulses_per_rev', 1)
        try:
            ppr = int(raw_ppr)
        except (TypeError, ValueError):
            ppr = 0
        if ppr < 1 or ppr != float(raw_ppr if raw_ppr is not None else 1):
            log.warning(
                'pulses_per_rev=%r is not a positive whole number; falling '
                'back to 1. The reported shaft speed changes as a result.',
                raw_ppr)
            ppr = 1

        return cls(
            pulses_per_rev=ppr,
            polarity=_str('polarity', 'rising', POLARITIES),
            threshold_mode=_str('threshold_mode', 'adaptive', THRESHOLD_MODES),
            threshold_mv=float(d.get('threshold_mv', 2500.0)),
            min_amplitude_mv=float(
                d.get('min_amplitude_mv', MIN_PULSE_AMPLITUDE_MV)),
            hysteresis_frac=float(d.get('hysteresis_frac', HYSTERESIS_FRAC)),
            reflector_size_mm=float(d.get('reflector_size_mm', 0.0)),
        )


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TachResult:
    """The shaft-speed reading of one frame, in RPM.

    Not a ChannelResult: a tachometer channel has no spectrum, overall,
    engineering unit or crest factor. Consumers branch on the type.
    `rpm` is None when there is no usable reading. It is never 0.0.
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
    # Width in seconds of each complete pulse (both edges inside the block).
    pulse_widths_s: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float64), repr=False)
    # Mean pulse width as a fraction of the pulse period; 0.0 when no complete
    # pulse was seen. It measures the active state: with 'falling' polarity,
    # the width of the notch.
    duty_cycle: float = 0.0

    @property
    def shaft_hz(self) -> float | None:
        """Shaft rate in Hz, or None when there is no reading."""
        return None if self.rpm is None else self.rpm / 60.0

    @property
    def is_usable(self) -> bool:
        """True when the quality is 'ok'.

        'inconsistent' and 'unsteady' readings have an rpm, but must not go to
        a trend, a baseline or an alarm.
        """
        return self.quality == QUALITY_OK


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def detect_pulses(x_mv: np.ndarray,
                  settings: 'TachSettings | None' = None
                  ) -> 'tuple[np.ndarray, np.ndarray]':
    """Return (opening_edges, closing_edges) as fractional sample indices.

    Opening edges time the shaft. Closing edges give the pulse width. Both come
    from one Schmitt state, so they agree on where the signal was high.
    """
    rise, fall, _ = _schmitt(x_mv, settings)
    return rise, fall


def detect_edges(x_mv: np.ndarray,
                 settings: 'TachSettings | None' = None) -> np.ndarray:
    """Return the opening edges, in fractional sample indices.

    Vectorised Schmitt trigger. An edge needs a real low-to-high crossing, so
    a block that starts during a pulse gives no edge at sample 1. The result
    is in samples; `estimate_rpm` converts it with the rate of the sample.
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

    # Sub-sample interpolation of the `hi` crossing between k-1 and k: 4x to
    # 14x less error than rounding at 70 to 1000 samples per pulse period.
    # Evidence: CONTRIBUTING.md, "E14.3. Interpolation".
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

    Spread finds one wrong edge (one outlier). Drift finds a speed ramp (a
    monotonic trend).
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

    A pulse cut by a block boundary is dropped, not shortened: its remainder
    depends on the start of the block and would bias the duty.
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
    """Turn edge positions (fractional samples) into a TachResult.

    `samplerate` is the achieved rate of the sample, in Hz. The speed is 60 /
    median interval / pulses_per_rev. The median, not first-to-last, keeps one
    wrong edge from moving the speed (0.15 RPM against 62.09 RPM at 1800 RPM).
    Fewer than min_edges_for(ppr) edges give rpm None, 'too_few_edges'.
    Evidence: CONTRIBUTING.md, "E14.7. Median estimator".
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

    # 'too_few_edges', not 'no_signal', even for zero edges: only tach_result
    # sees the span. A good signal on a slow shaft is not a broken cable.
    # Do not rename the string: every stored HDF5 tach group contains it.
    if edges.size < min_edges_for(s.pulses_per_rev) or fs <= 0:
        return _result(None, QUALITY_TOO_FEW_EDGES)

    med, spread, drift = _interval_stats(np.diff(edges) / fs)
    if med <= 0:
        return _result(None, QUALITY_TOO_FEW_EDGES)

    # Duty is the mean complete-pulse width over the pulse period (before the
    # pulses_per_rev divide). The `else` is defence only: between two rising
    # edges there is always a closing edge. Test widths.size >= n_edges - 1.
    duty = float(np.mean(widths) / med) if widths.size else 0.0

    # pulses_per_rev divides here and nowhere else in the module.
    rpm = 60.0 / med / s.pulses_per_rev

    # Drift uses per-half medians, so one outlier does not move it. When drift
    # is above its limit it also explains the spread, so 'unsteady' wins.
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

    The full tachometer path for one frame. `samplerate` must be the achieved
    rate of the sample (`VibeSample.samplerate`), not RAW_SAMPLERATE_HZ.
    Evidence: CONTRIBUTING.md, "E5. Report the achieved rate".
    """
    s = settings or TachSettings()
    x = np.asarray(x_mv, dtype=np.float64)
    span = float(x.max() - x.min()) if x.size else 0.0

    # Span gate before detection: 'no_signal' (nothing on the wire) must stay
    # different from 'too_few_edges' (a good signal, a shaft too slow for the
    # block). Both give rpm None; they send the operator to different places.
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
