"""Nothing may grow without a bound during an unattended run (audit S-02, critical).

Three defects that compound into the most likely way an overnight session
dies, and the one that leaves the least evidence — an OOM kill is SIGKILL, so
there is no traceback, no atexit and no log line. The app simply vanishes.

  (a) Burst capture retained every frame AND every ChannelResult with no cap.
  (b) max_burst_s was enforced only inside IntervalGate.enter_burst(), which
      the manual path calls and the ANOMALY path never did — it set
      _burst_end_mono directly, so the cap was inert on the path that actually
      fires unattended.
  (c) The writer queue was queue.Queue() with NO maxsize, so its
      `except queue.Full` branch was unreachable dead code and enqueue()
      always returned True — and enqueue's return is what increments the
      capture counter, so the UI reported successes that were never written.

Policy, as chosen: bounded queue, drop on full, count the drops and surface
them. Acquisition must never stall behind a slow disk, and a loss must be
visible rather than silent.
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
# (c) the writer queue is bounded and honest
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
    """Exercise MonitorWriterThread.__init__ itself, not a test-built queue.

    An earlier version of this file only ever checked a queue the helper had
    constructed with an explicit maxsize, so reverting the production code to
    queue.Queue() still passed every test — the same shape of gap as the
    power-vs-amplitude one in the averaging work. This drives the real
    __init__ so the bound cannot quietly disappear.
    """
    session = SimpleNamespace(session_h5=Path('/nonexistent/session.h5'))
    w = MonitorWriterThread(session)          # constructed, never started
    assert w._queue.maxsize == MonitorWriterThread.MAX_QUEUE_DEPTH
    assert MonitorWriterThread.MAX_QUEUE_DEPTH > 0


def test_the_real_constructor_starts_with_no_drops():
    session = SimpleNamespace(session_h5=Path('/nonexistent/session.h5'))
    assert MonitorWriterThread(session).dropped == 0


def test_enqueue_reports_failure_when_full():
    """enqueue()'s return value gates the capture counter, so it must be true.

    With no maxsize it always returned True and the UI counted captures that
    were never written.
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
    # If this used a blocking put it would hang here rather than return.
    assert w.enqueue({'n': 2}) is False


def test_drop_is_logged(caplog):
    import logging
    w = _writer(maxsize=1)
    w.enqueue({'n': 1})
    with caplog.at_level(logging.ERROR):
        w.enqueue({'n': 2})
    assert any('drop' in r.getMessage().lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# (a) burst retention is capped
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
    """Every frame AND every ChannelResult were retained, ~3x the raw block
    each. At F_max 50 kHz that was ~2 GB before the single flush."""
    c = _controller()
    cache = deque([{0: object()}], maxlen=32)
    for _ in range(100):
        c._handle_burst_frame([], cache, now=1.0, rel_time=1.0)
    assert len(c._burst_frames) <= c._max_burst_frames
    assert len(c._burst_all_results) <= c._max_burst_frames


def test_burst_cap_keeps_frames_and_results_aligned():
    """S-06 territory: the two lists are indexed together, so they must be
    trimmed together or every overall lands against the wrong waveform."""
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
# (b) max_burst_s applies to the anomaly path too
# ---------------------------------------------------------------------------

def test_gate_enforces_max_burst_s():
    g = IntervalGate(interval_s=1.0, start_monotonic=0.0)
    g.enter_burst(duration_s=10.0, now=0.0, max_burst_s=4.0)
    g.enter_burst(duration_s=10.0, now=1.0, max_burst_s=4.0)
    assert g._burst_end <= 4.0


def test_anomaly_burst_end_is_capped_by_max_burst_s():
    """The anomaly path set _burst_end_mono directly and skipped the cap.

    That is the path that fires unattended, so the cap was inert exactly where
    it mattered.
    """
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
    """The retrigger branch reads _burst_start; it was only ever set inside
    enter_burst(), leaving an AttributeError one refactor away."""
    g = IntervalGate(interval_s=1.0, start_monotonic=7.0)
    assert g._burst_start == 7.0


def test_dropped_count_is_surfaced_in_the_status_snapshot():
    """The UI must be able to show that captures were lost.

    enqueue() previously always reported success, so the capture counter it
    gates counted captures that never reached disk. A drop that nobody can see
    is the same defect in a new place.
    """
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
