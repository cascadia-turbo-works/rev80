import time
import threading

import numpy as np
import sounddevice
import endaq

from datetime import datetime as dt
from sys import platform
from dataclasses import dataclass, field
from typing import Tuple, List, Union

from vibechecker import logger

log = logger.get_logger('util')

eu_sen = np.array([100,100]) # if device returns volts, use this mV/g scale, set to 0 to return raw voltage
eu_units = ['g', 'g']
SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000]
BLOCKSIZES = list(map(int,np.pow(2, np.arange(8,15))))

SUPPORTED_UNITS = ["g", "mm","in"]

UNIT_CONVERSION = {
    ("g", "mm"): 9.80665 * 1000,
    ("mm", "g"): 1 / (9.80665 * 1000),
    ("g", "in"): 9.80665 * 1000 * 25.4,
    ("in", "g"): 1 / (9.80665 * 1000 * 25.4),
    ("mm", "in"): 25.4,
    ("in", "mm"): 1 / 25.4
}


class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass

@dataclass
class AcquisitionSettings:
    _domain: str = field(default="TIME", init=False)
    _time_params: tuple = field(default=(BLOCKSIZES[3], SAMPLERATES[0]))  # (Ns, Fs)
    _freq_params: tuple = field(default=(2000,1))    # (Fmax, dF)
    channel:int = 0

    def __post_init__(self):
        match self._domain:
            case "FREQ":
                self._update_time_from_freq()
            case "TIME":
                self._update_freq_from_time()
            case _:
                raise ValueError(f"Acquisition Settings: Invalid domain {self._domain}")

    @classmethod
    def from_time_domain(cls, blocksize: int, samplerate: float):
        inst = cls()
        inst._time_params = (int(blocksize), float(samplerate))
        inst._domain = "TIME"
        inst._update_freq_from_time()
        return inst

    @classmethod
    def from_freq_domain(cls, Fmax: float, dF: float):
        inst = cls()
        inst._freq_params = (float(Fmax), float(dF))
        inst._domain = "FREQ"
        inst._update_time_from_freq()
        return inst

    def _update_time_from_freq(self):
        Fmax, dF = self._freq_params
        Ns = (2*Fmax) // dF
        Fs = 2 * Fmax

        # snap to the nearest allowed samplerate
        Fs = SAMPLERATES[np.argmin(np.abs(np.array(SAMPLERATES) - Fs))]

        self._time_params = (int(Ns), float(Fs))
        
        self._update_freq_from_time

    def _update_freq_from_time(self):
        Ns, Fs = self._time_params
        Fmax = Fs / 2
        dF = Fs / Ns
        self._freq_params = (float(Fmax), float(dF))

    @property
    def blocksize(self) -> int:
        return self._time_params[0]
    @blocksize.setter
    def blocksize(self,bs):
        self._time_params = (int(bs), self.samplerate)
        self._update_freq_from_time()
        self._domain = 'TIME'

    @property
    def samplerate(self) -> float:
        return self._time_params[1]
    @samplerate.setter
    def samplerate(self, fs):
        self._time_params = (self.blocksize, float(fs))
        self._update_freq_from_time()
        self._domain = 'TIME'

    @property
    def maxfreq(self) -> float:
        return self._freq_params[0]
    @maxfreq.setter
    def maxfreq(self,fm):
        self._freq_params = (float(fm), self.binsize)
        self._update_time_from_freq()
        self._domain = 'FREQ'

    @property
    def binsize(self) -> float:
        return self._freq_params[1]
    @binsize.setter
    def binsize(self,df):
        self._freq_params = (self.maxfreq, float(df))
        self._update_time_from_freq()
        self._domain = 'FREQ'

    def set_time_params(self, blocksize:int = None, samplerate:float = None):
        Ns = blocksize or self._time_params[0]
        Fs = samplerate or self._time_params[1]
        self._time_params = ( int(Ns), float(Fs) )
        self._update_freq_from_time()
        self._domain = 'TIME'

    def set_freq_params(self, maxfreq:float = None, binsize:float = None):
        Fm = maxfreq or self._freq_params[0]
        Df = binsize or self._freq_params[1]
        self._freq_params = (float(Fm), float(Df))
        self._update_time_from_freq()
        self._domain = 'FREQ'

    @property
    def acquisition_period(self):
        return 1.0/self.samplerate
    
    @property
    def time_vec(self) -> np.ndarray:
        Ns, Fs = self._time_params
        return np.arange(Ns) / Fs

    @property
    def freq_vec(self) -> np.ndarray:
        Ns, Fs = self._time_params
        return np.fft.rfftfreq(Ns, d=1 / Fs)

def nextpow2(x:int):
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))


