# Rev80 frontend

import threading
import time
from pathlib import Path

import dearpygui.dearpygui as dpg
import h5py
import numpy as np

import rev80
from rev80 import _profile
from rev80.gui_charts import (  # noqa: F401 (envelope_search_fmax: re-export)
    DEFAULT_PEAK_DISPLAY_CAP, ChartsView, envelope_search_fmax,
)
from rev80 import peaks as rev80_peaks
import rev80.config as _cfg
import rev80.icons as icons
from rev80.sample import AcquisitionSettings
from rev80.scope_sensor import ScopeSensor
from rev80.scope_sensor_registry import ScopeSensorRegistry
from rev80 import tach as rev80_tach
from rev80.util import (
    ANOMALY_HOOK_LABELS,
    DEFAULT_RMS_ALPHA,
    DEFAULT_ROTATION_UNIT,
    DEFAULT_SPEC_ALPHA,
    ROTATION_UNIT_LABELS,
    ROTATION_UNITS,
    rotation_from_rpm,
    GUI_ANOMALY_HOOK_TYPES,
    UNIT_TO_SI,
    canonical_hook_type,
    gui_hook_type,
    hook_type_label,
    nearest_interval_preset,
)

log = rev80.get_logger("gui")
ui = rev80.UI_Elements()

# Layout constants
# TODO: make left/right panel widths and plot heights resizable by mouse drag.
#   DPG supports this via dpg.add_drag_line or manual splitter groups; defer
#   until the panel layout is otherwise stable.
WINDOW_WIDTH = 1500
WINDOW_HEIGHT = 1000
CONTROLS_WIDTH = 300
RESULTS_WIDTH = 300

# Config dialog dimensions — referenced wherever the dialog is built or positioned
_DLG_CFG_W = 720
_DLG_CFG_H = 840
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
_TACH_CARD_HEIGHT = _CARD_BASE_H + 2 * _CARD_LINE_H
_CARD_BTN_H = 28   # single button row height
_CARD_H_DEVICE = _CARD_BASE_H + _CARD_LINE_H * 5  # disconnected baseline
_CARD_H_CHANNELS = _CARD_BASE_H + _CARD_BTN_H + _CARD_LINE_H
_CARD_H_ACQ = (
    _CARD_BASE_H + _CARD_BTN_H * 6 + _CARD_LINE_H * 10
)  # Acquisition: toggle+controls+spectrum info box
_CARD_H_FILE = _CARD_BASE_H + _CARD_LINE_H + 105  # notes field only (Save/Load in header)
_CARD_H_MONITOR = _CARD_BASE_H + _CARD_BTN_H * 4 + _CARD_LINE_H * 5  # Monitor+Reset+RecordBurst+Load + status+burst indicator


def _c(key: str, alpha: int = 255) -> tuple:
    """Shorthand: THEME_COLORS[key] → DPG RGBA tuple."""
    return rev80.hex_to_rgba(rev80.THEME_COLORS[key], alpha)



_CH_COLORS = [
    _c("BLUE"),   # Ch A
    _c("ORANGE"),  # Ch B
    _c("LIME"),  # Ch C
    _c("CORAL"),  # Ch D
    _c("CYAN"),  # Ch E
    _c("VIOLET"),  # Ch F
    _c("GOLD"),  # Ch G
    _c("SILVER"),  # Ch H
]

# Spectrum dialog display labels — index-aligned with preset lists
_MAXFREQ_LABELS = [f"{int(f)} Hz" for f in rev80.MAXFREQ_PRESETS]


def derive_acquisition_preview(maxfreq: float, binsize: float) -> dict:
    """Derived acquisition values for the settings dialog preview.

    Delegates to AcquisitionSettings, so the preview shows the values that the
    instrument uses. Never duplicate the formula here.
    """
    cfg = rev80.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = binsize
    return {
        'samplerate': cfg.samplerate,
        'blocksize':  cfg.blocksize,
        'n_fft_bins': cfg.n_fft_bins,
        'acq_time':   cfg.acquisition_period,
        'mem_bytes':  cfg.memory_bytes,
        'binsize_actual': cfg.binsize_actual,
    }


# Seed values of the acquisition.yaml monitor block. The monitor fallbacks in
# this module use them, so that the GUI, the config file and headless agree.
_MON_SEED = _cfg._BUILTIN_ACQ['monitor']
_ANOM_SEED = _MON_SEED['anomaly']

# The units and amplitude modes that a hook can compare. The user selects
# both for each hook; there is no "each channel's own" choice.
_HOOK_UNITS = tuple(sorted(UNIT_TO_SI.keys()))
_HOOK_MODES = tuple(rev80.AMPLITUDE_MODES)


def _hook_choice(value, items, default) -> str:
    """A stored hook unit or mode, or `default` if it is empty or not in `items`."""
    return str(value) if value in items else default
# The seed has no EWMA times. These are the widget values when the config
# has none.
_EWMA_TIME_DEFAULTS = {'rms_ewma_time': 60.0, 'spec_ewma_time': 300.0}


def interval_from_label(label, fallback_s: float) -> float:
    """Interval in seconds for a MONITOR_INTERVAL_PRESETS label.

    Returns fallback_s when the label is not a preset label.
    """
    return float(next(
        (k for k, v in rev80.MONITOR_INTERVAL_PRESETS.items() if v == label),
        fallback_s,
    ))


def interval_to_save(label, stored_s) -> float:
    """Interval in seconds to write to acquisition.yaml.

    The combo shows only presets. A stored interval that is not a preset
    shows as the nearest preset. If the combo still shows that preset, keep
    the stored value, so that a dialog close does not change it.
    """
    try:
        stored = float(stored_s)
    except (TypeError, ValueError):
        stored = float(_MON_SEED['interval_s'])
    shown = rev80.MONITOR_INTERVAL_PRESETS.get(nearest_interval_preset(stored))
    if label == shown:
        return stored
    return interval_from_label(label, stored)


# Welch runs one segment per frame (nperseg == blocksize), so the overlap has
# no segments to act on.
_WELCH_OVERLAP_TIP = (
    "Welch Overlap: at present this setting has no effect on the spectrum. "
    "Welch uses one segment per frame: the segment is the full block, so "
    "there are no adjacent segments to overlap. The value is kept in the "
    "settings and in each saved file. To make the spectrum smoother, use "
    "Average spectrum."
)


def degraded_rate_text(effective_hz: float | None, cfg) -> str:
    """Text of the degraded-rate warning.

    The stream measures its raw acquisition rate, so compare it with the
    nominal raw rate, not with the display rate.
    """
    if effective_hz is None:
        return "⚠ rate degraded"
    return f"⚠ rate degraded: {effective_hz:.0f}/{cfg.raw_samplerate:.0f} Hz"


# Assumed gzip ratio for the storage estimate. It is not measured: the ratio
# changes with the signal.
_ASSUMED_GZIP_RATIO = 0.5


def monitor_storage_estimate(cfg, interval_s: float, burst_s: float,
                             pre_s: float) -> tuple[str, float]:
    """Estimated session storage, as (text, bytes per year of interval captures).

    Units are decimal (1 GB = 1e9 bytes). A session stores the raw-rate
    waveform of each vibration channel. A tachometer channel stores only
    edge times, a few float64 values per second, so it is not counted.
    """
    raw_fs = cfg.raw_samplerate
    block_s = cfg.raw_blocksize / raw_fs if raw_fs else 1.0
    block_bytes = cfg.raw_blocksize * len(cfg.vibration_channels) * 8  # float64
    compressed = block_bytes * _ASSUMED_GZIP_RATIO

    # Interval logger: one capture per interval
    per_year = (365 * 24 * 3600 / interval_s) * compressed
    if per_year >= 1e9:
        interval_est = f"~{per_year / 1e9:.1f} GB/year"
    else:
        interval_est = f"~{per_year / 1e6:.0f} MB/year"
    if per_year > 50e9:
        interval_est += "  (exceeds 50 GB)"

    # Per burst: pre-buffer frames + post-trigger frames
    burst_frames = max(1, int((burst_s + pre_s) / block_s)) if block_s > 0 else 1
    burst_bytes = burst_frames * compressed
    if burst_bytes >= 1e6:
        burst_est = f"~{burst_bytes / 1e6:.1f} MB/burst"
    else:
        burst_est = f"~{burst_bytes / 1e3:.0f} kB/burst"

    return f"Interval: {interval_est}\nBurst: {burst_est}", per_year
_BINSIZE_LABELS = [f"{b} Hz/bin" for b in rev80.BINSIZE_PRESETS]

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


def apply_tach_claim(collector, channel, implicit_enabled, settings=None):
    """Claim `channel` for the tachometer role, or release it when None.

    Returns the new implicitly enabled channel, or None. Free of dearpygui, so
    tests can run it without a viewport. Claiming enables the channel, because
    `config.tach_channels` ignores disabled channels. A release switches off a
    channel that the claim enabled: as a vibration channel, its pulse train
    reads as a failing bearing (1515 mV overall, kurtosis 15.94). Evidence:
    CONTRIBUTING.md, "E14. Tachometer".
    """
    cfg = collector.config
    for old in [c for c, r in cfg.channel_roles.items() if r == 'tachometer']:
        del cfg.channel_roles[old]
        collector.set_tach_settings(old, None)
        if old == implicit_enabled and old in cfg.enabled_channels:
            cfg.enabled_channels.remove(old)
        implicit_enabled = None

    if channel is None:
        return None

    cfg.channel_roles[channel] = 'tachometer'
    collector.set_tach_settings(channel, settings or rev80_tach.TachSettings())
    if channel not in cfg.enabled_channels:
        cfg.enabled_channels = sorted(cfg.enabled_channels + [channel])
        return channel
    return None


