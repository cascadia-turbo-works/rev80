import numpy as np
from path import Path

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
}


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    """Convert a #RRGGBB hex string to a (R, G, B, A) tuple for DearPyGui."""
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


# ── Audio interface rates + PicoScope-relevant rates (100 kHz – 1 MHz) ──────
SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000,
               100_000, 200_000, 500_000, 1_000_000]
BLOCKSIZES = list(map(int,np.pow(2, np.arange(8,18))))
MAXFREQS = [2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 2.4e4]
BINSIZES = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

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


SAVEDIR = Path('DEVDATA')
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
    BTN_DEVICE_SETUP   = 'BTN_DEVICE_SETUP'
    BTN_SENSOR_SETUP   = 'BTN_SENSOR_SETUP'

    # ── Spectrum Setup section ─────────────────────────────────────────────
    SPECTRUM_INFO_TEXT = 'SPECTRUM_INFO_TEXT'  # readonly multi-line text
    BTN_SPECTRUM_SETUP = 'BTN_SPECTRUM_SETUP'

    # ── Acquisition section ────────────────────────────────────────────────
    STREAM_STATUS      = 'STREAM_STATUS'       # drawlist tag
    STREAM_STATUS_RECT = 'STREAM_STATUS_RECT'
    ACQ_TOGGLE         = 'ACQ_TOGGLE'          # Stopped / Waiting / Running button
    ACQ_SINGLE         = 'ACQ_SINGLE'
    ACQ_BROWSE_PREV    = 'ACQ_BROWSE_PREV'     # ← older frame
    ACQ_BROWSE_NEXT    = 'ACQ_BROWSE_NEXT'     # → newer frame
    ACQ_BROWSE_LABEL   = 'ACQ_BROWSE_LABEL'    # "Frame N / M" text

    # ── File Handling section ──────────────────────────────────────────────
    FILE_SAVE = 'FILE_SAVE'
    FILE_LOAD = 'FILE_LOAD'

    # ── Dialogs ────────────────────────────────────────────────────────────
    DLG_CONFIG           = 'DLG_CONFIG'
    CONFIG_TAB_BAR       = 'CONFIG_TAB_BAR'
    CONFIG_TAB_DEVICE    = 'CONFIG_TAB_DEVICE'
    CONFIG_TAB_CHANNELS  = 'CONFIG_TAB_CHANNELS'
    CONFIG_TAB_SENSORS   = 'CONFIG_TAB_SENSORS'
    CONFIG_TAB_SPECTRUM  = 'CONFIG_TAB_SPECTRUM'
    DLG_SAVE_FILE       = 'DLG_SAVE_FILE'
    DLG_LOAD_FILE       = 'DLG_LOAD_FILE'

    # Spectrum dialog inputs
    SPEC_DLG_MAXFREQ    = 'SPEC_DLG_MAXFREQ'
    SPEC_DLG_BINSIZE    = 'SPEC_DLG_BINSIZE'
    SPEC_DLG_TREND_FMIN = 'SPEC_DLG_TREND_FMIN'
    SPEC_DLG_TREND_FMAX = 'SPEC_DLG_TREND_FMAX'

    # Sensor registry dialog
    SCOPE_REGISTRY_LIST   = 'SCOPE_REGISTRY_LIST'
    SCOPE_REGISTRY_ADD    = 'SCOPE_REGISTRY_ADD'
    SCOPE_REGISTRY_DELETE = 'SCOPE_REGISTRY_DELETE'

    # ── Plots ──────────────────────────────────────────────────────────────
    PLT_SAMPLE          = 'PLT_SAMPLE'
    PLT_SAMPLE_AX_TIME  = 'PLT_SAMPLE_AX_TIME'
    PLT_SAMPLE_AX_ACCEL = 'PLT_SAMPLE_AX_ACCEL'
    PLT_SAMPLE_OVERALL  = 'PLT_SAMPLE_OVERALL'

    PLT_FREQ         = 'PLT_FREQ'
    PLT_FREQ_AX_FREQ  = 'PLT_FREQ_AX_FREQ'
    PLT_FREQ_AX_ACCEL = 'PLT_FREQ_AX_ACCEL'
    PLT_FREQ_AX_2     = 'PLT_FREQ_AX_2'

    PLT_SAMPLE_AX_ACCEL_2 = 'PLT_SAMPLE_AX_ACCEL_2'

    PLT_TREND          = 'PLT_TREND'
    PLT_TREND_AX_TIME  = 'PLT_TREND_AX_TIME'
    PLT_TREND_AX_OVERALL = 'PLT_TREND_AX_OVERALL'
    PLT_TREND_DATA     = 'PLT_TREND_DATA'

    FFT_PEAKS_DISPLAY_COUNT = 'FFT_PEAK_DISPLAY_COUNT'
    FFT_PEAKS_TABLE         = 'FFT_PEAKS_TABLE'

    # ── Results pane ────────────────────────────────────────────────────────
    CH_WARNINGS_SECTION = 'CH_WARNINGS_SECTION'

    # ── Per-channel dynamic tags ───────────────────────────────────────────
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
