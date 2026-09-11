# PicoScope 4000A acquisition backend for rev80
#
# Provides:
#   FindPicoScope()      — enumerate connected PS4000A devices
#   PicoScopeStream      — streaming thread that replaces sounddevice.InputStream

import ctypes
import functools
import math
import threading
import time
from datetime import datetime

import numpy as np
import scipy.signal

from rev80._pico_loader import ensure_pico_dlls_loadable
ensure_pico_dlls_loadable()

# The PicoSDK *driver* (libps4000a) is a separate native install from the
# picosdk Python wrapper. picosdk.ps4000a instantiates Ps4000alib() at import
# time, which calls find_library('ps4000a') and raises CannotFindPicoSDKError
# when the driver is absent. Importing this module therefore used to be fatal
# on any machine without the driver — including CI and offline development,
# both of which the project explicitly supports via SimulatedSensor. Degrade
# to PICOSDK_AVAILABLE = False instead; FindPicoScope() reports no devices and
# the simulated path is unaffected.
try:
    from picosdk.ps4000a import ps4000a as ps  # noqa: E402
    from picosdk.functions import adc2mV, assert_pico_ok  # noqa: E402
    PICOSDK_AVAILABLE = True
    _PICOSDK_IMPORT_ERROR = None
except Exception as _exc:   # CannotFindPicoSDKError, CannotOpenPicoSDKError, OSError
    ps = None
    adc2mV = None
    assert_pico_ok = None
    PICOSDK_AVAILABLE = False
    _PICOSDK_IMPORT_ERROR = _exc

import rev80  # noqa: E402

log = rev80.get_logger(__name__)

# PICO_INFO enum values used with ps4000aGetUnitInfo
_PICO_VARIANT_INFO      = 3   # model variant string  e.g. "4461"
_PICO_BATCH_AND_SERIAL  = 4   # batch + serial string e.g. "CMY12/345"

# Rolling driver buffer size (samples). Independent of blocksize.
_DRIVER_BUFFER_SAMPLES = 1000

# Device open / reconnect tuning
_MAX_OPEN_ATTEMPTS      = 2     # retries for ps4000aOpenUnit at detection / start
_OPEN_RETRY_DELAY_S     = 1.0   # seconds between open attempts
_NOT_RESPONDING_DELAY_S = 2.0   # longer pause after PICO_NOT_RESPONDING (device resetting)

#: Streaming-clock quantum, nanoseconds. Measured on a 4824A: the reachable
#: streaming intervals are 12.5 ns apart (an 80 MHz timebase) and the driver
#: floors a request to the grid rather than rounding it. See
#: PicoScopeStream._start_streaming for the probe table and why snapping to
#: this grid ourselves is worth 5x in sample-clock accuracy. Only ever an
#: optimisation: the interval the driver reports back is what is believed.
_TIMEBASE_NS = 12.5

# Streaming watchdog / recovery tuning
_WATCHDOG_TIMEOUT_S     = 5.0   # seconds of silence → assume device hung
_MAX_RECONNECT_ATTEMPTS = 3     # recovery attempts before giving up

# Anti-alias oversample/decimate tuning.
#
# Measured on a PicoScope 4424A (4 channels) during hardware testing for R32:
# continuous ps4000aRunStreaming / ps4000aGetStreamingLatestValues silently
# drops the majority of samples above roughly 100-250 kHz (depending on
# channel count), with status='OKAY' and no overflow bit set — the driver
# gives zero indication anything was lost. Requested rates >=300k Hz saw
# delivery ratios drop as low as 15-23% at 4 channels; even the 1-channel
# case fell to ~34% once the driver internally clamped near 1 MHz. A flat,
# channel-count-independent ceiling of 100 kHz keeps clear margin across
# 1/2/4 channels (the 4-channel case is borderline in the 100-200k range).
#
# To get real anti-alias protection without hitting that ceiling, the ADC is
# run at effective_osr * config.raw_samplerate (oversampled), then filtered and
# decimated back down to config.raw_samplerate before reaching DataCollector.
#
# config.raw_samplerate is now a fixed constant (RAW_SAMPLERATE_HZ in
# sample.py, currently 25600 Hz = 2.56 x the 10 kHz top F_max preset),
# independent of the displayed F_max --
# acquisition always runs at this rate so envelope/demodulation analysis has
# real bearing-resonance bandwidth (2-20 kHz) regardless of what F_max the
# Spectrum tab is showing. Re-validated at that value on the same 4424A
# (scripts/validate-streaming-capacity), sustained 45s at 3 and 4 channels:
#
#   samplerate   osr   raw ADC rate/ch      overflow   degraded transitions
#   40000 Hz      2      ~83.3 kHz             0          0, every run
#   50000 Hz      2      100 kHz (at ceiling)  0          0 to 2, run-to-run
#   100000 Hz     1      100 kHz (at ceiling)  0          0  (but osr=1: no
#                                                             anti-alias margin)
#
# 40 kHz is the highest rate that came back clean *consistently*, with real
# anti-alias margin. 50 kHz sits at the same measured ceiling with zero
# headroom and was not reliable across repeated runs -- sometimes clean,
# sometimes not, on identical hardware and settings -- which disqualifies it
# for a shipped default even more than a rate that failed outright would.
# Only tested up to 4 channels (this hardware's limit); an 8+ channel device
# scaling the same way is an inherited assumption from this
# ceiling being documented as channel-count-independent, not independently
# re-proven here.
STREAMING_CEILING_HZ = 100_000
OSR_TARGET           = 4

