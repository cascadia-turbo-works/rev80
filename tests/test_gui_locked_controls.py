"""A control that a recording locks looks disabled and says why.

dearpygui draws a disabled button like an enabled one unless a theme has a
component for the disabled state. The tests make a dearpygui context, never
a viewport.
"""

import dearpygui.dearpygui as dpg
import pytest

from rev80.gui import GUI
from rev80.util import UI_Elements as ui


@pytest.fixture
def ctx():
    dpg.create_context()
    yield
    dpg.destroy_context()


def _components(theme: int) -> list:
    return dpg.get_item_children(theme, 1)


def test_disabled_theme_has_a_disabled_button_component(ctx):
    app = GUI.__new__(GUI)
    theme = app._create_disabled_theme()
    comps = _components(theme)
    assert dpg.mvButton in GUI._DISABLED_THEME_TYPES
    assert len(comps) == len(GUI._DISABLED_THEME_TYPES)
    for comp in comps:
        assert dpg.get_item_configuration(comp)['enabled_state'] is False
        # Text and frame colours at least.
        assert len(dpg.get_item_children(comp, 1)) >= 2


def test_create_gui_binds_the_disabled_theme():
    import inspect
    src = inspect.getsource(GUI._create_gui)
    assert 'dpg.bind_theme(self._create_disabled_theme())' in src
    assert 'self._create_locked_tips()' in src


@pytest.mark.parametrize('locked', [True, False])
def test_lock_toggles_every_control_and_its_tooltip(ctx, locked):
    app = GUI.__new__(GUI)
    with dpg.window():
        for tag in GUI._RECORDING_LOCKED_CONTROLS:
            dpg.add_button(tag=tag)
    app._create_locked_tips()
    for tag in GUI._RECORDING_LOCKED_CONTROLS:
        assert dpg.get_item_configuration(ui.locked_tip(tag))['show'] is False

    app._set_recording_lock(locked)
    for tag in GUI._RECORDING_LOCKED_CONTROLS:
        assert dpg.get_item_configuration(tag)['enabled'] is (not locked), tag
        assert dpg.get_item_configuration(ui.locked_tip(tag))['show'] is locked, tag

    app._set_recording_lock(not locked)
    for tag in GUI._RECORDING_LOCKED_CONTROLS:
        assert dpg.get_item_configuration(tag)['enabled'] is locked, tag
        assert dpg.get_item_configuration(ui.locked_tip(tag))['show'] is (not locked)
