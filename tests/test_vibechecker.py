"""Core DataCollector and VibeSample tests — simulated sensor only.

Hardware-specific tests (re-triggering, stream cycles against real hardware,
FFT peak validation via siggen loopback) live in test_picoscope_hw.py.
"""

import time
import yaml
import h5py
import numpy as np
import pytest
from pathlib import Path

from vibechecker import (
    AcquisitionSettings,
    DataCollector,
    VibeSample,
    VibeSensor,
    GUI,
    get_logger,
)
from vibechecker.scope_sensor import ScopeSensor

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
    """Collected simulated sample survives process() without error."""
    collector = DataCollector(sim_sensor)
    result = collector.collect_sample()
    collector.disconnect_sensor()

    for ch, sample in ((k, v) for k, v in result.items() if isinstance(k, int)):
        cr = collector.process_sample(ch, sample)
        assert cr is not None
        assert cr.time_data.flags['C_CONTIGUOUS']
        assert len(cr.freq) > 0
        assert len(cr.spectrum) == len(cr.freq)


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

    #fname.remove_p()


# ---------------------------------------------------------------------------
# Offline file loading — no device connected
# ---------------------------------------------------------------------------

def test_load_offline_configures_channels():
    """Loading an h5 with no sensor sets enabled_channels from file contents."""
    # First, create a file with known channel data
    collector = DataCollector(sim_sensor, acq_settings)
    result = collector.collect_sample()
    collector.disconnect_sensor()
    assert result

    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_offline.h5'
    fname.remove_p()
    collector.save_data(fname)

    # Load into a fresh collector with NO sensor
    offline = DataCollector(config=acq_settings)
    assert offline.sensor is None, 'Should have no sensor'
    assert offline.stream is None, 'Should have no stream'

    offline.load_data(fname)

    # Verify channels were auto-configured
    cache = offline.data['frame_cache']
    assert len(cache) >= 1, 'frame_cache empty after offline load'

    # Collect all channel keys from loaded frames
    loaded_channels = set()
    for frame in cache:
        loaded_channels.update(k for k in frame if isinstance(k, int))

    assert loaded_channels, 'No channel data in loaded file'
    assert set(offline.config.enabled_channels) == loaded_channels, (
        f'enabled_channels {offline.config.enabled_channels} != '
        f'file channels {sorted(loaded_channels)}'
    )

    # Verify reprocess works (process() on loaded samples)
    last_frame = cache[-1]
    for ch, sample in ((k, v) for k, v in last_frame.items() if isinstance(k, int)):
        cr = offline.process_sample(ch, sample)
        assert cr is not None, f'process_sample() returned None for channel {ch}'
        assert len(cr.freq) > 0

    fname.remove_p()


def test_load_offline_adjusts_maxfreq():
    """Loading a file whose samplerate > current config adjusts maxfreq."""
    # Create a file with high samplerate
    high_freq_config = AcquisitionSettings()
    high_freq_config.maxfreq = 50000.0  # → samplerate = 131072
    collector = DataCollector(sim_sensor, high_freq_config)
    result = collector.collect_sample()
    collector.disconnect_sensor()

    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_offline_hf.h5'
    fname.remove_p()
    collector.save_data(fname)

    # Load with a low-freq default config
    low_config = AcquisitionSettings()
    low_config.maxfreq = 500.0  # → samplerate = 1024
    offline = DataCollector(config=low_config)
    old_sr = offline.config.samplerate

    offline.load_data(fname)

    # Config should have been adjusted upward
    assert offline.config.samplerate >= high_freq_config.samplerate, (
        f'samplerate {offline.config.samplerate} should be >= '
        f'{high_freq_config.samplerate} after loading high-freq file'
    )

    fname.remove_p()


# ---------------------------------------------------------------------------
# Channel naming — AcquisitionSettings helpers
# ---------------------------------------------------------------------------

def test_channel_name_defaults_and_override():
    """name_for() returns default 'Ch A' and respects explicit override."""
    cfg = AcquisitionSettings()
    assert cfg.name_for(0) == 'Ch A'
    assert cfg.name_for(1) == 'Ch B'
    assert cfg.name_for(7) == 'Ch H'
    cfg.channel_names[0] = 'Drive End'
    assert cfg.name_for(0) == 'Drive End'
    assert cfg.name_for(1) == 'Ch B'   # unset channels keep default


# ---------------------------------------------------------------------------
# Scope sensor config persisted in h5
# ---------------------------------------------------------------------------

