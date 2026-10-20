import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

import numpy as np

log = logging.getLogger(__name__)


def ewma_alpha_from_time(ewma_time_s: float, dt: float) -> float:
    """Convert EWMA time constant τ (s) to alpha given block period dt (s).

    alpha = exp(-dt / τ).  At τ=30s, dt=1s → alpha≈0.967.
    """
    if ewma_time_s <= 0 or dt <= 0:
        raise ValueError(f"ewma_time_s and dt must be positive (got {ewma_time_s}, {dt})")
    return math.exp(-dt / ewma_time_s)


def frames_for_seconds(seconds: float, period: float) -> int:
    """Consecutive frames for a sustained time: round(seconds / period) + 1.

    0 s is one frame. A period of 0 or less (no frame period known) is one
    frame. Both front ends use it for `rms_s` and `fixed_s`.
    """
    if period <= 0:
        return 1
    return max(1, round(seconds / period) + 1)


@dataclass(frozen=True)
class AnomalyEvent:
    """An anomaly that a hook reports.

    `trigger_time` is the local time of the onset: the first frame of the
    streak, which can be earlier than the frame that confirms the anomaly.
    The controller stores it as `onset_timestamp`. The burst t = 0 is the
    confirming frame, stored at `n_pretrigger`; the controller sets its time.
    `trigger_rel_time` is the onset on the collector clock. The controller
    does not use it.
    """
    trigger_time: datetime
    channel: int
    reason: str
    burst_duration_s: float
    trigger_rel_time: float = 0.0


def valid_results(results: list) -> list:
    """Return the results that a hook may evaluate or learn from.

    Drops results with `overflow` or `degraded` set, or with `speed_ok` False.
    The frame is still shown and stored, but it must not raise an alarm or
    move a baseline. This is the only place the speed gate is applied: do not
    add it to `_build_anomaly_hook`, which is still copied in `gui.py` and
    `headless.py`. Evidence: CONTRIBUTING.md, "E20. Speed gate".
    """
    return [r for r in results
            if not (getattr(r, 'overflow', False) or getattr(r, 'degraded', False))
            and getattr(r, 'speed_ok', True)]


@runtime_checkable
class ResultViews(Protocol):
    """The views of one frame that a hook can ask for.

    `record`: the record results (each channel's record unit and mode, never
    averaged); the capture writer stores these. `results(unit, mode)`: the
    results in `unit` and `mode`; empty or None means the record unit or
    mode. A channel that cannot reach `unit` is absent. The collector
    supplies `collector.FrameViews`; this module imports no collector.
    """
    @property
    def record(self) -> list: ...

    def results(self, unit: 'str | None', mode: 'str | None') -> list: ...


class RecordViews:
    """`ResultViews` over a fixed list of results (tests, simple callers).

    A view in another unit or mode is the subset already in it: these
    results cannot be converted.
    """
    def __init__(self, results: list):
        self._record = list(results)

    @property
    def record(self) -> list:
        return self._record

    def results(self, unit: 'str | None', mode: 'str | None') -> list:
        if not unit and not mode:
            return self._record
        return [r for r in self._record
                if (not unit or getattr(r, 'unit', None) == unit)
                and (not mode or getattr(r, 'amplitude_mode', '') == mode)]


def as_views(results_or_views) -> 'ResultViews':
    """A `ResultViews` for a list of results, or the views unchanged."""
    if isinstance(results_or_views, (list, tuple)):
        return RecordViews(list(results_or_views))
    return results_or_views


@runtime_checkable
class AnomalyHook(Protocol):
    def on_results(self, views: 'ResultViews | list', frame_cache) -> 'AnomalyEvent | None': ...


class NullAnomalyHook:
    """A hook that never fires. Use it to record with no anomaly detection."""
    def on_results(self, views, frame_cache) -> 'AnomalyEvent | None':
        return None


