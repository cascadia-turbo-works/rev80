import time
import threading

import numpy as np
import sounddevice as sd

from datetime import datetime as dt
from sys import platform
from dataclasses import dataclass


SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000]

eu_sen = np.array([100,100]) # if device returns volts, use this mV/g scale, set to 0 to return raw voltage
eu_units = ['g', 'g']

def nextpow2(x:int):
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))

def GenerateVibrationData(blocksize:int, samplerate:int, channels:int=None):
    # Generate sample data representing rotating equipment with faulty bearing
    t = np.arange(0,blocksize/samplerate,1/samplerate) # time vector
    nnoise = lambda a: a * np.random.randn(blocksize) # normal noise
    signal = lambda a, f, p=0: a * np.sin(2*np.pi*f*t + p) # single frequency signal

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    data = nnoise(0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        data += signal(1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        data += signal(bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    if channels:
        # convert to shape (blocksize, channels_count)
        data = np.matlib.repmat(data.reshape(blocksize,1), 1, channels)

    return data
 
def FindDigiducerDevice():
    # The Modal Shop model number substrings
    models=["485B", "333D", "633A", "SDC0"]
    
    # Windows has a variety of API's to access audio
    # many of them manipulate the data and do not support setting actual
    # requested sample rates.  Windows Kernal Streaming allows direct control
    # so find devices using that API
    if platform == "win32":         # Windows...
        hapis=sd.query_hostapis()
        api_num=0
        for api in hapis:
            if api['name'] == "Windows WDM-KS":
                break
            api_num += 1
    else:
        # Not Windows - other platforms don't have the issue with the API
        api_num=0
    # Return all available audio inputs
    devices = sd.query_devices()
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
                device_info.append({"device_id":dev_num,
                                 "model_name":model,
                                 "serial_number":serialnum,
                                 "manufacture_date":date,
                                 "format_id":form,
                                 "sensitivity":sens,
                                 "scale":scale,
                                 "units": units
                                 })                  
        dev_num += 1
    # if len(device_info) == 0:
    #     raise NoDevicesFound("No compatible devices found")
    return device_info

def acceleration_to_velocity_fft(accel, Fs):
    """
    Convert time-domain acceleration signal to frequency-domain velocity using FFT.
    
    Parameters:
    - accel: numpy array of acceleration samples in g (gravity units)
    - Fs: Sampling frequency in Hz
    
    Returns:
    - freqs: Frequency axis (Hz)
    - accel_spectrum: One-sided acceleration amplitude spectrum (mm/s²)
    - vel_spectrum: One-sided velocity amplitude spectrum (mm/s)
    """
    N = len(accel)  # Number of samples
    dt = 1 / Fs     # Time step
    
    # Convert acceleration from g to mm/s²
    times = np.arange(len(accel))/Fs
    accel_mms2 = accel * 9.81 * 1000  # (9.81 m/s² * 1000) -> mm/s²

    # Compute FFT of acceleration
    A_f = np.fft.fft(accel_mms2) /N
    freqs = np.fft.fftfreq(N, dt)  # Frequency axis

    # Compute one-sided amplitude spectrum of acceleration
    accel_spectrum = 2 * np.abs(A_f[:N // 2])

    # Convert acceleration to velocity in the frequency domain
    V_f = np.zeros_like(A_f, dtype=np.complex128)
    nonzero_freqs = freqs != 0
    V_f[nonzero_freqs] = A_f[nonzero_freqs] / (1j * 2 * np.pi * freqs[nonzero_freqs])
    
    # Compute one-sided amplitude spectrum of velocity
    vel_spectrum = 2 * np.abs(V_f[:N // 2])  

    # Keep only positive frequencies
    freqs = freqs[:N // 2]
    
    return times, freqs, accel_mms2, vel_spectrum   

class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass


@dataclass
class AcquisitionSettings:
    blocksize: int
    samplerate: int
    channel: int

    pipeline = []

    @property
    def sampleperiod(self):
        return 1 / self.samplerate
    @property
    def acquisitionperiod(self):
        return self.blocksize/self.samplerate
    
@dataclass
class mock_C_time:
    currentTime: float
    inputBufferAdcTime: float
    outputBufferDacTime: float
    
@dataclass
class VibeSensor:
    device_id: int
    model_name: str
    serial_number: str
    manufacture_date: dt
    format_id: int
    sensitivity: list
    scale: np.ndarray
    units: list
    is_simulation: bool = False

    @classmethod
    def find(cls):
        stat = [cls(**dev) for dev in FindDigiducerDevice()]
        stat.append(cls.simulated())
        return stat
    
    @classmethod
    def simulated(cls):
        return cls(device_id = '-1',
                   model_name = 'Simulated Vibration Sensor',
                   serial_number = '0000',
                   manufacture_date = dt.now(),
                   format_id = 0,
                   sensitivity = [1,1],
                   scale = [1,1],
                   units = ['g','g'],
                   is_simulation = True
                   )
    
    def connect(self, settings: AcquisitionSettings, callback):
        '''Return stream object'''

        if self.is_simulation:
            # Simulate a device connection
            return SimulatedSensor(settings, callback=callback)
        else:
            return sd.InputStream(
                        device=self.device_id, 
                        channels=2, 
                        samplerate=settings.samplerate, 
                        blocksize=settings.blocksize,
                        callback=callback,
                        dtype='float32' 
                    )

class SimulatedSensor:

    def __init__(self,settings:AcquisitionSettings, callback):
        self._running: bool = False

        self.settings = settings

        self.blocksize = settings.blocksize
        self.samplerate = settings.samplerate
        self.channels = 2

        self.callback = callback

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self._stream = threading.Thread(target=self._stream, daemon=True)

    def _generate_data(self):
        return GenerateVibrationData(self.settings.blocksize, self.settings.samplerate, self.channels)
    
    def _stream(self):
        self._running = True
        while self._running:
            data = self._generate_data()
            t = time.monotonic()
            timestamp = mock_C_time(t, t, 0.0)
            time.sleep(self.settings.acquisitionperiod)
            self.callback(data,self.blocksize, timestamp, 'OK')

    def start(self):
        self._stream.start()

    def stop(self):
        self._running = False
        self._stream.join()
        self._stream = None
        self.create_stream()

    def close(self):
        pass

class VibeSample():
    pass
    # status: str
    # timestamp: int = None
    # settings: AcquisitionSettings = None

    # time: np.array = None
    # accel_g: np.array = None
    # accel_mps2: np.array = None

    # freq: np.array = None
         

'''
time_axis
accel_g
accel_mmps2
vel_mmps??

freq_axis_hz
freq_axis_cpm
spectrum_g
spectrum_mmps
spectrum_ips


self.data['last_sample'] = {'data': data,
                    'blocksize': frames,
                    'samplerate': self.settings.samplerate,
                    'units': self.sensor.units,
                    'timestamp': timestamp.currentTime,
                     'status': status}
'''                     