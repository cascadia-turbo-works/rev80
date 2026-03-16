import numpy as np
from path import Path
from typing import Union, Literal

# Audio interface rates + PicoScope-relevant rates (100 kHz – 1 MHz)
SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000,
               100_000, 200_000, 500_000, 1_000_000]
BLOCKSIZES = list(map(int,np.pow(2, np.arange(8,18))))
MAXFREQS = [2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 2.4e4]
BINSIZES = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

SUPPORTED_UNITS = Literal["g", "mm", "in", "mV"]
UNITS = {'Earth Gravity - g': 'g',
         'Metric - mm': 'mm',
         'Imperial - in': 'in',
         'Voltage - mV': 'mV'}
UNITS_REV = {v:k for k,v in UNITS.items()}

UNIT_CONVERSION = {
    ("g", "mm"): 9.80665 * 1000,
    ("mm", "g"): 1 / (9.80665 * 1000),
    ("g", "in"): 9.80665 * 1000 / 25.4,
    ("in", "g"): 1 / (9.80665 * 1000 / 25.4),
    ("mm", "in"): 1/ 25.4,
    ("in", "mm"): 25.4
}

SAVEDIR = Path('DEVDATA')
EXT = '.h5'

def convert_units(data: np.ndarray, from_unit: str, to_unit: str) -> np.ndarray:
    if from_unit == to_unit:
        return data
    try:
        factor = UNIT_CONVERSION[(from_unit, to_unit)]
        return data * factor
    except KeyError:
        raise ValueError(f"Unsupported conversion from {from_unit} to {to_unit}")


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

    SENSOR_SELECTOR = 'SENSOR_SELECTOR'
    SENSOR_REFRESH = 'SENSOR_REFRESH'
    SENSOR_CONNECT = 'SENSOR_CONNECT'
    SENSOR_DISCONNECT = 'SENSOR_DISCONNECT'

    ACQ_BLOCKSIZE = 'ACQ_BLOCKSIZE'
    ACQ_SAMPLERATE = 'ACQ_SAMPLERATE'
    ACQ_MAXFREQ = 'ACQ_MAXFREQ'
    ACQ_BINSIZE = 'ACQ_BINSIZE'
    ACQ_START = 'ACQ_START'
    ACQ_STOP = 'ACQ_STOP'
    ACQ_SINGLE = 'ACQ_SINGLE'
    ACQ_UNITS = 'ACQ_UNITS'
    ACQ_INTEGRATE = 'ACQ_INTEGRATE'
    ACQ_NORMALIZATION = 'ACQ_NORMALIZATION'

    FILE_NAME = 'FILE_NAME'
    FILE_TIMESTAMP = 'FILE_TIMESTAMP'
    FILE_SAVE = 'FILE_SAVE'
    FILE_LOAD = 'FILE_LOAD'
    FILE_DIALOG = 'FILE_DIALOG'

    PLT_SAMPLE = 'PLT_SAMPLE'
    PLT_SAMPLE_AX_TIME = 'PLT_SAMPLE_AX_TIME'
    PLT_SAMPLE_AX_ACCEL = 'PLT_SAMPLE_AX_ACCEL'
    PLT_SAMPLE_DATA = 'PLT_SAMPLE_DATA'
    PLT_SAMPLE_OVERALL = 'PLT_SAMPLE_OVERALL'

    PLT_FREQ = 'PLT_FREQ'
    PLT_FREQ_AX_FREQ = 'PLT_FREQ_AX_FREQ'
    PLT_FREQ_AX_ACCEL = 'PLT_FREQ_AX_ACCEL'
    PLT_FREQ_DATA = 'PLT_FREQ_DATA'
    PLT_FREQ_PEAKS = 'PLT_FREQ_PEAKS'

    PLT_TREND = 'PLT_TREND'
    PLT_TREND_AX_TIME = 'PLT_TREND_AX_TIME'
    PLT_TREND_AX_RMS = 'PLT_TREND_AX_RMS'
    PLT_TREND_DATA = 'PLT_TREND_DATA'

    FFT_PEAKS_DISPLAY_COUNT = 'FFT_PEAK_DISPLAY_COUNT'
    FFT_PEAKS_TABLE = 'FFT_PEAKS_TABLE'

    DEBUG_TXT = 'DEBUG_TXT'

    # Scope sensor channel assignment + registry
    SCOPE_CH0_SENSOR = 'SCOPE_CH0_SENSOR'
    SCOPE_REGISTRY_LIST = 'SCOPE_REGISTRY_LIST'
    SCOPE_REGISTRY_ADD = 'SCOPE_REGISTRY_ADD'
    SCOPE_REGISTRY_EDIT = 'SCOPE_REGISTRY_EDIT'
    SCOPE_REGISTRY_DELETE = 'SCOPE_REGISTRY_DELETE'
    SCOPE_SENSOR_DIALOG = 'SCOPE_SENSOR_DIALOG'
    SCOPE_DIALOG_NAME = 'SCOPE_DIALOG_NAME'
    SCOPE_DIALOG_MODALITY = 'SCOPE_DIALOG_MODALITY'
    SCOPE_DIALOG_UNITS = 'SCOPE_DIALOG_UNITS'
    SCOPE_DIALOG_SENSITIVITY = 'SCOPE_DIALOG_SENSITIVITY'
    SCOPE_DIALOG_NOTES = 'SCOPE_DIALOG_NOTES'
    SCOPE_DIALOG_OK = 'SCOPE_DIALOG_OK'
    SCOPE_DIALOG_CANCEL = 'SCOPE_DIALOG_CANCEL'

    @property
    def ACQ(self):
        return [self.ACQ_BLOCKSIZE,
                self.ACQ_SAMPLERATE,
                self.ACQ_MAXFREQ,
                self.ACQ_BINSIZE,
                self.ACQ_START,
                self.ACQ_STOP,
                self.ACQ_SINGLE,
                self.ACQ_UNITS,
                self.ACQ_INTEGRATE,]
