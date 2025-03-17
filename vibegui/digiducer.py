import numpy as np
import pandas as pd
import sounddevice as sd
import matplotlib.pyplot as plt
from datetime import datetime as dt
from sys import exit, platform
import time
import queue

from vibetools import GenerateVibrationData

class NoDevicesFound(Exception):
    pass

class FormatError(Exception):
    pass

eu_scale = np.array([100,100]) # if device returns volts, use this mV/g scale, set to 0 to return raw voltage
eu_units = ['g', 'g']

def FindDigiducerDevice():
    # The Modal Shop model number substrings
    models=["485B", "333D", "633A", "SDC0"]
    
    # Windows has a variety of API's to access audio
    # many of them manipulate the data and do not support setting actual
    # requested sample rates.  Windows Kernal Streaming allows direct control
    # so find devices using that API
    if platform == "win32":         # Windows...
        hapis=sd.query_hostapis()
        api_num=0
        for api in hapis:
            if api['name'] == "Windows WDM-KS":
                break
            api_num += 1
    else:
        # Not Windows - other platforms don't have the issue with the API
        api_num=0
    # Return all available audio inputs
    devices = sd.query_devices()
    device_info = []   # Array to store info about each compa
    dev_num=0
    # Iterate through available devices and find ones named with a TMS model.
    # Note this returns multiple instances of the same device, because there
    # are different audio API's available.
    for device in devices:
        if (device['hostapi'] == api_num):
            name = device['name']
            match = next((x for x in models if x in name), False)
            if match != False:
                loc = name.find(match)
                model = name[loc:loc+6] # Extract the model
                fmt = name[loc+7:loc+8] # Extract the format of data
                serialnum = name[loc+8:loc+14]  # Extract the serial number
                # parse devices that are voltage
                if fmt == "2" or fmt == '3':
                    form = 1    # Voltage
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+21]), int(name[loc+21:loc+28])]
                    if fmt == "3":  # 50mV reference for format 3
                        sens[0] *= 1/50e-3 # Convert to 1V reference
                        sens[1] *= 1/50e-3

                    units = ['v', 'v']
                    scale = np.array([8388608.0/sens[0], 8388608.0/sens[1]], dtype='float32') # scale to volts

                    for ch in range(len(scale)):
                        if eu_sen[ch] != 0.0:
                            scale[ch] *= 1.0 / (eu_sen[ch] / 1000.0)
                            units[ch] = eu_units[ch]

                    date = dt.strptime(name[loc+28:loc+34], '%y%m%d') # Isolate the calibration date from the fullname string

                elif fmt == "1":
                    # These devices are acceleration
                    form = 0
                    # Extract the sensitivity
                    sens = [int(name[loc+14:loc+19]), int(name[loc+19:loc+24])]
                    scale = np.array([855400.0/sens[0], 855400.0/sens[1]], dtype='float32') # scale to g's
                    units = ['g', 'g']
                    date = dt.strptime(name[loc+24:loc+30], '%y%m%d') # Isolate the calibration date from the fullname string
                else:
                      raise FormatError("Expecting 1, 2, or 3 format")

                 # Add new device to array   
                device_info.append({"device":      dev_num,
                                 "model":       model,
                                 "serial":      serialnum,
                                 "date":        date,
                                 "format":      form,
                                 "sensitivity": sens,
                                 "scale":       scale,
                                 "units":       units,
                                 })
        dev_num += 1
    if len(device_info) == 0:
        raise NoDevicesFound("No compatible devices found")
    return device_info

#class VibrationDevice: requirements
    # Detect and connect to device, or setup simulated device.
    # Detect and configure units
    # Start stream
    # Stop sensor stream

