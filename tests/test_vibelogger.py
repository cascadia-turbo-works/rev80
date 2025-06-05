import pytest
import time
from vibegui.vibelogger import VibeLogger, VibeSensor, VibeSample, AcquisitionSettings, SAMPLERATES

@pytest.mark.parametrize('dev', VibeSensor.find())
def test_stream_cycle(dev):
    vibr = VibeLogger(dev)
    vibr.start_data_queue()
    
    for i in range(10):
        vibr.start_stream()
        time.sleep(5)
        vibr.stop_stream()
        time.sleep(1)

    vibr.disconnect_sensor()
    
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', VibeSensor.find())
def test_sample_capture(dev):
    vibr = VibeLogger(dev)

    samples = []
    N = 5
    for _ in range(N):
        sample = vibr.collect_sample()
        assert isinstance(sample, VibeSample), 'invalid sample'
        samples.append(sample)
        time.sleep(0.5)

    vibr.disconnect_sensor()
    
    assert len(samples) == N, f"Expected {N} samples to be captured."
    assert vibr.stream is None, "Stream should be properly closed after test."

@pytest.mark.parametrize('dev', VibeSensor.find())
def test_stream(dev):
    import matplotlib.pyplot as plt

    plot_update_period = 0.01
    max_samples = 30

    vibr = VibeLogger(dev)
    # vibr.update_settings()

    try:
        sample = vibr.collect_sample()
        last_update_time = sample['timestamp']

        plt.ion()
        fig, ax = plt.subplots(2,1)

        plt.title("Digiducer Stream: " + vibr.sensor.model_name, fontsize=20)
        ax[0].xlabel('Time, ms')
        ax[0].ylabel('Acceleration, mm/s^2')
        ax[1].xlabel('Frequency, Hz')
        ax[1].ylabel('Velocity, mm/s/hz')
        
        time_plot, = ax[0].plot(sample.time, sample.acc_mmps2)
        freq_plot, = ax[1].plot(sample.freq, sample.vel_f)

        vibr.start_data_queue()
        vibr.start_stream()
        for _ in range(max_samples):
            if not plt.fignum_exists(fig.number):
                print('Window closed!')
                break

            sample = vibr.get_data_queue()

            if sample.timestamp >= last_update_time + plot_update_period:
                time_plot.set_data(sample.time, sample.acc_mmps2)
                freq_plot.set_data(sample.freq, sample.vel_f)
                
                fig.canvas.draw()
                fig.canvas.flush_events()
                print(sample.status)
                last_update_time = sample.timestamp
    
    finally:
        vibr.stop_stream()
        vibr.disconnect_sensor()
        plt.close(fig)
        del vibr

@pytest.mark.parametrize('dev', VibeSensor.find())
def test_save(dev):
    settings = AcquisitionSettings(1024, SAMPLERATES[4], 0)

    vl = VibeLogger(dev,settings)

    samp = vl.collect_sample()

    vl.disconnect_sensor()

    vl.save_data()

    time.sleep(0.5)

    vl.load_data()

    print(samp)
   
if __name__ == "__main__":
    pytest.main()
