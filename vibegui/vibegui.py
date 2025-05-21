import dearpygui.dearpygui as dpg
from digiducer import VibrationDevice, NoDevicesFound
from vibetools import acceleration_to_velocity_fft
from typing import Union, Tuple, List
import threading
import time
import typing
from datetime import datetime as dt
import numpy as np
import endaq
import numpy as np
from tkinter import filedialog
# from file_dialog.fdialog import FileDialog

SAVEDIR = 'DEVDATA'

def nextpow2(x:int):
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))

class VibeGUI:

    def __init__(self):
        self.device = None
        self.stream = None
        self.last_stream = None

        self.create_gui()

    def set_device(self,device):
        self.device = device

    def view_sensor_details(self):
        print(self.device.info)
    
    def set_status_message(self, msg:str):
        dpg.set_item_label('status',msg)
    
    def stop_collection(self):
        if self.device.running:
            self.device.stop_stream()
        else:
            print('Already stopped!')

        if self.stream:
            self.stream.join()
            self.lsat_stream = self.stream
            self.stream = None
    
    def start_collection(self):
        if self.device.running:
            print('Already Running!')
            return

        try:
            self.device.start_stream()
        except Exception as e:
            print(e)
            print('Error connecting to device. Try again or try replugging.')
            return

        self.stream = threading.Thread(target=self.stream_samples)
        self.stream.start()
        
    def toggle_collection(self):
        if self.device.running:
            self.stop_collection()
        else:
            self.start_collection()

    def stream_samples(self):
        max_rep_rate = 10 # Hz
        while self.device.running:
            tic = dt.now()
            self.update_plot(self.device.get())
            toc = dt.now()

            elapsed_ms = (toc - tic).total_seconds()
            time.sleep(max(0, (1/max_rep_rate) - elapsed_ms))

    def collect_sample(self):
        if self.device.running or self.stream:
            print('Stopping stream..')
            self.stop_collection()
        
        sample = self.device.collect_sample()

        if not sample:
            print('Invalid sample')
            return

        self.update_plot(sample)

    def update_sample_metadata(self, sample):
        # Update the display with the latest sample metadata
        # timestring = dt.fromtimestamp(sample['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        timestring = str(sample['timestamp'])

        dpg.set_value('disp_status',     f'Status:      {sample['status']}')
        dpg.set_value('disp_timestamp',  f'Time:        {timestring}')
        dpg.set_value('disp_blocksize',  f'Sample Size: {sample['blocksize'] }')
        dpg.set_value('disp_samplerate', f'Sample Rate: {sample['samplerate']} Hz')
        dpg.set_value('disp_units',      f'Units:       {sample['units'][self.device.channel]}')

    def update_plot(self, sample):

        self.update_sample_metadata(sample)

        # Generate time axis
        T = np.arange(sample['data'].shape[0]) / self.device.samplerate

        F, A, V = acceleration_to_velocity_fft(sample['data'], self.device.samplerate)

        dpg.set_value('time_data', [T, A])
        dpg.set_axis_limits('time_axis', T[0], T[-1])
        dpg.set_axis_limits('acc_axis', np.min(A), np.max(A))

        dpg.set_value('freq_data', [F, V])
        dpg.set_axis_limits('freq_axis', F[0], F[-1])
        dpg.set_axis_limits('vel_axis', 0, np.max(V))
        
    def update_streaming_config(self, sender, data):
        # Snapshot current values
        Ns = int(dpg.get_value('blocksize'))
        Fs = int(dpg.get_value('samplerate'))
        # dF = int(dpg.get_value('binsize'))
        # Fmax = int(dpg.get_value('maxfreq'))

        # assert None not in [Fs, Ns, dF, Fmax], 'Invalid config values'
        # print(Ns,Fs,dF,Fmax)

        try:
            match dpg.get_item_label(sender):
                case 'Sample Count':
                    print('update sample count')

                case 'Sample Rate':
                    print('update sample rate')

                # case 'Max Freq' | 'Bin Size':
                #     print('update max freq, or bin size')
                #     Fs = 2 * Fmax
                #     Ns = nextpow2(Fs/dF)
                #     print('Fs: {Fs_new}, Ns: {Ns_new}')

                case _:
                    #do nothing.
                    return
        except Exception as e:
            print(e)
            
        is_running_stream = self.device.running
        if is_running_stream:
            self.stop_collection()

        self.device.blocksize = Ns
        self.device.samplerate = Fs

        if is_running_stream:
            self.start_collection()


    def set_savedir(self, sender, data):
        print(data)
        dpg.set_value('save_dir',data)
        
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
                            config_width = 100
                            dpg.add_combo(label="Sample Count", tag='blocksize', items=list(map(int,np.pow(2, np.arange(8,15)))),
                                          width=config_width, default_value=2**10,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Sample Rate", tag='samplerate', items=VibrationDevice.SAMPLERATES, 
                                          width=config_width, default_value=VibrationDevice.SAMPLERATES[0],
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Frequnecy Bin Size", tag='binsize', items=sorted([.5, 1, 2, 5, 10]),
                                          default_value=1, width=config_width,
                                          callback=self.update_streaming_config)
                            dpg.add_combo(label="Maximum Frequency", tag='maxfreq', items=[250, 500, 1_000, 2_000, 5_000, 10_000],
                                          default_value=2000, width=config_width,
                                          callback=self.update_streaming_config)
                            with dpg.group(horizontal=True):
                                dpg.add_input_double(label="Running Rate", tag='running_rate', default_value=0)
                                dpg.add_combo(tag='running_rate_unit', items=['CPM', 'Hz'], default_value='Hz', width=50)

                            dpg.add_separator()

                            dpg.add_text('None', label='record_path')
                            dpg.add_button(label='browse..', callback=lambda: print('not connected'))
                            dpg.add_text("Data Collection")
                            dpg.add_button(label=u"Start", callback=self.start_collection)
                            dpg.add_button(label=u"Stop", callback=self.stop_collection)
                            dpg.add_button(label=u"Single", callback=self.collect_sample)

                            dpg.add_separator()

                            dpg.add_button(label=u"View Sensor Details", callback=self.view_sensor_details)

                            # dpg.add_separator()

                        with dpg.tab(label='Configure'):
                            pass
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

        dpg.start_dearpygui()  # App runs

        self.cleanup()
        dpg.destroy_context()

    def cleanup(self):
        self.stop_collection()

def main():

    try:
        # Attempt running with a real device if present.
        vd = VibrationDevice(blocksize=1024, samplerate=8000, simulate=False)
    except NoDevicesFound as e:
        # Otherwise, simulate
        print('No Device connection. Fallback to simulated device.')
        vd = VibrationDevice(blocksize=1024, samplerate=8000, simulate=True)

    app = VibeGUI()
    app.set_device(vd)

    app.run()


if __name__ == "__main__":
    main()