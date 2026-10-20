#!/usr/bin/env python3
"""pico-loss-probe — which PS4000A driver calls are safe on a lost handle.

Opens the scope, streams, makes the scope disappear, and then makes one driver
call on the old handle. Each run is a child process, so a native crash
(SIGSEGV, SIGBUS) shows as the child's exit signal and does not end the probe.
The child writes one JSON line for each event, and a "calling" line before
every driver call, so the parent knows which call was in progress at a crash.

Scenarios (the plan: .claude/plans/2026-10-15-device-loss-hardening.md):

    S0   no driver call after the loss: wait 10 s, then exit (the baseline)
    S1   GetStreamingLatestValues for 5 s after the loss
    S2   Stop while the scope is absent
    S3a  CloseUnit while absent, no Stop first
    S3b  Stop, then CloseUnit, while absent
    S3c  CloseUnit after the scope is back
    S3d  Stop, then CloseUnit, after the scope is back
    S4a  PingUnit while absent
    S4b  PingUnit after the scope is back
    S5   EnumerateUnits while absent, then until the serial is back
    S6   OpenUnit by serial after the scope is back, old handle not closed,
         then stream 2 s on the new handle
    S7   S6 for 20 losses in one process, no handle ever closed

Idle scenarios: stream, Stop while the scope is present, then the loss. The
handle stays open and idle, as in the GUI between a stop and the next start.

    S8a  no loss (control): PingUnit, EnumerateUnits, OpenUnit by serial with
         the old handle still open
    S8b  absent: PingUnit, EnumerateUnits
    S8c  after the scope is back: PingUnit, EnumerateUnits until the serial is
         listed, OpenUnit by serial (old handle not closed)
    S8d  absent: the app's start sequence on the old handle (SetChannel,
         SetSigGenBuiltIn, SetDataBuffers, RunStreaming); no CloseUnit
    S8e  S8d after the scope is back
    S8f  S8d, then CloseUnit (the GUI crash of 2026-10-15; reference only)

Loss methods (Linux only):

    authorized    write 0, then 1, to /sys/bus/usb/devices/<dev>/authorized
    port          write 1, then 0, to the hub port's "disable" file (powers
                  the port off: nearer to an over-current event)
    manual        the operator unplugs and replugs the cable when told

The two sysfs methods need write access to the sysfs file: run the probe as
root, or give write access once (it stays until the device or hub goes away):

    sudo chmod o+w /sys/bus/usb/devices/<dev>/authorized

    sudo .venv/bin/python scripts/pico-loss-probe.py --method authorized
    sudo .venv/bin/python scripts/pico-loss-probe.py -s S3c S3d --repeat 5
    .venv/bin/python scripts/pico-loss-probe.py --method manual -s S3d --repeat 5

Results go to a JSON-lines file (--out), one line for each run, and a summary
table is printed at the end. The time from loss to re-enumeration is in the
"present_after_s" field (sysfs) and, for S5, in the "enumerated" event.
"""

import argparse
import ctypes
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

USB_DEVICES = Path('/sys/bus/usb/devices')
PICO_VID = '0ce9'                       # Pico Technology USB vendor ID

ALL_SCENARIOS = ('S0', 'S1', 'S2', 'S3a', 'S3b', 'S3c', 'S3d',
                 'S4a', 'S4b', 'S5', 'S6', 'S7',
                 'S8a', 'S8b', 'S8c', 'S8d', 'S8e', 'S8f')
IDLE_SCENARIOS = ('S8a', 'S8b', 'S8c', 'S8d', 'S8e', 'S8f')

STREAM_INTERVAL_NS = 13025              # the app's request at osr 3, 25600 Hz raw
DRIVER_BUFFER_SAMPLES = 1000            # the app's rolling buffer
GOOD_DATA_S = 1.5                       # stream this long before the loss
SILENCE_S = 2.0                         # no callback data this long = lost
RETURN_TIMEOUT_S = 60.0                 # wait this long for the scope to come back
OPEN_RETRY_S = 0.25
S7_CYCLES = 20


# ---------------------------------------------------------------------------
# sysfs: driver-independent view of the scope
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def pico_devices() -> list[str]:
    """sysfs names (for example '1-1.2') of the USB devices with the Pico VID."""
    if not USB_DEVICES.is_dir():
        return []
    return sorted(d.name for d in USB_DEVICES.iterdir()
                  if ':' not in d.name and _read(d / 'idVendor') == PICO_VID)


