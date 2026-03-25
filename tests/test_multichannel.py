"""Tests for multi-channel DataCollector pipeline.

Verifies that data is correctly returned for various channel enable/disable
configurations without requiring physical hardware (SimulatedSensor used).
"""

import time
from datetime import datetime

import numpy as np
import pytest

import vibechecker as vc
from vibechecker.scope_sensor import ScopeSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _collect(dc, samp):
    """Push a raw sample through recieve_data, return the dict from the queue."""
    dc.start_data_queue()
    dc.recieve_data(samp)
    result = dc.queue.get_nowait()
    dc.kill_data_queue()
    return result


# ---------------------------------------------------------------------------
# DataCollector.recieve_data — channel fan-out
# ---------------------------------------------------------------------------

class TestRecieveDataMultiChannel:

    def test_two_channels_returns_dict_with_two_keys(self):
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0, 1]))

        assert isinstance(result, dict)
        assert set(result.keys()) == {0, 1}

    def test_each_value_is_vibesample(self):
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0, 1]))

        for sample in result.values():
            assert isinstance(sample, vc.VibeSample)

    def test_channel_data_values_are_independent(self):
        """Channel 0 gets col 0, channel 1 gets col 1, values don't cross."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(
            n, [0, 1], value_per_channel={0: 5.0, 1: 99.0}
        ))

        assert np.all(result[0].data == 5.0)
        assert np.all(result[1].data == 99.0)

    def test_four_channels_returns_four_samples(self):
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0, 1, 2, 3]))

        assert len(result) == 4
        assert set(result.keys()) == {0, 1, 2, 3}

    def test_single_enabled_channel_only(self):
        """When only one channel is in the payload, exactly one sample returned."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0]))

        assert list(result.keys()) == [0]

    def test_non_contiguous_channels(self):
        """Channels [0, 2] (B disabled) returns keys 0 and 2 only."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0, 2]))

        assert set(result.keys()) == {0, 2}

    def test_channel_a_only_no_b(self):
        """Disabling channel B: only channel A data returned."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        dc.config.enabled_channels = [0]
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [0]))

        assert 0 in result
        assert 1 not in result

    def test_channel_b_only_no_a(self):
        """Enabling only channel B: only channel B data returned."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        dc.config.enabled_channels = [1]
        n = dc.config.blocksize

        result = _collect(dc, _make_multichannel_samp(n, [1],
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
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        sensor = ScopeSensor(name='test', engineering_units='g', sensitivity=100.0)
        dc.set_scope_sensor(0, sensor)

        # 100 mV → 1 g (sensitivity = 100 mV/g)
        result = _collect(dc, _make_multichannel_samp(
            n, [0], value_per_channel={0: 100.0}
        ))

        assert result[0].unit == 'g'
        assert np.allclose(result[0].data, 1.0)

    def test_channels_converted_independently(self):
        """Each channel applies its own sensor conversion."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        s0 = ScopeSensor(name='ch0', engineering_units='g', sensitivity=100.0)
        s1 = ScopeSensor(name='ch1', engineering_units='g', sensitivity=50.0)
        dc.set_scope_sensor(0, s0)
        dc.set_scope_sensor(1, s1)

        result = _collect(dc, _make_multichannel_samp(
            n, [0, 1], value_per_channel={0: 200.0, 1: 150.0}
        ))

        assert np.allclose(result[0].data, 2.0)   # 200 mV / 100 mV/g
        assert np.allclose(result[1].data, 3.0)   # 150 mV / 50 mV/g

    def test_channel_without_sensor_passes_mv_through(self):
        """A channel with no assigned sensor preserves mV unit and raw value."""
        dc = vc.DataCollector()
        dc.config.butter_fc = None
        n = dc.config.blocksize

        # Only assign sensor to channel 0, not channel 1
        s0 = ScopeSensor(name='ch0', engineering_units='g', sensitivity=100.0)
        dc.set_scope_sensor(0, s0)

        result = _collect(dc, _make_multichannel_samp(
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
        cfg = vc.AcquisitionSettings()
        assert cfg.enabled_channels == [0]

    def test_multiple_channels_enabled(self):
        cfg = vc.AcquisitionSettings()
        cfg.enabled_channels = [0, 1, 2]
        assert cfg.enabled_channels == [0, 1, 2]

    def test_instances_are_independent(self):
        a = vc.AcquisitionSettings()
        b = vc.AcquisitionSettings()
        a.enabled_channels.append(3)
        assert 3 not in b.enabled_channels


# ---------------------------------------------------------------------------
# SimulatedSensor integration — collect_sample returns dict
# ---------------------------------------------------------------------------

class TestCollectSampleMultiChannel:

    @pytest.mark.parametrize('dev', vc.VibeSensor.find())
    def test_collect_sample_returns_dict(self, dev):
        dc = vc.DataCollector(dev)
        result = dc.collect_sample()
        dc.disconnect_sensor()

        assert isinstance(result, dict), f'Expected dict, got {type(result)}'

    @pytest.mark.parametrize('dev', [vc.VibeSensor.simulated()])
    def test_simulated_collect_sample_has_channel_0(self, dev):
        dc = vc.DataCollector(dev)
        result = dc.collect_sample()
        dc.disconnect_sensor()

        assert 0 in result
        assert isinstance(result[0], vc.VibeSample)
        assert result[0].blocksize > 1
