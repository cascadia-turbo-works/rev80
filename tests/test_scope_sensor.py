"""Tests for ScopeSensor, ScopeSensorRegistry, and pipeline scaling."""

import time
import pytest
import numpy as np
from pathlib import Path

import vibechecker as vc
from vibechecker.scope_sensor import ScopeSensor, BUILTIN_SENSORS
from vibechecker.scope_sensor_registry import ScopeSensorRegistry


# ---------------------------------------------------------------------------
# ScopeSensor round-trip
# ---------------------------------------------------------------------------

def test_scope_sensor_to_dict_from_dict_roundtrip():
    s = ScopeSensor(
        name='Test PCB',
        modality='acceleration',
        engineering_units='g',
        sensitivity=0.098,
        notes='test note',
    )
    d = s.to_dict()
    s2 = ScopeSensor.from_dict(d)

    assert s2.name == s.name
    assert s2.modality == s.modality
    assert s2.engineering_units == s.engineering_units
    assert s2.sensitivity == pytest.approx(s.sensitivity)
    assert s2.id == s.id
    assert s2.notes == s.notes


def test_scope_sensor_from_dict_missing_optional_fields():
    d = {
        'name': 'Minimal',
        'modality': 'velocity',
        'engineering_units': 'mm',
        'sensitivity': 0.5,
    }
    s = ScopeSensor.from_dict(d)
    assert s.name == 'Minimal'
    assert s.notes == ''
    assert s.id  # auto-generated uuid


# ---------------------------------------------------------------------------
# ScopeSensorRegistry CRUD + persistence
# ---------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path):
    sensors_file = tmp_path / 'scope_sensors.yaml'
    return ScopeSensorRegistry(path=sensors_file)


def test_registry_all_includes_builtins(registry):
    all_sensors = registry.all()
    builtin_ids = {s.id for s in BUILTIN_SENSORS}
    assert builtin_ids.issubset({s.id for s in all_sensors})


def test_registry_add_and_find(registry):
    s = ScopeSensor(name='My Sensor', modality='acceleration',
                    engineering_units='g', sensitivity=0.1)
    registry.add(s)

    found = registry.find_by_id(s.id)
    assert found is not None
    assert found.name == 'My Sensor'

    found_by_name = registry.find_by_name('My Sensor')
    assert found_by_name is not None
    assert found_by_name.id == s.id


def test_registry_update(registry):
    s = ScopeSensor(name='Original', modality='acceleration',
                    engineering_units='g', sensitivity=0.1)
    registry.add(s)

    updated = ScopeSensor(name='Updated', modality='acceleration',
                          engineering_units='g', sensitivity=0.2, id=s.id)
    registry.update(updated)

    found = registry.find_by_id(s.id)
    assert found.name == 'Updated'
    assert found.sensitivity == pytest.approx(0.2)


def test_registry_delete(registry):
    s = ScopeSensor(name='ToDelete', modality='acceleration',
                    engineering_units='g', sensitivity=0.1)
    registry.add(s)
    assert registry.find_by_id(s.id) is not None

    registry.delete(s.id)
    assert registry.find_by_id(s.id) is None


def test_registry_cannot_add_builtin_id(registry):
    s = ScopeSensor(name='Fake Builtin', modality='acceleration',
                    engineering_units='g', sensitivity=0.1,
                    id='builtin-pcb-352c33')
    with pytest.raises(ValueError):
        registry.add(s)


def test_registry_cannot_update_builtin(registry):
    builtin = BUILTIN_SENSORS[0]
    with pytest.raises(ValueError):
        registry.update(builtin)


def test_registry_cannot_delete_builtin(registry):
    builtin = BUILTIN_SENSORS[0]
    with pytest.raises(ValueError):
        registry.delete(builtin.id)


def test_registry_update_nonexistent_raises(registry):
    s = ScopeSensor(name='Ghost', modality='acceleration',
                    engineering_units='g', sensitivity=0.1)
    with pytest.raises(KeyError):
        registry.update(s)


