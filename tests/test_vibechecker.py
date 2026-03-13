import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc

DATADIR = Path('DEVDATA')
log = vc.get_logger('test')

samples = []
settings=vc.AcquisitionSettings()

def do_sample_calcs(sample:vc.VibeSample):
    acc, rms = sample.get_accel(settings)

    fft, peaks = sample.fft(settings)
    
    assert acc.time.to_numpy().flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    assert acc.signal.to_numpy().flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    # assert fft.freq.to_numpy().flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    # assert fft.acc_spectrum.to_numpy().flags['C_CONTIGUOUS'], 'Issue with T c-continuity'    

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_stream_cycle(dev: vc.VibeSensor):
    vibr = vc.DataCollector(dev)
    vibr.callbacks['test'] = do_sample_calcs

    vibr.start_data_queue()
    
    for _ in range(2):
        vibr.start_stream()
        time.sleep(settings.acquisition_period*1.05)
        vibr.stop_stream()
        time.sleep(0.1)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_sample_capture(dev: vc.VibeSensor):
    vibr = vc.DataCollector(dev)

    N = 3
    for _ in range(N):
        print('Collecting Sample')
        sample = vibr.collect_sample()
        if sample is None:
            pytest.skip(f'Hardware sensor {dev} unavailable (no sample returned)')
        assert isinstance(sample, vc.VibeSample), f'invalid sample {sample}'
        samples.append(sample)
        time.sleep(0.1)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_save(dev: vc.VibeSensor):
    dc = vc.DataCollector(dev,settings)
    vs1 = dc.collect_sample()
    dc.disconnect_sensor()

    if vs1 is None:
        pytest.skip(f'Hardware sensor {dev} unavailable (no sample returned)')
    assert isinstance(vs1, vc.VibeSample)
    time.sleep(0.5)
    vs1.label = 'pytest_data'
    fname = vs1.save()

    time.sleep(0.5)
    vs2 = vc.VibeSample.load(fname)

    assert vs2.status == vs1.status, 'status differs'
    assert vs2.timestamp == vs1.timestamp, 'timestamp differs'
    assert vs2.samplerate == vs1.samplerate, 'samplerate differs'
    assert vs2.unit == vs1.unit, 'unit differs'
    if not np.all(vs2.data == vs1.data):
        diff = np.abs(vs2.data - vs1.data)
        idiff = np.argwhere(diff != 0)
        raise AssertionError(f'Data differ after load. {idiff}, {diff[idiff]}')

    # Touch collector load method
    dc.load_data(fname)

def test_gui_build():
    app = vc.GUI()
    app.initialize()
    time.sleep(1)
    app.cleanup()
   
if __name__ == "__main__":
    pytest.main()
