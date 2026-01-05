import time
import threading
from dataclasses import dataclass
import scipy.fft as fft
import numpy as np

from vibechecker import AcquisitionSettings

def GenerateVibrationData_SpectralMethod(config:AcquisitionSettings):
    freqs = fft.rfftfreq(config.blocksize, d=config.sampleperiod)
    spectrum = np.zeros_like(freqs, dtype='complex128')

    # Create exponential noise with random phase
    N0 = 0.03
    NR = 1000
    spectrum +=  N0 * np.exp(-freqs/NR)  * np.exp(np.random.rand(*freqs.shape)*np.pi*2j)

    running = np.zeros_like(freqs) * 1j
    running_rate = 60
    running_level = 1. * np.exp(np.random.rand() * np.pi*2j)
    # running_overtones = 

    for k in range(int(freqs[-1] // running_rate)):
        running[np.argmin(np.abs(freqs-(k+1)*running_rate))] = running_level / (k+1)

    bearing = np.zeros_like(freqs) * 1j
    bearing_multiple = 9.23
    bearing_severity = 0.5 * np.exp(np.random.rand() * np.pi*2j)

    for k in range(int(freqs[-1] // bearing_multiple*running_rate)):
        bearing[np.argmin(np.abs(freqs-(k+1)*running_rate*bearing_multiple))] = bearing_severity / (k+1)

    spectrum = running + bearing + spectrum
    signal = np.array(fft.irfft(spectrum))

    if config.channel is not None:
        # convert to shape (blocksize, channels_count)
        signal = np.tile(signal, (1, max(1,config.channel)))

    return signal.T

def GenerateVibrationData_TemporalMethod(config:AcquisitionSettings):
    # Generate sample data representing rotating equipment with faulty bearing

    nnoise = lambda a: a * np.random.randn(config.blocksize) # normal noise
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

@dataclass
class mock_C_time:
    currentTime: float
    inputBufferAdcTime: float
    outputBufferDacTime: float

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
