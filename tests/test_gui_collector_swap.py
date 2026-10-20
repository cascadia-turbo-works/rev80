"""A new DataCollector for every load and every connect.

State of the old data source must not survive a load: the latched speed
reference, the RPM trend, the stage-1 caches, the cache depth, the cursor.
A file that does not load leaves the collector on screen unchanged. A
connect after a file load uses the acquisition.yaml settings, not the
file's. The tests use a GUI shell with no dearpygui context.
"""

import inspect
from datetime import datetime

import dearpygui.dearpygui as dpg
import numpy as np
import pytest

import rev80
from rev80 import config as cfg_mod
from rev80 import simulation as sim
from rev80.gui import GUI
from pipeline_helpers import tick

RUNNING_RATE = 29.37


class _LiveStream:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


_WIDGET_METHODS = (
    '_update_results_section_visibility', '_update_connection_summary',
    '_update_spectrum_info', '_update_browse_label', '_set_device_status',
    '_set_stream_status', '_update_monitor_card', '_populate_siggen_tab',
    '_populate_tach_tab', '_repopulate_device_list', '_rebuild_device_channel_rows',
)


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    monkeypatch.setattr(dpg, 'does_item_exist', lambda tag: False)
    a = GUI.__new__(GUI)
    a._monitor = None
    a._num_channels = 4
    a._autoscale_pending = False
    a._browse_context = {}
    a._status_deadline = None
    a.registry = _NoRegistry()
    a.collector = rev80.DataCollector()
    a._waiting_text = None
    a._device_fault = None
    a._charts = _NullCharts()
    for name in _WIDGET_METHODS:
        monkeypatch.setattr(a, name, lambda *args, **kw: None)
    return a


class _NullCharts:
    """ChartsView with no widgets."""

    def __getattr__(self, name):
        return lambda *a, **k: None


class _NoRegistry:
    def find_by_id(self, sid):
        return None

    def add(self, sensor):
        pass


def _live_collector(maxfreq=1000.0):
    cfg = rev80.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = 0.5
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    cfg.speed_gate_enabled = True
    dc = rev80.DataCollector(config=cfg)
    dc.init_trend_channels()
    dc.sensor = object()
    dc.stream = _LiveStream()
    return dc


