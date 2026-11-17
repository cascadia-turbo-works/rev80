"""A tachometer channel on the main window: Channels card and plots.

A tachometer channel has no sensor, no engineering unit and no spectrum. The
Channels card shows its rotation unit, not '(none) : mV'. The spectrum,
waveform and trend plots get no series for it, and its 'mV' does not open a
second Y axis. The tests make a dearpygui context, never a viewport.
"""

import dearpygui.dearpygui as dpg
import pytest

import rev80
from rev80.gui import GUI, apply_tach_claim
from rev80.tach import TachSettings
from rev80.util import UI_Elements as ui

_AXES = (
    ui.PLT_FREQ_AX_ACCEL, ui.PLT_FREQ_AX_2,
    ui.PLT_SAMPLE_AX_ACCEL, ui.PLT_SAMPLE_AX_ACCEL_2,
    ui.PLT_TREND_AX_OVERALL, ui.PLT_TREND_AX_OVERALL_2,
    ui.PLT_ENV_AX_AMPL,
)


class _Sensor:
    name = 'Accel 100'
    engineering_units = 'g'


@pytest.fixture
def ctx():
    dpg.create_context()
    yield
    dpg.destroy_context()


def _app(enabled=(0, 1), tach=0):
    cfg = rev80.AcquisitionSettings()
    cfg.enabled_channels = list(enabled)
    dc = rev80.DataCollector(config=cfg)
    for ch in enabled:
        if ch != tach:
            dc.scope_sensors[ch] = _Sensor()
    if tach is not None:
        apply_tach_claim(dc, tach, None, TachSettings())
    app = GUI.__new__(GUI)
    app.collector = dc
    app._num_channels = 4
    return app


def _with_plots(app):
    """The plot axes that the series and the axis assignment use."""
    with dpg.window():
        with dpg.plot():
            for tag in _AXES:
                dpg.add_plot_axis(dpg.mvYAxis, tag=tag)
    app._channel_themes = [dpg.add_theme()]
    app._peak_themes = [dpg.add_theme()]
    for ch in app.collector.config.enabled_channels:
        app._add_channel_series(ch)
    app._update_axis_assignment()


def _shown(tag):
    return dpg.get_item_configuration(tag)['show']


def test_channels_card_shows_a_tachometer_with_its_rotation_unit():
    app = _app()
    assert app._channel_summary_text(0) == 'Tach A : RPM'
    assert app._channel_summary_text(1) == 'Ch B : Accel 100 : g'


def test_channels_card_follows_the_rotation_unit_and_keeps_a_user_name():
    app = _app()
    app.collector.config.rotation_unit = 'Hz'
    app.collector.config.channel_names[0] = 'Motor shaft'
    assert app._channel_summary_text(0) == 'Motor shaft : Hz'


def test_a_tachometer_does_not_add_a_unit_group():
    app = _app()
    assert app._get_unit_groups() == [('g', [1])]


def test_a_tachometer_gets_no_series_and_no_second_axis(ctx):
    app = _app()
    _with_plots(app)
    for tag in (ui.plt_freq_series(0), ui.plt_time_series(0),
                ui.plt_trend_series(0), ui.plt_env_series(0)):
        assert not dpg.does_item_exist(tag), tag
    assert dpg.does_item_exist(ui.plt_freq_series(1))
    for ax in (ui.PLT_FREQ_AX_2, ui.PLT_SAMPLE_AX_ACCEL_2, ui.PLT_TREND_AX_OVERALL_2):
        assert not _shown(ax), ax
    assert dpg.get_item_label(ui.PLT_SAMPLE_AX_ACCEL) == 'Amplitude, g'


def test_claiming_removes_the_series_and_releasing_restores_them(ctx):
    app = _app(tach=None)
    _with_plots(app)
    assert dpg.does_item_exist(ui.plt_freq_series(0))

    apply_tach_claim(app.collector, 0, None, TachSettings())
    app._update_axis_assignment()
    assert not dpg.does_item_exist(ui.plt_freq_series(0))
    assert not _shown(ui.PLT_FREQ_AX_2)

    apply_tach_claim(app.collector, None, None)
    app._update_axis_assignment()
    assert dpg.does_item_exist(ui.plt_freq_series(0))
