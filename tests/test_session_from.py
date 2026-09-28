"""One session factory for both front ends (the H-01 shape, third round).

`MonitorSession` was constructed field-by-field in `gui._start_recording` and
in `headless._build_session`, fourteen arguments each. Two of those fields had
already drifted or died:

- **`pre_buffer_frames` and the frame-cache sizing that must match it.** The
  GUI sized the cache to `pre_buffer_n + 1`; headless omitted the `+ 1`, so an
  unattended burst kept one fewer pre-trigger frame than asked for.
- **`max_burst_s`** was a hardcoded 600.0 literal in both, while the value in
  `acquisition.yaml` was seeded, printed in the headless summary, and never
  read by anything.
"""

import pytest

import rev80 as vc
from rev80.monitor.session import (
    pre_buffer_frames_for,
    required_cache_frames,
    sensor_snapshot_for,
    session_from,
)


def _collector(pre_buffer_s=30.0):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 1.0
    cfg.enabled_channels = [0]
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    return dc


# --- item 2: the pre-trigger frame count and the cache that must hold it ---

def test_the_cache_holds_the_pre_trigger_frames_plus_the_trigger_frame():
    """The `+ 1` headless was missing.

    `MonitorController` slices `frame_cache[-n:]` for the pre-trigger window
    and then appends the trigger frame, which becomes `burst_frames[n]`. A
    cache sized to exactly n therefore yields n-1 true pre-trigger frames:
    the trigger frame has taken one of the slots. Nothing reports the achieved
    count, so the loss is silent.
    """
    assert required_cache_frames(cache_frames=8, pre_buffer_frames=32) == 33
    assert required_cache_frames(cache_frames=64, pre_buffer_frames=32) == 64, (
        'a cache already larger than needed is left alone')


@pytest.mark.parametrize('pre_s, block_s, expected', [
    (30.0, 1.0, 30),
    (0.5,  1.0, 1),      # never zero: one pre-trigger frame is the floor
    (0.0,  1.0, 1),
    (30.0, 0.0, 1),      # unknown block length must not divide by zero
])
def test_pre_buffer_frames_is_one_formula(pre_s, block_s, expected):
    assert pre_buffer_frames_for(pre_s, block_s) == expected


def test_both_front_ends_size_the_cache_through_the_same_helper():
    """Source inspection: the divergence was two call sites, not two values."""
    import inspect

    from rev80 import gui, headless

    for mod in (gui, headless):
        src = inspect.getsource(mod)
        assert 'required_cache_frames(' in src, (
            f'{mod.__name__} must size the frame cache through the shared rule')


# --- item 3: max_burst_s is a real setting -------------------------------

def test_max_burst_s_comes_from_the_caller_not_a_literal():
    dc = _collector()
    session = session_from(
        collector=dc, session_id='s', interval_s=600.0, pre_buffer_s=30.0,
        burst_duration_s=120.0, max_burst_s=120.0, output_dir=None,
    )
    assert session.max_burst_s == 120.0


def test_neither_front_end_hardcodes_the_burst_cap():
    """It bounds the one path that runs unattended. S-02 measured burst
    retention at ~2.26 MB/s (~8.1 GB/h on 4 channels); uncapped that is an
    OOM kill with no traceback. A cap nobody can change is not a cap.
    """
    import inspect

    from rev80 import gui, headless

    for mod in (gui, headless):
        src = inspect.getsource(mod)
        assert 'max_burst_s=600.0' not in src and 'max_burst_s       = 600.0' not in src, (
            f'{mod.__name__} still pins the burst cap to a literal')


def test_the_gui_config_save_preserves_a_hand_edited_burst_cap():
    """The GUI wrote `'max_burst_s': 600.0` back on every save, so editing the
    YAML was undone by the next time anyone touched the monitor dialog."""
    import inspect

    from rev80 import gui

    src = inspect.getsource(gui)
    assert "'max_burst_s':       600.0," not in src


# --- the factory itself ---------------------------------------------------

def test_session_from_builds_the_snapshots():
    dc = _collector()
    session = session_from(
        collector=dc, session_id='sess-1', interval_s=300.0, pre_buffer_s=30.0,
        burst_duration_s=60.0, max_burst_s=600.0, output_dir=None,
    )
    assert session.session_id == 'sess-1'
    assert session.acq_snapshot['maxfreq'] == 1000.0
    assert set(session.channel_snapshot) == {'0'}
    assert session.sensor_snapshot == {}
    assert session.session_dir.name == 'sess-1'
    assert session.session_dir.parent.name == 'monitor'


def test_session_from_honours_an_explicit_output_dir(tmp_path):
    session = session_from(
        collector=_collector(), session_id='sess-2', interval_s=1.0,
        pre_buffer_s=1.0, burst_duration_s=1.0, max_burst_s=1.0,
        output_dir=tmp_path,
    )
    assert session.session_dir == tmp_path / 'sess-2'


def test_sensor_snapshot_deduplicates_by_id():
    """One entry per unique sensor, however many channels share it -- the
    loop both front ends had their own copy of."""
    from rev80.scope_sensor import ScopeSensor

    dc = _collector()
    shared = ScopeSensor(id='s1', name='PCB 352C33', sensitivity=100.0,
                         engineering_units='g')
    dc.set_scope_sensor(0, shared)
    dc.set_scope_sensor(1, shared)
    assert list(sensor_snapshot_for(dc)) == ['s1']


def test_both_front_ends_use_the_factory():
    import inspect

    from rev80 import gui, headless

    for mod in (gui, headless):
        src = inspect.getsource(mod)
        assert 'session_from(' in src, f'{mod.__name__} must use the factory'
        assert 'MonitorSession(' not in src, (
            f'{mod.__name__} still constructs MonitorSession field-by-field')
