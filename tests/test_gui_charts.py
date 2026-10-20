"""Main-window charts from the layout in effect (gui_charts.ChartsView).

One tab for each chart; the selected chart stays selected over a rebuild;
a chart not on screen is not drawn, but the cards of every spectrum chart
update; a channel that cannot show the chart unit has an empty series and
the reason in its legend. The tests make a dearpygui context, never a
viewport.
"""

import math
from datetime import datetime

import dearpygui.dearpygui as dpg
import numpy as np
import pytest

import rev80
from rev80 import charts
from rev80 import gui_charts
from rev80 import simulation as sim
from rev80.charts import ChartSet, ChartSpec
from rev80.gui_charts import ChartsView, chart_id_of_tab, envelope_scale
from rev80.scope_sensor import ScopeSensor
from rev80.util import UI_Elements as ui
from pipeline_helpers import tick

TONE_HZ = 160.3


class _Host:
    """The parts of the GUI that ChartsView uses."""

    def __init__(self, collector):
        self.collector = collector
        self._channel_themes = []
        self._peak_themes = []
        self._sect_theme = None
        self._channel_colors = [(255, 0, 0, 255), (0, 255, 0, 255)]
        self.redraws = 0

    @staticmethod
    def _tooltip(target, text, wrap=320):
        with dpg.tooltip(parent=target):
            dpg.add_text(text, wrap=wrap)

    @staticmethod
    def _band_suffix():
        return ''

    def _redraw(self):
        self.redraws += 1


def _layout(*extra):
    return ChartSet((
        ChartSpec('c1', 'waveform', 'Waveform', channels=(0, 1), unit='g'),
        ChartSpec('c2', 'spectrum', 'Spectrum', channels=(0, 1), unit='g',
                  amplitude_mode='0-P'),
        ChartSpec('c3', 'trend', 'Trend', channels=(0,), unit='in/s',
                  amplitude_mode='RMS'),
    ) + tuple(extra))


class _LiveStream:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


def _collector(frames=2):
    """A live collector: channel 0 has a g sensor, channel 1 has none."""
    cfg = rev80.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = 2.0
    cfg.enabled_channels = [0, 1]
    dc = rev80.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g',
                                       sensitivity=100.0))
    dc.init_trend_channels()
    dc.sensor = object()
    dc.stream = _LiveStream()
    dc.chart_set = _layout()
    view = sim._RawRateView(cfg)
    for i in range(frames):
        tone = sim.GenerateTone(view, ampl=100.0, freq=TONE_HZ, phase=0.7)
        dc.receive_data({
            'data': np.column_stack([tone, 0.5 * tone]), 'channels': [0, 1],
            'status': 'OKAY', 'timestamp': datetime(2026, 10, 19),
            'rel_time': float(i), 'samplerate': cfg.raw_samplerate,
            'overflow_mask': 0, 'degraded': False,
        })
        tick(dc)
    return dc


@pytest.fixture
def view():
    dpg.create_context()
    with dpg.window():
        dpg.add_tab_bar(tag=ui.MAIN_CHART_TAB_BAR)
        dpg.add_group(tag=ui.CHART_CARDS)
    v = ChartsView(_Host(_collector()))
    v.rebuild()
    yield v
    dpg.destroy_context()


def _tab_ids():
    tabs = dpg.get_item_children(ui.MAIN_CHART_TAB_BAR, 1)
    return [chart_id_of_tab(dpg.get_item_alias(t)) for t in tabs]


def _xs(tag):
    return list(dpg.get_value(tag)[0])


# ---------------------------------------------------------------------------
# Tabs and cards from the layout
# ---------------------------------------------------------------------------

def test_one_tab_for_each_chart_in_layout_order(view):
    assert _tab_ids() == ['c1', 'c2', 'c3']


def test_cards_only_for_a_spectrum_chart(view):
    assert dpg.does_item_exist(ui.card_group('c2'))
    assert dpg.does_item_exist(ui.card('c2', 0))
    assert not dpg.does_item_exist(ui.card_group('c1'))
    assert not dpg.does_item_exist(ui.card_group('c3'))


