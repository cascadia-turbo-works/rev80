# Vibe logger

import numpy as np
from datetime import datetime as dt

import time
import queue

from vibetools import VibeSensor,  AcquisitionSettings, SimulatedSensor, SAMPLERATES

class VibeLogger:
    '''
    This class collects, analyzes, logs and loads data from the vibration sensor defined in    
    '''
    sensor: VibeSensor = None
    settings: AcquisitionSettings = None
    stream = None
    data: dict = {'last_sample': None, 'samples': 0, 'trend': [], 'queue': queue.Queue()}

    def __init__(self):
        pass

    @property
    def last_sample(self):
        return self.data['last_sample']

    def select_sensor(self):
        '''
        Select the device to use for data collection
        '''

        if self.stream is not None:
            # Disconnect any connected sensor first
            self.disconnect_sensor()

        try:
            devices = VibeSensor.find()
        except Exception as e:
            print(e)
        
        # Select the first device
        self.sensor = devices[0]

        # TODO: Allow selection from multiple devices.

    def connect_sensor(self):
        '''
        Connect to the device and return a stream object
        '''

        if self.sensor is None:
            print('Connect: No sensor connected')
        if self.settings is None:
            print('Connect: No settings implemented')
            return
        
        self.stream = self.sensor.connect(self.settings, self.raw_data_callback)

    def disconnect_sensor(self):

        if self.stream is None:
            print('Disconnect: No sensor connected')
            return
        
        if self.stream.active:
            self.stop_stream()

        self.stream.close()
        self.stream = None

    def start_stream(self):
        if self.stream is None:
            print('Start Stream: No sensor connected')
            return
        
        if self.stream.active:
            print('Start Stream: Already Running')
            return

        try:
            self.stream.start()
        except Exception as e:
            print(e)

    def stop_stream(self):
        if self.stream is None:
            print('Stop Stream: No sensor connected')
            return
        
        if not self.stream.active:
            print('Stop Stream: Not Running')
            return

        try:
            self.stream.stop()
        except Exception as e:
            print(e)

    def collect_sample(self):
        """Collects a single sample from the device."""

        self.data['last_sample'] = None
        self.start_stream()

        while not self.last_sample:
            time.sleep(0.01)

        self.stop_stream()

        return self.last_sample
    
    def update_settings(self, settings:AcquisitionSettings):
        '''
        Update the settings for the device
        '''
        # assert False, "Not supported - requires disconnect - reconnect"
        # TODO: Implement

        unwind = 1

        if self.stream is not None:
            unwind = unwind<<1
            if self.stream.active:
                unwind = unwind<<1
                print('UpdateSettings: Stopping Stream')
                self.stop_stream()

            print('UpdateSettings: Disconnecting Sensor')
            self.disconnect_sensor()

        print(f'UpdateSettings: Receiving settings: {settings}')
        self.settings = settings

        if unwind > 1:
            unwind = unwind >> 1
            print('UpdateSettings: Reconnecting sensor')
            self.connect_sensor()
        
        if unwind > 1:
            unwind = unwind >>1
            print('UpdateSettings: Restarting stream')
            self.start_stream()

    def raw_data_callback(self, indata, frames, timestamp, status):

        data = indata[:,self.settings.channel] * self.sensor.scale[self.settings.channel]

        self.data['last_sample'] = {'data': data,
                            'blocksize': frames,
                            'samplerate': self.settings.samplerate,
                            'units': self.sensor.units,
                            'timestamp': timestamp.currentTime,
                            'status': status}
        
        self.data['queue'].put(self.last_sample)

    def data_callback(self, sample: dict):
        pass

def test_stream(domain='TIME'):
    import matplotlib.pyplot as plt

    channel = 0

    # binsize = 1 # hz
    # max_freq = 5000 # khz

    # blocksize = max_freq // binsize
    # samplerate = max_freq * 2

    blocksize = 1024
    samplerate = 8000

    plot_update_period = 0.01
    max_samples = 30
    settings = AcquisitionSettings(blocksize, samplerate, channel)
    vibr = VibeLogger()
    vibr.update_settings(settings)
    # vibr.sensor = VibeSensor.simulated()
    vibr.select_sensor()
    vibr.connect_sensor()

    try:
        sample = vibr.collect_sample()
        last_update_time = 0. #sample['time']

        ax_scale = [0,0,-1,1]
        match domain:
            case 'TIME':
                X = np.arange(settings.blocksize) / settings.samplerate
                yfun = lambda y: y
                ax_scale = [X[0], X[-1], -4, 4]
                xlab = 'Time, ms'
                ylab = 'Amplitude'
            case 'FREQ':
                X = np.fft.fftfreq(settings.blocksize,1/settings.samplerate)[:settings.blocksize//2]
                yfun = lambda y: np.abs(np.fft.fft(y))[:settings.blocksize//2]
                ax_scale = [X[1], X[-1], 0, 100]
                xlab = 'Frequency, Hz'
                ylab = 'Amplitude'

        Y = yfun(sample['data'])

        plt.ion()
        fig, ax = plt.subplots()
        plt.title("Digiducer Stream: " + vibr.sensor.model_name, fontsize=20)
        plt.xlabel(xlab)
        plt.ylabel(ylab)
        line, = plt.plot(X, Y)
        # ax.set_xlim(ax_scale[:2])
        # ax.set_ylim(ax_scale[2:])

        vibr.start_stream()
        for _ in range(max_samples):
            if not plt.fignum_exists(fig.number):
                print('Window closed!')
                break

            sample = vibr.data['queue'].get()

            data = sample['data']

            Y = yfun(data)
            # ax.set_ylim([max(min(Y), 1e-3), max(Y)])

            if sample['timestamp'] >= last_update_time + plot_update_period:

                line.set_ydata(Y)
                fig.canvas.draw()
                fig.canvas.flush_events()
                print(sample['status'], sample['data'].shape)
                last_update_time = sample['timestamp']
    

    finally:
        vibr.stop_stream()
        vibr.disconnect_sensor()
        plt.close(fig)
    
def test_save():
    vs = AcquisitionSettings(1024, 8000, 0)

    vl = VibeLogger()
    vl.update_settings(vs)

    vl.select_sensor()

    vl.connect_sensor()
    samp = vl.collect_sample()
    vl.disconnect_sensor()

    print(samp)
    print('done.')
    
if __name__ == "__main__":
    test_stream('FREQ')
    test_save()
