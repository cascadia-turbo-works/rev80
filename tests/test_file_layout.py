"""The chart layout and the Rev80 version are stored in both data files.

A measurement file stores the layout in effect at Save; a session stores
the layout at the start of the recording, for its captures and its bursts.
A load sets the layout. A file with no layout, or an invalid one, gives the
default layout and a warning. Headless takes charts.yaml when it exists.
"""

import json
import logging
import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest

import rev80 as vc
from rev80 import charts
from rev80 import simulation as sim
from rev80.charts import ChartSet, ChartSpec
from rev80.monitor import MonitorController
from rev80.monitor.session import session_from
from rev80.scope_sensor import ScopeSensor
from pipeline_helpers import tick

FRAME_S = 0.5


def _layout():
    return ChartSet((
        ChartSpec('c1', 'spectrum', 'Velocity', channels=(0,), unit='in/s',
                  amplitude_mode='RMS', averaging=True, n_averages=4),
        ChartSpec('c5', 'trend', 'Accel trend', channels=(0,), unit='g',
                  amplitude_mode='0-P', show_rpm=True, tach_channel=1),
    ))


def _live():
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 2.0
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units='g', sensitivity=100.0))
    dc.init_trend_channels()
    dc.chart_set = _layout()
    return dc


def _feed(dc, i):
    blocks = sim.GenerateMachineWithTach(sim._RawRateView(dc.config), running_rate=29.37,
                                         seed=60 + i)
    dc.receive_data({
        'data': np.column_stack([blocks[0] * 100.0, blocks[1]]),
        'channels': [0, 1], 'status': 'OKAY', 'timestamp': datetime(2026, 10, 20),
        'rel_time': i * FRAME_S, 'samplerate': dc.config.raw_samplerate,
        'overflow_mask': 0, 'degraded': False,
    })


@pytest.fixture
def measurement(tmp_path):
    dc = _live()
    for i in range(3):
        _feed(dc, i)
        tick(dc)
    path = tmp_path / 'm.h5'
    dc.save_data(path)
    return path


@pytest.fixture(scope='module')
def session_h5(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('sess')
    dc = _live()
    session = session_from(
        collector=dc, session_id='e1', interval_s=0.01, pre_buffer_s=1.0,
        burst_duration_s=1.0, max_burst_s=5.0, output_dir=tmp,
        start_time=datetime.now(timezone.utc))
    dc.chart_set = ChartSet(())          # a later change is not the session's layout
    ctrl = MonitorController()
    ctrl.start(session)
    for i in range(5):
        _feed(dc, i)
        ctrl.on_results(tick(dc), dc.data['frame_cache'])
        if i == 2:
            ctrl.trigger_burst()
        time.sleep(0.03)
    ctrl.stop()
    for _ in range(100):
        if session.session_h5.exists():
            break
        time.sleep(0.05)
    return session.session_h5


def _meta(path):
    with h5py.File(path, 'r') as f:
        return dict(f['metadata'].attrs)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def test_measurement_file_is_version_6_with_layout_and_version(measurement):
    meta = _meta(measurement)
    assert int(meta['version']) == 6
    assert meta['rev80_version'] == vc.__version__
    assert json.loads(meta['chart_layout_json']) == _layout().to_dict()


def test_session_file_is_version_7_with_the_layout_at_the_start(session_h5):
    meta = _meta(session_h5)
    assert int(meta['file_version']) == 7
    assert meta['rev80_version'] == vc.__version__
    assert json.loads(meta['chart_layout_json']) == _layout().to_dict()


def test_session_from_takes_the_layout_in_effect():
    dc = _live()
    s = session_from(collector=dc, session_id='x', interval_s=1.0, pre_buffer_s=1.0,
                     burst_duration_s=1.0, max_burst_s=5.0)
    assert s.chart_layout == _layout().to_dict()
    dc.chart_set = None
    s = session_from(collector=dc, session_id='x', interval_s=1.0, pre_buffer_s=1.0,
                     burst_duration_s=1.0, max_burst_s=5.0)
    assert s.chart_layout == dc.chart_layout().to_dict()


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def test_a_measurement_load_sets_the_layout(measurement):
    dc = vc.DataCollector()
    dc.load_data(measurement)
    assert dc.chart_set == _layout()


@pytest.mark.parametrize('loader', ['session', 'burst', 'capture'])
def test_a_session_load_sets_the_layout(session_h5, loader):
    dc = vc.DataCollector()
    if loader == 'session':
        dc.load_monitor_session(session_h5)
    elif loader == 'capture':
        dc.load_monitor_capture(session_h5, 0)
    else:
        with h5py.File(session_h5, 'r') as f:
            burst_id = next(iter(f['burst'].keys()))
        dc.load_monitor_burst(session_h5, burst_id)
    assert dc.chart_set == _layout()


@pytest.mark.parametrize('stored', [None, 'not json', '{"version": 1, "charts": "x"}'])
def test_no_or_a_bad_layout_gives_the_default_and_a_warning(measurement, stored, caplog):
    with h5py.File(measurement, 'a') as f:
        if stored is None:
            del f['metadata'].attrs['chart_layout_json']
        else:
            f['metadata'].attrs['chart_layout_json'] = stored
    dc = vc.DataCollector()
    with caplog.at_level(logging.WARNING):
        dc.load_data(measurement)
    # The record view of the file's channel 0: its sensor's EU (g), not mV.
    # The load runs before a front end assigns the file's sensors.
    assert dc.chart_set == charts.default_layout([0], lambda ch: ('g', '0-P'))
    assert [c.unit for c in dc.chart_set.charts] == ['g', 'g']
    assert 'chart layout' in caplog.text


def test_record_view_rule():
    assert charts.record_view(None, 'in/s', 'RMS') == ('mV', 'RMS')
    assert charts.record_view('g', '', '') == ('g', '0-P')
    assert charts.record_view('g', 'in/s', 'P-P') == ('in/s', 'P-P')


# ---------------------------------------------------------------------------
# Headless
# ---------------------------------------------------------------------------

def test_headless_takes_charts_yaml(monkeypatch, tmp_path):
    from rev80 import config as cfg_mod
    from rev80.headless import _chart_set_for
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(cfg_mod.sys, 'platform', 'linux')
    dc = _live()
    dc.chart_set = None
    default = charts.default_layout(dc.config.vibration_channels, dc.default_view_of)
    assert _chart_set_for(dc) == default
    cfg_mod.ensure_config_dir()
    charts.save_chart_set(cfg_mod.charts_config_path(), _layout())
    assert _chart_set_for(dc) == _layout()
