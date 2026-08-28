"""Unit tests for rev80.picoscope.

All tests mock picosdk so they run without PicoScope hardware attached.
Tests cover:
  - FindPicoScope() — device enumeration, error handling, channel count
  - _channels_for_model() — model string → channel count
  - PicoScopeStream._streaming_callback() — accumulator logic, data contract
  - DataCollector integration — mV passthrough via receive_data
"""

import ctypes
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np

import rev80 as vc
import rev80.picoscope as pico_module
from rev80.picoscope import PicoScopeStream, _DRIVER_BUFFER_SAMPLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(maxfreq=500, binsize=8.0, coupling='AC', enabled_channels=None,
                  blocksize=None):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = maxfreq
    if blocksize is not None:
        # Derive binsize that produces the desired blocksize
        cfg.binsize = cfg.samplerate / blocksize
    else:
        cfg.binsize = binsize
    cfg.coupling = coupling
    cfg.highpass_enabled = False
    if enabled_channels is not None:
        cfg.enabled_channels = list(enabled_channels)
    return cfg


def _make_stream(config=None, monkeypatch=None):
    """Return a PicoScopeStream with adc2mV patched to identity."""
    if config is None:
        config = _make_config()
    received = []
    stream = PicoScopeStream(config, lambda samp: received.append(samp))
    stream._maxADC = ctypes.c_int16(32767)
    if monkeypatch is not None:
        monkeypatch.setattr(pico_module, 'adc2mV',
                            lambda buf, rng, maxADC: list(buf))
    return stream, received


def _fill_driver_buffers(stream, value=0, n=None):
    """Fill all driver buffers with a constant value."""
    size = n or _DRIVER_BUFFER_SAMPLES
    for ch in stream._enabled_channels:
        buf = np.full(max(size, _DRIVER_BUFFER_SAMPLES), value, dtype=np.int16)
        stream._driver_buffers[ch] = buf


# ---------------------------------------------------------------------------
# FindPicoScope — error paths (no hardware)
# ---------------------------------------------------------------------------

