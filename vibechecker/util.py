import time
import threading

import numpy as np
import scipy.signal as signal
import scipy.fft as fft
import sounddevice

from datetime import datetime as dt
from sys import platform
from dataclasses import dataclass, field
from typing import Union, Literal

from vibechecker import logger

log = logger.get_logger('util')

ENG_UNIT_SENSITIVITY = np.array([100,100]) # if device returns volts, use this mV/g scale, set to 0 to return raw voltage
ENG_UNITS = ['g', 'g']

SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000]
BLOCKSIZES = list(map(int,np.pow(2, np.arange(8,15))))
MAXFREQS = [2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4]
BINSIZES = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

SUPPORTED_UNITS = Literal["g", "mm", "in"]

UNIT_CONVERSION = {
    ("g", "mm"): 9.80665 * 1000,
    ("mm", "g"): 1 / (9.80665 * 1000),
    ("g", "in"): 9.80665 * 1000 * 25.4,
    ("in", "g"): 1 / (9.80665 * 1000 * 25.4),
    ("mm", "in"): 25.4,
    ("in", "mm"): 1 / 25.4
}

sd_needs_reset = threading.Event()

def nextpow2(x) -> int:
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))

class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass

@dataclass
class AcquisitionSettings:
    _ns: int = BLOCKSIZES[2]
    _fs: int = SAMPLERATES[0]
    channel: int = 0

    @classmethod
    def copy(cls, settings):
        return cls(settings.blocksize, settings.samplerate)
    
    @property
    def blocksize(self):
        return self._ns
    @blocksize.setter
    def blocksize(self, ns):
        self._ns = int(ns)

    @property
    def samplerate(self):
        return self._fs
    @samplerate.setter
    def samplerate(self, fs):
        self._fs = int(fs)

    @property
    def maxfreq(self) -> float:
        require_fm = self.samplerate / 2
        try:
            return next(filter(lambda fm: fm <= require_fm, reversed(MAXFREQS)))
        except StopIteration:
            return int(require_fm)

    @property
    def binsize(self) -> float:
        require_df = self.samplerate / self.blocksize
        try:
            return next(filter(lambda df: df >= require_df, BINSIZES))
        except StopIteration:
            return require_df
    
    @property
    def sampleperiod(self) -> float:
        return 1./self.samplerate

    @property
    def acquisition_period(self) -> float:
        return self.blocksize * self.sampleperiod
    
    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) * self.sampleperiod

    @property
    def freq_vec(self) -> np.ndarray:
        return fft.rfftfreq(self.blocksize, d=self.sampleperiod)
    
    def ensure_maxfreq(self, fm: float):
        require_fs = 2 * float(fm)
        try:
            fs = next(filter(lambda x: x > require_fs, SAMPLERATES))
        except StopIteration:
            fs = SAMPLERATES[-1]
            log.warning(f'Cannot acheive max frequency {fm} hz. Defaulting to max samplerate {fs}')

        self.samplerate = fs
    
    def ensure_binsize(self, df:float):
        ns = nextpow2(self.samplerate / float(df))
        
        self.blocksize = nextpow2(ns)
        log.debug(f'Set samplesize to {ns} hz to achieve {df} hz frequency resolution') 


