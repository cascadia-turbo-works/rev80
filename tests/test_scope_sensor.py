"""Tests for ScopeSensor, ScopeSensorRegistry, and pipeline scaling."""

import pytest
import numpy as np

import rev80 as vc
from rev80.scope_sensor import ScopeSensor
from rev80.scope_sensor_registry import ScopeSensorRegistry


# ---------------------------------------------------------------------------
# ScopeSensor round-trip
# ---------------------------------------------------------------------------

def test_scope_sensor_to_dict_from_dict_roundtrip():
    s = ScopeSensor(
        name='Test PCB',
        engineering_units='g',
        sensitivity=0.098,
        target_unit='mm/s',
        notes='test note',
    )
    d = s.to_dict()
    s2 = ScopeSensor.from_dict(d)

    assert s2.name == s.name
    assert s2.engineering_units == s.engineering_units
    assert s2.sensitivity == pytest.approx(s.sensitivity)
    assert s2.target_unit == s.target_unit
    assert s2.id == s.id
    assert s2.notes == s.notes


def test_scope_sensor_effective_target_unit():
    s_with_target = ScopeSensor(name='A', engineering_units='g',
                                sensitivity=10.0, target_unit='mm/s')
    assert s_with_target.effective_target_unit() == 'mm/s'

    s_no_target = ScopeSensor(name='B', engineering_units='g', sensitivity=10.0)
    assert s_no_target.effective_target_unit() == 'g'


def test_scope_sensor_from_dict_missing_optional_fields():
    d = {
        'name': 'Minimal',
        'engineering_units': 'mm/s',
        'sensitivity': 0.5,
    }
    s = ScopeSensor.from_dict(d)
    assert s.name == 'Minimal'
    assert s.notes == ''
    assert s.target_unit == ''
    assert s.id  # auto-generated uuid


def test_scope_sensor_from_dict_ignores_legacy_modality():
    """from_dict must silently ignore an old 'modality' key."""
    d = {
        'name': 'LegacySensor',
        'modality': 'acceleration',   # old key — should be ignored
        'engineering_units': 'g',
        'sensitivity': 10.0,
    }
    s = ScopeSensor.from_dict(d)
    assert s.name == 'LegacySensor'
    assert not hasattr(s, 'modality')


# ---------------------------------------------------------------------------
# ScopeSensorRegistry CRUD + persistence
# ---------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path):
    sensors_file = tmp_path / 'scope_sensors.yaml'
    return ScopeSensorRegistry(path=sensors_file)


def test_registry_starts_empty(registry):
    assert registry.all() == []


def test_registry_add_and_find(registry):
    s = ScopeSensor(name='My Sensor', engineering_units='g', sensitivity=0.1)
    registry.add(s)

    found = registry.find_by_id(s.id)
    assert found is not None
    assert found.name == 'My Sensor'

    found_by_name = registry.find_by_name('My Sensor')
    assert found_by_name is not None
    assert found_by_name.id == s.id


def test_registry_update(registry):
    s = ScopeSensor(name='Original', engineering_units='g', sensitivity=0.1)
    registry.add(s)

    updated = ScopeSensor(name='Updated', engineering_units='g',
                          sensitivity=0.2, id=s.id)
    registry.update(updated)

    found = registry.find_by_id(s.id)
    assert found.name == 'Updated'
    assert found.sensitivity == pytest.approx(0.2)


def test_registry_delete(registry):
    s = ScopeSensor(name='ToDelete', engineering_units='g', sensitivity=0.1)
    registry.add(s)
    assert registry.find_by_id(s.id) is not None

    registry.delete(s.id)
    assert registry.find_by_id(s.id) is None


def test_registry_update_nonexistent_raises(registry):
    s = ScopeSensor(name='Ghost', engineering_units='g', sensitivity=0.1)
    with pytest.raises(KeyError):
        registry.update(s)


# ---------------------------------------------------------------------------
# Pipeline scaling — DataCollector + ScopeSensor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('dev', [vc.VibeSensor.simulated()])
def test_pipeline_no_scope_sensor_unit_unchanged(dev: vc.VibeSensor):
    """Without a ScopeSensor the unit passes through unchanged from the sensor."""
    collector = vc.DataCollector(dev)
    result = collector.collect_sample()
    if not result:
        pytest.skip(f'Hardware sensor {dev} unavailable')
    assert isinstance(result, dict)
    assert len(result) > 0


def test_pipeline_scope_sensor_scales_mv_data():
    """When unit=='mV' and a ScopeSensor is assigned, data is scaled and unit changes.

    Sensitivity is in mV/eu (industry standard): eu = mV / sensitivity.
    """
    sim_sensor = vc.VibeSensor.simulated()
    # Disable Butterworth filter so we can check exact scaled values
    config = vc.AcquisitionSettings(highpass_enabled=False)
    collector = vc.DataCollector(sim_sensor, config=config)

    sensitivity = 10.0  # 10 mV/g (datasheet value)

    scope_sensor = ScopeSensor(
        name='ScaleTest',
        engineering_units='g',
        sensitivity=sensitivity,
    )
    collector.set_scope_sensor(0, scope_sensor)

    # Inject a synthetic mV packet directly into receive_data
    raw_mv = np.ones(256, dtype=np.float32) * 50.0  # 50 mV
    packet = {
        'data': raw_mv,
        'unit': 'mV',
        'channels': [0],
        'status': 'OKAY',
        'timestamp': '2026-01-01T00:00:00',
        'rel_time': 0.0,
    }

    collector.receive_data(packet)

    frame = collector.data['frame_cache'][-1]
    sample = frame[0]
    # Raw storage is always mV
    assert sample.unit == 'mV'
    assert np.allclose(sample.data, raw_mv, atol=1e-6)

    # process_sample applies mV→EU conversion: 50 mV / 10 mV/g = 5 g
    collector.config.channel_target_units[0] = 'g'
    result = collector.process_sample(0, sample)
    assert result is not None
    assert result.unit == 'g'


def test_pipeline_scope_sensor_clear():
    """set_scope_sensor(ch, None) removes the assignment so mV data is not scaled."""
    sim_sensor = vc.VibeSensor.simulated()
    collector = vc.DataCollector(sim_sensor)

    scope_sensor = ScopeSensor(
        name='TempSensor',
        engineering_units='g',
        sensitivity=0.1,
    )
    collector.set_scope_sensor(0, scope_sensor)
    collector.set_scope_sensor(0, None)

    raw_mv = np.ones(256, dtype=np.float32) * 50.0
    packet = {
        'data': raw_mv,
        'unit': 'mV',
        'channels': [0],
        'status': 'OKAY',
        'timestamp': '2026-01-01T00:00:00',
        'rel_time': 0.0,
    }

    collector.receive_data(packet)

    frame = collector.data['frame_cache'][-1]
    sample = frame[0]
    # Unit should still be mV since no sensor is assigned
    assert sample.unit == 'mV'