class RmsThresholdHook:
    """Fire when a channel's overall deviates from its EWMA baseline.

    Parameters
    ----------
    rms_threshold_pct: deviation from the baseline that fires, in % (50 = 50 %).
        A 3.2 % shaft-speed change alone moves the overall 10 %. Evidence:
        CONTRIBUTING.md, "E16. Anomaly thresholds".
    consecutive_n: consecutive frames above the threshold before the event fires.
    baseline_alpha: EWMA decay per frame. 0.97 is a time constant of about
        33 frames (half-life about 23 frames).
    min_baseline_samples: frames per channel before an event can fire.
    burst_duration_s: value put into the returned AnomalyEvent, in s.
    unit, amplitude_mode: the view the hook compares; empty is each channel's
        record unit and mode. The baseline is kept in this view.
    """

    def __init__(
        self,
        rms_threshold_pct: float = 50.0,
        consecutive_n: int = 3,
        baseline_alpha: float = 0.97,
        min_baseline_samples: int = 30,
        burst_duration_s: float = 60.0,
        unit: str = '',
        amplitude_mode: str = '',
    ):
        self._unit = unit or ''
        self._mode = amplitude_mode or ''
        self._threshold_frac = rms_threshold_pct / 100.0
        self._consecutive_n = consecutive_n
        self._alpha = baseline_alpha
        self._min_samples = min_baseline_samples
        self._burst_duration_s = burst_duration_s

        # Per-channel state
        self._baseline: dict[int, float] = {}
        self._n_samples: dict[int, int] = {}
        self._consec_above: dict[int, int] = {}
        # t=0 frame of the current above-threshold streak (the frame that
        # first crossed the deviation threshold, even though the event
        # doesn't fire until `consecutive_n` frames later)
        self._streak_start_time: dict[int, datetime] = {}
        self._streak_start_rel:  dict[int, float] = {}

    def reset_baseline(self) -> None:
        """Clear all per-channel state so the hook re-calibrates from scratch."""
        self._baseline.clear()
        self._n_samples.clear()
        self._consec_above.clear()
        self._streak_start_time.clear()
        self._streak_start_rel.clear()

    def baseline_snapshot(self) -> dict[int, float]:
        """Return a copy of the current per-channel EWMA baseline values."""
        return dict(self._baseline)

    def _view(self, views) -> list:
        return valid_results(as_views(views).results(self._unit, self._mode))

    def update_baseline(self, views) -> None:
        """Update EWMA state without checking for trigger events.

        Called during burst frames so the baseline keeps adapting while
        suppressing spurious retriggers. A burst frame ends every streak, as
        in the other hooks: after the burst, the count starts again.
        """
        self._consec_above = {ch: 0 for ch in self._consec_above}
        self._streak_start_time.clear()
        self._streak_start_rel.clear()
        for r in self._view(views):
            ch = r.channel
            current = r.overall
            if ch not in self._n_samples:
                self._n_samples[ch] = 0
                self._baseline[ch] = current
                self._consec_above[ch] = 0
            n = self._n_samples[ch]
            if n == 0:
                self._baseline[ch] = current
            else:
                self._baseline[ch] = (
                    self._alpha * self._baseline[ch]
                    + (1.0 - self._alpha) * current
                )
            self._n_samples[ch] = n + 1

    def on_results(self, views, frame_cache) -> 'AnomalyEvent | None':
        for r in self._view(views):
            ch = r.channel
            current = r.overall

            # Initialise per-channel counters on first sight
            if ch not in self._n_samples:
                self._n_samples[ch] = 0
                self._baseline[ch] = current
                self._consec_above[ch] = 0

            n = self._n_samples[ch]

            # Update EWMA baseline
            if n == 0:
                self._baseline[ch] = current
            else:
                self._baseline[ch] = (
                    self._alpha * self._baseline[ch]
                    + (1.0 - self._alpha) * current
                )
            self._n_samples[ch] = n + 1

            # Warmup period — no triggers yet
            if self._n_samples[ch] < self._min_samples:
                self._consec_above[ch] = 0
                continue

            baseline = self._baseline[ch]
            if baseline <= 0.0:
                self._consec_above[ch] = 0
                continue

            deviation = abs(current - baseline) / baseline

            if deviation > self._threshold_frac:
                if self._consec_above[ch] == 0:
                    # First above-threshold frame in this streak — flag it as
                    # the t=0 anomaly onset, even though the event won't fire
                    # until `consecutive_n` frames later.
                    self._streak_start_time[ch] = datetime.now()
                    self._streak_start_rel[ch]  = r.rel_time
                self._consec_above[ch] += 1
                log.debug(
                    "RMS ping ch%d: %.4g %s  baseline=%.4g  dev=%.1f%%  [%d/%d]",
                    ch, current, getattr(r, 'unit', ''),
                    baseline, deviation * 100.0,
                    self._consec_above[ch], self._consecutive_n,
                )
                if self._consec_above[ch] >= self._consecutive_n:
                    # Reset counter before returning so the next run starts fresh
                    self._consec_above[ch] = 0
                    reason = (
                        f"RMS deviation {deviation * 100:.1f}% > "
                        f"{self._threshold_frac * 100:.1f}% threshold on ch{ch}"
                    )
                    return AnomalyEvent(
                        trigger_time=self._streak_start_time.pop(ch, datetime.now()),
                        channel=ch,
                        reason=reason,
                        burst_duration_s=self._burst_duration_s,
                        trigger_rel_time=self._streak_start_rel.pop(ch, r.rel_time),
                    )
            else:
                # Below threshold — reset consecutive counter and streak marker
                self._consec_above[ch] = 0
                self._streak_start_time.pop(ch, None)
                self._streak_start_rel.pop(ch, None)

        return None


