# Survive the loss of the PicoScope during a stream

Branch: `fix/device-loss-recovery` (from `main`, which is `develop` plus the 0.1.4 release note).

## Context

Removing the PicoScope while it streams can crash Rev80. This is a known
issue. On 2026-10-14 it occurred three times in 13 minutes on `rev80pi-01`
(Raspberry Pi 5, PicoScope 4824A, 8 channels, GUI):

| Time | Kernel | Rev80 |
|---|---|---|
| 22:42:16.746 | over-current on all USB ports, scope re-enumerates | 22:42:16.786 `PICO_NOT_RESPONDING` at stream start |
| 22:43:13 | over-current on all USB ports | 22:43:16 rate "degraded, 0 Hz"; 22:43:18 "no data for 5.0 s", recovery; **SIGSEGV** in `_try_recover` (`ps4000aCloseUnit`) |
| 22:50:50 | over-current on all USB ports | 22:50:53 "degraded, 0 Hz"; 22:50:55 recovery; **SIGBUS** at the same line |

The power fault is a hardware matter. The Pi detected a 3 A supply, so it
limits all USB ports together to 600 mA, and the scope declares 896 mA. A
powered hub or a 5 A supply corrects it. But a unit in the field can always
lose the scope: a cable, a hub, an ESD event, a power dip. The software must
survive it: no native crash, a recovery when the scope comes back, and a
clear stop when it does not.

Intended outcome: a scope that disappears and comes back within the recovery
window gives a short gap and then data again. A scope that does not come back
gives a logged, clean stop. In headless mode the process exits with a non-zero
code, so a service manager can restart it. In no case does the process die by
a signal.

## Root causes found by reading the code

1. **Recovery calls the driver with the handle of a device that is gone.**
   `_try_recover()` (`picoscope.py`) calls `ps4000aStop` and then
   `ps4000aCloseUnit` on `self._chandle`. After a USB disconnect the driver's
   state for that handle refers to a device that no longer exists. Both crashes
   are in `ps4000aCloseUnit`. The `try/except Exception: pass` around the calls
   cannot catch a native crash. Also, ctypes driver calls return a status and do
   not raise, so these `except` clauses never run and the status is ignored.
2. **Two threads can be in the driver at the same time.** `stop()` waits 3 s
   for the poll thread and then calls `ps4000aStop` even if the thread is still
   alive. Recovery takes longer than 3 s (3 attempts, 1 s sleep each, plus the
   open retries). A user stop during recovery thus runs driver calls in parallel
   with `_open_device()`.
3. **The `PICO_NOT_RESPONDING` constant is wrong.** `_open_unit()` and
   `_open_unit_by_serial()` use 14. In picosdk 14 is `PICO_INVALID_TIMEBASE`;
   `PICO_NOT_RESPONDING` is 7 (the Pi log shows `status=7`). The longer delay
   after "not responding" never applies. The comments also swap 282 and 286
   (282 is `PICO_POWER_SUPPLY_NOT_CONNECTED`, 286 is
   `PICO_USB3_0_DEVICE_NON_USB3_0_PORT`).
4. **The rate watchdog gives a wrong diagnosis at 0 Hz.** It logs "USB/bus
   bandwidth ceiling, not a device hang" when no sample arrived. 0 Hz is a lost
   device. The silence watchdog owns that case.
5. **Headless does not notice a dead stream.** When recovery gives up, the
   stream sets `_active = False` and the poll thread exits. The headless loop
   waits on `new_frame_event` with a 1 s timeout and continues for ever. It
   logs nothing and records nothing. For an unattended logger this is a silent
   stop. (The GUI reaction is not known yet; check it in step 6.)
6. **The callback pointer of the old stream is released during recovery.**
   (Found in step 0.) `_poll_loop` makes a new `StreamingReadyType` after a
   recovery and drops the old one. The driver keeps threads on a lost handle
   (see "Step 0 results"), and the driver buffers of the old handle are given
   again to the new handle. Keep every callback pointer and every buffer that a
   handle received for the life of the stream object.

## Step 0: measure the driver's behaviour on hardware first — DONE 2026-10-15

Probe: `scripts/pico-loss-probe.py`. Each run is a child process; a "calling"
line before each driver call names the call that was in progress at a crash.
It keeps every buffer and callback referenced until exit.

