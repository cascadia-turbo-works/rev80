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

## Step 0: measure the driver's behaviour on hardware first

Do not choose the teardown rule from reading. Measure which driver calls are
safe on a lost handle. Put the table in CONTRIBUTING.md as
"E21. Device loss", with a pointer beside the constants.

- Add `scripts/pico-loss-probe.py`. It opens the scope, starts streaming,
  waits for the operator to remove the device, and then runs one driver call.
  It runs each scenario in a **child process**, so a native crash shows as an
  exit signal and does not end the probe.
- Simulate the loss with `echo 0 > /sys/bus/usb/devices/<port>/authorized`
  and then `1` (root; the user runs it in tmux session `0`). Repeat one
  scenario with a physical unplug, to confirm that the simulation is
  equivalent.
- Scenarios, each 5 times:

  | ID | After loss, call | Record |
  |---|---|---|
  | S1 | `ps4000aGetStreamingLatestValues` | status, or signal |
  | S2 | `ps4000aStop` | status, or signal |
  | S3 | `ps4000aCloseUnit` (with and without S2 first; device absent, and device back) | status, or signal |
  | S4 | `ps4000aPingUnit` | status, or signal |
  | S5 | `ps4000aEnumerateUnits` while absent and after it is back | serial list |
  | S6 | `ps4000aOpenUnit` by serial after it is back, old handle not closed | status, new handle |
  | S7 | S6 repeated 20 times without any close | first failure, if any (`PICO_MAX_UNITS_OPENED`?) |

- Also record the time from loss to re-enumeration (kernel log and S5).

**Decision rule.**
- If a call exists that reports "lost" without a crash (S1, S2 or S4), and
  S6/S7 show that an abandoned handle does not stop a new open, then use
  in-process recovery as below.
- If an abandoned handle stops a new open, or every call on a lost handle can
  crash, in-process recovery is not safe. Then stop at step 1 and step 5 of
  this plan (do not touch the lost handle; stop cleanly), and record "run the
  driver in a child process" as a new R-number. Do not build process isolation
  on this branch.

## Steps (assuming the decision rule allows in-process recovery)

1. **Read every driver status in the stream path.** Add one helper that maps a
   status to `ok`, `lost` (`PICO_NOT_FOUND`, `PICO_NOT_RESPONDING` and any
   others that S1 to S4 show) or `error`. Use the picosdk `PICO_STATUS` table,
   not number literals. The poll loop checks the status of
   `ps4000aGetStreamingLatestValues`; today it is ignored.
2. **Never call teardown on a lost handle.** Replace the teardown in
   `_try_recover()` with `_teardown(lost: bool)`:
   - lost: make no driver call on the old handle (or only the calls that
     step 0 proved safe); log at WARNING that the handle is abandoned; make a
     new `ctypes.c_int16` for the next open.
   - not lost (a hang): `ps4000aStop` and `ps4000aCloseUnit`, with status
     checked and logged.
   `stop()` and `close()` use the same rule: no driver call on a handle that is
   known lost.
3. **Wait for the device to come back before opening.** Poll
   `ps4000aEnumerateUnits` (if S5 shows it is safe) for the serial, with
   backoff, up to a recovery deadline. Choose the deadline from the
   re-enumeration time in step 0, with margin. It replaces the 3 x 1 s attempts.
   Log each wait once, not every poll.
4. **One thread in the driver at a time.** Add a lock that every driver call
   in `PicoScopeStream` takes (start, stop, close, poll, recovery). Recovery
   checks `_stop_event` between waits and returns early. `stop()` sets the
   event, joins the thread until it exits, and only then calls the driver.
   Bound the join by the recovery deadline. Do not leave a thread in the driver
   when `stop()` returns.
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
   watchdog handles it.
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

- **Lost device:** the fake returns `PICO_NOT_FOUND` from
  `GetStreamingLatestValues`, then shows the serial again after N polls.
  Assert: no `Stop` or `CloseUnit` on the old handle (or only the calls that
  step 0 proved safe); one new open by serial; blocks arrive again. Revert
  check: the current `_try_recover()` calls `CloseUnit` on the old handle, and
  the test must fail.
- **Device does not come back:** the stream gives up after the deadline (fake
  clock), sets `fault`, and `active` is false.
- **Stop during recovery:** the fake's open blocks on an `Event`. Call
  `stop()` from the test thread. The fake asserts it is never entered by two
  threads. `stop()` returns within the bound. Revert check without the lock.
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

On `rev80pi-01`, all commands in tmux session `0`, after the powered hub is
installed (so the only losses are the ones we make):

1. `python -m pytest tests/ -q` with the scope connected (the hardware tests
   included). Do not run a second pytest at the same time.
2. Headless, 8 channels: simulate a loss with `authorized` 0, wait 3 s, set 1.
   Expect: a WARNING for the abandoned handle, recovery, data again, the flagged
   frames after the gap, no entry in `faulthandler.log`. Repeat 10 times.
3. The same with a physical unplug and replug, 5 times.
4. Unplug and do not replug: headless logs the fault and exits with the new
   code within the deadline. The session file opens and reads back.
5. GUI over VNC: steps 2 and 4. The GUI does not crash and shows the fault.
6. Revert check on hardware: with the old `_try_recover()`, step 2 crashes
   (SIGSEGV or SIGBUS in `faulthandler.log`).
7. Record the results (counts, recovery times) in the CHANGELOG entry.

## Documentation, in the same change

- `doc/CHANGELOG.md`: the fault, the field evidence above, the step 0 table in
  short, before and after.
- `doc/PROGRESS.md`: a new R-number for "Survive the loss of the scope during a
  stream", Done when verified. A second new R-number for process isolation if
  the decision rule requires it.
- `CONTRIBUTING.md`: "E21. Device loss" with the step 0 table.
- `README.md`:
  - the headless exit code;
  - the GUI fault text;
  - a Raspberry Pi 5 power note: with a supply that is not 5 A, the Pi limits
    USB to 600 mA in total, and a PicoScope 4824A declares 896 mA. Use the
    official 27 W supply or a powered USB 3 hub.
- `CLAUDE.md`: the rule "no driver call on a lost handle" and the driver lock,
  under Invariants. Remove nothing from "Known-bad areas" that is not fixed.

## Out of scope

- R52 (headless closes the device on every exit path). Step 5 adds a clean exit
  for a lost stream only. Do not use it to close R52 without its own test.
- Running the driver in a child process (only if step 0 requires it).
- The dearpygui `show_viewport` abort in `faulthandler.log` on the Pi. It is a
  separate fault.