def pico_present() -> bool:
    """True if a Pico device is authorized and has a configured interface."""
    for name in pico_devices():
        dev = USB_DEVICES / name
        if _read(dev / 'authorized') == '1' and any(dev.glob(f'{name}:*')):
            return True
    return False


def port_disable_file(dev: str) -> Path:
    """The hub-port 'disable' file for the sysfs device name `dev`."""
    if '.' in dev:
        hub, port = dev.rsplit('.', 1)
        return USB_DEVICES / f'{hub}:1.0' / f'{hub}-port{port}' / 'disable'
    bus, port = dev.split('-', 1)
    return USB_DEVICES / f'{bus}-0:1.0' / f'usb{bus}-port{port}' / 'disable'


class LossSwitch:
    """Makes the scope disappear and come back through sysfs, or asks the operator."""

    def __init__(self, method: str, dev: str):
        self.method = method
        self.dev = dev
        self.lost = False
        if method == 'authorized':
            self._file, self._off, self._on = USB_DEVICES / dev / 'authorized', '0', '1'
        elif method == 'port':
            self._file, self._off, self._on = port_disable_file(dev), '1', '0'
        else:
            self._file = None
        if self._file is not None and not self._file.exists():
            sys.exit(f'ERROR: {self._file} does not exist')
        if self._file is not None and not os.access(self._file, os.W_OK):
            sys.exit(f'ERROR: cannot write {self._file}. Run as root, or once: '
                     f'sudo chmod o+w {self._file}')

    def remove(self) -> None:
        self.lost = True
        if self._file is None:
            print('\n>>> REMOVE the scope now.', flush=True)
        else:
            self._file.write_text(self._off)

    def restore(self) -> None:
        if not self.lost:
            return
        self.lost = False
        if self._file is None:
            print('\n>>> RECONNECT the scope now.', flush=True)
        else:
            self._file.write_text(self._on)


# ---------------------------------------------------------------------------
# Child: one scenario against the driver
# ---------------------------------------------------------------------------

