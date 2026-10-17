# Plot setup — wire channels to charts (phase 1)

Branch: `feat/plot-setup`, from `main` @ `ee72064` (v0.1.4).
Progress tracker: `.claude/plans/2026-10-17-plot-setup-progress.md`.
Requirement: R67 in `doc/PROGRESS.md`. Related open work: R24
(multi-channel plots: orbit, polar), R33 (flexible layout), R42 (crest and
kurtosis trend), R43 remainder (RPM on the trend plot).

## 1. Request

1. Add a **Charts** tab to the configuration dialog. It shows a table with
   one row for each active chart.
2. Below the table: a combo of chart types and a **+** button. The button
   adds a row for the selected type. Types:
   time waveform, trend, spectrum, envelope, polar (with tachometer),
   XY (two channels).
3. Columns of each row:
   - **−** button: remove the chart.
   - Chart type (read-only).
   - Chart name (editable). The main-window tab uses this name.
   - Channels: one checkbox for each available channel. This is the main
     feature: it selects which channels a chart shows.
   - Y-axis unit and amplitude mode, for example `in/s 0-P` or `mils P-P`.
     This sets the one y axis of the chart. **Unit and amplitude mode become
     a chart property, not a channel property.** One channel can show on two
     charts in two units. An XY chart uses the same unit on x and y.
   - Trend charts only: shaft speed from a tachometer channel on a second
     y axis, beside the overalls.
4. The chart set sets the main-window layout: one tab for each chart, named
   for the chart.
5. Only the chart on screen is processed and drawn, as the Envelope tab does
   now (`_envelope_on_screen()`).
6. Remove the time-waveform plot that shows all channels below the tabs. The
   tab bar fills the full middle pane.
7. Out of scope for phase 1: split panes and more than one chart on screen
   (R33).

## 2. Current state (facts that the design depends on)

| Fact | Where |
|---|---|
| Unit and amplitude mode are per channel: `channel_target_units`, `channel_amplitude_modes` | `sample.py:61-62`, `target_unit_for()`, `amplitude_mode_for()` |
| The Channels tab sets them with two combos for each channel | `gui.py` `_rebuild_device_channel_rows`, `_apply_channel_assignments_from_widgets` (`scope_ch_target_unit`, `scope_ch_amplitude_mode`) |
| `process_sample()` reads both, integrates the mV PSD and scales to the target unit. The mV PSD and the five mV overalls (orders −2 to +2) are cached on the sample and do not depend on the unit | `collector.py:843-1000`, `_psd_and_overalls_for` |
| The trend stores the five mV overalls for each frame. The unit and mode are applied at display time | `collector.py` `update_trend`, `get_trend_for_display()` |
| Crest factor and kurtosis come from `ChannelResult.time_data`, the trace in the target unit. They change with the integration order | `process_sample`, `ChannelResult` |
| Shaft speed has its own trend and never goes through unit scaling | `get_rpm_trend()`, `tach_trend` |
| `process_samples()` runs once for each displayed frame. It updates the trend and gives the results to `MonitorController.on_results()` and the result cards | `gui.py` `_display_frame_inner` |
| The main pane is a fixed tab bar (Spectrum, Envelope, Trend) with a time-series plot of all channels below it, height `TIME_PLOT_HEIGHT` = 300 px | `gui.py:4708-4786` |
| Two units at most: a second y axis on each plot, assigned by `_update_axis_assignment()` | `gui.py:454-536` |
| Series tags are global for each channel: `plt_freq_series(ch)`, `plt_time_series(ch)`, `plt_env_series(ch)`, `plt_trend_series(ch)` | `util.UI_Elements` |
| The Envelope tab shows when `envelope_enabled` is true. The chain is skipped when the plot is not on screen (about 2.8 ms for each channel and frame) | CONTRIBUTING.md, "E19. GUI render cost" |
| The monitor snapshot, the measurement file and the device YAML store `target_unit` and `amplitude_mode` for each channel | `monitor/session.py:47-48`, `collector.py:1305`, `gui.py:3565` |
| Headless reads `target_unit` and `amplitude_mode` from the device YAML | `headless.py:253-256` |
| dearpygui has no polar plot type | — |
| No 1x phase measurement exists. The tachometer plan put a balancing phase reference out of scope | `.claude/plans/2026-09-01-tachometer.md`, section 1.3 |

## 3. Design

### 3.1 Chart model — new module `src/rev80/charts.py`

No dearpygui import, so the model is testable on ARM and in headless.

