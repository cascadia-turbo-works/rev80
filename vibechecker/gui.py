# Vibechecker frontend

import time
import threading
import dearpygui.dearpygui as dpg

from path import Path
from typing import Union, Tuple, List, Literal
from datetime import datetime as dt
import sounddevice

import numpy as np
import pandas as pd

import vibechecker
from vibechecker.scope_sensor import ScopeSensor
from vibechecker.scope_sensor_registry import ScopeSensorRegistry

log = vibechecker.get_logger('gui')
ui = vibechecker.UI_Elements()

# Layout constants
WINDOW_WIDTH = 1500
WINDOW_HEIGHT = 1000
CONTROLS_WIDTH = 300
RESULTS_WIDTH = 300
TIME_PLOT_HEIGHT = 300

_MAX_CHANNELS = 8
_DEFAULT_NUM_CHANNELS = 4

def _c(key: str, alpha: int = 255) -> tuple:
    """Shorthand: THEME_COLORS[key] → DPG RGBA tuple."""
    return vibechecker.hex_to_rgba(vibechecker.THEME_COLORS[key], alpha)

_CH_COLORS = [
    _c('WHITE'),   # Ch A
    _c('ORANGE'),  # Ch B
    _c('LIME'),    # Ch C
    _c('CORAL'),   # Ch D
    _c('CYAN'),    # Ch E
    _c('VIOLET'),  # Ch F
    _c('GOLD'),    # Ch G
    _c('SILVER'),  # Ch H
]


