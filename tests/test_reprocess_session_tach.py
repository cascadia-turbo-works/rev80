"""`reprocess_session_trend` must accept a session with a tachometer channel.

The monitor writer stores edge times for a tachometer channel, not a `data`
dataset. The reprocess step must skip that channel group, in the interval
captures and in the burst frames, and write an overall for the vibration
channel only.
"""

import json
import time
from datetime import datetime, timezone

import h5py
import numpy as np

import rev80 as vc
from rev80 import simulation as sim
from rev80.monitor import MonitorController, MonitorSession

RUNNING_RATE_HZ = 30.0


def _frame(cfg, i):
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE_HZ, seed=i)
    return {
        'data': np.column_stack([blocks[0], blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 21), 'rel_time': float(i) * 0.5,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0,
        'degraded': False,
    }


def _record_session(tmp_path):
    """Record a vibration + tachometer session with one manual burst."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()

    session = MonitorSession(
        session_id='tach-reprocess', start_time=datetime.now(timezone.utc),
        interval_s=0.05, pre_buffer_frames=2, burst_duration_s=0.2,
        max_burst_s=1.0, session_dir=tmp_path / 'tach-reprocess',
        acq_snapshot=cfg.to_dict(),
        channel_snapshot={
            '0': {'name': 'Motor DE', 'unit': 'mV', 'role': 'vibration'},
            '1': {'name': 'Keyphasor', 'unit': 'mV', 'role': 'tachometer'},
        },
        sensor_snapshot={},
    )
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(8):
        dc.receive_data(_frame(cfg, i))
        ctrl.on_results(dc.process_samples(), dc.data['frame_cache'])
        if i == 2:
            ctrl.trigger_burst()
        time.sleep(0.06)
    ctrl.stop()
    for _ in range(50):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return dc, session.session_h5


def test_reprocess_skips_the_tach_channel_in_captures_and_bursts(tmp_path):
    dc, h5 = _record_session(tmp_path)

    with h5py.File(h5, 'r') as f:
        assert len(f['monitor']) > 0, 'no interval capture was written'
        assert 'burst' in f and len(f['burst']) > 0, 'no burst was written'
        cap = f['monitor'][sorted(f['monitor'], key=int)[0]]
        assert 'data' not in cap['1'], 'precondition: tach group has no data'

    n = dc.reprocess_session_trend(h5)

    with h5py.File(h5, 'r') as f:
        assert n == len(f['monitor'])
        for key in f['monitor']:
            overall = json.loads(f['monitor'][key].attrs['overall_json'])
            assert set(overall) == {'0'}
        burst_frames = [
            fi_grp
            for bid_grp in f['burst'].values()
            for k, fi_grp in bid_grp.items() if k.isdigit()
        ]
        assert burst_frames, 'the burst holds no frame groups'
        for fi_grp in burst_frames:
            overall = json.loads(fi_grp.attrs['overall_json'])
            assert set(overall) == {'0'}
