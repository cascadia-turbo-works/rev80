"""No monitor buffer grows without a bound during an unattended run.

An OOM kill is SIGKILL and leaves no log line. The writer queue is bounded and
drops (and counts) on full, so acquisition never waits for the disk. Burst
retention is capped, and max_burst_s applies to the anomaly path too.
"""

import queue
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from rev80.monitor.controller import MonitorController
from rev80.monitor.gate import IntervalGate
from rev80.monitor.writer import MonitorWriterThread


# ---------------------------------------------------------------------------
# The writer queue is bounded and reports drops
# ---------------------------------------------------------------------------

def _writer(maxsize=None):
    w = MonitorWriterThread.__new__(MonitorWriterThread)
    w._queue = queue.Queue(maxsize=maxsize if maxsize is not None
                           else MonitorWriterThread.MAX_QUEUE_DEPTH)
    w._stop_event = threading.Event()
    w._error = None
    w._warned_depth = False
    w._dropped = 0
    return w


def test_the_real_constructor_bounds_the_queue():
    """MonitorWriterThread.__init__ itself creates a bounded queue.

    The test uses the real constructor, not the _writer() helper, so a revert
    to an unbounded queue.Queue() fails here.
    """
    session = SimpleNamespace(session_h5=Path('/nonexistent/session.h5'))
    w = MonitorWriterThread(session)          # constructed, never started
    assert w._queue.maxsize == MonitorWriterThread.MAX_QUEUE_DEPTH
    assert MonitorWriterThread.MAX_QUEUE_DEPTH > 0


def test_the_real_constructor_starts_with_no_drops():
    session = SimpleNamespace(session_h5=Path('/nonexistent/session.h5'))
    assert MonitorWriterThread(session).dropped == 0


def test_enqueue_reports_failure_when_full():
    """enqueue() returns False on a full queue.

    The return value gates the capture counter. A True on a full queue would
    count a capture that is never written.
    """
    w = _writer(maxsize=2)
    assert w.enqueue({'n': 1}) is True
    assert w.enqueue({'n': 2}) is True
    assert w.enqueue({'n': 3}) is False, 'reported success on a full queue'


def test_dropped_captures_are_counted():
    w = _writer(maxsize=1)
    w.enqueue({'n': 1})
    for _ in range(5):
        w.enqueue({'n': 2})
    assert w.dropped == 5


def test_dropping_does_not_block(monkeypatch):
    """Acquisition must never stall behind the writer."""
    w = _writer(maxsize=1)
    w.enqueue({'n': 1})
    # A blocking put would hang here.
    assert w.enqueue({'n': 2}) is False


def test_drop_is_logged(caplog):
    import logging
    w = _writer(maxsize=1)
    w.enqueue({'n': 1})
    with caplog.at_level(logging.ERROR):
        w.enqueue({'n': 2})
    assert any('drop' in r.getMessage().lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Burst retention is capped
# ---------------------------------------------------------------------------

class _NullHook:
    def on_results(self, results, frame_cache):
        return None


def _controller(max_burst_s=5.0, interval_s=1.0):
    c = MonitorController.__new__(MonitorController)
    c._recording = True
    c._in_burst = True
    c._burst_frames = []
    c._burst_all_results = []
    c._burst_results = []
    c._burst_pre_overalls = []
    c._burst_pretrigger = 0
    c._burst_end_mono = 1e9
    c._anomaly_hook = _NullHook()
    c._last_trail_mono = 0.0
    c._session = None
    c._max_burst_frames = 10
    return c


def test_burst_frame_retention_is_capped():
    """Burst frames and burst results stay at or below _max_burst_frames.

    Each retained frame costs about 2.76 x the raw block, because it keeps
    the frame and every ChannelResult until the flush.
    """
    c = _controller()
    cache = deque([{0: object()}], maxlen=32)
    for _ in range(100):
        c._handle_burst_frame([], cache, now=1.0, rel_time=1.0)
    assert len(c._burst_frames) <= c._max_burst_frames
    assert len(c._burst_all_results) <= c._max_burst_frames


def test_burst_cap_keeps_frames_and_results_aligned():
    """The frame and result lists are trimmed together, because the flush
    indexes them in parallel."""
    c = _controller()
    cache = deque([{0: object()}], maxlen=32)
    for _ in range(100):
        c._handle_burst_frame([], cache, now=1.0, rel_time=1.0)
    assert len(c._burst_frames) == len(c._burst_all_results)


def test_burst_cap_is_derived_from_max_burst_s():
    """The cap must follow the configured burst length, not a magic number."""
    n = MonitorController.burst_frame_cap(max_burst_s=60.0, acquisition_period=0.5)
    assert n == pytest.approx(120, abs=2)


def test_burst_cap_has_a_floor():
    """A pathological acquisition_period must not produce a zero-length burst."""
    assert MonitorController.burst_frame_cap(max_burst_s=1.0, acquisition_period=1e9) >= 1


# ---------------------------------------------------------------------------
# max_burst_s applies to the anomaly path too
# ---------------------------------------------------------------------------

def test_gate_enforces_max_burst_s():
    g = IntervalGate(interval_s=1.0, start_monotonic=0.0)
    g.enter_burst(duration_s=10.0, now=0.0, max_burst_s=4.0)
    g.enter_burst(duration_s=10.0, now=1.0, max_burst_s=4.0)
    assert g._burst_end <= 4.0


def test_anomaly_burst_end_is_capped_by_max_burst_s():
    """capped_burst_end() applies max_burst_s to the anomaly burst end."""
    end = MonitorController.capped_burst_end(
        now=100.0, duration_s=600.0, max_burst_s=30.0, burst_start=100.0)
    assert end == pytest.approx(130.0)


def test_anomaly_burst_end_respects_a_shorter_duration():
    end = MonitorController.capped_burst_end(
        now=100.0, duration_s=10.0, max_burst_s=30.0, burst_start=100.0)
    assert end == pytest.approx(110.0)


def test_max_burst_s_of_zero_means_no_cap():
    """0 / None must mean 'unset', not 'zero-length burst'."""
    end = MonitorController.capped_burst_end(
        now=100.0, duration_s=10.0, max_burst_s=0.0, burst_start=100.0)
    assert end == pytest.approx(110.0)


def test_gate_burst_start_is_initialised():
    """IntervalGate sets _burst_start at construction, because the retrigger
    branch reads it."""
    g = IntervalGate(interval_s=1.0, start_monotonic=7.0)
    assert g._burst_start == 7.0


def test_dropped_count_is_surfaced_in_the_status_snapshot():
    """status_snapshot() reports the writer's dropped captures."""
    import time as _time

    c = MonitorController.__new__(MonitorController)
    c._recording = False
    c._start_mono = _time.monotonic()
    c._gate = None
    c._session = None
    c._capture_count = 0
    c._burst_count = 0
    c._in_burst = False
    c._burst_end_mono = 0.0
    c._anomaly_hook = _NullHook()
    c._cooldown_until_mono = 0.0
    w = _writer(maxsize=1)
    w.enqueue({'n': 1})
    w.enqueue({'n': 2})          # dropped
    c._writer = w

    snap = c.status_snapshot()
    assert snap['dropped_captures'] == 1
