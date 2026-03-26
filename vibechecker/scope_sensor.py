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

target_unit (optional) sets the display/integration target.  If empty,
the sensor data is displayed in its native engineering_units.
"""

from dataclasses import dataclass, field
import uuid


@dataclass
class ScopeSensor:
    name: str
    engineering_units: str          # source EU from datasheet (e.g. 'g', 'mm/s')
    sensitivity: float              # mV / eu  (datasheet value, e.g. 10.2 mV/g)
    target_unit: str = ''           # display/integration target; '' = same as engineering_units
    amplitude_mode: str = '0-P'    # 'RMS', '0-P', or 'P-P'
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notes: str = ''

    def effective_target_unit(self) -> str:
        """Return the display unit: target_unit if set, else engineering_units."""
        return self.target_unit if self.target_unit else self.engineering_units

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'engineering_units': self.engineering_units,
            'sensitivity': self.sensitivity,
            'target_unit': self.target_unit,
            'amplitude_mode': self.amplitude_mode,
            'id': self.id,
            'notes': self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ScopeSensor':
        return cls(
            name=d['name'],
            engineering_units=d['engineering_units'],
            sensitivity=float(d['sensitivity']),
            target_unit=d.get('target_unit', ''),
            amplitude_mode=d.get('amplitude_mode', '0-P'),
            id=d.get('id', str(uuid.uuid4())),
            notes=d.get('notes', ''),
            # 'modality' key in old YAML files is silently ignored
        )
