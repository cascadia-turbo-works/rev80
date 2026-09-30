"""Speed gating: a frame measured at the wrong shaft speed is not comparable.

For a rigid rotor below its first critical speed, the 1x velocity changes as
omega^3, so a 3.2 % shaft-speed change alone moves the overall by 10 %. The
gate is evaluated in DataCollector.speed_ok() and applied only in
monitor/anomaly.valid_results(), which every hook and both baseline paths call.
Thus the gate is not in _build_anomaly_hook, which gui.py and headless.py copy.
"""

import numpy as np
import pytest

import rev80 as vc
from rev80.monitor.anomaly import valid_results


def _result(rpm=1800.0, speed_ok=True, overflow=False, degraded=False, ch=0):
    """A minimal ChannelResult; only the gate-relevant fields matter here."""
    n = 8
    return vc.ChannelResult(
        channel=ch, unit='in/s', overflow=overflow, degraded=degraded,
        time_data=np.zeros(n), time_vec=np.arange(n) / 100.0, samplerate=100.0,
        freq=np.arange(n / 2 + 1), spectrum=np.zeros(int(n / 2 + 1)),
        peaks=np.array([], dtype=int), overall=1.0,
        timestamp=None, rel_time=0.0, status='OKAY',
        rpm=rpm, speed_ok=speed_ok,
    )


def _collector(gate=False, ref=None, tol=3.0):
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles = {1: 'tachometer'}
    cfg.speed_gate_enabled = gate
    cfg.speed_gate_rpm = ref
    cfg.speed_gate_tolerance_pct = tol
    return vc.DataCollector(config=cfg)


# --- ChannelResult carries the reading -----------------------------------

def test_channel_result_defaults_keep_every_existing_construction_valid():
    """ChannelResult defaults speed_ok to True and rpm to None, so a caller
    that does not pass them gets a result that the gate accepts."""
    r = vc.ChannelResult(
        channel=0, unit='g', overflow=False, degraded=False,
        time_data=np.zeros(4), time_vec=np.zeros(4), samplerate=100.0,
        freq=np.zeros(3), spectrum=np.zeros(3), peaks=np.array([], dtype=int),
        overall=0.0, timestamp=None, rel_time=0.0, status='OKAY')
    assert r.rpm is None
    assert r.speed_ok is True


# --- the gate itself ------------------------------------------------------

def test_gate_off_accepts_everything():
    """With the gate off (no tachometer, no reference), every frame passes."""
    dc = _collector(gate=False)
    assert dc.speed_ok(1800.0) is True
    assert dc.speed_ok(None) is True
    assert dc.speed_ok(50.0) is True


@pytest.mark.parametrize('rpm,expected', [
    (1800.0, True),    # on reference
    (1850.0, True),    # +2.8%, inside 3%
    (1750.0, True),    # -2.8%
    (1860.0, False),   # +3.3%, outside
    (1740.0, False),   # -3.3%
])
def test_gate_accepts_only_inside_the_declared_window(rpm, expected):
    dc = _collector(gate=True, ref=1800.0, tol=3.0)
    assert dc.speed_ok(rpm) is expected


def test_gate_fails_closed_when_there_is_no_reading():
    """With the gate on, a missing reading (rpm None) fails the gate.

    If the tach signal is lost during a session (cable, reflector tape, LED),
    passing those frames would let load changes raise alarms again.
    """
    dc = _collector(gate=True, ref=1800.0)
    assert dc.speed_ok(None) is False


def test_reference_latches_from_the_first_valid_frame_when_unset():
    """speed_gate_rpm=None means "latch", not "no gate"."""
    dc = _collector(gate=True, ref=None)
    assert dc.speed_ok(1500.0) is True          # first frame sets the reference
    assert dc.speed_ok(1505.0) is True
    assert dc.speed_ok(1800.0) is False         # 20% away from the latched 1500


def test_latched_reference_is_not_set_by_an_unreadable_frame():
    dc = _collector(gate=True, ref=None)
    assert dc.speed_ok(None) is False
    assert dc.speed_ok(1500.0) is True, 'a None must not latch as the reference'


# --- valid_results is the only place it is applied ------------------------

def test_valid_results_drops_out_of_window_frames():
    kept = valid_results([_result(speed_ok=True), _result(speed_ok=False)])
    assert len(kept) == 1
    assert kept[0].speed_ok is True


def test_valid_results_still_drops_overflow_and_degraded():
    """valid_results() still drops overflow and degraded frames."""
    assert valid_results([_result(overflow=True)]) == []
    assert valid_results([_result(degraded=True)]) == []


def test_valid_results_accepts_results_that_predate_the_field():
    """A result with no rpm/speed_ok attributes passes (getattr defaults)."""
    class Bare:
        overflow = False
        degraded = False
    assert len(valid_results([Bare()])) == 1


def test_an_out_of_window_frame_is_still_measured_and_displayed():
    """A frame outside the window keeps its overall and rpm for display.

    Its amplitude is correct, but it is not comparable with the trend.
    """
    r = _result(speed_ok=False)
    assert r.overall == 1.0
    assert r.rpm == 1800.0
