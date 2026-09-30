# Changelog

All notable changes to **Rev80** are documented here.
Sections dated before the 2026-08 rebrand describe the project under its
former name, vibechecker, and retain it as an accurate record.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### doc/revision — documentation split, audit record and design evidence (2026-09-30)

#### Added
- **`doc/audit-202608.md`, the record of the August 2026 audit.** It has one
  section for each finding, with the status and the commits that fixed it.
  Each heading is the bare finding ID, so a link such as
  `[S-02](audit-202608.md#s-02)` goes to the finding. This CHANGELOG and
  `doc/PROGRESS.md` refer to a finding only by such a link.
- **`CONTRIBUTING.md`, section "Design evidence".** It has one subsection for
  each design decision, E1 to E20. A subsection holds the value, the measured
  table, a "Measured on" line and the rejected alternatives. A comment beside a
  constant gives one line with the key number and the section title, for
  example `CONTRIBUTING.md, "E2. Anti-alias kernel"`.
- **`CONTRIBUTING.md`, section "Documentation rules".** It gives the place for
  each kind of text.

#### Changed
- **The documents have separate readers.** `README.md` is the operator manual
  and the vibration-engineering configuration. `CONTRIBUTING.md` is the
  developer guide: environment, layout, architecture, build, release, tests and
  design evidence. `CLAUDE.md` gives the invariants and the known-bad areas.
  This CHANGELOG and `doc/PROGRESS.md` hold the history.
- **Code, tests, README and CONTRIBUTING do not contain audit IDs or
  decision IDs.** A rule that is still true is written in plain words.
  `CLAUDE.md` gets the same change.
- **Docstrings and comments state the contract.** The measured tables moved to
  CONTRIBUTING, "Design evidence". The history of fixed defects moved to this
  file and to the audit record.
- **`doc/PROGRESS.md`**: the Requirements Tracker is the single status
  source. The open audit findings are tracked as R50 to R62.
- **This file**: each audit ID is a link to the audit record. The numbers of
  the vibration-engineering reviewer are replaced by the M-number of the same
  finding. The tachometer decision numbers are replaced by plain words,
  because no file defines them: "one pulse per revolution is the default and
  the recommended configuration", "a tachometer channel stores edge times,
  not the waveform", and "the RMS threshold default is 50 %". The text is in
  ASD-STE100 Simplified Technical English. No number, date or commit hash in
  the history changed. Where a figure is not correct for the current code, a
  dated correction line follows it.

#### Notes for the next person
- `doc/*.pdf` are build artifacts. `scripts/render_docs.sh` renders them in
  the release workflow. `doc/audit-202608.md` is not rendered and is not a
  release asset (owner decision).
- The work is in more than one commit on `doc/revision`. When this entry was
  written, the "Design evidence" subsections had their headings only,
  `CLAUDE.md` still had its old IDs, and only `[Unreleased]` and `[0.1.3]` of
  this file were revised. Later commits on the same branch do the rest.

### fix/tach — unusable tach readings, GUI compression level (2026-09-30)

#### Fixed
- **An unusable tach reading counts as no reading.** A reading with quality
  `unsteady` or `inconsistent` has an rpm, but `TachResult.is_usable` is
  False. No code used `is_usable`. Thus such a reading could pass the speed
  gate, latch the gate reference and go into the RPM trend. Now
  `DataCollector.speed_ok()` gets only a usable reading, so the gate fails
  closed on an unusable one: the frame is not trended, not used for a
  baseline and cannot raise an alarm. The RPM trend does not record it. The
  frame is still displayed and stored, and `ChannelResult.rpm` still shows
  the value. `tests/test_tach_usable.py` keeps this. Without the gate part,
  3 of its 4 tests fail. Without the trend part, 2 fail.
- **A GUI monitor session uses `monitor.compression_level`.** The GUI used
  gzip level 4 for each session. Now `_monitor_session_params()` reads the
  level from `acquisition.yaml`, as headless does.
  `tests/test_gui_compression_level.py` keeps this. Without the fix, its 2
  tests fail.

#### Removed
- **`_dsp.band_rms`.** No code called it. The overall uses the Hann-tapered
  path. CONTRIBUTING.md, "E10. Band RMS", records why.

#### Changed
- Comments: the `compression_level` seed in `config.py` and the
  `AnomalyEvent` fields. `trigger_time` is the onset. The burst t = 0 is the
  confirming frame. The controller does not use `trigger_rel_time`.
- README, "Storage": the estimate text agrees with
  `gui.monitor_storage_estimate` (decimal units, vibration channels only,
  50 % gzip as an assumption).

### fix/monitor — burst cap, compression and session times (2026-09-30)