```python
CHART_TYPES = ('waveform', 'trend', 'spectrum', 'envelope', 'polar', 'xy')

@dataclass
class ChartSpec:
    chart_id: str             # stable, e.g. 'c3'; tags derive from it, never from the name
    chart_type: str           # one of CHART_TYPES
    name: str                 # tab label; editable; need not be unique
    channels: list[int]       # in user order; xy: [x, y]
    unit: str                 # '' = each channel's sensor EU (see 3.3)
    amplitude_mode: str       # 'RMS' | '0-P' | 'P-P'
    show_rpm: bool = False    # trend only: shaft speed on y2
    tach_channel: int | None = None   # trend (show_rpm) and polar

@dataclass
class ChartSet:
    charts: list[ChartSpec]
    def to_dict(self) -> dict
    @classmethod
    def from_dict(cls, d) -> 'ChartSet'     # skips a bad entry, logs it
    @classmethod
    def default_for(cls, config) -> 'ChartSet'   # see 3.8
```

Validation functions (pure, unit-tested):

- `allowed_units(chart_type, sensor_eus)`: the units a chart can use.
  Spectrum, waveform, trend, XY, polar: every unit that `integration_steps()`
  reaches from each checked channel's sensor EU within ±2 steps. Envelope:
  acceleration units only (the envelope chain reads `eu_scaled_raw()`, sensor
  EU, no integration), or `mV` with no sensor.
- `channel_selectable(spec, ch, config, sensors)`: False for a channel whose
  sensor EU cannot reach `spec.unit`, and for a channel with no sensor on a
  chart in an engineering unit (only `mV` is honest there).
- Tachometer channels: selectable only as `tach_channel` on a trend or polar
  chart. Never in `channels`. A pulse train in the vibration path gives
  overall 1515 mV, crest 5.00 and kurtosis 15.94.
- XY: exactly two channels. Polar: at least one vibration channel and a
  usable tachometer channel.
- A chart with no selectable channel stays in the set and shows "no channel"
  on its tab. It is not deleted: a disconnected device must not erase the
  user's layout.

### 3.2 One unit for each chart: a view on the cached mV results

The expensive, unit-independent work is already cached on the sample: the
high-pass, the decimation, the mV PSD and the five mV overalls. The unit
step (integration factor, sensitivity, SI factor, amplitude scale, F_max
truncation, peak selection, time trace) is cheap and unit-dependent.

Change in `collector.py`:

- Split `process_sample()` into the cached stage (unchanged) and
  `result_view(ch, sample, unit, amplitude_mode, history)`, which returns a
  `ChannelResult` in that unit. `process_sample(ch, sample, history)` calls
  `result_view` with the channel's record unit (3.3). Behaviour of every
  existing caller does not change.
- `get_trend_for_display(unit=None, amplitude_mode=None, channels=None)`:
  the same conversion, with the unit and mode given by the chart.
- Cache the view results for the displayed frame, keyed
  `(frame index, ch, unit, amplitude_mode, averaging key)`, so that a tab
  change while stopped does not recompute.
- **Equality test** (speed and structure change on a measurement path):
  `result_view` with the channel's record unit gives a `ChannelResult` equal,
  array by array, to today's `process_sample`.
- **Conversion test** in `tests/test_measurement_validity.py`: an off-bin
  tone with a non-zero phase, one channel, two views (in/s and g). The
  overalls and the line amplitude agree through `v = a / (2 π f)` within the
  existing tolerance for that test file. Revert check: break the view's
  integration factor and see the test fail.

### 3.3 What stays per channel: the record unit

Monitor Mode, headless, the anomaly hooks, the measurement file and the
result card need one unit for each channel. A chart cannot supply it: a
channel can be on no chart or on three. Options:

| Option | For | Against |
|---|---|---|
| **A. Keep `channel_target_units` / `channel_amplitude_modes` as the record unit.** Move the two combos from the Channels tab to the Monitor tab ("Record and alarm unit"). Headless and the device YAML do not change | No change to files, sessions, hooks or headless. Thresholds keep their unit | Two places show units: charts (display) and Monitor (record) |
| B. Record unit = sensor EU, fixed | Simplest | `FixedThresholdHook` thresholds in a set unit change meaning; the result card shows g for a velocity job |
| C. Record unit = unit of the first trend chart that has the channel | No extra control | Hidden coupling: reordering tabs changes what is alarmed and stored |

**Recommendation: A.** The record unit is a measurement-chain setting; the
chart unit is a view. The result card and the peaks table show the record
unit, labelled. This is decision **Q1** for the owner.

