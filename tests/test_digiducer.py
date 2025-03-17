import pytest
import time
from vibegui import FindDigiducerDevice, VibrationDevice  # Replace 'your_module' with the actual module name


@pytest.mark.skipif(not FindDigiducerDevice())
def test_stream_cycle():
    device_id = FindDigiducerDevice()[0]
    manager = VibrationDevice(device=device_id)
    
    for i in range(10):
        manager.start_stream()
        time.sleep(5)
        manager.stop_stream()
        time.sleep(1)
    
    assert manager.stream is None, "Stream should be properly closed after test."

def test_sample_capture():
    device_id = FindDigiducerDevice()[0]
    manager = VibrationDevice(device=device_id)
    
    samples = []
    for _ in range(10):
        sample = manager.capture_sample()
        assert "data" in sample and "frames" in sample and "time" in sample and "status" in sample, "Sample dict missing required keys."
        samples.append(sample)
        time.sleep(0.5)
    
    assert len(samples) == 10, "Expected 10 samples to be captured."

if __name__ == "__main__":
    pytest.main()
