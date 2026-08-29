import numpy as np

from rev80._paths import data_dir

# ── GUI colour palette ──────────────────────────────────────────────────────
# All colours defined as hex strings (#RRGGBB).  Use hex_to_rgba() to convert
# to DearPyGui-compatible (R, G, B, A) tuples.
# Each hue has three variants: base, _LIGHT (+30 % brightness), _DARK (−30 %).

THEME_COLORS: dict = {
    # Status / signal colours
    'RED':           '#C03030',
    'RED_LIGHT':     '#E05858',
    'RED_DARK':      '#801818',
    'YELLOW':        '#C8A020',
    'YELLOW_LIGHT':  '#EAC040',
    'YELLOW_DARK':   '#8A6C10',
    'GREEN':         '#2A9040',
    'GREEN_LIGHT':   '#46C060',
    'GREEN_DARK':    '#186028',
    # Channel trace colours (match _CH_COLORS order in gui.py)
    'WHITE':         '#F0F0F0',
    'BLUE':          '#4A90E2',
    'ORANGE':        '#FFA500',
    'LIME':          '#64DC64',
    'CORAL':         '#FF5050',
    'CYAN':          '#64C8FF',
    'VIOLET':        '#C864FF',
    'GOLD':          '#FFFF64',
    'SILVER':        '#B4B4B4',
    # Neutral / UI chrome
    'BACKGROUND':    '#1E1E2E',
    'SURFACE':       '#2A2A3E',
    'ON_SURFACE':    '#C8C8D8',
    'BORDER':        '#48485C',
    'MUTED':         '#787890',
}


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    """Convert a #RRGGBB hex string to a (R, G, B, A) tuple for DearPyGui."""
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


# ── Spectrum preset values (quick-pick selections in the GUI) ────────────────
# These are convenience presets, NOT hard constraints.  AcquisitionSettings
# derives samplerate and blocksize arithmetically from maxfreq and binsize.
# Gated so that every offered preset can actually be anti-alias filtered:
# PicoScopeStream oversamples by an integer ratio and filters back down, so a
# preset is only safe if samplerate * 2 <= STREAMING_CEILING_HZ (100 kHz, a
# measured safe continuous-USB-streaming rate). The 20 kHz and 50 kHz presets
# were removed for that reason -- both ran with NO anti-alias filter at all,
# and the 50 kHz preset additionally requested 131072 Hz raw, 31% above the
# ceiling, where the driver silently drops most samples while reporting
# status='OKAY'. See picoscope.PicoScopeStream._choose_osr.
MAXFREQ_PRESETS = [2e2, 5e2, 1e3, 2e3, 5e3, 1e4]
BINSIZE_PRESETS = [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

# ── Unit taxonomy ──────────────────────────────────────────────────────────
# Each unit string encodes both the physical quantity (modality) and the
# measurement system.  'mV' is the raw pass-through unit (no physical dimension).

ACCELERATION_UNITS: frozenset = frozenset({'g', 'mm/s2', 'in/s2', 'mil/s2'})
VELOCITY_UNITS:     frozenset = frozenset({'mm/s', 'in/s', 'mil/s'})
DISPLACEMENT_UNITS: frozenset = frozenset({'mm', 'in', 'mil'})
RAW_UNITS:          frozenset = frozenset({'mV'})

EU_OPTIONS: list = [
    'mV',
    'g', 'mm/s2', 'in/s2', 'mil/s2',
    'mm/s', 'in/s', 'mil/s',
    'mm', 'in', 'mil',
]

# Amplitude normalization modes for frequency-domain display.
# Welch PSD with scaling='spectrum' yields power (RMS²).
#   RMS  = sqrt(spectrum)
#   0-P  = RMS * sqrt(2)
#   P-P  = 0-P * 2
# TODO: add 'PSD' (eu²/Hz) and 'ASD' (eu/√Hz) density modes.  These require
#   switching scipy.welch to scaling='density' and adjusting the amplitude
#   pipeline in VibeSample.process() — do not mix spectrum and density
#   normalization in the same AMPLITUDE_SCALE lookup.
AMPLITUDE_MODES: list = ['RMS', '0-P', 'P-P']
AMPLITUDE_SCALE: dict = {
    'RMS': 1.0,
    '0-P': np.sqrt(2),
    'P-P': 2 * np.sqrt(2),
}

# Modality ordering: acceleration=0, velocity=1, displacement=2
# n_steps = src_order - tgt_order
#   negative  → integrate  (e.g. acc→vel: 0-1=-1, one integration)
#   positive  → differentiate (e.g. vel→acc: 1-0=+1, one differentiation)
MODALITY_ORDER: dict = {'acceleration': 0, 'velocity': 1, 'displacement': 2}

# SI base values for each unit (m/s², m/s, m as appropriate)
# amp_scale = UNIT_TO_SI[src] / UNIT_TO_SI[tgt] applies across any
# integration/differentiation because the (2πf) factors cancel with the
# SI dimension shift.
UNIT_TO_SI: dict = {
    'g':      9.80665,          # m/s²
    'mm/s2':  1e-3,             # m/s²
    'in/s2':  0.0254,           # m/s²
    'mil/s2': 0.0254e-3,        # m/s²
    'mm/s':   1e-3,             # m/s
    'in/s':   0.0254,           # m/s
    'mil/s':  0.0254e-3,        # m/s
    'mm':     1e-3,             # m
    'in':     0.0254,           # m
    'mil':    0.0254e-3,        # m
    'mV':     1.0,              # dimensionless pass-through
}


def modality_of(unit: str) -> str:
    """Return 'acceleration'|'velocity'|'displacement'|'raw' for a unit string."""
    if unit in ACCELERATION_UNITS:
        return 'acceleration'
    if unit in VELOCITY_UNITS:
        return 'velocity'
    if unit in DISPLACEMENT_UNITS:
        return 'displacement'
    if unit in RAW_UNITS:
        return 'raw'
    raise ValueError(f'Unknown unit {unit!r}')


def integration_steps(source_unit: str, target_unit: str) -> int:
    """Number of frequency-domain operations needed to go from source to target.

    Negative = integrate  (e.g. acc→vel = -1, acc→disp = -2)
    Positive = differentiate  (e.g. vel→acc = +1)
    Zero     = pass-through (same modality, or either unit is mV)
    """
    if source_unit == target_unit:
        return 0
    src_mod = modality_of(source_unit)
    tgt_mod = modality_of(target_unit)
    if 'raw' in (src_mod, tgt_mod):
        return 0
    return MODALITY_ORDER[src_mod] - MODALITY_ORDER[tgt_mod]


SAVEDIR = data_dir()
EXT = '.h5'


def nextpow2(x:int) -> int:
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))