class GUI:
    collector: rev80.DataCollector
    found_sensors: list
    _pending_collector: 'rev80.DataCollector | None' = None

    def __init__(self):
        self.context = None
        # Render-loop failure bookkeeping — see _handle_render_error.
        self._render_errors: dict[str, int] = {}
        self._consecutive_render_errors: int = 0
        self._cleaned_up: bool = False
        self.collector = rev80.DataCollector()
        # A collector that a worker thread loaded; the render thread swaps it
        # in on its next tick. See _replace_collector.
        self._pending_collector = None
        self.registry = ScopeSensorRegistry()
        self._editing_scope_sensor_id: str | None = None
        # Channel the Tachometer tab switched on implicitly when it was
        # claimed, so releasing the role can switch it back off again.
        self._tach_implicit_enable: int | None = None
        # The chart tabs and the spectrum result cards. See gui_charts.py.
        self._charts = ChartsView(self)
        # Axes that _autoscale_plots locked; released one frame later.
        self._autoscale_locked: list[str] = []
        # The snapshot of the last displayed frame, for a tab change.
        self._last_snapshot = None
        # Last values pushed for two widgets whose state changes far less often
        # than once per frame. See _update_browse_label / _update_frame_info.
        self._browse_enabled: bool | None = None
        self._frame_info_height: int | None = None
        self._num_channels: int = _DEFAULT_NUM_CHANNELS
        self._channel_themes: list = []
        self._channel_colors: list = list(_CH_COLORS)
        self._peak_themes: list = []
        self._sect_theme = None
        self._toggle_themes: dict = {}  # 'active'|'waiting'|'idle' → dpg theme
        # Stale-frame watchdog deadline (monotonic seconds), or None when
        # disarmed. See _schedule_status_timeout.
        self._status_deadline: float | None = None
        # Why the device was lost (stream fault or failed start); shown on the
        # Device card until a device connects again.
        self._device_fault: str | None = None
        # The "waiting" text on the Device card while the stream waits for a
        # lost scope; None when not shown.
        self._waiting_text: str | None = None
        self.found_sensors: list = []
        self._autoscale_pending: bool = False  # True → autoscale on next frame
        self._was_streaming_before_config: bool = False  # stream state when config opened
        self._monitor: rev80.MonitorController | None = None
        self._session_browser_sessions: list = []
        self._sb_session_sel_ids: list = []   # selectable item IDs for single-select
        self._sb_burst_sel_ids:   list = []
        self._session_browser_rows: list = []
        self._session_browser_burst_list: list = []
        self._session_browser_selected_capture: int | None = None
        self._session_browser_selected_burst: str | None = None
        self._session_browser_selected_session_dir = None
        self._current_session_h5: 'Path | None' = None
        self._current_session_id: str = ''
        self._current_session_entry: dict = {}
        self._browse_context: dict = {}  # {type, burst_id, trigger_type, trigger_ts, session_*, ...}

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
                "lost": _c("RED"),
            }
            dpg.configure_item(ui.DEVICE_STATUS_RECT, fill=colors.get(state, _c("RED")))
        if dpg.does_item_exist(ui.CONN_STATUS_TEXT):
            labels = {
                "connected": "Connected",
                "file_loaded": "File Loaded",
                "disconnected": "Not Connected",
                "lost": "Device lost",
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
        """Re-arm the stale-frame watchdog: set a deadline of 2 frame periods.

        _poll_new_frames checks the deadline on the render thread at each tick.
        Do not use a timer thread: dearpygui calls must stay on the render thread.
        """
        self._status_deadline = (time.monotonic()
                                 + 2.0 * self.collector.config.acquisition_period)

    def _check_status_timeout(self):
        """Flip the indicator to 'Waiting' when frames have stopped arriving."""
        if self._status_deadline is None:
            return
        if time.monotonic() < self._status_deadline:
            return
        self._status_deadline = None
        if self.collector.is_streaming:
            self._set_stream_status("waiting")

    # ------------------------------------------------------------------
    # Tachometer tab
    # ------------------------------------------------------------------

    def _tach_unit(self) -> str:
        """The configured rate unit, resolved from its display label."""
        label = dpg.get_value(ui.TACH_ROTATION_UNIT) if dpg.does_item_exist(ui.TACH_ROTATION_UNIT) else None
        for unit, lbl in ROTATION_UNIT_LABELS.items():
            if lbl == label:
                return unit
        return self.collector.config.rotation_unit or DEFAULT_ROTATION_UNIT

    def format_rate(self, rpm) -> str:
        """A shaft rate with its unit, always. Never a bare number.

        30 is a plausible RPM, a plausible Hz and a plausible rad/s, and they
        differ by factors of 60 and 6.28.
        """
        unit = self.collector.config.rotation_unit or DEFAULT_ROTATION_UNIT
        val = rotation_from_rpm(rpm, unit)
        if val is None:
            return f"--  {ROTATION_UNIT_LABELS.get(unit, unit)}"
        return f"{val:,.1f} {ROTATION_UNIT_LABELS.get(unit, unit)}"

    def _populate_tach_tab(self):
        """Push the collector's tach state into the tab's widgets.

        Call it after a device config is applied, so the tab shows the restored
        values, not its construction defaults.
        """
        self._refresh_tach_channel_items()
        tach_channels = self.collector.config.tach_channels
        s = (self.collector.tach_settings_for(tach_channels[0]) if tach_channels
             else rev80_tach.TachSettings())
        for tag, val in (
            (ui.TACH_POLARITY, s.polarity),
            (ui.TACH_THRESH_MODE, s.threshold_mode),
            (ui.TACH_THRESH_MV, s.threshold_mv),
            (ui.TACH_MIN_AMPL_MV, s.min_amplitude_mv),
            (ui.TACH_REFLECTOR_MM, s.reflector_size_mm),
            (ui.TACH_PPR, s.pulses_per_rev),
        ):
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, val)
        unit = self.collector.config.rotation_unit or DEFAULT_ROTATION_UNIT
        if dpg.does_item_exist(ui.TACH_ROTATION_UNIT):
            dpg.set_value(ui.TACH_ROTATION_UNIT,
                          ROTATION_UNIT_LABELS.get(unit, unit))
        if dpg.does_item_exist(ui.TACH_THRESH_MV):
            dpg.configure_item(ui.TACH_THRESH_MV,
                               enabled=(s.threshold_mode == 'fixed'))

    def _refresh_tach_channel_items(self):
        """Repopulate the channel combo from what the device actually offers."""
        if not dpg.does_item_exist(ui.TACH_CHANNEL):
            return
        names = ["(none)"] + [
            f"{ch}: {self.collector.config.name_for(ch)}"
            for ch in range(self._num_channels)
        ]
        dpg.configure_item(ui.TACH_CHANNEL, items=names)
        current = self.collector.config.tach_channels
        sel = next((n for n in names[1:] if current and n.startswith(f"{current[0]}:")),
                   "(none)")
        dpg.set_value(ui.TACH_CHANNEL, sel)

    def _on_tach_channel_change(self):
        """Claim or release a channel for the tachometer role (see apply_tach_claim)."""
        val = dpg.get_value(ui.TACH_CHANNEL) or "(none)"
        ch = None if val == "(none)" else int(val.split(":", 1)[0])
        before = list(self.collector.config.enabled_channels)
        self._tach_implicit_enable = apply_tach_claim(
            self.collector, ch, self._tach_implicit_enable,
            self._tach_settings_from_ui() if ch is not None else None)
        changed = before != self.collector.config.enabled_channels

        # The stream has a fixed channel list: it does not sample a channel
        # that is enabled while it runs. Restart it, or the tab shows an empty
        # plot that looks like a dead sensor.
        if changed and self.collector.is_streaming:
            self._stop_stream()
            self._start_stream()
        elif ch is not None and not self.collector.is_streaming \
                and self.collector.stream is not None:
            # Claiming a channel is a request to see it. Start automatically
            # so there is a waveform to adjust the threshold against.
            self._start_stream()
        self.collector.init_trend_channels()
        self._rebuild_device_channel_rows()
        self._update_results_section_visibility()

    def _tach_settings_from_ui(self) -> 'rev80_tach.TachSettings':
        def _g(tag, default):
            return dpg.get_value(tag) if dpg.does_item_exist(tag) else default
        return rev80_tach.TachSettings(
            pulses_per_rev=max(1, int(_g(ui.TACH_PPR, 1))),
            polarity=str(_g(ui.TACH_POLARITY, 'rising')),
            threshold_mode=str(_g(ui.TACH_THRESH_MODE, 'adaptive')),
            threshold_mv=float(_g(ui.TACH_THRESH_MV, 2500.0)),
            min_amplitude_mv=float(_g(ui.TACH_MIN_AMPL_MV,
                                      rev80_tach.MIN_PULSE_AMPLITUDE_MV)),
            reflector_size_mm=float(_g(ui.TACH_REFLECTOR_MM, 0.0)),
        )

    def _on_tach_settings_change(self):
        mode = dpg.get_value(ui.TACH_THRESH_MODE) if dpg.does_item_exist(ui.TACH_THRESH_MODE) else 'adaptive'
        if dpg.does_item_exist(ui.TACH_THRESH_MV):
            dpg.configure_item(ui.TACH_THRESH_MV, enabled=(mode == 'fixed'))
        self.collector.config.rotation_unit = self._tach_unit()
        for ch in self.collector.config.tach_channels:
            self.collector.set_tach_settings(ch, self._tach_settings_from_ui())

    def _update_tach_tab(self):
        """Live waveform, edges and readouts while the tab is open.

        Returns at once when the config dialog is not shown. A modal does not
        stop the render loop, so without this check the plot updates each frame.
        """
        if not dpg.does_item_exist(ui.TACH_PLOT):
            return
        if not dpg.is_item_shown(ui.DLG_CONFIG):
            return

        # Slowest measurable shaft, from the block length and the configured
        # pulses/rev. Information only: an operator must be able to set the
        # tach up against a machine that is not running.
        t_block = 1.0 / max(self.collector.config.binsize, 1e-9)
        ppr = max(1, int(self._tach_settings_from_ui().pulses_per_rev))
        floor_rpm = rev80_tach.slowest_rpm_for(t_block, ppr)
        if dpg.does_item_exist(ui.TACH_FLOOR):
            dpg.set_value(
                ui.TACH_FLOOR,
                f"{icons.IC['warning']}  Below {self.format_rate(floor_rpm)} "
                f"reads as stopped (block {t_block:.2f} s)")

        if dpg.does_item_exist(ui.TACH_STREAM_BTN):
            dpg.configure_item(
                ui.TACH_STREAM_BTN,
                label="Stop" if self.collector.is_streaming else "Start",
                enabled=self.collector.stream is not None)

        tach_channels = self.collector.config.tach_channels
        if not tach_channels:
            for tag in (ui.TACH_PLOT_WAVE, ui.TACH_PLOT_THRESH, ui.TACH_PLOT_EDGES):
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, [[], []])
            dpg.set_value(ui.TACH_READOUT, "--")
            dpg.set_value(ui.TACH_QUALITY, "No tachometer channel selected.")
            if dpg.does_item_exist(ui.TACH_WARN_BOX):
                dpg.configure_item(ui.TACH_WARN_BOX, show=False)
            return

        ch = tach_channels[0]
        sample = self.collector.current_frame().get(ch)
        if sample is None or sample.data.size <= 1:
            dpg.set_value(ui.TACH_QUALITY, "Waiting for data...")
            return

        res = self.collector.tach_for(ch, sample)

        # Two independent cautions; each one opens the box. The floor caution:
        # the block is too short for this shaft speed. The sampling caution:
        # the pulse rate is too high for the raw rate (only with ppr above 1).
        show_floor = res.quality in (rev80_tach.QUALITY_TOO_FEW_EDGES,
                                     rev80_tach.QUALITY_NO_SIGNAL)
        samples_per_pulse = (
            float(sample.samplerate) * 60.0 / (res.rpm * ppr)
            if res.rpm else None)
        show_ppr = (samples_per_pulse is not None
                    and samples_per_pulse < rev80_tach.MIN_SAMPLES_PER_PULSE)
        if dpg.does_item_exist(ui.TACH_PPR_WARN):
            if show_ppr:
                dpg.set_value(
                    ui.TACH_PPR_WARN,
                    f"{icons.IC['warning']}  {samples_per_pulse:.0f} samples "
                    f"per pulse at {ppr}/rev -- below "
                    f"{rev80_tach.MIN_SAMPLES_PER_PULSE}, accuracy degrades to "
                    f"~0.8%. Use fewer pulses per revolution.")
            dpg.configure_item(ui.TACH_PPR_WARN, show=show_ppr)
        if dpg.does_item_exist(ui.TACH_FLOOR):
            dpg.configure_item(ui.TACH_FLOOR, show=show_floor)
        if dpg.does_item_exist(ui.TACH_WARN_BOX):
            # Only a warning when it is actually biting. The floor is normal
            # information at configure time, not a fault -- an operator must be
            # able to set the tach up against a machine that is not running.
            dpg.configure_item(ui.TACH_WARN_BOX,
                               show=show_floor or show_ppr,
                               height=34 if show_floor != show_ppr else 56)
        fs = float(sample.samplerate)
        x = np.asarray(sample.data, dtype=np.float64)
        t_axis = np.arange(x.size) / fs

        # Align the first detected pulse to t=0, so that frames overlay and the
        # threshold position is easy to see. A free trace moves by up to one
        # period between frames.
        edges = np.asarray(res.edge_times_s, dtype=np.float64)
        t0 = float(edges[0]) if edges.size else 0.0
        t_axis = t_axis - t0
        edges_shifted = edges - t0

        dpg.set_value(ui.TACH_PLOT_WAVE, [t_axis.tolist(), x.tolist()])

        span = float(x.max() - x.min())
        settings = self.collector.tach_settings_for(ch)
        if settings.threshold_mode == 'fixed':
            level = settings.threshold_mv
        else:
            level = (float(x.max()) + float(x.min())) / 2.0
        dpg.set_value(ui.TACH_PLOT_THRESH,
                      [[float(t_axis[0]), float(t_axis[-1])], [level, level]])
        dpg.set_value(ui.TACH_PLOT_EDGES,
                      [edges_shifted.tolist(), [level] * edges_shifted.size])

        # Two periods before and after the pulses. Use the pulse period, not
        # the shaft period: at 6 pulses/rev the shaft period makes the window
        # 6 times too wide.
        if res.shaft_hz:
            period = 1.0 / (res.shaft_hz * max(1, res.pulses_per_rev))
            dpg.set_axis_limits(ui.TACH_PLOT_X, -2.0 * period,
                                (res.n_edges + 2) * period)
        else:
            dpg.set_axis_limits_auto(ui.TACH_PLOT_X)
        # set_axis_limits_auto only clears a manual range -- it does not
        # refit. fit_axis_data is what actually rescales to the current data.
        dpg.set_axis_limits_auto(ui.TACH_PLOT_Y)
        dpg.fit_axis_data(ui.TACH_PLOT_Y)

        dpg.set_value(ui.TACH_READOUT, self.format_rate(res.rpm))
        duty_txt = f"{res.duty_cycle * 100:.1f}%" if res.duty_cycle else "--"
        dpg.set_value(
            ui.TACH_QUALITY,
            f"{res.quality}   {res.n_edges} edges   duty {duty_txt}   "
            f"span {span:.0f} mV")

    def _update_tach_cards(self) -> None:
        """Refresh every tachometer channel's result card.

        Runs on the main render path, also when the config dialog is closed.
        It reads the same TachResult as _update_tach_tab, so the two agree.
        """
        frame = self.collector.current_frame()
        for ch in self.collector.config.tach_channels:
            sample = frame.get(ch)
            if sample is None:
                continue
            self._update_tach_result_card(ch, self.collector.tach_for(ch, sample))

    def _update_tach_result_card(self, ch: int, res) -> None:
        """Put the shaft rate on one tachometer channel's result card."""
        if dpg.does_item_exist(ui.ch_tach_rate(ch)):
            dpg.set_value(ui.ch_tach_rate(ch), self.format_rate(res.rpm))
        if dpg.does_item_exist(ui.ch_tach_detail(ch)):
            duty = f"{res.duty_cycle * 100:.1f}%" if res.duty_cycle else "--"
            dpg.set_value(ui.ch_tach_detail(ch),
                          f"{res.quality}   {res.n_edges} edges   duty {duty}")

    def _update_browse_label(self):
        """Refresh the frame-browser label, nav buttons, and trend cursor line."""
        if not dpg.does_item_exist(ui.ACQ_BROWSE_LABEL):
            return
        cache = self.collector.data["frame_cache"]
        n = len(cache)
        cursor = self.collector._cache_cursor
        label = f"Frame {n - cursor} / {n}" if n else "No frames"
        dpg.set_value(ui.ACQ_BROWSE_LABEL, label)
        # configure_item only on an actual transition. This is four calls per
        # frame pushing a value that changes twice in a session -- once when
        # streaming starts and once when it stops.
        can_browse = (not self.collector.is_streaming) and n > 1
        if can_browse != self._browse_enabled:
            self._browse_enabled = can_browse
            for tag in [ui.ACQ_BROWSE_FIRST, ui.ACQ_BROWSE_PREV,
                        ui.ACQ_BROWSE_NEXT, ui.ACQ_BROWSE_LAST]:
                if dpg.does_item_exist(tag):
                    dpg.configure_item(tag, enabled=can_browse)

    def _update_frame_info(self) -> None:
        """Populate the Frame info card from the currently displayed frame + browse context."""
        if not dpg.does_item_exist(ui.FRAME_INFO_SECTION):
            return
        cache  = self.collector.data["frame_cache"]
        cursor = self.collector._cache_cursor
        if not cache:
            dpg.configure_item(ui.FRAME_INFO_SECTION, show=False)
            return

        frame  = cache[-(min(cursor, len(cache) - 1) + 1)]
        sample = next((v for k, v in frame.items() if isinstance(k, int)), None)
        if sample is None:
            dpg.configure_item(ui.FRAME_INFO_SECTION, show=False)
            return

        # ── Frame section (always visible) ──────────────────────────────────
        try:
            ts_str = sample._timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        except Exception:
            ts_str = str(getattr(sample, 'timestamp', '—'))
        dpg.set_value(ui.FRAME_INFO_TIMESTAMP, f"Capture Time:\n  {ts_str}")

        sr = sample.samplerate
        ns = sample.blocksize
        dpg.set_value(ui.FRAME_INFO_BLOCKSIZE,  f"Block size: {ns:,} samples")
        dpg.set_value(ui.FRAME_INFO_SAMPLERATE, f"Sample rate: {sr:,} Hz")

        ctx         = self._browse_context
        kind        = ctx.get('type', 'live')
        is_burst    = kind == 'burst'
        has_session = kind in ('burst', 'session')

        # Frame Time (burst only)
        if is_burst:
            rt   = float(sample.rel_time)
            sign = "-" if rt < 0 else "+"
            m, s = divmod(abs(rt), 60)
            h, m = divmod(int(m), 60)
            rel_str = (f"{sign}{h}:{m:02d}:{s:05.2f}" if h else f"{sign}{int(m):02d}:{s:05.2f}")
            dpg.set_value(ui.FRAME_INFO_REL_TIME, f"Frame Time: {rel_str}")
        dpg.configure_item(ui.FRAME_INFO_REL_TIME, show=is_burst)

        # ── Burst section ────────────────────────────────────────────────────
        for tag in (ui.FRAME_INFO_BURST_HEADER, ui.FRAME_INFO_BURST_SEP,
                    ui.FRAME_INFO_TRIGGER_TS, ui.FRAME_INFO_TRIGGER_TYPE):
            dpg.configure_item(tag, show=is_burst)
        if is_burst:
            dpg.set_value(ui.FRAME_INFO_TRIGGER_TS,
                          f"Burst Time:\n  {ctx.get('trigger_ts', '—')}")
            dpg.set_value(ui.FRAME_INFO_TRIGGER_TYPE,
                          f"Trigger type: {ctx.get('trigger_type', '—')}")

        # ── Session section ──────────────────────────────────────────────────
        for tag in (ui.FRAME_INFO_SESSION_HEADER, ui.FRAME_INFO_SESSION_SEP,
                    ui.FRAME_INFO_SESSION_START, ui.FRAME_INFO_SESSION_END,
                    ui.FRAME_INFO_N_CAPTURES, ui.FRAME_INFO_N_BURSTS,
                    ui.FRAME_INFO_INTERVAL):
            dpg.configure_item(tag, show=has_session)
        if has_session:
            dpg.set_value(ui.FRAME_INFO_SESSION_START,
                          f"Start Time:\n  {ctx.get('start_time', '—')}")
            dpg.set_value(ui.FRAME_INFO_SESSION_END,
                          f"End Time:\n  {ctx.get('end_time', '—')}")
            dpg.set_value(ui.FRAME_INFO_N_CAPTURES,
                          f"Captures: {ctx.get('n_captures', '—')}")
            dpg.set_value(ui.FRAME_INFO_N_BURSTS,
                          f"Bursts: {ctx.get('n_bursts', '—')}")
            iv = ctx.get('interval_s', 0.0)
            iv_str = f"{float(iv):.1f} s" if iv else '—'
            dpg.set_value(ui.FRAME_INFO_INTERVAL, f"Capture interval: {iv_str}")

        # ── Resize card to fit visible rows ──────────────────────────────────
        # Each 2-line item counts as 2 × _CARD_LINE_H; section headers = 1 row.
        _SEP_H   = 12  # add_separator pixel height
        always_h = 4 * _CARD_LINE_H          # Capture Time (2) + Block size + Sample rate
        burst_h  = (1 + 1 + 2 + 1) * _CARD_LINE_H + _SEP_H if is_burst    else 0
        # Frame Time + header + Burst Time (2) + Trigger type + sep
        sess_h   = (1 + 2 + 2 + 1 + 1 + 1) * _CARD_LINE_H + _SEP_H if has_session else 0
        # header + Start Time (2) + End Time (2) + Captures + Bursts + Interval + sep
        card_h = _CARD_BASE_H + always_h + burst_h + sess_h
        # Height only on change: a configure_item(height=) forces a dearpygui
        # relayout of the card, and this one is identical frame after frame.
        if card_h != self._frame_info_height:
            self._frame_info_height = card_h
            dpg.configure_item(ui.FRAME_INFO_SECTION, height=card_h, show=True)
        else:
            dpg.configure_item(ui.FRAME_INFO_SECTION, show=True)

    def _update_results_section_visibility(self):
        """Show the shaft-speed card of each enabled tachometer channel.

        A vibration channel's results are on the cards of each spectrum
        chart (gui_charts.py). A tachometer produces no ChannelResult, so
        its card shows the shaft rate only.
        """
        tach = set(self.collector.config.tach_channels)
        for ch in range(_MAX_CHANNELS):
            tag = ui.ch_result_section(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=(ch in tach))

    def _display_frame(self):
        """Process the current frame via collector and update all GUI plots."""
        with _profile.timed(_profile.GUI_DISPLAY):
            self._display_frame_inner()

    def _display_frame_inner(self):
        if self.collector.is_streaming:
            self._set_stream_status("active")
            self._schedule_status_timeout()

        # One snapshot for every view of this tick. advance_frame() adds the
        # trend point once for each new live frame. The record results go to
        # the monitor and are never averaged; the display uses the
        # configured averaging.
        snap = self.collector.snapshot()
        self._last_snapshot = snap
        self.collector.advance_frame(snap)
        record = self.collector.results_for(snap)

        n_overflow = 0
        for result in record:
            tag = ui.ch_overflow_warning(result.channel)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=result.overflow)
                if result.overflow:
                    n_overflow += 1
        self._charts.render(snap)

        if dpg.does_item_exist(ui.CH_WARNINGS_SECTION):
            dpg.configure_item(
                ui.CH_WARNINGS_SECTION,
                show=bool(n_overflow),
                height=_CARD_BASE_H + n_overflow * _CARD_LINE_H,
            )

        if self._monitor_accepts_frames():
            self._monitor.on_results(
                rev80.FrameViews(self.collector, snap, record), snap.history)

        self._update_browse_label()
        self._update_frame_info()
        self._charts.ensure_legends()
        if self._autoscale_pending:
            self._autoscale_plots()
            self._autoscale_pending = False

    def _monitor_accepts_frames(self) -> bool:
        """True when a recording runs and the frame comes from the live stream.

        A frame from a loaded file, or a frame shown while browsing the
        cache, is not a live measurement. It must not go into the session.
        """
        return bool(
            self._monitor is not None and self._monitor.is_recording
            and self.collector.is_streaming
        )

    def _file_access_locked(self) -> bool:
        """True while a recording runs.

        Then file load, session browse and clear-cache are not permitted.
        A load stops the stream, and the session browser can open the
        session file that the writer uses.
        """
        return bool(self._monitor is not None and self._monitor.is_recording)

    def _refuse_while_recording(self, action: str) -> bool:
        """Log and return True if a recording prevents this action."""
        if not self._file_access_locked():
            return False
        log.info("%s is not available while a monitor recording runs. "
                 "Stop the recording first.", action)
        return True

    #: Controls that are disabled while a monitor recording runs.
    _RECORDING_LOCKED_CONTROLS = (
        ui.BTN_DEVICE_SETUP, ui.BTN_CHANNELS_SETUP, ui.BTN_SPECTRUM_SETUP,
        ui.BTN_SENSOR_SETUP, ui.BTN_MONITOR_SETUP,
        ui.FILE_LOAD, ui.BTN_MONITOR_BROWSE, ui.ACQ_CLEAR_CACHE,
    )

    #: Tooltip on a locked control while a recording runs.
    _LOCKED_TIP_TEXT = "Stop the recording to change this."

    #: Widget types that get muted colours when disabled. Without a theme
    #: component for the disabled state, dearpygui draws a disabled button
    #: like an enabled one, and a click on it does nothing visible.
    _DISABLED_THEME_TYPES = (
        dpg.mvButton, dpg.mvCombo, dpg.mvCheckbox, dpg.mvInputText,
        dpg.mvInputInt, dpg.mvInputFloat, dpg.mvSliderInt, dpg.mvSliderFloat,
    )

    def _create_disabled_theme(self) -> int:
        """Global theme: muted colours for every disabled control."""
        muted = _c("MUTED")
        flat = _c("SURFACE")
        with dpg.theme() as theme:
            for item_type in self._DISABLED_THEME_TYPES:
                with dpg.theme_component(item_type, enabled_state=False):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, muted,
                                        category=dpg.mvThemeCat_Core)
                    for col in (dpg.mvThemeCol_Button, dpg.mvThemeCol_ButtonHovered,
                                dpg.mvThemeCol_ButtonActive, dpg.mvThemeCol_FrameBg,
                                dpg.mvThemeCol_FrameBgHovered,
                                dpg.mvThemeCol_FrameBgActive):
                        dpg.add_theme_color(col, flat, category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_CheckMark, muted,
                                        category=dpg.mvThemeCat_Core)
                    dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, muted,
                                        category=dpg.mvThemeCat_Core)
        return theme

    def _create_locked_tips(self) -> None:
        """One hidden tooltip on each lockable control; the lock shows it."""
        for tag in self._RECORDING_LOCKED_CONTROLS:
            if not dpg.does_item_exist(tag):
                continue
            with dpg.tooltip(parent=tag, tag=ui.locked_tip(tag), show=False):
                dpg.add_text(self._LOCKED_TIP_TEXT)

    def _set_recording_lock(self, locked: bool) -> None:
        """Disable (or enable again) the controls that a recording locks."""
        for tag in self._RECORDING_LOCKED_CONTROLS:
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=not locked)
            tip = ui.locked_tip(tag)
            if dpg.does_item_exist(tip):
                dpg.configure_item(tip, show=locked)

    def _poll_new_frames(self):
        """Check for new data from the collector and display the current frame.

        Called once per DPG render tick from the manual render loop.
        If multiple frames arrived since the last tick, only the most
        recent is displayed — earlier frames remain in frame_cache for browsing.
        """
        # Ahead of the new-frame check: with acquisition stopped no frames
        # arrive, and the Tachometer tab still has to show its Start button,
        # the measurable-speed floor, and whatever frame is currently loaded.
        # It early-returns when its dialog is not on screen.
        self._update_tach_tab()
        self._check_status_timeout()
        pending, self._pending_collector = self._pending_collector, None
        if pending is not None:
            # A collector built on a worker thread; swap it on this thread.
            self._replace_collector(pending)
        self._check_stream_fault()
        if not self.collector.new_frame_event.is_set():
            return
        self.collector.new_frame_event.clear()
        self._display_frame()
        self._update_tach_cards()
        if self._monitor is not None and self._monitor.is_recording:
            self._update_monitor_card()

    def _check_stream_fault(self):
        """Show a stream that stopped by itself: the scope was lost and did not
        come back. Render thread; the acquisition thread never touches a widget."""
        lost_s = self.collector.device_lost_for_s
        if lost_s is not None:
            self._show_device_waiting(lost_s)
            return
        if self._waiting_text is not None:
            # The scope came back: show the device as connected again.
            self._waiting_text = None
            self._update_connection_summary()
        fault = self.collector.stream_fault
        if fault is None or self.collector.is_streaming:
            return
        # The stream abandoned the lost handle: the disconnect makes no driver call.
        self.collector.disconnect_sensor()
        self._on_device_lost(fault)

    def _show_device_waiting(self, lost_s: float):
        """'Device lost — waiting mm:ss' on the Device card; changes once a second."""
        minutes, seconds = divmod(int(lost_s), 60)
        text = f"Device lost — waiting {minutes:02d}:{seconds:02d}"
        if text == self._waiting_text:
            return
        self._waiting_text = text
        self._set_device_status("lost")
        if dpg.does_item_exist(ui.CONN_STATUS_TEXT):
            dpg.set_value(ui.CONN_STATUS_TEXT, text)

    def _on_device_lost(self, reason: str):
        """Stop the stream display and show `reason` on the Device card."""
        log.error(f"Device lost: {reason}")
        if self._monitor is not None and self._monitor.is_recording:
            log.warning("The recording continues, but it gets no frames until a device connects")
        self._device_fault = reason
        self._status_deadline = None
        self._set_stream_status("idle")
        self._update_connection_summary()
        self._update_browse_label()

    def _redraw(self, sender=None, data=None):
        if not self.collector.is_streaming:
            self.collector.reprocess_last_block()

    def _on_chart_tab_change(self, sender=None, data=None):
        """Draw the chart of the new tab at once, from the frame on screen.

        Only the chart on screen is drawn on each frame, so the new tab
        would otherwise be empty until the next frame arrives.
        """
        snap = getattr(self, '_last_snapshot', None)
        cid = self._charts.selected_chart_id()
        if snap is not None and cid is not None:
            self._charts.render(snap, force=cid)

    @staticmethod
    def _tooltip(target, text: str, wrap: int = 320):
        """Attach a wrapped hover tooltip to an already-created widget."""
        with dpg.tooltip(parent=target):
            dpg.add_text(text, wrap=wrap)

    def _on_peak_threshold_change(self, sender=None, data=None):
        """Push the significance threshold into the config and reprocess.

        This is not a display-only setting: it changes which lines are
        selected, so the frame goes through the views again.
        """
        value = float(dpg.get_value(ui.FFT_PEAK_THRESHOLD_DB))
        self.collector.config.peak_threshold_db = max(0.0, value)
        self._redraw()

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
            self._device_fault = None
            self._set_device_status("connected")
        elif self._device_fault:
            self._set_device_status("lost")
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
            elif self._device_fault:
                dpg.add_text(self._device_fault, parent=ui.DEVICE_INFO_GROUP,
                             color=_c("RED"), wrap=0)
                dpg.add_text("Connect the scope again: Setup", parent=ui.DEVICE_INFO_GROUP,
                             color=dim)
            elif has_data:
                n_frames = len(self.collector.data["frame_cache"])
                n_ch = len(self.collector.config.enabled_channels)
                dpg.add_text("File loaded", parent=ui.DEVICE_INFO_GROUP, color=dim)
                dpg.add_text(f"  {n_frames} frames, {n_ch} channels", parent=ui.DEVICE_INFO_GROUP, color=dim)
            # Resize Device card
            if sensor is not None:
                n_info = 4
            elif self._device_fault:
                n_info = 3
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
        # Label F_max, not fs/2. The band above F_max is a guard band and is
        # not displayed: alias rejection is -21.8 dB for the frequency that
        # folds onto F_max, and about 0 dB at fs/2. Evidence: CONTRIBUTING.md,
        # "E11. Display rate, block size and line count".
        fmax_lbl = f"F_max {cfg.maxfreq:.0f} Hz"
        # Report the resolution actually delivered, not the one requested.
        info = (
            f"{cfg.maxfreq:.0f} Hz max  |  {cfg.binsize_actual:.2f} Hz/bin\n"
            f"{cfg.n_fft_bins} lines  |  {fs_ks:.1f} kS/s\n"
            f"Acq: {t_col:.3f} s  |  {cfg.fft_window}\n"
            f"{hp}  |  {fmax_lbl}"
        )
        if dpg.does_item_exist(ui.SPECTRUM_INFO_TEXT):
            dpg.set_value(ui.SPECTRUM_INFO_TEXT, info)

        # Streaming-rate degraded warning — only relevant while a real hardware
        # stream is active; SimulatedSensor and "no device" cases have no
        # concept of this and stay hidden.
        if dpg.does_item_exist(ui.SPECTRUM_DEGRADED_WARNING):
            degraded = bool(self.collector.stream_degraded)
            if degraded:
                stream = self.collector.stream
                eff = getattr(stream, 'effective_samplerate', None)
                dpg.set_value(ui.SPECTRUM_DEGRADED_WARNING, degraded_rate_text(eff, cfg))
            dpg.configure_item(ui.SPECTRUM_DEGRADED_WARNING, show=degraded)

    def _update_acq_derived(self):
        """Refresh derived display fields in the acquisition dialog based on current widget values."""
        mf_str = dpg.get_value(ui.ACQ_DLG_MAXFREQ) if dpg.does_item_exist(ui.ACQ_DLG_MAXFREQ) else ""
        bs_str = dpg.get_value(ui.ACQ_DLG_BINSIZE) if dpg.does_item_exist(ui.ACQ_DLG_BINSIZE) else ""
        try:
            maxfreq = rev80.MAXFREQ_PRESETS[_MAXFREQ_LABELS.index(mf_str)]
        except (ValueError, IndexError):
            maxfreq = self.collector.config.maxfreq
        try:
            binsize = rev80.BINSIZE_PRESETS[_BINSIZE_LABELS.index(bs_str)]
        except (ValueError, IndexError):
            binsize = self.collector.config.binsize
        derived    = derive_acquisition_preview(maxfreq, binsize)
        samplerate = derived['samplerate']
        n_fft_bins = derived['n_fft_bins']
        acq_time   = derived['acq_time']
        mem_bytes  = derived['mem_bytes']

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

        # Averaging window, in seconds: how long the machine must stay steady.
        # A frame is 1/binsize seconds, rounded up to a whole sample (see
        # AcquisitionSettings.blocksize), so the window is about N/binsize.
        if dpg.does_item_exist(ui.ACQ_DLG_AVG_TIME):
            if dpg.get_value(ui.ACQ_DLG_AVG_ENABLED):
                n_req = max(1, int(dpg.get_value(ui.ACQ_DLG_AVG_N)))
                n_eff = min(n_req, cache_frames)
                capped = '' if n_eff == n_req else f'  (capped by {cache_frames}-frame cache)'
                dpg.set_value(ui.ACQ_DLG_AVG_TIME,
                              f"{n_eff} x {acq_time:.3g} s = {n_eff * acq_time:.3g} s{capped}")
            else:
                dpg.set_value(ui.ACQ_DLG_AVG_TIME, "off")

        if dpg.does_item_exist(ui.ACQ_DLG_SAMPLERATE):
            dpg.set_value(ui.ACQ_DLG_SAMPLERATE, f"{samplerate / 1000:.3f} kS/s")
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
            # A recording continues without a stream, but gets no frames.
            # The Acquisition button, the Tachometer button and Ctrl+K come
            # here.
            if self._refuse_while_recording("Stream stop"):
                return
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        if self.collector.stream is None:
            log.warning("Connect a device before starting acquisition")
            return
        self._set_stream_status("waiting")
        self._autoscale_pending = True
        self._browse_context = {'type': 'live'}
        self.collector.clear_trend()  # reset rel_time so trend starts at t=0
        self.collector.start_stream()
        if self.collector.stream is None:
            # The start failed and the collector disconnected the device.
            self._on_device_lost(self.collector.start_error or "the stream did not start")
            return
        self._update_browse_label()

    def _stop_stream(self):
        if self.collector.stream is None:
            return
        self.collector.stop_stream()
        self._update_browse_label()
        self._status_deadline = None
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
        """Scale the axes of every chart to sensible initial bounds.

        Axes set with set_axis_limits (waveform X, trend X and Y) are
        released one frame later, so the user can pan and zoom. Axes scaled
        with fit_axis_data are one-shot and stay free.
        """
        self._autoscale_locked = self._charts.autoscale(
            self._TIME_WINDOW_OFFSET_MS, self._TIME_WINDOW_RANGE_MS)
        dpg.set_frame_callback(
            dpg.get_frame_count() + 1,
            callback=self._unlock_autoscaled_axes,
        )

    def _unlock_autoscaled_axes(self):
        """Release the axis locks that _autoscale_plots set, one frame later."""
        for ax in self._autoscale_locked:
            if dpg.does_item_exist(ax):
                dpg.set_axis_limits_auto(ax)
        self._autoscale_locked = []

    def _clear_cache(self, sender=None, data=None):
        """Wipe the frame cache and trend data, refresh the browse label."""
        if self._refuse_while_recording("Clear cache"):
            return
        self.collector.reset_data_store()
        self._update_browse_label()
        self._charts.clear()

    @staticmethod
    def _native_file_dialog(save: bool = False) -> str:
        """Open the platform-native file dialog; returns path string or ''."""
        from plyer import filechooser

        filters = [f"*{rev80.EXT}"]
        path = str(Path(rev80.SAVEDIR).resolve())
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
            p = p.with_suffix(rev80.EXT)
        if dpg.does_item_exist(ui.ACQ_NOTES):
            self.collector.notes = dpg.get_value(ui.ACQ_NOTES)
        self.collector.save_data(p)

    def _on_load_click(self, sender=None, data=None):
        # The Ctrl+O shortcut also comes here, so this check applies to both.
        if self._refuse_while_recording("File load"):
            return
        path_str = self._native_file_dialog(save=False)
        if not path_str:
            return
        self._on_load_file(Path(path_str))

    def _wire_session_sensors(self, collector: 'rev80.DataCollector | None' = None) -> None:
        """Register any unknown sensors from the loaded session/file and wire them to channels.

        Must be called after load_monitor_session() or load_data() so that
        _loaded_scope_sensors and _loaded_channel_sensor_configs are populated.
        `collector` defaults to the one on screen.
        """
        collector = collector if collector is not None else self.collector
        for sid, sensor_dict in collector._loaded_scope_sensors.items():
            if self.registry.find_by_id(sid) is None:
                try:
                    sensor = ScopeSensor.from_dict(sensor_dict)
                    self.registry.add(sensor)
                    log.info(f"Added sensor to registry from file: {sensor.name!r} ({sid})")
                except Exception as exc:
                    log.warning(f"_wire_session_sensors: could not add sensor {sid!r}: {exc}")
        for ch, sensor_cfg in collector._loaded_channel_sensor_configs.items():
            sid    = sensor_cfg.get("id")
            sensor = self.registry.find_by_id(sid) if sid else None
            collector.set_scope_sensor(ch, sensor)

    # ------------------------------------------------------------------
    # Data source: a new collector for each load and each connect
    # ------------------------------------------------------------------

    def _release_device(self) -> None:
        """Stop the stream and close the device of the collector on screen.

        Close it before another collector opens a device: a device left open
        makes the next open fail with PICO_NOT_FOUND.
        """
        if self.collector.is_streaming:
            self._stop_stream()
        if self.collector.sensor is not None:
            self.collector.disconnect_sensor()
            self._set_device_status("disconnected")

    def _replace_collector(self, new: 'rev80.DataCollector', setup=None) -> bool:
        """Put `new` on screen. The one place `self.collector` changes after __init__.

        A new collector for each load and connect, so no state of the old
        data source (speed reference, RPM trend, stage-1 caches, cache depth,
        cursor) can survive. Refused while a recording runs. Closes the old
        device, assigns, runs `setup()` if given, then calls
        `_on_data_source_changed()`. No GUI code may keep a reference to the
        old collector, its `data` dict or its cache.
        """
        if self._refuse_while_recording("A change of data source"):
            return False
        if new is not self.collector:
            self._release_device()
            if new.chart_set is None:
                new.chart_set = self.collector.chart_set
            self.collector = new
        try:
            if setup is not None:
                setup()
        finally:
            self._on_data_source_changed()
        return True

    def _load_into_new_collector(self, load, what: str) -> 'rev80.DataCollector | None':
        """Load a file into a new collector; None if the load fails or is empty.

        `load(collector)` reads the file. The collector on screen is not
        touched, so a refused or failed file leaves the screen unchanged.
        """
        new = rev80.DataCollector()
        try:
            load(new)
        except Exception as exc:
            log.error("%s: load failed: %s", what, exc)
            return None
        if not new.data["frame_cache"]:
            log.error("%s: no frames loaded; the display is unchanged", what)
            return None
        self._wire_session_sensors(new)
        return new

    def _on_data_source_changed(self) -> None:
        """Bring the widgets in line with the collector on screen, after a swap."""
        collector = self.collector
        if collector.sensor is not None:
            self._num_channels = collector.sensor.num_channels
        else:
            loaded: set[int] = set()
            for frame in collector.data["frame_cache"]:
                loaded.update(k for k in frame if isinstance(k, int))
            if loaded:
                self._num_channels = max(loaded) + 1
        # A tab change draws from the last snapshot; one of the old
        # collector must not reach the new one.
        self._last_snapshot = None
        self._charts.rebuild()
        self._update_results_section_visibility()
        self._update_connection_summary()
        self._update_spectrum_info()
        self._update_browse_label()
        if dpg.does_item_exist(ui.ACQ_NOTES):
            dpg.set_value(ui.ACQ_NOTES, collector.notes)
        self._autoscale_pending = True
        collector.reprocess_last_block()

    def _build_live_collector(self, sensor) -> 'rev80.DataCollector':
        """A new collector with the acquisition.yaml settings, connected to `sensor`."""
        acq_dict = _cfg.load_acquisition_config().get("acquisition", {})
        config = AcquisitionSettings.from_dict(acq_dict) if acq_dict else None
        new = rev80.DataCollector(config=config)
        new.connect_sensor(sensor)
        return new

    def _connect_device(self, sensor) -> bool:
        """Close the old device, then connect `sensor` in a new collector.

        Restores the device YAML (channels, siggen), the sensors from the
        registry and the tachometer settings. On failure the new device is
        closed and the indicator shows disconnected.
        """
        if self._refuse_while_recording("Device connect"):
            return False
        self._release_device()
        try:
            new = self._build_live_collector(sensor)
        except Exception as e:
            log.warning(f"Device connect failed: {e}")
            self._set_device_status("disconnected")
            return False

        def _setup():
            try:
                self._num_channels = sensor.num_channels
                self.collector.reset_channel_config(sensor.num_channels)
                device_cfg = _cfg.load_device_config(sensor.model_name, sensor.serial_number)
                self._restore_channel_assignments(device_cfg)
                self.collector.reconnect_stream()
                self._set_device_status("connected")
            except Exception as e:
                log.warning(f"Device connect failed: {e}")
                self.collector.disconnect_sensor()
                self._set_device_status("disconnected")

        return self._replace_collector(new, setup=_setup)

    def _on_load_file(self, path: Path) -> bool:
        """Load an h5 file into a new collector and put it on screen.

        Closes any device, so the file channels are the only ones active. A
        file that does not load leaves the screen unchanged.
        """
        if self._refuse_while_recording("File load"):
            return False
        new = self._load_into_new_collector(lambda c: c.load_data(path), path.name)
        if new is None:
            return False
        if not self._replace_collector(new):
            return False
        self._browse_context = {'type': 'file', 'name': path.stem}
        return True

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

        dpg.configure_item(
            ui.DLG_CONFIG,
            pos=((WINDOW_WIDTH - _DLG_CFG_W) // 2, (WINDOW_HEIGHT - _DLG_CFG_H) // 2),
        )
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
        """Background thread: find sensors, then update the device list.

        Does not disconnect the current sensor: from this thread that races
        the main thread and corrupts widget state. With a device connected, the
        scan is skipped (a PicoScope cannot be opened twice). Do not call
        _rebuild_device_channel_rows here: _on_device_connect_toggle calls it
        on the main thread, and a second call from this thread makes combos
        return stale values.
        """
        if self.collector.sensor is not None:
            # Device already connected — cannot re-scan while handle may be open.
            self.found_sensors = [self.collector.sensor]
        else:
            self.found_sensors = rev80.VibeSensor.find()
        self._repopulate_device_list()

    def _autoconnect(self):
        """Background startup thread: scan for PicoScopes and connect to the first one.

        Runs once after the viewport is shown. Follows the manual connect path
        of _on_device_connect_toggle. Does not start the stream. The slow steps
        (VibeSensor.find, connect_sensor, config load) are thread-safe; widget
        updates follow the same pattern as _discover_devices.
        """
        if rev80.PICOSCOPE_DRIVER_MISSING:
            log.debug("Autoconnect: PicoScope driver not available")
            return

        sensors = rev80.VibeSensor.find()
        self.found_sensors = sensors

        if not sensors:
            log.info("Autoconnect: no PicoScope found")
            self._update_connection_summary()
            return

        sensor = sensors[0]
        log.info(f"Autoconnect: found {sensor.model_name} (S/N {sensor.serial_number})")

        if self.collector.sensor is not None:
            log.info("Autoconnect: a device is already connected")
            return
        if not self._connect_device(sensor) or self.collector.sensor is None:
            log.warning("Autoconnect failed")
            return
        log.info(f"Autoconnect: connected to {sensor.model_name}")

        self._repopulate_device_list()
        self._rebuild_device_channel_rows()

    def _repopulate_device_list(self):
        """Rebuild the detected-device rows inside the Device Setup dialog."""
        if not dpg.does_item_exist(ui.DEVSETUP_DEVICE_LIST_GROUP):
            return
        dpg.delete_item(ui.DEVSETUP_DEVICE_LIST_GROUP, children_only=True)
        if not self.found_sensors:
            if rev80.PICOSCOPE_DRIVER_MISSING:
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
        self._refresh_tach_channel_items()
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
            is_tach = self.collector.config.role_for(ch) == 'tachometer'
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
                # The Tachometer tab owns a tachometer channel's Enable. If it
                # were switchable here, the shaft speed would stop with no
                # message, because tach_channels ignores disabled channels.
                _en = dpg.add_checkbox(
                    label="Enable",
                    tag=ui.scope_ch_enabled(ch),
                    default_value=is_enabled,
                    enabled=not is_tach,
                    callback=lambda s, d, c=ch: self._on_channel_enable_change(c),
                )
                if is_tach:
                    self._tooltip(
                        _en,
                        "Enabled because this input is claimed as the "
                        "tachometer. Release it in the Tachometer tab to "
                        "switch it off.")
                with dpg.drawlist(width=16, height=16):
                    dpg.draw_rectangle(pmin=(2, 2), pmax=(14, 14), fill=ch_color, color=(0, 0, 0, 0), rounding=2)
                dpg.add_text(ch_name, tag=ui.scope_ch_name_text(ch))
            # A channel claimed by the Tachometer tab is shown, not edited.
            # Its settings here are meaningless -- a pulse train has no sensor,
            # no engineering unit and no amplitude mode -- and a second control
            # able to set the role could disagree with the tab that owns it.
            if is_tach:
                _t = dpg.add_text(
                    f"    TACHOMETER  ({default_c}  {default_r})"
                    "   - configured in the Tachometer tab",
                    parent=ui.DEVSETUP_CHANNEL_GROUP, color=_c("MUTED"))
                self._tooltip(
                    _t,
                    "This input is claimed as the tachometer.\n\n"
                    "It carries a pulse train, not vibration, so it has no "
                    "sensor, no engineering unit and no spectrum. Change it "
                    "in the Tachometer tab.")
                continue
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
                        items=list(rev80.AMPLITUDE_MODES),
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
            self._connect_device(sensor)
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
                if amp in rev80.AMPLITUDE_MODES:
                    self.collector.config.channel_amplitude_modes[ch] = amp
                else:
                    self.collector.config.channel_amplitude_modes.pop(ch, None)
        self.collector.config.enabled_channels.sort()

    # ------------------------------------------------------------------
    # Session Browser
    # ------------------------------------------------------------------

    def _open_session_browser(self, sender=None, data=None) -> None:
        """Open (or refresh) the Monitor Session browser modal."""
        if self._refuse_while_recording("Session browse"):
            return
        if dpg.does_item_exist(ui.DLG_SESSION_BROWSER):
            self._refresh_session_browser()
            dpg.configure_item(
                ui.DLG_SESSION_BROWSER,
                pos=((WINDOW_WIDTH - 1030) // 2, (WINDOW_HEIGHT - 620) // 2),
                show=True,
            )
            return
        self._build_session_browser()

    def _build_session_browser(self) -> None:
        """Build the session browser modal — session table + burst table."""
        DLG_W, DLG_H = 1030, 620
        ROW_H = DLG_H - 130

        _tbl_kw = dict(
            header_row=True, row_background=True,
            borders_innerV=True, borders_outerH=True, borders_outerV=True,
            scrollY=True, freeze_rows=1, height=-1,
        )

        with dpg.window(
            label="Load Monitor Session",
            modal=True, show=True,
            tag=ui.DLG_SESSION_BROWSER,
            width=DLG_W, height=DLG_H,
            pos=((WINDOW_WIDTH - DLG_W) // 2, (WINDOW_HEIGHT - DLG_H) // 2),
            no_resize=False,
        ):
            # ── Source folder row ─────────────────────────────────────
            dpg.add_text("Session folder")
            with dpg.group(horizontal=True):
                dpg.add_input_text(
                    tag='_SB_FOLDER',
                    default_value=str(rev80.data_dir() / 'monitor'),
                    width=-90,
                    hint="Path to monitor sessions folder",
                )
                dpg.add_button(
                    label=icons.IC['folder_open'],
                    width=80,
                    callback=self._on_session_browser_pick_folder,
                )
            dpg.add_spacer(height=6)

            # ── Two-column table area ─────────────────────────────────
            with dpg.group(horizontal=True):
                # ── Sessions table ────────────────────────────────────
                with dpg.child_window(width=520, height=ROW_H, border=True):
                    dpg.add_text("Sessions  (click to load)", color=_c("ON_SURFACE"))
                    dpg.add_separator()
                    with dpg.table(tag='_SB_SESSION_TABLE', **_tbl_kw):
                        dpg.add_table_column(label="Date",     width_fixed=True, init_width_or_weight=90)
                        dpg.add_table_column(label="Time",     width_fixed=True, init_width_or_weight=70)
                        dpg.add_table_column(label="Ch",       width_fixed=True, init_width_or_weight=30)
                        dpg.add_table_column(label="Captures", width_fixed=True, init_width_or_weight=70)
                        dpg.add_table_column(label="Bursts",   width_fixed=True, init_width_or_weight=55)

                dpg.add_spacer(width=6)

                # ── Bursts table ──────────────────────────────────────
                with dpg.child_window(width=-1, height=ROW_H, border=True):
                    dpg.add_text("Bursts  (click to load)", color=_c("ON_SURFACE"))
                    dpg.add_separator()
                    with dpg.table(tag='_SB_BURST_TABLE', **_tbl_kw):
                        dpg.add_table_column(label="Date",        width_fixed=True, init_width_or_weight=90)
                        dpg.add_table_column(label="Time",        width_fixed=True, init_width_or_weight=70)
                        dpg.add_table_column(label="Max Overall", width_fixed=True, init_width_or_weight=110)

            # ── Bottom bar ────────────────────────────────────────────
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=f'{icons.IC["save"]}  Save Config',
                    tag='_SB_SAVE_CONFIG_BTN',
                    callback=self._on_sb_save_config,
                    width=120, height=28,
                )
                dpg.add_button(
                    label=f'{icons.IC["refresh"]}  Reprocess',
                    tag='_SB_REPROCESS_BTN',
                    callback=self._on_sb_reprocess,
                    width=110, height=28,
                )
                dpg.add_button(
                    label=f'{icons.IC["refresh"]}  Refresh',
                    callback=self._refresh_session_browser,
                    width=100, height=28,
                )
                dpg.add_spacer(width=-1)
                dpg.add_button(
                    label=f'{icons.IC["close"]}  Close',
                    callback=lambda: dpg.configure_item(ui.DLG_SESSION_BROWSER, show=False),
                    width=90, height=28,
                )

        self._refresh_session_browser()

    def _scan_session_dirs(self) -> list:
        """Return session metadata dicts sorted newest-first.

        Each entry: {session_id, session_dir, session_h5,
                     date, time, n_channels, n_captures, n_bursts}
        Reads the folder from the _SB_FOLDER widget if it exists, else default.
        """
        import json as _json
        if dpg.does_item_exist('_SB_FOLDER'):
            folder_str = dpg.get_value('_SB_FOLDER').strip()
            monitor_root = Path(folder_str) if folder_str else rev80.data_dir() / 'monitor'
        else:
            monitor_root = rev80.data_dir() / 'monitor'

        sessions = []
        if not monitor_root.exists():
            return sessions
        try:
            dirs = sorted(
                [d for d in monitor_root.iterdir() if d.is_dir()],
                key=lambda d: d.name, reverse=True,
            )
        except OSError as exc:
            log.error(f'session browser: cannot list {monitor_root}: {exc}')
            return sessions

        for d in dirs:
            h5 = d / 'session.h5'
            if not h5.exists():
                continue
            try:
                with h5py.File(str(h5), 'r') as f:
                    meta       = f.get('metadata', {})
                    start_time = str(meta.attrs.get('start_time', d.name) if meta else d.name)
                    interval_s = float(meta.attrs.get('interval_s', 0.0)) if meta else 0.0
                    n_channels = len(f.get('metadata/channels', {}))
                    n_captures = len(f.get('monitor', {}))
                    burst_raw  = f['burst'].attrs.get('burst_list', '[]') if 'burst' in f else '[]'
                    if isinstance(burst_raw, bytes):
                        burst_raw = burst_raw.decode()
                    n_bursts   = len(_json.loads(burst_raw) if burst_raw else [])
                    # End time: last capture's stored timestamp
                    end_time = '—'
                    mon_grp = f.get('monitor')
                    if mon_grp:
                        last_key = max(mon_grp.keys(), key=int, default=None)
                        if last_key is not None:
                            raw_end = str(mon_grp[last_key].attrs.get('timestamp', ''))
                            if raw_end:
                                end_time = raw_end[:19].replace('T', ' ')
            except Exception as exc:
                log.warning(f'session browser: skipping {h5}: {exc}')
                continue
            start_disp = start_time[:19].replace('T', ' ')
            sessions.append({
                'session_id':  d.name,
                'session_dir': d,
                'session_h5':  h5,
                'date':        start_disp[:10],   # kept for legacy table display
                'time':        start_disp[11:19],
                'start_time':  start_disp,
                'end_time':    end_time,
                'interval_s':  interval_s,
                'n_channels':  n_channels,
                'n_captures':  n_captures,
                'n_bursts':    n_bursts,
            })

        self._session_browser_sessions = sessions
        return sessions

    def _on_session_list_select(self, sender=None, data=None, user_data=None) -> None:
        """Load all interval frames from the selected session; populate burst table."""
        import json
        # user_data carries the session dict when called from table row selectable
        entry = user_data
        if entry is None:
            return
        # Single-select: deselect all other rows, keep only the clicked one active
        for sel_id in self._sb_session_sel_ids:
            if dpg.does_item_exist(sel_id):
                dpg.set_value(sel_id, sel_id == sender)
        self._sb_burst_sel_ids.clear()
        session_dir = entry['session_dir']
        session_h5  = entry['session_h5']
        self._session_browser_selected_session_dir = session_dir
        self._current_session_h5    = session_h5
        self._current_session_id    = entry.get('session_id', '')
        self._current_session_entry = entry
        self._browse_context = {
            'type':        'session',
            'start_time':  entry.get('start_time', '—'),
            'end_time':    entry.get('end_time',   '—'),
            'interval_s':  entry.get('interval_s', 0.0),
            'n_captures':  entry.get('n_captures', '—'),
            'n_bursts':    entry.get('n_bursts',   '—'),
        }

        # Load all interval frames into a new collector. A corrupt or old
        # file leaves the screen unchanged.
        new = self._load_into_new_collector(
            lambda c: c.load_monitor_session(session_h5), f'session {session_h5}')
        if new is not None:
            self._replace_collector(new)
            self._autoscale_plots()

        # Populate burst listbox
        burst_list: list = []
        try:
            with h5py.File(str(session_h5), 'r') as f:
                if 'burst' in f:
                    raw = f['burst'].attrs.get('burst_list', '[]')
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    burst_list = json.loads(raw) if raw else []
        except Exception as exc:
            log.warning(f'session browser: cannot read bursts from {session_h5}: {exc}')

        self._session_browser_burst_list = burst_list

        # Rebuild burst table rows
        self._sb_burst_sel_ids.clear()
        if dpg.does_item_exist('_SB_BURST_TABLE'):
            for child in (dpg.get_item_children('_SB_BURST_TABLE', slot=1) or []):
                dpg.delete_item(child)
            for b in burst_list:
                if not isinstance(b, dict):
                    continue
                ts = b.get('timestamp', '')
                date_s, time_s = ts[:10], ts[11:19] if 'T' in ts or len(ts) > 10 else (ts[:10], '')
                try:
                    max_ov = json.loads(b.get('max_overall_json', '{}'))
                    max_val = max((float(v) for v in max_ov.values()), default=0.0)
                    max_str = f'{max_val:.4f}'
                except Exception:
                    max_str = '-'
                with dpg.table_row(parent='_SB_BURST_TABLE'):
                    sel_id = dpg.add_selectable(
                        label=date_s,
                        span_columns=True,
                        callback=self._on_burst_list_select,
                        user_data=b,
                    )
                    self._sb_burst_sel_ids.append(sel_id)
                    dpg.add_text(time_s)
                    dpg.add_text(max_str)

        # Draw vertical lines on trend plot at burst trigger times
        burst_rel_times = [
            float(b['rel_time']) for b in burst_list
            if isinstance(b, dict) and 'rel_time' in b
        ]
        try:
            self._charts.set_burst_lines(burst_rel_times)
        except Exception as exc:
            log.warning(f'session browser: failed to draw burst vlines: {exc}')

    def _on_sb_save_config(self, sender=None, data=None) -> None:
        """Patch /metadata/channels/ and /metadata/scope_sensors/ with current config."""
        session_h5 = self._current_session_h5
        if session_h5 is None:
            log.warning("_on_sb_save_config: no session loaded")
            return
        try:
            with h5py.File(str(session_h5), 'a') as f:
                meta = f.require_group('metadata')
                # Recreate channels group — interpretation attrs only; hardware attrs unchanged
                if 'channels' in meta:
                    del meta['channels']
                ch_grp = meta.create_group('channels')
                for ch in self.collector.config.enabled_channels:
                    scope_s = self.collector.scope_sensors.get(ch)
                    cg = ch_grp.create_group(str(ch))
                    cg.attrs['name']            = self.collector.config.name_for(ch)
                    cg.attrs['scope_sensor_id'] = scope_s.id if scope_s else ''
                    cg.attrs['target_unit']     = self.collector.config.target_unit_for(ch)
                    cg.attrs['amplitude_mode']  = self.collector.config.amplitude_mode_for(ch)
                # Recreate scope_sensors group with currently wired sensors
                if 'scope_sensors' in meta:
                    del meta['scope_sensors']
                ss_grp = meta.create_group('scope_sensors')
                seen: set = set()
                for ch in self.collector.config.enabled_channels:
                    scope_s = self.collector.scope_sensors.get(ch)
                    if scope_s and scope_s.id not in seen:
                        seen.add(scope_s.id)
                        sg = ss_grp.create_group(scope_s.id)
                        for k, v in scope_s.to_dict().items():
                            sg.attrs[k] = v
            log.info(f"Saved config to {session_h5.name}")
        except (OSError, KeyError) as exc:
            # Catch only I/O (OSError) and missing-group (KeyError) errors.
            # A programming error must not be logged as a disk failure.
            log.error(f"_on_sb_save_config: failed to patch {session_h5}: {exc}")
            return
        # Reprocess trend with the new config
        self._on_sb_reprocess()

    def _on_sb_reprocess(self, sender=None, data=None) -> None:
        """Reprocess overall_json for all captures using the current sensor/channel config."""
        session_h5 = self._current_session_h5
        if session_h5 is None:
            log.warning("_on_sb_reprocess: no session loaded")
            return

        if dpg.does_item_exist('_SB_REPROCESS_BTN'):
            dpg.configure_item('_SB_REPROCESS_BTN', enabled=False, label='Reprocessing…')

        def _progress(i: int, n: int) -> None:
            if dpg.does_item_exist('_SB_REPROCESS_BTN'):
                dpg.configure_item('_SB_REPROCESS_BTN', label=f'{i} / {n}')

        def _run() -> None:
            # This thread never touches the collector on screen. It works on
            # its own collector, loaded from the patched session file, and
            # hands a freshly loaded one to the render thread.
            try:
                work = self._load_into_new_collector(
                    lambda c: c.load_monitor_session(session_h5), f'reprocess {session_h5}')
                if work is not None:
                    work.reprocess_session_trend(session_h5, progress_cb=_progress)
            except Exception as exc:
                log.error(f"_on_sb_reprocess: failed: {exc}")
            finally:
                if dpg.does_item_exist('_SB_REPROCESS_BTN'):
                    dpg.configure_item('_SB_REPROCESS_BTN', enabled=True,
                                       label=f'{icons.IC["refresh"]}  Reprocess')
            # Reload the session to show the updated trend.
            fresh = self._load_into_new_collector(
                lambda c: c.load_monitor_session(session_h5), f'reload {session_h5}')
            if fresh is not None:
                self._pending_collector = fresh

        threading.Thread(target=_run, daemon=True, name='SBReprocess').start()

    def _on_burst_list_select(self, sender=None, data=None, user_data=None) -> None:
        """Load all frames from the selected burst event."""
        burst = user_data
        if not burst:
            return
        # Single-select: deselect all other burst rows
        for sel_id in self._sb_burst_sel_ids:
            if dpg.does_item_exist(sel_id):
                dpg.set_value(sel_id, sel_id == sender)
        burst_id = burst.get('burst_id', '')
        session_dir = self._session_browser_selected_session_dir
        if not burst_id or session_dir is None:
            return
        session_h5 = Path(str(session_dir)) / 'session.h5'
        # Remove session vlines — burst view is independent, trend rebased to trigger=0
        try:
            self._charts.set_burst_lines([])
        except Exception as exc:                             # noqa: BLE001
            log.warning(f'session browser: failed to remove burst vlines: {exc}')

        new = self._load_into_new_collector(
            lambda c: c.load_monitor_burst(session_h5, burst_id),
            f'burst {burst_id} from {session_h5}')
        if new is None or not self._replace_collector(new):
            return

        se = self._current_session_entry
        self._browse_context = {
            'type':         'burst',
            'trigger_type': burst.get('trigger_type', 'burst'),
            'trigger_ts':   burst.get('timestamp', '')[:19].replace('T', ' '),
            'start_time':   se.get('start_time', '—'),
            'end_time':     se.get('end_time',   '—'),
            'interval_s':   se.get('interval_s', 0.0),
            'n_captures':   se.get('n_captures', '—'),
            'n_bursts':     se.get('n_bursts',   '—'),
        }
        self._update_browse_label()

        self._autoscale_plots()

    def _on_session_browser_pick_folder(self, sender=None, data=None) -> None:
        """Open the platform-native folder picker; update the session folder input."""
        try:
            from plyer import filechooser
            result = filechooser.choose_dir(
                title="Select monitor sessions folder",
                path=str(rev80.data_dir() / 'monitor'),
            )
            if result:
                if dpg.does_item_exist('_SB_FOLDER'):
                    dpg.set_value('_SB_FOLDER', str(result[0]))
                self._refresh_session_browser()
        except NotImplementedError:
            log.warning('session browser: folder picker not supported on this platform')
        except Exception as exc:
            log.error(f'session browser: folder picker failed: {exc}')

    def _refresh_session_browser(self) -> None:
        sessions = self._scan_session_dirs()

        # Rebuild session table
        self._sb_session_sel_ids.clear()
        if dpg.does_item_exist('_SB_SESSION_TABLE'):
            for child in (dpg.get_item_children('_SB_SESSION_TABLE', slot=1) or []):
                dpg.delete_item(child)
            for s in sessions:
                with dpg.table_row(parent='_SB_SESSION_TABLE'):
                    sel_id = dpg.add_selectable(
                        label=s['date'],
                        span_columns=True,
                        callback=self._on_session_list_select,
                        user_data=s,
                    )
                    self._sb_session_sel_ids.append(sel_id)
                    dpg.add_text(s['time'])
                    dpg.add_text(str(s['n_channels']))
                    dpg.add_text(str(s['n_captures']))
                    dpg.add_text(str(s['n_bursts']))

        # Clear burst table until a session is selected
        if dpg.does_item_exist('_SB_BURST_TABLE'):
            for child in (dpg.get_item_children('_SB_BURST_TABLE', slot=1) or []):
                dpg.delete_item(child)

        # If a session is already loaded and still in the list, re-highlight it without
        # reloading.  Only auto-load on first open (no session currently loaded) so that
        # re-opening the browser after changing channel settings doesn't overwrite them.
        if sessions:
            current = self._current_session_h5
            if current is not None:
                for i, s in enumerate(sessions):
                    if s['session_h5'] == current and i < len(self._sb_session_sel_ids):
                        dpg.set_value(self._sb_session_sel_ids[i], True)
                        break
            else:
                self._on_session_list_select(user_data=sessions[0])

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
        self._charts.rebuild()
        self._update_results_section_visibility()
        self.collector.init_trend_channels()

        # Single reconnect to apply all hardware changes at once
        if self.collector.sensor is not None:
            self.collector.reconnect_stream()

        if self._was_streaming_before_config:
            self._start_stream()
        else:
            self.collector.reprocess_last_block()

        self._save_monitor_config()
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
        if dpg.does_item_exist(ui.ACQ_DLG_AVG_ENABLED):
            dpg.set_value(ui.ACQ_DLG_AVG_ENABLED, cfg.averaging_enabled)
            dpg.set_value(ui.ACQ_DLG_AVG_N, cfg.n_averages)
        if dpg.does_item_exist(ui.ACQ_DLG_BAND_FMIN):
            # 0 is the "unset" sentinel in the widget; None in the config.
            dpg.set_value(ui.ACQ_DLG_BAND_FMIN, cfg.band_fmin or 0.0)
            dpg.set_value(ui.ACQ_DLG_BAND_FMAX, cfg.band_fmax or 0.0)
            dpg.set_value(ui.ACQ_DLG_BAND_PRESET, self._band_preset_label(cfg))
        if dpg.does_item_exist(ui.ACQ_DLG_CACHE_FRAMES):
            dpg.set_value(ui.ACQ_DLG_CACHE_FRAMES, cfg.cache_frames)
        if dpg.does_item_exist(ui.ACQ_DLG_ENV_ENABLED):
            dpg.set_value(ui.ACQ_DLG_ENV_ENABLED, cfg.envelope_enabled)
        self._update_acq_derived()

    def _band_suffix(self) -> str:
        """Compact ' 10-1000 Hz' qualifier for overall labels, or '' if unknown.

        The band is part of what the number means -- two overalls taken over
        different bands are not comparable -- so it rides on the label rather
        than only in a tooltip.
        """
        cfg = self.collector.config if self.collector else None
        if cfg is None:
            return ''
        lo, hi = cfg.band
        lo_s = f'{lo:g}' if lo else '0'
        return f'  {lo_s}-{hi:g} Hz'

    @staticmethod
    def _band_preset_label(cfg) -> str:
        """Which band preset, if any, the config's explicit edges correspond to."""
        if cfg.band_fmin is None and cfg.band_fmax is None:
            return 'Full band (HP - F_max)'
        for name, (lo, hi) in rev80.ISO_BAND_PRESETS.items():
            if (cfg.band_fmin == lo) and (cfg.band_fmax == hi):
                return name
        return 'Custom'

    def _on_band_preset(self, sender=None, data=None):
        """Fill the band edge fields from the chosen preset.

        The edges stay editable afterwards -- picking a preset is a shortcut for
        typing two numbers, not a mode.
        """
        label = dpg.get_value(ui.ACQ_DLG_BAND_PRESET)
        if label in rev80.ISO_BAND_PRESETS:
            lo, hi = rev80.ISO_BAND_PRESETS[label]
        else:
            lo, hi = 0.0, 0.0          # 'Full band' / 'Custom' -> unset, i.e. derive
        dpg.set_value(ui.ACQ_DLG_BAND_FMIN, float(lo))
        dpg.set_value(ui.ACQ_DLG_BAND_FMAX, float(hi))
        self._on_acq_preview()

    def _apply_acq_settings_from_widgets(self):
        """Read acquisition tab widgets and write values into collector.config.

        Pure settings application — no stream stop/start side effects.
        Stream lifecycle is the caller's responsibility.
        """
        cfg = self.collector.config
        mf_str = dpg.get_value(ui.ACQ_DLG_MAXFREQ)
        bs_str = dpg.get_value(ui.ACQ_DLG_BINSIZE)
        try:
            cfg.maxfreq = rev80.MAXFREQ_PRESETS[_MAXFREQ_LABELS.index(mf_str)]
        except (ValueError, IndexError):
            pass
        try:
            cfg.binsize = rev80.BINSIZE_PRESETS[_BINSIZE_LABELS.index(bs_str)]
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
        if dpg.does_item_exist(ui.ACQ_DLG_AVG_ENABLED):
            cfg.averaging_enabled = bool(dpg.get_value(ui.ACQ_DLG_AVG_ENABLED))
            cfg.n_averages = max(1, int(dpg.get_value(ui.ACQ_DLG_AVG_N)))
        if dpg.does_item_exist(ui.ACQ_DLG_BAND_FMIN):
            fmin = float(dpg.get_value(ui.ACQ_DLG_BAND_FMIN))
            fmax = float(dpg.get_value(ui.ACQ_DLG_BAND_FMAX))
            cfg.band_fmin = fmin if fmin > 0 else None
            cfg.band_fmax = fmax if fmax > 0 else None
        if dpg.does_item_exist(ui.ACQ_DLG_CACHE_FRAMES):
            n = max(1, int(dpg.get_value(ui.ACQ_DLG_CACHE_FRAMES)))
            cfg.cache_frames = n
            self.collector.resize_frame_cache(n)
        if dpg.does_item_exist(ui.ACQ_DLG_ENV_ENABLED):
            cfg.envelope_enabled = bool(dpg.get_value(ui.ACQ_DLG_ENV_ENABLED))

    def _on_acq_apply(self, sender=None, data=None):
        was_streaming = self.collector.is_streaming
        if was_streaming:
            self._stop_stream()
        self._apply_acq_settings_from_widgets()
        self._save_channel_assignments()  # persist acquisition settings to device YAML
        # The layout follows "Envelope analysis" and "Average spectrum", and
        # the card and axis labels show the band.
        self._charts.rebuild()
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
        """Sync Monitor config tab widgets from acquisition.yaml.

        initialize() calls it after the widgets exist, and the dialog calls
        it again when it opens on the Monitor tab. Thus the widgets always
        hold the config values: _save_monitor_config (on each dialog close),
        _start_recording and _build_anomaly_hook read the widgets.
        """
        if not dpg.does_item_exist(ui.MON_DLG_INTERVAL):
            return
        mon = _cfg.load_acquisition_config().get("monitor", {})
        interval_s = float(mon.get("interval_s", _MON_SEED["interval_s"]))
        pre_buf_s = float(mon.get("pre_burst_s", _MON_SEED["pre_burst_s"]))
        burst_dur_s = float(mon.get("burst_duration_s", _MON_SEED["burst_duration_s"]))
        out_dir = mon.get("output_dir") or ""
        compress = mon.get("compression", _MON_SEED["compression"]) == "gzip"

        # An interval that is not a preset shows the nearest preset. A fixed
        # fallback label would write a different interval back on save.
        interval_label = rev80.MONITOR_INTERVAL_PRESETS.get(
            int(interval_s),
            rev80.MONITOR_INTERVAL_PRESETS[nearest_interval_preset(interval_s)],
        )
        dpg.set_value(ui.MON_DLG_INTERVAL, interval_label)
        dpg.set_value(ui.MON_DLG_PRE_BUFFER, pre_buf_s)
        dpg.set_value(ui.MON_DLG_BURST_DUR, burst_dur_s)
        dpg.set_value(ui.MON_DLG_OUTPUT_DIR, str(out_dir))
        dpg.set_value(ui.MON_DLG_COMPRESS, compress)
        self._on_monitor_config_change()

        # Restore anomaly settings
        anom = mon.get("anomaly", {})
        # Headless uses an EWMA time before an alpha. Do not write an EWMA
        # time that the config does not have, unless the user changes it.
        self._ewma_time_not_stored = {
            key: default for key, default in _EWMA_TIME_DEFAULTS.items()
            if key not in anom
        }
        def _sv(tag, val):
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, val)
        _sv(ui.MON_ANOM_ENABLED,   bool(anom.get("enabled",    _ANOM_SEED["enabled"])))
        # Stored canonically in lowercase; the combo shows the display label.
        # gui_hook_type() clamps a stored 'spectral'/'both' — written by the
        # headless front end, which still offers them — to something this combo
        # actually lists. The stored value itself is preserved on save.
        self._stored_hook_type = canonical_hook_type(anom.get("hook_type", "rms"))
        _sv(ui.MON_ANOM_HOOK,      hook_type_label(gui_hook_type(self._stored_hook_type)))
        _sv(ui.MON_ANOM_RMS_PCT,      float(anom.get("rms_pct",       _ANOM_SEED["rms_pct"])))
        _sv(ui.MON_ANOM_RMS_S,        float(anom.get("rms_s",         _ANOM_SEED["rms_s"])))
        _sv(ui.MON_ANOM_RMS_EWMA_TIME, float(anom.get("rms_ewma_time", _EWMA_TIME_DEFAULTS["rms_ewma_time"])))
        _sv(ui.MON_ANOM_RMS_WARMUP,   int(anom.get("warmup",          _ANOM_SEED["warmup"])))
        _sv(ui.MON_ANOM_RMS_UNIT,     _hook_choice(anom.get("rms_unit"), _HOOK_UNITS, _ANOM_SEED["rms_unit"]))
        _sv(ui.MON_ANOM_RMS_MODE,     _hook_choice(anom.get("rms_amplitude_mode"), _HOOK_MODES, _ANOM_SEED["rms_amplitude_mode"]))
        _sv(ui.MON_ANOM_SPEC_PCT,     float(anom.get("spec_pct",      _ANOM_SEED["spec_pct"])))
        _sv(ui.MON_ANOM_SPEC_N,       int(anom.get("spec_n",          _ANOM_SEED["spec_n"])))
        _sv(ui.MON_ANOM_SPEC_FMIN,    float(anom.get("spec_fmin") or  0.0))
        _sv(ui.MON_ANOM_SPEC_FMAX,    float(anom.get("spec_fmax") or  0.0))
        _sv(ui.MON_ANOM_SPEC_EWMA_TIME, float(anom.get("spec_ewma_time", _EWMA_TIME_DEFAULTS["spec_ewma_time"])))

        _sv(ui.MON_ANOM_FIXED_UPPER_ENABLED, bool(anom.get("fixed_upper_enabled", False)))
        _sv(ui.MON_ANOM_FIXED_UPPER_VALUE,   float(anom.get("fixed_upper_value",  1.0)))
        _sv(ui.MON_ANOM_FIXED_UPPER_UNIT,    str(anom.get("fixed_upper_unit",     "in/s")))
        _sv(ui.MON_ANOM_FIXED_LOWER_ENABLED, bool(anom.get("fixed_lower_enabled", False)))
        _sv(ui.MON_ANOM_FIXED_LOWER_VALUE,   float(anom.get("fixed_lower_value",  0.05)))
        _sv(ui.MON_ANOM_FIXED_LOWER_UNIT,    str(anom.get("fixed_lower_unit",     "in/s")))
        _sv(ui.MON_ANOM_FIXED_UPPER_MODE,    _hook_choice(anom.get("fixed_upper_mode"), _HOOK_MODES, _ANOM_SEED["fixed_upper_mode"]))
        _sv(ui.MON_ANOM_FIXED_LOWER_MODE,    _hook_choice(anom.get("fixed_lower_mode"), _HOOK_MODES, _ANOM_SEED["fixed_lower_mode"]))
        _sv(ui.MON_ANOM_FIXED_S,             float(anom.get("fixed_s",            _ANOM_SEED["fixed_s"])))

        _sv(ui.MON_ANOM_COOLDOWN_ENABLED, bool(anom.get("cooldown_enabled", False)))
        _sv(ui.MON_ANOM_COOLDOWN_S,       float(anom.get("cooldown_s",      300.0)))

        self._on_anom_config_change()

    def _hook_type_to_save(self, widget_value) -> str:
        """Canonical hook type to persist, without clobbering a headless setting.

        The combo cannot show 'spectral'/'both' (see GUI_ANOMALY_HOOK_TYPES), so
        a headless config shows as 'rms'. If the stored value is one the GUI
        cannot offer, and the widget still shows the stand-in, keep the stored
        value. Otherwise, opening this dialog would change the headless setting.
        """
        shown = canonical_hook_type(widget_value)
        stored = getattr(self, '_stored_hook_type', None)
        if stored is not None and stored not in GUI_ANOMALY_HOOK_TYPES:
            if shown == gui_hook_type(stored):
                return stored
        return shown

    def _save_monitor_config(self) -> None:
        """Persist monitor + anomaly config to acquisition.yaml.

        Updates the stored monitor block in place. Keys that have no widget
        (max_burst_s, compression_level, rms_alpha, spec_alpha) keep their
        stored values, so that a dialog close does not undo a hand edit.
        """
        def _get(tag, default):
            return dpg.get_value(tag) if dpg.does_item_exist(tag) else default

        acq_cfg = _cfg.load_acquisition_config()
        stored = dict(acq_cfg.get('monitor', {}))
        anomaly = dict(stored.get('anomaly', {}))
        interval_s = interval_to_save(
            _get(ui.MON_DLG_INTERVAL, None),
            stored.get('interval_s', _MON_SEED['interval_s']),
        )
        stored.update({
            'interval_s':        interval_s,
            'pre_burst_s':       float(_get(ui.MON_DLG_PRE_BUFFER, _MON_SEED['pre_burst_s'])),
            'burst_duration_s':  float(_get(ui.MON_DLG_BURST_DUR,  _MON_SEED['burst_duration_s'])),
            'max_burst_s':       float(stored.get('max_burst_s', _MON_SEED['max_burst_s'])),
            'output_dir':        str(_get(ui.MON_DLG_OUTPUT_DIR, '')).strip() or None,
            'compression':       'gzip' if _get(ui.MON_DLG_COMPRESS, True) else 'none',
        })
        anomaly.update({
            'enabled':       bool(_get(ui.MON_ANOM_ENABLED,    _ANOM_SEED['enabled'])),
            'hook_type':     self._hook_type_to_save(_get(ui.MON_ANOM_HOOK, 'RMS')),
            'rms_pct':       float(_get(ui.MON_ANOM_RMS_PCT,        _ANOM_SEED['rms_pct'])),
            'rms_s':         float(_get(ui.MON_ANOM_RMS_S,          _ANOM_SEED['rms_s'])),
            'warmup':        int(_get(ui.MON_ANOM_RMS_WARMUP,        _ANOM_SEED['warmup'])),
            'rms_unit':      _hook_choice(_get(ui.MON_ANOM_RMS_UNIT, _ANOM_SEED['rms_unit']), _HOOK_UNITS, _ANOM_SEED['rms_unit']),
            'rms_amplitude_mode': _hook_choice(_get(ui.MON_ANOM_RMS_MODE, _ANOM_SEED['rms_amplitude_mode']), _HOOK_MODES, _ANOM_SEED['rms_amplitude_mode']),
            'spec_pct':      float(_get(ui.MON_ANOM_SPEC_PCT,        _ANOM_SEED['spec_pct'])),
            'spec_n':        int(_get(ui.MON_ANOM_SPEC_N,            _ANOM_SEED['spec_n'])),
            'spec_fmin':     _get(ui.MON_ANOM_SPEC_FMIN, None) or None,
            'spec_fmax':     _get(ui.MON_ANOM_SPEC_FMAX, None) or None,
            'cooldown_enabled':    bool(_get(ui.MON_ANOM_COOLDOWN_ENABLED, False)),
            'cooldown_s':          float(_get(ui.MON_ANOM_COOLDOWN_S,      300.0)),
            'fixed_upper_enabled': bool(_get(ui.MON_ANOM_FIXED_UPPER_ENABLED, False)),
            'fixed_upper_value':   float(_get(ui.MON_ANOM_FIXED_UPPER_VALUE,  1.0)),
            'fixed_upper_unit':    str(_get(ui.MON_ANOM_FIXED_UPPER_UNIT,     'in/s')),
            'fixed_lower_enabled': bool(_get(ui.MON_ANOM_FIXED_LOWER_ENABLED, False)),
            'fixed_lower_value':   float(_get(ui.MON_ANOM_FIXED_LOWER_VALUE,  0.05)),
            'fixed_lower_unit':    str(_get(ui.MON_ANOM_FIXED_LOWER_UNIT,     'in/s')),
            'fixed_upper_mode':    _hook_choice(_get(ui.MON_ANOM_FIXED_UPPER_MODE, _ANOM_SEED['fixed_upper_mode']), _HOOK_MODES, _ANOM_SEED['fixed_upper_mode']),
            'fixed_lower_mode':    _hook_choice(_get(ui.MON_ANOM_FIXED_LOWER_MODE, _ANOM_SEED['fixed_lower_mode']), _HOOK_MODES, _ANOM_SEED['fixed_lower_mode']),
            'fixed_s':             float(_get(ui.MON_ANOM_FIXED_S,            _ANOM_SEED['fixed_s'])),
        })
        not_stored = getattr(self, '_ewma_time_not_stored', {})
        for key, tag in (('rms_ewma_time', ui.MON_ANOM_RMS_EWMA_TIME),
                         ('spec_ewma_time', ui.MON_ANOM_SPEC_EWMA_TIME)):
            value = float(_get(tag, _EWMA_TIME_DEFAULTS[key]))
            if key in not_stored and value == not_stored[key]:
                continue
            anomaly[key] = value
        stored['anomaly'] = anomaly
        acq_cfg['monitor'] = stored
        _cfg.save_acquisition_config(acq_cfg)
        log.debug("Monitor config saved to acquisition.yaml")

    def _on_monitor_config_change(self, sender=None, data=None):
        """Update the storage estimate label when Monitor config widgets change."""
        if not dpg.does_item_exist(ui.MON_DLG_ESTIMATE):
            return
        def _get(tag, default):
            return dpg.get_value(tag) if dpg.does_item_exist(tag) else default

        interval_s = interval_from_label(
            _get(ui.MON_DLG_INTERVAL, None), _MON_SEED['interval_s'])
        burst_dur_s = float(_get(ui.MON_DLG_BURST_DUR, _MON_SEED['burst_duration_s']))
        pre_buf_s = float(_get(ui.MON_DLG_PRE_BUFFER, _MON_SEED['pre_burst_s']))
        estimate, per_year = monitor_storage_estimate(
            self.collector.config, interval_s, burst_dur_s, pre_buf_s)
        # Flag more than 10 GB/year: a long run with a daily or weekly
        # interval stores less, so the interval is possibly set too short.
        over_10gb = per_year > 10e9
        dpg.set_value(
            ui.MON_DLG_ESTIMATE,
            f"{icons.IC['warning']}  {estimate}" if over_10gb else estimate,
        )
        dpg.configure_item(
            ui.MON_DLG_ESTIMATE,
            color=_c("RED_LIGHT") if over_10gb else _c("ON_SURFACE"),
        )

    def _on_record_toggle(self, sender=None, data=None):
        if self._monitor is not None and self._monitor.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _monitor_session_params(self) -> dict:
        """Session parameters from the Monitor widgets, as session_from keywords.

        The widgets hold the acquisition.yaml values from startup. A missing
        widget gives the config seed value.
        """
        def _get(tag, default):
            return dpg.get_value(tag) if dpg.does_item_exist(tag) else default

        mon_saved = _cfg.load_acquisition_config().get('monitor', {})
        out_dir = str(_get(ui.MON_DLG_OUTPUT_DIR, '')).strip()
        return {
            # A stored interval that is not a preset stays as stored.
            'interval_s': interval_to_save(
                _get(ui.MON_DLG_INTERVAL, None),
                mon_saved.get('interval_s', _MON_SEED['interval_s'])),
            'pre_buffer_s': float(_get(ui.MON_DLG_PRE_BUFFER, _MON_SEED['pre_burst_s'])),
            'burst_duration_s': float(
                _get(ui.MON_DLG_BURST_DUR, _MON_SEED['burst_duration_s'])),
            'output_dir': out_dir or None,
            'compression': 'gzip' if _get(ui.MON_DLG_COMPRESS, True) else 'none',
            # No widget: read it from acquisition.yaml, as headless does.
            'compression_level': int(mon_saved.get(
                'compression_level', _MON_SEED['compression_level'])),
            'cooldown_enabled': bool(
                _get(ui.MON_ANOM_COOLDOWN_ENABLED, _ANOM_SEED['cooldown_enabled'])),
            'cooldown_s': float(_get(ui.MON_ANOM_COOLDOWN_S, _ANOM_SEED['cooldown_s'])),
            # max_burst_s has no widget: read it from acquisition.yaml. It
            # limits the memory that an unattended burst can use. Do not
            # replace it with a fixed value.
            'max_burst_s': float(mon_saved.get('max_burst_s', _MON_SEED['max_burst_s'])),
        }

    def _start_recording(self):
        """Start streaming (if not running) and start monitor session."""
        from datetime import datetime

        # Start streaming if needed
        if not self.collector.is_streaming:
            self._toggle_acquisition()

        # Abort if the stream failed to start (no device connected / stream is None)
        if not self.collector.is_streaming:
            log.warning("Monitor: cannot start — connect a device first")
            if dpg.does_item_exist(ui.MONITOR_STATUS_TEXT):
                dpg.set_value(ui.MONITOR_STATUS_TEXT, "No device connected")
            return

        params = self._monitor_session_params()
        pre_buf_s = params['pre_buffer_s']

        from rev80.monitor.session import required_cache_frames, session_from

        now_local  = datetime.now()
        session_id = now_local.strftime('%Y-%m-%d-%H%M%S')

        session = session_from(
            collector=self.collector,
            session_id=session_id,
            start_time=now_local,
            **params,
        )

        # The frame cache must hold the pre-trigger window plus the trigger
        # frame. Headless uses the same shared rule.
        self.collector.resize_frame_cache(required_cache_frames(
            self.collector.config.cache_frames, session.pre_buffer_frames))

        if self._monitor is None:
            self._monitor = rev80.MonitorController()
        anomaly_hook = self._build_anomaly_hook(pre_buffer_s=pre_buf_s)
        self._monitor.start(session, anomaly_hook=anomaly_hook)

        self._update_monitor_card()
        self._set_recording_lock(True)

    def _stop_recording(self):
        """Stop the monitor session; leave streaming running."""
        if self._monitor is not None:
            self._monitor.stop()
        self.collector.resize_frame_cache(self.collector.config.cache_frames)
        self._update_monitor_card()
        self._set_recording_lock(False)

    def _on_anom_config_change(self, sender=None, data=None) -> None:
        """Show/hide RMS/Spectral settings groups; refresh computed-alpha labels."""
        if not dpg.does_item_exist(ui.MON_ANOM_HOOK):
            return
        hook = canonical_hook_type(dpg.get_value(ui.MON_ANOM_HOOK))
        if dpg.does_item_exist(ui.MON_ANOM_RMS_GROUP):
            dpg.configure_item(ui.MON_ANOM_RMS_GROUP,  show=hook in ('rms',  'both'))
        if dpg.does_item_exist(ui.MON_ANOM_SPEC_GROUP):
            dpg.configure_item(ui.MON_ANOM_SPEC_GROUP, show=hook in ('spectral', 'both'))
        # Update α labels from ewma_time + current acquisition period
        from rev80.monitor.anomaly import ewma_alpha_from_time
        dt = self.collector.config.acquisition_period if self.collector else 1.0
        for time_tag, label_tag in (
            (ui.MON_ANOM_RMS_EWMA_TIME,  ui.MON_ANOM_RMS_ALPHA_LABEL),
            (ui.MON_ANOM_SPEC_EWMA_TIME, ui.MON_ANOM_SPEC_ALPHA_LABEL),
        ):
            if dpg.does_item_exist(time_tag) and dpg.does_item_exist(label_tag):
                t = float(dpg.get_value(time_tag))
                if t > 0 and dt > 0:
                    alpha = ewma_alpha_from_time(t, dt)
                    dpg.set_value(label_tag, f"  α = {alpha:.4f}  (dt = {dt:.3g} s)")

    def _build_anomaly_hook(self, pre_buffer_s: float | None = None):
        """Read anomaly config widgets and return a configured hook.

        Built once at session start; the hook is active for the whole session.
        Reads the Monitor tab widgets, which hold the acquisition.yaml values
        from startup. The `_get` fallbacks are the config seed values; they
        apply only when a widget does not exist.
        """
        from rev80.monitor.anomaly import (
            RmsThresholdHook, SpectralThresholdHook, FixedThresholdHook,
            CompositeAnomalyHook, NullAnomalyHook, ewma_alpha_from_time,
            frames_for_seconds,
        )
        def _get(tag, default):
            return dpg.get_value(tag) if dpg.does_item_exist(tag) else default

        burst_dur = float(_get(ui.MON_DLG_BURST_DUR, _MON_SEED['burst_duration_s']))
        if pre_buffer_s is None:
            pre_buffer_s = float(_get(ui.MON_DLG_PRE_BUFFER, _MON_SEED['pre_burst_s']))

        hooks = []
        # Bound before the hook branches: the RMS, the spectral and the fixed
        # branch all read `period`.
        period = self.collector.config.acquisition_period

        # ── EWMA-based hooks (RMS / Spectral) — gated by the main Enable switch
        if _get(ui.MON_ANOM_ENABLED, _ANOM_SEED['enabled']):
            hook_type = canonical_hook_type(_get(ui.MON_ANOM_HOOK, 'RMS'))
            # The seed value, the same as headless
            # (tests/test_anomaly_hook_build.py compares the two copies).
            warmup    = int(_get(ui.MON_ANOM_RMS_WARMUP, _ANOM_SEED['warmup']))

            if hook_type in ('rms', 'both'):
                rms_s  = float(_get(ui.MON_ANOM_RMS_S, _ANOM_SEED['rms_s']))
                consecutive_n = frames_for_seconds(rms_s, period)
                if rms_s > 0.25 * pre_buffer_s:
                    log.warning(
                        "Monitor anomaly: RMS sustained time %.3gs exceeds 25%% of the "
                        "pre-trigger buffer (%.3gs) — the t=0 frame will eat into the "
                        "pre-anomaly context captured in each burst",
                        rms_s, pre_buffer_s,
                    )
                rms_ewma_t = float(_get(ui.MON_ANOM_RMS_EWMA_TIME, 60.0))
                rms_alpha  = (ewma_alpha_from_time(rms_ewma_t, period)
                              if period > 0 else DEFAULT_RMS_ALPHA)
                hooks.append(RmsThresholdHook(
                    rms_threshold_pct    = float(_get(ui.MON_ANOM_RMS_PCT, _ANOM_SEED['rms_pct'])),
                    consecutive_n        = consecutive_n,
                    baseline_alpha       = rms_alpha,
                    min_baseline_samples = warmup,
                    burst_duration_s     = burst_dur,
                    unit                 = _hook_choice(_get(ui.MON_ANOM_RMS_UNIT, _ANOM_SEED['rms_unit']), _HOOK_UNITS, _ANOM_SEED['rms_unit']),
                    amplitude_mode       = _hook_choice(_get(ui.MON_ANOM_RMS_MODE, _ANOM_SEED['rms_amplitude_mode']), _HOOK_MODES, _ANOM_SEED['rms_amplitude_mode']),
                ))

            # Not reachable from the GUI: GUI_ANOMALY_HOOK_TYPES excludes
            # 'spectral'/'both'. Kept so this builder has the same shape as the
            # headless copy, which offers the hook, and so the test can compare
            # both. Tracked as R39 in doc/PROGRESS.md; change both copies together.
            if hook_type in ('spectral', 'both'):
                fmin_v      = float(_get(ui.MON_ANOM_SPEC_FMIN, 0.0))
                fmax_v      = float(_get(ui.MON_ANOM_SPEC_FMAX, 0.0))
                spec_ewma_t = float(_get(ui.MON_ANOM_SPEC_EWMA_TIME, 300.0))
                spec_alpha  = (ewma_alpha_from_time(spec_ewma_t, period)
                               if period > 0 else DEFAULT_SPEC_ALPHA)
                hooks.append(SpectralThresholdHook(
                    spectral_threshold_pct = float(_get(ui.MON_ANOM_SPEC_PCT, _ANOM_SEED['spec_pct'])),
                    consecutive_n          = int(_get(ui.MON_ANOM_SPEC_N, _ANOM_SEED['spec_n'])),
                    baseline_alpha         = spec_alpha,
                    min_baseline_samples   = warmup,
                    fmin                   = fmin_v if fmin_v > 0 else None,
                    fmax                   = fmax_v if fmax_v > 0 else None,
                    burst_duration_s       = burst_dur,
                ))

        # ── Fixed-level threshold trigger — independent enable switches
        upper_on = bool(_get(ui.MON_ANOM_FIXED_UPPER_ENABLED, False))
        lower_on = bool(_get(ui.MON_ANOM_FIXED_LOWER_ENABLED, False))
        if upper_on or lower_on:
            hooks.append(FixedThresholdHook(
                upper_limit = float(_get(ui.MON_ANOM_FIXED_UPPER_VALUE, 1.0))  if upper_on else None,
                upper_unit  = str(_get(ui.MON_ANOM_FIXED_UPPER_UNIT,    'in/s')),
                lower_limit = float(_get(ui.MON_ANOM_FIXED_LOWER_VALUE, 0.05)) if lower_on else None,
                lower_unit  = str(_get(ui.MON_ANOM_FIXED_LOWER_UNIT,    'in/s')),
                upper_mode  = _hook_choice(_get(ui.MON_ANOM_FIXED_UPPER_MODE, _ANOM_SEED['fixed_upper_mode']), _HOOK_MODES, _ANOM_SEED['fixed_upper_mode']),
                lower_mode  = _hook_choice(_get(ui.MON_ANOM_FIXED_LOWER_MODE, _ANOM_SEED['fixed_lower_mode']), _HOOK_MODES, _ANOM_SEED['fixed_lower_mode']),
                sustain_frames = frames_for_seconds(
                    float(_get(ui.MON_ANOM_FIXED_S, _ANOM_SEED['fixed_s'])), period),
                burst_duration_s = burst_dur,
            ))

        if not hooks:
            return NullAnomalyHook()
        if len(hooks) == 1:
            return hooks[0]
        return CompositeAnomalyHook(hooks)

    def _on_reset_baseline(self, sender=None, data=None) -> None:
        """Clear EWMA baseline data on the active anomaly hook(s) and restart warmup.

        Available from the Monitor card while recording — the config dialog is
        locked out during a session, but baselines may need recalibrating
        mid-run (e.g. after a maintenance event changes the "normal" level).
        """
        if self._monitor is None or not self._monitor.is_recording:
            return
        hook = self._monitor._anomaly_hook
        if hasattr(hook, 'reset_baseline'):
            hook.reset_baseline()
        log.info("Anomaly baseline reset — re-calibrating from next frame")

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
            dpg.configure_item(ui.MONITOR_RECORD_BTN, enabled=True)
            dpg.set_value(ui.MONITOR_STATUS_TEXT, status)
            if dpg.does_item_exist(ui.MONITOR_RESET_BTN):
                dpg.configure_item(ui.MONITOR_RESET_BTN, enabled=True)
            if dpg.does_item_exist(ui.MONITOR_BURST_BTN):
                dpg.configure_item(ui.MONITOR_BURST_BTN, enabled=not snap.get('is_in_burst', False))
            # Burst indicator
            if snap.get('is_in_burst', False):
                remaining = snap.get('burst_remaining_s', 0.0)
                if dpg.does_item_exist(ui.MONITOR_BURST_RECT):
                    dpg.configure_item(ui.MONITOR_BURST_RECT, fill=_c("YELLOW"))
                if dpg.does_item_exist(ui.MONITOR_BURST_TEXT):
                    dpg.set_value(ui.MONITOR_BURST_TEXT, f'Burst: {remaining:.0f}s remaining')
            else:
                if dpg.does_item_exist(ui.MONITOR_BURST_RECT):
                    dpg.configure_item(ui.MONITOR_BURST_RECT, fill=_c("GREEN"))
                if dpg.does_item_exist(ui.MONITOR_BURST_TEXT):
                    dpg.set_value(ui.MONITOR_BURST_TEXT, 'Ready')
        else:
            dpg.set_item_label(ui.MONITOR_RECORD_BTN, f'{icons.IC["record"]}  Monitor')
            if not self.collector.is_streaming:
                dpg.set_value(ui.MONITOR_STATUS_TEXT, 'Start stream to record')
            else:
                dpg.set_value(ui.MONITOR_STATUS_TEXT, 'Stopped')
            if dpg.does_item_exist(ui.MONITOR_RESET_BTN):
                dpg.configure_item(ui.MONITOR_RESET_BTN, enabled=False)
            if dpg.does_item_exist(ui.MONITOR_BURST_BTN):
                dpg.configure_item(ui.MONITOR_BURST_BTN, enabled=False)
            if dpg.does_item_exist(ui.MONITOR_BURST_RECT):
                dpg.configure_item(ui.MONITOR_BURST_RECT, fill=_c("GREEN"))
            if dpg.does_item_exist(ui.MONITOR_BURST_TEXT):
                dpg.set_value(ui.MONITOR_BURST_TEXT, 'Ready')

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
        sensor = ScopeSensor(
            name=name,
            engineering_units=dpg.get_value(ui.SREG_FIELD_UNITS),
            sensitivity=float(dpg.get_value(ui.SREG_FIELD_SENS)),
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
        new_sensor = ScopeSensor(name="New Sensor", engineering_units="g", sensitivity=100.0)
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
                # The Tachometer tab owns these, but they are per-channel
                # device state and belong in the device file with the rest of
                # it -- otherwise the tach reverts to a vibration channel every
                # time the config is reloaded.
                "role": self.collector.config.role_for(c),
                "tach": (self.collector.tach_settings_for(c).to_dict()
                         if self.collector.config.role_for(c) == 'tachometer'
                         else None),
            }
            for c in range(self._num_channels)
        }
        _cfg.save_device_config(
            self.collector.sensor.model_name,
            self.collector.sensor.serial_number,
            {"channels": channels, "siggen": self.collector.siggen_config},
        )
        acq_cfg = _cfg.load_acquisition_config()
        acq_cfg['acquisition'] = self.collector.config.to_dict()
        _cfg.save_acquisition_config(acq_cfg)

    def _on_channel_enable_change(self, ch: int):
        if not dpg.does_item_exist(ui.scope_ch_enabled(ch)):
            return
        enabled = dpg.get_value(ui.scope_ch_enabled(ch))
        if enabled:
            if ch not in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.append(ch)
                self.collector.config.enabled_channels.sort()
        else:
            self.collector.config.enabled_channels = [c for c in self.collector.config.enabled_channels if c != ch]
        self._save_channel_assignments()
        # Reflect enabled/disabled state in the header text color
        header_tag = ui.scope_ch_header(ch)
        theme_tag = ui.scope_ch_hdr_theme(ch, enabled)
        if dpg.does_item_exist(header_tag) and dpg.does_item_exist(theme_tag):
            dpg.bind_item_theme(header_tag, theme_tag)
        self._update_connection_summary()
        self._charts.rebuild()
        self._update_results_section_visibility()
        # Skip live reconnect while the config dialog is open — _on_config_close
        # will do a single reconnect with all changes applied at once.
        if not dpg.is_item_visible(ui.DLG_CONFIG):
            self.collector.reconnect_stream()

    def _refresh_channel_names(self):
        """Sync the channel names on the tachometer cards.

        The charts and their cards take the names at their rebuild, which
        follows in _on_config_close.
        """
        for ch in range(_MAX_CHANNELS):
            name = self.collector.config.name_for(ch)
            header_tag = ui.ch_header_text(ch)
            if dpg.does_item_exist(header_tag):
                dpg.set_value(header_tag, name)

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
        self._charts.rebuild()
        self._redraw()
        self._refresh_channel_header(ch)

    def _restore_channel_assignments(self, device_cfg: dict | None = None):
        """Apply saved channel assignments, siggen, and acquisition config to the collector."""
        # Acquisition settings always come from acquisition.yaml (instance-wide).
        acq_dict = _cfg.load_acquisition_config().get("acquisition", {})
        if acq_dict:
            self.collector.config = AcquisitionSettings.from_dict(acq_dict)
        # The peak significance widget lives in the results pane, not in the
        # config dialog, so nothing else repopulates it when config is reloaded.
        if dpg.does_item_exist(ui.FFT_PEAK_THRESHOLD_DB):
            dpg.set_value(ui.FFT_PEAK_THRESHOLD_DB, self.collector.config.peak_threshold_db)

        if device_cfg is None:
            if self.collector.sensor is not None:
                device_cfg = _cfg.load_device_config(
                    self.collector.sensor.model_name,
                    self.collector.sensor.serial_number,
                )
            else:
                device_cfg = {}

        # Restore siggen
        siggen = device_cfg.get("siggen")
        self.collector.siggen_config = siggen
        self._populate_siggen_tab()

        assignments = device_cfg.get("channels", {})
        for ch, info in assignments.items():
            if ch >= self._num_channels:
                continue
            sensor_id = info.get("sensor_id")
            voltage_range = info.get("voltage_range", 7)
            coupling = info.get("coupling", "AC")
            channel_name = info.get("channel_name", "")
            target_unit = info.get("target_unit", "")
            amplitude_mode = info.get("amplitude_mode", "")
            # One role decision for the GUI and headless (in config.py). It
            # also sets `enabled`: a tachometer channel is always enabled,
            # because config.tach_channels ignores disabled channels.
            role, tach_settings, enabled = _cfg.channel_role_state(info)
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
            if role == 'tachometer':
                self.collector.config.channel_roles[ch] = role
                self.collector.set_tach_settings(ch, tach_settings)
            else:
                self.collector.config.channel_roles.pop(ch, None)
                self.collector.set_tach_settings(ch, None)
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
        self.collector.config.enabled_channels.sort()
        self._charts.rebuild()
        # After the roles are restored, so the tab shows the loaded values,
        # not its construction defaults.
        self._populate_tach_tab()
        self._update_results_section_visibility()

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def _create_gui(self):
        dpg.create_context()
        _font = icons.load()
        if _font is not None:      # None → font file absent, use DPG default
            dpg.bind_font(_font)

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
                def _tip(target, text):
                    with dpg.tooltip(parent=target):
                        dpg.add_text(text, wrap=320)

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

                    # ── Tachometer tab ─────────────────────────────────────
                    # This tab owns the tachometer role. The Channels tab shows
                    # a claimed channel read-only, so two screens cannot
                    # disagree. The live plot is here, not in the main display:
                    # tach setup is done once per installation. After the
                    # dialog closes, the result card shows the shaft speed.
                    with dpg.tab(label="Tachometer", tag=ui.CONFIG_TAB_TACH):
                        with dpg.child_window(autosize_x=True, height=-1):
                            dpg.add_text("Tachometer Channel")
                            dpg.add_separator()
                            _tc = dpg.add_combo(
                                label="Channel", tag=ui.TACH_CHANNEL,
                                items=["(none)"], default_value="(none)",
                                width=_DLG_FIELD_W,
                                callback=lambda s, d: self._on_tach_channel_change())
                            _tip(_tc,
                                 "Which input carries the tachometer pulse.\n\n"
                                 "A tachometer has no sensor and no engineering "
                                 "unit, so the Channels tab shows it read-only "
                                 "once claimed here.")
                            dpg.add_spacer(height=4)

                            with dpg.group(horizontal=True):
                                dpg.add_combo(
                                    label="Polarity", tag=ui.TACH_POLARITY,
                                    items=list(rev80_tach.POLARITIES),
                                    default_value='rising', width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                                _tm = dpg.add_combo(
                                    label="Threshold", tag=ui.TACH_THRESH_MODE,
                                    items=list(rev80_tach.THRESHOLD_MODES),
                                    default_value='adaptive', width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                            _tip(_tm,
                                 "Adaptive places the threshold at the midpoint "
                                 "of each block's own span.\n\n"
                                 "A fixed threshold fails silently on an "
                                 "AC-coupled input: AC coupling removes the mean, "
                                 "and on a pulse train the mean IS the duty "
                                 "cycle, so above ~55% duty the signal never "
                                 "reaches a fixed level and the shaft reads as "
                                 "stopped. Measured on the bench at 70% and 85% "
                                 "duty. Leave this on adaptive unless you have a "
                                 "specific reason.")
                            with dpg.group(horizontal=True):
                                dpg.add_input_float(
                                    label="Level (mV)", tag=ui.TACH_THRESH_MV,
                                    default_value=2500.0, step=100.0,
                                    width=_DLG_FIELD_W // 2, enabled=False,
                                    callback=lambda s, d: self._on_tach_settings_change())
                                _ma = dpg.add_input_float(
                                    label="Min ampl. (mV)", tag=ui.TACH_MIN_AMPL_MV,
                                    default_value=rev80_tach.MIN_PULSE_AMPLITUDE_MV,
                                    step=100.0, width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                            _tip(_ma,
                                 "Below this peak-to-peak swing the channel is "
                                 "reported as having no tach signal.\n\n"
                                 "Measured front-end noise on this hardware "
                                 "spans at most 42.5 mV, so 1000 mV clears it "
                                 "23x while staying well under any real "
                                 "logic-level tach's 2 V swing.")

                            dpg.add_spacer(height=4)
                            with dpg.group(horizontal=True):
                                _ru = dpg.add_combo(
                                    label="Rate units", tag=ui.TACH_ROTATION_UNIT,
                                    items=[ROTATION_UNIT_LABELS[u] for u in ROTATION_UNITS],
                                    default_value=ROTATION_UNIT_LABELS[DEFAULT_ROTATION_UNIT],
                                    width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                                _rf = dpg.add_input_float(
                                    label="Reflector (mm)", tag=ui.TACH_REFLECTOR_MM,
                                    default_value=0.0, step=1.0,
                                    width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                            with dpg.group(horizontal=True):
                                _pr = dpg.add_input_int(
                                    label="Pulses/rev", tag=ui.TACH_PPR,
                                    default_value=1, min_value=1, step=1,
                                    min_clamped=True, width=_DLG_FIELD_W // 2,
                                    callback=lambda s, d: self._on_tach_settings_change())
                            _tip(_pr,
                                 "How many pulses the sensor sees per shaft "
                                 "revolution. One reflective tape or one keyway "
                                 "is 1.\n\n"
                                 "Leave this at 1 wherever you have the choice. "
                                 "At 1 pulse/rev every interval is exactly one "
                                 "revolution, so encoder division error and "
                                 "once-per-rev speed modulation cancel by "
                                 "construction: 0.0013% against 0.091% for a "
                                 "60-line encoder at any window length.\n\n"
                                 "A higher value is divided out correctly, but "
                                 "a rate is only reported once the block holds "
                                 "two whole revolutions -- so a finer encoder "
                                 "does NOT read a slower shaft. Use a smaller "
                                 "bin size for that.")
                            _tip(_ru, "Applies to every shaft-rate readout in the app.")
                            _tip(_rf,
                                 "Arc length of the reflective tape or key, "
                                 "measured along the shaft surface. 0 = not "
                                 "measured.\n\n"
                                 "With the duty cycle this gives the shaft "
                                 "circumference and hence surface velocity. "
                                 "Measure what the sensor actually sees -- spot "
                                 "width and probe field are not corrected for.")

                            dpg.add_separator()
                            with dpg.group(horizontal=True):
                                _tb = dpg.add_button(
                                    label="Start", tag=ui.TACH_STREAM_BTN,
                                    width=90,
                                    callback=lambda s, d: self._toggle_acquisition())
                                dpg.add_text("--", tag=ui.TACH_READOUT)
                            _tip(_tb,
                                 "Starts and stops acquisition -- the same "
                                 "control as the main window, not a second "
                                 "one, because there is one instrument.\n\n"
                                 "Claiming a tachometer channel starts it "
                                 "automatically so the waveform is there to "
                                 "adjust against.")
                            dpg.add_text("", tag=ui.TACH_QUALITY, color=_c("MUTED"))
                            # Warnings get a bordered orange box and the
                            # warning glyph. Muted grey on a dark ground reads
                            # as disabled text, which is the opposite of what a
                            # warning is for.
                            with dpg.theme(tag=ui.TACH_WARN_THEME):
                                with dpg.theme_component(dpg.mvChildWindow):
                                    dpg.add_theme_color(dpg.mvThemeCol_Border,
                                                        _c("ORANGE"),
                                                        category=dpg.mvThemeCat_Core)
                                    dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 2,
                                                        category=dpg.mvThemeCat_Core)
                            with dpg.child_window(tag=ui.TACH_WARN_BOX, border=True,
                                                  autosize_x=True, height=34,
                                                  show=False) as _wb:
                                _fl = dpg.add_text("", tag=ui.TACH_FLOOR,
                                                   color=_c("ORANGE"))
                                _pw = dpg.add_text("", tag=ui.TACH_PPR_WARN,
                                                   color=_c("ORANGE"), show=False)
                            dpg.bind_item_theme(_wb, ui.TACH_WARN_THEME)
                            _tip(_fl,
                                 "Two whole shaft revolutions must fall inside "
                                 "one acquisition block for a rate to be "
                                 "resolved, so the block length (1/bin size) "
                                 "sets a slowest measurable shaft.\n\n"
                                 "More pulses per revolution does not lower it "
                                 "meaningfully -- the gate is revolutions, not "
                                 "pulses. A smaller bin size does.\n\n"
                                 "This is information, not a limit on setup: "
                                 "configure the tach against a stopped machine "
                                 "with your best guess and it will read once the "
                                 "shaft turns.")
                            _tip(_pw,
                                 "Sub-sample edge interpolation needs about 70 "
                                 "samples per pulse. Below that the estimator "
                                 "collapses to ~0.8% error -- the median locks "
                                 "onto the modal integer sample period.\n\n"
                                 "Measured on the bench. Fewer pulses per "
                                 "revolution is the fix; the acquisition rate "
                                 "is fixed and cannot be raised.")
                            with dpg.plot(label="Tach signal", height=200,
                                          width=-1, tag=ui.TACH_PLOT):
                                dpg.add_plot_axis(dpg.mvXAxis, label="s from first pulse",
                                                  tag=ui.TACH_PLOT_X)
                                with dpg.plot_axis(dpg.mvYAxis, label="mV",
                                                   tag=ui.TACH_PLOT_Y):
                                    dpg.add_line_series([], [], label="signal",
                                                        tag=ui.TACH_PLOT_WAVE)
                                    dpg.add_line_series([], [], label="threshold",
                                                        tag=ui.TACH_PLOT_THRESH)
                                    dpg.add_scatter_series([], [], label="edges",
                                                           tag=ui.TACH_PLOT_EDGES)

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
                                    _sens_hdr = dpg.add_text("Sensor Configuration  (?)")
                                    _tip(_sens_hdr,
                                         "Source EU is the engineering unit the sensor produces "
                                         "(e.g. g, mm/s, in/s). "
                                         "Sensitivity is the charge-amp output voltage per EU, "
                                         "from the sensor calibration certificate (e.g. 100 mV/g). "
                                         "These values are used to scale raw scope voltage into "
                                         "physical units.")
                                    dpg.add_input_text(label="Name", tag=ui.SREG_FIELD_NAME, width=_SREG_FIELD_W)
                                    dpg.add_combo(
                                        label="Source EU",
                                        tag=ui.SREG_FIELD_UNITS,
                                        items=rev80.EU_OPTIONS,
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
                            _acq_n_hdr = dpg.add_text("Acquisition Sample Count  (?)")
                            _tip(_acq_n_hdr,
                                 "Freq. Resolution sets the spectral bin width (Hz/line). "
                                 "Finer resolution means more samples per block, which increases "
                                 "acquisition time and memory per frame. "
                                 "The derived 'Acq. Time' shows how long each block takes to fill.")
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
                            # Control: linear power averaging of the spectrum.
                            _avg_en = dpg.add_checkbox(
                                label="Average spectrum",
                                tag=ui.ACQ_DLG_AVG_ENABLED,
                                default_value=False,
                                callback=self._on_acq_preview,
                            )
                            self._tooltip(
                                _avg_en,
                                "Average the spectrum over several successive frames. "
                                "Each bin of a single frame has a standard deviation "
                                "equal to its own mean, so the floor looks rough and a "
                                "small line is hard to pick out; averaging N frames cuts "
                                "that scatter by sqrt(N).\n\n"
                                "It does NOT lower the noise floor -- only the "
                                "uncertainty of it. To separate two close lines you need "
                                "a finer bin size instead.\n\n"
                                "Assumes the machine is steady over the window. If the "
                                "speed drifts, lines smear across bins and averaging "
                                "blurs them rather than sharpening them.")
                            _avg_n = dpg.add_input_int(
                                label="Averages", tag=ui.ACQ_DLG_AVG_N,
                                default_value=8, min_value=1, max_value=512,
                                callback=self._on_acq_preview, width=_w,
                            )
                            self._tooltip(
                                _avg_n,
                                "Number of frames to average. Diminishing returns past "
                                "about 16, since the benefit goes as sqrt(N): 4 halves "
                                "the scatter, 16 quarters it, 64 only halves it again.\n\n"
                                "Capped by the frame cache below -- you cannot average "
                                "more frames than are kept. Frames rejected for ADC "
                                "overload or a degraded stream are skipped, so the count "
                                "actually achieved is shown beside the spectrum.")
                            dpg.add_input_text(
                                label="Avg. Window", tag=ui.ACQ_DLG_AVG_TIME,
                                readonly=True, width=_w,
                            )

                            dpg.add_separator()
                            dpg.add_text("Analysis Tabs")
                            _env_en = dpg.add_checkbox(
                                label="Envelope/Demodulation (bearing analysis)",
                                tag=ui.ACQ_DLG_ENV_ENABLED,
                                default_value=False,
                            )
                            self._tooltip(
                                _env_en,
                                "Shows the Envelope tab, which demodulates a housing "
                                "resonance to reveal rolling-element bearing defects. "
                                "Not every job is a bearing job -- turn this off to "
                                "keep it from cluttering ones that aren't.")

                            # Control: declared measurement band for the overall.
                            # Blank/0 means "derive": the highpass edge up to
                            # F_max. Two overalls are comparable only when
                            # their bands are the same.
                            _band_items = ['Full band (HP - F_max)'] + list(rev80.ISO_BAND_PRESETS)
                            _band_cmb = dpg.add_combo(
                                label="Overall Band", items=_band_items,
                                tag=ui.ACQ_DLG_BAND_PRESET,
                                default_value=_band_items[0],
                                callback=self._on_band_preset, width=_w,
                            )
                            self._tooltip(_band_cmb,
                                "The frequency band the Overall amplitude is measured over, "
                                "and stored with the data. 'Full band' follows the highpass "
                                "setting and F_max. The ISO bands are what ISO 20816 zone "
                                "limits are defined against -- a velocity RMS only means "
                                "anything against a zone boundary if it was measured over "
                                "the band that boundary assumes.")
                            with dpg.group(horizontal=True):
                                dpg.add_input_float(
                                    label="min", tag=ui.ACQ_DLG_BAND_FMIN, default_value=0.0,
                                    min_value=0.0, step=0, format="%.1f",
                                    callback=self._on_acq_preview, width=90,
                                )
                                dpg.add_input_float(
                                    label="max Hz", tag=ui.ACQ_DLG_BAND_FMAX, default_value=0.0,
                                    min_value=0.0, step=0, format="%.1f",
                                    callback=self._on_acq_preview, width=90,
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
                            _fft_hdr = dpg.add_text("FFT Conditioning  (?)")
                            _tip(_fft_hdr,
                                 f"{_WELCH_OVERLAP_TIP}\n\n"
                                 "Window: shape applied to each segment before FFT. Hann is a "
                                 "good general-purpose choice. Flat-top improves amplitude "
                                 "accuracy for calibration; Blackman-Harris reduces sidelobes "
                                 "for closely-spaced peaks.")
                            # Control: Welch % Overlap
                            _welch_w = dpg.add_input_float(
                                label="Welch Overlap %",
                                tag=ui.ACQ_DLG_OVERLAP,
                                default_value=50.0,
                                min_value=0.0,
                                max_value=95.0,
                                width=_w,
                            )
                            _tip(_welch_w, _WELCH_OVERLAP_TIP)
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
                            _sg_hdr = dpg.add_text("PicoScope Signal Generator  (?)")
                            _tip(_sg_hdr,
                                 "Built-in AWG on the PicoScope's front-panel BNC output. "
                                 "Use for sensor check-out, resonance excitation, or shaker drive. "
                                 "Hardware only — has no effect in simulation mode.")
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

                    # ── Monitor tab ─────────────────────────────────────────
                    with dpg.tab(label="Monitor", tag=ui.CONFIG_TAB_MONITOR):
                        with dpg.child_window(autosize_x=True, height=-1):
                            _mon_w = 220
                            dpg.add_text("Interval Datalogger")
                            dpg.add_separator()
                            dpg.add_combo(
                                label="Capture interval",
                                tag=ui.MON_DLG_INTERVAL,
                                items=list(rev80.MONITOR_INTERVAL_PRESETS.values()),
                                default_value="1 h",
                                width=_mon_w,
                                callback=self._on_monitor_config_change,
                            )
                            _pretrig_w = dpg.add_input_float(
                                label="Pre-trigger buffer (s)",
                                tag=ui.MON_DLG_PRE_BUFFER,
                                default_value=60.0,
                                min_value=0.0,
                                max_value=3600.0,
                                width=_mon_w,
                                callback=self._on_monitor_config_change,
                            )
                            _tip(_pretrig_w,
                                 "Raw data captured before the trigger timestamp and prepended "
                                 "to each burst. Drawn from the ring cache — lets you see the "
                                 "run-up to an event. Must be less than the ring cache duration "
                                 "(Cache Frames × Acq. Time in the Acquisition tab).")
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
                                hint=f"Default: {rev80.data_dir() / 'monitor'}",
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
                            _tip(ui.MON_DLG_ESTIMATE,
                                 "Estimated disk use in decimal units (1 GB = 10^9 bytes). "
                                 "It counts the raw-rate waveform of each vibration channel. "
                                 "A tachometer channel stores only edge times and is not "
                                 "counted. It assumes that gzip halves the data. This is an "
                                 "assumption, not a measurement: the ratio changes with the "
                                 "signal, and on simulated data gzip kept 96 % of the raw "
                                 "size. Plan for the raw size, two times the estimate.")

                            # ── Anomaly Detection ───────────────────────
                            dpg.add_spacer(height=8)
                            dpg.add_separator()
                            _anom_hdr = dpg.add_text("Anomaly Detection  (?)")
                            _tip(_anom_hdr,
                                 "Automatically triggers a burst capture when live vibration "
                                 "deviates from a self-calibrating baseline.\n\n"
                                 "RMS: tracks overall amplitude via an exponential moving average "
                                 "and fires when it shifts by more than Threshold %.\n\n"
                                 "Spectral: tracks the full frequency-domain shape and fires when "
                                 "the mean spectral deviation exceeds the threshold — useful for "
                                 "detecting changes in specific harmonics or bearing tones.")
                            dpg.add_checkbox(
                                label="Enable",
                                tag=ui.MON_ANOM_ENABLED,
                                default_value=False,
                                callback=self._on_anom_config_change,
                            )
                            _hook_combo = dpg.add_combo(
                                label="Hook",
                                items=[ANOMALY_HOOK_LABELS[k] for k in GUI_ANOMALY_HOOK_TYPES],
                                tag=ui.MON_ANOM_HOOK,
                                default_value=ANOMALY_HOOK_LABELS[GUI_ANOMALY_HOOK_TYPES[0]],
                                callback=self._on_anom_config_change,
                                width=_mon_w,
                            )
                            _tip(_hook_combo,
                                 "RMS: monitors overall vibration level. "
                                 "The Spectral detector is temporarily unavailable here — it "
                                 "fires on essentially every healthy frame, so it was unwired "
                                 "from this panel pending a rework (see R39). It is unchanged "
                                 "in the headless front end.")

                            with dpg.group(tag=ui.MON_ANOM_RMS_GROUP):
                                dpg.add_text("RMS settings", color=_c("ON_SURFACE"))
                                dpg.add_input_float(label="Threshold %",    tag=ui.MON_ANOM_RMS_PCT,   default_value=10.0, min_value=1.0,  max_value=100.0, step=1.0,  width=_mon_w)
                                _rms_s_w = dpg.add_input_float(label="Sustained (s)",  tag=ui.MON_ANOM_RMS_S,     default_value=3.0,  min_value=0.0,  max_value=3600.0, step=1.0, width=_mon_w,
                                                    callback=self._on_anom_config_change)
                                _tip(_rms_s_w,
                                     "Signal must remain above threshold for this many seconds "
                                     "before a burst is triggered. Filters momentary spikes. "
                                     "Set to 0 to trigger on the first anomalous frame.")
                                _ewma_rms_w = dpg.add_input_float(
                                    label="EWMA time (s)", tag=ui.MON_ANOM_RMS_EWMA_TIME,
                                    default_value=60.0, min_value=1.0, max_value=86400.0,
                                    step=10.0, width=_mon_w,
                                    callback=self._on_anom_config_change,
                                )
                                _tip(_ewma_rms_w,
                                     "Time constant τ of the exponential baseline (seconds). "
                                     "The baseline adapts to 1/e ≈ 37% of a step change in τ seconds. "
                                     "Larger τ = slower adaptation = detects sustained shifts; "
                                     "smaller τ tracks faster but may miss slow drift.")
                                dpg.add_text("", tag=ui.MON_ANOM_RMS_ALPHA_LABEL, color=_c("MUTED"))
                                _warmup_w = dpg.add_input_int(  label="Warmup frames",  tag=ui.MON_ANOM_RMS_WARMUP,default_value=30,   min_value=5,    max_value=500,   width=_mon_w)
                                _tip(_warmup_w,
                                     "Number of frames collected to build the initial baseline "
                                     "before anomaly detection activates. Increase if the machine "
                                     "takes a while to reach steady-state after startup.")
                                _rms_unit_w = dpg.add_combo(
                                    label="Unit", tag=ui.MON_ANOM_RMS_UNIT, items=list(_HOOK_UNITS),
                                    default_value=_ANOM_SEED['rms_unit'], width=_mon_w)
                                _tip(_rms_unit_w,
                                     "The unit of the overall that the baseline follows, "
                                     "for all channels. Example: g on a channel in in/s "
                                     "finds a high-frequency change sooner. A channel that "
                                     "cannot give the unit (no sensor) is not checked. "
                                     "The recording stores the channel unit in all cases.")
                                _rms_mode_w = dpg.add_combo(
                                    label="Amplitude", tag=ui.MON_ANOM_RMS_MODE, items=list(_HOOK_MODES),
                                    default_value=_ANOM_SEED['rms_amplitude_mode'], width=_mon_w)
                                _tip(_rms_mode_w,
                                     "The amplitude mode of the overall that the baseline "
                                     "follows, for all channels.")

                            with dpg.group(tag=ui.MON_ANOM_SPEC_GROUP, show=False):
                                _spec_hdr = dpg.add_text("Spectral settings  (?)", color=_c("ON_SURFACE"))
                                _tip(_spec_hdr,
                                     "Compares the live PSD against a learned spectral baseline. "
                                     "Triggers when the mean deviation across the monitored band "
                                     "exceeds Threshold % for Consecutive N frames. "
                                     "Useful for detecting new harmonics or changes in bearing tones "
                                     "that don't shift overall level much.")
                                dpg.add_input_float(label="Threshold %",     tag=ui.MON_ANOM_SPEC_PCT,  default_value=50.0, min_value=1.0, max_value=500.0, step=1.0,  width=_mon_w)
                                dpg.add_input_int(  label="Consecutive N",   tag=ui.MON_ANOM_SPEC_N,    default_value=3,   min_value=1,   max_value=20,   width=_mon_w)
                                dpg.add_input_float(label="Freq min (Hz)",   tag=ui.MON_ANOM_SPEC_FMIN, default_value=0.0, min_value=0.0, step=10.0,      width=_mon_w)
                                dpg.add_input_float(label="Freq max (0=all)",tag=ui.MON_ANOM_SPEC_FMAX, default_value=0.0, min_value=0.0, step=10.0,      width=_mon_w)
                                _ewma_spec_w = dpg.add_input_float(
                                    label="EWMA time (s)", tag=ui.MON_ANOM_SPEC_EWMA_TIME,
                                    default_value=300.0, min_value=1.0, max_value=86400.0,
                                    step=30.0, width=_mon_w,
                                    callback=self._on_anom_config_change,
                                )
                                _tip(_ewma_spec_w,
                                     "Time constant τ of the spectral baseline (seconds). "
                                     "The per-bin PSD baseline adapts to 1/e of a change in τ seconds. "
                                     "Spectral baselines typically need slower adaptation (larger τ) "
                                     "than RMS baselines to avoid chasing machine run-up variations.")
                                dpg.add_text("", tag=ui.MON_ANOM_SPEC_ALPHA_LABEL, color=_c("MUTED"))

                            # ── Fixed Level Trigger ─────────────────────
                            dpg.add_spacer(height=8)
                            dpg.add_separator()
                            _fixed_hdr = dpg.add_text("Fixed Level Trigger  (?)")
                            _tip(_fixed_hdr,
                                 "Fires on a fixed overall level, with no baseline and no "
                                 "warm-up. Each limit has its own unit and amplitude mode: "
                                 "a limit in in/s works on a channel in g. A channel with no "
                                 "sensor gives mV only, so a limit in another unit skips it.")
                            _unit_items = sorted(UNIT_TO_SI.keys())
                            with dpg.group(horizontal=True):
                                _upper_chk = dpg.add_checkbox(label="Upper limit", tag=ui.MON_ANOM_FIXED_UPPER_ENABLED, default_value=False)
                                dpg.add_input_float(tag=ui.MON_ANOM_FIXED_UPPER_VALUE, default_value=1.0, step=0.0, width=90)
                                dpg.add_combo(tag=ui.MON_ANOM_FIXED_UPPER_UNIT, items=_unit_items, default_value='in/s', width=80)
                                dpg.add_combo(tag=ui.MON_ANOM_FIXED_UPPER_MODE, items=list(_HOOK_MODES), default_value=_ANOM_SEED['fixed_upper_mode'], width=80)
                            _tip(_upper_chk, "Burst when overall vibration rises above this level.")
                            with dpg.group(horizontal=True):
                                _lower_chk = dpg.add_checkbox(label="Lower limit", tag=ui.MON_ANOM_FIXED_LOWER_ENABLED, default_value=False)
                                dpg.add_input_float(tag=ui.MON_ANOM_FIXED_LOWER_VALUE, default_value=0.05, step=0.0, width=90)
                                dpg.add_combo(tag=ui.MON_ANOM_FIXED_LOWER_UNIT, items=_unit_items, default_value='in/s', width=80)
                                dpg.add_combo(tag=ui.MON_ANOM_FIXED_LOWER_MODE, items=list(_HOOK_MODES), default_value=_ANOM_SEED['fixed_lower_mode'], width=80)
                            _tip(_lower_chk, "Burst when overall vibration drops below this level.")
                            _fixed_s_w = dpg.add_input_float(
                                label="Sustained (s)", tag=ui.MON_ANOM_FIXED_S,
                                default_value=0.0, min_value=0.0, max_value=3600.0,
                                step=1.0, width=_mon_w)
                            _tip(_fixed_s_w,
                                 "The overall must stay beyond a limit for this many "
                                 "seconds of consecutive valid frames. 0 fires on the "
                                 "first frame.")

                            # ── Cooldown ────────────────────────────────
                            dpg.add_spacer(height=8)
                            dpg.add_separator()
                            _cooldown_hdr = dpg.add_text("Cooldown  (?)")
                            _tip(_cooldown_hdr,
                                 "Blocks further anomaly-triggered bursts for this long "
                                 "after one fires — keeps long events from cluttering "
                                 "the session with overlapping captures.")
                            dpg.add_checkbox(label="Enable", tag=ui.MON_ANOM_COOLDOWN_ENABLED, default_value=False)
                            dpg.add_input_float(
                                label="Cooldown period (s)", tag=ui.MON_ANOM_COOLDOWN_S,
                                default_value=300.0, min_value=0.0, max_value=86400.0,
                                step=10.0, width=_mon_w,
                            )

            dpg.add_separator()
            dpg.add_button(label=f'{icons.IC["close"]}  Close', callback=self._on_config_close, width=-1)

        # ── Section container theme (slightly lighter than window background) ──
        _sect_bg = rev80.hex_to_rgba(rev80.THEME_COLORS["SURFACE"])
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
        with dpg.window(label="Rev80", tag=ui.PRIMARY_WINDOW):
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
                                label=f'{icons.IC["settings"]}  Setup',
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
                                label=f'{icons.IC["settings"]}  Setup',
                                tag=ui.BTN_CHANNELS_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_CHANNELS),
                            )
                        with dpg.group(horizontal=True):
                            dpg.add_button(
                                label=f'{icons.IC["sensors"]}  Sensor',
                                tag=ui.BTN_SENSOR_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_SENSORS),
                                width=-1,
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
                                label=f'{icons.IC["settings"]}  Setup',
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
                        dpg.add_text(
                            "",
                            tag=ui.SPECTRUM_DEGRADED_WARNING,
                            color=_c("RED_LIGHT"),
                            show=False,
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
                                label=f'{icons.IC["settings"]}  Setup',
                                tag=ui.BTN_MONITOR_SETUP,
                                callback=lambda: self._open_config_dialog(ui.CONFIG_TAB_MONITOR),
                            )
                        dpg.add_separator()
                        dpg.add_button(
                            label=f'{icons.IC["record"]}  Monitor',
                            tag=ui.MONITOR_RECORD_BTN,
                            callback=self._on_record_toggle,
                            width=-1,
                            height=32,
                        )
                        dpg.add_spacer(height=2)
                        dpg.add_button(
                            label=f'{icons.IC["refresh"]}  Reset Baseline',
                            tag=ui.MONITOR_RESET_BTN,
                            callback=self._on_reset_baseline,
                            width=-1,
                            enabled=False,
                        )
                        dpg.add_button(
                            label=f'{icons.IC["photo_camera"]}  Record Burst',
                            tag=ui.MONITOR_BURST_BTN,
                            callback=self._on_manual_burst,
                            width=-1,
                            enabled=False,
                        )
                        dpg.add_spacer(height=2)
                        dpg.add_text("Start stream to record", tag=ui.MONITOR_STATUS_TEXT, color=_c("ON_SURFACE"))
                        dpg.add_spacer(height=4)
                        with dpg.group(horizontal=True):
                            with dpg.drawlist(width=16, height=16, tag=ui.MONITOR_BURST_STATUS):
                                dpg.draw_rectangle(
                                    pmin=(1, 1), pmax=(15, 15),
                                    fill=_c("GREEN"),
                                    color=(0, 0, 0, 0),
                                    rounding=3,
                                    tag=ui.MONITOR_BURST_RECT,
                                )
                            dpg.add_text("Ready", tag=ui.MONITOR_BURST_TEXT, color=_c("ON_SURFACE"))
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

                    # One tab for each chart of the layout in effect.
                    # ChartsView.rebuild() fills it.
                    dpg.add_tab_bar(tag=ui.MAIN_CHART_TAB_BAR,
                                    callback=self._on_chart_tab_change)

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
                    # Primary peak control: a significance threshold, not a
                    # top-N count. A top-N list shows only the loudest part of
                    # the band. See CONTRIBUTING.md, "E12. Peak selection".
                    _pk_thr = dpg.add_input_float(
                        label="Peak Sig., dB",
                        tag=ui.FFT_PEAK_THRESHOLD_DB,
                        default_value=rev80_peaks.DEFAULT_THRESHOLD_DB,
                        min_value=0.0,
                        max_value=60.0,
                        step=0.5,
                        format="%.1f",
                        callback=self._on_peak_threshold_change,
                        width=100,
                    )
                    self._tooltip(
                        _pk_thr,
                        "How far a spectral line must rise above its own local noise "
                        "floor before it is reported, in dB.\n\n"
                        "The noise floor is estimated per bin, so a line in a quiet "
                        "part of the band and a line in a loud one are judged by the "
                        "same standard. Every line that passes is reported — the peak "
                        "count is a result, not a setting.\n\n"
                        "9.5 dB (3x) is the default. Lower admits more, and below "
                        "about 7 dB it admits noise: on pure noise a 6 dB gate reports "
                        "38 peaks per 2000 bins where 9.5 dB reports 0.8.",
                    )
                    _pk_cap = dpg.add_input_int(
                        label="Max Shown",
                        tag=ui.FFT_PEAKS_DISPLAY_COUNT,
                        default_value=DEFAULT_PEAK_DISPLAY_CAP,
                        min_value=1,
                        max_value=500,
                        callback=self._redraw,
                        width=100,
                    )
                    self._tooltip(
                        _pk_cap,
                        "Clutter cap on the table and the plot markers only. It hides "
                        "the smallest of the lines that already passed the "
                        "significance test; it does not decide which lines are real.",
                    )
                    dpg.add_spacer(height=4)

                    # Frame metadata card — hidden until first frame arrives
                    with dpg.child_window(
                        border=True,
                        autosize_x=True,
                        height=_CARD_BASE_H + 3 * _CARD_LINE_H,
                        no_scrollbar=True,
                        tag=ui.FRAME_INFO_SECTION,
                        show=False,
                    ) as _sfi:
                        dpg.bind_item_theme(_sfi, self._sect_theme)
                        dpg.add_text("Frame", color=_c("MUTED"))
                        dpg.add_separator()
                        # Always visible
                        dpg.add_text("Capture Time:\n  —", tag=ui.FRAME_INFO_TIMESTAMP)
                        dpg.add_text("Frame Time: —",      tag=ui.FRAME_INFO_REL_TIME,       show=False)
                        dpg.add_text("Block size: —",      tag=ui.FRAME_INFO_BLOCKSIZE)
                        dpg.add_text("Sample rate: —",     tag=ui.FRAME_INFO_SAMPLERATE)
                        # Burst section
                        dpg.add_text("Burst", color=_c("MUTED"), tag=ui.FRAME_INFO_BURST_HEADER, show=False)
                        dpg.add_separator(tag=ui.FRAME_INFO_BURST_SEP,      show=False)
                        dpg.add_text("Burst Time:\n  —",   tag=ui.FRAME_INFO_TRIGGER_TS,     show=False)
                        dpg.add_text("Trigger type: —",    tag=ui.FRAME_INFO_TRIGGER_TYPE,   show=False)
                        # Session / burst section
                        dpg.add_text("Session", color=_c("MUTED"), tag=ui.FRAME_INFO_SESSION_HEADER, show=False)
                        dpg.add_separator(tag=ui.FRAME_INFO_SESSION_SEP,    show=False)
                        dpg.add_text("Start Time:\n  —",   tag=ui.FRAME_INFO_SESSION_START,  show=False)
                        dpg.add_text("End Time:\n  —",     tag=ui.FRAME_INFO_SESSION_END,    show=False)
                        dpg.add_text("Captures: —",        tag=ui.FRAME_INFO_N_CAPTURES,     show=False)
                        dpg.add_text("Bursts: —",          tag=ui.FRAME_INFO_N_BURSTS,       show=False)
                        dpg.add_text("Capture interval: —", tag=ui.FRAME_INFO_INTERVAL,      show=False)
                    dpg.add_spacer(height=4)

                    # Shaft-speed card of each tachometer channel (hidden
                    # by default; _update_results_section_visibility shows
                    # the enabled ones). A tachometer has no overall, no
                    # spectrum and no engineering unit.
                    for _ch in range(_MAX_CHANNELS):
                        with dpg.child_window(
                            border=True,
                            autosize_x=True,
                            height=_TACH_CARD_HEIGHT,
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
                            with dpg.group(tag=ui.ch_tach_group(_ch)):
                                dpg.add_text("--", tag=ui.ch_tach_rate(_ch))
                                dpg.add_text("", tag=ui.ch_tach_detail(_ch),
                                             color=_c("MUTED"))
                        dpg.add_spacer(height=2)

                    # Result cards of each spectrum chart, one collapsing
                    # header for each chart. ChartsView.rebuild() fills it.
                    dpg.add_group(tag=ui.CHART_CARDS)

        # Last: the tooltips need the locked controls to exist.
        dpg.bind_theme(self._create_disabled_theme())
        self._create_locked_tips()

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _setup_keyboard_handlers(self) -> None:
        """Register global key bindings (Esc closes the open dialog).

        Ctrl+A  autoscale plots
        Ctrl+K  start / stop acquisition
        Ctrl+S  save recording
        Ctrl+O  open / load recording
        Ctrl+Q  quit
        Left / Right  previous / next frame (only when not streaming)
        """
        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self._on_key_press)

    def _on_key_press(self, sender, app_data) -> None:
        key = app_data
        ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)

        if key == dpg.mvKey_Escape:
            # Close whichever modal is currently visible
            if dpg.does_item_exist(ui.DLG_SESSION_BROWSER) and dpg.is_item_shown(ui.DLG_SESSION_BROWSER):
                dpg.configure_item(ui.DLG_SESSION_BROWSER, show=False)
            elif dpg.does_item_exist(ui.DLG_CONFIG) and dpg.is_item_shown(ui.DLG_CONFIG):
                self._on_config_close()
        elif ctrl:
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
        _cfg.ensure_config_dir()
        self._create_gui()
        # Fill the Monitor widgets from acquisition.yaml now. Each dialog
        # close saves them, and a recording reads them, also when the user
        # did not open the Monitor tab.
        try:
            self._populate_monitor_tab()
        except (TypeError, ValueError) as exc:
            log.warning("Monitor config in acquisition.yaml is not valid: %s", exc)
        self._setup_keyboard_handlers()
        self._update_spectrum_info()
        self._update_connection_summary()
        self._charts.rebuild()
        self._refresh_registry_dialog_list()
        self._set_stream_status("idle")  # apply initial toggle button theme
        log.info("Setup GUI")
        dpg.setup_dearpygui()
        # TODO: open the Device tab at startup when no device is found, so the
        #       user does not have to find the menu.
        # self._open_config_dialog(ui.CONFIG_TAB_DEVICE)

    def _load_from_path(self, path_str: str) -> None:
        """Load an h5 file (v5 measurement or v6 monitor session) by path.

        A file with a /monitor group, or a directory with a session.h5, loads
        as a session; any other file as a measurement. Call it after the first
        render frame, so that all plot series exist.
        """
        p = Path(path_str.strip())
        if not p.exists():
            log.error(f"--from-file: path does not exist: {p}")
            return
        # Resolve a session directory to its session.h5
        if p.is_dir():
            candidate = p / "session.h5"
            if candidate.exists():
                p = candidate
            else:
                log.error(f"--from-file: directory has no session.h5: {p}")
                return
        try:
            with h5py.File(str(p), "r") as f:
                is_monitor = "monitor" in f
        except Exception as exc:
            log.error(f"--from-file: cannot open {p}: {exc}")
            return

        log.info(f"--from-file: loading {'monitor session' if is_monitor else 'measurement'} {p}")
        if is_monitor:
            new = self._load_into_new_collector(
                lambda c: c.load_monitor_session(p), f"--from-file {p}")
            if new is None or not self._replace_collector(new):
                return
            self._current_session_h5 = p
            self._autoscale_plots()
        else:
            self._on_load_file(p)

    def run(self, initial_file: str | None = None, autodetect: bool = True):
        log.info("Launch app window")
        dpg.create_viewport(title="Rev80", width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        dpg.show_viewport()
        dpg.set_primary_window(ui.PRIMARY_WINDOW, True)
        if autodetect:
            threading.Thread(target=self._autoconnect, daemon=True).start()
        log.info("Start DPG backend")
        _loaded = not initial_file   # False = load pending after first frame
        while dpg.is_dearpygui_running():
            # Guarded: an exception must not leave run() without cleanup().
            # Otherwise ps4000aCloseUnit is not called, and the next launch
            # fails with PICO_NOT_FOUND until the USB is replugged. A bad .h5
            # file then gives a logged error, not a crash.
            try:
                if not _loaded:
                    # Defer one frame so all DPG series are fully initialised
                    dpg.render_dearpygui_frame()
                    self._load_from_path(initial_file)
                    _loaded = True
                    continue
                # gui.frame is the whole loop body; gui.render is dearpygui only.
                # A long render with a short proc.total points to the
                # acquisition thread (GIL); the reverse points to the DSP.
                with _profile.timed(_profile.GUI_FRAME):
                    self._poll_new_frames()
                    with _profile.timed(_profile.GUI_RENDER):
                        dpg.render_dearpygui_frame()
                self._note_render_success()
            except Exception as exc:                         # noqa: BLE001
                if not self._handle_render_error(exc):
                    break

    #: Consecutive failed render frames before a clean shutdown (which closes
    #: the device). A short burst of bad frames does not stop the app.
    MAX_CONSECUTIVE_RENDER_ERRORS: int = 30

    def _handle_render_error(self, exc: BaseException) -> bool:
        """Record a render-loop failure. Returns True to keep rendering.

        Logs one traceback for each exception type. Repeats are counted and
        summarised at shutdown, because a traceback for each frame would push
        all other entries out of the rotating log.
        """
        key = type(exc).__name__
        seen = self._render_errors.get(key, 0)
        self._render_errors[key] = seen + 1
        if seen == 0:
            log.error('Exception in render loop (further %s suppressed): %s',
                      key, exc, exc_info=exc)
        self._consecutive_render_errors += 1
        if self._consecutive_render_errors >= self.MAX_CONSECUTIVE_RENDER_ERRORS:
            log.error(
                'Render loop failed %d consecutive frames — shutting down '
                'cleanly so the device is closed properly. Error counts: %s',
                self._consecutive_render_errors, dict(self._render_errors),
            )
            return False
        return True

    def _note_render_success(self) -> None:
        """A frame rendered. Clears the consecutive-failure streak."""
        self._consecutive_render_errors = 0

    def cleanup(self):
        """Shut down in order: stop the monitor, close the device, destroy the DPG context.

        Idempotent. The writer is a daemon thread and loses queued captures at
        exit, so the monitor stops first. Each step has its own guard: a writer
        that hangs must not prevent ps4000aCloseUnit, because a device left open
        makes the next launch fail with PICO_NOT_FOUND until the USB is replugged.
        """
        if getattr(self, '_cleaned_up', False):
            return
        self._cleaned_up = True
        log.info("Cleanup app assets")

        monitor = getattr(self, '_monitor', None)
        if monitor is not None and getattr(monitor, 'is_recording', False):
            try:
                log.info("Stopping monitor session and flushing writer")
                monitor.stop()
            except Exception:                                # noqa: BLE001
                log.exception('Monitor failed to stop cleanly — continuing so '
                              'the device is still closed')

        try:
            self.collector.disconnect_sensor()
        except Exception:                                    # noqa: BLE001
            log.exception('disconnect_sensor() failed during cleanup')

        # getattr: cleanup() runs from main()'s finally and must survive a GUI
        # that failed partway through construction. It is the one method that
        # cannot be allowed to raise — it is what closes the device.
        render_errors = getattr(self, '_render_errors', None)
        if render_errors:
            log.warning('Render loop error totals this session: %s',
                        dict(render_errors))

        # The profile table, if --profile was given. Guarded and placed after
        # disconnect_sensor for the same reason every other step here is: a
        # diagnostic must never be what prevents ps4000aCloseUnit from running.
        if _profile.is_enabled():
            try:
                log.info('\n%s', _profile.report('pipeline profile (session)'))
            except Exception:                                # noqa: BLE001
                log.exception('Failed to emit the pipeline profile')

        try:
            dpg.destroy_context()
        except Exception:                                    # noqa: BLE001
            log.exception('destroy_context() failed during cleanup')
        log.info("App Exit")

    def serve(self):
        self.initialize()
        self.run()
        self.cleanup()
