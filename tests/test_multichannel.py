"""Tests for multi-channel DataCollector pipeline.

Verifies that data is correctly returned for various channel enable/disable
configurations without requiring physical hardware (SimulatedSensor used).
"""

import time
from datetime import datetime

import numpy as np
import pytest

from vibechecker import (
    AcquisitionSettings,
    DataCollector,
    VibeSample,
    VibeSensor,
    ChannelResult,
)
from vibechecker.scope_sensor import ScopeSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ch_samples(frame: dict) -> dict:
    """Return only the channel:VibeSample entries, excluding metadata keys."""
    return {k: v for k, v in frame.items() if isinstance(k, int)}


def _make_multichannel_samp(n, channels, value_per_channel=None):
    """Build a raw dict as produced by PicoScopeStream for N channels."""
    if value_per_channel is None:
        value_per_channel = {ch: float(ch + 1) * 10 for ch in channels}
    N = len(channels)
    data = np.zeros((n, N), dtype=np.float64)
    for i, ch in enumerate(channels):
        data[:, i] = value_per_channel[ch]
    return {
        'status':    'OKAY',
        'rel_time':  0.0,
        'timestamp': datetime.now(),
        'unit':      ['mV'] * N,
        'channels':  list(channels),
        'data':      data,
    }


def _collect(collector, samp):
    """Push a raw sample through receive_data, return the resulting dict."""
    result = {}
    collector.callbacks['_test'] = lambda s: result.update(s)
    collector.receive_data(samp)
    collector.callbacks.pop('_test', None)
    return result


# ---------------------------------------------------------------------------
# DataCollector.receive_data — channel fan-out
# ---------------------------------------------------------------------------

