"""The Monitor widgets hold the acquisition.yaml values from startup.

The widgets have construction defaults (1 h interval, 60 s pre-trigger, 60 s
burst, anomaly off, 10 % RMS threshold, 30 warm-up frames, spec_n 3). Before
the fix, only an open of the Monitor tab loaded the config into them. Thus:

- a close of the config dialog on any other tab wrote the construction
  defaults over the monitor block of acquisition.yaml;
- a recording started without an open of the Monitor tab used the
  construction defaults, not the config.

These tests use a fake dpg with a widget store and no DPG context.
"""

import pytest
import yaml

import rev80.config as cfg_mod
import rev80.gui as gui_module
from rev80.gui import GUI
from rev80.monitor.anomaly import CompositeAnomalyHook, RmsThresholdHook
from rev80.sample import AcquisitionSettings
from rev80.util import UI_Elements as ui

# The construction defaults of the Monitor widgets in GUI._create_gui.
_CONSTRUCTION_DEFAULTS = {
    ui.MON_DLG_INTERVAL: '1 h',
    ui.MON_DLG_PRE_BUFFER: 60.0,
    ui.MON_DLG_BURST_DUR: 60.0,
    ui.MON_DLG_OUTPUT_DIR: '',
    ui.MON_DLG_COMPRESS: True,
    ui.MON_DLG_ESTIMATE: '',
    ui.MON_ANOM_ENABLED: False,
    ui.MON_ANOM_HOOK: 'RMS',
    ui.MON_ANOM_RMS_PCT: 10.0,
    ui.MON_ANOM_RMS_S: 3.0,
    ui.MON_ANOM_RMS_EWMA_TIME: 60.0,
    ui.MON_ANOM_RMS_WARMUP: 30,
    ui.MON_ANOM_SPEC_PCT: 50.0,
    ui.MON_ANOM_SPEC_N: 3,
    ui.MON_ANOM_SPEC_FMIN: 0.0,
    ui.MON_ANOM_SPEC_FMAX: 0.0,
    ui.MON_ANOM_SPEC_EWMA_TIME: 300.0,
    ui.MON_ANOM_FIXED_UPPER_ENABLED: False,
    ui.MON_ANOM_FIXED_UPPER_VALUE: 1.0,
    ui.MON_ANOM_FIXED_UPPER_UNIT: 'in/s',
    ui.MON_ANOM_FIXED_LOWER_ENABLED: False,
    ui.MON_ANOM_FIXED_LOWER_VALUE: 0.05,
    ui.MON_ANOM_FIXED_LOWER_UNIT: 'in/s',
    ui.MON_ANOM_COOLDOWN_ENABLED: False,
    ui.MON_ANOM_COOLDOWN_S: 300.0,
}

# A user config that differs from the seed and from the widget defaults.
_USER_MONITOR = {
    'interval_s': 900,
    'pre_burst_s': 45,
    'burst_duration_s': 200,
    'max_burst_s': 1234,
    'output_dir': None,
    'compression': 'none',
    'compression_level': 4,
    'anomaly': {
        'enabled': True,
        'hook_type': 'rms',
        'warmup': 20,
        'rms_pct': 70.0,
        'rms_s': 2.0,
        'rms_alpha': 0.9,
        'spec_pct': 40.0,
        'spec_alpha': 0.995,
        'spec_n': 5,
        'spec_fmin': None,
        'spec_fmax': None,
        'cooldown_enabled': True,
        'cooldown_s': 120.0,
        'fixed_upper_enabled': False,
        'fixed_upper_value': 1.0,
        'fixed_upper_unit': 'in/s',
        'fixed_lower_enabled': False,
        'fixed_lower_value': 0.05,
        'fixed_lower_unit': 'in/s',
    },
}


class _FakeDpg:
    """A widget store. A widget exists when it has a value."""

    def __init__(self):
        self.store: dict = {}

    def does_item_exist(self, tag):
        return tag in self.store

    def get_value(self, tag):
        return self.store[tag]

    def set_value(self, tag, value):
        self.store[tag] = value

    def configure_item(self, tag, **kw):
        pass

    def setup_dearpygui(self):
        pass


class _FakeCollector:
    def __init__(self):
        self.config = AcquisitionSettings()


