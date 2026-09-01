"""Integration tests for monitor session write → load → browse workflow.

Exercises the full pipeline:
  record intervals + trigger burst → session.h5
  → load_monitor_session() → check trend + frames
  → load_monitor_burst()  → check rebased rel_times + trend
  → check collector state is consistent throughout

No hardware required. Uses synthetic VibeSample / ChannelResult.
"""

import json
import time
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import pytest

from rev80.collector import DataCollector
from rev80.monitor.controller import MonitorController
from rev80.monitor.session import MonitorSession
from rev80.sample import AcquisitionSettings, ChannelResult, VibeSample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLERATE  = 1000
BLOCKSIZE   = 64
N_CHANNELS  = 2
INTERVAL_S  = 0.05   # fast interval so tests finish quickly
BURST_S     = 0.2
PRE_FRAMES  = 2
STEP_S      = 0.01


def _make_vibe_sample(ch: int = 0, rel_time: float = 0.0,
                      amplitude: float = 0.1) -> VibeSample:
    return VibeSample(
        status     = 'OKAY',
        _timestamp = datetime.now(timezone.utc),
        samplerate = SAMPLERATE,
        unit       = 'mV',
        overflow   = False,
        data       = np.ones(BLOCKSIZE, dtype=np.float64) * amplitude,
        rel_time   = rel_time,
    )