class TestRecieveDataMultiChannel:

    def test_two_channels_returns_dict_with_two_keys(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0, 1]))

        assert isinstance(result, dict)
        assert set(ch_samples(result).keys()) == {0, 1}

    def test_each_value_is_vibesample(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0, 1]))

        for sample in ch_samples(result).values():
            assert isinstance(sample, VibeSample)

    def test_channel_data_values_are_independent(self):
        """Channel 0 gets col 0, channel 1 gets col 1, values don't cross."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(
            n, [0, 1], value_per_channel={0: 5.0, 1: 99.0}
        ))

        assert np.all(result[0].data == 5.0)
        assert np.all(result[1].data == 99.0)

    def test_four_channels_returns_four_samples(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0, 1, 2, 3]))

        assert len(ch_samples(result)) == 4
        assert set(ch_samples(result).keys()) == {0, 1, 2, 3}

    def test_single_enabled_channel_only(self):
        """When only one channel is in the payload, exactly one sample returned."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0]))

        assert list(ch_samples(result).keys()) == [0]

    def test_non_contiguous_channels(self):
        """Channels [0, 2] (B disabled) returns keys 0 and 2 only."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0, 2]))

        assert set(ch_samples(result).keys()) == {0, 2}

    def test_channel_a_only_no_b(self):
        """Disabling channel B: only channel A data returned."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.config.enabled_channels = [0]
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [0]))

        assert 0 in result
        assert 1 not in result

    def test_channel_b_only_no_a(self):
        """Enabling only channel B: only channel B data returned."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.config.enabled_channels = [1]
        n = collector.config.blocksize

        result = _collect(collector, _make_multichannel_samp(n, [1],
                                                              value_per_channel={1: 77.0}))

        assert 1 in result
        assert 0 not in result
        assert np.all(result[1].data == 77.0)


# ---------------------------------------------------------------------------
# Scope sensor EU conversion per channel
# ---------------------------------------------------------------------------

class TestPerChannelSensorConversion:

    def test_scope_sensor_converts_mv_to_g(self):
        """mV data / sensitivity → EU, unit changes from mV to sensor EU."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        sensor = ScopeSensor(name='test', engineering_units='g', sensitivity=100.0)
        collector.set_scope_sensor(0, sensor)

        # 100 mV → 1 g (sensitivity = 100 mV/g)
        result = _collect(collector, _make_multichannel_samp(
            n, [0], value_per_channel={0: 100.0}
        ))

        assert result[0].unit == 'g'
        assert np.allclose(result[0].data, 1.0)

    def test_channels_converted_independently(self):
        """Each channel applies its own sensor conversion."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        sensor_ch0 = ScopeSensor(name='ch0', engineering_units='g', sensitivity=100.0)
        sensor_ch1 = ScopeSensor(name='ch1', engineering_units='g', sensitivity=50.0)
        collector.set_scope_sensor(0, sensor_ch0)
        collector.set_scope_sensor(1, sensor_ch1)

        result = _collect(collector, _make_multichannel_samp(
            n, [0, 1], value_per_channel={0: 200.0, 1: 150.0}
        ))

        assert np.allclose(result[0].data, 2.0)   # 200 mV / 100 mV/g
        assert np.allclose(result[1].data, 3.0)   # 150 mV / 50 mV/g

    def test_channel_without_sensor_passes_mv_through(self):
        """A channel with no assigned sensor preserves mV unit and raw value."""
        collector = DataCollector()
        collector.config.highpass_enabled = False
        n = collector.config.blocksize

        # Only assign sensor to channel 0, not channel 1
        sensor_ch0 = ScopeSensor(name='ch0', engineering_units='g', sensitivity=100.0)
        collector.set_scope_sensor(0, sensor_ch0)

        result = _collect(collector, _make_multichannel_samp(
            n, [0, 1], value_per_channel={0: 100.0, 1: 55.5}
        ))

        assert result[0].unit == 'g'
        assert result[1].unit == 'mV'
        assert np.allclose(result[1].data, 55.5)


# ---------------------------------------------------------------------------
# AcquisitionSettings.enabled_channels
# ---------------------------------------------------------------------------

class TestEnabledChannels:

    def test_default_is_channel_0_only(self):
        config = AcquisitionSettings()
        assert config.enabled_channels == [0]

    def test_multiple_channels_enabled(self):
        config = AcquisitionSettings()
        config.enabled_channels = [0, 1, 2]
        assert config.enabled_channels == [0, 1, 2]

    def test_instances_are_independent(self):
        cfg_a = AcquisitionSettings()
        cfg_b = AcquisitionSettings()
        cfg_a.enabled_channels.append(3)
        assert 3 not in cfg_b.enabled_channels


# ---------------------------------------------------------------------------
# SimulatedSensor integration — collect_sample returns dict
# ---------------------------------------------------------------------------

class TestCollectSampleMultiChannel:

    @pytest.mark.parametrize('dev', [VibeSensor.simulated()])
    def test_collect_sample_returns_dict(self, dev):
        collector = DataCollector(dev)
        result = collector.collect_sample()
        collector.disconnect_sensor()

        assert isinstance(result, dict), f'Expected dict, got {type(result)}'

    @pytest.mark.parametrize('dev', [VibeSensor.simulated()])
    def test_simulated_collect_sample_has_channel_0(self, dev):
        collector = DataCollector(dev)
        result = collector.collect_sample()
        collector.disconnect_sensor()

        assert 0 in result
        assert isinstance(result[0], VibeSample)
        assert result[0].blocksize > 1


# ---------------------------------------------------------------------------
# Frame cache behaviour
# ---------------------------------------------------------------------------

class TestFrameCache:

    def _push(self, collector, n_blocks=1):
        """Push n_blocks through receive_data with queue active."""
        n = collector.config.blocksize
        samp = _make_multichannel_samp(n, collector.config.enabled_channels)
        for _ in range(n_blocks):
            collector.receive_data(samp)

    def test_frame_cache_grows_on_each_block(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        received = []
        collector.callbacks['t'] = lambda s: received.append(s)
        self._push(collector, n_blocks=3)
        assert len(collector.data['frame_cache']) == 3

    def test_frame_cache_bounded_at_32(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.callbacks['t'] = lambda s: None
        self._push(collector, n_blocks=40)
        assert len(collector.data['frame_cache']) == 32

    def test_frame_cache_contains_vibesamples(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.callbacks['t'] = lambda s: None
        self._push(collector, n_blocks=1)
        frame = collector.data['frame_cache'][-1]
        assert isinstance(frame, dict)
        for sample in ch_samples(frame).values():
            assert isinstance(sample, VibeSample)

    def test_browse_frame_moves_cursor(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.callbacks['t'] = lambda s: None
        self._push(collector, n_blocks=5)
        assert collector._cache_cursor == 0
        collector.browse_frame(+1)
        assert collector._cache_cursor == 1

    def test_browse_frame_clamps_at_bounds(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.callbacks['t'] = lambda s: None
        self._push(collector, n_blocks=3)
        collector.browse_frame(+100)
        assert collector._cache_cursor == 2   # clamped to len-1

    def test_new_block_resets_cursor(self):
        collector = DataCollector()
        collector.config.highpass_enabled = False
        collector.callbacks['t'] = lambda s: None
        self._push(collector, n_blocks=4)
        collector.browse_frame(+2)
        assert collector._cache_cursor == 2
        self._push(collector, n_blocks=1)
        assert collector._cache_cursor == 0   # reset by new arrival


# ---------------------------------------------------------------------------
# Trend store
# ---------------------------------------------------------------------------

class TestTrend:

    def test_update_trend_accumulates(self):
        collector = DataCollector()
        for i in range(5):
            collector.update_trend(0, float(i), float(i * 0.1))
        trend = collector.data['trend'][0]
        assert len(trend['rel_times']) == 5
        assert len(trend['overall']) == 5

    def test_update_trend_fifo_prune(self):
        collector = DataCollector()
        collector.config.trend_max_points = 4
        for i in range(7):
            collector.update_trend(0, float(i), float(i))
        trend = collector.data['trend'][0]
        assert len(trend['rel_times']) == 4
        assert trend['rel_times'][0] == 3.0   # oldest 3 entries dropped

    def test_clear_trend_resets_all_channels(self):
        collector = DataCollector()
        collector.update_trend(0, 1.0, 0.5)
        collector.update_trend(1, 1.0, 0.3)
        collector.data['trend'].setdefault(1, {'rel_times': [], 'overall': []})
        collector.clear_trend()
        for trend in collector.data['trend'].values():
            assert trend['rel_times'] == []
            assert trend['overall'] == []

    def test_init_trend_channels_creates_keys(self):
        collector = DataCollector()
        collector.config.enabled_channels = [0, 2]
        collector.init_trend_channels()
        assert set(collector.data['trend'].keys()) == {0, 2}

    def test_init_trend_channels_preserves_existing_data(self):
        collector = DataCollector()
        collector.config.enabled_channels = [0]
        collector.init_trend_channels()
        collector.update_trend(0, 1.0, 0.9)
        collector.config.enabled_channels = [0, 1]
        collector.init_trend_channels()
        # Channel 0 data preserved, channel 1 starts empty
        assert len(collector.data['trend'][0]['rel_times']) == 1
        assert collector.data['trend'][1]['rel_times'] == []


# ---------------------------------------------------------------------------
# ChannelResult dataclass
# ---------------------------------------------------------------------------

class TestChannelResult:

    def _make_result(self, ch=0, unit='g', n=64):
        freq = np.linspace(0, 1000, n)
        spec = np.ones(n)
        return ChannelResult(
            channel=ch,
            unit=unit,
            time_data=np.zeros(n),
            time_vec=np.linspace(0, 1, n),
            samplerate=8000,
            freq=freq,
            spectrum=spec,
            peaks=np.array([10, 20]),
            overall=1.0,
            timestamp=datetime.now(),
            rel_time=0.0,
            status='OKAY',
        )

    def test_channel_result_fields_accessible(self):
        result = self._make_result()
        assert result.channel == 0
        assert result.unit == 'g'
        assert len(result.freq) == 64
        assert result.overall == 1.0

    def test_channel_result_is_frozen(self):
        result = self._make_result()
        with pytest.raises(Exception):
            result.overall = 99.0   # frozen dataclass must reject mutation
