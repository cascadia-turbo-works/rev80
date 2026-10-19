# Review of the plot-setup plan (revision 6)

Plan: `.claude/plans/2026-10-17-plot-setup.md` @ `361e9c4`.
Reviewed 2026-10-19 against `feat/plot-setup` (code identical to `main` @
`ee72064`). Each finding was checked in the code; the file and line are
given. "Computed" marks a number derived, not measured.

## Verdict

The direction is sound: the unit-independent cache already exists, the
trend already stores mV orders, and the averaging decision (3.2.1) is
right. But six findings would ship wrong numbers or wrong behaviour if
the plan were built as written (C1 to C6), and the scope is four
changes in one branch. Fix C1 to C6 in the plan, then split the work
(section 4).

## 1. Critical: wrong numbers or wrong behaviour as written

### C1. A second `process_samples()` call duplicates the trend

Plan 3.4 step 2 calls `process_samples(alarm unit)` after
`process_samples()` in the record unit. `_process_samples()` appends to
the trend and to the RPM trend when streaming (`collector.py:1197-1204`,
`1225-1234`). A second call for each frame appends every point twice.
Headless has the same path.

Fix: split the per-frame side effects from the view. One
`advance_frame(snapshot)` per new frame updates the trend and the RPM
trend; `results_for(snapshot, unit, mode)` has no side effects. Test:
one frame, record and alarm views, the trend grows by one point.

### C2. The monitor stores what the hooks see

`MonitorController.on_results(results, frame_cache)` gives the same list
to the hooks and to the capture (`controller.py:243-280`). The writer
stores `overall_json`, `peaks_json` and `scalars_json` from it
(`writer.py:52-65`, `260-278`). If the front end passes the alarm-unit
results, the session stores alarm-unit values under a channel snapshot
that names the record unit. The loader back-scales them with the record
unit: wrong values, no error.

Fix: `on_results(record_results, alarm_results, frame_cache)`. The hooks
read the alarm results; the capture stores the record results. Test:
record in in/s, alarm in g; the stored `overall_json` equals the in/s
view.

### C3. "The displayed frame" is resolved again on every call

`result_view(index=None)` resolves the displayed frame on each call. The
acquisition thread appends to the cache between calls (no lock, R59). In
one render tick the record result, the alarm result, the chart, every
card and `current_rpm()` (`collector.py:1134`) can come from different
frames. Cards can disagree with the plot, and an alarm can test a frame
other than the one stored. Today `_process_samples()` resolves the frame
once (`collector.py:1183-1184`).

Fix: take one snapshot per tick (`list(cache)` and the index) and pass
it to every view, to the history and to the shaft speed. The plan's view
cache, keyed by "frame index", has the same defect: index −1 means a new
frame each time one arrives. Replace it with a memo for one tick, keyed
by sample identity, unit, mode and N.

### C4. The fixed-limit unit migration sets in/s for every user

Plan 3.3: "when `alarm_unit` is absent and `fixed_upper_unit` is set, use
it as the alarm unit". The seed writes `fixed_upper_unit: 'in/s'` in every
config (`config.py:121`), and the GUI saves it whether or not a limit is
enabled (`gui.py:3138`). So the condition is true for every existing
config. Every user gets alarm unit in/s, and the RMS hook changes from
the record unit to velocity on acceleration jobs.

Fix: migrate only when a fixed limit is enabled. If the upper and lower
units differ and have the same quantity, convert the other limit value;
otherwise disable that limit with a warning. In all other cases the alarm
unit stays empty (record unit, today's behaviour).

### C5. Rebuilding a measurement file's RPM trend from frames truncates it

S2b rebuilds the RPM trend from the loaded frames "(sessions, bursts,
measurement files)". A measurement file stores `/trend` (five orders) and
`/tach_trend` for the whole run, up to `trend_max_points` = 500 points
(`sample.py:74`). Its frames are the cache only: 32 frames, 15 from a
seeded `acquisition.yaml`. The rebuild replaces up to 500 points with 32
at most.

Fix: measurement files keep their stored `/trend` and `/tach_trend`.
Rebuild for sessions and bursts only, which store no orders and no RPM.

### C6. Rebuilding a session trend from frames can double its memory

Stage 1 caches on the sample: `filtered_mv` at the raw length
(`collector.py:455`), `decimated_mv` (`collector.py:765`), and the PSD.
S2b runs stage 1 on every loaded frame, so every sample keeps these
arrays. Example (computed): 1440 captures x 4 channels x 1 s at
25600 Hz = 1.18 GB of raw float64, already in memory after a session
load; the filtered copies add about 1.18 GB more.

Fix: compute the five orders on a path that does not keep `filtered_mv`
and `decimated_mv`, or release them after use. Measure peak memory and
load time with a long `SimulatedSensor` session before S6b, as the plan
already says for load time.

## 2. Significant design issues

### D1. The speed-gate reference is never reset

`speed_ok()` latches `_speed_ref_rpm` from the first reading when no
fixed reference is set (`collector.py:1114-1118`). No code resets it.
Every `result_view()` on a loaded or browsed frame calls `speed_ok()`. A
file's shaft speed can become the reference for a later live recording.
This exists now, but the plan adds many more views on loaded data
(Q9 cards, S2b). Proposed: reset it when a stream starts and on every
load; the vibration-engineer agent confirms. Track it as a defect.

### D2. Averaging does nothing between S2 and S4