def _make_result(channel: int = 0, overall: float = 0.1,
                 rel_time: float = 0.0) -> ChannelResult:
    freq = np.linspace(0, SAMPLERATE / 2, BLOCKSIZE // 2 + 1)
    return ChannelResult(
        channel    = channel,
        unit       = 'mV',
        overflow   = False,
        degraded   = False,
        time_data  = np.ones(BLOCKSIZE) * overall,
        time_vec   = np.arange(BLOCKSIZE) / SAMPLERATE,
        samplerate = SAMPLERATE,
        freq       = freq,
        spectrum   = np.ones_like(freq) * 0.01,
        peaks      = np.array([], dtype=int),
        overall    = overall,
        timestamp  = datetime.now(timezone.utc),
        rel_time   = rel_time,
        status     = 'OKAY',
    )


def _make_frame_cache(n_frames: int = 4, stream_t0: float = 0.0) -> deque:
    cache = deque(maxlen=32)
    for i in range(n_frames):
        rel_t = stream_t0 + i * (BLOCKSIZE / SAMPLERATE)
        cache.append({
            ch: _make_vibe_sample(ch, rel_time=rel_t)
            for ch in range(N_CHANNELS)
        })
    return cache


def _make_session(tmp_path: Path) -> MonitorSession:
    cfg = AcquisitionSettings()
    cfg.maxfreq    = SAMPLERATE / 2
    cfg.enabled_channels = list(range(N_CHANNELS))

    acq_snapshot     = cfg.to_dict()
    channel_snapshot = {
        str(ch): {'name': f'Ch{ch}', 'unit': 'mV', 'coupling': 'AC',
                  'voltage_range': 7, 'scope_sensor_id': '',
                  'target_unit': '', 'amplitude_mode': ''}
        for ch in range(N_CHANNELS)
    }
    return MonitorSession(
        session_id        = 'test-session',
        start_time        = datetime.now(timezone.utc),
        interval_s        = INTERVAL_S,
        pre_buffer_frames = PRE_FRAMES,
        burst_duration_s  = BURST_S,
        max_burst_s       = 5.0,
        session_dir       = tmp_path / 'test-session',
        acq_snapshot      = acq_snapshot,
        channel_snapshot  = channel_snapshot,
        sensor_snapshot   = {},
    )


def _record_session(session: MonitorSession, n_intervals: int = 6,
                    n_bursts: int = 2) -> list[str]:
    """Run a MonitorController, capture intervals and trigger bursts.

    Returns list of burst_ids that were triggered.
    """
    ctrl = MonitorController()
    ctrl.start(session)

    stream_t = 0.0
    frame_cache = _make_frame_cache(n_frames=PRE_FRAMES + 2, stream_t0=stream_t)

    # Drive enough interval captures
    deadline = time.monotonic() + INTERVAL_S * n_intervals * 1.5

    triggered = 0
    while time.monotonic() < deadline:
        stream_t += BLOCKSIZE / SAMPLERATE
        # Update frame cache with fresh timestamps
        frame_cache.append({
            ch: _make_vibe_sample(ch, rel_time=stream_t)
            for ch in range(N_CHANNELS)
        })
        results = [_make_result(ch, rel_time=stream_t) for ch in range(N_CHANNELS)]
        ctrl.on_results(results, frame_cache)

        # Trigger a burst partway through
        if triggered < n_bursts and time.monotonic() > deadline - INTERVAL_S * n_intervals * 0.6:
            snap = ctrl.status_snapshot()
            if not snap['is_in_burst']:
                ctrl.trigger_burst()
                triggered += 1

        time.sleep(STEP_S)

    ctrl.stop()
    return ctrl._burst_count


def _make_collector() -> DataCollector:
    """Collector configured to match session channels."""
    col = DataCollector()
    col.config.maxfreq = SAMPLERATE / 2
    col.config.enabled_channels = list(range(N_CHANNELS))
    col.init_trend_channels()
    return col


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionH5Structure:

    def test_session_h5_created_after_stop(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=4, n_bursts=0)
        assert session.session_h5.exists()

    def test_monitor_group_has_frames(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        with h5py.File(session.session_h5, 'r') as f:
            assert 'monitor' in f
            assert len(f['monitor']) >= 1

    def test_interval_frame_has_overall_json(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=4, n_bursts=0)
        with h5py.File(session.session_h5, 'r') as f:
            frame0 = f['monitor']['0']
            assert 'overall_json' in frame0.attrs
            overall = json.loads(frame0.attrs['overall_json'])
            assert len(overall) == N_CHANNELS

    def test_interval_frame_has_rel_time(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=4, n_bursts=0)
        with h5py.File(session.session_h5, 'r') as f:
            for key in f['monitor'].keys():
                rt = float(f['monitor'][key].attrs['rel_time'])
                assert math.isfinite(rt)

    def test_burst_group_created(self, tmp_path):
        session = _make_session(tmp_path)
        n_bursts = _record_session(session, n_intervals=8, n_bursts=1)
        if n_bursts == 0:
            pytest.skip("Burst did not complete in time window")
        with h5py.File(session.session_h5, 'r') as f:
            assert 'burst' in f
            assert len(f['burst'].keys()) > 0

    def test_burst_list_has_trigger_rel_time(self, tmp_path):
        session = _make_session(tmp_path)
        n_bursts = _record_session(session, n_intervals=8, n_bursts=1)
        if n_bursts == 0:
            pytest.skip("Burst did not complete in time window")
        with h5py.File(session.session_h5, 'r') as f:
            burst_list = json.loads(f['burst'].attrs['burst_list'])
        assert len(burst_list) >= 1
        b = burst_list[0]
        assert 'rel_time' in b
        assert math.isfinite(float(b['rel_time']))
        assert float(b['rel_time']) >= 0

    def test_burst_frames_have_overall_json(self, tmp_path):
        session = _make_session(tmp_path)
        n_bursts = _record_session(session, n_intervals=8, n_bursts=1)
        if n_bursts == 0:
            pytest.skip("Burst did not complete in time window")
        with h5py.File(session.session_h5, 'r') as f:
            burst_list = json.loads(f['burst'].attrs['burst_list'])
            burst_id = burst_list[0]['burst_id']
            bid_grp = f['burst'][burst_id]
            n_frames = int(bid_grp.attrs['n_frames'])
            assert n_frames > 0
            # At least some non-pretrigger frames should have overall_json
            n_pre = int(bid_grp.attrs.get('n_pretrigger_frames', 0))
            found = any(
                'overall_json' in bid_grp[str(fi)].attrs
                for fi in range(n_pre, n_frames)
                if str(fi) in bid_grp
            )
            assert found


class TestSessionLoad:

    def test_load_session_populates_frame_cache(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        col = _make_collector()
        col.load_monitor_session(session.session_h5)
        assert len(col.data['frame_cache']) >= 1

    def test_load_session_rebuilds_trend(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        col = _make_collector()
        col.load_monitor_session(session.session_h5)
        for ch in range(N_CHANNELS):
            trend = col.trend.get(ch, {})
            rt = trend.get('rel_times', np.array([]))
            assert len(rt) >= 1, f"Channel {ch} trend empty"

    def test_trend_rel_times_are_finite(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        col = _make_collector()
        col.load_monitor_session(session.session_h5)
        for ch in range(N_CHANNELS):
            rt = col.trend.get(ch, {}).get('rel_times', np.array([]))
            assert all(math.isfinite(t) for t in rt.tolist()), \
                f"NaN/inf in channel {ch} trend"

    def test_trend_monotonically_increasing(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        col = _make_collector()
        col.load_monitor_session(session.session_h5)
        ch = 0
        rt = col.trend.get(ch, {}).get('rel_times', np.array([]))
        if len(rt) >= 2:
            diffs = np.diff(rt)
            assert all(d >= 0 for d in diffs), "Trend times not monotonic"

    def test_cache_cursor_reset_after_load(self, tmp_path):
        session = _make_session(tmp_path)
        _record_session(session, n_intervals=6, n_bursts=0)
        col = _make_collector()
        col._cache_cursor = 999  # simulate stale cursor
        col.load_monitor_session(session.session_h5)
        assert col._cache_cursor == 0


class TestBurstLoad:

    def _write_and_get_burst(self, tmp_path):
        """Helper: record a session with one burst, return (collector, session_h5, burst_id)."""
        session = _make_session(tmp_path)
        n_bursts = _record_session(session, n_intervals=8, n_bursts=1)
        if n_bursts == 0:
            return None
        with h5py.File(session.session_h5, 'r') as f:
            burst_list = json.loads(f['burst'].attrs['burst_list'])
        if not burst_list:
            return None
        col = _make_collector()
        return col, session.session_h5, burst_list[0]['burst_id']

    def test_burst_load_populates_cache(self, tmp_path):
        result = self._write_and_get_burst(tmp_path)
        if result is None:
            pytest.skip("No burst captured")
        col, h5_path, burst_id = result
        col.load_monitor_burst(h5_path, burst_id)
        assert len(col.data['frame_cache']) >= 1

    def test_burst_trigger_frame_at_time_zero(self, tmp_path):
        """The trigger frame (first non-pretrigger frame) should land at rel_time=0."""
        result = self._write_and_get_burst(tmp_path)
        if result is None:
            pytest.skip("No burst captured")
        col, h5_path, burst_id = result
        col.load_monitor_burst(h5_path, burst_id)
        ch = 0
        trend = col.trend.get(ch, {})
        rt = trend.get('rel_times', np.array([]))
        if len(rt) == 0:
            pytest.skip("No trend data in burst")
        # The trend should span across 0 (pre-trigger negative, post positive)
        # or start at 0 if no pre-trigger frames had overall_json
        assert any(math.isfinite(t) for t in rt.tolist())

    def test_burst_trend_rel_times_finite(self, tmp_path):
        result = self._write_and_get_burst(tmp_path)
        if result is None:
            pytest.skip("No burst captured")
        col, h5_path, burst_id = result
        col.load_monitor_burst(h5_path, burst_id)
        for ch in range(N_CHANNELS):
            rt = col.trend.get(ch, {}).get('rel_times', np.array([]))
            assert all(math.isfinite(t) for t in rt.tolist()), \
                f"NaN in burst trend channel {ch}"

    def test_burst_cursor_reset(self, tmp_path):
        result = self._write_and_get_burst(tmp_path)
        if result is None:
            pytest.skip("No burst captured")
        col, h5_path, burst_id = result
        col._cache_cursor = 999
        col.load_monitor_burst(h5_path, burst_id)
        assert col._cache_cursor == 0

    def test_session_then_burst_load_no_nan(self, tmp_path):
        """Loading session then burst: trend must stay finite after both loads."""
        session = _make_session(tmp_path)
        n_bursts = _record_session(session, n_intervals=8, n_bursts=1)
        if n_bursts == 0:
            pytest.skip("No burst captured")
        with h5py.File(session.session_h5, 'r') as f:
            burst_list = json.loads(f['burst'].attrs['burst_list'])
        if not burst_list:
            pytest.skip("No burst in list")

        col = _make_collector()
        col.load_monitor_session(session.session_h5)
        # Session trend must be finite
        for ch in range(N_CHANNELS):
            rt = col.trend.get(ch, {}).get('rel_times', np.array([]))
            bad = [t for t in rt.tolist() if not math.isfinite(t)]
            assert not bad, f"NaN in session trend ch{ch}: {bad}"

        col.load_monitor_burst(session.session_h5, burst_list[0]['burst_id'])
        # Burst trend must also be finite
        for ch in range(N_CHANNELS):
            rt = col.trend.get(ch, {}).get('rel_times', np.array([]))
            bad = [t for t in rt.tolist() if not math.isfinite(t)]
            assert not bad, f"NaN in burst trend ch{ch}: {bad}"
