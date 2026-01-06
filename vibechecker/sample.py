from dataclasses import dataclass, field
from typing import Literal, Union
import numpy as np
import pandas as pd
from path import Path
import scipy.signal as signal
import h5py

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
    butter_fc: float | None = 10

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
        require_ns = self.samplerate / float(df)
        
        self.blocksize = nextpow2(require_ns)
        log.debug(f'Set samplesize to {self.blocksize} hz to achieve {df} hz frequency resolution') 

@dataclass
class VibeSample:
    status: str
    timestamp: float
    samplerate: int
    unit: SUPPORTED_UNITS
    data: np.ndarray = field(default_factory=lambda: np.array([0], dtype=np.float64))

    @classmethod
    def empty(cls):
        return VibeSample(status='EMPTY',
                          timestamp= -1,
                          samplerate= -1,
                          unit = 'g')

    @property
    def blocksize(self) -> int:
        return len(self.data)
    
    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) / self.samplerate
    
    def fft(self, config:AcquisitionSettings):
        _, accel = self.get_accel(config)
        
        rms = np.sqrt(np.mean(np.pow( accel,2)))

        fs = float(self.samplerate)
        df = config.binsize

        nperseg = min(self.blocksize, int(fs / df))
        freq, psd = signal.welch(accel, fs=fs, nperseg=nperseg, scaling='spectrum')

        # Integrate acceleration to velocity
        with np.errstate(divide='ignore', invalid='ignore'):
            psd_v = np.abs(psd / (2j * np.pi * freq))
        psd_v[0] = 0.0  # avoid division by zero at DC

        # normalize to zero-peak units per bin
        psd = np.sqrt(psd) / 2
        psd_v = np.sqrt(psd_v) / 2

        df = pd.DataFrame({'freq':freq,
                           'psd': psd,
                           'psd_v': psd_v})
        
        peaks, _ = signal.find_peaks(psd, distance=min(len(freq)/20, 1))
        peaks = peaks[np.argsort(-psd[peaks])]

        return df[df.freq<=config.maxfreq], peaks, rms
    
    @classmethod
    def load(cls, h5filename:Path):
        decode = lambda x: x.decode() if isinstance(x,bytes) else x
        with h5py.File(h5filename, 'r') as f:
            data = {k: decode(v[()]) for k,v in f.items()}
        return cls(**data) # type: ignore
    
    def save(self, h5filename:Path):
        with h5py.File(h5filename, 'w') as f:
            for k in self.__dataclass_fields__.keys():
                f.create_dataset(k, data=self.__getattribute__(k))

    def push_sample(self, 
                    status: str, 
                    timestamp: float,  
                    samplerate: int, 
                    unit:SUPPORTED_UNITS, 
                    data:np.ndarray):
        self.status = status
        self.timestamp = timestamp
        self.samplerate = samplerate
        self.unit = unit
        self.data = data

    def get_accel(self, config:AcquisitionSettings):
        accel = convert_units(self.data, self.unit, config.units)

        # Butterworth filter - causes lagg
        # sos = signal.butter(10, 10, 'hp', fs=self.samplerate, output='sos')
        # accel = np.ascontiguousarray(signal.sosfiltfilt(sos, accel))

        # Remove mean
        accel = accel - accel.mean()

        return self.time_vec, accel

    def get_rms(self, config:AcquisitionSettings):
        _, accel = self.get_accel(config)
        return np.sqrt(np.mean(np.pow(accel,2)))

    # def welch(self, config:AcquisitionSettings):
    #     _, accel = self.get_accel(config)
    #     fs = float(self.samplerate)
    #     df = config.binsize

    #     nperseg = min(self.blocksize, int(fs / df))
    #     freq, psd = signal.welch(accel, fs=fs, nperseg=nperseg, scaling='spectrum')

    #     # normalize to zero-peak units per bin
    #     psd = np.sqrt(psd) / 2

    #     # Crop to config window
    #     iicrop = freq < config.maxfreq
    #     freq = freq[iicrop]
    #     psd =  psd[iicrop]

    #     return freq, psd
    
    # def integrate_spectrum(self, freq, psd):
    #     # Integrate acceleration to velocity
    #     with np.errstate(divide='ignore', invalid='ignore'):
    #         psd = np.abs(psd / (2j * np.pi * freq))
    #     psd[0] = 0.0  # avoid division by zero at DC
    
    # def get_spectrum(self, config:AcquisitionSettings):
    #     freq, psd = self.welch(config)

    #     if config.integrate:
    #         _, psd_v = self.integrate_spectrum(freq,psd)

    #     peaks, props = signal.find_peaks(psd, distance=min(len(freq)/20, 1))
    #     peaks = peaks[np.argsort(-psd[peaks])]
    
    #     return freq, psd, peaks