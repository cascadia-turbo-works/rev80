# Plot setup — wire channels to charts

Branch: `feat/plot-setup`, from `main` @ `ee72064` (v0.1.4).
Progress tracker: `.claude/plans/2026-10-17-plot-setup-progress.md`.
Review of revision 6: `.claude/plans/2026-10-19-plot-setup-review.md`.
Requirement: R70 in `doc/PROGRESS.md`. Related: R24 (polar), R33 (split
panes), R42 (crest and kurtosis trend), R43 remainder (RPM on the trend),
R50 and R59 (collector thread safety), R71 (anomaly-trigger table).

## Revisions

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-10-17 | First plan |
| 2 | 2026-10-19 | Q1, Q2, Q4, Q5, Q7 decided; spectrum averaging moves to each spectrum chart |
| 3 | 2026-10-19 | Q2 and Q3 revised (cards belong to a spectrum chart); Q6, Q8 decided; `history` leaves `result_view()`; visible disabled state |
| 4 | 2026-10-19 | Data loaded from a file; session zero-trend defect found |
| 5 | 2026-10-19 | Q9, Q10 decided; R71 recorded |
| 6 | 2026-10-19 | Q11 to Q13 decided: chart layout in data files, new file versions, Rev80 1.0.0 |
| 7 | 2026-10-20 | Review findings applied. Q14 to Q16 decided. Work split into parts A to E and two releases. A new `DataCollector` for every load and connect. Each anomaly hook has its own unit. Converter script for 0.x files. Default layout: one time waveform and one spectrum |

## 1. Releases and parts

| Part | Content | Release |
|---|---|---|
| A | Defects in 0.1.4: visible disabled state; a new `DataCollector` for each load and connect; session and burst trends from the stored frames; averaging on contiguous frames only | 0.1.5 |
| B | Measurement-path refactor: one frame snapshot for each render tick; frame side effects split from the views; `result_view()` | 0.1.5 |
| C | Anomaly hooks: each hook has its own unit and amplitude mode; fixed-limit sustain time | 0.1.5 |
| D | Charts: Charts tab, one main-window tab for each chart, result cards for each spectrum chart, chart-driven units | 1.0.0 |
| E | Chart layout in the data files, new file versions, converter for 0.x files | 1.0.0 |

Release flow:

1. Parts A, B and C on `feat/plot-setup`, in that order, until complete.
2. Merge `feat/plot-setup` into `develop` for the field test.
3. Merge `develop` into `main` and tag `v0.1.5`. The tag runs
   `.github/workflows/release.yml` and makes a draft release.
4. Parts D and E continue on `feat/plot-setup`, then the same chain, tag
   `v1.0.0`.

Each part leaves the suite green at its last commit. Between the steps of
one part the branch is work in progress (owner decision): a control can
have no effect for some commits.

## 2. Request (parts D and E)

1. A **Charts** tab in the configuration dialog with a table, one row for
   each chart. Below the table: a chart-type combo and a **+** button.
   Types in this work: time waveform, trend, spectrum, envelope, XY. Polar
   is deferred to R24.
2. Columns: **−** (remove), type (read-only), name (editable; the tab
   label), channels (a checkbox for each channel; XY: two ordered
   selectors X and Y and a swap button), unit and amplitude mode, options.
3. **The chart sets the unit of every series on it.** Each chart has one
   y axis. One channel can show on two charts in two units. XY uses one
   unit on x and y. Trend: shaft speed on a second y axis. Spectrum: an
   **Average** checkbox and an integer **N**.
4. One main-window tab for each chart, named for the chart. The tab bar
   fills the middle pane. The time-series plot below the tabs is removed.
5. Plot series are drawn only for the chart on screen. The result cards of
   every spectrum chart update on each frame (Q9).
6. The Acquisition tab loses the **Envelope analysis** checkbox and the
   **Average spectrum** controls.
7. Every data file stores its chart layout. A load sets the layout.
8. Out of scope: split panes (R33), polar (R24), the anomaly-trigger table
   (R71).

## 3. Current state (facts the design depends on)