def GenerateVibrationData_SpectralMethod(config:AcquisitionSettings):
    F = config.freq_vec
    amplitude = np.zeros_like(F, dtype='complex128')

    # Create exponential noise with random phase
    N0 = 0.03
    NR = 1000
    amplitude +=  N0 * np.exp(-F/NR)  * np.exp(np.random.rand(*F.shape)*np.pi*2j)

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


    amplitude = running + bearing + amplitude

    signal = np.real(np.fft.ifft(np.concat((amplitude[-1:1:-1], amplitude))))

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
            if api['name'] == "Windows WDM-KS":
                break
            api_num += 1
    else:
        # Not Windows - other platforms don't have the issue with the API
        api_num=0
    # Return all available audio inputs
    devices = sounddevice.query_devices()
    device_info = []   # Array to store info about each compa
    dev_num=0
    # Iterate through available devices and find ones named with a TMS model.
    # Note this returns multiple instances of the same device, because there
    # are different audio API's available.
    for device in devices:
        if (device['hostapi'] == api_num):
            name = device['name']
            match = next((x for x in models if x in name), False)
            if match != False:
                loc = name.find(match)
                model = name[loc:loc+6] # Extract the model
                fmt = name[loc+7:loc+8] # Extract the format of data
                serialnum = name[loc+8:loc+14]  # Extract the serial number
                # parse devices that are voltage
                if fmt == "2" or fmt == '3':
                    form = 1    # Voltage
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+21]), int(name[loc+21:loc+28])]
                    if fmt == "3":  # 50mV reference for format 3
                        sens[0] *= 1/50e-3 # Convert to 1V reference
                        sens[1] *= 1/50e-3

                    units = ['v', 'v']
                    scale = np.array([8388608.0/sens[0], 8388608.0/sens[1]], dtype='float32') # scale to volts

                    for ch in range(len(scale)):
                        if eu_sen[ch] != 0.0:
                            scale[ch] *= 1.0 / (eu_sen[ch] / 1000.0)
                            units[ch] = eu_units[ch]

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
                   units = ['g','g'],
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
        
    def process_raw_data(self, config:AcquisitionSettings, raw_data:np.ndarray):
        return raw_data[:config.blocksize, config.channel] * self.scale[config.channel]

class SimulatedSensor:

    def __init__(self, config:AcquisitionSettings, sensor, callback):
        self._running: bool = False

        self.sensor = sensor
        self.config = config
        self.channels = 2
        self.callback = callback

        self.stream = None

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self.stream = threading.Thread(target=self._stream, daemon=True)

    def _generate_data(self):
        return GenerateVibrationData_SpectralMethod(self.config)
    
    def _stream(self):
        self._running = True
        while self._running:
            data = self._generate_data()
            t = time.monotonic()
            timestamp = mock_C_time(t, t, 0.0)
            time.sleep(0.95*self.config.acquisition_period)
            self.callback(data,self.config.blocksize, timestamp, 'OK')

    def start(self):
        self.stream.start()

    def stop(self):
        self._running = False
        self.stream.join()
        self.stream = None
        self.create_stream()

    def abort(self):
        self.stop()

    def close(self):
        pass
 
@dataclass
class VibeSample:
    config: AcquisitionSettings
    status: str
    timestamp: float
    target_unit: str = "mm"
    raw_data: np.ndarray = field(default_factory=lambda: np.array([]), repr=False)
    raw_unit: str = 'g'

    @classmethod
    def empty(cls, config:AcquisitionSettings=None):
        return VibeSample(config=config,
                          status='EMPTY',
                          timestamp=-1 )

    def set_config(self, config:AcquisitionSettings):
        self.config = config

    def push_sample(self, data:np.ndarray, timestamp:float, status:str):
        self.raw_data = data  # Assume single-channel
        self.timestamp = timestamp
        self.status = status

    def get_accel(self) -> np.ndarray:
        return convert_units(self.raw_data, self.raw_unit, self.target_unit)

    def get_rms(self) -> float:
        return np.sqrt(np.mean(np.pow(self.get_accel(),2)))

    def get_spectral_accel(self) -> np.ndarray:
        acc = self.get_accel()
        spectrum = np.abs( np.fft.rfft(acc) ) / len(acc)
        return spectrum

    def get_spectral_velocity(self) -> np.ndarray:
        freq = self.config.freq_vec
        spectral_acc = self.get_spectral_accel()
        with np.errstate(divide='ignore', invalid='ignore'):
            spectral_vel = spectral_acc / (2 * np.pi * freq)
            spectral_vel[0] = 0.0  # avoid division by zero at DC
        return spectral_vel
    
    def get_peak_velocity(self) -> float:
        velocity_spectrum = self.get_spectral_velocity()
        return np.max(np.abs(velocity_spectrum))
    
    # def peaks(self):
    #     spectrum = self.get_spectral_velocity()
    #     peaks, properties = find_peaks(10*np.log10(spectrum), height=3, distance=5)
    #     frequencies = self.config.freq_vec[peaks]
    #     amplitudes = spectrum[peaks]

    #     return frequencies, amplitudes, properties
    

if __name__=="__main__":
    print(AcquisitionSettings())
    config = AcquisitionSettings.from_time_domain(BLOCKSIZES[3], SAMPLERATES[0])
    # config = AcquisitionSettings.from_freq_domain(2000,1)
    sensor = VibeSensor.find()[0]

    stream = sensor.connect(config, lambda a,b,c,d,e: print(a,b,c,d,e))

    stream.start()
    time.sleep(.1)
    stream.stop()

    time.sleep(0.5)

    print(stream)