# Streaming-rate watchdog tuning (detects sustained-but-not-silent
# under-delivery — see PicoScopeStream.degraded).
_RATE_CHECK_INTERVAL_S     = 2.0   # seconds between rate-degradation checks
_RATE_DEGRADED_THRESHOLD   = 0.9   # effective/requested ratio below this = degraded
_RATE_DEGRADED_CONSECUTIVE = 2     # consecutive bad windows before flagging (~4s)


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


def _probe_channel_count(chandle) -> int:
    """Probe the open device to count available input channels.

    Calls ps4000aSetChannel for channels A–H and counts how many succeed.
    An invalid channel returns a non-zero status without raising; the device
    is left with all channels disabled (caller re-configures on stream start).
    Falls back to 2 if every probe call fails unexpectedly.
    """
    # PS4000A channel enum: A=0, B=1, … H=7
    # Disable the channel (enabled=0) with a nominal range — we just need to
    # know whether the channel exists, not to capture data from it.
    _RANGE_2V = 7    # PS4000A_2V — a safe mid-range value present on all variants
    count = 0
    for ch in range(8):
        status = ps.ps4000aSetChannel(
            chandle,
            ctypes.c_int32(ch),    # channel enum
            ctypes.c_int16(0),     # enabled = False
            ctypes.c_int32(1),     # coupling: AC = 1
            ctypes.c_int32(_RANGE_2V),
            ctypes.c_float(0.0),   # analogue offset
        )
        if status == 0:            # PICO_OK → channel exists
            count += 1
        else:
            break                  # channels are contiguous; first failure ends the range
    return max(count, 2)           # at least 2 for unrecognised responses


def _enumerate_serials() -> list[str]:
    """Return serial numbers for all connected PS4000A devices."""
    count      = ctypes.c_int16(0)
    serial_buf = ctypes.create_string_buffer(256)
    serial_len = ctypes.c_int16(256)
    status = ps.ps4000aEnumerateUnits(
        ctypes.byref(count), serial_buf, ctypes.byref(serial_len)
    )
    if status != 0 or count.value == 0:
        return []
    raw = serial_buf.value.decode('utf-8', errors='replace').strip()
    return [s.strip() for s in raw.split(',') if s.strip()]


def _open_unit_by_serial(chandle, serial: str) -> bool:
    """Open a specific PS4000A by serial number with USB-power handling."""
    _PICO_NOT_RESPONDING = 14
    serial_bytes = serial.encode('utf-8')

    for attempt in range(1, _MAX_OPEN_ATTEMPTS + 1):
        raw_status = ps.ps4000aOpenUnit(ctypes.byref(chandle), serial_bytes)

        if raw_status in (282, 286):
            chg = ps.ps4000aChangePowerSource(chandle, raw_status)
            try:
                assert_pico_ok(chg)
                return True
            except Exception as e:
                log.warning(f'PicoScope {serial}: power-source change failed (attempt {attempt}): {e}')
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
                log.info(f'PicoScope {serial}: open failed (attempt {attempt}, status={raw_status}): {e}')
            delay = _OPEN_RETRY_DELAY_S

        if attempt < _MAX_OPEN_ATTEMPTS:
            time.sleep(delay)

    return False


def FindPicoScope() -> list:
    """
    Probe for connected PicoScope 4000A devices.

    Returns a list of dicts compatible with VibeSensor(**dev), one entry per
    detected unit.  Returns an empty list if no scope is found (does not raise).
    """
    if not PICOSDK_AVAILABLE:
        log.warning('FindPicoScope: PicoSDK driver unavailable (%s) — no hardware devices '
                    'will be reported; use the simulated sensor', _PICOSDK_IMPORT_ERROR)
        return []

    serials = _enumerate_serials()
    if not serials:
        # Fall back to open-any if enumeration yields nothing (driver quirk on first plug-in)
        chandle = ctypes.c_int16()
        if not _open_unit(chandle):
            log.info('FindPicoScope: no scope detected')
            return []
        buf      = ctypes.create_string_buffer(32)
        req_size = ctypes.c_int16(0)
        ps.ps4000aGetUnitInfo(chandle, buf, ctypes.c_int16(32),
                              ctypes.byref(req_size), ctypes.c_uint32(_PICO_BATCH_AND_SERIAL))
        serials = [buf.value.decode('utf-8', errors='replace').strip()]
        ps.ps4000aCloseUnit(chandle)

    devices = []
    for serial in serials:
        chandle = ctypes.c_int16()
        if not _open_unit_by_serial(chandle, serial):
            log.warning(f'FindPicoScope: could not open {serial}, skipping')
            continue

        def _query_info(info_id: int) -> str:
            buf      = ctypes.create_string_buffer(32)
            req_size = ctypes.c_int16(0)
            ps.ps4000aGetUnitInfo(chandle, buf, ctypes.c_int16(32),
                                  ctypes.byref(req_size), ctypes.c_uint32(info_id))
            return buf.value.decode('utf-8', errors='replace').strip()

        model  = _query_info(_PICO_VARIANT_INFO)
        num_ch = _probe_channel_count(chandle)
        ps.ps4000aCloseUnit(chandle)
        log.info(f'FindPicoScope: found PicoScope {model} s/n {serial} ({num_ch} ch)')

        devices.append({
            'device_id':     'ps4000a',
            'model_name':    f'PicoScope {model}',
            'serial_number': serial,
            'build_date':    datetime.now(),
            'format_id':     0,
            'num_channels':  num_ch,
            'sensitivity':   [1.0] * num_ch,   # raw voltage pass-through
            'scale':         [1.0] * num_ch,   # ADC→mV handled inside PicoScopeStream
            'unit':          ['mV'] * num_ch,
        })

    return devices


