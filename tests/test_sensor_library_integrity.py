"""The sensor library must never be silently destroyed.

Root cause (three layers, one outcome):

  ScopeSensorRegistry._load_user swallowed ANY parse failure with
  `except Exception: return []`, and _save_user writes whatever _load_user
  returned straight back over the file. add() and delete() both follow exactly
  that load-then-save path, so a single unreadable entry erased every
  calibrated sensor definition the user had — with nothing logged.

Two independent triggers reached it:

  1. Documentation told users to hand-write `sensitivity_mv_per_eu:` in
     scope_sensors.yaml (see test_monitor_pretrigger_scaling.py). from_dict
     raised KeyError -> empty list -> next add/delete erased the file.

  2. config._atomic_yaml_write used yaml.dump with the UNSAFE default Dumper
     while every reader uses yaml.safe_load. Loading a colleague's .h5
     auto-registers its sensors into the global library with no prompt and no
     type coercion, so a non-scalar HDF5 attribute serialised as a
     `!!python/object/apply:` tag that safe_load then refused to parse.

No RCE exists today, but a writer that emits object tags means any future
switch to yaml.load becomes arbitrary code execution from a shared
measurement file.
"""

import numpy as np
import pytest
import yaml

from rev80.config import _atomic_yaml_write
from rev80.scope_sensor import ScopeSensor
from rev80.scope_sensor_registry import ScopeSensorRegistry


def _sensor(name='PCB 352C33', sid='sensor-1'):
    return ScopeSensor(name=name, engineering_units='g',
                       sensitivity=10.2, id=sid)


# ---------------------------------------------------------------------------
# Layer 1 — the writer must not emit anything the reader cannot parse
# ---------------------------------------------------------------------------

class TestAtomicYamlWrite:

    def test_round_trips_plain_data(self, tmp_path):
        path = tmp_path / 'ok.yaml'
        _atomic_yaml_write(path, [{'a': 1, 'b': 'two'}])
        assert yaml.safe_load(path.read_text()) == [{'a': 1, 'b': 'two'}]

    def test_rejects_non_serialisable_object(self, tmp_path):
        """safe_dump refuses arbitrary objects instead of emitting a python tag."""
        path = tmp_path / 'bad.yaml'
        with pytest.raises(yaml.YAMLError):
            _atomic_yaml_write(path, [{'sensitivity': np.float64(10.2), 'o': object()}])

    def test_failed_write_leaves_existing_file_untouched(self, tmp_path):
        """A refused write must not damage what is already on disk."""
        path = tmp_path / 'lib.yaml'
        _atomic_yaml_write(path, [{'name': 'good'}])
        before = path.read_text()

        with pytest.raises(yaml.YAMLError):
            _atomic_yaml_write(path, [{'name': object()}])

        assert path.read_text() == before

    def test_no_temp_files_left_behind(self, tmp_path):
        path = tmp_path / 'lib.yaml'
        with pytest.raises(yaml.YAMLError):
            _atomic_yaml_write(path, [{'name': object()}])
        assert list(tmp_path.glob('*.tmp')) == []

    def test_output_is_safe_loadable(self, tmp_path):
        """Whatever the writer produces, safe_load must be able to read it back."""
        path = tmp_path / 'lib.yaml'
        _atomic_yaml_write(path, [_sensor().to_dict()])
        restored = yaml.safe_load(path.read_text())
        assert ScopeSensor.from_dict(restored[0]).sensitivity == pytest.approx(10.2)


# ---------------------------------------------------------------------------
# Layer 2 — from_dict coerces and validates every field
# ---------------------------------------------------------------------------

class TestScopeSensorFromDict:

    def test_coerces_scalar_types_to_str(self):
        s = ScopeSensor.from_dict({
            'name': 12345, 'engineering_units': 'g',
            'sensitivity': '10.2', 'target_unit': 7, 'notes': 3.5,
        })
        assert s.name == '12345'
        assert s.target_unit == '7'
        assert s.notes == '3.5'
        assert isinstance(s.sensitivity, float)
        assert s.sensitivity == pytest.approx(10.2)

    @pytest.mark.parametrize('bad', [{'k': 'v'}, ['a', 'b'], ('a',), {1, 2}])
    def test_rejects_non_scalar_name(self, bad):
        with pytest.raises(TypeError):
            ScopeSensor.from_dict({'name': bad, 'engineering_units': 'g',
                                   'sensitivity': 10.2})

    @pytest.mark.parametrize('bad', [{'k': 'v'}, ['a'], object()])
    def test_rejects_non_scalar_sensitivity(self, bad):
        with pytest.raises(TypeError):
            ScopeSensor.from_dict({'name': 'x', 'engineering_units': 'g',
                                   'sensitivity': bad})

    def test_rejects_non_numeric_sensitivity(self):
        with pytest.raises(ValueError):
            ScopeSensor.from_dict({'name': 'x', 'engineering_units': 'g',
                                   'sensitivity': 'not-a-number'})

    def test_missing_required_key_raises_keyerror(self):
        with pytest.raises(KeyError):
            ScopeSensor.from_dict({'engineering_units': 'g', 'sensitivity': 1.0})

    def test_rejects_non_mapping(self):
        with pytest.raises(TypeError):
            ScopeSensor.from_dict(['not', 'a', 'dict'])

    def test_missing_id_gets_generated(self):
        s = ScopeSensor.from_dict({'name': 'x', 'engineering_units': 'g',
                                   'sensitivity': 1.0})
        assert s.id


