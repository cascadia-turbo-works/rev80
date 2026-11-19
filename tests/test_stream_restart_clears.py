"""A stream start sets a new rel_time zero, so it must clear the cached data.

Frames and trend points from the previous stream have rel_times on another
time base. Left in the cache, they plot as a step back in time on the trends,
and the browse cursor walks across two streams.
"""

import time

import numpy as np

from rev80 import AcquisitionSettings, DataCollector, VibeSensor


def _collector() -> DataCollector:
    """Channel 0 vibration, channel 1 tachometer."""
    cfg = AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.channel_roles[1] = 'tachometer'
    collector = DataCollector(VibeSensor.simulated(), cfg)
    collector.init_trend_channels()
    assert collector.config.tach_channels == [1]
    return collector


def _fill_old_stream_state(collector: DataCollector) -> None:
    """Put the data of a previous stream (rel_time 500 s) in the collector."""
    collector.data["frame_cache"].append({0: None})
    collector.data["frame_cache"].append({0: None})
    collector._cache_cursor = 1
    collector.update_trend(0, 500.0, np.ones(5), crest_factor=3.0, kurtosis=3.0)
    collector._update_tach_trend(1, 500.0, 1800.0)
    collector._advanced_frame = collector.data["frame_cache"][-1]


def test_start_stream_clears_cache_and_trends_before_the_stream_runs():
    collector = _collector()
    _fill_old_stream_state(collector)
    seen = {}

    def fake_start():
        seen["cache"] = len(collector.data["frame_cache"])
        seen["cursor"] = collector._cache_cursor
        seen["trend"] = {ch: len(td["rel_times"]) for ch, td in collector.trend.items()}
        seen["tach"] = {ch: len(td["rel_times"]) for ch, td in collector.tach_trend.items()}
        seen["advanced"] = collector._advanced_frame

    collector.stream.start = fake_start
    collector.start_stream()

    assert seen["cache"] == 0
    assert seen["cursor"] == 0
    assert all(n == 0 for n in seen["trend"].values())
    assert all(n == 0 for n in seen["tach"].values())
    assert seen["advanced"] is None


def test_reset_data_store_clears_the_rpm_trend():
    collector = _collector()
    collector._update_tach_trend(1, 500.0, 1800.0)
    collector.reset_data_store()
    assert all(len(td["rel_times"]) == 0 for td in collector.tach_trend.values())


def test_clear_trend_clears_the_rpm_trend():
    collector = _collector()
    collector._update_tach_trend(1, 500.0, 1800.0)
    collector.clear_trend()
    assert all(len(td["rel_times"]) == 0 for td in collector.tach_trend.values())


def test_simulated_rel_time_starts_at_zero_on_each_start():
    """The simulated stream has the same time base as the PicoScope stream."""
    collector = _collector()
    period = collector.config.acquisition_period
    try:
        for _ in range(2):
            collector.new_frame_event.clear()
            collector.start_stream()
            assert collector.new_frame_event.wait(timeout=period * 5)
            collector.stop_stream()
            rel = [s.rel_time for f in collector.data["frame_cache"]
                   for k, s in f.items() if isinstance(k, int) and s is not None]
            assert rel, "no frame arrived"
            assert min(rel) < 2 * period
            assert np.all(np.diff(rel) >= 0)
            time.sleep(0.05)
    finally:
        collector.disconnect_sensor()


def test_start_stream_keeps_an_enlarged_cache_depth():
    """Monitor Mode enlarges the cache for the pre-trigger frames of a burst.

    A restart during a recording must not shrink it to config.cache_frames.
    """
    collector = _collector()
    enlarged = collector.config.cache_frames + 25
    collector.resize_frame_cache(enlarged)
    seen = {}
    collector.stream.start = lambda: seen.setdefault(
        "maxlen", collector.data["frame_cache"].maxlen)
    collector.start_stream()
    assert seen["maxlen"] == enlarged
