"""ScopeSensor: an IEPE sensor connected to a PicoScope channel.

`sensitivity` is in mV per engineering unit, as on the datasheet (PCB 352C33:
10.2 mV/g -> 10.2). eu_data = mv_data / sensor.sensitivity.

`engineering_units` also gives the quantity: 'g', 'mm/s2', 'in/s2', 'mil/s2'
(acceleration); 'mm/s', 'in/s', 'mil/s' (velocity); 'mm', 'in', 'mil'
(displacement); 'mV' (no conversion).

The target unit and the amplitude mode are per-channel settings in
AcquisitionSettings, not sensor fields.
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

        Coerces each value to its declared type and rejects non-scalars. The
        input comes from other installs' YAML and from HDF5 attributes, so do
        not trust it: a dict or list in a field makes the YAML writer emit a
        tag that no reader can parse, and the sensor library is lost.
        """
        if not isinstance(d, dict):
            raise TypeError(f'sensor entry must be a mapping, got {type(d).__name__}')
        return cls(
            name=_scalar_str(d, 'name', required=True),
            engineering_units=_scalar_str(d, 'engineering_units', required=True),
            sensitivity=_scalar_float(d, 'sensitivity'),
            id=_scalar_str(d, 'id') or str(uuid.uuid4()),
            notes=_scalar_str(d, 'notes'),
            # 'modality' and 'target_unit' keys in a YAML file are ignored:
            # the target unit is AcquisitionSettings.channel_target_units.
        )
