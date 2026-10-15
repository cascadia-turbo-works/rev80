# Implement device-loss recovery, plus the idle-loss crash

Branch: `fix/device-loss-recovery`. Base plan:
`.claude/plans/2026-10-15-device-loss-hardening.md` (steps 1 to 7, tests,
hardware verification, documentation). This file adds the new case and the
order of work. It does not repeat the base plan.

## Context

The user made a new crash in the GUI on 2026-10-15, 09:05:

1. Stop the stream (09:05:17, `ps4000aStop` gave no error).
2. Unplug the PicoScope.
3. Start the stream (09:05:26).

`start()` saw `_device_open` True and did not open again. `SetChannel` x 8 and
`SetSigGenBuiltIn` did not raise on the absent scope. A later call
(`SetDataBuffers` or `RunStreaming`) raised. `DataCollector.start_stream()`
caught it and called `disconnect_sensor()` → `PicoScopeStream.close()` →
`ps4000aCloseUnit` on the lost handle → **SIGSEGV** (`faulthandler.log`,
`picoscope.py:461`, `collector.py:584`, `gui.py:1708`). The `log.error` comes
after `disconnect_sensor()`, so the failing status was never logged.

The base plan covers a loss **during** a stream only. This is a loss **while
idle, with the handle open**. The same rule applies: no teardown call on a
lost handle. The user's decision: **keep the handle open while idle** (the
connected scope gives metadata, channel count and configuration to the config
dialog), and **check the handle before the next driver call**.

## Step 0b: probe the idle loss on hardware (physical unplug)

Add scenarios to `scripts/pico-loss-probe.py`. Each: open, stream 2 s,
`Stop` while present (idle handle), then the loss. Use `--method manual`. The
user unplugs and replugs when told in the chat, turn by turn. 3 runs each.

| ID | After `Stop`, then | Record |
|---|---|---|
| S8a | no loss (control) | `PingUnit` status and time; `EnumerateUnits`: is our open serial listed?; `OpenUnit` by serial with the old handle open: status and time |
| S8b | unplug, scope absent | `PingUnit`, `EnumerateUnits`: statuses, crash or not |
| S8c | unplug and replug | `PingUnit`, `EnumerateUnits`, `OpenUnit` by serial (old handle not closed): statuses |
| S8d | unplug (absent), then replug | the `start()` sequence (`SetChannel`, `SetSigGenBuiltIn`, `SetDataBuffers`, `RunStreaming`) on the old handle, each status; **no** `CloseUnit` |

S8d with `CloseUnit` at the end reproduces the GUI crash; run it once as the
revert reference only.

Record the results in the base plan ("Step 0 results") and commit before the
code.

## Step 2b: check an idle handle before use

Moved into the base plan as step 2b, with the S8 results. Rule: `PingUnit` on
the idle handle; `PICO_OK` uses it, anything else abandons it. `start()` then
opens a new handle by serial; `close()` makes no driver call.

## Step 2c: the error path in the collector (new)

`DataCollector.start_stream()`: log the error (with the status text) before
`disconnect_sensor()`. Keep `disconnect_sensor()`: `close()` is now safe on a
lost handle. The GUI shows the fault (base step 5, GUI part).

## Order of work

1. Step 0b on hardware with the user; record the results; commit the plan
   update (base plan file).
2. Base step 1 (status helper, picosdk `PICO_STATUS` table) and step 6
   (constants 7/282/286, 0 Hz message). Small and independent.
3. Base step 4 (driver lock, `stop()` join) — the base for steps 2 and 2b.
4. Base steps 2 and 3 (recover by a new handle, 30 s deadline, cap 4).
5. Steps 2b and 2c.
6. Base step 5 (fault text; headless exit code; GUI shows it). Check the GUI
   behaviour when `active` goes false; no widget work off the main thread.
7. Base step 7 (high-pass reset and degraded flag after a gap). Ask the
   vibration-engineer agent to review it.
8. Documentation, in the same change: CHANGELOG, PROGRESS (new R-number),
   CONTRIBUTING "E21. Device loss" (with S8), README, CLAUDE.md invariants.
   Add "check an idle handle before use" to the CLAUDE.md invariant.

Commit each step separately (conventional commits, `--author="Claude AI
<claude@anthropic.com>"`).

## Critical files

- `src/rev80/picoscope.py`: `_open_unit`, `_open_unit_by_serial` (lines
  78–205), `PicoScopeStream.start/stop/close` (403–465), `_open_device`,
  `_start_streaming`, `_try_recover` (798), `_poll_loop` (850),
  `_check_rate_degradation` (895).
- `src/rev80/collector.py`: `disconnect_sensor`, `start_stream` (579–612),
  `receive_data` (high-pass reset, base step 7).
- `src/rev80/headless.py`: main loop timeout branch (base step 5).
- `src/rev80/gui.py`: `_start_stream` (1700), device status display.
- `scripts/pico-loss-probe.py`: S8 scenarios.
- Tests: `tests/test_picoscope.py` (fake driver), a headless test,
  `tests/test_measurement_validity.py`.

## Tests (in addition to the base plan)

With the fake driver that records each call and its handle:

- **Idle loss, absent:** start, stop, the fake hides the serial, start again.
  Assert: no `Stop`/`CloseUnit` on the old handle; `start()` raises the
  "not connected" error; `close()` then makes no driver call. Revert check:
  today's code calls `CloseUnit` on the old handle and the test fails.
- **Idle loss, re-enumerated:** the fake lists the serial and the new open
  gives `PICO_OK`. Assert: the old handle is abandoned, streaming runs on the
  new handle with new buffers and callback.
- **Idle, no loss:** the new open gives `HARDWARE_VERSION_NOT_SUPPORTED`.
  Assert: the old handle is used; no new handle is held.
- **Close while idle after a loss:** `close()` abandons; no driver call on
  the old handle.
- **Collector:** a failing `start()` logs the error before the disconnect.

Run `python -m ruff check src/ tests/` and
`python -m pytest tests/ -q --ignore=tests/test_picoscope_hw.py`.

## Verification on hardware (in addition to the base plan)

Local scope, the user unplugs when told in the chat:

1. GUI: stop, unplug, start. Expect: an error shown, no crash, nothing in
   `faulthandler.log`. Replug, start: streaming again.
2. GUI: stop, unplug, replug, start. Expect: WARNING for the abandoned
   handle, streaming on a new handle.
3. GUI: stop, unplug, quit. Expect a clean exit.
4. Revert check: with the old `close()`, case 1 crashes as today.
5. Then the base plan verification (stream-loss cases, headless exit code,
   the Pi steps when the powered hub is in place).
