"""Role plumbing: what a tachometer channel must and must not reach.

Almost everything downstream of receive_data assumes a channel has a
ScopeSensor, an engineering unit, a spectrum and an overall. A tachometer has
none of those, and feeding a pulse train through the vibration path does not
raise -- it returns a plausible wrong answer. Measured on a 5% duty square
wave through the real process_sample: overall 1515 mV, crest 5.00, kurtosis
15.94 and 63 "peaks", which reads as a severely failing bearing.

These tests are the fence around that.
"""

from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80 import tach

RUNNING_RATE = 29.37       # off-grid on purpose
RPM = RUNNING_RATE * 60.0


class _LiveStream:
    """Minimal stand-in so DataCollector.is_streaming reads True.

    Trend accumulation only happens while streaming -- browsing a file must
    not append to it -- so a test that wants trend data has to look live.
    """
    active = True


def _collector(tach_ch=1, binsize=0.5, streaming=False):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = binsize
    cfg.enabled_channels = [0, tach_ch]
    cfg.channel_roles = {tach_ch: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    if streaming:
        dc.sensor = object()
        dc.stream = _LiveStream()
    return dc


def _feed(dc, seed=5, severity=1.0):
    """Push one coherent vibration+tach frame through receive_data."""
    cfg = dc.config
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE, severity=severity,
        vib_channel=0, tach_channel=1, seed=seed)
    data = np.column_stack([blocks[0], blocks[1]])
    dc.receive_data({
        'data': data, 'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 1), 'rel_time': 0.0,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })
    return dc.data['frame_cache'][-1]


# --- receive_data ---------------------------------------------------------

def test_tach_channel_is_not_highpass_filtered():
    """Measured: the high-pass overshoot on each falling edge re-crosses the
    threshold, turning 31 edges into 108 at 15% duty -- an 1800 RPM shaft
    reads 6270. The bypass is not an optimisation.
    """
    dc = _collector()
    frame = _feed(dc)
    assert frame[1].filtered_mv is None, 'tach must not carry filtered data'
    assert frame[0].filtered_mv is not None, 'vibration still is filtered'


def test_tach_result_is_computed_at_ingestion_and_cached_on_the_sample():
    dc = _collector()
    frame = _feed(dc)
    assert frame[1].tach is not None
    assert frame[1].tach.rpm == pytest.approx(RPM, rel=3e-3)
    assert frame[0].tach is None, 'a vibration channel has no tach result'


def test_tach_uses_the_samples_own_rate_not_the_display_rate():
    """The display rate is maxfreq-driven and much lower; using it would scale
    every RPM reading by the decimation ratio."""
    dc = _collector()
    frame = _feed(dc)
    assert frame[1].tach.samplerate == dc.config.raw_samplerate
    assert frame[1].tach.samplerate != dc.config.samplerate


# --- process_samples ------------------------------------------------------

def test_tach_channel_produces_no_channel_result():
    """A TachResult is not a ChannelResult and must not be mistaken for one:
    it has no overall, no spectrum, no crest factor and no kurtosis."""
    dc = _collector()
    _feed(dc)
    results = dc.process_samples()
    assert [r.channel for r in results] == [0]
    assert all(isinstance(r, vc.ChannelResult) for r in results)


def test_vibration_result_is_unchanged_by_the_presence_of_a_tach_channel():
    """The tach path must be inert for vibration, to floating-point equality."""
    dc_with = _collector()
    _feed(dc_with)
    with_tach = dc_with.process_samples()[0]

    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 0.5
    cfg.enabled_channels = [0]
    dc_without = vc.DataCollector(config=cfg)
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(cfg), running_rate=RUNNING_RATE, severity=1.0, seed=5)
    dc_without.receive_data({
        'data': blocks[0][:, None], 'channels': [0], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 1), 'rel_time': 0.0,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })
    without_tach = dc_without.process_samples()[0]
    assert np.allclose(with_tach.spectrum, without_tach.spectrum)
    assert with_tach.overall == pytest.approx(without_tach.overall)


def test_current_rpm_reports_the_frames_shaft_speed():
    dc = _collector()
    _feed(dc)
    assert dc.current_rpm() == pytest.approx(RPM, rel=3e-3)


def test_current_rpm_is_none_without_a_tach_channel():
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0]
    assert vc.DataCollector(config=cfg).current_rpm() is None


# --- trend ----------------------------------------------------------------

def test_tach_channel_gets_no_amplitude_trend_line():
    """integration_steps('mV','mV') is 0, so a tach would be plotted as raw mV
    next to in/s -- a fifth trend line tracking LED brightness."""
    dc = _collector()
    _feed(dc)
    dc.process_samples()
    assert 1 not in dc.get_trend_for_display()


def test_rpm_is_trended_separately():
    """RPM must never run through UNIT_TO_SI, amplitude_scale or
    integration_steps -- the same reason crest factor sits beside `orders`
    rather than as a column of it."""
    dc = _collector(streaming=True)
    for i in range(3):
        _feed(dc, seed=5 + i)
        dc.process_samples()
    times, rpms = dc.get_rpm_trend()[1]
    assert len(rpms) == 3
    assert all(r == pytest.approx(RPM, rel=5e-3) for r in rpms)


# --- the assumptions a tach breaks ---------------------------------------

def test_eu_scaled_raw_refuses_a_tach_channel():
    """It would silently divide a pulse train by sensitivity 1.0 and return mV
    labelled as engineering units -- the classic field error."""
    dc = _collector()
    frame = _feed(dc)
    with pytest.raises(ValueError):
        dc.eu_scaled_raw(1, frame[1])


def test_reset_channel_config_prunes_roles_and_tach_settings():
    """Moving from a 4-channel to a 2-channel scope must not leave channel 3's
    tach role attached to an index the new device uses for vibration."""
    dc = _collector(tach_ch=3)
    dc.set_tach_settings(3, tach.TachSettings())
    dc.reset_channel_config(2)
    assert 3 not in dc.config.channel_roles
    assert 3 not in dc.tach_settings


def test_set_tach_settings_round_trips_and_clears():
    dc = _collector()
    s = tach.TachSettings(threshold_mode='fixed', threshold_mv=1500.0)
    dc.set_tach_settings(1, s)
    assert dc.tach_settings[1] == s
    dc.set_tach_settings(1, None)
    assert 1 not in dc.tach_settings


def test_tach_settings_change_recomputes_the_reading():
    """RPM is a view on stored data, not a value baked in at capture."""
    dc = _collector()
    frame = _feed(dc)
    first = dc.tach_for(1, frame[1])
    dc.set_tach_settings(1, tach.TachSettings(pulses_per_rev=2))
    second = dc.tach_for(1, frame[1])
    assert second.rpm == pytest.approx(first.rpm / 2.0, rel=1e-6)


def test_a_dead_tach_channel_reports_no_signal_not_zero():
    dc = _collector()
    cfg = dc.config
    n = cfg.raw_blocksize
    data = np.column_stack([
        sim.GenerateBearingVibration(sim._RawRateView(cfg), seed=1),
        np.random.default_rng(0).normal(0.0, 5.0, n),      # disconnected input
    ])
    dc.receive_data({
        'data': data, 'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 9, 1), 'rel_time': 0.0,
        'samplerate': cfg.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })
    assert dc.current_rpm() is None
    assert dc.data['frame_cache'][-1][1].tach.quality == tach.QUALITY_NO_SIGNAL
