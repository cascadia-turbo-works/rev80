"""ScopeSensorRegistry — persistent YAML-backed registry of user IEPE sensors.

Storage:
  {config_dir}/scope_sensors.yaml  — global sensor library (all devices)

Per-device channel assignments and acquisition settings are managed by
rev80.config (devices/{serial}.yaml), not by this class.
"""

from pathlib import Path

import yaml

from rev80.scope_sensor import ScopeSensor
from rev80.config import config_dir, _atomic_yaml_write


def _sensors_file(path: Path | None) -> Path:
    return Path(path) if path is not None else config_dir() / 'scope_sensors.yaml'


class ScopeSensorRegistry:
    """Registry of IEPE sensor configurations backed by a YAML file."""

    def __init__(self, path: Path | None = None):
        self._path = _sensors_file(path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_user(self) -> list[ScopeSensor]:
        try:
            with open(self._path) as f:
                data = yaml.safe_load(f) or []
            return [ScopeSensor.from_dict(d) for d in data]
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def _save_user(self, sensors: list[ScopeSensor]) -> None:
        _atomic_yaml_write(self._path, [s.to_dict() for s in sensors])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all(self) -> list[ScopeSensor]:
        """Return all user-defined sensors."""
        return self._load_user()

    def names(self) -> list[str]:
        return [s.name for s in self.all()]

    def find_by_id(self, sensor_id: str) -> ScopeSensor | None:
        return next((s for s in self.all() if s.id == sensor_id), None)

    def find_by_name(self, name: str) -> ScopeSensor | None:
        return next((s for s in self.all() if s.name == name), None)

    def add(self, sensor: ScopeSensor) -> None:
        user = self._load_user()
        user.append(sensor)
        self._save_user(user)

    def update(self, sensor: ScopeSensor) -> None:
        user = self._load_user()
        idx = next((i for i, s in enumerate(user) if s.id == sensor.id), None)
        if idx is None:
            raise KeyError(f'Sensor {sensor.id!r} not found in user registry')
        user[idx] = sensor
        self._save_user(user)

    def delete(self, sensor_id: str) -> None:
        user = self._load_user()
        self._save_user([s for s in user if s.id != sensor_id])
