# Plot setup — progress tracker

Plan: `.claude/plans/2026-10-17-plot-setup.md`. Branch: `feat/plot-setup`.
Requirement: R67 in `doc/PROGRESS.md`.

This file gives the status of each step of the plan. Update it in the same
commit as the step. Status: 🔲 TODO, 🔄 In progress, ✅ Done, ⏸ Blocked.

## Steps

| Step | Content | Status | Commit | Verification |
|---|---|---|---|---|
| S0 | Branch, plan, tracker, R67 | ✅ Done | (this commit) | — |
| S1 | `charts.py` model, validation, `charts.yaml` | 🔲 TODO | | |
| S2 | `collector.result_view()`, unit-parameterised trend, view cache | 🔲 TODO | | equality test; off-bin conversion test; revert check |
| S3 | Dynamic tab bar; bottom time-series removed; spectrum, waveform, trend renderers; on-screen-only rendering | 🔲 TODO | | profiling table before and after |
| S4 | Charts tab in the configuration dialog | 🔲 TODO | | |
| S5 | Envelope chart; Envelope checkbox retired | ⏸ Blocked on Q7 | | |
| S6 | Trend y2: shaft speed | 🔲 TODO | | |
| S7 | Unit and mode combos off the Channels tab; record unit | ⏸ Blocked on Q1 | | |
| S8 | XY chart | 🔲 TODO | | |
| S9 | Polar chart and 1x phase measurement | ⏸ Blocked on Q4 | | AWG loopback; vibration-engineer review |
| S10 | Profiling evidence, README, CONTRIBUTING, CLAUDE.md, CHANGELOG | 🔲 TODO | | technical-writer audit |

## Decisions

| # | Question | Decision | Date |
|---|---|---|---|
| Q1 | Unit for Monitor, headless, files, alarms, result card | Open (recommended: per-channel record unit on the Monitor tab) | |
| Q2 | Crest factor and kurtosis from the record-unit trace | Open (recommended: yes) | |
| Q3 | Peaks table unit | Open (recommended: follow the selected spectrum chart) | |
| Q4 | Polar in phase 1 | Open (recommended: disabled; S9 as phase 1b) | |
| Q5 | XY selection by two ordered combos | Open (recommended: yes) | |
| Q6 | Chart edits during a recording | Open (recommended: no) | |
| Q7 | Retire the Envelope checkbox | Open (recommended: yes, one-time migration) | |

## Measurements

Record each measurement here with the method (hardware model, AWG loopback,
or `SimulatedSensor`), then move the final table to CONTRIBUTING.md,
section 5.

| Date | What | Method | Result |
|---|---|---|---|
| | GUI time for each frame, 1 to 8 channels, before S3 | `scripts/profile-pipeline` | |
| | GUI time for each frame, 6 charts, 1 on screen, after S3 | `scripts/profile-pipeline` | |

## Notes

- No GUI viewport from an automated session. Tests make a context only.