class GUI:
    collector: vibechecker.DataCollector
    found_sensors: dict = {}
    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()
        self.collector.callbacks['plots'] = self.display_sample
        self.registry = ScopeSensorRegistry()
        self._editing_scope_sensor_id: str | None = None
        self._num_channels: int = _DEFAULT_NUM_CHANNELS
        self._channel_themes: list = []
        self._status_timer: threading.Timer | None = None

    def view_sensor_details(self):
        print(self.collector.sensor)

    def set_status_message(self, msg:str):
        dpg.set_item_label('status',msg)

    def update_fft_peaks_table(self, df:pd.DataFrame):
        children = dpg.get_item_children(ui.FFT_PEAKS_TABLE)
        if isinstance(children, dict):
            for sub in children.values():
                for tag in sub:
                    dpg.delete_item(tag)

        df = df.head(n = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT))
        for i in range(df.shape[1]):                    # Generates the correct amount of columns
            dpg.add_table_column(label=df.columns[i], parent=ui.FFT_PEAKS_TABLE)   # Adds the headers
        for i in range(df.shape[0]):                                   # Shows the first n rows
            with dpg.table_row(parent=ui.FFT_PEAKS_TABLE):
                for j in range(df.shape[1]):
                    dpg.add_text(f'{df.iloc[i,j]}')     # Displays the value of
                                                            # each row/column combination

    # ------------------------------------------------------------------
    # Status indicator helpers
    # ------------------------------------------------------------------

    def _set_device_status(self, state: str):
        """Update the device connection indicator: 'connected' | 'disconnected'."""
        if not dpg.does_item_exist(ui.DEVICE_STATUS_RECT):
            return
        color = _c('GREEN') if state == 'connected' else _c('RED')
        dpg.configure_item(ui.DEVICE_STATUS_RECT, fill=color)

    def _set_stream_status(self, state: str):
        """Update the stream activity indicator: 'active' | 'waiting' | 'idle'."""
        if not dpg.does_item_exist(ui.STREAM_STATUS_RECT):
            return
        color_map = {
            'active':  _c('GREEN'),
            'waiting': _c('YELLOW'),
            'idle':    _c('RED'),
        }
        dpg.configure_item(ui.STREAM_STATUS_RECT, fill=color_map.get(state, _c('RED')))

    def _schedule_status_timeout(self):
        """Re-arm a watchdog: if no data arrives within 2× acquisition period,
        revert the stream indicator from green back to yellow."""
        if self._status_timer is not None:
            self._status_timer.cancel()
        timeout = 2.0 * self.collector.config.acquisition_period
        self._status_timer = threading.Timer(timeout, self._on_status_timeout)
        self._status_timer.daemon = True
        self._status_timer.start()

    def _on_status_timeout(self):
        if self.collector.is_streaming:
            self._set_stream_status('waiting')

    def _get_time_axis_for(self, ch: int) -> str:
        """Return the Y-axis tag that ch's time series is bound to."""
        tag = ui.plt_time_series(ch)
        if dpg.does_item_exist(tag):
            parent = dpg.get_item_parent(tag)
            if parent == dpg.get_alias_id(ui.PLT_SAMPLE_AX_ACCEL_2):
                return ui.PLT_SAMPLE_AX_ACCEL_2
        return ui.PLT_SAMPLE_AX_ACCEL

    def _get_freq_axis_for(self, ch: int) -> str:
        """Return the Y-axis tag that ch's freq series is bound to."""
        tag = ui.plt_freq_series(ch)
        if dpg.does_item_exist(tag):
            parent = dpg.get_item_parent(tag)
            if parent == dpg.get_alias_id(ui.PLT_FREQ_AX_2):
                return ui.PLT_FREQ_AX_2
        return ui.PLT_FREQ_AX_ACCEL

    def _get_unit_groups(self) -> list:
        """Group enabled channels by effective target unit. Returns list of (unit, [chs])."""
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
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL, ui.PLT_SAMPLE_AX_ACCEL)
            unit = groups[0][0] if groups else 'mV'
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL, unit)
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL, unit)
        else:
            dpg.show_item(ui.PLT_FREQ_AX_2)
            dpg.show_item(ui.PLT_SAMPLE_AX_ACCEL_2)
            for ch in groups[0][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_ACCEL, ui.PLT_SAMPLE_AX_ACCEL)
            for ch in groups[1][1]:
                self._reassign_series_to_axis(ch, ui.PLT_FREQ_AX_2, ui.PLT_SAMPLE_AX_ACCEL_2)
            dpg.set_item_label(ui.PLT_FREQ_AX_ACCEL, groups[0][0])
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL, groups[0][0])
            dpg.set_item_label(ui.PLT_FREQ_AX_2, groups[1][0])
            dpg.set_item_label(ui.PLT_SAMPLE_AX_ACCEL_2, groups[1][0])

    def _reassign_series_to_axis(self, ch: int, freq_axis: str, time_axis: str):
        """If the series for ch are on different axes, delete and recreate them."""
        freq_tag = ui.plt_freq_series(ch)
        time_tag = ui.plt_time_series(ch)
        wrong_axis = False
        if dpg.does_item_exist(freq_tag):
            if dpg.get_item_parent(freq_tag) != dpg.get_alias_id(freq_axis):
                wrong_axis = True
        if dpg.does_item_exist(time_tag):
            if dpg.get_item_parent(time_tag) != dpg.get_alias_id(time_axis):
                wrong_axis = True
        if wrong_axis:
            self._remove_channel_series(ch)
            self._add_channel_series(ch, freq_axis=freq_axis, time_axis=time_axis)

    def update_time_plot(self, sample: vibechecker.VibeSample, ch: int = 0):
        if not dpg.does_item_exist(ui.plt_time_series(ch)):
            return
        target_unit = self.collector.get_active_eu(ch)
        acc, rms = sample.get_accel(target_unit)

        time = acc.time.to_numpy()
        signal = acc.signal.to_numpy()

        dpg.set_value(ui.plt_time_series(ch), [time, signal])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_TIME, time[0], time[-1])
        y_axis = self._get_time_axis_for(ch)
        sig_min, sig_max = float(np.min(signal)), float(np.max(signal))
        if sig_min == sig_max:
            sig_min -= 1.0
            sig_max += 1.0
        dpg.set_axis_limits(y_axis, sig_min, sig_max)

    def update_freq_plot(self, sample: vibechecker.VibeSample, ch: int = 0):
        if not dpg.does_item_exist(ui.plt_freq_series(ch)):
            return
        target_unit = self.collector.get_active_eu(ch)
        fft, peaks = sample.fft(target_unit, self.collector.config)
        if fft is None or peaks is None:
            return

        freq = fft.freq.to_numpy()
        signal = fft.display_0p.to_numpy()

        overall = np.sqrt(np.sum(np.square(signal))) * np.sqrt(2) / 2

        dpg.set_value(ui.plt_freq_series(ch), [freq, signal])
        dpg.set_value(ui.PLT_SAMPLE_OVERALL, f'{overall:.4f}')
        dpg.set_axis_limits(ui.PLT_FREQ_AX_FREQ, freq[0], freq[-1])
        y_axis = self._get_freq_axis_for(ch)
        y_max = float(np.max(signal)) if len(signal) > 0 else 0.0
        dpg.set_axis_limits(y_axis, 0, 1.05 * y_max if y_max > 0 else 1.0)

        peak_limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        if len(peaks) > 0:
            peak_freqs = freq[peaks[:peak_limit]]
            dpg.set_value(ui.plt_freq_peaks(ch), [peak_freqs.tolist()])
            fft_disp = fft[['freq', 'display_0p']].loc[peaks[:peak_limit]]
            fft_disp.columns = ['Frequency (hz)', f'{target_unit} 0-P']
            if ch == 0:
                self.update_fft_peaks_table(fft_disp)
        else:
            dpg.set_value(ui.plt_freq_peaks(ch), [[]])

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, samples: dict):
        if self.collector.is_streaming:
            self._set_stream_status('active')
            self._schedule_status_timeout()

        for ch, sample in samples.items():
            if sample.blocksize <= 1:
                continue
            self.update_time_plot(sample, ch)
            self.update_freq_plot(sample, ch)

        if self.collector.queue:
            dpg.set_value('debug', f'Stream queue len: {self.collector.queue.qsize()}')

    def redraw(self, sender=None, data=None):
        if not self.collector.is_streaming:
            self.display_sample({0: self.collector.sample})

    def update_axes_label(self):
        self._update_axis_assignment()

    def update_streaming_config(self, sender=None, data=None):
        '''Syncronize gui settings with sensor acquisition settings'''

        if data is None:
            self.sync_acq_settings_from_collector()
            return

        log.info(f'Setting {sender} to {data}')
        self.collector.update_acquisition_settings(sender, data)

        self.sync_acq_settings_from_collector()

        self.redraw(sender)

    def sync_acq_settings_from_collector(self):
        '''Retrieves aquisition settings from collector to display on GUI'''
        dpg.set_value(ui.ACQ_BLOCKSIZE, str(self.collector.config.blocksize))
        dpg.set_value(ui.ACQ_SAMPLERATE, str(self.collector.config.samplerate))
        dpg.set_value(ui.ACQ_MAXFREQ,   self.collector.config.maxfreq)
        dpg.set_value(ui.ACQ_BINSIZE,   self.collector.config.binsize)
        enabled_chs = self.collector.config.enabled_channels
        if enabled_chs:
            eu_parts = [f'Ch {chr(65+ch)}: {self.collector.get_active_eu(ch)}'
                        for ch in sorted(enabled_chs)]
            dpg.set_value(ui.ACQ_EU_DISPLAY, ' | '.join(eu_parts))
        else:
            dpg.set_value(ui.ACQ_EU_DISPLAY, 'Source: --')

    def refresh_sensors(self, sender=None, data=None, autoconnect=False):
        if self.collector.is_streaming:
            log.warning('Sensor refresh may break active stream')

        self.found_sensors = { str(s.device_id) + ' '+ str(s.model_name): s for s in vibechecker.VibeSensor.find() }
        dpg.configure_item(ui.SENSOR_SELECTOR, items=list(self.found_sensors.keys()))

        log.info(f'Discovered {len(self.found_sensors)-1} sensors. IDs = {', '.join([str(s.device_id) for s in self.found_sensors.values()])}')

        ## Autoconnect to last sensor in discovered list
        if autoconnect and len(self.found_sensors)>0:
            autosensor = list(self.found_sensors.keys())[-1]
            dpg.set_value(ui.SENSOR_SELECTOR, autosensor)
            self.connect_sensor()

    def connect_sensor(self, sender=None, data=None):
        name = dpg.get_value(ui.SENSOR_SELECTOR)

        if not name:
            log.warning('No sensor selected, try again')
            return

        sensor = self.found_sensors[name]

        try:
            log.info(f'Connecting sensor {sensor})')
            self.collector.connect_sensor(sensor)
            self._rebuild_channel_rows(sensor.num_channels)
            self._restore_channel_assignments()
            # Recreate stream now that enabled_channels is fully restored from YAML
            self.collector.reconnect_stream()
            self._set_device_status('connected')
        except sounddevice.PortAudioError as e:
            log.info('Selected device is not longer available, try again')
            self.disconnect_sensor()
            self.refresh_sensors()
            dpg.set_value(ui.SENSOR_SELECTOR,'')

    def disconnect_sensor(self, sender=None, data=None):
        log.info(f'Disconnecting sensor {self.collector.sensor}')
        self.collector.disconnect_sensor()
        dpg.set_value(ui.SENSOR_SELECTOR,'')
        self._set_device_status('disconnected')
        self._set_stream_status('idle')

    def start_stream(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Starting sensor stream with {self.collector.sensor}')
        self._set_stream_status('waiting')
        self.collector.start_stream()

    def stop_stream(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Stopping sensor stream')
        self.collector.stop_stream()
        if self._status_timer is not None:
            self._status_timer.cancel()
            self._status_timer = None
        self._set_stream_status('idle')

    def collect_sample(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Trigger single sample with {self.collector.sensor}')
        self._set_stream_status('waiting')
        samples = self.collector.collect_sample()
        self._set_stream_status('idle')
        if samples:
            self.display_sample(samples)

    def browser_handler(self, sender, data):
        dpg.set_value(ui.FILE_NAME, data['file_name'])
        self.collector.load_data(self.load_target())

    def set_sample_label(self, sender, data):
        self.collector.sample.label = data

    def save_target(self) -> Path:
        name:str = dpg.get_value(ui.FILE_NAME)

        if dpg.get_value(ui.FILE_TIMESTAMP):
            name += '_' + dt.now().isoformat()

        return (vibechecker.SAVEDIR / name).with_suffix(vibechecker.EXT)

    def load_target(self) -> Path:
        name = dpg.get_value(ui.FILE_NAME)
        if not name.endswith(vibechecker.EXT):
            name += vibechecker.EXT
        return Path.joinpath(vibechecker.SAVEDIR, name)

    def dpg_debug(self):
        dpg.show_item_registry()
        log.debug('Debugger. Break here')

    # ------------------------------------------------------------------
    # Scope sensor registry helpers
    # ------------------------------------------------------------------

    def _refresh_scope_registry_list(self):
        names = self.registry.names()
        dpg.configure_item(ui.SCOPE_REGISTRY_LIST, items=names)
        sensor_items = ['(none)'] + names
        for ch in range(self._num_channels):
            tag = ui.scope_ch_sensor(ch)
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, items=sensor_items)

    def _refresh_assigned_sensors(self):
        """Reload in-memory ScopeSensor objects from registry (called after an edit).

        If a channel's assigned sensor was edited, the collector still holds
        the old object.  This replaces it with the fresh version from YAML.
        """
        for ch in range(self._num_channels):
            existing = self.collector.scope_sensors.get(ch)
            if existing is not None:
                updated = self.registry.find_by_id(existing.id)
                self.collector.set_scope_sensor(ch, updated)  # None if deleted

    def _get_selected_scope_sensor(self) -> ScopeSensor | None:
        name = dpg.get_value(ui.SCOPE_REGISTRY_LIST)
        if not name:
            return None
        return self.registry.find_by_name(name)

    def _add_channel_series(self, ch: int,
                             freq_axis: str = ui.PLT_FREQ_AX_ACCEL,
                             time_axis: str = ui.PLT_SAMPLE_AX_ACCEL):
        """Add live plot series for a channel to all three plots."""
        ch_label = f'Ch {chr(65 + ch)}'
        theme = self._channel_themes[ch % len(self._channel_themes)]

        for tag, axis in [
            (ui.plt_time_series(ch), time_axis),
            (ui.plt_freq_series(ch), freq_axis),
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
        """Delete plot series for a channel from all three plots."""
        for tag in [
            ui.plt_time_series(ch),
            ui.plt_freq_series(ch),
            ui.plt_trend_series(ch),
            ui.plt_freq_peaks(ch),
        ]:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)

    def _save_channel_assignments(self):
        """Persist current enabled/sensor state for all channels."""
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
        """Checkbox toggled: update enabled_channels and reconnect hardware stream."""
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
        self.sync_acq_settings_from_collector()
        self._update_axis_assignment()
        # Recreate the stream so hardware picks up the new channel list
        self.collector.reconnect_stream()

    def _redraw_all_channels(self):
        """Re-display the last known sample for every enabled channel."""
        if self.collector.is_streaming:
            return  # live stream will update on the next incoming block
        samples = {
            ch: s
            for ch, s in self.collector._last_samples.items()
            if ch in self.collector.config.enabled_channels and s.blocksize > 1
        }
        if samples:
            self.display_sample(samples)
        elif self.collector.sample.blocksize > 1:
            # Fallback: at least redraw ch 0 from the legacy single-sample store
            self.display_sample({0: self.collector.sample})

    def _on_sensor_combo_change(self, ch: int, sensor_name: str):
        """Sensor combo changed: assign scope sensor and refresh display."""
        if not dpg.does_item_exist(ui.scope_ch_sensor(ch)):
            return
        sensor = (None if (not sensor_name or sensor_name == '(none)')
                  else self.registry.find_by_name(sensor_name))
        self.collector.set_scope_sensor(ch, sensor)

        self._save_channel_assignments()
        self.sync_acq_settings_from_collector()
        self._update_axis_assignment()
        self._redraw_all_channels()


    def _rebuild_channel_rows(self, num_channels: int):
        """Rebuild the per-channel rows in the Configure tab."""
        self._num_channels = num_channels

        if not dpg.does_item_exist('SCOPE_CHANNEL_ROWS_GROUP'):
            return

        # Remove all existing channel series from plots
        for ch in range(_MAX_CHANNELS):
            self._remove_channel_series(ch)

        # Remove tag aliases before deleting widgets; DPG does not free aliases
        # automatically when deleting via children_only=True.
        for ch in range(_MAX_CHANNELS):
            for tag in [ui.scope_ch_enabled(ch), ui.scope_ch_sensor(ch)]:
                if dpg.does_alias_exist(tag):
                    dpg.remove_alias(tag)

        dpg.delete_item('SCOPE_CHANNEL_ROWS_GROUP', children_only=True)

        sensor_items = ['(none)'] + self.registry.names()
        enabled_set = set(self.collector.config.enabled_channels)

        for ch in range(num_channels):
            ch_letter = chr(65 + ch)
            is_enabled = ch in enabled_set
            sensor = self.collector.scope_sensors.get(ch)
            default_sensor = sensor.name if sensor else '(none)'

            with dpg.group(horizontal=True, parent='SCOPE_CHANNEL_ROWS_GROUP'):
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
                    default_value=default_sensor,
                    width=-1,
                    callback=lambda s, d, c=ch: self._on_sensor_combo_change(c, d),
                )

    def _restore_channel_assignments(self):
        """Apply saved channel assignments to collector and GUI widgets."""
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

        # Guarantee plot series exist for every currently-enabled channel.
        # _add_channel_series guards with does_item_exist so this is idempotent.
        for ch in self.collector.config.enabled_channels:
            if ch < self._num_channels:
                self._add_channel_series(ch)

        self._update_axis_assignment()

    def _on_scope_add(self, sender=None, data=None):
        self._editing_scope_sensor_id = None
        dpg.set_value(ui.SCOPE_DIALOG_NAME, '')
        dpg.set_value(ui.SCOPE_DIALOG_UNITS, 'g')
        dpg.set_value(ui.SCOPE_DIALOG_TARGET_UNIT, '')
        dpg.set_value(ui.SCOPE_DIALOG_SENSITIVITY, 0.0)
        dpg.set_value(ui.SCOPE_DIALOG_NOTES, '')
        dpg.show_item(ui.SCOPE_SENSOR_DIALOG)

    def _on_scope_edit(self, sender=None, data=None):
        sensor = self._get_selected_scope_sensor()
        if sensor is None:
            return
        self._editing_scope_sensor_id = sensor.id
        dpg.set_value(ui.SCOPE_DIALOG_NAME, sensor.name)
        dpg.set_value(ui.SCOPE_DIALOG_UNITS, sensor.engineering_units)
        dpg.set_value(ui.SCOPE_DIALOG_TARGET_UNIT, sensor.target_unit)
        dpg.set_value(ui.SCOPE_DIALOG_SENSITIVITY, sensor.sensitivity)
        dpg.set_value(ui.SCOPE_DIALOG_NOTES, sensor.notes)
        dpg.show_item(ui.SCOPE_SENSOR_DIALOG)

    def _on_scope_delete(self, sender=None, data=None):
        sensor = self._get_selected_scope_sensor()
        if sensor is None:
            return
        self.registry.delete(sensor.id)
        self._refresh_scope_registry_list()

    def _on_scope_dialog_ok(self, sender=None, data=None):
        name = dpg.get_value(ui.SCOPE_DIALOG_NAME).strip()
        if not name:
            return
        units = dpg.get_value(ui.SCOPE_DIALOG_UNITS)
        target_unit = dpg.get_value(ui.SCOPE_DIALOG_TARGET_UNIT)
        sensitivity = float(dpg.get_value(ui.SCOPE_DIALOG_SENSITIVITY))
        notes = dpg.get_value(ui.SCOPE_DIALOG_NOTES).strip()

        if self._editing_scope_sensor_id is None:
            sensor = ScopeSensor(name=name,
                                 engineering_units=units,
                                 sensitivity=sensitivity,
                                 target_unit=target_unit,
                                 notes=notes)
            self.registry.add(sensor)
        else:
            sensor = ScopeSensor(name=name,
                                 engineering_units=units,
                                 sensitivity=sensitivity,
                                 target_unit=target_unit,
                                 id=self._editing_scope_sensor_id,
                                 notes=notes)
            self.registry.update(sensor)

        self._refresh_scope_registry_list()
        dpg.hide_item(ui.SCOPE_SENSOR_DIALOG)
        # Refresh in-memory sensor objects so units update immediately
        self._refresh_assigned_sensors()
        self.sync_acq_settings_from_collector()
        self._update_axis_assignment()
        self._redraw_all_channels()

    def _on_scope_dialog_cancel(self, sender=None, data=None):
        dpg.hide_item(ui.SCOPE_SENSOR_DIALOG)

    def create_gui(self):

        dpg.create_context()

        with dpg.file_dialog(show=False, default_path=str(vibechecker.SAVEDIR), callback=self.browser_handler, tag=ui.FILE_DIALOG, width=700 ,height=400):
            dpg.add_file_extension('Vibe Samples (*.h5){.h5}', color=(150, 255, 150, 255))
            dpg.add_file_extension('.*', color=(0, 150, 150, 150))
            dpg.add_file_extension('', color=(150, 255, 150, 255))

        with dpg.window(label='Sensor', modal=True, show=False,
                        tag=ui.SCOPE_SENSOR_DIALOG, width=400, no_resize=True):
            dpg.add_input_text(label='Name', tag=ui.SCOPE_DIALOG_NAME, width=200)
            dpg.add_combo(label='Source EU', tag=ui.SCOPE_DIALOG_UNITS,
                          items=vibechecker.EU_OPTIONS, default_value='g', width=200)
            dpg.add_combo(label='Target Unit', tag=ui.SCOPE_DIALOG_TARGET_UNIT,
                          items=[''] + vibechecker.EU_OPTIONS, default_value='', width=200)
            dpg.add_input_float(label='Sensitivity (mV/eu)', tag=ui.SCOPE_DIALOG_SENSITIVITY,
                                default_value=0.0, format='%.6f', width=200)
            dpg.add_input_text(label='Notes', tag=ui.SCOPE_DIALOG_NOTES, width=200)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label='OK', tag=ui.SCOPE_DIALOG_OK,
                               callback=self._on_scope_dialog_ok)
                dpg.add_button(label='Cancel', tag=ui.SCOPE_DIALOG_CANCEL,
                               callback=self._on_scope_dialog_cancel)

        config_width = 120

        with dpg.window(label='Vibe Checkup', tag='primary_window'):
            with dpg.group(horizontal=True):
                # ── Controls column (left) ────────────────────
                with dpg.child_window(width=CONTROLS_WIDTH, autosize_y=True):
                    with dpg.tab_bar():
                        # ── Acquire tab ───────────────────────
                        with dpg.tab(label='Acquire'):
                            with dpg.group(horizontal=True):
                                dpg.add_text('Device')
                                with dpg.drawlist(width=16, height=16,
                                                  tag=ui.DEVICE_STATUS):
                                    dpg.draw_rectangle(
                                        pmin=(1, 1), pmax=(15, 15),
                                        fill=_c('RED'), color=(0, 0, 0, 0),
                                        rounding=3, tag=ui.DEVICE_STATUS_RECT,
                                    )
                            dpg.add_combo(label='', tag=ui.SENSOR_SELECTOR, items=['<Trigger Refresh>'],
                                          callback=self.connect_sensor, width=-1)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Refresh', tag=ui.SENSOR_REFRESH, callback=self.refresh_sensors)
                                dpg.add_button(label='Connect', tag=ui.SENSOR_CONNECT, callback=self.connect_sensor)
                                dpg.add_button(label='Disconnect', tag=ui.SENSOR_DISCONNECT, callback=self.disconnect_sensor)

                            dpg.add_input_text(label='', tag=ui.ACQ_EU_DISPLAY, readonly=True,
                                               default_value='Source: --', width=-1)

                            dpg.add_separator()
                            dpg.add_text('Spectral Setpoints')
                            dpg.add_combo(label='Max Frequency', tag=ui.ACQ_MAXFREQ,
                                          items=tuple(map(str, vibechecker.MAXFREQS)),
                                          width=config_width, default_value=str(self.collector.config.maxfreq),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label='Bin Size', tag=ui.ACQ_BINSIZE,
                                          items=tuple(map(str, vibechecker.BINSIZES)),
                                          width=config_width, default_value=str(self.collector.config.binsize),
                                          callback=self.update_streaming_config)

                            dpg.add_separator()
                            dpg.add_text('Hardware Settings')
                            dpg.add_input_text(label='Sample Rate', tag=ui.ACQ_SAMPLERATE, readonly=True,
                                               default_value=str(self.collector.config.samplerate), width=config_width)
                            dpg.add_input_text(label='Block Size', tag=ui.ACQ_BLOCKSIZE, readonly=True,
                                               default_value=str(self.collector.config.blocksize), width=config_width)

                            dpg.add_separator()
                            with dpg.group(horizontal=True):
                                dpg.add_text('Data Collection')
                                with dpg.drawlist(width=16, height=16,
                                                  tag=ui.STREAM_STATUS):
                                    dpg.draw_rectangle(
                                        pmin=(1, 1), pmax=(15, 15),
                                        fill=_c('RED'), color=(0, 0, 0, 0),
                                        rounding=3, tag=ui.STREAM_STATUS_RECT,
                                    )
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Start', tag=ui.ACQ_START, callback=self.start_stream)
                                dpg.add_button(label='Stop', tag=ui.ACQ_STOP, callback=self.stop_stream)
                                dpg.add_button(label='Single', tag=ui.ACQ_SINGLE, callback=self.collect_sample)

                            with dpg.group(horizontal=True):
                                dpg.add_input_text(label='', tag=ui.FILE_NAME, callback=self.set_sample_label, width=180)
                                dpg.add_button(label='browse..', callback=lambda: dpg.show_item(ui.FILE_DIALOG))
                            dpg.add_checkbox(label='timestamp', tag=ui.FILE_TIMESTAMP)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Save', tag=ui.FILE_SAVE,
                                               callback=lambda: self.collector.save_data(self.save_target()))
                                dpg.add_button(label='Load', tag=ui.FILE_LOAD,
                                               callback=lambda: self.collector.load_data(self.load_target()))

                        # ── Configure tab ─────────────────────
                        with dpg.tab(label='Configure'):
                            dpg.add_button(label='DEBUG DPG', callback=self.dpg_debug)
                            dpg.add_button(label='Trigger Error', callback=lambda: exec('raise Exception(\'Fake Error\')'))

                            dpg.add_separator()
                            dpg.add_text('Channels')
                            with dpg.group(tag='SCOPE_CHANNEL_ROWS_GROUP'):
                                dpg.add_text('Connect a scope to configure channels',
                                             tag='SCOPE_CHANNEL_PLACEHOLDER')

                            dpg.add_separator()
                            dpg.add_text('Sensor Registry')
                            dpg.add_listbox(label='', tag=ui.SCOPE_REGISTRY_LIST,
                                            items=self.registry.names(), num_items=6, width=-1)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Add', tag=ui.SCOPE_REGISTRY_ADD,
                                               callback=self._on_scope_add)
                                dpg.add_button(label='Edit', tag=ui.SCOPE_REGISTRY_EDIT,
                                               callback=self._on_scope_edit)
                                dpg.add_button(label='Delete', tag=ui.SCOPE_REGISTRY_DELETE,
                                               callback=self._on_scope_delete)

                # ── Main column (center) ──────────────────────
                with dpg.child_window(width=-RESULTS_WIDTH, autosize_y=True, no_scrollbar=True):
                    # Build per-channel colour themes (created once; reused when
                    # series are added dynamically via _add_channel_series)
                    self._channel_themes = []
                    for color in _CH_COLORS:
                        with dpg.theme() as t:
                            with dpg.theme_component(dpg.mvLineSeries):
                                dpg.add_theme_color(dpg.mvPlotCol_Line, color,
                                                    category=dpg.mvThemeCat_Plots)
                        self._channel_themes.append(t)

                    with dpg.tab_bar():
                        with dpg.tab(label='Spectrum'):
                            with dpg.plot(label='Frequency Series', width=-1, height=-TIME_PLOT_HEIGHT, tag=ui.PLT_FREQ):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label='Frequency, hz', tag=ui.PLT_FREQ_AX_FREQ)
                                dpg.add_plot_axis(dpg.mvYAxis, label='', tag=ui.PLT_FREQ_AX_ACCEL)
                                dpg.add_plot_axis(dpg.mvYAxis, label='', tag=ui.PLT_FREQ_AX_2)
                                dpg.hide_item(ui.PLT_FREQ_AX_2)
                        with dpg.tab(label='Trend'):
                            with dpg.plot(label='Trend Series', width=-1, height=-TIME_PLOT_HEIGHT, tag=ui.PLT_TREND):
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label='Time, s', tag=ui.PLT_TREND_AX_TIME)
                                dpg.add_plot_axis(dpg.mvYAxis, label='Overall Vibration', tag=ui.PLT_TREND_AX_OVERALL)
                    with dpg.plot(label='Time Series', width=-1, height=TIME_PLOT_HEIGHT, tag=ui.PLT_SAMPLE):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label='Time, ms', tag=ui.PLT_SAMPLE_AX_TIME)
                        dpg.add_plot_axis(dpg.mvYAxis, label='', tag=ui.PLT_SAMPLE_AX_ACCEL)
                        dpg.add_plot_axis(dpg.mvYAxis, label='', tag=ui.PLT_SAMPLE_AX_ACCEL_2)
                        dpg.hide_item(ui.PLT_SAMPLE_AX_ACCEL_2)

                # ── Results column (right) ────────────────────
                with dpg.child_window(width=RESULTS_WIDTH, autosize_y=True):
                    dpg.add_text('Overall Vibration')
                    dpg.add_input_text(label='0-P', tag=ui.PLT_SAMPLE_OVERALL,
                                       readonly=True, default_value='0.0', width=-1)
                    dpg.add_separator()
                    dpg.add_text('Frequency Peaks')
                    dpg.add_input_int(label='# Peaks', tag=ui.FFT_PEAKS_DISPLAY_COUNT,
                                      default_value=1, callback=self.redraw, width=80)
                    dpg.add_table(header_row=True, row_background=True, borders_innerV=True,
                                  no_host_extendX=True, tag=ui.FFT_PEAKS_TABLE)
                    dpg.add_text('', tag=ui.DEBUG_TXT)

    def initialize(self):
        self.create_gui()
        self.update_streaming_config()
        self.update_axes_label()

        self._refresh_scope_registry_list()
        self._rebuild_channel_rows(self._num_channels)
        self._restore_channel_assignments()

        log.info('Setup GUI')
        dpg.setup_dearpygui()

    def run(self):
        log.info('Launch app window')
        dpg.create_viewport(title='Vibe Logger', width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        dpg.show_viewport()
        dpg.set_primary_window('primary_window', True)
        log.info('Start DGP backend')
        dpg.start_dearpygui()  # App runs

    def cleanup(self):
        log.info('Cleanup app assets')
        self.collector.disconnect_sensor()
        dpg.destroy_context()

        log.info('App Exit')

    def serve(self):
        self.initialize()
        self.run()
        self.cleanup()
