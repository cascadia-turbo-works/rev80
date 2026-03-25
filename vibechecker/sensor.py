import numpy as np
from dataclasses import dataclass
from datetime import datetime

import vibechecker

log = vibechecker.get_logger(__name__)

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
        sensors = [cls.simulated()]
        sensors += [cls(**dev) for dev in vibechecker.FindPicoScope()]
        return sensors

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
    
    def connect(self, config: vibechecker.AcquisitionSettings, callback,
                siggen_config: dict | None = None):
        """Return a stream object with .start() / .stop() / .close() / .active."""
        self.callback = callback   # app callback — DataCollector.recieve_data

        if self.is_simulation:
            # SimulatedSensor fires _sd_callback (sounddevice-style args) which
            # packages the dict and forwards to self.callback.
            return vibechecker.SimulatedSensor(config, sensor=self, callback=self._sd_callback)

        from vibechecker.picoscope import PicoScopeStream
        return PicoScopeStream(config, callback=callback, siggen_config=siggen_config)

    def _sd_callback(self, sd_data: np.ndarray, frames: int, sd_time, sd_status: str):
        """sounddevice / SimulatedSensor callback — packages raw data into a dict
        and forwards to the registered app callback (DataCollector.recieve_data)."""
        status = str(sd_status)
        try:
            rel_time = float(sd_time)
        except (TypeError, ValueError):
            rel_time = 0.0

        data = sd_data.copy() * self.scale

        # Derive channel list from data shape (columns = sequential channels).
        # sounddevice always returns 2-D (frames, N); SimulatedSensor matches.
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
    
