# Vibechecker frontend

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
CONTROLS_WIDTH = 300
RESULTS_WIDTH = 300
TIME_PLOT_HEIGHT = 300


class GUI:
    collector: vibechecker.DataCollector
    found_sensors: dict = {}
    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()
        self.collector.callbacks['plots'] = self.display_sample
        self.registry = ScopeSensorRegistry()
        self._editing_scope_sensor_id: str | None = None

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

    def update_time_plot(self,sample:vibechecker.VibeSample):
        acc, rms = sample.get_accel(self.collector.config)

        time = acc.time.to_numpy()
        signal = acc.signal.to_numpy()

        dpg.set_value(ui.PLT_SAMPLE_DATA, [time, signal])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_TIME, time[0], time[-1])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_ACCEL, np.min(signal), np.max(signal))

    def update_freq_plot(self,sample:vibechecker.VibeSample):
        fft, peaks = sample.fft(self.collector.config)
        if fft is None or peaks is None:
            return

        freq = fft.freq.to_numpy()
        signal = fft.display_0p.to_numpy()

        overall = np.sqrt(np.sum(np.square(signal))) * np.sqrt(2)/2

        dpg.set_value(ui.PLT_FREQ_DATA, [freq, signal])
        dpg.set_value(ui.PLT_SAMPLE_OVERALL, f'{overall:.4f}')
        dpg.set_axis_limits(ui.PLT_FREQ_AX_FREQ, freq[0], freq[-1])
        dpg.set_axis_limits(ui.PLT_FREQ_AX_ACCEL, 0, 1.05 * np.max(signal))

        # Draw peaks
        target = self.collector.config.integrate.capitalize()
        peak_limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        fft_disp = fft[['freq','display_0p']].loc[peaks[:peak_limit]]
        fft_disp.columns = [f'Frequency (hz)',
                            f'{target} 0-P']

        dpg.set_value(ui.PLT_FREQ_PEAKS, [freq[peaks[:peak_limit]]])
        self.update_fft_peaks_table(fft_disp)

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, sample:vibechecker.VibeSample):
        if sample.blocksize <= 1:
            return

        self.collector.config.units = vibechecker.UNITS[dpg.get_value(ui.ACQ_UNITS)] # type:ignore

        self.update_time_plot(sample)
        self.update_freq_plot(sample)

        if self.collector.queue:
            dpg.set_value('debug',f'Stream queue len: {self.collector.queue.qsize()}')

    def redraw(self, sender=None, data=None):
        if not self.collector.is_streaming:
            self.display_sample(self.collector.sample)

        if sender in [ui.ACQ_UNITS, ui.ACQ_INTEGRATE]:
            self.update_axes_label()

    def update_axes_label(self):
        display_units = self.collector.config.units
        target = self.collector.config.integrate  # 'acceleration', 'velocity', 'displacement'

        # Build unit suffix based on modality and unit system
        # g-system: g, g*s, g*s²  |  metric: mm/s², mm/s, mm  |  imperial: in/s², in/s, in
        if display_units == 'g':
            suffix_map = {'acceleration': 'g', 'velocity': 'g*s', 'displacement': 'g*s\u00b2'}
        else:
            suffix_map = {
                'acceleration': f'{display_units}/s\u00b2',
                'velocity': f'{display_units}/s',
                'displacement': f'{display_units}',
            }

        freq_label = f'{target.capitalize()} - {suffix_map.get(target, display_units)}'
        time_label = f'Source - {suffix_map.get("acceleration", display_units)}'

        dpg.configure_item(ui.PLT_SAMPLE_AX_ACCEL, label=time_label)
        dpg.configure_item(ui.PLT_FREQ_AX_ACCEL, label=freq_label)

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
        dpg.set_value(ui.ACQ_UNITS,     vibechecker.UNITS_REV[self.collector.config.units])
        dpg.set_value(ui.ACQ_INTEGRATE, self.collector.config.integrate.capitalize())
        dpg.set_value(ui.ACQ_EU_DISPLAY, f'Source: {self.collector.get_active_eu()}')

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
        except sounddevice.PortAudioError as e:
            log.info('Selected device is not longer available, try again')
            self.disconnect_sensor()
            self.refresh_sensors()
            dpg.set_value(ui.SENSOR_SELECTOR,'')

    def disconnect_sensor(self, sender=None, data=None):
        log.info(f'Disconnecting sensor {self.collector.sensor}')
        self.collector.disconnect_sensor()
        dpg.set_value(ui.SENSOR_SELECTOR,'')

    def start_stream(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Starting sensor stream with {self.collector.sensor}')
        self.collector.start_stream()

    def stop_stream(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Stopping sensor stream')
        self.collector.stop_stream()

    def collect_sample(self, sender=None, data=None):
        if self.collector.stream is None:
            log.warning('Connect sensor before using collection controls')
            return

        log.info(f'Trigger single sample with {self.collector.sensor}')
        sample = self.collector.collect_sample()
        if sample is not None:
            self.display_sample(sample)

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
        dpg.configure_item(ui.SCOPE_CH0_SENSOR, items=['(none)'] + names)

    def _get_selected_scope_sensor(self) -> ScopeSensor | None:
        name = dpg.get_value(ui.SCOPE_REGISTRY_LIST)
        if not name:
            return None
        return self.registry.find_by_name(name)

    def _on_ch0_sensor_change(self, sender=None, data=None):
        name = dpg.get_value(ui.SCOPE_CH0_SENSOR)
        if not name or name == '(none)':
            self.collector.set_scope_sensor(0, None)
            self.registry.save_channel_assignments({})
        else:
            sensor = self.registry.find_by_name(name)
            if sensor:
                self.collector.set_scope_sensor(0, sensor)
                self.registry.save_channel_assignments({0: sensor.id})
        # Update source EU display
        self.sync_acq_settings_from_collector()
        self.update_axes_label()

    def _on_scope_add(self, sender=None, data=None):
        self._editing_scope_sensor_id = None
        dpg.set_value(ui.SCOPE_DIALOG_NAME, '')
        dpg.set_value(ui.SCOPE_DIALOG_MODALITY, 'acceleration')
        dpg.set_value(ui.SCOPE_DIALOG_UNITS, 'g')
        dpg.set_value(ui.SCOPE_DIALOG_SENSITIVITY, 0.0)
        dpg.set_value(ui.SCOPE_DIALOG_NOTES, '')
        dpg.show_item(ui.SCOPE_SENSOR_DIALOG)

    def _on_scope_edit(self, sender=None, data=None):
        sensor = self._get_selected_scope_sensor()
        if sensor is None:
            return
        self._editing_scope_sensor_id = sensor.id
        dpg.set_value(ui.SCOPE_DIALOG_NAME, sensor.name)
        dpg.set_value(ui.SCOPE_DIALOG_MODALITY, sensor.modality)
        dpg.set_value(ui.SCOPE_DIALOG_UNITS, sensor.engineering_units)
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
        modality = dpg.get_value(ui.SCOPE_DIALOG_MODALITY)
        units = dpg.get_value(ui.SCOPE_DIALOG_UNITS)
        sensitivity = float(dpg.get_value(ui.SCOPE_DIALOG_SENSITIVITY))
        notes = dpg.get_value(ui.SCOPE_DIALOG_NOTES).strip()

        if self._editing_scope_sensor_id is None:
            sensor = ScopeSensor(name=name, modality=modality,
                                 engineering_units=units,
                                 sensitivity=sensitivity, notes=notes)
            self.registry.add(sensor)
        else:
            sensor = ScopeSensor(name=name, modality=modality,
                                 engineering_units=units,
                                 sensitivity=sensitivity,
                                 id=self._editing_scope_sensor_id, notes=notes)
            self.registry.update(sensor)

        self._refresh_scope_registry_list()
        dpg.hide_item(ui.SCOPE_SENSOR_DIALOG)

    def _on_scope_dialog_cancel(self, sender=None, data=None):
        dpg.hide_item(ui.SCOPE_SENSOR_DIALOG)

    def create_gui(self):

        dpg.create_context()

        with dpg.file_dialog(show=False, default_path=str(vibechecker.SAVEDIR), callback=self.browser_handler, tag=ui.FILE_DIALOG, width=700 ,height=400):
            dpg.add_file_extension('Vibe Samples (*.h5){.h5}', color=(150, 255, 150, 255))
            dpg.add_file_extension('.*', color=(0, 150, 150, 150))
            dpg.add_file_extension('', color=(150, 255, 150, 255))

        with dpg.window(label='Sensor', modal=True, show=False,
                        tag=ui.SCOPE_SENSOR_DIALOG, width=380, no_resize=True):
            dpg.add_input_text(label='Name', tag=ui.SCOPE_DIALOG_NAME, width=200)
            dpg.add_combo(label='Modality', tag=ui.SCOPE_DIALOG_MODALITY,
                          items=['acceleration', 'velocity', 'displacement'],
                          default_value='acceleration', width=200)
            dpg.add_combo(label='Units', tag=ui.SCOPE_DIALOG_UNITS,
                          items=['g', 'mm', 'in', 'mil'], default_value='g', width=200)
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
                            dpg.add_text('Select Device')
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
                            dpg.add_combo(label='Display Units', tag=ui.ACQ_UNITS,
                                          callback=self.update_streaming_config,
                                          items=list(vibechecker.UNITS.keys()),
                                          default_value=vibechecker.UNITS_REV['g'], width=config_width)
                            dpg.add_combo(label='Integration', tag=ui.ACQ_INTEGRATE,
                                          callback=self.update_streaming_config,
                                          items=['Acceleration', 'Velocity', 'Displacement'],
                                          default_value='Acceleration', width=config_width)

                            dpg.add_separator()
                            dpg.add_text('Data Collection')
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
                            dpg.add_text('Channel A Sensor')
                            dpg.add_combo(label='', tag=ui.SCOPE_CH0_SENSOR,
                                          items=['(none)'] + self.registry.names(),
                                          default_value='(none)',
                                          callback=self._on_ch0_sensor_change, width=-1)

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
                    with dpg.plot(label='Frequency Series', width=-1, height=-TIME_PLOT_HEIGHT, tag=ui.PLT_FREQ):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label='Frequency, hz', tag=ui.PLT_FREQ_AX_FREQ)
                        with dpg.plot_axis(dpg.mvYAxis, label='Acceleration', tag=ui.PLT_FREQ_AX_ACCEL):
                            dpg.add_line_series([0.], [0.], label='Frequency Domain', tag=ui.PLT_FREQ_DATA)
                            dpg.add_inf_line_series([0.], label='Peaks', tag=ui.PLT_FREQ_PEAKS)
                    with dpg.plot(label='Time Series', width=-1, height=TIME_PLOT_HEIGHT, tag=ui.PLT_SAMPLE):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label='Time, ms', tag=ui.PLT_SAMPLE_AX_TIME)
                        with dpg.plot_axis(dpg.mvYAxis, label='Acceleration', tag=ui.PLT_SAMPLE_AX_ACCEL):
                            dpg.add_line_series([0.], [0.], parent=ui.PLT_SAMPLE_AX_TIME, label='Time Domain', tag=ui.PLT_SAMPLE_DATA)

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

        # Restore scope channel assignments from disk
        self._refresh_scope_registry_list()
        assignments = self.registry.load_channel_assignments()
        for ch, sensor_id in assignments.items():
            sensor = self.registry.find_by_id(sensor_id)
            if sensor:
                self.collector.set_scope_sensor(ch, sensor)
                if ch == 0:
                    dpg.set_value(ui.SCOPE_CH0_SENSOR, sensor.name)

        self.refresh_sensors(autoconnect=True)

        log.info('Setup GUI')
        dpg.setup_dearpygui()

    def run(self):
        log.info('Launch app window')
        dpg.create_viewport(title='Vibe Logger', width=1200, height=800)
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
