"""Main-window charts: one tab for each chart of the layout in effect.

`ChartsView` builds the tabs and the result cards from
`DataCollector.chart_layout()` and draws them from one frame snapshot. The
chart sets the unit and amplitude mode of every series on it; the record
unit of a channel sets only what is stored.

Rules (CONTRIBUTING.md, "4.1 Threads and data flow"):

- A chart's series are drawn only while the chart is on screen. The result
  cards of every spectrum chart update on each frame, open or closed.
- A channel that cannot show the chart unit, or that is not in the data,
  has an empty series and the reason in its legend label. Never mV under an
  engineering-unit axis.
- Crest factor and kurtosis are never averaged; a spectrum chart averages
  its own spectrum and overall over contiguous valid frames.

Render thread only. The host is the GUI: it gives `collector`, the channel
and peak themes, `_sect_theme`, `_tooltip()`, `_band_suffix()` and the
time-window constants.
"""

from __future__ import annotations

import logging
import math

import dearpygui.dearpygui as dpg
import numpy as np

import rev80
from rev80 import _profile
from rev80 import charts as rev80_charts
from rev80 import envelope as rev80_env
from rev80.util import UNIT_TO_SI, UI_Elements as ui, amplitude_scale

log = logging.getLogger(__name__)

#: Height of one result card in the results column.
CARD_HEIGHT = 232
CARD_FIELD_W = 150
#: Clutter cap on a peaks table and the plot markers. Not a selection rule:
#: rev80.peaks decides which lines are real. Sized from the corpus counts at
#: the default threshold (median 40, p90 49, max 61 over 60 channel-spectra),
#: so in the normal case nothing is hidden.
DEFAULT_PEAK_DISPLAY_CAP = 50
# Ratio of a sample rate to the top of its anti-alias-protected band. The
# same 2.56 as AcquisitionSettings.samplerate = 2.56 x maxfreq: at 25600 Hz
# raw, the protected band ends at 10 kHz.
PROTECTED_BAND_RATIO = 2.56


def _c(key: str, alpha: int = 255) -> tuple:
    return rev80.hex_to_rgba(rev80.THEME_COLORS[key], alpha)


def envelope_search_fmax(samplerate: float) -> float:
    """Top of the protected band, as the fmax for envelope.suggest_band.

    Above it, the anti-alias filter attenuates the signal. A demodulation
    band there shows filter roll-off, not machine content.
    """
    return samplerate / PROTECTED_BAND_RATIO


def envelope_scale(sensor_eu: str, unit: str, mode: str) -> float:
    """Factor from the envelope spectrum in the sensor EU, 0-P, to `unit` `mode`.

    The envelope spectrum reads d·A/2 for a modulation of depth d on a
    carrier A: the 0-P amplitude of a sideband. The unit is the same
    quantity as the sensor EU (no integration), so only the SI scale and
    the amplitude mode change.
    """
    si = UNIT_TO_SI.get(sensor_eu, 1.0) / UNIT_TO_SI.get(unit, 1.0)
    return si * amplitude_scale(mode) / amplitude_scale('0-P')


def averaging_text(n_got: int, n_want: int, gap: bool) -> str:
    """'averaging k of N frames', with the reason when a gap in time stopped the walk."""
    got = int(n_got)
    suffix = '' if got >= n_want else f' of {n_want}'
    reason = ' (frames not contiguous)' if got < n_want and gap else ''
    return f'averaging {got}{suffix} frames{reason}'