| Fact | Where |
|---|---|
| Unit and mode are per channel (`channel_target_units`, `channel_amplitude_modes`); an empty unit is the sensor EU | `sample.py:61-62`, `collector.py:227` |
| `process_sample()` scales the cached mV PSD and the five mV overalls (orders −2 to +2) to the target unit. Stage 1 (filter, decimate, PSD, overalls) is cached on the sample | `collector.py:770-1050` |
| Stage 1 keeps `filtered_mv` at the raw length and `decimated_mv` on each sample | `collector.py:455`, `765` |
| `_process_samples()` resolves the displayed frame once, appends to the trend and to the RPM trend when streaming, and returns the results | `collector.py:1174-1235` |
| `current_rpm()` resolves the displayed frame again | `collector.py:1134` |
| The acquisition thread appends to the frame cache; `DataCollector` has no lock | CLAUDE.md, R59 |
| `MonitorController.on_results(results, frame_cache)` gives one list to the hooks, to `update_baseline()` and to the capture writer. The writer stores `overall_json`, `peaks_json` and `scalars_json` from it | `controller.py:243-280`, `479-480`; `writer.py:52-65` |
| `valid_results()` applies the overflow, degraded and speed-gate filter; `CompositeAnomalyHook` calls it | `anomaly.py:42-53`, `449-455` |
| `FixedThresholdHook` converts each limit to the result unit by `UNIT_TO_SI` only (same quantity), ignores the amplitude mode, and fires on one frame | `anomaly.py:347-435` |
| The config seed and the GUI save `fixed_upper_unit` and `fixed_lower_unit` (`'in/s'`) whether or not a limit is enabled | `config.py:121-124`, `gui.py:3138-3141` |
| `speed_ok()` latches `_speed_ref_rpm` from the first reading; nothing resets it | `collector.py:1114-1118` |
| The GUI makes one `DataCollector` in `__init__` and reuses it for every load and connect | `gui.py:325` |
| `load_data()` and the session loaders clear the cache before they read the file version | `collector.py:1371-1378`, `1650-1660` |
| Session and burst loaders rebuild the trend from `overall_json` (one value, record unit) into one order column; the other columns stay 0.0 | `collector.py:1689-1725`, `1849-1870`; reproduced, see A3 |
| Measurement files store `/trend` (five orders, up to `trend_max_points` = 500) and `/tach_trend`; the cache holds 32 frames (15 seeded) | `collector.py:1331-1360`, `sample.py:74` |
| Session captures are `interval_s` apart (default 600 s) | `config.py:98` |
| The envelope spectrum is in the sensor EU, scaled so a modulation of depth d on carrier A reads d·A/2 (0-P of the sideband) | `collector.py:1144-1163`, `envelope.py:43-46` |
| `tests/conftest.py` excludes GUI test modules on ARM by the pattern `from rev80\.gui ` (with a space) | `tests/conftest.py:14` |
| dearpygui 2.0.0 frees a tag when its item is deleted; a tab bar rebuilt with the same tags works | checked, scratchpad `dpgalias.py` |

## 4. Part A — defects in 0.1.4

### A1. Locked controls look disabled

`_set_recording_lock()` disables the controls, but `gui.py` binds no theme
for the disabled state, so a disabled button looks enabled. A user pressed
the acquisition setup button during a recording and saw nothing happen.

- One global theme with `dpg.theme_component(..., enabled_state=False)`
  for buttons, combos, checkboxes, input fields and sliders, in muted
  colours (`_c("MUTED")`). Bound once in `_create_gui()`.
- While locked, each control in `_RECORDING_LOCKED_CONTROLS` has the
  tooltip "Stop the recording to change this."
- Test (GUI context): the theme has a disabled-state component for
  `mvButton`; lock and unlock toggle every locked control.

### A2. A new `DataCollector` for every load and every connect

Owner decision (review D1). Stale state survives today: the latched speed
reference, the RPM trend, the stage-1 caches, the cache depth, the cursor.
Replacing the collector removes the class of defect instead of resetting
each field.

- `GUI._replace_collector(new)`: the one place `self.collector` changes
  after `__init__`. Order: refuse during a recording (the load and connect
  controls are already locked); stop the stream; close the old device
  (`disconnect_sensor()`) before a new one opens, or the next open fails
  with `PICO_NOT_FOUND`; assign; call `_on_data_source_changed()`.
- **Load.** Build a new `DataCollector`, load the file into it, and swap
  only when the load succeeds. A refused or failed file leaves the old
  collector and the screen unchanged. This replaces the plan-6 rule "check
  the version before any state is cleared": the old state is never cleared.
- **Connect.** Build a new `DataCollector` with the settings from
  `acquisition.yaml`, connect the sensor, restore the device YAML
  (channels, siggen), assign the sensors from the registry and the
  tachometer settings. The same code as now, moved into one builder,
  `_build_live_collector(sensor)`.
- **Session reprocess** (`_on_sb_reprocess`): the thread builds and loads
  its own collector and hands it to the render thread, which swaps it. The
  thread no longer touches the collector on screen (part of R50).
- Disconnect without a new device keeps the collector and its data, as
  now.
- `_on_data_source_changed()` is the one GUI hook after a swap. In part A
  it does what the load paths do now (series, axis assignment, cards,
  connection summary, spectrum info, notes, autoscale). Part D extends it
  to the charts. `_on_load_file()`, `_load_from_path()`,
  `_on_session_list_select()`, `_on_burst_list_select()` and the device
  connect paths call it instead of their own copies.
