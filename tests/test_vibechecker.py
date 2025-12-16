import pytest
import time
from path import Path
from datetime import datetime as dt
import vibechecker as vc

DATADIR = 'DEVDATA'
log = vc.logger.get_logger('test')

samples = []

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

@pytest.mark.parametrize('dev', vc.VibeSensor.find())
def test_stream(dev: vc.VibeSensor):
    import matplotlib.pyplot as plt

    sens = vc.VibeSensor.find()
    settings=vc.AcquisitionSettings.from_freq_domain(1000, 1)
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

    settings = vc.AcquisitionSettings()

    vl = vc.DataCollector(dev,settings)

    samp = vl.collect_sample()

    vl.disconnect_sensor()

    vl.save_data(file)

    time.sleep(0.5)

    vl.load_data(file)

    print(samp)
   
if __name__ == "__main__":
    pytest.main()