S2 makes `process_samples()` unaveraged. Averaging for each chart arrives
in S4, and the Acquisition-tab controls go in S6. Between S2 and S4 the
"Average spectrum" checkbox has no effect. Fix: in S2 the display call
passes the config N until S4 replaces it.

### D3. The default chart set is not today's layout

Today, two record units share one spectrum plot on two y axes. The
default set uses the first channel's unit and moves every reachable
channel to it. An accelerometer channel recorded in g, beside one in
in/s, changes to in/s. Fix: one chart of each type for each distinct
(record unit, mode) group. That gives today's split.

### D4. Envelope units and mode are not defined

`eu_scaled_raw()` returns the sensor EU only (`collector.py:1159-1163`).
To show m/s² or in/s² for a g sensor, the envelope path needs an SI scale
(no integration), with a test. The plan does not say whether the envelope
axis uses an amplitude mode. Phase-1 proposal: the sensor EU only, no
mode, with the label saying so.

### D5. New GUI test files are collected on ARM

`tests/conftest.py:14` excludes modules that match
`from rev80\.gui ` (with a space). `from rev80.gui_charts import ...` does
not match, so a new test for `gui_charts.py` is collected on a Raspberry
Pi and fails on the dearpygui import. Fix the pattern in the same commit
that adds `gui_charts.py`.

### D6. Edits while a file is loaded write `charts.yaml`

Plan 3.7: "Close applies it: save `charts.yaml`". Plan 3.9.2: "A load ...
never writes `charts.yaml`". As written, an edit while a file is loaded
writes the file's layout into `charts.yaml`. Q14 decides this, and it
must be decided before S5, not S6b.

### D7. Contiguity rule details

`rel_time` starts again at each stream start, so the difference between
two cached frames can be negative. Rule: contiguous when
0 < Δt ≤ 1.5 x the frame period. Use the achieved period of the frames
(`raw_blocksize / sample.samplerate`), not `config.acquisition_period`,
following the "use the achieved rate" invariant.

### D8. Q9 at full scale

Two spectrum charts with 8 channels give 16 cards, each with a peaks
table of up to 50 rows, in a 300 px column. Compute (computed from E19):
16 peak selections at about 0.56 ms is about 9 ms each frame, plus the
traces. The larger cost is likely the widget traffic and the scrolling.
Proposed: a collapsing header for each chart's group, which the user
opens and closes; the cards stay updated as decided. Measure as planned.

### D9. 1.0.0 makes the users' history unreadable

Monitor sessions are the long-term trend history, which is the product's
main value in predictive maintenance. In 1.0.0 every existing session
needs 0.1.4. Owner decision, kept. Two proposals that keep the app free
of old readers:

- A separate converter, `scripts/convert-0x`, that writes a version-6 or
  version-7 copy with the default layout. It is a script, not app code.
- A 0.1.5 release from `main` with the fixes that matter to people who
  keep 0.1.x for old files: the disabled-state theme (S0b), the session
  zero trend (3.11.1), clearing `tach_trend` on load, and D1.

## 3. Inconsistencies in the plan text

| Where | Problem |
|---|---|
| Revision log | Order 2, 6, 5, 4, 3. Put it in date order |
| Section 1, item 5 | "Only the chart on screen is processed" is no longer true for spectrum charts after Q9 |
| 3.2, stage 2 | "N most recent valid frames"; 3.2.1 says invalid frames in the window are dropped, not replaced |
| Section 4, invariants | "Crest factor and kurtosis: from the record-unit trace" contradicts Q2 as revised: cards use the chart unit; the trend uses the record unit |
| 3.4, step 2 | "an alarm unit different from a channel's record unit" mixes a global and a per-channel test. After C2 it is: one alarm view per frame when an alarm unit is set |
| 3.11 table and S2b | The table says measurement files store all five orders; S2b rebuilds them anyway (C5) |
| Section 6 | Q10 comes after Q16 |

## 4. Scope and order

The branch now holds four separate changes: a measurement-path refactor,
a change to alarm behaviour, a GUI rebuild, and a breaking file format.
One review of all four is too large to do well, and a defect in one
blocks the other three. Proposed split, each merged to `main` on its own:

| Part | Content | Release |
|---|---|---|
| A | S0b; session and burst zero trend (sessions and bursts only, C5); `tach_trend` cleared on load; D1 | 0.1.5, from `main` |
| B | S2 with C1 and C3: one snapshot per tick, side effects split from the view, `result_view()`. No UI change; equality tests | 0.2.0 |
| C | S3 with C2 and C4: alarm unit, `fixed_s` | 0.2.0 |
| D | S1, S4, S5, S6, S7, S8, S9: charts on the live layout | 0.3.0 or 1.0.0 |
| E | S6b, Q14 to Q16, the layout in data files, file versions | 1.0.0 |

B is the highest risk to the numbers and changes nothing visible, so it
should be reviewed alone. C needs B only. D needs B. E needs D.

## 5. Checked and correct

- dearpygui 2.0.0 frees a tag when its item is deleted. A tab bar
  rebuilt with `delete_item(tb, children_only=True)` takes the same tags
  again. Checked in a context with no viewport (scratchpad
  `dpgalias.py`).
- `_psd_for()` reads the PSD cached on each sample, so an average of N
  frames costs N additions (`collector.py:838-841`).
- A measurement file without a tachometer channel drops the live RPM
  trend on load (scratchpad `tachleak.py`).
- The history semantics in 3.2.1 match `collector.py:1186-1191` and
  `1212-1217`.
- The session zero trend (3.11.1) is reproduced (scratchpad
  `trendcols.py`).
