"""Both front ends build a MonitorSession through one factory, session_from().

The factory sizes the frame cache for the pre-trigger window plus the trigger
frame, and takes max_burst_s from the caller. Some tests read the source of
gui.py and headless.py to check that neither builds a session itself.
"""

from pathlib import Path

import pytest

import rev80 as vc
from rev80.monitor.session import (
    pre_buffer_frames_for,
    required_cache_frames,
    sensor_snapshot_for,
    session_from,
)


# Source checks read the files as text: importing rev80.gui needs dearpygui,
# which ARM installs do not have.
_PKG = Path(__file__).parent.parent / 'src' / 'rev80'


def _source(module):
    return (_PKG / f'{module}.py').read_text(encoding='utf-8')


def _front_end_sources():
    return [(f'rev80.{m}', _source(m)) for m in ('gui', 'headless')]


def _collector(pre_buffer_s=30.0):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq, cfg.binsize = 1000.0, 1.0
    cfg.enabled_channels = [0]
    dc = vc.DataCollector(config=cfg)
    dc.init_trend_channels()
    return dc


# --- the pre-trigger frame count and the cache that must hold it ---

def test_the_cache_holds_the_pre_trigger_frames_plus_the_trigger_frame():
    """required_cache_frames() is at least pre_buffer_frames + 1.

    The controller slices `frame_cache[-n:]` and then appends the trigger
    frame. A cache of exactly n frames gives n-1 pre-trigger frames.
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
    """gui.py and headless.py both call required_cache_frames() (source check)."""
    for name, src in _front_end_sources():
        assert 'required_cache_frames(' in src, (
            f'{name} must size the frame cache through the shared rule')


# --- max_burst_s is a real setting -------------------------------------

def test_max_burst_s_comes_from_the_caller_not_a_literal():
    dc = _collector()
    session = session_from(
        collector=dc, session_id='s', interval_s=600.0, pre_buffer_s=30.0,
        burst_duration_s=120.0, max_burst_s=120.0, output_dir=None,
    )
    assert session.max_burst_s == 120.0


def test_neither_front_end_hardcodes_the_burst_cap():
    """Neither front end passes a literal 600.0 as max_burst_s (source check).

    Burst retention grows at about 2.26 MB/s on 4 channels, so the cap must
    come from the configuration.
    """
    for name, src in _front_end_sources():
        assert 'max_burst_s=600.0' not in src and 'max_burst_s       = 600.0' not in src, (
            f'{name} still pins the burst cap to a literal')


def test_the_gui_config_save_preserves_a_hand_edited_burst_cap():
    """The GUI config save keeps a hand-edited max_burst_s (source check)."""
    src = _source('gui')
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
    """sensor_snapshot_for() gives one entry for each unique sensor ID."""
    from rev80.scope_sensor import ScopeSensor

    dc = _collector()
    shared = ScopeSensor(id='s1', name='PCB 352C33', sensitivity=100.0,
                         engineering_units='g')
    dc.set_scope_sensor(0, shared)
    dc.set_scope_sensor(1, shared)
    assert list(sensor_snapshot_for(dc)) == ['s1']


def test_both_front_ends_use_the_factory():
    for name, src in _front_end_sources():
        assert 'session_from(' in src, f'{name} must use the factory'
        assert 'MonitorSession(' not in src, (
            f'{name} still constructs MonitorSession field-by-field')
