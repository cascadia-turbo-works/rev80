import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import numpy as np

from vibechecker.util import UNIT_TO_SI, modality_of

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnomalyEvent:
    trigger_time: datetime    # UTC datetime of the t=0 frame (anomaly onset, not detection time)
    channel: int
    reason: str
    burst_duration_s: float
    trigger_rel_time: float = 0.0   # session rel_time of the t=0 frame


@runtime_checkable
class AnomalyHook(Protocol):
    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None': ...


class NullAnomalyHook:
    """Phase 1 stub — never fires."""
    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        return None


class RmsThresholdHook:
    """EWMA self-calibrating RMS baseline — fires when deviation exceeds threshold.

    Parameters
    ----------
    rms_threshold_pct:
        Percentage deviation from the EWMA baseline that triggers an event
        (e.g. 10 means 10 %).
    consecutive_n:
        Number of consecutive above-threshold frames required before firing.
    baseline_alpha:
        EWMA decay factor.  Higher → slower adaptation.  0.97 ≈ 33-frame
        half-life.
    min_baseline_samples:
        Warmup period; no events are raised until each channel has received
        at least this many samples.
    burst_duration_s:
        Duration placed in the returned AnomalyEvent.
    """

    def __init__(
        self,
        rms_threshold_pct: float = 10.0,
        consecutive_n: int = 3,
        baseline_alpha: float = 0.97,
        min_baseline_samples: int = 30,
        burst_duration_s: float = 60.0,
    ):
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

    def update_baseline(self, results: list) -> None:
        """Update EWMA state without checking for trigger events.

        Called during burst frames so the baseline keeps adapting while
        suppressing spurious retriggers.
        """
        for r in results:
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

    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        for r in results:
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
                    self._streak_start_time[ch] = datetime.now(timezone.utc)
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
                        trigger_time=self._streak_start_time.pop(ch, datetime.now(timezone.utc)),
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
    """EWMA self-calibrating per-bin baseline — fires when any bin deviates beyond threshold.

    Parameters
    ----------
    spectral_threshold_pct:
        Percentage deviation from the EWMA baseline that triggers (e.g. 50 means 50 %).
    consecutive_n:
        Number of consecutive above-threshold frames required before firing.
    baseline_alpha:
        EWMA decay factor per bin.  0.995 ≈ very slow adaptation (~200-frame half-life).
    min_baseline_samples:
        Warmup period; no events until each channel has at least this many frames.
    fmin, fmax:
        Frequency band limits (Hz).  None or negative value means no limit on that side.
    burst_duration_s:
        Duration placed in the returned AnomalyEvent.
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

    def update_baseline(self, results: list) -> None:
        """Update EWMA state without checking for trigger events."""
        for r in results:
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

    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        for r in results:
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
                        trigger_time=datetime.now(timezone.utc),
                        channel=ch,
                        reason=reason,
                        burst_duration_s=self._burst_duration_s,
                        trigger_rel_time=r.rel_time,
                    )
            else:
                self._consec_above[ch] = 0

        return None


class FixedThresholdHook:
    """Fires immediately when the broadband overall amplitude crosses a fixed,
    user-specified level — no baseline calibration or warmup involved.

    Either or both limits may be enabled independently:

    Parameters
    ----------
    upper_limit, upper_unit:
        If `upper_limit` is not None, fires when ``overall > upper_limit``
        (converted into the channel's reported unit).
    lower_limit, lower_unit:
        If `lower_limit` is not None, fires when ``overall < lower_limit``
        (converted into the channel's reported unit).
    burst_duration_s:
        Duration placed in the returned AnomalyEvent.

    Threshold values are entered in an arbitrary engineering unit and
    converted to ``ChannelResult.unit`` via the SI ratio in `UNIT_TO_SI`.
    Conversion is only possible between units of the same physical modality
    (e.g. velocity↔velocity). If the channel has no sensor assigned (its
    reported unit is the raw passthrough 'mV') or the modalities differ, the
    conversion is impossible — a warning is logged once per channel and that
    channel is simply skipped.
    """

    def __init__(
        self,
        upper_limit: float | None = None,
        upper_unit: str = 'mV',
        lower_limit: float | None = None,
        lower_unit: str = 'mV',
        burst_duration_s: float = 60.0,
    ):
        self._upper_limit = upper_limit
        self._upper_unit  = upper_unit
        self._lower_limit = lower_limit
        self._lower_unit  = lower_unit
        self._burst_duration_s = burst_duration_s

        # Channels for which a unit-conversion warning has already been logged
        self._warned_channels: set[int] = set()

    def _convert(self, value: float, from_unit: str, to_unit: str, ch: int) -> float | None:
        """Convert `value` from `from_unit` into `to_unit`; None if impossible."""
        if from_unit == to_unit:
            return value
        if from_unit == 'mV' or to_unit == 'mV':
            if ch not in self._warned_channels:
                log.warning(
                    "Fixed threshold ch%d: channel has no sensor/EU configured "
                    "(reported unit %r) — cannot convert %r threshold; "
                    "fixed-level trigger disabled for this channel",
                    ch, to_unit, from_unit,
                )
                self._warned_channels.add(ch)
            return None
        if modality_of(from_unit) != modality_of(to_unit):
            if ch not in self._warned_channels:
                log.warning(
                    "Fixed threshold ch%d: cannot convert %r threshold to "
                    "channel unit %r — incompatible physical quantities; "
                    "fixed-level trigger disabled for this channel",
                    ch, from_unit, to_unit,
                )
                self._warned_channels.add(ch)
            return None
        return value * UNIT_TO_SI[from_unit] / UNIT_TO_SI[to_unit]

    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        for r in results:
            ch = r.channel
            current = r.overall

            if self._upper_limit is not None:
                limit = self._convert(self._upper_limit, self._upper_unit, r.unit, ch)
                if limit is not None and current > limit:
                    return AnomalyEvent(
                        trigger_time=datetime.now(timezone.utc),
                        channel=ch,
                        reason=(
                            f"Overall {current:.4g} {r.unit} > upper limit "
                            f"{self._upper_limit:.4g} {self._upper_unit} on ch{ch}"
                        ),
                        burst_duration_s=self._burst_duration_s,
                        trigger_rel_time=r.rel_time,
                    )

            if self._lower_limit is not None:
                limit = self._convert(self._lower_limit, self._lower_unit, r.unit, ch)
                if limit is not None and current < limit:
                    return AnomalyEvent(
                        trigger_time=datetime.now(timezone.utc),
                        channel=ch,
                        reason=(
                            f"Overall {current:.4g} {r.unit} < lower limit "
                            f"{self._lower_limit:.4g} {self._lower_unit} on ch{ch}"
                        ),
                        burst_duration_s=self._burst_duration_s,
                        trigger_rel_time=r.rel_time,
                    )

        return None


class CompositeAnomalyHook:
    """Tries each hook in order and returns the first AnomalyEvent that fires.

    Parameters
    ----------
    hooks:
        Ordered list of hook objects that implement ``on_results()``.
    """

    def __init__(self, hooks: list):
        self._hooks = list(hooks)

    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        for hook in self._hooks:
            event = hook.on_results(results, frame_cache)
            if event is not None:
                return event
        return None

    def update_baseline(self, results: list) -> None:
        """Propagate update_baseline() to every child hook that supports it."""
        for hook in self._hooks:
            if hasattr(hook, 'update_baseline'):
                hook.update_baseline(results)

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
