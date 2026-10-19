# Plot setup — wire channels to charts (phase 1)

Branch: `feat/plot-setup`, from `main` @ `ee72064` (v0.1.4).
Progress tracker: `.claude/plans/2026-10-17-plot-setup-progress.md`.
Requirement: R67 in `doc/PROGRESS.md`. Related open work: R24
(multi-channel plots; the polar chart stays there), R33 (flexible layout),
R42 (crest and kurtosis trend), R43 remainder (RPM on the trend plot).

Revision 2 (2026-10-19): owner decisions Q1, Q2, Q4, Q5 and Q7 applied;
spectrum averaging moves from the Acquisition tab to each spectrum chart.
New open questions: Q3 (carried over), Q8.

## 1. Request

1. Add a **Charts** tab to the configuration dialog. It shows a table with
   one row for each active chart.
2. Below the table: a combo of chart types and a **+** button. The button
   adds a row for the selected type. Phase-1 types: time waveform, trend,
   spectrum, envelope, XY (two channels). Polar is deferred (R24, see 3.6).
3. Columns of each row:
   - **−** button: remove the chart.
   - Chart type (read-only).
   - Chart name (editable). The main-window tab uses this name.
   - Channels: one checkbox for each available channel. This is the main
     feature: it selects which channels a chart shows. XY: two ordered
     selectors (X, Y) and a swap button.
   - Y-axis unit and amplitude mode, for example `in/s 0-P` or `mils P-P`.
     This sets the one y axis of the chart. One channel can show on two
     charts in two units. An XY chart uses the same unit on x and y.
   - Options. Trend: shaft speed from a tachometer channel on a second
     y axis. Spectrum: an **Average** checkbox and an integer **N**.
4. The chart set sets the main-window layout: one tab for each chart, named
   for the chart.
5. Only the chart on screen is processed and drawn, as the Envelope tab does
   now (`_envelope_on_screen()`).
6. Remove the time-waveform plot that shows all channels below the tabs. The
   tab bar fills the full middle pane.
7. Retire from the Acquisition tab: the **Envelope analysis** checkbox (an
   envelope chart replaces it) and the **Average spectrum** checkbox with
   its **Averages** and **Avg. Window** fields (they move to each spectrum
   chart).
8. Out of scope for phase 1: split panes and more than one chart on screen
   (R33); the polar chart (R24).

## 2. Current state (facts that the design depends on)

| Fact | Where |
|---|---|
| Unit and amplitude mode are per channel: `channel_target_units`, `channel_amplitude_modes`. An empty unit means the sensor EU (`get_active_eu`) | `sample.py:61-62`, `collector.py:227` |
| The Channels tab sets them with two combos for each channel | `gui.py` `_rebuild_device_channel_rows`, `_apply_channel_assignments_from_widgets` |
| `process_sample()` reads both, integrates the mV PSD and scales to the target unit. The mV PSD and the five mV overalls (orders −2 to +2) are cached on the sample and do not depend on the unit | `collector.py:843-1050`, `_psd_and_overalls_for` |
| Callers of `process_sample()`: `_process_samples`, the session reprocess path (two calls), `scripts/advanced_plots.py` | `collector.py:1221`, `1918`, `1952` |
| Spectrum averaging: `averaging_enabled`, `n_averages` in `AcquisitionSettings`; a linear power average of the N most recent valid frames up to the displayed frame. It also averages `ChannelResult.overall`, which the anomaly hooks read | `sample.py:78-81`, `collector.py` step 3b |
| `n_averages_effective` clamps N to `cache_frames` | `sample.py:292` |
| The trend stores the five mV overalls for each frame, not averaged. The unit and mode are applied at display time | `update_trend`, `get_trend_for_display()` |
| Crest factor and kurtosis come from `ChannelResult.time_data`, the trace in the target unit. They change with the integration order | `process_sample` step 8 |
| Shaft speed has its own trend and never goes through unit scaling | `get_rpm_trend()`, `tach_trend` |
| `process_samples()` runs once for each displayed frame. It updates the trend and gives the results to `MonitorController.on_results()` and the result cards | `gui.py` `_display_frame_inner` |
| Anomaly hooks read `ChannelResult.overall` and `.unit`. `FixedThresholdHook` converts each limit's unit to the result unit through `UNIT_TO_SI`. It does not compare amplitude modes: a `0-P` limit is compared with a `P-P` reading without correction | `monitor/anomaly.py:347-435` |
| `_build_anomaly_hook` has two copies, GUI and headless (R58) | `gui.py:3292`, `headless.py:117` |
| The main pane is a fixed tab bar (Spectrum, Envelope, Trend) with a time-series plot of all channels below it, height `TIME_PLOT_HEIGHT` = 300 px | `gui.py:4708-4786` |
| Two units at most: a second y axis on each plot, assigned by `_update_axis_assignment()` | `gui.py:454-536` |
| Series tags are global for each channel: `plt_freq_series(ch)`, `plt_time_series(ch)`, `plt_env_series(ch)`, `plt_trend_series(ch)` | `util.UI_Elements` |
| The Envelope tab shows when `envelope_enabled` is true. The chain is skipped when the plot is not on screen (about 2.8 ms for each channel and frame) | CONTRIBUTING.md, "E19. GUI render cost" |
| dearpygui has no polar plot type. No 1x phase measurement exists | `.claude/plans/2026-09-01-tachometer.md`, section 1.3 |

