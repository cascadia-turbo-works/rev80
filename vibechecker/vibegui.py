import time
import threading
import dearpygui.dearpygui as dpg

from pathlib import Path
from typing import Union, Tuple, List
from datetime import datetime as dt

import endaq
import numpy as np

from vibechecker.vibelogger import VibeLogger
from vibechecker.vibetools import VibeSensor, VibeSample, AcquisitionSettings, BLOCKSIZES, SAMPLERATES

SAVEDIR = 'DEVDATA'

class VibeGUI:
    logger: VibeLogger
    found_sensors: List = {}
    def __init__(self):
        self.context = None
        self.logger = VibeLogger()

        self.logger.callbacks['plots'] = self.display_sample

        self.create_gui()
        self.update_streaming_config()
        self.refresh_sensors(None,None)

    def view_sensor_details(self):
        print(self.logger.sensor)
    
    def set_status_message(self, msg:str):
        dpg.set_item_label('status',msg)
    
    def update_sample_metadata(self, sample:VibeSample):
        # Update the display with the latest sample metadata
        timestring = str(sample.timestamp)

        dpg.set_value('disp_status',     f'Status:      {sample.status}')
        dpg.set_value('disp_timestamp',  f'Time:        {timestring}')
        dpg.set_value('disp_blocksize',  f'Sample Size: {sample.config.blocksize }')
        dpg.set_value('disp_samplerate', f'Sample Rate: {sample.config.samplerate} Hz')
        # TODO: Harmonize units

    def update_time_plot(self,T,A):
        dpg.set_value('time_data', [T, A])
        dpg.set_axis_limits('time_axis', T[0], T[-1])
        dpg.set_axis_limits('acc_axis', np.min(A), np.max(A))

    def update_freq_plot(self,F,V):
        dpg.set_value('freq_data', [F, V])
        dpg.set_axis_limits('freq_axis', F[0], F[-1])
        dpg.set_axis_limits('vel_axis', 0, np.max(V))

    def update_trend_plot(self,T,RMS_A):
        pass

    def display_sample(self, sample:VibeSample):
        self.update_sample_metadata(sample)

        self.update_time_plot(sample.config.time_vec, sample.get_accel())
        self.update_freq_plot(sample.config.freq_vec, sample.get_spectral_velocity())
        
    def update_streaming_config(self, sender=None, data=None):
        # Snapshot current values
        ns = int(dpg.get_value('blocksize'))
        fs = int(dpg.get_value('samplerate'))
        fm = int(float(dpg.get_value('maxfreq')))
        df = int(float(dpg.get_value('binsize')))

        print(ns,fs,fm,df)
        print(sender, data)

        if sender in ['blocksize', 'samplerate']:
            self.logger.config.set_time_params(blocksize=ns, samplerate=fs)
        elif sender in ['maxfreq', 'binsize']:
            self.logger.config.set_freq_params(maxfreq=fm, binsize=df)
        
        dpg.set_value('maxfreq', self.logger.config.maxfreq)
        dpg.set_value('binsize', self.logger.config.binsize)
        dpg.set_value('samplerate', self.logger.config.samplerate)
        dpg.set_value('blocksize', self.logger.config.blocksize)

    def set_savedir(self, sender, data):
        if Path(data).is_dir():
            self.logger.datadir = data
            print('Set_Savedir: valid path set')
        
    def refresh_sensors(self, sender, data):
        self.found_sensors = { str(s.device_id) + ' '+ str(s.model_name): s for s in VibeSensor.find() }
        dpg.configure_item('sensor_select', items=list(self.found_sensors.keys()))
            
    def connect_sensor(self, sender, data):
        name = dpg.get_value('sensor_select')
        self.logger.select_sensor(self.found_sensors[name])
        self.logger.connect_sensor()
    
    def disconnect_sensor(self, sender, data):
        self.logger.disconnect_sensor()

    def dpg_debug(self):
        dpg.show_item_registry()
        print('Debugger. Break here')
        
    def create_gui(self):

        dpg.create_context()

        # set nerd font
        # with dpg.font_registry():
        #     nerd_font = dpg.add_font("/home/myco/CODE/reveng/vibegui/font/Inconsolata/InconsolataNerdFont-Regular.ttf", 18)  # Adjust the path and size
        # dpg.bind_font(nerd_font)  # Set as default font
            
        dpg.add_file_dialog(directory_selector=True,  show=False, callback=self.set_savedir, tag="folder_dialog", width=800 ,height=400)

        with dpg.value_registry():
            dpg.add_string_value(tag='save_dir')

        with dpg.window(label="Vibe Logger", width=1200, height=800):
            with dpg.group(horizontal=True):
                with dpg.child_window(label="Toolbar", width=300, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Acquire'):
                            dpg.add_separator()
                            dpg.add_text("Select Device")
                            with dpg.group(horizontal=True):
                                dpg.add_combo(label="Device Select", tag='sensor_select', items=['<Trigger Refresh>'], callback=self.connect_sensor)
                                dpg.add_button(label='⟳', tag='refresh_btn', callback=self.refresh_sensors)
                            with dpg.group(horizontal=True):
                                dpg.add_button(label='Connect', tag='connect_btn', callback=self.connect_sensor)
                                dpg.add_button(label='Disconnect', tag='disconnect_btn', callback=self.disconnect_sensor)

                            config_width = 100
                            dpg.add_separator()
                            dpg.add_text("Acquisition Settings")
                            dpg.add_combo(label="Sample Count", tag='blocksize', items=list(map(int,np.pow(2, np.arange(8,15)))),
                                          width=config_width, default_value=self.logger.config.blocksize,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Sample Rate", tag='samplerate', items=SAMPLERATES, 
                                          width=config_width, default_value=self.logger.config.samplerate,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Maximum Frequency", tag='maxfreq', items=[250, 500, 1_000, 2_000, 5_000, 10_000],
                                          width=config_width, default_value=self.logger.config.maxfreq,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Frequnecy Bin Size", tag='binsize', items=sorted([.5, 1, 2, 5, 10]),
                                          width=config_width, default_value=self.logger.config.binsize,
                                          callback=self.update_streaming_config)
                            with dpg.group(horizontal=True):
                                dpg.add_input_double(label="Running Rate", tag='running_rate', default_value=0)
                                dpg.add_combo(tag='running_rate_unit', items=['CPM', 'Hz'], default_value='Hz', width=50)

                            dpg.add_separator()
                            dpg.add_text("Data Collection")
                            dpg.add_button(label=u"Start", callback=self.logger.start_stream)
                            dpg.add_button(label=u"Stop", callback=self.logger.stop_stream)
                            dpg.add_button(label=u"Single", callback=lambda: self.display_sample(self.logger.collect_sample()))

                            dpg.add_input_text(label='record_path', callback=self.set_savedir)
                            dpg.add_button(label='browse..', callback=lambda: print('not connected'))

                            dpg.add_separator()

                            dpg.add_button(label=u"Print Sensor Details", callback=self.view_sensor_details)

                        with dpg.tab(label='Configure'):
                            dpg.add_button(label='DEBUG DPG', callback=self.dpg_debug)
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

    def run(self):
        dpg.setup_dearpygui()
        dpg.create_viewport(title="Vibe Logger", width=1200, height=800)
        dpg.show_viewport()
        print('Starting App window')
        dpg.start_dearpygui()  # App runs
        print('App exited')
        self.cleanup() 
        dpg.destroy_context()

    def cleanup(self):
        self.logger.disconnect_sensor()

def main():

    app = VibeGUI()
    app.run()

if __name__ == "__main__":
    main()