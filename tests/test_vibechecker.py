"""Core DataCollector and VibeSample tests — simulated sensor only.

Hardware-specific tests (re-triggering, stream cycles against real hardware,
FFT peak validation via siggen loopback) live in test_picoscope_hw.py.
"""

import time
import numpy as np
import pytest
from path import Path

from vibechecker import (
    AcquisitionSettings,
    DataCollector,
    VibeSample,
    VibeSensor,
    GUI,
    get_logger,
)

DATADIR = Path('DEVDATA')
log = get_logger('test')

acq_settings = AcquisitionSettings()
sim_sensor   = VibeSensor.simulated()


# ---------------------------------------------------------------------------
# Stream start / stop cycle
# ---------------------------------------------------------------------------

def test_stream_cycle():
    """start_stream / stop_stream cycle works and leaves stream in clean state."""
    collector = DataCollector(sim_sensor)
    received = []
    collector.callbacks['test'] = lambda samples: received.extend(samples.values())

    for _ in range(2):
        collector.start_stream()
        time.sleep(acq_settings.acquisition_period * 1.05)
        collector.stop_stream()
        time.sleep(0.05)

    collector.disconnect_sensor()
    assert collector.stream is None, 'Stream should be None after disconnect'


# ---------------------------------------------------------------------------
# collect_sample — format and return-type contract
# ---------------------------------------------------------------------------

def test_collect_sample_returns_dict():
    """collect_sample() returns dict[int, VibeSample]."""
    collector = DataCollector(sim_sensor)
    result = collector.collect_sample()
    collector.disconnect_sensor()

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    ch_data = {k: v for k, v in result.items() if isinstance(k, int)}
    assert len(ch_data) > 0
    for sample in ch_data.values():
        assert isinstance(sample, VibeSample), f'invalid sample {sample}'
        assert sample.blocksize > 1


def test_collect_sample_signal_processing():
    """Collected simulated sample survives get_accel() and fft() without error."""
    collector = DataCollector(sim_sensor)
    result = collector.collect_sample()
    collector.disconnect_sensor()

    for sample in (v for k, v in result.items() if isinstance(k, int)):
        acc, rms = sample.get_accel()
        assert acc.time.to_numpy().flags['C_CONTIGUOUS']
        assert acc.signal.to_numpy().flags['C_CONTIGUOUS']
        fft, peaks = sample.fft('', acq_settings)
        assert fft is not None


# ---------------------------------------------------------------------------
# HDF5 save / load round-trip (file I/O only — no hardware needed)
# ---------------------------------------------------------------------------

def test_save_load_roundtrip():
    """DataCollector multi-channel HDF5 save / load preserves frame data."""
    collector = DataCollector(sim_sensor, acq_settings)
    result = collector.collect_sample()
    collector.disconnect_sensor()

    assert result, 'collect_sample returned empty dict'
    first_sample = next(v for k, v in result.items() if isinstance(k, int))
    assert isinstance(first_sample, VibeSample)

    # Save via DataCollector (new multi-channel format)
    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_roundtrip.h5'
    fname.remove_p()
    collector.save_data(fname)
    assert fname.exists(), 'save_data did not create file'

    # Load into a fresh collector and check the frame came back
    loaded_collector = DataCollector(sim_sensor, acq_settings)
    loaded_collector.load_data(fname)
    loaded_collector.disconnect_sensor()

    cache = loaded_collector.data['frame_cache']
    assert len(cache) >= 1, 'frame_cache empty after load'
    loaded_frame = cache[-1]
    ch = next(iter(loaded_frame))
    loaded_sample = loaded_frame[ch]
    assert loaded_sample.samplerate == first_sample.samplerate, 'samplerate differs after load'
    assert loaded_sample.unit == first_sample.unit,             'unit differs after load'
    assert np.allclose(loaded_sample.data, first_sample.data),  'data differs after load'

    fname.remove_p()


# ---------------------------------------------------------------------------
# GUI build smoke test
# ---------------------------------------------------------------------------

def test_gui_build():
    app = GUI()
    app.initialize()
    time.sleep(1)
    app.cleanup()


if __name__ == '__main__':
    pytest.main()