class VibrationDevice:

    SAMPLERATES = [8_000, 11_050, 16_000, 22_100, 32_000, 44_100, 48_000]

    def __init__(self, blocksize, samplerate, channel=0, simulate=None):
        # Acquisition config
        self.blocksize:int = blocksize
        self.samplerate:int = samplerate
        self.channel:int = channel

        # Stream attributes
        self.info = None
        self.stream = None
        self.simulate = simulate
        self.running = False
        self.queue = queue.Queue()

        # Persistent Data
        self.last_sample = None
        self.trend = None

        # Connect device
        self.find_device()
    @property
    def sampleperiod(self):
        return 1 / self.samplerate
    @property
    def acquisitionperiod(self):
        return self.blocksize/self.samplerate
    @property
    def scale(self):
        return self.info['scale']
    @property
    def units(self):
        return self.info['units']

    @property
    def time_axis(self):
        return np.arange(0, self.blocksize * self.sampleperiod, self.sampleperiod)
    
    @property
    def freq_axis(self):
        return np.fft.fftfreq(self.blocksize, self.sampleperiod)[:self.blocksize//2]

    def find_device(self):
        if self.simulate:
            self.info = {
                "device": "Simulated Digiducer",
                "model": "Simulated Model",
                "serial_number": "-1",
                "date": dt.now(),
                "format": 0,
                "sensitivity": [100, 100],
                "scale": np.array([1.0, 1.0]),
                "units": ['g', 'g'],
            }
            
        else:
            info = FindDigiducerDevice()
            self.info = info[0]  # Use the first device found

    def init_trend(self) -> None:
        if self.last_sample:
            sample = self.last_sample
        else:
            sample = self.collect_sample()

        # create empty DF with correct headers
        self.trend = self.sample_to_trend(self.last_sample)[0:-1]

    def sample_to_trend(self,sample):
        # create lineitems in dataframe TIME, RMS
        pass

    def collect_sample(self) -> dict:
        """Collects a single sample from the device."""

        self.last_sample = None
        self.start_stream()

        while True:
            sample = self.last_sample
            if sample: break

        self.stop_stream()

        return sample

    def start_stream(self):

        if self.simulate:
            import threading
            self.stream = threading.Thread(target=self._simulate_stream, daemon=True)
            self.stream.start()
            
        else:   
            self.stream = sd.InputStream(device=self.info['device'], 
                                         channels=2, 
                                         samplerate=self.samplerate, 
                                         dtype='float32', 
                                         blocksize=self.blocksize,
                                         callback=self.callback
                                         )
            self.stream.start()
            self.running = True

    def _generate_data(self):
        return GenerateVibrationData(self.blocksize, self.samplerate, 2)

    def _simulate_stream(self):
        self.running = True
        while self.running:
            data = self._generate_data()
            time.sleep(self.acquisitionperiod) # delay by sampling time
            self.callback(data, self.blocksize, time.time(), "OK")

    def stop_stream(self):
        self.running = False
        if self.simulate:
            self.stream.join()
        else:
            self.stream.stop()
            del self.queue
            self.queue = queue.Queue()

    def callback(self, data, frames, timestamp, status):
        self.last_sample = {'data': data[:,self.channel] * self.scale[self.channel],
                            'blocksize': frames,
                            'samplerate': self.samplerate,
                            'units': self.units,
                            'timestamp': timestamp,
                            'status': status}
        self.queue.put(self.last_sample)

        if isinstance(self.trend, pd.DataFrame):
            self.trend.append(self.sample_to_trend(sample), ignore_index=True)

    def get(self):
        return self.queue.get()

    def set_samplerate(self, samplerate:int):
        was_running = self.running
        if was_running:
            self.stop_stream()
        
        self.samplerate = samplerate

        if was_running:
            self.start_stream()

    def set_blocksize(self, blocksize:int):
        was_running = self.running
        if was_running:
            self.stop_stream()
        
        self.blocksize = blocksize

        if was_running:
            self.start_stream()

        
def run_simulation(domain='TIME'):
    channel = 0

    # binsize = 1 # hz
    # max_freq = 5000 # khz

    # blocksize = max_freq // binsize
    # samplerate = max_freq * 2

    blocksize = 1024
    samplerate = 8000

    plot_update_period = 0.01
    max_samples = 30
    vd = VibrationDevice(blocksize, samplerate, channel=channel, simulate=True)
    try:
        sample = vd.collect_sample()
        last_update_time = 0; #sample['time']
        sample_data = sample['data']

        ax_scale = [0,0,-1,1]
        match domain:
            case 'TIME':
                X = vd.time_axis
                yfun = lambda y: y
                ax_scale = [X[0], X[-1], -4, 4]
                xlab = 'Time, ms'
                ylab = 'Amplitude'
            case 'FREQ':
                X = vd.freq_axis
                yfun = lambda y: np.abs(np.fft.fft(y))[:vd.blocksize//2]
                ax_scale = [X[1], X[-1], 0, 100]
                xlab = 'Frequency, Hz'
                ylab = 'Amplitude'

        Y = yfun(sample_data)

        plt.ion()
        fig, ax = plt.subplots()
        plt.title("Digiducer Stream: " + vd.info['model'], fontsize=20)
        plt.xlabel(xlab)
        plt.ylabel(ylab)
        line, = plt.plot(X, Y)
        # ax.set_xlim(ax_scale[:2])
        # ax.set_ylim(ax_scale[2:])

        try:
            vd.start_stream()
            for _ in range(max_samples):
                if not plt.fignum_exists(fig.number):
                    print('Window closed!')
                    break

                sample = vd.get()

                data = sample['data']

                Y = yfun(data)
                # ax.set_ylim([max(min(Y), 1e-3), max(Y)])

                if sample['time'] >= last_update_time + plot_update_period:

                    line.set_ydata(Y)
                    fig.canvas.draw()
                    fig.canvas.flush_events()
                    print(sample['status'], sample['data'].shape)
                    last_update_time = sample['time']

        finally:
            vd.stop_stream()
            plt.close(fig)
    except Exception as e:
        print(e)
        exit(1)

def test_data_gen():

    blocksize = 2048
    samplerate = 8000

    vd = VibrationDevice(blocksize, samplerate, simulate=True)

    time_axis = np.arange(0, vd.blocksize*vd.sampleperiod, vd.sampleperiod)

    mkdata = lambda: vd.callback(vd._generate_data(), vd.blocksize, time.time(), "OK")

    mkdata()
    mkdata()

    sample1 = vd.get()
    sample2 = vd.get()

    data = sample2['data'][:,0]

    plt.plot(time_axis, data)
    plt.show()

    print('done')

if __name__ == "__main__":
    run_simulation('FREQ')