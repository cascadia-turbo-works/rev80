import numpy as np
from typing import Union, Literal

SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000]
BLOCKSIZES = list(map(int,np.pow(2, np.arange(8,15))))
MAXFREQS = [2e2, 5e2, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4]
BINSIZES = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

SUPPORTED_UNITS = Literal["g", "mm", "in"]

UNIT_CONVERSION = {
    ("g", "mm"): 9.80665 * 1000,
    ("mm", "g"): 1 / (9.80665 * 1000),
    ("g", "in"): 9.80665 * 1000 / 25.4,
    ("in", "g"): 1 / (9.80665 * 1000 / 25.4),
    ("mm", "in"): 1/ 25.4,
    ("in", "mm"): 25.4
}

def convert_units(data: np.ndarray, from_unit: str, to_unit: str) -> np.ndarray:
    if from_unit == to_unit:
        return data
    try:
        factor = UNIT_CONVERSION[(from_unit, to_unit)]
        return data * factor
    except KeyError:
        raise ValueError(f"Unsupported conversion from {from_unit} to {to_unit}")

def nextpow2(x) -> int:
    # calculate the next power of two above some number x
    return int( 2**np.ceil(np.log2(x)))

class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass

    
