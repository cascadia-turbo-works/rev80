import time
import threading
import scipy.fft as fft
import numpy as np

from rev80 import AcquisitionSettings

N_CHANNELS = 2

def GenerateTone(config:AcquisitionSettings,
                 ampl:float = 1,
                 freq:float = 500,
                 phase:float = 0):

    # single frequency tone with velocity amplitude
    return ampl * np.cos(2*np.pi*freq * config.time_vec - phase)

def GenerateNoise(config:AcquisitionSettings, ampl:float = 1):
    # normal noise
    return ampl * np.random.randn(config.blocksize)

def GenerateBearingVibration_SpectralMethod(config:AcquisitionSettings):
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

def GenerateBearingVibration_TemporalMethod(config:AcquisitionSettings):
    # Generate sample data representing rotating equipment with faulty bearing

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    signal = np.zeros_like(config.time_vec)

    signal += GenerateNoise(config, 0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        signal += GenerateTone(config, 1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        signal += GenerateTone(config, bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    time.sleep(config.acquisition_period)
    return signal


class SimulatedSensor:

    def __init__(self, config:AcquisitionSettings, sensor, callback):
        self._running: bool = False

        self.sensor = sensor
        self.config = config
        self.channels = 2
        self.callback = callback
        self.source: tuple = (GenerateBearingVibration_TemporalMethod,)
        self.stream: threading.Thread

        self.create_stream()

    @property
    def active(self):
        return self._running

    def create_stream(self):
        self.stream = threading.Thread(target=self._stream, daemon=True)

    def _sample(self):
        # HACK: to acomplish FFT units testing
        args = self.source[1:] if len(self.source)>1 else []
        signal = self.source[0].__call__(self.config, *args) # type: ignore

        n_ch = max(len(self.config.enabled_channels), N_CHANNELS)
        data = np.tile(signal, (n_ch, 1)).T
        return data

    def _stream(self):
        self._running = True
        while self._running:
            # time.sleep(self.config.acquisition_period)
            self.callback(self._sample(),self.config.blocksize, time.monotonic(), 'OKAY')

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
