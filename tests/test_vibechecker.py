import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc
import dearpygui as dpg

DATADIR = 'DEVDATA'
log = vc.logger.get_logger('test')

samples = []
settings=vc.AcquisitionSettings()

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_stream_cycle(dev: vc.VibeSensor):
    vibr = vc.DataCollector(dev)
    vibr.start_data_queue()
    
    for _ in range(2):
        print('Starting stream ...', end='')
        vibr.start_stream()
        time.sleep(1)
        print('stopping')
        vibr.stop_stream()
        time.sleep(0.1)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_sample_capture(dev: vc.VibeSensor):
    vibr = vc.DataCollector(dev)

    N = 5
    for _ in range(N):
        print('Collecting Sample')
        sample = vibr.collect_sample()
        assert isinstance(sample, vc.VibeSample), f'invalid sample {sample}'
        samples.append(sample)
        time.sleep(0.5)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

def test_sample_calcs():
    for sample in samples:
        time_vec, accel = vc.sample_accel(sample, settings)
        assert isinstance(accel, np.ndarray)

        freq,psd_t = vc.sample_accel_spectrum(sample, settings)
        _,psd_f = vc.integrate_accel_spectrum(freq,psd_t)
        assert isinstance(psd_f, np.ndarray)

        assert time_vec.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
        assert accel.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
        assert freq.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'
        assert psd_f.flags['C_CONTIGUOUS'], 'Issue with T c-continuity'    

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_stream(dev: vc.VibeSensor):
    import matplotlib.pyplot as plt

    sens = vc.VibeSensor.find()
    vibr = vc.DataCollector(sensor=sens[-1], config=settings)
    
    sample:vc.VibeSample = vibr.collect_sample()
    last_update_time = sample.timestamp
    plot_update_period = 0.05
    
    vis = vibr.visualize_init(sample)
    # plt.show()

    try:
        vibr.start_stream()
        for _ in range(100):
            if not plt.fignum_exists(vis['fig'].number):
                print('Window closed!')
                break

            if vibr.sample.timestamp >= last_update_time + plot_update_period:
                vibr.visualize_sample(vibr.sample, vis)
                plt.pause(plot_update_period)  # force GUI update
                last_update_time = vibr.sample.timestamp
    
    finally:
        vibr.stop_stream()
        vibr.disconnect_sensor()
        plt.close(vis['fig'])

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_save(dev: vc.VibeSensor):

    filename = 'pytest_data_' + dt.now().strftime('%Y-%m-%d_%H-%M-%S') + '.pkl'
    file = Path.joinpath(DATADIR,filename)

    vl = vc.DataCollector(dev,settings)

    samp = vl.collect_sample()

    vl.disconnect_sensor()

    vl.save_data(file)

    time.sleep(0.5)

    vl.load_data(file)

    print(samp)

def test_gui_build():
    app = vc.GUI()
    app.initialize()
    time.sleep(1)
    app.cleanup()
   
if __name__ == "__main__":
    pytest.main()
