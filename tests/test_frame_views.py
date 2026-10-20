"""Frame side effects are split from the views.

`advance_frame(snapshot)` adds one trend point and one RPM point for each new
live frame. `results_for()` and `result_view()` have no side effects and can
run any number of times in one tick, so a second view (an alarm unit, the
display average) does not add a second trend point. The record results are
never averaged; the display uses the configured averaging.
"""

import logging
from datetime import datetime

import numpy as np
import pytest

import rev80 as vc
from rev80 import simulation as sim
from rev80.scope_sensor import ScopeSensor


class _LiveStream:
    active = True


def _collector(streaming=True, averaging=False):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    cfg.channel_target_units = {0: 'in/s'}
    cfg.averaging_enabled = averaging
    cfg.n_averages = 4
    dc = vc.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    dc.init_trend_channels()
    if streaming:
        dc.sensor = object()
        dc.stream = _LiveStream()
    return dc


def _feed(dc, i):
    blocks = sim.GenerateMachineWithTach(
        sim._RawRateView(dc.config), running_rate=25.0, seed=i)
    dc.receive_data({
        'data': np.column_stack([blocks[0] * 100.0, blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 19), 'rel_time': i * dc.config.acquisition_period,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def _points(dc):
    return len(dc.trend[0]['rel_times']), len(dc.tach_trend[1]['rpm'])


def test_one_tick_with_record_and_other_views_adds_one_point():
    dc = _collector()
    _feed(dc, 0)
    snap = dc.snapshot()
    dc.advance_frame(snap)
    dc.results_for(snap)
    dc.results_for(snap, 'g', 'RMS')
    dc.results_for(snap, 'mil', 'P-P')
    assert _points(dc) == (1, 1)


def test_a_redisplay_of_the_same_frame_adds_no_point():
    dc = _collector()
    _feed(dc, 0)
    dc.advance_frame(dc.snapshot())
    dc.advance_frame(dc.snapshot())          # a settings change redisplays it
    assert _points(dc) == (1, 1)
    _feed(dc, 1)
    dc.advance_frame(dc.snapshot())
    assert _points(dc) == (2, 2)


def test_a_browsed_frame_adds_no_point():
    dc = _collector(streaming=False)
    _feed(dc, 0)
    dc.advance_frame(dc.snapshot())
    assert _points(dc) == (0, 0)


def test_results_for_has_no_side_effects_on_the_trend():
    dc = _collector()
    _feed(dc, 0)
    snap = dc.snapshot()
    for _ in range(3):
        dc.results_for(snap)
    assert _points(dc) == (0, 0)


def test_the_trend_point_is_the_record_view():
    dc = _collector()
    _feed(dc, 0)
    snap = dc.snapshot()
    dc.advance_frame(snap)
    (rec,) = dc.results_for(snap)
    (_, values) = dc.get_trend_for_display()[0]
    assert values == [pytest.approx(rec.overall, rel=1e-12)]
    assert dc.trend[0]['kurtosis'][-1] == rec.kurtosis


def test_the_view_is_memoised_for_the_tick_only():
    dc = _collector()
    _feed(dc, 0)
    snap = dc.snapshot()
    a = dc.result_view(snap, 0, 'g')
    assert dc.result_view(snap, 0, 'g') is a
    assert dc.result_view(snap, 0, 'in/s') is not a
    assert dc.result_view(dc.snapshot(), 0, 'g') is not a


def test_record_results_are_never_averaged():
    dc = _collector(averaging=True)
    for i in range(4):
        _feed(dc, i)
    snap = dc.snapshot()
    (rec,) = dc.results_for(snap)
    (disp,) = dc.results_for(snap, n_averages=dc.display_n_averages())
    assert rec.n_averages == 1
    assert disp.n_averages == 4
    assert rec.overall != disp.overall
    # Crest factor and kurtosis are never averaged.
    assert disp.kurtosis == rec.kurtosis


def test_no_result_for_the_tachometer_channel():
    dc = _collector()
    _feed(dc, 0)
    results = dc.results_for(dc.snapshot())
    assert [r.channel for r in results] == [0]


@pytest.mark.parametrize('unit', ['mV', 'furlongs', 'mil'])
def test_an_unreachable_unit_gives_none_and_logs_once(caplog, unit):
    dc = _collector()
    _feed(dc, 0)
    snap = dc.snapshot()
    if unit == 'mil':
        # Reachable from g (two integrations); a channel with no sensor is not.
        dc.set_scope_sensor(0, None)
    with caplog.at_level(logging.WARNING, logger='rev80.collector'):
        assert dc.result_view(snap, 0, unit) is None
        assert dc.result_view(dc.snapshot(), 0, unit) is None
    assert sum('cannot be shown' in r.getMessage() for r in caplog.records) == 1


def test_default_view_is_the_channel_target_unit_and_mode():
    dc = _collector()
    dc.config.channel_amplitude_modes[0] = 'P-P'
    assert dc.default_view_of(0) == ('in/s', 'P-P')
    dc.set_scope_sensor(0, None)
    assert dc.default_view_of(0) == ('mV', 'P-P')


def test_trend_in_another_unit_equals_the_view_in_that_unit():
    dc = _collector()
    for i in range(3):
        _feed(dc, i)
        snap = dc.snapshot()
        dc.advance_frame(snap)
    (_, values) = dc.get_trend_for_display('mil', 'P-P')[0]
    view = dc.result_view(snap, 0, 'mil', 'P-P')
    assert values[-1] == pytest.approx(view.overall, rel=1e-12)
    assert dc.get_trend_for_display('in/s', channels=[1, 5]) == {}
    assert dc.get_trend_for_display('mV')[0] == ([], [])
