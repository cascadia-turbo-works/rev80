import threading
from dataclasses import dataclass
from datetime import datetime

import sounddevice

from vibechecker.digiducer import FindDigiducerDevice
from vibechecker.simulation import SimulatedSensor
from vibechecker.sample import AcquisitionSettings

do_sounddevice_reset = threading.Event()

@dataclass
class VibeSensor:
    device_id: str
    model_name: str
    serial_number: str
    build_date: datetime
    format_id: int
    sensitivity: list
    scale: list
    units: list
    is_simulation: bool = False

    def __str__(self):
        return f'{self.model_name} (sn:{self.serial_number}, id:{self.device_id})'

    @classmethod
    def find(cls):
        if do_sounddevice_reset.is_set():
            # HACK: Reset sounddevice module before listing new devices.
            # This shouldn't be included in `FindDigiducers` function bc
            # it may break active streams if called a the wrong time.
            # This is necessary to acheieve hotplugging of sensors while app is open w/o restart
            sounddevice._terminate()
            sounddevice._initialize()
            # ENDHACK
            do_sounddevice_reset.clear()

        stat = [cls.simulated()] + [cls(**dev) for dev in FindDigiducerDevice()]
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
                   units = ['mm','mm'],
                   is_simulation = True
                   )
    
    def connect(self, config: AcquisitionSettings, callback):
        '''Return stream object'''

        if self.is_simulation:
            # Simulate a device connection
            return SimulatedSensor(config, sensor=self, callback=callback)
        else:
            return sounddevice.InputStream(
                        device=self.device_id, 
                        channels=2, 
                        samplerate=config.samplerate, 
                        blocksize=config.blocksize,
                        callback=callback,
                        dtype='float32')
