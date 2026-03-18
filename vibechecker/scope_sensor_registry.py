"""ScopeSensorRegistry — persistent YAML-backed registry of user IEPE sensors.

Storage layout:
  ~/.config/vibechecker/scope_sensors.yaml     — user-defined sensors
  ~/.config/vibechecker/channel_assignments.yaml — {channel_idx: sensor_id}
"""

import os
import tempfile
from pathlib import Path

import yaml

from vibechecker.scope_sensor import ScopeSensor

_DEFAULT_SENSORS_FILE   = Path.home() / '.config' / 'vibechecker' / 'scope_sensors.yaml'
_DEFAULT_CHANNELS_FILE  = Path.home() / '.config' / 'vibechecker' / 'channel_assignments.yaml'


def _atomic_yaml_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.yaml.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ScopeSensorRegistry:
    """Registry of IEPE sensor configurations backed by a YAML file."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else _DEFAULT_SENSORS_FILE

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

    # ------------------------------------------------------------------
    # Channel assignment persistence
    # ------------------------------------------------------------------

    def load_channel_assignments(self,
                                  path: Path | None = None) -> dict[int, str]:
        """Return {channel_idx: sensor_id} from saved assignments."""
        target = Path(path) if path is not None else _DEFAULT_CHANNELS_FILE
        try:
            with open(target) as f:
                raw = yaml.safe_load(f) or {}
            return {int(k): str(v) for k, v in raw.items()}
        except Exception:
            return {}

    def save_channel_assignments(self,
                                  assignments: dict[int, str],
                                  path: Path | None = None) -> None:
        target = Path(path) if path is not None else _DEFAULT_CHANNELS_FILE
        _atomic_yaml_write(target, {str(k): v for k, v in assignments.items()})
