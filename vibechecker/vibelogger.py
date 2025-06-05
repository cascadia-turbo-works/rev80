# Vibe logger

import numpy as np
import pandas as pd
from datetime import datetime as dt

import os
import time
from queue import Queue
from pathlib import Path

from vibetools import VibeSensor, VibeSample, AcquisitionSettings, acceleration_to_velocity_fft, SAMPLERATES

class VibeLogger:
    '''
    This class collects, analyzes, logs and loads data from the vibration sensor defined in    
    '''
    sensor: VibeSensor = None
    settings: AcquisitionSettings = None
    stream = None
    queue: Queue = None
    datadir: Path = Path('DEVDATA')
    data: dict = {'meta': {}, 'last_sample': None, 'analysis': None, 'samples': 0, 'trend': []}
    callbacks: dict = {}

    def __init__(self, sensor:VibeSensor=None, settings:AcquisitionSettings=None):
        if sensor is not None:
            self.select_sensor(sensor)
            if settings:
                self.update_settings(settings)
            else:
                # default settings
                self.update_settings()
                
            self.connect_sensor()

    @property
    def last_sample(self):
        return self.data['last_sample']
    
    @last_sample.setter
    def last_sample(self, sample):
        self.data['lastsample'] = sample

    def select_sensor(self, sensor=None):
        '''
        Select the device to use for data collection
        '''
        assert isinstance(sensor, VibeSensor), "Select Sensor: Invalid sensor"

        if self.stream is not None:
            # Disconnect any connected sensor first
            self.disconnect_sensor()
        
        self.sensor = sensor

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
        self.flush_data_queue  # clear all items from the queue

    def start_data_queue(self):
        if self.queue is None:
            self.queue = Queue()
        else:
            print('Start Data Queue: Queue is active')

    def get_data_queue(self):
        if self.queue is None:
            print('VibeLogger:Get Data Queue:: Initiate queue')
            return None
        
        return self.queue.queue.get()
    
    def flush_data_queue(self):
        self.queue.queue.clear()

    def kill_data_queue(self):
        self.flush_data_queue()
        self.queue = None

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

        for _ in range(10):
            if self.last_sample:
                break
            time.sleep(0.01)

        self.stop_stream()

        return self.last_sample
    
    def update_settings(self, blocksize:int=None, samplerate:int=None, channel:int=None, settings:AcquisitionSettings=None):
        '''
        Update the stream acquisition settings for the sensor
        '''

        if not settings:
            if not blocksize:
                blocksize = 1024
            if not samplerate:
                samplerate = SAMPLERATES[0]
            if not channel:
                channel = 0
            settings = AcquisitionSettings(blocksize, samplerate, channel)
        else:
            assert isinstance(settings, AcquisitionSettings), "Invalid settings"

        # apply new settings
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

    def save_data(self, name=None):
        ext = '.pkl'

        if not target.exists():
            print(f'Save: target does not exist {target}')
            return
        
        if target.is_dir():
            target = Path.joinpath(target, dt.now().strftime('%Y-%m-%d_%H-%M-%S') + ext)

        if not target.name.endswith(ext):
            target = Path(target.name + ext)    

        pd.to_pickle(self.data, target)

        return target

    def load_data(self, name=None):
        ext = '.pkl'

        if not isinstance(name, Path):
            target = Path.joinpath(self.datadir, name)

        if not ( target.is_file() and target.as_posix().endswith(ext) ):
            print(f'Not a valid file path to a pickle file: ${target}')
            return

        self.data = pd.read_pickle(target)

    def raw_data_callback(self, indata, frames, timestamp, status):
        '''log and analyze incoming data stream'''
        g2mms2 = 9.81 * 1e3

        sample = VibeSample()

        sample.timestamp= timestamp.currentTime
        sample.status   = status
        sample.samplerate = self.settings.samplerate
        sample.blocksize = frames
        
        # TIME
        sample.time = np.arange(frames) / sample.samplerate
        sample.acc_mmps2  = g2mms2 * indata[:,self.settings.channel] * self.sensor.scale[self.settings.channel]

        # FREQ
        freqs = np.fft.fftfreq(frames, 1/sample.samplerate)
        acc_f = np.fft.fft(sample.acc_mmps2) / frames
        vel_f = np.zeros_like(acc_f, dtype=np.complex128)
        nonzero_freq = freqs!=0
        vel_f[nonzero_freq] = acc_f[nonzero_freq]/ (1j * 2 * np.pi * freqs[nonzero_freq])


        sample.freq = freqs[:frames//2]
        sample.acc_f = 2 * np.abs(acc_f[:frames//2])
        sample.vel_f = 2 * np.abs(vel_f[:frames//2])
        
        self.data['last_sample'] = sample

        if self.queue is not None:
            self.queue.put(sample)

    def data_callback(self, sample):
        for fn in self.callbacks.items():
            fn(sample)

 
if __name__ == "__main__":
    print('Nothing to do. Run pytest.')
