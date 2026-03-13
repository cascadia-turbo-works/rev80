"""Unit tests for vibechecker.picoscope.

All tests mock picosdk so they run without PicoScope hardware attached.
Tests cover:
  - FindPicoScope() — device enumeration, error handling
  - PicoScopeStream._streaming_callback() — accumulator logic, data contract
  - DataCollector integration — mV passthrough via recieve_data
"""

import ctypes
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

import vibechecker as vc
import vibechecker.picoscope as pico_module
from vibechecker.picoscope import PicoScopeStream, _DRIVER_BUFFER_SAMPLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(blocksize=128, samplerate=1000, voltage_range=8, coupling='AC'):
    cfg = vc.AcquisitionSettings()
    cfg.blocksize = blocksize
    cfg.samplerate = samplerate
    cfg.voltage_range = voltage_range
    cfg.coupling = coupling
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


# ---------------------------------------------------------------------------
# FindPicoScope — error paths (no hardware)
# ---------------------------------------------------------------------------

class TestFindPicoScope:

    def test_no_hardware_returns_empty_list(self, monkeypatch):
        """When assert_pico_ok raises (PICO_NOT_FOUND), return []."""
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit',
                            lambda ptr, serial: 10)   # non-power-state error
        monkeypatch.setattr(pico_module, 'assert_pico_ok',
                            lambda s: (_ for _ in ()).throw(Exception('PICO_NOT_FOUND')))

        result = pico_module.FindPicoScope()
        assert result == []

    def test_power_source_failure_returns_empty_list(self, monkeypatch):
        """Power state 282 but ChangePowerSource fails → return []."""
        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit',
                            lambda ptr, serial: 282)
        monkeypatch.setattr(pico_module.ps, 'ps4000aChangePowerSource',
                            lambda handle, status: 10)
        call_count = {'n': 0}

        def strict_assert(status):
            call_count['n'] += 1
            raise Exception('PICO_NOT_FOUND')

        monkeypatch.setattr(pico_module, 'assert_pico_ok', strict_assert)

        result = pico_module.FindPicoScope()
        assert result == []

    def test_successful_find_returns_sensor_dict(self, monkeypatch):
        """Successful open + GetUnitInfo → list with one VibeSensor-compatible dict."""

        def fake_open(ptr, serial):
            return 0   # PICO_OK

        def fake_get_info(handle, buf, buf_len, req_size, info_id):
            # info_id is ctypes.c_uint32; .value gives the integer
            val = info_id.value if hasattr(info_id, 'value') else int(info_id)
            if val == 3:    # _PICO_VARIANT_INFO
                buf.value = b'4461'
            elif val == 4:  # _PICO_BATCH_AND_SERIAL
                buf.value = b'CMY12/345'
            return 0

        monkeypatch.setattr(pico_module.ps, 'ps4000aOpenUnit', fake_open)
        monkeypatch.setattr(pico_module.ps, 'ps4000aGetUnitInfo', fake_get_info)
        monkeypatch.setattr(pico_module.ps, 'ps4000aCloseUnit', lambda h: 0)
        monkeypatch.setattr(pico_module, 'assert_pico_ok', lambda s: None)

        result = pico_module.FindPicoScope()

        assert len(result) == 1
        dev = result[0]
        assert dev['device_id'] == 'ps4000a'
        assert 'PicoScope' in dev['model_name']
        assert '4461' in dev['model_name']
        assert dev['unit'] == ['mV']
        assert dev['scale'] == [1.0]
        assert dev['sensitivity'] == [1.0]
        assert isinstance(dev['serial_number'], str)
        assert isinstance(dev['build_date'], datetime)
        # Returned dict must be accepted by VibeSensor(**dev)
        sensor = vc.VibeSensor(**dev)
        assert not sensor.is_simulation


# ---------------------------------------------------------------------------
# PicoScopeStream — accumulator / _streaming_callback
# ---------------------------------------------------------------------------