def same_time_indices(t_x: np.ndarray, t_y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Indices of the samples of two traces of one frame that have the same time.

    Two channels in one chart unit can need a different number of
    integration steps, and so have a different overlap-save trim. A pair by
    index would then join samples that are not simultaneous.
    """
    t_x, t_y = np.asarray(t_x, dtype=float), np.asarray(t_y, dtype=float)
    if len(t_x) < 2 or len(t_y) < 2:
        n = min(len(t_x), len(t_y))
        return np.arange(n), np.arange(n)
    period = float(t_x[1] - t_x[0])
    kx = np.rint(t_x / period).astype(np.int64)
    ky = np.rint(t_y / period).astype(np.int64)
    _, ix, iy = np.intersect1d(kx, ky, assume_unique=True, return_indices=True)
    return ix, iy


def chart_id_of_tab(alias: str) -> str | None:
    """The chart id of a tab alias from `ui.chart_tab()`, else None."""
    if alias and alias.startswith('CHART_') and alias.endswith('_TAB'):
        return alias[len('CHART_'):-len('_TAB')]
    return None


class ChartsView:
    """The chart tabs and the spectrum result cards of the main window."""

    def __init__(self, host):
        self.host = host
        self.layout = rev80_charts.ChartSet(())
        self._peak_rows: dict[tuple, int] = {}
        self._peak_state: dict[tuple, tuple] = {}
        self._time_x0_ms: dict[str, float] = {}
        self._env_auto_band: dict[tuple, tuple] = {}
        self._burst_times: list[float] = []

    @property
    def collector(self):
        return self.host.collector

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def rebuild(self) -> None:
        """Build the tabs and the cards again from the layout in effect.

        The selected chart stays selected if it is still in the layout.
        """
        selected = self.selected_chart_id()
        self.layout = self.collector.chart_layout()
        self._peak_rows.clear()
        self._peak_state.clear()
        self._env_auto_band.clear()
        self._time_x0_ms.clear()
        roles, eus = self._channel_context()
        if dpg.does_item_exist(ui.MAIN_CHART_TAB_BAR):
            dpg.delete_item(ui.MAIN_CHART_TAB_BAR, children_only=True)
            for spec in self.layout.charts:
                self._build_tab(spec, roles, eus)
            keep = selected if self.layout.chart(selected or '') else None
            if keep is None and self.layout.charts:
                keep = self.layout.charts[0].chart_id
            if keep is not None:
                dpg.set_value(ui.MAIN_CHART_TAB_BAR, ui.chart_tab(keep))
        if dpg.does_item_exist(ui.CHART_CARDS):
            dpg.delete_item(ui.CHART_CARDS, children_only=True)
            for spec in self.layout.charts:
                if spec.chart_type == 'spectrum':
                    self._build_cards(spec, roles, eus)
        self.set_burst_lines(self._burst_times)
        # The new series and cards are empty: draw the frame on screen again.
        self.host._redraw()

    def selected_chart_id(self) -> str | None:
        if not dpg.does_item_exist(ui.MAIN_CHART_TAB_BAR):
            return None
        try:
            value = dpg.get_value(ui.MAIN_CHART_TAB_BAR)
            alias = dpg.get_item_alias(value) if value else ''
        except Exception:                                    # noqa: BLE001
            return None
        return chart_id_of_tab(alias or '')

    def _channel_context(self) -> tuple[dict, dict]:
        """({ch: role}, {ch: sensor EU or None}) for the channels present."""
        cfg = self.collector.config
        roles = {ch: cfg.role_for(ch) for ch in cfg.enabled_channels}
        eus = {}
        for ch in roles:
            sensor = self.collector.scope_sensors.get(ch)
            eus[ch] = sensor.engineering_units if sensor is not None else None
        return roles, eus

    def _series_channels(self, spec, roles=None) -> list[int]:
        """The channels of `spec` that get a series: no tachometer, no repeats.

        The role comes from the config, not from `roles`, which holds the
        enabled channels only: a disabled tachometer is still a tachometer.
        """
        role_for = self.collector.config.role_for
        return [ch for ch in dict.fromkeys(spec.channels) if role_for(ch) != 'tachometer']

    def _series_label(self, spec, ch, roles, eus) -> str:
        name = self.collector.config.name_for(ch)
        if ch not in roles:
            return f'{name}: not present'
        ok, why = rev80_charts.channel_selectable(spec, ch, roles, eus)
        return name if ok else f'{name}: {why}'

    def _y_label(self, spec) -> str:
        unit, mode = spec.unit, spec.amplitude_mode
        if spec.chart_type == 'trend':
            return f'Overall, {unit} {mode}{self.host._band_suffix()}'
        if spec.chart_type == 'envelope':
            return f'Envelope, {unit} {mode}'
        if spec.chart_type == 'spectrum':
            return f'Amplitude, {unit} {mode}'
        return f'Amplitude, {unit}'

    def _build_tab(self, spec, roles, eus) -> None:
        cid = spec.chart_id
        with dpg.tab(label=spec.name, tag=ui.chart_tab(cid), parent=ui.MAIN_CHART_TAB_BAR):
            problems = rev80_charts.problems(spec, roles, eus)
            dpg.add_text('; '.join(problems), tag=ui.chart_note(cid),
                         color=_c('YELLOW'), wrap=0, show=bool(problems))
            if spec.chart_type == 'envelope':
                self._build_envelope_controls(spec)
            x_label = {
                'waveform': 'Time, ms', 'spectrum': 'Frequency, Hz', 'trend': 'Time, s',
                'envelope': 'Modulation frequency, Hz',
                'xy': f'{self._xy_name(spec, 0)}, {spec.unit}',
            }[spec.chart_type]
            y_label = (f'{self._xy_name(spec, 1)}, {spec.unit}' if spec.chart_type == 'xy'
                       else self._y_label(spec))
            with dpg.plot(width=-1, height=-1, tag=ui.chart_plot(cid), crosshairs=True,
                          equal_aspects=spec.chart_type == 'xy'):
                dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=ui.chart_legend(cid))
                dpg.add_plot_axis(dpg.mvXAxis, label=x_label, tag=ui.chart_axis(cid, 'x'))
                dpg.add_plot_axis(dpg.mvYAxis, label=y_label, tag=ui.chart_axis(cid, 'y'))
                if spec.chart_type == 'trend' and spec.show_rpm:
                    dpg.add_plot_axis(dpg.mvYAxis2, label=self._rpm_axis_label(),
                                      tag=ui.chart_axis(cid, 'y2'))
            self._build_series(spec, roles, eus)

    def _xy_name(self, spec, i: int) -> str:
        if len(spec.channels) > i:
            return self.collector.config.name_for(spec.channels[i])
        return 'X' if i == 0 else 'Y'

    def _rpm_axis_label(self) -> str:
        from rev80.util import DEFAULT_ROTATION_UNIT, ROTATION_UNIT_LABELS
        unit = self.collector.config.rotation_unit or DEFAULT_ROTATION_UNIT
        return f'Shaft speed, {ROTATION_UNIT_LABELS.get(unit, unit)}'

    def _build_series(self, spec, roles, eus) -> None:
        cid = spec.chart_id
        y_axis = ui.chart_axis(cid, 'y')
        themes = self.host._channel_themes
        if spec.chart_type == 'xy':
            if len(spec.channels) == 2:
                ch = spec.channels[1]
                tag = ui.chart_series(cid, ch)
                label = f'{self._xy_name(spec, 1)} against {self._xy_name(spec, 0)}'
                dpg.add_line_series([], [], label=label, tag=tag, parent=y_axis)
                if themes:
                    dpg.bind_item_theme(tag, themes[ch % len(themes)])
            return
        for ch in self._series_channels(spec, roles):
            tag = ui.chart_series(cid, ch)
            dpg.add_line_series([], [], label=self._series_label(spec, ch, roles, eus),
                                tag=tag, parent=y_axis)
            if themes:
                dpg.bind_item_theme(tag, themes[ch % len(themes)])
            if spec.chart_type == 'spectrum':
                # Vertical marker at the shaft rate. A line's frequency is
                # diagnostic only relative to 1x.
                dpg.add_inf_line_series([], label=f'##onex_{cid}_{ch}',
                                        tag=ui.chart_one_x(cid, ch), parent=y_axis)
                peaks = ui.chart_peaks(cid, ch)
                dpg.add_scatter_series([], [], label=f'##peaks_{cid}_{ch}', tag=peaks,
                                       parent=y_axis)
                if self.host._peak_themes:
                    pt = self.host._peak_themes
                    dpg.bind_item_theme(peaks, pt[ch % len(pt)])
        if spec.chart_type == 'trend' and spec.show_rpm and spec.tach_channel is not None:
            if dpg.does_item_exist(ui.chart_axis(cid, 'y2')):
                tag = ui.chart_series(cid, spec.tach_channel)
                dpg.add_line_series([], [], tag=tag, parent=ui.chart_axis(cid, 'y2'),
                                    label=f'{self.collector.config.name_for(spec.tach_channel)}'
                                          f' shaft speed')

    def _build_envelope_controls(self, spec) -> None:
        # A bearing defect's impulses ring a housing resonance at 2-20 kHz
        # and are modulated at the defect rate; the envelope of the resonance
        # shows that as a clean line.
        cid = spec.chart_id
        dpg.add_text('', tag=ui.chart_env(cid, 'warn'), color=_c('YELLOW'), show=False, wrap=0)
        with dpg.group(horizontal=True):
            dpg.add_text('Band')
            dpg.add_input_float(label='-', tag=ui.chart_env(cid, 'lo'), default_value=0.0,
                                min_value=0.0, step=0, format='%.0f', width=80,
                                callback=lambda *_: self._on_env_band_change(cid))
            dpg.add_input_float(label='Hz', tag=ui.chart_env(cid, 'hi'), default_value=0.0,
                                min_value=0.0, step=0, format='%.0f', width=80,
                                callback=lambda *_: self._on_env_band_change(cid))
            auto = dpg.add_button(label='Auto', tag=ui.chart_env(cid, 'auto'),
                                  callback=lambda *_: self._on_env_auto_band(cid))
            self.host._tooltip(
                auto,
                "Pick a demodulation band from the current frame: the strongest "
                "concentration of high-frequency energy, which is where a housing "
                "resonance shows up. Leave the band at 0 to auto-select every frame.")
        dpg.add_text('', tag=ui.chart_env(cid, 'info'), color=_c('MUTED'))

    def _build_cards(self, spec, roles, eus) -> None:
        cid = spec.chart_id
        band = self.host._band_suffix()
        with dpg.collapsing_header(label=spec.name, default_open=True,
                                   tag=ui.card_group(cid), parent=ui.CHART_CARDS):
            for ch in self._series_channels(spec, roles):
                with dpg.child_window(border=True, autosize_x=True, height=CARD_HEIGHT,
                                      no_scrollbar=True, tag=ui.card(cid, ch)) as card:
                    if self.host._sect_theme is not None:
                        dpg.bind_item_theme(card, self.host._sect_theme)
                    with dpg.group(horizontal=True):
                        with dpg.drawlist(width=14, height=14):
                            colours = self.host._channel_colors or [_c('BLUE')]
                            dpg.draw_rectangle(pmin=(2, 2), pmax=(12, 12),
                                               fill=colours[ch % len(colours)],
                                               color=(0, 0, 0, 0), rounding=2)
                        dpg.add_text(self._series_label(spec, ch, roles, eus))
                    dpg.add_separator()
                    dpg.add_input_text(label=f'Overall, {spec.unit} {spec.amplitude_mode}{band}',
                                       tag=ui.card(cid, ch, 'overall'), readonly=True,
                                       default_value='--', width=CARD_FIELD_W)
                    sc = dpg.add_text('Crest -   Kurt -', tag=ui.card(cid, ch, 'scalars'),
                                      color=_c('MUTED'))
                    ox = dpg.add_text('', tag=ui.card(cid, ch, 'one_x'), color=_c('MUTED'),
                                      show=False)
                    dpg.add_text('', tag=ui.card(cid, ch, 'avg'), color=_c('MUTED'),
                                 show=spec.averaging)
                    dpg.add_text('', tag=ui.card(cid, ch, 'found'), color=_c('MUTED'))
                    self.host._tooltip(
                        ox,
                        "Vibration level at 1x shaft rate.\n\n1x rarely lands on a bin "
                        "centre, so this is the larger of the two bins straddling it -- no "
                        "interpolation, the same rule the peak table uses.")
                    self.host._tooltip(
                        sc,
                        "Crest factor = peak / RMS: 1.41 for a pure sine, ~3-4 for random "
                        "noise, higher when the signal is impulsive.\n\nKurtosis = 3.0 for "
                        "random noise, 1.5 for a pure sine. Above about 4 means impulsive. "
                        "Neither is averaged.")
                    dpg.add_table(header_row=True, row_background=True, borders_innerV=True,
                                  no_host_extendX=True, tag=ui.card(cid, ch, 'peaks'))

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def on_screen(self, cid: str) -> bool:
        """True when the chart's plot is rendered. Fails open on a query error.

        Queries the plot, not the tab: an unselected tab shows its header
        button, so the tab always reports visible.
        """
        tag = ui.chart_plot(cid)
        if not dpg.does_item_exist(tag):
            return False
        try:
            return bool(dpg.is_item_visible(tag))
        except Exception:                                    # noqa: BLE001
            return True

    def n_averages_for(self, spec) -> int:
        """The frames a spectrum chart averages, clamped to the cache depth."""
        if not spec.averaging:
            return 1
        return max(1, min(int(spec.n_averages), int(self.collector.config.cache_frames)))

    def render(self, snapshot, force: str | None = None) -> None:
        """Draw the charts on screen and the cards of every spectrum chart.

        `force` is a chart id to draw also when it is not on screen yet: a
        tab change. dearpygui reports a new tab's plot visible only after it
        draws it.
        """
        roles, _ = self._channel_context()
        for spec in self.layout.charts:
            visible = spec.chart_id == force or self.on_screen(spec.chart_id)
            kind = spec.chart_type
            if kind == 'spectrum':
                views = self._spectrum_views(spec, snapshot, roles)
                self._update_cards(spec, views)
                if visible:
                    self._draw_spectrum(spec, views)
            elif not visible:
                continue
            elif kind == 'waveform':
                self._draw_waveform(spec, snapshot, roles)
            elif kind == 'trend':
                self._draw_trend(spec, roles)
            elif kind == 'envelope':
                with _profile.timed(_profile.GUI_ENVELOPE):
                    self._draw_envelope(spec, snapshot, roles)
            elif kind == 'xy':
                self._draw_xy(spec, snapshot)
        self.update_cursors(snapshot)

    def _spectrum_views(self, spec, snapshot, roles) -> dict:
        n = self.n_averages_for(spec)
        return {ch: self.collector.result_view(snapshot, ch, spec.unit, spec.amplitude_mode,
                                               n_averages=n, peaks=True)
                for ch in self._series_channels(spec, roles)}

    @staticmethod
    def _set(tag, value) -> None:
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, value)

    @staticmethod
    def _peak_cap() -> int:
        tag = ui.FFT_PEAKS_DISPLAY_COUNT
        value = dpg.get_value(tag) if dpg.does_item_exist(tag) else None
        return max(1, int(value or DEFAULT_PEAK_DISPLAY_CAP))

    def _draw_spectrum(self, spec, views: dict) -> None:
        cid = spec.chart_id
        cap = self._peak_cap()
        for ch, r in views.items():
            if r is None:
                for tag in (ui.chart_series(cid, ch), ui.chart_peaks(cid, ch)):
                    self._set(tag, [[], []])
                self._set(ui.chart_one_x(cid, ch), [[]])
                continue
            self._set(ui.chart_series(cid, ch), [r.freq.tolist(), r.spectrum.tolist()])
            top = r.peaks[:cap]
            self._set(ui.chart_peaks(cid, ch),
                      [r.freq[top].tolist(), r.spectrum[top].tolist()] if len(top) else [[], []])
            f_1x = r.one_x_hz
            self._set(ui.chart_one_x(cid, ch), [[float(f_1x)]] if f_1x is not None else [[]])

    def _update_cards(self, spec, views: dict) -> None:
        cid = spec.chart_id
        cap = self._peak_cap()
        want = self.n_averages_for(spec)
        for ch, r in views.items():
            if r is None:
                self._set(ui.card(cid, ch, 'overall'), '--')
                self._set(ui.card(cid, ch, 'scalars'), 'Crest -   Kurt -')
                self._set(ui.card(cid, ch, 'found'), '')
                self._set(ui.card(cid, ch, 'avg'), '')
                if dpg.does_item_exist(ui.card(cid, ch, 'one_x')):
                    dpg.configure_item(ui.card(cid, ch, 'one_x'), show=False)
                self._update_peaks_table(cid, ch, ['Frequency (Hz)', 'Amp.'], [])
                continue
            self._set(ui.card(cid, ch, 'overall'), f'{r.overall:.4f}')
            self._set(ui.card(cid, ch, 'scalars'),
                      f'Crest {r.crest_factor:.2f}   Kurt {r.kurtosis:.2f}')
            self._update_one_x_text(cid, ch, r)
            if spec.averaging:
                self._set(ui.card(cid, ch, 'avg'),
                          averaging_text(r.n_averages, want, r.averaging_gap))
            n_found = len(r.peaks)
            self._set(ui.card(cid, ch, 'found'),
                      'no significant peaks' if n_found == 0
                      else f'{n_found} peaks, showing {cap}' if n_found > cap
                      else f'{n_found} peaks')
            top = r.peaks[:cap]
            rows = list(zip(np.round(r.freq[top], 2).tolist(),
                            np.round(r.spectrum[top], 6).tolist()))
            self._update_peaks_table(
                cid, ch, ['Frequency (Hz)', f'Amp., {r.unit} {spec.amplitude_mode}'], rows)

    def _update_one_x_text(self, cid, ch, r) -> None:
        """The 1x level, or hidden with no shaft-speed reading: never 0.0."""
        tag = ui.card(cid, ch, 'one_x')
        if not dpg.does_item_exist(tag):
            return
        if r.one_x_hz is None:
            dpg.configure_item(tag, show=False)
            return
        amp = r.one_x_amplitude
        shown = '--' if amp is None else f'{amp:.4g} {r.unit} {r.amplitude_mode}'
        dpg.set_value(tag, f'1x @ {r.one_x_hz:.2f} Hz:  {shown}')
        dpg.configure_item(tag, show=True)

    def _update_peaks_table(self, cid, ch, columns, rows) -> None:
        """Refresh one card's peaks table in place, reusing its widgets.

        Rows are a pool: created on demand, then updated with set_value;
        surplus rows are hidden, not deleted. Only what changed since the
        last frame is pushed: the cells that differ, and the show state of
        the rows between the old and the new count. Evidence:
        CONTRIBUTING.md, "E19. GUI render cost".
        """
        with _profile.timed(_profile.GUI_PEAKS_TBL):
            table = ui.card(cid, ch, 'peaks')
            if not dpg.does_item_exist(table):
                return
            key = (cid, ch)
            columns, rows = tuple(columns), tuple(rows)
            known = key in self._peak_state
            old_cols, old_rows = self._peak_state.get(key, ((), ()))
            if known and (old_cols, old_rows) == (columns, rows):
                return
            self._peak_state[key] = (columns, rows)
            if columns != old_cols:
                for c, label in enumerate(columns):
                    col = ui.card_peak_col(cid, ch, c)
                    if dpg.does_item_exist(col):
                        dpg.configure_item(col, label=label)
                    else:
                        dpg.add_table_column(label=label, tag=col, parent=table)
            pool = self._peak_rows.get(key, 0)
            # With no known state (after a clear), any pooled row can be shown.
            n_old = len(old_rows) if known else pool
            while pool < len(rows):
                with dpg.table_row(parent=table, tag=ui.card_peak_row(cid, ch, pool)):
                    for c in range(len(columns)):
                        dpg.add_text('', tag=ui.card_peak_cell(cid, ch, pool, c))
                pool += 1
            self._peak_rows[key] = pool
            for i, row in enumerate(rows):
                before = old_rows[i] if i < len(old_rows) else None
                for c, value in enumerate(row):
                    if before is None or before[c] != value:
                        dpg.set_value(ui.card_peak_cell(cid, ch, i, c), f'{value}')
            n_new = len(rows)
            first = min(n_old, n_new) if known else 0
            for i in range(first, max(n_old, n_new)):
                dpg.configure_item(ui.card_peak_row(cid, ch, i), show=i < n_new)

    def _draw_waveform(self, spec, snapshot, roles) -> None:
        cid = spec.chart_id
        for ch in self._series_channels(spec, roles):
            r = self.collector.result_view(snapshot, ch, spec.unit, None, peaks=False)
            if r is None:
                self._set(ui.chart_series(cid, ch), [[], []])
                continue
            t_ms = r.time_vec * 1000.0
            # Integrated traces cover only the middle of the block
            # (overlap-save), so the trace can start after t = 0.
            if len(t_ms):
                self._time_x0_ms[cid] = float(t_ms[0])
            self._set(ui.chart_series(cid, ch), [t_ms.tolist(), r.time_data.tolist()])

    def _draw_trend(self, spec, roles) -> None:
        cid = spec.chart_id
        channels = self._series_channels(spec, roles)
        data = self.collector.get_trend_for_display(spec.unit, spec.amplitude_mode, channels)
        for ch in channels:
            times, values = data.get(ch, ([], []))
            self._set(ui.chart_series(cid, ch), [list(times), list(values)])
        if spec.show_rpm and spec.tach_channel is not None:
            self._draw_rpm(spec)

    def _draw_rpm(self, spec) -> None:
        """Shaft speed on y2: usable readings only, in the rotation unit. No unit scaling."""
        from rev80.util import DEFAULT_ROTATION_UNIT, rotation_from_rpm
        unit = self.collector.config.rotation_unit or DEFAULT_ROTATION_UNIT
        times, rpm = self.collector.get_rpm_trend().get(spec.tach_channel, ([], []))
        xs, ys = [], []
        for t, r in zip(times, rpm):
            v = rotation_from_rpm(r, unit)
            if v is not None and math.isfinite(v):
                xs.append(float(t))
                ys.append(float(v))
        self._set(ui.chart_series(spec.chart_id, spec.tach_channel), [xs, ys])

    def _draw_xy(self, spec, snapshot) -> None:
        """Channel Y against channel X, the same frame and the same unit and span."""
        cid = spec.chart_id
        if len(spec.channels) != 2 or spec.channels[0] == spec.channels[1]:
            return
        cx, cy = spec.channels
        tag = ui.chart_series(cid, cy)
        if len(self._series_channels(spec)) != 2:
            self._set(tag, [[], []])               # a tachometer is never a trace
            return
        rx = self.collector.result_view(snapshot, cx, spec.unit, None, peaks=False)
        ry = self.collector.result_view(snapshot, cy, spec.unit, None, peaks=False)
        if rx is None or ry is None:
            self._set(tag, [[], []])
            return
        ix, iy = same_time_indices(rx.time_vec, ry.time_vec)
        self._set(tag, [rx.time_data[ix].tolist(), ry.time_data[iy].tolist()])

    # ------------------------------------------------------------------
    # Envelope
    # ------------------------------------------------------------------

    def _env_band(self, cid, signal, samplerate, ch):
        """The typed band, else the auto band of this frame (cached), else None."""
        lo_tag, hi_tag = ui.chart_env(cid, 'lo'), ui.chart_env(cid, 'hi')
        lo = float(dpg.get_value(lo_tag) or 0.0) if dpg.does_item_exist(lo_tag) else 0.0
        hi = float(dpg.get_value(hi_tag) or 0.0) if dpg.does_item_exist(hi_tag) else 0.0
        if lo > 0 and hi > lo:
            return (lo, hi)
        # Cached, so the auto band and the envelope axis stay the same from
        # frame to frame. A new sample rate makes a new key.
        key = (cid, ch, float(samplerate))
        if key in self._env_auto_band:
            return self._env_auto_band[key]
        try:
            band = rev80_env.suggest_band(signal, samplerate,
                                          fmax=envelope_search_fmax(samplerate))
        except (ValueError, IndexError):
            return None
        self._env_auto_band[key] = band
        return band

    def _on_env_band_change(self, cid) -> None:
        """Band edited by hand: drop the chart's cached auto bands, then redraw."""
        self._env_auto_band = {k: v for k, v in self._env_auto_band.items() if k[0] != cid}
        self.host._redraw()

    def _on_env_auto_band(self, cid) -> None:
        """Fill the band fields from the frame on screen, then redraw."""
        spec = self.layout.chart(cid)
        if spec is None:
            return
        snapshot = self.collector.snapshot()
        roles, _ = self._channel_context()
        ch = next((c for c in self._series_channels(spec, roles) if c in snapshot.frame), None)
        if ch is None:
            return
        signal, samplerate, _eu = self.collector.eu_scaled_raw(ch, snapshot.frame[ch])
        self._env_auto_band = {k: v for k, v in self._env_auto_band.items() if k[0] != cid}
        band = self._env_band(cid, signal, samplerate, ch)
        if band is None:
            return
        dpg.set_value(ui.chart_env(cid, 'lo'), float(band[0]))
        dpg.set_value(ui.chart_env(cid, 'hi'), float(band[1]))
        self.host._redraw()

    def envelope_series(self, spec, ch, sample):
        """(freq, amplitude) of one channel's envelope spectrum in the chart unit, or None."""
        sensor = self.collector.scope_sensors.get(ch)
        eu = sensor.engineering_units if sensor is not None else None
        if sample is None or not rev80_charts.unit_reachable(eu, spec.unit, 'envelope'):
            return None
        signal, samplerate, sensor_eu = self.collector.eu_scaled_raw(ch, sample)
        self._update_env_warning(spec.chart_id, samplerate)
        band = self._env_band(spec.chart_id, signal, samplerate, ch)
        if band is None:
            return None
        try:
            freq, amp = rev80_env.envelope_spectrum(signal, samplerate, band=band)
        except ValueError:
            self._set(ui.chart_env(spec.chart_id, 'info'),
                      f'band {band[0]:.0f}-{band[1]:.0f} Hz is outside this frame\'s usable range')
            return None
        info = ui.chart_env(spec.chart_id, 'lo')
        auto = ('' if dpg.does_item_exist(info) and float(dpg.get_value(info) or 0.0) > 0
                else '  (auto)')
        if len(freq):
            self._set(ui.chart_env(spec.chart_id, 'info'),
                      f'demodulating {band[0]:.0f}-{band[1]:.0f} Hz{auto}   '
                      f'envelope to {freq[-1]:.0f} Hz')
        return freq, amp * envelope_scale(sensor_eu, spec.unit, spec.amplitude_mode)

    def _draw_envelope(self, spec, snapshot, roles) -> None:
        for ch in self._series_channels(spec, roles):
            out = self.envelope_series(spec, ch, snapshot.frame.get(ch))
            tag = ui.chart_series(spec.chart_id, ch)
            self._set(tag, [[], []] if out is None else [out[0].tolist(), out[1].tolist()])

    def _update_env_warning(self, cid, samplerate) -> None:
        """Warn when the raw-rate Nyquist is below envelope.MIN_USEFUL_NYQUIST_HZ."""
        tag = ui.chart_env(cid, 'warn')
        if not dpg.does_item_exist(tag):
            return
        nyquist = samplerate / 2.0
        if nyquist < rev80_env.MIN_USEFUL_NYQUIST_HZ:
            dpg.set_value(tag, f"This recording's acquisition bandwidth gives only "
                               f"{nyquist:.0f} Hz of headroom -- a bearing resonance "
                               f"(typically 2-20 kHz) may not fit under Nyquist at all. "
                               f"Envelope results here should not be trusted for genuine "
                               f"defect detection.")
            dpg.configure_item(tag, show=True)
        else:
            dpg.configure_item(tag, show=False)

    # ------------------------------------------------------------------
    # Trend cursor and burst lines
    # ------------------------------------------------------------------

    def update_cursors(self, snapshot) -> None:
        """A line on each trend chart at the browsed frame; hidden while streaming."""
        rel_time = None
        if not self.collector.is_streaming and snapshot.frame:
            sample = next((v for k, v in snapshot.frame.items() if isinstance(k, int)), None)
            rel_time = None if sample is None else float(sample.rel_time)
        for spec in self.layout.charts:
            if spec.chart_type != 'trend':
                continue
            tag = ui.chart_cursor(spec.chart_id)
            axis = ui.chart_axis(spec.chart_id, 'y')
            if rel_time is None:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, show=False)
                continue
            if not dpg.does_item_exist(axis):
                continue
            if not dpg.does_item_exist(tag):
                dpg.add_inf_line_series([rel_time], tag=tag, parent=axis, label='##cursor')
                dpg.bind_item_theme(tag, self._cursor_theme())
            else:
                dpg.set_value(tag, [[rel_time]])
            dpg.configure_item(tag, show=True)

    def _cursor_theme(self) -> int:
        """The theme of the trend cursor, made once."""
        theme = getattr(self, '_cursor_theme_id', None)
        if theme is None or not dpg.does_item_exist(theme):
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_color(dpg.mvPlotCol_Line, _c('RED_LIGHT', 220))
                    dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5)
            self._cursor_theme_id = theme
        return theme

    def set_burst_lines(self, rel_times) -> None:
        """Vertical lines at the burst trigger times on every trend chart; [] removes them."""
        self._burst_times = list(rel_times)
        for spec in self.layout.charts:
            if spec.chart_type != 'trend':
                continue
            tag = ui.chart_bursts(spec.chart_id)
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
            axis = ui.chart_axis(spec.chart_id, 'y')
            if self._burst_times and dpg.does_item_exist(axis):
                dpg.add_inf_line_series(self._burst_times, parent=axis, tag=tag, label='Burst')

    # ------------------------------------------------------------------
    # Axes, legends, clear
    # ------------------------------------------------------------------

    def autoscale(self, time_window_offset_ms: float, time_window_range_ms: float) -> list[str]:
        """Scale every chart's axes; returns the axes locked with set_axis_limits.

        The host releases them one frame later, so the user can pan and zoom.
        """
        locked: list[str] = []
        roles, _ = self._channel_context()
        for spec in self.layout.charts:
            cid = spec.chart_id
            x, y, y2 = (ui.chart_axis(cid, a) for a in ('x', 'y', 'y2'))
            if not dpg.does_item_exist(x):
                continue
            kind = spec.chart_type
            if kind == 'waveform' and self.collector.config.acquisition_period > 0.5:
                start = self._time_x0_ms.get(cid, 0.0) + time_window_offset_ms
                dpg.set_axis_limits(x, start, start + time_window_range_ms)
                locked.append(x)
                dpg.fit_axis_data(y)
            elif kind == 'trend':
                locked += self._autoscale_trend(spec, roles, x, y)
                if dpg.does_item_exist(y2):
                    dpg.fit_axis_data(y2)
            else:
                dpg.fit_axis_data(x)
                dpg.fit_axis_data(y)
        return locked

    def _autoscale_trend(self, spec, roles, x, y) -> list[str]:
        channels = self._series_channels(spec, roles)
        data = self.collector.get_trend_for_display(spec.unit, spec.amplitude_mode, channels)
        times = [t for ch in channels for t in data.get(ch, ([], []))[0] if math.isfinite(t)]
        values = [v for ch in channels for v in data.get(ch, ([], []))[1] if math.isfinite(v)]
        locked = []
        if times:
            pad = max((max(times) - min(times)) * 0.1, 0.5)
            dpg.set_axis_limits(x, min(times) - pad, max(times) + pad)
            locked.append(x)
        else:
            dpg.fit_axis_data(x)
        peak = max(values, default=0.0)
        if peak > 0.0:
            dpg.set_axis_limits(y, 0.0, peak * 1.1)
            locked.append(y)
        else:
            dpg.fit_axis_data(y)
        return locked

    def ensure_legends(self) -> None:
        """Re-create a legend that dearpygui dropped after a series change."""
        for spec in self.layout.charts:
            plot, legend = ui.chart_plot(spec.chart_id), ui.chart_legend(spec.chart_id)
            if dpg.does_item_exist(plot) and not dpg.does_item_exist(legend):
                dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=legend, parent=plot)

    def clear(self) -> None:
        """Empty every series and card: the cache was cleared."""
        for spec in self.layout.charts:
            cid = spec.chart_id
            for ch in set(spec.channels) | ({spec.tach_channel} - {None}):
                for tag in (ui.chart_series(cid, ch), ui.chart_peaks(cid, ch)):
                    self._set(tag, [[], []])
                self._set(ui.chart_one_x(cid, ch), [[]])
            if spec.chart_type == 'spectrum':
                self._update_cards(spec, dict.fromkeys(self._series_channels(spec)))
            tag = ui.chart_cursor(cid)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)
        self._env_auto_band.clear()
