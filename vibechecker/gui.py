# Vibechecker frontend

import dearpygui.dearpygui as dpg

from path import Path
from typing import Union, Tuple, List, Literal
from datetime import datetime as dt
import sounddevice

import numpy as np 
import pandas as pd

import vibechecker

SAVEDIR = Path('DEVDATA')
EXT = '.pkl'
UNITS = {'Earth Gravity - g': 'g',
         'Metric - mm': 'mm',
         'Imperial - in': 'in'}
UNITS_REV = {v:k for k,v in UNITS.items()}

log = vibechecker.get_logger('gui')
ui = vibechecker.UI_Elements()

class GUI:
    collector: vibechecker.DataCollector
    found_sensors: dict = {}
    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()
        self.collector.callbacks['plots'] = self.display_sample
        
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
        time_vec, accel = sample.get_accel(self.collector.config)
        
        dpg.set_value(ui.PLT_SAMPLE_DATA, [time_vec, accel])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_TIME, time_vec[0], time_vec[-1])
        dpg.set_axis_limits(ui.PLT_SAMPLE_AX_ACCEL, np.min(accel), np.max(accel))

    def update_freq_plot(self,sample:vibechecker.VibeSample):
        freq, psd, peaks = sample.get_spectrum(self.collector.config)
        # TODO: Draw peaks
        # TODO: add N-peaks setting

        peak_limit = dpg.get_value(ui.FFT_PEAKS_DISPLAY_COUNT)
        show_peaks = freq[peaks[:peak_limit]]

        tab = pd.DataFrame({'Frequency (hz)':freq[peaks], 'Amplitude': psd[peaks]})
        self.update_fft_peaks_table(tab)

        dpg.set_value(ui.PLT_FREQ_DATA, [freq, psd])
        dpg.set_axis_limits(ui.PLT_FREQ_AX_FREQ, freq[0], freq[-1])
        dpg.set_axis_limits(ui.PLT_FREQ_AX_ACCEL, 0, np.max(psd))

        dpg.set_value(ui.PLT_FREQ_PEAKS, [show_peaks])

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, sample:vibechecker.VibeSample):
        if not sample.raw_data.size > 0:
            return
        
        self.collector.config.units = UNITS[dpg.get_value(ui.ACQ_UNITS)] # type:ignore

        self.update_time_plot(sample)
        self.update_freq_plot(sample)

        if self.collector.queue:
            dpg.set_value('debug',f'Stream queue len: {self.collector.queue.qsize()}')

    def redraw(self):
        if not self.collector.is_streaming:
            self.display_sample(self.collector.sample)

    def sample_unit_callback(self, sender, data):
        if sender == ui.ACQ_UNITS:
            self.collector.config.units = UNITS[data] # type: ignore
        if sender == ui.ACQ_FFT_INTEGRATION:
            self.collector.config.fft_integration = (data == 'Velocity')

        freq_label = f'{dpg.get_value(ui.ACQ_FFT_INTEGRATION)} - {self.collector.config.units}'
        time_label = f'Acceleration - {self.collector.config.units}'

        if self.collector.config.units == 'g':
            if self.collector.config.fft_integration:
                freq_label += '*s'
        else:
            freq_label += '/s'
            if not self.collector.config.fft_integration:
                freq_label += '^2'

        dpg.configure_item(ui.PLT_SAMPLE_AX_ACCEL, label=time_label)
        dpg.configure_item(ui.PLT_FREQ_AX_ACCEL, label=freq_label)

        self.redraw()
    
    def update_streaming_config(self, parameter=None, value=None):
        '''Syncronize gui settings with sensor acquisition settings'''

        if value is None:
            self.sync_acq_settings_from_collector()
            return
        
        log.info(f'Setting {parameter} to {value}')
        self.collector.update_acquisition_settings(parameter, value)

        self.sync_acq_settings_from_collector()

        self.redraw()
    
    def sync_acq_settings_from_collector(self):
        '''Retrieves aquisition settings from collector to display on GUI'''
        dpg.set_value(ui.ACQ_BLOCKSIZE, self.collector.config.blocksize)
        dpg.set_value(ui.ACQ_SAMPLERATE,self.collector.config.samplerate)
        dpg.set_value(ui.ACQ_MAXFREQ,   self.collector.config.maxfreq)
        dpg.set_value(ui.ACQ_BINSIZE,   self.collector.config.binsize)

    def set_savedir(self, sender=None, data=str):
        p = Path(data)

        if not p.is_dir():
            log.error(f'Failed to set datapath. {p} does not exist')
            return
        
        self.collector.datadir = p
        log.info(f'Set datapath: valid path set to {p}')
        
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
        self.display_sample(sample)

    def browser_handler(self, sender, data):
        # example data:
        # { 'file_path_name': '/home/hgg/CODE/reveng/vibegui/DEVDATA/pytest_data_2025-12-16_12-23-27.pkl',
        #   'file_name': 'pytest_data_2025-12-16_12-23-27.pkl',
        #   'current_path': '/home/hgg/CODE/reveng/vibegui/DEVDATA', 
        #   'current_filter': 'Vibe Samples (*.pkl)', 
        #   'min_size': [100.0, 100.0], 
        #   'max_size': [30000.0, 30000.0], 
        #   'selections': {
        #       'pytest_data_2025-12-16_12-23-27.pkl': '/home/hgg/CODE/reveng/vibegui/DEVDATA/pytest_data_2025-12-16_12-23-27.pkl'
        #   }
        # }
        dpg.set_value(ui.FILE_NAME, data['file_name'])
        self.collector.load_data(self.load_target())

    def save_target(self) -> Path:
        name = dpg.get_value(ui.FILE_NAME)

        if dpg.get_value(ui.FILE_TIMESTAMP):
            name += '_' + str(dt.now().strftime('%Y-%m-%d_%H-%M-%S'))

        name += EXT

        return Path.joinpath(SAVEDIR, name)
    
    def load_target(self) -> Path:
        name = dpg.get_value(ui.FILE_NAME)
        if not name.endswith(EXT):
            name += EXT
        return Path.joinpath(SAVEDIR, name)

    def dpg_debug(self):
        dpg.show_item_registry()
        log.debug('Debugger. Break here')
        
    def create_gui(self):

        dpg.create_context()
            
        with dpg.file_dialog(show=False, default_path=SAVEDIR, callback=self.browser_handler, tag=ui.FILE_DIALOG, width=700 ,height=400):
            dpg.add_file_extension('Vibe Samples (*.pkl){.pkl}', color=(150, 255, 150, 255))
            dpg.add_file_extension('.*', color=(0, 150, 150, 150))
            dpg.add_file_extension('', color=(150, 255, 150, 255))

        with dpg.window(label='Vibe Checkup', width=1200, height=800):
            with dpg.group(horizontal=True):
                with dpg.child_window(label='Toolbar', width=300, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Acquire'):
                            dpg.add_separator()
                            dpg.add_text('Select Device')
                            dpg.add_combo(label='Device Select', tag=ui.SENSOR_SELECTOR, items=['<Trigger Refresh>'], callback=self.connect_sensor)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='⟳', tag=ui.SENSOR_REFRESH, callback=self.refresh_sensors)
                                dpg.add_button(label='Connect', tag=ui.SENSOR_CONNECT, callback=self.connect_sensor)
                                dpg.add_button(label='Disconnect', tag=ui.SENSOR_DISCONNECT, callback=self.disconnect_sensor)

                            config_width = 100
                            dpg.add_separator()
                            dpg.add_text('Acquisition Settings')
                            dpg.add_combo(label='Sample Count', tag=ui.ACQ_BLOCKSIZE, items=tuple(map(str,vibechecker.BLOCKSIZES)),
                                          width=config_width, default_value=str(self.collector.config.blocksize),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label='Sample Rate', tag=ui.ACQ_SAMPLERATE, items=tuple(map(str,vibechecker.SAMPLERATES)),
                                          width=config_width, default_value=str(self.collector.config.samplerate),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label='Maximum Frequency', tag=ui.ACQ_MAXFREQ, items=tuple(map(str, vibechecker.MAXFREQS)),
                                          width=config_width, default_value=str(self.collector.config.maxfreq),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label='Frequnecy Bin Size', tag=ui.ACQ_BINSIZE, items=tuple(map(str,vibechecker.BINSIZES)),
                                          width=config_width, default_value=str(self.collector.config.binsize),
                                          callback=self.update_streaming_config)

                            dpg.add_separator()
                            dpg.add_text('Data Collection')
                            dpg.add_button(label=u'Start', tag=ui.ACQ_START, callback=self.start_stream)
                            dpg.add_button(label=u'Stop', tag=ui.ACQ_STOP, callback=self.stop_stream)
                            dpg.add_button(label=u'Single', tag=ui.ACQ_SINGLE, callback=self.collect_sample)

                            with dpg.group(horizontal=True):
                                dpg.add_input_text(label='', tag=ui.FILE_NAME)
                                dpg.add_button(label='browse..', callback=lambda: dpg.show_item(ui.FILE_DIALOG)) # TODO, implement file browsing
                            dpg.add_checkbox(label='timestamp', tag=ui.FILE_TIMESTAMP)
                            
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Save', tag=ui.FILE_SAVE, callback=lambda: self.collector.save_data(self.save_target()))
                                dpg.add_button(label='Load', tag=ui.FILE_LOAD, callback=lambda: self.collector.load_data(self.load_target())) 

                            dpg.add_separator()

                            dpg.add_button(label=u'Print Sensor Details', callback=self.view_sensor_details)

                        with dpg.tab(label='Configure'):
                            dpg.add_button(label='DEBUG DPG', callback=self.dpg_debug)
                            dpg.add_button(label='Trigger Error', callback=lambda: exec('raise Exception(\'Fake Error\')'))
                # Right display window
                with dpg.child_window(label='Data Display', autosize_x=True, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Time Domain'):
                            with dpg.plot(label='Time Series', width=-1, height=600, tag=ui.PLT_SAMPLE):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label='Time, ms', tag=ui.PLT_SAMPLE_AX_TIME)
                                with dpg.plot_axis(dpg.mvYAxis, label='Acceleration', tag=ui.PLT_SAMPLE_AX_ACCEL):
                                    dpg.add_line_series([0.], [0.], parent=ui.PLT_SAMPLE_AX_TIME, label='Time Domain', tag=ui.PLT_SAMPLE_DATA)
                        with dpg.tab(label='Frequency Domain'):
                            with dpg.plot(label='Frequency Series', width=-1, height=600, tag=ui.PLT_FREQ):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label='Frequency, hz', tag=ui.PLT_FREQ_AX_FREQ)
                                with dpg.plot_axis(dpg.mvYAxis, label='Acceleration', tag=ui.PLT_FREQ_AX_ACCEL):
                                    dpg.add_line_series([0.], [0.], label='Frequency Domain', tag=ui.PLT_FREQ_DATA)
                                    dpg.add_inf_line_series([0.], label='Peaks', tag=ui.PLT_FREQ_PEAKS)
                    
                        # with dpg.tab(label='Running Trend'):
                            # with dpg.plot(label='Trend', width=-1, height=600, tag=ui.PLT_TREND):
                            #     # Plot legend
                            #     dpg.add_plot_legend()
                            #     dpg.add_plot_axis(dpg.mvXAxis, label='Time, s', tag=ui.PLT_TREND_AX_TIME)
                            #     dpg.add_plot_axis(dpg.mvYAxis, label='', tag=ui.PLT_TREND_AX_RMS)

                            #     dpg.add_line_series(np.array([0]), np.array([0]), label=self.domain, parent='y_axis', tag=ui.PLT_TREND_DATA)

                    dpg.add_input_int(label='# Peaks', tag=ui.FFT_PEAKS_DISPLAY_COUNT, default_value=1, callback=self.redraw)
                    dpg.add_combo(label='Sample Units', tag=ui.ACQ_UNITS, callback=self.sample_unit_callback,
                                    items=list(UNITS.keys()), default_value='Earth Gravity - g')                                                
                    dpg.add_combo(label='Sample Integration', tag=ui.ACQ_FFT_INTEGRATION, callback=self.sample_unit_callback,
                                    items=['Velocity', 'Acceleration'], default_value='Acceleration')

                    
                    dpg.add_table(header_row=True, row_background=True, borders_innerV=True,
                                   no_host_extendX=True, tag=ui.FFT_PEAKS_TABLE)
                    dpg.add_text('', tag=ui.DEBUG_TXT)

    def initialize(self):

        self.create_gui()
        self.update_streaming_config()
        self.refresh_sensors(autoconnect=True)

        log.info('Setup GUI')
        dpg.setup_dearpygui()

    def run(self):
        log.info('Launch app window')
        dpg.create_viewport(title='Vibe Logger', width=1200, height=800)
        dpg.show_viewport()

        log.info('Start DGP backend')
        dpg.start_dearpygui()  # App runs

    def cleanup(self):
        log.info('Cleanup app assets')
        self.collector.disconnect_sensor()
        dpg.destroy_context()

        log.info('App Exit')
