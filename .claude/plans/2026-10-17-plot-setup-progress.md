# Plot setup — progress tracker

Plan: `.claude/plans/2026-10-17-plot-setup.md` (revision 4, 2026-10-19).
Branch: `feat/plot-setup`. Requirement: R67 in `doc/PROGRESS.md`.

This file gives the status of each step of the plan. Update it in the same
commit as the step. Status: 🔲 TODO, 🔄 In progress, ✅ Done, ⏸ Blocked.

## Steps

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| S0 | Branch, plan, tracker, R67 | ✅ Done | `e3ec953`, revisions 2 and 3 | — |
| S0b | Fix: locked controls look disabled during a recording | 🔲 TODO | | lock and unlock test |
| S1 | `charts.py` model, validation, `charts.yaml` | 🔲 TODO | | |
| S2 | `result_view()` as the one path; `process_sample()` removed; unaveraged `process_samples(unit, mode)`; unit-parameterised trend; view cache | 🔲 TODO | | equality test; off-bin conversion test; revert check |
| S2b | Loaded trends from stored frames (all units, NaN gaps, RPM); contiguous-frame averaging | ⏸ Q12, Q13 | | zero-trend reproduction, then fix |
| S3 | Alarm unit and mode on the Monitor tab; both `_build_anomaly_hook` copies; headless | 🔲 TODO | | hook-build defaults agree |
| S4 | Dynamic tab bar; bottom time-series removed; waveform, spectrum, trend renderers; result cards for each (spectrum chart, channel); on-screen-only rendering | ⏸ Q9 for the cards | | profiling table before and after |
| S5 | Charts tab in the configuration dialog; XY selectors with swap | 🔲 TODO | | |
| S6 | Envelope and averaging controls off the Acquisition tab; settings fields removed; migration | 🔲 TODO | | old YAML and files load |
| S7 | Envelope chart | 🔲 TODO | | |
| S8 | Trend y2: shaft speed | 🔲 TODO | | |
| S9 | XY chart | 🔲 TODO | | |
| S10 | Profiling evidence, README, CONTRIBUTING, CLAUDE.md, CHANGELOG | 🔲 TODO | | technical-writer audit; vibration-engineer review |
| — | Polar chart and 1x phase measurement | Deferred to R24 | | |

## Decisions

| # | Question | Decision | Date |
|---|---|---|---|
| Q1 | Unit for alarms | Alarm unit and mode on the Monitor tab, passed to `result_view()`. Channels keep their target unit (default: sensor EU) | 2026-10-19 |
| Q2 | Crest factor and kurtosis | On each card, in its spectrum chart's unit, never averaged; trend stores record-unit values | 2026-10-19 (revised) |
| Q3 | Peaks table and result cards | One card for each (spectrum chart, channel), in the chart's unit | 2026-10-19 |
| Q4 | Polar in phase 1 | Deferred to R24 | 2026-10-19 |
| Q5 | XY selection | Two ordered selectors and a swap button | 2026-10-19 |
| Q6 | Chart edits during a recording | Locked; locked controls must look disabled (S0b) | 2026-10-19 |
| Q7 | Envelope checkbox | Retired; an envelope chart replaces it | 2026-10-19 |
| Q8 | Averaged data for alarms | Never; the sustain time is the debounce | 2026-10-19 |
| — | Spectrum averaging | Setting on each spectrum chart (checkbox and N); history derived by the collector from the frame cache; no `history` argument in `result_view()` | 2026-10-19 |
| Q9 | Cards of spectrum charts not on screen | Open (recommended: collapsed one-line summary, updated without peaks) | |
| Q10 | Sustain time for `FixedThresholdHook` | Open (recommended: yes) | |
| Q11 | Chart set on a file load | Open (recommended: keep the user's set, select by index) | |
| Q12 | Averaging on non-contiguous frames | Open (recommended: contiguous only) | |
| Q13 | Rebuild session and burst trends from stored frames | Open (recommended: yes) | |

## Measurements

Record each measurement here with the method (hardware model, AWG loopback,
or `SimulatedSensor`), then move the final table to CONTRIBUTING.md,
section 5.

| Date | What | Method | Result |
|---|---|---|---|
| | GUI time for each frame, 1 to 8 channels, before S4 | `scripts/profile-pipeline` | |
| | GUI time for each frame, 6 charts, 1 on screen, after S4 | `scripts/profile-pipeline` | |
| | Extra time for the alarm-unit view during a recording | `scripts/profile-pipeline` | |
| 2026-10-19 | Session trend rebuilt from `overall_json`, accelerometer 100 mV/g, recorded in in/s, shown in in/s / g / mil | synthetic trend, `get_trend_for_display()` (scratchpad `trendcols.py`) | 273.0, 283.9, 278.5 / 0.0 x3 / 0.0 x3: defect, 3.11.1 |
| | Session load time with the trend rebuilt from frames, 1440 captures, 4 channels | `SimulatedSensor` session | |
| | Extra time for collapsed card summaries (`peaks=False`), 2 spectrum charts, 8 channels | `scripts/profile-pipeline` | |

## Notes

- No GUI viewport from an automated session. Tests make a context only.
- The averaging control is a linear power average of N frames, not an
  exponential one.
