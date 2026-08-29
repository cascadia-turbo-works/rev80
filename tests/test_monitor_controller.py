"""Integration tests for rev80.monitor.controller.MonitorController.

Uses synthetic ChannelResult + VibeSample objects — no hardware required.
interval_s is set very short (0.05–0.1 s) so tests complete in <2 s wall time.
"""

import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np

from rev80.monitor.anomaly import AnomalyEvent
from rev80.monitor.controller import MonitorController
from rev80.monitor.session import MonitorSession
from rev80.sample import ChannelResult, VibeSample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(tmp_path: Path, interval_s: float = 0.1,
                  pre_buffer_frames: int = 2) -> MonitorSession:
    return MonitorSession(
        session_id        = '2026-05-28-120000_test',
        start_time        = datetime.now(timezone.utc),
        interval_s        = interval_s,
        pre_buffer_frames = pre_buffer_frames,
        burst_duration_s  = 0.3,
        max_burst_s       = 5.0,
        session_dir       = tmp_path / 'session',
    )


def _make_sample(n: int = 64, samplerate: int = 1000) -> VibeSample:
    return VibeSample(
        status     = 'OKAY',
        _timestamp = datetime.now(timezone.utc),
        samplerate = samplerate,
        unit       = 'mV',
        overflow   = False,
        data       = np.ones(n, dtype=np.float64) * 0.1,
    )