#### Fixed
- **An anomaly burst keeps its pre-trigger frames**
  ([S-02](audit-202608.md#s-02)). `MonitorSession` had no frame period. Thus
  the burst frame cap was `MIN_BURST_FRAMES` (4), and an anomaly burst kept
  only its last 4 frames. Now `session_from()` records `acquisition_period`
  (`raw_blocksize / raw_samplerate`). The cap is `max_burst_s / period + 1`
  frames after the trigger, plus the pre-trigger frames. If a session has no
  frame period, the controller logs a warning.
- **A manual burst uses the same limits as an anomaly burst**
  ([S-02](audit-202608.md#s-02)). The manual trigger did not clamp its end to
  `max_burst_s` and did not set a frame cap. Now both paths use
  `capped_burst_end()` and the same frame cap.
- **A session without compression records.** `--no-compress`,
  `monitor.compression: none` and the GUI compression box give compression
  `'none'`. h5py has no filter of that name, so the first write failed and the
  session stopped. Now the writer writes uncompressed data for `'none'`.
- **The resource trail logs the capture count.** It always logged
  `captures -1`.
- **Headless reads `monitor.compression_level`.** Before this change, headless
  sessions always used gzip level 4. The GUI also reads it since fix/tach
  (2026-09-30).
- **The headless session ID uses local time** ([S-10](audit-202608.md#s-10)).
  Before this change, headless made the ID from UTC. The GUI and `start_time`
  use local time.
- **The headless shutdown message is correct.** It said "after current
  interval". The loop stops within approximately 1 s.
- **The headless tachometer full-accuracy limit uses the achieved rate.** The
  summary prints before the stream starts, so it uses the nominal rate and
  says so. After the first frame, headless logs the limit again at the
  achieved rate.
- **The trigger time of an anomaly burst describes its t = 0 frame.** The
  frame at `n_pretrigger` is the frame that confirms the anomaly. Before this
  change, the burst recorded the onset from the hook as its trigger time, and
  the onset `rel_time` was on the collector clock. Now `trigger_timestamp` and
  `trigger_rel_time` describe the stored t = 0 frame, on the session clock.
  The onset is in the new `onset_timestamp` attribute (anomaly bursts only).

#### Notes for the next person
- Tests: `tests/test_monitor_burst_cap.py`,
  `tests/test_monitor_writer_compression.py`,
  `tests/test_monitor_resource_trail.py`, `tests/test_headless_session.py`
  and `tests/test_monitor_burst_onset.py`. Each fails without its fix.
- fix/tach (2026-09-30) makes the GUI read `monitor.compression_level`.

### fix/gui — monitor config and four GUI defects (2026-09-30)

#### Fixed
- **A config dialog close keeps the monitor block of `acquisition.yaml`.**
  Before this change, only an open of the Monitor tab loaded the config into
  the Monitor widgets. Each dialog close saves those widgets. Thus a close on
  any other tab wrote the widget construction defaults over the monitor block
  of the user: interval 1 h, pre-trigger 60 s, burst 60 s, anomaly off, RMS
  threshold 10 %, warm-up 30 frames. A recording started without an open of
  the Monitor tab also used those defaults. Now `GUI.initialize` loads the
  config into the widgets at startup. The save:
  - keeps the keys that have no widget (`max_burst_s`, `compression_level`,
    `rms_alpha`, `spec_alpha`);
  - keeps a stored interval that is not a preset;
  - does not add an EWMA time that the config does not have (headless uses an
    EWMA time before an alpha).

  All monitor fallbacks in `gui.py` are now the `config.py` seed values.
  Before this change, `_start_recording` used 60 s / 60 s, and the dialog
  30 s / 120 s. `tests/test_gui_monitor_config.py` keeps this. Without the
  startup load, 5 of its 11 tests fail.
- **The automatic envelope band stays in the protected band.** The GUI
  searched for a demodulation band up to the raw Nyquist frequency (12.8 kHz
  at 25600 Hz). Above 10 kHz, the anti-alias filter attenuates the signal.
  Now the search ends at the raw rate / 2.56 (10 kHz), as the
  `envelope.suggest_band` contract requires.
- **The degraded-rate warning compares two raw rates.** It compared the
  measured raw rate with the display rate, for example "25000/5120 Hz". Now
  it compares with the nominal raw rate, for example "25000/25600 Hz".
- **The monitor storage estimate has correct units.** It divided by 10^9 and
  10^6, but showed "GiB" and "MiB". Now it shows "GB", "MB" and "kB". It
  also counted a tachometer channel as a full waveform. A session stores only
  the edge times of that channel, so now the estimate does not count it. The
  estimate still assumes that gzip halves the data. Its new tooltip says that
  this is an assumption. `tests/test_gui_small_defects.py` keeps these three
  fixes. Without them, 5 of its 8 tests fail.
- **A recording refuses a stream stop.** Ctrl+K, the Acquisition button and
  the Tachometer tab button could stop the stream while a recording ran. The
  recording then continued, but got no frames. Now the stop is refused with
  an info message: stop the recording first.
  `tests/test_gui_stream_stop_lock.py` keeps this. Without the fix, 3 of its
  6 tests fail.
- **The Welch Overlap tooltip is correct.** It said that a higher overlap
  smooths the spectrum. Welch uses one segment for each frame
  (`nperseg == blocksize`), so the overlap has no effect. Now the tooltip
  says this and refers to Average spectrum. `tests/test_welch_overlap_tip.py`
  shows that the spectrum is bit-identical at 0 % and 90 % overlap, at six
  F_max and bin-size presets.

### fix/collector — reprocess a session with a tachometer channel (2026-09-29)

#### Fixed
- **"Reprocess session" accepts a session with a tachometer channel.** The
  monitor writer stores edge times for a tachometer channel, not a waveform.
  `DataCollector.reprocess_session_trend` read a `data` dataset from each
  channel group and stopped with `KeyError`. Now it skips each channel group
  that has no waveform, in the interval captures and in the burst frames. The
  new `overall_json` holds the vibration channels only.
  `tests/test_reprocess_session_tach.py` keeps this.

### fix/monitor — burst alignment and live-only recording (2026-09-29)

#### Fixed
- **A manual burst writes each overall beside its own waveform**
  ([S-06](audit-202608.md#s-06)). The manual trigger put the trigger frame in
  the frame list, but not its results in the results list. The results list
  was one entry short. Thus each later overall was written beside the
  previous frame, and the last frame had no overall. Now the trigger frame
  gets the results of the last `on_results` call, as in the anomaly path.
  The trigger frame is the frame that those results belong to. A frame that
  arrives after it has no results yet, so it is not included. The two lists
  have equal length in all cases, also with an empty frame cache.
- **A monitor recording contains only live frames**
  ([S-03](audit-202608.md#s-03)). Before this change, the GUI sent each
  displayed frame to the monitor while a recording ran. A file load, or a
  browse through the cache, thus wrote frames that were not live into the
  live `session.h5`. Now the monitor gets a frame only when the collector
  streams.
- **A recording locks file access.** While a recording runs, these controls
  are disabled: File Load, Load Session and Clear Cache. The Ctrl+O shortcut
  does not use the button state, so the load handler also refuses and logs
  an info message. The session browser and clear-cache handlers refuse in
  the same way. Thus the session browser cannot open the session file while
  the writer appends to it.

#### Notes for the next person
- `tests/test_manual_burst_alignment.py` makes sure that frame *k* and
  results *k* are the same frame, at the trigger and after each new frame.
  Without the fix, two of its four tests fail.
- `tests/test_monitor_live_only.py` tests the GUI decisions without a DPG
  viewport. Without the fix, 12 of its 14 tests fail. This includes the test
  that sends a browsed frame through `_display_frame_inner`.
- This change did not lock Ctrl+K. fix/gui (2026-09-30) does: a stream stop
  from Ctrl+K, the Acquisition button or the Tachometer tab is refused while
  a recording runs.

### fix/collector — each file type has its own version limit (2026-09-29)

#### Fixed
- **A current monitor session does not give a false version warning.**
  Measurement files are version 5 (`DataCollector._FILE_VERSION`). Monitor
  sessions are version 6 (`monitor/writer.py`). The session loaders
  (`load_monitor_session`, `load_monitor_capture`, `load_monitor_burst`) used
  `_restore_metadata`, which compared all files with 5. Thus each load of a
  current session logged "File version 6 is newer than this build supports (5)".
  Now `_restore_metadata` takes the limit for the file type. The session
  loaders give the limit of the session writer. The limit comes from the
  writer constant, not from a literal.

#### Notes for the next person
- **The warning continues to operate for a file that is really newer.** A
  version 7 session and a version 6 measurement file both give the warning.
  `tests/test_file_version_check.py` makes sure of the two cases and of the
  case without a warning.
- `collector.py` imports the writer constant inside a function. A
  module-level import is circular, because `monitor/writer.py` imports
  `collector.py`.

### fix/paths — logs go to the user directory in every install (2026-09-29)

#### Fixed
- **The log directory does not change with the working directory.** Before
  this change, `_paths.log_dir()` used `~/Documents/Rev80/logs/` only in a
  frozen build. All other installs used the relative directory `log/` in the
  current working directory:
  - A desktop launcher after `pip install --user .` starts with the working
    directory `$HOME`. The logs went to `~/log/`.
  - `rev80-headless` under systemd without `WorkingDirectory=` starts with the
    working directory `/`. `mkdir('/log')` raised `PermissionError`, and the
    program stopped before logging started.

  Now every install writes its logs to `~/Documents/Rev80/logs/`: the frozen
  build, a `pip install`, and an editable checkout. This is the same as
  `data_dir()`. `faulthandler.log` uses the same directory.

#### Notes for the next person
- **An editable checkout does not write to `./log/` now.** Look in
  `~/Documents/Rev80/logs/`. The `log/` entry in `.gitignore` stays, because
  old checkouts can still have that directory.
- `tests/test_paths.py` makes sure that `log_dir()` is absolute and does not
  change when the working directory changes.

### build/ci — rendered docs are release artifacts, not commits (2026-09-28)

The pre-commit hook rendered `doc/*.pdf` again at each commit, and the PDFs
were committed with their Markdown. Measured before the change: **10.3 MB of
PDF blobs across 34 commits, against 13.4 MB for every version of every
source file**. Each commit that touched a document added approximately
300 KB. PDF is already compressed, so git cannot delta it. Rendered copies of
files in the repository were near half of its storage and were its largest
growth term. The hook also made pandoc and WeasyPrint (with the native Pango
stack of WeasyPrint) necessary to make a commit. No consumer used the PDFs:
not the installer, not the wheel, not CI.

#### Changed
- **`doc/*.pdf` are gitignored build artifacts.** They are not tracked. A new
  `docs` job in `release.yml` renders them. It is the only place where the
  toolchain is installed. The draft-release job attaches its output with the
  installer and the wheel. Thus a PDF given to a client is pinned to a
  release, not to the last commit that rendered it.
- **The pre-commit hook runs ruff only.** The blocking lint gate stays. It
  uses the same invocation as CI.
- **WeasyPrint is pinned (`==69.0`) in the workflow.** This is the version
  that these documents were last checked against. Thus a WeasyPrint release
  cannot change the layout of a client document between two tags without a
  notice.

#### Added
- **`scripts/render_docs.sh`** renders all four published documents. The
  document list was in the hook. Now it is in this script, and the workflow
  runs the script. The list is not repeated.

#### Fixed
- **Each PDF rendered after the August rebrand said "vibechecker"** in the
  page header at the top right. The name was hardcoded in the CSS of
  `render_md.sh`. Now it is "Rev80".

#### Notes for the next person
- **Rendering in `build.sh` was considered and rejected.** `build.sh` runs
  under Git Bash on Windows for the installer targets, and WeasyPrint on
  Windows needs GTK. That puts the heaviest form of the dependency on the
  platform where the build already has the most parts. Also, the output would
  still be committed.
- **The history was not rewritten** to recover the 10.3 MB. The GitHub remote
  is live, and a force-push to save ten megabytes is a bad trade. `git gc`
  repacks the loose objects and gives most of the practical gain.
- **The `docs` job has no tag guard.** Only the release job has one. Thus a
  `workflow_dispatch` run tests the render before a real tag depends on it.

### feature/tachometer — one session factory, and two defects it hid (2026-09-21)

This follows R44. It lists what was still different between `gui.py` and
`headless.py`. Both front ends made a `MonitorSession` field by field, with
fourteen arguments each. Two of those fields had drifted or had no effect.

#### Fixed
- **Headless kept one pre-trigger frame less than configured.** The GUI set
  the frame cache to `pre_buffer_n + 1` frames, and headless to
  `pre_buffer_frames`. The comment in the GUI gives the reason for the
  `+ 1`: `MonitorController` slices `frame_cache[-n:]`, and the trigger frame
  then becomes `burst_frames[n]`. Thus a cache of exactly n gives n-1 true
  pre-trigger frames, because the trigger frame uses one slot. No code reports
  the achieved count, so each unattended burst had one frame less lead-in
  than configured, without a notice. Now both front ends call
  `monitor.session.required_cache_frames()`.
- **The setting `max_burst_s` had no effect.** `config.py` seeded it in
  `acquisition.yaml`, and the headless session summary printed it, but **no
  code read it**. Both front ends gave a hardcoded `600.0` to
  `MonitorSession`. The config save of the GUI wrote `600.0` back as a
  literal, so the next use of the monitor dialog removed a manual edit. Thus
  `max_burst_s: 120` printed "max 120s", applied 600, and changed itself back.
  This setting is the limit that stops an unattended burst before it grows
  until the OOM killer stops the process ([S-02](audit-202608.md#s-02),
  measured at ~2.26 MB/s / ~8.1 GB/h on four channels). A limit that no one
  can change is not an acceptable defect to keep. Now both front ends read
  it, and the GUI keeps it on save and does not write it again. It still has
  no widget. It is a setting in `acquisition.yaml` only, and now it has an
  effect.

#### Added
- **`monitor.session.session_from()`**, the single `MonitorSession`
  constructor. It is keyword-only, because fourteen positional fields let the
  two copies drift without a notice. With it come `sensor_snapshot_for()`
  (the loop that removes duplicate sensors by ID; each front end had its own
  copy) and `pre_buffer_frames_for()` (the same formula, with the
  divide-by-zero guard in a different place in each copy).
- Tests that read the source and assert that neither front end makes a
  `MonitorSession` directly, sets the cache size itself, or pins the burst cap
  to a literal. `tests/test_anomaly_hook_build.py` uses the same method on the
  one copy that remains.

#### Notes for the next person
- **`_build_anomaly_hook` is now the last duplicated pair.** It is the
  hardest: the two copies read from different sources (DPG widgets and a
  config dict). They need a parameter object between them, not the direct
  extraction that the other three pairs got.

### feature/tachometer — headless runs a tachometer (R44) (2026-09-21)

Before this change, `rev80-headless` refused tachometer channels. It reads
the same `devices/*.yaml` that the GUI writes. A tachometer channel through
the vibration path gives overall 1514.9 mV, crest 5.00, kurtosis 15.94 and 63
spectral peaks on a 5% duty 1800 RPM square wave. An analyst who reads that
session concludes that a bearing is badly damaged. Thus "out of scope" had to
mean "does not do it".

Now headless runs a tachometer. The pipeline below `receive_data` already
knew the channel role, so most of this change connects existing parts. But
the survey that said so was wrong in three places, and these three places
are the important part of this change.

#### Added
- **`config.channel_role_state()`**, the single decision for what a
  `channels/{ch}` block means: role, tach calibration, enabled. The GUI and
  headless each had their own copy, and the copies **had already drifted**:
  the GUI set a missing `enabled` to True, headless to False. The loader is
  also safer now: an unknown role reads as vibration, with a warning, and
  does not propagate. A config loader that raises once erased the sensor
  library ([X-01](audit-202608.md#x-01)).
- **`monitor.session.channel_snapshot_for()`**, for the same reason, for the
  channel snapshot in `session.h5`. Both copies omitted the channel `role`, so
  a loaded session could only infer it from a missing `data` dataset.
  Tachometer channels now also carry their calibration, so the shaft speed can
  be calculated again at a different `pulses_per_rev`.
- **`sensor._simulate_tach_sources()`.** No code in the package set
  `SimulatedSensor.channel_sources`; only tests did. Thus a simulated
  tachometer channel got the same accelerometer waveform as the vibration
  input and read `no_signal`. As a result, **neither front end could run
  offline against a tachometer**. The function uses
  `machine_with_tach_sources`, so the pulse train stays locked to the shaft
  rate of the vibration channel.
- **A tachometer block in the headless session summary**: channel, threshold
  mode, polarity, pulses/rev, and the two limits that a ppr above 1 meets:
  the slowest shaft that can be measured (`slowest_rpm_for`) and the
  `MIN_SAMPLES_PER_PULSE` accuracy ceiling. An unattended run has no
  Tachometer tab to show these values, and the session file does not hold
  them.
- **Shaft speed on the headless status line.** It shows `--`, never `0`, when
  there is no reading (R45), and an `[off-speed]` tag when the gate excludes a
  frame.

#### Fixed
- **Each monitor session stored the full waveform of a tachometer channel.**
  `_write_channel_group` takes `role=` and sets it to `'vibration'` by
  default. `DataCollector.save_data` gave it, and `MonitorWriterThread` did
  not, at either of its two call sites. That is ~427x the stored size per
  frame (25600 samples against 60 edge times, measured), on the one code path
  that runs unattended for hours. It also lost the rpm, quality and edge times
  of each frame. Thus the rule "a tachometer channel stores edge times, not
  the waveform" held in measurement files only. Now the writer gets the role
  from the sample itself through `collector.role_of_sample`.
  `monitor/controller.py` already used this test for the pre-trigger overall.
- **`_apply_overrides` was dead code.** No code called it: `run()` had its own
  copy of the maxfreq/binsize overrides and handled `--channels` separately,
  by a change to the `enabled` flags in the device file. It was unreachable
  from the Rev80 rebrand (`62dd2c2`). Now `run()` calls it, and `--channels`
  agrees with the roles. If `--channels` omits the tachometer, headless obeys,
  because it is an explicit instruction. But it tells the operator, because
  otherwise the session records `rpm=NaN` on each capture, the speed gate
  fails closed, and each frame is excluded from trend and alarm with no
  reason given.
- **`--channels` does not write `enabled: false` on a tachometer channel.**
  The role owns that flag: `channel_role_state` sets a claimed channel on,
  because `tach_channels` filters by `enabled_channels`. Thus the stored flag
  was one that each loader ignores. The exclusion for one run belongs in
  `_apply_overrides`, and it is there now.

#### Notes for the next person
- **The premise of the R44 survey was correct, and three of its facts were
  wrong.** It read `if sample.tach is not None: continue` in
  `monitor/controller.py` as "the monitor stores a tach as edge times". That
  branch only keeps the tach out of the pre-trigger overall. All three
  defects survived because a guard was read as evidence of a feature.
- **Verified end to end offline.** This was not possible before
  `_simulate_tach_sources`. `rev80-headless --device sim`, with a device file
  that has a tachometer channel, reads 3600 RPM on a 60 Hz simulated shaft.
  For that channel it writes `edge_times`/`pulse_widths` and no `data`. It
  records `rpm`/`speed_ok` on each capture, and stores the roles in
  `/metadata/channels`.

### feature/tachometer — configurable pulses/rev, gated on revolutions (2026-09-18)

`pulses_per_rev` becomes a control for the user. The minimum-data gate that
it depends on changes from a fixed edge count to whole shaft revolutions.

One pulse per revolution is still the default and the recommended
configuration, for the same reason as before. The change is this: an operator
cannot remove a keyphasor or an encoder that is already installed on a
machine. A refusal to divide by its pulse count is a refusal of the machine.

#### Changed
- **`MIN_EDGES = 3` → `MIN_REVS = 2.0` plus `min_edges_for(ppr)`.** The two
  agree exactly at 1 ppr (three edges, two intervals, two whole turns), and
  at no other value. Three edges of a 60-line encoder are 0.033 of a
  revolution. `test_three_edges_is_two_whole_revolutions_at_one_ppr` pins the
  equivalence.
- **A block with less than `MIN_REVS` revolutions reports no rate.** Measured
  through the real `tach_result`: a 6 ppr block with 1.5 revolutions has 10
  rising edges, three times the old gate, and passed it. It returned
  `quality='ok'` and 1800.0 RPM, calculated from a fraction of a turn. There,
  division error and once-per-rev modulation have not cancelled yet (0.580%
  mean / 1.898% worst at 0.05 rev, against 0.091% from one full turn).
  Revert-checked: with the fixed gate restored,
  `test_high_ppr_block_under_min_revs_reports_no_reading` fails with
  `rpm=1799.9999999999998` where it expects `None`.
- **The quality string stays `'too_few_edges'`**, although the limit is now in
  revolutions. The test still counts edges, and each stored HDF5 tach group
  contains the string. A new name would make old files unreadable for a
  better word.
- **`TachSettings.from_dict` does not warn on ppr != 1.** It is a supported
  setting with its own control. The warning now fires on a real fault: a
  zero, negative or fractional ppr. That is a corrupt file, not a
  configuration, and its fallback to 1 changes the reported speed.

#### Added
- **Pulses/rev in the Tachometer tab.** Its tooltip gives the reason why one
  pulse per revolution is the default and the recommended configuration.
- **`slowest_rpm_for(block_s, ppr)`.** It replaces an inline
  `MIN_EDGES * 60 / t_block` in `gui.py`. It carries the binsize table that
  was loose in the module docstring. The docstring table now comes from the
  function, and a test asserts that they agree.
- **`MIN_SAMPLES_PER_PULSE = 70`, and a live caution in the tab** when the
  configured ppr makes the pulse rate higher than edge interpolation can
  resolve (~0.8% error below it, measured; 6000 RPM at 6 ppr, 600 at 60). It
  is a caution, not a gate: a degraded reading is still a reading.
  - Correction (2026-09-30): 6000 RPM and 600 RPM are correct at a raw rate of
    41666.5 Hz. At 25600 Hz, 70 samples per pulse gives approximately
    3657 RPM at 6 ppr and 366 RPM at 60 ppr. These values are calculated, not
    measured at 25600 Hz. The caution uses the achieved rate of the stream.

#### Fixed
- **The x-axis of the tach preview plot used the shaft period in place of the
  pulse period.** At 1 ppr they are the same number, so the defect was not
  visible. At 6 ppr the window was six times too wide, and the trace became a
  stripe.

#### Notes for the next person
- **Verified electrically** on a 4424A (AWG loopback, channel A), 27 hardware
  tests pass:
  - **The ppr divides the hardware rate exactly once**, at 1, 2 and 6
    pulses/rev against a 60 Hz square wave: 3600, 1800 and 600 RPM, within
    the published ±0.2% of reading.
  - **The gate holds back a reading on real edges.** 5 Hz in a 1 s block is
    ~5 rising edges: 300 RPM at 1 ppr. At 6 ppr it is 0.8 of a revolution.
    Before this change it returned 50 RPM with `quality='ok'`. Now it returns
    `None`.
- **A finer encoder does not read a slower shaft, and the UI must continue to
  say so.** The gate is two revolutions in both cases. A higher ppr recovers
  only one pulse period of phase margin: a whole revolution at 1 ppr, and 1/60
  of one at 60. At a 1 s block the floor goes from 180 → 121 RPM, a third,
  not sixtyfold. To read a slower shaft, use a longer block.
- **`MIN_REVS = 2.0`, not the 1.0 that the error table alone supports.** The
  statistical floor is stricter at 1 ppr, where one revolution is a single
  interval with no spread. 2.0 also makes each half-block span one
  revolution, so `_MIN_EDGES_FOR_DRIFT` needs no companion in revolutions. At
  1.0, a steady shaft with a load zone reads as 'unsteady'.
- **Replay uses the same gate, and that is intentional.** A file captured at
  1 ppr and read again as a 60-line encoder now holds back the rate. It does
  not divide 0.97 of a revolution by 60 and report 29 RPM for a 1762 RPM
  shaft.

## [0.1.3] - 2026-09-17

Tag v0.1.2 was not released: its build failed on the Windows runner. 0.1.3
contains the same content and the CI fix that installs PicoSDK on the Windows
runner (`951ff47`).

### fix/stability-cluster (2026-08-30, merged 2026-09-11)

This branch fixes the four audit findings about whether the app *stays up*,
not whether it measures correctly. Two are critical:
[S-01](audit-202608.md#s-01) and [S-02](audit-202608.md#s-02). The other two
decide whether a crash leaves evidence to read: [H-07](audit-202608.md#h-07)
and [H-03](audit-202608.md#h-03). The branch was written against develop at
2026-08-30 and merged unchanged after the tachometer and raw-rate work. Each
defect below was still present at the merge, and the merge had no conflicts.
**927 unit tests and all 23 hardware tests pass on the merged result**
(4424A, AWG loopback).

The order is intentional: evidence first. Without it, if the app still
stopped after the fixes to [S-01](audit-202608.md#s-01) and
[S-02](audit-202608.md#s-02), there would still be nothing to
read.

#### Added
- **`logger.install_excepthooks()`** (idempotent). It replaces the bare
  `sys.excepthook = ...` line in both front ends. It covers three crash
  routes. Before this change, each route left a different amount of nothing.
  - **`threading.excepthook`.** `sys.excepthook` covers only the main thread,
    and most of the work runs on other threads: the PicoScope poll thread,
    the simulation generator, the monitor writer, the autoconnect and
    reprocess workers. Their deaths went to stderr, which goes nowhere when a
    desktop entry starts the app. Now they go to the rotating log. The entry
    names the thread and notes that anything that waits on it will hang, not
    fail. Verified end to end: a worker that raises writes a full traceback to
    `error.log`.
  - **`faulthandler`** → `log/faulthandler.log`. This file is the only
    evidence that survives a SIGSEGV. It tells a driver-level crash
    ([X-05](audit-202608.md#x-05)) from an OOM kill, which leaves nothing at
    all. Verified with a deliberate NULL dereference: the file names the exact
    frame and lists the loaded extension modules. (fix/paths, 2026-09-29,
    moved the file to `~/Documents/Rev80/logs/`.)
  - **A periodic resource line** (`MonitorController`, every 5 minutes during
    a session): RSS, thread count, burst frame retention, writer queue depth.
    SIGKILL cannot be trapped, so the only possible evidence comes before it.
    This line turns an unexplained disappearance into a readable ramp, and
    [S-02](audit-202608.md#s-02) makes exactly that ramp. It never raises: a diagnostic that stops the
    session it diagnoses is worse than no diagnostic.
- **`tests/test_app_lifecycle.py`** (177), **`tests/test_bounded_resources.py`**
  (233), **`tests/test_crash_evidence.py`** (150).

#### Fixed
- **[S-01](audit-202608.md#s-01) (critical): the app could skip shutdown, and
  then the device stayed open.** Two defects combine. Together they explain
  both halves of the reported symptom: *"I came back and the session was
  truncated, and then the scope wouldn't connect until I replugged it."*
  - `GUI.cleanup()` never called `self._monitor.stop()`. The writer is a
    **daemon** thread, so the interpreter stopped it without unwinding,
    possibly inside `h5py.File(…, 'a')`, with captures still in the queue.
    `MonitorController.stop()` already flushed the partial burst and drained
    the writer correctly, but app close never called it. Now `cleanup()`
    stops the monitor **first**, then closes the device, then destroys the DPG
    context. Each step has its own guard. A wedged writer must not prevent
    `ps4000aCloseUnit`, because a device left open makes the next launch fail
    with `PICO_NOT_FOUND`.
  - The loop body of `GUI.run()` had no `try/except`, and `__main__.main()`
    had no `try/finally`. Thus an exception in the render path skipped
    `cleanup()`. Now `main()` wraps `run()` in `try/finally`, and `cleanup()`
    is idempotent, so the guarded exit of the loop is harmless. This also
    makes [X-02](audit-202608.md#x-02) less severe. A shared `.h5` with
    `binsize=0` raises `ZeroDivisionError` in the render path. Before, that
    ended the process and left the device open. Now it is a logged error.
  - Render-loop policy: log once for each exception **type**, continue to
    render, and stop after `MAX_CONSECUTIVE_RENDER_ERRORS` (30) consecutive
    failures. The loop stops with a break, so shutdown still goes *through*
    `cleanup()`. Deduplication is necessary: without it, a persistent fault
    writes a traceback at frame rate and rolls all other diagnostics out of
    the rotating log. That is the failure of
    [S-09](audit-202608.md#s-09). A successful frame clears the count, so
    occasional bad frames in a long run cannot add up to a shutdown. The
    totals for each type are logged once at exit.
  - `cleanup()` reads `_render_errors` through `getattr`. It runs from the
    `finally` of `main()` and must survive a GUI whose construction failed
    part of the way. It is the one method that must not raise, because it
    closes the device.
- **[S-02](audit-202608.md#s-02) (critical): each resource that an
  unattended run can grow now has a limit.** Three defects combine into the
  most probable way for an overnight session to stop, and the way that leaves
  the least evidence. An OOM kill is SIGKILL: no traceback, no `atexit`, no
  log line. The app disappears.
  - **(a) Burst retention had no cap.** It held every frame *and* every
    `ChannelResult` until the single flush. Now `burst_frame_cap()` sets the
    cap from `max_burst_s` and the acquisition period, not from a magic
    number. A floor prevents a zero-length burst when the period is not
    valid. `_burst_frames` and `_burst_all_results` are trimmed **together**,
    because `_flush_burst` indexes them in parallel: a trim of one list only
    puts each overall against the wrong waveform. The cap gives one warning
    when it is reached.
  - **(b) `max_burst_s` had no effect on the path that fires unattended.**
    Only `IntervalGate.enter_burst()` applied it, and only the *manual* path
    calls that. The anomaly path set `_burst_end_mono` directly. Now both
    paths use a shared `capped_burst_end()`. 0 or `None` still means "not
    set", not "zero length". `IntervalGate._burst_start` is now set in
    `__init__`. The retrigger branch reads it, and one refactor could have
    caused an `AttributeError` in the hot path of the monitor.
  - **(c) The writer queue was `queue.Queue()` with no maxsize.** Thus its
    `except queue.Full` branch was dead code, and `enqueue()` always returned
    True. That return value controls the capture counter, so **the UI
    reported captures that were never written to disk.** Now the queue has a
    limit. When it is full, it drops the item and does not block: back-pressure
    there would reach the render loop and stop acquisition behind the disk.
    The drops are counted, logged with the queue depth, and shown in
    `status_snapshot()` as `dropped_captures`. A loss that no one can see is
    the same defect in a new place.
  - **Measured: burst retention costs 2.76x the raw block.** Measured on 4
    channels through the real pipeline at `RAW_SAMPLERATE_HZ` = 25600 (deep
    ndarray bytes that one retained frame and its `ChannelResults` reach):

    | binsize | acq. period | raw block | retained | multiple |
    |---|---|---|---|---|
    | 0.5 Hz | 2.000 s | 1.638 MB | 4.517 MB | 2.76x |
    | 1.0 Hz | 1.000 s | 0.819 MB | 2.259 MB | 2.76x |
    | 2.0 Hz | 0.500 s | 0.410 MB | 1.130 MB | 2.76x |

    Thus growth without a cap is **2.26 MB/s on 4 channels, ~8.1 GB/h,
    independent of F_max and binsize**. Since the raw/display split, stored
    frames are the capture at the raw rate. A low F_max does not give margin
    here, as it did when this defect was first written up (the original note
    gave ~2 GB at an F_max 50 kHz preset that does not exist now). At the
    shipped `max_burst_s` default of 600 s, the cap holds one burst to
    ~1.36 GB. The docstring carries this table.
- **[H-03](audit-202608.md#h-03): a field log could not be tied to a
  build.** `__version__` now comes from `git describe` in a source checkout.
  In an installed or frozen build it comes from the stamped `_version.py`.
  The stamp comes from a pre-commit hook that is **not** installed
  automatically, and it was seen 100 commits stale.
  - Correction: `setuptools_scm` generates `_version.py` at build or install
    time. The pre-commit hook does not stamp it. build/ci — release
    automation (2026-09-17) corrects the same claim in `CLAUDE.md`.

#### Notes for the next person
- All three fixes are revert-checked. Removal of the monitor stop, of the
  render-error deduplication, or of the idempotence of `cleanup()` makes tests
  fail.
- **The first revert-check found a gap.** With the writer queue changed back
  to unbounded, all 15 tests still passed. The helper made its own queue with
  an explicit `maxsize`, and no test used the real `__init__` of
  `MonitorWriterThread`. This is the same type of gap as the power-against-
  amplitude gap in feature/spectral-averaging. Tests that use the real
  constructor were added, and the revert now fails as it must.
- **[H-01](audit-202608.md#h-01) is not addressed.** `_build_anomaly_hook` is
  still copied between `gui.py` and `headless.py`.

---

### feature/tachometer (R43) (2026-09-01)

#### Added
- **`rev80.tach`**: tachometer edge detection and shaft-speed estimation.
  Pure functions and two frozen dataclasses (`TachSettings`, `TachResult`),
  with no dearpygui, h5py or `DataCollector` imports. No code uses it yet:
  this is step 1 of the tachometer feature.
  - `detect_edges()`: a vectorised Schmitt trigger with sub-sample
    interpolation of the crossing instant. The vectorised form is 68x faster
    than the obvious loop (0.090 ms against 6.1 ms on a 1.0 s block), and it
    is also more correct. It requires a real crossing. The loop reports a
    phantom edge at sample 1 each time a block starts inside a pulse.
  - `estimate_rpm()`: **median of intervals**, not first-to-last. Measured at
    1800 RPM over 200 repetitions: one dropped edge costs first-to-last
    62.09 RPM and the median 0.15 RPM. Tolerance of a miscount is more
    important than a tight result under jitter, because jitter shows in
    `interval_spread` and a miscount does not.
  - The quality has classes: `ok` / `no_signal` / `too_few_edges` /
    `inconsistent` / `unsteady`. **`rpm` is `None` when there is no usable
    reading, never `0.0`.** "I cannot see a tach signal" and "the shaft is
    stopped" send an analyst to different places.

- **Channel roles and the speed gate** (`AcquisitionSettings`): step 2, not
  used yet. `channel_roles` (`{ch: 'vibration'|'tachometer'}`) with
  `role_for()`, and the derived `tach_channels` / `vibration_channels`
  partitions that `process_samples` will iterate. An unknown role string
  falls back to `vibration` and does not propagate. Thus a hand-edited YAML
  cannot make a third channel type that each downstream branch then fails to
  handle. The partitions filter by *enabled* channels, so a tach role on a
  disabled input does not make the collector look for a pulse train that no
  one samples.
- **`speed_gate_enabled` / `speed_gate_rpm` / `speed_gate_tolerance_pct`.**
  Off by default: with no tachometer, there is no reference for the gate.
  `speed_gate_rpm = None` means "latch from the first valid frame", and it
  survives the config round trip, for the same reason as
  `band_fmin`/`band_fmax`: a resolved value written back would freeze the
  running speed of one session into the config.
- `role` and a nested `tach` block in `_BUILTIN_CHANNEL_TEMPLATE`, and the
  three `speed_gate_*` keys in `_BUILTIN_ACQ`. Thus each device and
  acquisition YAML written before R43 upgrades through the existing merge,
  with no notice.

- **Hardware close-out on the 4424A**: 14 new self-skipping tests in
  `tests/test_picoscope_hw.py`. All go through the real acquisition path
  (`PicoScopeStream` → `antialias_decimate` → `receive_data` → `tach_result`)
  and do not give synthetic arrays to the detector. **23 hardware tests
  pass.**
  - AWG sweep 300–10200 RPM: each point is within the published ±0.2% of
    reading.
  - The test asserts that the reported rate is 41666.5 Hz and *not*
    `RAW_SAMPLERATE_HZ`. This is the 4.166% trap that is exactly correct in
    CI and wrong on hardware.
  - The AC-coupling failure is reproduced electrically with a 70%-duty
    arbitrary waveform: a fixed threshold returns no reading, and the
    adaptive threshold follows the shaft.
  - Duty cycle is measured against the 50% that the generator gives.
  - A tachometer channel gives no `ChannelResult` on real hardware.
  - Four channels with a tachometer stream for 8 s with zero overflow and
    zero rate-degradation events.
  - One test was wrong and was corrected. A fixed threshold at **50% duty** is
    the one case where fixed and adaptive give the same result. Whether a
    1000 mV level is inside the AC-coupled swing was seen both ways in
    different runs. An assertion on either result would pin a coin toss. Thus
    the assertion now covers only the regime where the difference is real and
    repeatable.
  - **Measured values for the module constants.** The constants carry the
    table that justifies them. Verified on a PicoScope 4424A (serial
    12462/0067) with AWG loopback on channel A:
    - **The reported sample rate is 41666.5 Hz, not `RAW_SAMPLERATE_HZ`
      (40000).** The driver rounds the sample interval to 12 us, so the true
      rate is 83333/2 Hz. An RPM calculated from the constant reads **4.166%
      high on hardware and exactly correct in CI**. That is the worst
      combination for a defect. `tach` takes the rate from the sample, and a
      test pins it.
    - **`MIN_PULSE_AMPLITUDE_MV = 1000.0`.** Front-end noise measured with the
      AWG idle: 0.37 mV RMS at +/-1 V, up to 5.09 mV RMS at +/-20 V; worst
      block span 42.5 mV. The gate is 23.5x above that, and still a factor of
      two below a real logic-level swing. Without it, an adaptive threshold on
      noise only returns ~9100 edges/block: 547752 RPM.
    - **Adaptive thresholding is the default, and the reason is electrical.**
      AC coupling removes the mean, and on a pulse train the mean is the duty
      cycle. On the bench at 30 Hz, a fixed threshold at the correct DC
      midpoint detected nothing above ~55% duty (the AC-coupled signal
      maximum falls to 980 mV at 70% duty, 750 mV at 85%). Adaptive returned
      1801.7 RPM in all ten duty/coupling combinations. The fixed-threshold
      failure gives no error and reads as a stopped machine.
    - **RPM accuracy: +/-0.2% of reading**, 300 to 10200 RPM at 1 pulse/rev
      (worst case 0.164% at 300 RPM, 0.040% at 10200). The earlier simulated
      claim of a fixed +/-0.2 RPM is not true on hardware: the error
      increases with speed.
    - **`SPEED_DRIFT_MAX_PCT = 1.0`**: the speed change in one block above
      which a frame is `unsteady`. Bearing analysis is done at steady state,
      so a smeared spectrum is rejected, not corrected. This replaces an
      order-resampling path. It is the only constant in the module that is
      still set from simulation, not from the bench.

- **Tachometer tab, and selectable rotation-rate units**: step 9.
  - A **Tachometer tab** in the config dialog. It *owns* the tach role:
    channel claim, polarity, threshold mode and level, minimum amplitude,
    reflector size, rate units, a live waveform with the threshold and the
    detected edges, and RPM / quality / duty / span readouts. Tach setup is
    done once for each installation, at commissioning. Thus the diagnostic
    view belongs with the settings: adjust, watch the edges move and confirm
    the rate on one screen. When the dialog closes, only the derived values
    stay. This removes the need to "hide the waveform once it works" by the
    structure, not by a toggle that the operator must manage. (Verified first
    that a dearpygui modal does not block the render loop: 60/60 frames
    advanced with a modal shown.)
  - The waveform is **aligned so that the first detected pulse is at
    t = 0**. A free-running trace jitters by up to a whole period between
    frames. Aligned, successive frames overlay, and the effect of a threshold
    change is clear. The X limits span two periods on each side.
  - The **Channels tab has no role control now.** A claimed channel shows
    read-only in its summary line. Its settings there have no meaning: a pulse
    train has no sensor, engineering unit or amplitude mode. Two screens that
    can both set the role could disagree.
  - **Rotation-rate units**: RPM, Hz, rad/s (ω), deg/s. `rad/s` *is* angular
    frequency, so it is one option with both names, not two. The unit shows
    wherever a rate shows: 30 is a plausible RPM, Hz and rad/s, and they
    differ by factors of 60 and 6.28. It is a **display preference only**.
    `TachResult` and each stored file stay in RPM, because a number whose
    meaning depends on a setting is the class of defect that this codebase
    finds again and again.
  - The slowest shaft that can be measured at the current bin size shows as
    **information, not validation**. An operator must be able to configure
    the tach on a machine that is not running, with a best estimate.

- **1× shaft-rate marker and level**: the first use of shaft speed in the
  display, and intentionally the simplest: a vertical line on the spectrum at
  1×, and the level beside it on each channel result card, above the peaks
  table. No resampling, no interpolation, no second axis type.
  - The frequency of a line is diagnostic only relative to 1×: unbalance is
    on it, misalignment on 2×, and a bearing tone typically *between* orders.
  - `ChannelResult.one_x_hz` / `.one_x_amplitude`. 1× is rarely at a bin
    centre, so the level is the **larger of the two bins on each side of
    it**. This recovers most of what a strict nearest-bin reading loses to
    the offset, and agrees with how peaks are reported.
  - Both are **hidden, not zeroed**, when there is no tachometer reading. The
    amplitude is `None` when 1× is outside the displayed band: F_max can be
    below the shaft rate on a fast machine, and the edge bin would be a wrong
    number, not a missing one.

- **Duty cycle and pulse widths** on `TachResult`, stored in v5.
  `detect_edges` found only the active edge, so it did not capture pulse
  width, and thus not duty. Now `detect_pulses()` returns both edges from the
  same Schmitt state, so the two cannot disagree about where the signal was
  high. `pulse_widths()` pairs them.
  - A pulse across either block boundary is **dropped, not truncated**. Its
    remainder depends on where the block started, so it would bias duty by an
    amount that has no relation to the reflector.
  - Duty is measured against the *pulse* period, not the shaft period: with
    more than one pulse per turn, a reflector covers a fraction of the
    interval between pulses.
  - With `falling` polarity it measures the notch, which is what the key of a
    keyphasor covers.
  - This is necessary for surface velocity (R46). The reflector covers `duty`
    of a revolution, so the circumference is `L/duty` and `v = f·L/duty`: the
    tape also measures the shaft diameter. Added to v5, not to a new file
    version, because the format has not shipped and no real file contains a
    `TachResult` yet.

- **`RmsThresholdHook` default 10% → 50%.** This is not a tachometer change.
  It corrects a shipped default that the speed analysis showed to be wrong.
  For a rigid rotor below its first critical speed, the 1× velocity goes as
  ω³:

  | speed deviation | 1× velocity change |
  |---|---|
  | 0.5% | +1.5% |
  | 1.0% | +3.0% |
  | 2.0% | +6.1% |
  | **3.2%** | **+10.0%** ← the old default |
  | 5.0% | +15.8% |
  | 10.0% | +33.1% |

  A 3.2% speed change alone crossed the threshold. The ~2% no-load-to-full-load
  slip change of a typical induction motor shows as a +6% rise on a machine
  whose condition did not change. On each VFD or load-following machine, the
  detector measured load. At 50%, a broadband RMS rise has a meaning without
  a speed reference. Where a tachometer is fitted, the speed gate is the more
  certain discriminator, and the threshold can be tighter for that
  installation. Where there is none (common, and often not practical to
  retrofit), detection must come from envelope techniques or fixed
  thresholds. Changed in all five places that had it: the hook, the config
  template, both `_build_anomaly_hook` copies and the headless summary. Thus
  `tests/test_anomaly_hook_build.py` still passes.

- **Monitor sessions record shaft speed; `session.h5` `_FILE_VERSION` 5 → 6**:
  step 8. Each interval capture and burst now has `rpm` and `speed_ok`.
  Without them, a monitor trend point cannot be compared with another point
  at a different load. The declared band uses the same argument for the
  overall. It is also necessary for a later order analysis.
  - A **scalar**, not a `{ch: rpm}` map. This instrument supports one
    tachometer on one shaft (more shafts need order ratios and a
    machine-train model, which is a different feature). Thus each result in a
    frame has the same reading. NaN means no reading, never 0.0.
  - `MonitorController._compute_pretrigger_overalls()` now **skips
    tachometer channels**. It reads `overall_ampl_by_integration_order`,
    which is never set on a channel that `process_sample` does not process.
    Thus a tachometer gave a literal `0.0`, and `load_monitor_session()` then
    made a trend line at zero for it.

- **`rev80-headless` refuses tachometer channels**: step 7. Tachometry is out
  of scope there (tracked as R44), but "out of scope" must mean "does not do
  it", not "does it wrong". Headless reads the same `devices/*.yaml` that the
  GUI writes. Without the refusal, a channel that the operator configured as
  a tachometer would be enabled, high-passed, given an overall, trended and
  given to the anomaly hooks as vibration. Measured on a 5% duty pulse train
  at 1800 RPM through the real `process_sample`: overall 1514.9 mV, crest
  5.00, **kurtosis 15.94** and 63 spectral peaks. An analyst who reads that
  unattended session concludes that a bearing is badly damaged. The value
  also drifts with no cause on the machine: a tach LED that ages from 5.0 V
  to 4.5 V moves the overall of that channel by exactly −10%, the shipped
  `RmsThresholdHook` threshold, on three consecutive frames. The refusal logs
  at INFO and is not silent. The per-channel config load moved out of `run()`
  into `_apply_channel_config()`.
  - Superseded by feature/tachometer — headless runs a tachometer (R44)
    (2026-09-21).

- **Speed gate**: step 6. A frame captured outside a declared shaft-speed
  window is still measured, displayed and stored. It is excluded from trend,
  baseline adaptation and alarm evaluation, because its amplitude is
  *correct* but not comparable. For a rigid rotor below its first critical
  speed, the 1× velocity goes as ω³, so a **3.2% speed change alone moves the
  overall by 10%**: the shipped `RmsThresholdHook` default. On each VFD or
  load-following machine, the anomaly detector measured load, not condition.
  - `ChannelResult.rpm` / `.speed_ok`. `speed_ok` is `True` by default, so no
    existing construction site, fixture or reconstructed result changes.
  - `DataCollector.speed_ok()` is the single place that evaluates the gate,
    and `monitor/anomaly.valid_results()` the single place that applies it.
    That function already existed to answer this question, and each hook and
    both baseline-adaptation paths already call it.
  - **Fails closed** on a missing reading. If the tach stops in a session
    (cable pulled, tape off, LED aged), "no speed reading" treated as "speed
    is correct" would make an unattended monitor alarm on load changes that
    it cannot see. That is the false-alarm mechanism that the gate exists to
    remove.
  - `speed_gate_rpm = None` latches the reference from the first frame that
    has a reading. A frame with no reading cannot latch.
  - **`_build_anomaly_hook` is not changed in either copy**, and
    `tests/test_anomaly_hook_build.py` passes with no change. That shows that
    the right place was chosen: the gate as a hook parameter would need a
    change to both copies, which is what [H-01](audit-202608.md#h-01) exists
    to prevent.

- **Tachometer persistence; measurement file `_FILE_VERSION` 4 → 5**: step 5.
  - A tachometer channel stores **`edge_times`, not a `data` waveform**: ~30
    float64 per second against 41666, a factor of ~1400. This is most
    important in long unattended sessions, where a tachometer channel would
    otherwise be most of the file. The cost is that the signal cannot be
    thresholded again after capture. What stays is all that makes RPM a
    *view* on stored data: `pulses_per_rev` is a divisor on the intervals
    after capture, and a shaft-angle vector, if necessary, is an
    interpolation of the same edge times. Readers must branch on the presence
    of `data`, not assume it.
    - Correction: 41666 is the raw rate of that time. At the 25600 Hz raw
      rate the factor is approximately 850.
  - `/metadata/channels/{ch}` gets `role` and the `tach_*` calibration that
    made the stored reading. `/frames/{i}/{ch}` gets `rpm`, `quality`,
    `n_edges`, `interval_spread` and `speed_drift_pct` as a cross-check.
    `/tach_trend/{ch}` holds the RPM history.
  - **A newer file version now gives a warning, not a wrong reading.** An
    older build that reads a v5 file takes its most permissive branch and
    restores a tachometer as a usual vibration channel. It then calculates a
    false overall on a square wave and trends it. The guard is useful also
    without the tachometer.
  - The frame cache stays homogeneous. Each entry is still a `VibeSample`,
    with an empty waveform and a populated `TachResult`, because many
    consumers index it.
  - `reprocess_session_trend()` skips tachometer channels. Otherwise they get
    a false amplitude trend at zero (`overall_ampl_by_integration_order` is
    never set on a channel that `process_sample` does not process). This
    moved here from step 4, because it needs the role from the file metadata
    to know what to skip.

- **Tachometer channels connected to `DataCollector`**: step 4.
  - `receive_data()` branches on the role. A tachometer channel **skips the
    high-pass** and is edge-detected in its place. Measured: the filter
    overshoot on each falling edge crosses the threshold again, which turns
    31 edges into 108 at 15% duty, and an 1800 RPM shaft reads 6270.
    Detection runs here for the same reason as the filter: this is the one
    place where a block arrives exactly once and in stream order.
  - `tach_settings` / `set_tach_settings()` / `tach_settings_for()`, keyed
    like `scope_sensors`. `tach_for()` calculates again when the calibration
    changed after capture, so RPM stays a *view* on stored data, not a value
    fixed at capture.
  - `current_rpm()`: the shaft speed of the displayed frame, or `None`. Never
    `0.0`.
  - `process_samples()` now iterates `config.vibration_channels`. A
    tachometer gives no `ChannelResult`, so kurtosis 15.94 for a square wave
    does not show on a channel card.
  - `tach_trend` / `get_rpm_trend()`, separate from `trend`, because shaft
    speed must never go through `UNIT_TO_SI`, `amplitude_scale` or
    `integration_steps`. For the same reason, crest factor is beside `orders`
    and not a column of it. `get_trend_for_display()` and
    `init_trend_channels()` are partitioned to match.
  - `eu_scaled_raw()` **raises** on a tachometer channel. With no
    `ScopeSensor` it would divide by a sensitivity of 1.0 and return raw mV
    with an engineering-unit label. That is the classic field error, and it
    looks correct on screen.
  - `reset_channel_config()` prunes `channel_roles` and `tach_settings`. Thus
    a change from a 4-channel scope to a 2-channel scope cannot leave the
    tach role of channel 3 on an index that the new device uses for
    vibration.
  - `VibeSample.tach` / `_tach_config_key`, cached like `psd_mv` and
    `filtered_mv`.

- **Simulated tachometer signals and per-channel simulation sources**: step
  3. Before this change, `SimulatedSensor._sample()` copied one generated
  signal to each enabled channel. Thus a simulated tachometer was not
  possible: the tach input had the same accelerometer waveform as the
  vibration input, and the tachometer had no offline CI.
  - `SimulatedSensor.channel_sources`: `{ch: (fn, *args)}` overrides for each
    channel. When it is empty, the output is **byte-identical** to the copied
    signal, so no existing test or caller changes.
  - `GenerateTachPulse()`: a pulse train in mV with a **finite rise** (1.5
    samples by default). An ideal rectangle is a degenerate stimulus: no
    sample is in the hysteresis band of the detector, and sub-sample
    interpolation has nothing to interpolate. CI would then test a regime that
    the instrument never sees. Real edges have approximately one
    intermediate sample, measured on a 4424A.
  - `GenerateMachineWithTach()`: a vibration channel and a tach channel from
    the *same* shaft. They share `running_rate` and an explicit shaft phase,
    so the tach edge marks the angular position where the load zone is
    maximum. This coherence is the purpose. A tach that is not locked to the
    shaft rate of the vibration cannot validate anything: a broken tachometer
    and a correct one both return a plausible number against an unrelated
    signal. This module makes the same argument about pure cosines and
    envelope analysis. A test asserts that the measured RPM agrees with the
    1× peak in the spectrum of the vibration channel.
  - `machine_with_tach_sources()`: the streaming counterpart, so the two
    rates cannot be set independently and drift apart.
  - `GenerateBearingVibration()` gets an optional `shaft_phase`. When it is
    not given, it comes from the same rng as before, so the draw order and
    the output do not change.

#### Changed
- **Tachometer support is specified around 1 pulse/rev.** One pulse per
  revolution is the default and the recommended configuration. The UI will
  offer no pulses/rev control. One reflective tape or one keyway is the
  common installation, and it is also the accurate one. At 1 ppr each
  interval is exactly one shaft revolution, so encoder division error and
  once-per-rev speed modulation cancel *inside each interval, by
  construction*. Above 1 ppr they cancel only after a whole revolution, and
  more pulses give nothing before that. Measured with a 60-line encoder with
  ±0.05° division error and 0.5% once-per-rev modulation, over 40 random
  start phases: 0.580% error at 0.05 rev, 0.344% at 0.25 rev, **0.091% at
  1.00 rev and flat after that, to 20 rev**. The same test at 1 ppr gives
  **0.0013%** from three edges: 70× better than 60 ppr gets at any window
  length.
  - `pulses_per_rev` and the divide stay, so the capability can come back. A
    value other than 1 is **used, with a warning, and never clamped without a
    notice**. A clamp would report an integer multiple of the true speed with
    nothing on screen to show it.
  - Thus there is **no minimum-revolutions constant and no new user
    setting**: `MIN_EDGES = 3` already is two whole revolutions at 1 ppr.
  - Rejected: to infer ppr from multi-modal pulse periods. `interval_spread`
    already flags unequally spaced reflectors as `inconsistent` when the two
    gaps differ by more than ~90° of shaft rotation. A pair that is almost
    evenly spaced reads an exact integer multiple, which is the most obvious
    error for a technician who knows the machine.
  - Correction: feature/tachometer — configurable pulses/rev (2026-09-18)
    adds a pulses/rev control and replaces `MIN_EDGES` with `MIN_REVS` and
    `min_edges_for(ppr)`.
- The published figures for the slowest shaft that can be measured are **3×
  higher than first stated**. Three rising edges at any start phase need a
  block that spans three periods, so the floor is `180/T_block` RPM: 45 RPM
  at 0.25 Hz bins, 180 at 1 Hz, and **1800 at 10 Hz**. At 10 Hz no shaft
  below 1800 RPM can be read. That is the one case where a correct setup
  returns no reading, and the GUI must say so.

#### Fixed
- **`AcquisitionSettings.copy()` copies `channel_roles`.** The per-channel
  dicts are in the `channels` config section. Thus, unlike the scalars, they
  are outside the `to_dict`/`from_dict` round trip, and an explicit tuple
  lists them by name. A sixth dict added without an edit of that tuple is
  **[H-08](audit-202608.md#h-08) again**. For roles, the result is a copy in
  which each tachometer is vibration again, with no notice. The pipeline then
  high-passes a pulse train and reports kurtosis ~16 on it. A revert-checked
  test pins it.

#### Notes for the next person
- Sub-sample interpolation works only on a **band-limited** edge. On an ideal
  rectangle both samples on each side of the edge are at the rails, and the
  estimator becomes nearest-sample quantisation. The mandatory anti-alias
  filter upstream band-limits real edges. That is why bench accuracy is
  better than the accuracy on a synthetic square wave, and why accuracy tests
  must send their signals through `antialias_decimate`.
- All 44 tests in `tests/test_tach.py` were revert-checked against 11
  invariants. The first pass found **5 of them pinned by nothing**: the
  min-span gate inside `detect_edges`, hysteresis, the Schmitt low-state
  requirement, sub-sample interpolation and polarity inversion. Each could be
  deleted and the suite stayed green. All five were tests that passed for the
  wrong reason, and one shared assumption caused them. An *ideal rectangle*
  changes state in zero time, so no sample is in the hysteresis band and
  interpolation has nothing to interpolate. Also, the rate does not depend on
  polarity, so a comparison of rates shows nothing about which end of the
  pulse is timed. The fix: a band-limited pulse generator
  (`make_ramped_pulses`), and assertions on edge *instants*, not only on
  rates. All 11 invariants are now pinned.

### hotfix/RAW_SAMPLERATE (2026-09-09)

#### Fixed
- **The Acquisition dialog showed a sample rate that the instrument never
  produced.** `RAW_SAMPLERATE_HZ` was made lower to decrease GUI lag with 4
  channels streaming. This showed a latent defect in the display-rate
  derivation. `samplerate` was `nextpow2(2.56 * maxfreq)`: it rounded *up* to
  a power of two, so it overstated the rate by up to 2x. The defect was not
  visible while `raw_samplerate` was large enough to absorb the overshoot.
  Measured at the 10 kHz preset against 25.6 kHz of acquisition:

  | | dialog showed | pipeline delivered |
  |---|---|---|
  | sample rate | 32.8 kS/s | 25.6 kS/s |
  | lines | 10001 | computed from a rate that did not exist |

  It gave no error, because `decimate_to_rate` returns the block unchanged
  when `target_rate >= raw_rate`. The result was a readout that disagreed
  with the data, and `n_fft_bins`/`binsize_actual` derived from a rate that
  did not exist.

  `samplerate` is now **exactly** `2.56 * maxfreq`. This cannot overshoot:
  the `maxfreq` setter already clamps to `raw_samplerate/2/1.28`, which *is*
  the condition `2.56 * maxfreq <= raw_samplerate`. A power-of-two *rate*
  gave nothing: the FFT length is `blocksize`, not the rate. Each preset rate
  is now 5-smooth and divides `raw_samplerate` exactly, so raw→display
  decimation is an exact integer factor (50/20/10/5/2/1) at all six presets.

- **`blocksize` is now `ceil(samplerate / binsize)`**, not `nextpow2(...)`.
  With a power-of-two rate that divided exactly, a frame was really
  `1/binsize` seconds. With an exact 2.56x rate, `nextpow2` would make frames
  up to 2x longer than the dialog states. Measured worst-case frame-length
  overshoot across the 54 preset combinations: **56.2% → 17.2%**, with 24
  combinations now exact. The delivered bin is still never coarser than the
  requested one. `blocksize` is not a power of two now, and that has no
  effect: it is a Welch segment length, pocketfft is efficient for each
  5-smooth length, and each preset combination is one.
  - Correction (2026-09-30): at the current presets, 10 of the 54
    combinations give a `blocksize` that is not 5-smooth, and 43 combinations
    are exact. Calculated from `MAXFREQ_PRESETS` and `BINSIZE_PRESETS`.

- **`RAW_SAMPLERATE_HZ` = 25600** (2.56 × the 10 kHz top preset). It replaces
  a value of `10_000` that was set for a short time and did not include the
  2.56 factor. At 10 kHz raw, the `maxfreq` setter clamped to 3906 Hz with no
  notice: the 5 kHz and 10 kHz presets were unreachable, and the envelope
  bandwidth was half. 25600 Hz gives osr=3 (76.8 kHz/channel at the ADC),
  which asks *less* of the ADC than the 40000 Hz configuration that was
  measured clean on a 4424A. **Validated on hardware 2026-09-09** (4424A s/n
  12462/0067): `effective_osr=3`, actual raw ADC rate 76923 Hz/channel
  against 76800 requested (+0.16%, the discrete timebase of the driver),
  **0 overflow and 0 rate-degradation transitions** over 45 s at 3 and at 4
  simultaneous channels. All 9 AWG-loopback hardware tests pass. The GUI-load
  problem that caused the lower rate is a separate problem and is still open.

- **`tests/test_picoscope_hw.py` asserted a sample rate that the stream never
  requested.** `STREAM_SAMPLERATE = 50_000` was older than the raw/display
  split. `PicoScopeStream` acquires at `raw_samplerate`, so the hardware never
  got a 50 kHz request. The assertion allowed 40% deviation. That is wide
  enough to hide a rate that is wrong by a factor of 1.56, and it passed only
  while `raw_samplerate` was 40 kHz, 20% away. At 25600 Hz it failed at
  48.7%. Also, `test_stream_start_stop_cycle` calculated its sleep as
  `STREAM_BLOCKSIZE / STREAM_SAMPLERATE` = 1.0 s against a real
  `acquisition_period` of 1.95 s. Thus no callback could arrive, and the test
  reported a streaming failure that it caused itself. Both now come from the
  config (`raw_samplerate`, `acquisition_period`), and the rate tolerance is
  5%, against a measured quantisation error of 0.16%.

#### Changed
- `tests/test_acquisition_settings.py`: `test_samplerate_is_power_of_two` and
  `test_blocksize_is_power_of_two` pinned the wrong behaviour. They are
  replaced with the important invariants: samplerate is exactly 2.56x
  maxfreq; the display rate is never more than the acquisition rate; the
  decimation ratio is an exact integer; no preset is clamped; the delivered
  bin is never coarser than requested; and a frame is never more than one
  sample longer than `1/binsize`.
- `tests/test_declared_band.py`: the out-of-band tone was 1500 Hz against
  `F_max`=1000. It was in the guard band only because `nextpow2` increased
  fs/2 to 2048. At the correct fs/2 = 1280 it is above Nyquist, where the
  decimation filter removes it fully (−240 dB measured). Thus the test would
  pass with no effect from the band mask. The tone is now at 1100 Hz, which is
  measured to survive decimation at −0.7 dB, so only the band mask can
  exclude it. Revert-checked: with the `band_fmax_resolved` clamp removed, it
  fails by +123.6%.

- **Tooling defects after the repository moved (no effect on measurement).**
  The checkout moved three times (`~/CODE/reveng/vibegui` →
  `~/Documents/reveng/code/vibegui` → `~/Documents/reveng/vibration/rev80`).
  Each move left absolute-path state that fails *with no error*:
  - `core.hooksPath` still pointed at `.git/hooks` of the previous clone, a
    directory that did not exist. In that state git runs no hooks. Thus the
    blocking `ruff check src/ tests/` gate and the `doc/*.pdf` render had not
    run since the move. Now it is set to the relative `.githooks`, which
    survives each future move. The stale `gitflow.path.hooks` (which pointed
    two moves back, at `~/PurpleDocs/...`) was unset.
  - The `.pth` of the editable install pointed at the removed
    `.../code/vibegui/src`. Thus `import rev80` raised `ModuleNotFoundError`,
    and the `rev80` / `rev80-headless` console scripts and the desktop
    launcher did not work. The editable install was done again. A stale
    `vibechecker` distribution from before the rename (a separate dist that
    `pip install -e .` does not touch) was uninstalled at the same time.

  No one saw this, because **`pytest` is immune to it**: `pyproject.toml`
  sets `pythonpath = ["src"]`, resolved from rootdir. Thus all 737 tests
  collected and passed against the source tree while each installed entry
  point was broken. Green CI does not prove that the app starts.

- `.python-version`, `.vscode/` and `.ruff_cache/` are now gitignored (and
  `.python-version` is untracked), so each checkout owns its own development
  environment. As a result, a moved checkout does not select the pyenv
  environment automatically. Select the environment *before*
  `pip install -e .`, or the editable install goes into the wrong
  interpreter. CONTRIBUTING.md, in the new **Moving the checkout** section,
  records this and the hooks fix above.
- Two stale vendor datasheet PDFs were removed from `doc/`.

### experimental/profiling (2026-09-11)

This branch is about GUI response. After the mandatory Kaiser anti-alias
filter and oversampled streaming were added, the GUI stuttered on each
processing call on a 4824A. It was acceptable at 3 enabled channels and
became worse up to 8. The bottleneck was not known: USB transfer, DSP and
dearpygui rendering were all possible. Thus this branch first adds per-stage
timing, and then fixes what the measurements show.

**It was not a throughput problem, and that is why it was difficult to
find.** Processing never fell behind acquisition, and the frame queue never
grew. It could not: the 32-frame ring cache is *designed* to skip to the
latest frame, so a main-thread overrun shows as latency, never as a backlog.
A look at the queue depth found nothing, because there was nothing to find.

There were three independent causes. Each is **linear in the number of
enabled channels**, so the symptom alone could not separate them.

#### Added
- **`src/rev80/_profile.py`**: per-stage timing for the whole pipeline, from
  the driver callback to `render_dearpygui_frame()`. Thirteen named stages,
  grouped by *thread*, because the thread that gets a cost is the whole
  question. Main-thread time blocks the mouse. Hardware-thread time takes the
  GIL. The two need different fixes. `gui.render` beside `proc.total` makes
  that decision clear. The cost is almost zero when it is off: measured
  **442 ns/call disabled** (3015 ns enabled), net of the loop baseline. That
  is 0.27 ms per wall-second at the busiest call site, so the instrumentation
  ships permanently and is not compiled out. It is bounded by construction (a
  fixed-length ring for each stage): a diagnostic that causes the next
  [S-02](audit-202608.md#s-02) is worse than no diagnostic.
- **`rev80 --profile`** (and `REV80_PROFILE=1`, which a desktop launcher can
  set when it cannot give a flag): logs the stage table at exit. It runs
  inside the guarded order of `cleanup()`, where it cannot prevent
  `ps4000aCloseUnit`.
- **`scripts/profile-pipeline`**: a sweep over channel counts that prints one
  stage table for each count, simulated or `--hardware`. Its `--raw-rate`
  **defaults to the clock that hardware really gives, not the nominal one**,
  because the main defect below is not visible at exactly 25600 Hz.
- **`tests/test_adc_conversion.py`** (6 cases x 14 ranges),
  **`tests/test_display_rate.py`** (38), and a bit-exactness suite for
  `_running_median` in `tests/test_peak_selection.py` (110).

#### Fixed
- **Cause 1: `decimate_to_rate` designed a 512,821-tap FIR on each call, on
  real hardware only.** `resample_poly` makes a `2*10*max(up,down)+1` tap
  filter, so the denominator of the ratio multiplies the cost directly. The
  ratio had a nominal bound, but `limit_denominator` was applied to each rate
  *separately, before the division*. Both are integers there, so each reduced
  to denominator 1, and the ratio had no bound.

  The defect was not visible offline, because `SimulatedSensor` reports
  exactly 25600 Hz, which reduces against each display rate to a small
  integer factor. The driver did not. The streaming interval was requested in
  whole **microseconds**, and `int(1e6 / 76800)` truncated 13.02 to 13. That
  gave 76923 Hz and a reported 25641. 5120 and 25641 are coprime. Measured,
  12800-sample block:

  | raw rate | up / down | taps | ms/call | out length |
  |---|---|---|---|---|
  | 25600.00 (simulated) | 1 / 5 | 101 | **0.64** | 2560 |
  | 25641.00 (hardware) | 5120 / 25641 | **512 821** | **73.62** | **2556** |

  At 8 channels that is 589 ms of main-thread work against a 500 ms frame.
  **Green CI was not evidence here either**: the whole test suite passed at
  0.64 ms while the instrument stalled at 73.6.

  It was also a measurement defect, not only a speed defect. 2556 is less
  than `nperseg`, which started the Welch fallback with no notice. Thus the
  delivered bin width was not the one that the Spectrum tab stated.

  The fix has two independent halves. Each is sufficient alone:
  - **The streaming interval is now requested in nanoseconds, snapped to the
    clock grid of the device.** This is also a fix for frequency-axis
    accuracy: each displayed line was 0.16% high, so a 1000 Hz line read
    1001.6 Hz.

    The simple version of this change (`round(1e9/76800)` = 13021 ns) was
    measured on the 4824A, and it did *not* do what the arithmetic said. A
    probe of the driver with a range of intervals, with a readback of the
    interval that it used, shows that the reachable points are **12.5 ns
    apart** (an 80 MHz timebase). The driver **floors** to the grid, it does
    not round, so 13021 lands one whole grid point high:

    | requested ns | returned ns | rate/ch Hz | /osr Hz | ppm vs 25600 |
    |---|---|---|---|---|
    | 13000 (and 13012) | 13000 | 76923.08 | 25641.03 | **+1603** |
    | 13021 (naive round) | 13012 | 76852.14 | 25617.38 | **+679** |
    | 13025 (grid-snapped) | 13025 | 76775.43 | 25591.81 | **-320** |

    8e7/1041 and 8e7/1042 are on each side of 76800, and 1042 is nearer, so
    -320 ppm is the best that this hardware can reach. The fix rounds to the
    nearest grid point and then rounds up to whole ns, so that the floor of
    the driver lands where intended. The result is **5x better than shipped,
    not the 100x that the ns resolution alone suggested.** This is recorded
    because the arithmetic and the hardware disagreed, and the hardware was
    correct.

    Nothing in this depends on the snap. The driver still writes back the
    interval that it used, and everything downstream uses that readback. A
    device with a different timebase floors to its own grid and reports it,
    as before. The snap is only an optimisation.
  - **The ratio bound is applied to the ratio**, through the coarsest
    denominator cap that is within `_RESAMPLE_RATE_TOL`. Each shipped preset
    now reduces to its exact integer factor. An F_max that is not a preset
    costs a few thousand taps, not half a million. Measured worst case under
    the cap: **1.05 ms**. At the real hardware rate: **73.62 ms -> 0.42 ms**,
    with the output length back to the declared 2560.

    The two halves are independent, and each does a different thing: **the
    ratio bound makes it fast** (0.42 ms at either clock), and **the grid
    snap makes it accurate**. Neither replaces the other.

  **The F_max preset for the user does not change and stays a round
  number.** The sub-Hz difference between the requested and the achieved
  display rate is internal. The frequency axis is correct against it, and it
  never shows as an odd number on a control. `highpass_fc` gets the same
  treatment: a declared edge, with the real value below it.

  A fractional raw rate had two more effects, and both were fixed. The
  readback paths for HDF5 and monitor sessions did `int(samplerate)`, which
  truncates 25599.67 to 25599, which is coprime again. Thus **replay would
  take the expensive path that the live display does not take**, against the
  rule that replay shows what the live display showed. Both are `float` now,
  and so is the value that `MonitorWriterThread` writes. The missing-key
  fallback of `receive_data` also read `config.samplerate` (display) for a
  block at the raw rate. It is not reachable now, but it would be wrong if it
  ran. It is now `raw_samplerate`.

- **Cause 2: `picosdk.functions.adc2mV` is a per-sample Python loop, and it
  runs inside the driver callback, which holds the GIL.** It is
  `[(np.int64(x) * vRange) / maxADC.value for x in bufferADC]`, which boxes a
  numpy scalar for each sample. Its cost comes directly from the GUI thread.
  Replaced with a vectorised `_adc_to_mv()`:

  | samples/ch | `adc2mV` | vectorised | speedup |
  |---|---|---|---|
  | 4 096 | 4.22 ms | 0.021 ms | 201x |
  | 19 200 | 19.86 ms | 0.052 ms | 382x |
  | 38 400 | 40.28 ms | 0.112 ms | 361x |

  At ~1.03 us/sample and 76.9 kHz for each channel, that was 0.079
  CPU-seconds per wall-second for each channel: **0.634 s/s at 8 channels**.
  Measured effect on a main loop similar to 60 Hz, p95 tick latency against a
  0.5 ms target:

  | channels | 1 | 3 | 4 | 8 |
  |---|---|---|---|---|
  | `adc2mV` | 1.42 ms | 4.67 ms | 5.75 ms | **5.76 ms** |
  | vectorised | 0.58 ms | 0.59 ms | 0.59 ms | **0.59 ms** |

  The replacement is **bit-identical**, not only close, over each voltage
  range across the full int16 domain, if the order of operations stays:
  `x * vRange / maxADC`, never `x * (vRange / maxADC)`, which rounds
  differently in the last bit. `tests/test_adc_conversion.py` asserts the
  equality *and* that the pre-divided form is not equivalent, so a test backs
  the comment that explains it.

  This also explains an earlier workaround. `RAW_SAMPLERATE_HZ` was made
  lower "to relieve GUI lag while streaming 4 channels" (hotfix/RAW_SAMPLERATE,
  2026-09-09). The lower rate decreased the number of samples through this
  loop. That trade may now be possible to reverse.

- **Cause 3: the peaks table of each channel was destroyed and made again
  on each frame.** `_update_fft_peaks_table` deleted each column and row and
  made them again, once for each vibration channel in each frame, from *both*
  branches of `_update_freq_plot`. Thus it ran also with zero peaks.
  `select_peaks` reports a corpus median of 40 lines, so that was **~164
  widget create/destroy operations for each channel in each frame**, plus a
  full dearpygui table layout pass: ~1300 for each frame at 8 channels,
  approximately 80% of all DPG traffic in a frame.

  Columns and rows are now a persistent pool. The pool creates them on
  demand and after that changes their labels or uses `set_value`. It hides
  surplus rows and does not delete them. A frame with unchanged contents
  sends nothing. Each plot *series* in this file already worked that way;
  this applies the same idea to a table. It repairs itself if the table is
  made again under it, as `_ensure_legends` does.

#### Changed
- **The edge handling of `peaks._running_median` is vectorised.** It was a
  Python loop of `np.median` calls, one for each edge bin, and it was **91% of
  the cost of the function**. The `scipy.ndimage.median_filter` over the
  interior is only 0.047 ms of it, which is the opposite of where one would
  look.

  | | before | after |
  |---|---|---|
  | median_filter (interior) | 0.047 ms | 0.047 ms |
  | edge bins | 1.161 ms | 0.408 ms |
  | `_running_median` total | **1.274 ms** | **0.563 ms** |

  The statistic does not change, and that is the whole constraint. The
  truncated window, and the measured error table that chose it over
  zero-padding, reflection and replication, do not change. A test asserts
  that the new code is **bit-identical** to the loop that it replaces across
  110 length x width combinations. Even widths are included intentionally.
  They are not reachable now, because `local_noise_floor` forces an odd
  window. But the edge window is `[i-half, i+half]` inclusive, which is
  `2*half+1` samples at each parity, and a window sized by `width` would make
  each even case shorter with no notice.
- **The stale-frame watchdog does not start a thread for each frame.**
  `_schedule_status_timeout` cancelled a `threading.Timer` and made a new one
  on each displayed frame, and then changed a dearpygui widget *from that
  timer thread*. Both halves were wrong, the second more than the first: no
  DPG call belongs outside the render thread. It is now a deadline that
  `_poll_new_frames` checks. That function already runs on each tick, with or
  without a frame, which is exactly when the check must run.
- **Envelope analysis runs only when it is on screen.** Its docstring always
  said so, but the code did not do it: `envelope_enabled` is a config flag,
  not a statement about the selected tab. With the tab enabled and the user on
  Spectrum, a `butter` design, a `sosfiltfilt`, a Hilbert transform and (on
  an automatic band) a `suggest_band` convolution ran for each channel in each
  frame for a plot that no one could see: ~2.8 ms for each channel, plus
  1.4-1.9 ms when automatic. The gate tests the *plot*, not the tab: a tab
  that is not selected still renders its own header button and reports
  visible in both cases.
- **`suggest_band` is cached for each channel** and is not calculated again
  on each frame. This is also better behaviour, not only lower cost. The
  docstring of `_on_env_auto_band` already says that the band should "stay put
  across frames instead of drifting each time", and a band that moves on each
  frame makes the axis of the envelope plot unstable. The cache is cleared
  when the band fields are edited, when the Envelope tab is toggled, and by
  the Auto button. Auto means "pick one from the frame on screen now" and must
  not return the answer of an earlier frame.
- Two `configure_item` calls on each frame that sent an unchanged value now
  send only a change: the four `enabled=` flags of the browse buttons (which
  change twice in a session), and the `height=` of the Frame info card, which
  causes a dearpygui relayout each time.

#### Notes for the next person
- **Result after the fixes.** `./scripts/profile-pipeline --hardware
  --channels 1,3,4,8 --seconds 12` on the 4824A (s/n 13290/0013), ms of work
  per wall-second:

  | stage | 1 ch | 3 ch | 4 ch | 8 ch |
  |---|---|---|---|---|
  | `usb.poll` | 57.9 | 73.7 | 83.1 | 128.6 |
  | `usb.adc2mv` | 9.2 | 12.8 | 14.6 | 23.0 |
  | `usb.antialias` | 7.8 | 19.8 | 26.6 | **58.3** |
  | `ingest.receive` | 1.4 | 2.5 | 3.1 | 7.5 |
  | `proc.total` | 13.9 | 30.8 | 40.2 | **84.1** |
  | `proc.decimate` | 2.2 | 5.0 | 6.3 | 13.3 |
  | `proc.psd` | 6.3 | 13.7 | 17.9 | 36.6 |
  | `proc.peaks` | 3.5 | 7.8 | 10.3 | 22.1 |

  Zero overflow and zero rate degradation at each count. `usb.poll`
  *contains* the three stages below it: the app callback runs synchronously
  inside `ps4000aGetStreamingLatestValues`. `proc.total` contains
  `proc.decimate`/`psd`/`peaks`. Thus the stages are nested, not additive;
  the harness says so in its own output.

  `proc.total` at 8 channels is 39.5 ms mean against a 500 ms frame:
  ~8% of the main thread. Before the fixes it was over budget.
- **The next finding of the profiler, recorded but not acted on.** With
  `adc2mV` removed, `usb.antialias` is now the largest single cost on the
  acquisition thread: the mandatory Kaiser FIR that decimates a (38400, 8)
  block on each frame. That is real, necessary work, not a defect, and
  58 ms/s causes no problem now. It is where the next investigation should
  start, if one is necessary. It is visible only because the instrumentation
  now exists.
- **Not done, intentionally:** a streaming rate that adapts to the channel
  count, and a cap on the number of enabled channels. Both were options at
  the start. Both give up measurement capability to work around a Python loop
  and an unreduced fraction, and Causes 1 and 2 remove the reason for either.
  The move of `process_samples()` off the render thread is also not done. It
  would change the `new_frame_event` contract that browse mode,
  `collect_sample`, the monitor and the tests depend on. Cause 1 alone removes
  ~589 ms of the ~610 ms main-thread budget at 8 channels. If a hitch
  remains, it gets its own branch and its own measurements.

### build/ci — release automation (2026-09-17)

A `vX.Y.Z` tag now builds the Windows installer and the Python wheel, and
attaches both to a **draft** GitHub Release. This replaces the manual step
"boot into Windows, pull, run `scripts/build.sh`". The cause was the move
from the self-hosted `catherby` remote to
`github.com/cascadia-turbo-works/rev80`.

Not yet run against a real remote. Read *Rehearsing a release* in `CONTRIBUTING.md`
before you trust a release.

#### Added
- **`.github/workflows/release.yml`**: four jobs on a `v*` tag: a test gate,
  a wheel/sdist build (ubuntu), a driver-less installer build (windows), and
  `gh release create --draft`. The gate prevents a release from a red tree.
  It runs one Python version, because the full matrix already ran on the
  branch.
- **`scripts/build.sh wheel`**: builds the wheel and sdist, which `build.sh`
  never did before. It is the only target that runs outside Windows.
- **`scripts/build.sh … nodlls`**: skips DLL collection. Hosted Windows
  runners have no PicoSDK, and PicoSDK has no reliable unattended install.
  Thus CI installers are **driver-less**: they work, but the user installs
  PicoSDK, and the `.iss` already warns when it is missing. A local
  `./scripts/build.sh` does not change and still bundles the DLLs.
  - Correction: the release workflow of 0.1.3 installs PicoSDK on the Windows
    runner, because the `picosdk` wrapper does not install without it
    (`951ff47`). The build still passes `nodlls`, so the installer is still
    driver-less.
- **`build` added to the `dev` extra.**

#### Fixed
- **`fetch_font.sh` shipped an installer without the font on failure, with
  no error.** It has no `set -e` and returned the status of its last `echo`.
  Thus a failed `curl` or a missing `unzip` exited 0. `build.sh` continued,
  and `rev80.spec` printed its "fonts not found" warning into a log that no
  one reads. Each failure path now exits non-zero with a reason.
- **It also downloaded a font that the repository already tracks.**
  `assets/fonts/CommitMonoNerdFont-Regular.otf` is committed and
  byte-identical to the download (sha256 `4eda301c…`, verified before the
  change). The tracked copy is now the primary source and the download is a
  fallback. Thus the release build does not need the network, or the `unzip`
  of Git Bash on the Windows runner, which is not guaranteed.

#### Changed
- **`ci.yml` triggers on branch pushes only** (`push: branches: ['**']`). A
  bare `push:` also matches tags, so a tag would run the full 4-job matrix in
  addition to `release.yml` and its own gate.
- **`CLAUDE.md` does not say that the pre-commit hook stamps `_version.py`.**
  The hook has not done so since the move to setuptools_scm. The hook had a
  comment that said so, while the document said the opposite. The correct
  operation of the release workflow depends on the real mechanism, so the
  passage now states it.

#### Notes for the next person
- **`fetch-depth: 0` is necessary, and its failure is silent.**
  `setuptools_scm` reads `git describe`. A shallow checkout has no tags,
  falls back to `0.0.0+unknown`, and ships `Rev80Setup-0.0.0+unknown.exe`
  with no failure. Both build jobs assert against that string and do not
  trust the checkout. A dirty tree is the same hazard from the other side: it
  appends `+d<date>`. That is why `_version.py`, `installer/version.iss`,
  `drivers/*.dll` and the fetched font are all gitignored.
- **`python -m build` cannot run from the repository root.** The `build/`
  directory of this repository shadows the `build` PyPI package as an
  implicit namespace package: `import build` succeeds, and `python -m build`
  stops with *No module named `build.__main__`*. Also, `python` is a pyenv
  shim that selects its version from the cwd, so a run from a different
  directory selects a different interpreter. `build.sh wheel` handles both:
  it resolves the interpreter to an absolute path, then runs from a scratch
  cwd with the repository given explicitly.
- **A tag trigger ignores branches.** GitHub Actions has no concept of
  "tagged on main": each `v*` tag builds, on any branch. This is accepted
  intentionally. The old `rc0.x` tags do not match `v*`.
- **The wheel is a release asset, not a PyPI package.** `picosdk` is a
  direct git URL dependency, and PyPI does not accept those.
- **Releases are drafts**, because the exe and the installer are not signed.
- The `--sdist` and `--wheel` invocations are separate intentionally, so that
  the wheel is built from the source tree. The theory was that the
  git-tracked file finder of setuptools_scm would drop the gitignored font.
  Measured: it does not, because `package_data` wins. The separation stays as
  an extra safeguard, and the result is recorded as measured, not as a claim.


## [0.1.0] - 2026-09-01

First tagged release. The sections below were written branch-by-branch during
development and are kept as originally recorded, grouped here under the
release they shipped in.

### feature/raw-stream-retention (2026-08-31)

#### Added
- **Acquisition rate decoupled from the display `F_max`.** Envelope/demodulation
  analysis needs Nyquist headroom into the 2–20 kHz range where bearing housing
  resonances live, but `F_max` is a *display* setting users routinely set to
  1–2 kHz per ISO route-monitoring convention — and at that `F_max`, acquisition
  itself discarded everything above Nyquist before any analysis ever saw it. The
  raw stream is now retained at full bandwidth and `F_max` governs only what the
  Spectrum tab displays.
  - **`AcquisitionSettings.raw_samplerate` / `.raw_blocksize`** — a second,
    independent rate pair, fixed at `RAW_SAMPLERATE_HZ` and *not* maxfreq-derived.
    This is what `PicoScopeStream` acquires, what `VibeSample` / the HDF5 file /
    `frame_cache` hold, and what envelope analysis reads. `samplerate` /
    `blocksize` keep their previous maxfreq/binsize derivation and become
    display-only. One frame is one time window at two sample counts: `raw_blocksize`
    and `blocksize` span the same `acquisition_period`.
  - **`RAW_SAMPLERATE_HZ = 40000`** as shipped here, validated on a PicoScope 4424A
    up to 4 simultaneous channels. (Later reduced to a briefly-set `10_000` to
    relieve GUI lag, then corrected to **25600** = 2.56 × the top preset — see
    hotfix/RAW_SAMPLERATE under [Unreleased], which is also where the display-rate
    derivation this split exposed was fixed.)
  - **`collector.decimate_to_rate()`** — anti-alias filter + resample from the raw
    rate down to the display rate before Welch. Generalises
    `picoscope.antialias_decimate`'s integer-factor decimation to an arbitrary
    rational ratio via `resample_poly`, because a maxfreq-driven display rate is not
    in general a clean divisor of a fixed raw rate. `antialias_decimate` itself is
    deliberately untouched — that is the electrically validated hardware acquisition
    path — but the two are pinned to the same stopband target (`_AA_STOPBAND_DB`,
    through `scipy.signal.kaiser_beta`) rather than to two independently chosen
    filter designs. The ratio is `Fraction.limit_denominator(1000)`, and the function
    returns the rate it *actually* achieved (`raw_rate * up / down`), not the one it
    was asked for.
  - **`DataCollector.eu_scaled_raw(ch, sample)`** — the high-pass-filtered signal in
    the sensor's own native EU at the raw rate. Converts mV → EU but skips the
    SI/target-unit conversion and every integration order: envelope analysis
    demodulates the raw sensor signal directly and has no target unit of its own.
  - **`DataCollector.current_frame()`** — the `{ch: VibeSample}` dict for the frame
    currently displayed, using the same streaming-vs-browse cursor selection
    `process_samples()` uses, so a consumer needing the raw `VibeSample` rather than
    a decimated `ChannelResult` reaches the same frame without re-deriving the index.
  - The **Envelope tab is rewired** onto `eu_scaled_raw()` via `current_frame()`,
    instead of `process_sample()`'s now-decimated `ChannelResult`. Without this the
    one feature the whole split exists for would still have been display-rate-limited.
  - **`simulation._RawRateView`** — presents `config` at `raw_samplerate` /
    `raw_blocksize` to the signal generators, so `SimulatedSensor` generates *and
    reports* at the same rate `PicoScopeStream` delivers. Without it the simulated
    path silently generated at the display rate and offline dev/CI never exercised
    the raw→display decimation at all — the simulator would have defeated the
    retention it is supposed to test. Proxying leaves every generator, and the tests
    that call them directly against a real `AcquisitionSettings`, unchanged.
  - **`scripts/validate-streaming-capacity`** — sustained continuous-streaming stress
    test against a real PicoScope: configurable duration, rate and channel count,
    reporting overflow count, rate-degradation transitions (the streaming-rate
    watchdog in `picoscope.py`) and actual vs. requested raw ADC delivery rate. Exit
    status is 0 only on zero overflow *and* zero degradation transitions. This is how
    `RAW_SAMPLERATE_HZ` was chosen, and it is the reusable diagnostic for
    re-validating it against different hardware or a different expected channel
    count — rather than the measurement being re-derived by hand each time.
  - Monitor config dialog: a **>10 GB/year red warning** on the storage estimate.
    Per-year storage no longer scales down with a low `F_max`, because every stored
    frame is now the raw-rate capture.

---

### hotfix/cli-ux-refactor (2026-08-30)

#### Added
- **`desktop.py` — Linux desktop integration**, driven by `rev80
  --install-desktop-entry` / `--uninstall-desktop-entry`. Writes a
  `~/.local/share/applications/rev80.desktop` entry plus a hicolor PNG icon set
  under `~/.local/share/icons/`, then best-effort refreshes the desktop and icon
  caches so the launcher appears without a re-login. Windows is unaffected — the
  frozen build gets its Start Menu shortcut from the Inno Setup installer — and
  both commands refuse to run off Linux rather than half-installing.
  - The launcher's `Exec` is resolved as the `rev80` console script **next to the
    running interpreter** first, falling back to `PATH`. That is where pip places
    console scripts for a `--user`, venv or system install, so the entry points at
    the environment rev80 was actually installed into rather than whatever happens
    to be first on `PATH`. If that directory is not on `PATH`, `install()` says so
    and prints the `export` line — the launcher works either way, the terminal
    command does not.
  - **The icon set is PNG, not the source SVG.** Qt/KDE's SVG renderer does not
    render this icon correctly, breaking it in both the launcher and the taskbar; a
    plain hicolor PNG set at fixed sizes works everywhere.
  - `uninstall()` removes only the entry and the icons it installed, and reports
    "nothing to do" rather than failing when there is nothing there.
- **Unified `rev80` CLI** — a `headless` subcommand, top-level info commands
  (`--init-config`, `--list-devices`, `--list-sensors`, `--edit-config`) that need
  neither GUI nor hardware, and `--version`. `rev80-headless` remains as a
  standalone shortcut.
- **`CONTRIBUTING.md`** — `README.md` split into user-facing documentation and
  dev/build concerns (dev environment, project layout, testing, icon regeneration,
  Windows installer build).

#### Fixed
- **A non-editable `pip install .` produced a broken app.** `logging.yaml` and the
  icon font were not shipped as package data, and `resource_path()` assumed a source
  checkout — it resolved relative to the *project root*, which does not exist once
  the package is installed normally. `resource_path()` now resolves relative to the
  package's own directory, correct for an editable checkout, a normal install and a
  frozen `sys._MEIPASS` bundle alike; anything resolved this way must physically live
  under `src/rev80/` and be declared in `pyproject.toml`'s
  `[tool.setuptools.package-data]`. The editable checkout every test runs against is
  precisely the one layout that hid this.
- **`.githooks/pre-commit` restored** — the ruff check and the `_version.py`
  git-describe stamp, extended to re-render `doc/*.pdf` from `README.md`,
  `CONTRIBUTING.md`, `doc/PROGRESS.md` and `doc/CHANGELOG.md` via
  `scripts/render_md.sh` when those are staged. Ruff is warn-only here against 209
  pre-existing findings — a gate on the backlog, not on the commit.

#### Changed
- **`_paths.data_dir()` is always `~/Documents/Rev80/data`**, in development and
  frozen builds alike, instead of `./DEVDATA` in development. `DEVDATA` remains test
  scratch space only, hardcoded independently in `tests/`. A dev run and a shipped
  run now write measurements to the same place the user is told to look.

#### Removed
- **`ScopeSensor.target_unit`** and `effective_target_unit()` — dead. The registry
  field was never user-settable and always defaulted to a wrong value. The
  display/integration target is a per-channel setting (`channel_target_units`) and is
  unchanged: one sensor may be wired to several channels with different targets, so
  the target never belonged on the sensor definition.

---

### feature/spectral-averaging (2026-08-29)

#### Added
- **Linear power averaging of the spectrum over N frames**, with an enable
  checkbox and N in the acquisition dialog (off by default). Welch's method
  *is* linear power averaging, but since the F-8 fix set `nperseg = blocksize`
  it runs exactly one segment per frame — so there was no averaging anywhere in
  the chain, and `welch_overlap` had nothing to act on. Each bin of a
  single-segment estimate is χ²(2), with a standard deviation equal to its own
  mean, which is why the floor looks rough and a small line is hard to pick out
  of it.
  - `AcquisitionSettings.averaging_enabled` / `.n_averages` /
    `.n_averages_effective` (clamped to `cache_frames` — you cannot average
    more frames than are retained); `ChannelResult.n_averages` reports the
    count **actually achieved**.
  - A derived **Avg. Window** field reading `16 x 0.5 s = 8 s`, flagged when
    capped by the cache: N alone is hard to reason about, and how long the
    machine must stay steady is what the analyst actually needs to know. A
    frame is exactly `1/binsize` seconds.
  - A live "averaging 12 of 16 frames" line beside the peak count, showing
    "of N" only when the delivered count falls short.
  - `DataCollector._psd_and_overalls_for()` — the per-frame Welch PSD and
    5-order overalls, extracted from `process_sample` so the averaging
    accumulator reaches earlier frames through exactly that code rather than a
    second copy. Two divergent copies of one path was the direct cause of M-05.
  - `tests/test_spectral_averaging.py` — 19 tests.

#### The rule tying live and replay together
The average is the N most recent **valid** frames up to and including the frame
being displayed. Live that is the last N received; browsing it is
`frames[cursor-N+1 … cursor]`. One rule, so stepping forward through a loaded
file reproduces exactly what the live display showed at that moment — the same
replay-fidelity property F-4 established for the high-pass.

**Nothing is baked into the file.** The HDF5 stores individual raw frames, so a
capture taken with averaging *off* can be given 16 averages after loading, and
changing N recomputes without reloading. Averaging is a view on stored data,
not a property of it.

#### Decisions, each pinned by a test
- **Power domain, never amplitude.** Average |X|², then sqrt at the end. On a
  coherent line the two are identical, which is exactly why this is easy to get
  wrong and stay green — it shows only on the noise floor, where averaging
  magnitudes converges about **11% low** (a Rayleigh magnitude has mean
  0.886·√μ against the RMS). The overall combines as `sqrt(mean(squares))` for
  the same reason.
- **Above the per-frame PSD cache**, so changing N invalidates no per-frame
  work and does not have to join `psd_key`.
- **Overloaded records are rejected from the average**, including when the
  displayed frame is the overloaded one — analyzer practice, and the same
  reasoning F-5 used to keep them out of the trend. The waveform, the scalars
  and the overflow flag still come from the displayed frame, so nothing is
  hidden; only the spectral estimate is protected.
- **Crest factor and kurtosis are NOT averaged.** Averaging is for steady-state
  estimation; those exist to catch the frame that is *not* steady.

> Recorded because it is the point of the whole exercise: the first
> revert-check pass showed that swapping power averaging for amplitude
> averaging **passed all 17 tests**, despite the design note calling it the one
> thing that must be right. Two tests were added asserting against *both*
> candidate answers so the wrong one cannot pass.

#### Measured
Noise plus a 300 Hz line, F_max 1000 / df 2:

| N | floor CV | 1/√N predicted | floor level | line amplitude |
|---|---|---|---|---|
|  1 | 0.5260 | 0.5260 | 0.03387 | 0.22366 |
|  4 | 0.2248 | 0.2630 | 0.03626 | 0.22183 |
| 16 | 0.1189 | 0.1315 | 0.03740 | 0.21965 |
| 64 | 0.0604 | 0.0657 | 0.03800 | 0.21878 |

Scatter tracks 1/√N; the line is untouched at −2% across a 64× change. The
floor *level* rises 12% over that range — not drift, but the
Rayleigh-mean-to-RMS convergence the power-domain argument predicts, and the
clearest confirmation that the average is being taken correctly.

#### Still open
`welch_overlap` remains inert: averaging across frames does not overlap
segments *within* a frame. Making it real would roughly double the available
averages for the same wall time.

---

### round 2: vibration-analysis integrity (2026-08-29)

Second remediation round from the three-discipline audit, addressing the
vibration-engineering findings the first round did not cover. Round 1 fixed
*how* the numbers were computed; this round fixes *what they were computed
over*, and adds the diagnostics an instrument in this class needs.

#### Added
- **`envelope.py`** — envelope (demodulation) analysis, the audit's only
  "blocks stated purpose" gap. `envelope_spectrum()` band-passes around a
  structural resonance, takes the Hilbert magnitude, removes the DC term and
  returns a coherent-gain-corrected amplitude spectrum; `suggest_band()` picks
  a demodulation band from the frame. A bearing defect's impulses ring a
  housing resonance at 2–20 kHz and are buried under the 1x in the raw
  spectrum, but appear as a clean line at the defect rate with ±1x load-zone
  sidebands in the envelope — months before the broadband overall moves.
  Verified end to end against the simulated oracle: auto band 2546–5046 Hz
  against a true 4000 Hz resonance, BPFO expected 325.8 Hz found at 324.0 Hz
  (within one bin) at **125× SNR**, with the 1x and lower sideband next.
  New **Envelope** plot tab with band controls and an Auto button.
- **`_dsp.crest_factor()` / `_dsp.kurtosis()`** and `ChannelResult.crest_factor`
  / `.kurtosis` — the two impulsiveness scalars a broadband overall averages
  away entirely. Non-excess kurtosis (Gaussian = 3.0), which is what
  condition-monitoring practice quotes. Computed on the band-limited displayed
  trace, never on the Hann-tapered array the overall uses, whose taper is an
  amplitude envelope that would corrupt any peak statistic. Trended, persisted
  to HDF5 and to the monitor session, and shown on each result card.
- **Declared measurement band** — `AcquisitionSettings.band_fmin`/`.band_fmax`
  with resolved properties, `util.ISO_BAND_PRESETS` (ISO 20816 10–1000 Hz and
  low-speed 2–1000 Hz), an acquisition-dialog preset combo plus editable edges,
  `ChannelResult.band_fmin`/`.band_fmax`, HDF5 and monitor-writer persistence,
  and the band shown on the result card and both trend axes.
- **`simulation.GenerateBearingVibration()`** — a physically realistic
  bearing-defect model: impulse train at the defect rate, each impulse ringing
  a structural resonance, amplitude-modulated at the shaft rate by the load
  zone, with cumulative slip jitter, and `severity=0` as the healthy negative
  control. Now the default `SimulatedSensor` source.
- **`tests/test_declared_band.py`** (46), **`test_bearing_oracle.py`** (20),
  **`test_diagnostic_scalars.py`** (13), **`test_envelope.py`** (14).

#### Fixed
- **M-06 — the overall was not band-limited.** It was the RMS of the whole
  filtered block, so its band was `highpass_fc … fs/2`, and fs/2 is 1.28×–2.56×
  maxfreq depending on where the power-of-two rounding in `samplerate` lands —
  **2.048× at the 500/1000/2000 Hz presets**. F-9 had already truncated the
  *spectrum* at maxfreq, so the number on the result card and the picture
  beside it described different bands, and nothing recorded which. Content the
  user had explicitly excluded via F_max still reached the trend (+25% on the
  audit's case, enough to cross an ISO 20816 zone boundary), and overalls were
  not comparable across sessions taken at different F_max — which silently
  invalidates long-horizon trending.
  - All five integration orders now share one masked, Hann-tapered path. Order
    0 previously skipped the taper, correctly, because a passthrough performs
    no transform-domain multiply. Band-limiting removes that premise: the mask
    *is* such a multiply, hence a circular convolution in time.
  - The un-tapered Parseval alternative was measured and rejected: exact in
    band, but with a rectangular window's −13 dB sidelobes it let a 3× tone at
    30 Hz past a 100 Hz edge at only **−22 dB**, inflating the overall +2.70%.
    Hann rejects it by **−84 dB**, and −100 to −144 dB elsewhere, for 4.9e-4
    worst-case in-band error.
  - Hardware (4424A, AWG loopback, band 10–1000 Hz at F_max 2000): 800 Hz
    +0.0 dB, 950 Hz −0.0 dB, 1000 Hz −3.1 dB, **1100 Hz −58.2 dB**, 1300 Hz
    −58.6 dB, 1600 Hz −58.9 dB — a measured 58 dB cliff at the declared edge.
- **ISO 2954 — the high-pass −3 dB point sat on the declared band edge.** A
  4th-order Butterworth designed *at* 10 Hz reads 29% low at 10 Hz, the very
  frequency the standard names as the bottom of its declared band.
  `highpass_fc` is now the declared edge and the knee sits below it at
  `f_edge * (A²/(1−A²))^(−1/2N)`; at N=4, A=0.9 that is `0.8342 × f_edge`, so
  a 10 Hz edge designs at 8.34 Hz and reads −0.915 dB at 10 Hz. Safe only
  because the band mask now removes sub-band energy exactly, so the `1/ω²`
  blow-up the higher knee implicitly guarded against cannot reach the result.
  Hardware: 100 Hz +0.00 dB, 20 Hz −0.04 dB, **10 Hz −1.05 dB** (was −3.0),
  5 Hz −18.40 dB.
- **M-12 — anti-alias stopband was ~55 dB against an ~80 dB expectation.**
  `scipy.signal.decimate(ftype='fir')` uses a Hamming kernel; measured
  **−60.0 dB** worst case, capping usable dynamic range regardless of the ADC
  resolution negotiated elsewhere. Replaced with a cached Kaiser design
  (100 dB, 0.20 transition, 259 taps at q=4): **−111.7 dB**, passband flat to
  1e-4 at F_max. The wider 0.25 transition saves 52 taps but starts eating the
  passband at F_max. The longer kernel costs nothing at block edges — measured
  on one block against the analytic RMS, hamming +0.2416% vs kaiser −0.0001%,
  because the overall's Hann taper already de-weights the edges where the
  start-up transient lives. Hardware A/B on identical captured samples, q=8:
  **+10.8 dB** at 2600 Hz and +10.3 dB at 3100 Hz where alias leakage rises
  above the capture noise floor; below it both kernels sit under the floor.
- **M-14 — the simulated bearing signal was not a valid oracle.** Ten pure
  cosines plus white noise, kurtosis ~3, no impulsiveness, no resonance
  carrier, no sidebands, no slip. Every diagnostic added this round keys on
  exactly those properties, so it could not have validated any of them: a
  broken envelope analyser and a correct one both return "nothing here" on ten
  pure cosines. Also fixed the operator-precedence bug —
  `int(freqs[-1] // bearing_multiple*running_rate)` binds left to right, giving
  ~5000× too many iterations with every out-of-range harmonic collapsing onto
  the last bin via `argmin`; extracted as `bearing_harmonic_count()` so the two
  loops needing this arithmetic cannot disagree again.
  - Two constants set by measurement, not from the textbook. **`resonance_q`**:
    what governs impulsiveness is ring-down time over impulse period, and at
    the textbook Q=40 the ring-down is *longer* than the gap between impulses,
    so kurtosis reads 3.08 against a healthy 3.09 — the fault is undetectable.
    Q=8 gives τ/period 0.21 and separates 5.28 from 3.09. **Harmonic phase**: a
    single shared phase made healthy kurtosis swing 2.03–4.00 across seeds on
    nothing but how the cosines lined up, overlapping the faulted range;
    independent phases are both more physical and stable.
  - The healthy control is correctly *sub-Gaussian* (1.54–3.04), not Gaussian:
    a machine dominated by running-speed harmonics genuinely has kurtosis
    below 3.
- **S-12 — `SimulatedSensor` died silently above two channels.** `simulated()`
  ships a 2-element `scale` while the generator emits one column per enabled
  channel, so three channels raised a broadcast `ValueError` inside `_stream`,
  which had no `try/except`: the thread died while `_running` stayed set and
  `is_streaming` reported a healthy stream producing nothing, indefinitely. The
  scale is now fitted to the data, `_stream` is guarded and clears `_running`
  in a `finally`, and `_sample()` emits exactly one column per enabled channel
  (the old `max(..., N_CHANNELS)` floor gave single-channel configs a phantom
  second channel).
- **H-08 — `AcquisitionSettings.copy()`** copied only maxfreq and binsize,
  silently dropping every other field including all five per-channel dicts. It
  now round-trips through `to_dict`/`from_dict`, so a field added there cannot
  be forgotten here.

#### Changed
- **The spectral anomaly hook is unwired from the GUI panel**
  (`GUI_ANOMALY_HOOK_TYPES = ('rms',)`). It fires on essentially every healthy
  frame: it triggers on `np.any(|spec − baseline| / baseline > threshold)`
  across every bin while Welch runs a single segment in every shipped preset,
  so each noise-floor bin is χ²(2) with a standard deviation equal to its own
  mean and P(some bin of ~2000 exceeds 1.5×) is ~1.0 — `consecutive_n` is a
  delay, not a defence. Bins 0 and 1 are hard-zeroed for integration, so on any
  velocity/displacement channel they deviate by ~1e12 and fire permanently. The
  hook, the config schema and the headless front end are untouched, and a
  stored `spectral`/`both` is preserved rather than rewritten when the dialog
  is merely opened. Tracked for a fix-or-remove decision as **R39**.
- Stream pacing moved out of `GenerateBearingVibration_TemporalMethod` — a
  signal generator should not contain a `time.sleep` — into
  `SimulatedSensor._stream`, which paces against a deadline so the block rate
  stays honest when generation is slow.
- `doc/PROGRESS.md` gains **R34–R38** (standards conformance), **R39** and
  **R40**. R40 records that IEPE bias monitoring is **not achievable on this
  hardware**: the coupler has a DC blocking capacitor so the bias never reaches
  the scope on either coupling setting, and the 4000A ranges only to ±20 V
  against a 24 V supply, so even a direct pre-cap tap would over-range.

---

### hotfix/claude-ultrareview (2026-08-29)

Integration branch for the three-discipline audit remediation. Sections for the
individual branches follow below.

#### Changed
- **`util.py`** / **`gui.py`** — the **spectral anomaly hook is unwired from the GUI panel**. `GUI_ANOMALY_HOOK_TYPES` now restricts the monitor dialog's hook combo to `('rms',)`; `SpectralThresholdHook`, the config schema and the headless front end are untouched, so reviving it is a one-line change
  - It fires on essentially every healthy frame and has never been useful in practice. It triggers on `np.any(|spec − baseline| / baseline > threshold)` across every bin in the band, while Welch runs a single segment in every shipped preset (`nperseg == blocksize`) — so each noise-floor bin is χ²(2), with a standard deviation equal to its own mean. P(some bin of ~2000 exceeds 1.5×) is ~1.0 on healthy data, which makes `consecutive_n` a delay rather than a defence. Bins 0 and 1 are additionally hard-zeroed for integration, so on any velocity/displacement channel they deviate by ~1e12 and fire permanently
  - A stored `spectral`/`both` — which headless still writes — is clamped for display only. `GUI._hook_type_to_save()` preserves the original, so merely opening the monitor dialog cannot silently rewrite a headless user's configuration; that is the S-07 failure mode this branch had already fixed once
  - Tracked for a fix-or-remove decision as **R39**. A real fix needs band RMS rather than per-bin, a threshold in σ rather than fixed %, and a default band — i.e. it depends on R34
- **`doc/PROGRESS.md`** — added **R39** (spectral hook fix-or-remove) and **R40** (sensor-fault detection; records that IEPE bias monitoring is impossible on this hardware — the coupler has a DC blocking capacitor so the bias never reaches the scope, and the 4000A ranges only to ±20 V against a 24 V supply)

---

### feature/peak-selection (2026-08-29)

#### Added
- **`src/rev80/peaks.py`** — significance-based spectral peak selection, replacing "report the top N local maxima by absolute amplitude"
  - The local noise floor is not flat: across the 60 channel-spectra of the `old castle` corpus it varies by up to 7× *within a single spectrum*. On `blower 4 - bearing DE.h5` ch2 the median local floor is 9.0 mV overall but 39.4 mV over 1890–2000 Hz, so ranking by absolute amplitude ranked by *how loud the neighbourhood is* rather than by *how far a line stands out of it* — 6 of that spectrum's top 12 came from ripple in the noisy top of the band
  - The diagnostic cost was real: 1034 and 1088 Hz are sidebands at ±25/29 Hz around the 1059 Hz carrier — the bearing-fault signature — and ranked 10th and 4th, so at the shipped display count of 6 the sideband family was broken up and pushed off the table. The instrument was hiding the fault evidence behind noise ripple
  - `local_noise_floor()` estimates the floor per bin with a running median, then `select_peaks()` passes **array-valued** `height` and `prominence` to a single `find_peaks` call, so admission is evaluated bin by bin against each line's own neighbourhood. Everything that passes is reported; the count becomes an output and the user knob becomes a significance threshold in dB
  - **Amplitude reporting is unchanged** — the reported value is still the amplitude of the maximum bin, with no frequency interpolation and no energy summation across a peak. Ranking is still by descending amplitude: significance decides *whether* a line is reported, amplitude decides where it sits in the table
- **`tests/test_peak_selection.py`** — 626 lines, including an opt-in real-corpus regression suite (`REV80_CORPUS_DIR`, skipped by default since `DEVDATA/` is gitignored)

#### Changed
- **`collector.py`** — `process_sample()` step 6 calls `rev80.peaks.select_peaks` instead of `find_peaks(..., distance=5)` + top-N sort. `n_segments` is derived from the Welch parameters rather than assumed to be 1, so the median-to-mean floor correction stays right if `nperseg` ever stops equalling `blocksize`
- **`sample.py`** — `AcquisitionSettings.peak_threshold_db` (default 9.5), persisted in `to_dict`/`from_dict`
- **`gui.py`** — the "Peak Display" count spinner is replaced by a "Peak Sig., dB" threshold. The count still exists but only as a clutter cap on the table and plot markers (default 50, against a measured corpus median of 40 and p90 of 49), and a text line reports how many lines passed and whether the cap is hiding any — without it, a capped table is indistinguishable from a spectrum that genuinely had few significant lines

#### Measured
- **Default threshold 9.5 dB is set by a false-alarm cliff, not taste.** On pure noise (2001 bins, no lines at all) the mean reported count is 37.9 at 6.0 dB, **0.8 at 9.5 dB**, 0.0 at 12.0 dB
- **Floor window width 65 bins** tuned against the corpus, not argued. Scoring single-frame estimators against a 16-frame-averaged reference floor over 20 files × 3 channels × 4 frames gives a broad flat basin from 31 to 65 bins (median |error| 1.097 dB at 31, 1.039 at 45, 1.085 at 65, 1.326 at 129). A *synthetic* spectrum with a deliberately smooth floor prefers 129 — the disagreement is the point
- **Edge handling: truncated window, not the edge replication first proposed.** Replication copies one random bin 32 times, and 32 copies of a single exponential draw dominate a 65-sample median: median |error| 1.480 dB / p95 5.246 dB, against 0.591 / 1.829 dB truncated. Zero-padding (`scipy.signal.medfilt`) is worst, at −3.568 dB mean bias
- Corpus-wide at the default: count median 40, p10 22, p90 49. Under the old top-10 rule 6.67% of reported peaks stood less than 2× above their local floor (18.17% with a flat-top window); the gate admits none
- `wlen` is mandatory with `prominence` — unbounded, a single broad hump spanning the band has prominence 34.6 and its apex looks like the most prominent thing in the spectrum
- Known cost, asserted by a test so it cannot drift silently: **broad features are rejected on purpose.** A 40-bin-σ hump's apex has prominence 7 against a requirement of 144 and never reaches the table. That is right for a line table and wrong if you want broadband resonances flagged; they remain visible in the plot only

---

### fix/measurement-validity (2026-08-28)

Nine measurement-validity defects (F-1 … F-9) from the vibration-engineering audit,
plus one adjacent logging defect (S-09).

**Root cause of the whole class: the test suite was degenerate.** `tests/test_sample.py`
sets F_max=10000, binsize=2 → fs=32768, N=16384, so bin spacing is exactly 2.000 Hz —
then swept tones at 500, 1000, 1500 … 9500 Hz, **every one an exact multiple of 2**.
That is the single case where the block is genuinely periodic in N samples, the FFT's
circular-wrap discontinuity vanishes, and the integration error is identically zero.
`_make_dc` also defaulted `highpass_enabled=False`, so the filtered path was never
exercised by any amplitude assertion, and the displacement tests asserted only on the
spectrum peak, never on `result.overall`. Phase 1 of this branch was therefore a
deliberately **red** commit: 110 tests, 92 failing, before any fix was written.

The same mistake was then made again, and caught: every tone in the new suite was
generated as `sin(2πft)`, so **every record started at phase 0** and `x[0]` equalled the
DC level exactly — degenerate in precisely the same way bin-centred frequencies are.
Real hardware exposed it. `tone()` now takes a `phase` argument defaulting to 0.7 rad.

#### Added
- **`src/rev80/_dsp.py`** — windowing helpers for frequency-domain integration, carrying the measured error tables that justify each choice
- **`sample.py`** — `AcquisitionSettings.nperseg` and `.binsize_actual`: the Welch segment length and the bin width actually delivered
- **`collector.py`** — `filter_block()`, `filtered_data_for()`, `reset_filter_state()`, `_seed_zi()`: persistent per-channel high-pass state
- **`gui.py`** — `derive_acquisition_preview()`, a single source of truth for the dialog preview
- **`monitor/anomaly.py`** — `valid_results()`, a shared validity filter for anomaly hooks
- **`tests/test_measurement_validity.py`** — 123 tests covering F-1 … F-9 and S-09, all off-bin, with the high-pass enabled, across block boundaries and at every preset

#### Changed
- **`util.py`** — `MAXFREQ_PRESETS` is `[2e2, 5e2, 1e3, 2e3, 5e3, 1e4]`; **the 20 kHz and 50 kHz presets are removed** and F_max now tops out at 10 kHz (see F-3)
- **`sample.py`** — `VibeSample.samplerate` / `ChannelResult.samplerate` / the HDF5 `samplerate` attribute are now `float`. The true rate is generally not an integer
- **`sample.py`** — `n_fft_bins` counts **displayed** lines (DC…F_max), not the full one-sided transform: 1001 at the default preset, not 2049
- **`gui.py`** — the spectrum info panel reports `binsize_actual`, and is labelled `F_max` rather than `AA`
- **`monitor/writer.py`** — no longer carries its own divergent copy of `_write_channel_group`
- CRLF → LF in `picoscope.py` and two `examples/` scripts

#### Fixed
- **F-1 `collector.py`** — **FFT wrap leakage corrupted every integrated overall and waveform.** `rfft` was taken on the raw, un-windowed block and multiplied by `(jω)^n`. The DFT treats the record as periodic; unless it is exactly periodic in N samples there is a step discontinuity at the wrap point whose spectrum is broadband and low-frequency-weighted, and `n < 0` amplifies it by `1/ω^|n|`. The in-code claim that the round-trip was lossless held only for `n_ord == 0`, and zeroing bins 0 and 1 left the leakage in bins 2, 3, 4 … The spectrum was never affected (Welch already windows); what was wrong was the Overall card, the trend, `overall_json`, the anomaly detector's input, and the displayed waveform
  - Two treatments, because the consumers want different things. **Scalar overalls**: Hann taper, RMS divided by the window power gain `sqrt(mean(w²))`. **Displayed waveform**: cannot be tapered — the envelope would be plainly visible on the trace — so overlap-save instead, with a Tukey `α=0.5` window killing the wrap discontinuity and only the flat middle, where the window is exactly 1.0, returned. `time_vec` is truncated to match
  - **Cost, deliberate and documented:** integrated/differentiated traces span the middle 50% of the block
  - Measured (1.0 unit 0-pk sine, fs=32768, N=16384) — velocity overall at 61.0 Hz **+12.25% → +0.05%**; displacement overall at 61.0 Hz **+470.59% → +0.18%**, at 120.7 Hz +777.84% → +0.05%, at 501.0 Hz **+4473.76% → +0.00%**; on-bin 500.0 Hz was +0.00% before and after, which is exactly why the old suite never saw any of it. Waveform peak, displacement at 501.0 Hz: +10176.68% → +0.24%
  - Taper-width sweep at the worst case (61 Hz displacement): α 0.05 → +335.84%, 0.10 → +7.00%, 0.30 → +4.22%, **0.50 → +1.47%**. Reflection padding was tried and is far worse (+1918%) — it doubles the effective near-DC content. Differentiation (n=+1) verified unaffected, worst +0.018%
- **F-2 `picoscope.py`** — **the reported sample rate was not the rate actually used.** `_start_streaming` computed `actual_raw_fs` correctly from the interval the driver writes back, then discarded it (`self._actual_samplerate = self.config.samplerate`); the comment had conflated "hide the oversampling ratio" with "hide the actual rate". The driver quantises the sample interval to whole microseconds, so at F_max=2000 the hardware runs 8333.25 Hz while the app labelled it 8192 — **−1.70%**, rising to −8.25% at the (now removed) 50 kHz preset
  - **Confirmed on real hardware** (PicoScope 4424A, AWG loopback on channel A), same captured samples under two labellings: a commanded 1000.00 Hz tone read 983.062 Hz (−1.694%) and now reads 1000.012 Hz (+0.001%). Mean |error| across four tones **1.676% → 0.034%**. Reported as a float — rounding would reintroduce a smaller version of the same error
- **F-3 `picoscope.py`** — **no anti-alias filtering at all above F_max = 20 kHz.** `antialias_decimate()` is a no-op at factor 1, and `max(1, int(min(OSR_TARGET, CEILING / samplerate)))` truncated toward zero: 1.526 → 1 at 20 kHz, 0.763 → 0 → clamped to 1 at 50 kHz. The 50 kHz preset additionally requested 131072 Hz raw, **31% above** the measured `STREAMING_CEILING_HZ` — the exact condition the module docstring says makes the driver silently drop most samples while still reporting `status='OKAY'`
  - A general-purpose IEPE accelerometer has a mounted resonance at 25–80 kHz with 20–30 dB of gain, so at F_max=20 kHz an unfiltered 50 kHz component folds to 15536 Hz — inside the displayed band, indistinguishable from real signal, and *larger* than the real signal because of the resonance gain
  - `_choose_osr()` now uses explicit `math.floor` and requires `osr >= 2`. Only F_max ≤ 10 kHz satisfies `fs*2 <= 100 kHz`, hence the preset removal above. Overrule by raising `STREAMING_CEILING_HZ`, which requires re-measuring the safe continuous streaming rate on the target hardware and channel count. A maxfreq outside the presets still degrades rather than failing, but now logs a WARNING naming the frequency above which content will alias
- **F-4 `collector.py`** — **high-pass filter state was reset to zero on every block.** `sosfilt` was called with no `zi`, reintroducing a startup transient at the head of every frame of a continuous stream. Measured over blocks 1–3 of a 200 Hz tone at a 10 Hz high-pass: acceleration waveform peak +9.41% → −0.000%, displacement overall +19.15% → +0.017%; with 1000 mV of residual DC offset, acceleration overall **+14321.74% → −0.000%**
  - **Two regimes, handled distinctly, because replay is not a stream.** Live streaming filters once per frame in `receive_data`, in order, carrying state, and caches the result on the `VibeSample` since `process_sample` is called repeatedly on the same frame. Replay/browse re-processes stored frames out of order and carries no state — verified bit-identical forward and reverse to 12 significant figures. Block 0 of a stream still shows genuine settling; there is no history to carry
  - **F-4 follow-up, found by hardware:** `sosfilt_zi(sos) * x[0]` is scipy's documented idiom and is correct when the first sample represents the baseline — true for a step, false for anything oscillatory. On four consecutive real captures the block mean was −0.06…−0.21 mV (the true DC) while `x[0]` ranged over **36…305 mV**, and under `1/ω²` that spurious step dominated: worst-block displacement error **+4297.20%** against a settled reference. Now seeded from the block mean (−2.22%). A warm-up pass — filter the block, reuse its final state as its initial state — was measured and is *worse* (+61.10%): it imposes a periodic assumption the block does not satisfy. The branch's own synthetic tests missed this because they used phase-0 sines, reproducing the suite's own central blind spot
- **F-5 `collector.py`, `monitor/writer.py`, `monitor/anomaly.py`** — **overload and degraded frames were trended, alarmed on, and stripped on save.** Five gaps forming the classic spurious-alarm mechanism: a clipped waveform reads high with harmonic distortion, the trend records a step change that never happened, the detector fires — and on reload the record looks clean
  1. The overflow bitmask was read from whichever callback completed a block, so a callback raising overflow mid-accumulation had its flag discarded. Now latched with `|=` and cleared on emit
  2. `update_trend` ran regardless of the flags. Flagged frames are now excluded from the trend, while still being displayed and still flagged
  3. `_read_frame_group` hard-coded `overflow=False` and never set `degraded`, so the flags `_write_channel_group` had faithfully stored were never read back
  4. `monitor/writer.py` had a second, divergent `_write_channel_group` that wrote no validity flags at all — the divergence *was* the defect; they are now one function
  5. The anomaly hooks never read either flag. `valid_results()` is applied to both event evaluation and baseline adaptation: letting a clipped frame into an EWMA baseline poisons the reference for ~33 frames just as surely as firing on it
- **F-6 `gui.py`** — **the acquisition dialog computed the sample rate with 2×, not 2.56×.** It duplicated the derivation and used the bare Nyquist minimum, so at the default F_max=2000 it advertised 4.1 kS/s, 2049 lines, 1.000 s and half the true memory while the instrument ran at 8.2 kS/s, 4097 lines, 0.500 s. Now delegates to `AcquisitionSettings`; verified equal across the full preset grid
- **F-7 `collector.py`** — **the PSD cache key omitted binsize and samplerate.** Switching 2 Hz → 0.5 Hz bins returned the identical cached 2049-point, 2 Hz spectrum: the user believed they had quadrupled the resolution and nothing had changed. Masked while streaming, since each new `VibeSample` starts with `psd_mv=None`, so it bit in browse/offline mode and after loading a file
- **F-8 `sample.py`** — **stated line count and bin width did not match the computed spectrum.** `n_fft_bins` returned `blocksize//2 + 1` while Welch used `nfft = int(samplerate/binsize)` and `blocksize = nextpow2(samplerate/binsize) >= nfft`. **40 of 72** preset combinations were wrong; worst F_max=200/df=20, a real resolution of 20.480 Hz (+2.40%) and 17 lines claimed against an actual 13. Fixed with `nperseg = blocksize`; re-verified **0 of 72** mismatch. The existing amplitude suite was unaffected — at its F_max=10000/df=2 the old and new `nperseg` were already both 16384
- **F-9 `gui.py`, `collector.py`** — **the spectrum was displayed out to fs/2, where alias rejection is ~12 dB.** The axis, the peaks table and `find_peaks` all ran to fs/2 = 1.28 × F_max — the anti-alias filter's transition band, −21.8 dB at the folding frequency and effectively 0 dB at fs/2 itself. The whole point of the F_max = fs/2.56 convention is that the guard band is never shown. Now truncated at F_max before peak-finding. The info label had also called fs/2 the "AA" frequency, which read as a specification the instrument does not meet
- **S-09 `picoscope.py`** — **the ADC overflow warning inhibit was inverted, flooding the log.** `elif ch in self._overflow_warned: remove(ch)` fired precisely when a channel was *still* clipping, re-arming the warning every other callback — measured **10 warnings from 20 callbacks**. At a 1 ms poll interval that rolls every other diagnostic out of the rotating log during exactly the run being diagnosed. The clear-down loop also had to move out of `if overflow:`, since a return to zero is the only way to observe it

---

### chore/config-consistency-ci (2026-08-28)

#### Added

- **`.github/workflows/ci.yml`** — first CI for the project. There was no
  `.github/` at all: 300+ tests and nothing ran them.
  - push + pull_request, `ubuntu-latest`, matrix over Python 3.10–3.13
    (the range the new `requires-python` floor admits)
  - checkout → setup-python → `pip install -e ".[dev]"` → `ruff check src/ tests/`
    → `pytest tests/ -q`; `fail-fast: false`, concurrency group cancels
    superseded runs
  - installs `libx11-6`: dearpygui's `_dearpygui.so` links against libX11 at
    load time (confirmed with `ldd`). No GL and no X server are needed because
    the suite never calls `create_viewport()`.
  - the native PicoSDK driver is deliberately **not** installed; the suite runs
    against `SimulatedSensor`
  - **Verified end to end locally**, not assumed: a clean Python 3.12 venv built
    exactly as CI does, with the PicoSDK driver stubbed out and
    `DISPLAY`/`WAYLAND_DISPLAY` unset, gives 300 passed / 10 skipped. The
    `picosdk` `git+https` pin resolved and built a wheel with no special
    handling, so `--no-deps` is not needed. `dearpygui==2.0.0` publishes
    manylinux wheels for cp310–cp313 (checked against the PyPI JSON API), so the
    whole matrix is covered.
- **`util.py`** — `amplitude_scale(mode)`, `nearest_interval_preset(seconds)`,
  `canonical_hook_type(value)`, `hook_type_label(value)`, `ANOMALY_HOOK_LABELS`,
  `DEFAULT_AMPLITUDE_MODE`, `DEFAULT_ANOMALY_HOOK_TYPE`, `DEFAULT_RMS_ALPHA`,
  `DEFAULT_SPEC_ALPHA`, and an explicit `__all__`
- **`util.py`** — `600: '10 min'` added to `MONITOR_INTERVAL_PRESETS`
- **`README.md`** — Contributing section now documents the one-time
  `git config core.hooksPath .githooks` install step
- **Tests** — 7 new files, 135 tests: `test_gui_save_config.py`,
  `test_icons.py`, `test_monitor_pretrigger_scaling.py`,
  `test_sensor_library_integrity.py`, `test_config_contract.py`,
  `test_anomaly_hook_build.py`, `test_util_small_defects.py`

#### Fixed

- **`.githooks/pre-commit`** — still ran `ruff check vibechecker/` and wrote
  `vibechecker/_version.py` after the rebrand moved the package to
  `src/rev80/`. ruff exited non-zero against a nonexistent directory, so the
  hook blocked every commit for anyone who had installed it. Repointed at
  `src/ tests/` and `src/rev80/_version.py`.
  - `src/rev80/_version.py` regenerated: it read `rc0.4-10-g11a72f4` while
    `git describe` gives `rc0.5-44-g7bf4712`. **Shipped builds reported a
    version 34 commits behind, so a field bug report could not be tied to a
    build.**
  - Root cause of the silent rot: the hook is not installed by default
    (`core.hooksPath` is the stock `.git/hooks`), now documented in the README.

- **`pyproject.toml`** — four defects, each breaking a clean install:
  - `requires-python` was `>=3.8`, two minor versions below the real floor. No
    module uses `from __future__ import annotations`, so every annotation is
    evaluated at import: PEP 604 `dict | None` in `sensor.py:46` needs 3.10;
    `dict[str, Any]` in `config.py:219` and `argparse.BooleanOptionalAction` in
    `__main__.py:17` need 3.9. pip installed happily on 3.8/3.9 and the app
    raised `TypeError` on first import. Raised to `>=3.10`. Swept for 3.11+/3.12+
    constructs (`tomllib`, `StrEnum`, `ExceptionGroup`, `except*`, `TaskGroup`,
    `typing.Self`, `typing.override`, `itertools.batched`, `datetime.UTC`, PEP
    695 generics) — none present, so 3.10 is correct, not merely safe.
  - `dearpygui` was an optional `[gui]` extra, but `gui.py:6` and `icons.py:3`
    import it at module scope and the `rev80` console script reaches both via
    `__main__:main`. `pip install -e .` — exactly what CLAUDE.md instructs —
    produced a `rev80` command that ImportErrors. Moved into required
    dependencies; `[gui]` kept as an empty alias.
  - `pandas` and `matplotlib` were declared runtime dependencies but imported
    nowhere under `src/`. `matplotlib` was already in the PyInstaller excludes,
    confirming it was never needed at runtime. Removed. (Both are still used by
    the standalone `examples/TMS_Digital_Audio.py` and
    `scripts/advanced_plots.py`, which sit outside the installed package.)
  - `numpy`, `scipy`, `h5py`, `pyyaml`, `plyer`, `pywin32` were entirely
    unconstrained, so a shipped installer's contents depended on what PyPI
    served that day. Added lower bounds (not pins) chosen as the oldest releases
    that support 3.10 and carry the APIs actually used.

- **`pyproject.toml` / CI reproducibility** — `[tool.ruff.lint]` set only
  `ignore`, never `select`, so ruff linted with whatever its *current default*
  happened to be — and that default moves between releases. On an identical
  tree: **ruff 0.15.10 → 0 errors, ruff 0.16.5 → 167 errors**, none from a code
  change. With `ruff` unbounded in `[dev]`, CI would have gone red on an
  untouched tree at the next ruff release. Fixed at both layers:
  `select = ["E4", "E7", "E9", "F"]` makes the rule set explicit, and
  `ruff>=0.15,<0.17` bounds the version. Both versions now report clean.

- **`gui.py`** — `_on_sb_save_config` called `h5py.File(...)` but `gui.py` never
  imported `h5py` at module scope; the three other users each did a
  function-local import and this one did not. The resulting `NameError` was
  caught by a broad `except Exception` and logged as
  `"failed to patch {session_h5}"`, so the session browser's **"Save Config"
  button was dead code** and the message pointed the user at disk permissions.
  Added the module-scope import, removed the three redundant local ones, and
  narrowed the `except` to `(OSError, KeyError)`.

- **`icons.py` / `gui.py`** — `test_gui_build` failed on any clone that had not
  run `scripts/build.sh`, with an opaque
  `SystemError: <built-in function pop_container_stack> returned a result with
  an exception set`. `assets/fonts/` is gitignored and populated by build.sh, so
  the font is absent on a fresh clone and on every CI runner; `icons.load()`
  passed the nonexistent path to `dpg.font()`, and the failure inside the
  context manager surfaced from `pop_container_stack` naming neither the font
  nor the path — taking down all of `_create_gui()`. Now checks for the file and
  falls back to the DPG default with a warning. *This was the pre-existing
  failure standing between the suite and green, and the blocker for CI.*

- **`picoscope.py`** — the PicoSDK *driver* (`libps4000a`) is a separate native
  install from the `picosdk` Python wrapper, and `picosdk/ps4000a.py`
  instantiates `Ps4000alib()` at import time, raising `CannotFindPicoSDKError`
  when the driver is absent. `picoscope.py` imported it unguarded, so
  `import rev80.picoscope` was fatal without the driver. Reproduced by stubbing
  `find_library`: the **whole suite aborts** with 3 collection errors, not
  3 modules' worth of skips — note `test_antialias.py` is pure DSP and was
  collateral damage. Also contradicted CLAUDE.md's claim of "offline development
  and CI without hardware". Now degrades to `PICOSDK_AVAILABLE = False`, mirroring
  the guard `__init__.py:9-17` already uses for this exact import;
  `FindPicoScope()` returns `[]` with a warning. Verified identical results with
  the driver present and absent.

- **`monitor/controller.py:258`** — read the sensor sensitivity under
  `sensitivity_mv_per_eu`, a key that exists nowhere in the codebase;
  `session.sensor_snapshot` holds `ScopeSensor.to_dict()` output, which emits
  `sensitivity`. The `1.0` default therefore **always** won: the mV→EU division
  never happened and every burst's pre-trigger trend points came out a factor of
  `sensitivity` too large (~10x for a 10.2 mV/g sensor) against the post-trigger
  points on the same continuous plot. `engineering_units` on the adjacent line
  used the correct key, so the unit *label* converted while the magnitude did
  not — worse than an obvious break. Now rehydrates through
  `ScopeSensor.from_dict()` once per call so the field name can only be wrong in
  one place; misleading comment at `:246` corrected.

- **`README.md:920` / `CLAUDE.md:127`** — documented the same wrong
  `sensitivity_mv_per_eu` key. Following the README raised `KeyError` in
  `from_dict`, and the very next README paragraph correctly said the code
  divides by `sensitivity` — the two lines contradicted each other. Both fixed.

- **Sensor library could be silently and permanently destroyed.**
  `ScopeSensorRegistry._load_user` swallowed any parse failure with
  `except Exception: return []`, and `_save_user` writes whatever `_load_user`
  returned straight back over the file. `add()` and `delete()` both follow that
  load-then-save path, so **one unreadable entry erased every calibrated sensor
  definition, with nothing logged.** Two independent triggers reached it: the
  wrong documented key above, and `config._atomic_yaml_write` using `yaml.dump`
  with the **unsafe default Dumper** while every reader uses `yaml.safe_load` —
  loading a colleague's `.h5` auto-registers its sensors with no prompt and no
  type coercion, so a non-scalar attribute serialised as a
  `!!python/object/apply:` tag that `safe_load` then refused. Fixed at all three
  layers:
  1. `config.py:159` → `yaml.safe_dump`; unrepresentable values now fail loudly
     at write time and the existing file survives. Also closes a latent
     escalation: a writer emitting object tags means any future switch to
     `yaml.load` becomes arbitrary code execution from a shared measurement
     file. *No RCE today.*
  2. `scope_sensor.py` → `from_dict` coerces every field and rejects containers
     and arbitrary objects, so junk cannot reach the writer.
  3. `scope_sensor_registry.py` → a bad *entry* is logged with file, index and
     content and skipped; a bad *file* raises, so a read failure can never
     become an overwrite. Read-only callers go through `all()`, which degrades
     to `[]` and logs, so a corrupt file cannot crash GUI construction.

- **`config.py` / `gui.py` / `headless.py`** — two monitor defaults the GUI could
  not represent and therefore silently rewrote:
  - `hook_type`: `config.py:83` seeds `'rms'` (lowercase); the GUI combo items
    are capitalised and both `_on_anom_config_change` and `_build_anomaly_hook`
    compared raw strings, while `headless.py:159` did `.lower()`. On a fresh
    install `'rms'` matched neither `('RMS','Both')` nor `('Spectral','Both')`:
    opening Config→Monitor once **hid both hook groups, built zero anomaly
    hooks, and silently disabled anomaly detection** behind an Enable switch
    that was on. Now canonical lowercase everywhere, capitalisation demoted to a
    display label.
  - `interval_s`: `config.py:74` seeds `600`, which was not a preset member, so
    the widget showed "1 h" and saving wrote `3600.0` back — **silently changing
    a 10-minute logging interval to hourly, discarding 5 of every 6
    measurements.** Fixed at both ends: `600` is now a preset, and the fallback
    picks the *nearest* preset rather than a hardcoded 3600.

- **`headless.py` / `gui.py`** — `_build_anomaly_hook` bound `period` only inside
  the `if hook_type in ("rms","both")` branch but read it in the spectral
  branch, so a **Spectral-only config raised `UnboundLocalError`**. In headless
  this fires *after* `collector.start_stream()`, killing the process with the
  PicoScope still streaming and never closed — the worst outcome for an
  unattended run. The two copies fail differently, which is why it survived:
  `gui.py` reads `period` unconditionally and always raises, while
  `headless.py`'s `if "spec_ewma_time" in anom_cfg and period > 0`
  short-circuits, so it only raises when that key is present — which is exactly
  what the GUI writes. Hoisted in both.

- **Reconciled the four ways the two `_build_anomaly_hook` copies had drifted:**
  hook-type casing (above); `warmup` default 30 (GUI) vs 10 (headless) → 10,
  matching `config.py`'s seed, since at 30 the GUI needed a 3x longer baseline
  warm-up during which nothing could fire; `spec_n` default 3 (GUI) vs 10
  (headless) → 10, since at 3 the GUI fired on a third of the evidence headless
  required; and the EWMA-alpha fallbacks, previously hardcoded separately in
  each copy, now `util.DEFAULT_RMS_ALPHA` / `DEFAULT_SPEC_ALPHA`.

- **`_pico_loader.py:24`** — computed `Path(__file__).parent.parent / 'drivers'`
  → `src/drivers`, which does not exist; `_paths.py:25` already gets this right
  with three `.parent`s. `ensure_pico_dlls_loadable()` silently returned `False`
  in development, bundled DLLs were never registered, and picosdk fell back to
  walking `%PATH%`. Frozen builds use the `sys._MEIPASS` branch and were
  unaffected. Now delegates to `_paths.resource_path('drivers')` — the
  duplication was the bug — and logs a warning on Windows when it returns False.

- **`collector.py:1187,1224`** — deprecated `datetime.utcnow()` replaced with
  `datetime.now(timezone.utc).replace(tzinfo=None)`, deliberately **naive** to
  match `utcnow()`'s exact semantics. See follow-ups.

- **`AMPLITUDE_SCALE.get()` fallback inconsistency** — called with two different
  defaults across five sites: `np.sqrt(2)` in the live path
  (`collector.py:231`, `:550`) and `1.0` in the reload path
  (`collector.py:992`, `:1147`, `monitor/controller.py:267`). An unrecognised
  mode reconstructed a loaded trend **1.414x off** relative to the live trend on
  the same plot. All five now call `util.amplitude_scale()`; the fallback is
  `'0-P'` because every call site already normalises with `or '0-P'` before the
  lookup. Unknown modes are logged. A test asserts no `AMPLITUDE_SCALE.get()`
  survives anywhere in `src/`.

- **`util.py`** — no `__all__`, so `rev80/__init__.py`'s
  `from rev80.util import *` re-exported `np` and every imported name into the
  top-level namespace. Added an explicit `__all__`. `data_dir` is listed
  deliberately: it is imported into `util` from `rev80._paths` and reached as
  `rev80.data_dir()` by six call sites in `gui.py`/`headless.py`, so omitting it
  would have broken them at runtime rather than at import.

- **18 ruff errors** cleared (unused imports/variables, one `E401`). The five
  unsafe `F841`s were handled by hand: `test_vibechecker.py:186`'s `old_sr` was
  kept and *asserted on* — `test_load_offline_adjusts_maxfreq` captured the
  pre-load samplerate but never compared against it, so the "adjusts" behaviour
  it is named for went unverified. No `noqa` added anywhere.

#### Reverted

- **`.python-version`** — briefly changed to `3.13` on the premise that the
  literal `vibecheck` was a stale string. That premise was wrong: `vibecheck` is
  a real pyenv-virtualenv holding every project dependency, and naming a
  virtualenv there is correct pyenv-virtualenv usage. The change resolved to a
  bare interpreter with no packages and produced 15 collection errors. Reverted;
  the `pyproject.toml` changes from the same commit stand.

---

### refactor/event-pipeline (develop)

#### Changed
- **`collector.py`** — removed `callbacks` dict entirely; all consumers now read
  from `frame_cache` via `new_frame_event` rather than receiving samples directly
  - `collect_sample()` rewritten: `new_frame_event.clear()` / `wait()` / `frame_cache[-1]`
    instead of a `_one_shot` closure pinned into `callbacks`
  - `_data_callback()` simplified: appends to cache and sets event; no callback fan-out
- **`collector.py`** — `data_callback` renamed `_data_callback` (internal-only convention)
- **`gui.py`** — internal methods renamed with leading underscore:
  `display_frame` → `_display_frame`, `poll_new_frames` → `_poll_new_frames`,
  `create_gui` → `_create_gui`
- **`gui.py`** — removed vestigial `callbacks['plots']` registrations from `_on_load_file`;
  file-load display now goes through `new_frame_event` → `_poll_new_frames` exclusively,
  eliminating a latent DPG thread-safety bug (hardware-thread `_display_frame` call)
- **`gui.py`** — trend plot (`_update_trend_plot`) now called unconditionally in
  `_display_frame` so loaded HDF5 trend data is rendered in offline browse mode
- **`gui.py`** — removed two merge-artifact duplicate method definitions:
  `poll_new_frames` (stale single-quote copy) and `_on_save_click` (old DPG dialog version)
- **`gui.py`** — removed duplicate `ACQ_NOTES` widget block in `_create_gui`
  (caused DPG "alias already exists" crash on `test_gui_build`)

#### Refactored
- **Tests** — `callbacks` references replaced with `frame_cache` reads across
  `test_vibechecker.py`, `test_multichannel.py`, `test_picoscope.py`, `test_scope_sensor.py`

---

### hotfix/hpf-integration-fix (2026-08-28)

#### Fixed
- **`collector.py`** — `process_sample()` highpass + integration blow-up (field-reported spurious spike at ~1–2 Hz)
  - Root cause 1: the integration transfer function (`(2πf)^n`, applied at all three sites — 5-order overalls, PSD, time-domain output) only zeroed the exact DC bin; bin 1 (1x binsize) received the full multiplier applied to residual near-DC energy and dominated the whole spectrum (0.313 in/s at bin1 vs. a real 0.747 in/s tone peak in a captured reference file)
  - A first fix attempt weighted the transfer function by the highpass filter's frequency response (`scipy.signal.sosfreqz`); this suppressed bin1 by ~50,000x but, being a smooth multiply across many bins rather than an exact single-bin removal, behaved as a wide kernel under circular convolution and badly distorted the time-domain signal at both block edges
  - Fixed instead by hard-zeroing bin1 directly, unconditionally (not gated on `highpass_enabled`) — zeroing an exact FFT bin removes one Fourier basis component losslessly with no boundary sensitivity, the same property that already made the bin0 zero safe
  - Root cause 2 ("edge wobble", found while investigating #1): the zero-phase highpass (`sosfiltfilt`, introduced in feature/anti-alias) effectively doubles filter order via its forward+backward pass, overshooting the raw signal by 35–45% at both block edges for a low cutoff over a short block (10 Hz over a 1s/4096-sample block); reverted the highpass filter back to causal `sosfilt` (~8–10% startup transient)
  - Verified against real hardware captures (`DEVDATA/hpf-10hz.h5`, 78 Hz / 0.75 in/s-0P test tone): bin1 now exactly 0.0, overall amplitude 0.760 in/s vs. an expected ~0.75, residual edge softness reduced from 350%/246% to ~30–55%
- **Tests** — 4 new regression tests in `test_sample.py`: bin1 hard-zeroed for integration regardless of `highpass_enabled`, bin1 left untouched for differentiation and passthrough, and a bound on time-domain edge overshoot for the causal highpass

---

### feature/anti-alias (2026-08-26)

#### Added
- **`picoscope.py`** — mandatory anti-alias oversample/decimate stage in `PicoScopeStream`
  - Field incident: a high-frequency bearing-fault harmonic aliased into the low-frequency band at low apparent power, injecting spurious spectral energy; root cause was driving the ADC directly at the target analysis rate with no anti-alias filtering
  - Always oversamples the ADC (`effective_osr`, up to 4x, capped by `STREAMING_CEILING_HZ` — a ceiling measured on real hardware: continuous `ps4000aRunStreaming`/`GetStreamingLatestValues` silently drops most samples above ~100–250 kHz depending on channel count, with no error indication), applies a zero-phase anti-alias filter, then decimates back to `config.samplerate` via the new `antialias_decimate()` helper — fully transparent to `DataCollector` and everything above it
  - Electrically verified on a PicoScope 4424A with siggen loopback: a tone above target Nyquist that aliased to a spurious 125 mV peak under naive decimation is suppressed 61.9 dB by the real pipeline; an in-band tone near maxfreq passes through unattenuated
- **`picoscope.py`** — second, independent streaming-rate watchdog flags (`.degraded`) sustained USB throughput below `_RATE_DEGRADED_THRESHOLD` of the requested raw rate — the same silent data-loss mode uncovered during the anti-alias investigation, invisible to the existing silence watchdog since callbacks keep firing with `status='OKAY'`; deliberately never triggers `_try_recover()` (a USB/bus bandwidth ceiling, not a device hang)
- **`sample.py`** — `VibeSample`/`ChannelResult` gain a `degraded: bool` field
- **`tests/test_antialias.py`** — regression tests for `antialias_decimate()`: aliasing tone suppressed >20x vs. naive decimation, factor=1 no-op, legitimate low-frequency tone survives intact, independent multi-channel handling
- **`tests/test_picoscope.py`** — `TestRateDegradationWatchdog`: monkeypatched-clock coverage of `_check_rate_degradation()` (healthy/degraded/recovery), confirms `_try_recover()` is never called for this condition

#### Changed
- **`sample.py`** / **`util.py`** — `samplerate` now derives from `nextpow2(2.56 * maxfreq)` instead of 2x, guaranteeing >=28% Nyquist margin for the anti-alias filter's transition band (matching the ratio commercial FFT vibration analyzers use); `MAXFREQ_PRESETS` drops the 100k/250k/500k Hz entries — hardware measurement showed these already exceed this PicoScope's continuous-streaming ceiling, silently corrupting captured data
- **`collector.py`** — `receive_data()` threads the `degraded` flag from each incoming frame onto every channel's `VibeSample`/`ChannelResult` and persists it into saved `.h5` files alongside `overflow`; new `DataCollector.stream_degraded` property mirrors `is_streaming`
- **`collector.py`** — `process_sample()`'s lowpass Butterworth block removed (anti-aliasing is now mandatory upstream in `PicoScopeStream`); highpass filter switched from causal `sosfilt` to zero-phase `sosfiltfilt` (reverted in hotfix/hpf-integration-fix, below)
- **`gui.py`** — Lowpass checkbox/field removed from the acquisition dialog; status line shows the auto-derived AA cutoff instead of "LP ..." text; a warning line appears when the stream is degraded

#### Removed
- User-facing `lowpass_enabled`/`lowpass_fc` fields — they ran after the ADC had already sampled and so could never actually prevent aliasing; anti-aliasing is now mandatory and handled at capture time

---

### rebrand-to-rev80 (2026-08-19 – 2026-08-28)

From this point forward the product is named **Rev80** (formerly vibechecker). Earlier sections below retain the historical "vibechecker" name as an accurate record of the codebase at the time.

#### Changed
- Rebrand vibechecker → Rev80 across the codebase, packaging, and docs
  - Package moved from `./vibechecker/` to `./src/rev80/` (src-layout; history preserved via `git mv`); all imports updated `from vibechecker` → `from rev80`
  - `pyproject.toml`: package name `rev80`, entry points `rev80`/`rev80-headless`, `where=["src"]`, `pythonpath=["src"]`
  - User data dir moved to `~/Documents/Rev80/`; config dir moved to `~/.config/rev80/`
  - GUI title/label, CLI `prog` name, installer (`installer/rev80.iss`), build spec (`rev80.spec`), and icons (`assets/icons/rev80.ico`/`.svg`) renamed to match; README/PROGRESS docs updated
  - **`_paths.py`** fix: `resource_path()`'s base needed one more `.parent` after the src-layout move added a directory level (it was resolving into `src/` instead of the project root); `logger.py` now resolves `logging.yaml` directly relative to its own file instead of through `resource_path()`
- **`build/collect_pico_dlls.py`** / `build.sh` — search a bundled `vendor/` folder for PicoSDK DLLs first, removing the requirement to install PicoSDK system-wide before building
- Repo root reorganized: loose docs (`CHANGELOG.md`, `PROGRESS.md`, `VibeGui Project.md`) moved into `doc/`; dev scripts (`build.sh`, `render_progress.sh` → `render_md.sh`, `runtimes.ipynb`) moved into `scripts/`; `rev80.spec` moved into `build/` alongside `collect_pico_dlls.py`, with `ROOT` updated to resolve from `SPECPATH`'s parent so spec-relative paths still point at the repo root; stale `requirements.txt` and `picosdk-install.md` removed
- `.gitignore` — corrected the PyInstaller build-output path exclusion left stale by the repo reorg
- Project management docs revisited — outstanding requirements and tech debt items reviewed and updated

---

### hotfix/welch_leakage (2026-08-18)

#### Fixed
- **`collector.py`** — Welch window functions (Hann, Blackman-Harris, etc.) introduce spectral leakage that inflates the reported overall vibration level by a window-dependent factor (Hann: √(3/2)); overall amplitude is now derived from the RMS of an exact-inverse time-domain reconstruction instead of summing spectral peaks
  - The 5-order (`-2`…`+2`) mV RMS overalls are now computed via `irfft` of the integration-scaled `rfft` — reusing the same plain, unwindowed `rfft` already computed once for the time-domain output step, so the round-trip is lossless — as `sqrt(mean(time_ord**2))` instead of `sqrt(sum(psd_ord**2))`
  - The target-unit overall (step 7) now reuses the cached 5-order mV RMS column instead of re-deriving it from the spectrum
- **`collector.py`** — `process_sample()` now guards against the resolved integration order falling outside `[-2, 2]`; previously an out-of-range order silently indexed the wrong overalls column, producing false scaling — it now logs an error and returns `None` for the frame

---

### feature/monitor_mode (2026-05-28 – 2026-06-30)

#### Added
- **`monitor/` package** — Monitor Mode interval datalogger
  - `gate.py`: `IntervalGate` with snap-to-grid scheduling and burst mode
  - `session.py`: `MonitorSession` frozen dataclass (later gains `acq_snapshot`/`channel_snapshot`/`sensor_snapshot`, `cooldown_enabled`/`cooldown_s`)
  - `anomaly.py`: `AnomalyHook` protocol + `NullAnomalyHook` stub
  - `writer.py`: `MonitorWriterThread` (daemon, disk-space guard)
  - `controller.py`: `MonitorController` orchestrating gate/writer/anomaly
  - `gui.py`: Monitor card with config tab and arm/disarm controls (relabeled and reworked repeatedly through the branch — see Changed)
  - 51+ new tests across `test_monitor_gate.py`, `test_monitor_index.py`, `test_monitor_controller.py`
- Session storage iterated through several revisions in-branch:
  - v4: monitor captures write the standard metadata+frames HDF5 layout so `collector.load_data()` can open them directly with no adapter; a `capture_trigger` root attr distinguishes monitor files from manual saves
  - v5 (Phase 2 storage redesign): one `session.h5` per session (`DEVDATA/monitor/{session_id}/`) replaces per-capture files and the SQLite index entirely — `/monitor/{N}/` groups for interval captures, `/burst/{burst_id}/{frame_index}/` groups for burst events, `/burst.attrs['burst_list']` JSON for fast browser rendering without loading frame data
- **Burst capture** — manual (`trigger_burst()`) and anomaly-triggered bursts with a pre-trigger ring buffer
  - Session browser rewritten as a two-tab modal (Monitor / Burst views); `resize_frame_cache()` now expands the cache before load so all captures in a session are browsable, not just the most recent `cache_frames`
  - A run of alignment fixes during the branch: the trigger frame was double-counted in the pre-trigger snapshot; `_burst_all_results` indices were misaligned against pre-trigger frames; burst `rel_time` rebased to the trigger frame (t=0) instead of session-relative time; frame cache resized before loading burst frames (previously silently evicted pre-trigger frames at the default 32-frame cache); pre-trigger overalls pre-computed at capture time (`_compute_pretrigger_overalls()`) rather than reprocessed at load; disk-usage estimate corrected to include the pre-buffer, not just burst duration; trend unit conversion restored when browsing a loaded session (sensor wiring was missing on the session-load path, so channels fell back to raw mV)
- **Anomaly detection hooks** (`monitor/anomaly.py`)
  - `RmsThresholdHook` — EWMA self-calibrating per-channel baseline, triggers when `|current - baseline| / baseline` exceeds a threshold for N consecutive frames; tracks streak onset time so `trigger_time`/`trigger_rel_time` reflect anomaly onset rather than the confirmation frame
  - `SpectralThresholdHook` — initially a stored-baseline bin-by-bin dB comparison with an optional fmin/fmax band; later rewritten to an EWMA per-bin baseline with a percentage threshold and peak-frequency reporting in the trigger reason
  - `CompositeAnomalyHook` — tries each hook in order, returns the first event; propagates `reset_baseline()` to all children
  - `FixedThresholdHook` — independent upper/lower level triggers with unit conversion via `UNIT_TO_SI`
  - `ewma_alpha_from_time(tau, dt)` helper lets EWMA settings be specified as a time constant τ (seconds) instead of the opaque `alpha` value; GUI shows a live computed-α label
  - Post-burst cooldown gating replaces arm/disarm entirely: the anomaly hook is supplied once at `start()` and active for the whole session; a cooldown deadline set after any burst fires suppresses further triggers while interval captures continue normally
  - GUI: Anomaly Detection section in the Monitor config tab (hook-type combo, RMS/Spectral/Fixed-level/cooldown settings groups, tooltips throughout); "Reset Baseline" replaces the old Arm/Disarm button
  - 15+ new tests (`test_monitor_anomaly.py`) covering warmup gating, consecutive-N triggers, baseline set/reset, composite fallthrough, streak tracking, cooldown
- **Headless CLI** (`headless.py`) — interval datalogger without the GUI
  - `python -m vibechecker.headless` / `vibechecker-headless` console script: discovers a PicoScope (or `--device sim`), loads saved device config, starts the stream, runs `MonitorController`, prints periodic status, and shuts down cleanly on SIGINT/SIGTERM with a session summary
  - `--headless` flag routes `__main__.py` into headless mode; shares the collector/monitor/sample/picoscope pipeline unchanged with the GUI path
  - `--from-file` loads an `.h5` file or monitor session directory on startup (both GUI and CLI); `--[no-]autodetect` controls device discovery, defaulting off when `--from-file` is given
  - `--init-config` seeds `~/.config/vibechecker/` with `acquisition.yaml` and `devices/picoscope-defaults.yaml`
  - Monitor/anomaly settings configured once in the GUI persist to device config and are read back by headless as defaults, overridable by CLI args
  - `dearpygui` made an optional dependency (`pip install -e .` for headless-only installs; `pip install -e '.[gui]'` for the GUI)
- **`drivers/install-picoscope4000a-driver.sh`** — Linux PicoScope driver install script; registers `/opt/picoscope/lib` with `ldconfig` after install
- **`gui.py`** — Frame info card in the right panel: timestamp, block size, and sample rate always shown; burst-browse-only fields (frame time relative to trigger, burst ID, trigger type/timestamp, max overall per channel); session ID when browsing a session or burst
- **`gui.py`** — CommitMono Nerd Font icons throughout the left panel (card headers, action buttons, browse-nav arrows); font auto-downloaded on first build and bundled into the frozen app
- **`gui.py`** — global keyboard shortcuts: Ctrl+A autoscale, Ctrl+K start/stop, Ctrl+S save, Ctrl+O load, Ctrl+Q quit, ←/→ frame browse (live only)
- **`gui.py`** — configurable frame cache depth (`AcquisitionSettings.cache_frames`, default 32) with derived recording-window and memory-usage display

#### Changed
- **`config.py`** — layout split into `acquisition.yaml` (maxfreq/binsize/monitor/anomaly, per instance), `devices/picoscope-<model>-<SN>.yaml` (channels + siggen, per device), and `devices/picoscope-defaults.yaml` (new-device template); `device_config_path()` now takes `(model_name, serial_number)` and produces human-readable filenames; no migration path — delete `~/.config/vibechecker` to reseed
- **`collector.py`** — overalls now always computed over the full FFT spectrum; the `trend_fmin`/`trend_fmax` "Trend Frequency Window" band-limiting knob removed entirely (dataclass field, config default, UI tags, dialog widgets, tests)
- **`collector.py`** — `nperseg` clamped to signal length in the Welch PSD call to avoid spurious warnings on short blocks
- **`collector.py`** — `_load_v3`/`_load_v4` consolidated into a single `load_data()` method, fixing a v4 load crash where the old `_load_v4` delegated to `_load_v3`, which read a `data` key that doesn't exist on v4 trend groups
- Version tooling: git-describe version written by a `post-commit` hook, later moved to `pre-commit` so `_version.py` is included in the commit that changes it; installer version now derived from `_version.py` at build time instead of hardcoded in the `.iss` file
- Build fixes accumulated through the branch: UPX disabled (was corrupting the frozen `python3XX.dll`'s PE import table); `pandas` removed (pulled in a `pytz` version-detection failure in frozen builds; the peaks table now uses `list[tuple]`); `plyer`'s Windows filechooser dependency (`win32com`/`pywintypes`) added to hidden imports; `pyyaml` hidden-import name corrected (`yaml`, not `pyyaml`); `dist/` cleaned and any running instance killed before rebuilding; `assets/` bundled into the frozen app (font was missing, causing a startup crash); PyInstaller cache wipe no longer runs by default (`./build.sh all clean` to force it); Inno Setup arch identifier updated to `x64compatible`

#### Removed
- `monitor/index.py` (SQLite session index) — superseded by the single-`session.h5` v5 layout
- Arm/disarm as a user-facing concept — anomaly detection now runs for the whole monitored session, gated only by post-burst cooldown

---

### refactor/mv-domain-trend (2026-05-05)

#### Changed
- **`sample.py`** / **`collector.py`** — `VibeSample` now stores raw mV throughout; all sensitivity conversion, Butterworth filtering, and Welch PSD computation moved into `DataCollector.process_sample()`
  - `VibeSample`: `process()`, `_convert_time_domain()`, `push_sample()`, `save()`, `load()` removed; adds `overflow: bool` and cached `psd_mv`/`freq_hz`/`_psd_config_key`/`overall_ampl_by_integration_order` (5,) mV RMS fields
  - `ChannelResult` gains an `overflow` field
  - `receive_data()` becomes a pure mV pass-through (no sensitivity or filtering applied)
  - `process_sample(ch, sample)`: filter → Welch PSD (cached) → 5-order overalls (cached) → sensitivity + SI + integration → `ChannelResult`
  - `process_samples()` becomes the collector-owned frame dispatcher; appends to trend only while streaming, uses a `-1` cursor index in browse mode
  - Trend storage changed from a dict-of-lists to `dict[int, {rel_times: ndarray, orders: ndarray(M,5)}]`; new `get_trend_for_display()` centralizes unit/sensitivity/amplitude-mode conversion so `gui.py` no longer imports `util` for it
  - `get_active_eu()` returns `'mV'` immediately when no `ScopeSensor` is assigned, avoiding nonsensical unit conversion before sensitivity is known
  - HDF5 v4: per-channel `(M,5)` orders matrix plus per-channel `rel_times`; v3 files are promoted to v4 trend structure on load (order-0 only)
- **`gui.py`** — display loop simplified around `process_samples()`/`get_trend_for_display()`; `_compute_channel_result()` removed; overflow now read from `result.overflow` instead of a bitmask
- **`picoscope.py`** — `_setup_siggen()` now also called from `start()`; previously it only fired on the reconnect path in `_try_recover()`, so the signal generator never started on the initial `stream.start()` call
- **`collector.py`** — overalls now computed over the full FFT spectrum unconditionally (groundwork later formalized by removing `trend_fmin`/`trend_fmax` in feature/monitor_mode); HDF5 load paths consolidated

#### Added
- **`gui.py`** — global keyboard shortcuts (Ctrl+A/K/S/O/Q, arrow-key frame browse) — later extended in feature/monitor_mode
- **`gui.py`** — configurable frame cache depth with recording-window/memory display, `DEFAULT_CACHE_FRAMES` sourced from `config._BUILTIN_DEFAULTS` — later extended in feature/monitor_mode
- Build tooling: git-describe version written by a post-commit hook and embedded into the installer via `_version.py`; PyInstaller/Inno Setup fixes for UPX corruption, a `vibechecker.spec` merge conflict, `pandas`/`plyer` bundling, and `pyyaml` hidden-import naming

---

### feature/windows-build (2026-03-29 – 2026-05-27)

#### Added
- **`_paths.py`** — cross-platform path sanitization (Phase 1): `sys._MEIPASS`-aware `data_dir()`, `log_dir()`, `resource_path()`; replaces the third-party `path` library with stdlib `pathlib` across all modules; `SAVEDIR`/`DataCollector.datadir` route to `~/Documents/vibechecker/data/` in frozen builds
- **`_pico_loader.py`** / `build/collect_pico_dlls.py` — PicoScope driver bundling (Phase 2): a Windows script locates `ps4000a.dll`/`picoipp.dll` from the PicoSDK install (registry + default paths), validates the 64-bit PE header, and copies them to `drivers/`; `_pico_loader.py` registers that directory via `os.add_dll_directory()` before `picosdk` import, handling both frozen (`sys._MEIPASS/drivers/`) and dev layouts
- **`vibechecker.spec`** / `installer/vibechecker.iss` / `build.bat` / `build.sh` — PyInstaller + Inno Setup build pipeline (Phase 3): one-dir PyInstaller build bundling `logging.yaml`, driver DLLs, and dearpygui data; Inno Setup 6 script for a 64-bit, non-admin install to `%LOCALAPPDATA%` with a soft PicoSDK-present check and Start Menu/desktop shortcuts
- App icon: placeholder icon wired into both the PyInstaller spec and Inno Setup script (real artwork deferred)
- **`README.md`** — restructured for users, contributors, and Windows builders: Windows install section (PicoSDK + installer), cross-platform source install section, Contributing section (dev env, project layout, icon swap guide), full prerequisites table (Python, Git for Windows, PicoSDK, Inno Setup)

#### Fixed
- PicoSDK 11.x detection by DLL path when the registry key is absent
- `logging.yaml` moved into `vibechecker/` so `resource_path()` resolves it correctly in both dev and frozen builds
- Removed `scipy` submodule excludes from the PyInstaller spec — `scipy.signal` depends on `scipy.linalg` internally and the build broke without it
- Debug `print()` statements stripped from `gui.py`/`__main__.py`; Inno Setup branding (publisher, copyright, license) updated
- Inno Setup Compiler (`ISCC`) lookup corrected to the proper install `APPDATA` directory
- Icon assets moved to `assets/icons/`

#### Changed
- **`picoscope.py`** — `FindPicoScope` replaced with multi-device enumeration via `ps4000aEnumerateUnits`, opening each device by serial number; `PicoScopeStream` gains `_open_unit_by_serial` so it targets the correct device when multiple scopes are connected
- **`picoscope.py`** — hand-maintained `_channels_for_model` lookup table replaced by `_probe_channel_count`, which calls `ps4000aSetChannel` for channels A–H and counts successes, so any future hardware variant self-reports its channel count without a code change
- Ruff lint fixes across `picoscope.py`, `sample.py`, `util.py`

---

### feature/channel-naming (2026-04-03 – 2026-04-13)

#### Added
- **`sample.py`** — `AcquisitionSettings` gains `channel_names` and `channel_target_units` dicts with `name_for(ch)`/`target_unit_for(ch)` helpers, persisted in `to_dict`/`from_dict`; later extended with `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges` dicts and matching typed accessors (`amplitude_mode_for`, `coupling_for`, `voltage_range_for`)
- **`gui.py`** — offline post-analysis mode: `load_data` auto-configures `enabled_channels` and `maxfreq` from file contents; plot series, axes, and results panel sync after load; connection summary shows "File Loaded" (yellow) with frame/channel count; trend plot gets a vertical cursor line for the browsed frame position; acquisition buttons disabled when no device is connected
- **`gui.py`** — native file dialogs via `plyer.filechooser` (kdialog on KDE, native Win32) replace the DPG file dialog; `SAVEDIR` resolved to an absolute path so the dialog opens in the right place; browse-waveform controls consolidated into a single `_on_browse` dispatcher
- **`gui.py`** — Channels tab redesign: per-channel collapsing header row (color swatch + name text, then coupling/range/sensor on a second line), themed colored-when-enabled / grey-when-disabled; enabled state moved outside the collapsing header with a target-unit/amplitude indicator on the header itself; amplitude-mode combo added per channel; color indicators switched from a `■` glyph (didn't render in the app font) to `drawlist`/`draw_rectangle`
- **`util.py`** — expanded `UI_Elements` tag registry: named constants replace previously hardcoded `DEVSETUP_*`/`SREG_FIELD_*` strings; new tags for the redesigned channel rows (`scope_ch_name_text`, `scope_ch_hdr_theme`, `scope_ch_amplitude_mode`)
- File Handling card gains a multiline Measurement Notes widget, read on save and populated on load
- Tooling: `ruff` added to dev dependencies with a `.githooks/pre-commit` hook (`git config core.hooksPath .githooks` to activate); `pyproject.toml` sets line-length 120, ignores E402/E701

#### Changed
- **`collector.py`** — HDF5 format migrated v1 → v2 → v3 across the branch
  - v2: metadata moved into `.attrs` (`/acquisition`, per-frame/per-channel groups) instead of child datasets; `_load_v1` retained for back-compat
  - v3: structured `/metadata/` group — `/metadata/acquisition` (scalars only), `/metadata/scope_sensors/{id}` (sensor library, each unique sensor stored once), `/metadata/channels/{ch}` (name/unit/coupling/voltage_range/sensor_id/target_unit/amplitude_mode); `/frames/{i}/{ch}/data` stores raw samples only; `/trend/rel_times` becomes a shared axis with `/trend/{ch}/data` per channel; `load_data` dispatches to `_load_v3` only, `_load_v1`/`_load_v2` removed; `save_data` overwrites existing files instead of early-returning
  - Fixed a file-mode bug where the channel list in the config dialog was derived from `enabled_channels` rather than the frame cache, so disabling a channel made it disappear from the dialog entirely
- **`scope_sensor.py`** — `amplitude_mode` field removed; it's a per-channel acquisition setting, not a sensor property, and moves to `AcquisitionSettings.channel_amplitude_modes` (old files with the key are silently ignored on load)
- **`gui.py`** — config dialog scroll fix: outer window gets `no_scrollbar`/`no_scroll_with_mouse`, the tab bar and each tab's content are wrapped in their own `child_window` so scrolling stays contained per-tab, and the Close button is pinned outside the tab area
- **`sample.py`** — spectral peak detection: display count default raised (3 → 6) and relabeled "Peak Display"; minimum peak distance changed from a spectrum-length-relative value to a fixed 5 bins

---

### refactor/queue-handoff (2026-04-08)

#### Changed
- **`collector.py`** / **`gui.py`** — decouple collector→GUI with `threading.Event`, precursor to the fuller refactor/event-pipeline cleanup above
  - `DataCollector.new_frame_event`: set by `data_callback` and `reprocess_last_block`
  - `GUI.poll_new_frames`: polls the event each render tick and grabs `frame_cache[-1]`
  - Switched from `dpg.start_dearpygui()` to a manual render loop
  - Removed the `callbacks['plots']` registration — the GUI no longer hooks directly into the collector for display; `collect_sample`'s one-shot capture still used the `callbacks` dict at this point (removed entirely later, in refactor/event-pipeline)
  - Naturally handles GUI lag: rendering always shows the latest frame and skips intermediates, while all frames remain in `frame_cache` for browsing regardless of render rate
- **`gui.py`** — guarded `poll_new_frames` against a rare `IndexError` race if the hardware thread shifts the deque between `len()` and indexing; silently skips the frame since fresh data arrives next tick
- **`README.md`** / **`CLAUDE.md`** — architecture docs updated for the event-based collector↔GUI decoupling: callback diagrams replaced with the event-signal + poll-loop pattern; stale `sounddevice` references removed

---

### feature/picoscope

#### Added
- **`vibechecker/picoscope.py`** — PicoScope 4000A acquisition backend (Phase 1)
  - `FindPicoScope()` — enumerates connected PS4000A units; returns `VibeSensor`-compatible
    dicts with `unit=['mV']`, mirroring the `FindDigiducer` interface
  - `PicoScopeStream` — background polling thread wrapping `ps4000aRunStreaming`
    - Converts ADC counts → mV via `adc2mV` on every driver callback
    - Accumulates variable-sized chunks into exact `blocksize` blocks before firing
      `DataCollector.recieve_data`
    - Implements `.active / .start() / .stop() / .close()` interface (compatible with
      `sounddevice.InputStream` and `SimulatedSensor`)
    - Handles USB-only / non-USB3 power states (status codes 282 / 286)
    - Reads back actual achieved sample rate after `ps4000aRunStreaming` and updates
      `AcquisitionSettings.samplerate`
- **`AcquisitionSettings`** — two new PicoScope-specific fields (`sample.py`):
  - `voltage_range: int = 8` — PS4000A range index (8 = PS4000A_5V)
  - `coupling: str = 'AC'` — channel A input coupling (`'AC'` or `'DC'`)
- **`util.py`** — extended `SAMPLERATES` list to include PicoScope-relevant rates:
  100 kHz, 200 kHz, 500 kHz, 1 MHz
- **`util.py`** — added `'mV'` to `SUPPORTED_UNITS` / `UNITS` dict for raw voltage passthrough
- **`examples/ps4000a_triangle_stream_plot.py`** — standalone script:
  generates a 500 Hz triangle wave (0.5 V amplitude, +1.4 V DC offset) via the PS4000A
  signal generator, streams Channel A at 50 kHz for 100 ms, then renders a Plotly HTML
  report with Welch PSD (10 windows, 50 % overlap) and top-5 peak detection

#### Changed
- **`sensor.py`** — `VibeSensor.find()` now calls `FindPicoScope()` instead of
  `FindDigiducer()`; `VibeSensor.connect()` returns a `PicoScopeStream` for hardware
  sensors and a `SimulatedSensor` for the simulation path
- **`sensor.py`** — removed `sounddevice` import and the sounddevice reset workaround;
  renamed internal `_callback` → `_sd_callback` (simulation path only)
- **`collector.py`** — removed `sounddevice` import; broadened `PortAudioError` catch in
  `start_stream()` to `Exception`; rewrote `recieve_data()` channel extraction to handle
  both `(N, channels)` 2-D arrays and 1-D arrays, with channel index clamping
- **`sample.py`** — `VibeSample.get_accel()` wraps `convert_units` in a try/except so
  unsupported conversions (e.g. `'mV' → 'g'` before sensitivity is applied) pass through
  raw data instead of raising
- **`README.md`** — added PicoScope Integration section: architecture change, new
  `AcquisitionSettings` fields, Phase 1 data flow diagram, Phase 2 roadmap

#### Removed
- `digiducer.py` / `sounddevice` no longer used in the main acquisition path (file
  retained for reference; `FindDigiducer` still exported from `__init__.py`)

---

## [0.0.1] — early prototype (2025, sounddevice/Digiducer path)

Initial public snapshot of the **sounddevice / Digiducer** acquisition path with:

- `VibeSensor` / `SimulatedSensor` / `DataCollector` pipeline
- `VibeSample` with Welch FFT, velocity spectrum, HDF5 save/load
- `AcquisitionSettings` with enforced interdependencies
- `dearpygui` GUI with real-time time-domain and frequency-domain plots
- Butterworth highpass filter (4th-order SOS, default 10 Hz cutoff)
- Simulated bearing-defect signals (`GenerateBearingVibration_SpectralMethod`,
  `GenerateBearingVibration_TemporalMethod`)
- Comprehensive README and pytest suite
