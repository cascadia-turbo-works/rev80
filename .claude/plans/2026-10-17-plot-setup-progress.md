# Plot setup — progress tracker

Plan: `.claude/plans/2026-10-17-plot-setup.md` (revision 2, 2026-10-19).
Branch: `feat/plot-setup`. Requirement: R67 in `doc/PROGRESS.md`.

This file gives the status of each step of the plan. Update it in the same
commit as the step. Status: 🔲 TODO, 🔄 In progress, ✅ Done, ⏸ Blocked.

## Steps

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| S0 | Branch, plan, tracker, R67 | ✅ Done | `e3ec953`, revision 2 | — |
| S1 | `charts.py` model, validation, `charts.yaml` | 🔲 TODO | | |
| S2 | `result_view()` as the one path; `process_sample()` removed; unaveraged `process_samples(unit, mode)`; unit-parameterised trend; view cache | ⏸ Q8 | | equality test; off-bin conversion test; revert check |
| S3 | Alarm unit and mode on the Monitor tab; both `_build_anomaly_hook` copies; headless | 🔲 TODO | | hook-build defaults agree |
| S4 | Dynamic tab bar; bottom time-series removed; waveform, spectrum, trend renderers; on-screen-only rendering | 🔲 TODO | | profiling table before and after |
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
| Q2 | Crest factor and kurtosis from the record-unit trace | Yes | 2026-10-19 |
| Q3 | Peaks table unit | Open (recommended: follow the spectrum chart on screen) | |
| Q4 | Polar in phase 1 | Deferred to R24 | 2026-10-19 |
| Q5 | XY selection | Two ordered selectors and a swap button | 2026-10-19 |
| Q6 | Chart edits during a recording | Not answered; existing lock kept | |
| Q7 | Envelope checkbox | Retired; an envelope chart replaces it | 2026-10-19 |
| — | Spectrum averaging | Moved from the Acquisition tab to each spectrum chart: checkbox and N | 2026-10-19 |
| Q8 | Record and alarm results unaveraged | Open (recommended: yes) | |

## Measurements

Record each measurement here with the method (hardware model, AWG loopback,
or `SimulatedSensor`), then move the final table to CONTRIBUTING.md,
section 5.

| Date | What | Method | Result |
|---|---|---|---|
| | GUI time for each frame, 1 to 8 channels, before S4 | `scripts/profile-pipeline` | |
| | GUI time for each frame, 6 charts, 1 on screen, after S4 | `scripts/profile-pipeline` | |
| | Extra time for the alarm-unit view during a recording | `scripts/profile-pipeline` | |

## Notes

- No GUI viewport from an automated session. Tests make a context only.
- The averaging control is a linear power average of N frames, not an
  exponential one.
