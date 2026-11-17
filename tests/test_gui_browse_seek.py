"""The frame number in the browse row is editable.

Only the browse widgets are made, in a dearpygui context with no viewport.
The GUI is a shell with a collector that holds frames and no device.
"""

from datetime import datetime

import dearpygui.dearpygui as dpg
import numpy as np
import pytest

import rev80
from rev80.gui import GUI
from rev80.util import UI_Elements as ui

N_FRAMES = 40


def _collector(n_frames: int) -> rev80.DataCollector:
    c = rev80.DataCollector()
    c.config.highpass_enabled = False
    c.config.enabled_channels = [0]
    c.resize_frame_cache(n_frames)
    samp = {'status': 'OKAY', 'rel_time': 0.0, 'timestamp': datetime.now(),
            'unit': ['mV'], 'channels': [0],
            'data': np.zeros((c.config.raw_blocksize, 1))}
    for _ in range(n_frames):
        c.receive_data(samp)
    return c


@pytest.fixture
def app():
    collector = _collector(N_FRAMES)
    dpg.create_context()
    with dpg.window():
        for tag in (ui.ACQ_BROWSE_FIRST, ui.ACQ_BROWSE_PREV,
                    ui.ACQ_BROWSE_NEXT, ui.ACQ_BROWSE_LAST):
            dpg.add_button(tag=tag)
        dpg.add_text("Frame", tag=ui.ACQ_BROWSE_LABEL)
        dpg.add_input_int(tag=ui.ACQ_BROWSE_INPUT, step=0, enabled=False)
        dpg.add_text("", tag=ui.ACQ_BROWSE_TOTAL)
    a = GUI.__new__(GUI)
    a._browse_enabled = None
    a._update_trend_cursor = lambda: None
    a.collector = collector
    yield a
    dpg.destroy_context()


def test_label_shows_the_newest_frame_editable(app):
    app._update_browse_label()
    assert dpg.get_value(ui.ACQ_BROWSE_LABEL) == "Frame"
    assert dpg.get_value(ui.ACQ_BROWSE_INPUT) == N_FRAMES
    assert dpg.get_value(ui.ACQ_BROWSE_TOTAL) == f"/ {N_FRAMES}"
    assert dpg.get_item_configuration(ui.ACQ_BROWSE_INPUT)["show"]
    assert dpg.get_item_configuration(ui.ACQ_BROWSE_INPUT)["enabled"]


def test_typed_number_seeks(app):
    app._update_browse_label()
    dpg.set_value(ui.ACQ_BROWSE_INPUT, 7)
    app._on_browse_seek()
    assert app.collector._cache_cursor == N_FRAMES - 7
    assert dpg.get_value(ui.ACQ_BROWSE_INPUT) == 7


def test_out_of_range_number_goes_to_the_end(app):
    dpg.set_value(ui.ACQ_BROWSE_INPUT, 10_000)
    app._on_browse_seek()
    assert app.collector._cache_cursor == 0
    assert dpg.get_value(ui.ACQ_BROWSE_INPUT) == N_FRAMES
    dpg.set_value(ui.ACQ_BROWSE_INPUT, 0)
    app._on_browse_seek()
    assert app.collector._cache_cursor == N_FRAMES - 1
    assert dpg.get_value(ui.ACQ_BROWSE_INPUT) == 1


def test_no_seek_while_streaming(app, monkeypatch):
    monkeypatch.setattr(type(app.collector), "is_streaming", property(lambda s: True))
    dpg.set_value(ui.ACQ_BROWSE_INPUT, 3)
    app._on_browse_seek()
    assert app.collector._cache_cursor == 0
    app._update_browse_label()
    assert not dpg.get_item_configuration(ui.ACQ_BROWSE_INPUT)["enabled"]
