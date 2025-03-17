import numpy as np

def GenerateVibrationData(blocksize:int, samplerate:int, channels:int=None):
    # Generate sample data representing rotating equipment with faulty bearing
    t = np.arange(0,blocksize/samplerate,1/samplerate) # time vector
    nnoise = lambda a: a * np.random.randn(blocksize) # normal noise
    signal = lambda a, f, p=0: a * np.sin(2*np.pi*f*t + p) # single frequency signal

    runningrate = 60 # hz, base freq
    running_phase = np.random.rand() * 2*np.pi
    bearing_multiple = 6.243
    bearing_severity = 0.8
    bearing_phase = np.random.rand() * 2*np.pi

    data = nnoise(0.8)

    # machine running rate and harmonics

    for k in range(1,11):
        data += signal(1/(.5*k), runningrate*k, running_phase)
    
    # Bearing defect and harmonics
    for k in range(1,11):
        data += signal(bearing_severity/(0.4*k), runningrate*bearing_multiple*k, bearing_phase)

    if channels:
        # convert to shape (blocksize, channels_count)
        data = np.matlib.repmat(data.reshape(blocksize,1), 1, channels)

    return data
    
def acceleration_to_velocity_fft(accel, Fs):
    """
    Convert time-domain acceleration signal to frequency-domain velocity using FFT.
    
    Parameters:
    - accel: numpy array of acceleration samples in g (gravity units)
    - Fs: Sampling frequency in Hz
    
    Returns:
    - freqs: Frequency axis (Hz)
    - accel_spectrum: One-sided acceleration amplitude spectrum (mm/s²)
    - vel_spectrum: One-sided velocity amplitude spectrum (mm/s)
    """
    N = len(accel)  # Number of samples
    dt = 1 / Fs     # Time step
    
    # Convert acceleration from g to mm/s²
    accel_mms2 = accel * 9.81 * 1000  # (9.81 m/s² * 1000) -> mm/s²

    # Compute FFT of acceleration
    A_f = np.fft.fft(accel_mms2) /N
    freqs = np.fft.fftfreq(N, dt)  # Frequency axis

    # Compute one-sided amplitude spectrum of acceleration
    accel_spectrum = 2 * np.abs(A_f[:N // 2])

    # Convert acceleration to velocity in the frequency domain
    V_f = np.zeros_like(A_f, dtype=np.complex128)
    nonzero_freqs = freqs != 0
    V_f[nonzero_freqs] = A_f[nonzero_freqs] / (1j * 2 * np.pi * freqs[nonzero_freqs])
    
    # Compute one-sided amplitude spectrum of velocity
    vel_spectrum = 2 * np.abs(V_f[:N // 2])  

    # Keep only positive frequencies
    freqs = freqs[:N // 2]
    
    return freqs, accel_mms2, vel_spectrum