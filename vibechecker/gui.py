import dearpygui.dearpygui as dpg

from pathlib import Path
from typing import Union, Tuple, List
from datetime import datetime as dt

import endaq
import numpy as np 

import vibechecker
from vibechecker import logger
from vibechecker.collector import DataCollector
from vibechecker.util import VibeSensor, VibeSample, BLOCKSIZES, SAMPLERATES

SAVEDIR = 'DEVDATA'

log = logger.get_logger('gui')

class GUI:
    collector: DataCollector
    found_sensors: dict = {}
    def __init__(self):
        self.context = None
        self.collector = DataCollector()

        self.collector.callbacks['plots'] = self.display_sample
        
        self.create_gui()
        self.update_streaming_config()
        self.refresh_sensors()

        ## Autoconnect to last sensor in discovered list
        if len(self.found_sensors)>0:
            autosensor = list(self.found_sensors.keys())[-1]
            dpg.set_value('sensor_select', autosensor)
            self.connect_sensor()

    def view_sensor_details(self):
        print(self.collector.sensor)
    
    def set_status_message(self, msg:str):
        dpg.set_item_label('status',msg)
    
    def update_sample_metadata(self, sample:VibeSample):
        # Update the display with the latest sample metadata
        timestring = str(sample.timestamp)

        dpg.set_value('disp_status',     f'Status:      {sample.status}')
        dpg.set_value('disp_timestamp',  f'Time:        {timestring}')
        dpg.set_value('disp_blocksize',  f'Sample Size: {sample.config.blocksize }')
        dpg.set_value('disp_samplerate', f'Sample Rate: {sample.config.samplerate} Hz')
        # TODO: Harmonize units. ex Hz, rpm

    def update_time_plot(self,T,A):
        dpg.set_value('time_data', [T, A])
        dpg.set_axis_limits('time_axis', T[0], T[-1])
        dpg.set_axis_limits('acc_axis', np.min(A), np.max(A))

    def update_freq_plot(self,F,V):
        iicrop = F<self.collector.config.maxfreq
        F = F[iicrop]
        V = V[iicrop]

        dpg.set_value('freq_data', [F, V])
        dpg.set_axis_limits('freq_axis', F[0], F[-1])
        dpg.set_axis_limits('vel_axis', 0, np.max(V))

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, sample:VibeSample):
        self.update_sample_metadata(sample)

        self.update_time_plot(sample.config.time_vec, sample.get_accel())
        self.update_freq_plot(sample.config.freq_vec, sample.get_spectral_velocity())

        if self.collector.queue:
            dpg.set_value('debug',f'Stream queue len: {self.collector.queue.qsize()}')
        
    def update_streaming_config(self, parameter=None, value=None):
        '''Syncronize gui settings with sensor acquisition settings'''

        if self.collector.is_streaming:
            log.warning('Stop stream to update Acquisition Settings')
            self.sync_acq_settings_from_collector()
            return

        log.info(f'Setting {parameter} to {value}')
        self.collector.update_acquisition_settings(parameter, value)
        self.sync_acq_settings_from_collector()
    
    def sync_acq_settings_from_collector(self):
        '''Retrieves aquisition settings from collector to display on GUI'''
        dpg.set_value('maxfreq', self.collector.config.maxfreq)
        dpg.set_value('binsize', self.collector.config.binsize)
        dpg.set_value('samplerate', self.collector.config.samplerate)
        dpg.set_value('blocksize', self.collector.config.blocksize)

    def set_savedir(self, sender=None, data=None):
        if Path(data).is_dir():
            self.collector.datadir = data
            log.info(f'Set datapath: valid path set to {data}')
        
    def refresh_sensors(self, sender=None, data=None):
        if self.collector.is_streaming:
            log.warning('Sensor refresh may break active stream')

        # HACK: Reset sounddevice module before listing new devices.
        # This shouldn't be included in `FindDigiducers` function bc
        # it may break active streams if called a the wrong time.
        # This is necessary to acheieve hotplugging of sensors while app is open w/o restart
        vibechecker.util.sounddevice._terminate()
        vibechecker.util.sounddevice._initialize()
        # ENDHACK

        self.found_sensors = { str(s.device_id) + ' '+ str(s.model_name): s for s in VibeSensor.find() }
        dpg.configure_item('sensor_select', items=list(self.found_sensors.keys()))

        log.info(f'Discovered {len(self.found_sensors)-1} sensors. IDs = {', '.join([str(s.device_id) for s in self.found_sensors.values()])}')
            
    def connect_sensor(self, sender=None, data=None):
        name = dpg.get_value('sensor_select')

        if not name:
            log.warning('No sensor selected, try again')
            return

        sensor = self.found_sensors[name]

        try:
            log.info(f'Connecting sensor {sensor})')
            self.collector.connect_sensor(sensor)
        except vibechecker.util.sounddevice.PortAudioError as e:
            log.info('Selected device is not longer available, try again')
            self.disconnect_sensor()
            self.refresh_sensors()
            dpg.set_value('sensor_select','')
    
    def disconnect_sensor(self, sender=None, data=None):
        log.info(f'Disconnecting sensor {self.collector.sensor}')
        self.collector.disconnect_sensor()
        dpg.set_value('sensor_select','')

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

    def dpg_debug(self):
        dpg.show_item_registry()
        log.debug('Debugger. Break here')
        
    def create_gui(self):

        dpg.create_context()

        # set nerd font
        # with dpg.font_registry():
        #     nerd_font = dpg.add_font("/home/myco/CODE/reveng/gui/font/Inconsolata/InconsolataNerdFont-Regular.ttf", 18)  # Adjust the path and size
        # dpg.bind_font(nerd_font)  # Set as default font
            
        #dpg.add_file_dialog(directory_selector=True,  show=False, callback=self.set_savedir, tag="folder_dialog", width=800 ,height=400)

        with dpg.value_registry():
            dpg.add_string_value(tag='save_dir')

        with dpg.window(label="Vibe Logger", width=1200, height=800):
            with dpg.group(horizontal=True):
                with dpg.child_window(label="Toolbar", width=300, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Acquire'):
                            dpg.add_separator()
                            dpg.add_text("Select Device")
                            dpg.add_combo(label="Device Select", tag='sensor_select', items=['<Trigger Refresh>'], callback=self.connect_sensor)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='⟳', tag='refresh_btn', callback=self.refresh_sensors)
                                dpg.add_button(label='Connect', tag='connect_btn', callback=self.connect_sensor)
                                dpg.add_button(label='Disconnect', tag='disconnect_btn', callback=self.disconnect_sensor)

                            config_width = 100
                            dpg.add_separator()
                            dpg.add_text("Acquisition Settings")
                            dpg.add_combo(label="Sample Count", tag='blocksize', items=BLOCKSIZES,
                                          width=config_width, default_value=self.collector.config.blocksize,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Sample Rate", tag='samplerate', items=SAMPLERATES, 
                                          width=config_width, default_value=self.collector.config.samplerate,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Maximum Frequency", tag='maxfreq', items=[250., 500., 1_000., 2_000., 5_000., 10_000.],
                                          width=config_width, default_value=self.collector.config.maxfreq,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Frequnecy Bin Size", tag='binsize', items=sorted([0.5, 1.0, 2.0, 5.0, 10.0]),
                                          width=config_width, default_value=self.collector.config.binsize,
                                          callback=self.update_streaming_config)
                            with dpg.group(horizontal=True):
                                dpg.add_input_double(label="Running Rate", tag='running_rate', default_value=0)
                                dpg.add_combo(tag='running_rate_unit', items=['CPM', 'Hz'], default_value='Hz', width=50)

                            dpg.add_separator()
                            dpg.add_text("Data Collection")
                            dpg.add_button(label=u"Start", callback=self.start_stream)
                            dpg.add_button(label=u"Stop", callback=self.stop_stream)
                            dpg.add_button(label=u"Single", callback=self.collect_sample)

                            dpg.add_input_text(label='record_path', callback=self.set_savedir)
                            dpg.add_button(label='browse..', callback=lambda: log.warning('File browser: not connected')) # TODO, implement file browsing
                            
                            with dpg.group(horizontal=True):
                                dpg.add_button(label="Save", callback=lambda: self.collector.save_data(name=dpg.get_value('record_path')))
                                dpg.add_button(label='Load', callback=lambda: log.warning('Load data Not Connected')) # TODO, implement data loader

                            dpg.add_separator()

                            dpg.add_button(label=u"Print Sensor Details", callback=self.view_sensor_details)

                        with dpg.tab(label='Configure'):
                            dpg.add_button(label='DEBUG DPG', callback=self.dpg_debug)
                            dpg.add_button(label='Trigger Error', callback=lambda: exec('raise Exception("Fake Error")'))
                # Right display window
                with dpg.child_window(label="Data Display", autosize_x=True, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Time Domain'):
                            with dpg.plot(label="Time Series", width=-1, height=600, tag='time_plot'):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Time, ms", tag="time_axis")
                                dpg.add_plot_axis(dpg.mvYAxis, label="mm/s/s", tag="acc_axis")

                                dpg.add_line_series(np.array([0]), np.array([0]), parent="time_axis", label="Time Domain", tag="time_data")
                        with dpg.tab(label='Frequency Domain'):
                            with dpg.plot(label="Frequency Series", width=-1, height=600, tag='freq_plot'):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Freq, hz", tag="freq_axis")
                                dpg.add_plot_axis(dpg.mvYAxis, label="Velocity, mm/s", tag="vel_axis")

                                dpg.add_line_series(np.array([0]), np.array([0]), parent="freq_axis", label="Frequency Domain", tag="freq_data")

                        # with dpg.tab(label='Running Trend'):
                            # with dpg.plot(label="Trend", width=-1, height=600, tag='trend_plot'):
                            #     # Plot legend
                            #     dpg.add_plot_legend()
                            #     dpg.add_plot_axis(dpg.mvXAxis, label="Time, s", tag="x_axis")
                            #     dpg.add_plot_axis(dpg.mvYAxis, label="", tag="y_axis")

                            #     dpg.add_line_series(np.array([0]), np.array([0]), label=self.domain, parent="y_axis", tag="trend_data")
                        
                    dpg.add_text('-', label='Status', tag='disp_status')
                    dpg.add_text('', label='Last Sample', tag='disp_timestamp')
                    dpg.add_text('', label='Frame Size', tag='disp_blocksize')
                    dpg.add_text('', label='Sample Rate', tag='disp_samplerate')
                    dpg.add_text('', label='Units', tag='disp_units')
                    dpg.add_text('', tag='debug')

    def run(self):
        log.info('Setup GUI')
        dpg.setup_dearpygui()

        log.info('Launch app window')
        dpg.create_viewport(title="Vibe Logger", width=1200, height=800)
        dpg.show_viewport()

        log.info('Start DGP backend')
        dpg.start_dearpygui()  # App runs

        log.info('Cleanup app assets')
        self.cleanup()

        log.info('App Exit')

    def cleanup(self):
        self.collector.disconnect_sensor()
        dpg.destroy_context()
