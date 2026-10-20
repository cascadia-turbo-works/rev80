"""The Charts tab of the configuration dialog (gui_charts_tab.ChartsTab).

Rows from the working copy; add, remove and XY swap; a channel that cannot
show the chart unit is disabled; an absent channel stays checked; with live
data Close saves charts.yaml, with a file on screen it does not. The tests
make a dearpygui context, never a viewport.
"""

import dearpygui.dearpygui as dpg
import pytest

import rev80
from rev80 import charts
from rev80 import config as cfg_mod
from rev80.charts import ChartSet, ChartSpec
from rev80.gui_charts_tab import ChartsTab
from rev80.scope_sensor import ScopeSensor
from rev80.util import UI_Elements as ui


class _Host:
    def __init__(self, collector):
        self.collector = collector
        self._channel_colors = [(255, 0, 0, 255), (0, 255, 0, 255)]
        self.live = True

    @staticmethod
    def _tooltip(target, text, wrap=320):
        with dpg.tooltip(parent=target):
            dpg.add_text(text, wrap=wrap)

    def _live_data_on_screen(self):
        return self.live


def _layout():
    return ChartSet((
        ChartSpec('c1', 'waveform', 'Waveform', channels=(0, 1), unit='g'),
        ChartSpec('c2', 'spectrum', 'Spectrum', channels=(0,), unit='g',
                  amplitude_mode='0-P'),
        ChartSpec('c3', 'xy', 'Orbit', channels=(0, 1), unit='mV'),
    ))


def _collector():
    """Channel 0 has a g sensor, channel 1 has none, channel 2 is a tachometer."""
    cfg = rev80.AcquisitionSettings()
    cfg.enabled_channels = [0, 1, 2]
    cfg.channel_roles = {2: 'tachometer'}
    cfg.cache_frames = 15
    dc = rev80.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    dc.chart_set = _layout()
    return dc


