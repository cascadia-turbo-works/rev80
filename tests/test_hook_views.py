"""Each anomaly hook reads its own view of the frame.

The RMS (EWMA baseline) hook has its own unit and amplitude mode; each fixed
limit reads the overall in its own unit and mode. The capture writer stores
the record view, in the unit that the channel snapshot names. Empty keys
are the record view: today's behaviour.
"""

import json
import logging
import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80.collector import FrameViews
from rev80.monitor import MonitorController
from rev80.monitor.anomaly import FixedThresholdHook, RmsThresholdHook
from rev80.monitor.session import session_from
from rev80.scope_sensor import ScopeSensor


class _LiveStream:
    active = True


def _collector(record_unit='in/s', record_mode='0-P', sensor=True):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0]
    cfg.channel_target_units = {0: record_unit}
    cfg.channel_amplitude_modes = {0: record_mode}
    dc = vc.DataCollector(config=cfg)
    if sensor:
        dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g',
                                           sensitivity=100.0, id='acc'))
    dc.init_trend_channels()
    dc.sensor = object()
    dc.stream = _LiveStream()
    return dc


def _block(dc, i, hf_g=0.0):
    """60.3 Hz at 0.5 g plus an optional 870.3 Hz component, in mV (100 mV/g)."""
    fs, n = dc.config.raw_samplerate, dc.config.raw_blocksize
    t = (np.arange(n) + i * n) / fs
    rng = np.random.default_rng(i)
    g = (0.5 * np.sin(2 * np.pi * 60.3 * t + 0.7)
         + hf_g * np.sin(2 * np.pi * 870.3 * t + 1.1)
         + 0.002 * rng.standard_normal(n))
    return 100.0 * g


def _feed(dc, i, hf_g=0.0):
    dc.receive_data({
        'data': _block(dc, i, hf_g)[:, None], 'channels': [0], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 19), 'rel_time': i * dc.config.acquisition_period,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def _views(dc):
    snap = dc.snapshot()
    dc.advance_frame(snap)
    return FrameViews(dc, snap)


def _rms(unit='', mode=''):
    return RmsThresholdHook(rms_threshold_pct=50.0, consecutive_n=1,
                            baseline_alpha=0.97, min_baseline_samples=3,
                            unit=unit, amplitude_mode=mode)


def test_rms_hook_in_g_fires_on_the_g_overall_of_an_in_s_channel():
    """A high-frequency defect doubles the g overall; the in/s overall barely moves."""
    dc = _collector(record_unit='in/s')
    in_g, in_rec = _rms('g'), _rms()
    fired_g = fired_rec = None
    for i in range(8):
        _feed(dc, i, hf_g=0.0 if i < 6 else 1.0)
        v = _views(dc)
        fired_g = fired_g or in_g.on_results(v, None)
        fired_rec = fired_rec or in_rec.on_results(v, None)
    assert fired_g is not None
    assert fired_rec is None
    # The baseline is kept in the hook's unit.
    snap = dc.snapshot()
    assert in_g.baseline_snapshot()[0] < dc.result_view(snap, 0, 'g').overall


def test_empty_keys_read_the_record_results_themselves():
    dc = _collector()
    _feed(dc, 0)
    v = _views(dc)
    assert v.results('', '') is v.record
    assert v.results(None, None) is v.record
    hook = _rms()
    hook.on_results(v, None)
    assert hook.baseline_snapshot()[0] == v.record[0].overall


def test_fixed_limit_in_0p_on_a_channel_recorded_in_pp():
    dc = _collector(record_unit='in/s', record_mode='P-P')
    _feed(dc, 0)
    v = _views(dc)
    pp = v.record[0].overall
    zp = dc.result_view(dc.snapshot(), 0, 'in/s', '0-P').overall
    assert zp == pytest.approx(pp / 2, rel=1e-12)
    limit = 0.75 * pp                       # between the 0-P and the P-P value
    as_0p = FixedThresholdHook(upper_limit=limit, upper_unit='in/s', upper_mode='0-P')
    as_record = FixedThresholdHook(upper_limit=limit, upper_unit='in/s')
    assert as_0p.on_results(v, None) is None
    assert as_record.on_results(v, None) is not None


def test_a_velocity_limit_works_on_a_channel_recorded_in_g():
    dc = _collector(record_unit='g')
    _feed(dc, 0, hf_g=1.0)                  # g reads about 2x the in/s number
    v = _views(dc)
    vel = dc.result_view(dc.snapshot(), 0, 'in/s').overall
    assert FixedThresholdHook(upper_limit=0.9 * vel, upper_unit='in/s').on_results(v, None)
    assert FixedThresholdHook(upper_limit=1.1 * vel, upper_unit='in/s').on_results(v, None) is None


def test_a_channel_with_no_sensor_is_skipped_with_one_warning(caplog):
    dc = _collector(record_unit='', sensor=False)
    hook = FixedThresholdHook(upper_limit=1e-9, upper_unit='in/s')
    with caplog.at_level(logging.WARNING, logger='rev80.monitor.anomaly'):
        for i in range(3):
            _feed(dc, i)
            assert hook.on_results(_views(dc), None) is None
    assert sum('Fixed threshold ch0' in r.getMessage() for r in caplog.records) == 1


def test_the_capture_stores_the_record_unit_with_a_hook_in_g(tmp_path):
    dc = _collector(record_unit='in/s')
    session = session_from(
        collector=dc, session_id='c1', interval_s=0.01, pre_buffer_s=1.0,
        burst_duration_s=1.0, max_burst_s=5.0, output_dir=tmp_path,
        start_time=datetime.now(timezone.utc))
    ctrl = MonitorController()
    ctrl.start(session, anomaly_hook=_rms('g'))
    stored_expected = []
    for i in range(3):
        _feed(dc, i)
        v = _views(dc)
        stored_expected.append(v.record[0].overall)
        ctrl.on_results(v, dc.data['frame_cache'])
        time.sleep(0.03)
    ctrl.stop()
    for _ in range(100):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    with h5py.File(session.session_h5, 'r') as f:
        mon = f['monitor']
        stored = [json.loads(mon[k].attrs['overall_json'])['0']
                  for k in sorted(mon.keys(), key=int)]
        assert f['metadata']['channels']['0'].attrs['target_unit'] == 'in/s'
    assert stored and all(s in stored_expected for s in stored)
    # 0.5 g at 60.3 Hz is 0.51 in/s: the two values differ by only 2 %.
    g = dc.result_view(dc.snapshot(), 0, 'g').overall
    assert stored[-1] != pytest.approx(g, rel=1e-3)
