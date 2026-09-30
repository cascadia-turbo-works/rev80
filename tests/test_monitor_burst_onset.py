"""An anomaly burst's trigger time describes the stored frame at n_pretrigger.

The frame at index n_pretrigger is frame_cache[-1] when the hook fires: the
frame that confirms the anomaly. A sustained hook reports the onset, which
can be the sustain time earlier. The trigger timestamp and rel_time must be
those of the stored frame, and the onset goes in a separate attribute.
"""

import json
from collections import deque
from datetime import datetime, timedelta

import h5py
import pytest

import rev80 as vc
from rev80.monitor.anomaly import AnomalyEvent
from rev80.monitor.controller import MonitorController
from test_monitor_burst_cap import _feed, _session

ONSET_LEAD_S = 10.0


class _SustainedHook:
    """Fire once, with an onset ONSET_LEAD_S before the confirming frame."""

    def __init__(self) -> None:
        self.fire = False
        self.event: AnomalyEvent | None = None

    def on_results(self, results, frame_cache):
        if not self.fire:
            return None
        self.fire = False
        self.event = AnomalyEvent(
            trigger_time=datetime.now() - timedelta(seconds=ONSET_LEAD_S),
            channel=0, reason='sustained', burst_duration_s=600.0,
            # A time on another clock: it must not reach the file as t = 0.
            trigger_rel_time=12345.0,
        )
        return self.event


def _record(tmp_path):
    session = _session(tmp_path)
    hook = _SustainedHook()
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, hook)
    try:
        _feed(ctrl, cache, 35)
        hook.fire = True
        _feed(ctrl, cache, 1)
        assert ctrl._in_burst
        _feed(ctrl, cache, 3)
    finally:
        ctrl.stop()
    return session, hook.event


def test_trigger_time_is_the_confirming_frame(tmp_path):
    session, event = _record(tmp_path)
    with h5py.File(session.session_h5, 'r') as f:
        burst_list = json.loads(f['burst'].attrs['burst_list'])
        bid = f['burst'][burst_list[0]['burst_id']]
        # The trigger frame also went to /monitor as an interval capture,
        # with the same session rel_time.
        last_interval = f['monitor'][str(len(f['monitor']) - 1)]
        trigger_rel = float(bid.attrs['trigger_rel_time'])
        assert trigger_rel == pytest.approx(float(last_interval.attrs['rel_time']))
        assert float(burst_list[0]['rel_time']) == pytest.approx(trigger_rel)

        trigger_ts = datetime.fromisoformat(bid.attrs['trigger_timestamp'])
        assert abs((datetime.now() - trigger_ts).total_seconds()) < 5

        assert bid.attrs['onset_timestamp'] == event.trigger_time.isoformat()
        onset_ts = datetime.fromisoformat(bid.attrs['onset_timestamp'])
        assert (trigger_ts - onset_ts).total_seconds() == pytest.approx(
            ONSET_LEAD_S, abs=1.0)


def test_load_monitor_burst_puts_the_stored_trigger_frame_at_zero(tmp_path):
    session, _ = _record(tmp_path)
    with h5py.File(session.session_h5, 'r') as f:
        burst_id = json.loads(f['burst'].attrs['burst_list'])[0]['burst_id']
        n_pre = int(f['burst'][burst_id].attrs['n_pretrigger_frames'])
    assert n_pre == session.pre_buffer_frames - 1

    col = vc.DataCollector()
    col.config.maxfreq, col.config.binsize = 1000.0, 1.0
    col.config.enabled_channels = [0]
    col.init_trend_channels()
    col.load_monitor_burst(session.session_h5, burst_id)
    frames = list(col.data['frame_cache'])
    assert frames[n_pre][0].rel_time == pytest.approx(0.0)


def test_manual_burst_has_no_onset_attribute(tmp_path):
    session = _session(tmp_path)
    ctrl = MonitorController()
    cache: deque = deque(maxlen=64)
    ctrl.start(session, None)
    try:
        _feed(ctrl, cache, 5)
        ctrl.trigger_burst()
        _feed(ctrl, cache, 2)
    finally:
        ctrl.stop()
    with h5py.File(session.session_h5, 'r') as f:
        burst_id = json.loads(f['burst'].attrs['burst_list'])[0]['burst_id']
        assert 'onset_timestamp' not in f['burst'][burst_id].attrs
