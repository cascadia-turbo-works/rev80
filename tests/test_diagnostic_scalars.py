"""Crest factor and kurtosis on the result (audit capability gap).

Two scalars, computed on data the pipeline already holds, that RMS cannot see.
A bearing defect raises crest factor early and then lowers it again as the
defect spalls and the signal becomes more random; kurtosis above ~4 flags the
impulsiveness that a broadband overall averages away entirely. The audit called
their absence "disproportionate to their cost".

Validated against the physically realistic generator in test_bearing_oracle.py,
because ten pure cosines cannot falsify either of them.
"""

import numpy as np
import pytest
import scipy.stats

import rev80 as vc
from rev80 import simulation as sim

from test_measurement_validity import make_collector, make_sample, tone


def oracle_cfg():
    c = vc.AcquisitionSettings()
    c.maxfreq = 10000.0
    c.binsize = 2.0
    return c


# ===========================================================================
# Definition
# ===========================================================================

def test_pure_sine_has_the_textbook_crest_factor():
    """A sine's crest factor is sqrt(2); anything else means a scaling error."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, tone(dc, 217.3, amp=1.0)))
    assert r.crest_factor == pytest.approx(np.sqrt(2), rel=0.02)


def test_pure_sine_has_the_textbook_kurtosis():
    """A sine's kurtosis is 1.5 (non-Fisher). Gaussian is 3."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, tone(dc, 217.3, amp=1.0)))
    assert r.kurtosis == pytest.approx(1.5, rel=0.05)


def test_gaussian_noise_has_kurtosis_three():
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    rng = np.random.default_rng(3)
    data = rng.standard_normal(dc.config.blocksize)
    r = dc.process_sample(0, make_sample(dc, data))
    assert r.kurtosis == pytest.approx(3.0, abs=0.35)