class TestFindPicoScope:

    def test_no_hardware_returns_empty_list(self, monkeypatch):
        """When assert_pico_ok raises (PICO_NOT_FOUND), return []."""
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit',
                            lambda ptr, serial: 10)
        monkeypatch.setattr(pico_module, 'assert_pico_ok',
                            lambda s: (_ for _ in ()).throw(Exception('PICO_NOT_FOUND')))

        result = pico_module.FindPicoScope()
        assert result == []

    def test_power_source_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit',
                            lambda ptr, serial: 282)
        monkeypatch.setattr(pico_module.ps, 'ps4000aChangePowerSource',
                            lambda handle, status: 10)

        def strict_assert(status):
            raise Exception('PICO_NOT_FOUND')

        monkeypatch.setattr(pico_module, 'assert_pico_ok', strict_assert)

        result = pico_module.FindPicoScope()
        assert result == []

    def test_successful_find_returns_sensor_dict(self, monkeypatch):
        """Successful open + GetUnitInfo → list with one VibeSensor-compatible dict."""

        def fake_open(ptr, serial):
            return 0

        def fake_get_info(handle, buf, buf_len, req_size, info_id):
            val = info_id.value if hasattr(info_id, 'value') else int(info_id)
            if val == 3:
                buf.value = b'4461'
            elif val == 4:
                buf.value = b'CMY12/345'
            return 0

        def fake_set_channel_4ch(handle, ch, enabled, coupling, rng, offset):
            ch_num = ch.value if hasattr(ch, 'value') else int(ch)
            return 0 if ch_num < 4 else 1  # PICO_OK for ch A-D, fail for ch E+

        monkeypatch.setattr(pico_module.ps, 'ps4000aEnumerateUnits',
                            lambda count, buf, buf_len: 1)  # non-zero → use fallback path
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit', fake_open)
        monkeypatch.setattr(pico_module.ps, 'ps4000aGetUnitInfo', fake_get_info)
        monkeypatch.setattr(pico_module.ps, 'ps4000aSetChannel', fake_set_channel_4ch)
        monkeypatch.setattr(pico_module.ps, 'ps4000aCloseUnit', lambda h: 0)
        monkeypatch.setattr(pico_module, 'assert_pico_ok', lambda s: None)

        result = pico_module.FindPicoScope()

        assert len(result) == 1
        dev = result[0]
        assert dev['device_id'] == 'ps4000a'
        assert 'PicoScope' in dev['model_name']
        assert '4461' in dev['model_name']
        assert dev['num_channels'] == 4
        assert len(dev['unit']) == 4
        assert all(u == 'mV' for u in dev['unit'])
        assert isinstance(dev['serial_number'], str)
        assert isinstance(dev['build_date'], datetime)
        sensor = vc.VibeSensor(**dev)
        assert sensor.num_channels == 4
        assert not sensor.is_simulation

    def test_find_8ch_model_reports_8_channels(self, monkeypatch):
        def fake_open(ptr, serial): return 0

        def fake_get_info(handle, buf, buf_len, req_size, info_id):
            val = info_id.value if hasattr(info_id, 'value') else int(info_id)
            if val == 3:
                buf.value = b'4824A'
            elif val == 4:
                buf.value = b'AB123/456'
            return 0

        monkeypatch.setattr(pico_module.ps, 'ps4000aEnumerateUnits',
                            lambda count, buf, buf_len: 1)  # non-zero → use fallback path
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit', fake_open)
        monkeypatch.setattr(pico_module.ps, 'ps4000aGetUnitInfo', fake_get_info)
        monkeypatch.setattr(pico_module.ps, 'ps4000aSetChannel', lambda h, ch, e, c, r, o: 0)  # all 8 ok
        monkeypatch.setattr(pico_module.ps, 'ps4000aCloseUnit', lambda h: 0)
        monkeypatch.setattr(pico_module, 'assert_pico_ok', lambda s: None)

        result = pico_module.FindPicoScope()
        assert result[0]['num_channels'] == 8


# ---------------------------------------------------------------------------
# PicoScopeStream — accumulator / _streaming_callback (single channel)
# ---------------------------------------------------------------------------

