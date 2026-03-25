# Data Collector

import numpy as np
import scipy.signal
import pandas as pd
from datetime import datetime as dt
from queue import Queue
from path import Path
from typing import Union, Literal, List, Tuple, Dict

import vibechecker
from vibechecker.scope_sensor import ScopeSensor

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

    def __init__(self,
                 sensor: Union[vibechecker.VibeSensor, None] = None,
                 config: Union[vibechecker.AcquisitionSettings,None] = None):

        if config:
            self.config = config
        else:
            # default settings
            self.config = vibechecker.AcquisitionSettings()

        self.scope_sensors: dict[int, ScopeSensor] = {}
        self.callbacks: dict = {}   # instance-level; not shared across DataCollector instances

        if sensor is not None:
            self.connect_sensor(sensor)

        self.reset_data_store()

    def set_scope_sensor(self, channel: int, sensor: ScopeSensor | None) -> None:
        """Assign or clear a ScopeSensor on a PicoScope channel for mV→EU conversion."""
        if sensor is None:
            self.scope_sensors.pop(channel, None)
        else:
            self.scope_sensors[channel] = sensor

    def get_active_eu(self, ch: int = 0) -> str:
        """Return the display/target unit for a channel.

        Priority: scope_sensor.effective_target_unit() > VibeSensor unit > 'mV'.
        """
        scope_sensor = self.scope_sensors.get(ch)
        if scope_sensor is not None:
            return scope_sensor.effective_target_unit()
        if self.sensor is not None:
            unit = getattr(self.sensor, 'unit', None)
            if isinstance(unit, list):
                return unit[min(ch, len(unit) - 1)]
            if unit is not None:
                return unit
        return 'mV'

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
        self._last_samples: dict = {}   # per-channel last VibeSample

        log.info('Reset data store.')

    @property
    def sample(self) -> vibechecker.VibeSample:
        return self.data['sample']
    @sample.setter
    def sample(self, sample):
        self.data['sample'] = sample
        self.data['sample_count'] += 1

    def connect_sensor(self, sensor: vibechecker.VibeSensor,
                       siggen_config: dict | None = None):
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
        self.stream = self.sensor.connect(self.config, self.recieve_data,
                                           siggen_config=siggen_config)
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

        if parameter == ui.ACQ_MAXFREQ:
            self.config.maxfreq = float(value)
        elif parameter == ui.ACQ_BINSIZE:
            self.config.binsize = float(value)
        else:
            log.error(f'Acquisition parameter invalid: {parameter}')
             
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
            return None

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
        except Exception as e:
            self.disconnect_sensor()
            log.error(f'Error starting stream: {e}')
        log.debug(f'Stream started')

    def stop_stream(self):
        '''Terminate sensor stream'''
        if not self.stream or not self.is_streaming:
            log.warning('Attempted Stop Stream: No stream running')
            return

        self.stream.stop()
        log.debug(f'Stream stopped')

    def reconnect_stream(self):
        """Close and recreate the stream with current config.

        Call this after modifying config.enabled_channels so hardware
        (e.g. PicoScopeStream) picks up the new channel list.
        """
        if self.sensor is None:
            return
        sensor = self.sensor
        was_streaming = self.is_streaming
        if was_streaming:
            self.stop_stream()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self.stream = sensor.connect(self.config, self.recieve_data)
        if was_streaming:
            self.start_stream()

    def collect_sample(self) -> dict:
        """Collect one block from each enabled channel. Returns {channel: VibeSample}."""
        if self.is_streaming:
            self.stop_stream()

        self.start_data_queue()
        self.start_stream()

        try:
            samples = self.get_data_queue()
        except Exception:
            samples = {}
        finally:
            self.stop_stream()
            self.kill_data_queue()

        return samples if isinstance(samples, dict) else {}

    def save_data(self, target:Path):
        if target.exists():
            log.warning('Save target exists. Delete existing file before saving.')
            return

        self.sample.save(target)

    def load_data(self, target:Path):
        if not target.is_file():
            log.error(f'load_data: file does not exist: {target}')
            return

        self.sample = vibechecker.VibeSample.load(target)

        self.data_callback({0: self.sample})

        log.info(f'Loaded data sample {target}')

    def recieve_data(self, samp: dict):
        """Preprocess one incoming data block and fan out to per-channel VibeSamples."""
        data_arr = np.asarray(samp['data'])
        unit_arr = samp['unit']
        channels = samp.get('channels', [0])

        # Ensure 2-D (blocksize, N)
        if data_arr.ndim == 1:
            data_arr = data_arr[:, np.newaxis]

        samples: dict[int, vibechecker.VibeSample] = {}

        for i, ch in enumerate(channels):
            col  = min(i, data_arr.shape[1] - 1)
            data = data_arr[:, col].copy()
            unit = unit_arr[ch] if isinstance(unit_arr, list) and ch < len(unit_arr) else (
                   unit_arr[i] if isinstance(unit_arr, list) and i < len(unit_arr) else unit_arr)

            # mV → EU conversion via assigned ScopeSensor
            if unit == 'mV':
                scope_sensor = self.scope_sensors.get(ch)
                if scope_sensor is not None:
                    data = np.asarray(data, dtype=np.float64) / scope_sensor.sensitivity
                    unit = scope_sensor.engineering_units

            # Butterworth highpass filter
            if self.config.butter_fc:
                nyq = float(self.config.samplerate) / 2.0
                if self.config.butter_fc < nyq:
                    sos = scipy.signal.butter(4, self.config.butter_fc,
                                              btype='highpass',
                                              fs=self.config.samplerate,
                                              output='sos')
                    data = scipy.signal.sosfilt(sos, np.asarray(data, dtype=np.float64))

            samples[ch] = vibechecker.VibeSample(
                samp['status'],
                samp['timestamp'],
                self.config.samplerate,
                unit,
                np.ascontiguousarray(data),
                samp['rel_time'],
            )

        self.data_callback(samples)

    def data_callback(self, samples: dict):
        """Deliver {channel: VibeSample} to queue or registered GUI callbacks."""
        if self.queue is not None:
            self.queue.put(samples)
        else:
            if samples:
                self.sample = next(iter(samples.values()))
                self._last_samples.update(samples)   # per-channel storage for redraw
            for fn in self.callbacks.values():
                fn(samples)

    def visualize_init(self, sample:vibechecker.VibeSample):
        target_unit = self.get_active_eu(0)
        acc, rms = sample.get_accel(target_unit)
        fft, pkk = sample.fft(target_unit, self.config)
        if fft is None:
            return

        import matplotlib.pyplot as plt
        plt.ion()
        fig, ax = plt.subplots(2,1)

        if self.sensor:
            title = "Digiducer Stream: " + self.sensor.model_name
        else:
            title = ''

        fig.suptitle(title, fontsize=20)
        ax[0].set_xlabel('Time, s')
        ax[0].set_ylabel(f'Signal, {sample.unit}')
        ax[1].set_xlabel('Frequency, Hz')
        ax[1].set_ylabel(f'Amplitude, {target_unit}')

        time_plot, = ax[0].plot(acc.time, acc.signal)
        freq_plot, = ax[1].plot(fft.freq, fft.display_0p)

        vis = {'fig': fig,
               'ax': ax,
               'time_plot': time_plot,
               'freq_plot': freq_plot,
               'acc': acc,
               'rms': rms,
               'fft': fft,
               'peak': pkk}

        return vis

    def visualize_sample(self, sample:vibechecker.VibeSample, vis:dict):
        target_unit = self.get_active_eu(0)
        acc, rms = sample.get_accel(target_unit)
        fft, pkk = sample.fft(target_unit, self.config)
        if fft is None:
            return

        vis['time_plot'].set_data(acc.time, acc.signal)
        vis['freq_plot'].set_data(fft.freq, fft.display_0p)

        vis['fig'].canvas.draw()
        vis['fig'].canvas.flush_events()

        vis['acc'] = acc
        vis['rms'] = rms
        vis['fft'] = fft
        vis['peak'] = pkk

        return vis

