"""ScopeSensor — describes an IEPE sensor connected to a PicoScope channel.

sensitivity is stored as millivolts per engineering-unit (mV/eu),
matching the industry-standard datasheet convention.
To convert raw mV data to engineering units: eu_data = mv_data / sensor.sensitivity

Example: PCB 352C33 datasheet says 10.2 mV/g → sensitivity = 10.2

engineering_units encodes the physical modality via the unit string:
  acceleration: 'g', 'mm/s2', 'in/s2', 'mil/s2'
  velocity:     'mm/s', 'in/s', 'mil/s'
  displacement: 'mm', 'in', 'mil'
  raw / no conversion: 'mV'

The display/integration target unit is a per-channel setting
(AcquisitionSettings.channel_target_units), not part of the sensor
definition — a sensor may be wired to different channels with different
targets.
"""

from dataclasses import dataclass, field
import uuid


# ---------------------------------------------------------------------------
# Field coercion helpers
# ---------------------------------------------------------------------------

# Anything not in here is a container or an arbitrary object and must not be
# silently str()'d into a field — that is how junk reaches the YAML writer.
_SCALARS = (str, int, float, bool)


def _scalar_str(d: dict, key: str, required: bool = False) -> str:
    """Return d[key] coerced to str. Rejects non-scalars."""
    if key not in d or d[key] is None:
        if required:
            raise KeyError(key)
        return ''
    v = d[key]
    if not isinstance(v, _SCALARS):
        raise TypeError(f'{key!r} must be a scalar, got {type(v).__name__}: {v!r}')
    return str(v)


def _scalar_float(d: dict, key: str) -> float:
    """Return d[key] coerced to float. Rejects non-scalars and bad numbers."""
    if key not in d or d[key] is None:
        raise KeyError(key)
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, _SCALARS):
        raise TypeError(f'{key!r} must be a number, got {type(v).__name__}: {v!r}')
    return float(v)   # raises ValueError on a non-numeric string


@dataclass
class ScopeSensor:
    name: str
    engineering_units: str          # source EU from datasheet (e.g. 'g', 'mm/s')
    sensitivity: float              # mV / eu  (datasheet value, e.g. 10.2 mV/g)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notes: str = ''

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'engineering_units': self.engineering_units,
            'sensitivity': self.sensitivity,
            'id': self.id,
            'notes': self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ScopeSensor':
        """Build a ScopeSensor from a plain dict, coercing and validating fields.

        Every value is coerced to its declared type and non-scalars are
        rejected. Sensor definitions arrive from YAML written by other
        installs and from HDF5 attributes in measurement files shared between
        machines, so the values are not trustworthy. An uncoerced dict/list
        reaching a field used to survive all the way to the YAML writer, which
        then emitted a `!!python/object/apply:` tag that no reader could parse
        — corrupting the whole sensor library.
        """
        if not isinstance(d, dict):
            raise TypeError(f'sensor entry must be a mapping, got {type(d).__name__}')
        return cls(
            # Coercion retained from the X-01 hardening: sensor definitions
            # arrive from other installs' YAML and from HDF5 attributes in
            # shared measurement files, so the values are not trustworthy.
            name=_scalar_str(d, 'name', required=True),
            engineering_units=_scalar_str(d, 'engineering_units', required=True),
            sensitivity=_scalar_float(d, 'sensitivity'),
            id=_scalar_str(d, 'id') or str(uuid.uuid4()),
            notes=_scalar_str(d, 'notes'),
            # 'modality' and 'target_unit' keys in old YAML files are silently
            # ignored. target_unit moved to AcquisitionSettings.channel_target_units,
            # since one sensor may be wired to channels wanting different targets.
        )
