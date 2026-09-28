"""A monitor session must store a tachometer channel's edge times (D-2).

`_write_channel_group` is the single channel writer, shared by
`DataCollector.save_data` and `MonitorWriterThread`. It takes a `role=`
parameter and **defaults it to `'vibration'`**. `save_data` passed it; the
monitor writer did not, at either of its two call sites.

So every monitor session -- GUI or headless -- stored the tach channel's full
waveform: 25600 samples where 60 edge times would do, measured, on the one
code path that runs unattended for hours. It also lost the per-frame rpm,
quality and edge times that make the shaft speed a view on stored data, and
left the channel indistinguishable from a vibration one on load.

Decision D-2 held in measurement files and nowhere else. This file is the
regression: it drives a real `MonitorController` with a coherent
vibration + tachometer pair and reads the session back off disk.
"""

import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80.monitor import MonitorController, MonitorSession

RUNNING_RATE_HZ = 30.0
RPM = RUNNING_RATE_HZ * 60.0


def _session_h5(tmp_path):
    """Record a short monitor session from a coherent vibration+tach pair.

    The channel snapshot is written out by hand here rather than built by
    `monitor.session.channel_snapshot_for`: what is on trial is the writer's
    channel-group layout, and the test should not fail for a reason that
    lives in the snapshot builder.
    """
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()

    session = MonitorSession(
        session_id='tach-session', start_time=datetime.now(timezone.utc),
        interval_s=0.05, pre_buffer_frames=2, burst_duration_s=0.2,
        max_burst_s=1.0, session_dir=tmp_path / 'tach-session',
        acq_snapshot=cfg.to_dict(),
        channel_snapshot={
            '0': {'name': 'Motor DE', 'unit': 'mV', 'role': 'vibration'},
            '1': {'name': 'Keyphasor', 'unit': 'mV', 'role': 'tachometer'},
        },
        sensor_snapshot={},
    )
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(4):
        blocks = sim.GenerateMachineWithTach(
            sim._RawRateView(cfg), running_rate=RUNNING_RATE_HZ, seed=i)
        dc.receive_data({
            'data': np.column_stack([blocks[0], blocks[1]]),
            'channels': [0, 1], 'status': 'OKAY',
            'timestamp': datetime(2026, 9, 21), 'rel_time': float(i) * 0.5,
            'samplerate': cfg.raw_samplerate, 'overflow_mask': 0,
            'degraded': False,
        })
        ctrl.on_results(dc.process_samples(), dc.data['frame_cache'])
        time.sleep(0.06)
    ctrl.stop()
    for _ in range(50):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return session.session_h5


def test_a_tach_channel_stores_edge_times_not_a_waveform(tmp_path):
    with h5py.File(_session_h5(tmp_path), 'r') as f:
        caps = sorted(f['monitor'], key=int)
        assert caps, 'no interval capture was written'
        cap = f[f'monitor/{caps[0]}']
        assert 'data' in cap['0'], 'vibration still stores its waveform'
        assert 'data' not in cap['1'], 'a tach channel must not store a waveform'
        assert 'edge_times' in cap['1']


def test_the_stored_tach_group_carries_the_per_frame_reading(tmp_path):
    """What the waveform layout silently dropped. Without these a session's
    shaft speed cannot be re-derived at a different pulses/rev, which is the
    whole justification for storing edges rather than samples.
    """
    with h5py.File(_session_h5(tmp_path), 'r') as f:
        cap = f[f'monitor/{sorted(f["monitor"], key=int)[0]}']
        attrs = cap['1'].attrs
        assert attrs['rpm'] == pytest.approx(RPM, rel=5e-3)
        assert attrs['quality'] == 'ok'
        assert int(attrs['n_edges']) > 0
        assert int(attrs['pulses_per_rev']) == 1


def test_the_tach_group_is_orders_of_magnitude_smaller(tmp_path):
    """The size argument D-2 rests on, measured rather than asserted in the
    abstract: a 1 s block at the raw rate is 25600 samples against ~60 edges.
    """
    with h5py.File(_session_h5(tmp_path), 'r') as f:
        cap = f[f'monitor/{sorted(f["monitor"], key=int)[0]}']
        assert cap['0']['data'].size / cap['1']['edge_times'].size > 100


def test_role_of_sample_reads_the_role_off_the_sample_itself():
    """`MonitorWriterThread` runs off a queue and holds samples, not an
    `AcquisitionSettings`, so it cannot ask `config.role_for` the way
    `save_data` does. `receive_data` populates `sample.tach` for tach-role
    channels and nothing else, so the sample carries its own role --
    `monitor/controller.py` already relied on exactly this test.
    """
    from rev80.collector import role_of_sample

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE_HZ, seed=1)
    dc.receive_data({
        'data': np.column_stack([blocks[0], blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY', 'timestamp': datetime(2026, 9, 21),
        'rel_time': 0.0, 'samplerate': cfg.raw_samplerate,
        'overflow_mask': 0, 'degraded': False,
    })
    frame = dc.data['frame_cache'][-1]
    assert role_of_sample(frame[0]) == 'vibration'
    assert role_of_sample(frame[1]) == 'tachometer'
