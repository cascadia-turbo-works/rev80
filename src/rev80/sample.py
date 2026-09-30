import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

import rev80
from rev80 import CHANNEL_ROLES, DEFAULT_CHANNEL_ROLE, DEFAULT_ROTATION_UNIT
from rev80.config import DEFAULT_CACHE_FRAMES
from rev80.peaks import DEFAULT_THRESHOLD_DB as PEAK_THRESHOLD_DB_DEFAULT

log = rev80.get_logger(__name__)

#: Raw rate in Hz: the fixed acquisition and storage rate, independent of
#: maxfreq. It is 2.56 x the top F_max preset (10 kHz), so every preset
#: decimates from it by an integer factor (50/20/10/5/2/1), and envelope
#: analysis always has bandwidth to 10 kHz. A 4824A achieves about 25591.8 Hz
#: (12.5 ns clock grid, see picoscope._TIMEBASE_NS).
#: Evidence: CONTRIBUTING.md, "E1. Streaming ceiling and the raw rate".
RAW_SAMPLERATE_HZ: int = 25_600


def _opt_float(v) -> float | None:
    """Coerce a config value to float, preserving None (and empty/0 as unset)."""
    if v is None or v == '':
        return None
    f = float(v)
    return f if f > 0 else None


@dataclass
class AcquisitionSettings:
    """Spectrum acquisition parameters.

    Two rates, not one:

    - `raw_samplerate` / `raw_blocksize` — fixed at RAW_SAMPLERATE_HZ,
      independent of maxfreq. This is what PicoScopeStream actually
      acquires, what VibeSample.data/HDF5/frame_cache hold, and what
      envelope analysis operates on directly.
    - `samplerate` / `blocksize` — the display rate and block, derived from
      maxfreq and binsize. The Acquisition dialog's "Sample Rate" field shows
      this rate, and the Spectrum tab's Welch PSD runs at it.
      DataCollector decimates the raw block to it (collector.decimate_to_rate).
      maxfreq sets only what is displayed and analysed, not the acquisition.

    Arithmetic flow:
        maxfreq  → samplerate = 2.56 * maxfreq   (display)
        binsize  → blocksize  = ceil(samplerate / binsize)  (display)
        RAW_SAMPLERATE_HZ → raw_blocksize, spanning the same
            acquisition_period as blocksize above  (acquisition/storage)
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
    channel_roles: dict = field(default_factory=dict)           # {ch: str}  'vibration'|'tachometer'
    # Speed gate: a frame outside the shaft-speed window is measured, shown and
    # stored, but not trended, used for baselines or alarmed on. Off by
    # default (it needs a tachometer). Evidence: CONTRIBUTING.md, "E20. Speed gate".
    speed_gate_enabled: bool = False
    speed_gate_rpm: float | None = None   # None = latch from the first valid frame
    speed_gate_tolerance_pct: float = 3.0
    # Display unit for every shaft-rate readout. A preference, never a property
    # of stored data -- TachResult.rpm and the HDF5 files stay in RPM.
    rotation_unit: str = DEFAULT_ROTATION_UNIT
    # Trend history
    trend_max_points: int = 500
    # FFT / Welch
    fft_window: str = 'hann'
    welch_overlap: float = 0.5     # 0.0–0.95 fraction of nperseg
    # Spectral averaging of N frames in the power domain. Off by default: it
    # changes what the displayed number means, and it needs a steady machine.
    averaging_enabled: bool = False
    n_averages: int = 8
    # Peak selection: dB above the line's own local noise floor. See rev80.peaks.
    peak_threshold_db: float = PEAK_THRESHOLD_DB_DEFAULT
    # High-pass: applied with state in DataCollector.receive_data; stateless on replay.
    highpass_enabled: bool = True
    # Lower band edge: the response is inside tolerance here. Not the -3 dB
    # knee, which is lower. See DataCollector.highpass_knee_hz().
    highpass_fc: float = 10.0      # Hz
    # Declared band for the overall, in Hz. None = derive: highpass_fc (0 with
    # the high-pass off) up to maxfreq.
    band_fmin: float | None = None
    band_fmax: float | None = None
    # Envelope tab. Off by default: it is for bearing jobs only.
    envelope_enabled: bool = False
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

    def role_for(self, ch: int) -> str:
        """Return 'vibration' (the default) or 'tachometer' for a channel.

        An unrecognised value falls back to 'vibration' rather than propagating:
        a hand-edited YAML must not be able to invent a third kind of channel
        that every downstream `if role == ...` branch then fails to handle.
        """
        role = self.channel_roles.get(ch, DEFAULT_CHANNEL_ROLE)
        return role if role in CHANNEL_ROLES else DEFAULT_CHANNEL_ROLE

    @property
    def tach_channels(self) -> list:
        """Enabled channels acting as tachometers.

        Enabled, not merely configured: a tach role left on a channel that is
        switched off would otherwise have the collector hunting for a pulse
        train on an input nobody is sampling.
        """
        return [ch for ch in sorted(self.enabled_channels)
                if self.role_for(ch) == 'tachometer']

    @property
    def vibration_channels(self) -> list:
        """Enabled channels carrying vibration -- everything not a tachometer.

        This is what `process_samples` iterates. A tachometer channel has no
        spectrum, no overall and no engineering unit, so it must never reach
        the paths that assume all three.
        """
        return [ch for ch in sorted(self.enabled_channels)
                if self.role_for(ch) != 'tachometer']

    @classmethod
    def copy(cls, settings: 'AcquisitionSettings') -> 'AcquisitionSettings':
        """Return an independent copy of `settings`.

        Scalars go through to_dict/from_dict, so a field added there is copied
        automatically. The per-channel dicts are copied one by one (below).
        """
        c = cls.from_dict(settings.to_dict())
        c.coupling         = settings.coupling
        c.enabled_channels = list(settings.enabled_channels)
        # List every per-channel dict here. They are outside the
        # to_dict/from_dict round trip. A dict that is not in this tuple is lost
        # silently: without channel_roles, every tachometer in the copy becomes
        # a vibration channel.
        for name in ('channel_voltage_ranges', 'channel_couplings', 'channel_names',
                     'channel_target_units', 'channel_amplitude_modes',
                     'channel_roles'):
            setattr(c, name, dict(getattr(settings, name)))
        return c

    def to_dict(self) -> dict:
        """Serialise acquisition parameters to the 'acquisition' section of a device config.

        Per-channel fields (names, target units, amplitude modes, couplings,
        voltage ranges, roles) are stored in the 'channels' section, not here.
        """
        return {
            'maxfreq':          self._fm,
            'binsize':          self._df,
            'fft_window':       self.fft_window,
            'welch_overlap':    self.welch_overlap,
            'peak_threshold_db': self.peak_threshold_db,
            'averaging_enabled': self.averaging_enabled,
            'n_averages':       self.n_averages,
            'highpass_enabled': self.highpass_enabled,
            'highpass_fc':      self.highpass_fc,
            # None must survive the round trip: writing the resolved value back
            # would freeze the F_max in force at save time into the config.
            'band_fmin':        self.band_fmin,
            'band_fmax':        self.band_fmax,
            'envelope_enabled': self.envelope_enabled,
            'speed_gate_enabled': self.speed_gate_enabled,
            # None means "latch the reference from the first valid frame".
            # Writing a resolved value back would freeze one session's running
            # speed into the config -- the trap band_fmin/band_fmax also guard.
            'speed_gate_rpm':   self.speed_gate_rpm,
            'speed_gate_tolerance_pct': self.speed_gate_tolerance_pct,
            'rotation_unit':    self.rotation_unit,
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
        if 'peak_threshold_db' in d: obj.peak_threshold_db = float(d['peak_threshold_db'])  # noqa: E701
        if 'averaging_enabled' in d: obj.averaging_enabled = bool(d['averaging_enabled'])  # noqa: E701
        if 'n_averages'       in d: obj.n_averages       = int(d['n_averages'])        # noqa: E701
        if 'highpass_enabled' in d: obj.highpass_enabled = bool(d['highpass_enabled']) # noqa: E701
        if 'highpass_fc'      in d: obj.highpass_fc      = float(d['highpass_fc'])     # noqa: E701
        if 'band_fmin'        in d: obj.band_fmin        = _opt_float(d['band_fmin'])  # noqa: E701
        if 'band_fmax'        in d: obj.band_fmax        = _opt_float(d['band_fmax'])  # noqa: E701
        if 'envelope_enabled' in d: obj.envelope_enabled = bool(d['envelope_enabled'])  # noqa: E701
        if 'speed_gate_enabled' in d: obj.speed_gate_enabled = bool(d['speed_gate_enabled'])  # noqa: E701
        if 'speed_gate_rpm'   in d: obj.speed_gate_rpm    = _opt_float(d['speed_gate_rpm'])  # noqa: E701
        if 'speed_gate_tolerance_pct' in d: obj.speed_gate_tolerance_pct = float(d['speed_gate_tolerance_pct'])  # noqa: E701
        if 'rotation_unit'    in d: obj.rotation_unit    = str(d['rotation_unit'])   # noqa: E701
        if 'trend_max_points' in d: obj.trend_max_points = int(d['trend_max_points'])  # noqa: E701
        if 'cache_frames'     in d: obj.cache_frames     = int(d['cache_frames'])           # noqa: E701
        return obj

    # ── Derived values ───────────────────────────────────────────────

    @property
    def samplerate(self) -> int:
        """Display rate in Hz: exactly 2.56 x maxfreq, rounded to an integer.

        Nyquist is 1.28 x maxfreq, a 28 % guard band for the anti-alias filter.
        The maxfreq clamp keeps this rate at or below raw_samplerate. Evidence:
        CONTRIBUTING.md, "E11. Display rate, block size and line count".
        """
        return int(round(2.56 * self._fm))

    @property
    def blocksize(self) -> int:
        """Display block length: ceil(samplerate / binsize) samples.

        This is the shortest block whose bin is not coarser than binsize. It
        is not a power of two. Evidence: CONTRIBUTING.md, "E11. Display rate,
        block size and line count".
        """
        return max(1, math.ceil(self.samplerate / self._df))

    @property
    def raw_samplerate(self) -> int:
        """Nominal raw rate, RAW_SAMPLERATE_HZ. Does not depend on maxfreq."""
        return RAW_SAMPLERATE_HZ

    @property
    def raw_blocksize(self) -> int:
        """Raw-rate block length: the same acquisition_period as `blocksize`.

        This is the number of samples per channel in each block that
        PicoScopeStream and SimulatedSensor deliver.
        """
        return max(1, round(self.raw_samplerate * self.acquisition_period))

    @property
    def maxfreq(self) -> float:
        return self._fm

    @maxfreq.setter
    def maxfreq(self, fm: float):
        fm = float(fm)
        # Clamp so that 2.56 x maxfreq <= raw_samplerate: the display cannot
        # show more than the raw data contains (same 1.28 x Nyquist margin).
        max_displayable = RAW_SAMPLERATE_HZ / 2.0 / 1.28
        if fm > max_displayable:
            log.warning(
                "maxfreq=%.1f Hz exceeds what raw_samplerate=%d Hz can display "
                "(max %.1f Hz) -- clamping.", fm, RAW_SAMPLERATE_HZ, max_displayable,
            )
            fm = max_displayable
        self._fm = fm

    @property
    def binsize(self) -> float:
        return self._df

    @binsize.setter
    def binsize(self, df: float):
        self._df = float(df)

    @property
    def n_averages_effective(self) -> int:
        """Averages that the ring cache can hold: n_averages clamped to cache_frames.

        The dialog must state what is delivered. The count used for one frame
        is in ChannelResult.n_averages; early and excluded frames lower it.
        """
        return max(1, min(int(self.n_averages), int(self.cache_frames)))

    @property
    def band_fmin_resolved(self) -> float:
        """Lower edge of the declared band, in Hz.

        Defaults to the high-pass edge, since content below it has already been
        attenuated and is not a measurement. Zero when the high-pass is off.
        """
        if self.band_fmin is not None:
            return max(0.0, float(self.band_fmin))
        return float(self.highpass_fc) if self.highpass_enabled else 0.0

    @property
    def band_fmax_resolved(self) -> float:
        """Upper edge of the declared band, in Hz.

        Defaults to maxfreq, and is clamped to it. Between maxfreq and fs/2
        is the anti-alias transition band, which does not reject aliases.
        The spectrum is not shown there, and the overall must not include it.
        """
        if self.band_fmax is not None:
            return min(float(self.band_fmax), float(self._fm))
        return float(self._fm)

    @property
    def band(self) -> tuple[float, float]:
        """The declared band as (fmin, fmax), both resolved."""
        return self.band_fmin_resolved, self.band_fmax_resolved

    @property
    def raw_sampleperiod(self) -> float:
        return 1.0 / self.raw_samplerate

    @property
    def raw_time_vec(self) -> np.ndarray:
        return np.arange(self.raw_blocksize) * self.raw_sampleperiod

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
        """Welch segment length: the whole block, so one segment per frame.

        This keeps n_fft_bins, binsize_actual and acquisition_period consistent.
        Evidence: CONTRIBUTING.md, "E11. Display rate, block size and line count".
        """
        return self.blocksize

    @property
    def binsize_actual(self) -> float:
        """The bin width actually delivered — always <= the requested binsize."""
        return self.samplerate / self.nperseg

    @property
    def n_fft_bins(self) -> int:
        """Number of displayed spectrum lines, DC up to maxfreq.

        Not nperseg // 2 + 1: the guard band above maxfreq is not displayed.
        Nominal, from `samplerate`. The live spectrum uses the achieved rate
        (-320 ppm on a 4824A), so the live count can be larger by up to
        320 ppm: 40013 lines against 40001 at 10 kHz and 0.25 Hz.
        """
        df = self.binsize_actual
        n_below = int(self._fm / df + 1e-9) + 1      # bins at 0, df, 2df … <= fm
        return min(n_below, self.nperseg // 2 + 1)

    @property
    def memory_bytes(self) -> int:
        """Approximate bytes per channel per block: raw_blocksize x 8 (float64).

        frame_cache and HDF5 hold raw-rate data, so the value changes with
        binsize (through acquisition_period) but not with maxfreq.
        """
        return self.raw_blocksize * 8

@dataclass
class VibeSample:
    status: str
    _timestamp: datetime
    # Achieved raw rate in Hz (after oversampling decimation). Generally not an
    # integer (12.5 ns clock grid on a 4824A). Store it as a float: 25591 in
    # place of 25591.81 moves every frequency by 32 ppm.
    # Evidence: CONTRIBUTING.md, "E5. Report the achieved rate".
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

    # High-pass-filtered mV. Set at ingestion (receive_data, filter state
    # carried across blocks); recomputed statelessly on replay or after a
    # filter-config change.
    filtered_mv: np.ndarray | None      = field(default=None, repr=False)
    _filter_config_key: tuple | None    = field(default=None, repr=False)

    # filtered_mv decimated to the display rate, for the Spectrum-tab Welch
    # input. Cached: process_sample runs many times on one frame (browse).
    decimated_mv: np.ndarray | None        = field(default=None, repr=False)
    decimated_samplerate: float | None     = field(default=None, repr=False)
    _decimation_config_key: tuple | None   = field(default=None, repr=False)

    # TachResult on a tachometer channel; None on a vibration channel. Set at
    # ingestion, keyed on its settings, so a changed pulses_per_rev recomputes.
    tach: 'object | None'             = field(default=None, repr=False)
    _tach_config_key: tuple | None    = field(default=None, repr=False)

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
    overall:    float            # band amplitude in target unit + amp mode
    timestamp:  datetime
    rel_time:   float
    status:     str
    # Declared band of `overall`, in Hz. None = not declared (test fixtures,
    # files without a stored band). Do not default it to a plausible band.
    band_fmin:  float | None = None
    band_fmax:  float | None = None
    # Dimensionless impulsiveness scalars of `time_data`. Never averaged.
    crest_factor: float = 0.0
    kurtosis:     float = 3.0
    # Frames averaged into `spectrum` and `overall`; 1 = no averaging.
    n_averages:   int = 1
    # Shaft speed in RPM; None = no tachometer reading, never 0.0.
    rpm:        float | None = None
    # False when the frame is outside the speed window: shown and stored, but
    # not trended, used for baselines or alarmed on. True when no gate applies.
    speed_ok:   bool = True

    @property
    def one_x_hz(self) -> 'float | None':
        """Shaft rate in Hz for this frame, or None with no tachometer reading."""
        return None if self.rpm is None else self.rpm / 60.0

    @property
    def one_x_amplitude(self) -> 'float | None':
        """Spectrum level at 1x: the larger of the two bins on each side of it.

        This is consistent with the peak report: max-bin amplitude, no energy
        summation, no frequency interpolation. None when there is no reading,
        or when 1x is outside the displayed spectrum (F_max can be below the
        shaft rate). The edge bin would be a wrong number, not a missing one.
        """
        f = self.one_x_hz
        if f is None or len(self.freq) == 0 or len(self.spectrum) == 0:
            return None
        if f < float(self.freq[0]) or f > float(self.freq[-1]):
            return None
        hi = int(np.searchsorted(self.freq, f, side='left'))
        lo = max(0, hi - 1)
        hi = min(hi, len(self.spectrum) - 1)
        return float(max(self.spectrum[lo], self.spectrum[hi]))

    @property
    def band(self) -> 'tuple[float, float] | None':
        """The declared band as (fmin, fmax), or None if this result has none."""
        if self.band_fmin is None or self.band_fmax is None:
            return None
        return (self.band_fmin, self.band_fmax)
