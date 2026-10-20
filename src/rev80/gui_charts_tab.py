"""The Charts tab of the configuration dialog: edit the chart layout.

One table row for each chart: remove, type, name, channels, unit and
options. Below the table: a type combo and an add button. The rules of an
edit (which units, which channels, a new chart) are pure functions in
`rev80.charts`; this module holds the widgets only.

Edits go to a working copy. The dialog's Close calls `apply()`: the copy
becomes the layout in effect (`collector.chart_set`). With live data, Close
also saves `charts.yaml`. With a file on screen, Close changes the layout in
effect only, and a later Save stores it in the measurement file; "Use for
live data" copies the layout to `charts.yaml`.

The table never removes a channel because it is absent now: a checked
channel that is not present shows "not present" and stays checked.

Render thread only. The host is the GUI: it gives `collector`,
`_channel_colors`, `_tooltip()` and `_live_data_on_screen()`.
"""

from __future__ import annotations

import logging

import dearpygui.dearpygui as dpg

import rev80
from rev80 import charts as rev80_charts
from rev80 import config as _cfg
from rev80.util import UI_Elements as ui

log = logging.getLogger(__name__)

_NAME_W = 140
_UNIT_W = 110
_XY_W = 110
_N_W = 90


def _c(key: str, alpha: int = 255) -> tuple:
    return rev80.hex_to_rgba(rev80.THEME_COLORS[key], alpha)


