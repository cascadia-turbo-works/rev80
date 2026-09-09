import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

import rev80
from rev80.config import DEFAULT_CACHE_FRAMES
from rev80.peaks import DEFAULT_THRESHOLD_DB as PEAK_THRESHOLD_DB_DEFAULT

log = rev80.get_logger(__name__)

#: Fixed acquisition/storage sample rate (Hz), independent of the displayed
#: F_max. Bearing housing resonances (envelope/demodulation analysis) live
#: at 2-20 kHz -- well above where a display-driven F_max (often 1-2 kHz
#: per ISO route-monitoring convention) would give any Nyquist headroom.
#: Acquiring at a fixed rate high enough to always contain a resonance
#: means envelope analysis works regardless of what F_max the user has
#: picked for the Spectrum tab.
#:
#: The value is 2.56 x the top F_max preset (10 kHz), which is what makes
#: the analyzer internally consistent: the display rate is exactly
#: 2.56 * maxfreq, so at the top preset display rate == acquisition rate and
#: no preset can ever ask to display more than acquisition contains. Every
#: preset then decimates from this rate by an exact integer factor
#: (50/20/10/5/2/1), which is the cheapest and cleanest polyphase path.
#:
#: Hardware provenance, measured on a PicoScope 4424A
#: (scripts/validate-streaming-capacity, and picoscope.py's
#: STREAMING_CEILING_HZ comment), sustained 45 s at 3 and 4 channels:
#:
#:   raw rate    osr   ADC rate/ch    overflow   degraded transitions
#:   40000 Hz     2     ~83.3 kHz  (m)     0         0, every run
#:   50000 Hz     2     100.0 kHz  (m)     0         0 to 2, run-to-run
#:   25600 Hz     3      76.8 kHz  (c)     -         NOT YET RE-MEASURED
#:
#: (m) measured, (c) computed from osr -- the driver's achieved rate can
#: differ from the requested one (see PicoScopeStream._report_samplerate),
#: which is why the 40000 Hz row reads 83.3 rather than 80.0.
#:
#: 25600 Hz requests less of the ADC than the 40000 Hz configuration that
#: measured clean, so it is not expected to regress USB streaming -- but that
#: is an inference from the table, not a measurement.
#: Re-run scripts/validate-streaming-capacity when a scope is attached.
#:
#: History: briefly set to 10_000 (dropping the 2.56 factor) to relieve GUI
#: lag while streaming 4 channels. That silently clamped maxfreq to 3906 Hz
#: -- the 5 kHz and 10 kHz presets could not be reached at all -- and halved
#: envelope bandwidth. GUI cost is being addressed separately; it is not a
#: reason to lower the acquisition rate below what the presets require.
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
    - `samplerate` / `blocksize` — unchanged from before this split:
      still maxfreq/binsize-derived, still what the Acquisition dialog's
      "Sample Rate" field shows and what the Spectrum tab's Welch PSD is
      computed at. DataCollector digitally decimates the raw block down
      to this rate (see collector.decimate_to_rate) before computing the
      displayed spectrum -- maxfreq no longer drives acquisition, only
      what's displayed/analysed from it.

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
    # Trend history
    trend_max_points: int = 500
    # FFT / Welch
    fft_window: str = 'hann'
    welch_overlap: float = 0.5     # 0.0–0.95 fraction of nperseg
    # Spectral averaging. Welch's method IS linear power averaging, but since
    # nperseg == blocksize it runs exactly one segment per frame, so each bin is
    # chi-squared(2) with a standard deviation equal to its own mean. Averaging
    # N frames cuts that scatter as 1/sqrt(N) -- which is what makes a small
    # line distinguishable from floor roughness. It does NOT lower the floor's
    # expected level, only the uncertainty of the estimate.
    #
    # Off by default: it changes what the displayed number means, and assumes
    # the machine is steady over the window. If speed drifts, lines smear
    # across bins and averaging blurs them rather than sharpening them.
    averaging_enabled: bool = False
    n_averages: int = 8
    # Peak selection — how far above its own local noise floor a spectral line
    # must rise before it is reported. This replaced a fixed "report the top N
    # by amplitude" rule, which ranked by how loud a line's neighbourhood was
    # rather than by how far it stood out of it. See rev80.peaks.
    peak_threshold_db: float = PEAK_THRESHOLD_DB_DEFAULT
    # Butterworth filters (applied per-channel in DataCollector.receive_data)
    highpass_enabled: bool = True
    # Lower edge of the declared measurement band, and the frequency at which
    # the high-pass is required to still be within passband tolerance -- NOT
    # the filter's -3 dB knee, which sits below it. See
    # DataCollector.highpass_knee_hz().
    highpass_fc: float = 10.0      # Hz
    # Declared measurement band for the overall amplitude. None means "derive":
    # highpass_fc (or 0 with the high-pass off) up to maxfreq.
    #
    # Before this existed the overall was the RMS of the whole filtered block,
    # so its band was highpass_fc ... fs/2 -- and fs/2 is 1.28x-2.56x maxfreq
    # depending on where the power-of-two rounding in `samplerate` lands
    # (2.048x at the 500/1000/2000 Hz presets). Content the user had explicitly
    # excluded via F_max still reached the trend: 2 g RMS at 1500 Hz outside a
    # 1000 Hz F_max inflated reported overall velocity by +25%, enough to move
    # a machine from ISO 20816 zone B to zone C on a reading that should never
    # have included it. Overalls were also not comparable across sessions taken
    # at different F_max, which silently invalidates long-horizon trending.
    band_fmin: float | None = None
    band_fmax: float | None = None
    # Envelope/demodulation analysis is bearing-specific: not every job is a
    # bearing job, and the tab is dead weight (and a source of "what does
    # this mean?" confusion) on ones that aren't. Off by default -- opt in
    # per job rather than opt out.
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

    @classmethod
    def copy(cls, settings: 'AcquisitionSettings') -> 'AcquisitionSettings':
        """Duplicate a settings object.

        This used to copy only maxfreq and binsize, silently dropping every
        other field including all five per-channel dicts (audit H-08). Now it
        round-trips through to_dict/from_dict for the scalars -- so a field
        added there is carried here automatically, and cannot be forgotten --
        and deep-copies the per-channel dicts so the copy is independent.
        """
        c = cls.from_dict(settings.to_dict())
        c.coupling         = settings.coupling
        c.enabled_channels = list(settings.enabled_channels)
        for name in ('channel_voltage_ranges', 'channel_couplings', 'channel_names',
                     'channel_target_units', 'channel_amplitude_modes'):
            setattr(c, name, dict(getattr(settings, name)))
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
        if 'trend_max_points' in d: obj.trend_max_points = int(d['trend_max_points'])  # noqa: E701
        if 'cache_frames'     in d: obj.cache_frames     = int(d['cache_frames'])           # noqa: E701
        return obj

    # ── Derived values ───────────────────────────────────────────────

    @property
    def samplerate(self) -> int:
        """Display rate: exactly 2.56x maxfreq, the standard analyzer ratio.

        2.56 (rather than the bare 2x Nyquist minimum) puts Nyquist at
        1.28 * maxfreq, a 28% guard band for the mandatory anti-alias filter
        applied upstream (see PicoScopeStream). It is the ratio real FFT
        vibration analyzers use, and it is what the Acquisition dialog
        advertises.

        This used to be nextpow2(2.56 * maxfreq), which rounded *up* to a
        power of two and so overstated the rate by up to 2x. That was
        harmless only while raw_samplerate was large enough to absorb it.
        Once RAW_SAMPLERATE_HZ came down to 2.56 x the top preset, the top
        preset rounded to 32768 Hz against 25600 Hz of real data:
        decimate_to_rate's `target_rate >= raw_rate` guard returned the block
        undecimated at 25600 Hz while the dialog advertised 32.8 kS/s, and
        n_fft_bins/binsize_actual were computed from the rate that did not
        exist. Exact 2.56x cannot overshoot: maxfreq's own setter clamps to
        raw_samplerate/2/1.28, which is precisely the condition
        2.56 * maxfreq <= raw_samplerate.

        The FFT length is `blocksize`, not this -- a power-of-two *rate* buys
        nothing. Every preset rate here is 5-smooth (512, 1280, 2560, 5120,
        12800, 25600) and divides RAW_SAMPLERATE_HZ exactly, so raw -> display
        decimation is an exact integer factor at every setting.
        """
        return int(round(2.56 * self._fm))

    @property
    def blocksize(self) -> int:
        """Shortest block achieving the requested binsize: ceil(fs / binsize).

        Was nextpow2(samplerate / binsize). With a power-of-two samplerate
        that divided exactly and a frame was exactly 1/binsize seconds; with
        an exact-2.56x samplerate it would round up to as much as 2x that,
        making frames up to twice as long as the dialog's "1/binsize seconds"
        claim. ceil() restores the invariant and additionally makes
        binsize_actual land on the requested binsize exactly at every preset
        (both grids divide evenly), while still never delivering a coarser
        bin than asked for -- which is what binsize_actual documents.

        Not a power of two any more. It does not need to be: this is a
        Welch segment length handed to scipy's pocketfft, which is efficient
        for any 5-smooth length, and every preset combination here is one.
        """
        return max(1, math.ceil(self.samplerate / self._df))

    @property
    def raw_samplerate(self) -> int:
        """Fixed acquisition/storage rate -- see RAW_SAMPLERATE_HZ. Not maxfreq-derived."""
        return RAW_SAMPLERATE_HZ

    @property
    def raw_blocksize(self) -> int:
        """Raw-rate block length spanning the same duration as `blocksize` (display).

        One frame is one time window at two sample counts -- this and
        `blocksize` cover the same acquisition_period. Not necessarily a
        power of two: unlike `blocksize` this isn't a Welch segment length,
        just how many samples PicoScopeStream accumulates per callback.
        """
        return max(1, round(self.raw_samplerate * self.acquisition_period))

    @property
    def maxfreq(self) -> float:
        return self._fm

    @maxfreq.setter
    def maxfreq(self, fm: float):
        fm = float(fm)
        # samplerate/blocksize (display) are no longer what acquisition runs
        # at, but maxfreq still can't ask to display more than
        # raw_samplerate/2 actually contains -- the anti-alias filter has
        # already discarded anything above that before this data exists.
        # 1.28x mirrors the same margin `samplerate`'s own docstring uses.
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
        """Averages actually achievable: the request, clamped to the ring cache.

        You cannot average more frames than are retained, and quietly averaging
        fewer than the dialog states is the F-8 failure mode -- stated has to
        match delivered. Clamping here keeps the advertised value honest at the
        one place the limit is knowable; the count actually used in any given
        frame is reported separately on the result, since early frames and
        excluded (overflow/degraded) frames lower it further.
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

        Defaults to maxfreq, and is clamped to it: the span between maxfreq and
        fs/2 is the anti-alias filter's transition band, measured at -21.8 dB
        at the folding frequency and effectively 0 dB at fs/2 itself. Content
        there is not a measurement, which is why F-9 stopped displaying it --
        and it must not reach the overall by another route.
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
        """Welch segment length — the whole block.

        Previously the Welch call used nfft = int(samplerate / binsize) while
        blocksize was nextpow2(samplerate / binsize) >= nfft, so the spectrum
        had a different number of lines and a different bin width from the ones
        the UI advertised. Across the preset grid 40 of 72 combinations were
        wrong: F_max=200 / df=20 claimed 17 lines against an actual 13, at a
        real resolution of 20.48 Hz rather than 20 (+2.4%); F_max=2000 / df=5
        claimed 1025 lines against an actual 820.

        Using the whole block makes n_fft_bins, binsize_actual and
        acquisition_period consistent by construction. Since
        blocksize = ceil(samplerate / binsize), the delivered resolution is
        always at least as fine as the one requested (and exactly equal to it
        on the preset grid).
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
        """Approximate memory per channel per block (float64).

        Against raw_blocksize, not blocksize: frame_cache/HDF5 hold the raw
        (acquisition-rate) data, not the maxfreq-decimated display view, so
        this is what actually drives cache/storage cost. Consequently it no
        longer varies with F_max -- only with binsize (via acquisition_period)
        and cache_frames.
        """
        return self.raw_blocksize * 8

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

    # filtered_mv digitally decimated from samplerate (raw acquisition rate)
    # down to the maxfreq-driven display rate, for Spectrum-tab Welch input.
    # Cached the same way as psd_mv -- decimation is real compute
    # (FIR filter + polyphase resample) and process_sample can be called
    # many times on one frame (browsing, unit changes).
    decimated_mv: np.ndarray | None        = field(default=None, repr=False)
    decimated_samplerate: float | None     = field(default=None, repr=False)
    _decimation_config_key: tuple | None   = field(default=None, repr=False)

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
    # The declared band `overall` was measured over, in Hz. Carried on the
    # result so a stored number can be compared with another one: an overall
    # taken over a different band is a different measurement, and before this
    # existed there was nothing recording which band that was.
    #
    # None means "not declared" and appears only on results not built by
    # process_sample -- synthetic test fixtures, and anything reconstructed
    # from a file written before the band was stored. It is deliberately not
    # defaulted to a plausible-looking band, because a wrong band declaration
    # is worse than an absent one.
    band_fmin:  float | None = None
    band_fmax:  float | None = None
    # Impulsiveness scalars, computed on `time_data` -- the band-limited trace
    # the analyst is actually looking at. Dimensionless, so they are unaffected
    # by sensor sensitivity, display unit or amplitude mode. A broadband
    # overall averages impulsiveness away completely; these are what see it.
    crest_factor: float = 0.0
    kurtosis:     float = 3.0
    # Number of frames actually averaged into `spectrum` and `overall`. 1 means
    # no averaging. Reported rather than assumed from config: early frames and
    # frames excluded for overflow/degraded both lower it.
    n_averages:   int = 1

    @property
    def band(self) -> 'tuple[float, float] | None':
        """The declared band as (fmin, fmax), or None if this result has none."""
        if self.band_fmin is None or self.band_fmax is None:
            return None
        return (self.band_fmin, self.band_fmax)