## 3. Design

### 3.1 Chart model — new module `src/rev80/charts.py`

No dearpygui import, so the model is testable on ARM.

```python
CHART_TYPES = ('waveform', 'trend', 'spectrum', 'envelope', 'xy')

@dataclass
class ChartSpec:
    chart_id: str             # stable, e.g. 'c3'; tags derive from it, never from the name
    chart_type: str           # one of CHART_TYPES
    name: str                 # tab label; editable; need not be unique
    channels: list[int]       # display order; xy: [x, y]
    unit: str                 # always explicit: one chart, one y axis
    amplitude_mode: str       # 'RMS' | '0-P' | 'P-P'; ignored by waveform and xy
    show_rpm: bool = False    # trend only: shaft speed on y2
    tach_channel: int | None = None   # trend with show_rpm
    averaging: bool = False   # spectrum only
    n_averages: int = 8       # spectrum only; clamped to cache_frames at use

@dataclass
class ChartSet:
    charts: list[ChartSpec]
    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d) -> 'ChartSet'     # skips a bad entry, logs it
    @classmethod
    def default_for(cls, config, sensors) -> 'ChartSet'   # see 3.9
```

Validation functions (pure, unit-tested):

- `allowed_units(chart_type, sensor_eus)`: the units that every checked
  channel can reach from its sensor EU through `integration_steps()`, within
  ±2 steps. Envelope: acceleration units only (the envelope chain reads
  `eu_scaled_raw()`, sensor EU, no integration), or `mV` with no sensor.
- `channel_selectable(spec, ch, ...)`: False for a channel whose sensor EU
  cannot reach `spec.unit`, and for a channel with no sensor on a chart in an
  engineering unit (only `mV` is honest there). The dialog shows the reason
  in a tooltip.
- Tachometer channels: selectable only as `tach_channel` on a trend chart.
  Never in `channels`. A pulse train in the vibration path gives overall
  1515 mV, crest 5.00 and kurtosis 15.94.
- XY: exactly two different channels.
- A chart with no selectable channel stays in the set and shows "no
  channel" on its tab. A disconnected device must not erase the layout.

### 3.2 `result_view()`: the one path to a channel result in a unit

Owner decision: channels keep their target unit, which defaults to the
sensor EU. `collector.result_view()` becomes the main path for a channel
signal in a target unit and mode. Every consumer goes through it: the
record path, each chart, the alarm view and the session reprocess.

```python
def result_view(self, ch, sample, unit=None, amplitude_mode=None,
                n_averages=1, history=None) -> ChannelResult | None
```

- `unit=None` gives the channel's target unit, then the sensor EU
  (`get_active_eu`). `amplitude_mode=None` gives the channel's mode, then
  `0-P`.
- Stage 1, cached on the sample, unit-independent (no change): high-pass,
  decimation to the display rate, mV PSD, five mV overalls.
- Stage 2, the view: power average of the N most recent valid frames
  (`n_averages > 1`, same rule as now, so replay shows what live showed);
  integration factor; sensitivity; SI factor; amplitude scale; F_max
  truncation; peak selection; overlap-save time trace; crest factor and
  kurtosis of that trace.
