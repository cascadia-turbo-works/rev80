"""A GUI monitor session uses monitor.compression_level from acquisition.yaml.

The level has no widget. Headless reads it; the GUI used the MonitorSession
default (4) for every session. The fake dpg here has a widget store and no
DPG context, as in test_gui_monitor_config.py.
"""

import pytest

import rev80 as vc
import rev80.config as cfg_mod
import rev80.gui as gui_module
from rev80.gui import GUI
from rev80.monitor.session import session_from


class _FakeDpg:
    def __init__(self):
        self.store: dict = {}

    def does_item_exist(self, tag):
        return tag in self.store

    def get_value(self, tag):
        return self.store[tag]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    monkeypatch.setattr(gui_module, 'dpg', _FakeDpg())
    cfg_mod.ensure_config_dir()
    a = GUI.__new__(GUI)
    a.collector = vc.DataCollector()
    return a


def _set_level(level):
    data = cfg_mod.load_acquisition_config()
    data['monitor'] = {**data.get('monitor', {}), 'compression_level': level}
    cfg_mod.save_acquisition_config(data)


def test_session_parameters_carry_the_configured_level(app):
    _set_level(7)
    params = app._monitor_session_params()
    assert params['compression_level'] == 7
    session = session_from(collector=app.collector, session_id='t', **params)
    assert session.compression_level == 7


def test_missing_level_gives_the_config_seed(app):
    data = cfg_mod.load_acquisition_config()
    data['monitor'] = {k: v for k, v in data.get('monitor', {}).items()
                       if k != 'compression_level'}
    cfg_mod.save_acquisition_config(data)
    seed = cfg_mod._BUILTIN_ACQ['monitor']['compression_level']
    assert app._monitor_session_params()['compression_level'] == seed
