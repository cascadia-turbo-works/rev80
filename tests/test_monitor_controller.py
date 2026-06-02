"""Integration tests for vibechecker.monitor.controller.MonitorController.

Uses synthetic ChannelResult + VibeSample objects — no hardware required.
interval_s is set very short (0.05–0.1 s) so tests complete in <2 s wall time.
"""

import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import pytest

import vibechecker as vc
from vibechecker.monitor.controller import MonitorController
from vibechecker.monitor.session import MonitorSession
from vibechecker.sample import ChannelResult, VibeSample


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

    def test_is_not_armed_by_default(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        assert not ctrl.is_armed
        ctrl.stop()

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
# Arm / disarm
# ---------------------------------------------------------------------------

class TestArmDisarm:

    def test_arm_enables_armed_flag(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        assert not ctrl.is_armed
        ctrl.arm()
        assert ctrl.is_armed
        ctrl.stop()

    def test_disarm_clears_armed_flag(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.arm()
        ctrl.disarm()
        assert not ctrl.is_armed
        ctrl.stop()

    def test_arm_noop_when_not_recording(self):
        ctrl = MonitorController()
        ctrl.arm()  # must not raise
        assert not ctrl.is_armed

    def test_disarm_noop_when_not_recording(self):
        ctrl = MonitorController()
        ctrl.disarm()  # must not raise
        assert not ctrl.is_armed

    def test_stop_clears_armed_flag(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.arm()
        ctrl.stop()
        assert not ctrl.is_armed


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

    def test_disarmed_defaults(self):
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
