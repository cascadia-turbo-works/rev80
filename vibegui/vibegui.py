import dearpygui.dearpygui as dpg
from digiducer import VibrationDevice
from vibetools import acceleration_to_velocity_fft
from typing import Union, Tuple, List
import threading
import typing
import numpy as np
import endaq


class VibeGUI:

    ICON_LARGE = '/usr/share/icons/manjaro/green/128x128.png'
    ICON_SMALL = '/usr/share/icons/manjaro/green/24x24.png'

    def __init__(self):
        self.device:dict = None
        self.domain: typing.Literal([None, 'TIME','FREQ','TREND']) = 'TIME'
        self.stream = None

        self.create_gui()

    def set_device(self,device):
        self.device = device

    def view_sensor_details(self):
        print(self.device.info)
    
    def set_status_message(self, msg:str):
        dpg.set_item_label('status',msg)

    def view_time_domain_data(self, x, y):
        self.set_status_message("Displaying time-domain data...")
        # dpg.delete_item("Freq", children_only=True)
        # with dpg.plot_axis(dpg.mvXAxis, label="Time", parent="Freq") as x_axis:
        #     pass
        # with dpg.plot_axis(dpg.mvYAxis, label="Amplitude", parent="Time") as y_axis:
        #     dpg.add_line_series(x, y, label="Time Domain", parent=y_axis)

        dpg.set_value('plot', [x, y])

        # Enable auto-scaling
        dpg.set_axis_auto_fit("x_axis")
        dpg.set_axis_auto_fit("y_axis")

    def save_time_domain_data(self):
        self.set_status_message("Saving time-domain data...")

    def view_frequency_domain_data(self, x, y):
        self.set_status_message("Displaying frequency-domain data...")
        # Placeholder data for plot
        
        dpg.set_value('plot', [x, y])

    def save_frequency_domain_data(self):
        self.set_status_message("Saving frequency-domain data...")

    def view_trend_data(sender, data):
        dpg.set_item_label('status','Trend not supported yet')
        # Placeholder data for plot
        x = list(range(100))
        y1 = [i*0.5 for i in x]
        y2 = [i*0.2 for i in x]
        clear_plot("Left Pane")
        clear_plot("Right Pane")
        add_line_series("Left Pane", "Trend 1", x, y1, weight=2)
        add_line_series("Right Pane", "Trend 2", x, y2, weight=2)

    def save_trend_data(sender, data):
        self.set_status_message("Saving trend data...")
    
    def stop_collection(self):
        if self.device.running:
            self.device.stop_stream()
        else:
            print('Already stopped!')

        if self.stream:
            self.stream.join()
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
        while self.device.running:
            self.update_plot(self.device.get())

    def collect_sample(self):
        if self.device.running or self.stream:
            print('Stopping stream..')
            self.stop_collection()
        
        sample = self.device.collect_sample()

        if not sample:
            print('Invalid sample')
            return

        self.update_plot(sample)

    def update_plot(self, sample):
        T = self.device.time_axis

        F, A, V = acceleration_to_velocity_fft(sample['data'], self.device.samplerate)

        dpg.set_value('time_data', [T, A])
        dpg.set_axis_limits_auto('time_axis')
        dpg.set_axis_limits_auto('acc_axis')


        dpg.set_value('freq_data', [F, V])
        dpg.set_axis_limits_auto('freq_axis')
        dpg.set_axis_limits_auto('vel_axis')

        if self.device.trend:
            X = np.array([0])
            Y = np.array([0])
        
    def create_gui(self):

        dpg.create_context()

        # set nerd font
        # with dpg.font_registry():
        #     nerd_font = dpg.add_font("/home/myco/CODE/reveng/vibegui/font/Inconsolata/InconsolataNerdFont-Regular.ttf", 18)  # Adjust the path and size
        # dpg.bind_font(nerd_font)  # Set as default font

        with dpg.window(label="Vibe Logger", width=1200, height=800):
            with dpg.group(horizontal=True):
                with dpg.child_window(label="Toolbar", width=300, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Acquire'):
                            dpg.add_text("Data Collection")
                            dpg.add_button(label=u"Start", callback=self.start_collection)
                            dpg.add_button(label=u"Stop", callback=self.stop_collection)
                            dpg.add_button(label=u"Single", callback=self.collect_sample)
                            dpg.add_separator()

                            dpg.add_button(label=u"View Sensor Details", callback=self.view_sensor_details)
                            dpg.add_separator()

                            dpg.add_text("Time Domain Data")
                            dpg.add_button(label="View", callback=lambda: self.__setattr__('domain', 'TIME'))
                            dpg.add_button(label="Save", callback=self.save_time_domain_data)
                            dpg.add_separator()

                            dpg.add_text("Frequency Domain Data")
                            dpg.add_button(label="View", callback=lambda: self.__setattr__('domain', 'FREQ'))
                            dpg.add_button(label="Save", callback=self.save_frequency_domain_data)
                            dpg.add_separator()

                            dpg.add_text("Trend Data")
                            dpg.add_button(label="View", callback=lambda: self.__setattr__('domain', 'TREND'))
                            dpg.add_button(label="Save", callback=self.save_trend_data)
                        with dpg.tab(label='Configure'):
                            config_width = 100
                            dpg.add_combo(label="Sample Size", items=list(map(int,np.pow(2, np.arange(8,15)))), default_value=2**10, 
                                          width=config_width, callback=lambda sender, value: self.device.set_blocksize(int(value)))
                            dpg.add_combo(label="Sample Rate", items=[8000, 11050, 16000, 22100, 32000, 44100, 48000], 
                                          width=config_width, default_value=8000, callback=lambda sender, value: self.device.set_samplerate(int(value)))
                            dpg.add_combo(label="Bin Size", items=sorted([.25, .5, 1, 2, 5, 10]), default_value=1, width=config_width)
                            dpg.add_combo(label="Max Freq", items=[250, 500, 1000, 2000, 5000, 10_000], default_value=2000, width=config_width)
                            with dpg.group(horizontal=True):
                                dpg.add_input_double(label="Running Rate", tag='running_rate', default_value=0)
                                dpg.add_combo(tag='running_rate_unit', items=['CPM', 'Hz'], default_value='Hz', width=50)
                # Right display window
                with dpg.child_window(label="Display", autosize_x=True, autosize_y=True):
                    with dpg.tab_bar():
                        with dpg.tab(label='Time Domain'):
                            with dpg.plot(label="Time Series", width=-1, height=600, tag='time_plot'):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Time, ms", tag="time_axis")
                                dpg.add_plot_axis(dpg.mvYAxis, label="mm/s/s", tag="acc_axis")

                                dpg.add_line_series(np.array([0]), np.array([0]), label=self.domain, parent="time_axis", tag="time_data")

                        with dpg.tab(label='Frequency Domain'):
                            with dpg.plot(label="Frequency Series", width=-1, height=600, tag='freq_plot'):
                                # Plot legend
                                dpg.add_plot_legend()
                                dpg.add_plot_axis(dpg.mvXAxis, label="Freq, hz", tag="freq_axis")
                                dpg.add_plot_axis(dpg.mvYAxis, label="Velocity, mm/s", tag="vel_axis")

                                dpg.add_line_series(np.array([0]), np.array([0]), label=self.domain, parent="freq_axis", tag="freq_data")
                        # with dpg.tab(label='Running Trend'):
                            # with dpg.plot(label="Trend", width=-1, height=600, tag='trend_plot'):
                            #     # Plot legend
                            #     dpg.add_plot_legend()
                            #     dpg.add_plot_axis(dpg.mvXAxis, label="Time, s", tag="x_axis")
                            #     dpg.add_plot_axis(dpg.mvYAxis, label="", tag="y_axis")

                            #     dpg.add_line_series(np.array([0]), np.array([0]), label=self.domain, parent="y_axis", tag="trend_data")
                        
                    dpg.add_text('Initial', label='Status', tag='status')

    def run(self):
        dpg.setup_dearpygui()
        dpg.create_viewport(title="Vibe Logger", width=1200, height=800)
        dpg.show_viewport()

        dpg.start_dearpygui()  # App runs

        self.cleanup()
        dpg.destroy_context()

    def cleanup(self):
        self.stop_collection()


if __name__ == "__main__":

    vd = VibrationDevice(blocksize=1024, samplerate=8000, simulate=False)

    app = VibeGUI()
    app.set_device(vd)

    app.run()
