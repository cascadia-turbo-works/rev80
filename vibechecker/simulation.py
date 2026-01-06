import time
import threading
from dataclasses import dataclass
import scipy.fft as fft
import numpy as np

from vibechecker import AcquisitionSettings

N_CHANNELS = 2

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

    return signal

def GenerateVibrationData_TemporalMethod(config:AcquisitionSettings):
    # Generate sample data representing rotating equipment with faulty bearing

    nnoise = lambda a: a * np.random.randn(config.blocksize) # normal noise
    tone = lambda a, f, p=0.: a * np.sin(2*np.pi*f*config.time_vec + p) # single frequency tone

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    signal = np.zeros_like(config.time_vec)

    signal += nnoise(0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        signal += tone(1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        signal += tone(bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    time.sleep(config.acquisition_period)
    return signal

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
            signal = GenerateVibrationData_TemporalMethod(self.config)
            data = np.tile(signal, (max(self.config.channel,N_CHANNELS),1)).T
            timestamp = time.monotonic()
            time.sleep(self.config.acquisition_period)
            self.callback(data,self.config.blocksize, timestamp, 'OKAY')

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
