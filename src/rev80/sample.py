from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

import rev80
from rev80 import nextpow2
from rev80.config import DEFAULT_CACHE_FRAMES

log = rev80.get_logger(__name__)

@dataclass
class AcquisitionSettings:
    """Spectrum acquisition parameters.

    The user controls two primary values — maxfreq and binsize.
    Everything else (samplerate, blocksize, acquisition time) is derived.

    Arithmetic flow:
        maxfreq  → samplerate = nextpow2(2.56 * maxfreq)
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
    # FFT / Welch
    fft_window: str = 'hann'
    welch_overlap: float = 0.5     # 0.0–0.95 fraction of nperseg
    # Butterworth filters (applied per-channel in DataCollector.receive_data)
    highpass_enabled: bool = True
    highpass_fc: float = 10.0      # Hz
    # Frame cache
    cache_frames: int = DEFAULT_CACHE_FRAMES  # depth of the ring cache in DataCollector

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
        """Serialise acquisition parameters to the 'acquisition' section of a device config.

        Per-channel fields (names, target_units, amplitude_modes, couplings, voltage_ranges)
        are stored in the 'channels' config section, not here.
        """
        return {
            'maxfreq':          self._fm,
            'binsize':          self._df,
            'fft_window':       self.fft_window,
            'welch_overlap':    self.welch_overlap,
            'highpass_enabled': self.highpass_enabled,
            'highpass_fc':      self.highpass_fc,
            'trend_max_points': self.trend_max_points,
            'cache_frames':     self.cache_frames,
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
        if 'trend_max_points' in d: obj.trend_max_points = int(d['trend_max_points'])  # noqa: E701
        if 'cache_frames'     in d: obj.cache_frames     = int(d['cache_frames'])           # noqa: E701
        return obj

    # ── Derived values ───────────────────────────────────────────────

    @property
    def samplerate(self) -> int:
        """Minimum power-of-2 sample rate guaranteeing >=1.28x maxfreq at Nyquist.

        Uses 2.56x maxfreq (rather than the bare 2x Nyquist minimum) before
        rounding up to a power of two. Since nextpow2 only rounds up, this
        guarantees Nyquist (samplerate/2) >= 1.28 * maxfreq, i.e. at least a
        28% margin at every preset. This is the same oversampling ratio real
        FFT vibration analyzers use, and provides the transition-band room
        needed for the mandatory anti-alias filter applied upstream of this
        setting (see PicoScopeStream).
        """
        return nextpow2(int(2.56 * self._fm))

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
    def nperseg(self) -> int:
        """Welch segment length — the whole block.

        Previously the Welch call used nfft = int(samplerate / binsize) while
        blocksize was nextpow2(samplerate / binsize) >= nfft, so the spectrum
        had a different number of lines and a different bin width from the ones
        the UI advertised. Across the preset grid 40 of 72 combinations were
        wrong: F_max=200 / df=20 claimed 17 lines against an actual 13, at a
        real resolution of 20.48 Hz rather than 20 (+2.4%); F_max=2000 / df=5
        claimed 1025 lines against an actual 820.

        Using the whole (power-of-two) block makes n_fft_bins, binsize_actual
        and acquisition_period consistent by construction, and keeps the FFT a
        power of two. Since blocksize = nextpow2(samplerate / binsize), the
        delivered resolution is always at least as fine as the one requested.
        """
        return self.blocksize

    @property
    def binsize_actual(self) -> float:
        """The bin width actually delivered — always <= the requested binsize."""
        return self.samplerate / self.nperseg

    @property
    def n_fft_bins(self) -> int:
        """Number of spectrum lines actually displayed: DC up to maxfreq.

        Not nperseg // 2 + 1. That counts the full one-sided transform out to
        fs/2, but the band between maxfreq and fs/2 is a guard band and is no
        longer displayed (see DataCollector.process_sample step 6), so quoting
        it as a line count overstated what the user can actually see by the
        full 2.56/2 ratio.

        Nominal: derived from config.samplerate. The live spectrum is built on
        the rate the hardware actually achieved, which differs by up to ~1.7%
        (see PicoScopeStream._report_samplerate), so the realised line count
        can differ by a line or two.
        """
        df = self.binsize_actual
        n_below = int(self._fm / df + 1e-9) + 1      # bins at 0, df, 2df … <= fm
        return min(n_below, self.nperseg // 2 + 1)

    @property
    def memory_bytes(self) -> int:
        """Approximate memory per channel per block (float64)."""
        return self.blocksize * 8

@dataclass
class VibeSample:
    status: str
    _timestamp: datetime
    # The rate the hardware actually achieved, post-decimation. Generally not
    # an integer: the driver rounds the streaming interval to whole
    # microseconds (see PicoScopeStream._report_samplerate).
    samplerate: float
    unit: str
    overflow: bool
    degraded: bool = False
    data: np.ndarray = field(default_factory=lambda: np.array([0], dtype=np.float64))

    # at processing time, calculate the overall amplitude for -2 ..0 .. +2 orders of integration/derivative
    # OverallAmplitude_mv_RMS[ -2, -1, 0, 1, 2 ]
    overall_ampl_by_integration_order: np.ndarray = field(default_factory=lambda: np.zeros(5))
    rel_time: float = field(default=0)
    label: str = field(default='')

    # Cached by DataCollector.process_sample on first call; keyed to Welch/filter config
    psd_mv: np.ndarray | None     = field(default=None, repr=False)
    freq_hz: np.ndarray | None    = field(default=None, repr=False)
    _psd_config_key: tuple | None = field(default=None, repr=False)

    # Highpass-filtered mV data, cached by DataCollector. Populated once per
    # frame at ingestion (receive_data) so the filter's state can be carried
    # across consecutive blocks of one continuous stream; recomputed
    # statelessly, from a steady-state initial condition, when a stored frame
    # is replayed or the filter config changed after capture.
    filtered_mv: np.ndarray | None      = field(default=None, repr=False)
    _filter_config_key: tuple | None    = field(default=None, repr=False)

    @classmethod
    def empty(cls):
        return VibeSample(status='EMPTY', _timestamp=datetime.now(),
                          samplerate=-1, unit='mV', overflow=False)
    
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
    


@dataclass(frozen=True)
class ChannelResult:
    """Pre-computed display result for one channel at one capture instant.

    All arrays are in `unit` (the target display unit).  Constructed by
    DataCollector.process_sample(); never mutated after creation.
    """
    channel:    int
    unit:       str              # target display unit, e.g. 'in/s', 'g', 'mV'
    overflow:   bool             # True if ADC clipped during this block
    degraded:   bool             # True if streaming rate was degraded during this block
    time_data:  np.ndarray       # (N,) signal in target unit
    time_vec:   np.ndarray       # (N,) seconds
    samplerate: float
    freq:       np.ndarray       # (K,) Hz
    spectrum:   np.ndarray       # (K,) amplitude in target unit + amp mode
    peaks:      np.ndarray       # indices into freq / spectrum, descending
    overall:    float            # broadband amplitude in target unit + amp mode
    timestamp:  datetime
    rel_time:   float
    status:     str