- `process_sample()` is removed. Its callers call `result_view()`,
  `scripts/advanced_plots.py` included.
- `process_samples(unit=None, amplitude_mode=None)` returns one result for
  each vibration channel through `result_view()`, never averaged (Q8). It
  updates the trend as now; the trend stores mV orders, so it is unit-
  independent.
- `get_trend_for_display(unit=None, amplitude_mode=None, channels=None)`:
  the same conversion, with the unit and mode given by the chart.
- View cache for the displayed frame, keyed
  `(frame index, ch, unit, mode, n_averages, config key)`, render thread
  only. A tab change while stopped does not recompute.

Tests:

- **Equality test** (structure change on a measurement path): for each
  shipped unit pair and mode, `result_view()` with the channel's unit gives
  arrays equal to the current `process_sample()`. Capture the reference
  output before the refactor.
- **Conversion test** in `tests/test_measurement_validity.py`: an off-bin
  tone with a non-zero phase, one channel, two views (in/s and g). The
  overall and the line amplitude agree through `v = a / (2 π f)`, and the
  `P-P`/`0-P`/`RMS` views agree through `amplitude_scale()`. Revert check:
  break the view's integration factor; the test must fail.
- `tests/test_spectral_averaging.py` (26 references to the config fields)
  moves to the `n_averages` argument. The averaging rule does not change.

### 3.3 Record unit, alarm unit, crest factor and kurtosis

- **Record unit** = the channel's target unit (Channels tab, as now; empty
  means the sensor EU). It sets: the result card, the monitor capture, the
  measurement file attributes, the headless results. No change to files,
  sessions or headless input.
- **Alarm unit** (owner decision Q1): the Monitor tab anomaly section gets a
  unit and mode selector. The front end calls
  `process_samples(unit=alarm_unit, amplitude_mode=alarm_mode)` and gives
  those results to the anomaly hooks. Stage 1 is cached, so the extra cost
  is stage 2 only. Measure it (3.4).
  - Config keys `alarm_unit` and `alarm_amplitude_mode` in the
    `monitor.anomaly` block of `acquisition.yaml`. Headless reads the same
    keys. Empty means each channel's record unit (today's behaviour).
  - A channel that cannot reach the alarm unit (no sensor, other quantity)
    is skipped by the hooks with one warning, as `FixedThresholdHook` does
    now for a unit it cannot convert.
  - `FixedThresholdHook`: the limits are in the alarm unit and mode. The
    per-limit unit fields go. Migration: when `alarm_unit` is absent and
    `fixed_upper_unit` is set, use it as the alarm unit. This also removes
    the amplitude-mode mismatch in the table above.
  - `RmsThresholdHook` is a % deviation, but the unit still matters: a
    velocity overall weights low frequencies more than an acceleration
    overall. The alarm unit sets which.
  - The speed gate does not change: `rpm` and `speed_ok` are on every
    result, and `valid_results()` stays the one place that applies it.
  - Both copies of `_build_anomaly_hook` change in the same commit;
    `tests/test_anomaly_hook_build.py` checks that their defaults agree.
  - Where the alarm view is built: one shared helper,
    `monitor.anomaly.alarm_view(anom_cfg)` → `(unit, mode)`, called by both
    front ends. No copy in a front end.
- **Crest factor and kurtosis** (owner decision Q2): from the record-unit
  trace. The result card labels them with the unit, for example
  `Crest 3.10 (in/s)`. A waveform chart in another unit does not change
  them. The trend stores the record-unit values, as now.

### 3.4 Processing: the always-run part and the on-screen part

Each new frame, whatever the selected tab:

1. `process_samples()` in the record unit: trend update, tachometer trend,
   speed gate, overflow flags, result cards, monitor capture.
2. When recording with an alarm unit different from a channel's record
   unit: `process_samples(alarm unit)` for the hooks.

Steps 1 and 2 must not depend on the selected tab, or a recording made with
the Spectrum tab selected differs from one made with the Trend tab
selected.

Then, only for the chart on screen:

3. `_render_chart(spec)`: one `result_view()` for each checked channel in
   the chart unit (cache hit when it equals step 1), then `set_value` on
   that chart's series.