class SpectralThresholdHook:
    """Fire when any spectrum line in the band deviates from its EWMA baseline.

    Not offered in the GUI, because it fires on healthy one-segment Welch
    spectra (tracked as R39 in doc/PROGRESS.md; evidence: CONTRIBUTING.md,
    "E16. Anomaly thresholds"). Headless still accepts it. Units: threshold
    in %, counts in frames, fmin and fmax in Hz (None = no limit).
    baseline_alpha is per frame: 0.995 is a time constant of about 200 frames.
    """

    def __init__(
        self,
        spectral_threshold_pct: float = 50.0,
        consecutive_n: int = 10,
        baseline_alpha: float = 0.995,
        min_baseline_samples: int = 10,
        fmin: float | None = None,
        fmax: float | None = None,
        burst_duration_s: float = 60.0,
    ):
        self._threshold_frac = spectral_threshold_pct / 100.0
        self._consecutive_n = consecutive_n
        self._alpha = baseline_alpha
        self._min_samples = min_baseline_samples
        self._fmin = fmin
        self._fmax = fmax
        self._burst_duration_s = burst_duration_s

        # Per-channel EWMA state
        self._baseline: dict[int, np.ndarray] = {}
        self._n_samples: dict[int, int] = {}
        self._consec_above: dict[int, int] = {}

    def reset_baseline(self) -> None:
        """Clear all per-channel EWMA state so the hook re-calibrates from scratch."""
        self._baseline.clear()
        self._n_samples.clear()
        self._consec_above.clear()

    def set_baseline(self, results: list) -> None:
        """Seed the EWMA baseline from a snapshot of the current spectra.

        Resets consecutive counters. Useful for the GUI 'Set Baseline' button.
        """
        for r in results:
            ch = r.channel
            self._baseline[ch] = np.array(r.spectrum, dtype=float)
            self._n_samples[ch] = self._min_samples   # skip warmup
            self._consec_above[ch] = 0

    def _freq_mask(self, freq: np.ndarray) -> np.ndarray:
        mask = np.ones(len(freq), dtype=bool)
        if self._fmin is not None:
            mask &= freq >= self._fmin
        if self._fmax is not None:
            mask &= freq <= self._fmax
        return mask

    def update_baseline(self, views) -> None:
        """Update EWMA state without checking for trigger events.

        Called during burst frames. A burst frame ends every streak.
        """
        self._consec_above = {ch: 0 for ch in self._consec_above}
        for r in valid_results(as_views(views).record):
            self._update_channel(r.channel, np.array(r.spectrum, dtype=float))

    def _update_channel(self, ch: int, spectrum: np.ndarray) -> None:
        if ch not in self._n_samples:
            self._n_samples[ch] = 0
            self._baseline[ch] = spectrum.copy()
            self._consec_above[ch] = 0
        n = self._n_samples[ch]
        if n == 0:
            self._baseline[ch] = spectrum.copy()
        else:
            self._baseline[ch] = self._alpha * self._baseline[ch] + (1.0 - self._alpha) * spectrum
        self._n_samples[ch] = n + 1

    def on_results(self, views, frame_cache) -> 'AnomalyEvent | None':
        for r in valid_results(as_views(views).record):
            ch = r.channel
            spectrum = np.array(r.spectrum, dtype=float)

            self._update_channel(ch, spectrum)

            if self._n_samples[ch] < self._min_samples:
                self._consec_above[ch] = 0
                continue

            freq = np.array(r.freq, dtype=float)
            if len(freq) != len(spectrum):
                self._consec_above[ch] = 0
                continue

            mask = self._freq_mask(freq)
            if not np.any(mask):
                self._consec_above[ch] = 0
                continue

            baseline = self._baseline[ch]
            deviation = np.abs(spectrum[mask] - baseline[mask]) / np.maximum(baseline[mask], 1e-12)

            if np.any(deviation > self._threshold_frac):
                self._consec_above.setdefault(ch, 0)
                self._consec_above[ch] += 1
                peak_idx  = int(np.argmax(deviation))
                peak_freq = float(freq[mask][peak_idx])
                max_dev   = float(deviation[peak_idx]) * 100.0
                log.debug(
                    "Spectral ping ch%d: dev=%.1f%% @ %.1f Hz  [%d/%d]",
                    ch, max_dev, peak_freq,
                    self._consec_above[ch], self._consecutive_n,
                )
                if self._consec_above[ch] >= self._consecutive_n:
                    self._consec_above[ch] = 0
                    reason = (
                        f"Spectral deviation {max_dev:.1f}% > "
                        f"{self._threshold_frac * 100:.1f}% threshold "
                        f"on ch{ch} @ {peak_freq:.1f} Hz"
                    )
                    return AnomalyEvent(
                        trigger_time=datetime.now(),
                        channel=ch,
                        reason=reason,
                        burst_duration_s=self._burst_duration_s,
                        trigger_rel_time=r.rel_time,
                    )
            else:
                self._consec_above[ch] = 0

        return None