# Anti-alias kernel design.
#
# `scipy.signal.decimate(ftype='fir')` builds a 20*q+1 tap FIR with a HAMMING
# window, whose sidelobes sit at about -53 dB. Measured end to end through the
# real decimation path at q=4: worst-case stopband rejection -60.0 dB, and the
# passband already 0.29% off at 0.05*fs_out. ISO 2954 and general analyzer
# practice call for >= 80 dB, so that put a hard ~55-60 dB ceiling on usable
# dynamic range regardless of the 14/16-bit resolution negotiated elsewhere.
#
# A Kaiser-windowed FIR reaches any specified attenuation; the cost is taps,
# driven by the transition width. Measured at q=4 (fs_raw 32768 -> 8192):
#
#     design                       taps   worst stopband   passband @ F_max
#     hamming 20q+1 (previous)       81         -60.0 dB          +0.27%
#     kaiser 90 dB,  tw 0.20        231        -105.0 dB          +0.00%
#     kaiser 100 dB, tw 0.20        259        -111.7 dB          +0.00%
#     kaiser 100 dB, tw 0.25        207        -112.4 dB          -0.42%
#
# 100 dB at a 0.20 transition width is chosen: the wider 0.25 transition saves
# 52 taps but starts eating the passband at F_max, which is exactly the region
# the 2.56x oversampling convention exists to keep flat.
#
# The longer kernel does NOT cost block-edge accuracy, which was the obvious
# worry given the filter runs per block. Measured on an in-band tone through a
# single block, against the analytic RMS, at every shipped blocksize:
# hamming +0.2416%, kaiser -0.0001%. The overall's Hann taper already
# de-weights the block edges where the start-up transient lives, and the
# Kaiser design's flatter passband wins by more than the longer transient
# costs.
_AA_STOPBAND_DB: float = 100.0
_AA_TRANSITION_FRAC: float = 0.20


@functools.lru_cache(maxsize=8)
def _antialias_taps(factor: int) -> np.ndarray:
    """Kaiser-windowed FIR decimation kernel for an integer decimation factor.

    Cached: the design depends only on `factor`, and a stream re-runs this on
    every block.
    """
    nyq_out = 0.5 / factor                      # normalised to the raw rate
    f_pass  = nyq_out * (1.0 - _AA_TRANSITION_FRAC)
    ntaps, beta = scipy.signal.kaiserord(_AA_STOPBAND_DB, (nyq_out - f_pass) * 2)
    ntaps |= 1                                  # odd -> exact linear phase
    cutoff = (f_pass + nyq_out) / 2.0
    return scipy.signal.firwin(ntaps, cutoff * 2, window=('kaiser', beta))


