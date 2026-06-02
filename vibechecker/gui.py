# Vibechecker frontend

import threading
from pathlib import Path

import dearpygui.dearpygui as dpg
import numpy as np

import vibechecker
import vibechecker.config as _cfg
import vibechecker.icons as icons
from vibechecker.sample import AcquisitionSettings
from vibechecker.scope_sensor import ScopeSensor
from vibechecker.scope_sensor_registry import ScopeSensorRegistry
from vibechecker.util import UNIT_TO_SI

log = vibechecker.get_logger("gui")
ui = vibechecker.UI_Elements()

# Layout constants
# TODO: make left/right panel widths and plot heights resizable by mouse drag.
#   DPG supports this via dpg.add_drag_line or manual splitter groups; defer
#   until the panel layout is otherwise stable.
WINDOW_WIDTH = 1500
WINDOW_HEIGHT = 1000
CONTROLS_WIDTH = 300
RESULTS_WIDTH = 300
TIME_PLOT_HEIGHT = 300

# Config dialog dimensions — referenced wherever the dialog is built or positioned
_DLG_CFG_W = 720
_DLG_CFG_H = 560
# Field widths inside the config dialog (golden-ratio of dialog width)
_DLG_FIELD_W = int(_DLG_CFG_W * 0.618)  # ~444 px  — full-width text/combo
_SREG_LIST_W = 200  # sensor registry list pane
_SREG_FIELD_W = int((_DLG_CFG_W - _SREG_LIST_W - 40) * 0.618)  # ~297 px

# Channel-row widget widths (inside the Channels tab collapsing headers)
_CH_COUPLING_W = 80
_CH_RANGE_W = 100
_CH_INDENT = 16
_CH_HALF_FIELD_W = _DLG_FIELD_W // 2  # half-width for paired combos on one row

# Height reserved at the bottom of the config dialog for the close-button row
_DLG_CLOSE_H = 36
# Sensor registry button width (Add / Delete)
_SREG_BTN_W = 88
# Signal generator control widget width
_DLG_SIGGEN_W = 160
# Spacer pushing the Device-tab "Refresh" button to the right edge
_DLG_DEVICE_TAB_SPACER = _DLG_CFG_W - 434

_MAX_CHANNELS = 8
_DEFAULT_NUM_CHANNELS = 4
# Height of each per-channel result card so 4 cards fit the default window height
_RESULTS_CARD_HEIGHT = (WINDOW_HEIGHT - 70) // 4  # ≈ 232 px
# Width of paired buttons side-by-side in the left control panel
_BTN_HALF = (CONTROLS_WIDTH - 30) // 2

# Left-panel card heights.  DPG child_window has no shrink-to-content mode:
# autosize_y=True fills the parent rather than the content.  Heights must be
# fixed or dynamically updated.  Estimates based on DPG style metrics with 16px font:
#   text line ≈ 20 px (16 px font + 4 px ItemSpacing.y)
#   button    ≈ 28 px (24 px frame + 4 px spacing)
#   card base ≈ 68 px (top/bottom WindowPadding + title + separator)
_CARD_LINE_H = 20  # per text-line height estimate (font + spacing)
_CARD_BASE_H = 68  # card overhead: padding + title + separator + bottom pad
_CARD_BTN_H = 28   # single button row height
_CARD_H_DEVICE = _CARD_BASE_H + _CARD_LINE_H * 5  # disconnected baseline
_CARD_H_CHANNELS = _CARD_BASE_H + _CARD_LINE_H
_CARD_H_ACQ = (
    _CARD_BASE_H + _CARD_BTN_H * 6 + _CARD_LINE_H * 10
)  # Acquisition: toggle+controls+spectrum info box
_CARD_H_FILE = _CARD_BASE_H + _CARD_LINE_H + 105  # notes field only (Save/Load in header)
_CARD_H_MONITOR = _CARD_BASE_H + _CARD_BTN_H * 4 + _CARD_LINE_H * 4  # Record + Arm + Burst + Load Session + status


def _c(key: str, alpha: int = 255) -> tuple:
    """Shorthand: THEME_COLORS[key] → DPG RGBA tuple."""
    return vibechecker.hex_to_rgba(vibechecker.THEME_COLORS[key], alpha)


_CH_COLORS = [
    _c("WHITE"),  # Ch A
    _c("ORANGE"),  # Ch B
    _c("LIME"),  # Ch C
    _c("CORAL"),  # Ch D
    _c("CYAN"),  # Ch E
    _c("VIOLET"),  # Ch F
    _c("GOLD"),  # Ch G
    _c("SILVER"),  # Ch H
]

# Spectrum dialog display labels — index-aligned with preset lists
_MAXFREQ_LABELS = [f"{int(f)} Hz" for f in vibechecker.MAXFREQ_PRESETS]
_BINSIZE_LABELS = [f"{b} Hz/bin" for b in vibechecker.BINSIZE_PRESETS]

# Welch FFT window options (scipy.signal.welch 'window' argument strings)
_FFT_WINDOWS = ["hann", "blackmanharris", "flattop", "hamming", "boxcar", "bartlett"]

# Signal generator waveform names → PS4000A wave type string
_SIGGEN_WAVE_TYPES: dict[str, str] = {
    "Sine": "PS4000A_SINE",
    "Square": "PS4000A_SQUARE",
    "Triangle": "PS4000A_TRIANGLE",
    "Ramp Up": "PS4000A_RAMP_UP",
    "Ramp Down": "PS4000A_RAMP_DOWN",
    "DC": "PS4000A_DC_VOLTAGE",
}

# PS4000A voltage range labels — index matches PS4000A_RANGE enum (0=±10mV … 10=±20V)
_VOLTAGE_RANGE_LABELS = [
    "±10mV",
    "±20mV",
    "±50mV",
    "±100mV",
    "±200mV",
    "±500mV",
    "±1V",
    "±2V",
    "±5V",
    "±10V",
    "±20V",
]