On-screen test: `dpg.is_item_visible(plot_tag)`, failing open, as
`_envelope_on_screen()` does now. Generalise it to `_chart_on_screen(cid)`.

A tab change (tab-bar callback) renders the new chart at once from the
current frame. Without it, the tab stays blank for up to one acquisition
period (4 s at 0.25 Hz/bin).

Cost: measure before and after with `scripts/profile-pipeline`
(hardware-realistic `--raw-rate`) and the `_profile` counters, 1 to 8
channels: today's 3 tabs against 6 charts with 1 on screen, recording with
and without a separate alarm unit. Record the table in CONTRIBUTING.md,
"E19. GUI render cost".

### 3.5 Chart types

| Type | Data | X axis | Y axis | Notes |
|---|---|---|---|---|
| Time waveform | `result_view(...).time_data`, display rate | Time, ms | chart unit (a trace has no amplitude mode; the label gives the unit only) | Replaces the bottom plot. Integrated traces start after t = 0 (overlap-save); keep `_last_time_x0_ms` for each chart |
| Spectrum | `result_view(..., n_averages)`: spectrum, peaks, 1x marker | Frequency, Hz | `unit mode` | Average checkbox and N for each chart. Info line "averaging k of N frames" for each chart. Avg. window (N × acquisition period) shown in the Charts table row |
| Trend | `get_trend_for_display(unit, mode, channels)` | Time, s | `Overall, unit mode, band` | y2: shaft speed from `get_rpm_trend()` in the user's rotation unit (`rotation_from_rpm`); usable readings only. Browse cursor for each trend chart. Never averaged |
| Envelope | `eu_scaled_raw()`, `envelope_spectrum()` | Modulation frequency, Hz | acceleration unit | Band controls and the Auto button move into the chart tab. Auto-band cache key becomes `(chart_id, ch, rate)` |
| XY | two traces of the same frame, chart unit | channel X | channel Y | Same frame, same clock, same anti-alias and high-pass, so the phase between the two is kept. Equal axis scale. Trim both traces to the same span |

### 3.6 Polar chart — deferred to R24

Owner decision Q4. Not in the phase-1 type combo. It needs a new
measurement: the phase of the 1x component relative to a once-per-revolution
tachometer edge, with the anti-alias FIR and high-pass group delay at 1x
corrected, verified by AWG loopback over 300 to 10200 RPM, and reviewed by
the vibration-engineer agent. dearpygui has no polar axes, so the plot is
drawn on an equal-aspect plot. R24 in `doc/PROGRESS.md` holds this.

### 3.7 Configuration dialog

**Charts tab** (`CONFIG_TAB_CHARTS`, after Channels and Tachometer):

- `dpg.table`, columns: `−`, Type, Name, Channels, Unit, Options.
  - Channels: a horizontal group of checkboxes, one for each enabled
    vibration channel, labelled with `name_for(ch)` in the channel colour.
    A channel that the chart unit cannot use is disabled, with the reason in
    a tooltip.
  - XY (owner decision Q5): two combos, X and Y, and a swap button (⇄)
    between them.
  - Unit: one combo of `unit mode` items from `allowed_units()`. Waveform
    and XY show the unit only.
  - Options: trend — "Shaft speed on y2" checkbox and a tachometer combo,
    shown only when a tachometer channel exists. Spectrum — "Average"
    checkbox, N input (1 to `cache_frames`), and the averaging window in
    seconds, read-only.
- Below the table: type combo and `+` button.
- Edits go to a working copy of the `ChartSet`. Close applies it: save
  `charts.yaml`, rebuild the main tab bar, render the selected chart.
- Rebuild the table when a channel is enabled or disabled, a sensor is
  assigned, or the tachometer role changes.
- Recording lock: the existing lock on the dialog buttons stays (Q6, not
  answered; default kept).

**Acquisition tab:** remove `ACQ_DLG_ENV_ENABLED`, `ACQ_DLG_AVG_ENABLED`,
`ACQ_DLG_AVG_N`, `ACQ_DLG_AVG_TIME` and their callbacks and tooltips.

**Channels tab:** no change. The target unit and amplitude mode combos
stay; they set the record unit.

