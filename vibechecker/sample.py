from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy import signal

from path import Path
import h5py

import vibechecker
from vibechecker import BLOCKSIZES, \
                        SAMPLERATES, \
                        MAXFREQS, \
                        BINSIZES, \
                        nextpow2
from vibechecker.util import UNIT_TO_SI, AMPLITUDE_SCALE, integration_steps

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
    coupling: str = 'AC'      # global default — 'AC' or 'DC'
    enabled_channels: list = field(default_factory=lambda: [0])
    channel_voltage_ranges: dict = field(default_factory=lambda: {0: 7})
    channel_couplings: dict = field(default_factory=dict)  # {ch: 'AC'|'DC'}
    # Trend history settings
    trend_max_points: int = 500
    trend_fmin: float = 0.0
    trend_fmax: float | None = None   # None → clamp to maxfreq at compute time
    fft_window: str = 'hann'

    def voltage_range_for(self, ch: int) -> int:
        """Return the PS4000A voltage range index for a given channel (default ±2V)."""
        return self.channel_voltage_ranges.get(ch, 7)

    def coupling_for(self, ch: int) -> str:
        """Return 'AC' or 'DC' for a channel; falls back to the global default."""
        return self.channel_couplings.get(ch, self.coupling)

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
    unit: str
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
        def decode(x): return x.decode() if isinstance(x, bytes) else x
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
                except TypeError:
                    log.error(f'H5 failed to save {key} = {val} ({type(val)})')
        return h5filename
    
    def push_sample(self, 
                    status: str, 
                    rel_time: float,  
                    samplerate: int, 
                    unit: str,
                    data:np.ndarray):
        self.status = status
        self._timestamp = datetime.now()
        self.rel_time = rel_time
        self.samplerate = samplerate
        self.unit = unit
        self.data = data

    # ------------------------------------------------------------------
    # Time-domain conversion
    # ------------------------------------------------------------------

    def _convert_time_domain(self, target_unit: str) -> np.ndarray:
        """Convert raw data to target_unit in the time domain.

        Same-modality: direct SI ratio scaling.
        Cross-modality: FFT → integrate/differentiate → IFFT.
        """
        n_steps = integration_steps(self.unit, target_unit)
        src_si = UNIT_TO_SI.get(self.unit, 1.0)
        tgt_si = UNIT_TO_SI.get(target_unit, 1.0)

        if n_steps == 0:
            return self.data * (src_si / tgt_si)

        N = len(self.data)
        spectrum = np.fft.rfft(self.data)
        freq = np.fft.rfftfreq(N, d=1.0 / self.samplerate)

        omega = 2 * np.pi * freq
        omega[0] = 1.0                           # protect DC from div-by-zero
        transfer = np.power(1j * omega, n_steps)
        transfer[0] = 0.0                         # zero DC — no DC recovery

        spectrum = spectrum * transfer * (src_si / tgt_si)
        return np.fft.irfft(spectrum, n=N)

    # ------------------------------------------------------------------
    # Unified processing: VibeSample → ChannelResult
    # ------------------------------------------------------------------

    def process(self, channel: int, target_unit: str,
                config: 'AcquisitionSettings',
                amplitude_mode: str = '0-P') -> 'ChannelResult | None':
        """Compute everything needed for display in one call.

        Produces a frozen ChannelResult containing:
        - converted time-domain signal (IFFT for cross-modality)
        - Welch spectrum in the configured amplitude mode (RMS/0-P/P-P)
        - sorted peak indices
        - broadband overall amplitude over the trend frequency window

        Returns None if the sample is empty.
        """
        if self.blocksize <= 1:
            log.error('Attempt to process an EMPTY sample')
            return None

        effective_target = target_unit if target_unit else self.unit

        # ── Time-domain conversion (same or cross-modality) ──────────
        time_signal = self._convert_time_domain(effective_target)

        # ── Welch PSD (on raw source data) ───────────────────────────
        fs = self.samplerate
        df = config.binsize
        nfft = int(fs / df)
        nperseg = nfft
        noverlap = min(self.blocksize, int(nperseg / 2))

        freq, source_spectrum = signal.welch(
            self.data,
            fs=float(fs),
            window=config.fft_window,
            nperseg=nperseg,
            noverlap=noverlap,
            nfft=nfft,
            scaling='spectrum',
            detrend='constant',
            average='mean',
        )

        # ── Frequency-domain integration / differentiation ───────────
        n_steps = integration_steps(self.unit, effective_target)
        if n_steps != 0:
            omega_factor = np.power(
                np.where(freq > 0, 2 * np.pi * freq, np.inf),
                2 * n_steps,
            )
            display_spectrum = source_spectrum * omega_factor
        else:
            display_spectrum = source_spectrum.copy()

        # SI amplitude scaling
        src_si = UNIT_TO_SI.get(self.unit, 1.0)
        tgt_si = UNIT_TO_SI.get(effective_target, 1.0)
        amp_scale = src_si / tgt_si
        display_spectrum = display_spectrum * (amp_scale ** 2)

        # ── Amplitude mode (RMS / 0-P / P-P) ────────────────────────
        amp_factor = AMPLITUDE_SCALE.get(amplitude_mode, np.sqrt(2))
        spectrum_amp = np.sqrt(np.maximum(display_spectrum, 0)) * amp_factor

        # ── Peaks ────────────────────────────────────────────────────
        peaks, _ = signal.find_peaks(spectrum_amp,
                                     distance=max(1, int(len(freq) / 50)))
        peaks = np.array(peaks[np.argsort(-spectrum_amp[peaks])])

        # ── Overall broadband amplitude (trend freq window) ──────────
        fmin = config.trend_fmin
        fmax = (min(config.trend_fmax, config.maxfreq)
                if config.trend_fmax is not None else config.maxfreq)
        mask = (freq >= fmin) & (freq <= fmax)
        band = spectrum_amp[mask] if mask.any() else spectrum_amp
        band_rms = band / amp_factor
        overall = float(np.sqrt(np.sum(np.square(band_rms)))) * amp_factor

        return ChannelResult(
            channel=channel,
            unit=effective_target,
            time_data=time_signal,
            time_vec=self.time_vec,
            samplerate=self.samplerate,
            freq=freq,
            spectrum=spectrum_amp,
            peaks=peaks,
            overall=overall,
            timestamp=self._timestamp,
            rel_time=self.rel_time,
            status=self.status,
        )


@dataclass(frozen=True)
class ChannelResult:
    """Pre-computed display result for one channel at one capture instant.

    All arrays are in `unit` (the target display unit).  Constructed by
    VibeSample.process(); never mutated after creation.
    """
    channel:    int
    unit:       str              # target display unit, e.g. 'in/s', 'g', 'mV'
    time_data:  np.ndarray       # (N,) signal in target unit
    time_vec:   np.ndarray       # (N,) seconds
    samplerate: int
    freq:       np.ndarray       # (K,) Hz
    spectrum:   np.ndarray       # (K,) amplitude in target unit + amp mode
    peaks:      np.ndarray       # indices into freq / spectrum, descending
    overall:    float            # broadband amplitude in target unit + amp mode
    timestamp:  datetime
    rel_time:   float
    status:     str
