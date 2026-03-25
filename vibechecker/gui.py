# Vibechecker frontend

import threading
import dearpygui.dearpygui as dpg

from path import Path
import sounddevice

import numpy as np
import pandas as pd

import vibechecker
from vibechecker.scope_sensor import ScopeSensor
from vibechecker.scope_sensor_registry import ScopeSensorRegistry

log = vibechecker.get_logger('gui')
ui = vibechecker.UI_Elements()

# Layout constants
WINDOW_WIDTH    = 1500
WINDOW_HEIGHT   = 1000
CONTROLS_WIDTH  = 300
RESULTS_WIDTH   = 300
TIME_PLOT_HEIGHT = 300

_MAX_CHANNELS         = 8
_DEFAULT_NUM_CHANNELS = 4

def _c(key: str, alpha: int = 255) -> tuple:
    """Shorthand: THEME_COLORS[key] → DPG RGBA tuple."""
    return vibechecker.hex_to_rgba(vibechecker.THEME_COLORS[key], alpha)

_CH_COLORS = [
    _c('WHITE'),  # Ch A
    _c('ORANGE'),  # Ch B
    _c('LIME'),    # Ch C
    _c('CORAL'),   # Ch D
    _c('CYAN'),    # Ch E
    _c('VIOLET'),  # Ch F
    _c('GOLD'),    # Ch G
    _c('SILVER'),  # Ch H
]

# Spectrum dialog display labels — index-aligned with MAXFREQS / BINSIZES
_MAXFREQ_LABELS = [f'{int(f)} Hz' for f in vibechecker.MAXFREQS]
_BINSIZE_LABELS  = [f'{b} Hz/bin' for b in vibechecker.BINSIZES]


