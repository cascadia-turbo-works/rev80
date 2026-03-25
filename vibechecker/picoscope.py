# PicoScope 4000A acquisition backend for vibechecker
#
# Provides:
#   FindPicoScope()      — enumerate connected PS4000A devices
#   PicoScopeStream      — streaming thread that replaces sounddevice.InputStream
#
# Data contract with DataCollector.receive_data:
#   callback(dict) where dict keys are:
#     status    : str  — 'OKAY' | 'OVERFLOW'
#     rel_time  : float — seconds since stream started
#     timestamp : datetime
#     unit      : list[str] — ['mV']
#     data      : np.ndarray shape (blocksize, 1), dtype float64, values in mV
#
# Phase 1: raw voltage only. Engineering-unit conversion (sensitivity, modality)
# is deferred to Phase 2 via SensorConfig.

import ctypes
import threading
import time
from datetime import datetime

import numpy as np

from picosdk.ps4000a import ps4000a as ps
from picosdk.functions import adc2mV, assert_pico_ok

import vibechecker

log = vibechecker.get_logger(__name__)

# PICO_INFO enum values used with ps4000aGetUnitInfo
_PICO_VARIANT_INFO      = 3   # model variant string  e.g. "4461"
_PICO_BATCH_AND_SERIAL  = 4   # batch + serial string e.g. "CMY12/345"

# Rolling driver buffer size (samples). Independent of blocksize.
_DRIVER_BUFFER_SAMPLES = 1000

# Device open / reconnect tuning
_MAX_OPEN_ATTEMPTS      = 5     # retries for ps4000aOpenUnit at detection / start
_OPEN_RETRY_DELAY_S     = 1.0   # seconds between open attempts
_NOT_RESPONDING_DELAY_S = 2.0   # longer pause after PICO_NOT_RESPONDING (device resetting)

# Streaming watchdog / recovery tuning
_WATCHDOG_TIMEOUT_S     = 5.0   # seconds of silence → assume device hung
_MAX_RECONNECT_ATTEMPTS = 3     # recovery attempts before giving up
_OVERFLOW_LOG_INTERVAL  = 2.0   # minimum seconds between overflow log lines


def _open_unit(chandle) -> bool:
    """
    Call ps4000aOpenUnit with USB-2 power-source handling and up to
    _MAX_OPEN_ATTEMPTS retries.  Returns True on success, False on failure.
    Leaves chandle populated on success.

    After any partially-successful open (status 282/286), the driver holds
    the handle open even if ChangePowerSource fails.  We must call CloseUnit
    before retrying, otherwise subsequent OpenUnit calls return PICO_NOT_FOUND.
    """
    # PICO_NOT_RESPONDING status value (14 = 0x0E hex in picosdk error table)
    _PICO_NOT_RESPONDING = 14

    for attempt in range(1, _MAX_OPEN_ATTEMPTS + 1):
        raw_status = ps.ps4000aOpenUnit(ctypes.byref(chandle), None)

        if raw_status in (282, 286):
            # 282 = PICO_USB3_0_DEVICE_NON_USB3_0_PORT
            # 286 = PICO_POWER_SUPPLY_NOT_CONNECTED
            # Device was found but needs to be told to run on USB power only.
            chg = ps.ps4000aChangePowerSource(chandle, raw_status)
            try:
                assert_pico_ok(chg)
                return True
            except Exception as e:
                log.warning(
                    f'PicoScope: power-source change failed '
                    f'(attempt {attempt}/{_MAX_OPEN_ATTEMPTS}, open_status={raw_status}): {e}'
                )
                # Release the partially-open handle so the next OpenUnit succeeds.
                try:
                    ps.ps4000aCloseUnit(chandle)
                except Exception:
                    pass
                delay = _NOT_RESPONDING_DELAY_S if chg == _PICO_NOT_RESPONDING else _OPEN_RETRY_DELAY_S
        else:
            try:
                assert_pico_ok(raw_status)
                return True
            except Exception as e:
                log.info(
                    f'PicoScope: open failed '
                    f'(attempt {attempt}/{_MAX_OPEN_ATTEMPTS}, status={raw_status}): {e}'
                )
            delay = _OPEN_RETRY_DELAY_S

        if attempt < _MAX_OPEN_ATTEMPTS:
            time.sleep(delay)

    return False