Crest factor and kurtosis: today they come from the trace in the channel's
target unit. Under A they come from the record-unit trace, and the result
card says which (for example `Crest 3.1 (in/s)`). A waveform chart in
another unit does not change them. The rule "from the displayed trace" in
CLAUDE.md becomes "from the record-unit trace". Vibration-engineer review
needed (**Q2**).

### 3.4 Processing: the always-run part and the on-screen part

Each new frame, whatever the selected tab:

1. `process_samples()` in the record unit, as now: trend update, tachometer
   trend, speed gate, overflow flags, result cards, `MonitorController`.
   This must not depend on which tab is selected, or a recording made with
   the Spectrum tab selected differs from one made with the Trend tab
   selected.

Then, only for the chart on screen:

2. `_render_chart(spec, frame)`: one `result_view` for each checked channel
   in the chart unit (cache hit when the unit is the record unit), then
   `set_value` on that chart's series.

On-screen test: `dpg.is_item_visible(plot_tag)`, which fails open, as
`_envelope_on_screen()` does now. Generalise it to `_chart_on_screen(cid)`.

A tab change (tab-bar callback) renders the newly selected chart at once
from the current frame. Without it, the tab stays blank for up to one
acquisition period (4 s at 0.25 Hz/bin).

Cost to measure before and after with `scripts/profile-pipeline`
(hardware-realistic `--raw-rate`) and `_profile` counters, 1 to 8 channels:
the per-frame GUI time with 6 charts defined and 1 on screen must not exceed
today's time with 3 tabs. Record the table in CONTRIBUTING.md, "E19. GUI
render cost".

### 3.5 Chart types

| Type | Data | X axis | Y axis | Notes |
|---|---|---|---|---|
| Time waveform | `result_view(...).time_data`, display rate | Time, ms | chart unit (amplitude mode not applied to a trace; label says unit only) | Replaces the bottom plot. The overlap-save trace starts after t = 0 for integrated units; keep `_last_time_x0_ms` per chart |
| Spectrum | `result_view(...).spectrum`, peaks, 1x marker | Frequency, Hz | `unit mode` | Peak markers per chart. The peaks table in the results column stays in the record unit (Q3) |
| Trend | `get_trend_for_display(unit, mode, channels)` | Time, s | `Overall, unit mode, band` | y2: shaft speed from `get_rpm_trend()`, in the user's rotation unit (`rotation_from_rpm`). Usable readings only (already true of `tach_trend`). Browse cursor per trend chart |
| Envelope | `eu_scaled_raw()`, `envelope_spectrum()` | Modulation frequency, Hz | acceleration unit | Band controls and auto band move into the chart tab. Auto-band cache key becomes `(chart_id, ch, rate)` |
| XY | two traces of the same frame, chart unit | channel X | channel Y | Same samples, same clock; both channels go through the same anti-alias and high-pass, so the phase between them is preserved. Equal axis scale (`equal_aspects=True`). Integrated traces are trimmed (overlap-save), so trim both to the same span |
| Polar | 1x amplitude and phase for each channel, referenced to the tachometer | — | amplitude, chart unit | **Needs a new measurement**: the phase of the 1x component relative to a tachometer edge. See 3.6 |

### 3.6 Polar chart: a new measurement, scheduled last

There is no 1x phase today. The polar chart needs, for each frame and
channel: the 1x amplitude (exists: `one_x_amplitude`) and the 1x phase
relative to the once-per-revolution tachometer edge (new).

- Method to evaluate: a single-bin DFT at the measured shaft rate over whole
  revolutions between tachometer edges (`TachResult` edge times), phase
  referenced to the first edge. Correct for the anti-alias FIR and high-pass
  group delay at 1x, or the phase is wrong by a frequency-dependent angle.
- Accuracy target and evidence: AWG loopback (tone on channel B, a pulse
  locked to it on channel A), phase error over 300 to 10200 RPM, in
  CONTRIBUTING.md section 5 as a new "E" entry.
- `pulses_per_rev` > 1 gives no unique phase reference; refuse the chart
  unless ppr = 1 (or a once-per-rev marker exists).
- Plot: dearpygui has no polar axes. Draw on an equal-aspect plot: range
  rings and 30° spokes as line series, the vector as a line from the origin,
  a short trail of recent frames as a scatter.
- vibration-engineer review is mandatory before merge.

If this does not fit in phase 1, the Polar type stays in the combo but is
disabled with the tooltip "Needs 1x phase measurement (R24)". This is
decision **Q4**.

### 3.7 Configuration dialog: Charts tab

- New tab `CONFIG_TAB_CHARTS`, after Channels and Tachometer, because it
  depends on both.