@pytest.fixture
def cfg_home(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    return cfg_mod.charts_config_path()


@pytest.fixture
def tab(cfg_home):
    dpg.create_context()
    with dpg.window():
        t = ChartsTab(_Host(_collector()))
        t.build()
    t.populate()
    yield t
    dpg.destroy_context()


def _row_ids(t):
    return [cid for cid in (c.chart_id for c in t.working.charts)
            if dpg.does_item_exist(ui.charts_row(cid, 'row'))]


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def test_one_row_for_each_chart(tab):
    assert _row_ids(tab) == ['c1', 'c2', 'c3']
    assert dpg.get_value(ui.charts_row('c2', 'unit')) == 'g 0-P'
    assert dpg.get_value(ui.charts_row('c1', 'unit')) == 'g'


def test_a_tachometer_is_never_a_channel_checkbox(tab):
    assert not dpg.does_item_exist(ui.charts_row_ch('c1', 2))
    assert dpg.does_item_exist(ui.charts_row_ch('c1', 0))


def test_a_channel_that_cannot_show_the_unit_is_disabled(tab):
    # c2 is in g; channel 1 has no sensor and is not checked.
    tag = ui.charts_row_ch('c2', 1)
    assert dpg.get_item_configuration(tag)['enabled'] is False
    assert dpg.get_value(tag) is False
    # c1 has channel 1 checked: it stays enabled, so it can be unchecked.
    assert dpg.get_item_configuration(ui.charts_row_ch('c1', 1))['enabled'] is True


def test_an_absent_channel_stays_checked(tab):
    tab.working = tab.working.replace_chart(
        tab.working.chart('c1').evolve(channels=(0, 5)))
    tab.refresh()
    tag = ui.charts_row_ch('c1', 5)
    assert dpg.get_value(tag) is True
    assert 'not present' in dpg.get_item_configuration(tag)['label']
    assert tab.working.chart('c1').channels == (0, 5)


# ---------------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------------

def test_add_and_remove(tab):
    tab.add_chart('trend')
    new = tab.working.charts[-1]
    assert new.chart_type == 'trend' and new.chart_id not in {'c1', 'c2', 'c3'}
    assert (new.show_rpm, new.tach_channel) == (True, 2)
    assert dpg.does_item_exist(ui.charts_row(new.chart_id, 'row'))
    tab.remove_chart('c1')
    assert _row_ids(tab) == ['c2', 'c3', new.chart_id]
    assert not dpg.does_item_exist(ui.charts_row('c1', 'row'))
    assert tab.edited


def test_xy_swap(tab):
    tab.swap_xy('c3')
    assert tab.working.chart('c3').channels == (1, 0)
    assert dpg.get_value(ui.charts_row('c3', 'xy0')) == tab.collector.config.name_for(1)


def test_channel_toggle_and_unit_change(tab):
    tab.set_channel('c2', 0, False)
    assert tab.working.chart('c2').channels == ()
    tab.set_unit('c2', 'in/s RMS')
    spec = tab.working.chart('c2')
    assert (spec.unit, spec.amplitude_mode) == ('in/s', 'RMS')


def test_n_averages_is_clamped_to_the_cache(tab):
    tab.set_averaging('c2', True)
    tab.set_n_averages('c2', 99)
    assert tab.working.chart('c2').n_averages == 15
    period = tab.collector.config.acquisition_period
    assert dpg.get_value(ui.charts_row('c2', 'window')) == f'{15 * period:.1f} s'


def test_a_name_edit_does_not_rebuild_the_table(tab):
    field = dpg.get_alias_id(ui.charts_row('c1', 'name'))
    tab.set_name('c1', 'Shaft')
    assert tab.working.chart('c1').name == 'Shaft'
    assert dpg.get_alias_id(ui.charts_row('c1', 'name')) == field
    tab.set_name('c1', '   ')
    assert tab.working.chart('c1').name == 'Shaft'      # an empty name is not taken


# ---------------------------------------------------------------------------
# Apply (the dialog's Close)
# ---------------------------------------------------------------------------

def test_close_with_live_data_saves_charts_yaml(tab, cfg_home):
    tab.remove_chart('c3')
    assert tab.apply() is True
    assert tab.collector.chart_set == tab.working
    assert charts.load_chart_set(cfg_home, lambda: ChartSet(()))[0] == tab.working


def test_close_with_a_file_changes_the_layout_in_effect_only(tab, cfg_home):
    tab.host.live = False
    tab.refresh()
    assert dpg.is_item_shown(ui.CHARTS_TAB_USE_LIVE)
    tab.remove_chart('c3')
    assert tab.apply() is True
    assert tab.collector.chart_set == tab.working
    assert not cfg_home.exists()
    tab.use_for_live_data()
    assert charts.load_chart_set(cfg_home, lambda: ChartSet(()))[0] == tab.working


def test_use_for_live_data_is_hidden_with_live_data(tab):
    assert not dpg.is_item_shown(ui.CHARTS_TAB_USE_LIVE)


def test_an_unedited_close_changes_nothing(tab, cfg_home):
    before = tab.collector.chart_set
    assert tab.apply() is False
    assert tab.collector.chart_set is before
    assert not cfg_home.exists()


def test_populate_starts_from_the_layout_in_effect(tab):
    tab.remove_chart('c1')
    tab.populate()
    assert _row_ids(tab) == ['c1', 'c2', 'c3']
    assert not tab.edited


def test_a_new_data_source_drops_the_edits(tab, cfg_home):
    """A connect while the dialog is open: the old layout reaches nothing."""
    tab.host.live = False
    tab.remove_chart('c3')
    file_layout = tab.working
    tab.host.collector = _collector()           # the new live collector
    tab.host.live = True
    assert tab.apply() is False
    assert tab.collector.chart_set != file_layout
    assert not cfg_home.exists()


def test_a_refresh_after_a_new_data_source_starts_again(tab):
    tab.remove_chart('c3')
    tab.host.collector = _collector()
    tab.refresh()
    assert _row_ids(tab) == ['c1', 'c2', 'c3'] and not tab.edited


def test_the_last_chart_cannot_be_removed(tab):
    tab.remove_chart('c1')
    tab.remove_chart('c2')
    assert dpg.get_item_configuration(ui.charts_row('c3', 'remove'))['enabled'] is False
    tab.remove_chart('c3')
    assert _row_ids(tab) == ['c3']


def test_xy_labels_are_unique_when_names_repeat(tab):
    cfg = tab.collector.config
    cfg.channel_names = {0: 'Motor', 1: 'Motor'}
    tab.refresh()
    items = dpg.get_item_configuration(ui.charts_row('c3', 'xy0'))['items']
    assert items == ['Motor (ch0)', 'Motor (ch1)']
    assert dpg.get_value(ui.charts_row('c3', 'xy1')) == 'Motor (ch1)'


def test_populate_clears_the_status(tab):
    tab.use_for_live_data()
    assert dpg.get_value(ui.CHARTS_TAB_STATUS)
    tab.populate()
    assert dpg.get_value(ui.CHARTS_TAB_STATUS) == ''
