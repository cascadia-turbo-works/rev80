"""The monitor records only live frames, and a recording locks file access.

A file load or a cache browse during a recording puts frames that are not
live measurements through _display_frame. They must not go into the
session. File load (button and Ctrl+O), session browse and clear-cache are
refused while a recording runs. These tests use a GUI shell with no DPG
context.
"""

import inspect
import logging

import dearpygui.dearpygui as dpg
import pytest

from rev80.gui import GUI
from rev80.util import UI_Elements as ui


class _FakeMonitor:
    def __init__(self, recording: bool = True) -> None:
        self.is_recording = recording
        self.calls: list = []

    def on_results(self, results, frame_cache) -> None:
        self.calls.append(results)


class _FakeCollector:
    def __init__(self, streaming: bool) -> None:
        self.is_streaming = streaming
        self.data = {'frame_cache': []}
        self.resets = 0

    def process_samples(self):
        return []

    def current_frame(self):
        return {}

    def reset_data_store(self):
        self.resets += 1


def _app(monitor=None, streaming=True) -> GUI:
    app = GUI.__new__(GUI)
    app._monitor = monitor
    app.collector = _FakeCollector(streaming)
    app._autoscale_pending = False
    for name in ('_set_stream_status', '_schedule_status_timeout',
                 '_update_trend_plot', '_update_browse_label',
                 '_update_frame_info', '_ensure_legends'):
        setattr(app, name, lambda *a, **k: None)
    return app


@pytest.fixture
def no_dpg(monkeypatch):
    """No widget exists; record configure_item calls."""
    configured: dict = {}
    monkeypatch.setattr(dpg, 'does_item_exist', lambda tag: False)
    monkeypatch.setattr(dpg, 'configure_item',
                        lambda tag, **kw: configured.update({tag: kw}))
    return configured


# ---------------------------------------------------------------------------
# The monitor receives only live-stream frames
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('recording, streaming, expected', [
    (True, True, True),
    (True, False, False),     # loaded file or browsed cache
    (False, True, False),
])
def test_monitor_accepts_only_live_frames(recording, streaming, expected):
    app = _app(_FakeMonitor(recording), streaming=streaming)
    assert app._monitor_accepts_frames() is expected


def test_no_monitor_accepts_nothing():
    assert _app(None)._monitor_accepts_frames() is False


def test_browsed_frame_is_not_sent_to_the_monitor(no_dpg):
    mon = _FakeMonitor(recording=True)
    app = _app(mon, streaming=False)
    app._display_frame_inner()
    assert mon.calls == [], 'a non-live frame was written into the session'


def test_live_frame_is_sent_to_the_monitor(no_dpg):
    mon = _FakeMonitor(recording=True)
    app = _app(mon, streaming=True)
    app._display_frame_inner()
    assert len(mon.calls) == 1


# ---------------------------------------------------------------------------
# File access is refused while a recording runs
# ---------------------------------------------------------------------------

def _forbid_dialog(app):
    def _dialog(*a, **k):
        raise AssertionError('file dialog opened during a recording')
    app._native_file_dialog = _dialog


def test_load_click_is_refused_while_recording(caplog):
    app = _app(_FakeMonitor(recording=True))
    _forbid_dialog(app)
    with caplog.at_level(logging.INFO):
        app._on_load_click()
    assert 'not available while a monitor recording runs' in caplog.text


def test_ctrl_o_is_refused_while_recording(monkeypatch):
    app = _app(_FakeMonitor(recording=True))
    _forbid_dialog(app)
    monkeypatch.setattr(dpg, 'is_key_down', lambda key: True)
    app._on_key_press(None, dpg.mvKey_O)


def test_load_click_works_when_not_recording():
    app = _app(_FakeMonitor(recording=False))
    opened = []
    app._native_file_dialog = lambda save=False: opened.append(save) or ''
    app._on_load_click()
    assert opened == [False]


def test_session_browser_is_refused_while_recording(no_dpg):
    app = _app(_FakeMonitor(recording=True))
    app._build_session_browser = lambda: pytest.fail('browser opened')
    app._refresh_session_browser = lambda: pytest.fail('browser opened')
    app._open_session_browser()


def test_clear_cache_is_refused_while_recording(no_dpg):
    app = _app(_FakeMonitor(recording=True))
    app._clear_cache()
    assert app.collector.resets == 0


# ---------------------------------------------------------------------------
# The recording lock disables the file-access controls
# ---------------------------------------------------------------------------

_FILE_CONTROLS = (ui.FILE_LOAD, ui.BTN_MONITOR_BROWSE, ui.ACQ_CLEAR_CACHE)


@pytest.mark.parametrize('locked', [True, False])
def test_recording_lock_sets_file_controls(monkeypatch, locked):
    configured: dict = {}
    monkeypatch.setattr(dpg, 'does_item_exist', lambda tag: True)
    monkeypatch.setattr(dpg, 'configure_item',
                        lambda tag, **kw: configured.update({tag: kw}))
    _app()._set_recording_lock(locked)
    for tag in _FILE_CONTROLS:
        assert configured[tag] == {'enabled': not locked}, tag


def test_start_and_stop_recording_apply_the_lock():
    assert '_set_recording_lock(True)' in inspect.getsource(GUI._start_recording)
    assert '_set_recording_lock(False)' in inspect.getsource(GUI._stop_recording)
