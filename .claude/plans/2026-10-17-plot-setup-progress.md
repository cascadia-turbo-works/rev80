# Plot setup — progress tracker

Plan: `.claude/plans/2026-10-17-plot-setup.md` (revision 7, 2026-10-20).
Review: `.claude/plans/2026-10-19-plot-setup-review.md`.
Branch: `feat/plot-setup`. Requirement: R67 in `doc/PROGRESS.md`.

Update this file in the same commit as each step. Status: 🔲 TODO,
🔄 In progress, ✅ Done, ⏸ Blocked.

## Release 0.1.5 — parts A, B, C

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| A1 | Visible disabled state for locked controls | ✅ Done | 85d630c | lock and unlock test (`test_gui_locked_controls.py`) |
| A2 | A new `DataCollector` for every load and connect; `_on_data_source_changed()` | ✅ Done | 1e28e05 | no stale state; refused load leaves state; connect uses `acquisition.yaml`; revert check (`test_gui_collector_swap.py`) |
| A3 | Session and burst trends from stored frames (no stage-1 arrays kept); NaN; RPM trend | ✅ Done | 56fc4c2 | zero trend reproduced on the old code (g, mil 0.0), then fixed; equality with `overall_json` 7.4e-5; load time and memory measured (`test_session_trend_from_frames.py`) |
| A3a | Progress bar while a session or burst loads (native dearpygui `add_progress_bar`) | 🔲 TODO | | owner request 2026-10-19: a 1440-capture load takes about 3 s with no sign of activity |
| A4 | Averaging on contiguous frames only | ✅ Done | 1417ccb | session k = 1; live and burst k = N; restart stops the walk; 1.5-period limit; revert check (`test_spectral_averaging.py`) |
| B0 | Reference results from the old path | ✅ Done | 5413dbf | `tests/reference/result_view_reference.npz`, 16 cases |
| B1 | `FrameSnapshot`; `current_rpm(snapshot)` | ✅ Done | da8667e | append between calls (`test_frame_snapshot.py`) |
| B2 | `advance_frame()`, `results_for()`; `process_samples()` removed | ✅ Done | fc655b4 | one trend point per tick; redisplay adds none (`test_frame_views.py`) |
| B3 | `result_view()`, tick memo, unit-parameterised trend | ✅ Done | fc655b4 | equality bit for bit, 16 cases (`test_result_view_equality.py`); off-bin conversion with revert check (`test_measurement_validity.py`) |
| C1 | `ResultViews`; RMS hook unit and mode; fixed-limit modes; capture stores the record view | ✅ Done | 8b2b260 | RMS hook in g fires on an in/s channel; capture stores in/s; 0-P limit on a P-P channel; velocity limit on a g channel; no sensor warns once; empty keys give the record list itself; revert check 4 of 6 fail (`test_hook_views.py`) |
| C2 | Fixed-limit sustain time `fixed_s` (default 0 s) | ✅ Done | c8b1fa6 | hook `sustain_frames`: 1 fires on one frame; 3 needs 3 frames and reports the first; a dropped frame and a burst frame end the streak; revert checks 3 and 2 fail (`test_hook_views.py`). The `fixed_s` key and widget are in C3 |
| C3 | Monitor-tab controls; both hook builders; headless | ✅ Done | 35b0ffe | defaults agree, keys reach both builders, config round trip; revert check 2 fail (`test_anomaly_hook_build.py`, `test_gui_monitor_config.py`). Cost on the PC: +4.5 ms per frame against 12.5 ms (8 ch). Pi 3 cost not measured |
| R1 | Docs, vibration-engineer review (A3, A4, B, C), technical-writer audit | ✅ Done | ffadbc6, 98bbf83, 46f3c94, 30c60ed | Docs audit (ffadbc6). Fixed: sensor EU `mV` unreachable; capture stored the newest frame, not the snapshot frame (98bbf83); a burst frame ends the streak of every hook (46f3c94); no "Channel" choice, explicit unit and mode for each hook (30c60ed). Owner decisions 2026-10-19: the A3 band-edge error of the loaded trend (+92 % velocity at a 2 Hz edge with 0.6 Hz content) is fixed with E1, not in 0.1.5; `rel_time` jitter is accepted (frame periods are 0.5 to 2 s); ISO modes are the user's choice |
| R2 | Merge to `develop`; field test | 🔲 TODO | | field-test notes |
| R3 | Merge to `main`; tag `v0.1.5` | 🔲 TODO | | draft release built |

