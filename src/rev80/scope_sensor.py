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
        return cls(
            name=d['name'],
            engineering_units=d['engineering_units'],
            sensitivity=float(d['sensitivity']),
            id=d.get('id', str(uuid.uuid4())),
            notes=d.get('notes', ''),
            # 'modality' and 'target_unit' keys in old YAML files are silently ignored
        )
