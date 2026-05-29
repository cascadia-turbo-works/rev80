"""Integration tests for vibechecker.monitor.controller.MonitorController.

Uses synthetic ChannelResult + VibeSample objects — no hardware required.
interval_s is set very short (0.05–0.1 s) so tests complete in <2 s wall time.
"""

import time
import yaml
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import pytest

import vibechecker as vc
from vibechecker.monitor.controller import MonitorController
from vibechecker.monitor.index import SessionIndex
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
        output_dir        = tmp_path / 'session',
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

    def test_start_creates_output_dir(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path)
        ctrl.start(session)
        assert session.output_dir.exists()
        ctrl.stop()

    def test_start_creates_index_sqlite(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path)
        ctrl.start(session)
        assert (session.output_dir / 'index.sqlite').exists()
        ctrl.stop()

    def test_is_armed_after_start(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        assert ctrl.is_armed
        ctrl.stop()

    def test_is_not_armed_after_stop(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.stop()
        assert not ctrl.is_armed

    def test_stop_writes_session_yaml(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        ctrl.stop()
        assert (tmp_path / 'session' / 'session.yaml').exists()

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
            output_dir=tmp_path / 'session2',
        )
        ctrl.start(s2)  # must not raise even though s1 is still running
        ctrl.stop()


# ---------------------------------------------------------------------------
# Interval capture
# ---------------------------------------------------------------------------

class TestIntervalCapture:

    def test_no_capture_before_deadline(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=100.0)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result()]
        ctrl.on_results(results, frame_cache)
        ctrl.stop()

        idx = SessionIndex(session.output_dir)
        assert idx.count() == 0
        idx.close()

    def test_captures_written_to_index(self, tmp_path):
        """After several deadlines pass, SQLite should accumulate rows."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result()]
        _drive(ctrl, frame_cache, results, duration_s=0.8)
        ctrl.stop()

        idx = SessionIndex(session.output_dir)
        count = idx.count()
        idx.close()
        assert count >= 1

    def test_h5_files_created(self, tmp_path):
        """Each interval capture must produce one .h5 file."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.3)
        ctrl.stop()

        h5_files = list(session.output_dir.glob('*.h5'))
        assert len(h5_files) >= 1

    def test_h5_file_has_frame_and_channel_groups(self, tmp_path):
        """HDF5 layout: file_version=5 in attrs, frame_0000/0/data present."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.2)
        ctrl.stop()

        h5_files = list(session.output_dir.glob('*.h5'))
        assert h5_files, 'Expected at least one .h5 file'
        with h5py.File(h5_files[0], 'r') as f:
            assert f.attrs['file_version'] == 5
            assert 'frame_0000' in f
            assert '0' in f['frame_0000']
            assert 'data' in f['frame_0000']['0']

    def test_index_row_trigger_is_interval(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        _drive(ctrl, frame_cache, [_make_result()], duration_s=0.2)
        ctrl.stop()

        idx = SessionIndex(session.output_dir)
        rows = idx.query()
        idx.close()
        assert rows
        assert rows[0]['trigger'] == 'interval'

    def test_index_row_overall_json(self, tmp_path):
        """Each row must store per-channel overall amplitude."""
        ctrl = MonitorController()
        session = _make_session(tmp_path, interval_s=0.05)
        ctrl.start(session)
        frame_cache = _make_frame_cache()
        results = [_make_result(channel=0, overall=0.42)]
        _drive(ctrl, frame_cache, results, duration_s=0.2)
        ctrl.stop()

        idx = SessionIndex(session.output_dir)
        rows = idx.query()
        idx.close()
        assert rows
        assert '0' in rows[0]['overall']
        assert isinstance(rows[0]['overall']['0'], float)


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------

class TestStatusSnapshot:

    def test_armed_fields_present(self, tmp_path):
        ctrl = MonitorController()
        ctrl.start(_make_session(tmp_path))
        snap = ctrl.status_snapshot()
        assert snap['armed'] is True
        assert snap['capture_count'] == 0
        assert snap['queue_depth'] >= 0
        assert snap['next_capture_s'] >= 0
        assert snap['in_burst'] is False
        assert snap['error'] is None
        ctrl.stop()

    def test_disarmed_defaults(self):
        ctrl = MonitorController()
        snap = ctrl.status_snapshot()
        assert snap['armed'] is False
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


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------

class TestSessionMeta:

    def test_session_id_in_index(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path)
        ctrl.start(session)
        ctrl.stop()

        idx = SessionIndex(session.output_dir)
        assert idx.get_meta('session_id') == session.session_id
        idx.close()

    def test_session_yaml_fields(self, tmp_path):
        ctrl = MonitorController()
        session = _make_session(tmp_path)
        ctrl.start(session)
        ctrl.stop()

        with open(session.output_dir / 'session.yaml') as f:
            data = yaml.safe_load(f)
        assert data['session_id'] == session.session_id
        assert 'start_time' in data
        assert 'stop_time' in data
        assert data['interval_s'] == session.interval_s