def _make_result(channel: int = 0, n: int = 64, samplerate: int = 1000,
                 overall: float = 0.1) -> ChannelResult:
    freq = np.linspace(0, 500, n // 2 + 1)
    spec = np.ones_like(freq) * 0.01
    return ChannelResult(
        channel    = channel,
        unit       = 'mV',
        overflow   = False,
        degraded   = False,
        time_data  = np.ones(n) * overall,
        time_vec   = np.arange(n) / samplerate,
        samplerate = samplerate,
        freq       = freq,
        spectrum   = spec,
        peaks      = np.array([], dtype=int),
        overall    = overall,
        timestamp  = datetime.now(timezone.utc),
        rel_time   = 0.0,
        status     = 'OKAY',
    )


def _make_frame_cache(n_frames: int = 3, n_samples: int = 64) -> deque:
    cache = deque(maxlen=32)
    for _ in range(n_frames):
        cache.append({0: _make_sample(n_samples)})
    return cache


def _drive(ctrl: MonitorController, frame_cache: deque, results: list,
           duration_s: float, step_s: float = 0.01) -> None:
    """Call on_results in a tight loop for duration_s seconds."""
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        ctrl.on_results(results, frame_cache)
        time.sleep(step_s)


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:

    def test_start_creates_session_dir(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path)
        ctrl.start(session)
        # Writer creates session_dir on first write; we just verify it exists after stop
        results = [_make_result()]
        ctrl.on_results(results, _make_frame_cache())
        ctrl.stop()
        assert session.session_dir.exists()

    def test_is_recording_after_start(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        assert ctrl.is_recording
        ctrl.stop()

    def test_is_not_recording_after_stop(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.stop()
        assert not ctrl.is_recording

    def test_stop_is_idempotent(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.stop()
        ctrl.stop()  # must not raise

    def test_start_twice_stops_previous(self, tmp_path):
        ctrl = MonitorController()
        s1 = _make_session(tmp_path)
        ctrl.start(s1)
        s2 = MonitorSession(
            session_id='s2', start_time=datetime.now(timezone.utc),
            interval_s=0.1, pre_buffer_frames=2,
            burst_duration_s=0.3, max_burst_s=5.0,
            session_dir=tmp_path / 'session2',
        )
        ctrl.start(s2)  # must not raise even though s1 is still running
        ctrl.stop()


# ---------------------------------------------------------------------------
# Anomaly hook wiring — built at start(), no separate arm/disarm step
# ---------------------------------------------------------------------------

class _AlwaysFireHook:
    """Stub anomaly hook that fires an event on every call — for wiring tests."""

    def __init__(self, burst_duration_s: float = 0.05):
        self.calls = 0
        self._burst_duration_s = burst_duration_s

    def on_results(self, results, frame_cache):
        self.calls += 1
        return AnomalyEvent(
            trigger_time=datetime.now(timezone.utc),
            channel=0, reason='stub', burst_duration_s=self._burst_duration_s,
            trigger_rel_time=0.0,
        )


class TestAnomalyHookWiring:

    def test_hook_passed_at_start_fires_without_arming(self, tmp_path):
        """The hook supplied to start() is active immediately — no arm() step exists."""
        ctrl = MonitorController()
        hook = _AlwaysFireHook()
        session = _make_session(tmp_path, interval_s=100.0)
        ctrl.start(session, anomaly_hook=hook)
        ctrl.on_results([_make_result()], _make_frame_cache())
        assert hook.calls >= 1
        assert ctrl._in_burst
        ctrl.stop()

    def test_no_hook_records_without_detection(self, tmp_path):
        """start(session) with no hook records normally; nothing ever bursts."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=100.0)
        ctrl.start(session)
        ctrl.on_results([_make_result()], _make_frame_cache())
        assert not ctrl._in_burst
        ctrl.stop()


# ---------------------------------------------------------------------------
# Cooldown gating
# ---------------------------------------------------------------------------

class TestCooldownGating:

    def _cooldown_session(self, tmp_path, cooldown_enabled, cooldown_s=10.0):
        return MonitorSession(
            session_id='cooldown-test', start_time=datetime.now(timezone.utc),
            interval_s=100.0, pre_buffer_frames=2,
            burst_duration_s=0.05, max_burst_s=5.0,
            session_dir=tmp_path / 'session',
            cooldown_enabled=cooldown_enabled, cooldown_s=cooldown_s,
        )

    def test_cooldown_suppresses_hook_after_burst(self, tmp_path):
        """Once a burst fires, cooldown blocks further hook checks until it expires."""
        ctrl = MonitorController()
        hook = _AlwaysFireHook()
        session = self._cooldown_session(tmp_path, cooldown_enabled=True, cooldown_s=10.0)
        ctrl.start(session, anomaly_hook=hook)
        frame_cache = _make_frame_cache()
        results = [_make_result()]

        ctrl.on_results(results, frame_cache)   # triggers burst, arms cooldown
        assert ctrl._in_burst
        calls_at_trigger = hook.calls

        _drive(ctrl, frame_cache, results, duration_s=0.2)
        assert not ctrl._in_burst   # burst has run its course

        ctrl.on_results(results, frame_cache)
        assert hook.calls == calls_at_trigger, "hook must not be consulted during cooldown"
        ctrl.stop()

    def test_disabled_cooldown_allows_immediate_retrigger(self, tmp_path):
        """Without cooldown enabled, the hook is consulted again as soon as the burst ends."""
        ctrl = MonitorController()
        hook = _AlwaysFireHook()
        session = self._cooldown_session(tmp_path, cooldown_enabled=False)
        ctrl.start(session, anomaly_hook=hook)
        frame_cache = _make_frame_cache()
        results = [_make_result()]

        ctrl.on_results(results, frame_cache)   # triggers the first burst
        assert ctrl._in_burst

        # Drive until that burst completes and flushes
        deadline = time.monotonic() + 2.0
        while ctrl._in_burst and time.monotonic() < deadline:
            ctrl.on_results(results, frame_cache)
            time.sleep(0.01)
        assert not ctrl._in_burst

        calls_before_retrigger = hook.calls
        ctrl.on_results(results, frame_cache)   # no cooldown — hook consulted immediately
        assert hook.calls > calls_before_retrigger
        ctrl.stop()


# ---------------------------------------------------------------------------
# Interval capture — HDF5 layout v5
# ---------------------------------------------------------------------------

class TestIntervalCapture:

    def test_no_second_capture_before_deadline(self, tmp_path):
        """First call captures immediately; a second call before the next deadline does not."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=100.0)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result()]
        ctrl.on_results(results, frame_cache)  # first call → immediate capture
        ctrl.on_results(results, frame_cache)  # second call 0 s later → no new capture
        ctrl.stop()

        assert session.session_h5.exists()
        with h5py.File(session.session_h5, 'r') as f:
            assert '0' in f['monitor']
            assert '1' not in f['monitor']

    def test_captures_written_to_h5(self, tmp_path):
        """After several deadlines pass, /monitor should accumulate groups."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result()]
        _drive(ctrl, frame_cache, results, duration_s=0.8)
        ctrl.stop()

        assert session.session_h5.exists()
        with h5py.File(session.session_h5, 'r') as f:
            assert len(f['monitor']) >= 1

    def test_h5_file_has_frame_and_channel_groups(self, tmp_path):
        """HDF5 layout v5: /metadata with file_version=5, /monitor/0/0/data."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.2)
        ctrl.stop()

        assert session.session_h5.exists()
        with h5py.File(session.session_h5, 'r') as f:
            assert 'metadata' in f
            assert f['metadata'].attrs['file_version'] == 5
            assert 'monitor' in f
            assert '0' in f['monitor']
            assert '0' in f['monitor']['0']       # channel group
            assert 'data' in f['monitor']['0']['0']

    def test_monitor_group_has_overall_json(self, tmp_path):
        """Each /monitor/{N}/ group stores overall_json attr with ch amplitude."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result(channel=0, overall=0.42)]
        _drive(ctrl, frame_cache, results, duration_s=0.2)
        ctrl.stop()

        import json
        with h5py.File(session.session_h5, 'r') as f:
            overall_json = f['monitor']['0'].attrs['overall_json']
            overall = json.loads(overall_json)
            assert '0' in overall
            assert isinstance(overall['0'], float)


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------

class TestStatusSnapshot:

    def test_recording_fields_present(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        snap = ctrl.status_snapshot()
        assert snap['capture_count'] == 0
        assert snap['burst_count'] == 0
        assert snap['queue_depth'] >= 0
        assert snap['next_capture_s'] >= 0
        assert snap['error'] is None
        ctrl.stop()

    def test_default_snapshot_before_start(self):
        ctrl = MonitorController()
        snap = ctrl.status_snapshot()
        assert snap['elapsed_s'] == 0.0

    def test_capture_count_increments(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.3)
        snap = ctrl.status_snapshot()
        ctrl.stop()
        assert snap['capture_count'] >= 1

    def test_total_bytes_after_writes(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.3)
        ctrl.stop()
        snap = ctrl.status_snapshot()
        assert snap['total_bytes'] > 0