def antialias_decimate(raw_block: np.ndarray, factor: int) -> np.ndarray:
    """Anti-alias filter + decimate a (N, channels) raw block by an integer factor.

    Linear-phase polyphase FIR decimation: no group-delay distortion, and no
    forward/backward pass to double the effective order. factor=1 is a no-op
    (some maxfreq presets have no streaming headroom for oversampling — see
    AcquisitionSettings docs).

    See _antialias_taps and the constants above for why this no longer uses
    scipy.signal.decimate's default Hamming kernel.
    """
    if factor <= 1:
        return raw_block
    return scipy.signal.resample_poly(
        raw_block, 1, factor, axis=0, window=_antialias_taps(factor)
    )


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
    * ADC overflow (signal clipping) is logged at WARNING level once per
      channel per stream start; inhibit resets when settings change.
    """

    def __init__(self, config, callback, serial: str = '', siggen_config: dict | None = None):
        """
        Parameters
        ----------
        config   : AcquisitionSettings
            Provides samplerate, blocksize, voltage_range, coupling.
        callback : callable
            DataCollector.receive_data — called with sample dict on each block.
        serial : str
            Serial number used to open the correct device when multiple scopes
            are connected.  Empty string falls back to open-any behaviour.
        siggen_config : dict | None
            Optional signal generator parameters applied on every start().
            Keys: freq_hz (float), pktopk_uv (int), offset_uv (int),
                  wave_type (str, default 'PS4000A_SINE').
            Intended for hardware testing (siggen loopback) and calibration.
        """
        self.config        = config
        self._serial       = serial
        self._app_callback = callback
        self._siggen_config = siggen_config

        self._chandle      = ctypes.c_int16()
        self._maxADC       = ctypes.c_int16()
        self._active       = False
        self._device_open  = False
        self._stop_event   = threading.Event()
        self._thread: threading.Thread | None = None

        # Oversample ratio: the ADC is driven at effective_osr * config.raw_samplerate
        # and the result is filtered + decimated back down before reaching the
        # app callback. Capped at OSR_TARGET and by how much headroom is left
        # under STREAMING_CEILING_HZ at this target rate (see module docstring
        # comment above STREAMING_CEILING_HZ for the hardware measurements this
        # is based on).
        self._effective_osr = self._choose_osr(config.raw_samplerate)

        # One rolling driver buffer per enabled channel
        self._enabled_channels: list[int] = list(config.enabled_channels)
        self._driver_buffers: dict[int, np.ndarray] = {
            ch: np.zeros(_DRIVER_BUFFER_SAMPLES, dtype=np.int16)
            for ch in self._enabled_channels
        }

        # 2-D accumulator: shape (acc_size, N) — one column per enabled channel.
        # Sized in raw (oversampled) samples — see _effective_osr above.
        N = len(self._enabled_channels)
        self._accumulator   = np.zeros((config.raw_blocksize * self._effective_osr * 2, N),
                                       dtype=np.float64)
        self._acc_ptr       = 0
        self._stream_start  = 0.0

        # Actual sample rate reported by hardware after ps4000aRunStreaming;
        # initialised from config and updated in _start_streaming. This is the
        # *target* rate reported downstream (DataCollector, VibeSample, HDF5) —
        # oversampling is fully transparent to consumers of this attribute.
        self._actual_samplerate = config.raw_samplerate
        # Actual *raw* (oversampled) rate achieved by hardware, updated in
        # _start_streaming. Used only internally (decimation, rate watchdog).
        self._actual_raw_samplerate = config.raw_samplerate * self._effective_osr
        # Watchdog: updated by _streaming_callback whenever data arrives
        self._last_data_time    = 0.0
        # Channels already warned about overflow this stream; cleared on start/recover
        self._overflow_warned: set[int] = set()
        # Overflow bits are latched across the accumulation window: a callback
        # can raise overflow without completing a block, and that clipping
        # still corrupts the block it lands in. Cleared when a block is emitted.
        self._overflow_latch: int = 0

        # Streaming-rate watchdog state (detects sustained under-delivery —
        # see _poll_loop and _streaming_callback).
        self._rate_window_samples = 0
        self._rate_window_start   = 0.0
        self._rate_last_check     = 0.0
        self._rate_bad_windows    = 0
        self.degraded: bool = False
        self.effective_samplerate: float = 0.0

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
        self._setup_siggen()
        self._start_streaming()

        # Reset accumulator and watchdog state
        N = len(self._enabled_channels)
        self._acc_ptr         = 0
        self._accumulator     = np.zeros(
            (self.config.raw_blocksize * self._effective_osr * 2, N), dtype=np.float64)
        self._stream_start    = time.monotonic()
        self._last_data_time  = time.monotonic()
        self._overflow_warned = set()   # reset per-channel overflow inhibit on each stream start
        self._overflow_latch = 0

        # Reset streaming-rate watchdog state
        self._rate_window_samples = 0
        self._rate_window_start   = time.monotonic()
        self._rate_last_check     = time.monotonic()
        self._rate_bad_windows    = 0
        self.degraded              = False
        self.effective_samplerate  = 0.0

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

    # PS4000A device-resolution enum values (PS4000A_DEVICE_RESOLUTION).
    # picosdk does not expose these as a named dict for the 4000A family;
    # the values match PICO_DEVICE_RESOLUTION in PicoDeviceEnums.py.
    _RES_8BIT  = 0
    _RES_12BIT = 1
    _RES_14BIT = 2
    _RES_16BIT = 4
    _RES_BITS  = {0: 8, 1: 12, 2: 14, 4: 16}

    def _open_device(self):
        if self._device_open:
            return
        ok = (_open_unit_by_serial(self._chandle, self._serial) if self._serial
              else _open_unit(self._chandle))
        if not ok:
            raise RuntimeError(
                f'PicoScope: could not open device after {_MAX_OPEN_ATTEMPTS} attempts'
            )
        assert_pico_ok(ps.ps4000aMaximumValue(self._chandle,
                                               ctypes.byref(self._maxADC)))
        self._device_open = True
        log.debug(f'PicoScope opened, maxADC={self._maxADC.value}')
        self._set_max_resolution()

    def _set_max_resolution(self):
        """Attempt to set the highest ADC resolution the hardware supports.

        PS4000A resolution constraints (programmer's guide §3.69):
          16-bit : ≤ 1 channel enabled
          14-bit : ≤ 4 channels enabled
          12-bit : ≤ 8 channels enabled   (or any count on the 4824)
           8-bit : always available

        The 4824 returns PICO_NOT_SUPPORTED_BY_THIS_DEVICE — it has fixed
        12-bit hardware and the API is not applicable.  All other failures
        are logged and we fall back to the next lower resolution.

        Note: picosdk always normalises ADC counts to the signed int16 range
        (maxADC = 32767) regardless of resolution, so adc2mV() stays correct
        without refreshing _maxADC here.
        """
        _PICO_NOT_SUPPORTED = 0x11F   # PICO_NOT_SUPPORTED_BY_THIS_DEVICE

        n_ch = len(self._enabled_channels)
        if n_ch <= 1:
            candidates = [self._RES_16BIT, self._RES_14BIT, self._RES_12BIT, self._RES_8BIT]
        elif n_ch <= 4:
            candidates = [self._RES_14BIT, self._RES_12BIT, self._RES_8BIT]
        else:
            candidates = [self._RES_12BIT, self._RES_8BIT]

        for res in candidates:
            raw = ps.ps4000aSetDeviceResolution(self._chandle, ctypes.c_int32(res))
            if raw == 0:   # PICO_OK
                log.info(f'PicoScope resolution: {self._RES_BITS[res]}-bit '
                         f'({n_ch} channel(s) enabled)')
                return
            if raw == _PICO_NOT_SUPPORTED:
                # Device has fixed resolution (e.g. 4824 is always 12-bit)
                res_out = ctypes.c_int32()
                ps.ps4000aGetDeviceResolution(self._chandle, ctypes.byref(res_out))
                native = self._RES_BITS.get(res_out.value, '?')
                log.info(f'PicoScope resolution: {native}-bit fixed '
                         f'(SetDeviceResolution not supported by this variant)')
                return
            log.debug(f'PicoScope: {self._RES_BITS[res]}-bit resolution rejected '
                      f'(status={raw:#x}), trying lower')

        log.warning('PicoScope: could not set any resolution — using hardware default')

    def _configure_channel(self):
        # PS4000A channel enum values equal channel indices: A=0, B=1, …, H=7.
        # The picosdk dict uses a *tuple* key for channel E:
        #   ('PS4000A_CHANNEL_E', 'PS4000A_MAX_4_CHANNELS') → 4
        # so ps.PS4000A_CHANNEL['PS4000A_CHANNEL_E'] raises KeyError even on an
        # 8-channel scope.  Using the index directly as the enum value is safe and
        # avoids the lookup entirely.

        for i in range(8):
            ch_id = i  # PS4000A_CHANNEL_{A..H} == 0..7 by definition
            coupling_key = ('PS4000A_AC' if self.config.coupling_for(i) == 'AC'
                            else 'PS4000A_DC')
            coupling = ps.PS4000A_COUPLING[coupling_key]
            if i in self._enabled_channels:
                try:
                    assert_pico_ok(ps.ps4000aSetChannel(
                        self._chandle, ch_id,
                        1,                               # enabled
                        coupling,
                        self.config.voltage_range_for(i),
                        0.0,
                    ))
                    log.debug(f'Channel {chr(65+i)} enabled: {coupling_key}, '
                              f'range index={self.config.voltage_range_for(i)}')
                except Exception:
                    # Hardware rejected this channel — scope doesn't have it.
                    # Remove from _enabled_channels so _start_streaming skips it.
                    log.debug(f'Channel {chr(65+i)} not available on this scope variant')
                    self._enabled_channels = [
                        ch for ch in self._enabled_channels if ch != i
                    ]
                    break
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

        # Register a rolling buffer for each enabled channel.
        # Use ch directly as the channel enum value (A=0, B=1, …, H=7);
        # avoids the string-key lookup that fails for channel E on picosdk
        # (which uses a tuple alias key instead of a plain string for E).
        for ch in self._enabled_channels:
            assert_pico_ok(ps.ps4000aSetDataBuffers(
                self._chandle,
                ch,                              # PS4000A_CHANNEL_{A..H} == 0..7
                self._driver_buffers[ch].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                None,                            # no min buffer
                _DRIVER_BUFFER_SAMPLES,
                0,                               # memory segment
                ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
            ))

        # Drive the ADC at effective_osr * config.raw_samplerate (oversampled) so the
        # anti-alias filter in _streaming_callback has real signal above the
        # target Nyquist to filter out before decimating back down. See
        # STREAMING_CEILING_HZ / OSR_TARGET module comment for why this is
        # necessary and bounded.
        raw_samplerate = self.config.raw_samplerate * self._effective_osr

        # NANOSECONDS, not microseconds, and rounded rather than truncated.
        #
        # The interval is quantised to whole units of whatever time unit is
        # named here, so the unit sets the achievable rate grid. In us this is
        # brutally coarse at streaming rates: 1e6/76800 = 13.0208 truncated to
        # 13 us, giving 76923 Hz against 76800 requested -- a 1600 ppm error
        # that scaled every displayed frequency, and the reason
        # _report_samplerate exists at all.
        #
        # Two things got worse downstream from that 41 Hz:
        #   * every displayed frequency was 0.16% high, which is real error in
        #     an instrument whose whole job is naming lines;
        #   * 25641 is coprime with every display rate (5120 at F_max=2000), so
        #     collector.decimate_to_rate's rational ratio could not reduce and
        #     scipy designed a 512821-tap FIR on every call -- 73.6 ms per
        #     channel per frame against 0.64 ms at an integer factor.
        #
        # ns is finer but NOT continuous, and the second half of this matters.
        # Probed directly on the 4824A (s/n 13290/0013), requesting a range of
        # intervals and reading back what the driver used:
        #
        #     requested ns   returned ns   rate/ch Hz   /osr Hz    ppm vs 25600
        #        13021          13012       76852.14   25617.38        +679
        #        13020          13012       76852.14   25617.38        +679
        #        13015          13012       76852.14   25617.38        +679
        #        13013          13012       76852.14   25617.38        +679
        #        13012          13000       76923.08   25641.03       +1603
        #        13000          13000       76923.08   25641.03       +1603
        #        12995          12987       77071.29   25690.43       +3532
        #        13025          13025       76775.43   25591.81        -320
        #        13026          13025       76775.43   25591.81        -320
        #        12500          12500       80000.00   26666.67      +41667
        #
        # Two facts fall out. The reachable points are 12.5 ns apart (12987.5,
        # 13000, 13012.5, 13025 ...), i.e. an **80 MHz timebase**; and the
        # driver **floors** to the grid rather than rounding, which is why
        # asking for the arithmetically-correct 13021 lands a whole grid point
        # high. So the naive round(1e9/fs) is better than the us request but
        # still lands on the wrong side.
        #
        # Snapping to the grid ourselves, rounding to NEAREST and then ceil-ing
        # into whole ns so the driver's floor lands where intended, reaches
        # 13025 ns: -320 ppm, the best this hardware can do (8e7/1041 and
        # 8e7/1042 straddle 76800 and 1042 is the nearer). Against +1603 ppm
        # shipped previously, that is 5x better, and every displayed frequency
        # improves with it -- a 1000 Hz line read 1001.6 Hz before.
        #
        # None of this is trusted blind: the driver writes back the interval it
        # really used and that readback (below) is what everything downstream
        # believes. A device with a different timebase simply floors to its own
        # grid and reports it, exactly as before.
        target_ns = 1e9 / raw_samplerate
        grid_ns   = round(target_ns / _TIMEBASE_NS) * _TIMEBASE_NS
        sample_interval_ns = ctypes.c_int32(max(1, math.ceil(grid_ns)))

        assert_pico_ok(ps.ps4000aRunStreaming(
            self._chandle,
            ctypes.byref(sample_interval_ns),
            ps.PS4000A_TIME_UNITS['PS4000A_NS'],
            0,                               # maxPreTriggerSamples
            self.config.raw_blocksize * 4,       # maxPostTriggerSamples — driver buffer budget; autoStop=0 streams continuously regardless
            0,                               # autoStop = 0  → continuous
            1,                               # downsampleRatio
            ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
            _DRIVER_BUFFER_SAMPLES,
        ))

        # Read back the actual achieved raw (oversampled) sample rate: the
        # driver writes into sample_interval_ns whatever it could really use.
        # Kept as a float -- rounding it to an int here is what would put the
        # ns-resolution gain straight back in the bin (76799.02 -> 76799).
        actual_ns = sample_interval_ns.value
        actual_raw_fs = 1e9 / actual_ns if actual_ns > 0 else float(raw_samplerate)
        if abs(actual_raw_fs - raw_samplerate) > 0.5:
            log.debug(f'PicoScope actual raw sample rate: {actual_raw_fs:.2f} Hz '
                      f'(requested {raw_samplerate} Hz, osr={self._effective_osr}, '
                      f'interval {actual_ns} ns)')
        self._actual_raw_samplerate = actual_raw_fs
        self._actual_samplerate = self._report_samplerate(actual_raw_fs)

    @staticmethod
    def _choose_osr(samplerate: float) -> int:
        """Oversample ratio for a target rate, or 1 if none is achievable.

        antialias_decimate() is a no-op at factor 1, so an osr of 1 means the
        stream has NO anti-alias protection whatsoever. The previous
        expression, max(1, int(min(OSR_TARGET, CEILING / samplerate))),
        truncated 1.526 to 1 at F_max=20 kHz and 0.763 to 0 (then clamped to
        1) at F_max=50 kHz, so both of the top presets ran completely
        unfiltered — and the 50 kHz case additionally requested 131072 Hz raw,
        31% above the measured STREAMING_CEILING_HZ, the exact condition the
        module docstring says makes the driver silently drop most samples
        while still reporting status='OKAY' with no overflow bit.

        That matters because a general-purpose IEPE accelerometer has a
        mounted resonance at 25-80 kHz with 20-30 dB of gain there. At
        F_max=20 kHz an unfiltered 50 kHz component folds to 15536 Hz, inside
        the displayed band and indistinguishable from real signal.

        `samplerate` here is config.raw_samplerate (RAW_SAMPLERATE_HZ,
        sample.py) -- a fixed constant, not maxfreq-derived, so this no
        longer varies with what F_max the user picks. Validated at
        RAW_SAMPLERATE_HZ=40000 (osr=2, real margin) on real hardware -- see
        the STREAMING_CEILING_HZ comment above. The constant is now 25600,
        measured on the same 4424A at osr=3 / 76923 Hz per channel, clean at
        3 and 4 simultaneous channels (see the RAW_SAMPLERATE_HZ comment in
        sample.py for the full table). This function still degrades
        gracefully, with a loud warning, if that constant is ever raised past
        what leaves real anti-alias headroom.
        """
        osr = int(math.floor(STREAMING_CEILING_HZ / float(samplerate)))
        osr = min(OSR_TARGET, osr)
        if osr < 2:
            log.warning(
                'ANTI-ALIAS DISABLED: sample rate %g Hz leaves no headroom under '
                'the %d Hz safe streaming ceiling for even 2x oversampling. '
                'Frequencies above %g Hz will alias into the displayed band and '
                'cannot be distinguished from real signal. Lower RAW_SAMPLERATE_HZ '
                '(sample.py).',
                samplerate, STREAMING_CEILING_HZ, samplerate / 2.0,
            )
            return 1
        return osr

    def _report_samplerate(self, actual_raw_fs: float) -> float:
        """The true post-decimation sample rate, for everything downstream.

        Oversampling itself *is* hidden from DataCollector / VibeSample / HDF5
        — that is what dividing by the (exact, integer) decimation ratio does.
        What must NOT be hidden is the rate the hardware actually ran at: the
        driver quantises the streaming interval to its own clock grid (12.5 ns
        on the 4824A — see _start_streaming) and writes back what it used,
        which is generally not what was requested.

        Reporting config.raw_samplerate instead scaled every displayed frequency by
        requested/actual. Measured at F_max=2000: requested 32768 Hz raw, driver
        rounded 30.5 us down to 30 us -> 33333 Hz raw -> 8333.33 Hz decimated,
        reported as 8192 Hz. A true 100 Hz tone displayed at 98.3 Hz and a
        60 Hz line read 59.0 Hz, which breaks harmonic-family identification,
        sideband spacing, and any BPFO/BPFI comparison against a nameplate.

        Returned as a float: the true rate is generally not an integer, and
        rounding it would reintroduce a (smaller) version of the same error.
        """
        return float(actual_raw_fs) / float(self._effective_osr)

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

        # Streaming-rate watchdog: accumulate raw samples actually delivered
        # by the driver this callback, independent of the accumulator/decimate
        # accounting below — this measures raw hardware delivery, not
        # decimated output. Checked periodically in _poll_loop.
        self._rate_window_samples += noOfSamples

        # Latch overflow for the block currently being accumulated. Without
        # this, clipping reported by a callback that does not happen to
        # complete a block was silently discarded, and the block it corrupted
        # was emitted flagged clean.
        self._overflow_latch |= int(overflow)

        # Log ADC overflow (signal clipping) once per channel per stream.
        # overflow is a bitmask: bit n set → channel n clipped.
        #
        # Runs unconditionally, NOT under `if overflow:`. The inhibit is
        # cleared when a channel stops clipping, and that can only be observed
        # on a callback where the mask has gone back to zero — gating the loop
        # on `if overflow` meant a channel that stopped clipping never left the
        # set, so it was never warned about again for the rest of the stream.
        for ch in self._enabled_channels:
            clipping = bool(overflow & (1 << ch))
            if clipping and ch not in self._overflow_warned:
                log.warning(
                    f'PicoScopeStream: ADC overflow on Channel {chr(65 + ch)}'
                )
                self._overflow_warned.add(ch)
            elif not clipping:
                # Only clear when the channel is genuinely no longer clipping.
                # The previous `elif ch in self._overflow_warned` fired exactly
                # when a channel was STILL clipping — the first branch was
                # False only because the channel was already warned — so it
                # removed the inhibit and re-armed the warning for the very
                # next callback. With a 1 ms poll interval that is hundreds of
                # identical WARNING lines per second into the rotating file
                # handler, rolling every other diagnostic out of the log during
                # exactly the run being diagnosed.
                self._overflow_warned.discard(ch)

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

        # Grow accumulator rows if needed. Sized in raw samples — bs below is
        # the raw (oversampled) block size needed before decimation.
        raw_bs = self.config.raw_blocksize * self._effective_osr
        if end > self._accumulator.shape[0]:
            new_rows = end + raw_bs
            grown = np.zeros((new_rows, N), dtype=np.float64)
            grown[:self._accumulator.shape[0]] = self._accumulator
            self._accumulator = grown

        for i, chunk_mv in enumerate(chunks_mv):
            self._accumulator[self._acc_ptr:end, i] = chunk_mv
        self._acc_ptr = end

        # Fire app callback for each complete raw block accumulated, decimated
        # down to config.raw_blocksize before being handed to the app callback.
        bs = raw_bs
        while self._acc_ptr >= bs:
            raw_block = self._accumulator[:bs, :].copy()   # shape (raw_bs, N)
            remainder = self._acc_ptr - bs
            self._accumulator[:remainder] = self._accumulator[bs:self._acc_ptr]
            self._acc_ptr = remainder

            # Anti-alias filter + decimate back down to the target blocksize.
            # DataCollector and everything downstream is unaware oversampling
            # happened — 'samplerate' below stays the target rate.
            block = antialias_decimate(raw_block, self._effective_osr)

            rel_time = self._last_data_time - self._stream_start
            # Consume the latch: it covers every callback that contributed to
            # this block, not just the one that happened to complete it.
            block_overflow = self._overflow_latch
            self._overflow_latch = 0
            status   = 'OVERFLOW' if block_overflow else 'OKAY'

            samp = {
                'status':        status,
                'overflow_mask': int(block_overflow),  # bitmask: bit n set → Ch n clipped
                'rel_time':      rel_time,
                'timestamp':     datetime.now(),
                'unit':          ['mV'] * N,
                'channels':      list(self._enabled_channels),
                'data':          block,           # shape (blocksize, N)
                'samplerate':    self._actual_samplerate,
                'degraded':      self.degraded,
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
                self._open_device()   # calls _set_max_resolution internally
                self._configure_channel()
                self._setup_siggen()
                self._start_streaming()
                # Reset accumulator so stale partial data isn't carried forward
                N = len(self._enabled_channels)
                self._acc_ptr         = 0
                self._accumulator     = np.zeros(
                    (self.config.raw_blocksize * self._effective_osr * 2, N),
                    dtype=np.float64)
                self._last_data_time  = time.monotonic()
                self._overflow_warned = set()   # settings changed — re-arm overflow warnings
                # Reset streaming-rate watchdog state too — a fresh connection
                # deserves a fresh measurement window, not one polluted by the
                # gap during recovery.
                self._rate_window_samples = 0
                self._rate_window_start   = time.monotonic()
                self._rate_last_check     = time.monotonic()
                self._rate_bad_windows    = 0
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

            # Streaming-rate watchdog: detects sustained-but-not-silent
            # under-delivery (e.g. USB/bus bandwidth ceiling exceeded) — a
            # failure mode the silence watchdog above cannot see, since
            # callbacks keep firing regularly with status='OKAY' the whole
            # time. Deliberately does NOT call _try_recover() — see
            # _check_rate_degradation for why.
            self._check_rate_degradation()

            time.sleep(0.001)

        log.debug('PicoScopeStream poll loop exited')

    def _check_rate_degradation(self):
        """Periodically compare delivered vs. requested raw sample rate.

        Independent of the silence watchdog in _poll_loop: a device that is
        streaming at a fraction of the requested rate keeps calling back
        regularly with status='OKAY' and no overflow bit, so the silence
        watchdog never trips even though the majority of samples may be
        silently dropped by the driver (measured on a PicoScope 4424A — see
        STREAMING_CEILING_HZ comment above).
        """
        now = time.monotonic()
        if now - self._rate_last_check < _RATE_CHECK_INTERVAL_S:
            return

        elapsed = now - self._rate_window_start
        effective_rate = self._rate_window_samples / elapsed if elapsed > 0 else 0.0
        self.effective_samplerate = effective_rate

        requested = self._actual_raw_samplerate
        ratio = effective_rate / requested if requested > 0 else 1.0

        if ratio < _RATE_DEGRADED_THRESHOLD:
            self._rate_bad_windows += 1
            if self._rate_bad_windows >= _RATE_DEGRADED_CONSECUTIVE and not self.degraded:
                self.degraded = True
                log.warning(
                    f'PicoScopeStream: streaming rate degraded — '
                    f'{effective_rate:.0f} Hz measured vs {requested:.0f} Hz requested '
                    f'({ratio:.0%}). This is a USB/bus bandwidth ceiling, not a '
                    f'device hang — NOT triggering recovery (reopening the device '
                    f'would not change available throughput).'
                )
        else:
            self._rate_bad_windows = 0
            if self.degraded:
                self.degraded = False
                log.info(
                    f'PicoScopeStream: streaming rate recovered — '
                    f'{effective_rate:.0f} Hz measured vs {requested:.0f} Hz requested '
                    f'({ratio:.0%})'
                )

        self._rate_window_samples = 0
        self._rate_window_start   = now
        self._rate_last_check     = now
