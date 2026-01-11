import threading
import numpy as np
from dataclasses import dataclass
from datetime import datetime

import sounddevice

import vibechecker

do_sounddevice_reset = threading.Event()

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
    is_simulation: bool = False
    callback = None

    def __str__(self):
        return f'{self.model_name} (sn:{self.serial_number}, id:{self.device_id})'

    @classmethod
    def find(cls):
        if do_sounddevice_reset.is_set() or True:
            # HACK: Reset sounddevice module before listing new devices.
            # This shouldn't be included in `FindDigiducers` function bc
            # it may break active streams if called a the wrong time.
            # This is necessary to acheieve hotplugging of sensors while app is open w/o restart
            sounddevice._terminate()
            sounddevice._initialize()
            # ENDHACK
            do_sounddevice_reset.clear()

        stat = [cls.simulated()] + [cls(**dev) for dev in vibechecker.FindDigiducer()]
        return stat

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
    
    def connect(self, config: vibechecker.AcquisitionSettings, callback):
        '''Return stream object'''

        self.callback = callback

        if self.is_simulation:
            # Simulate a device connection
            return vibechecker.SimulatedSensor(config, sensor=self, callback=self._callback)
        else:
            return sounddevice.InputStream(
                        device=self.device_id, 
                        channels=2, 
                        samplerate=config.samplerate, 
                        blocksize=config.blocksize,
                        callback=self._callback,
                        dtype='float32')
        
    def _callback(self, sd_data:np.ndarray, frames:int, sd_time, sd_status:str):
        
        # Parse C objects to python
        if isinstance(sd_status, sounddevice.CallbackFlags):
            status = vibechecker.parse_sd_status(sd_status)
        else:
            status = str(sd_status)
        if str(type(sd_time)) == "<class '_cffi_backend._CDataBase'>":
            rel_time = sd_time.currentTime
        else:
            rel_time = float(sd_time)

        # scale data
        data = sd_data.copy() * self.scale

        sample = {'status': status,
                  'rel_time': rel_time,
                  'timestamp': datetime.now(),
                  'unit': self.unit,
                  'data': data}
        
        if self.callback:
            self.callback(sample)
    
