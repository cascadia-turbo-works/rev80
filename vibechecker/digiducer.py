from sys import platform
from datetime import datetime
import numpy as np
import sounddevice

from vibechecker.util import NoDevicesFound, FormatError

ENG_UNIT_SENSITIVITY = [100,100] # if device returns volts, use this mV/g scale, set to 0 to return raw voltage
ENG_UNITS = ['g', 'g']

def FindDigiducer():
    # The Modal Shop model number substrings
    models=["485B", "333D", "633A", "SDC0"]
    
    # Windows has a variety of API's to access audio
    # many of them manipulate the data and do not support setting actual
    # requested sample rates.  Windows Kernal Streaming allows direct control
    # so find devices using that API
    if platform == "win32":         # Windows...
        hapis=sounddevice.query_hostapis()
        api_num=0
        for api in hapis:
            if api['name'] == "Windows WDM-KS": # type: ignore
                break
            api_num += 1
    else:
        # Not Windows - other platforms don't have the issue with the API
        api_num=0
    # Return all available audio inputs
    devices = sounddevice.query_devices()
    device_info = []   # Array to store info about each compa
    dev_num=0
    # Iterate through available devices and find ones named with a TMS model.
    # Note this returns multiple instances of the same device, because there
    # are different audio API's available.
    for device in devices:
        if (device['hostapi'] == api_num): # type: ignore
            name = device['name'] # type: ignore
            match = next((x for x in models if x in name), False)
            if match != False:
                loc = name.find(match) # type: ignore
                model = name[loc:loc+6] # Extract the model
                fmt = name[loc+7:loc+8] # Extract the format of data
                serialnum = name[loc+8:loc+14]  # Extract the serial number
                # parse devices that are voltage
                if fmt == "2" or fmt == '3':
                    form = 1    # Voltage
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+21]), int(name[loc+21:loc+28])]
                    if fmt == "3":  # 50mV reference for format 3
                        sens[0] *= int(1/50e-3) # Convert to 1V reference
                        sens[1] *= int(1/50e-3)

                    units = ['v', 'v']
                    scale = np.array([8388608.0/sens[0], 8388608.0/sens[1]], dtype='float32') # scale to volts

                    for ch in range(len(scale)):
                        if ENG_UNIT_SENSITIVITY[ch] != 0.0:
                            scale[ch] *= 1.0 / (ENG_UNIT_SENSITIVITY[ch] / 1000.0)
                            units[ch] = ENG_UNITS[ch]

                    date = datetime.strptime(name[loc+28:loc+34], '%y%m%d') # Isolate the calibration date from the fullname string

                elif fmt == "1":
                    # These devices are acceleration
                    form = 0
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+19]), int(name[loc+19:loc+24])]
                    scale = np.array([855400.0/sens[0], 855400.0/sens[1]], dtype='float32') # scale to g's
                    units = ['g', 'g']
                    date = datetime.strptime(name[loc+24:loc+30], '%y%m%d') # Isolate the calibration date from the fullname string
                else:
                      raise FormatError("Expecting 1, 2, or 3 format")

                 # Add new device to array   
                device_info.append({"device_id":    dev_num,
                                 "model_name":      'Digiducer_'+model,
                                 "serial_number":   serialnum,
                                 "build_date":      date,
                                 "format_id":       form,
                                 "sensitivity":     sens,
                                 "scale":           scale,
                                 "units":           units
                                 })                  
        dev_num += 1
    # if len(device_info) == 0:
    #     raise NoDevicesFound("No compatible devices found")
    return device_info