- No GUI code may keep a reference to `self.collector`, its `data` dict or
  its cache across a swap. Search for bound methods of the collector given
  as callbacks.
- Tests: load a file after live frames with a latched speed reference and
  an RPM trend; neither survives. A refused file leaves the frame cache
  identical. A connect after a file load uses the `acquisition.yaml`
  settings, not the file's.
- Headless keeps one collector for its run.

### A3. Session and burst trends from the stored frames

Defect: `load_monitor_session()` and `load_monitor_burst()` rebuild the
trend from `overall_json` into one order column; the other four stay 0.0.
Reproduced 2026-10-19 (scratchpad `trendcols.py`, an accelerometer at
100 mV/g, recorded in in/s): in/s 273.0, 283.9, 278.5; g 0.0, 0.0, 0.0;
mil 0.0, 0.0, 0.0. Reachable now by a channel-unit change after a session
load.

- Sessions and bursts: compute the five mV orders of each loaded frame
  from its stored waveform. **Use a path that does not keep `filtered_mv`
  and `decimated_mv` on the sample** (review C6): a 1440-capture,
  4-channel session at 1 s blocks holds 1.18 GB of raw float64 (computed),
  and the cached copies would add about as much again. Keep the five
  orders on the sample.
- A frame with no waveform (tachometer, damaged group): NaN in all five
  columns, never 0.0.
- Shaft-speed trend for sessions and bursts from the loaded tachometer
  samples (each has a `TachResult` from its edge times), usable readings
  only.
- **Measurement files keep their stored `/trend` and `/tach_trend`**
  (review C5): they hold up to 500 points; the frames are 32 at most.
- Equality test: in the record unit, the rebuilt trend equals
  `overall_json` to float tolerance (for sessions written with the same
  averaging state). Reproduce the zero trend first, then fix it; revert
  check.
- Measure load time and peak memory of a 1440-capture, 4-channel
  `SimulatedSensor` session. Record it in the tracker, then CONTRIBUTING.md
  section 5.

### A4. Averaging on contiguous frames only

A session's captures are 600 s apart by default; an average of N = 8
spans 80 min and is labelled "averaging 8 frames".

- The walk back stops at the first frame that is not contiguous with the
  next: contiguous when 0 < Δ`rel_time` ≤ 1.5 × the frame period. The frame
  period is the achieved one, `raw_blocksize / sample.samplerate`, not
  `config.acquisition_period` (review D7). A negative Δ (a new stream) is a
  gap.
- The count line says why: "averaging 1 of 8 frames (frames not
  contiguous)".
- Tests: a session gives k = 1; a burst and a live cache give k = N; a
  stream restart inside the window stops the walk.

## 5. Part B — measurement-path refactor

### B1. One frame snapshot for each render tick

Review C3. Every view in one tick must come from the same frame.

```python
@dataclass(frozen=True)
class FrameSnapshot:
    frames: tuple          # tuple(cache) at the time of the snapshot
    index: int             # position of the displayed frame in `frames`
    is_live: bool          # streaming (newest frame) or browsing (cursor)

def snapshot(self) -> FrameSnapshot     # DataCollector
```

- The render loop takes one snapshot for each new frame. Every call in
  that tick uses it: the frame advance, the record results, the hook
  views, the display, `current_rpm()`.
- `current_rpm(snapshot)` and the speed gate read the tachometer sample of
  the snapshot frame.
- History for averaging is taken from `snapshot.frames`.

### B2. Frame side effects split from the views

Review C1.

- `advance_frame(snapshot)`: once for each new live frame. Appends the
  five mV orders, crest factor and kurtosis (record unit) to the trend and
  the usable shaft speed to the RPM trend. Nothing else changes state.
- `results_for(snapshot, unit=None, mode=None, n_averages=1)`: one
  `ChannelResult` for each vibration channel. No side effects. Callable any
  number of times.
- `process_samples()` is removed. Callers: the GUI render loop, headless
  (`headless.py:644`), the tests.

### B3. `result_view()`

```python
def result_view(self, snapshot, ch, unit=None, amplitude_mode=None,
                n_averages=1, peaks=True) -> ChannelResult | None
```

- `unit=None`: the channel's target unit, then the sensor EU.
  `amplitude_mode=None`: the channel's mode, then `0-P`.
- Returns None for a channel that cannot reach `unit` (no sensor, another
  quantity, more than ±2 integration steps). It logs once for each
  (channel, unit).
- Stage 1 (cached, unit-independent) does not change.
- Stage 2: power average over the contiguous valid frames among the N most
  recent (A4; invalid frames are dropped, not replaced); integration;
  sensitivity; SI factor; amplitude scale; F_max truncation; peaks; the
  overlap-save trace; crest factor and kurtosis of that trace.