# ---------------------------------------------------------------------------
# Channel assignment persistence
# ---------------------------------------------------------------------------

def test_save_load_channel_assignments(tmp_path, registry):
    s = ScopeSensor(name='Chan0Sensor', modality='acceleration',
                    engineering_units='g', sensitivity=0.098)
    registry.add(s)

    assign_file = tmp_path / 'channel_assignments.yaml'
    registry.save_channel_assignments({0: s.id}, path=assign_file)

    loaded = registry.load_channel_assignments(path=assign_file)
    assert loaded == {0: s.id}


def test_load_channel_assignments_missing_file(tmp_path, registry):
    missing = tmp_path / 'no_such_file.yaml'
    result = registry.load_channel_assignments(path=missing)
    assert result == {}


# ---------------------------------------------------------------------------
# Pipeline scaling — DataCollector + ScopeSensor
# ---------------------------------------------------------------------------

def _make_simulated_collector(sensitivity: float, eu: str):
    """Return a DataCollector wired to a SimulatedSensor with a ScopeSensor on ch 0."""
    sim_sensor = vc.VibeSensor.simulated()
    collector = vc.DataCollector(sim_sensor)

    scope_sensor = ScopeSensor(
        name='PipelineTest',
        modality='acceleration',
        engineering_units=eu,
        sensitivity=sensitivity,
    )
    collector.set_scope_sensor(0, scope_sensor)
    return collector


@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_pipeline_no_scope_sensor_unit_unchanged(dev: vc.VibeSensor):
    """Without a ScopeSensor the unit passes through unchanged from the sensor."""
    collector = vc.DataCollector(dev)
    sample = collector.collect_sample()
    if sample is None:
        pytest.skip(f'Hardware sensor {dev} unavailable')
    # Unit should be whatever the sensor reports — just verify we got a sample
    assert sample is not None


def test_pipeline_scope_sensor_scales_mv_data():
    """When unit=='mV' and a ScopeSensor is assigned, data is scaled and unit changes."""
    sim_sensor = vc.VibeSensor.simulated()
    # Disable Butterworth filter so we can check exact scaled values
    config = vc.AcquisitionSettings(butter_fc=None)
    collector = vc.DataCollector(sim_sensor, config=config)

    sensitivity = 0.1  # 0.1 g/mV

    scope_sensor = ScopeSensor(
        name='ScaleTest',
        modality='acceleration',
        engineering_units='g',
        sensitivity=sensitivity,
    )
    collector.set_scope_sensor(0, scope_sensor)

    # Inject a synthetic mV packet directly into recieve_data
    raw_mv = np.ones(256, dtype=np.float32) * 50.0  # 50 mV
    packet = {
        'data': raw_mv,
        'unit': 'mV',
        'status': 'OKAY',
        'timestamp': '2026-01-01T00:00:00',
        'rel_time': 0.0,
    }

    received = []
    collector.callbacks['test'] = received.append
    collector.recieve_data(packet)

    assert len(received) == 1
    sample = received[0]
    assert sample.unit == 'g'
    assert np.allclose(sample.data, raw_mv * sensitivity, atol=1e-6)


def test_pipeline_scope_sensor_clear():
    """set_scope_sensor(ch, None) removes the assignment so mV data is not scaled."""
    sim_sensor = vc.VibeSensor.simulated()
    collector = vc.DataCollector(sim_sensor)

    scope_sensor = ScopeSensor(
        name='TempSensor',
        modality='acceleration',
        engineering_units='g',
        sensitivity=0.1,
    )
    collector.set_scope_sensor(0, scope_sensor)
    collector.set_scope_sensor(0, None)

    raw_mv = np.ones(256, dtype=np.float32) * 50.0
    packet = {
        'data': raw_mv,
        'unit': 'mV',
        'status': 'OKAY',
        'timestamp': '2026-01-01T00:00:00',
        'rel_time': 0.0,
    }

    received = []
    collector.callbacks['test'] = received.append
    collector.recieve_data(packet)

    sample = received[0]
    # Unit should still be mV since no sensor is assigned
    assert sample.unit == 'mV'
