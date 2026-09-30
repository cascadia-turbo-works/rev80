"""An unusable tach reading counts as no reading.

'inconsistent' and 'unsteady' readings have an rpm, but the rpm is not
trustworthy. The speed gate must fail closed on them, as on a missing reading,
and the RPM trend must not record them. The frame is still displayed and
stored, and ChannelResult.rpm still shows the value.
"""

import dataclasses
from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80 import tach

RUNNING_RATE = 29.37
RPM = RUNNING_RATE * 60.0


class _LiveStream:
    active = True


def _streaming_collector():
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = 0.5
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    cfg.speed_gate_enabled = True
    cfg.speed_gate_rpm = RPM
    cfg.speed_gate_tolerance_pct = 3.0
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    dc.sensor = object()
    dc.stream = _LiveStream()
    return dc


def _feed(dc, quality=None):
    """Push one frame; optionally force the quality of its tach reading."""
    cfg = dc.config
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE, severity=1.0,
        vib_channel=0, tach_channel=1, seed=5)
    dc.receive_data({
        'data': np.column_stack([blocks[0], blocks[1]]), 'channels': [0, 1],
        'status': 'OKAY', 'timestamp': datetime(2026, 9, 1), 'rel_time': 0.0,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })
    frame = dc.data['frame_cache'][-1]
    if quality is not None:
        # Keep the cache key, so tach_for returns this reading unchanged.
        frame[1].tach = dataclasses.replace(frame[1].tach, quality=quality)
    return frame


def test_good_reading_passes_the_gate_and_is_trended():
    dc = _streaming_collector()
    frame = _feed(dc)
    assert frame[1].tach.quality == tach.QUALITY_OK
    res = dc.process_samples()[0]
    assert res.speed_ok is True
    assert dc.tach_trend[1]['rpm'].size == 1
    assert dc.tach_trend[1]['rpm'][0] == pytest.approx(RPM, rel=3e-3)


@pytest.mark.parametrize('quality',
                         [tach.QUALITY_UNSTEADY, tach.QUALITY_INCONSISTENT])
def test_unusable_reading_fails_the_gate_and_is_not_trended(quality):
    dc = _streaming_collector()
    _feed(dc, quality=quality)
    res = dc.process_samples()[0]
    assert res.speed_ok is False, 'an unusable reading must fail closed'
    assert dc.tach_trend[1]['rpm'].size == 0, 'no RPM trend point'
    # The frame is still displayed with its rpm.
    assert res.rpm == pytest.approx(RPM, rel=3e-3)


def test_unusable_reading_does_not_latch_the_reference():
    dc = _streaming_collector()
    dc.config.speed_gate_rpm = None
    _feed(dc, quality=tach.QUALITY_UNSTEADY)
    assert dc.process_samples()[0].speed_ok is False
    assert dc._speed_ref_rpm is None