- `dpg.table` with columns: `−`, Type, Name, Channels, Unit, Options.
  - Channels: a horizontal group of checkboxes, one for each enabled
    vibration channel, labelled with `name_for(ch)` and the channel colour.
    A channel that the chart unit cannot use is disabled, with a tooltip
    that gives the reason. XY: two combos (X, Y) in place of checkboxes,
    because the order matters (**Q5**).
  - Unit: one combo of `unit mode` items, from `allowed_units()`. Waveform
    shows the unit only.
  - Options: trend — "Shaft speed on y2" checkbox and a tachometer combo
    (shown only when a tachometer channel exists); polar — tachometer combo.
- Below the table: type combo, `+` button.
- Edits go to a working copy of the `ChartSet`. Close applies it: save
  `charts.yaml`, rebuild the main tab bar, render the selected chart.
- Rebuild the table when channels are enabled or disabled, a sensor is
  assigned, or the tachometer role changes, because these change what is
  selectable.
- Recording lock: the dialog buttons are locked during a recording. Charts
  are display only, so they could stay editable then. Phase 1 keeps the
  existing lock (**Q6**).

### 3.8 Main window

- Delete the bottom `PLT_SAMPLE` plot and `TIME_PLOT_HEIGHT`. The tab bar
  fills the middle pane (`height=-1` on each plot).
- Delete the second-y-axis logic for spectrum and waveform
  (`_update_axis_assignment`, `_reassign_series_to_axis`,
  `PLT_FREQ_AX_2`, `PLT_SAMPLE_AX_ACCEL_2`, `PLT_TREND_AX_OVERALL_2`). Each
  chart has one unit, so one y axis. The trend's y2 is now shaft speed.
- Tags: `ui.chart_tab(cid)`, `ui.chart_plot(cid)`, `ui.chart_axis(cid, 'x'|'y'|'y2')`,
  `ui.chart_series(cid, ch)`, `ui.chart_peaks(cid, ch)`, `ui.chart_one_x(cid, ch)`.
  Built from `chart_id`, never from the editable name.
- `_build_chart_tabs()` deletes and rebuilds the tab-bar children from the
  `ChartSet`. It keeps the selected tab when its `chart_id` still exists.
- Update every consumer of the old global tags: `_ensure_legends`,
  `_autoscale_plots`, `_unlock_autoscaled_axes`, `_update_trend_cursor`,
  `_add_channel_series` / `_remove_channel_series`, `_redraw_all_channels`,
  `_refresh_channel_names`, the keyboard handlers, the session-browser
  display path.
- The Envelope enable checkbox (`ACQ_DLG_ENV_ENABLED`) is replaced by the
  presence of an envelope chart. `envelope_enabled` stays readable in
  `acquisition.yaml` and files for one release; on first start it adds an
  envelope chart to the default set (**Q7**).

### 3.9 Persistence

- `charts.yaml` in the config directory, through a new
  `config.charts_config_path()` (uses `config_dir()`, so `_paths.py` rules
  hold). Not in `acquisition.yaml`, which holds acquisition and monitor
  settings, and not in the device YAML, which holds `channels` and `siggen`.
  Headless does not read it.
- A chart refers to a channel by index. A different device with fewer
  channels gives charts with unchecked missing channels, not an error.
- Unreadable or invalid `charts.yaml`: log, use the default set, and **do not
  overwrite the file** (the same rule as the sensor library).
- Default set when no file exists, equal to today's layout:
  Spectrum (all vibration channels), Trend (all vibration channels, shaft
  speed on y2 if a tachometer exists), Time waveform (all vibration
  channels), plus Envelope if `envelope_enabled`. Unit: the first enabled
  channel's record unit; channels that cannot use it go on a second chart of
  the same type.
- Measurement files and monitor sessions: no change in phase 1. They keep the
  record unit for each channel (option A). The file version does not change.
  Storing the chart set in a file is a later decision.
- `AcquisitionSettings.copy()`: no new per-channel dict is added. If one is
  added, it goes in the tuple in `copy()`.

### 3.10 Headless

No change. Headless has no charts. Its unit settings are the record unit.

## 4. Invariants to keep (checklist for each step)

- [ ] Tachometer channels: no `ChannelResult`, no unit scaling, never in
      `ChartSpec.channels`.
- [ ] `rpm` stays `None` with no reading; only usable readings on the trend
      y2.
- [ ] Overflow and degraded frames: shown and flagged on every chart type,
      not trended, not averaged.
- [ ] Replay shows what the live display showed: browse renders the same
      view through the same `result_view`, same averaging rule.
- [ ] Power-domain averaging stays in the cached stage; the view does not
      average magnitudes.