**Monitor tab:** add the alarm unit and mode combos to the anomaly section.
Remove the unit combos beside the fixed upper and lower limits.

### 3.8 Main window

- Delete the bottom `PLT_SAMPLE` plot and `TIME_PLOT_HEIGHT`. The tab bar
  fills the middle pane.
- Delete the second-y-axis logic (`_update_axis_assignment`,
  `_reassign_series_to_axis`, `PLT_FREQ_AX_2`, `PLT_SAMPLE_AX_ACCEL_2`,
  `PLT_TREND_AX_OVERALL_2`). Each chart has one unit and one y axis. The
  trend's y2 is shaft speed.
- Tags from `chart_id`, never from the editable name:
  `ui.chart_tab(cid)`, `ui.chart_plot(cid)`, `ui.chart_axis(cid, 'x'|'y'|'y2')`,
  `ui.chart_series(cid, ch)`, `ui.chart_peaks(cid, ch)`, `ui.chart_one_x(cid, ch)`.
- `_build_chart_tabs()` deletes and rebuilds the tab-bar children from the
  `ChartSet`. It keeps the selected tab when its `chart_id` still exists,
  else it selects the first tab.
- Update every consumer of the old global tags: `_ensure_legends`,
  `_autoscale_plots`, `_unlock_autoscaled_axes`, `_update_trend_cursor`,
  `_add_channel_series` / `_remove_channel_series`, `_redraw_all_channels`,
  `_refresh_channel_names`, `_update_avg_count_text`, the keyboard
  handlers, the session-browser display path.
- Put the chart builders and renderers in a new module `gui_charts.py`, so
  `gui.py` (R61) gets shorter.

### 3.9 Persistence and migration

- `charts.yaml` in the config directory, through a new
  `config.charts_config_path()` (uses `config_dir()`). Not in
  `acquisition.yaml` and not in the device YAML. Headless does not read it.
- A chart refers to a channel by index. A device with fewer channels gives
  charts with the missing channels unchecked, not an error.
- An unreadable or invalid `charts.yaml`: log it, use the default set, and
  do not overwrite the file.
- Default set when no file exists, equal to today's layout: Spectrum, Trend
  (shaft speed on y2 when a tachometer exists) and Time waveform, all
  vibration channels, unit and mode of the first enabled channel's record
  unit. Channels that cannot use that unit go on a second chart of the same
  type.
- One-time migration from `acquisition.yaml`: `envelope_enabled: true` adds
  an Envelope chart; `averaging_enabled` and `n_averages` set the averaging
  of the default Spectrum chart.
- `AcquisitionSettings`: remove `envelope_enabled`, `averaging_enabled`,
  `n_averages` and `n_averages_effective`. `from_dict` ignores the keys in
  old files and YAML; `to_dict` stops writing them. The measurement-file
  version does not change (a reader already tolerates an absent key).
  Update `tests/test_config.py` and `tests/test_config_contract.py`.
- Measurement files and monitor sessions keep the record unit for each
  channel. The chart set is not stored in a file in phase 1.

### 3.10 Headless

Reads `alarm_unit` and `alarm_amplitude_mode` and builds the alarm view
with the shared helper. No charts. Its results are no longer averaged
(Q8). Everything else is unchanged.

## 4. Invariants to keep (checklist for each step)

- [ ] Tachometer channels: no `ChannelResult`, no unit scaling, never in
      `ChartSpec.channels`.
- [ ] `rpm` stays `None` with no reading; only usable readings on the trend
      y2.
- [ ] Overflow and degraded frames: shown and flagged on every chart type,
      not trended, not averaged.
- [ ] Replay shows what the live display showed: browse renders the same
      `result_view()` with the same averaging rule.
- [ ] Power-domain averaging only. The view never averages magnitudes.
- [ ] Crest factor and kurtosis: from the record-unit trace, never averaged.
- [ ] Monitor results, alarms and trends do not depend on the selected tab.
- [ ] The speed gate is applied in `valid_results()` only.
- [ ] Achieved rate, not `config.samplerate`, in every view.
- [ ] No dearpygui import in `charts.py`, `collector.py`, `sample.py`,
      `monitor/`.
