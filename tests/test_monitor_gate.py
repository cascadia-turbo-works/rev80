"""Unit tests for rev80.monitor.gate.IntervalGate.

All tests inject monotonic time explicitly — no wall-clock dependency.
"""

import pytest
from rev80.monitor.gate import IntervalGate


def _gate(interval: float, start: float = 0.0) -> IntervalGate:
    return IntervalGate(interval_s=interval, start_monotonic=start)


class TestIntervalCapture:
    def test_capture_fires_immediately_on_arm(self):
        """First capture should fire at t=start (deadline == start_monotonic)."""
        g = _gate(10.0, start=100.0)
        assert g.should_capture(100.0)

    def test_no_capture_before_second_deadline(self):
        """After the first capture is marked, no capture until start + interval."""
        g = _gate(10.0, start=100.0)
        g.mark_captured(100.0)
        assert not g.should_capture(109.9)

    def test_capture_after_deadline(self):
        g = _gate(10.0, start=100.0)
        assert g.should_capture(115.0)

    def test_mark_captured_advances_deadline(self):
        g = _gate(10.0, start=100.0)
        g.mark_captured(110.0)
        assert not g.should_capture(119.9)
        assert g.should_capture(120.0)

    def test_snap_to_grid_no_drift(self):
        """1000 consecutive captures must stay on-grid, no drift accumulation."""
        g = _gate(10.0, start=0.0)
        for i in range(1, 1001):
            deadline = i * 10.0
            g.mark_captured(deadline)
        assert g.time_to_next(10000.0) == pytest.approx(10.0, abs=1e-9)

    def test_catchup_after_long_gap(self):
        """If multiple deadlines were missed, the next deadline should be in the future."""
        g = _gate(10.0, start=0.0)
        # Miss 5 deadlines; mark at t=60
        g.mark_captured(60.0)
        # Next deadline should be 70 (not 110)
        assert g.time_to_next(65.0) == pytest.approx(5.0, abs=1e-9)

    def test_time_to_next_zero_when_overdue(self):
        g = _gate(10.0, start=0.0)
        # At t=15 the deadline (10) has passed but mark_captured not called
        assert g.time_to_next(15.0) == 0.0

    def test_time_to_next_returns_remaining(self):
        g = _gate(10.0, start=0.0)
        g.mark_captured(10.0)
        assert g.time_to_next(15.0) == pytest.approx(5.0, abs=1e-9)


class TestBurstMode:
    def test_enter_burst_captures_every_call(self):
        g = _gate(3600.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        assert g.should_capture(1.0)
        assert g.should_capture(4.9)

    def test_burst_ends_after_duration(self):
        g = _gate(3600.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        assert not g.should_capture(5.0)

    def test_retrigger_extends_burst(self):
        g = _gate(3600.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        # Retrigger at t=3: extends to 3+5=8, capped at now+max_burst=3+600
        g.enter_burst(5.0, now=3.0, max_burst_s=600.0)
        assert g.should_capture(7.9)
        assert not g.should_capture(10.0)  # burst_end = 0+5+5 = 10, but should_capture checks now < burst_end

    def test_retrigger_respects_max_burst(self):
        g = _gate(3600.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        # Retrigger many times — should never exceed now + max_burst_s
        for _ in range(20):
            g.enter_burst(5.0, now=1.0, max_burst_s=10.0)
        assert g.in_burst
        # burst_end must not exceed 1.0 + 10.0 = 11.0
        assert not g.should_capture(11.0)

    def test_exit_burst_resumes_interval(self):
        g = _gate(10.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        g.exit_burst(now=5.0)
        assert not g.in_burst
        # Next interval deadline = 5.0 + 10.0 = 15.0
        assert not g.should_capture(14.9)
        assert g.should_capture(15.0)

    def test_in_burst_property(self):
        g = _gate(10.0, start=0.0)
        assert not g.in_burst
        g.enter_burst(5.0, now=0.0)
        assert g.in_burst
        g.exit_burst(now=5.0)
        assert not g.in_burst

    def test_time_to_next_is_zero_in_burst(self):
        g = _gate(3600.0, start=0.0)
        g.enter_burst(60.0, now=0.0)
        assert g.time_to_next(30.0) == 0.0

    def test_mark_captured_no_op_in_burst(self):
        """mark_captured during burst should not advance the interval deadline."""
        g = _gate(10.0, start=0.0)
        g.enter_burst(5.0, now=0.0)
        g.mark_captured(3.0)   # should be no-op
        g.exit_burst(now=5.0)
        # After exit, deadline = 5.0 + 10.0 = 15.0
        assert g.time_to_next(6.0) == pytest.approx(9.0, abs=1e-9)
