"""Regression tests for pre-trigger overall scaling in MonitorController.

Bug: MonitorController._compute_pretrigger_overalls read the sensor
sensitivity out of the session snapshot under the key
'sensitivity_mv_per_eu'. session.sensor_snapshot holds ScopeSensor.to_dict()
output, which emits 'sensitivity' — the other name appears nowhere in the
codebase. The `.get(..., 1.0)` default therefore ALWAYS won, the mV->EU
division never happened, and every burst's pre-trigger trend points came out
a factor of `sensitivity` too large (~100x for a typical 10.2 mV/g
accelerometer) against the post-trigger points on the very same plot.

Worse, `engineering_units` on the adjacent line used the correct key, so the
unit *label* converted while the *magnitude* did not — the plot looked
plausible and was wrong.
"""

import json

import numpy as np
import pytest

from rev80.monitor.controller import MonitorController
from rev80.monitor.session import MonitorSession
from rev80.monitor.writer import _compute_overall_peaks
from rev80.sample import VibeSample
from rev80.scope_sensor import ScopeSensor

from test_monitor_controller import _make_result

SENSITIVITY_MV_PER_G = 10.2
RAW_MV = 51.0                                  # steady signal, in mV
# amplitude_mode is 'RMS' throughout (AMPLITUDE_SCALE 1.0) so these tests
# isolate the mV->EU division rather than folding in a sqrt(2) peak factor.
EXPECTED_G = RAW_MV / SENSITIVITY_MV_PER_G     # 5.0 g


def _sample_with_raw_mv(raw_mv: float) -> VibeSample:
    """A VibeSample carrying a known raw-mV overall at integration order 0.

    _compute_pretrigger_overalls indexes overall_ampl_by_integration_order at
    `n_steps + 2`; with source EU == target EU there is no integration, so the
    index is 2.
    """
    s = VibeSample(
        status='OKAY', _timestamp=None, samplerate=1000, unit='mV',
        overflow=False, data=np.ones(64) * raw_mv,
    )
    from datetime import datetime, timezone
    s._timestamp = datetime.now(timezone.utc)
    arr = np.zeros(5)
    arr[2] = raw_mv
    s.overall_ampl_by_integration_order = arr
    return s


def _session(tmp_path, sensor_snapshot: dict, channel_snapshot: dict) -> MonitorSession:
    """MonitorSession is frozen, so snapshots must be supplied at construction."""
    from datetime import datetime, timezone
    return MonitorSession(
        session_id        = '2026-05-28-120000_test',
        start_time        = datetime.now(timezone.utc),
        interval_s        = 0.1,
        pre_buffer_frames = 2,
        burst_duration_s  = 0.3,
        max_burst_s       = 5.0,
        session_dir       = tmp_path / 'session',
        sensor_snapshot   = sensor_snapshot,
        channel_snapshot  = channel_snapshot,
    )


def _session_with_sensor(tmp_path, target_unit: str = '') -> MonitorSession:
    sensor = ScopeSensor(
        name='PCB 352C33',
        engineering_units='g',
        sensitivity=SENSITIVITY_MV_PER_G,
        target_unit=target_unit,
        id='sensor-1',
    )
    return _session(
        tmp_path,
        {'sensor-1': sensor.to_dict()},
        {'0': {
            'name': 'ch0',
            'scope_sensor_id': 'sensor-1',
            'target_unit': target_unit or 'g',
            'amplitude_mode': 'RMS',
        }},
    )


def test_pretrigger_applies_sensitivity(tmp_path):
    """Raw mV must be divided by the sensor sensitivity, not passed through."""
    ctrl = MonitorController()
    ctrl._session = _session_with_sensor(tmp_path)

    (out,) = ctrl._compute_pretrigger_overalls([{0: _sample_with_raw_mv(RAW_MV)}])
    value = json.loads(out)['0']

    assert value == pytest.approx(EXPECTED_G), (
        f'expected {RAW_MV} mV / {SENSITIVITY_MV_PER_G} mV/g = {EXPECTED_G} g, '
        f'got {value}'
    )
    # Guard the specific regression: the un-divided value must NOT come back.
    assert value != pytest.approx(RAW_MV)


def test_pretrigger_matches_posttrigger_for_steady_signal(tmp_path):
    """A steady signal must produce the same trend value either side of the trigger.

    This is the user-visible symptom: pre-trigger points sat ~100x above
    post-trigger points on one continuous plot.
    """
    ctrl = MonitorController()
    ctrl._session = _session_with_sensor(tmp_path)

    # Post-trigger path: ChannelResult.overall is already in target EU.
    post_json, _, _, _ = _compute_overall_peaks([_make_result(channel=0, overall=EXPECTED_G)])
    post = json.loads(post_json)['0']

    # Pre-trigger path: same physical signal, still in raw mV.
    (pre_json,) = ctrl._compute_pretrigger_overalls([{0: _sample_with_raw_mv(RAW_MV)}])
    pre = json.loads(pre_json)['0']

    assert pre == pytest.approx(post, rel=1e-9), (
        f'pre-trigger {pre} != post-trigger {post} for a steady signal'
    )


def test_pretrigger_falls_back_to_mv_without_sensor(tmp_path):
    """No sensor assigned → no division, value stays in mV."""
    ctrl = MonitorController()
    ctrl._session = _session(
        tmp_path, {}, {'0': {'name': 'ch0', 'amplitude_mode': 'RMS'}}
    )

    (out,) = ctrl._compute_pretrigger_overalls([{0: _sample_with_raw_mv(RAW_MV)}])
    assert json.loads(out)['0'] == pytest.approx(RAW_MV)


def test_pretrigger_survives_unusable_sensor_snapshot(tmp_path):
    """A malformed sensor entry degrades that channel to mV instead of raising."""
    ctrl = MonitorController()
    ctrl._session = _session(
        tmp_path,
        {'sensor-1': {'nonsense': True}},   # no required keys
        {'0': {'name': 'ch0', 'scope_sensor_id': 'sensor-1', 'amplitude_mode': 'RMS'}},
    )

    (out,) = ctrl._compute_pretrigger_overalls([{0: _sample_with_raw_mv(RAW_MV)}])
    assert json.loads(out)['0'] == pytest.approx(RAW_MV)