# ---------------------------------------------------------------------------
# Layer 3 — a read failure must never become an overwrite
# ---------------------------------------------------------------------------

class TestRegistryResilience:

    def test_bad_entry_is_skipped_good_ones_survive(self, tmp_path, caplog):
        path = tmp_path / 'scope_sensors.yaml'
        path.write_text(yaml.safe_dump([
            _sensor('Good A', 'a').to_dict(),
            {'name': 'Broken', 'sensitivity': 1.0},          # no engineering_units
            _sensor('Good B', 'b').to_dict(),
        ]))
        reg = ScopeSensorRegistry(path)

        with caplog.at_level('ERROR'):
            sensors = reg.all()

        assert [s.name for s in sensors] == ['Good A', 'Good B']
        assert any('skipping unusable entry' in r.message for r in caplog.records)

    def test_add_after_bad_entry_preserves_good_entries(self, tmp_path):
        """The historical data-loss path: load-then-save must not drop the survivors."""
        path = tmp_path / 'scope_sensors.yaml'
        path.write_text(yaml.safe_dump([
            _sensor('Good A', 'a').to_dict(),
            {'name': 'Broken', 'sensitivity': 1.0},
        ]))
        reg = ScopeSensorRegistry(path)
        reg.add(_sensor('New', 'n'))

        names = {s.name for s in reg.all()}
        assert 'Good A' in names, 'a valid sensor was destroyed by an unrelated bad entry'
        assert 'New' in names

    def test_corrupt_file_raises_rather_than_loading_empty(self, tmp_path):
        path = tmp_path / 'scope_sensors.yaml'
        path.write_text('!!python/object/apply:os.system ["echo pwned"]\n')
        reg = ScopeSensorRegistry(path)
        with pytest.raises(yaml.YAMLError):
            reg._load_user()

    def test_corrupt_file_is_never_overwritten_by_add(self, tmp_path):
        """THE regression: add() on an unreadable library must not erase it."""
        path = tmp_path / 'scope_sensors.yaml'
        original = '!!python/object/apply:os.system ["echo pwned"]\n'
        path.write_text(original)
        reg = ScopeSensorRegistry(path)

        with pytest.raises(yaml.YAMLError):
            reg.add(_sensor())

        assert path.read_text() == original, 'unreadable sensor library was overwritten'

    def test_corrupt_file_is_never_overwritten_by_delete(self, tmp_path):
        path = tmp_path / 'scope_sensors.yaml'
        original = 'this: [is, not: a list\n'      # malformed YAML
        path.write_text(original)
        reg = ScopeSensorRegistry(path)

        with pytest.raises(yaml.YAMLError):
            reg.delete('sensor-1')

        assert path.read_text() == original

    def test_non_list_document_raises(self, tmp_path):
        path = tmp_path / 'scope_sensors.yaml'
        path.write_text(yaml.safe_dump({'not': 'a list'}))
        reg = ScopeSensorRegistry(path)
        with pytest.raises(ValueError):
            reg._load_user()

    def test_all_degrades_to_empty_without_raising(self, tmp_path, caplog):
        """Read-only display paths must not crash the app over a bad file."""
        path = tmp_path / 'scope_sensors.yaml'
        path.write_text('this: [is, not: a list\n')
        reg = ScopeSensorRegistry(path)

        with caplog.at_level('WARNING'):
            assert reg.all() == []
            assert reg.names() == []
            assert reg.find_by_id('anything') is None

    def test_missing_file_is_not_an_error(self, tmp_path):
        reg = ScopeSensorRegistry(tmp_path / 'does-not-exist.yaml')
        assert reg.all() == []

    def test_add_then_read_round_trip(self, tmp_path):
        path = tmp_path / 'scope_sensors.yaml'
        reg = ScopeSensorRegistry(path)
        reg.add(_sensor())
        (got,) = reg.all()
        assert got.name == 'PCB 352C33'
        assert got.sensitivity == pytest.approx(10.2)
