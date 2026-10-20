"""One frame snapshot for each render tick.

The acquisition thread appends to the frame cache between two calls of one
render tick (no lock). Every view of the tick takes the snapshot, so a frame
appended between calls does not change what the tick shows, stores or
alarms on.
"""

from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim


class _LiveStream:
    active = True


def _collector(streaming=True):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    if streaming:
        dc.sensor = object()
        dc.stream = _LiveStream()
    return dc


def _feed(dc, running_rate, i, amp=1.0):
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(dc.config), running_rate=running_rate, seed=i)
    dc.receive_data({
        'data': np.column_stack([blocks[0] * amp, blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 19), 'rel_time': i * dc.config.acquisition_period,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def test_snapshot_of_an_empty_cache():
    snap = _collector().snapshot()
    assert snap.frames == () and snap.index == -1 and snap.frame == {}


def test_live_snapshot_shows_the_newest_frame():
    dc = _collector()
    for i in range(3):
        _feed(dc, 25.0, i)
    snap = dc.snapshot()
    assert snap.is_live and snap.index == 2
    assert snap.frame is dc.data['frame_cache'][-1]


def test_browse_snapshot_shows_the_cursor_frame():
    dc = _collector(streaming=False)
    for i in range(4):
        _feed(dc, 25.0, i)
    dc._cache_cursor = 2
    snap = dc.snapshot()
    assert not snap.is_live and snap.index == 1
    dc._cache_cursor = 99                      # clamped to the oldest frame
    assert dc.snapshot().index == 0


def test_an_appended_frame_does_not_change_the_snapshot_rpm():
    dc = _collector()
    _feed(dc, 25.0, 0)
    snap = dc.snapshot()
    before = dc.current_rpm(snap)
    assert before == pytest.approx(1500.0, rel=3e-3)
    _feed(dc, 40.0, 1)                         # the acquisition thread appends
    assert dc.current_rpm(snap) == before
    assert dc.current_rpm() == pytest.approx(2400.0, rel=3e-3)


def test_an_appended_frame_does_not_change_a_result_of_the_snapshot():
    dc = _collector()
    _feed(dc, 25.0, 0, amp=1.0)
    snap = dc.snapshot()
    first = dc.process_sample(0, snap.frame[0], snapshot=snap)
    _feed(dc, 40.0, 1, amp=3.0)
    again = dc.process_sample(0, snap.frame[0], snapshot=snap)
    assert again.overall == first.overall
    assert again.rpm == first.rpm
    np.testing.assert_array_equal(again.spectrum, first.spectrum)
