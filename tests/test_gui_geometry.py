"""Window geometry: a maximized viewport and a proportional configuration dialog.

The tests make a dearpygui context, never a viewport.
"""

import inspect
from types import SimpleNamespace

import dearpygui.dearpygui as dpg
import pytest

from rev80.gui_geometry import proportional_rect


# ---------------------------------------------------------------------------
# proportional_rect
# ---------------------------------------------------------------------------

def test_the_rect_covers_the_bounds_of_the_client_area():
    assert proportional_rect(2000, 1000, (0.2, 0.8), (0.2, 0.7)) == (400, 200, 1200, 500)


def test_the_rect_rounds_to_whole_pixels():
    x, y, w, h = proportional_rect(1366, 741, (0.2, 0.8), (0.2, 0.7))
    assert all(isinstance(v, int) for v in (x, y, w, h))
    assert (x, y) == (273, 148)
    assert x + w == 1093 and y + h == 519


@pytest.mark.parametrize('bounds_x, bounds_y', [
    ((0.8, 0.2), (0.2, 0.7)),     # reversed
    ((0.2, 0.8), (0.5, 0.5)),     # empty
    ((-0.1, 0.8), (0.2, 0.7)),    # outside 0..1
    ((0.2, 0.8), (0.2, 1.2)),
])
def test_invalid_bounds_raise(bounds_x, bounds_y):
    with pytest.raises(ValueError):
        proportional_rect(2000, 1000, bounds_x, bounds_y)


def test_a_client_area_with_no_size_raises():
    with pytest.raises(ValueError):
        proportional_rect(0, 1000, (0.2, 0.8), (0.2, 0.7))


# ---------------------------------------------------------------------------
# The GUI
# ---------------------------------------------------------------------------

def test_the_viewport_is_maximized_after_it_is_shown():
    from rev80.gui import GUI
    src = inspect.getsource(GUI.run)
    assert 'dpg.maximize_viewport()' in src
    assert src.index('dpg.show_viewport()') < src.index('dpg.maximize_viewport()')


@pytest.fixture
def dialog_app(monkeypatch):
    import rev80.gui as gui_module
    from rev80.gui import GUI
    from rev80.util import UI_Elements as ui
    dpg.create_context()
    with dpg.window(tag=ui.DLG_CONFIG, show=False, width=720, height=840):
        with dpg.tab_bar(tag=ui.CONFIG_TAB_BAR):
            dpg.add_tab(tag=ui.CONFIG_TAB_CHARTS)
    app = GUI.__new__(GUI)
    app.collector = SimpleNamespace(is_streaming=False)
    app._populate_acq_tab = lambda: None
    app._charts_tab = SimpleNamespace(populate=lambda: None)
    monkeypatch.setattr(gui_module.dpg, 'get_viewport_client_width', lambda: 2000)
    monkeypatch.setattr(gui_module.dpg, 'get_viewport_client_height', lambda: 1000)
    yield app, ui
    dpg.destroy_context()


def test_the_config_dialog_opens_at_its_proportional_bounds(dialog_app):
    app, ui = dialog_app
    app._open_config_dialog(ui.CONFIG_TAB_CHARTS)
    cfg = dpg.get_item_configuration(ui.DLG_CONFIG)
    assert list(dpg.get_item_pos(ui.DLG_CONFIG)) == [400, 200]
    assert (cfg['width'], cfg['height']) == (1200, 500)


def test_the_config_dialog_falls_back_to_the_default_window_size(dialog_app, monkeypatch):
    """Before the first frame the client size can read 0."""
    import rev80.gui as gui_module
    app, ui = dialog_app
    monkeypatch.setattr(gui_module.dpg, 'get_viewport_client_width', lambda: 0)
    monkeypatch.setattr(gui_module.dpg, 'get_viewport_client_height', lambda: 0)
    app._open_config_dialog(ui.CONFIG_TAB_CHARTS)
    expected = proportional_rect(gui_module.WINDOW_WIDTH, gui_module.WINDOW_HEIGHT,
                                 gui_module.DLG_CFG_BOUNDS_X, gui_module.DLG_CFG_BOUNDS_Y)
    cfg = dpg.get_item_configuration(ui.DLG_CONFIG)
    assert list(dpg.get_item_pos(ui.DLG_CONFIG)) == list(expected[:2])
    assert (cfg['width'], cfg['height']) == expected[2:]
