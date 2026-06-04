from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class AnomalyEvent:
    trigger_time: datetime   # UTC datetime of the triggering frame
    channel: int
    reason: str
    burst_duration_s: float


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

    def reset_baseline(self) -> None:
        """Clear all per-channel state so the hook re-calibrates from scratch."""
        self._baseline.clear()
        self._n_samples.clear()
        self._consec_above.clear()

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
                self._consec_above[ch] += 1
                if self._consec_above[ch] >= self._consecutive_n:
                    # Reset counter before returning so the next run starts fresh
                    self._consec_above[ch] = 0
                    reason = (
                        f"RMS deviation {deviation * 100:.1f}% > "
                        f"{self._threshold_frac * 100:.1f}% threshold on ch{ch}"
                    )
                    return AnomalyEvent(
                        trigger_time=datetime.now(timezone.utc),
                        channel=ch,
                        reason=reason,
                        burst_duration_s=self._burst_duration_s,
                    )
            else:
                # Below threshold — reset consecutive counter
                self._consec_above[ch] = 0

        return None


class SpectralThresholdHook:
    """Compares current PSD against a stored reference PSD.

    Triggers when any bin in the configured frequency band exceeds the
    reference by ``spectral_threshold_db`` dB for ``consecutive_n`` frames.

    Parameters
    ----------
    spectral_threshold_db:
        dB excess over reference that constitutes an anomaly (e.g. 3.0 dB).
    consecutive_n:
        Number of consecutive exceeding frames before an event is raised.
    fmin, fmax:
        Optional frequency band limits (Hz).  Bins outside [fmin, fmax]
        are ignored.  ``None`` means no limit on that side.
    burst_duration_s:
        Duration placed in the returned AnomalyEvent.
    """

    def __init__(
        self,
        spectral_threshold_db: float = 3.0,
        consecutive_n: int = 3,
        fmin: float | None = None,
        fmax: float | None = None,
        burst_duration_s: float = 60.0,
    ):
        self._threshold_db = spectral_threshold_db
        self._consecutive_n = consecutive_n
        self._fmin = fmin
        self._fmax = fmax
        self._burst_duration_s = burst_duration_s

        # Per-channel reference PSD
        self._ref_freq: dict[int, np.ndarray] = {}
        self._ref_spectrum: dict[int, np.ndarray] = {}
        self._consec_above: dict[int, int] = {}

    def has_baseline(self, ch: int) -> bool:
        """Return True if a reference PSD has been stored for channel ``ch``."""
        return ch in self._ref_spectrum

    def set_baseline(self, results: list) -> None:
        """Snapshot freq and spectrum from each ChannelResult as the reference PSD.

        Resets consecutive counters for all channels in ``results``.
        """
        for r in results:
            ch = r.channel
            self._ref_freq[ch] = np.array(r.freq, dtype=float)
            self._ref_spectrum[ch] = np.array(r.spectrum, dtype=float)
            self._consec_above[ch] = 0

    def reset_baseline(self) -> None:
        """Clear all reference PSDs and consecutive counters."""
        self._ref_freq.clear()
        self._ref_spectrum.clear()
        self._consec_above.clear()

    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        for r in results:
            ch = r.channel

            # Skip channels with no reference
            if ch not in self._ref_spectrum:
                continue

            ref_spectrum = self._ref_spectrum[ch]
            cur_spectrum = np.array(r.spectrum, dtype=float)

            # Skip if array lengths differ (settings may have changed)
            if len(cur_spectrum) != len(ref_spectrum):
                continue

            # Build frequency-band mask
            freq = np.array(r.freq, dtype=float)
            mask = np.ones(len(freq), dtype=bool)
            if self._fmin is not None:
                mask &= freq >= self._fmin
            if self._fmax is not None:
                mask &= freq <= self._fmax

            if not np.any(mask):
                continue

            # Compute dB excess over reference; guard against divide-by-zero
            with np.errstate(divide='ignore', invalid='ignore'):
                db_excess = 10.0 * np.log10(
                    cur_spectrum[mask] / np.maximum(ref_spectrum[mask], 1e-12)
                )
                db_excess = np.nan_to_num(db_excess, nan=0.0, posinf=0.0, neginf=0.0)

            if np.any(db_excess > self._threshold_db):
                self._consec_above.setdefault(ch, 0)
                self._consec_above[ch] += 1
                if self._consec_above[ch] >= self._consecutive_n:
                    self._consec_above[ch] = 0
                    max_excess = float(np.max(db_excess))
                    reason = (
                        f"Spectral excess {max_excess:.1f} dB > "
                        f"{self._threshold_db:.1f} dB threshold on ch{ch}"
                    )
                    return AnomalyEvent(
                        trigger_time=datetime.now(timezone.utc),
                        channel=ch,
                        reason=reason,
                        burst_duration_s=self._burst_duration_s,
                    )
            else:
                self._consec_above[ch] = 0

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

    def reset_baseline(self) -> None:
        """Propagate reset_baseline() to every child hook that supports it."""
        for hook in self._hooks:
            if hasattr(hook, 'reset_baseline'):
                hook.reset_baseline()
