class IntervalGate:
    def __init__(self, interval_s: float, start_monotonic: float):
        # First deadline = start_monotonic so the first capture fires immediately on arm
        self._interval = interval_s
        self._next_deadline = start_monotonic
        self._in_burst = False
        self._burst_end = 0.0
        # Initialised here rather than only in enter_burst(): the retrigger
        # branch reads it, and while that is currently unreachable without a
        # prior enter_burst(), it was one refactor away from an AttributeError
        # inside the monitor's hot path.
        self._burst_start = start_monotonic

    def should_capture(self, now: float) -> bool:
        """Return True if a capture should be taken at this moment."""
        if self._in_burst:
            return now < self._burst_end
        return now >= self._next_deadline

    def mark_captured(self, now: float) -> None:
        """Advance deadline; snap-to-grid so drift never accumulates."""
        if self._in_burst:
            return
        self._next_deadline += self._interval
        # if we fell far behind, catch up to the next future deadline
        while self._next_deadline <= now:
            self._next_deadline += self._interval

    def enter_burst(self, duration_s: float, now: float,
                    max_burst_s: float = 600.0) -> None:
        """Enter burst mode or extend current burst (retrigger)."""
        if self._in_burst:
            # retrigger: extend but cap at max_burst_s from the ORIGINAL burst start
            self._burst_end = min(self._burst_end + duration_s, self._burst_start + max_burst_s)
        else:
            self._in_burst = True
            self._burst_start = now
            self._burst_end = now + duration_s

    def exit_burst(self, now: float) -> None:
        """Exit burst mode and schedule next interval deadline from now."""
        self._in_burst = False
        self._next_deadline = now + self._interval

    @property
    def in_burst(self) -> bool:
        return self._in_burst

    def time_to_next(self, now: float) -> float:
        """Seconds until next scheduled capture (0.0 if in burst or overdue)."""
        if self._in_burst:
            return 0.0
        return max(0.0, self._next_deadline - now)
