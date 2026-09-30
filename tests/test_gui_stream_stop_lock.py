"""A recording refuses a stream stop.

The recording continues when the stream stops, but it gets no frames. The
Acquisition toggle button, the Tachometer tab button and Ctrl+K all go
through GUI._toggle_acquisition. These tests use a GUI shell with no DPG
context.
"""

import logging

import dearpygui.dearpygui as dpg
import pytest

from rev80.gui import GUI


class _FakeMonitor:
    def __init__(self, recording: bool) -> None:
        self.is_recording = recording


class _FakeCollector:
    def __init__(self, streaming: bool) -> None:
        self.is_streaming = streaming


def _app(recording: bool, streaming: bool) -> tuple[GUI, list]:
    app = GUI.__new__(GUI)
    app._monitor = _FakeMonitor(recording)
    app.collector = _FakeCollector(streaming)
    calls: list = []
    app._stop_stream = lambda: calls.append('stop')
    app._start_stream = lambda: calls.append('start')
    return app, calls


@pytest.mark.parametrize('recording, streaming, expected', [
    (True, True, []),            # refused
    (False, True, ['stop']),
    (False, False, ['start']),
    (True, False, ['start']),    # _start_recording starts the stream
])
def test_toggle_acquisition(recording, streaming, expected):
    app, calls = _app(recording, streaming)
    app._toggle_acquisition()
    assert calls == expected


def test_refusal_logs_an_info_message(caplog):
    app, _ = _app(recording=True, streaming=True)
    with caplog.at_level(logging.INFO, logger='rev80'):
        app._toggle_acquisition()
    assert any('Stop the recording first' in r.getMessage() for r in caplog.records)


def test_ctrl_k_does_not_stop_a_recording_stream(monkeypatch):
    monkeypatch.setattr(dpg, 'is_key_down', lambda key: key == dpg.mvKey_LControl)
    app, calls = _app(recording=True, streaming=True)
    app._on_key_press(None, dpg.mvKey_K)
    assert calls == []