def test_the_selected_chart_stays_selected_over_a_rebuild(view):
    dpg.set_value(ui.MAIN_CHART_TAB_BAR, ui.chart_tab('c2'))
    assert view.selected_chart_id() == 'c2'
    view.collector.chart_set = _layout(
        ChartSpec('c4', 'spectrum', 'Second', channels=(0,), unit='in/s',
                  amplitude_mode='RMS'))
    view.rebuild()
    assert _tab_ids() == ['c1', 'c2', 'c3', 'c4']
    assert view.selected_chart_id() == 'c2'


def test_a_removed_selected_chart_selects_the_first(view):
    dpg.set_value(ui.MAIN_CHART_TAB_BAR, ui.chart_tab('c2'))
    view.collector.chart_set = _layout().without('c2')
    view.rebuild()
    assert view.selected_chart_id() == 'c1'


def test_a_rebuild_does_not_duplicate_cards(view):
    view.rebuild()
    groups = dpg.get_item_children(ui.CHART_CARDS, 1)
    assert len(groups) == 1


# ---------------------------------------------------------------------------
# Only the chart on screen is drawn; the cards always update
# ---------------------------------------------------------------------------

def test_a_chart_not_on_screen_is_not_drawn(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: cid == 'c3')
    view.render(view.collector.snapshot())
    assert _xs(ui.chart_series('c1', 0)) == []
    assert _xs(ui.chart_series('c2', 0)) == []
    assert len(_xs(ui.chart_series('c3', 0))) == 2       # two trend points


def test_the_cards_of_a_hidden_spectrum_chart_update(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: False)
    snap = view.collector.snapshot()
    view.render(snap)
    r = view.collector.result_view(snap, 0, 'g', '0-P', peaks=True)
    assert dpg.get_value(ui.card('c2', 0, 'overall')) == f'{r.overall:.4f}'


def test_force_draws_the_new_tab_at_once(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: False)
    snap = view.collector.snapshot()
    view.render(snap, force='c1')
    r = view.collector.result_view(snap, 0, 'g', None, peaks=False)
    assert _xs(ui.chart_series('c1', 0)) == pytest.approx((r.time_vec * 1000.0).tolist())


def test_series_are_in_the_chart_unit(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: True)
    snap = view.collector.snapshot()
    view.render(snap)
    r = view.collector.result_view(snap, 0, 'g', '0-P', peaks=True)
    assert list(dpg.get_value(ui.chart_series('c2', 0))[1]) == pytest.approx(r.spectrum.tolist())
    times, values = view.collector.get_trend_for_display('in/s', 'RMS', [0])[0]
    assert list(dpg.get_value(ui.chart_series('c3', 0))[1]) == pytest.approx(values)


# ---------------------------------------------------------------------------
# A channel that cannot show the chart unit
# ---------------------------------------------------------------------------

def test_a_channel_with_no_sensor_has_an_empty_series_and_the_reason(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: True)
    view.render(view.collector.snapshot())
    label = dpg.get_item_label(ui.chart_series('c2', 1))
    assert label.endswith(charts.unreachable_reason(None, 'g'))
    assert _xs(ui.chart_series('c2', 1)) == []
    assert dpg.get_value(ui.card('c2', 1, 'overall')) == '--'


def test_an_absent_channel_stays_on_the_chart_and_says_so(view):
    view.collector.chart_set = _layout(
        ChartSpec('c4', 'spectrum', 'Absent', channels=(0, 3), unit='g',
                  amplitude_mode='0-P'))
    view.rebuild()
    assert dpg.get_item_label(ui.chart_series('c4', 3)).endswith('not present')
    assert 'ch3: not present' in dpg.get_value(ui.chart_note('c4'))
    assert dpg.get_item_configuration(ui.chart_note('c4'))['show'] is True