class FixedThresholdHook:
    """Fire when a channel's overall crosses a fixed upper or lower limit.

    No baseline and no warm-up. Set `upper_limit` or `lower_limit` to None to
    disable that side. Each limit reads its own view: the overall in the
    limit's unit and mode (an empty mode is the record mode), so a velocity
    limit works on an accelerometer channel. A channel that cannot reach the
    unit (no sensor, another quantity) is skipped with one warning.

    `sustain_frames` is the number of consecutive valid frames beyond the
    limit before the hook fires; 1 fires on the first frame. A frame that
    `valid_results()` drops, a frame inside the limit, a burst frame
    (`update_baseline`) and `reset_baseline()` end the streak. The trigger
    time is the first frame of the streak.
    """

    def __init__(
        self,
        upper_limit: float | None = None,
        upper_unit: str = 'mV',
        lower_limit: float | None = None,
        lower_unit: str = 'mV',
        burst_duration_s: float = 60.0,
        upper_mode: str = '',
        lower_mode: str = '',
        sustain_frames: int = 1,
    ):
        self._upper_limit = upper_limit
        self._upper_unit  = upper_unit
        self._upper_mode  = upper_mode or ''
        self._lower_limit = lower_limit
        self._lower_unit  = lower_unit
        self._lower_mode  = lower_mode or ''
        self._burst_duration_s = burst_duration_s
        self._sustain_frames = max(1, int(sustain_frames))

        # (side, channel) pairs for which a missing view was already logged
        self._warned: set[tuple[str, int]] = set()
        # (side, channel) -> (frames beyond the limit, datetime and rel_time
        # of the first frame of the streak)
        self._streaks: dict[tuple[str, int], tuple[int, datetime, float]] = {}

    def reset_baseline(self) -> None:
        """End every streak. The hook has no baseline to reset."""
        self._streaks = {}

    def update_baseline(self, views) -> None:
        """A burst frame: end every streak, so a streak does not span a burst."""
        self._streaks = {}

    def _side_view(self, views, side: str, unit: str, mode: str) -> list:
        """The valid results of one limit's view; warns once for a missing channel."""
        view = as_views(views)
        results = view.results(unit, mode)
        present = {r.channel for r in results}
        for r in valid_results(view.record):
            if r.channel not in present and (side, r.channel) not in self._warned:
                self._warned.add((side, r.channel))
                log.warning(
                    "Fixed threshold ch%d: the channel cannot be shown in %r "
                    "(no sensor, or another quantity); the %s limit is "
                    "disabled for this channel", r.channel, unit, side)
        return valid_results(results)

    def _sides(self):
        if self._upper_limit is not None:
            yield ('upper', self._upper_unit, self._upper_mode, self._upper_limit,
                   '>', lambda value: value > self._upper_limit)
        if self._lower_limit is not None:
            yield ('lower', self._lower_unit, self._lower_mode, self._lower_limit,
                   '<', lambda value: value < self._lower_limit)

    def on_results(self, views, frame_cache) -> 'AnomalyEvent | None':
        # Only the streaks that this frame continues are kept: a channel that
        # is inside the limit or that valid_results() dropped starts again.
        streaks: dict[tuple[str, int], tuple[int, datetime, float]] = {}
        event = None
        for side, unit, mode, limit, op, beyond in self._sides():
            for r in self._side_view(views, side, unit, mode):
                if not beyond(r.overall):
                    continue
                key = (side, r.channel)
                n, t0, rel0 = self._streaks.get(key, (0, datetime.now(), r.rel_time))
                n += 1
                if n < self._sustain_frames or event is not None:
                    streaks[key] = (n, t0, rel0)
                    continue
                event = AnomalyEvent(
                    trigger_time=t0,
                    channel=r.channel,
                    reason=(
                        f"Overall {r.overall:.4g} {r.unit} {op} {side} limit "
                        f"{limit:.4g} {unit} on ch{r.channel}"
                    ),
                    burst_duration_s=self._burst_duration_s,
                    trigger_rel_time=rel0,
                )
        self._streaks = streaks
        return event


class CompositeAnomalyHook:
    """Tries each hook in order and returns the first AnomalyEvent that fires.

    Parameters
    ----------
    hooks:
        Ordered list of hook objects that implement ``on_results()``.
    """

    def __init__(self, hooks: list):
        self._hooks = list(hooks)

    def on_results(self, views, frame_cache) -> 'AnomalyEvent | None':
        # Each child applies valid_results() to the view it reads.
        views = as_views(views)
        for hook in self._hooks:
            event = hook.on_results(views, frame_cache)
            if event is not None:
                return event
        return None

    def update_baseline(self, views) -> None:
        """Propagate update_baseline() to every child hook that supports it."""
        views = as_views(views)
        for hook in self._hooks:
            if hasattr(hook, 'update_baseline'):
                hook.update_baseline(views)

    def reset_baseline(self) -> None:
        """Propagate reset_baseline() to every child hook that supports it."""
        for hook in self._hooks:
            if hasattr(hook, 'reset_baseline'):
                hook.reset_baseline()

    def baseline_snapshot(self) -> dict[int, float]:
        """Return baseline from the first child hook that exposes one."""
        for hook in self._hooks:
            if hasattr(hook, 'baseline_snapshot'):
                return hook.baseline_snapshot()
        return {}