def GenerateVibrationData_SpectralMethod(config:AcquisitionSettings):
    F = config.freq_vec
    spectrum = np.zeros_like(F, dtype='complex128')

    # Create exponential noise with random phase
    N0 = 0.03
    NR = 1000
    spectrum +=  N0 * np.exp(-F/NR)  * np.exp(np.random.rand(*F.shape)*np.pi*2j)

    running = np.zeros_like(F) * 1j
    running_rate = 60
    running_level = 1. * np.exp(np.random.rand() * np.pi*2j)
    # running_overtones = 

    for k in range(int(F[-1] // running_rate)):
        running[np.argmin(np.abs(F-(k+1)*running_rate))] = running_level / (k+1)

    bearing = np.zeros_like(F) * 1j
    bearing_multiple = 9.23
    bearing_severity = 0.5 * np.exp(np.random.rand() * np.pi*2j)

    for k in range(int(F[-1] // bearing_multiple*running_rate)):
        bearing[np.argmin(np.abs(F-(k+1)*running_rate*bearing_multiple))] = bearing_severity / (k+1)

    spectrum = running + bearing + spectrum
    signal = np.array(fft.irfft(spectrum))

    if config.channel is not None:
        # convert to shape (blocksize, channels_count)
        signal = np.tile(signal, (1, max(1,config.channel)))

    return signal.T

def GenerateVibrationData_TemporalMethod(config:AcquisitionSettings):
    # Generate sample data representing rotating equipment with faulty bearing

    nnoise = lambda a: a * np.random.randn(config.time_vec.shape[0]) # normal noise
    signal = lambda a, f, p=0.: a * np.sin(2*np.pi*f*config.time_vec + p) # single frequency signal

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    data = np.zeros_like(config.time_vec)

    data += nnoise(0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        data += signal(1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        data += signal(bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    if config.channel is not None:
        # convert to shape (blocksize, channels_count)
        data = np.tile(data, (1, max(1,config.channel)))

    time.sleep(config.acquisition_period)
    return data.T 
 
def FindDigiducerDevice():
    # The Modal Shop model number substrings
    models=["485B", "333D", "633A", "SDC0"]
    
    # Windows has a variety of API's to access audio
    # many of them manipulate the data and do not support setting actual
    # requested sample rates.  Windows Kernal Streaming allows direct control
    # so find devices using that API
    if platform == "win32":         # Windows...
        hapis=sounddevice.query_hostapis()
        api_num=0
        for api in hapis:
            if api['name'] == "Windows WDM-KS": # type: ignore
                break
            api_num += 1
    else:
        # Not Windows - other platforms don't have the issue with the API
        api_num=0
    # Return all available audio inputs
    sd_needs_reset.set()
    devices = sounddevice.query_devices()
    device_info = []   # Array to store info about each compa
    dev_num=0
    # Iterate through available devices and find ones named with a TMS model.
    # Note this returns multiple instances of the same device, because there
    # are different audio API's available.
    for device in devices:
        if (device['hostapi'] == api_num): # type: ignore
            name = device['name'] # type: ignore
            match = next((x for x in models if x in name), False)
            if match != False:
                loc = name.find(match) # type: ignore
                model = name[loc:loc+6] # Extract the model
                fmt = name[loc+7:loc+8] # Extract the format of data
                serialnum = name[loc+8:loc+14]  # Extract the serial number
                # parse devices that are voltage
                if fmt == "2" or fmt == '3':
                    form = 1    # Voltage
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+21]), int(name[loc+21:loc+28])]
                    if fmt == "3":  # 50mV reference for format 3
                        sens[0] *= int(1/50e-3) # Convert to 1V reference
                        sens[1] *= int(1/50e-3)

                    units = ['v', 'v']
                    scale = np.array([8388608.0/sens[0], 8388608.0/sens[1]], dtype='float32') # scale to volts

                    for ch in range(len(scale)):
                        if ENG_UNIT_SENSITIVITY[ch] != 0.0:
                            scale[ch] *= 1.0 / (ENG_UNIT_SENSITIVITY[ch] / 1000.0)
                            units[ch] = ENG_UNITS[ch]

                    date = dt.strptime(name[loc+28:loc+34], '%y%m%d') # Isolate the calibration date from the fullname string

                elif fmt == "1":
                    # These devices are acceleration
                    form = 0
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+19]), int(name[loc+19:loc+24])]
                    scale = np.array([855400.0/sens[0], 855400.0/sens[1]], dtype='float32') # scale to g's
                    units = ['g', 'g']
                    date = dt.strptime(name[loc+24:loc+30], '%y%m%d') # Isolate the calibration date from the fullname string
                else:
                      raise FormatError("Expecting 1, 2, or 3 format")

                 # Add new device to array   
                device_info.append({"device_id":    dev_num,
                                 "model_name":      'Digiducer_'+model,
                                 "serial_number":   serialnum,
                                 "build_date":      date,
                                 "format_id":       form,
                                 "sensitivity":     sens,
                                 "scale":           scale,
                                 "units":           units
                                 })                  
        dev_num += 1
    # if len(device_info) == 0:
    #     raise NoDevicesFound("No compatible devices found")
    return device_info

def convert_units(data: np.ndarray, from_unit: str, to_unit: str) -> np.ndarray:
    if from_unit == to_unit:
        return data
    try:
        factor = UNIT_CONVERSION[(from_unit, to_unit)]
        return data * factor
    except KeyError:
        raise ValueError(f"Unsupported conversion from {from_unit} to {to_unit}")

@dataclass
class mock_C_time:
    currentTime: float
    inputBufferAdcTime: float
    outputBufferDacTime: float
    
@dataclass
class VibeSensor:
    device_id: str
    model_name: str
    serial_number: str
    build_date: dt
    format_id: int
    sensitivity: list
    scale: list
    units: list
    is_simulation: bool = False

    def __str__(self):
        return f'{self.model_name} (sn:{self.serial_number}, id:{self.device_id})'

    @classmethod
    def find(cls):
        if sd_needs_reset.is_set():
            # HACK: Reset sounddevice module before listing new devices.
            # This shouldn't be included in `FindDigiducers` function bc
            # it may break active streams if called a the wrong time.
            # This is necessary to acheieve hotplugging of sensors while app is open w/o restart
            sounddevice._terminate()
            sounddevice._initialize()
            # ENDHACK
            sd_needs_reset.clear()

        stat = [cls.simulated()] + [cls(**dev) for dev in FindDigiducerDevice()]
        return stat

    @classmethod
    def simulated(cls):
        return cls(device_id = '-1',
                   model_name = 'Simulated Vibration Sensor',
                   serial_number = '0000',
                   build_date = dt.now(),
                   format_id = 0,
                   sensitivity = [1,1],
                   scale = [1,1],
                   units = ['mm','mm'],
                   is_simulation = True
                   )
    
    def connect(self, config: AcquisitionSettings, callback):
        '''Return stream object'''

        if self.is_simulation:
            # Simulate a device connection
            return SimulatedSensor(config, sensor=self, callback=callback)
        else:
            return sounddevice.InputStream(
                        device=self.device_id, 
                        channels=2, 
                        samplerate=config.samplerate, 
                        blocksize=config.blocksize,
                        callback=callback,
                        dtype='float32'
                    )

class SimulatedSensor:

    def __init__(self, config:AcquisitionSettings, sensor, callback):
        self._running: bool = False

        self.sensor = sensor
        self.config = config
        self.channels = 2
        self.callback = callback

        self.stream: threading.Thread

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self.stream = threading.Thread(target=self._stream, daemon=True)

    def _stream(self):
        self._running = True
        while self._running:
            data = GenerateVibrationData_TemporalMethod(self.config)
            t = time.monotonic()
            timestamp = mock_C_time(t, t, 0.0)
            time.sleep(0.95*self.config.acquisition_period)
            self.callback(data,self.config.blocksize, timestamp, 'OK')

    def start(self):
        self.stream.start()

    def stop(self):
        self._running = False
        self.stream.join()
        self.create_stream()

    def abort(self):
        self.stop()

    def close(self):
        pass
 

@dataclass
class VibeSample:
    status: str
    timestamp: float
    samplerate: int
    raw_unit: SUPPORTED_UNITS
    raw_data: np.ndarray = field(default_factory=lambda: np.array([]))
    target_unit: SUPPORTED_UNITS = field(default=SUPPORTED_UNITS.__args__[0])

    integration: Literal['acceleration', 'velocity'] = field(default='acceleration')

    @classmethod
    def empty(cls):
        return VibeSample(status='EMPTY',
                          timestamp= -1,
                          raw_unit='g',
                          samplerate= -1,)
    
    @property # TODO: Use functools.@cached_property. self.__dict__.pop('config',None) to invalidate
    def config(self):
        assert self.samplerate > 0, 'No data in this sample. Use `VibeSample.push_sample()`'
        return AcquisitionSettings(len(self.raw_data), self.samplerate)
    
    def push_sample(self, status:str, timestamp:float, raw_unit:SUPPORTED_UNITS, samplerate: int, data:np.ndarray):
        self.status = status
        self.raw_unit = raw_unit
        self.samplerate = samplerate
        self.raw_data = data  # single-channel
        self.timestamp = timestamp

        self.__dict__.pop('config',None)

    def get_accel(self):
        time = self.config.time_vec
        accel = convert_units(self.raw_data, self.raw_unit, self.target_unit)
        return time, accel

    def get_rms(self):
        _, accel = self.get_accel()
        return np.sqrt(np.mean(np.pow(accel,2)))

    def get_spectral_accel(self):
        fs = self.config.samplerate
        df = self.config.binsize
        _, accel = self.get_accel()
        nperseg = min(len(accel), int(fs / df))

        freq, psd = signal.welch(accel, fs=fs, nperseg=nperseg)

        psd = psd * 2 * freq[1]

        return freq, psd

    def get_spectral_velocity(self):
        freq, spectral_acc = self.get_spectral_accel()
        with np.errstate(divide='ignore', invalid='ignore'):
            spectral_vel = np.abs(spectral_acc / (2j * np.pi * freq))
        spectral_vel[0] = 0.0  # avoid division by zero at DC
        return freq, spectral_vel
    
    def get_spectrum(self):
        if self.integration == 'Velocity':
            return self.get_spectral_velocity()
        return self.get_spectral_accel()
    
    def get_peak_velocity(self) -> float:
        _, velocity_spectrum = self.get_spectral_velocity()
        return np.max(np.abs(velocity_spectrum))
    