def test_a_chart_with_no_problem_hides_its_note(view):
    assert dpg.get_item_configuration(ui.chart_note('c3'))['show'] is False


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_chart_id_of_tab_inverts_chart_tab():
    assert chart_id_of_tab(ui.chart_tab('c12')) == 'c12'
    assert chart_id_of_tab('PLT_FREQ') is None
    assert chart_id_of_tab('') is None


def test_envelope_scale_is_the_si_scale_and_the_mode():
    assert envelope_scale('g', 'g', '0-P') == 1.0
    assert envelope_scale('g', 'mm/s2', '0-P') == pytest.approx(9806.65)
    assert envelope_scale('g', 'g', 'RMS') == pytest.approx(1 / math.sqrt(2))
    assert envelope_scale('g', 'g', 'P-P') == pytest.approx(2.0)


def test_envelope_search_fmax_is_reexported_from_gui():
    from rev80.gui import envelope_search_fmax
    assert envelope_search_fmax is gui_charts.envelope_search_fmax


def test_the_arm_pattern_leaves_out_a_gui_charts_import():
    """tests/conftest.py must leave out a test module that imports gui_charts."""
    from conftest import _GUI_IMPORT
    for line in ('from rev80.gui_charts import ChartsView',
                 'from rev80.gui_charts_tab import ChartsTab',
                 'import rev80.gui_charts',
                 'from rev80 import gui_charts',
                 'from rev80.gui import GUI'):
        assert _GUI_IMPORT.search(line), line
    for line in ('from rev80.charts import ChartSet', 'import rev80'):
        assert not _GUI_IMPORT.search(line), line


# ---------------------------------------------------------------------------
# The main window
# ---------------------------------------------------------------------------

def test_the_main_window_shows_the_charts_of_the_collector(monkeypatch, tmp_path):
    """Build the window, swap in a live collector, display one frame."""
    from rev80 import config as cfg_mod
    from rev80.gui import GUI
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    dpg.create_context()
    try:
        app = GUI()
        app._create_gui()
        dc = _collector(3)
        dc.chart_set = None                     # the default layout
        dc.sensor = rev80.VibeSensor.simulated()
        app.collector = dc
        app._on_data_source_changed()
        app._display_frame_inner()
        assert _tab_ids() == ['c1', 'c2']
        snap = dc.snapshot()
        r = dc.result_view(snap, 0, *dc.default_view_of(0), peaks=True)
        assert dpg.get_value(ui.card('c2', 0, 'overall')) == f'{r.overall:.4f}'
        assert r.overall == pytest.approx(1.0, rel=1e-3)   # 100 mV at 100 mV/g
    finally:
        dpg.destroy_context()


# ---------------------------------------------------------------------------
# Peaks-table widget pool
# ---------------------------------------------------------------------------

_COLS = ['Frequency (Hz)', 'Amp., g 0-P']


def _shown_rows(cid, ch):
    out = []
    i = 0
    while dpg.does_item_exist(ui.card_peak_row(cid, ch, i)):
        if dpg.get_item_configuration(ui.card_peak_row(cid, ch, i))['show']:
            out.append(tuple(dpg.get_value(ui.card_peak_cell(cid, ch, i, c)) for c in range(2)))
        i += 1
    return out


def test_the_table_shows_exactly_the_new_rows(view):
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5), (2.0, 0.25), (3.0, 0.1)])
    view._update_peaks_table('c2', 0, _COLS, [(4.0, 0.9)])
    assert _shown_rows('c2', 0) == [('4.0', '0.9')]
    view._update_peaks_table('c2', 0, _COLS, [(4.0, 0.9), (5.0, 0.8)])
    assert _shown_rows('c2', 0) == [('4.0', '0.9'), ('5.0', '0.8')]


def test_after_a_clear_a_shorter_table_hides_the_old_rows(view):
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5), (2.0, 0.25), (3.0, 0.1)])
    view.clear()
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5)])
    assert _shown_rows('c2', 0) == [('1.0', '0.5')]


