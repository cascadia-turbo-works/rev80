# Plot setup — wire channels to charts (phase 1)

Branch: `feat/plot-setup`, from `main` @ `ee72064` (v0.1.4).
Progress tracker: `.claude/plans/2026-10-17-plot-setup-progress.md`.
Requirement: R67 in `doc/PROGRESS.md`. Related open work: R24
(multi-channel plots; the polar chart stays there), R33 (flexible layout),
R42 (crest and kurtosis trend), R43 remainder (RPM on the trend plot).

Revision 2 (2026-10-19): owner decisions Q1, Q2, Q4, Q5 and Q7 applied;
spectrum averaging moves from the Acquisition tab to each spectrum chart.
Revision 5 (2026-10-19): Q9 decided (all cards always shown and updated);
Q10 decided (a sustain time for the fixed-limit alarm, default 0 s). A
table of anomaly triggers is recorded as later work (R68), not in scope.
Revision 4 (2026-10-19): section 3.11, data loaded from a file; a defect
found (a session trend reads 0.0 in any other unit); Q11 to Q13.
Revision 3 (2026-10-19): Q2 and Q3 revised (result cards and the peaks
table belong to a spectrum chart, in its unit); Q6 and Q8 decided; the
`history` argument leaves the public `result_view()` (3.2.1); the
recording lock gets a visible disabled state (3.7). New open question: Q9.

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
| Spectrum averaging: `averaging_enabled`, `n_averages` in `AcquisitionSettings`; a linear power average over the N most recent frames up to the displayed frame; overflow and degraded frames in that window are dropped, not replaced. It also averages `ChannelResult.overall`, which the anomaly hooks read | `sample.py:78-81`, `collector.py` step 3b |
| `n_averages_effective` clamps N to `cache_frames` | `sample.py:292` |
| The trend stores the five mV overalls for each frame, not averaged. The unit and mode are applied at display time | `update_trend`, `get_trend_for_display()` |
| Crest factor and kurtosis come from `ChannelResult.time_data`, the trace in the target unit. They change with the integration order | `process_sample` step 8 |
| Shaft speed has its own trend and never goes through unit scaling | `get_rpm_trend()`, `tach_trend` |
| `process_samples()` runs once for each displayed frame. It updates the trend and gives the results to `MonitorController.on_results()` and the result cards | `gui.py` `_display_frame_inner` |
| The RMS hook has a sustain time (`rms_s`, converted to `consecutive_n` frames). `FixedThresholdHook` has none: it fires on one frame | `headless.py:139-141`, `anomaly.py:356` |
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
def result_view(self, ch, unit=None, amplitude_mode=None, n_averages=1,
                index=None, peaks=True) -> ChannelResult | None
