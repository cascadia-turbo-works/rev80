# Data Collector

import numpy as np
import pickle
from datetime import datetime as dt
from queue import Queue
from path import Path
from typing import Union, Literal, List, Tuple, Dict
import sounddevice

import vibechecker

log = vibechecker.get_logger('collector')
ui = vibechecker.UI_Elements()

class DataCollector:
    '''
    This class collects, analyzes, logs and loads data from the vibration sensor
    '''
    sensor: Union[vibechecker.VibeSensor, None] = None

    # TODO: Make sensor take ownership of config. shouldn't be owned by collector
    config: vibechecker.AcquisitionSettings
    stream = None
    queue: Union[Queue, None] = None
    datadir: Union[Path, None] = Path('DEVDATA')
    data: Dict = {}
    callbacks: Dict = {}

    def __init__(self, 
                 sensor: Union[vibechecker.VibeSensor, None] = None, 
                 config: Union[vibechecker.AcquisitionSettings,None] = None):

        if config:
            self.config = config
        else:
            # default settings
            self.config = vibechecker.AcquisitionSettings()

        if sensor is not None:
            self.connect_sensor(sensor)

        self.reset_data_store()

    @property
    def is_streaming(self):
        try:
            return self.sensor and self.stream and self.stream.active
        except Exception:
            log.error('Device connection may be interrupted')
            return False

    def reset_data_store(self):
        self.data = {}
        self.data['meta'] = []
        self.data['sample'] = vibechecker.VibeSample.empty()
        self.data['sample_count'] = 0
        self.data['trend'] = []
        self.data['rolling_average'] = {'N':0, 'k': 0, 'samples': []}

        log.info('Reset data store.')

    @property
    def sample(self) -> vibechecker.VibeSample:
        return self.data['sample']
    @sample.setter
    def sample(self, sample):
        self.data['sample'] = sample

    def connect_sensor(self, sensor:vibechecker.VibeSensor):
        '''
        Connect to the device and return a stream object
        '''
        if not isinstance(sensor, vibechecker.VibeSensor):
            raise TypeError(f"Attempted to select invalid sensor of {type(sensor)}")

        if self.stream is not None or self.sensor is not None:
            # Disconnect any connected sensor first
            self.disconnect_sensor()
        
        if self.config is None:
            log.error(f'Attempted to connect sensor {self.sensor} but no configuration implemented')
            return
        
        self.sensor = sensor
        self.stream = self.sensor.connect(self.config, self.recieve_data)
        log.debug(f'Connected sensor {self.sensor})')

    def disconnect_sensor(self):

        if self.is_streaming:
            # stop active stream
            self.stop_stream()

        if self.stream is not None:
            # close stream
            self.stream.close()
            self.stream = None

        if self.queue is not None:    
            self.kill_data_queue()  # clear all items from the queue

        if self.sensor:
            log.debug(f'Disconnecting sensor {self.sensor})')
            self.sensor = None

    def update_acquisition_settings(self,parameter, value):
        if parameter not in ui.ACQ:
            raise ValueError(f'Cannot set {parameter}') 
        
        stream_state = self.is_streaming
        if stream_state:
            self.stop_stream()

        if parameter == ui.ACQ_BLOCKSIZE:
            self.config.blocksize = int(value)
        elif parameter == ui.ACQ_SAMPLERATE:
            self.config.samplerate = int(value)
        elif parameter == ui.ACQ_MAXFREQ:
            self.config.maxfreq = float(value)
        elif parameter == ui.ACQ_BINSIZE:
            self.config.binsize = float(value)
        else:
            log.error('Acquisition arameter invalid')
             
        if self.sensor:
            # Reconnect sensor stream with updated settings.
            self.connect_sensor(self.sensor)

        if stream_state:
            self.start_stream()

    def start_data_queue(self):
        if self.queue is None:
            self.queue = Queue()
            log.debug('Data Queue initialized')
        else:
            log.warning('Data Queue is already active')

    def get_data_queue(self):
        if self.queue is None:
            raise RuntimeError('DataCollector:Get Data Queue:: Initilize queue before `get`')
        
        return self.queue.get()
    
    def flush_data_queue(self):
        if self.queue is None:
            log.warning('Attempted to flush inactive queue')
            return
        
        qsize = self.queue.qsize()
        self.queue.queue.clear()
        log.debug(f'Data Queue flushed ({qsize} items)')

    def kill_data_queue(self):
        if self.queue is None:
            log.warning('Attempted to kill inactive queue')
            return

        self.flush_data_queue()
        self.queue = None

        log.debug('Data Queue destroyed')

    def start_stream(self):
        '''Initiate sensor stream'''        
        if self.is_streaming:
            log.warning('Attempted Start Stream: Already Running')
            return
        
        if not self.stream:
            return

        try:
            self.stream.start()
        except sounddevice.PortAudioError: # likely means sensor disconnected
            self.disconnect_sensor()
            log.error('Error starting stream: Sensor not found')
        log.debug(f'Stream started')

    def stop_stream(self):
        '''Terminate sensor stream'''
        if not self.stream or not self.is_streaming:
            log.warning('Attempted Stop Stream: No stream running')
            return

        self.stream.stop()
        log.debug(f'Stream stopped')

    def collect_sample(self):
        """Collect single sample from sensor"""
        if self.is_streaming:
            self.stop_stream()
         
        self.start_data_queue()
        self.start_stream()

        try:
            sample = self.get_data_queue()
        except Exception:
            sample = None
            raise

        finally:
            self.stop_stream()
            self.kill_data_queue()

        return sample

    def save_data(self, target:Path):
        if target.is_file():
            log.warning('Save target exists. Delete existing file before saving.')
            return
        
        with open(target, 'wb') as f:
            pickle.dump(self.data, f)
        log.info(f'Saved current data to {target}')

        return target

    def load_data(self, target:Path):
        if not target.is_file():
            log.error(f'load_data: file does not exist: {target}')

        with open(target, 'rb') as f:
            self.data = pickle.load(f)

        self.data_callback(self.sample)

        log.info(f'Loaded data sample {target}')

    def recieve_data(self, indata:np.ndarray, frames:int, timestamp, status:str):
        '''log and preprocess incoming data stream'''

        if self.sensor is None:
            return

        data = np.ascontiguousarray(indata[:, self.config.channel])  # slice
        data *= self.sensor.scale[self.config.channel]  # scale
        data_unit = self.sensor.units[self.config.channel]

        # self.sample = vibechecker.VibeSample(status,
        #                                      timestamp.currentTime,
        #                                      self.config.samplerate, 
        #                                      data_unit,
        #                                      data)
    
        # TODO: Push acq settings to sample at capture.
        self.sample.push_sample(status,
                                timestamp.currentTime,
                                self.config.samplerate,
                                data_unit, # type: ignore
                                data) 

        self.data_callback(self.sample)

    def data_callback(self, sample):

        if self.queue is not None:
            self.queue.put(self.sample)
        else:
            for fn in self.callbacks.values():
                fn(sample)
            self.data['sample_count'] += 1

    def visualize_init(self, sample:vibechecker.VibeSample):  
        import matplotlib.pyplot as plt      
        plt.ion()
        fig, ax = plt.subplots(2,1)

        if self.sensor:
            title = "Digiducer Stream: " + self.sensor.model_name
        else:
            title = ''

        fig.suptitle(title, fontsize=20)
        ax[0].set_xlabel('Time, ms')
        ax[0].set_ylabel('Acceleration, mm/s^2')
        ax[1].set_xlabel('Frequency, Hz')
        ax[1].set_ylabel('Velocity, mm/s/hz')

        time_vec, acc_t_mmps2 = sample.get_accel(self.config)
        freq_vec, vel_f_mmps, peak = sample.get_spectrum(self.config)
        time_plot, = ax[0].plot(time_vec, acc_t_mmps2)
        freq_plot, = ax[1].plot(freq_vec, vel_f_mmps)

        vis = {'fig': fig,
               'ax': ax,
               'time_vec': time_vec,
               'freq_vec': freq_vec,
               'time_plot': time_plot,
               'freq_plot': freq_plot}

        return vis

    def visualize_sample(self, sample:vibechecker.VibeSample, vis:dict):
        time_vec, acc_t_mmps2 = sample.get_accel(self.config)
        freq_vec, vel_f_mmps, peak = sample.get_spectrum(self.config)
        
        vis['time_plot'].set_data(time_vec, acc_t_mmps2)
        vis['freq_plot'].set_data(freq_vec, vel_f_mmps)
        
        vis['fig'].canvas.draw()
        vis['fig'].canvas.flush_events()