def test_after_a_clear_a_longer_table_shows_the_hidden_rows(view):
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5), (2.0, 0.25), (3.0, 0.1)])
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5)])
    view.clear()
    view._update_peaks_table('c2', 0, _COLS, [(1.0, 0.5), (2.0, 0.25)])
    assert _shown_rows('c2', 0) == [('1.0', '0.5'), ('2.0', '0.25')]


# ---------------------------------------------------------------------------
# Review findings
# ---------------------------------------------------------------------------

def test_a_rebuild_requests_a_redraw(view):
    before = view.host.redraws
    view.rebuild()
    assert view.host.redraws == before + 1


def test_clear_empties_every_part_of_a_card(view, monkeypatch):
    monkeypatch.setattr(view, 'on_screen', lambda cid: True)
    view.render(view.collector.snapshot())
    assert _shown_rows('c2', 0)
    view.clear()
    assert dpg.get_value(ui.card('c2', 0, 'overall')) == '--'
    assert dpg.get_value(ui.card('c2', 0, 'scalars')) == 'Crest -   Kurt -'
    assert dpg.get_value(ui.card('c2', 0, 'found')) == ''
    assert dpg.get_value(ui.card('c2', 0, 'avg')) == ''
    assert _shown_rows('c2', 0) == []


def _tach_on_1(view):
    cfg = view.collector.config
    cfg.channel_roles = {1: 'tachometer'}


def test_xy_never_draws_a_tachometer_channel(view, monkeypatch):
    _tach_on_1(view)
    view.collector.set_scope_sensor(0, None)         # both channels reach mV
    view.collector.chart_set = _layout(
        ChartSpec('c4', 'xy', 'XY', channels=(0, 1), unit='mV'))
    view.rebuild()
    monkeypatch.setattr(view, 'on_screen', lambda cid: True)
    view.render(view.collector.snapshot())
    tag = ui.chart_series('c4', 1)
    assert not dpg.does_item_exist(tag) or _xs(tag) == []


def test_a_disabled_tachometer_is_still_not_a_vibration_series(view):
    cfg = view.collector.config
    cfg.channel_roles = {3: 'tachometer'}          # not enabled
    view.collector.chart_set = _layout(
        ChartSpec('c4', 'spectrum', 'S', channels=(0, 3), unit='g', amplitude_mode='0-P'))
    view.rebuild()
    assert not dpg.does_item_exist(ui.chart_series('c4', 3))
    assert not dpg.does_item_exist(ui.card('c4', 3))


def test_xy_pairs_samples_of_the_same_time():
    """Two traces with different windows pair by time, not by index."""
    from rev80.gui_charts import same_time_indices
    period = 1 / 5120.0
    t_x = np.arange(100, 740) * period
    t_y = np.arange(64, 704) * period
    ix, iy = same_time_indices(t_x, t_y)
    assert np.array_equal(t_x[ix], t_y[iy])
    assert len(ix) == 704 - 100


def test_xy_draws_y_against_x_of_one_frame(view, monkeypatch):
    dc = view.collector
    dc.set_scope_sensor(1, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    dc.chart_set = _layout(ChartSpec('c4', 'xy', 'XY', channels=(0, 1), unit='g'))
    view.rebuild()
    monkeypatch.setattr(view, 'on_screen', lambda cid: True)
    snap = dc.snapshot()
    view.render(snap)
    rx = dc.result_view(snap, 0, 'g', None, peaks=False)
    ry = dc.result_view(snap, 1, 'g', None, peaks=False)
    xs, ys = dpg.get_value(ui.chart_series('c4', 1))[:2]
    assert list(xs) == pytest.approx(rx.time_data.tolist())
    assert list(ys) == pytest.approx(ry.time_data.tolist())


def test_the_gui_rebuilds_the_charts_on_acquisition_apply():
    import inspect
    from rev80.gui import GUI
    assert '_charts.rebuild()' in inspect.getsource(GUI._on_acq_apply)


def test_a_swap_drops_the_snapshot_of_the_old_collector():
    import inspect
    from rev80.gui import GUI
    assert 'self._last_snapshot = None' in inspect.getsource(GUI._on_data_source_changed)
