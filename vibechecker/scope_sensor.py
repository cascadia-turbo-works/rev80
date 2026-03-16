"""ScopeSensor — describes an IEPE sensor connected to a PicoScope channel.

sensitivity is stored as engineering-units per millivolt (eu/mV).
To convert raw mV data to engineering units: eu_data = mv_data * sensor.sensitivity

Example: PCB 352C33 datasheet says 10.2 mV/g → sensitivity = 1/10.2 ≈ 0.098 g/mV
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
    sensitivity: float          # eu / mV  (= 1 / datasheet_mV_per_eu)
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


# Common IEPE accelerometers — always available, cannot be edited or deleted.
BUILTIN_SENSORS: list[ScopeSensor] = [
    ScopeSensor(
        name='PCB 352C33',
        modality='acceleration',
        engineering_units='g',
        sensitivity=1.0 / 10.2,    # 10.2 mV/g
        id='builtin-pcb-352c33',
        notes='PCB Piezotronics 352C33, 10.2 mV/g IEPE accelerometer',
    ),
    ScopeSensor(
        name='Wilcoxon 786A',
        modality='acceleration',
        engineering_units='g',
        sensitivity=1.0 / 100.0,   # 100 mV/g
        id='builtin-wilcoxon-786a',
        notes='Wilcoxon Research 786A, 100 mV/g IEPE accelerometer',
    ),
    ScopeSensor(
        name='Generic IEPE 10 mV/g',
        modality='acceleration',
        engineering_units='g',
        sensitivity=1.0 / 10.0,    # 10 mV/g
        id='builtin-generic-iepe-10mvg',
        notes='Generic IEPE accelerometer, 10 mV/g',
    ),
]