class GUI:
    collector: vibechecker.DataCollector
    found_sensors: list

    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()
        self.registry = ScopeSensorRegistry()
        self._editing_scope_sensor_id: str | None = None
        self._num_channels: int = _DEFAULT_NUM_CHANNELS
        self._channel_themes: list = []
        self._peak_themes: list = []
        self._sect_theme = None
        self._toggle_themes: dict = {}  # 'active'|'waiting'|'idle' → dpg theme
        self._status_timer: threading.Timer | None = None
        self.found_sensors: list = []
        self._autoscale_pending: bool = False  # True → autoscale on next frame
        self._was_streaming_before_config: bool = False  # stream state when config opened
        self._monitor: vibechecker.MonitorController | None = None
        self._session_browser_sessions: list = []
        self._session_browser_rows: list = []
        self._session_browser_burst_list: list = []
        self._session_browser_selected_capture: int | None = None
        self._session_browser_selected_burst: str | None = None
        self._session_browser_selected_session_dir = None

    # ------------------------------------------------------------------
    # Status indicator helpers
    # ------------------------------------------------------------------

    def _set_device_status(self, state: str):
        """Update the device connection indicator: 'connected'|'file_loaded'|'disconnected'."""
        if dpg.does_item_exist(ui.DEVICE_STATUS_RECT):
            colors = {
                "connected": _c("GREEN"),
                "file_loaded": _c("YELLOW"),
                "disconnected": _c("RED"),
            }
            dpg.configure_item(ui.DEVICE_STATUS_RECT, fill=colors.get(state, _c("RED")))
        if dpg.does_item_exist(ui.CONN_STATUS_TEXT):
            labels = {
                "connected": "Connected",
                "file_loaded": "File Loaded",
                "disconnected": "Not Connected",
            }
            dpg.set_value(ui.CONN_STATUS_TEXT, labels.get(state, "Not Connected"))

    def _set_stream_status(self, state: str):
        """Update the toggle button color and label: 'active'|'waiting'|'idle'."""
        if dpg.does_item_exist(ui.ACQ_TOGGLE):
            label_map = {
                "active":  f'{icons.IC["stop"]}  Running',
                "waiting": f'{icons.IC["stop"]}  Waiting',
                "idle":    f'{icons.IC["play_arrow"]}  Stopped',
            }
            dpg.set_item_label(ui.ACQ_TOGGLE, label_map.get(state, f'{icons.IC["play_arrow"]}  Stopped'))
            theme = self._toggle_themes.get(state)
            if theme:
                dpg.bind_item_theme(ui.ACQ_TOGGLE, theme)

    def _schedule_status_timeout(self):
        """Re-arm watchdog: revert stream indicator to yellow if no data arrives."""
        if self._status_timer is not None:
            self._status_timer.cancel()
        timeout = 2.0 * self.collector.config.acquisition_period
        self._status_timer = threading.Timer(timeout, self._on_status_timeout)
        self._status_timer.daemon = True
        self._status_timer.start()

    def _on_status_timeout(self):
        if self.collector.is_streaming:
            self._set_stream_status("waiting")

    # ------------------------------------------------------------------
    # Plot axis helpers
    # ------------------------------------------------------------------

    def _get_time_axis_for(self, ch: int) -> str:
        tag = ui.plt_time_series(ch)
        if dpg.does_item_exist(tag):
            parent = dpg.get_item_parent(tag)
            if parent == dpg.get_alias_id(ui.PLT_SAMPLE_AX_ACCEL_2):
                return ui.PLT_SAMPLE_AX_ACCEL_2
        return ui.PLT_SAMPLE_AX_ACCEL

    def _get_freq_axis_for(self, ch: int) -> str:
        tag = ui.plt_freq_series(ch)
        if dpg.does_item_exist(tag):
            parent = dpg.get_item_parent(tag)
            if parent == dpg.get_alias_id(ui.PLT_FREQ_AX_2):
                return ui.PLT_FREQ_AX_2
        return ui.PLT_FREQ_AX_ACCEL

    def _get_unit_groups(self) -> list:
        """Group enabled channels by effective target unit."""
        groups: dict = {}
        for ch in sorted(self.collector.config.enabled_channels):
            unit = self.collector.get_active_eu(ch)
            groups.setdefault(unit, []).append(ch)
        return list(groups.items())

    def _freq_axis_label(self, unit: str, channels: list[int] | None = None) -> str:
        """Build a frequency-plot Y-axis label like 'Amplitude, mils P-P'."""
        mode = self._get_amplitude_mode(channels[0]) if channels else "0-P"
        return f"Amplitude, {unit} {mode}"

    def _update_axis_assignment(self):
        """Show/hide secondary axes and reassign series based on unit groups."""
        groups = self._get_unit_groups()

        if len(groups) > 2:
            log.warning(
                "More than 2 unique output units configured %s; only the first 2 will have dedicated axes.",
                [g[0] for g in groups],
            )
            # Absorb excess channels into group 1
            overflow = [ch for _, chs in groups[2:] for ch in chs]
            groups = [groups[0], (groups[1][0], groups[1][1] + overflow)]

        if len(groups) <= 1:
            # ── Single unit: hide all secondary axes ─────────────────────
            dpg.hide_item(ui.PLT_FREQ_AX_2)
            dpg.hide_item(ui.PLT_SAMPLE_AX_ACCEL_2)
            dpg.hide_item(ui.PLT_TREND_AX_OVERALL_2)
            for ch in self.collector.config.enabled_channels:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL, ui.PLT_SAMPLE_AX_ACCEL, ui.PLT_TREND_AX_OVERALL)
            unit = groups[0][0] if groups else "mV"
            chs = groups[0][1] if groups else []
            mode = self._get_amplitude_mode(chs[0]) if chs else "0-P"
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL, self._freq_axis_label(unit, chs))
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL, f"Amplitude, {unit}")
            dpg.set_item_label(ui.PLT_TREND_AX_OVERALL, f"Overall Vibration, {unit} {mode}")
            for ch in chs:
                tag = ui.ch_overall_value(ch)
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, label=f"Overall, {unit} {mode}")
        else:
            # ── Two units: show secondary axes and split channels ─────────
            dpg.show_item(ui.PLT_FREQ_AX_2)
            dpg.show_item(ui.PLT_SAMPLE_AX_ACCEL_2)
            dpg.show_item(ui.PLT_TREND_AX_OVERALL_2)
            for ch in groups[0][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL, ui.PLT_SAMPLE_AX_ACCEL, ui.PLT_TREND_AX_OVERALL)
            for ch in groups[1][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_2, ui.PLT_SAMPLE_AX_ACCEL_2, ui.PLT_TREND_AX_OVERALL_2)
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL, self._freq_axis_label(groups[0][0], groups[0][1]))
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL, f"Amplitude, {groups[0][0]}")
            dpg.set_item_label(ui.PLT_FREQ_AX_2, self._freq_axis_label(groups[1][0], groups[1][1]))
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL_2, f"Amplitude, {groups[1][0]}")
            mode0 = self._get_amplitude_mode(groups[0][1][0]) if groups[0][1] else "0-P"
            mode1 = self._get_amplitude_mode(groups[1][1][0]) if groups[1][1] else "0-P"
            dpg.set_item_label(ui.PLT_TREND_AX_OVERALL, f"Overall, {groups[0][0]} {mode0}")
            dpg.set_item_label(ui.PLT_TREND_AX_OVERALL_2, f"Overall, {groups[1][0]} {mode1}")
            for unit, chs in groups:
                mode = self._get_amplitude_mode(chs[0]) if chs else "0-P"
                for ch in chs:
                    tag = ui.ch_overall_value(ch)
                    if dpg.does_item_exist(tag):
                        dpg.configure_item(tag, label=f"Overall, {unit} {mode}")

    def _reassign_series_to_axis(
        self,
        ch: int,
        freq_axis: str,
        time_axis: str,
        trend_axis: str = ui.PLT_TREND_AX_OVERALL,
    ):
        """If a channel's series are on wrong axes, delete and recreate them."""
        wrong = False
        for tag, axis in [
            (ui.plt_freq_series(ch), freq_axis),
            (ui.plt_time_series(ch), time_axis),
            (ui.plt_trend_series(ch), trend_axis),
        ]:
            if dpg.does_item_exist(tag) and dpg.get_item_parent(tag) != dpg.get_alias_id(axis):
                wrong = True
                break
        if wrong:
            self._remove_channel_series(ch)
            self._add_channel_series(ch, freq_axis=freq_axis, time_axis=time_axis, trend_axis=trend_axis)

    # ------------------------------------------------------------------
    # Plot update helpers
    # ------------------------------------------------------------------

    def _update_fft_peaks_table(self, columns: list[str], rows: list[tuple], ch: int):
        table_tag = ui.ch_peaks_table(ch)
        if not dpg.does_item_exist(table_tag):
            return
        children = dpg.get_item_children(table_tag)
        if isinstance(children, dict):
            for sub in children.values():
                for tag in sub:
                    dpg.delete_item(tag)
        limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        for col in columns:
            dpg.add_table_column(label=col, parent=table_tag)
        for row in rows[:limit]:
            with dpg.table_row(parent=table_tag):
                for val in row:
                    dpg.add_text(f"{val}")

    def _get_amplitude_mode(self, ch: int) -> str:
        """Return amplitude mode: channel config → default '0-P'."""
        return self.collector.config.amplitude_mode_for(ch) or "0-P"

    def _update_time_plot(self, result: vibechecker.ChannelResult, ch: int):
        if not dpg.does_item_exist(ui.plt_time_series(ch)):
            return
        time = result.time_vec * 1000.0  # convert s → ms (axis label is "Time, ms")
        signal = result.time_data
        dpg.set_value(ui.plt_time_series(ch), [time.tolist(), signal.tolist()])

    def _update_freq_plot(self, result: vibechecker.ChannelResult, ch: int):
        if not dpg.does_item_exist(ui.plt_freq_series(ch)):
            return
        freq = result.freq
        spectrum = result.spectrum
        dpg.set_value(ui.plt_freq_series(ch), [freq.tolist(), spectrum.tolist()])
        if dpg.does_item_exist(ui.ch_overall_value(ch)):
            dpg.set_value(ui.ch_overall_value(ch), f"{result.overall:.4f}")
        peak_limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        peaks = result.peaks
        if len(peaks) > 0:
            top_peaks = peaks[:peak_limit]
            dpg.set_value(ui.plt_freq_peaks(ch), [freq[top_peaks].tolist(), spectrum[top_peaks].tolist()])
            amp_mode = self._get_amplitude_mode(ch)
            cols = ["Frequency (Hz)", f"Amp., {result.unit} {amp_mode}"]
            rows = list(
                zip(
                    np.round(freq[top_peaks], 2).tolist(),
                    np.round(spectrum[top_peaks], 6).tolist(),
                )
            )
            self._update_fft_peaks_table(cols, rows, ch)
        else:
            dpg.set_value(ui.plt_freq_peaks(ch), [[], []])

    def _update_trend_plot(self):
        """Refresh the trend plot; collector handles unit/sensitivity conversion."""
        trend_data = self.collector.get_trend_for_display()
        for ch in self.collector.config.enabled_channels:
            tag = ui.plt_trend_series(ch)
            if not dpg.does_item_exist(tag):
                continue
            times, values = trend_data.get(ch, ([], []))
            if times and values:
                dpg.set_value(tag, [times, values])
            else:
                dpg.set_value(tag, [[0.0], [0.0]])
        # NOTE: trend X range is NOT updated here; use the Autoscale button to
        # fit [0, max_t * 1.1].  Updating it every frame would lock out user pan/zoom.

    def _update_browse_label(self):
        """Refresh the frame-browser label, nav buttons, and trend cursor line."""
        if not dpg.does_item_exist(ui.ACQ_BROWSE_LABEL):
            return
        cache = self.collector.data["frame_cache"]
        n = len(cache)
        cursor = self.collector._cache_cursor
        label = f"Frame {n - cursor} / {n}" if n else "No frames"
        dpg.set_value(ui.ACQ_BROWSE_LABEL, label)
        can_browse = (not self.collector.is_streaming) and n > 1
        for tag in [ui.ACQ_BROWSE_FIRST, ui.ACQ_BROWSE_PREV, ui.ACQ_BROWSE_NEXT, ui.ACQ_BROWSE_LAST]:
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=can_browse)

        # Vertical cursor on trend plot showing current browse position
        self._update_trend_cursor()

    def _update_trend_cursor(self):
        """Show/hide a vertical line on the trend plot at the browsed frame's rel_time."""
        cache = self.collector.data["frame_cache"]
        cursor = self.collector._cache_cursor
        show = (not self.collector.is_streaming) and len(cache) > 0

        if show:
            idx = min(cursor, len(cache) - 1)
            frame = cache[-(idx + 1)]
            # Get rel_time from the first channel sample in the frame
            rel_time = None
            for k, v in frame.items():
                if isinstance(k, int):
                    rel_time = v.rel_time
                    break

            if rel_time is not None and dpg.does_item_exist(ui.PLT_TREND_AX_OVERALL):
                if not dpg.does_item_exist(ui.PLT_TREND_CURSOR):
                    dpg.add_inf_line_series(
                        [rel_time], tag=ui.PLT_TREND_CURSOR, parent=ui.PLT_TREND_AX_OVERALL, label="##cursor"
                    )
                    with dpg.theme() as cursor_theme:
                        with dpg.theme_component(dpg.mvAll):
                            dpg.add_theme_color(dpg.mvPlotCol_Line, _c("ON_SURFACE", 180))
                            dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.0)
                    dpg.bind_item_theme(ui.PLT_TREND_CURSOR, cursor_theme)
                else:
                    dpg.set_value(ui.PLT_TREND_CURSOR, [[rel_time]])
                dpg.configure_item(ui.PLT_TREND_CURSOR, show=True)
                return

        # Hide cursor when streaming or no data
        if dpg.does_item_exist(ui.PLT_TREND_CURSOR):
            dpg.configure_item(ui.PLT_TREND_CURSOR, show=False)

    def _update_results_section_visibility(self):
        """Show per-channel result sections only for enabled channels."""
        enabled = set(self.collector.config.enabled_channels)
        for ch in range(_MAX_CHANNELS):
            tag = ui.ch_result_section(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=(ch in enabled))

    def _display_frame(self):
        """Process the current frame via collector and update all GUI plots."""
        if self.collector.is_streaming:
            self._set_stream_status("active")
            self._schedule_status_timeout()

        results = self.collector.process_samples()

        n_overflow = 0
        for result in results:
            ch = result.channel
            tag = ui.ch_overflow_warning(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=result.overflow)
                if result.overflow:
                    n_overflow += 1
            self._update_time_plot(result, ch)
            self._update_freq_plot(result, ch)

        if dpg.does_item_exist(ui.CH_WARNINGS_SECTION):
            dpg.configure_item(
                ui.CH_WARNINGS_SECTION,
                show=bool(n_overflow),
                height=_CARD_BASE_H + n_overflow * _CARD_LINE_H,
            )

        if self._monitor is not None and self._monitor.is_recording:
            self._monitor.on_results(results, self.collector.data["frame_cache"])

        self._update_trend_plot()
        self._update_browse_label()
        self._ensure_legends()
        if self._autoscale_pending:
            self._autoscale_plots()
            self._autoscale_pending = False

    def _ensure_legends(self):
        """Re-create any plot legend that has been lost (DPG can drop them on
        dynamic series add/remove).  Called every _display_frame so recovery is
        immediate."""
        for plot_tag, legend_tag in [
            (ui.PLT_FREQ, ui.PLT_FREQ_LEGEND),
            (ui.PLT_TREND, ui.PLT_TREND_LEGEND),
            (ui.PLT_SAMPLE, ui.PLT_SAMPLE_LEGEND),
        ]:
            if dpg.does_item_exist(plot_tag) and not dpg.does_item_exist(legend_tag):
                dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=legend_tag, parent=plot_tag)

    def _poll_new_frames(self):
        """Check for new data from the collector and display the current frame.

        Called once per DPG render tick from the manual render loop.
        If multiple frames arrived since the last tick, only the most
        recent is displayed — earlier frames remain in frame_cache for browsing.
        """
        if not self.collector.new_frame_event.is_set():
            return
        self.collector.new_frame_event.clear()
        self._display_frame()
        if self._monitor is not None and self._monitor.is_recording:
            self._update_monitor_card()

    def _redraw(self, sender=None, data=None):
        if not self.collector.is_streaming:
            self.collector.reprocess_last_block()

    # ------------------------------------------------------------------
    # Channel series management
    # ------------------------------------------------------------------

    def _add_channel_series(
        self,
        ch: int,
        freq_axis: str = ui.PLT_FREQ_AX_ACCEL,
        time_axis: str = ui.PLT_SAMPLE_AX_ACCEL,
        trend_axis: str = ui.PLT_TREND_AX_OVERALL,
    ):
        ch_label = self.collector.config.name_for(ch)
        theme = self._channel_themes[ch % len(self._channel_themes)]
        for tag, axis in [
            (ui.plt_time_series(ch), time_axis),
            (ui.plt_freq_series(ch), freq_axis),
            (ui.plt_trend_series(ch), trend_axis),
        ]:
            if not dpg.does_item_exist(tag):
                dpg.add_line_series([0.0], [0.0], label=ch_label, tag=tag, parent=axis)
                dpg.bind_item_theme(tag, theme)
        peaks_tag = ui.plt_freq_peaks(ch)
        if not dpg.does_item_exist(peaks_tag):
            dpg.add_scatter_series([0.0], [0.0], label=f"##peaks_{ch}", tag=peaks_tag, parent=freq_axis)
            if self._peak_themes:
                dpg.bind_item_theme(peaks_tag, self._peak_themes[ch % len(self._peak_themes)])

    def _remove_channel_series(self, ch: int):
        for tag in [ui.plt_time_series(ch), ui.plt_freq_series(ch), ui.plt_trend_series(ch), ui.plt_freq_peaks(ch)]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

    # ------------------------------------------------------------------
    # Connection summary (left panel display)
    # ------------------------------------------------------------------

    @property
    def _has_loaded_data(self) -> bool:
        """True when frame_cache has data but no device is connected."""
        return self.collector.sensor is None and len(self.collector.data["frame_cache"]) > 0

    def _update_connection_summary(self):
        """Refresh device info and per-channel lines in the left panel."""
        sensor = self.collector.sensor
        has_data = self._has_loaded_data

        if sensor is not None:
            self._set_device_status("connected")
        elif has_data:
            self._set_device_status("file_loaded")
        else:
            self._set_device_status("disconnected")

        # Rebuild Device card info group
        if dpg.does_item_exist(ui.DEVICE_INFO_GROUP):
            dpg.delete_item(ui.DEVICE_INFO_GROUP, children_only=True)
            dim = _c("ON_SURFACE")
            if sensor is not None:
                for line in [
                    sensor.model_name,
                    f"  S/N: {sensor.serial_number}",
                    f"  ID:  {sensor.device_id}",
                    f"  Ch:  {sensor.num_channels}",
                ]:
                    dpg.add_text(line, parent=ui.DEVICE_INFO_GROUP, color=dim)
            elif has_data:
                n_frames = len(self.collector.data["frame_cache"])
                n_ch = len(self.collector.config.enabled_channels)
                dpg.add_text("File loaded", parent=ui.DEVICE_INFO_GROUP, color=dim)
                dpg.add_text(f"  {n_frames} frames, {n_ch} channels", parent=ui.DEVICE_INFO_GROUP, color=dim)
            # Resize Device card
            if sensor is not None:
                n_info = 4
            elif has_data:
                n_info = 2
            else:
                n_info = 0
            device_h = _CARD_BASE_H + n_info * _CARD_LINE_H + 2 + _CARD_BTN_H + 8
            dev_card = dpg.get_item_parent(ui.DEVICE_INFO_GROUP)
            if dev_card:
                dpg.configure_item(dev_card, height=device_h)

        show_channels = (sensor is not None) or has_data
        if dpg.does_item_exist(ui.CONN_CHANNEL_SUMMARY):
            dpg.delete_item(ui.CONN_CHANNEL_SUMMARY, children_only=True)
            if show_channels:
                for ch in sorted(self.collector.config.enabled_channels):
                    scope_s = self.collector.scope_sensors.get(ch)
                    sname = scope_s.name if scope_s else "(none)"
                    tunit = self.collector.get_active_eu(ch)
                    ch_color = _CH_COLORS[ch % len(_CH_COLORS)]
                    with dpg.group(horizontal=True, parent=ui.CONN_CHANNEL_SUMMARY):
                        with dpg.drawlist(width=12, height=12):
                            dpg.draw_rectangle(
                                pmin=(1, 1), pmax=(11, 11), fill=ch_color, color=(0, 0, 0, 0), rounding=2
                            )
                        dpg.add_text(
                            f" {self.collector.config.name_for(ch)} : {sname} : {tunit}",
                        )
                # Signal generator summary line (only when device connected)
                if sensor is not None:
                    sigcfg = self.collector.siggen_config
                    if sigcfg:
                        wave = next((k for k, v in _SIGGEN_WAVE_TYPES.items() if v == sigcfg.get("wave_type")), "Sine")
                        freq_hz = float(sigcfg.get("freq_hz", 0))
                        pktopk_mv = float(sigcfg.get("pktopk_uv", 0)) / 1000.0
                        freq_str = f"{freq_hz / 1000:.3g} kHz" if freq_hz >= 1000 else f"{freq_hz:.0f} Hz"
                        amp_str = f"{pktopk_mv / 1000:.3g} V" if pktopk_mv >= 1000 else f"{pktopk_mv:.0f} mV"
                        gen_text = f"Gen : {wave} : {freq_str} x {amp_str}"
                    else:
                        gen_text = "Gen : Off"
                    dpg.add_text(gen_text, parent=ui.CONN_CHANNEL_SUMMARY, color=_c("ON_SURFACE"))

        # Resize Channels card to match actual line count
        if dpg.does_item_exist(ui.CHANNELS_CARD):
            if show_channels:
                n_lines = len(self.collector.config.enabled_channels) + 1
                if sensor is not None:
                    n_lines += 1  # +gen line
            else:
                n_lines = 0
            h = _CARD_H_CHANNELS + n_lines * _CARD_LINE_H
            dpg.configure_item(ui.CHANNELS_CARD, height=h)

        self._update_acq_button_state()

    # ------------------------------------------------------------------
    # Spectrum info display
    # ------------------------------------------------------------------

    def _update_spectrum_info(self):
        """Refresh the read-only spectrum parameter block in the left panel."""
        cfg = self.collector.config
        fs_ks = cfg.samplerate / 1000
        t_col = cfg.acquisition_period
        hp = f"HP {cfg.highpass_fc:.0f} Hz" if cfg.highpass_enabled else "HP off"
        lp = f"LP {cfg.lowpass_fc:.0f} Hz" if cfg.lowpass_enabled else "LP off"
        info = (
            f"{cfg.maxfreq:.0f} Hz max  |  {cfg.binsize:.2f} Hz/bin\n"
            f"{cfg.n_fft_bins} lines  |  {fs_ks:.1f} kS/s\n"
            f"Acq: {t_col:.3f} s  |  {cfg.fft_window}\n"
            f"{hp}  |  {lp}"
        )
        if dpg.does_item_exist(ui.SPECTRUM_INFO_TEXT):
            dpg.set_value(ui.SPECTRUM_INFO_TEXT, info)

    def _update_acq_derived(self):
        """Refresh derived display fields in the acquisition dialog based on current widget values."""
        mf_str = dpg.get_value(ui.ACQ_DLG_MAXFREQ) if dpg.does_item_exist(ui.ACQ_DLG_MAXFREQ) else ""
        bs_str = dpg.get_value(ui.ACQ_DLG_BINSIZE) if dpg.does_item_exist(ui.ACQ_DLG_BINSIZE) else ""
        try:
            maxfreq = vibechecker.MAXFREQ_PRESETS[_MAXFREQ_LABELS.index(mf_str)]
        except (ValueError, IndexError):
            maxfreq = self.collector.config.maxfreq
        try:
            binsize = vibechecker.BINSIZE_PRESETS[_BINSIZE_LABELS.index(bs_str)]
        except (ValueError, IndexError):
            binsize = self.collector.config.binsize
        samplerate = vibechecker.nextpow2(int(2 * maxfreq))
        blocksize = vibechecker.nextpow2(int(samplerate / binsize))
        n_fft_bins = blocksize // 2 + 1
        acq_time = blocksize / samplerate
        mem_bytes = blocksize * 8

        cache_frames = (
            int(dpg.get_value(ui.ACQ_DLG_CACHE_FRAMES))
            if dpg.does_item_exist(ui.ACQ_DLG_CACHE_FRAMES)
            else self.collector.config.cache_frames
        )
        n_enabled = max(1, len(self.collector.config.enabled_channels))
        rec_window = acq_time * cache_frames
        total_mem = mem_bytes * n_enabled * cache_frames

        if total_mem >= 1024 * 1024:
            mem_str = f"{total_mem / (1024 * 1024):.1f} MB"
        elif total_mem >= 1024:
            mem_str = f"{total_mem / 1024:.1f} KB"
        else:
            mem_str = f"{total_mem} B"

        if dpg.does_item_exist(ui.ACQ_DLG_SAMPLERATE):
            dpg.set_value(ui.ACQ_DLG_SAMPLERATE, f"{samplerate / 1000:.1f} kS/s")
        if dpg.does_item_exist(ui.ACQ_DLG_NFFT_BINS):
            dpg.set_value(ui.ACQ_DLG_NFFT_BINS, str(n_fft_bins))
        if dpg.does_item_exist(ui.ACQ_DLG_ACQ_TIME):
            dpg.set_value(ui.ACQ_DLG_ACQ_TIME, f"{acq_time:.3f} s")
        if dpg.does_item_exist(ui.ACQ_DLG_REC_WINDOW):
            dpg.set_value(ui.ACQ_DLG_REC_WINDOW, f"{rec_window:.1f} s")
        if dpg.does_item_exist(ui.ACQ_DLG_MEMORY):
            dpg.set_value(ui.ACQ_DLG_MEMORY, mem_str)

    def _on_acq_preview(self, sender=None, data=None):
        """Update derived fields live as the user changes acquisition combo / int widgets."""
        self._update_acq_derived()

    # ------------------------------------------------------------------
    # Acquisition toggle
    # ------------------------------------------------------------------

    def _update_acq_button_state(self):
        """Enable/disable acquisition buttons based on device connection."""
        has_device = self.collector.stream is not None
        for tag in [ui.ACQ_TOGGLE, ui.ACQ_SINGLE]:
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=has_device)

    def _toggle_acquisition(self, sender=None, data=None):
        if self.collector.is_streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        if self.collector.stream is None:
            log.warning("Connect a device before starting acquisition")
            return
        self._set_stream_status("waiting")
        self._autoscale_pending = True
        self.collector.clear_trend()  # reset rel_time so trend starts at t=0
        self.collector.start_stream()
        self._update_browse_label()

    def _stop_stream(self):
        if self.collector.stream is None:
            return
        self.collector.stop_stream()
        self._update_browse_label()
        if self._status_timer is not None:
            self._status_timer.cancel()
            self._status_timer = None
        self._set_stream_status("idle")
        self._update_monitor_card()

    def _collect_sample(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning("Connect a device before collecting")
            return
        self._set_stream_status("waiting")
        self.collector.collect_sample()
        self._set_stream_status("idle")
        # Frame is now in cache and new_frame_event is set;
        # _poll_new_frames will display it on the next render tick.

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _on_browse(self, sender=None, data=None):
        """Navigate the frame cache based on which browse button was clicked."""
        cache = self.collector.data["frame_cache"]
        if not cache:
            return
        tag = dpg.get_item_alias(sender) if sender else None
        if tag == ui.ACQ_BROWSE_FIRST:
            self.collector._cache_cursor = len(cache) - 1
            self.collector.reprocess_last_block()
        elif tag == ui.ACQ_BROWSE_PREV:
            self.collector.browse_frame(+1)
        elif tag == ui.ACQ_BROWSE_NEXT:
            self.collector.browse_frame(-1)
        elif tag == ui.ACQ_BROWSE_LAST:
            self.collector._cache_cursor = 0
            self.collector.reprocess_last_block()

    # Default time-series window: ~10 cycles at 60 Hz ≈ 167 ms, rounded to 300 ms
    # so a typical 60 Hz fundamental fills the trace legibly on autoscale.
    _TIME_WINDOW_RANGE_MS: float = 300.0
    _TIME_WINDOW_OFFSET_MS: float = 200.0

    def _autoscale_plots(self, sender=None, data=None):
        """Scale all plot axes to sensible initial bounds.

        Axes that are explicitly set via set_axis_limits (time-series X and
        trend Y/X) are unlocked one frame later so the user can freely pan/zoom
        afterwards.  Axes scaled with fit_axis_data are inherently one-shot and
        don't need unlocking.
        """
        # Time Series X: fixed window for legibility (not fit-to-data)
        if self.collector.config.acquisition_period > 0.5 and dpg.does_item_exist(ui.PLT_SAMPLE_AX_TIME):
            dpg.set_axis_limits(
                ui.PLT_SAMPLE_AX_TIME,
                self._TIME_WINDOW_OFFSET_MS,
                self._TIME_WINDOW_OFFSET_MS + self._TIME_WINDOW_RANGE_MS,
            )
        else:
            # Acq period too small. Fit whole axis
            dpg.fit_axis_data(ui.PLT_SAMPLE_AX_TIME)

        # Amplitude / frequency axes: fit to current data (one-shot, no lock)
        for ax in [
            ui.PLT_SAMPLE_AX_ACCEL,
            ui.PLT_SAMPLE_AX_ACCEL_2,
            ui.PLT_FREQ_AX_FREQ,
            ui.PLT_FREQ_AX_ACCEL,
            ui.PLT_FREQ_AX_2,
        ]:
            if dpg.does_item_exist(ax):
                dpg.fit_axis_data(ax)

        # Trend X: fit to current data extent
        all_times: list[float] = []
        for ch in self.collector.config.enabled_channels:
            td = self.collector.trend.get(ch, {})
            rt = td.get("rel_times")
            if rt is not None and len(rt) > 0:
                all_times.extend(rt.tolist())
        if all_times and dpg.does_item_exist(ui.PLT_TREND_AX_TIME):
            dpg.set_axis_limits(ui.PLT_TREND_AX_TIME, 0.0, max(all_times) * 1.5)
        elif dpg.does_item_exist(ui.PLT_TREND_AX_TIME):
            dpg.fit_axis_data(ui.PLT_TREND_AX_TIME)

        # Trend Y: scale each axis independently by its own channels
        groups = self._get_unit_groups()
        trend_axes = [ui.PLT_TREND_AX_OVERALL, ui.PLT_TREND_AX_OVERALL_2]
        trend_display = self.collector.get_trend_for_display()
        for i, (_, chs) in enumerate(groups[:2]):
            ax = trend_axes[i]
            if not dpg.does_item_exist(ax):
                continue
            peak = 0.0
            for ch in chs:
                _, vals = trend_display.get(ch, ([], []))
                if vals:
                    peak = max(peak, max(vals))
            if peak > 0.0:
                dpg.set_axis_limits(ax, 0.0, peak * 1.1)
            else:
                dpg.fit_axis_data(ax)

        # Unlock all explicitly-set axes one frame later so user can pan/zoom freely.
        # dpg.set_axis_limits locks the axis until set_axis_limits_auto is called;
        # doing it on the next frame preserves the view while releasing the lock.
        dpg.set_frame_callback(
            dpg.get_frame_count() + 1,
            callback=self._unlock_autoscaled_axes,
        )

    def _unlock_autoscaled_axes(self):
        """Release axis locks set by _autoscale_plots (called one frame later)."""
        for ax in [ui.PLT_SAMPLE_AX_TIME, ui.PLT_TREND_AX_TIME, ui.PLT_TREND_AX_OVERALL, ui.PLT_TREND_AX_OVERALL_2]:
            if dpg.does_item_exist(ax):
                dpg.set_axis_limits_auto(ax)

    def _clear_cache(self, sender=None, data=None):
        """Wipe the frame cache and trend data, refresh the browse label."""
        self.collector.reset_data_store()
        self._update_browse_label()
        # Push flat (0,0) traces to every series so the plots visually clear
        for ch in range(_MAX_CHANNELS):
            for tag in [ui.plt_time_series(ch), ui.plt_freq_series(ch), ui.plt_trend_series(ch), ui.plt_freq_peaks(ch)]:
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, [[0.0], [0.0]])
        if dpg.does_item_exist(ui.PLT_TREND_AX_TIME):
            dpg.set_axis_limits(ui.PLT_TREND_AX_TIME, 0.0, 1.0)

    @staticmethod
    def _native_file_dialog(save: bool = False) -> str:
        """Open the platform-native file dialog; returns path string or ''."""
        from plyer import filechooser

        filters = [f"*{vibechecker.EXT}"]
        path = str(Path(vibechecker.SAVEDIR).resolve())
        if save:
            result = filechooser.save_file(title="Save Vibration Data", path=path, filters=filters)
        else:
            result = filechooser.open_file(title="Load Vibration Data", path=path, filters=filters)
        if result:
            return result[0]
        return ""

    def _on_save_click(self, sender=None, data=None):
        path_str = self._native_file_dialog(save=True)
        if not path_str:
            return
        p = Path(path_str)
        if not p.suffix:
            p = p.with_suffix(vibechecker.EXT)
        if dpg.does_item_exist(ui.ACQ_NOTES):
            self.collector.notes = dpg.get_value(ui.ACQ_NOTES)
        self.collector.save_data(p)

    def _on_load_click(self, sender=None, data=None):
        path_str = self._native_file_dialog(save=False)
        if not path_str:
            return
        self._on_load_file(Path(path_str))

    def _on_load_file(self, path: Path):
        """Load an h5 file and sync all GUI state to the loaded data."""
        if self.collector.is_streaming:
            self._stop_stream()

        # Disconnect any attached hardware so file channels are unambiguously active
        if self.collector.sensor is not None:
            self.collector.disconnect_sensor()
            self._set_device_status("disconnected")

        self.collector.load_data(path)

        cache = self.collector.data["frame_cache"]
        if not cache:
            return

        # Determine channels present in the loaded data
        loaded_channels: set[int] = set()
        for frame in cache:
            loaded_channels.update(k for k in frame if isinstance(k, int))

        # Update _num_channels from file data (mirrors what device connect does from hardware)
        if loaded_channels:
            self._num_channels = max(loaded_channels) + 1

        # Remove stale series and trend cursor, then create series for loaded channels
        for ch in range(_MAX_CHANNELS):
            self._remove_channel_series(ch)
        if dpg.does_item_exist(ui.PLT_TREND_CURSOR):
            dpg.delete_item(ui.PLT_TREND_CURSOR)
        for ch in sorted(loaded_channels):
            self._add_channel_series(ch)

        # Auto-add any sensors from the file that aren't in the local registry,
        # then assign them to channels so scope_sensors is populated for the config dialog.
        for sid, sensor_dict in self.collector._loaded_scope_sensors.items():
            if self.registry.find_by_id(sid) is None:
                try:
                    sensor = ScopeSensor.from_dict(sensor_dict)
                    self.registry.add(sensor)
                    log.info(f"Added sensor from file to registry: {sensor.name!r} ({sid})")
                except Exception as exc:
                    log.warning(f"Could not restore sensor {sid!r} from file: {exc}")

        # Wire scope sensors to channels from the loaded channel configs
        for ch, sensor_cfg in self.collector._loaded_channel_sensor_configs.items():
            sid = sensor_cfg.get("id")
            sensor = self.registry.find_by_id(sid) if sid else None
            self.collector.set_scope_sensor(ch, sensor)

        self._update_axis_assignment()
        self._update_results_section_visibility()
        self._update_connection_summary()
        self._update_spectrum_info()
        if dpg.does_item_exist(ui.ACQ_NOTES):
            dpg.set_value(ui.ACQ_NOTES, self.collector.notes)
        self._autoscale_pending = True
        self.collector.reprocess_last_block()

    # ------------------------------------------------------------------
    # Device Setup Dialog
    # ------------------------------------------------------------------

    def _open_config_dialog(self, tab_tag: str):
        """Show the unified config dialog focused on the requested tab.

        Acquisition is stopped here so widget callbacks (channel enable, coupling,
        range) don't each trigger individual reconnects while the dialog is open.
        _on_config_close restarts streaming if it was active when we opened.
        """
        self._was_streaming_before_config = self.collector.is_streaming
        if self._was_streaming_before_config:
            self._stop_stream()

        dpg.show_item(ui.DLG_CONFIG)
        dpg.set_value(ui.CONFIG_TAB_BAR, tab_tag)
        # Always sync spectrum widgets so they reflect current config
        # regardless of which tab was used to open the dialog.
        self._populate_acq_tab()
        if tab_tag == ui.CONFIG_TAB_DEVICE:
            self._start_device_discovery()
        elif tab_tag == ui.CONFIG_TAB_CHANNELS:
            self._rebuild_device_channel_rows()
        elif tab_tag == ui.CONFIG_TAB_SENSORS:
            self._init_sensor_registry_tab()
        elif tab_tag == ui.CONFIG_TAB_SIGGEN:
            self._populate_siggen_tab()
        elif tab_tag == ui.CONFIG_TAB_MONITOR:
            self._populate_monitor_tab()

    def _start_device_discovery(self, sender=None, data=None):
        """Clear device list, show placeholder, then discover in a background thread."""
        if dpg.does_item_exist(ui.DEVSETUP_DEVICE_LIST_GROUP):
            dpg.delete_item(ui.DEVSETUP_DEVICE_LIST_GROUP, children_only=True)
            dpg.add_text("... Populating sensor list ...", parent=ui.DEVSETUP_DEVICE_LIST_GROUP)
        threading.Thread(target=self._discover_devices, daemon=True).start()

    def _discover_devices(self):
        """Background: find sensors, then update the device list.

        Does NOT auto-disconnect the current sensor — doing so from a background
        thread races with main-thread GUI operations and can corrupt widget state.
        If a device is already connected the scan is skipped (PicoScope cannot be
        opened twice); the existing sensor is kept as the sole list entry.

        _rebuild_device_channel_rows is intentionally NOT called here: it is
        already invoked on the main thread by _on_device_connect_toggle, and
        calling it from a background thread concurrently with main-thread
        widget reads (_apply_channel_assignments_from_widgets) causes DPG
        state corruption (combo returns stale/default values).
        """
        if self.collector.sensor is not None:
            # Device already connected — cannot re-scan while handle may be open.
            self.found_sensors = [self.collector.sensor]
        else:
            self.found_sensors = vibechecker.VibeSensor.find()
        self._repopulate_device_list()

    def _autoconnect(self):
        """Background startup thread: scan for PicoScopes and connect to the first found.

        Runs once after the viewport is shown. Mirrors the manual connect path in
        _on_device_connect_toggle so the user lands in a ready state without opening
        the Device Setup dialog. Does not start the stream — the user controls that.

        Safe to run concurrently with the render loop: the slow operations
        (VibeSensor.find, connect_sensor, config load) are thread-safe; DPG updates
        follow the same background-thread pattern as _discover_devices.
        """
        if vibechecker.PICOSCOPE_DRIVER_MISSING:
            log.debug("Autoconnect: PicoScope driver not available")
            return

        sensors = vibechecker.VibeSensor.find()
        self.found_sensors = sensors

        if not sensors:
            log.info("Autoconnect: no PicoScope found")
            self._update_connection_summary()
            return

        sensor = sensors[0]
        log.info(f"Autoconnect: found {sensor.model_name} (S/N {sensor.serial_number})")

        try:
            self.collector.connect_sensor(sensor)
            self._num_channels = sensor.num_channels
            for ch in range(_MAX_CHANNELS):
                self._remove_channel_series(ch)
            self.collector.reset_channel_config(sensor.num_channels)
            device_cfg = _cfg.load_device_config(sensor.serial_number)
            self._restore_channel_assignments(device_cfg)
            self.collector.reconnect_stream()
            self._set_device_status("connected")
            log.info(f"Autoconnect: connected to {sensor.model_name}")
        except Exception as e:
            log.warning(f"Autoconnect failed: {e}")
            self.collector.disconnect_sensor()
            self._set_device_status("disconnected")
            return

        self._repopulate_device_list()
        self._rebuild_device_channel_rows()
        self._update_connection_summary()
        self._update_axis_assignment()
        self._update_results_section_visibility()
        self._update_spectrum_info()

    def _repopulate_device_list(self):
        """Rebuild the detected-device rows inside the Device Setup dialog."""
        if not dpg.does_item_exist(ui.DEVSETUP_DEVICE_LIST_GROUP):
            return
        dpg.delete_item(ui.DEVSETUP_DEVICE_LIST_GROUP, children_only=True)
        if not self.found_sensors:
            if vibechecker.PICOSCOPE_DRIVER_MISSING:
                dpg.add_text(
                    "PicoScope driver not found.\nInstall PicoSDK to connect a device.",
                    parent=ui.DEVSETUP_DEVICE_LIST_GROUP,
                    color=_c("YELLOW"),
                )
            else:
                dpg.add_text("No devices found.", parent=ui.DEVSETUP_DEVICE_LIST_GROUP)
            return
        for sensor in self.found_sensors:
            is_connected = self.collector.sensor is not None and self.collector.sensor.device_id == sensor.device_id
            btn_label = "Disconnect" if is_connected else "Connect"
            conn_color = _c("GREEN_LIGHT") if is_connected else _c("ON_SURFACE")
            with dpg.group(parent=ui.DEVSETUP_DEVICE_LIST_GROUP):
                with dpg.group(horizontal=True):
                    dpg.add_button(label=btn_label, user_data=sensor, callback=self._on_device_connect_toggle, width=90)
                    dpg.add_text(sensor.model_name, color=conn_color)
                dpg.add_text(f"  Serial:    {sensor.serial_number}", color=_c("ON_SURFACE"), indent=10)
                dpg.add_text(f"  Device ID: {sensor.device_id}", color=_c("ON_SURFACE"), indent=10)
                dpg.add_text(f"  Channels:  {sensor.num_channels}", color=_c("ON_SURFACE"), indent=10)
                dpg.add_spacer(height=4)

    def _rebuild_device_channel_rows(self):
        """Rebuild per-channel rows inside the Device Setup dialog."""
        if not dpg.does_item_exist(ui.DEVSETUP_CHANNEL_GROUP):
            return
        for ch in range(_MAX_CHANNELS):
            for tag in [
                ui.scope_ch_header(ch),
                ui.scope_ch_enabled(ch),
                ui.scope_ch_sensor(ch),
                ui.scope_ch_range(ch),
                ui.scope_ch_coupling(ch),
                ui.scope_ch_name(ch),
                ui.scope_ch_target_unit(ch),
                ui.scope_ch_amplitude_mode(ch),
                ui.scope_ch_name_text(ch),
            ]:
                if dpg.does_alias_exist(tag):
                    dpg.remove_alias(tag)
            for theme_tag in [ui.scope_ch_hdr_theme(ch, True), ui.scope_ch_hdr_theme(ch, False)]:
                if dpg.does_item_exist(theme_tag):
                    dpg.delete_item(theme_tag)
        dpg.delete_item(ui.DEVSETUP_CHANNEL_GROUP, children_only=True)
        if self.collector.sensor is None and not self.collector.data["frame_cache"]:
            dpg.add_text("No device connected.", parent=ui.DEVSETUP_CHANNEL_GROUP)
            return
        sensor_items = ["(none)"] + self.registry.names()
        tu_items = ["(use sensor)"] + sorted(UNIT_TO_SI.keys())
        enabled_set = set(self.collector.config.enabled_channels)
        # In file mode, show all channels present in the cache (regardless of enabled state).
        # In hardware mode, show all channels the device exposes.
        if self.collector.sensor is not None:
            channel_list = list(range(self._num_channels))
        else:
            file_channels: set[int] = set()
            for frame in self.collector.data.get("frame_cache", []):
                file_channels.update(k for k in frame if isinstance(k, int))
            channel_list = sorted(file_channels)
        for ch in channel_list:
            is_enabled = ch in enabled_set
            scope_s = self.collector.scope_sensors.get(ch)
            default_s = scope_s.name if scope_s else "(none)"
            range_idx = self.collector.config.voltage_range_for(ch)
            default_r = (
                _VOLTAGE_RANGE_LABELS[range_idx] if range_idx < len(_VOLTAGE_RANGE_LABELS) else _VOLTAGE_RANGE_LABELS[7]
            )
            default_c = self.collector.config.coupling_for(ch)
            ch_tu = self.collector.config.target_unit_for(ch) or "(use sensor)"
            ch_amp = self.collector.config.amplitude_mode_for(ch) or "0-P"
            ch_name = self.collector.config.name_for(ch)
            summary = f"{default_c}  {default_r}  {default_s} -> {ch_tu} {ch_amp}"
            ch_color = _CH_COLORS[ch % len(_CH_COLORS)]
            grey_color = _c("ON_SURFACE")
            # Per-channel header themes: enabled = channel color, disabled = grey
            with dpg.theme(tag=ui.scope_ch_hdr_theme(ch, True)):
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, ch_color, category=dpg.mvThemeCat_Core)
            with dpg.theme(tag=ui.scope_ch_hdr_theme(ch, False)):
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, grey_color, category=dpg.mvThemeCat_Core)
            # Line 1: color swatch + channel name
            with dpg.group(horizontal=True, parent=ui.DEVSETUP_CHANNEL_GROUP):
                dpg.add_checkbox(
                    label="Enable",
                    tag=ui.scope_ch_enabled(ch),
                    default_value=is_enabled,
                    callback=lambda s, d, c=ch: self._on_channel_enable_change(c),
                )
                with dpg.drawlist(width=16, height=16):
                    dpg.draw_rectangle(pmin=(2, 2), pmax=(14, 14), fill=ch_color, color=(0, 0, 0, 0), rounding=2)
                dpg.add_text(ch_name, tag=ui.scope_ch_name_text(ch))
            # Line 2: collapsing header with settings summary
            with dpg.collapsing_header(
                label=summary, tag=ui.scope_ch_header(ch), parent=ui.DEVSETUP_CHANNEL_GROUP
            ) as _hdr:
                # dpg.bind_item_theme(_hdr, ui.scope_ch_hdr_theme(ch, is_enabled))
                dpg.add_input_text(
                    label="Name",
                    tag=ui.scope_ch_name(ch),
                    default_value=ch_name,
                    indent=_CH_INDENT,
                    width=_DLG_FIELD_W,
                    callback=lambda s, d, c=ch: self._refresh_channel_header(c),
                )
                with dpg.group(horizontal=True, indent=_CH_INDENT):
                    dpg.add_combo(
                        label="Coupling",
                        tag=ui.scope_ch_coupling(ch),
                        items=["AC", "DC"],
                        default_value=default_c,
                        width=_CH_COUPLING_W,
                        callback=lambda s, d, c=ch: self._on_coupling_combo_change(c, d),
                    )
                    dpg.add_combo(
                        label="Range",
                        tag=ui.scope_ch_range(ch),
                        items=_VOLTAGE_RANGE_LABELS,
                        default_value=default_r,
                        width=_CH_RANGE_W,
                        callback=lambda s, d, c=ch: self._on_range_combo_change(c, d),
                    )
                dpg.add_combo(
                    label="Sensor",
                    tag=ui.scope_ch_sensor(ch),
                    items=sensor_items,
                    default_value=default_s,
                    indent=_CH_INDENT,
                    width=_DLG_FIELD_W,
                    callback=lambda s, d, c=ch: self._on_sensor_combo_change(c, d),
                )
                with dpg.group(horizontal=True, indent=_CH_INDENT):
                    dpg.add_combo(
                        label="Unit",
                        tag=ui.scope_ch_target_unit(ch),
                        items=tu_items,
                        default_value=ch_tu,
                        width=_CH_HALF_FIELD_W,
                    )
                    dpg.add_combo(
                        label="Amplitude",
                        tag=ui.scope_ch_amplitude_mode(ch),
                        items=list(vibechecker.AMPLITUDE_MODES),
                        default_value=ch_amp,
                        width=_CH_HALF_FIELD_W,
                    )

    def _on_device_connect_toggle(self, sender, data, user_data):
        """Connect or disconnect a device row in the Device Setup dialog."""
        sensor = user_data
        if self.collector.sensor is not None and self.collector.sensor.device_id == sensor.device_id:
            self.collector.disconnect_sensor()
            self._set_device_status("disconnected")
            self._set_stream_status("idle")
        else:
            if self.collector.sensor is not None:
                self.collector.disconnect_sensor()
            try:
                self.collector.connect_sensor(sensor)
                self._num_channels = sensor.num_channels
                # Purge all stale series before config reset so no ghost traces remain
                for _ch in range(_MAX_CHANNELS):
                    self._remove_channel_series(_ch)
                self.collector.reset_channel_config(sensor.num_channels)
                device_cfg = _cfg.load_device_config(sensor.serial_number)
                self._restore_channel_assignments(device_cfg)
                self.collector.reconnect_stream()
                self._set_device_status("connected")
            except Exception as e:
                log.warning(f"Device connect failed: {e}")
                self.collector.disconnect_sensor()
        self._repopulate_device_list()
        self._rebuild_device_channel_rows()

    def _apply_channel_assignments_from_widgets(self):
        """Read Device-tab widget values and push them into the collector."""
        for ch in range(self._num_channels):
            enabled_tag = ui.scope_ch_enabled(ch)
            sensor_tag = ui.scope_ch_sensor(ch)
            if dpg.does_item_exist(enabled_tag):
                enabled = dpg.get_value(enabled_tag)
                if enabled and ch not in self.collector.config.enabled_channels:
                    self.collector.config.enabled_channels.append(ch)
                elif not enabled and ch in self.collector.config.enabled_channels:
                    self.collector.config.enabled_channels.remove(ch)
            if dpg.does_item_exist(sensor_tag):
                sensor_name = dpg.get_value(sensor_tag)
                sensor = (
                    None if (not sensor_name or sensor_name == "(none)") else self.registry.find_by_name(sensor_name)
                )
                self.collector.set_scope_sensor(ch, sensor)
            range_tag = ui.scope_ch_range(ch)
            if dpg.does_item_exist(range_tag):
                label = dpg.get_value(range_tag)
                if label in _VOLTAGE_RANGE_LABELS:
                    self.collector.config.channel_voltage_ranges[ch] = _VOLTAGE_RANGE_LABELS.index(label)
            coupling_tag = ui.scope_ch_coupling(ch)
            if dpg.does_item_exist(coupling_tag):
                val = dpg.get_value(coupling_tag)
                if val in ("AC", "DC"):
                    self.collector.config.channel_couplings[ch] = val
            name_tag = ui.scope_ch_name(ch)
            if dpg.does_item_exist(name_tag):
                name = dpg.get_value(name_tag).strip()
                if name:
                    self.collector.config.channel_names[ch] = name
                else:
                    self.collector.config.channel_names.pop(ch, None)
            tu_tag = ui.scope_ch_target_unit(ch)
            if dpg.does_item_exist(tu_tag):
                tu = dpg.get_value(tu_tag)
                if tu and tu != "(use sensor)":
                    self.collector.config.channel_target_units[ch] = tu
                else:
                    self.collector.config.channel_target_units.pop(ch, None)
            amp_tag = ui.scope_ch_amplitude_mode(ch)
            if dpg.does_item_exist(amp_tag):
                amp = dpg.get_value(amp_tag)
                if amp in vibechecker.AMPLITUDE_MODES:
                    self.collector.config.channel_amplitude_modes[ch] = amp
                else:
                    self.collector.config.channel_amplitude_modes.pop(ch, None)
        self.collector.config.enabled_channels.sort()
        # Sync plot series visibility with final widget state (hide/show, preserve data)
        for ch in range(self._num_channels):
            enabled_tag = ui.scope_ch_enabled(ch)
            if dpg.does_item_exist(enabled_tag):
                series_tags = [
                    ui.plt_time_series(ch),
                    ui.plt_freq_series(ch),
                    ui.plt_trend_series(ch),
                    ui.plt_freq_peaks(ch),
                ]
                if dpg.get_value(enabled_tag):
                    if any(dpg.does_item_exist(t) for t in series_tags):
                        for t in series_tags:
                            if dpg.does_item_exist(t):
                                dpg.show_item(t)
                    else:
                        self._add_channel_series(ch)
                else:
                    for t in series_tags:
                        if dpg.does_item_exist(t):
                            dpg.hide_item(t)

    # ------------------------------------------------------------------
    # Session Browser
    # ------------------------------------------------------------------

    def _open_session_browser(self, sender=None, data=None) -> None:
        """Open (or refresh) the Monitor Session browser modal."""
        if dpg.does_item_exist(ui.DLG_SESSION_BROWSER):
            self._refresh_session_browser()
            dpg.configure_item(ui.DLG_SESSION_BROWSER, show=True)
            return
        self._build_session_browser()

    def _build_session_browser(self) -> None:
        """Build the session browser modal — session list + burst list, select to load."""
        DLG_W, DLG_H = 760, 520
        COL_W = 340          # each of the two list columns
        ROW_H = DLG_H - 130  # height of the two list panes

        with dpg.window(
            label="Load Monitor Session",
            modal=True,
            show=True,
            tag=ui.DLG_SESSION_BROWSER,
            width=DLG_W,
            height=DLG_H,
            no_resize=False,
        ):
            # ── Source folder row ─────────────────────────────────────
            dpg.add_text("Session folder")
            with dpg.group(horizontal=True):
                dpg.add_input_text(
                    tag='_SB_FOLDER',
                    default_value=str(vibechecker.data_dir() / 'monitor'),
                    width=-90,
                    hint="Path to monitor sessions folder",
                )
                dpg.add_button(
                    label=icons.IC['folder_open'],
                    width=80,
                    callback=self._on_session_browser_pick_folder,
                )
            dpg.add_spacer(height=6)

            # ── Two-column list area ──────────────────────────────────
            with dpg.group(horizontal=True):
                # ── Sessions column ───────────────────────────────────
                with dpg.child_window(width=COL_W, height=ROW_H, border=True):
                    dpg.add_text("Sessions", color=_c("ON_SURFACE"))
                    dpg.add_separator()
                    dpg.add_listbox(
                        items=[],
                        tag='_SB_SESSION_LIST',
                        width=-1,
                        num_items=20,
                        callback=self._on_session_list_select,
                    )

                dpg.add_spacer(width=6)

                # ── Bursts column ─────────────────────────────────────
                with dpg.child_window(width=-1, height=ROW_H, border=True):
                    dpg.add_text("Bursts (select to load)", color=_c("ON_SURFACE"))
                    dpg.add_separator()
                    dpg.add_listbox(
                        items=[],
                        tag='_SB_BURST_LIST',
                        width=-1,
                        num_items=20,
                        callback=self._on_burst_list_select,
                    )

            # ── Bottom bar ────────────────────────────────────────────
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=f'{icons.IC["refresh"]}  Refresh',
                    callback=self._refresh_session_browser,
                    width=100,
                    height=28,
                )
                dpg.add_spacer(width=-1)
                dpg.add_button(
                    label=f'{icons.IC["close"]}  Close',
                    callback=lambda: dpg.configure_item(ui.DLG_SESSION_BROWSER, show=False),
                    width=90,
                    height=28,
                )

        self._refresh_session_browser()

    def _scan_session_dirs(self) -> list:
        """Return [(session_id, session_dir, session_h5)] sorted newest-first.

        Reads the folder from the _SB_FOLDER widget if it exists, else default.
        """
        import h5py
        if dpg.does_item_exist('_SB_FOLDER'):
            folder_str = dpg.get_value('_SB_FOLDER').strip()
            monitor_root = Path(folder_str) if folder_str else vibechecker.data_dir() / 'monitor'
        else:
            monitor_root = vibechecker.data_dir() / 'monitor'

        sessions = []
        if not monitor_root.exists():
            return sessions
        try:
            dirs = sorted(
                [d for d in monitor_root.iterdir() if d.is_dir()],
                key=lambda d: d.name,
                reverse=True,
            )
        except OSError as exc:
            log.error(f'session browser: cannot list {monitor_root}: {exc}')
            return sessions

        for d in dirs:
            h5 = d / 'session.h5'
            if not h5.exists():
                continue
            sessions.append((d.name, d, h5))

        self._session_browser_sessions = sessions
        return sessions

    def _on_session_list_select(self, sender=None, data=None) -> None:
        """Load all interval frames from the selected session; populate burst list."""
        import h5py, json
        if not self._session_browser_sessions:
            return
        selected = dpg.get_value('_SB_SESSION_LIST') if dpg.does_item_exist('_SB_SESSION_LIST') else data
        entry = next((s for s in self._session_browser_sessions if s[0] == selected), None)
        if entry is None:
            return
        _, session_dir, session_h5 = entry
        self._session_browser_selected_session_dir = session_dir

        # Load all interval frames immediately
        try:
            self.collector.load_monitor_session(session_h5)
        except Exception as exc:
            log.error(f'session browser: failed to load session {session_h5}: {exc}')

        # Populate burst listbox
        burst_list: list = []
        try:
            with h5py.File(str(session_h5), 'r') as f:
                if 'burst' in f:
                    raw = f['burst'].attrs.get('burst_list', '[]')
                    burst_list = json.loads(raw)
        except Exception as exc:
            log.error(f'session browser: cannot read bursts from {session_h5}: {exc}')

        self._session_browser_burst_list = burst_list
        burst_labels = [
            f'{b.get("timestamp", "")[:19]}  {b.get("trigger_type","")}'
            for b in burst_list
        ]
        if dpg.does_item_exist('_SB_BURST_LIST'):
            dpg.configure_item('_SB_BURST_LIST', items=burst_labels)

    def _on_burst_list_select(self, sender=None, data=None) -> None:
        """Load all frames from the selected burst event."""
        if not self._session_browser_burst_list:
            return
        selected_label = dpg.get_value('_SB_BURST_LIST') if dpg.does_item_exist('_SB_BURST_LIST') else data
        # Find burst by matching the label we built
        burst = next(
            (b for b in self._session_browser_burst_list
             if f'{b.get("timestamp","")[:19]}  {b.get("trigger_type","")}' == selected_label),
            None,
        )
        if burst is None:
            return
        burst_id = burst.get('burst_id', '')
        session_dir = self._session_browser_selected_session_dir
        if not burst_id or session_dir is None:
            return
        session_h5 = Path(str(session_dir)) / 'session.h5'
        try:
            self.collector.load_monitor_burst(session_h5, burst_id)
        except Exception as exc:
            log.error(f'session browser: failed to load burst {burst_id}: {exc}')

    def _on_session_browser_pick_folder(self, sender=None, data=None) -> None:
        """Open a folder picker and update the session folder text input."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            folder = filedialog.askdirectory(
                title="Select monitor sessions folder",
                initialdir=str(vibechecker.data_dir() / 'monitor'),
            )
            root.destroy()
            if folder and dpg.does_item_exist('_SB_FOLDER'):
                dpg.set_value('_SB_FOLDER', folder)
                self._refresh_session_browser()
        except Exception as exc:
            log.error(f'session browser: folder picker failed: {exc}')

    def _refresh_session_browser(self) -> None:
        sessions = self._scan_session_dirs()
        labels = [s[0] for s in sessions]
        if dpg.does_item_exist('_SB_SESSION_LIST'):
            dpg.configure_item('_SB_SESSION_LIST', items=labels)
        if dpg.does_item_exist('_SB_BURST_LIST'):
            dpg.configure_item('_SB_BURST_LIST', items=[])
        if sessions:
            self._on_session_list_select(sender='_SB_SESSION_LIST', data=sessions[0][0])

    # ------------------------------------------------------------------

    def _on_config_close(self, sender=None, data=None):
        """Apply all tab settings, do a single reconnect, then hide the dialog.

        Acquisition was already stopped in _open_config_dialog; _was_streaming_before_config
        records whether to restart it here.  All widget-level callbacks (channel enable,
        coupling, range) are gated from calling reconnect_stream while the dialog is
        open, so this is the one and only reconnect point.
        """
        # Apply all settings from every tab into collector.config
        self._apply_acq_settings_from_widgets()

        if dpg.does_item_exist(ui.SIGGEN_ENABLED):
            if dpg.get_value(ui.SIGGEN_ENABLED):
                wave_name = dpg.get_value(ui.SIGGEN_WAVE_TYPE)
                self.collector.siggen_config = {
                    "wave_type": _SIGGEN_WAVE_TYPES.get(wave_name, "PS4000A_SINE"),
                    "freq_hz": float(dpg.get_value(ui.SIGGEN_FREQ_HZ) or 1000.0),
                    "pktopk_uv": int(float(dpg.get_value(ui.SIGGEN_PKTOPK_MV) or 0.0) * 1000),
                    "offset_uv": int(float(dpg.get_value(ui.SIGGEN_OFFSET_MV) or 0.0) * 1000),
                }
            else:
                self.collector.siggen_config = None

        self._apply_channel_assignments_from_widgets()
        self._refresh_channel_names()
        self._save_channel_assignments()
        self._save_registry_sensor_fields()
        self._refresh_assigned_sensors()
        self._update_connection_summary()
        self._update_spectrum_info()
        self._update_axis_assignment()
        self._update_results_section_visibility()
        self.collector.init_trend_channels()

        # Single reconnect to apply all hardware changes at once
        if self.collector.sensor is not None:
            self.collector.reconnect_stream()

        if self._was_streaming_before_config:
            self._start_stream()
        else:
            self.collector.reprocess_last_block()

        self._was_streaming_before_config = False
        dpg.hide_item(ui.DLG_CONFIG)

    # ------------------------------------------------------------------
    # Acquisition Setup Tab
    # ------------------------------------------------------------------

    def _populate_acq_tab(self):
        """Sync acquisition tab widgets with current config values."""
        cfg = self.collector.config
        curr_mf = f"{int(cfg.maxfreq)} Hz"
        curr_bs = f"{cfg.binsize} Hz/bin"
        if dpg.does_item_exist(ui.ACQ_DLG_MAXFREQ):
            if curr_mf in _MAXFREQ_LABELS:
                dpg.set_value(ui.ACQ_DLG_MAXFREQ, curr_mf)
        if dpg.does_item_exist(ui.ACQ_DLG_BINSIZE):
            if curr_bs in _BINSIZE_LABELS:
                dpg.set_value(ui.ACQ_DLG_BINSIZE, curr_bs)
        if dpg.does_item_exist(ui.ACQ_DLG_WINDOW):
            dpg.set_value(ui.ACQ_DLG_WINDOW, cfg.fft_window)
        if dpg.does_item_exist(ui.ACQ_DLG_OVERLAP):
            dpg.set_value(ui.ACQ_DLG_OVERLAP, cfg.welch_overlap * 100.0)
        if dpg.does_item_exist(ui.ACQ_DLG_HP_ENABLED):
            dpg.set_value(ui.ACQ_DLG_HP_ENABLED, cfg.highpass_enabled)
        if dpg.does_item_exist(ui.ACQ_DLG_HP_FC):
            dpg.set_value(ui.ACQ_DLG_HP_FC, cfg.highpass_fc)
        if dpg.does_item_exist(ui.ACQ_DLG_LP_ENABLED):
            dpg.set_value(ui.ACQ_DLG_LP_ENABLED, cfg.lowpass_enabled)
        if dpg.does_item_exist(ui.ACQ_DLG_LP_FC):
            dpg.set_value(ui.ACQ_DLG_LP_FC, cfg.lowpass_fc)
        if dpg.does_item_exist(ui.ACQ_DLG_CACHE_FRAMES):
            dpg.set_value(ui.ACQ_DLG_CACHE_FRAMES, cfg.cache_frames)
        self._update_acq_derived()

    def _apply_acq_settings_from_widgets(self):
        """Read acquisition tab widgets and write values into collector.config.

        Pure settings application — no stream stop/start side effects.
        Stream lifecycle is the caller's responsibility.
        """
        cfg = self.collector.config
        mf_str = dpg.get_value(ui.ACQ_DLG_MAXFREQ)
        bs_str = dpg.get_value(ui.ACQ_DLG_BINSIZE)
        try:
            cfg.maxfreq = vibechecker.MAXFREQ_PRESETS[_MAXFREQ_LABELS.index(mf_str)]
        except (ValueError, IndexError):
            pass
        try:
            cfg.binsize = vibechecker.BINSIZE_PRESETS[_BINSIZE_LABELS.index(bs_str)]
        except (ValueError, IndexError):
            pass
        if dpg.does_item_exist(ui.ACQ_DLG_WINDOW):
            win = dpg.get_value(ui.ACQ_DLG_WINDOW)
            if win in _FFT_WINDOWS:
                cfg.fft_window = win
        if dpg.does_item_exist(ui.ACQ_DLG_OVERLAP):
            cfg.welch_overlap = float(dpg.get_value(ui.ACQ_DLG_OVERLAP)) / 100.0
        if dpg.does_item_exist(ui.ACQ_DLG_HP_ENABLED):
            cfg.highpass_enabled = dpg.get_value(ui.ACQ_DLG_HP_ENABLED)
        if dpg.does_item_exist(ui.ACQ_DLG_HP_FC):
            cfg.highpass_fc = float(dpg.get_value(ui.ACQ_DLG_HP_FC))
        if dpg.does_item_exist(ui.ACQ_DLG_LP_ENABLED):
            cfg.lowpass_enabled = dpg.get_value(ui.ACQ_DLG_LP_ENABLED)
        if dpg.does_item_exist(ui.ACQ_DLG_LP_FC):
            cfg.lowpass_fc = float(dpg.get_value(ui.ACQ_DLG_LP_FC))
        if dpg.does_item_exist(ui.ACQ_DLG_CACHE_FRAMES):
            n = max(1, int(dpg.get_value(ui.ACQ_DLG_CACHE_FRAMES)))
            cfg.cache_frames = n
            self.collector.resize_frame_cache(n)

    def _on_acq_apply(self, sender=None, data=None):
        was_streaming = self.collector.is_streaming
        if was_streaming:
            self._stop_stream()
        self._apply_acq_settings_from_widgets()
        self._save_channel_assignments()  # persist acquisition settings to device YAML
        if self.collector.sensor is not None:
            self.collector.reconnect_stream()
        if was_streaming:
            self._start_stream()
        else:
            self.collector.reprocess_last_block()
        self._update_spectrum_info()

    # ------------------------------------------------------------------
    # Signal Generator Tab
    # ------------------------------------------------------------------

    def _populate_siggen_tab(self):
        """Sync signal generator tab widgets with current siggen_config."""
        cfg = self.collector.siggen_config
        if not dpg.does_item_exist(ui.SIGGEN_ENABLED):
            return
        if cfg is None:
            dpg.set_value(ui.SIGGEN_ENABLED, False)
        else:
            dpg.set_value(ui.SIGGEN_ENABLED, True)
            wave_name = next(
                (k for k, v in _SIGGEN_WAVE_TYPES.items() if v == cfg.get("wave_type")),
                "Sine",
            )
            dpg.set_value(ui.SIGGEN_WAVE_TYPE, wave_name)
            dpg.set_value(ui.SIGGEN_FREQ_HZ, float(cfg.get("freq_hz", 1000.0)))
            dpg.set_value(ui.SIGGEN_PKTOPK_MV, float(cfg.get("pktopk_uv", 0)) / 1000.0)
            dpg.set_value(ui.SIGGEN_OFFSET_MV, float(cfg.get("offset_uv", 0)) / 1000.0)

    # ------------------------------------------------------------------
    # Monitor Mode
    # ------------------------------------------------------------------

    def _populate_monitor_tab(self):
        """Sync Monitor config tab widgets from current device config."""
        if not dpg.does_item_exist(ui.MON_DLG_INTERVAL):
            return
        serial = self.collector.sensor.serial_number if self.collector.sensor else "__default__"
        device_cfg = _cfg.load_device_config(serial)
        mon = device_cfg.get("monitor", {})
        interval_s = float(mon.get("interval_s", 3600))
        pre_buf_s = float(mon.get("pre_buffer_s", 60))
        burst_dur_s = float(mon.get("burst_duration_s", 60))
        out_dir = mon.get("output_dir") or ""
        compress = mon.get("compression", "gzip") == "gzip"

        interval_label = vibechecker.MONITOR_INTERVAL_PRESETS.get(
            int(interval_s),
            vibechecker.MONITOR_INTERVAL_PRESETS[3600],
        )
        dpg.set_value(ui.MON_DLG_INTERVAL, interval_label)
        dpg.set_value(ui.MON_DLG_PRE_BUFFER, pre_buf_s)
        dpg.set_value(ui.MON_DLG_BURST_DUR, burst_dur_s)
        dpg.set_value(ui.MON_DLG_OUTPUT_DIR, str(out_dir))
        dpg.set_value(ui.MON_DLG_COMPRESS, compress)
        self._on_monitor_config_change()

    def _on_monitor_config_change(self, sender=None, data=None):
        """Update the storage estimate label when Monitor config widgets change."""
        if not dpg.does_item_exist(ui.MON_DLG_ESTIMATE):
            return
        interval_label = dpg.get_value(ui.MON_DLG_INTERVAL) if dpg.does_item_exist(ui.MON_DLG_INTERVAL) else "1 h"
        interval_s = next(
            (k for k, v in vibechecker.MONITOR_INTERVAL_PRESETS.items() if v == interval_label),
            3600,
        )
        burst_dur_s = float(dpg.get_value(ui.MON_DLG_BURST_DUR)) if dpg.does_item_exist(ui.MON_DLG_BURST_DUR) else 60.0

        cfg = self.collector.config
        block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 1.0
        block_bytes = cfg.blocksize * len(cfg.enabled_channels) * 8  # float64
        compressed = block_bytes * 0.5  # gzip ~50% compression

        # Interval logger: one capture per interval
        per_year = (365 * 24 * 3600 / interval_s) * compressed
        if per_year >= 1e9:
            interval_est = f"~{per_year / 1e9:.1f} GiB/year"
        else:
            interval_est = f"~{per_year / 1e6:.0f} MiB/year"
        if per_year > 50e9:
            interval_est += "  (exceeds 50 GiB)"

        # Per burst: frames captured during burst duration
        burst_frames = max(1, int(burst_dur_s / block_s)) if block_s > 0 else 1
        burst_bytes = burst_frames * compressed
        if burst_bytes >= 1e6:
            burst_est = f"~{burst_bytes / 1e6:.1f} MiB/burst"
        else:
            burst_est = f"~{burst_bytes / 1e3:.0f} KiB/burst"

        estimate = f"Interval: {interval_est}\nBurst: {burst_est}"
        dpg.set_value(ui.MON_DLG_ESTIMATE, estimate)

    def _on_record_toggle(self, sender=None, data=None):
        if self._monitor is not None and self._monitor.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        """Start streaming (if not running) and start monitor session."""
        from datetime import datetime, timezone

        # Start streaming if needed
        if not self.collector.is_streaming:
            self._toggle_acquisition()

        # Read dialog config (fall back to defaults when dialog hasn't been opened)
        interval_label = dpg.get_value(ui.MON_DLG_INTERVAL) if dpg.does_item_exist(ui.MON_DLG_INTERVAL) else "1 h"
        interval_s = next(
            (k for k, v in vibechecker.MONITOR_INTERVAL_PRESETS.items() if v == interval_label),
            3600,
        )
        pre_buf_s = float(dpg.get_value(ui.MON_DLG_PRE_BUFFER)) if dpg.does_item_exist(ui.MON_DLG_PRE_BUFFER) else 60.0
        burst_dur = float(dpg.get_value(ui.MON_DLG_BURST_DUR)) if dpg.does_item_exist(ui.MON_DLG_BURST_DUR) else 60.0
        out_dir_s = dpg.get_value(ui.MON_DLG_OUTPUT_DIR).strip() if dpg.does_item_exist(ui.MON_DLG_OUTPUT_DIR) else ""
        compress = dpg.get_value(ui.MON_DLG_COMPRESS) if dpg.does_item_exist(ui.MON_DLG_COMPRESS) else True

        cfg = self.collector.config
        block_s = cfg.blocksize / cfg.samplerate
        pre_buffer_n = max(1, int(pre_buf_s / block_s)) if block_s > 0 else 1

        now_utc = datetime.now(timezone.utc)
        session_id = now_utc.strftime('%Y-%m-%d-%H%M%S')

        if out_dir_s:
            output_dir = Path(out_dir_s) / session_id
        else:
            output_dir = vibechecker.data_dir() / "monitor" / session_id

        # Build config snapshots for embedding in every capture file
        acq_snapshot = cfg.to_dict()
        ch_snapshot: dict = {}
        for ch in cfg.enabled_channels:
            sc = self.collector.scope_sensors.get(ch)
            ch_snapshot[str(ch)] = {
                'name':           cfg.name_for(ch),
                'unit':           'mV',
                'coupling':       cfg.coupling_for(ch),
                'voltage_range':  cfg.voltage_range_for(ch),
                'scope_sensor_id': sc.id if sc else '',
                'target_unit':    cfg.target_unit_for(ch),
                'amplitude_mode': cfg.amplitude_mode_for(ch),
            }
        seen: set = set()
        sensor_snapshot: dict = {}
        for sc in self.collector.scope_sensors.values():
            if sc.id not in seen:
                seen.add(sc.id)
                sensor_snapshot[sc.id] = sc.to_dict()

        session = vibechecker.MonitorSession(
            session_id=session_id,
            start_time=now_utc,
            interval_s=float(interval_s),
            pre_buffer_frames=pre_buffer_n,
            burst_duration_s=burst_dur,
            max_burst_s=600.0,
            session_dir=output_dir,
            compression="gzip" if compress else "none",
            compression_level=4,
            acq_snapshot=acq_snapshot,
            channel_snapshot=ch_snapshot,
            sensor_snapshot=sensor_snapshot,
        )

        # Enlarge frame cache to hold pre-trigger frames
        self.collector.resize_frame_cache(max(self.collector.config.cache_frames, pre_buffer_n))

        if self._monitor is None:
            self._monitor = vibechecker.MonitorController()
        self._monitor.start(session)

        self._update_monitor_card()
        # Disable config setup buttons while recording
        for btn in (ui.BTN_DEVICE_SETUP, ui.BTN_CHANNELS_SETUP,
                    ui.BTN_SPECTRUM_SETUP, ui.BTN_SENSOR_SETUP, ui.BTN_MONITOR_SETUP):
            if dpg.does_item_exist(btn):
                dpg.configure_item(btn, enabled=False)

    def _stop_recording(self):
        """Stop the monitor session; leave streaming running."""
        if self._monitor is not None:
            self._monitor.stop()
        self.collector.resize_frame_cache(self.collector.config.cache_frames)
        self._update_monitor_card()
        for btn in (ui.BTN_DEVICE_SETUP, ui.BTN_CHANNELS_SETUP,
                    ui.BTN_SPECTRUM_SETUP, ui.BTN_SENSOR_SETUP, ui.BTN_MONITOR_SETUP):
            if dpg.does_item_exist(btn):
                dpg.configure_item(btn, enabled=True)

    def _on_arm_toggle(self, sender=None, data=None):
        if self._monitor is None or not self._monitor.is_recording:
            return
        if self._monitor.is_armed:
            self._monitor.disarm()
        else:
            self._monitor.arm()
        self._update_monitor_card()

    def _on_manual_burst(self, sender=None, data=None):
        if self._monitor is None or not self._monitor.is_recording:
            return
        self._monitor.trigger_burst()

    def _update_monitor_card(self):
        """Refresh the Monitor card labels and status text from controller state."""
        if not dpg.does_item_exist(ui.MONITOR_RECORD_BTN):
            return
        if self._monitor is not None and self._monitor.is_recording:
            snap = self._monitor.status_snapshot()
            h, rem = divmod(int(snap['elapsed_s']), 3600)
            m, s = divmod(rem, 60)
            captures = snap['capture_count']
            bursts = snap.get('burst_count', 0)
            nxt = snap['next_capture_s']
            err = snap.get('error')
            status = (f"REC  {h:02d}:{m:02d}:{s:02d}\n"
                      f"Captures: {captures}  Bursts: {bursts}\n"
                      f"Next: {nxt:.0f}s")
            if err:
                status += f"\nERR: {err[:40]}"
            session_id = self._monitor._session.session_id if self._monitor._session else ''
            status += f"\n{session_id}"
            dpg.set_item_label(ui.MONITOR_RECORD_BTN, f'{icons.IC["disarm"]}  Stop')
            dpg.set_value(ui.MONITOR_STATUS_TEXT, status)
            # Arm / Burst buttons
            if dpg.does_item_exist(ui.MONITOR_ARM_BTN):
                dpg.configure_item(ui.MONITOR_ARM_BTN, enabled=True)
                armed = self._monitor.is_armed
                dpg.set_item_label(ui.MONITOR_ARM_BTN,
                    f'{icons.IC["arm"]}  {"Disarm" if armed else "Arm"}')
            if dpg.does_item_exist(ui.MONITOR_BURST_BTN):
                dpg.configure_item(ui.MONITOR_BURST_BTN, enabled=True)
        else:
            dpg.set_item_label(ui.MONITOR_RECORD_BTN, f'{icons.IC["record"]}  Record')
            if not self.collector.is_streaming:
                dpg.set_value(ui.MONITOR_STATUS_TEXT, 'Start stream to record')
            else:
                dpg.set_value(ui.MONITOR_STATUS_TEXT, 'Stopped')
            if dpg.does_item_exist(ui.MONITOR_ARM_BTN):
                dpg.configure_item(ui.MONITOR_ARM_BTN, enabled=False)
                dpg.set_item_label(ui.MONITOR_ARM_BTN, f'{icons.IC["arm"]}  Arm')
            if dpg.does_item_exist(ui.MONITOR_BURST_BTN):
                dpg.configure_item(ui.MONITOR_BURST_BTN, enabled=False)

    # ------------------------------------------------------------------
    # Sensor Registry Dialog
    # ------------------------------------------------------------------

    def _init_sensor_registry_tab(self):
        """Populate the Sensors tab with current registry contents."""
        self._editing_scope_sensor_id = None
        self._refresh_registry_dialog_list()
        names = self.registry.names()
        if names:
            first = self.registry.find_by_name(names[0])
            self._editing_scope_sensor_id = first.id if first else None
            if dpg.does_item_exist(ui.SCOPE_REGISTRY_LIST):
                dpg.set_value(ui.SCOPE_REGISTRY_LIST, names[0])
            self._load_registry_sensor_fields(first)
        else:
            self._load_registry_sensor_fields(None)

    def _refresh_registry_dialog_list(self):
        """Refresh the sensor list in the registry dialog + channel dropdowns."""
        names = self.registry.names()
        if dpg.does_item_exist(ui.SCOPE_REGISTRY_LIST):
            dpg.configure_item(ui.SCOPE_REGISTRY_LIST, items=names)
        sensor_items = ["(none)"] + names
        for ch in range(self._num_channels):
            tag = ui.scope_ch_sensor(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, items=sensor_items)

    def _load_registry_sensor_fields(self, sensor: ScopeSensor | None):
        if not dpg.does_item_exist(ui.SREG_FIELD_NAME):
            return
        if sensor is None:
            dpg.set_value(ui.SREG_FIELD_NAME, "")
            dpg.set_value(ui.SREG_FIELD_UNITS, "g")
            dpg.set_value(ui.SREG_FIELD_SENS, 0.0)
            dpg.set_value(ui.SREG_FIELD_NOTES, "")
        else:
            dpg.set_value(ui.SREG_FIELD_NAME, sensor.name)
            dpg.set_value(ui.SREG_FIELD_UNITS, sensor.engineering_units)
            dpg.set_value(ui.SREG_FIELD_SENS, float(sensor.sensitivity))
            dpg.set_value(ui.SREG_FIELD_NOTES, sensor.notes or "")

    def _save_registry_sensor_fields(self):
        """Persist the right-pane fields to the registry if a sensor is selected."""
        if self._editing_scope_sensor_id is None:
            return
        if not dpg.does_item_exist(ui.SREG_FIELD_NAME):
            return
        name = dpg.get_value(ui.SREG_FIELD_NAME).strip()
        if not name:
            return
        existing = self.registry.find_by_id(self._editing_scope_sensor_id)
        sensor = ScopeSensor(
            name=name,
            engineering_units=dpg.get_value(ui.SREG_FIELD_UNITS),
            sensitivity=float(dpg.get_value(ui.SREG_FIELD_SENS)),
            target_unit=existing.target_unit if existing else "",
            id=self._editing_scope_sensor_id,
            notes=dpg.get_value(ui.SREG_FIELD_NOTES).strip(),
        )
        try:
            self.registry.update(sensor)
        except KeyError:
            pass
        self._refresh_registry_dialog_list()

    def _on_registry_sensor_select(self, sender, data):
        self._save_registry_sensor_fields()
        name = dpg.get_value(ui.SCOPE_REGISTRY_LIST)
        sensor = self.registry.find_by_name(name) if name else None
        self._editing_scope_sensor_id = sensor.id if sensor else None
        self._load_registry_sensor_fields(sensor)

    def _on_registry_add(self, sender=None, data=None):
        self._save_registry_sensor_fields()
        new_sensor = ScopeSensor(name="New Sensor", engineering_units="g", sensitivity=100.0, target_unit="g")
        self.registry.add(new_sensor)
        self._refresh_registry_dialog_list()
        self._editing_scope_sensor_id = new_sensor.id
        dpg.set_value(ui.SCOPE_REGISTRY_LIST, new_sensor.name)
        self._load_registry_sensor_fields(new_sensor)

    def _on_registry_delete(self, sender=None, data=None):
        if self._editing_scope_sensor_id is None:
            return
        self.registry.delete(self._editing_scope_sensor_id)
        self._editing_scope_sensor_id = None
        self._load_registry_sensor_fields(None)
        self._refresh_registry_dialog_list()

    # ------------------------------------------------------------------
    # Channel assignment helpers
    # ------------------------------------------------------------------

    def _refresh_assigned_sensors(self):
        """Re-fetch in-memory ScopeSensor objects after a registry edit."""
        for ch in range(self._num_channels):
            existing = self.collector.scope_sensors.get(ch)
            if existing is not None:
                updated = self.registry.find_by_id(existing.id)
                self.collector.set_scope_sensor(ch, updated)

    def _save_channel_assignments(self):
        if self.collector.sensor is None:
            return
        channels = {
            c: {
                "enabled": c in self.collector.config.enabled_channels,
                "sensor_id": self.collector.scope_sensors[c].id if c in self.collector.scope_sensors else None,
                "voltage_range": self.collector.config.voltage_range_for(c),
                "coupling": self.collector.config.coupling_for(c),
                "channel_name": self.collector.config.channel_names.get(c, ""),
                "target_unit": self.collector.config.channel_target_units.get(c, ""),
                "amplitude_mode": self.collector.config.channel_amplitude_modes.get(c, ""),
            }
            for c in range(self._num_channels)
        }
        device_cfg = {
            "channels": channels,
            "siggen": self.collector.siggen_config,
            "acquisition": self.collector.config.to_dict(),
        }
        _cfg.save_device_config(self.collector.sensor.serial_number, device_cfg)

    def _on_channel_enable_change(self, ch: int):
        if not dpg.does_item_exist(ui.scope_ch_enabled(ch)):
            return
        enabled = dpg.get_value(ui.scope_ch_enabled(ch))
        series_tags = [ui.plt_time_series(ch), ui.plt_freq_series(ch), ui.plt_trend_series(ch), ui.plt_freq_peaks(ch)]
        if enabled:
            if ch not in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.append(ch)
                self.collector.config.enabled_channels.sort()
            # Show if series already exists (file or prior capture); create if not
            if any(dpg.does_item_exist(t) for t in series_tags):
                for t in series_tags:
                    if dpg.does_item_exist(t):
                        dpg.show_item(t)
            else:
                self._add_channel_series(ch)
        else:
            self.collector.config.enabled_channels = [c for c in self.collector.config.enabled_channels if c != ch]
            for t in series_tags:
                if dpg.does_item_exist(t):
                    dpg.hide_item(t)
        self._save_channel_assignments()
        # Reflect enabled/disabled state in the header text color
        header_tag = ui.scope_ch_header(ch)
        theme_tag = ui.scope_ch_hdr_theme(ch, enabled)
        if dpg.does_item_exist(header_tag) and dpg.does_item_exist(theme_tag):
            dpg.bind_item_theme(header_tag, theme_tag)
        self._update_connection_summary()
        self._update_axis_assignment()
        self._update_results_section_visibility()
        # Skip live reconnect while the config dialog is open — _on_config_close
        # will do a single reconnect with all changes applied at once.
        if not dpg.is_item_visible(ui.DLG_CONFIG):
            self.collector.reconnect_stream()

    def _refresh_channel_names(self):
        """Sync channel name labels in plot series and results panel headers."""
        for ch in range(_MAX_CHANNELS):
            name = self.collector.config.name_for(ch)
            for series_tag in [ui.plt_time_series(ch), ui.plt_freq_series(ch), ui.plt_trend_series(ch)]:
                if dpg.does_item_exist(series_tag):
                    dpg.set_item_label(series_tag, name)
            header_tag = ui.ch_header_text(ch)
            if dpg.does_item_exist(header_tag):
                dpg.set_value(header_tag, name)

    def _redraw_all_channels(self):
        """Re-display the current cached frame for all enabled channels."""
        if not self.collector.is_streaming:
            self.collector.reprocess_last_block()

    def _refresh_channel_header(self, ch: int):
        """Update the name display text and collapsing-header summary label."""
        header_tag = ui.scope_ch_header(ch)
        name_tag = ui.scope_ch_name_text(ch)
        if not dpg.does_item_exist(header_tag):
            return
        name = dpg.get_value(ui.scope_ch_name(ch)).strip() or self.collector.config.name_for(ch)
        coup = (
            dpg.get_value(ui.scope_ch_coupling(ch))
            if dpg.does_item_exist(ui.scope_ch_coupling(ch))
            else self.collector.config.coupling_for(ch)
        )
        rng = dpg.get_value(ui.scope_ch_range(ch)) if dpg.does_item_exist(ui.scope_ch_range(ch)) else ""
        sensor = dpg.get_value(ui.scope_ch_sensor(ch)) if dpg.does_item_exist(ui.scope_ch_sensor(ch)) else "(none)"
        if dpg.does_item_exist(name_tag):
            dpg.set_value(name_tag, name)
        dpg.configure_item(header_tag, label=f"{coup}  {rng}  {sensor}")

    def _on_coupling_combo_change(self, ch: int, value: str):
        if value in ("AC", "DC"):
            self.collector.config.channel_couplings[ch] = value
            if self.collector.sensor is not None and not dpg.is_item_visible(ui.DLG_CONFIG):
                self.collector.reconnect_stream()
        self._refresh_channel_header(ch)

    def _on_range_combo_change(self, ch: int, label: str):
        if label not in _VOLTAGE_RANGE_LABELS:
            return
        self.collector.config.channel_voltage_ranges[ch] = _VOLTAGE_RANGE_LABELS.index(label)
        if self.collector.sensor is not None and not dpg.is_item_visible(ui.DLG_CONFIG):
            self.collector.reconnect_stream()
        self._refresh_channel_header(ch)

    def _on_sensor_combo_change(self, ch: int, sensor_name: str):
        if not dpg.does_item_exist(ui.scope_ch_sensor(ch)):
            return
        sensor = None if (not sensor_name or sensor_name == "(none)") else self.registry.find_by_name(sensor_name)
        self.collector.set_scope_sensor(ch, sensor)
        self._save_channel_assignments()
        self._update_connection_summary()
        self._update_axis_assignment()
        self._redraw_all_channels()
        self._refresh_channel_header(ch)

    def _restore_channel_assignments(self, device_cfg: dict | None = None):
        """Apply saved channel assignments, siggen, and acquisition config to the collector."""
        if device_cfg is None:
            if self.collector.sensor is not None:
                device_cfg = _cfg.load_device_config(self.collector.sensor.serial_number)
            else:
                device_cfg = _cfg.load_device_config("__default__")

        # Restore acquisition settings wholesale; channel-specific dicts applied below
        acq_dict = device_cfg.get("acquisition", {})
        if acq_dict:
            self.collector.config = AcquisitionSettings.from_dict(acq_dict)

        # Restore siggen
        siggen = device_cfg.get("siggen")
        self.collector.siggen_config = siggen
        self._populate_siggen_tab()

        assignments = device_cfg.get("channels", {})
        for ch, info in assignments.items():
            if ch >= self._num_channels:
                continue
            sensor_id = info.get("sensor_id")
            enabled = info.get("enabled", True)
            voltage_range = info.get("voltage_range", 7)
            coupling = info.get("coupling", "AC")
            channel_name = info.get("channel_name", "")
            target_unit = info.get("target_unit", "")
            amplitude_mode = info.get("amplitude_mode", "")
            sensor = self.registry.find_by_id(sensor_id) if sensor_id else None
            self.collector.set_scope_sensor(ch, sensor)
            self.collector.config.channel_voltage_ranges[ch] = voltage_range
            self.collector.config.channel_couplings[ch] = coupling
            if channel_name:
                self.collector.config.channel_names[ch] = channel_name
            if target_unit:
                self.collector.config.channel_target_units[ch] = target_unit
            if amplitude_mode:
                self.collector.config.channel_amplitude_modes[ch] = amplitude_mode
            if enabled and ch not in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.append(ch)
            elif not enabled and ch in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.remove(ch)
            if dpg.does_item_exist(ui.scope_ch_enabled(ch)):
                dpg.set_value(ui.scope_ch_enabled(ch), enabled)
            if sensor and dpg.does_item_exist(ui.scope_ch_sensor(ch)):
                dpg.set_value(ui.scope_ch_sensor(ch), sensor.name)
            range_tag = ui.scope_ch_range(ch)
            if dpg.does_item_exist(range_tag) and voltage_range < len(_VOLTAGE_RANGE_LABELS):
                dpg.set_value(range_tag, _VOLTAGE_RANGE_LABELS[voltage_range])
            coupling_tag = ui.scope_ch_coupling(ch)
            if dpg.does_item_exist(coupling_tag):
                dpg.set_value(coupling_tag, coupling)
            if enabled:
                self._add_channel_series(ch)
            else:
                self._remove_channel_series(ch)
        self.collector.config.enabled_channels.sort()
        for ch in self.collector.config.enabled_channels:
            if ch < self._num_channels:
                self._add_channel_series(ch)
        self._update_axis_assignment()
        self._update_results_section_visibility()

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def _create_gui(self):
        dpg.create_context()
        dpg.bind_font(icons.load())

        # ── Unified Config Dialog (Device / Sensors / Acquisition tabs) ───
        with dpg.window(
            label="Configuration",
            modal=True,
            show=False,
            tag=ui.DLG_CONFIG,
            width=_DLG_CFG_W,
            height=_DLG_CFG_H,
            pos=((WINDOW_WIDTH - _DLG_CFG_W) // 2, (WINDOW_HEIGHT - _DLG_CFG_H) // 2),
            no_scrollbar=True,
            no_scroll_with_mouse=True,
        ):
            with dpg.child_window(height=-_DLG_CLOSE_H, no_scrollbar=True, border=False):
                with dpg.tab_bar(tag=ui.CONFIG_TAB_BAR):
                    # ── Device tab ─────────────────────────────────────────
                    with dpg.tab(label="Device", tag=ui.CONFIG_TAB_DEVICE):
                        with dpg.child_window(autosize_x=True, height=-1):
                            with dpg.group(horizontal=True):
                                dpg.add_text("Detected Devices")
                                dpg.add_spacer(width=_DLG_DEVICE_TAB_SPACER)
                                dpg.add_button(label=icons.IC['refresh'], small=True, callback=self._start_device_discovery)
                            with dpg.group(tag=ui.DEVSETUP_DEVICE_LIST_GROUP):
                                pass

                    # ── Channels tab ────────────────────────────────────────
                    with dpg.tab(label="Channels", tag=ui.CONFIG_TAB_CHANNELS):
                        with dpg.child_window(autosize_x=True, height=-1):
                            dpg.add_text("Channel Configuration")
                            dpg.add_separator()
                            with dpg.group(tag=ui.DEVSETUP_CHANNEL_GROUP):
                                dpg.add_text("No device connected.")

                    # ── Sensors tab ────────────────────────────────────────
                    with dpg.tab(label="Sensors", tag=ui.CONFIG_TAB_SENSORS):
                        with dpg.child_window(height=-1, no_scrollbar=True, border=False):
                            with dpg.group(horizontal=True):
                                with dpg.child_window(width=_SREG_LIST_W, height=-1):
                                    dpg.add_text("Sensor Library")
                                    dpg.add_listbox(
                                        items=self.registry.names(),
                                        tag=ui.SCOPE_REGISTRY_LIST,
                                        num_items=15,
                                        width=-1,
                                        callback=self._on_registry_sensor_select,
                                    )
                                    dpg.add_separator()
                                    with dpg.group(horizontal=True):
                                        dpg.add_button(
                                            label=f'{icons.IC["add"]} Add',
                                            tag=ui.SCOPE_REGISTRY_ADD,
                                            callback=self._on_registry_add,
                                            width=_SREG_BTN_W,
                                        )
                                        dpg.add_button(
                                            label=f'{icons.IC["delete"]} Delete',
                                            tag=ui.SCOPE_REGISTRY_DELETE,
                                            callback=self._on_registry_delete,
                                            width=-1,
                                        )
                                with dpg.child_window(autosize_x=True, height=-1):
                                    dpg.add_text("Sensor Configuration")
                                    dpg.add_input_text(label="Name", tag=ui.SREG_FIELD_NAME, width=_SREG_FIELD_W)
                                    dpg.add_combo(
                                        label="Source EU",
                                        tag=ui.SREG_FIELD_UNITS,
                                        items=vibechecker.EU_OPTIONS,
                                        width=_SREG_FIELD_W,
                                    )
                                    dpg.add_input_float(
                                        label="Sensitivity (mV/eu)",
                                        tag=ui.SREG_FIELD_SENS,
                                        format="%.6f",
                                        width=_SREG_FIELD_W,
                                    )
                                    dpg.add_input_text(label="Notes", tag=ui.SREG_FIELD_NOTES, width=_SREG_FIELD_W)

                    # ── Acquisition tab ────────────────────────────────────
                    with dpg.tab(label="Acquisition", tag=ui.CONFIG_TAB_ACQUISITION):
                        with dpg.child_window(autosize_x=True, height=-1):
                            _w = 160
                            # Control: Freq. Range
                            dpg.add_text("Acquisition Sample Rate")
                            dpg.add_combo(
                                label="Freq. Range",
                                tag=ui.ACQ_DLG_MAXFREQ,
                                items=_MAXFREQ_LABELS,
                                width=_w,
                                callback=self._on_acq_preview,
                            )
                            # Derived: Sample Rate
                            dpg.add_input_text(label="Sample Rate", tag=ui.ACQ_DLG_SAMPLERATE, readonly=True, width=_w)

                            # Control: Freq. Resolution
                            dpg.add_separator()
                            dpg.add_text("Acqusition Sample Count")
                            dpg.add_combo(
                                label="Freq. Resolution",
                                tag=ui.ACQ_DLG_BINSIZE,
                                items=_BINSIZE_LABELS,
                                width=_w,
                                callback=self._on_acq_preview,
                            )
                            # Derived: # spectral lines
                            dpg.add_input_text(
                                label="Spectral Lines", tag=ui.ACQ_DLG_NFFT_BINS, readonly=True, width=_w
                            )
                            # Derived: Acquisition Time
                            dpg.add_input_text(label="Acq. Time", tag=ui.ACQ_DLG_ACQ_TIME, readonly=True, width=_w)

                            dpg.add_separator()
                            dpg.add_text("Signal Conditioning")
                            # Control: Highpass filter
                            with dpg.group(horizontal=True):
                                dpg.add_checkbox(label="Highpass", tag=ui.ACQ_DLG_HP_ENABLED, default_value=True)
                                dpg.add_input_float(
                                    label="Hz", tag=ui.ACQ_DLG_HP_FC, default_value=10.0, min_value=0.1, width=100
                                )
                            # Control: Lowpass filter
                            with dpg.group(horizontal=True):
                                dpg.add_checkbox(label="Lowpass", tag=ui.ACQ_DLG_LP_ENABLED, default_value=False)
                                dpg.add_input_float(
                                    label="Hz", tag=ui.ACQ_DLG_LP_FC, default_value=1000.0, min_value=1.0, width=100
                                )

                            # Control: Frame cache depth
                            dpg.add_separator()
                            dpg.add_text("Recording Length")
                            dpg.add_input_int(
                                label="Cache Frames",
                                tag=ui.ACQ_DLG_CACHE_FRAMES,
                                default_value=32,
                                min_value=1,
                                max_value=512,
                                callback=self._on_acq_preview,
                                width=_w,
                            )
                            # Derived: Recording window (acq_time × cache_frames)
                            dpg.add_input_text(label="Rec. Window", tag=ui.ACQ_DLG_REC_WINDOW, readonly=True, width=_w)
                            # Derived: Total memory (mem_per_ch × n_enabled × cache_frames)
                            dpg.add_input_text(label="Memory", tag=ui.ACQ_DLG_MEMORY, readonly=True, width=_w)

                            dpg.add_separator()
                            dpg.add_text("FFT Conditioning")
                            # Control: Welch % Overlap
                            dpg.add_input_float(
                                label="Welch Overlap %",
                                tag=ui.ACQ_DLG_OVERLAP,
                                default_value=50.0,
                                min_value=0.0,
                                max_value=95.0,
                                width=_w,
                            )
                            # Control: FFT Window
                            dpg.add_combo(
                                label="FFT Window",
                                tag=ui.ACQ_DLG_WINDOW,
                                items=_FFT_WINDOWS,
                                default_value="hann",
                                width=_w,
                            )

                    # ── Signal Generator tab ────────────────────────────────
                    with dpg.tab(label="Generate", tag=ui.CONFIG_TAB_SIGGEN):
                        with dpg.child_window(autosize_x=True, height=-1):
                            dpg.add_text("PicoScope Signal Generator")
                            dpg.add_separator()
                            dpg.add_checkbox(
                                label="Enable signal generator", tag=ui.SIGGEN_ENABLED, default_value=False
                            )
                            dpg.add_spacer(height=6)
                            dpg.add_combo(
                                label="Waveform",
                                tag=ui.SIGGEN_WAVE_TYPE,
                                items=list(_SIGGEN_WAVE_TYPES.keys()),
                                default_value="Sine",
                                width=_DLG_SIGGEN_W,
                            )
                            dpg.add_input_float(
                                label="Frequency (Hz)",
                                tag=ui.SIGGEN_FREQ_HZ,
                                default_value=1000.0,
                                min_value=0.0,
                                max_value=20_000_000.0,
                                width=_DLG_SIGGEN_W,
                            )
                            dpg.add_input_float(
                                label="Amplitude pk-pk (mV)",
                                tag=ui.SIGGEN_PKTOPK_MV,
                                default_value=1000.0,
                                min_value=0.0,
                                max_value=4000.0,
                                width=_DLG_SIGGEN_W,
                            )
                            dpg.add_input_float(
                                label="Offset (mV)",
                                tag=ui.SIGGEN_OFFSET_MV,
                                default_value=0.0,
                                min_value=-2000.0,
                                max_value=2000.0,
                                width=_DLG_SIGGEN_W,
                            )
                            dpg.add_spacer(height=6)
                            dpg.add_text("Note: Only active on PicoScope hardware.", color=_c("ON_SURFACE"))

                    # ── Monitor tab ─────────────────────────────────────────
                    with dpg.tab(label="Monitor", tag=ui.CONFIG_TAB_MONITOR):
                        with dpg.child_window(autosize_x=True, height=-1):
                            _mon_w = 220
                            dpg.add_text("Interval Datalogger")
                            dpg.add_separator()
                            dpg.add_combo(
                                label="Capture interval",
                                tag=ui.MON_DLG_INTERVAL,
                                items=list(vibechecker.MONITOR_INTERVAL_PRESETS.values()),
                                default_value="1 h",
                                width=_mon_w,
                                callback=self._on_monitor_config_change,
                            )
                            dpg.add_input_float(
                                label="Pre-trigger buffer (s)",
                                tag=ui.MON_DLG_PRE_BUFFER,
                                default_value=60.0,
                                min_value=0.0,
                                max_value=3600.0,
                                width=_mon_w,
                                callback=self._on_monitor_config_change,
                            )
                            dpg.add_input_float(
                                label="Burst duration (s)",
                                tag=ui.MON_DLG_BURST_DUR,
                                default_value=60.0,
                                min_value=1.0,
                                max_value=600.0,
                                width=_mon_w,
                                callback=self._on_monitor_config_change,
                            )
                            dpg.add_spacer(height=6)
                            dpg.add_separator()
                            dpg.add_text("Output directory", color=_c("ON_SURFACE"))
                            dpg.add_input_text(
                                tag=ui.MON_DLG_OUTPUT_DIR,
                                default_value="",
                                hint="Default: DEVDATA/monitor/",
                                width=-1,
                                callback=self._on_monitor_config_change,
                            )
                            dpg.add_spacer(height=4)
                            dpg.add_checkbox(
                                label="gzip compression",
                                tag=ui.MON_DLG_COMPRESS,
                                default_value=True,
                                callback=self._on_monitor_config_change,
                            )
                            dpg.add_spacer(height=6)
                            dpg.add_separator()
                            dpg.add_text("", tag=ui.MON_DLG_ESTIMATE, color=_c("ON_SURFACE"))

            dpg.add_separator()
            dpg.add_button(label=f'{icons.IC["close"]}  Close', callback=self._on_config_close, width=-1)

        # ── Section container theme (slightly lighter than window background) ──
        _sect_bg = vibechecker.hex_to_rgba(vibechecker.THEME_COLORS["SURFACE"])
        with dpg.theme() as self._sect_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _sect_bg, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 8, 6, category=dpg.mvThemeCat_Core)

        # ── Toggle button state themes (idle=red, waiting=yellow, active=green) ──
        for state, bg_key, fg_key in [
            ("idle", "RED_DARK", "RED_LIGHT"),
            ("waiting", "YELLOW_DARK", "YELLOW_LIGHT"),
            ("active", "GREEN_DARK", "GREEN_LIGHT"),
        ]:
            bg = _c(bg_key)
            fg = _c(fg_key)
            with dpg.theme() as _t:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, bg, category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, bg, category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, bg, category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_Text, fg, category=dpg.mvThemeCat_Core)
            self._toggle_themes[state] = _t

        # ── Main window ────────────────────────────────────────────────
        with dpg.window(label="Vibe Checkup", tag=ui.PRIMARY_WINDOW):
            with dpg.group(horizontal=True):
                # ── Controls column (left) ────────────────────────────
                with dpg.child_window(width=CONTROLS_WIDTH, autosize_y=True):
                    # ── Device ───────────────────────────────────────
                    with dpg.child_window(border=True, width=-1, height=_CARD_H_DEVICE, no_scrollbar=True) as _s1:
                        dpg.bind_item_theme(_s1, self._sect_theme)
                        with dpg.group(horizontal=True):
                            dpg.add_text(icons.IC['developer_board'])
                            dpg.add_spacer(width=4)
                            dpg.add_text("Device")
                            dpg.add_spacer(width=-1)
                            dpg.add_button(
                                label=icons.IC['settings'],
                                tag=ui.BTN_DEVICE_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_DEVICE),
                            )
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            with dpg.drawlist(width=16, height=16, tag=ui.DEVICE_STATUS):
                                dpg.draw_rectangle(
                                    pmin=(1, 1),
                                    pmax=(15, 15),
                                    fill=_c("RED"),
                                    color=(0, 0, 0, 0),
                                    rounding=3,
                                    tag=ui.DEVICE_STATUS_RECT,
                                )
                            dpg.add_text("Not Connected", tag=ui.CONN_STATUS_TEXT)
                        with dpg.group(tag=ui.DEVICE_INFO_GROUP):
                            pass
                        dpg.add_spacer(height=2)

                    dpg.add_spacer(height=6)

                    # ── Channels ─────────────────────────────────────
                    with dpg.child_window(
                        border=True,
                        width=-1,
                        height=_CARD_H_CHANNELS,
                        no_scrollbar=True,
                        tag=ui.CHANNELS_CARD,
                    ) as _s_ch:
                        dpg.bind_item_theme(_s_ch, self._sect_theme)
                        with dpg.group(horizontal=True):
                            dpg.add_text(icons.IC['channels'])
                            dpg.add_spacer(width=4)
                            dpg.add_text("Channels")
                            dpg.add_spacer(width=-1)
                            dpg.add_button(
                                label=icons.IC['sensors'],
                                tag=ui.BTN_SENSOR_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_SENSORS),
                            )
                            dpg.add_button(
                                label=icons.IC['settings'],
                                tag=ui.BTN_CHANNELS_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_CHANNELS),
                            )
                        dpg.add_separator()
                        with dpg.group(tag=ui.CONN_CHANNEL_SUMMARY):
                            pass
                        dpg.add_spacer(height=2)

                    dpg.add_spacer(height=6)

                    # ── Acquisition (stream control + spectrum info) ──
                    with dpg.child_window(border=True, width=-1, height=_CARD_H_ACQ, no_scrollbar=True) as _s2:
                        dpg.bind_item_theme(_s2, self._sect_theme)
                        with dpg.group(horizontal=True):
                            dpg.add_text(icons.IC['acquisition'])
                            dpg.add_spacer(width=4)
                            dpg.add_text("Acquisition")
                            dpg.add_spacer(width=-1)
                            dpg.add_button(
                                label=icons.IC['settings'],
                                tag=ui.BTN_SPECTRUM_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_ACQUISITION),
                            )
                        dpg.add_separator()
                        dpg.add_button(
                            label=f'{icons.IC["play_arrow"]}  Stopped', tag=ui.ACQ_TOGGLE,
                            callback=self._toggle_acquisition, width=-1, height=40,
                        )
                        dpg.add_spacer(height=2)
                        dpg.add_button(label=f'{icons.IC["photo_camera"]}  Single', tag=ui.ACQ_SINGLE, callback=self._collect_sample, width=-1)
                        dpg.add_button(
                            label=f'{icons.IC["fit_screen"]}  Autoscale', tag=ui.ACQ_AUTOSCALE, callback=self._autoscale_plots, width=-1
                        )
                        with dpg.group(horizontal=True):
                            dpg.add_button(
                                label=f'{icons.IC["delete_sweep"]}  Clear Cache', tag=ui.ACQ_CLEAR_CACHE, callback=self._clear_cache, width=-1
                            )
                        dpg.add_spacer(height=4)
                        dpg.add_separator()
                        dpg.add_text("Browse Waveforms", color=_c("ON_SURFACE"))
                        with dpg.group(horizontal=True):
                            dpg.add_button(
                                label=icons.IC['first_page'], tag=ui.ACQ_BROWSE_FIRST, callback=self._on_browse, width=28, enabled=False
                            )
                            dpg.add_button(
                                label=icons.IC['navigate_before'], tag=ui.ACQ_BROWSE_PREV, callback=self._on_browse, width=28, enabled=False
                            )
                            dpg.add_text("No frames", tag=ui.ACQ_BROWSE_LABEL)
                            dpg.add_button(
                                label=icons.IC['navigate_next'], tag=ui.ACQ_BROWSE_NEXT, callback=self._on_browse, width=28, enabled=False
                            )
                            dpg.add_button(
                                label=icons.IC['last_page'], tag=ui.ACQ_BROWSE_LAST, callback=self._on_browse, width=28, enabled=False
                            )
                        dpg.add_spacer(height=6)
                        dpg.add_separator()
                        dpg.add_text("Spectrum Setup", color=_c("ON_SURFACE"))
                        dpg.add_input_text(
                            tag=ui.SPECTRUM_INFO_TEXT,
                            multiline=True,
                            readonly=True,
                            default_value="",
                            width=-1,
                            height=120,
                        )

                    dpg.add_spacer(height=6)

                    # ── Monitor Mode ──────────────────────────────────
                    with dpg.child_window(
                        border=True,
                        width=-1,
                        height=_CARD_H_MONITOR,
                        no_scrollbar=True,
                        tag=ui.MONITOR_CARD,
                    ) as _s_mon:
                        dpg.bind_item_theme(_s_mon, self._sect_theme)
                        with dpg.group(horizontal=True):
                            dpg.add_text(icons.IC['monitor_heart'])
                            dpg.add_spacer(width=4)
                            dpg.add_text("Monitor Mode")
                            dpg.add_spacer(width=-1)
                            dpg.add_button(
                                label=icons.IC['settings'],
                                tag=ui.BTN_MONITOR_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_MONITOR),
                            )
                        dpg.add_separator()
                        dpg.add_button(
                            label=f'{icons.IC["record"]}  Record',
                            tag=ui.MONITOR_RECORD_BTN,
                            callback=self._on_record_toggle,
                            width=-1,
                            height=32,
                        )
                        dpg.add_spacer(height=2)
                        dpg.add_button(
                            label=f'{icons.IC["arm"]}  Arm',
                            tag=ui.MONITOR_ARM_BTN,
                            callback=self._on_arm_toggle,
                            width=-1,
                            enabled=False,
                        )
                        dpg.add_button(
                            label=f'{icons.IC["photo_camera"]}  Trigger Burst',
                            tag=ui.MONITOR_BURST_BTN,
                            callback=self._on_manual_burst,
                            width=-1,
                            enabled=False,
                        )
                        dpg.add_spacer(height=2)
                        dpg.add_text("Start stream to record", tag=ui.MONITOR_STATUS_TEXT, color=_c("ON_SURFACE"))
                        dpg.add_spacer(height=4)
                        dpg.add_button(
                            label=f'{icons.IC["folder_open"]}  Load Session',
                            tag=ui.BTN_MONITOR_BROWSE,
                            callback=self._open_session_browser,
                            width=-1,
                        )

                    dpg.add_spacer(height=6)

                    # ── File ──────────────────────────────────────────
                    with dpg.child_window(border=True, width=-1, height=_CARD_H_FILE, no_scrollbar=True) as _s4:
                        dpg.bind_item_theme(_s4, self._sect_theme)
                        with dpg.group(horizontal=True):
                            dpg.add_text(icons.IC['folder'])
                            dpg.add_spacer(width=4)
                            dpg.add_text("File")
                            dpg.add_spacer(width=-1)
                            dpg.add_button(
                                label=f'{icons.IC["save"]} Save', tag=ui.FILE_SAVE, callback=self._on_save_click
                            )
                            dpg.add_button(
                                label=f'{icons.IC["folder_open"]} Load', tag=ui.FILE_LOAD, callback=self._on_load_click
                            )
                        dpg.add_separator()
                        dpg.add_text("Measurement Notes", color=_c("ON_SURFACE"))
                        dpg.add_input_text(
                            tag=ui.ACQ_NOTES,
                            multiline=True,
                            width=-1,
                            height=90,
                            hint="Worksite, machine, sensor location…",
                        )

                # ── Main column (center — plots) ──────────────────────
                with dpg.child_window(width=-RESULTS_WIDTH, autosize_y=True, no_scrollbar=True):
                    self._channel_themes = []
                    self._peak_themes = []
                    for color in _CH_COLORS:
                        with dpg.theme() as t:
                            with dpg.theme_component(dpg.mvLineSeries):
                                dpg.add_theme_color(dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots)
                        self._channel_themes.append(t)
                        with dpg.theme() as pt:
                            with dpg.theme_component(dpg.mvScatterSeries):
                                dpg.add_theme_style(
                                    dpg.mvPlotStyleVar_Marker, dpg.mvPlotMarker_Square, category=dpg.mvThemeCat_Plots
                                )
                                dpg.add_theme_color(dpg.mvPlotCol_MarkerFill, color, category=dpg.mvThemeCat_Plots)
                                dpg.add_theme_color(dpg.mvPlotCol_MarkerOutline, color, category=dpg.mvThemeCat_Plots)
                        self._peak_themes.append(pt)

                    with dpg.tab_bar():
                        with dpg.tab(label="Spectrum"):
                            with dpg.plot(
                                label="Frequency Series",
                                width=-1,
                                height=-TIME_PLOT_HEIGHT,
                                tag=ui.PLT_FREQ,
                                crosshairs=True,
                            ):
                                dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=ui.PLT_FREQ_LEGEND)
                                dpg.add_plot_axis(dpg.mvXAxis, label="Frequency, hz", tag=ui.PLT_FREQ_AX_FREQ)
                                dpg.add_plot_axis(dpg.mvYAxis, label="", tag=ui.PLT_FREQ_AX_ACCEL)
                                dpg.add_plot_axis(dpg.mvYAxis2, label="", tag=ui.PLT_FREQ_AX_2)
                                dpg.hide_item(ui.PLT_FREQ_AX_2)
                        with dpg.tab(label="Trend"):
                            with dpg.plot(
                                label="Trend Series",
                                width=-1,
                                height=-TIME_PLOT_HEIGHT,
                                tag=ui.PLT_TREND,
                                crosshairs=True,
                            ):
                                dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=ui.PLT_TREND_LEGEND)
                                dpg.add_plot_axis(dpg.mvXAxis, label="Time, s", tag=ui.PLT_TREND_AX_TIME)
                                dpg.add_plot_axis(dpg.mvYAxis, label="Overall Vibration", tag=ui.PLT_TREND_AX_OVERALL)
                                dpg.add_plot_axis(dpg.mvYAxis2, label="", tag=ui.PLT_TREND_AX_OVERALL_2)
                                dpg.hide_item(ui.PLT_TREND_AX_OVERALL_2)
                    with dpg.plot(
                        label="Time Series", width=-1, height=TIME_PLOT_HEIGHT, tag=ui.PLT_SAMPLE, crosshairs=True
                    ):
                        dpg.add_plot_legend(location=dpg.mvPlot_Location_East, tag=ui.PLT_SAMPLE_LEGEND)
                        dpg.add_plot_axis(dpg.mvXAxis, label="Time, ms", tag=ui.PLT_SAMPLE_AX_TIME)
                        dpg.add_plot_axis(dpg.mvYAxis, label="", tag=ui.PLT_SAMPLE_AX_ACCEL)
                        dpg.add_plot_axis(dpg.mvYAxis2, label="", tag=ui.PLT_SAMPLE_AX_ACCEL_2)
                        dpg.hide_item(ui.PLT_SAMPLE_AX_ACCEL_2)

                # ── Results column (right) ────────────────────────────
                with dpg.child_window(width=RESULTS_WIDTH, autosize_y=True):
                    # Channel warnings — hidden until an overflow occurs
                    with dpg.child_window(
                        border=True,
                        autosize_x=True,
                        height=_CARD_BASE_H,
                        no_scrollbar=True,
                        tag=ui.CH_WARNINGS_SECTION,
                        show=False,
                    ) as _sw:
                        dpg.bind_item_theme(_sw, self._sect_theme)
                        dpg.add_text("Channel Warnings", color=_c("RED_LIGHT"))
                        dpg.add_separator()
                        for _ch in range(_MAX_CHANNELS):
                            dpg.add_text(
                                f"Overvoltage Ch {chr(65 + _ch)}",
                                tag=ui.ch_overflow_warning(_ch),
                                color=_c("RED_LIGHT"),
                                show=False,
                            )

                    dpg.add_spacer(height=4)
                    dpg.add_input_int(
                        label="Peak Display",
                        tag=ui.FFT_PEAKS_DISPLAY_COUNT,
                        default_value=6,
                        callback=self._redraw,
                        width=100,
                    )
                    dpg.add_spacer(height=4)

                    # Per-channel result sections (all hidden by default;
                    # _update_results_section_visibility shows enabled ones)
                    for _ch in range(_MAX_CHANNELS):
                        with dpg.child_window(
                            border=True,
                            autosize_x=True,
                            height=_RESULTS_CARD_HEIGHT,
                            no_scrollbar=True,
                            tag=ui.ch_result_section(_ch),
                            show=False,
                        ) as _sr:
                            dpg.bind_item_theme(_sr, self._sect_theme)
                            with dpg.group(horizontal=True):
                                with dpg.drawlist(width=14, height=14):
                                    dpg.draw_rectangle(
                                        pmin=(2, 2),
                                        pmax=(12, 12),
                                        fill=_CH_COLORS[_ch % len(_CH_COLORS)],
                                        color=(0, 0, 0, 0),
                                        rounding=2,
                                    )
                                dpg.add_text(self.collector.config.name_for(_ch), tag=ui.ch_header_text(_ch))
                            dpg.add_separator()
                            dpg.add_input_text(
                                label="Overall",
                                tag=ui.ch_overall_value(_ch),
                                readonly=True,
                                default_value="0.0",
                                width=RESULTS_WIDTH // 2,
                            )
                            dpg.add_table(
                                header_row=True,
                                row_background=True,
                                borders_innerV=True,
                                no_host_extendX=True,
                                tag=ui.ch_peaks_table(_ch),
                            )
                        dpg.add_spacer(height=2)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _setup_keyboard_handlers(self) -> None:
        """Register global key bindings via DPG handler registry.

        Ctrl+A  autoscale plots
        Ctrl+K  start / stop acquisition
        Ctrl+S  save recording
        Ctrl+O  open / load recording
        Ctrl+Q  quit
        Left    previous frame  (browse mode only)
        Right   next frame      (browse mode only)
        """
        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self._on_key_press)

    def _on_key_press(self, sender, app_data) -> None:
        key = app_data
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)

        if ctrl:
            if key == dpg.mvKey_A:
                self._autoscale_plots()
            elif key == dpg.mvKey_K:
                self._toggle_acquisition()
            elif key == dpg.mvKey_S:
                self._on_save_click()
            elif key == dpg.mvKey_O:
                self._on_load_click()
            elif key == dpg.mvKey_Q:
                dpg.stop_dearpygui()
        elif not self.collector.is_streaming:
            if key == dpg.mvKey_Left:
                self.collector.browse_frame(+1)
            elif key == dpg.mvKey_Right:
                self.collector.browse_frame(-1)

    def initialize(self):
        _cfg.ensure_default_config()
        self._create_gui()
        self._setup_keyboard_handlers()
        self._update_spectrum_info()
        self._update_connection_summary()
        self._update_axis_assignment()
        self._refresh_registry_dialog_list()
        self._set_stream_status("idle")  # apply initial toggle button theme
        log.info("Setup GUI")
        dpg.setup_dearpygui()
        # TODO: open device connection window automatically at startup so the user
        #       is prompted to connect a device without needing to find the menu.
        #       Uncomment the line below once the config dialog open/close lifecycle
        #       is stable (see _on_config_close TODO above).
        # self._open_config_dialog(ui.CONFIG_TAB_DEVICE)

    def run(self):
        log.info("Launch app window")
        dpg.create_viewport(title="Vibe Logger", width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        dpg.show_viewport()
        dpg.set_primary_window(ui.PRIMARY_WINDOW, True)
        threading.Thread(target=self._autoconnect, daemon=True).start()
        log.info("Start DPG backend")
        while dpg.is_dearpygui_running():
            self._poll_new_frames()
            dpg.render_dearpygui_frame()

    def cleanup(self):
        log.info("Cleanup app assets")
        self.collector.disconnect_sensor()
        dpg.destroy_context()
        log.info("App Exit")

    def serve(self):
        self.initialize()
        self.run()
        self.cleanup()
