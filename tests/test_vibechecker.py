import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc
import dearpygui as dpg
import pickle

DATADIR = Path('DEVDATA')
log = vc.get_logger('test')

samples = []
settings=vc.AcquisitionSettings()

def do_sample_calcs(sample:vc.VibeSample):
    time_vec, accel = sample.get_accel(settings)
    assert isinstance(accel, np.ndarray)

    df, peaks, rms = sample.fft(settings)
    
    assert time_vec.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    assert accel.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    # assert df.freq.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
    # assert df.psd_v.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'    

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
        assert isinstance(sample, vc.VibeSample), f'invalid sample {sample}'
        samples.append(sample)
        time.sleep(0.1)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_stream(dev: vc.VibeSensor):
    import matplotlib.pyplot as plt

    sens = vc.VibeSensor.find()
    vibr = vc.DataCollector(sensor=sens[-1], config=settings)
    
    sample:vc.VibeSample = vibr.collect_sample()
    plot_update_period = 0.1
    
    vis = vibr.visualize_init(sample)
    # plt.show()

    try:
        vibr.start_data_queue()
        vibr.start_stream()
        for _ in range(100):
            if not plt.fignum_exists(vis['fig'].number):
                print('Window closed!')
                break

            vibr.visualize_sample(vibr.get_data_queue(), vis)
            # plt.pause(plot_update_period)  # force GUI update
    
    finally:
        vibr.stop_stream()
        vibr.disconnect_sensor()
        plt.close(vis['fig'])

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_save(dev: vc.VibeSensor):

    filename = 'pytest_data_' + dt.now().strftime('%Y-%m-%d_%H-%M-%S') + vc.EXT
    file = DATADIR / filename

    dc = vc.DataCollector(dev,settings)
    vs = dc.collect_sample()
    data1 = vs.data.copy()
    dc.disconnect_sensor()

    time.sleep(1)

    vs.save(file)
    time.sleep(0.1)
    vs2 = vc.VibeSample.load(file)

    data2 = vs2.data.copy()

    assert vs2.status == vs.status, 'status differs'
    assert vs2.timestamp == vs.timestamp, 'timestamp differs'
    assert vs2.samplerate == vs.samplerate, 'samplerate differs'
    assert vs2.unit == vs.unit, 'unit differs'
    if not np.all(vs2.data == vs.data):
        diff = np.abs(vs2.data - vs.data)
        idiff = np.argwhere(diff != 0)
        raise AssertionError(f'Data differ after load. {idiff}, {diff[idiff]}')

    # Touch collector load method
    dc.load_data(file)

def test_gui_build():
    app = vc.GUI()
    app.initialize()
    time.sleep(1)
    app.cleanup()
   
if __name__ == "__main__":
    pytest.main()