@pytest.fixture
def fake_dpg(monkeypatch):
    fake = _FakeDpg()
    monkeypatch.setattr(gui_module, 'dpg', fake)
    return fake


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    """acquisition.yaml in a temporary config directory, with _USER_MONITOR."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    cfg_mod.ensure_config_dir()
    data = cfg_mod.load_acquisition_config()
    data['monitor'] = _USER_MONITOR
    cfg_mod.save_acquisition_config(data)
    return cfg_mod.load_acquisition_config()['monitor']


def _started_app(fake_dpg) -> GUI:
    """Run GUI.initialize with a _create_gui that makes the widgets only."""
    app = GUI.__new__(GUI)
    app.collector = _FakeCollector()

    def _create_gui():
        fake_dpg.store.update(_CONSTRUCTION_DEFAULTS)

    app._create_gui = _create_gui
    for name in ('_setup_keyboard_handlers', '_update_spectrum_info',
                 '_update_connection_summary', '_update_axis_assignment',
                 '_refresh_registry_dialog_list', '_set_stream_status'):
        setattr(app, name, lambda *a, **k: None)
    app.initialize()
    return app


def test_recording_parameters_equal_the_config_after_startup(fake_dpg, user_config):
    app = _started_app(fake_dpg)
    params = app._monitor_session_params()
    assert params['interval_s'] == float(user_config['interval_s'])
    assert params['pre_buffer_s'] == float(user_config['pre_burst_s'])
    assert params['burst_duration_s'] == float(user_config['burst_duration_s'])
    assert params['compression'] == user_config['compression']
    assert params['cooldown_enabled'] == user_config['anomaly']['cooldown_enabled']
    assert params['cooldown_s'] == user_config['anomaly']['cooldown_s']
    assert params['max_burst_s'] == float(user_config['max_burst_s'])


def test_anomaly_hook_uses_the_config_after_startup(fake_dpg, user_config):
    app = _started_app(fake_dpg)
    hook = app._build_anomaly_hook(pre_buffer_s=45.0)
    leaves = list(hook._hooks) if isinstance(hook, CompositeAnomalyHook) else [hook]
    (rms,) = [h for h in leaves if isinstance(h, RmsThresholdHook)]
    anom = user_config['anomaly']
    assert rms._threshold_frac == pytest.approx(anom['rms_pct'] / 100.0)
    assert rms._min_samples == anom['warmup']
    assert rms._burst_duration_s == float(user_config['burst_duration_s'])


def test_dialog_close_without_monitor_tab_keeps_the_monitor_block(fake_dpg, user_config):
    """_on_config_close calls _save_monitor_config on every close."""
    app = _started_app(fake_dpg)
    app._save_monitor_config()
    assert cfg_mod.load_acquisition_config()['monitor'] == user_config


def test_save_keeps_keys_that_have_no_widget(fake_dpg, user_config):
    app = _started_app(fake_dpg)
    app._save_monitor_config()
    with open(cfg_mod.acquisition_config_path()) as f:
        raw = yaml.safe_load(f)['monitor']
    assert raw['max_burst_s'] == 1234
    assert raw['anomaly']['rms_alpha'] == 0.9


@pytest.mark.parametrize('stored, label, expected', [
    (900, '15 min', 900.0),     # a preset
    (1000, '15 min', 1000.0),   # not a preset; the widget shows the nearest
    (1000, '1 h', 3600.0),      # the user selected another preset
    (600, 'not a label', 600.0),
])
def test_interval_to_save(stored, label, expected):
    assert gui_module.interval_to_save(label, stored) == expected


def test_save_does_not_add_an_ewma_time(fake_dpg, user_config):
    """Headless uses an EWMA time before an alpha: an added one changes it."""
    app = _started_app(fake_dpg)
    app._save_monitor_config()
    anom = cfg_mod.load_acquisition_config()['monitor']['anomaly']
    assert 'rms_ewma_time' not in anom
    assert 'spec_ewma_time' not in anom


def test_save_writes_an_ewma_time_that_the_user_changed(fake_dpg, user_config):
    app = _started_app(fake_dpg)
    fake_dpg.store[ui.MON_ANOM_RMS_EWMA_TIME] = 120.0
    app._save_monitor_config()
    anom = cfg_mod.load_acquisition_config()['monitor']['anomaly']
    assert anom['rms_ewma_time'] == 120.0
    assert 'spec_ewma_time' not in anom


def test_fallbacks_agree_with_the_config_seed(tmp_path, monkeypatch):
    """With no widgets and no config file, the parameters are the seed values."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    fake = _FakeDpg()
    monkeypatch.setattr(gui_module, 'dpg', fake)
    app = GUI.__new__(GUI)
    app.collector = _FakeCollector()
    seed = cfg_mod._BUILTIN_ACQ['monitor']
    params = app._monitor_session_params()
    assert params['interval_s'] == float(seed['interval_s'])
    assert params['pre_buffer_s'] == float(seed['pre_burst_s'])
    assert params['burst_duration_s'] == float(seed['burst_duration_s'])
    assert params['max_burst_s'] == float(seed['max_burst_s'])