def _channels_for_model(model: str) -> int:
    """Return the number of input channels for a PS4000A model string."""
    m = model.upper().replace(' ', '')
    if any(m.startswith(p) for p in ('4824',)):
        return 8
    if any(m.startswith(p) for p in ('4444', '4461', '4462', '4463', '4464')):
        return 4
    if any(m.startswith(p) for p in ('4225', '4226', '4227', '4262', '4264')):
        return 2
    return 2   # safe default for unrecognised variants


def FindPicoScope() -> list:
    """
    Probe for connected PicoScope 4000A devices.

    Returns a list of dicts compatible with VibeSensor(**dev), one entry per
    detected unit.  Returns an empty list if no scope is found (does not raise).
    """
    chandle = ctypes.c_int16()
    if not _open_unit(chandle):
        log.info('FindPicoScope: no scope detected after retries')
        return []

    def _query_info(info_id: int) -> str:
        buf      = ctypes.create_string_buffer(32)
        req_size = ctypes.c_int16(0)
        ps.ps4000aGetUnitInfo(chandle, buf, ctypes.c_int16(32),
                              ctypes.byref(req_size), ctypes.c_uint32(info_id))
        return buf.value.decode('utf-8', errors='replace').strip()

    model  = _query_info(_PICO_VARIANT_INFO)
    serial = _query_info(_PICO_BATCH_AND_SERIAL)
    num_ch = _channels_for_model(model)

    ps.ps4000aCloseUnit(chandle)   # PicoScopeStream re-opens on .start()
    log.info(f'FindPicoScope: found PicoScope {model} s/n {serial} ({num_ch} ch)')

    return [{
        'device_id':     'ps4000a',
        'model_name':    f'PicoScope {model}',
        'serial_number': serial,
        'build_date':    datetime.now(),
        'format_id':     0,
        'num_channels':  num_ch,
        'sensitivity':   [1.0] * num_ch,   # raw voltage pass-through
        'scale':         [1.0] * num_ch,   # ADC→mV handled inside PicoScopeStream
        'unit':          ['mV'] * num_ch,
    }]


