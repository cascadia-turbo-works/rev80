"""A loaded session or burst trends the overalls that the live display showed.

Each stored capture and burst frame holds the five live mV orders of each
vibration channel (`orders_mv`). The loaded trend uses them. Calculated
again from the stored waveform with the stateless replay filter, the trend
read high near a low band edge: the live filter carries its state from
frame to frame, the replay filter cannot. A frame with no stored orders
(an older file, or a frame that was never processed live) is calculated
from its waveform.
"""

import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80.monitor import MonitorController
from rev80.monitor.session import session_from
from rev80.scope_sensor import ScopeSensor
from pipeline_helpers import tick

N_FRAMES = 8
TOL = 0.005                          # 0.5 % for every order


def _live():
    """A 2 Hz band edge, 1 Hz bins, in/s RMS record unit on a g sensor."""
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 1.0
    cfg.highpass_fc = 2.0
    cfg.enabled_channels = [0]
    cfg.channel_target_units = {0: 'in/s'}
    cfg.channel_amplitude_modes = {0: 'RMS'}
    dc = vc.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    dc.init_trend_channels()
    return dc


def _signal(cfg, n_frames):
    """Continuous mV: 0.6 Hz below the edge, 2.7 Hz near it, 47.3 Hz in band; off-bin, phased."""
    n = cfg.raw_blocksize
    t = np.arange(n * n_frames) / cfg.raw_samplerate
    x = (40.0 * np.sin(2 * np.pi * 0.6 * t + 0.9)
         + 25.0 * np.sin(2 * np.pi * 2.7 * t + 0.4)
         + 10.0 * np.sin(2 * np.pi * 47.3 * t + 1.3))
    return x.reshape(n_frames, n)


class _LiveStream:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


def _streaming(dc):
    """A collector that is live, so advance_frame runs."""
    dc.sensor = object()
    dc.stream = _LiveStream()
    return dc


def _key(data):
    """Identify a frame by its waveform: loaded rel_times are relative to the session."""
    return np.asarray(data[:16], dtype=np.float64).tobytes()


