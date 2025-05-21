# Vibe logger

import numpy as np
import sounddevice as sd
from dataclasses import dataclass
from datetime import datetime as dt

import threading
import time
import queue

from vibetools_2 import GenerateVibrationData, FindDigiducerDevice, SAMPLERATES

@dataclass
class VibeDevice:
    device_id: int
    model_name: str
    serial_number: str
    manufacture_date: dt
    format_id: int
    sensitivity: list
    scale: np.ndarray
    units: list
    active_channel: int
    simulation: bool = False

@dataclass
class VibeSettings:
    blocksize: int
    samplerate: int
    channel: int
    units: str

    pipeline = []

def connect_sensor(dev:VibeDevice, callback=None):
    '''
    Connect to the device and return a stream object
    '''
    if dev.simulation:
        # Simulate a device connection
        raise Exception('Simulation not implemented yet')
    else:
        return sd.InputStream(
                    device=dev.device_id, 
                    channels=2, 
                    samplerate=dev.samplerate, 
                    dtype='float32', 
                    blocksize=dev.blocksize,
                    callback=callback
                )

class VibeLogger:
    '''
    This class collects, analyzes, logs and loads data from the vibration sensor defined in    
    '''

    def __init__(self):
        self.sensor = None
        self.settings = VibeSettings(blocksize=1024, samplerate=1000, channel=0)
        self.stream = None
        self.data = {'last_sample': None, 'samples': 0, 'trend': [], 'queue': queue.Queue()}

    def select_sensor(self):
        '''
        Select the device to use for data collection
        '''
        try:
            devices = FindDigiducerDevice()
        except Exception as e:
            print(e)
        
        # Select the first device
        self.sensor = devices[0]

    def connect_sensor(self):
        if self.device is None:
            print('Select sensor first')
            return
        
        self.stream = connect_sensor(self.sensor, self.raw_data_callback)

    def disconnect_sensor(self):

        if self.stream is None:
            print('Disconnect: No sensor connected')
            return
        
        self.stop_stream()
        self.stream.close()
        self.stream = None

    def start_stream(self):
        if self.stream is None:
            print('Start: No sensor connected')
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
            print('Start: No sensor connected')
            return
        
        if not self.stream.active:
            print('Stop Stream: Not Running')
            return

        try:
            self.stream.start()
        except Exception as e:
            print(e)

    def collect_sample(self):
        """Collects a single sample from the device."""

        self.last_sample = None
        self.start_stream()

        while not self.last_sample:
            time.sleep(0.01)

        self.stop_stream()

        return self.last_sample
    
    def update_settings(self, settings=None, blocksize=None, samplerate=None, channel=None):
        '''
        Update the settings for the device
        '''

        paused_running_stream = self.stream.active
        if paused_running_stream:
            self.stream.stop()

        if isinstance(settings, VibeSettings):
            self.settings = settings
        if isinstance(blocksize, int):
            self.settings.blocksize = blocksize
        if isinstance(samplerate, int):
            self.settings.samplerate = samplerate
        if isinstance(channel, int):
            self.settings.channel = channel

        if paused_running_stream:
            self.stream.start()

    def raw_data_callback(self, indata, frames, time, status):
        data = indata[:,self.settings.channel] * self.sensor['scale'][self.settings.channel]
        self.last_sample = {'data': data,
                            'blocksize': frames,
                            'samplerate': self.settings.samplerate,
                            'units': self.settings.units,
                            'timestamp': time,
                            'status': status}
        
        self.data['queue'].put(self.last_sample)

    def data_callback(self, sample: dict):
        pass


if __name__ == "__main__":
    vs = VibeSettings()

    print('done.')