class TestStreamingCallbackAccumulator:

    def test_single_chunk_smaller_than_blocksize_no_callback(self, monkeypatch):
        """A chunk smaller than blocksize must not fire the app callback."""
        stream, received = _make_stream(monkeypatch=monkeypatch)
        bs = stream.config.blocksize

        chunk = np.ones(bs - 1, dtype=np.int16)
        stream._streaming_callback(
            handle=0, noOfSamples=len(chunk), startIndex=0,
            overflow=0, triggerAt=0, triggered=0, autoStop=0, param=None,
        )
        assert len(received) == 0

    def test_exact_blocksize_fires_once(self, monkeypatch):
        """Exactly one blocksize worth of samples fires the callback once."""
        stream, received = _make_stream(monkeypatch=monkeypatch)
        bs = stream.config.blocksize

        chunk = np.arange(bs, dtype=np.int16)
        stream._driver_buffer = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer[:bs] = chunk

        stream._streaming_callback(
            handle=0, noOfSamples=bs, startIndex=0,
            overflow=0, triggerAt=0, triggered=0, autoStop=0, param=None,
        )
        assert len(received) == 1

    def test_two_chunks_fire_one_callback(self, monkeypatch):
        """Two partial chunks that together equal one block → one callback."""
        stream, received = _make_stream(monkeypatch=monkeypatch)
        bs = stream.config.blocksize
        half = bs // 2

        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf

        buf[:half] = 1
        stream._streaming_callback(0, half, 0, 0, 0, 0, 0, None)
        assert len(received) == 0

        buf[half:bs] = 2
        stream._streaming_callback(0, half, half, 0, 0, 0, 0, None)
        assert len(received) == 1

    def test_double_blocksize_fires_twice(self, monkeypatch):
        """Delivering 2× blocksize at once fires the callback exactly twice."""
        stream, received = _make_stream(monkeypatch=monkeypatch)
        bs = stream.config.blocksize

        buf = np.zeros(max(bs * 2, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf

        stream._streaming_callback(0, bs * 2, 0, 0, 0, 0, 0, None)
        assert len(received) == 2

    def test_data_shape_is_blocksize_by_one(self, monkeypatch):
        """Fired data dict must have data.shape == (blocksize, 1)."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)

        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, 0, 0, 0, 0, None)

        assert len(received) == 1
        assert received[0]['data'].shape == (bs, 1)

    def test_unit_is_mv(self, monkeypatch):
        """Fired data dict must have unit == ['mV']."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)
        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, 0, 0, 0, 0, None)

        assert received[0]['unit'] == ['mV']

    def test_overflow_sets_status(self, monkeypatch):
        """overflow=1 in the driver callback → status='OVERFLOW' in the dict."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)
        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, overflow=1,
                                    triggerAt=0, triggered=0, autoStop=0, param=None)

        assert received[0]['status'] == 'OVERFLOW'

    def test_okay_status(self, monkeypatch):
        """overflow=0 → status='OKAY'."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)
        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, overflow=0,
                                    triggerAt=0, triggered=0, autoStop=0, param=None)

        assert received[0]['status'] == 'OKAY'

    def test_data_dtype_float64(self, monkeypatch):
        """Accumulated data must be float64 (ready for Butterworth filter)."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)
        buf = np.ones(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, 0, 0, 0, 0, None)

        assert received[0]['data'].dtype == np.float64

    def test_timestamp_is_datetime(self, monkeypatch):
        """Each fired dict must carry a datetime timestamp."""
        bs = 64
        stream, received = _make_stream(_make_config(blocksize=bs),
                                        monkeypatch=monkeypatch)
        buf = np.zeros(max(bs, _DRIVER_BUFFER_SAMPLES), dtype=np.int16)
        stream._driver_buffer = buf
        stream._streaming_callback(0, bs, 0, 0, 0, 0, 0, None)

        assert isinstance(received[0]['timestamp'], datetime)

    def test_zero_samples_noop(self, monkeypatch):
        """noOfSamples=0 must not call the app callback."""
        stream, received = _make_stream(monkeypatch=monkeypatch)
        stream._streaming_callback(0, 0, 0, 0, 0, 0, 0, None)
        assert len(received) == 0


# ---------------------------------------------------------------------------
# PicoScopeStream — stream interface (active property)
# ---------------------------------------------------------------------------

class TestPicoScopeStreamInterface:

    def test_active_starts_false(self):
        """A freshly constructed stream must not be active."""
        stream, _ = _make_stream()
        assert stream.active is False

    def test_active_is_false_after_construction(self):
        config = _make_config()
        received = []
        s = PicoScopeStream(config, lambda samp: received.append(samp))
        assert s.active is False

    def test_accumulator_initialised_correct_size(self):
        """Accumulator pre-allocated to 2× blocksize."""
        bs = 256
        stream, _ = _make_stream(_make_config(blocksize=bs))
        assert len(stream._accumulator) == bs * 2

    def test_acc_ptr_starts_zero(self):
        stream, _ = _make_stream()
        assert stream._acc_ptr == 0


# ---------------------------------------------------------------------------
# DataCollector integration — mV passthrough
# ---------------------------------------------------------------------------

class TestMvPassthrough:

    def test_recieve_data_mv_2d(self):
        """DataCollector.recieve_data with (N,1) mV data → VibeSample.unit='mV'."""
        sensor = vc.VibeSensor.simulated()
        dc = vc.DataCollector(sensor)
        dc.config.butter_fc = None   # disable filter for this test

        n = dc.config.blocksize
        samp = {
            'status':    'OKAY',
            'rel_time':  0.0,
            'timestamp': datetime.now(),
            'unit':      ['mV'],
            'data':      np.ones((n, 1), dtype=np.float64),
        }
        dc.start_data_queue()
        dc.recieve_data(samp)
        result = dc.queue.get_nowait()
        dc.kill_data_queue()

        assert isinstance(result, vc.VibeSample)
        assert result.unit == 'mV'
        assert result.data.shape == (n,)

    def test_recieve_data_mv_selects_channel(self):
        """Channel clamping: channel=0 from (N,1) data gives column 0."""
        sensor = vc.VibeSensor.simulated()
        dc = vc.DataCollector(sensor)
        dc.config.channel = 0
        dc.config.butter_fc = None

        n = dc.config.blocksize
        col0 = np.full((n, 1), 42.0, dtype=np.float64)
        samp = {
            'status': 'OKAY', 'rel_time': 0.0,
            'timestamp': datetime.now(), 'unit': ['mV'], 'data': col0,
        }
        dc.start_data_queue()
        dc.recieve_data(samp)
        result = dc.queue.get_nowait()
        dc.kill_data_queue()

        assert np.all(result.data == 42.0)

    def test_recieve_data_channel_clamping(self):
        """config.channel > available columns → clamped to last column."""
        sensor = vc.VibeSensor.simulated()
        dc = vc.DataCollector(sensor)
        dc.config.channel = 5   # only 1 column available → clamped to 0
        dc.config.butter_fc = None

        n = dc.config.blocksize
        col0 = np.full((n, 1), 7.0, dtype=np.float64)
        samp = {
            'status': 'OKAY', 'rel_time': 0.0,
            'timestamp': datetime.now(), 'unit': ['mV'], 'data': col0,
        }
        dc.start_data_queue()
        dc.recieve_data(samp)
        result = dc.queue.get_nowait()
        dc.kill_data_queue()

        assert np.all(result.data == 7.0)

    def test_get_accel_mv_passthrough(self):
        """VibeSample.get_accel() passes through raw data when unit='mV' and
        config.units='g' (unsupported conversion) without raising."""
        n = 512
        data = np.random.randn(n)
        sample = vc.VibeSample(
            status='OKAY',
            _timestamp=datetime.now(),
            samplerate=1000,
            unit='mV',
            data=data,
        )
        config = vc.AcquisitionSettings()
        config.units = 'g'

        acc_df, rms = sample.get_accel(config)

        assert len(acc_df) == n
        assert np.allclose(acc_df['signal'].to_numpy(), data)


# ---------------------------------------------------------------------------
# AcquisitionSettings — new PicoScope fields
# ---------------------------------------------------------------------------

class TestAcquisitionSettingsPicoFields:

    def test_default_voltage_range(self):
        config = vc.AcquisitionSettings()
        assert config.voltage_range == 8    # PS4000A_5V

    def test_default_coupling(self):
        config = vc.AcquisitionSettings()
        assert config.coupling == 'AC'

    def test_voltage_range_settable(self):
        config = vc.AcquisitionSettings()
        config.voltage_range = 7
        assert config.voltage_range == 7

    def test_coupling_settable(self):
        config = vc.AcquisitionSettings()
        config.coupling = 'DC'
        assert config.coupling == 'DC'
