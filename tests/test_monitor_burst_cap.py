"""The burst frame cap, for anomaly and manual bursts, on a real session.

The cap is max_burst_s / frame period + 1 frames after the trigger, plus the
pre-trigger frames. A session built by session_from() must give the
controller the frame period. Without it the cap falls to MIN_BURST_FRAMES,
and a burst keeps only its last 4 frames: the pre-trigger frames are lost.
"""

from collections import deque
from datetime import datetime, timezone

import numpy as np
import pytest

import rev80 as vc
from rev80.monitor import controller as controller_mod
from rev80.monitor.anomaly import AnomalyEvent
from rev80.monitor.controller import MonitorController
from rev80.monitor.session import MonitorSession, session_from
from rev80.sample import ChannelResult, VibeSample

PRE_BUFFER_S = 30.0
MAX_BURST_S = 120.0


def _collector() -> vc.DataCollector:
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 1.0
    cfg.enabled_channels = [0]
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    return dc


def _session(tmp_path) -> MonitorSession:
    return session_from(
        collector=_collector(), session_id='burst-cap', interval_s=3600.0,
        pre_buffer_s=PRE_BUFFER_S, burst_duration_s=600.0,
        max_burst_s=MAX_BURST_S, output_dir=tmp_path,
    )


def _sample() -> VibeSample:
    return VibeSample(status='OKAY', _timestamp=datetime.now(timezone.utc),
                      samplerate=1000, unit='mV', overflow=False,
                      data=np.ones(64) * 0.1)


def _result() -> ChannelResult:
    n = 64
    freq = np.linspace(0, 500, n // 2 + 1)
    return ChannelResult(
        channel=0, unit='mV', overflow=False, degraded=False,
        time_data=np.ones(n) * 0.1, time_vec=np.arange(n) / 1000,
        samplerate=1000, freq=freq, spectrum=np.ones_like(freq) * 0.01,
        peaks=np.array([], dtype=int), overall=0.1,
        timestamp=datetime.now(timezone.utc), rel_time=0.0, status='OKAY',
    )


class _OnceHook:
    """Raise one anomaly when `fire` is set, then none."""

    def __init__(self) -> None:
        self.fire = False

    def on_results(self, results, frame_cache):
        if not self.fire:
            return None
        self.fire = False
        return AnomalyEvent(trigger_time=datetime.now(), channel=0,
                            reason='test', burst_duration_s=600.0)


def _feed(ctrl, cache, n):
    for _ in range(n):
        cache.append({0: _sample()})
        ctrl.on_results([_result()], cache)


def _expected_cap(session, n_pretrigger):
    post = int(MAX_BURST_S / session.acquisition_period) + 1
    return post + n_pretrigger


def test_session_from_records_the_frame_period(tmp_path):
    session = _session(tmp_path)
    cfg = _collector().config
    assert session.acquisition_period == pytest.approx(
        cfg.raw_blocksize / cfg.raw_samplerate)
    assert session.acquisition_period > 0
    assert session.pre_buffer_frames == 30


def test_anomaly_burst_keeps_its_pre_trigger_frames(tmp_path):
    session = _session(tmp_path)
    hook = _OnceHook()
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, hook)
    try:
        _feed(ctrl, cache, 40)
        hook.fire = True
        _feed(ctrl, cache, 1)
        assert ctrl._in_burst
        n_pre = session.pre_buffer_frames - 1
        assert ctrl._burst_pretrigger == n_pre

        _feed(ctrl, cache, 10)
        assert ctrl._burst_pretrigger == n_pre, 'pre-trigger frames were trimmed'
        assert len(ctrl._burst_frames) == session.pre_buffer_frames + 10
        assert len(ctrl._burst_frames) == len(ctrl._burst_all_results)

        post = MonitorController.burst_frame_cap(
            MAX_BURST_S, session.acquisition_period)
        assert post == int(MAX_BURST_S / session.acquisition_period) + 1
        assert ctrl._max_burst_frames == _expected_cap(session, n_pre)
    finally:
        ctrl.stop()


def test_manual_burst_uses_the_same_cap_as_an_anomaly_burst(tmp_path):
    """A manual burst with no anomaly burst before it."""
    session = _session(tmp_path)
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, None)
    try:
        _feed(ctrl, cache, 40)
        assert not hasattr(ctrl, '_max_burst_frames') or not ctrl._max_burst_frames
        ctrl.trigger_burst()
        n_pre = session.pre_buffer_frames - 1
        assert ctrl._burst_pretrigger == n_pre
        assert ctrl._max_burst_frames == _expected_cap(session, n_pre)

        _feed(ctrl, cache, 10)
        assert ctrl._burst_pretrigger == n_pre
        assert len(ctrl._burst_frames) == session.pre_buffer_frames + 10
    finally:
        ctrl.stop()


def test_manual_burst_end_is_clamped_to_max_burst_s(tmp_path):
    session = _session(tmp_path)          # burst_duration_s 600 > max_burst_s 120
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, None)
    try:
        _feed(ctrl, cache, 3)
        ctrl.trigger_burst()
        import time
        remaining = ctrl._burst_end_mono - time.monotonic()
        assert remaining <= MAX_BURST_S + 1e-6
    finally:
        ctrl.stop()


def test_a_missing_frame_period_is_logged(tmp_path, monkeypatch):
    """A session without a frame period must not fall silently to 4 frames."""
    warnings: list[str] = []

    class _Log:
        def warning(self, msg, *args):
            warnings.append(msg % args if args else msg)

        def __getattr__(self, name):
            return lambda *a, **k: None

    monkeypatch.setattr(controller_mod, 'log', _Log())
    session = MonitorSession(
        session_id='no-period', start_time=datetime.now(), interval_s=3600.0,
        pre_buffer_frames=3, burst_duration_s=600.0, max_burst_s=600.0,
        session_dir=tmp_path / 's',
    )
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, None)
    try:
        _feed(ctrl, cache, 5)
        ctrl.trigger_burst()
    finally:
        ctrl.stop()
    assert any('frame period' in w for w in warnings), warnings