class PicoScopeStream:
    """
    Wraps ps4000a streaming API in a background polling thread.

    Interface matches sounddevice.InputStream and SimulatedSensor:
        .active  → bool
        .start() → open device, configure channel A, begin streaming
        .stop()  → stop streaming, release driver resources
        .close() → close device handle (call after stop)

    The app callback receives a dict matching DataCollector.receive_data's
    expected format on every accumulated blocksize-worth of samples.

    Resilience features
    -------------------
    * OpenUnit is retried up to _MAX_OPEN_ATTEMPTS times on transient failures.
    * A watchdog in the poll loop detects data-silent hangs (e.g. after
      overvoltage) and triggers an automatic stop/reopen/restart recovery cycle.
    * ADC overflow (signal clipping) is logged at WARNING level, rate-limited
      to one line per _OVERFLOW_LOG_INTERVAL seconds.
    """

    def __init__(self, config, callback, siggen_config: dict | None = None):
        """
        Parameters
        ----------
        config   : AcquisitionSettings
            Provides samplerate, blocksize, voltage_range, coupling.
        callback : callable
            DataCollector.receive_data — called with sample dict on each block.
        siggen_config : dict | None
            Optional signal generator parameters applied on every start().
            Keys: freq_hz (float), pktopk_uv (int), offset_uv (int),
                  wave_type (str, default 'PS4000A_SINE').
            Intended for hardware testing (siggen loopback) and calibration.
        """
        self.config        = config
        self._app_callback = callback
        self._siggen_config = siggen_config

        self._chandle      = ctypes.c_int16()
        self._maxADC       = ctypes.c_int16()
        self._active       = False
        self._device_open  = False
        self._stop_event   = threading.Event()
        self._thread: threading.Thread | None = None

        # One rolling driver buffer per enabled channel
        self._enabled_channels: list[int] = list(config.enabled_channels)
        self._driver_buffers: dict[int, np.ndarray] = {
            ch: np.zeros(_DRIVER_BUFFER_SAMPLES, dtype=np.int16)
            for ch in self._enabled_channels
        }

        # 2-D accumulator: shape (acc_size, N) — one column per enabled channel
        N = len(self._enabled_channels)
        self._accumulator   = np.zeros((config.blocksize * 2, N), dtype=np.float64)
        self._acc_ptr       = 0
        self._stream_start  = 0.0

        # Watchdog: updated by _streaming_callback whenever data arrives
        self._last_data_time    = 0.0
        # Rate-limit overflow warnings
        self._last_overflow_log = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    def start(self):
        if self._active:
            log.warning('PicoScopeStream.start() called while already active')
            return

        self._open_device()
        self._configure_channel()
        self._start_streaming()

        # Reset accumulator and watchdog state
        N = len(self._enabled_channels)
        self._acc_ptr        = 0
        self._accumulator    = np.zeros((self.config.blocksize * 2, N), dtype=np.float64)
        self._stream_start   = time.monotonic()
        self._last_data_time = time.monotonic()

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name='PicoScopeStream-poll')
        self._active = True
        self._thread.start()
        log.debug('PicoScopeStream started')

    def stop(self):
        if not self._active:
            log.warning('PicoScopeStream.stop() called while not active')
            return

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                log.warning('PicoScopeStream poll thread did not exit cleanly')

        self._active = False
        try:
            ps.ps4000aStop(self._chandle)
        except Exception as e:
            log.warning(f'PicoScopeStream: ps4000aStop error: {e}')
        log.debug('PicoScopeStream stopped')

    def close(self):
        if self._active:
            self.stop()
        if self._device_open:
            try:
                ps.ps4000aCloseUnit(self._chandle)
            except Exception as e:
                log.warning(f'PicoScopeStream: ps4000aCloseUnit error: {e}')
            self._device_open = False
        log.debug('PicoScopeStream closed')

    # ------------------------------------------------------------------
    # Device setup (called from start() and _try_recover())
    # ------------------------------------------------------------------

    def _open_device(self):
        if self._device_open:
            return
        if not _open_unit(self._chandle):
            raise RuntimeError(
                f'PicoScope: could not open device after {_MAX_OPEN_ATTEMPTS} attempts'
            )
        assert_pico_ok(ps.ps4000aMaximumValue(self._chandle,
                                               ctypes.byref(self._maxADC)))
        self._device_open = True
        log.debug(f'PicoScope opened, maxADC={self._maxADC.value}')

    def _configure_channel(self):
        coupling_key = ('PS4000A_AC' if self.config.coupling == 'AC'
                        else 'PS4000A_DC')
        coupling = ps.PS4000A_COUPLING[coupling_key]
        channel_keys = [f'PS4000A_CHANNEL_{chr(65 + i)}' for i in range(8)]

        for i, ch_key in enumerate(channel_keys):
            try:
                ch_id = ps.PS4000A_CHANNEL[ch_key]
            except KeyError:
                # This scope variant doesn't have this many channels
                break
            if i in self._enabled_channels:
                assert_pico_ok(ps.ps4000aSetChannel(
                    self._chandle, ch_id,
                    1,                               # enabled
                    coupling,
                    self.config.voltage_range_for(i),
                    0.0,
                ))
                log.debug(f'Channel {chr(65+i)} enabled: {coupling_key}, '
                          f'range index={self.config.voltage_range_for(i)}')
            else:
                # Disable unused channels — range index 7 (±2V) is nominal
                try:
                    assert_pico_ok(ps.ps4000aSetChannel(
                        self._chandle, ch_id, 0,
                        ps.PS4000A_COUPLING['PS4000A_DC'], 7, 0.0,
                    ))
                except Exception:
                    # Scope may not have this many channels; ignore gracefully
                    break

    def _setup_siggen(self):
        """Start the built-in signal generator if siggen_config was provided."""
        cfg = self._siggen_config
        if cfg is None:
            return
        wave_type_key = cfg.get('wave_type', 'PS4000A_SINE')
        assert_pico_ok(ps.ps4000aSetSigGenBuiltIn(
            self._chandle,
            int(cfg.get('offset_uv', 0)),
            int(cfg['pktopk_uv']),
            ps.PS4000A_WAVE_TYPE[wave_type_key],
            float(cfg['freq_hz']),
            float(cfg['freq_hz']),
            0, 1,
            ps.PS4000A_SWEEP_TYPE['PS4000A_UP'],
            0, 0, 0,
            ps.PS4000A_SIGGEN_TRIG_TYPE['PS4000A_SIGGEN_RISING'],
            ps.PS4000A_SIGGEN_TRIG_SOURCE['PS4000A_SIGGEN_NONE'],
            ctypes.c_int16(0),
        ))
        log.debug(f'PicoScope siggen started: {cfg["freq_hz"]} Hz, '
                  f'{cfg["pktopk_uv"]} µV pk-pk')

    def _start_streaming(self):
        # Configure signal generator if requested (before streaming starts)
        self._setup_siggen()

        # Register a rolling buffer for each enabled channel
        for ch in self._enabled_channels:
            ch_key = f'PS4000A_CHANNEL_{chr(65 + ch)}'
            assert_pico_ok(ps.ps4000aSetDataBuffers(
                self._chandle,
                ps.PS4000A_CHANNEL[ch_key],
                self._driver_buffers[ch].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                None,                            # no min buffer
                _DRIVER_BUFFER_SAMPLES,
                0,                               # memory segment
                ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
            ))

        sample_interval_us = ctypes.c_int32(max(1, int(1e6 / self.config.samplerate)))

        assert_pico_ok(ps.ps4000aRunStreaming(
            self._chandle,
            ctypes.byref(sample_interval_us),
            ps.PS4000A_TIME_UNITS['PS4000A_US'],
            0,                               # maxPreTriggerSamples
            self.config.blocksize * 4,       # maxPostTriggerSamples — driver buffer budget; autoStop=0 streams continuously regardless
            0,                               # autoStop = 0  → continuous
            1,                               # downsampleRatio
            ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
            _DRIVER_BUFFER_SAMPLES,
        ))

        # Read back the actual achieved sample interval and update config
        actual_us = sample_interval_us.value
        actual_fs = int(round(1e6 / actual_us))
        if actual_fs != self.config.samplerate:
            log.info(f'PicoScope actual sample rate: {actual_fs} Hz '
                     f'(requested {self.config.samplerate} Hz)')
            self.config.samplerate = actual_fs

    # ------------------------------------------------------------------
    # Streaming callback + poll loop (run on background thread)
    # ------------------------------------------------------------------

    def _streaming_callback(self, handle, noOfSamples, startIndex, overflow,
                            triggerAt, triggered, autoStop, param):
        """Called synchronously from ps4000aGetStreamingLatestValues."""
        if noOfSamples == 0:
            return

        # Watchdog heartbeat
        self._last_data_time = time.monotonic()

        # Log ADC overflow (signal exceeds voltage range), rate-limited
        if overflow:
            now = time.monotonic()
            if now - self._last_overflow_log >= _OVERFLOW_LOG_INTERVAL:
                log.warning(
                    'PicoScopeStream: ADC overflow — signal clipped'
                )
                self._last_overflow_log = now

        # Convert ADC counts → mV for each enabled channel.
        # The driver treats the registered buffer as a circular ring, so
        # startIndex + noOfSamples may wrap past _DRIVER_BUFFER_SAMPLES.
        chunks_mv = []
        buf_size = _DRIVER_BUFFER_SAMPLES
        end_idx  = startIndex + noOfSamples
        for ch in self._enabled_channels:
            if end_idx <= buf_size:
                chunk_adc = self._driver_buffers[ch][startIndex:end_idx].copy()
            else:
                # Two-part read: tail of buffer + wrapped head
                first  = self._driver_buffers[ch][startIndex:buf_size]
                second = self._driver_buffers[ch][0:end_idx - buf_size]
                chunk_adc = np.concatenate([first, second])
            chunks_mv.append(np.array(
                adc2mV(chunk_adc, self.config.voltage_range_for(ch), self._maxADC),
                dtype=np.float64,
            ))

        N   = len(self._enabled_channels)
        end = self._acc_ptr + noOfSamples

        # Grow accumulator rows if needed
        if end > self._accumulator.shape[0]:
            new_rows = end + self.config.blocksize
            grown = np.zeros((new_rows, N), dtype=np.float64)
            grown[:self._accumulator.shape[0]] = self._accumulator
            self._accumulator = grown

        for i, chunk_mv in enumerate(chunks_mv):
            self._accumulator[self._acc_ptr:end, i] = chunk_mv
        self._acc_ptr = end

        # Fire app callback for each complete block accumulated
        bs = self.config.blocksize
        while self._acc_ptr >= bs:
            block     = self._accumulator[:bs, :].copy()   # shape (blocksize, N)
            remainder = self._acc_ptr - bs
            self._accumulator[:remainder] = self._accumulator[bs:self._acc_ptr]
            self._acc_ptr = remainder

            rel_time = time.monotonic() - self._stream_start
            status   = 'OVERFLOW' if overflow else 'OKAY'

            samp = {
                'status':    status,
                'rel_time':  rel_time,
                'timestamp': datetime.now(),
                'unit':      ['mV'] * N,
                'channels':  list(self._enabled_channels),
                'data':      block,                         # shape (blocksize, N)
            }
            try:
                self._app_callback(samp)
            except Exception as e:
                log.error(f'PicoScopeStream: app callback error: {e}')

    def _try_recover(self) -> bool:
        """
        Attempt to stop, close, reopen, and restart streaming after a hang or
        driver error.  Returns True if streaming was successfully restarted.
        """
        log.warning('PicoScopeStream: attempting recovery...')

        # Tear down current state
        try:
            ps.ps4000aStop(self._chandle)
        except Exception:
            pass
        try:
            ps.ps4000aCloseUnit(self._chandle)
        except Exception:
            pass
        self._device_open = False

        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            log.info(f'PicoScopeStream: reconnect attempt '
                     f'{attempt}/{_MAX_RECONNECT_ATTEMPTS}')
            time.sleep(1.0)
            try:
                self._open_device()
                self._configure_channel()
                self._start_streaming()
                # Reset accumulator so stale partial data isn't carried forward
                N = len(self._enabled_channels)
                self._acc_ptr        = 0
                self._accumulator    = np.zeros((self.config.blocksize * 2, N),
                                                dtype=np.float64)
                self._last_data_time = time.monotonic()
                log.info('PicoScopeStream: recovery successful')
                return True
            except Exception as e:
                log.warning(f'PicoScopeStream: reconnect attempt {attempt} failed: {e}')

        log.error(
            f'PicoScopeStream: recovery failed after {_MAX_RECONNECT_ATTEMPTS} attempts'
        )
        return False

    def _poll_loop(self):
        """Background thread: poll driver for new streaming data."""
        c_func_ptr = ps.StreamingReadyType(self._streaming_callback)
        log.debug('PicoScopeStream poll loop started')

        while not self._stop_event.is_set():
            # Poll the driver
            try:
                ps.ps4000aGetStreamingLatestValues(self._chandle, c_func_ptr, None)
            except Exception as e:
                log.error(f'PicoScopeStream: GetStreamingLatestValues error: {e}')
                if not self._try_recover():
                    self._active = False
                    break
                # Recovery re-registered buffers; rebuild the C callback pointer
                c_func_ptr = ps.StreamingReadyType(self._streaming_callback)
                continue

            # Watchdog: if the callback hasn't fired in a while, the device
            # has silently stopped (e.g. internal reset after overvoltage).
            silent_s = time.monotonic() - self._last_data_time
            if silent_s > _WATCHDOG_TIMEOUT_S:
                log.error(
                    f'PicoScopeStream: no data for {silent_s:.1f}s — '
                    f'device appears hung, triggering recovery'
                )
                if not self._try_recover():
                    self._active = False
                    break
                c_func_ptr = ps.StreamingReadyType(self._streaming_callback)
                continue

            time.sleep(0.001)

        log.debug('PicoScopeStream poll loop exited')
