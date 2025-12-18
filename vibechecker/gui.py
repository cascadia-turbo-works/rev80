# Vibechecker frontend

import dearpygui.dearpygui as dpg

from path import Path
from typing import Union, Tuple, List, Literal
from datetime import datetime as dt

import endaq
import numpy as np 

import vibechecker

SAVEDIR = Path('DEVDATA')
EXT = '.pkl'
UNITS = {'Earth Gravity - g': 'g',
         'Metric - mm': 'mm',
         'Imperial - in': 'in'}
UNITS_REV = {v:k for k,v in UNITS.items()}

log = vibechecker.get_logger('gui')

class GUI:
    collector: vibechecker.DataCollector
    found_sensors: dict = {}
    def __init__(self):
        self.context = None
        self.collector = vibechecker.DataCollector()

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

    def sample_unit_callback(self, sender, data):
    
        if sender == 'sample_units':
            self.collector.sample.target_unit = UNITS[data] # type: ignore

        # resulting_units = UNITS_REV[self.collector.sample.target_unit]
        # dpg.set_value('sample_units', resulting_units)

        if not self.collector.is_streaming:
            self.display_sample(self.collector.sample)

        freq_label = dpg.get_value('sample_units')
        if dpg.get_value('sample_integration') == 'Acceleration':
            freq_label += '/s^2'
        elif dpg.get_value('sample_integration') == 'Velocity':
            freq_label += '/s'

        dpg.configure_item('freq_axis', label=freq_label)
    
    def update_sample_metadata(self, sample:vibechecker.VibeSample):
        # Update the display with the latest sample metadata
        timestring = str(sample.timestamp)

        dpg.set_value('disp_status',     f'Status:      {sample.status}')
        dpg.set_value('disp_timestamp',  f'Time:        {timestring}')
        dpg.set_value('disp_blocksize',  f'Sample Size: {sample.config.blocksize }')
        dpg.set_value('disp_samplerate', f'Sample Rate: {sample.config.samplerate} Hz')

    def update_time_plot(self,sample:vibechecker.VibeSample):
        T = sample.config.time_vec
        T, A = sample.get_accel()

        dpg.set_value('time_data', [T, A])
        dpg.set_axis_limits('time_axis', T[0], T[-1])
        dpg.set_axis_limits('acc_axis', np.min(A), np.max(A))

    def update_freq_plot(self,sample:vibechecker.VibeSample):

        freq_unit = dpg.get_value('sample_integration')
        if freq_unit == 'Velocity':
            F, V = sample.get_spectral_velocity()
        elif freq_unit == 'Acceleration':
            F, V = sample.get_spectral_accel()

        iicrop = F < self.collector.config.maxfreq
        F = F[iicrop]
        V = V[iicrop]

        dpg.set_value('freq_data', [F, V])
        dpg.set_axis_limits('freq_axis', F[0], F[-1])
        dpg.set_axis_limits('vel_axis', 0, np.max(V))

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, sample:vibechecker.VibeSample):
        if not sample.raw_data.size > 0:
            return
        
        unit = UNITS[dpg.get_value('sample_units')]
        self.collector.sample.target_unit = unit # type:ignore

        self.update_sample_metadata(sample)

        self.update_time_plot(sample)
        self.update_freq_plot(sample)

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

    def set_savedir(self, sender=None, data=str):
        p = Path(data)
        if p.is_dir():
            self.collector.datadir = p
            log.info(f'Set datapath: valid path set to {data}')
        
    def refresh_sensors(self, sender=None, data=None):
        if self.collector.is_streaming:
            log.warning('Sensor refresh may break active stream')

        self.found_sensors = { str(s.device_id) + ' '+ str(s.model_name): s for s in vibechecker.VibeSensor.find() }
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
        except vibechecker.sounddevice.PortAudioError as e:
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

    def browser_handler(self, sender, data):
        dpg.set_value('record_path', data['file_name'])
        self.collector.load_data(self.load_target())

    def save_target(self) -> Path:
        name = dpg.get_value('record_path')

        if dpg.get_value('timestamp_savefile'):
            name += '_' + str(dt.now().strftime('%Y-%m-%d_%H-%M-%S'))

        name += EXT

        return Path.joinpath(SAVEDIR, name)
    
    def load_target(self) -> Path:
        name = dpg.get_value('record_path')
        if not name.endswith(EXT):
            name += EXT
        return Path.joinpath(SAVEDIR, name)

    def dpg_debug(self):
        dpg.show_item_registry()
        log.debug('Debugger. Break here')
        
    def create_gui(self):

        dpg.create_context()
            
        with dpg.file_dialog(show=False, default_path=SAVEDIR, callback=self.browser_handler, id="file_dialog", width=700 ,height=400):
            dpg.add_file_extension("Vibe Samples (*.pkl){.pkl}", color=(150, 255, 150, 255))
            dpg.add_file_extension(".*", color=(0, 150, 150, 150))
            dpg.add_file_extension("", color=(150, 255, 150, 255))


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
                            dpg.add_combo(label="Sample Count", tag='blocksize', items=tuple(map(str,vibechecker.BLOCKSIZES)),
                                          width=config_width, default_value=str(self.collector.config.blocksize),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Sample Rate", tag='samplerate', items=tuple(map(str,vibechecker.SAMPLERATES)),
                                          width=config_width, default_value=str(self.collector.config.samplerate),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Maximum Frequency", tag='maxfreq', items=['250', '500', '1000', '2000', '5000', '10000'],
                                          width=config_width, default_value=str(self.collector.config.maxfreq),
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Frequnecy Bin Size", tag='binsize', items=['0.5', '1.0', '2.0', '5.0', '10.0'],
                                          width=config_width, default_value=str(self.collector.config.binsize),
                                          callback=self.update_streaming_config)
                            with dpg.group(horizontal=True):
                                dpg.add_input_double(label="Running Rate", tag='running_rate', default_value=0)
                                dpg.add_combo(tag='running_rate_unit', items=['CPM', 'Hz'], default_value='Hz', width=50)

                            dpg.add_separator()
                            dpg.add_text("Data Collection")
                            dpg.add_button(label=u"Start", callback=self.start_stream)
                            dpg.add_button(label=u"Stop", callback=self.stop_stream)
                            dpg.add_button(label=u"Single", callback=self.collect_sample)

                            with dpg.group(horizontal=True):
                                dpg.add_input_text(label='', tag='record_path')
                                dpg.add_button(label='browse..', callback=lambda: dpg.show_item('file_dialog')) # TODO, implement file browsing
                            dpg.add_checkbox(label='timestamp', tag='timestamp_savefile')
                            
                            with dpg.group(horizontal=True):
                                dpg.add_button(label="Save", callback=lambda: self.collector.save_data(self.save_target()))
                                dpg.add_button(label='Load', callback=lambda: self.collector.load_data(self.load_target())) 

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

                                dpg.add_line_series([0.], [0.], parent="time_axis", label="Time Domain", tag="time_data")
                        with dpg.tab(label='Frequency Domain'):
                            with dpg.plot(label="Frequency Series", width=-1, height=600, tag='freq_plot'):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Freq, hz", tag="freq_axis")
                                dpg.add_plot_axis(dpg.mvYAxis, label="Velocity, mm/s", tag="vel_axis")

                                dpg.add_line_series([0.], [0.], parent="freq_axis", label="Frequency Domain", tag="freq_data")

                    dpg.add_combo(label='Sample Units', tag='sample_units', callback=self.sample_unit_callback,
                                    items=list(UNITS.keys()), default_value='Earth Gravity - g')                                                
                    dpg.add_combo(label="Sample Integration", tag='sample_integration', callback=self.sample_unit_callback,
                                    items=['Velocity', 'Acceleration'], default_value='Acceleration')

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
