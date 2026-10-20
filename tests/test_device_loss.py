"""Loss of the PicoScope: no driver call on a lost handle, recovery by a new one.

A fake driver records every call with the handle it got. It models what the
probe measured on a 4000A (CONTRIBUTING.md, "E21. Device loss"):
- after a loss the poll still returns PICO_OK, with no data;
- PingUnit gives PICO_OK only for a present, owned, idle handle;
- OpenUnit gives a new handle once the scope is back on a new USB node, and
  PICO_HARDWARE_VERSION_NOT_SUPPORTED while a lost handle still owns it.
Stop or CloseUnit on a lost handle crashes the real process, so the fake
records it as a violation.
"""

import ctypes
import logging
import threading
import time

import pytest

import rev80 as vc
import rev80.picoscope as pico_module
from rev80.picoscope import (PICO_BUSY, PICO_HARDWARE_VERSION_NOT_SUPPORTED, PICO_OK,
                             PICO_NOT_RESPONDING, PicoScopeStream)
from picosdk.constants import PICO_STATUS

PICO_NOT_FOUND = PICO_STATUS['PICO_NOT_FOUND']
SERIAL = 'TEST/0001'


class FakeDriver:
    """A PS4000A driver with one scope that can be lost and come back."""

    PS4000A_COUPLING = {'PS4000A_AC': 1, 'PS4000A_DC': 0}
    PS4000A_WAVE_TYPE = {'PS4000A_SINE': 0}
    PS4000A_SWEEP_TYPE = {'PS4000A_UP': 0}
    PS4000A_SIGGEN_TRIG_TYPE = {'PS4000A_SIGGEN_RISING': 0}
    PS4000A_SIGGEN_TRIG_SOURCE = {'PS4000A_SIGGEN_NONE': 0}
    PS4000A_RATIO_MODE = {'PS4000A_RATIO_MODE_NONE': 0}
    PS4000A_TIME_UNITS = {'PS4000A_NS': 2}

    def __init__(self, samples_per_poll=64):
        self.calls: list[tuple[str, int]] = []
        self.violations: list[str] = []
        self.present = True
        self.owner: int | None = None       # handle that owns the scope
        self.lost: set[int] = set()         # handles that refer to a lost device
        self.streaming: int | None = None
        self.next_handle = 1
        self.samples_per_poll = samples_per_poll
        self.callbacks: list = []           # every callback given to the driver
        self.open_gate: threading.Event | None = None
        self._inside = 0
        self._lock = threading.Lock()

    # -- test controls ----------------------------------------------------

    def lose(self, same_node=False):
        """Remove the scope. same_node: it stays on its USB node, and the old
        handle still owns it when it comes back."""
        self.present = False
        if self.owner is not None:
            self.lost.add(self.owner)
            if not same_node:
                self.owner = None
        self.streaming = None

    def replug(self):
        self.present = True

    def calls_on(self, handle: int, after: int = 0) -> list[str]:
        return [fn for fn, h in self.calls[after:] if h == handle]

    # -- bookkeeping ------------------------------------------------------

    def _enter(self, fn, handle):
        with self._lock:
            self._inside += 1
            if self._inside > 1:
                self.violations.append(f'{fn}: two threads in the driver')
            self.calls.append((fn, handle))
        if fn in ('ps4000aStop', 'ps4000aCloseUnit') and handle in self.lost \
                and not (self.present and self.owner == handle):
            self.violations.append(f'{fn} on lost handle {handle}')

    def _exit(self):
        with self._lock:
            self._inside -= 1

    @staticmethod
    def _value(h):
        return h.value if isinstance(h, ctypes.c_int16) else int(h)

    def _call(self, fn, handle, body):
        self._enter(fn, handle)
        try:
            return body()
        finally:
            self._exit()

    # -- driver API ---------------------------------------------------------

    def StreamingReadyType(self, fn):
        return fn

    def ps4000aOpenUnit(self, href, serial):
        handle_obj = href._obj

        def body():
            if self.open_gate is not None:
                self.open_gate.wait()
            if not self.present:
                return PICO_NOT_FOUND
            if self.owner is not None:
                return (PICO_HARDWARE_VERSION_NOT_SUPPORTED if self.owner in self.lost
                        else PICO_NOT_FOUND)
            handle_obj.value = self.next_handle
            self.owner = self.next_handle
            self.next_handle += 1
            return PICO_OK
        return self._call('ps4000aOpenUnit', -1, body)

    def ps4000aChangePowerSource(self, h, status):
        return self._call('ps4000aChangePowerSource', self._value(h), lambda: PICO_OK)

    def ps4000aMaximumValue(self, h, vref):
        def body():
            vref._obj.value = 32767
            return PICO_OK
        return self._call('ps4000aMaximumValue', self._value(h), body)

    def ps4000aSetDeviceResolution(self, h, res):
        return self._call('ps4000aSetDeviceResolution', self._value(h),
                          lambda: pico_module.PICO_NOT_SUPPORTED_BY_THIS_DEVICE)

    def ps4000aGetDeviceResolution(self, h, ref):
        return self._call('ps4000aGetDeviceResolution', self._value(h), lambda: PICO_OK)

    def _alive(self, h):
        return self.present and self.owner == h and h not in self.lost

    def ps4000aSetChannel(self, h, *args):
        return self._call('ps4000aSetChannel', self._value(h), lambda: PICO_OK)

    def ps4000aSetSigGenBuiltIn(self, h, *args):
        hv = self._value(h)
        return self._call('ps4000aSetSigGenBuiltIn', hv,
                          lambda: PICO_OK if self._alive(hv) else PICO_NOT_RESPONDING)

    def ps4000aSetDataBuffers(self, h, *args):
        return self._call('ps4000aSetDataBuffers', self._value(h), lambda: PICO_OK)

    def ps4000aRunStreaming(self, h, *args):
        hv = self._value(h)

        def body():
            if not self._alive(hv):
                return PICO_NOT_RESPONDING
            self.streaming = hv
            return PICO_OK
        return self._call('ps4000aRunStreaming', hv, body)

    def ps4000aGetStreamingLatestValues(self, h, cb, param):
        hv = self._value(h)

        def body():
            if cb not in self.callbacks:
                self.callbacks.append(cb)
            if self.streaming == hv and self._alive(hv):
                cb(hv, self.samples_per_poll, 0, 0, 0, 0, 0, None)
            return PICO_OK                  # also after a loss, as the real driver
        return self._call('ps4000aGetStreamingLatestValues', hv, body)

    def ps4000aPingUnit(self, h):
        hv = self._value(h)

        def body():
            if self.streaming == hv:
                return PICO_BUSY
            return PICO_OK if self._alive(hv) else PICO_NOT_RESPONDING
        return self._call('ps4000aPingUnit', hv, body)

    def ps4000aStop(self, h):
        hv = self._value(h)

        def body():
            if self.streaming == hv:
                self.streaming = None
            return PICO_OK
        return self._call('ps4000aStop', hv, body)

    def ps4000aCloseUnit(self, h):
        hv = self._value(h)

        def body():
            if self.owner == hv:
                self.owner = None
            self.lost.discard(hv)
            return PICO_OK
        return self._call('ps4000aCloseUnit', hv, body)


