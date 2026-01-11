import pytest
import time
import numpy as np
from path import Path
from datetime import datetime as dt
import vibechecker as vc

devs = vc.VibeSensor.find()
simsensor = devs[0]


config = vc.AcquisitionSettings()
config.binsize = 2
config.maxfreq = 10000
config.units = 'mm'

dc = vc.DataCollector(simsensor, config)
stream: vc.SimulatedSensor | None = dc.stream \
        if isinstance(dc.stream,vc.SimulatedSensor) else None

tone_step = 500
tol = 1e-4
@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_vel(freq):
    if stream is None:
        return
    
    vel_ampl = 1.0
    
    stream.source = (vc.GenerateTone, 2*np.pi*freq*vel_ampl, freq, 0)
    sample = dc.collect_sample()
    acc, rms = sample.get_accel(config)
    fft, peak = sample.fft(config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.vel_0p - vel_ampl) < tol


@pytest.mark.parametrize('freq', range(tone_step,int(config.maxfreq), tone_step))
def test_tone_acc(freq):
    if stream is None:
        return
    
    acc_ampl = 1.0
    
    stream.source = (vc.GenerateTone, acc_ampl, freq, 0)
    sample = dc.collect_sample()
    acc, rms = sample.get_accel(config)
    fft, peak = sample.fft(config)

    row = fft.loc[np.abs(fft.freq-freq).argmin()]

    assert np.abs(row.acc_0p - acc_ampl) < tol