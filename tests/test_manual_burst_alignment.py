"""A manual burst must keep its per-frame results parallel to its frames.

_flush_burst writes all_results[k] beside frames[k], and the burst cap trims
the two lists together. If the lists start at different lengths, every
overall is written beside the wrong waveform and the last frame has none.
The anomaly path pads the trigger frame with its own results; the manual
path must do the same.
"""

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rev80.monitor.controller import MonitorController
from rev80.monitor.session import MonitorSession
from rev80.sample import ChannelResult, VibeSample


def _session(tmp_path: Path, pre_buffer_frames: int = 3) -> MonitorSession:
    # A long burst, so no flush occurs while the test inspects the lists.
    return MonitorSession(
        session_id        = '2026-09-29-120000_test',
        start_time        = datetime.now(timezone.utc),
        interval_s        = 3600.0,
        pre_buffer_frames = pre_buffer_frames,
        burst_duration_s  = 600.0,
        max_burst_s       = 600.0,
        session_dir       = tmp_path / 'session',
    )


def _sample() -> VibeSample:
    return VibeSample(
        status     = 'OKAY',
        _timestamp = datetime.now(timezone.utc),
        samplerate = 1000,
        unit       = 'mV',
        overflow   = False,
        data       = np.ones(64) * 0.1,
    )


def _result() -> ChannelResult:
    n = 64
    freq = np.linspace(0, 500, n // 2 + 1)
    return ChannelResult(
        channel    = 0,
        unit       = 'mV',
        overflow   = False,
        degraded   = False,
        time_data  = np.ones(n) * 0.1,
        time_vec   = np.arange(n) / 1000,
        samplerate = 1000,
        freq       = freq,
        spectrum   = np.ones_like(freq) * 0.01,
        peaks      = np.array([], dtype=int),
        overall    = 0.1,
        timestamp  = datetime.now(timezone.utc),
        rel_time   = 0.0,
        status     = 'OKAY',
    )


class _Stream:
    """A frame cache plus the results the pipeline made for each frame."""

    def __init__(self) -> None:
        self.cache: deque = deque(maxlen=32)
        self.owner: dict[int, int] = {}    # id(result) -> id(sample)

    def new_frame(self) -> list:
        sample, result = _sample(), _result()
        self.cache.append({0: sample})
        self.owner[id(result)] = id(sample)
        return [result]


def _assert_aligned(ctrl: MonitorController, stream: _Stream) -> None:
    frames, all_results = ctrl._burst_frames, ctrl._burst_all_results
    assert len(frames) == len(all_results), (len(frames), len(all_results))
    for k in range(ctrl._burst_pretrigger, len(frames)):
        assert all_results[k], f'frame {k} has no results'
        assert stream.owner[id(all_results[k][0])] == id(frames[k][0]), (
            f'results at index {k} belong to a different frame')


def _recording(tmp_path: Path) -> MonitorController:
    ctrl = MonitorController()
    ctrl.start(_session(tmp_path))
    return ctrl


def test_manual_burst_lists_are_parallel_at_trigger_and_after(tmp_path):
    ctrl, stream = _recording(tmp_path), _Stream()
    try:
        for _ in range(5):
            ctrl.on_results(stream.new_frame(), stream.cache)
        ctrl.trigger_burst()
        _assert_aligned(ctrl, stream)
        for _ in range(4):
            ctrl.on_results(stream.new_frame(), stream.cache)
            _assert_aligned(ctrl, stream)
    finally:
        ctrl.stop()


def test_trigger_frame_is_the_frame_the_monitor_last_saw(tmp_path):
    """A frame that arrives after on_results has no results yet.

    It must not become the trigger frame, or the trigger frame is written
    beside the previous frame's results.
    """
    ctrl, stream = _recording(tmp_path), _Stream()
    try:
        for _ in range(4):
            ctrl.on_results(stream.new_frame(), stream.cache)
        seen = stream.cache[-1]
        stream.new_frame()                      # not yet processed
        ctrl.trigger_burst()
        assert ctrl._burst_frames[ctrl._burst_pretrigger][0] is seen[0]
        _assert_aligned(ctrl, stream)
    finally:
        ctrl.stop()


def test_manual_burst_with_an_empty_frame_cache(tmp_path):
    ctrl, stream = _recording(tmp_path), _Stream()
    try:
        ctrl.on_results([_result()], deque())
        ctrl.trigger_burst()
        assert len(ctrl._burst_frames) == len(ctrl._burst_all_results) == 0
        ctrl.on_results(stream.new_frame(), stream.cache)
        _assert_aligned(ctrl, stream)
    finally:
        ctrl.stop()


def test_manual_burst_before_any_frame(tmp_path):
    ctrl, stream = _recording(tmp_path), _Stream()
    try:
        ctrl.trigger_burst()
        assert len(ctrl._burst_frames) == len(ctrl._burst_all_results) == 0
        ctrl.on_results(stream.new_frame(), stream.cache)
        _assert_aligned(ctrl, stream)
    finally:
        ctrl.stop()