- [ ] Monitor results and trends do not depend on the selected tab.
- [ ] Achieved rate, not `config.samplerate`, in every view.
- [ ] No dearpygui import in `charts.py`, `collector.py`, `sample.py`,
      `monitor/`.
- [ ] Source-inspection rules for `gui.py` comments (no `MonitorSession(`,
      `max_burst_s=600.0`, `info.get('role')` in text).
- [ ] No viewport in tests. GUI tests make a context only.
- [ ] `max_burst_s` and `compression_level` keep their saved values.

## 5. Work breakdown

Each step: tests first where the step changes behaviour, a revert check for
each fix, `ruff check src/ tests/`, the full suite without the hardware
file. One commit for each step. Docs in the same commit as the code.

| Step | Content | Tests |
|---|---|---|
| S0 | Branch, this plan, progress tracker, R67 in PROGRESS | — |
| S1 | `charts.py`: `ChartSpec`, `ChartSet`, validation, `default_for`, YAML load/save, `charts_config_path()` | `tests/test_charts.py`: round trip, bad entry skipped, bad file not overwritten, allowed units, tachometer refused, default set equals today's layout |
| S2 | `collector.result_view()`, unit-parameterised `get_trend_for_display()`, view cache | equality test (record unit, bit-identical); conversion test in `test_measurement_validity.py` (off-bin, phase ≠ 0); revert check |
| S3 | Main window: dynamic tab bar from the `ChartSet`; remove the bottom time-series plot and the second-y-axis code; Spectrum, Time waveform and Trend chart renderers; on-screen-only rendering; render on tab change | GUI-context tests: tabs built from a set, rebuild keeps the selection, hidden chart not rendered (patch `is_item_visible`), tag scheme by `chart_id` |
| S4 | Charts tab in the dialog: table, add, remove, rename, checkboxes, unit combo; apply on close | GUI-context tests: add/remove rows, incompatible channel disabled, close saves and rebuilds |
| S5 | Envelope chart: band controls per chart, auto-band cache per chart; retire `ACQ_DLG_ENV_ENABLED` | existing `test_envelope.py` passes; envelope computed only when on screen |
| S6 | Trend y2: shaft speed in the rotation unit | usable readings only; `None` gives no point; no unit scaling |
| S7 | Channels tab: remove the unit and mode combos; record unit on the Monitor tab (option A, after Q1) | `test_gui_save_config.py`, `test_gui_monitor_config.py` updated; device YAML round trip unchanged |
| S8 | XY chart | two traces same span and length; same unit enforced |
| S9 | Polar chart: 1x phase measurement and evidence, plot (after Q4) | AWG loopback on hardware; off-bin simulation test with known phase; vibration-engineer review |
| S10 | Profiling table (E19), README (Charts tab, chart types, record unit), CONTRIBUTING (architecture 4.1, 4.3, E19), CLAUDE.md rules, CHANGELOG | technical-writer audit; vibration-engineer review of S2, S3, S6, S9 |

S3 and S4 can swap order. S3 first lets the default set run the app before
the editor exists.

## 6. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| Q1 | Which unit do Monitor, headless, files, alarms and the result card use? | Option A: keep a per-channel record unit, set on the Monitor tab |
| Q2 | Crest factor and kurtosis: from the record-unit trace? | Yes, labelled with the unit on the result card |
| Q3 | Peaks table in the results column: record unit, or follow the selected spectrum chart? | Follow the selected spectrum chart when one is on screen, else the record unit; the column header gives the unit |
| Q4 | Polar in phase 1, or disabled until the 1x phase measurement is done and verified? | Disabled in phase 1; S9 as phase 1b |
| Q5 | XY channel selection: two ordered combos in place of checkboxes? | Yes |
| Q6 | Allow chart edits during a recording? | Not in phase 1 |
| Q7 | Retire the "Envelope analysis" checkbox in favour of an envelope chart? | Yes, with a one-time migration |

## 7. Risks

- `gui.py` is about 5200 lines (R61). This work touches most plot code. Put
  the chart renderers in a new module `gui_charts.py` (imports dearpygui;
  excluded on ARM by `tests/conftest.py` like the other GUI modules) so that
  `gui.py` gets shorter, not longer.
- dearpygui can drop legends when series are added and removed
  (`_ensure_legends`). Rebuilding whole tabs makes this more likely; test it.
- Deleting a tab item that is selected can leave the tab bar with no
  selection. Select the first tab after a rebuild if the old one is gone.
- `DataCollector` has no lock (R59). The view cache is used on the render
  thread only. The session reprocess thread (R50) must not touch it.
