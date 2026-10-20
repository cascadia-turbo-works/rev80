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
| A2 | A new `DataCollector` for every load and connect; `_on_data_source_changed()` | ✅ Done | A2 | no stale state; refused load leaves state; connect uses `acquisition.yaml`; revert check (`test_gui_collector_swap.py`) |
| A3 | Session and burst trends from stored frames (no stage-1 arrays kept); NaN; RPM trend | 🔲 TODO | | zero-trend reproduction, then fix; load time and memory |
| A4 | Averaging on contiguous frames only | 🔲 TODO | | session k = 1 |
| B1 | `FrameSnapshot`; `current_rpm(snapshot)` | 🔲 TODO | | append between calls |
| B2 | `advance_frame()`, `results_for()`; `process_samples()` removed | 🔲 TODO | | one trend point per tick |
| B3 | `result_view()`, tick memo, unit-parameterised trend | 🔲 TODO | | equality; off-bin conversion; revert check |
| C1 | `ResultViews`; RMS hook unit and mode; fixed-limit modes; capture stores the record view | 🔲 TODO | | stored record unit; empty keys bit for bit |
| C2 | Fixed-limit sustain time `fixed_s` (default 0 s) | 🔲 TODO | | 0 s = one frame |
| C3 | Monitor-tab controls; both hook builders; headless | 🔲 TODO | | defaults agree; Pi 3 cost |
| R1 | Docs, vibration-engineer review (A3, A4, B, C), technical-writer audit | 🔲 TODO | | |
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
| E1 | Layout in data files; versions 6 and 7; headless layout | 🔲 TODO | | round trip |
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
| | Session load time and peak memory, 1440 captures, 4 channels, before and after A3 | `SimulatedSensor` session | |
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
