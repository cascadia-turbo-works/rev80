"""ScopeSensorRegistry — persistent YAML-backed registry of user IEPE sensors.

Storage:
  {config_dir}/scope_sensors.yaml  — global sensor library (all devices)

Per-device channel assignments and acquisition settings are managed by
rev80.config (devices/picoscope-<model>-<serial>.yaml), not by this class.
"""

from pathlib import Path

import yaml

import rev80
from rev80.scope_sensor import ScopeSensor
from rev80.config import config_dir, _atomic_yaml_write

log = rev80.get_logger(__name__)


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
        """Parse the sensor library, skipping (and logging) unusable entries.

        add(), update() and delete() save what this returns over the file, so:
          - A bad entry is skipped and logged; the other entries are kept.
          - A bad file raises. A short list must not reach a save: a read
            failure must never become an overwrite.
        """
        try:
            with open(self._path) as f:
                raw = f.read()
        except FileNotFoundError:
            return []
        except OSError as exc:
            log.error('Sensor library %s could not be read (%s) — refusing to '
                      'continue rather than risk overwriting it', self._path, exc)
            raise

        try:
            data = yaml.safe_load(raw) or []
        except yaml.YAMLError as exc:
            log.error('Sensor library %s is not valid YAML (%s) — refusing to load, '
                      'so it will not be overwritten. Fix or move the file.',
                      self._path, exc)
            raise

        if not isinstance(data, list):
            log.error('Sensor library %s must contain a list, found %s — refusing to load.',
                      self._path, type(data).__name__)
            raise ValueError(f'{self._path} must contain a list of sensors')

        sensors: list[ScopeSensor] = []
        for i, entry in enumerate(data):
            try:
                sensors.append(ScopeSensor.from_dict(entry))
            except (KeyError, TypeError, ValueError) as exc:
                log.error('Sensor library %s: skipping unusable entry %d (%s): %r',
                          self._path, i, exc, entry)
        return sensors

    def _save_user(self, sensors: list[ScopeSensor]) -> None:
        _atomic_yaml_write(self._path, [s.to_dict() for s in sensors])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all(self) -> list[ScopeSensor]:
        """Return all user-defined sensors, or [] if the library is unreadable.

        Read-only callers (populating combo boxes, resolving a sensor for
        display) must not crash the app over a bad file, and _load_user() has
        already logged the reason. Mutating callers deliberately do NOT go
        through here — they call _load_user() directly so that a read failure
        propagates and can never be committed back over the file.
        """
        try:
            return self._load_user()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            log.warning('Sensor library unavailable (%s) — treating as empty for '
                        'display only; it will not be overwritten', exc)
            return []

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
