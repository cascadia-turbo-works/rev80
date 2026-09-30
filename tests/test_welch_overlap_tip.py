"""The Welch Overlap tooltip says what the setting does.

Welch runs one segment per frame (nperseg == blocksize). Thus the overlap
has no segments to act on, and the spectrum does not change with it. The
old tooltip said that a higher overlap smooths the spectrum.
"""

from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import gui
from rev80.scope_sensor import ScopeSensor


def _spectrum(maxfreq: float, binsize: float, overlap: float) -> np.ndarray:
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    cfg.binsize = binsize
    cfg.welch_overlap = overlap
    dc = vc.DataCollector(None, cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='t', engineering_units='mm/s2',
                                       sensitivity=1.0))
    n = cfg.raw_blocksize
    rng = np.random.default_rng(3)
    t = np.arange(n) / cfg.raw_samplerate
    data = np.sin(2 * np.pi * 123.4 * t + 0.7) + 0.1 * rng.standard_normal(n)
    sample = vc.VibeSample(
        status='OKAY', _timestamp=datetime.now(), samplerate=cfg.raw_samplerate,
        unit='mV', overflow=False, degraded=False, data=data, rel_time=0.0)
    return np.asarray(dc.process_sample(0, sample).spectrum)


@pytest.mark.parametrize('maxfreq', [500.0, 2000.0, 10000.0])
@pytest.mark.parametrize('binsize', [1.0, 5.0])
def test_overlap_does_not_change_the_spectrum(maxfreq, binsize):
    a = _spectrum(maxfreq, binsize, 0.0)
    b = _spectrum(maxfreq, binsize, 0.9)
    np.testing.assert_array_equal(a, b)


def test_tooltip_does_not_claim_an_effect():
    tip = gui._WELCH_OVERLAP_TIP
    assert 'smooths the spectrum' not in tip
    assert 'no effect' in tip
    assert 'one segment' in tip