class GUI:
    collector: vibechecker.DataCollector
    found_sensors: list

    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()
        self.collector.callbacks['plots'] = self.display_frame
        self.registry = ScopeSensorRegistry()
        self._editing_scope_sensor_id: str | None = None
        self._num_channels: int = _DEFAULT_NUM_CHANNELS
        self._channel_themes: list = []
        self._status_timer: threading.Timer | None = None
        self.found_sensors: list = []

    # ------------------------------------------------------------------
    # Status indicator helpers
    # ------------------------------------------------------------------

    def _set_device_status(self, state: str):
        """Update the device connection indicator: 'connected' | 'disconnected'."""
        if dpg.does_item_exist(ui.DEVICE_STATUS_RECT):
            color = _c('GREEN') if state == 'connected' else _c('RED')
            dpg.configure_item(ui.DEVICE_STATUS_RECT, fill=color)
        if dpg.does_item_exist(ui.CONN_STATUS_TEXT):
            dpg.set_value(ui.CONN_STATUS_TEXT,
                          'Connected' if state == 'connected' else 'Not Connected')

    def _set_stream_status(self, state: str):
        """Update the stream indicator and toggle button: 'active'|'waiting'|'idle'."""
        if dpg.does_item_exist(ui.STREAM_STATUS_RECT):
            color_map = {
                'active':  _c('GREEN'),
                'waiting': _c('YELLOW'),
                'idle':    _c('RED'),
            }
            dpg.configure_item(ui.STREAM_STATUS_RECT,
                                fill=color_map.get(state, _c('RED')))
        if dpg.does_item_exist(ui.ACQ_TOGGLE):
            label_map = {'active': 'Running', 'waiting': 'Waiting', 'idle': 'Stopped'}
            dpg.set_item_label(ui.ACQ_TOGGLE, label_map.get(state, 'Stopped'))

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
            self._set_stream_status('waiting')

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

    def _update_axis_assignment(self):
        """Show/hide secondary axes and reassign series based on unit groups."""
        groups = self._get_unit_groups()
        if len(groups) <= 1:
            dpg.hide_item(ui.PLT_FREQ_AX_2)
            dpg.hide_item(ui.PLT_SAMPLE_AX_ACCEL_2)
            for ch in self.collector.config.enabled_channels:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL,
                                              ui.PLT_SAMPLE_AX_ACCEL)
            unit = groups[0][0] if groups else 'mV'
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL, unit)
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL, unit)
        else:
            dpg.show_item(ui.PLT_FREQ_AX_2)
            dpg.show_item(ui.PLT_SAMPLE_AX_ACCEL_2)
            for ch in groups[0][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL,
                                              ui.PLT_SAMPLE_AX_ACCEL)
            for ch in groups[1][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_2,
                                              ui.PLT_SAMPLE_AX_ACCEL_2)
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL,      groups[0][0])
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL,    groups[0][0])
            dpg.set_item_label(ui.PLT_FREQ_AX_2,          groups[1][0])
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL_2,  groups[1][0])

    def _reassign_series_to_axis(self, ch: int, freq_axis: str, time_axis: str):
        """If a channel's series are on wrong axes, delete and recreate them."""
        freq_tag = ui.plt_freq_series(ch)
        time_tag = ui.plt_time_series(ch)
        wrong = False
        if dpg.does_item_exist(freq_tag):
            if dpg.get_item_parent(freq_tag) != dpg.get_alias_id(freq_axis):
                wrong = True
        if dpg.does_item_exist(time_tag):
            if dpg.get_item_parent(time_tag) != dpg.get_alias_id(time_axis):
                wrong = True
        if wrong:
            self._remove_channel_series(ch)
            self._add_channel_series(ch, freq_axis=freq_axis, time_axis=time_axis)

    # ------------------------------------------------------------------
    # Plot update helpers
    # ------------------------------------------------------------------

    def _update_fft_peaks_table(self, df: pd.DataFrame):
        children = dpg.get_item_children(ui.FFT_PEAKS_TABLE)
        if isinstance(children, dict):
            for sub in children.values():
                for tag in sub:
                    dpg.delete_item(tag)
        df = df.head(n=dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT))
        for i in range(df.shape[1]):
            dpg.add_table_column(label=df.columns[i], parent=ui.FFT_PEAKS_TABLE)
        for i in range(df.shape[0]):
            with dpg.table_row(parent=ui.FFT_PEAKS_TABLE):
                for j in range(df.shape[1]):
                    dpg.add_text(f'{df.iloc[i, j]}')

    def _compute_channel_result(self, ch: int,
                                 sample: vibechecker.VibeSample
                                 ) -> vibechecker.ChannelResult | None:
        """Compute a ChannelResult from a raw VibeSample in one call.

        Calls sample.get_accel() and sample.fft() once each; applies the
        trend frequency window from config to compute overall vibration.
        Returns None if the sample is empty or FFT fails.
        """
        target_unit = self.collector.get_active_eu(ch)
        acc_df, _   = sample.get_accel(target_unit)
        fft_df, peaks = sample.fft(target_unit, self.collector.config)
        if fft_df is None or peaks is None:
            return None

        freq     = fft_df.freq.to_numpy()
        spectrum = fft_df.display_0p.to_numpy()

        # Overall amplitude over the configured trend frequency window
        cfg  = self.collector.config
        fmin = cfg.trend_fmin
        fmax = min(cfg.trend_fmax, cfg.maxfreq) if cfg.trend_fmax is not None \
               else cfg.maxfreq
        mask = (freq >= fmin) & (freq <= fmax)
        band = spectrum[mask] if mask.any() else spectrum
        overall = float(np.sqrt(np.sum(np.square(band))) * np.sqrt(2) / 2)

        return vibechecker.ChannelResult(
            channel=ch,
            unit=target_unit,
            time_data=acc_df.signal.to_numpy(),
            time_vec=acc_df.time.to_numpy(),
            samplerate=sample.samplerate,
            freq=freq,
            spectrum=spectrum,
            peaks=peaks,
            overall=overall,
            timestamp=sample._timestamp,
            rel_time=sample.rel_time,
            status=sample.status,
        )

    def _update_time_plot(self, result: vibechecker.ChannelResult, ch: int):
        if not dpg.does_item_exist(ui.plt_time_series(ch)):
            return
        time   = result.time_vec
        signal = result.time_data
        dpg.set_value(ui.plt_time_series(ch), [time.tolist(), signal.tolist()])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_TIME, float(time[0]), float(time[-1]))
        y_axis = self._get_time_axis_for(ch)
        sig_min, sig_max = float(np.min(signal)), float(np.max(signal))
        if sig_min == sig_max:
            sig_min -= 1.0
            sig_max += 1.0
        dpg.set_axis_limits(y_axis, sig_min, sig_max)

    def _update_freq_plot(self, result: vibechecker.ChannelResult, ch: int):
        if not dpg.does_item_exist(ui.plt_freq_series(ch)):
            return
        freq     = result.freq
        spectrum = result.spectrum
        dpg.set_value(ui.plt_freq_series(ch), [freq.tolist(), spectrum.tolist()])
        dpg.set_value(ui.PLT_SAMPLE_OVERALL, f'{result.overall:.4f}')
        dpg.set_axis_limits(ui.PLT_FREQ_AX_FREQ, float(freq[0]), float(freq[-1]))
        y_axis = self._get_freq_axis_for(ch)
        y_max  = float(np.max(spectrum)) if len(spectrum) > 0 else 0.0
        dpg.set_axis_limits(y_axis, 0.0, 1.05 * y_max if y_max > 0 else 1.0)
        peak_limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        peaks = result.peaks
        if len(peaks) > 0:
            top_peaks = peaks[:peak_limit]
            dpg.set_value(ui.plt_freq_peaks(ch), [freq[top_peaks].tolist()])
            if ch == 0:
                peak_df = pd.DataFrame({
                    'Frequency (Hz)': np.round(freq[top_peaks], 2),
                    result.unit:      np.round(spectrum[top_peaks], 6),
                })
                self._update_fft_peaks_table(peak_df)
        else:
            dpg.set_value(ui.plt_freq_peaks(ch), [[]])

    def _update_trend_plot(self):
        """Refresh the trend plot from DataCollector's trend store."""
        all_times: list[float] = []
        for ch in self.collector.config.enabled_channels:
            tag = ui.plt_trend_series(ch)
            if not dpg.does_item_exist(tag):
                continue
            td = self.collector.data['trend'].get(ch, {})
            times   = td.get('rel_times', [])
            overall = td.get('overall', [])
            if times:
                dpg.set_value(tag, [times, overall])
                all_times.extend(times)
            else:
                dpg.set_value(tag, [[0.], [0.]])
        if all_times and dpg.does_item_exist(ui.PLT_TREND_AX_TIME):
            dpg.set_axis_limits(ui.PLT_TREND_AX_TIME,
                                min(all_times), max(all_times))

    def _update_browse_label(self):
        """Refresh the frame-browser label and enable/disable nav buttons."""
        if not dpg.does_item_exist(ui.ACQ_BROWSE_LABEL):
            return
        cache  = self.collector.data['frame_cache']
        n      = len(cache)
        cursor = self.collector._cache_cursor
        label  = f'Frame {n - cursor} / {n}' if n else 'No frames'
        dpg.set_value(ui.ACQ_BROWSE_LABEL, label)
        can_browse = (not self.collector.is_streaming) and n > 1
        for tag in [ui.ACQ_BROWSE_PREV, ui.ACQ_BROWSE_NEXT]:
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=can_browse)

    def display_frame(self, samples: dict):
        """Compute ChannelResults from raw samples and update all GUI plots."""
        if self.collector.is_streaming:
            self._set_stream_status('active')
            self._schedule_status_timeout()
        for ch, sample in samples.items():
            if sample.blocksize <= 1:
                continue
            result = self._compute_channel_result(ch, sample)
            if result is None:
                continue
            self._update_time_plot(result, ch)
            self._update_freq_plot(result, ch)
            self.collector.update_trend(ch, result.rel_time, result.overall)
        self._update_trend_plot()
        self._update_browse_label()

    def _redraw(self, sender=None, data=None):
        if not self.collector.is_streaming:
            self.collector.reprocess_last_block()

    # ------------------------------------------------------------------
    # Channel series management
    # ------------------------------------------------------------------

    def _add_channel_series(self, ch: int,
                             freq_axis: str = ui.PLT_FREQ_AX_ACCEL,
                             time_axis: str = ui.PLT_SAMPLE_AX_ACCEL):
        ch_label = f'Ch {chr(65 + ch)}'
        theme = self._channel_themes[ch % len(self._channel_themes)]
        for tag, axis in [
            (ui.plt_time_series(ch),  time_axis),
            (ui.plt_freq_series(ch),  freq_axis),
            (ui.plt_trend_series(ch), ui.PLT_TREND_AX_OVERALL),
        ]:
            if not dpg.does_item_exist(tag):
                dpg.add_line_series([0.], [0.], label=ch_label,
                                    tag=tag, parent=axis)
                dpg.bind_item_theme(tag, theme)
        peaks_tag = ui.plt_freq_peaks(ch)
        if not dpg.does_item_exist(peaks_tag):
            dpg.add_inf_line_series([0.], label=f'Peaks {chr(65+ch)}',
                                    tag=peaks_tag, parent=freq_axis)

    def _remove_channel_series(self, ch: int):
        for tag in [ui.plt_time_series(ch), ui.plt_freq_series(ch),
                    ui.plt_trend_series(ch), ui.plt_freq_peaks(ch)]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

    # ------------------------------------------------------------------
    # Connection summary (left panel display)
    # ------------------------------------------------------------------

    def _update_connection_summary(self):
        """Refresh device name and per-channel lines in the left panel."""
        if self.collector.sensor is not None:
            self._set_device_status('connected')
            if dpg.does_item_exist(ui.CONN_DEVICE_NAME):
                dpg.set_value(ui.CONN_DEVICE_NAME,
                              self.collector.sensor.model_name)
        else:
            self._set_device_status('disconnected')
            if dpg.does_item_exist(ui.CONN_DEVICE_NAME):
                dpg.set_value(ui.CONN_DEVICE_NAME, '')

        if dpg.does_item_exist(ui.CONN_CHANNEL_SUMMARY):
            dpg.delete_item(ui.CONN_CHANNEL_SUMMARY, children_only=True)
            if self.collector.sensor is not None:
                for ch in sorted(self.collector.config.enabled_channels):
                    scope_s = self.collector.scope_sensors.get(ch)
                    sname   = scope_s.name if scope_s else '(none)'
                    tunit   = self.collector.get_active_eu(ch)
                    dpg.add_text(
                        f'Ch {chr(65+ch)} : {sname} : {tunit}',
                        parent=ui.CONN_CHANNEL_SUMMARY,
                    )

    # ------------------------------------------------------------------
    # Spectrum info display
    # ------------------------------------------------------------------

    def _update_spectrum_info(self):
        """Refresh the read-only spectrum parameter block."""
        cfg = self.collector.config
        n_bins = cfg.blocksize // cfg.oversample
        fs_ks  = cfg.samplerate / 1000
        t_col  = cfg.acquisition_period
        info = (
            f'{cfg.maxfreq:.0f} Hz  (max freq)\n'
            f'{n_bins} bins\n'
            f'{cfg.binsize:.2f} Hz/bin\n'
            f'{cfg.blocksize} samples\n'
            f'Sample Rate: {fs_ks:.1f} kS/sec\n'
            f'Collection time: {t_col:.3f} sec'
        )
        if dpg.does_item_exist(ui.SPECTRUM_INFO_TEXT):
            dpg.set_value(ui.SPECTRUM_INFO_TEXT, info)

    # ------------------------------------------------------------------
    # Acquisition toggle
    # ------------------------------------------------------------------

    def _toggle_acquisition(self, sender=None, data=None):
        if self.collector.is_streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        if self.collector.stream is None:
            log.warning('Connect a device before starting acquisition')
            return
        self._set_stream_status('waiting')
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
        self._set_stream_status('idle')

    def _collect_sample(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect a device before collecting')
            return
        self._set_stream_status('waiting')
        samples = self.collector.collect_sample()
        self._set_stream_status('idle')
        if samples:
            self.display_frame(samples)

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _on_browse_prev(self, sender=None, data=None):
        """Browse to an older cached frame."""
        self.collector.browse_frame(+1)

    def _on_browse_next(self, sender=None, data=None):
        """Browse to a newer cached frame."""
        self.collector.browse_frame(-1)

    def _on_save_click(self, sender=None, data=None):
        dpg.show_item(ui.DLG_SAVE_FILE)

    def _on_save_dialog(self, sender, data):
        path_str = data.get('file_path_name', '')
        if not path_str:
            return
        p = Path(path_str)
        if not p.suffix:
            p = p.with_suffix(vibechecker.EXT)
        self.collector.save_data(p)

    def _on_load_dialog(self, sender, data):
        path_str = data.get('file_path_name', '')
        if not path_str:
            return
        self.collector.load_data(Path(path_str))

    # ------------------------------------------------------------------
    # Device Setup Dialog
    # ------------------------------------------------------------------

    def _open_device_setup_dialog(self, sender=None, data=None):
        dpg.show_item(ui.DLG_DEVICE_SETUP)
        self._start_device_discovery()

    def _start_device_discovery(self, sender=None, data=None):
        """Clear device list, show placeholder, then discover in a background thread."""
        if dpg.does_item_exist('DEVSETUP_DEVICE_LIST_GROUP'):
            dpg.delete_item('DEVSETUP_DEVICE_LIST_GROUP', children_only=True)
            dpg.add_text('... Populating sensor list ...',
                         parent='DEVSETUP_DEVICE_LIST_GROUP')
        threading.Thread(target=self._discover_devices, daemon=True).start()

    def _discover_devices(self):
        """Background: find sensors then update the Device Setup dialog."""
        self.found_sensors = vibechecker.VibeSensor.find()
        # Real hardware first, simulated last
        self.found_sensors.sort(key=lambda s: getattr(s, 'is_simulation', False))
        self._repopulate_device_list()
        self._rebuild_device_channel_rows()

    def _repopulate_device_list(self):
        """Rebuild the detected-device rows inside the Device Setup dialog."""
        if not dpg.does_item_exist('DEVSETUP_DEVICE_LIST_GROUP'):
            return
        dpg.delete_item('DEVSETUP_DEVICE_LIST_GROUP', children_only=True)
        for sensor in self.found_sensors:
            is_connected = (
                self.collector.sensor is not None
                and self.collector.sensor.device_id == sensor.device_id
            )
            btn_label = 'Disconnect' if is_connected else 'Connect'
            with dpg.group(horizontal=True,
                           parent='DEVSETUP_DEVICE_LIST_GROUP'):
                dpg.add_button(label=btn_label, user_data=sensor,
                               callback=self._on_device_connect_toggle)
                dpg.add_text(f'{sensor.model_name}  s/n {sensor.serial_number}')

    def _rebuild_device_channel_rows(self):
        """Rebuild per-channel rows inside the Device Setup dialog."""
        if not dpg.does_item_exist('DEVSETUP_CHANNEL_GROUP'):
            return
        for ch in range(_MAX_CHANNELS):
            for tag in [ui.scope_ch_enabled(ch), ui.scope_ch_sensor(ch)]:
                if dpg.does_alias_exist(tag):
                    dpg.remove_alias(tag)
        dpg.delete_item('DEVSETUP_CHANNEL_GROUP', children_only=True)
        if self.collector.sensor is None:
            dpg.add_text('No device connected.',
                         parent='DEVSETUP_CHANNEL_GROUP')
            return
        sensor_items = ['(none)'] + self.registry.names()
        enabled_set  = set(self.collector.config.enabled_channels)
        for ch in range(self._num_channels):
            ch_letter   = chr(65 + ch)
            is_enabled  = ch in enabled_set
            scope_s     = self.collector.scope_sensors.get(ch)
            default_s   = scope_s.name if scope_s else '(none)'
            with dpg.group(horizontal=True,
                           parent='DEVSETUP_CHANNEL_GROUP'):
                dpg.add_checkbox(
                    label=f'Ch {ch_letter}',
                    tag=ui.scope_ch_enabled(ch),
                    default_value=is_enabled,
                    callback=lambda s, d, c=ch: self._on_channel_enable_change(c),
                )
                dpg.add_combo(
                    label='',
                    tag=ui.scope_ch_sensor(ch),
                    items=sensor_items,
                    default_value=default_s,
                    width=-1,
                    callback=lambda s, d, c=ch: self._on_sensor_combo_change(c, d),
                )

    def _on_device_connect_toggle(self, sender, data, user_data):
        """Connect or disconnect a device row in the Device Setup dialog."""
        sensor = user_data
        if (self.collector.sensor is not None
                and self.collector.sensor.device_id == sensor.device_id):
            self.collector.disconnect_sensor()
            self._set_device_status('disconnected')
            self._set_stream_status('idle')
        else:
            if self.collector.sensor is not None:
                self.collector.disconnect_sensor()
            try:
                self.collector.connect_sensor(sensor)
                self._num_channels = sensor.num_channels
                self._restore_channel_assignments()
                self.collector.reconnect_stream()
                self._set_device_status('connected')
            except sounddevice.PortAudioError as e:
                log.warning(f'Device connect failed: {e}')
                self.collector.disconnect_sensor()
        self._repopulate_device_list()
        self._rebuild_device_channel_rows()

    def _on_device_setup_close(self, sender=None, data=None):
        self._save_channel_assignments()
        self._update_connection_summary()
        self._update_spectrum_info()
        self._update_axis_assignment()
        self.collector.init_trend_channels()
        self.collector.clear_trend()
        self.collector.reprocess_last_block()
        dpg.hide_item(ui.DLG_DEVICE_SETUP)

    # ------------------------------------------------------------------
    # Spectrum Setup Dialog
    # ------------------------------------------------------------------

    def _open_spectrum_dialog(self, sender=None, data=None):
        cfg = self.collector.config
        curr_mf = f'{int(cfg.maxfreq)} Hz'
        curr_bs = f'{cfg.binsize} Hz/bin'
        if dpg.does_item_exist(ui.SPEC_DLG_MAXFREQ):
            if curr_mf in _MAXFREQ_LABELS:
                dpg.set_value(ui.SPEC_DLG_MAXFREQ, curr_mf)
        if dpg.does_item_exist(ui.SPEC_DLG_BINSIZE):
            if curr_bs in _BINSIZE_LABELS:
                dpg.set_value(ui.SPEC_DLG_BINSIZE, curr_bs)
        if dpg.does_item_exist(ui.SPEC_DLG_TREND_FMIN):
            dpg.set_value(ui.SPEC_DLG_TREND_FMIN, cfg.trend_fmin)
        if dpg.does_item_exist(ui.SPEC_DLG_TREND_FMAX):
            dpg.set_value(ui.SPEC_DLG_TREND_FMAX,
                          cfg.trend_fmax if cfg.trend_fmax is not None else 0.0)
        dpg.show_item(ui.DLG_SPECTRUM_SETUP)

    def _on_spectrum_apply(self, sender=None, data=None):
        mf_str = dpg.get_value(ui.SPEC_DLG_MAXFREQ)
        bs_str = dpg.get_value(ui.SPEC_DLG_BINSIZE)
        try:
            maxfreq = vibechecker.MAXFREQS[_MAXFREQ_LABELS.index(mf_str)]
        except (ValueError, IndexError):
            maxfreq = self.collector.config.maxfreq
        try:
            binsize = vibechecker.BINSIZES[_BINSIZE_LABELS.index(bs_str)]
        except (ValueError, IndexError):
            binsize = self.collector.config.binsize
        trend_fmin = float(dpg.get_value(ui.SPEC_DLG_TREND_FMIN) or 0.0)
        trend_fmax = float(dpg.get_value(ui.SPEC_DLG_TREND_FMAX) or 0.0)

        was_streaming = self.collector.is_streaming
        if was_streaming:
            self._stop_stream()
        self.collector.config.maxfreq = maxfreq
        self.collector.config.binsize = binsize
        self.collector.config.trend_fmin = trend_fmin
        self.collector.config.trend_fmax = trend_fmax if trend_fmax > 0 else None
        if self.collector.sensor is not None:
            self.collector.reconnect_stream()
        if was_streaming:
            self._start_stream()
        else:
            self.collector.clear_trend()
            self.collector.reprocess_last_block()
        self._update_spectrum_info()
        dpg.hide_item(ui.DLG_SPECTRUM_SETUP)

    # ------------------------------------------------------------------
    # Sensor Registry Dialog
    # ------------------------------------------------------------------

    def _open_sensor_registry_dialog(self, sender=None, data=None):
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
        dpg.show_item(ui.DLG_SENSOR_REGISTRY)

    def _refresh_registry_dialog_list(self):
        """Refresh the sensor list in the registry dialog + channel dropdowns."""
        names = self.registry.names()
        if dpg.does_item_exist(ui.SCOPE_REGISTRY_LIST):
            dpg.configure_item(ui.SCOPE_REGISTRY_LIST, items=names)
        sensor_items = ['(none)'] + names
        for ch in range(self._num_channels):
            tag = ui.scope_ch_sensor(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, items=sensor_items)

    def _load_registry_sensor_fields(self, sensor: ScopeSensor | None):
        if not dpg.does_item_exist('SREG_FIELD_NAME'):
            return
        if sensor is None:
            dpg.set_value('SREG_FIELD_NAME', '')
            dpg.set_value('SREG_FIELD_UNITS', 'g')
            dpg.set_value('SREG_FIELD_TARGET', '')
            dpg.set_value('SREG_FIELD_SENS', 0.0)
            dpg.set_value('SREG_FIELD_NOTES', '')
        else:
            dpg.set_value('SREG_FIELD_NAME', sensor.name)
            dpg.set_value('SREG_FIELD_UNITS', sensor.engineering_units)
            dpg.set_value('SREG_FIELD_TARGET', sensor.target_unit or '')
            dpg.set_value('SREG_FIELD_SENS', float(sensor.sensitivity))
            dpg.set_value('SREG_FIELD_NOTES', sensor.notes or '')

    def _save_registry_sensor_fields(self):
        """Persist the right-pane fields to the registry if a sensor is selected."""
        if self._editing_scope_sensor_id is None:
            return
        if not dpg.does_item_exist('SREG_FIELD_NAME'):
            return
        name = dpg.get_value('SREG_FIELD_NAME').strip()
        if not name:
            return
        sensor = ScopeSensor(
            name=name,
            engineering_units=dpg.get_value('SREG_FIELD_UNITS'),
            sensitivity=float(dpg.get_value('SREG_FIELD_SENS')),
            target_unit=dpg.get_value('SREG_FIELD_TARGET'),
            id=self._editing_scope_sensor_id,
            notes=dpg.get_value('SREG_FIELD_NOTES').strip(),
        )
        try:
            self.registry.update(sensor)
        except KeyError:
            pass
        self._refresh_registry_dialog_list()

    def _on_registry_sensor_select(self, sender, data):
        self._save_registry_sensor_fields()
        name   = dpg.get_value(ui.SCOPE_REGISTRY_LIST)
        sensor = self.registry.find_by_name(name) if name else None
        self._editing_scope_sensor_id = sensor.id if sensor else None
        self._load_registry_sensor_fields(sensor)

    def _on_registry_add(self, sender=None, data=None):
        self._save_registry_sensor_fields()
        new_sensor = ScopeSensor(name='New Sensor', engineering_units='g',
                                 sensitivity=100.0, target_unit='g')
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

    def _on_registry_close(self, sender=None, data=None):
        self._save_registry_sensor_fields()
        self._refresh_assigned_sensors()
        self._update_connection_summary()
        self._update_axis_assignment()
        self.collector.clear_trend()
        self.collector.reprocess_last_block()
        dpg.hide_item(ui.DLG_SENSOR_REGISTRY)

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
        assignments = {
            c: {
                'enabled':   c in self.collector.config.enabled_channels,
                'sensor_id': self.collector.scope_sensors[c].id
                             if c in self.collector.scope_sensors else None,
            }
            for c in range(self._num_channels)
        }
        self.registry.save_channel_assignments(assignments)

    def _on_channel_enable_change(self, ch: int):
        if not dpg.does_item_exist(ui.scope_ch_enabled(ch)):
            return
        enabled = dpg.get_value(ui.scope_ch_enabled(ch))
        if enabled:
            if ch not in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.append(ch)
                self.collector.config.enabled_channels.sort()
            self._add_channel_series(ch)
        else:
            self.collector.config.enabled_channels = [
                c for c in self.collector.config.enabled_channels if c != ch
            ]
            self._remove_channel_series(ch)
        self._save_channel_assignments()
        self._update_connection_summary()
        self._update_axis_assignment()
        self.collector.reconnect_stream()

    def _redraw_all_channels(self):
        """Re-display the current cached frame for all enabled channels."""
        if not self.collector.is_streaming:
            self.collector.reprocess_last_block()

    def _on_sensor_combo_change(self, ch: int, sensor_name: str):
        if not dpg.does_item_exist(ui.scope_ch_sensor(ch)):
            return
        sensor = (None if (not sensor_name or sensor_name == '(none)')
                  else self.registry.find_by_name(sensor_name))
        self.collector.set_scope_sensor(ch, sensor)
        self._save_channel_assignments()
        self._update_connection_summary()
        self._update_axis_assignment()
        self._redraw_all_channels()

    def _restore_channel_assignments(self):
        """Apply saved channel assignments to the collector and any open dialog widgets."""
        assignments = self.registry.load_channel_assignments()
        for ch, info in assignments.items():
            if ch >= self._num_channels:
                continue
            sensor_id = info.get('sensor_id')
            enabled   = info.get('enabled', True)
            sensor    = self.registry.find_by_id(sensor_id) if sensor_id else None
            self.collector.set_scope_sensor(ch, sensor)
            if enabled and ch not in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.append(ch)
            elif not enabled and ch in self.collector.config.enabled_channels:
                self.collector.config.enabled_channels.remove(ch)
            if dpg.does_item_exist(ui.scope_ch_enabled(ch)):
                dpg.set_value(ui.scope_ch_enabled(ch), enabled)
            if sensor and dpg.does_item_exist(ui.scope_ch_sensor(ch)):
                dpg.set_value(ui.scope_ch_sensor(ch), sensor.name)
            if enabled:
                self._add_channel_series(ch)
            else:
                self._remove_channel_series(ch)
        self.collector.config.enabled_channels.sort()
        for ch in self.collector.config.enabled_channels:
            if ch < self._num_channels:
                self._add_channel_series(ch)
        self._update_axis_assignment()

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def create_gui(self):
        dpg.create_context()

        # File dialogs
        with dpg.file_dialog(
                show=False,
                default_path=str(vibechecker.SAVEDIR),
                callback=self._on_save_dialog,
                tag=ui.DLG_SAVE_FILE,
                width=700, height=400):
            dpg.add_file_extension(
                f'Vibe Samples (*{vibechecker.EXT}){{{vibechecker.EXT}}}',
                color=(150, 255, 150, 255))
            dpg.add_file_extension('.*', color=(0, 150, 150, 150))

        with dpg.file_dialog(
                show=False,
                default_path=str(vibechecker.SAVEDIR),
                callback=self._on_load_dialog,
                tag=ui.DLG_LOAD_FILE,
                width=700, height=400):
            dpg.add_file_extension(
                f'Vibe Samples (*{vibechecker.EXT}){{{vibechecker.EXT}}}',
                color=(150, 255, 150, 255))
            dpg.add_file_extension('.*', color=(0, 150, 150, 150))

        # ── Device Setup Dialog ────────────────────────────────────────
        _dlg_dev_w, _dlg_dev_h = 520, 520
        with dpg.window(label='Device Setup', modal=True, show=False,
                        tag=ui.DLG_DEVICE_SETUP, width=_dlg_dev_w, height=_dlg_dev_h,
                        pos=((WINDOW_WIDTH - _dlg_dev_w) // 2,
                             (WINDOW_HEIGHT - _dlg_dev_h) // 2)):
            with dpg.group(horizontal=True):
                dpg.add_text('Detected Devices')
                dpg.add_spacer(width=286)
                dpg.add_button(label='Refresh', small=True,
                               callback=self._start_device_discovery)
            with dpg.group(tag='DEVSETUP_DEVICE_LIST_GROUP'):
                pass
            dpg.add_separator()
            dpg.add_text('Channel Configuration')
            with dpg.group(tag='DEVSETUP_CHANNEL_GROUP'):
                dpg.add_text('No device connected.')
            dpg.add_separator()
            dpg.add_button(label='Close', callback=self._on_device_setup_close,
                           width=-1)

        # ── Spectrum Setup Dialog ──────────────────────────────────────
        _dlg_spec_w = 280
        with dpg.window(label='Spectrum Setup', modal=True, show=False,
                        tag=ui.DLG_SPECTRUM_SETUP, width=_dlg_spec_w,
                        pos=((WINDOW_WIDTH - _dlg_spec_w) // 2, 200)):
            dpg.add_text('Max Frequency')
            dpg.add_listbox(items=_MAXFREQ_LABELS, tag=ui.SPEC_DLG_MAXFREQ,
                            num_items=len(_MAXFREQ_LABELS), width=-1)
            dpg.add_spacer(height=4)
            dpg.add_text('Bin Size')
            dpg.add_listbox(items=_BINSIZE_LABELS, tag=ui.SPEC_DLG_BINSIZE,
                            num_items=len(_BINSIZE_LABELS), width=-1)
            dpg.add_spacer(height=6)
            dpg.add_text('Trend Frequency Window')
            with dpg.group(horizontal=True):
                dpg.add_input_float(label='Hz min', tag=ui.SPEC_DLG_TREND_FMIN,
                                    default_value=0.0, min_value=0.0, width=100)
                dpg.add_input_float(label='Hz max', tag=ui.SPEC_DLG_TREND_FMAX,
                                    default_value=0.0, min_value=0.0, width=100)
            dpg.add_text('(0 max = use spectrum max freq)', indent=4)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label='Apply',
                               callback=self._on_spectrum_apply, width=-1)
                dpg.add_button(label='Cancel',
                               callback=lambda: dpg.hide_item(ui.DLG_SPECTRUM_SETUP),
                               width=-1)

        # ── Sensor Registry Dialog ─────────────────────────────────────
        _dlg_reg_w, _dlg_reg_h = 700, 460
        _sreg_field_w = int((_dlg_reg_w - 200) * 0.618)   # ~309px
        with dpg.window(label='Sensor Registry', modal=True, show=False,
                        tag=ui.DLG_SENSOR_REGISTRY, width=_dlg_reg_w, height=_dlg_reg_h,
                        pos=((WINDOW_WIDTH - _dlg_reg_w) // 2,
                             (WINDOW_HEIGHT - _dlg_reg_h) // 2)):
            with dpg.group(horizontal=True):
                with dpg.child_window(width=200, autosize_y=True):
                    dpg.add_listbox(items=self.registry.names(),
                                    tag=ui.SCOPE_REGISTRY_LIST,
                                    num_items=15, width=-1,
                                    callback=self._on_registry_sensor_select)
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_button(label='Add',
                                       tag=ui.SCOPE_REGISTRY_ADD,
                                       callback=self._on_registry_add,
                                       width=88)
                        dpg.add_button(label='Delete',
                                       tag=ui.SCOPE_REGISTRY_DELETE,
                                       callback=self._on_registry_delete,
                                       width=-1)
                with dpg.child_window(autosize_x=True, autosize_y=True):
                    dpg.add_input_text(label='Name',
                                       tag='SREG_FIELD_NAME', width=_sreg_field_w)
                    dpg.add_combo(label='Source EU',
                                  tag='SREG_FIELD_UNITS',
                                  items=vibechecker.EU_OPTIONS, width=_sreg_field_w)
                    dpg.add_combo(label='Target Unit',
                                  tag='SREG_FIELD_TARGET',
                                  items=[''] + vibechecker.EU_OPTIONS, width=_sreg_field_w)
                    dpg.add_input_float(label='Sensitivity (mV/eu)',
                                        tag='SREG_FIELD_SENS',
                                        format='%.6f', width=_sreg_field_w)
                    dpg.add_input_text(label='Notes',
                                       tag='SREG_FIELD_NOTES', width=_sreg_field_w)
            dpg.add_separator()
            dpg.add_button(label='Close', callback=self._on_registry_close,
                           width=-1)

        # ── Section container theme (slightly lighter than window background) ──
        _sect_bg = vibechecker.hex_to_rgba(vibechecker.THEME_COLORS['SURFACE'])
        with dpg.theme() as _sect_theme:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _sect_bg,
                                    category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6,
                                    category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 8, 6,
                                    category=dpg.mvThemeCat_Core)

        # ── Main window ────────────────────────────────────────────────
        with dpg.window(label='Vibe Checkup', tag='primary_window'):
            with dpg.group(horizontal=True):

                # ── Controls column (left) ────────────────────────────
                with dpg.child_window(width=CONTROLS_WIDTH, autosize_y=True):

                    # ── Connection Status ─────────────────────────────
                    with dpg.child_window(border=True, autosize_x=True,
                                          height=220) as _s1:
                        dpg.bind_item_theme(_s1, _sect_theme)
                        dpg.add_text('Connection Status')
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            with dpg.drawlist(width=16, height=16,
                                              tag=ui.DEVICE_STATUS):
                                dpg.draw_rectangle(
                                    pmin=(1, 1), pmax=(15, 15),
                                    fill=_c('RED'), color=(0, 0, 0, 0),
                                    rounding=3, tag=ui.DEVICE_STATUS_RECT,
                                )
                            dpg.add_text('Not Connected', tag=ui.CONN_STATUS_TEXT)
                        dpg.add_text('', tag=ui.CONN_DEVICE_NAME)
                        with dpg.group(tag=ui.CONN_CHANNEL_SUMMARY):
                            pass
                        dpg.add_spacer(height=2)
                        dpg.add_button(label='Device Setup',
                                       tag=ui.BTN_DEVICE_SETUP,
                                       callback=self._open_device_setup_dialog,
                                       width=-1)
                        dpg.add_button(label='Sensor Setup',
                                       tag=ui.BTN_SENSOR_SETUP,
                                       callback=self._open_sensor_registry_dialog,
                                       width=-1)

                    dpg.add_spacer(height=6)

                    # ── Spectrum Setup ────────────────────────────────
                    with dpg.child_window(border=True, autosize_x=True,
                                          height=202, no_scrollbar=True) as _s2:
                        dpg.bind_item_theme(_s2, _sect_theme)
                        dpg.add_text('Spectrum Setup')
                        dpg.add_separator()
                        dpg.add_input_text(tag=ui.SPECTRUM_INFO_TEXT,
                                           multiline=True, readonly=True,
                                           default_value='', width=-1, height=120)
                        dpg.add_button(label='Spectrum Setup',
                                       tag=ui.BTN_SPECTRUM_SETUP,
                                       callback=self._open_spectrum_dialog,
                                       width=-1)

                    dpg.add_spacer(height=6)

                    # ── Acquisition ───────────────────────────────────
                    with dpg.child_window(border=True, autosize_x=True,
                                          height=105, no_scrollbar=True) as _s3:
                        dpg.bind_item_theme(_s3, _sect_theme)
                        dpg.add_text('Acquisition')
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            with dpg.drawlist(width=20, height=20,
                                              tag=ui.STREAM_STATUS):
                                dpg.draw_rectangle(
                                    pmin=(1, 1), pmax=(19, 19),
                                    fill=_c('RED'), color=(0, 0, 0, 0),
                                    rounding=4, tag=ui.STREAM_STATUS_RECT,
                                )
                            dpg.add_button(label='Stopped',
                                           tag=ui.ACQ_TOGGLE,
                                           callback=self._toggle_acquisition,
                                           width=-1)
                        dpg.add_button(label='Single',
                                       tag=ui.ACQ_SINGLE,
                                       callback=self._collect_sample,
                                       width=-1)
                        dpg.add_spacer(height=2)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='<', tag=ui.ACQ_BROWSE_PREV,
                                           callback=self._on_browse_prev,
                                           width=28, enabled=False)
                            dpg.add_text('No frames', tag=ui.ACQ_BROWSE_LABEL)
                            dpg.add_button(label='>', tag=ui.ACQ_BROWSE_NEXT,
                                           callback=self._on_browse_next,
                                           width=28, enabled=False)

                    dpg.add_spacer(height=6)

                    # ── File Handling ─────────────────────────────────
                    with dpg.child_window(border=True, autosize_x=True,
                                          height=78, no_scrollbar=True) as _s4:
                        dpg.bind_item_theme(_s4, _sect_theme)
                        dpg.add_text('File Handling')
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='Save', tag=ui.FILE_SAVE,
                                           callback=self._on_save_click, width=-1)
                            dpg.add_button(label='Load', tag=ui.FILE_LOAD,
                                           callback=lambda: dpg.show_item(ui.DLG_LOAD_FILE),
                                           width=-1)

                # ── Main column (center — plots) ──────────────────────
                with dpg.child_window(width=-RESULTS_WIDTH, autosize_y=True,
                                      no_scrollbar=True):
                    self._channel_themes = []
                    for color in _CH_COLORS:
                        with dpg.theme() as t:
                            with dpg.theme_component(dpg.mvLineSeries):
                                dpg.add_theme_color(dpg.mvPlotCol_Line, color,
                                                    category=dpg.mvThemeCat_Plots)
                        self._channel_themes.append(t)

                    with dpg.tab_bar():
                        with dpg.tab(label='Spectrum'):
                            with dpg.plot(label='Frequency Series',
                                          width=-1, height=-TIME_PLOT_HEIGHT,
                                          tag=ui.PLT_FREQ):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis,
                                                  label='Frequency, hz',
                                                  tag=ui.PLT_FREQ_AX_FREQ)
                                dpg.add_plot_axis(dpg.mvYAxis, label='',
                                                  tag=ui.PLT_FREQ_AX_ACCEL)
                                dpg.add_plot_axis(dpg.mvYAxis, label='',
                                                  tag=ui.PLT_FREQ_AX_2)
                                dpg.hide_item(ui.PLT_FREQ_AX_2)
                        with dpg.tab(label='Trend'):
                            with dpg.plot(label='Trend Series',
                                          width=-1, height=-TIME_PLOT_HEIGHT,
                                          tag=ui.PLT_TREND):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label='Time, s',
                                                  tag=ui.PLT_TREND_AX_TIME)
                                dpg.add_plot_axis(dpg.mvYAxis,
                                                  label='Overall Vibration',
                                                  tag=ui.PLT_TREND_AX_OVERALL)
                    with dpg.plot(label='Time Series', width=-1,
                                  height=TIME_PLOT_HEIGHT, tag=ui.PLT_SAMPLE):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label='Time, ms',
                                          tag=ui.PLT_SAMPLE_AX_TIME)
                        dpg.add_plot_axis(dpg.mvYAxis, label='',
                                          tag=ui.PLT_SAMPLE_AX_ACCEL)
                        dpg.add_plot_axis(dpg.mvYAxis, label='',
                                          tag=ui.PLT_SAMPLE_AX_ACCEL_2)
                        dpg.hide_item(ui.PLT_SAMPLE_AX_ACCEL_2)

                # ── Results column (right) ────────────────────────────
                with dpg.child_window(width=RESULTS_WIDTH, autosize_y=True):
                    dpg.add_text('Overall Vibration')
                    dpg.add_input_text(label='0-P', tag=ui.PLT_SAMPLE_OVERALL,
                                       readonly=True, default_value='0.0',
                                       width=-1)
                    dpg.add_separator()
                    dpg.add_text('Frequency Peaks')
                    dpg.add_input_int(label='# Peaks',
                                      tag=ui.FFT_PEAKS_DISPLAY_COUNT,
                                      default_value=1, callback=self._redraw,
                                      width=80)
                    dpg.add_table(header_row=True, row_background=True,
                                  borders_innerV=True,
                                  no_host_extendX=True,
                                  tag=ui.FFT_PEAKS_TABLE)

    def initialize(self):
        self.create_gui()
        self._update_spectrum_info()
        self._update_connection_summary()
        self._update_axis_assignment()
        self._refresh_registry_dialog_list()
        self._restore_channel_assignments()
        log.info('Setup GUI')
        dpg.setup_dearpygui()

    def run(self):
        log.info('Launch app window')
        dpg.create_viewport(title='Vibe Logger',
                            width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        dpg.show_viewport()
        dpg.set_primary_window('primary_window', True)
        log.info('Start DPG backend')
        dpg.start_dearpygui()

    def cleanup(self):
        log.info('Cleanup app assets')
        self.collector.disconnect_sensor()
        dpg.destroy_context()
        log.info('App Exit')

    def serve(self):
        self.initialize()
        self.run()
        self.cleanup()