## Release 1.0.0 — parts D, E

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| D1 | `charts.py`; default layout = time waveform + spectrum | 🔲 TODO | | |
| D2 | Main window from `chart_set`; cards with collapsing headers; `gui_charts.py`; ARM pattern | 🔲 TODO | | profiling before and after |
| D3 | Charts tab; XY swap; file-loaded edits and "Use for live data" | 🔲 TODO | | |
| D4 | Acquisition-tab controls and fields removed; YAML migration | 🔲 TODO | | |
| D5 | Envelope chart with SI scale and mode | 🔲 TODO | | |
| D6 | Trend y2: shaft speed | 🔲 TODO | | |
| D7 | XY chart | 🔲 TODO | | |
| E1 | Layout in data files; versions 6 and 7; headless layout; stored mV orders for each capture (load without DSP) | 🔲 TODO | | round trip; load time against E21; loaded trend = live overall within 0.5 % for every order at a 2 Hz edge, 1 Hz bins, off-bin 0.6 Hz content (fixes the A3 replay-filter error found in R1) |
| E2 | Exact-version reading; older and newer refused; old reader removed | 🔲 TODO | | revert checks |
| E3 | `scripts/convert-0x` | 🔲 TODO | | converted files equal; source unchanged |
| R4 | Docs, reviews, merge chain, tag `v1.0.0` | 🔲 TODO | | |

## Not in this work

| Item | Tracked as |
|---|---|
| Polar chart and 1x phase measurement | R24 |
| Anomaly triggers as a configurable table (trigger type per row; fixed triggers with > or <) | R68 |
| Split panes, more than one chart on screen | R33 |

## Decisions

All open questions are decided. The list is section 11 of the plan.

| Date | Decisions |
|---|---|
| 2026-10-19 | Q1 to Q13 |
| 2026-10-20 | Q14 to Q16; review findings: C1, C2, C3, C5, C6 fixed in the plan; C4 replaced by a unit for each hook; D1 a new collector for each load and connect; D2 accepted as work in progress; D3 and D4 chart-driven units; D5 to D8 fixed; D9 converter; releases 0.1.5 (A, B, C) and 1.0.0 (D, E) |

## Measurements

Record each one with the method (hardware model, AWG loopback, or
`SimulatedSensor`), then move the final table to CONTRIBUTING.md,
section 5.

| Date | What | Method | Result |
|---|---|---|---|
| 2026-10-19 | Session trend rebuilt from `overall_json`, accelerometer 100 mV/g, recorded in in/s, shown in in/s / g / mil | synthetic trend, `get_trend_for_display()` (scratchpad `trendcols.py`) | 273.0, 283.9, 278.5 / 0.0 x3 / 0.0 x3: defect, A3 |
| 2026-10-19 | Session load time and peak memory, 1440 captures, 4 channels, before and after A3 | `SimulatedSensor` frames copied to 1440 captures, i7-1260P (scratchpad `mksession.py`, `loadsession.py`) | 1.7 s, 778 MB before; 5.3 s, 779 MB one call for each frame; 3.0 s, 783 MB with 2-D chunks of 16. CONTRIBUTING.md E21 |
| | Extra time for the hook views during a recording, 8 channels | Raspberry Pi 3 headless; GUI PC | |
| | GUI time for each frame, 1 to 8 channels, before D2 | `scripts/profile-pipeline` | |
| | GUI time for each frame, 6 charts, 1 on screen, after D2 | `scripts/profile-pipeline` | |
| | Cards of 2 spectrum charts × 8 channels | `scripts/profile-pipeline` | |

## Notes

- No GUI viewport from an automated session. Tests make a context only.
- Implementation continues on a machine with PicoSDK installed; the cloud
  container could not install `picosdk`.
- The averaging control is a linear power average of N frames, not an
  exponential one.
