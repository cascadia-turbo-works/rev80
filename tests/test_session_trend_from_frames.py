"""Session and burst trends are rebuilt from the stored frames.

The loaders rebuilt the trend from `overall_json`, which holds one value in
the record unit, into one order column. The other four columns stayed 0.0,
so a session recorded in in/s and shown in g or mil read 0.0 on every
point. The trend now holds the five live mV orders stored with each frame.
A frame with no waveform gives NaN, never 0.0. The shaft-speed trend holds
the usable readings of the stored edge times.
"""

import json
import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80.monitor import MonitorController
from rev80.monitor.session import session_from
from rev80.scope_sensor import ScopeSensor
from pipeline_helpers import tick, view_of

RUNNING_RATE_HZ = 29.37
N_FRAMES = 6
FRAME_S = 0.5


def _live(record_unit='in/s', mode='RMS'):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    cfg.channel_target_units = {0: record_unit}
    cfg.channel_amplitude_modes = {0: mode}
    dc = vc.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g',
                                       sensitivity=100.0))
    dc.init_trend_channels()
    return dc


def _feed(dc, i):
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(dc.config), running_rate=RUNNING_RATE_HZ, seed=40 + i)
    dc.receive_data({
        'data': np.column_stack([blocks[0] * 100.0, blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 19), 'rel_time': i * FRAME_S,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0,
        'degraded': False,
    })


@pytest.fixture(scope='module')
def session_h5(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('sess')
    dc = _live()
    session = session_from(
        collector=dc, session_id='a3', interval_s=0.01, pre_buffer_s=1.0,
        burst_duration_s=1.0, max_burst_s=5.0, output_dir=tmp,
        start_time=datetime.now(timezone.utc))
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(N_FRAMES):
        _feed(dc, i)
        ctrl.on_results(tick(dc), dc.data['frame_cache'])
        if i == 2:
            ctrl.trigger_burst()
        time.sleep(0.03)
    ctrl.stop()
    for _ in range(100):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return session.session_h5


def _loaded(path, loader='session'):
    dc = vc.DataCollector()
    if loader == 'session':
        dc.load_monitor_session(path)
    else:
        with h5py.File(path, 'r') as f:
            burst_id = next(iter(f['burst'].keys()))
        dc.load_monitor_burst(path, burst_id)
    for ch, d in dc._loaded_channel_sensor_configs.items():
        if d:
            dc.set_scope_sensor(ch, ScopeSensor.from_dict(d))
    return dc


def _stored_overalls(path):
    with h5py.File(path, 'r') as f:
        mon = f['monitor']
        return [json.loads(mon[k].attrs['overall_json'])['0']
                for k in sorted(mon.keys(), key=int)]


def test_record_unit_trend_equals_the_stored_overall(session_h5):
    dc = _loaded(session_h5)
    _, values = dc.get_trend_for_display()[0]
    stored = _stored_overalls(session_h5)
    assert len(values) == len(stored) >= 3
    # The trend is the stored live orders, so it equals the stored overall.
    np.testing.assert_allclose(values, stored, rtol=1e-9)


@pytest.mark.parametrize('unit, steps', [('g', 1), ('mil', -1), ('mm/s2', 1)])
def test_every_unit_shows_a_value_not_zero(session_h5, unit, steps):
    dc = _loaded(session_h5)
    dc.config.channel_target_units[0] = unit
    _, values = dc.get_trend_for_display()[0]
    assert values and all(np.isfinite(v) and v > 0.0 for v in values), values
    # Each point equals that frame's overall, processed in the new unit: the
    # trend point and the card of a loaded frame agree.
    frames = list(dc.data['frame_cache'])
    for v, frame in zip(values, frames):
        ref = view_of(dc, 0, frame[0])
        assert v == pytest.approx(ref.overall, rel=1e-9)


def test_loaded_frames_keep_no_stage1_arrays(session_h5):
    dc = vc.DataCollector()
    dc.load_monitor_session(session_h5)
    frames = list(dc.data['frame_cache'])
    # Nothing has rendered yet, so no frame has been processed for display.
    for frame in frames:
        assert frame[0].decimated_mv is None
        assert frame[0].filtered_mv is None


def test_a_frame_with_no_waveform_is_nan_not_zero(session_h5, tmp_path):
    damaged = tmp_path / 'damaged.h5'
    damaged.write_bytes(session_h5.read_bytes())
    with h5py.File(damaged, 'a') as f:
        del f['monitor']['1']['0']['data']
    dc = _loaded(damaged)
    for unit in ('in/s', 'g'):
        dc.config.channel_target_units[0] = unit
        _, values = dc.get_trend_for_display()[0]
        assert np.isnan(values[1])
        assert all(np.isfinite(v) and v > 0 for i, v in enumerate(values) if i != 1)


def test_session_rpm_trend_from_the_stored_edges(session_h5):
    dc = _loaded(session_h5)
    rel, rpm = dc.get_rpm_trend()[1]
    assert len(rpm) == len(dc.data['frame_cache'])
    np.testing.assert_allclose(rpm, RUNNING_RATE_HZ * 60.0, rtol=2e-3)


def test_burst_trend_from_frames(session_h5):
    with h5py.File(session_h5, 'r') as f:
        if 'burst' not in f or not len(f['burst']):
            pytest.skip('burst not written')
    dc = _loaded(session_h5, loader='burst')
    dc.config.channel_target_units[0] = 'g'
    rel, values = dc.get_trend_for_display()[0]
    assert len(values) == len(dc.data['frame_cache']) >= 2
    assert all(np.isfinite(v) and v > 0 for v in values)
    _, rpm = dc.get_rpm_trend()[1]
    assert len(rpm) == len(values)


def test_crest_and_kurtosis_trend_from_scalars_json(session_h5):
    dc = _loaded(session_h5)
    with h5py.File(session_h5, 'r') as f:
        mon = f['monitor']
        stored = [json.loads(mon[k].attrs['scalars_json'])['0']['kurtosis']
                  for k in sorted(mon.keys(), key=int)]
    np.testing.assert_allclose(dc.trend[0]['kurtosis'], stored)