class ChartsTab:
    """The widgets of the Charts tab and its working copy of the layout."""

    def __init__(self, host):
        self.host = host
        self.working: rev80_charts.ChartSet | None = None
        self.edited = False
        # The collector that the working copy came from. A new data source
        # while the dialog is open (a connect) drops the copy: the layout of
        # one source must never reach another, or charts.yaml.
        self._source = None
        self._check_themes: dict[int, int] = {}

    @property
    def collector(self):
        return self.host.collector

    # ------------------------------------------------------------------
    # Build, populate, apply
    # ------------------------------------------------------------------

    def build(self) -> None:
        """The static widgets. Call inside the tab of the dialog."""
        dpg.add_text("Charts on the main window, in tab order")
        dpg.add_separator()
        dpg.add_group(tag=ui.CHARTS_TAB_TABLE_GROUP)
        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_combo(
                [rev80_charts.CHART_TYPE_LABELS[t] for t in rev80_charts.CHART_TYPES],
                default_value=rev80_charts.CHART_TYPE_LABELS['spectrum'],
                tag=ui.CHARTS_TAB_ADD_TYPE, width=160)
            dpg.add_button(label="+", tag=ui.CHARTS_TAB_ADD, width=30,
                           callback=lambda: self.add_chart(self._add_type()))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Use for live data", tag=ui.CHARTS_TAB_USE_LIVE,
                           callback=lambda: self.use_for_live_data(), show=False)
        self.host._tooltip(ui.CHARTS_TAB_USE_LIVE,
                           "A file is on screen: Close changes its layout only. "
                           "This button also saves the layout for live data (charts.yaml).")
        dpg.add_text("", tag=ui.CHARTS_TAB_STATUS, color=_c('ON_SURFACE'))

    def populate(self) -> None:
        """A new working copy from the layout in effect. Call when the dialog opens."""
        self.working = self.collector.chart_layout()
        self.edited = False
        self._source = self.collector
        self._status("")
        self.refresh()

    def refresh(self) -> None:
        """Build the table again from the working copy and the channels now."""
        if self.working is None or not dpg.does_item_exist(ui.CHARTS_TAB_TABLE_GROUP):
            return
        if self._source is not self.collector:
            self.populate()
            return
        if dpg.does_item_exist(ui.CHARTS_TAB_USE_LIVE):
            dpg.configure_item(ui.CHARTS_TAB_USE_LIVE,
                               show=not self.host._live_data_on_screen())
        dpg.delete_item(ui.CHARTS_TAB_TABLE_GROUP, children_only=True)
        roles, eus = self._channel_context()
        with dpg.table(parent=ui.CHARTS_TAB_TABLE_GROUP, header_row=True,
                       borders_innerH=True, borders_outerH=True, resizable=False,
                       policy=dpg.mvTable_SizingFixedFit):
            for label in ('', 'Type', 'Name', 'Channels', 'Unit', 'Options'):
                dpg.add_table_column(label=label)
            for spec in self.working.charts:
                self._build_row(spec, roles, eus)
        if not self.working.charts:
            dpg.add_text("No chart. Select a type and click +.",
                         parent=ui.CHARTS_TAB_TABLE_GROUP, color=_c('YELLOW'))

    def apply(self) -> bool:
        """Make the working copy the layout in effect. True if it changed.

        With live data on screen, also save `charts.yaml`. With a file on
        screen, only the layout in effect changes. An unedited copy changes
        nothing, so the dialog's Close writes no file for it.
        """
        if self.working is None or not self.edited:
            return False
        if self._source is not self.collector:
            log.warning("Chart edits dropped: the data source changed while "
                        "the dialog was open")
            self.working, self.edited = None, False
            return False
        self.collector.chart_set = self.working
        if self.host._live_data_on_screen():
            self._save(self.working)
        self.edited = False
        return True

    def use_for_live_data(self) -> None:
        """Save the working copy to `charts.yaml` for live data."""
        if self.working is not None:
            self._save(self.working)

    def _save(self, chart_set) -> None:
        path = _cfg.charts_config_path()
        try:
            rev80_charts.save_chart_set(path, chart_set)
        except OSError as exc:
            log.warning("Chart layout not saved to %s: %s", path, exc)
            self._status(f"Not saved: {exc}")
            return
        log.info("Chart layout saved to %s", path)
        self._status(f"Saved to {path}")

    def _status(self, text: str) -> None:
        if dpg.does_item_exist(ui.CHARTS_TAB_STATUS):
            dpg.set_value(ui.CHARTS_TAB_STATUS, text)

    # ------------------------------------------------------------------
    # Edits
    # ------------------------------------------------------------------

    def _edit(self, spec) -> None:
        self.working = self.working.replace_chart(spec)
        self.edited = True

    def _spec(self, cid: str):
        return self.working.chart(cid)

    def add_chart(self, chart_type: str) -> None:
        roles, eus = self._channel_context()
        spec = rev80_charts.new_chart(self.working, chart_type, roles, eus,
                                      self.collector.default_view_of)
        self.working = self.working.with_chart(spec)
        self.edited = True
        self.refresh()

    def remove_chart(self, cid: str) -> None:
        if len(self.working.charts) <= 1:
            return
        self.working = self.working.without(cid)
        self.edited = True
        self.refresh()

    def set_name(self, cid: str, name: str) -> None:
        # No refresh: a rebuild of the table takes the focus from the field.
        self._edit(self._spec(cid).evolve(name=name.strip() or self._spec(cid).name))

    def set_channel(self, cid: str, ch: int, on: bool) -> None:
        self._edit(rev80_charts.with_channel(self._spec(cid), ch, on))
        self.refresh()

    def set_xy(self, cid: str, axis: int, ch: int) -> None:
        self._edit(rev80_charts.with_xy(self._spec(cid), axis, ch))
        self.refresh()

    def swap_xy(self, cid: str) -> None:
        self._edit(rev80_charts.swapped_xy(self._spec(cid)))
        self.refresh()

    def set_unit(self, cid: str, label: str) -> None:
        unit, mode = rev80_charts.parse_unit_label(label)
        self._edit(self._spec(cid).evolve(unit=unit, amplitude_mode=mode))
        self.refresh()

    def set_show_rpm(self, cid: str, on: bool) -> None:
        spec = self._spec(cid)
        tach = spec.tach_channel
        if on and tach is None:
            tachs = self._tach_channels()
            tach = tachs[0] if tachs else None
        self._edit(spec.evolve(show_rpm=bool(on), tach_channel=tach))
        self.refresh()

    def set_tach(self, cid: str, ch: int) -> None:
        self._edit(self._spec(cid).evolve(tach_channel=int(ch)))

    def set_averaging(self, cid: str, on: bool) -> None:
        self._edit(self._spec(cid).evolve(averaging=bool(on)))
        self.refresh()

    def set_n_averages(self, cid: str, n: int) -> None:
        n = max(1, min(int(n), self._cache_depth()))
        self._edit(self._spec(cid).evolve(n_averages=n))
        tag = ui.charts_row(cid, 'window')
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, self._window_text(n))

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------

    def _build_row(self, spec, roles, eus) -> None:
        cid = spec.chart_id
        with dpg.table_row(tag=ui.charts_row(cid, 'row')):
            # The last chart stays: an empty layout is not a valid charts.yaml.
            dpg.add_button(label="-", tag=ui.charts_row(cid, 'remove'), width=24,
                           enabled=len(self.working.charts) > 1,
                           callback=lambda: self.remove_chart(cid))
            dpg.add_text(rev80_charts.CHART_TYPE_LABELS[spec.chart_type])
            dpg.add_input_text(default_value=spec.name, width=_NAME_W,
                               tag=ui.charts_row(cid, 'name'),
                               callback=lambda s, a: self.set_name(cid, a))
            with dpg.group():
                if spec.chart_type == 'xy':
                    self._build_xy_selectors(spec, roles)
                else:
                    self._build_channel_checks(spec, roles, eus)
            dpg.add_combo(rev80_charts.unit_choices(spec, roles, eus),
                          default_value=rev80_charts.unit_label(spec.unit, spec.amplitude_mode),
                          tag=ui.charts_row(cid, 'unit'), width=_UNIT_W,
                          callback=lambda s, a: self.set_unit(cid, a))
            with dpg.group():
                self._build_options(spec)

    def _build_channel_checks(self, spec, roles, eus) -> None:
        cid = spec.chart_id
        shown = rev80_charts.vibration_channels_of(roles)
        absent = [ch for ch in spec.channels if ch not in roles]
        with dpg.group(horizontal=True):
            for ch in sorted(set(shown) | set(absent)):
                tag = ui.charts_row_ch(cid, ch)
                checked = ch in spec.channels
                name = self.collector.config.name_for(ch)
                if ch not in roles:
                    dpg.add_checkbox(label=f'{name} (not present)', tag=tag,
                                     default_value=True,
                                     callback=lambda s, a, u: self.set_channel(cid, u, a),
                                     user_data=ch)
                    self.host._tooltip(tag, "Not in the data now. The chart keeps it.")
                    continue
                ok, why = rev80_charts.channel_selectable(spec, ch, roles, eus)
                # A checked channel stays enabled, so it can be unchecked.
                dpg.add_checkbox(label=name, tag=tag, default_value=checked,
                                 enabled=ok or checked,
                                 callback=lambda s, a, u: self.set_channel(cid, u, a),
                                 user_data=ch)
                theme = self._check_theme(ch)
                if theme is not None:
                    dpg.bind_item_theme(tag, theme)
                if not ok:
                    self.host._tooltip(tag, why)
        if not shown and not absent:
            dpg.add_text("No vibration channel", color=_c('YELLOW'))

    def _build_xy_selectors(self, spec, roles) -> None:
        cid = spec.chart_id
        chans = rev80_charts.vibration_channels_of(roles)
        chans += [ch for ch in dict.fromkeys(spec.channels) if ch not in roles]
        by_ch = self._labels(chans, absent=[ch for ch in chans if ch not in roles])
        names = {n: ch for ch, n in by_ch.items()}
        with dpg.group(horizontal=True):
            for axis, label in ((0, 'X'), (1, 'Y')):
                current = spec.channels[axis] if len(spec.channels) > axis else None
                dpg.add_text(label)
                dpg.add_combo(list(names), width=_XY_W,
                              default_value=by_ch.get(current, ''),
                              tag=ui.charts_row(cid, f'xy{axis}'),
                              callback=lambda s, a, u: self.set_xy(cid, u, names[a]),
                              user_data=axis)
            dpg.add_button(label="Swap", tag=ui.charts_row(cid, 'swap'),
                           callback=lambda: self.swap_xy(cid))

    def _build_options(self, spec) -> None:
        cid = spec.chart_id
        if spec.chart_type == 'trend':
            tachs = self._tach_channels()
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="Shaft speed", default_value=spec.show_rpm,
                                 tag=ui.charts_row(cid, 'rpm'), enabled=bool(tachs) or spec.show_rpm,
                                 callback=lambda s, a: self.set_show_rpm(cid, a))
                if spec.show_rpm:
                    by_ch = self._labels(tachs)
                    names = {n: ch for ch, n in by_ch.items()}
                    current = by_ch.get(spec.tach_channel, '')
                    dpg.add_combo(list(names), default_value=current, width=_XY_W,
                                  tag=ui.charts_row(cid, 'tach'),
                                  callback=lambda s, a: self.set_tach(cid, names[a]))
            if not tachs:
                self.host._tooltip(ui.charts_row(cid, 'rpm'),
                                   "No tachometer channel. Set one up on the Tachometer tab.")
        elif spec.chart_type == 'spectrum':
            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="Average", default_value=spec.averaging,
                                 tag=ui.charts_row(cid, 'avg'),
                                 callback=lambda s, a: self.set_averaging(cid, a))
                if spec.averaging:
                    n = min(spec.n_averages, self._cache_depth())
                    dpg.add_input_int(default_value=n, min_value=1, max_value=self._cache_depth(),
                                      min_clamped=True, max_clamped=True, width=_N_W,
                                      tag=ui.charts_row(cid, 'n'),
                                      callback=lambda s, a: self.set_n_averages(cid, a))
                    dpg.add_text(self._window_text(n), tag=ui.charts_row(cid, 'window'))
        else:
            dpg.add_text("")

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def _channel_context(self) -> tuple[dict, dict]:
        """({ch: role}, {ch: sensor EU or None}) of the enabled channels."""
        cfg = self.collector.config
        roles = {ch: cfg.role_for(ch) for ch in cfg.enabled_channels}
        eus = {}
        for ch in roles:
            sensor = self.collector.scope_sensors.get(ch)
            eus[ch] = sensor.engineering_units if sensor is not None else None
        return roles, eus

    def _labels(self, chans, absent=()) -> dict[int, str]:
        """{ch: combo label}, unique: a repeated name gets its channel number."""
        name_for = self.collector.config.name_for
        names = [name_for(ch) for ch in chans]
        out = {}
        for ch, name in zip(chans, names):
            label = f'{name} (ch{ch})' if names.count(name) > 1 else name
            out[ch] = f'{label} (not present)' if ch in absent else label
        return out

    def _tach_channels(self) -> list[int]:
        return list(self.collector.config.tach_channels)

    def _cache_depth(self) -> int:
        return max(1, int(self.collector.config.cache_frames))

    def _window_text(self, n: int) -> str:
        return f"{n * self.collector.config.acquisition_period:.1f} s"

    def _add_type(self) -> str:
        label = dpg.get_value(ui.CHARTS_TAB_ADD_TYPE)
        by_label = {v: k for k, v in rev80_charts.CHART_TYPE_LABELS.items()}
        return by_label.get(label, 'spectrum')

    def _check_theme(self, ch: int):
        colors = self.host._channel_colors
        if not colors:
            return None
        if ch not in self._check_themes:
            with dpg.theme() as t:
                with dpg.theme_component(dpg.mvCheckbox):
                    dpg.add_theme_color(dpg.mvThemeCol_CheckMark, colors[ch % len(colors)])
            self._check_themes[ch] = t
        return self._check_themes[ch]