def _feed(dc, block, i):
    dc.receive_data({
        'data': block[:, None], 'channels': [0], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 20), 'rel_time': i * dc.config.acquisition_period,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


@pytest.fixture(scope='module')
def recorded(tmp_path_factory):
    """(session.h5, {rel_time: live orders}) with a burst."""
    tmp = tmp_path_factory.mktemp('orders')
    dc = _live()
    session = session_from(
        collector=dc, session_id='e1b', interval_s=0.01, pre_buffer_s=2.0,
        burst_duration_s=2.0, max_burst_s=10.0, output_dir=tmp,
        start_time=datetime.now(timezone.utc))
    ctrl = MonitorController()
    ctrl.start(session)
    live = {}
    for i, block in enumerate(_signal(dc.config, N_FRAMES)):
        _feed(dc, block, i)
        results = tick(dc)
        sample = dc.data['frame_cache'][-1][0]
        live[_key(sample.data)] = sample.overall_ampl_by_integration_order.copy()
        ctrl.on_results(results, dc.data['frame_cache'])
        if i == 3:
            ctrl.trigger_burst()
        time.sleep(0.03)
    ctrl.stop()
    for _ in range(100):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return session.session_h5, live


def _loaded(path, loader):
    dc = vc.DataCollector()
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    if loader == 'session':
        dc.load_monitor_session(path)
    else:
        with h5py.File(path, 'r') as f:
            burst_id = next(iter(f['burst'].keys()))
        dc.load_monitor_burst(path, burst_id)
    return dc


def _assert_live(dc, live, minimum):
    frames = list(dc.data['frame_cache'])
    orders = dc.trend[0]['orders']
    assert len(orders) == len(frames) >= minimum
    for i, (frame, row) in enumerate(zip(frames, orders)):
        np.testing.assert_allclose(row, live[_key(frame[0].data)], rtol=TOL,
                                   err_msg=f'frame {i}')


@pytest.mark.parametrize('loader', ['session', 'burst'])
def test_the_loaded_trend_is_the_live_overall_for_every_order(recorded, loader):
    path, live = recorded
    with h5py.File(path, 'r') as f:
        if loader == 'burst' and not len(f.get('burst', {})):
            pytest.fail('the burst was not written')
    _assert_live(_loaded(path, loader), live, minimum=3)


def test_each_capture_stores_the_live_orders(recorded):
    path, live = recorded
    with h5py.File(path, 'r') as f:
        for key in f['monitor']:
            grp = f['monitor'][key]
            stored = grp['0'].attrs['orders_mv']
            want = live[_key(grp['0']['data'][:16])]
            np.testing.assert_array_equal(stored, want)


def test_a_frame_without_stored_orders_is_calculated_from_its_waveform(recorded, tmp_path):
    path, live = recorded
    old = tmp_path / 'old.h5'
    old.write_bytes(path.read_bytes())
    with h5py.File(old, 'a') as f:
        del f['monitor']['1']['0'].attrs['orders_mv']
    dc = _loaded(old, 'session')
    frames = list(dc.data['frame_cache'])
    replay = dc._stored_orders([frames[1][0]])[0]
    np.testing.assert_array_equal(dc.trend[0]['orders'][1], replay)
    for i, frame in enumerate(frames):
        if i != 1:
            np.testing.assert_allclose(dc.trend[0]['orders'][i], live[_key(frame[0].data)],
                                       rtol=TOL)


# ---------------------------------------------------------------------------
# The stored overalls are valid only for the settings that computed them
# ---------------------------------------------------------------------------

def test_the_card_of_a_loaded_frame_equals_its_trend_point(recorded):
    from pipeline_helpers import view_of
    path, _ = recorded
    dc = _loaded(path, 'session')
    for unit in ('in/s', 'g', 'mil'):
        dc.config.channel_target_units[0] = unit
        _, values = dc.get_trend_for_display()[0]
        for v, frame in zip(values, dc.data['frame_cache']):
            assert view_of(dc, 0, frame[0]).overall == pytest.approx(v, rel=1e-9)


def test_pre_trigger_frames_of_an_old_band_are_not_used(tmp_path):
    """Frames cached before a band change keep the overalls of the old band."""
    dc = _live()
    blocks = _signal(dc.config, 8)
    for i in range(5):
        _feed(dc, blocks[i], i)
        tick(dc)
    dc.config.highpass_fc = 10.0                    # changed, then the recording starts
    session = session_from(
        collector=dc, session_id='band', interval_s=60.0, pre_buffer_s=8.0,
        burst_duration_s=2.0, max_burst_s=10.0, output_dir=tmp_path,
        start_time=datetime.now(timezone.utc))
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(5, 8):
        _feed(dc, blocks[i], i)
        results = tick(dc)
        ctrl.on_results(results, dc.data['frame_cache'])
        if i == 5:
            ctrl.trigger_burst()
        time.sleep(0.03)
    ctrl.stop()
    loaded = _loaded(session.session_h5, 'burst')
    frames = list(loaded.data['frame_cache'])
    assert len(frames) >= 6
    # Every point is for the declared band (10 Hz). Far from 2 Hz, the replay
    # and the live overall agree closely, so a point of the old band
    # (about 46 times higher in velocity) fails this.
    bare = [vc.VibeSample(status='OK', _timestamp=datetime.now(), samplerate=f[0].samplerate,
                          unit='mV', overflow=False, data=f[0].data) for f in frames]
    replay = loaded._stored_orders(bare)
    np.testing.assert_allclose(loaded.trend[0]['orders'], replay, rtol=0.05)
    # The frames of the new band use their stored live overalls.
    assert any(loaded.stored_orders_valid(f[0]) for f in frames)
    assert not all(loaded.stored_orders_valid(f[0]) for f in frames)


def test_a_frame_that_was_not_shown_gets_its_live_overalls(tmp_path):
    """A render stall: two frames arrive between ticks."""
    dc = _streaming(_live())
    blocks = _signal(dc.config, 6)
    for i in (0, 1):
        _feed(dc, blocks[i], i)
        tick(dc)
    _feed(dc, blocks[2], 2)                          # never shown
    _feed(dc, blocks[3], 3)
    tick(dc)
    skipped = dc.data['frame_cache'][-2][0]
    assert skipped._orders_from_stream
    # The same as if it had been shown.
    ref = _streaming(_live())
    for i in range(3):
        _feed(ref, blocks[i], i)
        tick(ref)
    np.testing.assert_array_equal(skipped.overall_ampl_by_integration_order,
                                  ref.data['frame_cache'][-1][0].overall_ampl_by_integration_order)


def test_reprocess_keeps_the_live_overall(recorded, tmp_path):
    path, _ = recorded
    copy = tmp_path / 'r.h5'
    copy.write_bytes(path.read_bytes())
    dc = _loaded(copy, 'session')
    dc.reprocess_session_trend(copy)
    _, values = dc.get_trend_for_display()[0]
    import json
    with h5py.File(copy, 'r') as f:
        mon = f['monitor']
        stored = [json.loads(mon[k].attrs['overall_json'])['0']
                  for k in sorted(mon.keys(), key=int)]
    np.testing.assert_allclose(stored, values, rtol=1e-9)


def test_a_save_of_a_loaded_session_keeps_the_stored_overalls(recorded, tmp_path):
    path, _ = recorded
    dc = _loaded(path, 'session')
    out = tmp_path / 'm.h5'
    dc.save_data(out)
    with h5py.File(out, 'r') as f:
        groups = [f['frames'][k]['0'] for k in f['frames']]
        assert groups and all('orders_mv' in g.attrs and 'orders_key' in g.attrs
                              for g in groups)