class TestStreamingCallbackAccumulator:

    def test_single_chunk_smaller_than_blocksize_no_callback(self, monkeypatch):
        stream, received = _make_stream(monkeypatch=monkeypatch)
        raw_bs = stream.config.blocksize * stream._effective_osr

        _fill_driver_buffers(stream, value=0, n=raw_bs)
        stream._streaming_callback(
            handle=0, noOfSamples=raw_bs - 1, startIndex=0,
            overflow=0, triggerAt=0, triggered=0, autoStop=0, param=None,
        )
        assert len(received) == 0

    def test_exact_blocksize_fires_once(self, monkeypatch):
        stream, received = _make_stream(monkeypatch=monkeypatch)
        raw_bs = stream.config.blocksize * stream._effective_osr

        buf = np.arange(raw_bs, dtype=np.int16)
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffers[0][:raw_bs] = buf

        stream._streaming_callback(
            handle=0, noOfSamples=raw_bs, startIndex=0,
            overflow=0, triggerAt=0, triggered=0, autoStop=0, param=None,
        )
        assert len(received) == 1

    def test_two_chunks_fire_one_callback(self, monkeypatch):
        stream, received = _make_stream(monkeypatch=monkeypatch)
        raw_bs = stream.config.blocksize * stream._effective_osr
        half = raw_bs // 2

        buf = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffers[0] = buf

        buf[:half] = 1
        stream._streaming_callback(0, half, 0, 0, 0, 0, 0, None)
        assert len(received) == 0

        buf[half:raw_bs] = 2
        stream._streaming_callback(0, half, half, 0, 0, 0, 0, None)
        assert len(received) == 1

    def test_double_blocksize_fires_twice(self, monkeypatch):
        stream, received = _make_stream(monkeypatch=monkeypatch)
        raw_bs = stream.config.blocksize * stream._effective_osr

        buf = np.zeros(max(raw_bs * 2, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffers[0] = buf

        stream._streaming_callback(0, raw_bs * 2, 0, 0, 0, 0, 0, None)
        assert len(received) == 2

    def test_data_shape_is_blocksize_by_n_channels(self, monkeypatch):
        """Fired data must have shape (blocksize, N) where N = enabled channels,
        after anti-alias decimation from the raw (oversampled) block size."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr

        buf = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffers[0] = buf
        stream._streaming_callback(0, raw_bs, 0, 0, 0, 0, 0, None)

        assert len(received) == 1
        N = len(stream._enabled_channels)
        assert received[0]['data'].shape == (bs, N)

    def test_channels_key_in_payload(self, monkeypatch):
        """Each fired dict must carry a 'channels' key matching enabled_channels."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, 0, 0, 0, 0, None)

        assert 'channels' in received[0]
        assert received[0]['channels'] == [0]

    def test_unit_length_matches_channel_count(self, monkeypatch):
        """unit list length must equal number of enabled channels."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, 0, 0, 0, 0, None)

        N = len(stream._enabled_channels)
        assert len(received[0]['unit']) == N
        assert all(u == 'mV' for u in received[0]['unit'])

    def test_overflow_sets_status(self, monkeypatch):
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, overflow=1,
                                   triggerAt=0, triggered=0, autoStop=0, param=None)
        assert received[0]['status'] == 'OVERFLOW'

    def test_okay_status(self, monkeypatch):
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, overflow=0,
                                   triggerAt=0, triggered=0, autoStop=0, param=None)
        assert received[0]['status'] == 'OKAY'

    def test_data_dtype_float64(self, monkeypatch):
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.ones(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, 0, 0, 0, 0, None)
        assert received[0]['data'].dtype == np.float64

    def test_timestamp_is_datetime(self, monkeypatch):
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs), monkeypatch=monkeypatch)
        raw_bs = bs * stream._effective_osr
        stream._driver_buffers[0] = np.zeros(max(raw_bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._streaming_callback(0, raw_bs, 0, 0, 0, 0, 0, None)
        assert isinstance(received[0]['timestamp'], datetime)

    def test_zero_samples_noop(self, monkeypatch):
        stream, received = _make_stream(monkeypatch=monkeypatch)
        stream._streaming_callback(0, 0, 0, 0, 0, 0, 0, None)
        assert len(received) == 0


# ---------------------------------------------------------------------------
# PicoScopeStream — streaming-rate degradation watchdog (R32)
#
# _check_rate_degradation() is driven directly (not via the background poll
# thread) with a fully controlled fake clock, monkeypatching time.monotonic
# in the picoscope module namespace so no real sleeping is needed.
# ---------------------------------------------------------------------------

class TestRateDegradationWatchdog:

    RAW_RATE = 4000.0  # requested raw (oversampled) samplerate for these tests

    def _fake_clock(self, monkeypatch, start=1000.0):
        clock = {'t': start}
        monkeypatch.setattr(pico_module.time, 'monotonic', lambda: clock['t'])
        return clock

    def _prime(self, stream, clock):
        """Reset watchdog bookkeeping to the current fake time, as start()
        would, so the first _check_rate_degradation() call sees a clean
        window rather than a huge bogus elapsed time since object init."""
        stream._actual_raw_samplerate = self.RAW_RATE
        stream._rate_window_start = clock['t']
        stream._rate_last_check = clock['t']
        stream._rate_window_samples = 0
        stream._rate_bad_windows = 0
        stream.degraded = False

    def test_healthy_stream_stays_not_degraded(self, monkeypatch):
        stream, _ = _make_stream()
        clock = self._fake_clock(monkeypatch)
        self._prime(stream, clock)
        interval = pico_module._RATE_CHECK_INTERVAL_S

        for _ in range(5):
            clock['t'] += interval
            stream._rate_window_samples = int(self.RAW_RATE * interval)  # 100% delivered
            stream._check_rate_degradation()
            assert stream.degraded is False

    def test_sustained_shortfall_triggers_then_recovers(self, monkeypatch):
        stream, _ = _make_stream()
        clock = self._fake_clock(monkeypatch)
        self._prime(stream, clock)
        interval = pico_module._RATE_CHECK_INTERVAL_S
        consecutive = pico_module._RATE_DEGRADED_CONSECUTIVE

        # Well below _RATE_DEGRADED_THRESHOLD (0.9) — 50% delivered.
        bad_samples = int(self.RAW_RATE * interval * 0.5)

        for i in range(consecutive):
            clock['t'] += interval
            stream._rate_window_samples = bad_samples
            stream._check_rate_degradation()
            if i < consecutive - 1:
                # Debounce: fewer than _RATE_DEGRADED_CONSECUTIVE bad windows
                # must not flag degraded yet.
                assert stream.degraded is False

        assert stream.degraded is True

        # A subsequent healthy window clears the flag.
        clock['t'] += interval
        stream._rate_window_samples = int(self.RAW_RATE * interval)
        stream._check_rate_degradation()
        assert stream.degraded is False

    def test_try_recover_never_called_for_rate_degradation(self, monkeypatch):
        """Explicit design decision: a USB/bus bandwidth ceiling is not a
        device hang, so the rate watchdog must never trigger _try_recover()
        (unlike the silence watchdog)."""
        stream, _ = _make_stream()
        spy = MagicMock()
        monkeypatch.setattr(stream, '_try_recover', spy)

        clock = self._fake_clock(monkeypatch)
        self._prime(stream, clock)
        interval = pico_module._RATE_CHECK_INTERVAL_S
        consecutive = pico_module._RATE_DEGRADED_CONSECUTIVE
        bad_samples = int(self.RAW_RATE * interval * 0.5)

        # Drive several consecutive bad windows — well past the debounce.
        for _ in range(consecutive + 2):
            clock['t'] += interval
            stream._rate_window_samples = bad_samples
            stream._check_rate_degradation()
        assert stream.degraded is True

        # ... then recover.
        clock['t'] += interval
        stream._rate_window_samples = int(self.RAW_RATE * interval)
        stream._check_rate_degradation()
        assert stream.degraded is False

        spy.assert_not_called()


# ---------------------------------------------------------------------------
# PicoScopeStream — stream interface (active property, accumulator)
# ---------------------------------------------------------------------------

class TestPicoScopeStreamInterface:

    def test_active_starts_false(self):
        stream, _ = _make_stream()
        assert stream.active is False

    def test_accumulator_shape_is_2d(self):
        """Accumulator is 2-D: (2*blocksize*effective_osr, N_channels) — sized
        in raw (oversampled) samples, since decimation happens after
        accumulation."""
        bs = 256
        stream, _ = _make_stream(_make_config(blocksize=bs))
        assert stream._accumulator.ndim == 2
        assert stream._accumulator.shape[0] == bs * stream._effective_osr * 2
        assert stream._accumulator.shape[1] == len(stream._enabled_channels)

    def test_acc_ptr_starts_zero(self):
        stream, _ = _make_stream()
        assert stream._acc_ptr == 0

    def test_driver_buffers_keyed_by_channel(self):
        """_driver_buffers must be a dict keyed by channel index."""
        stream, _ = _make_stream()
        assert isinstance(stream._driver_buffers, dict)
        for ch in stream._enabled_channels:
            assert ch in stream._driver_buffers


# ---------------------------------------------------------------------------
# DataCollector integration — mV passthrough, multi-channel fan-out
# ---------------------------------------------------------------------------

class TestMvPassthrough:

    def _collect(self, collector, samp):
        collector.receive_data(samp)
        cache = collector.data['frame_cache']
        return dict(cache[-1]) if cache else {}

    def test_receive_data_single_channel_returns_dict(self):
        """receive_data returns a dict keyed by channel index."""
        collector = vc.DataCollector(vc.VibeSensor.simulated())
        collector.config.highpass_enabled = False
        n = collector.config.blocksize
        samp = {
            'status': 'OKAY', 'rel_time': 0.0,
            'timestamp': datetime.now(),
            'unit': ['mV'],
            'channels': [0],
            'data': np.ones((n, 1), dtype=np.float64),
        }
        result = self._collect(collector, samp)

        assert isinstance(result, dict)
        assert 0 in result
        assert isinstance(result[0], vc.VibeSample)

    def test_receive_data_mv_unit_preserved(self):
        collector = vc.DataCollector(vc.VibeSensor.simulated())
        collector.config.highpass_enabled = False
        n = collector.config.blocksize
        samp = {
            'status': 'OKAY', 'rel_time': 0.0,
            'timestamp': datetime.now(),
            'unit': ['mV'],
            'channels': [0],
            'data': np.ones((n, 1), dtype=np.float64),
        }
        result = self._collect(collector, samp)

        assert result[0].unit == 'mV'

    def test_receive_data_correct_values(self):
        """Channel 0 column data flows through unchanged (no scope sensor assigned)."""
        collector = vc.DataCollector(vc.VibeSensor.simulated())
        collector.config.highpass_enabled = False
        n = collector.config.blocksize
        samp = {
            'status': 'OKAY', 'rel_time': 0.0,
            'timestamp': datetime.now(),
            'unit': ['mV'],
            'channels': [0],
            'data': np.full((n, 1), 42.0, dtype=np.float64),
        }
        result = self._collect(collector, samp)

        assert np.all(result[0].data == 42.0)

    def test_process_mv_passthrough(self):
        """process_sample passes through raw mV data when no sensor is assigned."""
        n = 512
        data = np.random.randn(n)
        sample = vc.VibeSample(
            status='OKAY',
            _timestamp=datetime.now(),
            samplerate=1000,
            unit='mV',
            overflow=False,
            data=data,
        )
        collector = vc.DataCollector()
        collector.config.highpass_enabled = False
        result = collector.process_sample(0, sample)
        assert result is not None
        assert len(result.time_data) == n
        assert np.allclose(result.time_data, data)


# ---------------------------------------------------------------------------
# AcquisitionSettings — new multi-channel fields
# ---------------------------------------------------------------------------

class TestAcquisitionSettingsPicoFields:

    def test_default_enabled_channels(self):
        """enabled_channels must be a non-empty list of valid channel indices."""
        config = vc.AcquisitionSettings()
        assert isinstance(config.enabled_channels, list)
        assert len(config.enabled_channels) >= 1

    def test_default_coupling(self):
        """Global coupling must be AC or DC."""
        config = vc.AcquisitionSettings()
        assert config.coupling in ('AC', 'DC')

    def test_voltage_range_for_default(self):
        config = vc.AcquisitionSettings()
        assert 0 <= config.voltage_range_for(0) <= 13   # valid PS4000A range index

    def test_voltage_range_for_unknown_channel_returns_default(self):
        config = vc.AcquisitionSettings()
        assert 0 <= config.voltage_range_for(7) <= 13   # unknown ch → valid default

    def test_voltage_range_for_set_per_channel(self):
        config = vc.AcquisitionSettings()
        config.channel_voltage_ranges = {0: 5, 1: 8}
        assert config.voltage_range_for(0) == 5
        assert config.voltage_range_for(1) == 8
        assert 0 <= config.voltage_range_for(2) <= 13   # unknown ch → valid default

    def test_enabled_channels_settable(self):
        config = vc.AcquisitionSettings()
        config.enabled_channels = [0, 1, 2]
        assert config.enabled_channels == [0, 1, 2]

    def test_coupling_settable(self):
        config = vc.AcquisitionSettings()
        config.coupling = 'DC'
        assert config.coupling == 'DC'

    def test_each_instance_has_independent_enabled_channels(self):
        """Mutable default_factory: two instances must not share the list."""
        a = vc.AcquisitionSettings()
        b = vc.AcquisitionSettings()
        a.enabled_channels.append(1)
        assert b.enabled_channels == [0]