Set-up: x86-64 Linux, 8-channel PicoScope 4000A (4824A class), 5 Gbit/s USB
port, `libps4000a` 2.2.257-2r7890, 8 channels at 13025 ns (76.8 kHz ADC).
Loss method `authorized` = `echo 0`, then `1`, to
`/sys/bus/usb/devices/<dev>/authorized`, 3 s absent. "Manual" = physical
unplug and replug, about 5 s.

### Step 0 results

| ID | After the loss | `authorized` (5 runs) | Physical unplug |
|---|---|---|---|
| S0 | no driver call; exit 10 s later | 5/5 clean | — |
| S1 | `GetStreamingLatestValues` for 5 s | 5/5 clean; status `PICO_OK` | — |
| S2 | `Stop`, absent | **4/5 SIGSEGV** | — |
| S3a | `CloseUnit`, absent | **3/5 SIGSEGV** | — |
| S3b | `Stop` + `CloseUnit`, absent | **1/5 SIGSEGV** (in `Stop`) | — |
| S3c | `CloseUnit`, after return | 5/5 clean, `PICO_OK` | — |
| S3d | `Stop` + `CloseUnit`, after return | 5/5 clean, `PICO_OK` | **2/2 SIGSEGV in `CloseUnit`** (`Stop` gave `PICO_OK`) |
| S4a/b | `PingUnit`, absent / after return | 10/10 clean, `PICO_BUSY` | — |
| S5 | `EnumerateUnits` | clean; `PICO_NOT_FOUND` in 33–60 ms while absent; serial listed 4.1–4.2 s after the loss (3 s absent); 1.08–1.13 s per call when present | — |
| S6 | `OpenUnit` by serial after return, old handle not closed | **5/5 fail for 60 s**, `PICO_HARDWARE_VERSION_NOT_SUPPORTED` | **2/2 `PICO_OK` at the first attempt**, new handle 2, 75.5–75.8 kHz |
| S7 | S6 for 20 losses | not run | not run |

Other facts:

- **The poll does not report the loss.** `GetStreamingLatestValues` returns
  `PICO_OK` (rarely `PICO_BUSY`) after the scope is gone. Only the silence
  shows it. Reading the status (step 1) is still correct, but it is not the
  detector.
- **`PingUnit` returns `PICO_BUSY` while streaming**, also on a good scope. It
  cannot check that the scope is alive.
- **A crash can occur in a driver thread**, not in the call. In S2 the main
  thread was in plain Python code about 2 ms after `Stop` returned `PICO_OK`.
- **Process exit with an abandoned handle is clean** (S0, S1, S6: 17 runs).
- `OpenUnit` takes 2.8–2.9 s; `EnumerateUnits` takes 1.6 s for the first call
  in a process.
- **`authorized` is not a real unplug.** It keeps the USB device node; a real
  unplug makes a new one. The absent-scope rows (S0 to S3b, S4a) are valid. The
  after-return rows (S3c, S3d, S4b, S6) are valid only for a device that stayed
  on the same node. The field event (over-current, port power lost,
  re-enumeration) is a real unplug: the field crash matches the manual S3d row
  exactly (`Stop` `PICO_OK`, then SIGSEGV in `CloseUnit`).

### Idle loss (S8), 2026-10-15

The GUI crashed (SIGSEGV in `CloseUnit`) after: stop the stream, unplug, start.
`start()` used the open idle handle, `RunStreaming` failed, and the error path
in `DataCollector.start_stream()` closed the lost handle. Probe S8: stream,
`Stop` while present, then a physical unplug. Same PC and scope as above.

| ID | After `Stop` | Result (3 runs each, all clean) |
|---|---|---|
| S8a | no loss | `PingUnit` `PICO_OK` (0.2–0.4 ms). `EnumerateUnits` `PICO_NOT_FOUND`: **a scope open in this process is not listed**. `OpenUnit` by serial `PICO_NOT_FOUND` |
| S8b | absent | `PingUnit` `PICO_NOT_RESPONDING` (<0.1 ms); `EnumerateUnits` `PICO_NOT_FOUND` |
| S8c | after replug | `PingUnit` `PICO_NOT_RESPONDING`; serial listed; `OpenUnit` `PICO_OK` at the first attempt (3.0 s) |
| S8d | absent, start sequence | `SetChannel` x 8 `PICO_OK` (no device access), `SetSigGenBuiltIn` and `RunStreaming` `PICO_NOT_RESPONDING`; `SetDataBuffers` `PICO_OK`; no crash |
| S8e | after replug, start sequence | as S8d |