@pytest.fixture
def driver(monkeypatch):
    fake = FakeDriver()
    monkeypatch.setattr(pico_module, 'ps', fake)
    monkeypatch.setattr(pico_module, 'assert_pico_ok', _assert_ok)
    monkeypatch.setattr(pico_module, '_WATCHDOG_TIMEOUT_S', 0.2)
    monkeypatch.setattr(pico_module, '_ABANDONED', [])     # the registry is per process
    monkeypatch.setattr(pico_module, '_RETIRED', [])
    monkeypatch.setattr(pico_module, '_RECOVERY_POLL_MIN_S', 0.01)
    monkeypatch.setattr(pico_module, '_RECOVERY_POLL_MAX_S', 0.02)
    monkeypatch.setattr(pico_module, '_OPEN_RETRY_DELAY_S', 0.0)
    monkeypatch.setattr(pico_module, '_NOT_RESPONDING_DELAY_S', 0.0)
    monkeypatch.setattr(pico_module, '_STOP_JOIN_S', 5.0)
    return fake


def _assert_ok(status):
    if status != PICO_OK:
        raise RuntimeError(f'driver status {pico_module.status_name(status)}')


def _stream(blocks: list | None = None) -> PicoScopeStream:
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 1]
    cfg.highpass_enabled = False
    sink = blocks if blocks is not None else []
    return PicoScopeStream(cfg, sink.append, serial=SERIAL)


