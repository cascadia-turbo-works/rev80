# Plot setup — progress tracker

Plan: `.claude/plans/2026-10-17-plot-setup.md` (revision 7, 2026-10-20).
Review: `.claude/plans/2026-10-19-plot-setup-review.md`.
Branch: `feat/plot-setup`. Requirement: R70 in `doc/PROGRESS.md`.

Update this file in the same commit as each step. Status: 🔲 TODO,
🔄 In progress, ✅ Done, ⏸ Blocked.

## Release 0.1.5 — parts A, B, C

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| A1 | Visible disabled state for locked controls | ✅ Done | 85d630c | lock and unlock test (`test_gui_locked_controls.py`) |
| A2 | A new `DataCollector` for every load and connect; `_on_data_source_changed()` | ✅ Done | 1e28e05 | no stale state; refused load leaves state; connect uses `acquisition.yaml`; revert check (`test_gui_collector_swap.py`) |
| A3 | Session and burst trends from stored frames (no stage-1 arrays kept); NaN; RPM trend | ✅ Done | 56fc4c2 | zero trend reproduced on the old code (g, mil 0.0), then fixed; equality with `overall_json` 7.4e-5; load time and memory measured (`test_session_trend_from_frames.py`) |
| A3a | Progress bar while a session or burst loads | ⏭ Moved | | to doc/PROGRESS.md as R72 (owner, 2026-10-20); not in this branch |
| A4 | Averaging on contiguous frames only | ✅ Done | 1417ccb | session k = 1; live and burst k = N; restart stops the walk; 1.5-period limit; revert check (`test_spectral_averaging.py`) |
| B0 | Reference results from the old path | ✅ Done | 5413dbf | `tests/reference/result_view_reference.npz`, 16 cases |
| B1 | `FrameSnapshot`; `current_rpm(snapshot)` | ✅ Done | da8667e | append between calls (`test_frame_snapshot.py`) |
| B2 | `advance_frame()`, `results_for()`; `process_samples()` removed | ✅ Done | fc655b4 | one trend point per tick; redisplay adds none (`test_frame_views.py`) |
| B3 | `result_view()`, tick memo, unit-parameterised trend | ✅ Done | fc655b4 | equality, 16 cases: axes, peaks and counts identical, floats to 1e-9 of full scale (`test_result_view_equality.py`; bit for bit failed on every other machine, CI included, by up to 1.1e-10: the stored reference is one machine's FFT rounding. Revert check: a 1e-7 scale change fails 16 of 16); off-bin conversion with revert check (`test_measurement_validity.py`) |
| C1 | `ResultViews`; RMS hook unit and mode; fixed-limit modes; capture stores the record view | ✅ Done | 8b2b260 | RMS hook in g fires on an in/s channel; capture stores in/s; 0-P limit on a P-P channel; velocity limit on a g channel; no sensor warns once; empty keys give the record list itself; revert check 4 of 6 fail (`test_hook_views.py`) |
| C2 | Fixed-limit sustain time `fixed_s` (default 0 s) | ✅ Done | c8b1fa6 | hook `sustain_frames`: 1 fires on one frame; 3 needs 3 frames and reports the first; a dropped frame and a burst frame end the streak; revert checks 3 and 2 fail (`test_hook_views.py`). The `fixed_s` key and widget are in C3 |
| C3 | Monitor-tab controls; both hook builders; headless | ✅ Done | 35b0ffe | defaults agree, keys reach both builders, config round trip; revert check 2 fail (`test_anomaly_hook_build.py`, `test_gui_monitor_config.py`). Cost on the PC: +4.5 ms per frame against 12.5 ms (8 ch). Pi 3 cost not measured |
| R1 | Docs, vibration-engineer review (A3, A4, B, C), technical-writer audit | ✅ Done | ffadbc6, 98bbf83, 46f3c94, 30c60ed | Docs audit (ffadbc6). Fixed: sensor EU `mV` unreachable; capture stored the newest frame, not the snapshot frame (98bbf83); a burst frame ends the streak of every hook (46f3c94); no "Channel" choice, explicit unit and mode for each hook (30c60ed). Owner decisions 2026-10-19: the A3 band-edge error of the loaded trend (+92 % velocity at a 2 Hz edge with 0.6 Hz content) is fixed with E1, not in 0.1.5; `rel_time` jitter is accepted (frame periods are 0.5 to 2 s); ISO modes are the user's choice |
| R2 | Merge to `develop`; field test | 🔄 In progress | f723972, 2c8b028, be7db48 | merged to `develop` 2026-10-19 and pushed. CI on `f723972` was red (the bit-for-bit equality test); 2026-10-21: the test fix (2c8b028, cherry-pick of 58c5404) and the session-select fix (be7db48) on `develop`, suite 1372 passed. Field test: owner |
| R3 | Merge to `main`; tag `v0.1.5` | 🔲 TODO | | draft release built |

## Release 1.0.0 — parts D, E

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| D1 | `charts.py`; default layout = time waveform + spectrum | ✅ Done | 3b4659e | round trip of every type through YAML; bad entry skipped; bad file not overwritten (3 cases); unit rules; tachometer refused; XY needs two; default = waveform + spectrum; collector uses the same rule (`test_charts.py`) |
| D2 | Main window from `chart_set`; cards with collapsing headers; `gui_charts.py`; ARM pattern | ✅ Done | 49c0b7d, (this commit) | tabs from a set; selection kept and first tab after a removal; hidden chart not drawn, its cards updated; tab change draws at once; series in the chart unit; legend reason and tab note; peaks pool shrink, grow and clear; main window build and one display tick; ARM pattern (`test_gui_charts.py`). Revert checks: drawing every chart fails the hidden-chart test; the XY and disabled-tachometer tests fail without their fixes. Code review (python-reviewer): 2 HIGH, 4 MEDIUM fixed (Apply rebuild, XY tachometer, rebuild redraw, clear, stale snapshot; XY by time as a guard, the trims are equal today); LOW: cursor theme and x0 fixed, envelope info line for each chart and no autoscale at the first open of a tab accepted. Profiling in E19. The renderers of D5 (envelope SI scale and mode), D6 (y2 shaft speed) and D7 (XY) are in this step; their steps add the tests. The default layout has no trend (owner, 2026-10-20: keep Q15 exactly); a trend first comes back with the Charts tab (D3) |
| D3 | Charts tab; XY swap; file-loaded edits and "Use for live data" | ✅ Done | b1a6760 | edit rules in `charts.py` (`test_charts.py`, 9 new); tab rows, add, remove, swap, disabled and absent channels, N clamp, name edit without rebuild, Close with live data saves `charts.yaml`, with a file only the layout in effect, unedited Close writes nothing (`test_gui_charts_tab.py`, 14); a connect after a file load takes `charts.yaml`, not the file's layout (`test_gui_collector_swap.py`, 2). Revert checks: live guard, disabled checkbox, edited flag, collector carry-over, live `charts.yaml` each fail a test. ARM pattern now matches every `rev80.gui_*` module. Code review (python-reviewer): fixed — a data-source change while the dialog is open drops the edits (a file layout could reach `charts.yaml`), unique combo labels for repeated channel names, the last chart cannot be removed (an empty `charts.yaml` is not valid), `with_xy` keeps the axis, status cleared at open; each with a test and a revert check. Accepted: an edit freezes the old envelope and averaging settings until D4 removes them; a Charts-tab select applies the channel widgets (Close does the same); repeated chart names |
| D4 | Acquisition-tab controls and fields removed; YAML migration | ✅ Done | b853a4d | `averaging_enabled`, `n_averages`, `envelope_enabled`, `n_averages_effective` and their widgets removed; `DataCollector.n_averages_for(spec)`; `config.migrate_chart_settings()` at a GUI connect (old keys moved once, both off writes no `charts.yaml`, an existing `charts.yaml` not changed; `test_config.py`, 4) and the connect test (`test_gui_collector_swap.py`); averaging tests use the chart averaging (`pipeline_helpers.set_spectrum_averaging`). Revert check: no migration call at connect fails the connect test. Headless does not migrate (no sensors, R73). `profile-pipeline --envelope` removed (no effect) |
| D5 | Envelope chart with SI scale and mode | ✅ Done | (this commit) | sensor-EU envelope × SI scale × mode for g 0-P, mm/s² RMS, in/s² P-P on `GenerateBearingVibration`; not computed off screen (`test_gui_charts.py`). Revert check: no scale fails 2 cases. D5 to D7 are one commit: tests only, the renderers came with D2 |
| D6 | Trend y2: shaft speed | ✅ Done | (this commit) | missing reading gives no point; the same values for every chart unit; rotation unit Hz; no y2 without shaft speed. Usable-only gating is in the collector (`test_tach_usable.py`). Revert checks: no NaN filter and an amplitude-mode scale each fail a test |
| D7 | XY chart | ✅ Done | (this commit) | in/s: two traces of the same span, the same unit, equal axes, unit on both axis labels; with the D2 tests (Y against X of one frame, no tachometer, pairing by time) |
| E1 | Layout in data files; versions 6 and 7; headless layout; stored mV orders for each capture (load without DSP) | ✅ Done | 2d32fd2, (this commit) | E1a (2d32fd2): layout and Rev80 version in both files, a load sets the layout, missing or bad layout gives the default and a warning, headless reads charts.yaml (`test_file_layout.py`, 11 tests). Found: headless assigns no scope sensor (R73, not in this work). E1b: `orders_mv` on each vibration channel group whose overalls came from the stateful filter; loaded session and burst trends equal the live orders within 0.5 % for every order (measured: equal) at a 2 Hz edge, 1 Hz bins, off-bin 0.6 Hz content; a frame without them is the waveform replay (`test_session_live_orders.py`, 4). Revert check: without the stored orders the test fails (velocity 21 % low, displacement 27 % low). Load time: 1.7 to 1.85 s against 3.3 s without `orders_mv` (E22). Review (vibration-engineer): fixed — `orders_key` with the orders, used only while it matches (old-band pre-trigger frames stepped a burst trend about 46x); the loaded frame's view uses the stored row (card -21 % to +22 % from its trend point; the strong card-equals-trend test restored); Reprocess uses it; skipped frames get their live overalls in `advance_frame()`; a save keeps stored rows. Each with a test and a revert check (`test_session_live_orders.py`, 9). Not verified on hardware: the first frame of a stream (R47) with a 2 Hz edge on AWG loopback |
| E2 | Exact-version reading; older and newer refused; old reader removed | ✅ Done | (this commit) | `check_file_version(f, kind)` and `FileVersionError` (exported); every loader checks before any state changes; older (measurement 3, 4, 5; session 6) and newer refused with the message for each case; the wrong type refused; a refused load leaves the collector unchanged; Reprocess never writes into an older session (checksum) (`test_file_version_check.py`, 15). GUI: a refused file logs the message alone; the session browser lists an old session with its reason and does not auto-load it; selecting it changes nothing; Save Config does not write into it (`test_gui_collector_swap.py`, 5). Revert checks: no check in `load_data` (6 fail), none in Reprocess, the check after the clear, no early return in the session select, no check in Save Config: each fails a test. Removed: `_loaded_channel_units()`, the v3 frame unit and trend. Found and fixed: a refused session became the current session (burst table and lines of the refused file; Save Config wrote into it). The same defect for a corrupt or empty file in the 0.1.5 code: fixed on `develop` (be7db48) |
| E3 | `scripts/convert-0x` | ✅ Done | (this commit) | measurement v5 (with a tachometer) and v4 (no roles) convert and load: frames bit for bit, trend orders equal, default layout channel 0 in g (the stored sensor); the stored target unit and mode set the layout; a v6 session (directory or `session.h5`) converts and loads, a burst too; the source unchanged (checksum); v3 measurement and v5 session refused with nothing written; a current file, an existing copy refused; `--out`; a failure leaves no copy; exit code 1 with one bad path (`test_convert_0x.py`, 12). Revert checks: no version change (5 fail), layout without the stored sensor (3 fail). Found and fixed: a v6/v7 file with no stored layout got a default in mV, because the load made it before the sensors were assigned; `charts.record_view()` is now the one rule (`test_file_layout.py`; revert check 3 fail). Open: `scripts/` is not in the wheel or the installer, so an installed user cannot run it |
| R4 | Docs, reviews, merge chain, tag `v1.0.0` | 🔲 TODO | | |

## Not in this work

| Item | Tracked as |
|---|---|
| Polar chart and 1x phase measurement | R24 |
| Anomaly triggers as a configurable table (trigger type per row; fixed triggers with > or <) | R71 |
| Split panes, more than one chart on screen | R33 |

## Decisions

All open questions are decided. The list is section 11 of the plan.

| Date | Decisions |
|---|---|
| 2026-10-19 | Q1 to Q13 |
| 2026-10-20 | Default layout: keep Q15 exactly (waveform and spectrum, no trend), for the GUI, headless and the converter; a user adds a trend in the Charts tab |
| 2026-10-20 | Q14 to Q16; review findings: C1, C2, C3, C5, C6 fixed in the plan; C4 replaced by a unit for each hook; D1 a new collector for each load and connect; D2 accepted as work in progress; D3 and D4 chart-driven units; D5 to D8 fixed; D9 converter; releases 0.1.5 (A, B, C) and 1.0.0 (D, E) |

## Measurements

Record each one with the method (hardware model, AWG loopback, or
`SimulatedSensor`), then move the final table to CONTRIBUTING.md,
section 5.

| Date | What | Method | Result |
|---|---|---|---|
| 2026-10-19 | Session trend rebuilt from `overall_json`, accelerometer 100 mV/g, recorded in in/s, shown in in/s / g / mil | synthetic trend, `get_trend_for_display()` (scratchpad `trendcols.py`) | 273.0, 283.9, 278.5 / 0.0 x3 / 0.0 x3: defect, A3 |
| 2026-10-19 | Session load time and peak memory, 1440 captures, 4 channels, before and after A3 | `SimulatedSensor` frames copied to 1440 captures, i7-1260P (scratchpad `mksession.py`, `loadsession.py`) | 1.7 s, 778 MB before; 5.3 s, 779 MB one call for each frame; 3.0 s, 783 MB with 2-D chunks of 16. CONTRIBUTING.md E22 |
| 2026-10-20 | Extra time for the hook views during a recording, 8 channels, GUI PC | 4824A at 25591.8 Hz, AWG on A, live stream, i7-1260P (scratchpad `bench_hooks_hw.py`) | RMS hook in the record unit 0.03 ms; in another unit 5.03 ms (p90 5.57); frame advance and record results 14.57 ms. CONTRIBUTING.md E16 |
| | The same on a Raspberry Pi 3, headless | Pi 3 + 4824A | ⏭ Skipped for now (owner, 2026-10-20) |
| 2026-10-20 | GUI time for each frame, 8 channels, before and after D2 | `GUI._display_frame_inner`, `SimulatedSensor` frames, dearpygui context with no viewport, i7-1260P (scratchpad `bench_render.py`) | before 18.2 to 18.7 ms; 3 charts in the record unit 16.0 to 16.6 ms; in another unit 20.2 to 20.7 ms; 6 charts with 2 spectrum charts × 8 channels of cards 23.2 to 23.8 ms (26.0 to 26.3 ms before the pool pushed only changes). CONTRIBUTING.md E19 |
| 2026-10-20 | The same on hardware | 4824A, 8 channels at 25591.8 Hz, AWG 500 Hz on A, live stream (scratchpad `bench_render_hw.py`) | before 18.1 ms; 3 charts record unit 17.2 ms; other unit 21.2 ms; 6 charts 23.3 ms. `test_picoscope_hw.py` 27 passed |

## Notes

- No GUI viewport from an automated session. Tests make a context only.
- Implementation continues on a machine with PicoSDK installed; the cloud
  container could not install `picosdk`.
- The averaging control is a linear power average of N frames, not an
  exponential one.
