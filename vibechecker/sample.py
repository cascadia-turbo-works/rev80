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
                        nextpow2
from vibechecker.util import UNIT_TO_SI, integration_steps

log = vibechecker.get_logger(__name__)

@dataclass
class AcquisitionSettings:
    _ns: int = BLOCKSIZES[3]
    _fs: int = SAMPLERATES[0]
    _fm: float = MAXFREQS[3]
    _df: float = BINSIZES[3]
    oversample: int = 2
    butter_fc: float | None = 10
    # PicoScope channel settings (ignored by sounddevice / SimulatedSensor paths)
    coupling: str = 'AC'      # 'AC' or 'DC'
    enabled_channels: list = field(default_factory=lambda: [0])
    channel_voltage_ranges: dict = field(default_factory=lambda: {0: 10})

    def voltage_range_for(self, ch: int) -> int:
        """Return the PS4000A voltage range index for a given channel (default ±20V)."""
        return self.channel_voltage_ranges.get(ch, 10)

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
    modality: str = field(default='acceleration')

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

    def get_accel(self, target_unit: str = '') -> tuple:
        """Return (DataFrame[time, signal], rms) with data scaled to target_unit.

        If target_unit is '' or matches self.unit, data is returned as-is.
        Scaling uses the SI ratio between source and target units.
        """
        effective = target_unit if target_unit else self.unit
        if effective == self.unit:
            accel = self.data.copy()
        else:
            src_si = UNIT_TO_SI.get(self.unit, 1.0)
            tgt_si = UNIT_TO_SI.get(effective, 1.0)
            accel = self.data * (src_si / tgt_si)

        rms = np.sqrt(np.mean(np.square(accel))) * np.sqrt(2)
        return pd.DataFrame({'time': self.time_vec, 'signal': accel}), rms

    def fft(self, target_unit: str, config: 'AcquisitionSettings'):
        """Compute Welch PSD and convert to target_unit via freq-domain integration.

        target_unit: desired display/integration unit (e.g. 'mm/s', 'g', 'mm').
                     Pass '' to stay in self.unit (no conversion).

        Integration direction and amplitude scaling are derived from the
        unit strings alone via integration_steps() and UNIT_TO_SI.
        """
        if self.blocksize <= 1:
            log.error('Attempt to fft an EMPTY sample')
            return None, None

        effective_target = target_unit if target_unit else self.unit

        fs = self.samplerate
        df = config.binsize
        nfft = int(fs / df)
        nperseg = nfft
        noverlap = min(self.blocksize, int(nperseg / 2))

        freq, source_spectrum = signal.welch(
            self.data,
            fs=float(fs),
            window='hann',
            nperseg=nperseg,
            noverlap=noverlap,
            nfft=nfft,
            scaling='spectrum',
            detrend='constant',
            average='mean',
        )

        # Frequency-domain integration / differentiation
        n_steps = integration_steps(self.unit, effective_target)
        if n_steps != 0:
            omega_factor = np.power(
                np.where(freq > 0, 2 * np.pi * freq, np.inf),
                2 * n_steps,
            )
            display_spectrum = source_spectrum * omega_factor
        else:
            display_spectrum = source_spectrum.copy()

        # Amplitude scale: SI ratio covers both unit-system conversion and
        # the dimensional change introduced by any integration/differentiation.
        src_si = UNIT_TO_SI.get(self.unit, 1.0)
        tgt_si = UNIT_TO_SI.get(effective_target, 1.0)
        amp_scale = src_si / tgt_si
        display_spectrum = display_spectrum * (amp_scale ** 2)

        source_0p = np.sqrt(source_spectrum) * np.sqrt(2)
        display_0p = np.sqrt(np.maximum(display_spectrum, 0)) * np.sqrt(2)

        result = pd.DataFrame({
            'freq': freq,
            'source_spectrum': source_spectrum,
            'display_spectrum': display_spectrum,
            'source_0p': source_0p,
            'display_0p': display_0p,
        })

        peaks, _ = signal.find_peaks(display_0p, distance=min(len(freq) / 50, 1))
        peaks = np.array(peaks[np.argsort(-display_0p[peaks])])

        return (result[result.freq <= config.maxfreq],
                peaks[freq[peaks] <= config.maxfreq])
    