def _wait_for(predicate, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# A loss while idle (stopped, handle open): the GUI crash of 2026-10-15
# ---------------------------------------------------------------------------

class TestIdleLoss:

    def test_absent_scope_start_fails_and_close_makes_no_call(self, driver):
        """Stop, unplug, start: a clear error, and no Stop or CloseUnit on the
        lost handle, also at close. Today's crash path was start -> error ->
        close -> CloseUnit(lost handle)."""
        stream = _stream()
        stream.start()
        stream.stop()
        old = stream._chandle.value
        driver.lose()
        mark = len(driver.calls)

        with pytest.raises(RuntimeError, match='not connected'):
            stream.start()
        stream.close()

        assert driver.calls_on(old, mark) == ['ps4000aPingUnit']
        assert driver.violations == []
        assert not stream.active

    def test_reenumerated_scope_streams_on_a_new_handle(self, driver):
        blocks = []
        stream = _stream(blocks)
        stream.start()
        stream.stop()
        old = stream._chandle.value
        old_buffers = stream._driver_buffers
        old_callback = stream._c_callback
        driver.lose()
        driver.replug()
        mark = len(driver.calls)

        stream.start()
        try:
            assert stream._chandle.value != old
            assert driver.calls_on(old, mark) == ['ps4000aPingUnit']
            assert stream._driver_buffers is not old_buffers
            assert stream._c_callback is not old_callback
            retired = pico_module._RETIRED[-1]
            assert retired[1] is old_buffers and retired[2] is old_callback
            assert _wait_for(lambda: blocks)
        finally:
            stream.close()
        assert driver.violations == []

    def test_no_loss_reuses_the_handle(self, driver):
        stream = _stream()
        stream.start()
        stream.stop()
        handle = stream._chandle.value
        stream.start()
        stream.close()
        opens = [fn for fn, _ in driver.calls if fn == 'ps4000aOpenUnit']
        assert len(opens) == 1
        assert driver.calls[-1] == ('ps4000aCloseUnit', handle)
        assert stream._abandoned == []

    def test_close_after_an_idle_loss_abandons(self, driver):
        stream = _stream()
        stream.start()
        stream.stop()
        old = stream._chandle.value
        driver.lose()
        driver.replug()
        mark = len(driver.calls)
        stream.close()
        assert driver.calls_on(old, mark) == ['ps4000aPingUnit']
        assert [h.value for h in stream._abandoned] == [old]
        assert driver.violations == []


# ---------------------------------------------------------------------------
# A loss during a stream
# ---------------------------------------------------------------------------

class TestStreamLoss:

    def test_reenumerated_scope_recovers_on_a_new_handle(self, driver):
        blocks = []
        stream = _stream(blocks)
        stream.start()
        try:
            assert _wait_for(lambda: blocks)
            old = stream._chandle.value
            old_callback = stream._c_callback
            driver.lose()
            mark = len(driver.calls)
            time.sleep(0.4)                 # past the watchdog: recovery waits
            driver.replug()
            assert _wait_for(lambda: any(b['gap'] for b in blocks))
        finally:
            stream.stop()

        after = driver.calls_on(old, mark)
        assert set(after) <= {'ps4000aGetStreamingLatestValues'}
        assert stream._chandle.value != old
        assert old_callback in [r[2] for r in pico_module._RETIRED]
        first_after_gap = next(b for b in blocks if b['gap'])
        assert first_after_gap['degraded'] is True
        assert driver.violations == []

    def test_same_node_closes_the_old_handle_then_reopens(self, driver):
        """A new open says the lost handle still owns the scope: only then are
        Stop and CloseUnit on it allowed."""
        blocks = []
        stream = _stream(blocks)
        stream.start()
        try:
            assert _wait_for(lambda: blocks)
            old = stream._chandle.value
            driver.lose(same_node=True)
            driver.replug()
            assert _wait_for(lambda: any(b['gap'] for b in blocks))
        finally:
            stream.stop()
        assert driver.calls_on(old)[-2:] == ['ps4000aStop', 'ps4000aCloseUnit']
        assert stream._abandoned == [] and pico_module.abandoned_handle_count() == 0
        assert driver.violations == []

    def test_scope_that_does_not_come_back_gives_a_fault(self, driver):
        blocks = []
        stream = _stream(blocks)
        stream.config.device_wait_s = 0.3
        stream.start()
        assert _wait_for(lambda: blocks)
        old = stream._chandle.value
        driver.lose()
        mark = len(driver.calls)
        assert _wait_for(lambda: not stream.active, timeout=5.0)
        assert 'not back within' in stream.fault
        stream.close()
        assert set(driver.calls_on(old, mark)) <= {'ps4000aGetStreamingLatestValues'}
        assert driver.violations == []

    def test_waits_with_no_time_limit_by_default(self, driver):
        blocks = []
        stream = _stream(blocks)
        assert stream.config.device_wait_s is None
        stream.start()
        try:
            assert _wait_for(lambda: blocks)
            driver.lose()
            assert _wait_for(lambda: stream.lost_since is not None)
            time.sleep(1.0)                 # many attempts with the scope absent
            assert stream.active and stream.fault is None
            driver.replug()
            assert _wait_for(lambda: any(b['gap'] for b in blocks))
            assert stream.lost_since is None
        finally:
            stream.stop()
        assert driver.violations == []

    def test_still_waiting_is_logged(self, driver, monkeypatch, caplog):
        monkeypatch.setattr(pico_module, '_RECOVERY_LOG_EVERY_S', 0.1)
        blocks = []
        stream = _stream(blocks)
        stream.start()
        assert _wait_for(lambda: blocks)
        with caplog.at_level(logging.WARNING):
            driver.lose()
            assert _wait_for(lambda: 'still waiting for the scope' in caplog.text)
        stream.stop()

    def test_abandoned_handle_limit_counts_for_the_whole_process(self, driver, monkeypatch):
        """A reconnect makes a new stream object; the lost handles of the old
        one still count, because the driver still holds them."""
        monkeypatch.setattr(pico_module, '_MAX_ABANDONED_HANDLES', 2)
        first = _stream()
        first.start()
        first.stop()
        driver.lose()
        driver.replug()
        first.close()                       # abandons: 1
        del first

        blocks = []
        second = _stream(blocks)
        second.start()
        assert _wait_for(lambda: blocks)
        driver.lose()                       # abandons: 2, the limit
        driver.replug()
        assert _wait_for(lambda: not second.active, timeout=5.0)
        assert 'restart the program' in second.fault
        assert pico_module.abandoned_handle_count() == 2
        assert len(pico_module._RETIRED) == 2   # references kept after `del first`
        assert driver.violations == []

    def test_abandoned_handle_limit_ends_in_a_fault(self, driver, monkeypatch):
        monkeypatch.setattr(pico_module, '_MAX_ABANDONED_HANDLES', 2)
        blocks = []
        stream = _stream(blocks)
        stream.start()
        assert _wait_for(lambda: blocks)
        driver.lose()
        driver.replug()
        assert _wait_for(lambda: any(b['gap'] for b in blocks))
        driver.lose()
        driver.replug()
        assert _wait_for(lambda: not stream.active, timeout=5.0)
        assert 'restart the program' in stream.fault
        opens = [fn for fn, _ in driver.calls if fn == 'ps4000aOpenUnit']
        assert len(opens) == 2              # the start and the first recovery
        assert driver.violations == []

    def test_stop_during_recovery_waits_and_makes_no_call_on_lost_handle(self, driver):
        blocks = []
        stream = _stream(blocks)
        stream.start()
        assert _wait_for(lambda: blocks)
        old = stream._chandle.value
        driver.open_gate = threading.Event()
        driver.lose()
        mark = len(driver.calls)
        # Recovery is now blocked inside OpenUnit.
        assert _wait_for(lambda: ('ps4000aOpenUnit', -1) in driver.calls[mark:])

        done = threading.Event()
        threading.Thread(target=lambda: (stream.stop(), done.set()), daemon=True).start()
        time.sleep(0.1)
        assert not done.is_set()            # stop() waits for the thread in the driver
        driver.open_gate.set()
        assert done.wait(3.0)

        assert set(driver.calls_on(old, mark)) <= {'ps4000aGetStreamingLatestValues'}
        assert stream._thread is not None and not stream._thread.is_alive()
        assert driver.violations == []

    def test_stop_while_a_recovery_succeeds_stops_the_new_handle(self, driver):
        """The recovery finishes on a new, good handle while stop() waits. The
        stale data of the lost handle must not make stop() abandon the new one."""
        blocks = []
        stream = _stream(blocks)
        stream.start()
        assert _wait_for(lambda: blocks)
        driver.open_gate = threading.Event()
        driver.lose()
        mark = len(driver.calls)
        assert _wait_for(lambda: ('ps4000aOpenUnit', -1) in driver.calls[mark:])
        time.sleep(pico_module._FRESH_DATA_S + 0.1)   # the lost handle's data is now stale

        done = threading.Event()
        threading.Thread(target=lambda: (stream.stop(), done.set()), daemon=True).start()
        time.sleep(0.05)
        driver.replug()
        driver.open_gate.set()
        assert done.wait(3.0)

        new = stream._chandle.value
        assert driver.calls_on(new)[-1] == 'ps4000aStop'
        assert len(stream._abandoned) == 1
        driver.open_gate = None
        stream.start()                      # the same handle starts again
        stream.close()
        assert driver.violations == []

    def test_start_refused_while_the_old_poll_thread_is_alive(self, driver):
        stream = _stream()
        stream._thread = threading.Thread(target=time.sleep, args=(0.5,), daemon=True)
        stream._thread.start()
        with pytest.raises(RuntimeError, match='still'):
            stream.start()

    def test_stop_in_the_silence_window_abandons_instead_of_stop(self, driver, monkeypatch):
        """A stop after the loss but before the watchdog: Stop on the absent
        handle can crash, so the stale data makes it abandon the handle."""
        monkeypatch.setattr(pico_module, '_WATCHDOG_TIMEOUT_S', 10.0)
        monkeypatch.setattr(pico_module, '_FRESH_DATA_S', 0.05)
        blocks = []
        stream = _stream(blocks)
        stream.start()
        assert _wait_for(lambda: blocks)
        old = stream._chandle.value
        driver.lose()
        mark = len(driver.calls)
        time.sleep(0.15)
        stream.stop()
        stream.close()
        assert set(driver.calls_on(old, mark)) <= {'ps4000aGetStreamingLatestValues'}
        assert driver.violations == []


# ---------------------------------------------------------------------------
# Status handling
# ---------------------------------------------------------------------------

def test_open_waits_longer_after_not_responding(monkeypatch):
    """PICO_NOT_RESPONDING is 7 in picosdk (14 is PICO_INVALID_TIMEBASE)."""
    sleeps = []
    monkeypatch.setattr(pico_module.time, 'sleep', sleeps.append)
    monkeypatch.setattr(pico_module, '_open_once', lambda h, serial='': 7)
    assert pico_module._open_unit(ctypes.c_int16()) is False
    assert sleeps == [pico_module._NOT_RESPONDING_DELAY_S] * (pico_module._MAX_OPEN_ATTEMPTS - 1)


def test_zero_rate_window_is_not_a_bandwidth_fault(monkeypatch, caplog):
    stream = _stream()
    clock = {'t': 1000.0}
    monkeypatch.setattr(pico_module.time, 'monotonic', lambda: clock['t'])
    stream._actual_raw_samplerate = 76800.0
    stream._rate_window_start = stream._rate_last_check = clock['t']
    with caplog.at_level(logging.WARNING):
        for _ in range(pico_module._RATE_DEGRADED_CONSECUTIVE + 2):
            clock['t'] += pico_module._RATE_CHECK_INTERVAL_S
            stream._rate_window_samples = 0
            stream._check_rate_degradation()
    assert stream.degraded is False
    assert 'bandwidth' not in caplog.text


def test_poll_error_status_is_logged_once(caplog):
    stream = _stream()
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            stream._note_poll_status(PICO_NOT_RESPONDING)
        stream._note_poll_status(PICO_BUSY)
        stream._note_poll_status(PICO_OK)
    assert caplog.text.count('PICO_NOT_RESPONDING') == 1
    assert 'PICO_BUSY' not in caplog.text


# ---------------------------------------------------------------------------
# DataCollector
# ---------------------------------------------------------------------------

class _FailingStream:
    def __init__(self, events):
        self.events = events
        self.active = False

    def start(self):
        raise RuntimeError('PicoScope TEST/0001 not connected')

    def close(self):
        self.events.append('close')


def test_collector_logs_a_start_error_before_the_teardown(caplog):
    events = []

    class _Recorder(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                events.append('log')

    dc = vc.DataCollector(config=vc.AcquisitionSettings())
    dc.sensor = object()
    dc.stream = _FailingStream(events)
    handler = _Recorder()
    logging.getLogger('rev80.collector').addHandler(handler)
    try:
        dc.start_stream()
    finally:
        logging.getLogger('rev80.collector').removeHandler(handler)
    assert events == ['log', 'close']
    assert dc.stream is None
    assert 'not connected' in dc.start_error