def test_save_data_persists_scope_sensor():
    """save_data writes scope sensor into the /metadata sensor library (v3 format)."""
    sensor = ScopeSensor(name='Test Sensor', engineering_units='g',
                         sensitivity=10.0)
    collector = DataCollector(sim_sensor, acq_settings)
    collector.set_scope_sensor(0, sensor)
    collector.collect_sample()
    collector.disconnect_sensor()

    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_sensor_save.h5'
    fname.remove_p()
    collector.save_data(fname)

    with h5py.File(fname, 'r') as f:
        assert int(f['metadata'].attrs['version']) >= 3, 'Expected v3+ format'
        # Sensor library: one entry per unique sensor used
        ss_grp = f['metadata']['scope_sensors']
        assert len(ss_grp) >= 1, 'Expected at least 1 sensor in library'
        assert sensor.id in ss_grp, f'Sensor id {sensor.id!r} not found in library'
        sg = ss_grp[sensor.id]
        assert float(sg.attrs['sensitivity']) == pytest.approx(10.0)
        assert sg.attrs['engineering_units'] == 'g'
        assert sg.attrs['name'] == 'Test Sensor'
        # Channel metadata references the sensor by id
        ch_meta = f['metadata']['channels']['0']
        assert ch_meta.attrs['scope_sensor_id'] == sensor.id

    fname.remove_p()


def test_load_data_restores_scope_sensor_configs():
    """load_data populates _loaded_channel_sensor_configs and _loaded_scope_sensors (v3)."""
    sensor = ScopeSensor(name='Load Test', engineering_units='in/s',
                         sensitivity=50.0)
    collector = DataCollector(sim_sensor, acq_settings)
    collector.set_scope_sensor(0, sensor)
    collector.collect_sample()
    collector.disconnect_sensor()

    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_sensor_load.h5'
    fname.remove_p()
    collector.save_data(fname)

    fresh = DataCollector(config=acq_settings)
    fresh.load_data(fname)

    # Per-channel sensor config (keyed to registry id)
    cfg = fresh._loaded_channel_sensor_configs
    assert 0 in cfg, 'Channel 0 missing from _loaded_channel_sensor_configs'
    assert cfg[0]['sensitivity'] == pytest.approx(50.0)
    assert cfg[0]['id'] == sensor.id
    assert cfg[0]['engineering_units'] == 'in/s'

    # Sensor library (for auto-adding to registry on GUI load)
    lib = fresh._loaded_scope_sensors
    assert sensor.id in lib, 'Sensor id missing from _loaded_scope_sensors'
    assert lib[sensor.id]['name'] == 'Load Test'

    fname.remove_p()


def test_notes_roundtrip():
    """Measurement notes survive save/load."""
    collector = DataCollector(sim_sensor, acq_settings)
    collector.notes = 'Motor bearing — drive end'
    collector.collect_sample()
    collector.disconnect_sensor()

    DATADIR.makedirs_p()
    fname = DATADIR / 'pytest_notes.h5'
    fname.remove_p()
    collector.save_data(fname)

    fresh = DataCollector(config=acq_settings)
    fresh.load_data(fname)
    assert fresh.notes == 'Motor bearing — drive end'

    fname.remove_p()


# ---------------------------------------------------------------------------
# Event-based frame delivery (no GUI callback registered)
# ---------------------------------------------------------------------------

def test_new_frame_event_set_on_stream():
    """Streaming sets new_frame_event without any GUI callback registered."""
    collector = DataCollector(sim_sensor, acq_settings)
    assert not collector.new_frame_event.is_set()

    collector.start_stream()
    # Wait for at least one frame
    got_frame = collector.new_frame_event.wait(timeout=acq_settings.acquisition_period * 3)
    collector.stop_stream()
    collector.disconnect_sensor()

    assert got_frame, 'new_frame_event was never set during streaming'
    assert len(collector.data['frame_cache']) >= 1, 'frame_cache empty after streaming'


def test_new_frame_event_set_on_reprocess():
    """reprocess_last_block sets new_frame_event for the GUI poll loop."""
    collector = DataCollector(sim_sensor, acq_settings)
    collector.collect_sample()
    collector.disconnect_sensor()

    assert len(collector.data['frame_cache']) >= 1
    collector.new_frame_event.clear()

    collector.reprocess_last_block()
    assert collector.new_frame_event.is_set(), \
        'reprocess_last_block should set new_frame_event'


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