def _feed(dc, seed, rel_time):
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(dc.config), running_rate=RUNNING_RATE, severity=1.0, seed=seed)
    dc.receive_data({
        'data': np.column_stack([blocks[0], blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 1), 'rel_time': rel_time,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def _measurement_file(tmp_path, maxfreq=1000.0):
    dc = _live_collector(maxfreq)
    for i in range(3):
        _feed(dc, seed=5 + i, rel_time=float(i))
        tick(dc)
    path = tmp_path / 'm.h5'
    dc.save_data(path)
    return path


def _streamed(app, frames=3):
    dc = _live_collector()
    for i in range(frames):
        _feed(dc, seed=20 + i, rel_time=float(i))
        tick(dc)
    app.collector = dc
    return dc


def test_load_replaces_the_collector_and_drops_live_state(app, tmp_path):
    path = _measurement_file(tmp_path)
    old = _streamed(app)
    old.tach_trend[1] = {'rel_times': np.arange(5.0), 'rpm': np.full(5, 1762.0)}
    assert old._speed_ref_rpm is not None          # latched from the stream
    assert app._on_load_file(path) is True
    new = app.collector
    assert new is not old
    assert new._speed_ref_rpm is None
    # The RPM trend is the file's, not the live one.
    assert all(len(td['rpm']) <= 3 for td in new.tach_trend.values())
    assert len(new.data['frame_cache']) == 3
    # The old device was closed.
    assert old.sensor is None and old.stream is None


@pytest.mark.parametrize('content', [None, b'not an hdf5 file'])
def test_a_file_that_does_not_load_changes_nothing(app, tmp_path, content):
    old = _streamed(app)
    frames = list(old.data['frame_cache'])
    trend_len = len(old.trend[0]['rel_times'])
    path = tmp_path / 'bad.h5'
    if content is not None:
        path.write_bytes(content)
    assert app._on_load_file(path) is False
    assert app.collector is old
    assert list(old.data['frame_cache']) == frames
    assert all(a is b for a, b in zip(old.data['frame_cache'], frames))
    assert len(old.trend[0]['rel_times']) == trend_len
    assert old.sensor is not None                   # device not closed


def test_load_is_refused_while_recording(app, tmp_path):
    path = _measurement_file(tmp_path)
    old = _streamed(app)

    class _Recording:
        is_recording = True
    app._monitor = _Recording()
    assert app._on_load_file(path) is False
    assert app.collector is old


def test_connect_after_a_file_load_uses_acquisition_yaml(app, tmp_path, monkeypatch):
    path = _measurement_file(tmp_path, maxfreq=1000.0)
    assert app._on_load_file(path)
    assert app.collector.config.maxfreq == 1000.0   # the file's setting

    data = cfg_mod.load_acquisition_config()
    data['acquisition']['maxfreq'] = 2000.0
    cfg_mod.save_acquisition_config(data)

    loaded = app.collector
    sensor = rev80.VibeSensor.simulated()
    assert app._connect_device(sensor)
    assert app.collector is not loaded
    assert app.collector.config.maxfreq == 2000.0
    assert app.collector.sensor is sensor
    assert len(app.collector.data['frame_cache']) == 0
    app.collector.disconnect_sensor()


def test_connect_closes_the_old_device_first(app, monkeypatch):
    old = _streamed(app)
    order = []
    monkeypatch.setattr(old, 'disconnect_sensor',
                        lambda: order.append('close old'))
    real_build = app._build_live_collector

    def _build(sensor):
        order.append('open new')
        return real_build(sensor)
    monkeypatch.setattr(app, '_build_live_collector', _build)
    app._connect_device(rev80.VibeSensor.simulated())
    assert order[:2] == ['close old', 'open new']
    app.collector.disconnect_sensor()


def test_render_thread_swaps_a_pending_collector(app, tmp_path):
    path = _measurement_file(tmp_path)
    old = _streamed(app)
    new = rev80.DataCollector()
    new.load_data(path)
    app._pending_collector = new
    app._update_tach_tab = lambda: None
    app._check_status_timeout = lambda: None
    app._display_frame = lambda: None
    app._update_tach_cards = lambda: None
    app._poll_new_frames()
    assert app.collector is new
    assert app._pending_collector is None
    assert old.sensor is None


def test_collector_is_assigned_only_in_init_and_replace():
    src = inspect.getsource(GUI)
    assigned = [line.strip() for line in src.splitlines()
                if 'self.collector = ' in line]
    assert assigned == ['self.collector = rev80.DataCollector()',
                        'self.collector = new']


def test_reprocess_thread_does_not_use_the_collector_on_screen():
    src = inspect.getsource(GUI._on_sb_reprocess)
    assert 'self.collector' not in src
    assert 'self._pending_collector = fresh' in src


def test_connect_after_a_file_load_uses_charts_yaml_not_the_file_layout(app, tmp_path):
    """The layout of a file is the layout of that file only."""
    from rev80 import charts
    from rev80.charts import ChartSet, ChartSpec
    path = _measurement_file(tmp_path)
    assert app._on_load_file(path)
    assert app.collector.chart_set is not None     # the file's layout
    sensor = rev80.VibeSensor.simulated()
    assert app._connect_device(sensor)
    assert app.collector.chart_set is None         # no charts.yaml: the default
    app.collector.disconnect_sensor()

    live = ChartSet((ChartSpec('c7', 'spectrum', 'Live', channels=(0,), unit='mV',
                               amplitude_mode='RMS'),))
    cfg_mod.ensure_config_dir()
    charts.save_chart_set(cfg_mod.charts_config_path(), live)
    assert app._on_load_file(path)
    assert app._connect_device(rev80.VibeSensor.simulated())
    assert app.collector.chart_set == live
    app.collector.disconnect_sensor()


def test_live_data_on_screen(app, tmp_path):
    assert app._live_data_on_screen()              # start: nothing loaded
    assert app._on_load_file(_measurement_file(tmp_path))
    assert not app._live_data_on_screen()          # a file, no device
    app.collector.sensor = object()
    assert app._live_data_on_screen()              # a device is connected


def test_connect_moves_the_old_chart_settings_to_charts_yaml(app):
    """"Envelope analysis" and "Average spectrum" of an old acquisition.yaml."""
    data = cfg_mod.load_acquisition_config()
    data['acquisition'].update(envelope_enabled=True, averaging_enabled=True, n_averages=6)
    cfg_mod.save_acquisition_config(data)
    assert app._connect_device(rev80.VibeSensor.simulated())
    layout = app.collector.chart_set
    assert [c.chart_type for c in layout.charts] == ['waveform', 'spectrum', 'envelope']
    assert layout.charts[1].n_averages == 6
    assert cfg_mod.charts_config_path().exists()
    assert 'envelope_enabled' not in cfg_mod.load_acquisition_config()['acquisition']
    app.collector.disconnect_sensor()


# --- data files of another version (E2) ------------------------------------

def _set_file_version(path, version):
    import h5py
    with h5py.File(path, 'a') as f:
        attrs = f['metadata'].attrs
        attrs['version' if 'version' in attrs else 'file_version'] = version
        if 'rev80_version' in attrs:
            del attrs['rev80_version']


def test_an_older_measurement_file_is_refused_with_its_message(app, tmp_path, caplog):
    path = _measurement_file(tmp_path)
    _set_file_version(path, 5)
    old = _streamed(app)
    with caplog.at_level('ERROR'):
        assert app._on_load_file(path) is False
    assert app.collector is old
    msg = ' '.join(r.getMessage() for r in caplog.records if r.levelname == 'ERROR')
    assert 'Rev80 0.1.5' in msg and 'convert' in msg
    assert 'load failed' not in msg                 # the message stands alone


@pytest.fixture
def sessions_root(app, tmp_path, monkeypatch):
    """Two sessions under data_dir()/monitor: an old one (newer name) and a current one."""
    import shutil
    from test_monitor_session_load import _make_session, _record_session
    root = tmp_path / 'data'
    monkeypatch.setattr(rev80, 'data_dir', lambda: root)
    src = _make_session(tmp_path / 'src')
    _record_session(src, n_intervals=3, n_bursts=1)
    for name in ('2026-10-01_current', '2026-10-02_old'):
        shutil.copytree(src.session_dir, root / 'monitor' / name)
    _set_file_version(root / 'monitor' / '2026-10-02_old' / 'session.h5', 6)
    return root / 'monitor'


def test_the_session_browser_lists_an_old_session_with_its_reason(app, sessions_root):
    sessions = app._scan_session_dirs()
    by_id = {s['session_id']: s for s in sessions}
    assert set(by_id) == {'2026-10-01_current', '2026-10-02_old'}
    assert by_id['2026-10-01_current']['version_error'] == ''
    assert 'Rev80 0.1.5, or convert a copy' in by_id['2026-10-02_old']['version_error']


def test_selecting_an_old_session_changes_nothing(app, sessions_root, monkeypatch):
    old = _streamed(app)
    app._current_session_h5 = None
    app._sb_session_sel_ids = []
    app._sb_burst_sel_ids = []
    app._session_browser_burst_list = ['untouched']
    entry = {s['session_id']: s for s in app._scan_session_dirs()}['2026-10-02_old']
    app._on_session_list_select(user_data=entry)
    assert app.collector is old
    assert app._current_session_h5 is None          # Save config cannot reach it
    assert app._session_browser_burst_list == ['untouched']


def test_selecting_a_current_session_loads_it(app, sessions_root, monkeypatch):
    _streamed(app)
    app._current_session_h5 = None
    app._sb_session_sel_ids = []
    app._sb_burst_sel_ids = []
    monkeypatch.setattr(app, '_autoscale_plots', lambda *a, **k: None)
    monkeypatch.setattr(app, '_wire_session_sensors', lambda c: None)
    entry = {s['session_id']: s for s in app._scan_session_dirs()}['2026-10-01_current']
    app._on_session_list_select(user_data=entry)
    assert app._current_session_h5 == entry['session_h5']
    assert len(app.collector.data['frame_cache']) == 3


def test_save_config_never_patches_an_old_session(app, sessions_root):
    import hashlib
    h5 = sessions_root / '2026-10-02_old' / 'session.h5'
    sha = hashlib.sha256(h5.read_bytes()).hexdigest()
    app._current_session_h5 = h5
    app._on_sb_save_config()
    assert hashlib.sha256(h5.read_bytes()).hexdigest() == sha