Consequences:

- **`PingUnit` on an idle handle is the liveness check**: `PICO_OK` only for a
  present, owned scope; clean in all cases. (While streaming it returns
  `PICO_BUSY` and cannot be used, S4.)
- "Serial not listed" does not mean "absent": the open scope is never listed.
  "Listed" while we hold a handle means the scope re-enumerated.
- The start calls on a lost handle are safe; only teardown crashes.

### Decision

In-process recovery is safe, with this rule: **after a loss, make no driver
call on the old handle, and open a new handle.** Evidence: S0/S1 (no crash
without a teardown call) and manual S6 (a new open works with the old handle
abandoned). Every teardown call on a lost handle can crash: absent (S2, S3a,
S3b) and after a real replug (manual S3d). No process isolation is necessary on
this branch.

The `PICO_HARDWARE_VERSION_NOT_SUPPORTED` result of `authorized` S6 shows the
other case: the old handle still owns the device (same node; also the expected
state for a real hang without a USB loss). There, and only there, `Stop` +
`CloseUnit` on the old handle are safe (S3c, S3d `authorized`: 10/10).

Open risks:

- **S7 is not measured**: how many abandoned handles one process can hold.
  Measure it on the Pi with `--method port` (port power off), after S6 with
  `--method port` shows that `port` behaves as a real unplug (a new open
  works). Until then, cap the abandoned handles (step 2).
- **A real hang was not produced.** The same-node case is the nearest model.

## Steps

1. **Read every driver status in the stream path.** Add one helper that maps a
   status to `ok`, `busy` or `error`, from the picosdk `PICO_STATUS` table, not
   number literals. The poll loop logs a non-OK, non-BUSY status of
   `ps4000aGetStreamingLatestValues` once for each status value; today it is
   ignored. The silence watchdog stays the loss detector (step 0: the poll
   returns `PICO_OK` after the loss).
2. **Recover by a new handle; never tear down a lost handle.** Replace
   `_try_recover()`:
   1. Make no driver call on the old handle.
   2. Poll `ps4000aEnumerateUnits` until the serial is listed, with backoff, up
      to the recovery deadline (step 3). Log the wait once, not for each poll.
   3. `ps4000aOpenUnit` by serial into a **new** `ctypes.c_int16`.
   4. `PICO_OK`: the scope re-enumerated. Abandon the old handle: log at
      WARNING, and never call the driver with it again (not in `stop()`,
      `close()` or at exit).
   5. `PICO_HARDWARE_VERSION_NOT_SUPPORTED`: the old handle still owns the
      scope (same node). Then `ps4000aStop` + `ps4000aCloseUnit` on the old
      handle, statuses logged, and open again.
   6. Any other status: retry until the deadline.
   7. Configure, set up the siggen and start streaming on the new handle, with
      **new** driver buffers and a **new** callback pointer. Keep the old
      buffers and callback pointers referenced for the life of the stream
      object (root cause 6).
   8. Cap the abandoned handles at a small number (4) until S7 is measured. At
      the cap, recovery gives up with a fault (step 5), and the service
      manager restarts the process. Put the S7 result beside the constant.
   For an open at start (`start()`), keep today's path.
2b. **Check an idle handle before use** (S8). Before any driver call on a
   handle that was idle (at the top of `start()` when the device is open, and
   in `close()` when not streaming), call `ps4000aPingUnit`. `PICO_OK`: use
   the handle. Any other status: abandon it (as step 2.4). Then `start()`
   opens a new handle by serial (one open; the scope is absent → a clear
   "not connected" error), and `close()` makes no driver call. A failure of a
   driver call later in `start()` also abandons the handle, with no teardown.
   The handle stays open while idle: the GUI reads metadata from it.
2c. **Log a start error before the teardown** in
   `DataCollector.start_stream()`, so the failing status is in the log.
