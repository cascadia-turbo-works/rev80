from dataclasses import dataclass, field
from typing import Literal, Union
import numpy as np
import scipy.signal as signal

from vibechecker.util import BLOCKSIZES, \
                             SAMPLERATES, \
                             MAXFREQS, \
                             BINSIZES, \
                             SUPPORTED_UNITS, \
                             convert_units, \
                             nextpow2
from vibechecker.logger import get_logger

log = get_logger(__name__)

@dataclass
class AcquisitionSettings:
    _ns: int = BLOCKSIZES[2]
    _fs: int = SAMPLERATES[0]
    _fm: float = MAXFREQS[3]
    _df: float = BINSIZES[3]
    channel: int = 0
    units: SUPPORTED_UNITS = 'g'
    integrate: bool = False

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
        if require_fm > self._fm:
            return self._fm
        
        try:
            return next(filter(lambda fm: fm <= require_fm, reversed(MAXFREQS)))
        except StopIteration:
            return require_fm
        
    @maxfreq.setter
    def maxfreq(self, fm:float):
        self.ensure_maxfreq(fm)
        self._fm = float(fm)

    @property
    def binsize(self) -> float:
        require_df = self.samplerate / self.blocksize
        if require_df > self._df:
            return self._df
        
        try:
            return next(filter(lambda df: df >= require_df, BINSIZES))
        except StopIteration:
            return require_df
        
    @binsize.setter
    def binsize(self, df:float):
        self.ensure_binsize(df)
        self._df = float(df)    
    @property
    def sampleperiod(self) -> float:
        return 1./self.samplerate

    @property
    def acquisition_period(self) -> float:
        return self.blocksize * self.sampleperiod
    
    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) * self.sampleperiod

    
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

@dataclass
class VibeSample:
    status: str
    timestamp: float
    samplerate: int
    raw_unit: SUPPORTED_UNITS
    raw_data: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float64))

    integration: Literal['acceleration', 'velocity'] = field(default='acceleration')

    @classmethod
    def empty(cls):
        return VibeSample(status='EMPTY',
                          timestamp= -1,
                          raw_unit='g',
                          samplerate= -1,)
   
    @property
    def blocksize(self) -> int:
        return len(self.raw_data)
    
    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) / self.samplerate
    
    def push_sample(self, 
                    status:str, 
                    timestamp:float,  
                    samplerate: int, 
                    raw_unit:SUPPORTED_UNITS, 
                    raw_data:np.ndarray):
        self.status = status
        self.timestamp = timestamp
        self.samplerate = samplerate
        self.raw_unit = raw_unit
        self.raw_data = raw_data

    def get_accel(self, config:AcquisitionSettings):
        accel = convert_units(self.raw_data, self.raw_unit, config.units)

        # Butterworth filter - causes lagg
        # sos = signal.butter(10, 10, 'hp', fs=self.samplerate, output='sos')
        # accel = np.ascontiguousarray(signal.sosfiltfilt(sos, accel))

        # Remove mean
        accel = accel - accel.mean()

        return self.time_vec, accel

    def get_rms(self, config:AcquisitionSettings):
        _, accel = self.get_accel(config)
        return np.sqrt(np.mean(np.pow(accel,2)))

    def welch(self, config:AcquisitionSettings):
        _, accel = self.get_accel(config)
        fs = self.samplerate
        df = config.binsize

        nperseg = min(self.blocksize, int(fs / df))
        freq, psd = signal.welch(accel, fs=fs, nperseg=nperseg, scaling='spectrum')

        # Crop to config window
        iicrop = freq < config.maxfreq
        freq = freq[iicrop]
        psd =  psd[iicrop]

        return freq, psd
    
    def get_spectrum(self, config:AcquisitionSettings):
        freq, psd = self.welch(config)

        if config.integrate:
            # Integrate acceleration to velocity
            with np.errstate(divide='ignore', invalid='ignore'):
                psd = np.abs(psd / (2j * np.pi * freq))
            psd[0] = 0.0  # avoid division by zero at DC

        peaks, props = signal.find_peaks(psd, distance=min(len(freq)/20, 1))
        peaks = peaks[np.argsort(-psd[peaks])]
    
        return freq, psd, peaks