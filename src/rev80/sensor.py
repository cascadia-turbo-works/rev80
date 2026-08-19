import numpy as np
from dataclasses import dataclass
from datetime import datetime

import rev80

log = rev80.get_logger(__name__)

@dataclass
class VibeSensor:
    device_id: str
    model_name: str
    serial_number: str
    build_date: datetime
    format_id: int
    sensitivity: list
    scale: list
    unit: list
    num_channels: int = 1
    is_simulation: bool = False
    callback = None

    def __str__(self):
        return f'{self.model_name} (sn:{self.serial_number}, id:{self.device_id})'

    @classmethod
    def find(cls):
        """Return all connected hardware sensors. SimulatedSensor is excluded —
        use VibeSensor.simulated() directly for CI/testing."""
        return [cls(**dev) for dev in rev80.FindPicoScope()]

    @classmethod
    def simulated(cls):
        return cls(device_id = '-1',
                   model_name = 'Simulated Vibration Sensor',
                   serial_number = '0000',
                   build_date = datetime.now(),
                   format_id = 0,
                   sensitivity = [1,1],
                   scale = [1,1],
                   unit = ['mm','mm'],
                   is_simulation = True
                   )
    
    def connect(self, config: rev80.AcquisitionSettings, callback,
                siggen_config: dict | None = None):
        """Return a stream object with .start() / .stop() / .close() / .active."""
        self.callback = callback   # app callback — DataCollector.receive_data

        if self.is_simulation:
            return rev80.SimulatedSensor(config, sensor=self, callback=self._callback)

        from rev80.picoscope import PicoScopeStream
        return PicoScopeStream(config, callback=callback,
                               serial=self.serial_number, siggen_config=siggen_config)

    def _callback(self, raw_data: np.ndarray, frames: int, cb_time, cb_status):
        """SimulatedSensor callback — packages raw data into a dict and forwards
        to the registered app callback (DataCollector.receive_data)."""
        status = str(cb_status)
        try:
            rel_time = float(cb_time)
        except (TypeError, ValueError):
            rel_time = 0.0

        data = raw_data.copy() * self.scale

        # Derive channel list from data shape (columns = sequential channels).
        # Data is 2-D (frames, channels); SimulatedSensor matches this layout.
        channels = list(range(data.shape[1])) if data.ndim == 2 else [0]

        sample = {
            'status':    status,
            'rel_time':  rel_time,
            'timestamp': datetime.now(),
            'unit':      self.unit,
            'channels':  channels,
            'data':      data,
        }

        if self.callback:
            self.callback(sample)
    