- `process_sample()` is removed. A private
  `_view_of_sample(ch, sample, unit, mode, history=())` holds stage 2. The
  session reprocess calls it for a sample that is not in a snapshot.
  `scripts/advanced_plots.py` uses `result_view()`.
- Memo for one tick, keyed by (sample identity, unit, mode, N, peaks). Not
  keyed by cache index (review C3). Cleared with each new snapshot.
- `get_trend_for_display(unit=None, amplitude_mode=None, channels=None)`.
- In 0.1.5 the display uses the record unit and the config averaging
  (`averaging_enabled`, `n_averages`), as now. The record results and the
  hook views are never averaged (Q8).

Tests:

- Equality: for each shipped unit pair and mode, `result_view()` gives
  arrays equal to `process_sample()` before the change (reference captured
  first).
- Conversion (`tests/test_measurement_validity.py`): off-bin tone, non-zero
  phase; in/s and g views agree through `v = a / (2 π f)`; the three modes
  agree through `amplitude_scale()`. Revert check.
- One tick, record and display views: the trend grows by one point.
- Snapshot: a frame appended between two `result_view()` calls with the
  same snapshot does not change the result.
- `tests/test_spectral_averaging.py` moves to the `n_averages` argument.

## 6. Part C — anomaly hooks

### C1. Each hook asks for its own view

Review C2 and C4; owner decision: the RMS (EWMA baseline) hook has its own
unit and mode, separate from the fixed-limit units.

```python
class ResultViews(Protocol):           # in monitor/anomaly.py; no collector import
    def results(self, unit: str | None, mode: str | None) -> list: ...
    @property
    def record(self) -> list: ...      # record unit and mode, never averaged
```

- `MonitorController.on_results(views, frame_cache)`. The capture writer
  stores `views.record` (record unit, as the channel snapshot says). The
  hooks and `update_baseline()` get `views`.
- The collector supplies `FrameViews(collector, snapshot)`: `results()`
  calls `results_for(snapshot, unit, mode)`, memoised for the tick, then
  `valid_results()`. `valid_results()` stays the one place the gate is
  applied.