@pytest.mark.parametrize('amp', [0.05, 1.0, 250.0])
def test_both_scalars_are_amplitude_invariant(amp):
    """Dimensionless by definition -- they must not move with signal level,
    sensor sensitivity or display unit."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, tone(dc, 217.3, amp=amp)))
    assert r.crest_factor == pytest.approx(np.sqrt(2), rel=0.02)
    assert r.kurtosis == pytest.approx(1.5, rel=0.05)


def test_scalars_are_invariant_to_sensor_sensitivity():
    a = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000,
                       binsize=2.0, sensitivity=1.0)
    b = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000,
                       binsize=2.0, sensitivity=100.0)
    data = tone(a, 217.3, amp=1.0)
    ra = a.process_sample(0, make_sample(a, data))
    rb = b.process_sample(0, make_sample(b, data))
    assert ra.crest_factor == pytest.approx(rb.crest_factor, rel=1e-9)
    assert ra.kurtosis == pytest.approx(rb.kurtosis, rel=1e-9)


# ===========================================================================
# They see what the overall cannot
# ===========================================================================

def test_scalars_separate_a_bearing_defect_the_overall_hides():
    """The whole point: an overall that barely moves while kurtosis doubles.

    Severity is scaled so the defect carries the same RMS as the shaft signal,
    so the broadband overall changes only modestly -- which is exactly the
    situation where an RMS-only instrument misses a developing fault.
    """
    cfg = oracle_cfg()
    for seed in range(6):
        healthy = sim.GenerateBearingVibration(cfg, severity=0.0, seed=seed)
        faulted = sim.GenerateBearingVibration(cfg, severity=1.0, seed=seed)

        dc = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                            maxfreq=10000, binsize=2.0)
        rh = dc.process_sample(0, make_sample(dc, healthy))
        dc2 = make_collector(eu='mm/s2', target_unit='mm/s2', amp_mode='RMS',
                             maxfreq=10000, binsize=2.0)
        rf = dc2.process_sample(0, make_sample(dc2, faulted))

        assert rf.kurtosis > rh.kurtosis + 1.0, (
            f'seed {seed}: kurtosis {rh.kurtosis:.2f} -> {rf.kurtosis:.2f}')
        assert rf.crest_factor > rh.crest_factor, (
            f'seed {seed}: crest {rh.crest_factor:.2f} -> {rf.crest_factor:.2f}')


def test_scalars_track_severity_monotonically():
    cfg = oracle_cfg()
    for seed in range(4):
        ks, cs = [], []
        for sev in (0.0, 0.5, 1.0):
            dc = make_collector(eu='mm/s2', target_unit='mm/s2',
                                maxfreq=10000, binsize=2.0)
            x = sim.GenerateBearingVibration(cfg, severity=sev, seed=seed)
            r = dc.process_sample(0, make_sample(dc, x))
            ks.append(r.kurtosis)
            cs.append(r.crest_factor)
        assert ks[0] < ks[1] < ks[2], f'seed {seed}: kurtosis {ks}'
        assert cs[0] < cs[1] < cs[2], f'seed {seed}: crest {cs}'


def test_scalars_are_computed_on_the_displayed_trace():
    """They must describe the same data the analyst is looking at.

    time_data is band-limited and, for integrated orders, is the flat middle of
    the Tukey overlap-save window. Computing the scalars on anything else --
    the raw block, or the Hann-tapered array the overall uses -- would make
    them describe a signal that is not on screen. The Hann case matters most:
    its taper is an amplitude envelope, so a peak-based statistic taken from it
    is simply wrong.
    """
    dc = make_collector(eu='mm/s2', target_unit='mm/s', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, tone(dc, 217.3, amp=1.0)))
    x = r.time_data
    assert r.crest_factor == pytest.approx(
        float(np.max(np.abs(x)) / np.sqrt(np.mean(x ** 2))), rel=1e-9)
    assert r.kurtosis == pytest.approx(
        float(scipy.stats.kurtosis(x, fisher=False)), rel=1e-9)


def test_degenerate_trace_does_not_raise():
    """An all-zero block divides by zero in both definitions."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, np.zeros(dc.config.blocksize)))
    assert r is not None
    assert np.isfinite(r.crest_factor)
    assert np.isfinite(r.kurtosis)


# ===========================================================================
# They are recorded, not just displayed
# ===========================================================================

def test_scalars_are_trended():
    """Watching kurtosis rise over weeks is the point; one reading is not."""
    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=10000, binsize=2.0)
    from types import SimpleNamespace
    dc.sensor = SimpleNamespace(name='fake')
    dc.stream = SimpleNamespace(active=True)

    cfg = oracle_cfg()
    for i, sev in enumerate((0.0, 0.5, 1.0)):
        x = sim.GenerateBearingVibration(cfg, severity=sev, seed=i)
        dc.receive_data({
            'status': 'OKAY', 'overflow_mask': 0, 'rel_time': float(i),
            'timestamp': __import__('datetime').datetime.now(), 'unit': ['mV'],
            'channels': [0], 'data': x[:, None],
            'samplerate': dc.config.samplerate, 'degraded': False,
        })
        dc.process_samples()

    td = dc.trend[0]
    assert len(td['kurtosis']) == 3
    assert len(td['crest_factor']) == 3
    assert td['kurtosis'][0] < td['kurtosis'][-1]


def test_monitor_writer_records_the_scalars():
    import json

    from rev80.monitor.writer import _compute_overall_peaks

    dc = make_collector(eu='mm/s2', target_unit='mm/s2', maxfreq=1000, binsize=2.0)
    r = dc.process_sample(0, make_sample(dc, tone(dc, 217.3, amp=1.0)))
    scalars_json = _compute_overall_peaks([r])[3]
    got = json.loads(scalars_json)['0']
    assert got['crest_factor'] == pytest.approx(np.sqrt(2), rel=0.02)
    assert got['kurtosis'] == pytest.approx(1.5, rel=0.05)