3. **Recovery deadline.** 30 s from the loss, checked between waits. Evidence:
   the serial is listed 4.2 s after a loss of 3 s, a manual replug took up to
   8.2 s, and an open takes 2.9 s. Replace `_MAX_RECONNECT_ATTEMPTS` (3 x 1 s).
4. **One thread in the driver at a time.** Add a lock that every driver call
   in `PicoScopeStream` takes (start, stop, close, poll, recovery). Recovery
   checks `_stop_event` between waits and returns early. `stop()` sets the
   event, joins the thread until it exits, and only then calls the driver, and
   only on a handle that is not abandoned. Bound the join by the recovery
   deadline plus one open (2.9 s). Do not leave a thread in the driver when
   `stop()` returns.
5. **Report a lost stream.** When recovery gives up, `PicoScopeStream` sets a
   `fault` text (for example "device lost: not found after 30 s"). The
   collector exposes it.
   - Headless: in the 1 s timeout branch of the main loop, check
     `collector.is_streaming`. If the stream died, log ERROR with the fault,
     stop the monitor, close the session file, and exit with a distinct
     non-zero code. Document the code in README.md ("Headless datalogger").
   - GUI: check what it does today when `active` becomes false. Minimum: the
     Device tab shows the fault and offers Connect again. No widget work on the
     acquisition thread.
6. **Correct the constants and the 0 Hz message.** Use 7
   (`PICO_NOT_RESPONDING`, from the table) in both open helpers. Correct the
   282/286 comments. In `_check_rate_degradation()`, a window with no samples
   does not set `degraded` and does not log the bandwidth text. The silence
   watchdog handles it. Do not use `ps4000aPingUnit` as a health check: it
   returns `PICO_BUSY` while streaming.
7. **Keep the measurement chain honest across the gap.** After a recovery, the
   first block comes from a new stream. The high-pass state in
   `receive_data` still holds the state from before the gap, so the first
   frames have a transient (compare R47). Mark the first block after a recovery
   (a `status` value or a flag in the sample dict). The collector resets the
   high-pass state for that block, and the first frames after the gap are
   flagged as degraded, so they are shown but not trended, averaged or alarmed
   on. Store the flag, as for overflow. Ask the vibration-engineer agent to
   review this step.

## Tests

Use a fake driver module (`monkeypatch.setattr(pico_module, 'ps', ...)`, as
`tests/test_picoscope.py` does) that records every call with the handle it got.

- **Lost device, re-enumerated:** the fake stops the callbacks, returns
  `PICO_OK` from `GetStreamingLatestValues` (as the driver does), hides the
  serial from `EnumerateUnits` for N polls, then lists it and opens a new
  handle with `PICO_OK`. Assert: no driver call of any kind on the old handle
  after the loss; one new open by serial; new buffers and a new callback, the
  old ones still referenced; blocks arrive again. Revert check: the current
  `_try_recover()` calls `Stop` and `CloseUnit` on the old handle, and the test
  must fail.
- **Same node:** the first new open returns
  `PICO_HARDWARE_VERSION_NOT_SUPPORTED`. Assert: `Stop` and `CloseUnit` on the
  old handle, then a second open that succeeds.
- **Abandoned-handle cap:** losses beyond the cap end in a fault, not an open.
- **Device does not come back:** the stream gives up after the deadline (fake
  clock), sets `fault`, and `active` is false. No driver call on the old handle.
- **Stop during recovery:** the fake's open blocks on an `Event`. Call
  `stop()` from the test thread. The fake asserts it is never entered by two
  threads. `stop()` returns within the bound and makes no call on an abandoned
  handle. Revert check without the lock.
- **Constant:** `_open_unit()` with status 7 sleeps `_NOT_RESPONDING_DELAY_S`
  (spy on `time.sleep`). Revert check: with 14, the test fails.
- **0 Hz window:** `degraded` stays false and no bandwidth warning is logged.
  The existing `test_try_recover_never_called_for_rate_degradation` still
  passes.
- **Headless:** a sensor whose stream dies makes `run()` return the new exit
  code within a few seconds, with the session file closed. Use a fake stream;
  do not depend on burst timing.
- **Measurement:** in `tests/test_measurement_validity.py`, a recovery block
  resets the high-pass state, and the frames flagged after the gap do not reach
  the trend. Use an off-bin tone with a non-zero phase.

