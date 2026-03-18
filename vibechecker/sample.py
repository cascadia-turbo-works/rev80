from dataclasses import dataclass, field
from typing import Literal, Union
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import signal

from path import Path
import h5py

import vibechecker
from vibechecker import BLOCKSIZES, \
                        SAMPLERATES, \
                        MAXFREQS, \
                        BINSIZES, \
                        SUPPORTED_UNITS, \
                        convert_units, \
                        nextpow2

log = vibechecker.get_logger(__name__)

@dataclass
class AcquisitionSettings:
    _ns: int = BLOCKSIZES[3]
    _fs: int = SAMPLERATES[0]
    _fm: float = MAXFREQS[3]
    _df: float = BINSIZES[3]
    channel: int = 0
    units: SUPPORTED_UNITS = 'g'
    integrate: bool = False
    oversample: int = 2
    butter_fc: float | None = 10
    # PicoScope channel settings (ignored by sounddevice / SimulatedSensor paths)
    voltage_range: int = 10   # PS4000A range index: 10 = PS4000A_20V (±20 V, hardware max)
    coupling: str = 'AC'      # 'AC' or 'DC'

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
        require_df = self.oversample * self.samplerate / self.blocksize
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
        self.ensure_binsize(self.binsize)
    
    def ensure_binsize(self, df:float):
        require_ns = self.oversample * int(self.samplerate / float(df))
        self.blocksize = nextpow2(require_ns)
        log.debug(f'Set samplesize to {self.blocksize} hz to achieve {df} hz frequency resolution') 

@dataclass
class VibeSample:
    status: str
    _timestamp: datetime
    samplerate: int
    unit: SUPPORTED_UNITS
    data: np.ndarray = field(default_factory=lambda: np.array([0], dtype=np.float64))
    rel_time: float = field(default=0)
    label: str = field(default='')

    @classmethod
    def empty(cls):
        return VibeSample(status='EMPTY',
                          _timestamp=datetime.now(),
                          samplerate= -1,
                          unit = 'g')
    
    @property
    def timestamp(self) -> str:
        return self._timestamp.isoformat()
    @timestamp.setter
    def timestamp(self, ts:str|datetime):
        if isinstance(ts, datetime):
            self._timestamp = ts
            return
        
        try:
            self._timestamp = datetime.fromisoformat(ts)
        except ValueError:
            log.error(f'VibeSample got invalid iso timestamp {ts}')

    @property
    def blocksize(self) -> int:
        return len(self.data)
    
    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) / self.samplerate
    
    @classmethod
    def load(cls, h5filename:Path):
        log.debug(f'Loading {h5filename}')
        decode = lambda x: x.decode() if isinstance(x,bytes) else x
        with h5py.File(h5filename, 'r') as f:
            data = {k: decode(v[()]) for k,v in f.items()}

        data['_timestamp'] = datetime.now() # default
        if 'timestamp' in data.keys():
            timestamp = data.pop('timestamp')
            try:
                data['_timestamp'] = datetime.fromisoformat(timestamp)
            except TypeError:
                log.error(f'Failed to parse timestamp {timestamp} in file ')
        
        return cls(**data) # type: ignore
    
    def save(self, h5filename:Path|None=None):
        if h5filename is None:
            stem = self.label if self.label else 'vibedata'
            ts = self._timestamp.isoformat().replace(':','-')
            h5filename = vibechecker.SAVEDIR / (stem + '_' + ts + vibechecker.EXT)
        with h5py.File(h5filename, 'w') as f:
            for key in self.__dataclass_fields__.keys():
                val = self.__getattribute__(key)
                if key == '_timestamp':
                    val = self.timestamp
                    key = 'timestamp'
                try:
                    f.create_dataset(key, data=val)
                except TypeError as e:
                    log.error(f'H5 failed to save {key} = {val} ({type(val)})')
        return h5filename
    
    def push_sample(self, 
                    status: str, 
                    rel_time: float,  
                    samplerate: int, 
                    unit:SUPPORTED_UNITS, 
                    data:np.ndarray):
        self.status = status
        self._timestamp = datetime.now()
        self.rel_time = rel_time
        self.samplerate = samplerate
        self.unit = unit
        self.data = data

    def get_accel(self, config: AcquisitionSettings):
        try:
            accel = convert_units(self.data, self.unit, config.units)
        except ValueError:
            log.warning(f'Unit conversion from {self.unit!r} to {config.units!r} not defined; passing through raw data')
            accel = self.data

        # Butterworth filter - causes lagg
        # sos = accel.butter(10, 10, 'hp', fs=self.samplerate, output='sos')
        # accel = np.ascontiguousarray(accel.sosfiltfilt(sos, accel))

        # Remove mean
        # accel = accel - accel.mean()

        rms = np.sqrt(np.mean(np.square(accel))) * np.sqrt(2)

        tab = {'time': self.time_vec, 'signal': accel}
        return pd.DataFrame(tab), rms

    def fft(self, config:AcquisitionSettings):
        if self.blocksize <= 1:
            log.error('Attempt to fft an EMPTY sample')
            return None, None
        
        accel, _ = self.get_accel(config)

        fs = self.samplerate
        df = config.binsize

        nfft = int(fs/df)
        nperseg = nfft
        noverlap = min(self.blocksize,int(nperseg / 2)) # 50% overlap
        freq, acc_spectrum = signal.welch(accel.signal.to_numpy(),
                                 fs = float(fs),
                                 window = 'hann',
                                 nperseg = nperseg,
                                 noverlap = noverlap,
                                 nfft = nfft,
                                 scaling = 'spectrum',
                                 detrend = 'constant',
                                 average = 'mean')

        # Integrate acceleration to velocity
        omega = np.square(2*np.pi*freq)
        omega[0] = np.inf
        vel_spectrum = acc_spectrum / omega

        # with np.errstate(divide='ignore', invalid='ignore'):
        #     vel_spectrum = np.abs(acc_spectrum / (2*np.pi*freq))
        #     vel_spectrum[0] = 0.0

        # normalize to rms and zero-peak units per bin
        acc_rms = np.sqrt(acc_spectrum)
        vel_rms = np.sqrt(vel_spectrum)
        acc_0p = acc_rms * np.sqrt(2)
        vel_0p = vel_rms * np.sqrt(2)

        df = pd.DataFrame({'freq':freq,
                           'acc_spectrum': acc_spectrum,
                           'vel_spectrum': vel_spectrum,
                           'acc_rms': acc_rms,
                           'vel_rms': vel_rms,
                           'acc_0p': acc_0p,
                           'vel_0p': vel_0p})
        
        peaks, _ = signal.find_peaks(acc_0p, distance=min(len(freq)/50, 1))
        peaks = np.array(peaks[np.argsort(-acc_0p[peaks])])

        return df[df.freq<=config.maxfreq], \
               peaks[freq[peaks]<=config.maxfreq]
    