class Probe:
    """The driver side. Every buffer and callback stays referenced until exit,
    so the driver never writes into freed memory through an abandoned handle."""

    def __init__(self, serial: str, channels: int | None):
        from picosdk.constants import PICO_STATUS
        from picosdk.ps4000a import ps4000a as ps
        self.ps = ps
        self.names = {v: k for k, v in PICO_STATUS.items()}
        self.serial = serial
        self.channels = channels
        self.keep: list = []            # buffers and callbacks, never released
        self.samples = 0
        self.last_data = time.monotonic()
        self.t_loss: float | None = None

    # -- output -----------------------------------------------------------

    def emit(self, event: str, **fields) -> None:
        if self.t_loss is not None:
            fields['t_after_loss_s'] = round(time.monotonic() - self.t_loss, 3)
        print(json.dumps({'event': event, **fields}), flush=True)

    def call(self, fn: str, *args) -> int:
        """Run one driver call, with a 'calling' line before and the status after."""
        present = pico_present()
        self.emit('calling', fn=fn, present=present)
        t0 = time.monotonic()
        status = getattr(self.ps, fn)(*args)
        self.emit('status', fn=fn, status=status, name=self.names.get(status, '?'),
                  ms=round((time.monotonic() - t0) * 1e3, 1),
                  present_before=present, present_after=pico_present())
        return status

    # -- device -----------------------------------------------------------

    def enumerate(self) -> list[str]:
        count = ctypes.c_int16(0)
        buf = ctypes.create_string_buffer(256)
        length = ctypes.c_int16(256)
        status = self.call('ps4000aEnumerateUnits',
                           ctypes.byref(count), buf, ctypes.byref(length))
        if status != 0 or count.value == 0:
            return []
        return [s.strip() for s in buf.value.decode(errors='replace').split(',') if s.strip()]

    def open(self) -> tuple[int, ctypes.c_int16]:
        handle = ctypes.c_int16()
        self.keep.append(handle)
        status = self.call('ps4000aOpenUnit', ctypes.byref(handle), self.serial.encode())
        if status in (282, 286):        # USB power only; tell the scope so
            status = self.call('ps4000aChangePowerSource', handle, status)
        self.emit('opened', status=status, handle=handle.value)
        return status, handle

    def open_with_retry(self) -> ctypes.c_int16 | None:
        t0 = time.monotonic()
        attempts = 0
        while time.monotonic() - t0 < RETURN_TIMEOUT_S:
            attempts += 1
            status, handle = self.open()
            if status == 0:
                self.emit('open_ok', attempts=attempts,
                          s_after_present=round(time.monotonic() - t0, 3))
                return handle
            time.sleep(OPEN_RETRY_S)
        self.emit('open_gave_up', attempts=attempts)
        return None

    def start_stream(self, handle: ctypes.c_int16):
        ps = self.ps
        n_ch = 0
        for ch in range(8):
            if self.channels is not None and ch >= self.channels:
                status = ps.ps4000aSetChannel(handle, ch, 0, 1, 7, 0.0)
                continue
            status = ps.ps4000aSetChannel(handle, ch, 1, 1, 7, 0.0)   # AC, +-2 V
            if status != 0:
                break
            n_ch += 1
        for ch in range(n_ch):
            buf = (ctypes.c_int16 * DRIVER_BUFFER_SAMPLES)()
            self.keep.append(buf)
            ps.ps4000aSetDataBuffers(handle, ch, buf, None, DRIVER_BUFFER_SAMPLES, 0,
                                     ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'])
        interval = ctypes.c_int32(STREAM_INTERVAL_NS)
        status = self.call('ps4000aRunStreaming', handle, ctypes.byref(interval),
                           ps.PS4000A_TIME_UNITS['PS4000A_NS'], 0, 4096 * 4, 0, 1,
                           ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
                           DRIVER_BUFFER_SAMPLES)
        if status != 0:
            raise RuntimeError(f'RunStreaming status {status}')

        def on_data(_h, n, _start, _ovf, _trig_at, _trig, _auto, _param):
            if n:
                self.samples += n
                self.last_data = time.monotonic()

        cb = ps.StreamingReadyType(on_data)
        self.keep.append(cb)
        self.emit('stream_started', channels=n_ch, interval_ns=interval.value)
        return cb

    def stream_for(self, handle, cb, seconds: float) -> None:
        """Poll for `seconds` with no loss expected; report the rate."""
        t0, n0 = time.monotonic(), self.samples
        while time.monotonic() - t0 < seconds:
            self.ps.ps4000aGetStreamingLatestValues(handle, cb, None)
            time.sleep(0.001)
        rate = (self.samples - n0) / seconds
        self.emit('stream_ok', samples_per_s=round(rate))

    def poll_until_loss(self, handle, cb) -> None:
        """Poll the driver until sysfs or silence shows the loss."""
        statuses: Counter = Counter()
        self.last_data = time.monotonic()
        while True:
            if not pico_present():
                cause = 'sysfs'
                break
            if time.monotonic() - self.last_data > SILENCE_S:
                cause = 'silence'
                break
            statuses[self.ps.ps4000aGetStreamingLatestValues(handle, cb, None)] += 1
            time.sleep(0.001)
        self.t_loss = time.monotonic()
        self.emit('lost', cause=cause,
                  poll_statuses={self.names.get(k, str(k)): v for k, v in statuses.items()})

    def wait_absent(self) -> bool:
        """Wait until sysfs shows the scope gone; this is the loss time."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < RETURN_TIMEOUT_S:
            if not pico_present():
                self.t_loss = time.monotonic()
                self.emit('lost', cause='sysfs')
                return True
            time.sleep(0.05)
        self.emit('not_removed')
        return False

    def wait_present(self) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < RETURN_TIMEOUT_S:
            if pico_present():
                self.emit('present')
                return True
            time.sleep(0.05)
        self.emit('not_back')
        return False

    # -- scenarios --------------------------------------------------------

    def run(self, scenario: str) -> None:
        if not self.serial:
            serials = self.enumerate()
            if not serials:
                self.emit('error', text='no scope found')
                sys.exit(2)
            self.serial = serials[0]
        handle = self.open_with_retry()
        if handle is None:
            sys.exit(2)
        cb = self.start_stream(handle)
        self.stream_for(handle, cb, GOOD_DATA_S)
        if scenario in IDLE_SCENARIOS:
            self.run_idle(scenario, handle)
            self.emit('done')
            return
        cycles = S7_CYCLES if scenario == 'S7' else 1
        for cycle in range(1, cycles + 1):
            self.emit('streaming', cycle=cycle)    # the parent removes the scope now
            self.poll_until_loss(handle, cb)
            handle, cb = self.after_loss(scenario, handle, cb)
            self.t_loss = None
            if handle is None:
                break
        self.emit('done')

    def after_loss(self, scenario: str, handle, cb):
        ps = self.ps
        if scenario == 'S0':
            time.sleep(10.0)
            self.emit('idle_ok')
        elif scenario == 'S1':
            self.emit('calling', fn='ps4000aGetStreamingLatestValues x5s')
            statuses: Counter = Counter()
            t0 = time.monotonic()
            while time.monotonic() - t0 < 5.0:
                statuses[ps.ps4000aGetStreamingLatestValues(handle, cb, None)] += 1
                time.sleep(0.001)
            self.emit('statuses', fn='ps4000aGetStreamingLatestValues',
                      counts={self.names.get(k, str(k)): v for k, v in statuses.items()})
        elif scenario in ('S2', 'S3b'):
            self.call('ps4000aStop', handle)
            if scenario == 'S3b':
                self.call('ps4000aCloseUnit', handle)
        elif scenario == 'S3a':
            self.call('ps4000aCloseUnit', handle)
        elif scenario == 'S4a':
            self.call('ps4000aPingUnit', handle)
        elif scenario in ('S3c', 'S3d', 'S4b'):
            if self.wait_present():
                time.sleep(1.0)         # let the kernel finish the enumeration
                if scenario == 'S4b':
                    self.call('ps4000aPingUnit', handle)
                else:
                    if scenario == 'S3d':
                        self.call('ps4000aStop', handle)
                    self.call('ps4000aCloseUnit', handle)
        elif scenario == 'S5':
            self.emit('enumerated', serials=self.enumerate())
            t0 = time.monotonic()
            while time.monotonic() - t0 < RETURN_TIMEOUT_S:
                serials = self.enumerate()
                if self.serial in serials:
                    self.emit('enumerated', serials=serials, back=True)
                    break
                time.sleep(0.2)
            else:
                self.emit('enumerated', serials=[], back=False)
        elif scenario in ('S6', 'S7'):
            if not self.wait_present():
                return None, None
            new = self.open_with_retry()
            if new is None:
                return None, None
            new_cb = self.start_stream(new)
            self.stream_for(new, new_cb, 2.0)
            return new, new_cb
        return None, None


    # -- idle scenarios ---------------------------------------------------

    def ping_and_enumerate(self, handle) -> None:
        self.call('ps4000aPingUnit', handle)
        self.emit('enumerated', serials=self.enumerate())

    def open_probe(self, seconds: float) -> None:
        """OpenUnit by serial into new handles until PICO_OK or `seconds`."""
        t0 = time.monotonic()
        while True:
            status, _new = self.open()
            if status == 0 or time.monotonic() - t0 > seconds:
                return
            time.sleep(OPEN_RETRY_S)

    def start_sequence(self, handle) -> None:
        """The app's start() calls on `handle`, each one logged."""
        ps = self.ps
        for ch in range(8):
            enabled = self.channels is None or ch < self.channels
            if self.call('ps4000aSetChannel', handle, ch, int(enabled), 1, 7, 0.0) != 0:
                break
        self.call('ps4000aSetSigGenBuiltIn', handle, 0, 1000000,
                  ps.PS4000A_WAVE_TYPE['PS4000A_SINE'], 20.0, 20.0, 0, 1,
                  ps.PS4000A_SWEEP_TYPE['PS4000A_UP'], 0, 0, 0,
                  ps.PS4000A_SIGGEN_TRIG_TYPE['PS4000A_SIGGEN_RISING'],
                  ps.PS4000A_SIGGEN_TRIG_SOURCE['PS4000A_SIGGEN_NONE'],
                  ctypes.c_int16(0))
        buf = (ctypes.c_int16 * DRIVER_BUFFER_SAMPLES)()
        self.keep.append(buf)
        self.call('ps4000aSetDataBuffers', handle, 0, buf, None, DRIVER_BUFFER_SAMPLES, 0,
                  ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'])
        interval = ctypes.c_int32(STREAM_INTERVAL_NS)
        self.call('ps4000aRunStreaming', handle, ctypes.byref(interval),
                  ps.PS4000A_TIME_UNITS['PS4000A_NS'], 0, 4096 * 4, 0, 1,
                  ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
                  DRIVER_BUFFER_SAMPLES)

    def run_idle(self, scenario: str, handle) -> None:
        self.call('ps4000aStop', handle)        # scope present: a normal stop
        time.sleep(0.5)
        if scenario == 'S8a':
            self.ping_and_enumerate(handle)
            self.open_probe(0.0)
            return
        self.emit('idle')                       # the parent removes the scope now
        if not self.wait_absent():
            return
        time.sleep(1.0)
        if scenario in ('S8c', 'S8e'):
            if not self.wait_present():
                return
            time.sleep(1.0)                     # let the kernel finish the enumeration
        if scenario in ('S8b', 'S8c'):
            self.ping_and_enumerate(handle)
            if scenario == 'S8c':
                t0 = time.monotonic()
                while (self.serial not in self.enumerate()
                       and time.monotonic() - t0 < RETURN_TIMEOUT_S):
                    time.sleep(0.2)
                self.open_probe(15.0)
        else:
            self.start_sequence(handle)
            if scenario == 'S8f':
                self.call('ps4000aCloseUnit', handle)


def child_main(args) -> int:
    global RETURN_TIMEOUT_S
    RETURN_TIMEOUT_S = args.return_timeout
    import faulthandler
    faulthandler.enable()               # a native crash prints the Python stack to stderr
    Probe(args.serial, args.channels).run(args.child)
    return 0


# ---------------------------------------------------------------------------
# Parent: run the scenarios, cause the losses, record the outcome
# ---------------------------------------------------------------------------

def _reader(stream, q: queue.Queue) -> None:
    for line in stream:
        q.put(line)
    q.put(None)


def wait_device(timeout: float) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pico_present():
            return True
        time.sleep(0.1)
    return False


def run_one(args, scenario: str, index: int, switch: LossSwitch, log_dir: Path) -> dict:
    stderr_path = log_dir / f'{scenario}-{index}.stderr'
    cmd = [sys.executable, __file__, '--child', scenario]
    if args.serial:
        cmd += ['--serial', args.serial]
    if args.channels is not None:
        cmd += ['--channels', str(args.channels)]
    cmd += ['--return-timeout', str(args.return_timeout)]
    with open(stderr_path, 'w') as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()

    events: list[dict] = []
    t_start = time.monotonic()
    restore_at: float | None = None
    t_removed: float | None = None
    present_after: list[float] = []
    timed_out = False
    try:
        while True:
            if restore_at is not None and time.monotonic() >= restore_at:
                switch.restore()
                restore_at = None
            if time.monotonic() - t_start > args.timeout:
                timed_out = True
                proc.kill()
                break
            try:
                line = q.get(timeout=0.05)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = {'event': 'text', 'text': line.rstrip()}
            events.append(ev)
            if args.verbose:
                print(f'    {ev}', flush=True)
            if ev['event'] in ('streaming', 'idle'):
                switch.remove()
                t_removed = time.monotonic()
                if switch.method != 'manual':
                    restore_at = t_removed + args.absent_s
            elif ev['event'] == 'lost' and scenario in ('S8c', 'S8e'):
                switch.restore()        # these scenarios need the scope back
            elif ev['event'] == 'present' and t_removed is not None:
                present_after.append(round(time.monotonic() - t_removed, 3))
        proc.wait(timeout=10)
    finally:
        switch.restore()

    rc = proc.returncode
    # A crash is in a driver call when the child's last line is 'calling'.
    last = next((e for e in reversed(events) if e['event'] != 'text'), None)
    in_call = last is not None and last['event'] == 'calling'
    last_calling = last['fn'] if in_call else None
    done = any(e['event'] == 'done' for e in events)
    return {
        'scenario': scenario,
        'run': index,
        'method': switch.method,
        'returncode': rc,
        'signal': signal.Signals(-rc).name if rc is not None and rc < 0 else None,
        'timed_out': timed_out,
        'done': done,
        'crashed_in': last_calling if rc != 0 else None,
        'crash_after_done': bool(done and rc is not None and rc < 0),
        'present_after_s': present_after,
        'events': events,
        'stderr': str(stderr_path),
    }


def describe(result: dict) -> str:
    if result['timed_out']:
        return f'HANG (killed after timeout); last call {result["crashed_in"]}'
    if result['signal']:
        where = ('at exit, after done' if result['crash_after_done']
                 else f'in {result["crashed_in"]}')
        return f'{result["signal"]} {where}'
    if result['returncode'] != 0:
        return f'exit {result["returncode"]}'
    calls = [f'{e["fn"].removeprefix("ps4000a")}={e["name"]}'
             for e in result['events'] if e['event'] == 'status'
             and (e.get('t_after_loss_s') is not None or result['scenario'] == 'S8a')]
    return 'ok  ' + ' '.join(calls)


def parent_main(args) -> int:
    if sys.platform != 'linux':
        sys.exit('ERROR: the probe reads sysfs and runs on Linux only')
    devs = pico_devices()
    if args.method != 'manual':
        if args.usb_device:
            dev = args.usb_device
        elif len(devs) == 1:
            dev = devs[0]
        else:
            sys.exit(f'ERROR: found Pico USB devices {devs}; give --usb-device')
    else:
        dev = devs[0] if devs else ''
    if not wait_device(5.0):
        sys.exit('ERROR: no PicoScope present in sysfs')
    switch = LossSwitch(args.method, dev)

    log_dir = Path(args.out).with_suffix('')
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f'USB device {dev or "?"}, method {args.method}, '
          f'results {args.out}, child stderr in {log_dir}/', flush=True)

    results = []
    with open(args.out, 'a') as out:
        for scenario in args.scenarios:
            for i in range(1, args.repeat + 1):
                print(f'{scenario} run {i}/{args.repeat} ...', flush=True)
                result = run_one(args, scenario, i, switch, log_dir)
                results.append(result)
                out.write(json.dumps(result) + '\n')
                out.flush()
                print(f'  {describe(result)}', flush=True)
                if switch.method == 'manual' and not pico_present():
                    print('>>> RECONNECT the scope now.', flush=True)
                if not wait_device(args.return_timeout):
                    print('ERROR: the scope did not come back; stopping', flush=True)
                    return summarise(results)
                time.sleep(args.settle_s)
    return summarise(results)


def summarise(results: list[dict]) -> int:
    print('\nSummary')
    by_scenario: dict[str, list[dict]] = {}
    for r in results:
        by_scenario.setdefault(r['scenario'], []).append(r)
    for scenario, rs in by_scenario.items():
        outcomes = Counter(describe(r) for r in rs)
        print(f'  {scenario}:')
        for text, n in outcomes.most_common():
            print(f'    {n} x {text}')
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split('\n', 2)[2])
    p.add_argument('-s', '--scenarios', nargs='+', default=list(ALL_SCENARIOS),
                   choices=ALL_SCENARIOS, metavar='ID',
                   help='scenarios to run (default: all)')
    p.add_argument('--repeat', type=int, default=5, help='runs per scenario (default 5)')
    p.add_argument('--method', choices=('authorized', 'port', 'manual'),
                   default='authorized', help='how to lose the scope (default authorized)')
    p.add_argument('--absent-s', type=float, default=3.0,
                   help='seconds the scope stays away (sysfs methods; default 3)')
    p.add_argument('--settle-s', type=float, default=3.0,
                   help='seconds between runs after the scope is back (default 3)')
    p.add_argument('--usb-device', default='',
                   help='sysfs device name, for example 1-1 (default: the only Pico device)')
    p.add_argument('--serial', default='', help='scope serial (default: the first found)')
    p.add_argument('--channels', type=int, default=None,
                   help='channels to stream (default: all the scope has)')
    p.add_argument('--return-timeout', type=float, default=RETURN_TIMEOUT_S,
                   help='seconds to wait for the scope to come back (default 60)')
    p.add_argument('--timeout', type=float, default=120.0,
                   help='kill a child after this many seconds (default 120)')
    p.add_argument('--out', default='pico-loss-probe.jsonl', help='results file (appended)')
    p.add_argument('-v', '--verbose', action='store_true', help='print every child event')
    p.add_argument('--child', choices=ALL_SCENARIOS, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.child:
        return child_main(args)
    return parent_main(args)


if __name__ == '__main__':
    sys.exit(main())
