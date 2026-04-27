from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy import signal

from pathlib import Path
import h5py

import vibechecker
from vibechecker import nextpow2
from vibechecker.util import UNIT_TO_SI, AMPLITUDE_SCALE, integration_steps

log = vibechecker.get_logger(__name__)

@dataclass
class AcquisitionSettings:
    """Spectrum acquisition parameters.

    The user controls two primary values — maxfreq and binsize.
    Everything else (samplerate, blocksize, acquisition time) is derived.

    Arithmetic flow:
        maxfreq  → samplerate = nextpow2(2 * maxfreq)
        binsize  → blocksize  = nextpow2(samplerate / binsize)
    """
    _fm: float = 2e3               # max analysis frequency (Hz)
    _df: float = 2.0               # frequency bin resolution (Hz)
    # PicoScope channel settings
    coupling: str = 'AC'
    enabled_channels: list = field(default_factory=lambda: [0])
    channel_voltage_ranges: dict = field(default_factory=lambda: {0: 7})
    channel_couplings: dict = field(default_factory=dict)
    channel_names: dict = field(default_factory=dict)           # {ch: str}  default: 'Ch A'
    channel_target_units: dict = field(default_factory=dict)   # {ch: str}  '' = use sensor EU
    channel_amplitude_modes: dict = field(default_factory=dict) # {ch: str}  'RMS'|'0-P'|'P-P'
    # Trend history
    trend_max_points: int = 500
    trend_fmin: float = 0.0
    trend_fmax: float | None = None
    # FFT / Welch
    fft_window: str = 'hann'
    welch_overlap: float = 0.5     # 0.0–0.95 fraction of nperseg
    # Butterworth filters (applied per-channel in DataCollector.receive_data)
    highpass_enabled: bool = True
    highpass_fc: float = 10.0      # Hz
    lowpass_enabled: bool = False
    lowpass_fc: float = 1000.0     # Hz

    _BUTTER_ORDER: int = field(default=4, repr=False)  # clamped, not user-exposed

    def voltage_range_for(self, ch: int) -> int:
        return self.channel_voltage_ranges.get(ch, 7)

    def coupling_for(self, ch: int) -> str:
        return self.channel_couplings.get(ch, self.coupling)

    def name_for(self, ch: int) -> str:
        """Return user-assigned channel name, or default 'Ch A', 'Ch B', …"""
        return self.channel_names.get(ch, f'Ch {chr(65 + ch)}')

    def target_unit_for(self, ch: int) -> str:
        """Return per-channel target display unit, or '' to use sensor EU."""
        return self.channel_target_units.get(ch, '')

    def amplitude_mode_for(self, ch: int) -> str:
        """Return per-channel amplitude display mode, or '' to fall back to sensor/default."""
        return self.channel_amplitude_modes.get(ch, '')

    @classmethod
    def copy(cls, settings: 'AcquisitionSettings') -> 'AcquisitionSettings':
        c = cls()
        c.maxfreq = settings.maxfreq
        c.binsize = settings.binsize
        return c

    def to_dict(self) -> dict:
        """Serialise user-facing fields to the 'acquisition' section of a device config."""
        return {
            'maxfreq':              self._fm,
            'binsize':              self._df,
            'fft_window':           self.fft_window,
            'welch_overlap':        self.welch_overlap,
            'highpass_enabled':     self.highpass_enabled,
            'highpass_fc':          self.highpass_fc,
            'lowpass_enabled':      self.lowpass_enabled,
            'lowpass_fc':           self.lowpass_fc,
            'trend_max_points':     self.trend_max_points,
            'trend_fmin':           self.trend_fmin,
            'trend_fmax':           self.trend_fmax,
            'channel_names':           dict(self.channel_names),
            'channel_target_units':    dict(self.channel_target_units),
            'channel_amplitude_modes': dict(self.channel_amplitude_modes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'AcquisitionSettings':
        """Build an AcquisitionSettings from an 'acquisition' config dict.

        Missing keys fall back to the dataclass field defaults.
        """
        obj = cls()
        if 'maxfreq'          in d: obj.maxfreq         = float(d['maxfreq'])          # noqa: E701
        if 'binsize'          in d: obj.binsize          = float(d['binsize'])          # noqa: E701
        if 'fft_window'       in d: obj.fft_window       = str(d['fft_window'])        # noqa: E701
        if 'welch_overlap'    in d: obj.welch_overlap    = float(d['welch_overlap'])   # noqa: E701
        if 'highpass_enabled' in d: obj.highpass_enabled = bool(d['highpass_enabled']) # noqa: E701
        if 'highpass_fc'      in d: obj.highpass_fc      = float(d['highpass_fc'])     # noqa: E701
        if 'lowpass_enabled'  in d: obj.lowpass_enabled  = bool(d['lowpass_enabled'])  # noqa: E701
        if 'lowpass_fc'       in d: obj.lowpass_fc       = float(d['lowpass_fc'])      # noqa: E701
        if 'trend_max_points' in d: obj.trend_max_points = int(d['trend_max_points'])  # noqa: E701
        if 'trend_fmin'       in d: obj.trend_fmin       = float(d['trend_fmin'])      # noqa: E701
        if 'trend_fmax'       in d:
            obj.trend_fmax = float(d['trend_fmax']) if d['trend_fmax'] is not None else None
        if 'channel_names'           in d: obj.channel_names           = {int(k): str(v) for k, v in d['channel_names'].items()}
        if 'channel_target_units'    in d: obj.channel_target_units    = {int(k): str(v) for k, v in d['channel_target_units'].items()}
        if 'channel_amplitude_modes' in d: obj.channel_amplitude_modes = {int(k): str(v) for k, v in d['channel_amplitude_modes'].items()}
        return obj

    # ── Derived values ───────────────────────────────────────────────

    @property
    def samplerate(self) -> int:
        """Minimum power-of-2 sample rate satisfying Nyquist for maxfreq."""
        return nextpow2(int(2 * self._fm))

    @property
    def blocksize(self) -> int:
        """Minimum power-of-2 block length achieving the requested binsize."""
        return nextpow2(int(self.samplerate / self._df))

    @property
    def maxfreq(self) -> float:
        return self._fm

    @maxfreq.setter
    def maxfreq(self, fm: float):
        self._fm = float(fm)

    @property
    def binsize(self) -> float:
        return self._df

    @binsize.setter
    def binsize(self, df: float):
        self._df = float(df)

    @property
    def sampleperiod(self) -> float:
        return 1.0 / self.samplerate

    @property
    def acquisition_period(self) -> float:
        return self.blocksize * self.sampleperiod

    @property
    def time_vec(self) -> np.ndarray:
        return np.arange(self.blocksize) * self.sampleperiod

    @property
    def n_fft_bins(self) -> int:
        """Number of frequency bins in the one-sided spectrum."""
        return self.blocksize // 2 + 1

    @property
    def memory_bytes(self) -> int:
        """Approximate memory per channel per block (float64)."""
        return self.blocksize * 8

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
        noverlap = min(self.blocksize - 1, int(nperseg * config.welch_overlap))

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
        peaks, _ = signal.find_peaks(spectrum_amp, distance=5)
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