- [ ] Source-inspection rules for `gui.py` and `headless.py` text.
- [ ] No viewport in tests. GUI tests make a context only.
- [ ] `max_burst_s` and `compression_level` keep their saved values.

## 5. Work breakdown

Each step: tests first where the step changes behaviour, a revert check for
each fix, `ruff check src/ tests/`, the full suite without the hardware
file. One commit for each step. CHANGELOG, PROGRESS and README in the same
commit as the code.

| Step | Content | Tests |
|---|---|---|
| S0 | Branch, plan, tracker, R67 | — |
| S1 | `charts.py`: model, validation, `default_for`, YAML load/save, `charts_config_path()` | `tests/test_charts.py`: round trip; bad entry skipped; bad file not overwritten; allowed units; tachometer refused; XY needs two; default set equals today's layout |
| S2 | `result_view()`; `process_sample()` removed; `process_samples(unit, mode)` unaveraged; unit-parameterised `get_trend_for_display()`; view cache | equality test (reference captured before the change); conversion test (off-bin, phase ≠ 0); revert check; `test_spectral_averaging.py` moved to the argument |
| S3 | Alarm view: Monitor-tab unit and mode, `alarm_view()` helper, both `_build_anomaly_hook` copies, headless, fixed-limit migration | hook fires on the alarm-unit overall; channel that cannot convert is skipped; migration from `fixed_upper_unit`; GUI and headless defaults agree |
| S4 | Main window: dynamic tab bar; bottom plot and second-y-axis code removed; waveform, spectrum (with per-chart averaging) and trend renderers; on-screen-only rendering; render on tab change | GUI-context tests: tabs from a set; rebuild keeps the selection; hidden chart not rendered (patch `is_item_visible`); tags by `chart_id` |
| S5 | Charts tab in the dialog: add, remove, rename, checkboxes, XY selectors with swap, unit combo, options | GUI-context tests: add and remove rows; incompatible channel disabled; swap; close saves and rebuilds |
| S6 | Acquisition tab: Envelope and averaging controls removed; settings fields removed; migration | old YAML and old files load; migration adds the envelope chart and the averaging |
| S7 | Envelope chart: band controls for each chart | `test_envelope.py` passes; chain runs only on screen |
| S8 | Trend y2: shaft speed | usable readings only; no point for `None`; no unit scaling |
| S9 | XY chart | two traces, same span and length; same unit |
| S10 | Profiling table (E19), README, CONTRIBUTING (4.1, 4.3, 4.6, 4.8, E19), CLAUDE.md, CHANGELOG | technical-writer audit; vibration-engineer review of S2, S3, S4, S8 |

## 6. Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Unit for alarms | ✅ A unit and mode selector on the Monitor tab, passed to `result_view()` for the anomaly test. Channels keep their target unit (default: sensor EU) as the record unit |
| Q2 | Crest factor and kurtosis from the record-unit trace | ✅ Yes |
| Q3 | Peaks table in the results column: record unit, or follow the selected spectrum chart? | Open. Recommended: follow the spectrum chart on screen (its unit, mode and averaging); with no spectrum chart on screen, the record unit. The column header gives the unit |
| Q4 | Polar in phase 1 | ✅ Deferred to R24 |
| Q5 | XY selection | ✅ Two ordered selectors and a swap button |
| Q6 | Chart edits during a recording | Not answered. Default: the existing dialog lock stays |
| Q7 | Envelope checkbox | ✅ Retired; an envelope chart replaces it |
| Q8 | With averaging moved to the charts, the record and alarm results are never averaged. Today, with averaging on, the hooks see an averaged overall | Open. Recommended: unaveraged. The trend is already unaveraged; the RMS hook smooths with its own EWMA and needs `consecutive_n` frames to fire |

## 7. Risks

- `gui.py` is about 5200 lines (R61). This work touches most plot code;
  `gui_charts.py` takes the new code.
- dearpygui can drop legends when series are added and removed. Rebuilding
  whole tabs makes this more likely; test it.
- Deleting the selected tab can leave the tab bar with no selection.
- A second `process_samples()` call for the alarm unit costs stage 2 for
  each channel during a recording. Measure it before S3 merges.
- `DataCollector` has no lock (R59). The view cache is used on the render
  thread only. The session reprocess thread (R50) must not touch it.
