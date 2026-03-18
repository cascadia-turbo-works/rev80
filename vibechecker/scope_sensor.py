"""ScopeSensor — describes an IEPE sensor connected to a PicoScope channel.

sensitivity is stored as millivolts per engineering-unit (mV/eu),
matching the industry-standard datasheet convention.
To convert raw mV data to engineering units: eu_data = mv_data / sensor.sensitivity

Example: PCB 352C33 datasheet says 10.2 mV/g → sensitivity = 10.2
"""

from dataclasses import dataclass, field
from typing import Literal
import uuid

Modality = Literal['acceleration', 'velocity', 'displacement']
EngineeringUnit = Literal['g', 'mm', 'in']


@dataclass
class ScopeSensor:
    name: str
    modality: Modality
    engineering_units: EngineeringUnit
    sensitivity: float          # mV / eu  (datasheet value, e.g. 10.2 mV/g)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notes: str = ''

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'modality': self.modality,
            'engineering_units': self.engineering_units,
            'sensitivity': self.sensitivity,
            'id': self.id,
            'notes': self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ScopeSensor':
        return cls(
            name=d['name'],
            modality=d['modality'],
            engineering_units=d['engineering_units'],
            sensitivity=float(d['sensitivity']),
            id=d.get('id', str(uuid.uuid4())),
            notes=d.get('notes', ''),
        )