def parse_sd_status(sd_status):
    '''
    Parse sounddevice callbackflags objet to string
    
    :param sd_status: Sounddevice status object
    :type sd_status: sounddevice.CallbackFlags
    '''
    if not sd_status._flags:
        return 'OKAY'
    
    # Filters flags to build status string
    status = ' '.join([s for s in filter(lambda s: not s.startswith('_'), dir(sd_status)) if sd_status.__getattribute__(s)])
    if not status:
        return 'ERROR'
    return status


class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass

class UI_Elements:

    # ── Connection Status section ──────────────────────────────────────────
    DEVICE_STATUS      = 'DEVICE_STATUS'       # drawlist tag
    DEVICE_STATUS_RECT = 'DEVICE_STATUS_RECT'
    CONN_STATUS_TEXT   = 'CONN_STATUS_TEXT'    # "Connected" / "Not Connected"
    CONN_DEVICE_NAME   = 'CONN_DEVICE_NAME'    # device model name
    CONN_CHANNEL_SUMMARY = 'CONN_CHANNEL_SUMMARY'  # group for per-channel lines
    DEVICE_INFO_GROUP  = 'DEVICE_INFO_GROUP'   # dynamic device detail lines
    BTN_DEVICE_SETUP   = 'BTN_DEVICE_SETUP'
    BTN_CHANNELS_SETUP = 'BTN_CHANNELS_SETUP'
    BTN_SENSOR_SETUP   = 'BTN_SENSOR_SETUP'
    BTN_SIGGEN_SETUP   = 'BTN_SIGGEN_SETUP'

    # ── Spectrum Setup section ─────────────────────────────────────────────
    SPECTRUM_INFO_TEXT = 'SPECTRUM_INFO_TEXT'  # readonly multi-line text
    SPECTRUM_DEGRADED_WARNING = 'SPECTRUM_DEGRADED_WARNING'  # shown only when stream is rate-degraded
    BTN_SPECTRUM_SETUP = 'BTN_SPECTRUM_SETUP'

    # ── Acquisition section ────────────────────────────────────────────────
    STREAM_STATUS      = 'STREAM_STATUS'       # drawlist tag
    STREAM_STATUS_RECT = 'STREAM_STATUS_RECT'
    ACQ_TOGGLE         = 'ACQ_TOGGLE'          # Stopped / Waiting / Running button
    ACQ_SINGLE         = 'ACQ_SINGLE'
    ACQ_AUTOSCALE      = 'ACQ_AUTOSCALE'       # fit all plot axes to data
    ACQ_CLEAR_CACHE    = 'ACQ_CLEAR_CACHE'     # wipe frame cache + trend
    CHANNELS_CARD      = 'CHANNELS_CARD'        # left-panel Channels card window
    CHANNELS_GEN_LINE  = 'CHANNELS_GEN_LINE'   # "Gen : wave : freq x amp" text
    ACQ_BROWSE_FIRST   = 'ACQ_BROWSE_FIRST'     # << oldest frame
    ACQ_BROWSE_PREV    = 'ACQ_BROWSE_PREV'     # < older frame
    ACQ_BROWSE_NEXT    = 'ACQ_BROWSE_NEXT'     # > newer frame
    ACQ_BROWSE_LAST    = 'ACQ_BROWSE_LAST'     # >> newest frame
    ACQ_BROWSE_LABEL   = 'ACQ_BROWSE_LABEL'    # "Frame N / M" text

    # ── File Handling section ──────────────────────────────────────────────
    FILE_SAVE = 'FILE_SAVE'
    FILE_LOAD = 'FILE_LOAD'
    ACQ_NOTES = 'ACQ_NOTES'

    # ── Primary window ─────────────────────────────────────────────────────
    PRIMARY_WINDOW = 'primary_window'

    # ── Dialogs ────────────────────────────────────────────────────────────
    DLG_CONFIG           = 'DLG_CONFIG'
    CONFIG_TAB_BAR       = 'CONFIG_TAB_BAR'
    CONFIG_TAB_DEVICE    = 'CONFIG_TAB_DEVICE'
    CONFIG_TAB_CHANNELS  = 'CONFIG_TAB_CHANNELS'
    CONFIG_TAB_SENSORS   = 'CONFIG_TAB_SENSORS'
    CONFIG_TAB_ACQUISITION = 'CONFIG_TAB_ACQUISITION'
    CONFIG_TAB_SIGGEN    = 'CONFIG_TAB_SIGGEN'
    CONFIG_TAB_MONITOR   = 'CONFIG_TAB_MONITOR'

    # Monitor Mode setup button + card (left panel)
    BTN_MONITOR_SETUP    = 'BTN_MONITOR_SETUP'
    BTN_MONITOR_BROWSE   = 'BTN_MONITOR_BROWSE'
    MONITOR_BURST_BTN    = 'MONITOR_BURST_BTN'
    MONITOR_BURST_STATUS = 'MONITOR_BURST_STATUS'   # drawlist
    MONITOR_BURST_RECT   = 'MONITOR_BURST_RECT'     # rectangle inside drawlist
    MONITOR_BURST_TEXT   = 'MONITOR_BURST_TEXT'     # "Xs remaining" text
    PLT_TREND_BURST_VLINES = 'PLT_TREND_BURST_VLINES'  # vline_series on trend plot
    DLG_SESSION_BROWSER  = 'DLG_SESSION_BROWSER'
    MONITOR_CARD         = 'MONITOR_CARD'
    MONITOR_RECORD_BTN   = 'MONITOR_RECORD_BTN'
    MONITOR_RESET_BTN    = 'MONITOR_RESET_BTN'
    MONITOR_STATUS_TEXT  = 'MONITOR_STATUS_TEXT'

    # Monitor config dialog inputs
    MON_DLG_INTERVAL     = 'MON_DLG_INTERVAL'
    MON_DLG_PRE_BUFFER   = 'MON_DLG_PRE_BUFFER'
    MON_DLG_BURST_DUR    = 'MON_DLG_BURST_DUR'
    MON_DLG_OUTPUT_DIR   = 'MON_DLG_OUTPUT_DIR'
    MON_DLG_COMPRESS     = 'MON_DLG_COMPRESS'
    MON_DLG_ESTIMATE     = 'MON_DLG_ESTIMATE'

    # Anomaly detection config (Monitor config tab) — controls the EWMA-based
    # RMS / Spectral hooks. Fixed-level and cooldown triggers below have their
    # own independent enable switches.
    MON_ANOM_ENABLED      = 'MON_ANOM_ENABLED'
    MON_ANOM_HOOK         = 'MON_ANOM_HOOK'
    MON_ANOM_RMS_GROUP    = 'MON_ANOM_RMS_GROUP'
    MON_ANOM_RMS_PCT      = 'MON_ANOM_RMS_PCT'
    MON_ANOM_RMS_S        = 'MON_ANOM_RMS_S'
    MON_ANOM_RMS_EWMA_TIME  = 'MON_ANOM_RMS_EWMA_TIME'
    MON_ANOM_RMS_ALPHA_LABEL = 'MON_ANOM_RMS_ALPHA_LABEL'
    MON_ANOM_RMS_WARMUP   = 'MON_ANOM_RMS_WARMUP'
    MON_ANOM_SPEC_GROUP   = 'MON_ANOM_SPEC_GROUP'
    MON_ANOM_SPEC_PCT     = 'MON_ANOM_SPEC_PCT'
    MON_ANOM_SPEC_N       = 'MON_ANOM_SPEC_N'
    MON_ANOM_SPEC_FMIN    = 'MON_ANOM_SPEC_FMIN'
    MON_ANOM_SPEC_FMAX    = 'MON_ANOM_SPEC_FMAX'
    MON_ANOM_SPEC_EWMA_TIME  = 'MON_ANOM_SPEC_EWMA_TIME'
    MON_ANOM_SPEC_ALPHA_LABEL = 'MON_ANOM_SPEC_ALPHA_LABEL'

    # Fixed-level threshold triggers (independent enable switches; Monitor config tab)
    MON_ANOM_FIXED_UPPER_ENABLED = 'MON_ANOM_FIXED_UPPER_ENABLED'
    MON_ANOM_FIXED_UPPER_VALUE   = 'MON_ANOM_FIXED_UPPER_VALUE'
    MON_ANOM_FIXED_UPPER_UNIT    = 'MON_ANOM_FIXED_UPPER_UNIT'
    MON_ANOM_FIXED_LOWER_ENABLED = 'MON_ANOM_FIXED_LOWER_ENABLED'
    MON_ANOM_FIXED_LOWER_VALUE   = 'MON_ANOM_FIXED_LOWER_VALUE'
    MON_ANOM_FIXED_LOWER_UNIT    = 'MON_ANOM_FIXED_LOWER_UNIT'

    # Post-burst cooldown gate (Monitor config tab)
    MON_ANOM_COOLDOWN_ENABLED = 'MON_ANOM_COOLDOWN_ENABLED'
    MON_ANOM_COOLDOWN_S       = 'MON_ANOM_COOLDOWN_S'

    # Signal generator dialog inputs
    SIGGEN_ENABLED       = 'SIGGEN_ENABLED'
    SIGGEN_WAVE_TYPE     = 'SIGGEN_WAVE_TYPE'
    SIGGEN_FREQ_HZ       = 'SIGGEN_FREQ_HZ'
    SIGGEN_PKTOPK_MV     = 'SIGGEN_PKTOPK_MV'
    SIGGEN_OFFSET_MV     = 'SIGGEN_OFFSET_MV'
    # DLG_SAVE_FILE / DLG_LOAD_FILE removed — replaced by tkinter dialogs

    # Acquisition dialog inputs — controls
    ACQ_DLG_MAXFREQ    = 'ACQ_DLG_MAXFREQ'
    ACQ_DLG_BINSIZE    = 'ACQ_DLG_BINSIZE'
    ACQ_DLG_WINDOW     = 'ACQ_DLG_WINDOW'
    ACQ_DLG_OVERLAP    = 'ACQ_DLG_OVERLAP'
    ACQ_DLG_HP_ENABLED = 'ACQ_DLG_HP_ENABLED'
    ACQ_DLG_HP_FC      = 'ACQ_DLG_HP_FC'
    ACQ_DLG_CACHE_FRAMES = 'ACQ_DLG_CACHE_FRAMES'
    # Acquisition dialog — derived display fields
    ACQ_DLG_SAMPLERATE = 'ACQ_DLG_SAMPLERATE'
    ACQ_DLG_NFFT_BINS  = 'ACQ_DLG_NFFT_BINS'
    ACQ_DLG_ACQ_TIME   = 'ACQ_DLG_ACQ_TIME'
    ACQ_DLG_REC_WINDOW = 'ACQ_DLG_REC_WINDOW'
    ACQ_DLG_MEMORY     = 'ACQ_DLG_MEMORY'

    # Sensor registry dialog
    SCOPE_REGISTRY_LIST   = 'SCOPE_REGISTRY_LIST'
    SCOPE_REGISTRY_ADD    = 'SCOPE_REGISTRY_ADD'
    SCOPE_REGISTRY_DELETE = 'SCOPE_REGISTRY_DELETE'
    SREG_FIELD_NAME       = 'SREG_FIELD_NAME'    # sensor name input
    SREG_FIELD_UNITS      = 'SREG_FIELD_UNITS'   # engineering units combo
    SREG_FIELD_SENS       = 'SREG_FIELD_SENS'    # sensitivity input
    SREG_FIELD_NOTES      = 'SREG_FIELD_NOTES'   # notes input

    # ── Device setup dialog internal groups ────────────────────────────────
    DEVSETUP_DEVICE_LIST_GROUP = 'DEVSETUP_DEVICE_LIST_GROUP'  # device picker rows
    DEVSETUP_CHANNEL_GROUP     = 'DEVSETUP_CHANNEL_GROUP'      # per-channel rows

    # ── Plots ──────────────────────────────────────────────────────────────
    PLT_SAMPLE          = 'PLT_SAMPLE'
    PLT_SAMPLE_AX_TIME  = 'PLT_SAMPLE_AX_TIME'
    PLT_SAMPLE_AX_ACCEL = 'PLT_SAMPLE_AX_ACCEL'
    PLT_SAMPLE_OVERALL  = 'PLT_SAMPLE_OVERALL'

    PLT_FREQ          = 'PLT_FREQ'
    PLT_FREQ_LEGEND   = 'PLT_FREQ_LEGEND'
    PLT_FREQ_AX_FREQ  = 'PLT_FREQ_AX_FREQ'
    PLT_FREQ_AX_ACCEL = 'PLT_FREQ_AX_ACCEL'
    PLT_FREQ_AX_2     = 'PLT_FREQ_AX_2'

    PLT_SAMPLE_AX_ACCEL_2  = 'PLT_SAMPLE_AX_ACCEL_2'
    PLT_SAMPLE_LEGEND      = 'PLT_SAMPLE_LEGEND'

    PLT_TREND            = 'PLT_TREND'
    PLT_TREND_LEGEND     = 'PLT_TREND_LEGEND'
    PLT_TREND_AX_TIME    = 'PLT_TREND_AX_TIME'
    PLT_TREND_AX_OVERALL   = 'PLT_TREND_AX_OVERALL'
    PLT_TREND_AX_OVERALL_2 = 'PLT_TREND_AX_OVERALL_2'
    PLT_TREND_DATA         = 'PLT_TREND_DATA'
    PLT_TREND_CURSOR     = 'PLT_TREND_CURSOR'    # vertical line at browsed frame time

    FFT_PEAKS_DISPLAY_COUNT = 'FFT_PEAK_DISPLAY_COUNT'
    FFT_PEAKS_TABLE         = 'FFT_PEAKS_TABLE'

    # ── Results pane ────────────────────────────────────────────────────────
    CH_WARNINGS_SECTION = 'CH_WARNINGS_SECTION'

    # ── Frame info card ─────────────────────────────────────────────────────
    FRAME_INFO_SECTION        = 'FRAME_INFO_SECTION'
    FRAME_INFO_TIMESTAMP      = 'FRAME_INFO_TIMESTAMP'      # always (2-line)
    FRAME_INFO_REL_TIME       = 'FRAME_INFO_REL_TIME'       # burst only
    FRAME_INFO_BLOCKSIZE      = 'FRAME_INFO_BLOCKSIZE'      # always
    FRAME_INFO_SAMPLERATE     = 'FRAME_INFO_SAMPLERATE'     # always
    FRAME_INFO_BURST_HEADER   = 'FRAME_INFO_BURST_HEADER'   # "Burst" section label
    FRAME_INFO_BURST_SEP      = 'FRAME_INFO_BURST_SEP'      # burst section divider
    FRAME_INFO_TRIGGER_TS     = 'FRAME_INFO_TRIGGER_TS'     # burst only (2-line)
    FRAME_INFO_TRIGGER_TYPE   = 'FRAME_INFO_TRIGGER_TYPE'   # burst only
    FRAME_INFO_SESSION_HEADER = 'FRAME_INFO_SESSION_HEADER' # "Session" section label
    FRAME_INFO_SESSION_SEP    = 'FRAME_INFO_SESSION_SEP'    # session/burst divider
    FRAME_INFO_SESSION_START  = 'FRAME_INFO_SESSION_START'  # session or burst (2-line)
    FRAME_INFO_SESSION_END    = 'FRAME_INFO_SESSION_END'    # session or burst (2-line)
    FRAME_INFO_N_CAPTURES     = 'FRAME_INFO_N_CAPTURES'     # session or burst
    FRAME_INFO_N_BURSTS       = 'FRAME_INFO_N_BURSTS'       # session or burst
    FRAME_INFO_INTERVAL       = 'FRAME_INFO_INTERVAL'       # session or burst

    # ── Per-channel dynamic tags ───────────────────────────────────────────
    @staticmethod
    def scope_ch_header(ch: int) -> str:
        return f'SCOPE_CH{ch}_HEADER'

    @staticmethod
    def scope_ch_enabled(ch: int) -> str:
        return f'SCOPE_CH{ch}_ENABLED'

    @staticmethod
    def scope_ch_sensor(ch: int) -> str:
        return f'SCOPE_CH{ch}_SENSOR'

    @staticmethod
    def scope_ch_range(ch: int) -> str:
        return f'SCOPE_CH{ch}_RANGE'

    @staticmethod
    def scope_ch_coupling(ch: int) -> str:
        return f'SCOPE_CH{ch}_COUPLING'

    @staticmethod
    def scope_ch_name(ch: int) -> str:
        return f'SCOPE_CH{ch}_NAME'

    @staticmethod
    def scope_ch_target_unit(ch: int) -> str:
        return f'SCOPE_CH{ch}_TARGET_UNIT'

    @staticmethod
    def scope_ch_amplitude_mode(ch: int) -> str:
        return f'SCOPE_CH{ch}_AMP_MODE'

    @staticmethod
    def scope_ch_name_text(ch: int) -> str:
        return f'SCOPE_CH{ch}_NAME_TEXT'

    @staticmethod
    def scope_ch_hdr_theme(ch: int, enabled: bool) -> str:
        return f'SCOPE_CH{ch}_HDR_THEME_{"ON" if enabled else "OFF"}'

    @staticmethod
    def ch_header_text(ch: int) -> str:
        return f'CH{ch}_HEADER_TEXT'

    @staticmethod
    def ch_overflow_warning(ch: int) -> str:
        return f'CH{ch}_OVERFLOW'

    @staticmethod
    def ch_result_section(ch: int) -> str:
        return f'CH{ch}_RESULT_SECTION'

    @staticmethod
    def ch_overall_value(ch: int) -> str:
        return f'CH{ch}_OVERALL'

    @staticmethod
    def ch_peaks_table(ch: int) -> str:
        return f'CH{ch}_PEAKS_TABLE'

    @staticmethod
    def plt_time_series(ch: int) -> str:
        return f'PLT_TIME_CH{ch}'

    @staticmethod
    def plt_freq_series(ch: int) -> str:
        return f'PLT_FREQ_CH{ch}'

    @staticmethod
    def plt_freq_peaks(ch: int) -> str:
        return f'PLT_FREQ_PEAKS_CH{ch}'

    @staticmethod
    def plt_trend_series(ch: int) -> str:
        return f'PLT_TREND_CH{ch}'


# Monitor Mode capture interval presets (seconds → display label)
MONITOR_INTERVAL_PRESETS: dict[int, str] = {
    5:      '5 s',
    30:     '30 s',
    60:     '1 min',
    300:    '5 min',
    900:    '15 min',
    3600:   '1 h',
    21600:  '6 h',
    86400:  '1 day',
    172800: '2 days',
}
