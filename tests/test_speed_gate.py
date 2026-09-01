"""Speed gating: a frame measured at the wrong shaft speed is not comparable.

For a rigid rotor below its first critical, unbalance response goes as omega^2
in displacement and so the 1x *velocity* goes as omega^3. A 3.2% speed change
alone moves the overall by 10%, which is the shipped RmsThresholdHook default:
on any VFD or load-following machine the anomaly detector was measuring load
rather than condition.

The gate lives in monitor/anomaly.valid_results() and nowhere else. That seam
already exists to answer exactly this question -- "is this frame a measurement
I should act on?" -- and is already called by every hook and by both baseline
adaptation paths. Putting it there also keeps _build_anomaly_hook byte-identical
between gui.py and headless.py, which audit H-01 requires: those two copies have
already diverged once, and a gate added as a hook parameter would be two bugs
instead of one.
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
    """speed_ok defaults True and rpm None, so every existing construction
    site, fixture and reconstructed result is unaffected."""
    r = vc.ChannelResult(
        channel=0, unit='g', overflow=False, degraded=False,
        time_data=np.zeros(4), time_vec=np.zeros(4), samplerate=100.0,
        freq=np.zeros(3), spectrum=np.zeros(3), peaks=np.array([], dtype=int),
        overall=0.0, timestamp=None, rel_time=0.0, status='OKAY')
    assert r.rpm is None
    assert r.speed_ok is True


# --- the gate itself ------------------------------------------------------

def test_gate_off_accepts_everything():
    """With no tachometer fitted there is no reference, so the gate must be
    inert rather than rejecting every frame."""
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
    """If the tach dies mid-session -- cable pulled, tape peeled, LED aged out
    -- treating "no speed reading" as "speed is fine" leaves an unattended
    monitor alarming on load swings it can no longer see, which is the exact
    false-alarm mechanism the gate exists to remove.
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
    """The existing behaviour must be untouched."""
    assert valid_results([_result(overflow=True)]) == []
    assert valid_results([_result(degraded=True)]) == []


def test_valid_results_accepts_results_that_predate_the_field():
    """getattr defaults keep synthetic and reconstructed results working."""
    class Bare:
        overflow = False
        degraded = False
    assert len(valid_results([Bare()])) == 1


def test_an_out_of_window_frame_is_still_measured_and_displayed():
    """Excluded from alarming, not from the screen. The amplitude is correct;
    it is simply not comparable to the rest of the trend."""
    r = _result(speed_ok=False)
    assert r.overall == 1.0
    assert r.rpm == 1800.0