Run `python -m ruff check src/ tests/` and
`python -m pytest tests/ -q --ignore=tests/test_picoscope_hw.py`.

## Verification on hardware

Do not use the `authorized` method to verify the fix: it does not produce the
re-enumeration of the field event. Use a physical unplug, or `--method port`
after it is validated.

Locally (the scope on this PC; the user unplugs when told in the chat):

1. Headless, 8 channels: physical unplug for about 5 s, 3 times. Expect: a
   WARNING for the abandoned handle, recovery, data again, the flagged frames
   after the gap, no entry in `faulthandler.log`.
2. Revert check: with the old `_try_recover()`, step 1 crashes (SIGSEGV in
   `CloseUnit`, as manual S3d).
3. Unplug and do not replug: headless logs the fault and exits with the new
   code within the deadline. The session file opens and reads back.

On `rev80pi-01`, all commands in tmux session `0`, after the powered hub is
installed (so the only losses are the ones we make):

4. Probe S6 with `--method port`, 5 runs. If the new open works, `port`
   behaves as a real unplug: run S7 with `--method port` and set the
   abandoned-handle cap from it. If not, measure S7 by unplugs or keep the cap.
5. `python -m pytest tests/ -q` with the scope connected (the hardware tests
   included). Do not run a second pytest at the same time.
6. Headless, 8 channels: 10 losses with `--method port` (or 5 physical
   unplugs). Same expectations as step 1.
7. GUI over VNC: steps 1 and 3. The GUI does not crash and shows the fault.
8. Record the results (counts, recovery times) in the CHANGELOG entry.

## Documentation, in the same change

- `doc/CHANGELOG.md`: the fault, the field evidence above, the step 0 table in
  short, before and after.
- `doc/PROGRESS.md`: a new R-number for "Survive the loss of the scope during a
  stream", Done when verified. If S7 shows a low handle limit, a second
  R-number for process isolation of the driver.
- `CONTRIBUTING.md`: "E21. Device loss" with the step 0 table, the
  `authorized`-versus-unplug caveat, and the probe usage. Pointers beside the
  recovery deadline, the abandoned-handle cap and the "same node" status.
- `README.md`:
  - the headless exit code;
  - the GUI fault text;
  - the recovery behaviour: a gap of about 5 s plus the time the scope is
    away, then data again, with the first frames flagged;
  - a Raspberry Pi 5 power note: with a supply that is not 5 A, the Pi limits
    USB to 600 mA in total, and a PicoScope 4824A declares 896 mA. Use the
    official 27 W supply or a powered USB 3 hub.
- `CLAUDE.md`, under Invariants: "no driver call on a lost handle; recover by
  a new handle", "keep every buffer and callback a handle received", and the
  driver lock. Remove nothing from "Known-bad areas" that is not fixed.

## Out of scope

- R52 (headless closes the device on every exit path). Step 5 adds a clean exit
  for a lost stream only. Do not use it to close R52 without its own test.
- Running the driver in a child process (only if S7 shows a low handle limit).
- A shorter silence watchdog (5 s). A shorter one gives a shorter gap but was
  not measured for false alarms.
- The dearpygui `show_viewport` abort in `faulthandler.log` on the Pi. It is a
  separate fault.

## Changes after the GUI verification (2026-10-15)

- **Step 3 is replaced.** The user decided: no time limit by default. A scope
  can come back days later. `device_wait_s` in `acquisition.yaml` sets a
  limit; a stop or a change of the stream settings ends the wait. The GUI
  shows "Device lost — waiting mm:ss"; the stream logs every 5 min.
- **The abandoned-handle limit counts for the whole process** (module
  registry `_ABANDONED`, references in `_RETIRED`). It was per stream object,
  and a reconnect in Setup reset it. The limit stays 4 until S7 is measured
  (R68).
- **Settling after a gap:** frames flagged for 2 / `highpass_fc` seconds, at
  least 1 (vibration-engineer review, simulation table in E21).
- **Still open:** headless on hardware (exit code 3, AWG loopback settling of
  frames 0 to 10 after a replug), the Pi steps, S7, R69 (store a gap; break
  the average at a gap).
