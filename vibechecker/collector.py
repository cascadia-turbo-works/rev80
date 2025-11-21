# Vibe logger

import numpy as np
import pandas as pd
from datetime import datetime as dt

from dataclasses import replace

from queue import Queue
from pathlib import Path

from vibechecker.util import VibeSensor, VibeSample, AcquisitionSettings
from vibechecker import logger

log = logger.get_logger('collector')

class DataCollector:
    '''
    This class collects, analyzes, logs and loads data from the vibration sensor
    '''
    sensor: VibeSensor = None
    config: AcquisitionSettings = None
    stream = None
    queue: Queue = None
    datadir: Path = Path('DEVDATA')
    data: dict = None
    callbacks: dict = {}

    def __init__(self, sensor:VibeSensor=None, config:AcquisitionSettings=None):

        if config:
            self.config = config
        else:
            # default settings
            self.config = AcquisitionSettings()

        if sensor is not None:
            self.connect_sensor(sensor)

        self.reset_data_store()

    @property
    def is_streaming(self):
        try:
            is_streaming = self.sensor and self.stream and self.stream.active
        except Exception:
            log.error('Device connection may be interrupted')
            return False
        return is_streaming

    def reset_data_store(self):
        self.data = {}
        self.data['meta'] = []
        self.data['sample'] = VibeSample.empty(self.sensor, self.config)
        self.data['last_sample'] = None
        self.data['sample_count'] = 0
        self.data['trend'] = []
        self.data['rolling_average'] = {'N':0, 'k': 0, 'samples': []}

        log.info('Reset data store.')

    @property
    def last_sample(self):
        return self.data['last_sample']

    @last_sample.setter
    def last_sample(self, sample):
        self.data['lastsample'] = sample

    def connect_sensor(self, sensor:VibeSensor):
        '''
        Connect to the device and return a stream object
        '''
        if not isinstance(sensor, VibeSensor):
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
        match parameter:
            case 'blocksize':
                self.config.blocksize = value
            case 'samplerate':
                self.config.samplerate = value
            case 'maxfreq':
                self.config.maxfreq = value
            case 'binsize':
                self.config.binsize = value
        
        if self.sensor:
            self.connect_sensor(self.sensor)

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

        self.stream.start()
        log.debug(f'Stream started')

    def stop_stream(self):
        '''Terminate sensor stream'''
        if not self.is_streaming:
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

    def save_data(self, name=None, target:Path=None):
        ext = '.pkl'

        if not name:
            name = dt.now().strftime('%Y-%m-%d_%H-%M-%S')

        if not target:
            target = Path.joinpath(self.datadir, name)
        elif isinstance(target, str):
            if not target.endswith(ext):
                target += ext 
            target = Path.joinpath(self.datadir, target)
        elif isinstance(target, Path):
            if target.is_dir():
                target = Path.joinpath(target, name+ext)
            elif not target.name.endswith(ext):
                target = Path.joinpath(target.parent, target.name + ext)

        pd.to_pickle(self.data, target)
        log.info(f'Saved current data to {target}')

        return target

    def load_data(self, target:Path=None):
        ext = '.pkl'

        if not target:
            log.error('TODO: load latest data not implemented')
            return
            # TODO: LOAD Latest file
        elif isinstance(target,str):
            if not target.endswith(ext):
                target += ext 
            target = Path.joinpath(self.datadir, target)

        assert target.is_file(), f'Load Data: target file does not exist {target}'

        self.data = pd.read_pickle(target)
        log.info(f'Loaded data sample {target}')

    def recieve_data(self, indata:np.ndarray, frames:int, timestamp:float, status:str):
        '''log and preprocess incoming data stream'''
        
        data = self.sensor.process_raw_data(self.config, indata)

        new_sample = VibeSample(sensor=self.sensor,
                                config=replace(self.config),
                                status=status,
                                timestamp=timestamp.currentTime,
                                data_raw=data
                                )
        
        self.data['last_sample'] = new_sample

        if self.queue is not None:
            self.queue.put(new_sample)
        else:
            self.data_callback(new_sample)

    def data_callback(self, sample):
        for fn in self.callbacks.values():
            fn(sample)

    def visualize_init(self, sample):  
        import matplotlib.pyplot as plt      
        plt.ion()
        fig, ax = plt.subplots(2,1)

        fig.suptitle("Digiducer Stream: " + self.sensor.model_name, fontsize=20)
        ax[0].set_xlabel('Time, ms')
        ax[0].set_ylabel('Acceleration, mm/s^2')
        ax[1].set_xlabel('Frequency, Hz')
        ax[1].set_ylabel('Velocity, mm/s/hz')

        time_vec, acc_t_mmps2 = (sample.config.time_vec, sample.get_accel('mm/s^2'))
        freq_vec, vel_f_mmps = (sample.config.freq_vec, sample.get_spectral_velocity('mm/s^2'))            
        time_plot, = ax[0].plot(time_vec, acc_t_mmps2)
        freq_plot, = ax[1].plot(freq_vec, vel_f_mmps)

        vis = {'fig': fig,
               'ax': ax,
               'time_vec': time_vec,
               'freq_vec': freq_vec,
               'time_plot': time_plot,
               'freq_plot': freq_plot}

        return vis

    def visualize_sample(self, sample, vis):
        time_vec, acc_t_mmps2 = (sample.config.time_vec, sample.get_accel('mm/s^2'))
        freq_vec, vel_f_mmps = (sample.config.freq_vec, sample.get_spectral_velocity('mm/s^2'))
        
        vis['time_plot'].set_data(time_vec, acc_t_mmps2)
        vis['freq_plot'].set_data(freq_vec, vel_f_mmps)
        
        vis['fig'].canvas.draw()
        vis['fig'].canvas.flush_events()

 
if __name__ == "__main__":
    import matplotlib.pyplot as plt

    sens = VibeSensor.find()
    settings=AcquisitionSettings.from_freq_domain(1000, 1)
    vibr = DataCollector(sensor=sens[-1], config=settings)
    
    sample:VibeSample = vibr.collect_sample()
    last_update_time = sample.timestamp
    plot_update_period = 0.05
    
    vis = vibr.visualize_init(sample)

    try:
        vibr.start_stream()
        for _ in range(100):
            if not plt.fignum_exists(vis['fig'].number):
                print('Window closed!')
                break

            sample = vibr.last_sample

            if sample.timestamp >= last_update_time + plot_update_period:
                vibr.visualize_sample(sample, vis)
                plt.pause(plot_update_period)  # force GUI update
                last_update_time = sample.timestamp
    
    finally:
        vibr.stop_stream()
        vibr.disconnect_sensor()
        plt.close(vis['fig'])