```

- `index=None` is the displayed frame: the newest when streaming, the browse
  cursor when stopped (the rule `process_samples()` uses now). Otherwise a
  position in the frame cache.
- `peaks=False` skips peak selection, for a caller that needs the overall
  and the scalars only (see 3.3).
- The averaging history is found inside the collector, not passed in. See
  3.2.1.

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
- `process_sample()` is removed. A private
  `_view_of_sample(ch, sample, unit, mode, history=())` holds the stage-2
  code. `result_view()` finds the sample and its history in the cache and
  calls it. The session reprocess path calls it directly for a sample that
  is not in the cache, with no history. `scripts/advanced_plots.py` uses
  `result_view()`.
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

#### 3.2.1 Where the averaging state lives

What `history` is now: a list of `VibeSample` objects for one channel,
oldest first. `_process_samples()` takes the frames before the displayed
frame from the frame cache (`list(cache)[stop - N + 1 : stop]`) and drops
the overflow and degraded ones. Stage 2 then walks the displayed frame and
the history newest first, sums `_psd_for()` and the squared mV overalls of
each, and stops at N frames or at the first frame whose PSD has a
different shape (a settings change). `_psd_for()` reads the PSD cached on
each sample, so an average costs one addition for each frame, not a
transform. The history is a window on the shared frame cache; nothing is
copied and no state is kept between calls.

Two places for the averaging state:

| | Chart keeps its own ring of past spectra | Collector derives the history from the frame cache (recommended) |
|---|---|---|
| Browse and replay | The ring holds what was displayed, in display order. Stepping back through the cache shows a different average than live showed. Breaks "replay shows what the live display showed" | Same rule live and browse: the N most recent frames up to the displayed one |
| Hidden charts | Only the chart on screen renders, so a hidden chart's ring has gaps. On a tab change it shows an average of stale frames | The cache has every frame; a chart that comes on screen gets a full average at once |
| Overflow, degraded, settings change | The chart needs the sample flags and the transform shape, so it needs the samples anyway | Already handled |
| Memory | A second copy of up to N spectra for each chart and channel | None: views on the existing cache |
| Units | Ring in mV² to stay unit-agnostic, or flushed on a unit change | Averaged in mV², converted after |
| Signature | `result_view(ch, sample, unit, mode)`, no history | `result_view(ch, unit, mode, n_averages, index)`, no history |

Decision for this plan: the chart owns the *setting* (Average on, N); the
collector owns the *data*. The chart stays agnostic: it asks for a view of
the displayed frame with its unit, mode and N, and draws what it gets.
`history` leaves the public signature, which is the simplification asked
for, without a second store of past frames. N is clamped to the cache
depth (`cache_frames`), and the chart row says when it is.

One behaviour to state in the README: the window is the N most recent
frames, and invalid frames in it are dropped, not replaced. So the count
can be below N after an overflow. `ChannelResult.n_averages` gives the
count, and the chart shows "averaging k of N frames".

### 3.3 Record unit, alarm unit, crest factor and kurtosis

- **Record unit** = the channel's target unit (Channels tab, as now; empty
  means the sensor EU). It sets: the monitor capture, the measurement file
  attributes, the trend's stored crest factor and kurtosis, the headless
  results. It does not set the result cards (see below). No change to
  files, sessions or headless input.
- **Alarm unit** (owner decision Q1): the Monitor tab anomaly section gets a
  unit and mode selector. The front end calls
  `process_samples(unit=alarm_unit, amplitude_mode=alarm_mode)` and gives
  those results to the anomaly hooks. Stage 1 is cached, so the extra cost
  is stage 2 only. Measure it (3.4).
  - **Alarms always use unaveraged results** (owner decision Q8).
    `process_samples()` never averages. The anomaly sustain time (`rms_s`,
    converted to `consecutive_n` frames) is the debounce, not an average.
    Today a hook sees an averaged overall when averaging is on; that ends.
  - `FixedThresholdHook` has no sustain time: one frame over the limit
    fires it. With averaging on, the average hid single-frame spikes from
    it; unaveraged, it does not. **It gets its own sustain time** (owner
    decision Q10): config key `fixed_s`, default 0 s, which is one frame,
    the current behaviour. It converts to frames as `rms_s` does
    (`round(s / period) + 1`), and it has its own field in the anomaly
    section beside the fixed limits. It is separate from the RMS sustain
    time (default 3 s), because the defaults differ. A frame that fails the
    speed gate or is flagged resets the count, as for the RMS hook. Both
    `_build_anomaly_hook` copies and headless change; the hook-build test
    checks that the defaults agree.
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
- **Result cards and the peaks table** (owner decisions Q2 and Q3,
  revision 3): a card belongs to a (spectrum chart, channel) pair, not to a
  channel. Its overall, crest factor, kurtosis, 1x level and peaks table
  are in that chart's unit and mode, from the same `result_view()` that
  draws the chart. A channel on two spectrum charts has two cards, possibly
  in two units. Each value has its unit on the card, for example
  `Crest 3.10 (in/s)`.
  - The overall on a card of an averaging chart is the averaged overall,
    labelled "avg k". Crest factor and kurtosis are never averaged: they
    come from the displayed frame's trace in the chart unit.
  - The cards are grouped under a header with the chart name.
  - A tachometer channel keeps one shaft-speed card for each channel, not
    for each chart. A shaft speed has no unit view.
  - The overflow warning stays one line for each channel at the top of the
    column. It is a fact of the frame, not of a view.
  - **All cards always show and update** (owner decision Q9): every
    spectrum chart's cards, expanded, peaks table included, on every frame,
    whichever tab is on screen. Only the plot series of a chart that is not
    on screen are skipped. So for a spectrum chart, "process only the chart
    on screen" applies to drawing, not to the `result_view()` calls.
- The trend keeps storing crest factor and kurtosis of the record-unit
  trace, from step 1 of 3.4.

### 3.4 Processing: the always-run part and the on-screen part

Each new frame, whatever the selected tab:

1. `process_samples()` in the record unit, unaveraged: trend update,
   tachometer trend, speed gate, overflow flags, monitor capture.
2. When recording with an alarm unit different from a channel's record
   unit: `process_samples(alarm unit)` for the hooks.

Steps 1 and 2 must not depend on the selected tab, or a recording made with
the Spectrum tab selected differs from one made with the Trend tab
selected.

Then, only for the chart on screen:

3. `_render_chart(spec)`: one `result_view()` for each checked channel in
   the chart unit, mode and N (cache hit when it equals step 1), then
   `set_value` on that chart's series. For a spectrum chart, the same
   results update its result cards.
4. The cards of every other spectrum chart (Q9): one `result_view()` for
   each of their channels, peaks included, and the card widgets. No
   `set_value` on their plot series. Cost: one view for each (spectrum
   chart, channel) for each frame. The peaks-table widget pool (E19) keeps
   the widget traffic to the rows that change. Measure it (2 spectrum
   charts, 8 channels); if it is too slow, the fallback is a one-line
   summary for the cards of a chart not on screen, updated with
   `peaks=False`.

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
| Spectrum | `result_view(..., n_averages)`: spectrum, peaks, 1x marker | Frequency, Hz | `unit mode` | Average checkbox and N for each chart. Info line "averaging k of N frames" for each chart. Avg. window (N × acquisition period) shown in the Charts table row. Owns the result cards and peaks tables of its channels (3.3) |
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
- Opened from a **Charts** button in a new strip above the tab bar of the
  middle pane (`BTN_CHARTS_SETUP`), and from the dialog's tab bar.
- **Recording lock** (owner decision Q6): chart setup is locked during a
  recording, like every acquisition window. `BTN_CHARTS_SETUP` goes into
  `_RECORDING_LOCKED_CONTROLS`.

**Recording lock: visible disabled state (reported bug).** A user pressed
the acquisition setup button during a recording and nothing happened. The
button was disabled by `_set_recording_lock()`, but it looked the same as
an enabled button: `gui.py` binds no theme for the disabled state, and
dearpygui draws a disabled button with the normal colours. Fix:

- One global theme with `dpg.theme_component(..., enabled_state=False)`
  for buttons, combos, checkboxes, input fields and sliders: muted text and
  frame colours from the existing palette (`_c("MUTED")`). Bind it once in
  `_create_gui()`, so every disabled widget in the app is visibly disabled,
  not only the locked ones.
- A tooltip on each locked control while it is locked: "Stop the recording
  to change this."
- Test (GUI context): the theme exists with a disabled-state component for
  `mvButton`; `_set_recording_lock(True)` disables every control in
  `_RECORDING_LOCKED_CONTROLS`, `BTN_CHARTS_SETUP` included, and
  `_set_recording_lock(False)` enables them again.
- This is a separate commit (S0b) ahead of the chart work, because it is a
  defect in the released version. CHANGELOG entry under Fixed.

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
- Results column: the channel result sections (`ch_result_section(ch)`,
  `ch_overall_value(ch)`, `ch_scalars_text(ch)`, `ch_one_x_text(ch)`, the
  peaks-table pool keyed by channel) become sections keyed by
  `(chart_id, ch)`, grouped under a header for each spectrum chart. The
  peaks-table widget pool (E19) is kept, keyed the same way. Tachometer
  cards and the overflow warning stay keyed by channel.
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

### 3.11 Data loaded from a file

Five entry points load data into the frame cache:

| Entry point | Collector call | Frames | Trend source |
|---|---|---|---|
| File > Load, `--from-file` with a measurement file | `load_data()` | the saved frame cache: contiguous frames | `/trend`: all five mV orders (v4 and later); order 0 only (v3) |
| Session browser, `--from-file` with a session | `load_monitor_session()` | every interval capture; the cache grows to hold all N | `overall_json`: one value for each capture, in the record unit |
| Session browser, one capture | `load_monitor_capture()` | one capture | none |
| Session browser, one burst | `load_monitor_burst()` | contiguous burst frames, `rel_time` rebased to the trigger | `overall_json` for each frame, in the record unit |
| Session reprocess (thread) | `reprocess_session_trend()`, then `load_monitor_session()` | as the session load | rewritten `overall_json`, record unit |

What a load does now, and what it means for charts:

1. **The acquisition settings come from the file.** `_restore_metadata()`
   replaces `collector.config` with the file's settings: F_max, bin size,
   band, high-pass, and the per-channel names, target units, amplitude
   modes, roles and tachometer calibration. `_wire_session_sensors()`
   assigns the file's sensors. `_post_load()` sets `enabled_channels` to
   the channels in the frames.
2. **The chart set does not come from the file.** It is the user's layout
   (`charts.yaml`), and the plan keeps it unchanged through a load. Charts
   select channels by index. This is the useful case: the same layout for
   live data and for files of the same machine.

Consequences and the rule for each:

| Case | Rule |
|---|---|
| A chart's channel is not in the file | The series is empty. The legend entry reads "Ch C: not in this file". The channel stays checked in the chart. |
| A file channel is on no chart | It is not shown. The Frame info card lists the loaded channels, so this is visible. The Charts tab offers it. |
| A file channel cannot reach the chart unit (no sensor in the file, or another quantity) | The series is empty, with the reason in the legend: "Ch B: no sensor in this file, cannot show in/s". Never a value in mV under an in/s axis. |
| A file channel has a different name than the live channel at the same index | The legend uses the file's name (`name_for(ch)` reads the loaded config). The chart name, which the user typed, does not change. The README says that charts select by index. |
| A file channel is a tachometer, but the chart has it as a vibration channel (or the reverse) | `channel_selectable()` uses the loaded roles. A tachometer is never drawn as vibration. A trend chart's `tach_channel` that is not a tachometer in the file gives no y2 series. |
| The Charts tab is opened while a file is loaded | The table shows the loaded channels. A checked channel that is not loaded shows greyed with "not loaded" and stays checked. **The table never removes a channel from a chart because it is absent now.** Otherwise one edit during a file browse loses the live layout. |
| The record unit | From the file (`target_unit` attribute). It sets the stored trend's unit and the session `overall_json`; it does not limit the charts. |

One GUI hook replaces the per-path series code. `_on_load_file()`,
`_load_from_path()` (session branch), `_on_session_list_select()` and
`_on_burst_list_select()` each remove and add series and call
`_update_axis_assignment()` in their own way now. Replace this with one
`_on_data_source_changed()`, called after every load and after a device
connect: it re-evaluates each chart against the loaded channels, units and
roles, rebuilds the series and the legend notes, rebuilds the cards (3.3),
and renders the chart on screen.

#### 3.11.1 Defect: a session trend shows zeros in any other unit

`load_monitor_session()` and `load_monitor_burst()` rebuild the trend from
`overall_json`, a single value in the record unit. They back-scale it to mV
and put it in the one order column of that unit. The other four columns
stay `0.0`. `get_trend_for_display()` then gives `0.0` for every point in
any unit with another integration order.

Reproduced (2026-10-19, scratchpad `trendcols.py`, an accelerometer at
100 mV/g, trend rebuilt as the session loader does, recorded in in/s):

| Display unit | Trend values |
|---|---|
| in/s | 273.0, 283.9, 278.5 |
| g | 0.0, 0.0, 0.0 |
| mil | 0.0, 0.0, 0.0 |

Today this is reachable by a change of the channel unit after a session
load. With per-chart units, any trend chart in another unit shows it: a
flat zero line that reads as a measured value. v3 measurement files fill
order 0 only, so they have the same defect for integrated units.

Fix (step S2b), in order of preference:

1. **Rebuild the trend from the stored frames.** Every capture and burst
   frame stores its raw-rate mV waveform, and the loader already reads all
   of them into the cache. Stage 1 of `result_view()` gives the five mV
   orders of each frame (cached on the sample). The trend is then exact in
   every unit. Equality test: in the record unit, the rebuilt trend equals
   the `overall_json` values to float tolerance. Measure the load time of a
   long session (for example 1440 captures, 4 channels).
2. **Where a frame has no waveform** (a tachometer channel, a damaged
   group): NaN in the missing columns, never 0.0. A NaN point is a gap on
   the plot.
3. **Shaft speed** from the loaded tachometer samples: each frame has a
   `TachResult` from its stored edge times. Today a session load builds no
   RPM trend, so a trend chart with y2 is empty for a session. Rebuild the
   RPM trend from the usable readings, with the frame `rel_time`. Also:
   neither `load_data()` nor `load_monitor_session()` clears `tach_trend`,
   and `init_trend_channels()` keeps the entries of every channel that is a
   tachometer in the loaded config. So a session with a tachometer on the
   same channel as the live setup keeps the live RPM trend beside the
   session's vibration trend. Found by reading the code, not reproduced;
   a measurement file without a tachometer channel drops it correctly
   (checked, scratchpad `tachleak.py`). Clear `tach_trend` at the start of
   every load.

`overall_json` stays in the file for older readers, and
`reprocess_session_trend()` keeps writing it in the record unit.

#### 3.11.2 Averaging on loaded data

The averaging rule takes "the N most recent frames up to the displayed
frame". That is correct for contiguous frames: a live cache, a measurement
file, a burst. A monitor session is not contiguous: its captures are
`interval_s` apart (default 600 s). A spectrum chart with N = 8 on a session
averages 8 captures over 80 min and labels it "averaging 8 frames". That is
a different measurement, and on a machine that changes speed or load it
smears lines.

Rule: the average uses contiguous frames only. A frame is contiguous with
the next when the difference of their `rel_time` is at most 1.5 x the
acquisition period. The walk back stops at the first gap, as it stops now
at a settings change. On a session, k = 1 and the chart says "averaging 1
of 8 frames (captures are not contiguous)". `rel_time` is in every stored
frame.

#### 3.11.3 Other loaded-data points

- **Envelope and XY** need only the raw-rate frame, which every file
  stores. No change.
- **1x marker and cards:** `current_rpm()` reads the tachometer sample of
  the displayed frame, so a loaded frame shows its own shaft speed. No
  change.
- **The session reprocess thread** (`_on_sb_reprocess`) calls
  `load_monitor_session()` off the render thread (R50). The view cache and
  `_on_data_source_changed()` are render-thread only; the thread must hand
  the result back to the render thread, not call them.
- **Storing the chart set in a file** is not in phase 1. If a later phase
  stores it, a load offers it; it does not replace the user's set.

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
- [ ] A loaded file never changes the chart set, and the Charts tab never
      drops a checked channel because it is absent now.
- [ ] No trend value is 0.0 because it was not recorded: NaN, a gap.
- [ ] An average uses contiguous frames only.
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
| S0b | Fix: locked controls show a disabled state during a recording, with a tooltip | disabled-state theme bound; lock and unlock of every locked control |
| S1 | `charts.py`: model, validation, `default_for`, YAML load/save, `charts_config_path()` | `tests/test_charts.py`: round trip; bad entry skipped; bad file not overwritten; allowed units; tachometer refused; XY needs two; default set equals today's layout |
| S2 | `result_view()` (no `history` argument); `_view_of_sample()`; `process_sample()` removed; `process_samples(unit, mode)` unaveraged; unit-parameterised `get_trend_for_display()`; view cache | equality test (reference captured before the change); conversion test (off-bin, phase ≠ 0); revert check; `test_spectral_averaging.py` moved to the argument |
| S2b | Loaded trends: rebuild the five orders from the stored frames for sessions and bursts; NaN where no waveform; RPM trend from the loaded tachometer samples; contiguous-frame averaging rule | reproduce the zero trend first (3.11.1), then the fix; equality with `overall_json` in the record unit; NaN gap; a session gives k = 1; revert checks; session load time measured |
| S3 | Alarm view: Monitor-tab unit and mode, `alarm_view()` helper, both `_build_anomaly_hook` copies, headless, fixed-limit migration, fixed-limit sustain time `fixed_s` | hook fires on the alarm-unit overall; `fixed_s` = 0 fires on one frame (today's behaviour, equality); `fixed_s` > 0 needs consecutive frames and a flagged frame resets the count; channel that cannot convert is skipped; migration from `fixed_upper_unit`; GUI and headless defaults agree |
| S4 | Main window: dynamic tab bar; Charts button; `_on_data_source_changed()` for every load path and device connect; bottom plot and second-y-axis code removed; waveform, spectrum (with per-chart averaging) and trend renderers; result cards and peaks tables for each (spectrum chart, channel); on-screen-only rendering; render on tab change | GUI-context tests: tabs from a set; rebuild keeps the selection; a load with a missing channel and a channel with no sensor gives empty series with a legend note; hidden chart not rendered (patch `is_item_visible`); tags by `chart_id` |
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
| Q2 | Crest factor and kurtosis | ✅ Revised: on a result card, in the unit of that card's spectrum chart, never averaged. The trend stores the record-unit values |
| Q3 | Peaks table and result cards | ✅ One card for each (spectrum chart, channel), in the chart's unit, mode and averaging. A channel on two spectrum charts has two cards |
| Q4 | Polar in phase 1 | ✅ Deferred to R24 |
| Q5 | XY selection | ✅ Two ordered selectors and a swap button |
| Q6 | Chart edits during a recording | ✅ Locked, like all acquisition windows. The locked controls must look disabled (reported bug, S0b) |
| Q7 | Envelope checkbox | ✅ Retired; an envelope chart replaces it |
| Q8 | Averaged data for alarms | ✅ Never. Alarms use unaveraged results; the sustain time is the debounce |
| — | Averaging state | ✅ The chart owns the setting (on, N); the collector derives the history from the frame cache. `history` leaves the public `result_view()` (3.2.1) |
| Q9 | Result cards of spectrum charts not on screen | ✅ Always shown and updated, peaks table included (3.3, 3.4). Fallback if too slow: a one-line summary |
| Q11 | On a file load: keep the user's chart set and select channels by index? | Open. Recommended: yes (3.11). Charts never change on a load |
| Q12 | Averaging on non-contiguous frames (monitor sessions) | Open. Recommended: contiguous frames only; a session averages 1 frame and says why (3.11.2) |
| Q13 | Session and burst trends: rebuild the five orders from the stored frames on load? | Open. Recommended: yes; it fixes the zero trend (3.11.1) and gives the RPM trend. Measure the load time first |
| Q10 | Sustain time for the fixed-limit alarm | ✅ Yes: its own `fixed_s`, default 0 s (one frame, as now) |
| — | Anomaly triggers as a table (like the Charts table): add a trigger type, set it up in a row; fixed triggers as one type with > or < | Not in this work. Tracked as R68 |

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
