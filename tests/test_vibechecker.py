"""Core DataCollector and VibeSample tests — simulated sensor only.

Hardware-specific tests (re-triggering, stream cycles against real hardware,
FFT peak validation via siggen loopback) live in test_picoscope_hw.py.
"""

import time
import numpy as np
import pytest
from path import Path

import vibechecker as vc

DATADIR = Path('DEVDATA')
log = vc.get_logger('test')

settings = vc.AcquisitionSettings()
simsensor = vc.VibeSensor.simulated()


# ---------------------------------------------------------------------------
# Stream start / stop cycle
# ---------------------------------------------------------------------------

def test_stream_cycle():
    """start_stream / stop_stream cycle works and leaves stream in clean state."""
    dc = vc.DataCollector(simsensor)
    received = []
    dc.callbacks['test'] = lambda s: received.extend(s.values())

    dc.start_data_queue()
    for _ in range(2):
        dc.start_stream()
        time.sleep(settings.acquisition_period * 1.05)
        dc.stop_stream()
        time.sleep(0.05)

    dc.disconnect_sensor()
    assert dc.stream is None, 'Stream should be None after disconnect'


# ---------------------------------------------------------------------------
# collect_sample — format and return-type contract
# ---------------------------------------------------------------------------

def test_collect_sample_returns_dict():
    """collect_sample() returns dict[int, VibeSample]."""
    dc = vc.DataCollector(simsensor)
    result = dc.collect_sample()
    dc.disconnect_sensor()

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    assert len(result) > 0
    for sample in result.values():
        assert isinstance(sample, vc.VibeSample), f'invalid sample {sample}'
        assert sample.blocksize > 1


def test_collect_sample_signal_processing():
    """Collected simulated sample survives get_accel() and fft() without error."""
    dc = vc.DataCollector(simsensor)
    result = dc.collect_sample()
    dc.disconnect_sensor()

    for sample in result.values():
        acc, rms = sample.get_accel()
        assert acc.time.to_numpy().flags['C_CONTIGUOUS']
        assert acc.signal.to_numpy().flags['C_CONTIGUOUS']
        fft, peaks = sample.fft('', settings)
        assert fft is not None


# ---------------------------------------------------------------------------
# HDF5 save / load round-trip (file I/O only — no hardware needed)
# ---------------------------------------------------------------------------

def test_save_load_roundtrip():
    """VibeSample.save() / .load() preserves all fields."""
    dc = vc.DataCollector(simsensor, settings)
    result = dc.collect_sample()
    dc.disconnect_sensor()

    vs1 = next(iter(result.values()))
    assert isinstance(vs1, vc.VibeSample)

    vs1.label = 'pytest_data'
    fname = vs1.save()

    vs2 = vc.VibeSample.load(fname)

    assert vs2.status == vs1.status,     'status differs'
    assert vs2.timestamp == vs1.timestamp, 'timestamp differs'
    assert vs2.samplerate == vs1.samplerate, 'samplerate differs'
    assert vs2.unit == vs1.unit,         'unit differs'
    if not np.all(vs2.data == vs1.data):
        diff = np.abs(vs2.data - vs1.data)
        idiff = np.argwhere(diff != 0)
        raise AssertionError(f'Data differ after load. {idiff}, {diff[idiff]}')

    # Exercise DataCollector.load_data path
    dc2 = vc.DataCollector(simsensor, settings)
    dc2.load_data(fname)
    dc2.disconnect_sensor()


# ---------------------------------------------------------------------------
# GUI build smoke test
# ---------------------------------------------------------------------------

def test_gui_build():
    app = vc.GUI()
    app.initialize()
    time.sleep(1)
    app.cleanup()


if __name__ == '__main__':
    pytest.main()