- `RmsThresholdHook(unit, mode, ...)`: reads `views.results(unit, mode)`.
  Config keys `rms_unit`, `rms_amplitude_mode`; empty means the record unit
  and mode (today's behaviour). Baselines are kept in that unit.
- `FixedThresholdHook`: the upper limit reads
  `views.results(fixed_upper_unit, fixed_upper_mode)`, the lower limit
  `views.results(fixed_lower_unit, fixed_lower_mode)`. New keys
  `fixed_upper_mode`, `fixed_lower_mode`; empty means the record mode
  (today's comparison). The `UNIT_TO_SI` conversion goes: the view is in
  the limit's unit. A velocity limit on an accelerometer now works (today
  it is skipped as another quantity). A channel with no sensor is skipped
  with one warning, as now.
- No migration is needed: every new key is empty by default, which is
  today's behaviour (review C4 does not arise).
- `SpectralThresholdHook` (headless only, R39): `views.record`, unchanged.
- `MonitorController` builds the burst pre-trigger `overall_json` from the
  stored mV orders and the record unit, as now.

### C2. Fixed-limit sustain time

Owner decision Q10. Key `fixed_s`, default 0 s = one frame (today). Frames
= `round(fixed_s / period) + 1`, as for `rms_s`. A frame that
`valid_results()` drops resets the count. Its own field beside the fixed
limits.

### C3. Both front ends

- Monitor tab: unit and mode combos in the RMS section; a mode combo
  beside each fixed-limit unit combo; the `fixed_s` field.
- Both `_build_anomaly_hook` copies (`gui.py`, `headless.py`) and the
  config seed change in the same commit. `tests/test_anomaly_hook_build.py`
  checks that their defaults agree.
- Tests: RMS hook in g on a channel recorded in in/s fires on the g
  overall; the stored `overall_json` is in in/s (review C2); upper limit
  in in/s 0-P with the record mode P-P compares 0-P values; `fixed_s` = 0
  fires on one frame (equality with today); `fixed_s` > 0 needs
  consecutive valid frames; empty keys give today's results bit for bit.
- Cost: measure the extra views during a recording on a Raspberry Pi 3
  with 8 channels (headless) and on the GUI PC.

## 7. Part D — charts

### D1. Chart model — `src/rev80/charts.py`

No dearpygui import.

```python
CHART_TYPES = ('waveform', 'trend', 'spectrum', 'envelope', 'xy')

@dataclass
class ChartSpec:
    chart_id: str             # stable; tags derive from it, never from the name
    chart_type: str
    name: str
    channels: list[int]       # display order; xy: [x, y]
    unit: str                 # explicit: the chart sets the unit of every series
    amplitude_mode: str       # spectrum, trend, envelope; not waveform or xy
    show_rpm: bool = False    # trend
    tach_channel: int | None = None
    averaging: bool = False   # spectrum
    n_averages: int = 8       # spectrum; clamped to the cache depth at use

@dataclass
class ChartSet:
    charts: list[ChartSpec]
    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d) -> 'ChartSet'      # skips a bad entry, logs it

def default_layout(vibration_channels: list[int],
                   record_unit_of: Callable[[int], tuple[str, str]]) -> ChartSet
```

- **Default layout** (Q15): one time waveform and one spectrum, with all
  vibration channels: the default before this feature. Unit and mode: the
  record unit of the first vibration channel. A channel that cannot reach
  it stays on the chart with a legend note (D4). `default_layout()` takes
  plain data, so the converter (E3) and headless can call it.
- Validation (pure): `allowed_units(chart_type, sensor_eus)` and
  `channel_selectable(spec, ch, roles, sensor_eus)`.
  - Spectrum, waveform, trend, XY: units within ±2 integration steps of
    every checked channel's sensor EU.
  - Envelope: units with 0 integration steps from the sensor EU (same
    quantity, SI scale only; review D4). Mode: `0-P` is the native
    sideband amplitude; RMS and P-P by `amplitude_scale()` relative to
    `0-P`.
  - A channel with no sensor: `mV` charts only.
  - Tachometer: only as `tach_channel` of a trend. Never in `channels`.
  - XY: two different channels.
- A chart with no usable channel stays in the set and says why on its tab.

### D2. Chart-driven units (owner decision, review D3 and D4)

The chart sets the unit and mode of every series on it, for every chart
type, in the Charts tab. The record unit (Channels tab) sets only what is
stored and the trend's stored scalars. The envelope path gets the SI scale
step for D1's envelope units, with a test against the sensor-EU result.

### D3. Rendering

For each new frame, after part B's always-run work:

1. For the chart on screen: one `result_view()` for each channel in the
   chart's unit, mode and N, and `set_value` on its series. A spectrum
   chart also updates its cards.
2. For every other spectrum chart: one `result_view()` for each channel,
   peaks included, and the cards only (Q9). No series update.

- On-screen test: `_chart_on_screen(cid)`, from `_envelope_on_screen()`,
  failing open.
- A tab change renders the new chart at once from the current snapshot.
- Measure: 6 charts with 1 on screen against today's 3 tabs; 2 spectrum
  charts × 8 channels of cards. E19 in CONTRIBUTING.md.

### D4. Chart types

| Type | Data | X axis | Y axis | Notes |
|---|---|---|---|---|
| Time waveform | `result_view().time_data` | Time, ms | chart unit | Integrated traces start after t = 0; keep `_last_time_x0_ms` for each chart |
| Spectrum | `result_view(n_averages)`: spectrum, peaks, 1x | Frequency, Hz | unit mode | Average and N per chart; "averaging k of N frames"; window N × frame period in the Charts row; owns its cards |
| Trend | `get_trend_for_display(unit, mode, channels)` | Time, s | Overall, unit mode, band | y2: shaft speed (`rotation_from_rpm`), usable readings only; browse cursor per chart; NaN is a gap |
| Envelope | `eu_scaled_raw()` × SI scale, `envelope_spectrum()` | Modulation frequency, Hz | unit mode | Band controls in the chart tab; auto-band cache key `(chart_id, ch, rate)` |
| XY | two traces of one frame | channel X | channel Y | Same unit; equal axis scale; same span |

A channel that cannot reach the chart unit, or is not in the data: empty
series with the reason in the legend ("Ch B: no sensor, cannot show
in/s"). Never mV under an engineering-unit axis.

### D5. Result cards

- One card for each (spectrum chart, channel): overall, crest factor,
  kurtosis, 1x level and peaks table in the chart's unit and mode. Each
  value has its unit. The overall of an averaging chart is averaged
  ("avg k"); crest factor and kurtosis never are.
- Cards are grouped under a **collapsing header** for each spectrum chart,
  named for the chart (review D8). The user opens and closes a group; the
  cards update either way (Q9).
- A tachometer channel has one shaft-speed card for each channel. The
  overflow warning stays one line for each channel.
- The peaks-table widget pool (E19) is keyed by (chart_id, ch).

### D6. Charts tab

- `CONFIG_TAB_CHARTS`, after Channels and Tachometer. Opened also from a
  **Charts** button above the tab bar (`BTN_CHARTS_SETUP`, in
  `_RECORDING_LOCKED_CONTROLS`; Q6).
- `dpg.table`: `−`, Type, Name, Channels, Unit, Options. Channels: a
  checkbox for each vibration channel in the channel colour; a channel the
  unit cannot use is disabled with the reason in a tooltip; a checked
  channel that is not present shows greyed "not present" and stays checked.
  **The table never removes a channel because it is absent now.** XY: X and
  Y combos and a swap button (Q5). Unit: `unit mode` items from
  `allowed_units()`. Options: trend — shaft speed on y2 and a tachometer
  combo; spectrum — Average, N (1 to cache depth), window in seconds.
- Below the table: type combo and `+`.
- Edits go to a working copy. Close applies it to the layout in effect
  (`collector.chart_set`) and rebuilds the tabs.
- **Q14**: with live data, Close also saves `charts.yaml`. With a file
  loaded, Close changes the layout in effect only; a later Save of a
  measurement stores it. A **Use for live data** button, shown only with a
  file loaded, copies the layout to `charts.yaml`.

### D7. Main window

- Delete `PLT_SAMPLE`, `TIME_PLOT_HEIGHT`, `_update_axis_assignment`,
  `_reassign_series_to_axis` and the second y axes.
- Tags from `chart_id`: `ui.chart_tab(cid)`, `ui.chart_plot(cid)`,
  `ui.chart_axis(cid, 'x'|'y'|'y2')`, `ui.chart_series(cid, ch)`,
  `ui.chart_peaks(cid, ch)`, `ui.chart_one_x(cid, ch)`.
- `_build_chart_tabs()` rebuilds the tab-bar children from
  `collector.chart_set`; keeps the selected `chart_id` if it exists, else
  selects the first tab.
- `_on_data_source_changed()` (A2) also rebuilds the tabs and the cards.
- Update every consumer of the old tags: `_ensure_legends`,
  `_autoscale_plots`, `_unlock_autoscaled_axes`, `_update_trend_cursor`,
  `_add_channel_series`, `_remove_channel_series`, `_redraw_all_channels`,
  `_refresh_channel_names`, `_update_avg_count_text`, the keyboard
  handlers, the session-browser path.
- New module `gui_charts.py` for the chart builders and renderers. Update
  the ARM pattern in `tests/conftest.py` to match `rev80.gui_charts` in the
  same commit (review D5), with a test of the pattern.

### D8. Live layout and configuration

- `charts.yaml` through `config.charts_config_path()`. Unreadable or
  invalid: log it, use the default layout, do not overwrite the file.
- The collector holds the layout in effect: `DataCollector.chart_set`. A
  live collector (A2) takes it from `charts.yaml`.
- `acquisition.yaml` migration, once: `envelope_enabled: true` adds an
  envelope chart; `averaging_enabled` and `n_averages` set the averaging of
  the default spectrum.
- Remove `envelope_enabled`, `averaging_enabled`, `n_averages`,
  `n_averages_effective` from `AcquisitionSettings` and the Acquisition-tab
  controls (`ACQ_DLG_ENV_ENABLED`, `ACQ_DLG_AVG_*`).
- Channels tab: unchanged; the target unit and mode are the record unit.

## 8. Part E — chart layout in the data files

### E1. Format

| File | Writer | 0.1.x | 1.0.0 |
|---|---|---|---|
| Measurement | `DataCollector.save_data()`, `_FILE_VERSION` | 5 | 6 |
| Session `session.h5` | `MonitorWriterThread`, `monitor.writer._FILE_VERSION` | 6 | 7 |

- `/metadata` attribute `chart_layout_json` = `json.dumps(ChartSet.to_dict())`,
  the same dict as `charts.yaml`.
- `/metadata` attribute `rev80_version` = `rev80.__version__`.
- Each session capture and burst frame stores the five mV orders of each
  vibration channel (`orders_json`, orders −2 to +2). A session or burst
  load then reads the trend and does no DSP: today the A3 rebuild adds
  about 1.3 s to a 1440-capture, 4-channel load (CONTRIBUTING.md E22). The
  converter (E3) computes them from the stored waveforms.
- Measurement: the layout in effect at Save. Session: the layout at the
  start of the recording (charts are locked during a recording).
- **Headless** (Q15): `charts.yaml` from its config directory if present,
  else `default_layout()`.

### E2. Reading

- `_restore_metadata(f, version)` accepts exactly the current version of
  its file type.
- Older (Q11): refuse, ERROR: "<name>: data file version 5 was written by
  Rev80 0.x. Rev80 1.0.0 reads version 6. Open it with Rev80 0.1.5, or
  convert it with `scripts/convert-0x`."
- Newer (Q16): refuse, ERROR: "<name>: data file version 7 was written by
  Rev80 <rev80_version>. Update Rev80."
- A refused file changes nothing: it loads into a new collector (A2) that
  is discarded.
- No `chart_layout_json`, or an invalid one: warning and `default_layout()`.
  The stored layout is validated (D1); a chart that does not validate says
  why on its tab.
- Remove the old-format reader code: the v3 frame path in
  `_read_frame_group()`, the v3 shared trend axis in `load_data()`,
  `_loaded_channel_units()` if unused.
- The same check in every reader: `_scan_session_dirs()` lists a 0.x
  session as "Rev80 0.x session: convert or open with 0.1.5";
  `reprocess_session_trend()`, `_on_sb_save_config()`,
  `scripts/advanced_plots.py`.

### E3. Converter for 0.x files (review D9)

`scripts/convert-0x <file or session dir> [--out DIR]`. A script, not app
code.

- Reads with `h5py` only, and writes a **copy**, never in place: a
  measurement `<name>.v6.h5`; a session directory copy with `session.h5`
  at version 7.
- Accepts measurement version 4 and 5, session version 6. Version 3 is
  refused: "open it in Rev80 0.1.5 and save it again". (v3 frames are in
  the recorded unit, not mV.)
- Copies every group and attribute, sets the version, writes
  `rev80_version` = "convert-0x <version>" and `chart_layout_json` from
  `default_layout()` (Q15), using the stored channel roles and record
  units.
- Tests: a v5 file and a v6 session (written by the current writer, then
  the new attributes removed and the version set back) convert, then load
  in 1.0.0 with the default layout and frames and trends equal to the
  source. The source file is unchanged (checksum).

### E4. Tests

- Round trip, both file types; bursts and single captures get the
  session's layout.
- Older and newer versions refused with the messages above; the screen
  state unchanged; revert check on each refusal.
- Missing layout: default layout and a warning.

## 9. Invariants (check at each step)

- [ ] Tachometer channels: no `ChannelResult`, no unit scaling, never in
      `ChartSpec.channels`.
- [ ] `rpm` is `None` with no reading; only usable readings on a trend.
- [ ] Overflow and degraded frames: shown and flagged, never trended,
      averaged or alarmed on.
- [ ] One snapshot per tick; every view of the tick uses it.
- [ ] Frame side effects only in `advance_frame()`, once per live frame.
- [ ] The capture stores the record view; hooks use their own views.
- [ ] `valid_results()` is the only place the speed gate is applied.
- [ ] Power-domain averaging over contiguous valid frames only.
- [ ] Crest factor and kurtosis are never averaged. Cards: chart unit.
      Trend: record unit.
- [ ] Monitor results, alarms and trends do not depend on the tab on
      screen.
- [ ] Achieved rate and achieved frame period, never the config values.
- [ ] No trend value is 0.0 because it was not recorded.
- [ ] A load or connect makes a new collector; a refused file changes
      nothing.
- [ ] A load never writes `charts.yaml`; the Charts tab never drops a
      checked channel because it is absent now.
- [ ] No dearpygui import in `charts.py`, `collector.py`, `sample.py`,
      `monitor/`.
- [ ] Source-inspection rules for `gui.py` and `headless.py` text.
- [ ] No viewport in tests.
- [ ] `max_burst_s` and `compression_level` keep their saved values.

## 10. Work breakdown

Each step: tests first where behaviour changes, a revert check for each
fix, `ruff check src/ tests/`, the suite without the hardware file, and
CHANGELOG, PROGRESS and README in the same commit.

| Step | Content | Tests |
|---|---|---|
| A1 | Visible disabled state | disabled-state theme; lock and unlock |
| A2 | `_replace_collector()`, `_build_live_collector()`, load into a new collector, reprocess thread hands over, `_on_data_source_changed()` | no stale speed reference or RPM trend; refused load leaves state; connect uses `acquisition.yaml` |
| A3 | Session and burst trends from frames, without the stage-1 arrays; NaN; RPM trend; measurement files keep stored trends | reproduce, then fix; equality with `overall_json`; NaN gap; load time and memory measured |
| A4 | Contiguous-frame averaging | session k = 1; burst and live k = N; restart stops the walk |
| B1 | `FrameSnapshot`, `snapshot()`, `current_rpm(snapshot)` | append between calls does not change a result |
| B2 | `advance_frame()`, `results_for()`; `process_samples()` removed; GUI and headless callers | trend grows by one point per tick |
| B3 | `result_view()`, `_view_of_sample()`, tick memo, unit-parameterised trend | equality; conversion; revert check; averaging tests moved |
| C1 | `ResultViews`, `FrameViews`, `on_results(views, ...)`, RMS unit and mode, fixed-limit modes | stored `overall_json` in the record unit with an RMS hook in g; empty keys give today's results |
| C2 | `fixed_s` | 0 s fires on one frame; > 0 needs consecutive frames |
| C3 | Monitor-tab controls; both hook builders; headless; seed | defaults agree; Pi 3 cost measured |
| — | Release 0.1.5: CHANGELOG, README, CONTRIBUTING; vibration-engineer review of A3, A4, B, C; technical-writer audit; merge to `develop`, field test, merge to `main`, tag `v0.1.5` | |
| D1 | `charts.py`: model, validation, `default_layout()`, YAML | round trip; bad entry skipped; bad file not overwritten; units; tachometer refused; XY needs two; default = waveform + spectrum |
| D2 | Main window: tab bar from `chart_set`, Charts button, renderers for waveform, spectrum, trend; cards per spectrum chart with collapsing headers; on-screen drawing; tab-change render; `gui_charts.py`; conftest pattern | tabs from a set; selection kept; hidden chart not drawn; legend notes; ARM pattern |
| D3 | Charts tab: rows, checkboxes, XY selectors and swap, unit combo, options; Q14 apply and "Use for live data" | add, remove, swap; disabled channel; file-loaded edits do not write `charts.yaml` |
| D4 | Acquisition-tab controls and settings fields removed; `acquisition.yaml` migration | old YAML migrates |
| D5 | Envelope chart with SI scale and mode | equals the sensor-EU result times the SI factor; only on screen |
| D6 | Trend y2: shaft speed | usable only; `None` no point; no unit scaling |
| D7 | XY chart | two traces, same span; same unit |
| E1 | Layout and `rev80_version` written; versions 6 and 7; headless layout | round trip |
| E2 | Exact-version reading, older and newer refused, old reader code removed, every reader | messages; state unchanged; revert checks |
| E3 | `scripts/convert-0x` | converted files load equal; source unchanged; v3 refused |
| — | Release 1.0.0: profiling table (E19), README (Charts tab, Data files v6 and v7, converter), CONTRIBUTING, CLAUDE.md (file versions, collector replacement, snapshot rule), CHANGELOG with a Breaking section; reviews; merge chain; tag `v1.0.0` | |

## 11. Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Unit for alarms | Each hook has its own unit and mode (revised in rev 7, C1). Channels keep the record unit |
| Q2 | Crest factor and kurtosis | Cards: chart unit, never averaged. Trend: record unit |
| Q3 | Peaks table and cards | One card for each (spectrum chart, channel), chart unit |
| Q4 | Polar | Deferred to R24 |
| Q5 | XY selection | Two ordered selectors and a swap button |
| Q6 | Chart edits during a recording | Locked; locked controls look disabled (A1) |
| Q7 | Envelope checkbox | Retired; an envelope chart replaces it |
| Q8 | Averaged data for alarms | Never |
| — | Averaging state | Chart owns the setting; the collector derives history from the snapshot |
| Q9 | Cards of charts not on screen | Always shown and updated; collapsing header per chart |
| Q10 | Fixed-limit sustain time | `fixed_s`, default 0 s |
| — | Anomaly-trigger table | R71, not in this work |
| Q11 | Layout in data files | Stored; a load sets it; old versions refused |
| Q12 | Averaging on non-contiguous frames | Contiguous only (A4) |
| Q13 | Loaded trends from frames | Yes, shaft speed included; sessions and bursts only (A3) |
| Q14 | Charts-tab edits with a file loaded | Layout in effect only; "Use for live data" copies to `charts.yaml` |
| Q15 | Default and headless layout | Default: one time waveform and one spectrum, all vibration channels. Headless: `charts.yaml` if present, else the default |
| Q16 | Newer file | Refused |
| — | Stale state | A new `DataCollector` for every load and connect (A2) |
| — | 0.x files | `scripts/convert-0x` with the default layout (E3) |
| — | Releases | A, B, C → 0.1.5; D, E → 1.0.0 |

## 12. Risks

- **A2 touches every load and connect path.** 259 references to
  `self.collector` in `gui.py`; any code that keeps a reference across a
  swap is a defect. Search for bound collector methods passed as callbacks
  and for module-level references.
- **Part B changes the measurement path in a patch release.** The equality
  tests are the guard. The vibration-engineer review and the field test on
  `develop` are mandatory before `v0.1.5`.
- **Part C changes alarm behaviour in a patch release** only where a user
  sets a new key; empty keys must give today's results bit for bit.
- **A3 memory and load time** are not measured; measure before A3 merges.
- **Part C cost on a Raspberry Pi 3**: one extra view set for each hook
  unit for each frame. Measure with 8 channels.
- `gui.py` is about 5200 lines (R61); new code goes to `gui_charts.py`.
- dearpygui can drop legends when series are added and removed; test the
  tab rebuild.
- Users with 0.x files need 0.1.5 or the converter; the 1.0.0 notes and
  the README say so.
