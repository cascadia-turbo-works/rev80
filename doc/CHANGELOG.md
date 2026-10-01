# Changelog

All notable changes to **Rev80** are documented here.
Sections dated before the 2026-08 rebrand describe the project under its
former name, vibechecker, and retain it as an accurate record.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### build/arm — install on ARM computers without the GUI (2026-09-30)

#### Fixed
- **`pip install .` failed on a Raspberry Pi.** dearpygui 2.0.0 has no Linux
  ARM wheel, and pip stopped with "No matching distribution found for
  dearpygui==2.0.0" (Pi 3, Debian 13, Python 3.13, aarch64). An environment
  marker now installs dearpygui on x86-64 only (`x86_64`, `AMD64`). A plain
  `pip install .` on a PC still installs the GUI. An optional `[gui]` extra
  was rejected, because a new user then gets no GUI from `pip install .`.

#### Changed
- **A bare `rev80` without dearpygui** prints "the GUI is not available on
  this platform" and exits with code 2, instead of an `AttributeError`.
- **Tests on ARM.** `tests/conftest.py` leaves out the ten test modules that
  import dearpygui or `rev80.gui` when dearpygui is not installed, and names
  them in the report header. Four helpers or tests that import the GUI inside
  a function call `pytest.importorskip("dearpygui")`. The source checks in
  `test_session_from.py` and `test_headless_tach.py` read `gui.py` as text, so
  they also run on ARM. On a Raspberry Pi 3 (Debian 13, Python 3.13, PicoScope
  4824A with AWG loopback on channel A) the suite gives 1159 passed and 44
  skipped, hardware tests included.
- **CONTRIBUTING, "6.4 Tests on a Raspberry Pi".** `/tmp` there is a 453 MB
  tmpfs, and the monitor writer stops below 1 GiB free, so about 30 monitor
  tests fail unless `TMPDIR` points to the SD card.

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
- Plan drafts are now in `.claude/plans/`, under version control
  (`.claude/settings.json` sets `plansDirectory`). The plan for this revision
  is `.claude/plans/2026-09-29-doc-revision.md`. Earlier plans were only in
  the home directory of one machine; that is how the definitions of the
  F-numbers and D-numbers were lost.
- CONTRIBUTING does not give a test count or a list of test files. Both
  change too often, and `tests/` shows them.
- Measured values whose source is not known say "not recorded". The drift
  limit of the tachometer is tracked as R63.

### ci/plain-artifacts — release artifacts are plain files (2026-09-30)

#### Changed
- **Each release product is its own artifact, not a zip.** The workflow uses
  `actions/upload-artifact@v7` with `archive: false`, one step for each file:
  the installer `.exe`, the wheel `.whl`, the sdist `.tar.gz` and the four
  PDFs. The draft-release job uses `actions/download-artifact@v8`, which
  reads these artifacts.
- **The draft-release job also runs on a manual dispatch.** It downloads the
  artifacts and checks that there are exactly 7 files, then stops before
  `gh release create`. Before, a dispatch did not test the download step.
- **Artifacts expire after 7 days** (`retention-days: 7`, was the default
  of 90 days). The repository is public, and any signed-in GitHub user can
  download a development build while its artifacts exist.

### build — installer identity and shortcut icon (2026-09-30)

#### Fixed
- **The installer shortcuts had no icon.** `installer/rev80.iss` pointed
  `IconFilename` at `{app}\rev80.ico`, and no file is at that path.
  PyInstaller 6 puts data files under `_internal\`. The shortcuts now point
  at `{app}\_internal\assets\icons\rev80.ico`.

#### Changed
- **`AppId` is a real GUID.** It was the placeholder
  `A1B2C3D4-E5F6-7890-ABCD-EF1234567890`. Setup does not upgrade an install
  made with the old `AppId` in place: uninstall v0.1.3 once before you install
  a later version.
- **`build/rev80.spec`** no longer passes `win_no_prefer_redirects`,
  `win_private_assemblies` or `cipher`. They have no effect in PyInstaller 6.

#### Notes for the next person
- Not verified by a Windows build yet. The next release-tag build verifies it.

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

First tagged release. Each section below records one branch that this
release contains. The sections were written during development, one for
each branch.

### release fix — version tag parsing (2026-09-01)

#### Fixed
- **`setuptools_scm` could not parse a `vX.Y.Z` tag** (`a332aeb`). The custom
  `tag_regex` in `pyproject.toml` was written for the old `rc0.2` tags. An
  uncommitted attempt to widen it read `v0.1.0` as version `1.0`. The custom
  pattern is removed; the default regex of `setuptools_scm` parses `vX.Y.Z`.

#### Notes for the next person
- A rehearsal tag must be a valid version. `setuptools_scm` 10.3.4 stops on
  `v0.0.1rcx`, so the rehearsal in CONTRIBUTING.md, "11. Automated releases",
  uses `v0.0.1rc1`.

### feature/raw-stream-retention (2026-08-31)

#### Added
- **The acquisition rate is independent of the display `F_max`.** Envelope
  (demodulation) analysis needs Nyquist headroom into the 2–20 kHz range,
  where bearing housing resonances occur. `F_max` is a *display* setting.
  Users usually set it to 1–2 kHz, as ISO route monitoring does. At that
  `F_max`, acquisition removed all content above Nyquist before any analysis
  saw it. Now the raw stream keeps its full bandwidth, and `F_max` controls
  only what the Spectrum tab shows.
  - **`AcquisitionSettings.raw_samplerate` / `.raw_blocksize`**: a second,
    independent rate pair. It is fixed at `RAW_SAMPLERATE_HZ` and *not*
    derived from maxfreq. `PicoScopeStream` acquires at this rate.
    `VibeSample`, the HDF5 file and `frame_cache` hold it, and envelope
    analysis reads it. `samplerate` / `blocksize` keep their maxfreq/binsize
    derivation and are for the display only. One frame is one time window at
    two sample counts: `raw_blocksize` and `blocksize` span the same
    `acquisition_period`.
  - **`RAW_SAMPLERATE_HZ = 40000`** in this release, validated on a
    PicoScope 4424A with up to 4 simultaneous channels. (It was then set to
    `10_000` for a short time to decrease GUI lag, and then corrected to
    **25600** = 2.56 × the top preset. See hotfix/RAW_SAMPLERATE under
    [0.1.3]. That entry also fixes the display-rate derivation that this
    split exposed.)
  - **`collector.decimate_to_rate()`**: anti-alias filter and resample from
    the raw rate to the display rate before Welch. It extends the
    integer-factor decimation of `picoscope.antialias_decimate` to any
    rational ratio through `resample_poly`, because a display rate derived
    from maxfreq does not usually divide a fixed raw rate. This branch does
    not change `antialias_decimate`, because it is the electrically validated
    hardware acquisition path. Both functions use the same stopband target
    (`_AA_STOPBAND_DB`, through `scipy.signal.kaiser_beta`), not two
    independent filter designs. The ratio is
    `Fraction.limit_denominator(1000)`. The function returns the rate that
    it *achieved* (`raw_rate * up / down`), not the rate that the caller
    asked for.
    - Correction (2026-09-30): the ratio is now bounded by
      `_RESAMPLE_DENOM_LADDER` (caps 4 to 256). See experimental/profiling
      under [0.1.3].
  - **`DataCollector.eu_scaled_raw(ch, sample)`**: the high-pass-filtered
    signal at the raw rate, in the native EU of the sensor. It converts mV →
    EU but does not apply the SI/target-unit conversion or any integration
    order. Envelope analysis demodulates the raw sensor signal and has no
    target unit.
  - **`DataCollector.current_frame()`**: the `{ch: VibeSample}` dict for the
    displayed frame. It uses the same streaming-or-browse cursor selection as
    `process_samples()`. Thus a consumer that needs the raw `VibeSample`, not
    a decimated `ChannelResult`, gets the same frame without a second
    calculation of the index.
  - The **Envelope tab** now reads `eu_scaled_raw()` through
    `current_frame()`, not the decimated `ChannelResult` of
    `process_sample()`. Without this change, the display rate would still
    limit envelope analysis, the one feature that the split is for.
  - **`simulation._RawRateView`**: gives `config` to the signal generators at
    `raw_samplerate` / `raw_blocksize`. Thus `SimulatedSensor` generates *and
    reports* at the same rate as `PicoScopeStream`. Without it, the simulated
    path generated at the display rate, with no warning. Offline development
    and CI then never ran the raw→display decimation, and the simulator
    defeated the retention that it must test. The proxy does not change any
    generator, or the tests that call the generators directly with a real
    `AcquisitionSettings`.
  - **`scripts/validate-streaming-capacity`**: a continuous-streaming stress
    test against a real PicoScope. Duration, rate and channel count are
    configurable. It reports the overflow count, the rate-degradation
    transitions (the streaming-rate watchdog in `picoscope.py`) and the
    achieved against the requested raw ADC delivery rate. The exit status is
    0 only for zero overflow *and* zero degradation transitions. This script
    selected `RAW_SAMPLERATE_HZ`. Use it again to validate the value for
    different hardware or a different channel count, instead of a new
    measurement by hand.
  - Monitor config dialog: a **>10 GB/year red warning** on the storage
    estimate. The storage for each year does not decrease with a low `F_max`
    now, because each stored frame is the raw-rate capture.

---

### hotfix/cli-ux-refactor (2026-08-30)

#### Added
- **`desktop.py`: Linux desktop integration**, through `rev80
  --install-desktop-entry` / `--uninstall-desktop-entry`. It writes a
  `~/.local/share/applications/rev80.desktop` entry and a hicolor PNG icon
  set under `~/.local/share/icons/`. Then it tries to refresh the desktop and
  icon caches, so that the launcher appears without a new login. There is no
  change on Windows: the frozen build gets its Start Menu shortcut from the
  Inno Setup installer. Both commands refuse to run on other systems, so
  that they do not make a partial installation.
  - The launcher `Exec` is the `rev80` console script **in the directory of
    the running interpreter**, or else the one on `PATH`. pip puts console
    scripts there for a `--user`, venv or system install. Thus the entry
    points to the environment where rev80 is installed, not to the first
    match on `PATH`. If that directory is not on `PATH`, `install()` says so
    and prints the `export` line. The launcher works in both cases; the
    terminal command does not.
  - **The icon set is PNG, not the source SVG.** The SVG renderer of Qt/KDE
    renders this icon incorrectly, in the launcher and in the taskbar. A
    plain hicolor PNG set at fixed sizes works on all desktops.
  - `uninstall()` removes only the entry and the icons that it installed. It
    reports "nothing to do", and does not fail, when they are not there.
- **Unified `rev80` CLI**: a `headless` subcommand, top-level information
  commands (`--init-config`, `--list-devices`, `--list-sensors`,
  `--edit-config`) that need no GUI and no hardware, and `--version`.
  `rev80-headless` stays as a standalone shortcut.
- **`CONTRIBUTING.md`**: `README.md` is split into user documentation and
  development/build topics (development environment, project layout,
  testing, icon regeneration, Windows installer build).

#### Fixed
- **A non-editable `pip install .` gave a broken app.** `logging.yaml` and
  the icon font were not package data. `resource_path()` assumed a source
  checkout: it resolved relative to the *project root*, which does not exist
  after a normal install. Now `resource_path()` resolves relative to the
  directory of the package. This is correct for an editable checkout, a
  normal install and a frozen `sys._MEIPASS` bundle. A file that this
  function resolves must be under `src/rev80/` and declared in
  `[tool.setuptools.package-data]` of `pyproject.toml`. All tests run
  against an editable checkout, which is the one layout that hid this
  defect.
- **`.githooks/pre-commit` is restored**: the ruff check and the
  `_version.py` git-describe stamp. It is extended to render `doc/*.pdf`
  again from `README.md`, `CONTRIBUTING.md`, `doc/PROGRESS.md` and
  `doc/CHANGELOG.md` through `scripts/render_md.sh` when those files are
  staged. Ruff only warns here, because of 209 existing findings: the hook
  controls the backlog, not the commit.
  - Correction (2026-09-30): the hook now runs `ruff check src/ tests/` only,
    and a ruff finding stops the commit. It does not stamp the version or
    render PDFs. See build/ci (2026-09-28) under [Unreleased].

#### Changed
- **`_paths.data_dir()` is always `~/Documents/Rev80/data`**, in
  development and in frozen builds. It is not `./DEVDATA` in development.
  `DEVDATA` stays as test scratch space only, set independently in
  `tests/`. Thus a development run and a shipped run write measurements to
  the location that the user is told to look in. This fixes the data part of
  [X-08](audit-202608.md#x-08).

#### Removed
- **`ScopeSensor.target_unit`** and `effective_target_unit()`: dead code.
  The user could not set the registry field, and its default was always
  wrong. The display/integration target is a per-channel setting
  (`channel_target_units`) and does not change. One sensor can connect to
  several channels with different targets, so the target does not belong on
  the sensor definition.

---

### feature/spectral-averaging (2026-08-29)

#### Added
- **Linear power averaging of the spectrum over N frames**, with an enable
  checkbox and N in the acquisition dialog (off by default). Welch's method
  *is* linear power averaging. But the fix for
  [M-10](audit-202608.md#m-10) set `nperseg = blocksize`, so Welch runs one
  segment for each frame. Thus the chain did no averaging at all, and
  `welch_overlap` had nothing to act on. Each bin of a single-segment
  estimate is χ²(2), with a standard deviation equal to its mean. That is
  why the floor looks rough and a small line is hard to see in it.
  - `AcquisitionSettings.averaging_enabled` / `.n_averages` /
    `.n_averages_effective` (clamped to `cache_frames`: you cannot average
    more frames than the cache keeps). `ChannelResult.n_averages` reports
    the count **achieved**.
  - A derived **Avg. Window** field that reads `16 x 0.5 s = 8 s`, with a
    flag when the cache limits it. N alone is hard to interpret. The analyst
    needs to know how long the machine must stay steady. A frame is exactly
    `1/binsize` seconds.
  - A live "averaging 12 of 16 frames" line next to the peak count. It shows
    "of N" only when the delivered count is less than N.
  - `DataCollector._psd_and_overalls_for()`: the Welch PSD and 5-order
    overalls of one frame, extracted from `process_sample`. The averaging
    accumulator reaches earlier frames through this code, not through a
    second copy. Two divergent copies of one path were the direct cause of
    [M-05](audit-202608.md#m-05).
  - `tests/test_spectral_averaging.py`: 19 tests.
  - **One rule for live and replay.** The average is the N most recent
    **valid** frames up to and including the displayed frame. Live, that is
    the last N received. In browse, it is `frames[cursor-N+1 … cursor]`.
    Because the rule is the same, a step forward through a loaded file shows
    exactly what the live display showed at that time. The fix for
    [M-04](audit-202608.md#m-04) gave the high-pass the same replay property.
  - **The file holds no averaged data.** The HDF5 stores individual raw
    frames. Thus a capture made with averaging *off* can get 16 averages
    after it is loaded, and a change of N calculates again without a new
    load. Averaging is a view on stored data, not a property of it.
  - Measured with noise plus a 300 Hz line, F_max 1000 / df 2. The entry
    does not record whether the data was synthetic or from hardware.

    | N | floor CV | 1/√N predicted | floor level | line amplitude |
    |---|---|---|---|---|
    |  1 | 0.5260 | 0.5260 | 0.03387 | 0.22366 |
    |  4 | 0.2248 | 0.2630 | 0.03626 | 0.22183 |
    | 16 | 0.1189 | 0.1315 | 0.03740 | 0.21965 |
    | 64 | 0.0604 | 0.0657 | 0.03800 | 0.21878 |

    The scatter follows 1/√N. The line stays at −2% across a 64× change.
    The floor *level* increases 12% over that range. That is not drift. It
    is the convergence from the Rayleigh mean to the RMS that the
    power-domain argument predicts, and it is the clearest confirmation that
    the average is correct.

#### Notes for the next person
Each decision below has a test.
- **Power domain, never amplitude.** Average |X|², then take the square root
  at the end. On a coherent line the two methods give the same result. That
  is why this error is easy to make and the tests stay green. It shows only
  on the noise floor, where an average of magnitudes converges about
  **11% low** (a Rayleigh magnitude has mean 0.886·√μ against the RMS). The
  overall combines as `sqrt(mean(squares))` for the same reason.
- **The average is above the per-frame PSD cache.** Thus a change of N
  invalidates no per-frame work and does not need to be part of `psd_key`.
- **Overloaded records are not used in the average**, also when the
  displayed frame is the overloaded one. This is analyser practice. The fix
  for [M-05](audit-202608.md#m-05) kept them out of the trend for the same
  reason. The waveform, the scalars and the overflow flag still come from
  the displayed frame, so nothing is hidden. Only the spectral estimate is
  protected.
- **Crest factor and kurtosis are NOT averaged.** Averaging estimates a
  steady state. These two scalars exist to catch the frame that is *not*
  steady.
- **The first revert check failed to detect the wrong method.** A change
  from power averaging to amplitude averaging **passed all 17 tests**, while
  the design note called it the one thing that must be correct. Two tests
  were added that assert against *both* candidate answers, so the wrong one
  cannot pass.
- **Still open:** `welch_overlap` has no effect. Averaging across frames
  does not overlap segments *within* a frame. An overlap would give about
  double the averages for the same wall time.

---

### round 2: vibration-analysis integrity (2026-08-29)

Second remediation round of the three-discipline audit. It fixes the
vibration-engineering findings that the first round did not cover. Round 1
fixed *how* the numbers were calculated. This round fixes *what they were
calculated over*, and adds the diagnostics that an instrument in this class
needs.

#### Added
- **`envelope.py`**: envelope (demodulation) analysis. The audit named it
  the only gap that "blocks stated purpose". `envelope_spectrum()`
  band-passes around a structural resonance, takes the Hilbert magnitude,
  removes the DC term and returns an amplitude spectrum corrected for
  coherent gain. `suggest_band()` selects a demodulation band from the
  frame. The impulses of a bearing defect ring a housing resonance at
  2–20 kHz. In the raw spectrum the 1x hides them. In the envelope they
  show as a clean line at the defect rate with ±1x load-zone sidebands,
  months before the broadband overall changes. Verified end to end against
  the simulated oracle: auto band 2546–5046 Hz against a true 4000 Hz
  resonance, BPFO expected at 325.8 Hz and found at 324.0 Hz (within one
  bin) at **125× SNR**, with the 1x and the lower sideband next. New
  **Envelope** plot tab with band controls and an Auto button.
- **`_dsp.crest_factor()` / `_dsp.kurtosis()`** and
  `ChannelResult.crest_factor` / `.kurtosis`: the two impulsiveness scalars
  that a broadband overall removes by averaging. Kurtosis is non-excess
  (Gaussian = 3.0), which is the value that condition-monitoring practice
  quotes. Both are calculated on the band-limited displayed trace. They are
  never calculated on the Hann-tapered array of the overall, because its
  taper is an amplitude envelope that corrupts any peak statistic. They are
  trended, stored in HDF5 and in the monitor session, and shown on each
  result card.
- **Declared measurement band**: `AcquisitionSettings.band_fmin`/`.band_fmax`
  with resolved properties, `util.ISO_BAND_PRESETS` (ISO 20816 10–1000 Hz
  and low-speed 2–1000 Hz), a preset combo and editable edges in the
  acquisition dialog, `ChannelResult.band_fmin`/`.band_fmax`, persistence in
  HDF5 and in the monitor writer, and the band on the result card and on
  both trend axes.
- **`simulation.GenerateBearingVibration()`**: a physically realistic
  bearing-defect model. An impulse train at the defect rate rings a
  structural resonance at each impulse. The load zone modulates the
  amplitude at the shaft rate, with cumulative slip jitter. `severity=0` is
  the healthy negative control. It is now the default `SimulatedSensor`
  source.
- **`tests/test_declared_band.py`** (46), **`test_bearing_oracle.py`** (20),
  **`test_diagnostic_scalars.py`** (13), **`test_envelope.py`** (14).

#### Fixed
- **[M-06](audit-202608.md#m-06): the overall was not band-limited.** It was
  the RMS of the whole filtered block, so its band was `highpass_fc … fs/2`.
  fs/2 is 1.28×–2.56× maxfreq, depending on where the power-of-two rounding
  in `samplerate` lands: **2.048× at the 500/1000/2000 Hz presets**. The fix
  for [M-11](audit-202608.md#m-11) had already truncated the *spectrum* at
  maxfreq. Thus the number on the result card and the plot beside it
  described different bands, and nothing recorded which. Content that the
  user had excluded through F_max still reached the trend (+25% on the case
  of the audit, enough to cross an ISO 20816 zone boundary). Overalls taken
  at different F_max in different sessions were not comparable, and this
  invalidated long-term trends with no warning.
  - All five integration orders now use one masked, Hann-tapered path. Order
    0 skipped the taper before, correctly, because a passthrough does no
    multiplication in the transform domain. Band-limiting removes that
    premise: the mask *is* such a multiplication, and thus a circular
    convolution in time.
  - The untapered Parseval alternative was measured and rejected. It is
    exact in band, but a rectangular window has −13 dB sidelobes. It let a
    3× tone at 30 Hz past a 100 Hz edge at only **−22 dB**, and the overall
    increased +2.70%. Hann rejects the same tone by **−84 dB**, and by −100
    to −144 dB elsewhere, for a worst-case in-band error of 4.9e-4.
  - Hardware (4424A, AWG loopback, band 10–1000 Hz at F_max 2000): 800 Hz
    +0.0 dB, 950 Hz −0.0 dB, 1000 Hz −3.1 dB, **1100 Hz −58.2 dB**, 1300 Hz
    −58.6 dB, 1600 Hz −58.9 dB. The measured drop at the declared edge is
    58 dB.
- **ISO 2954: the high-pass −3 dB point was on the declared band edge.** A
  4th-order Butterworth designed *at* 10 Hz reads 29% low at 10 Hz. The
  standard names that frequency as the bottom of its declared band.
  `highpass_fc` is now the declared edge, and the knee is below it at
  `f_edge * (A²/(1−A²))^(−1/2N)`. At N=4, A=0.9 that is
  `0.8342 × f_edge`, so a 10 Hz edge designs at 8.34 Hz and reads −0.915 dB
  at 10 Hz. This is safe only because the band mask now removes sub-band
  energy exactly. Thus the `1/ω²` increase that the higher knee prevented
  cannot reach the result. Hardware: 100 Hz +0.00 dB, 20 Hz −0.04 dB,
  **10 Hz −1.05 dB** (was −3.0), 5 Hz −18.40 dB.
- **[M-12](audit-202608.md#m-12): the anti-alias stopband was ~55 dB against
  an expected ~80 dB.** `scipy.signal.decimate(ftype='fir')` uses a Hamming
  kernel. Its measured worst case is **−60.0 dB**, which limits the usable
  dynamic range whatever the ADC resolution. It is replaced by a cached
  Kaiser design (100 dB, 0.20 transition, 259 taps at q=4): **−111.7 dB**,
  with the passband flat to 1e-4 at F_max. A wider 0.25 transition saves 52
  taps but attenuates the passband at F_max. The longer kernel costs nothing
  at the block edges. Measured on one block against the analytic RMS:
  hamming +0.2416% against kaiser −0.0001%, because the Hann taper of the
  overall already de-weights the edges where the start-up transient is.
  Hardware A/B on the same captured samples, q=8: **+10.8 dB** at 2600 Hz
  and +10.3 dB at 3100 Hz, where the alias leakage is above the capture
  noise floor. Where the leakage is below that floor, both kernels are
  below it.
- **[M-14](audit-202608.md#m-14): the simulated bearing signal was not a
  valid oracle.** It was ten pure cosines plus white noise: kurtosis ~3, no
  impulses, no resonance carrier, no sidebands, no slip. Each diagnostic
  that this round adds depends on those properties, so the old signal could
  not validate any of them. On ten pure cosines, a broken envelope analyser
  and a correct one both return "nothing here". Also fixed: an
  operator-precedence bug. `int(freqs[-1] // bearing_multiple*running_rate)`
  binds left to right. It gave ~5000× too many iterations, and `argmin` put
  each out-of-range harmonic on the last bin. The calculation is now one
  function, `bearing_harmonic_count()`, so the two loops that need it cannot
  disagree again.
  - Two constants come from measurement, not from the textbook.
    **`resonance_q`**: impulsiveness depends on the ring-down time divided by
    the impulse period. At the textbook Q=40 the ring-down is *longer* than
    the gap between impulses. Kurtosis then reads 3.08 against a healthy
    3.09, and the fault cannot be detected. Q=8 gives τ/period 0.21 and
    separates 5.28 from 3.09. **Harmonic phase**: with one shared phase, the
    healthy kurtosis changed between 2.03 and 4.00 across seeds, only
    because of how the cosines aligned. That range overlapped the faulted
    range. Independent phases are more physical and stable.
  - The healthy control is *sub-Gaussian* (1.54–3.04), not Gaussian, and
    that is correct. A machine where running-speed harmonics dominate has
    kurtosis below 3.
- **[S-12](audit-202608.md#s-12): `SimulatedSensor` stopped with no error
  above two channels.** `simulated()` supplies a 2-element `scale`, but the
  generator gives one column for each enabled channel. Thus three channels
  raised a broadcast `ValueError` inside `_stream`, which had no
  `try/except`. The thread stopped while `_running` stayed set, and
  `is_streaming` reported a healthy stream that produced nothing, with no
  time limit. Now the scale fits the data, `_stream` is guarded and clears
  `_running` in a `finally`, and `_sample()` gives exactly one column for
  each enabled channel. (The old `max(..., N_CHANNELS)` floor gave
  single-channel configurations a phantom second channel.)
- **[H-08](audit-202608.md#h-08): `AcquisitionSettings.copy()`** copied only
  maxfreq and binsize, and lost every other field with no warning, including
  all five per-channel dicts. It now makes a round trip through
  `to_dict`/`from_dict`, so a field added there cannot be forgotten here.

#### Changed
- **The spectral anomaly hook is removed from the GUI panel**
  (`GUI_ANOMALY_HOOK_TYPES = ('rms',)`). The full entry is under
  hotfix/claude-ultrareview below.
- Stream pacing moved out of `GenerateBearingVibration_TemporalMethod` (a
  signal generator must not contain a `time.sleep`) into
  `SimulatedSensor._stream`. It paces against a deadline, so the block rate
  stays correct when generation is slow.
- `doc/PROGRESS.md` gets **R34–R38** (standards conformance), **R39**
  (spectral hook: fix or remove) and **R40** (sensor-fault detection). R40
  records that IEPE bias monitoring is **not possible on this hardware**.
  The coupler has a DC blocking capacitor, so the bias never reaches the
  scope on either coupling setting. The 4000A ranges only to ±20 V against a
  24 V supply, so even a direct tap before the capacitor would over-range.

---

### hotfix/claude-ultrareview (2026-08-29)

Integration branch for the remediation of the three-discipline audit. The
sections for the individual branches follow.

#### Changed
- **`util.py`** / **`gui.py`**: the **spectral anomaly hook is removed from
  the GUI panel**. `GUI_ANOMALY_HOOK_TYPES` restricts the hook combo of the
  monitor dialog to `('rms',)`. This change does not touch
  `SpectralThresholdHook`, the config schema or the headless front end, so a
  one-line change makes the hook available again.
  - It fires on almost every healthy frame and has not been useful in
    practice. It triggers on
    `np.any(|spec − baseline| / baseline > threshold)` across every bin in
    the band. Welch runs one segment in every shipped preset
    (`nperseg == blocksize`), so each noise-floor bin is χ²(2), with a
    standard deviation equal to its mean. On healthy data, P(some bin of
    ~2000 exceeds 1.5×) is ~1.0. Thus `consecutive_n` is a delay, not a
    defence. Also, bins 0 and 1 are set to zero for integration, so on each
    velocity/displacement channel they deviate by ~1e12 and fire
    permanently.
  - The GUI clamps a stored `spectral`/`both` (which headless still writes)
    for display only. `GUI._hook_type_to_save()` keeps the original value.
    Thus an open of the monitor dialog cannot rewrite the configuration of a
    headless user with no warning. This branch had already fixed that
    failure once, as [S-07](audit-202608.md#s-07).
  - Tracked as **R39** for a decision to fix or remove. A real fix needs a
    band RMS instead of per-bin values, a threshold in σ instead of a fixed
    %, and a default band. Thus it depends on R34.
- **`doc/PROGRESS.md`**: **R39** and **R40** added. See round 2 above.

---

### feature/peak-selection (2026-08-29)

#### Added
- **`src/rev80/peaks.py`**: spectral peak selection by significance. It
  replaces "report the top N local maxima by absolute amplitude".
  - The local noise floor is not flat. Across the 60 channel-spectra of the
    `old castle` corpus it changes by up to 7× *within one spectrum*. On
    `blower 4 - bearing DE.h5` ch2 the median local floor is 9.0 mV overall
    but 39.4 mV over 1890–2000 Hz. Thus a rank by absolute amplitude ranked
    lines by *how loud the neighbourhood is*, not by *how far a line stands
    above it*. 6 of the top 12 in that spectrum came from ripple in the
    noisy top of the band.
  - This had a diagnostic cost. 1034 and 1088 Hz are sidebands at ±25/29 Hz
    around the 1059 Hz carrier: the bearing-fault signature. They ranked 10th
    and 4th. At the shipped display count of 6, the sideband family was
    split and pushed off the table. The instrument hid the fault evidence
    behind noise ripple.
  - `local_noise_floor()` estimates the floor for each bin with a running
    median. Then `select_peaks()` gives **array-valued** `height` and
    `prominence` to one `find_peaks` call, so each bin is compared with the
    neighbourhood of its own line. Each line that passes is reported. The
    count becomes an output, and the user setting becomes a significance
    threshold in dB.
  - **Amplitude reporting does not change.** The reported value is still the
    amplitude of the maximum bin, with no frequency interpolation and no
    energy sum across a peak. The rank is still by descending amplitude.
    Significance decides *whether* a line is reported; amplitude decides its
    position in the table.
  - Measured values for the defaults:
    - **The default threshold of 9.5 dB comes from a false-alarm cliff.** On
      pure noise (2001 bins, no lines) the mean reported count is 37.9 at
      6.0 dB, **0.8 at 9.5 dB** and 0.0 at 12.0 dB.
    - **The floor window width of 65 bins is tuned against the corpus.**
      Single-frame estimators were scored against a 16-frame-averaged
      reference floor over 20 files × 3 channels × 4 frames. The result is a
      broad flat basin from 31 to 65 bins (median |error| 1.097 dB at 31,
      1.039 at 45, 1.085 at 65, 1.326 at 129). A *synthetic* spectrum with a
      smooth floor prefers 129. That disagreement is the reason to tune on
      the corpus.
    - **Edge handling: a truncated window, not the edge replication that was
      first proposed.** Replication copies one random bin 32 times, and 32
      copies of one exponential draw dominate a 65-sample median: median
      |error| 1.480 dB / p95 5.246 dB, against 0.591 / 1.829 dB truncated.
      Zero padding (`scipy.signal.medfilt`) is the worst, at −3.568 dB mean
      bias.
    - Across the corpus at the default: count median 40, p10 22, p90 49.
      Under the old top-10 rule, 6.67% of reported peaks were less than 2×
      above their local floor (18.17% with a flat-top window). The gate
      admits none.
    - `wlen` is mandatory with `prominence`. Without a bound, one broad hump
      across the band has prominence 34.6, and its apex looks like the most
      prominent feature in the spectrum.
    - Known cost, asserted by a test so that it cannot change without
      notice: **broad features are rejected on purpose.** The apex of a
      hump with σ = 40 bins has prominence 7 against a requirement of 144,
      and never reaches the table. That is correct for a line table and
      wrong if you want broadband resonances flagged. They stay visible in
      the plot only.
- **`tests/test_peak_selection.py`**: 626 lines, including an opt-in
  regression suite on the real corpus (`REV80_CORPUS_DIR`, skipped by
  default because `DEVDATA/` is gitignored).

#### Changed
- **`collector.py`**: step 6 of `process_sample()` calls
  `rev80.peaks.select_peaks`, not `find_peaks(..., distance=5)` and a top-N
  sort. `n_segments` is derived from the Welch parameters, not assumed to be
  1. Thus the median-to-mean floor correction stays correct if `nperseg`
  becomes different from `blocksize`.
- **`sample.py`**: `AcquisitionSettings.peak_threshold_db` (default 9.5),
  stored in `to_dict`/`from_dict`.
- **`gui.py`**: a "Peak Sig., dB" threshold replaces the "Peak Display"
  count spinner. The count is now only a clutter limit on the table and the
  plot markers (default 50, against a measured corpus median of 40 and p90
  of 49). A text line reports how many lines passed and whether the limit
  hides any. Without that line, a limited table looks the same as a
  spectrum that had few significant lines.

---

### fix/measurement-validity (2026-08-28)

Nine measurement-validity defects from the vibration-engineering audit
([M-01](audit-202608.md#m-01) to [M-05](audit-202608.md#m-05) and
[M-08](audit-202608.md#m-08) to [M-11](audit-202608.md#m-11)), and one
related logging defect ([S-09](audit-202608.md#s-09)).

**The root cause of the whole class was a degenerate test suite
([M-13](audit-202608.md#m-13)).** `tests/test_sample.py` sets F_max=10000,
binsize=2 → fs=32768, N=16384, so the bin spacing is exactly 2.000 Hz. It
then swept tones at 500, 1000, 1500 … 9500 Hz, **each one an exact multiple
of 2**. That is the one case where the block is periodic in N samples. The
circular-wrap discontinuity of the FFT does not occur, and the integration
error is exactly zero. `_make_dc` also set `highpass_enabled=False` by
default, so no amplitude assertion ran the filtered path. The displacement
tests asserted only on the spectrum peak, never on `result.overall`. Thus
phase 1 of this branch was a **red** commit on purpose: 110 tests, 92
failing, before any fix.

The same error was then made again, and found. Each tone in the new suite
was generated as `sin(2πft)`, so **each record started at phase 0** and
`x[0]` was exactly the DC level. That is degenerate in the same way as
bin-centred frequencies. Real hardware showed it. `tone()` now takes a
`phase` argument with a default of 0.7 rad.

#### Added
- **`src/rev80/_dsp.py`**: windowing helpers for frequency-domain
  integration, with the measured error tables that justify each choice.
- **`sample.py`**: `AcquisitionSettings.nperseg` and `.binsize_actual`: the
  Welch segment length and the bin width that the chain delivers.
- **`collector.py`**: `filter_block()`, `filtered_data_for()`,
  `reset_filter_state()`, `_seed_zi()`: persistent high-pass state for each
  channel.
- **`gui.py`**: `derive_acquisition_preview()`, the one source of the
  dialog preview.
- **`monitor/anomaly.py`**: `valid_results()`, a shared validity filter for
  the anomaly hooks.
- **`tests/test_measurement_validity.py`**: 123 tests for
  [M-01](audit-202608.md#m-01) to [M-05](audit-202608.md#m-05),
  [M-08](audit-202608.md#m-08) to [M-11](audit-202608.md#m-11) and
  [S-09](audit-202608.md#s-09). All tones are off-bin, the high-pass is
  enabled, and the tests run across block boundaries and at every preset.

#### Changed
- **`util.py`**: `MAXFREQ_PRESETS` is `[2e2, 5e2, 1e3, 2e3, 5e3, 1e4]`.
  **The 20 kHz and 50 kHz presets are removed**, and the maximum F_max is
  now 10 kHz (see [M-03](audit-202608.md#m-03)).
- **`sample.py`**: `VibeSample.samplerate`, `ChannelResult.samplerate` and
  the HDF5 `samplerate` attribute are now `float`. The true rate is usually
  not an integer.
- **`sample.py`**: `n_fft_bins` counts the **displayed** lines (DC…F_max),
  not the full one-sided transform: 1001 at the default preset, not 2049.
- **`gui.py`**: the spectrum info panel reports `binsize_actual`, and its
  label is `F_max`, not `AA`.
- **`monitor/writer.py`**: it does not have its own divergent copy of
  `_write_channel_group` now.
- CRLF → LF in `picoscope.py` and two `examples/` scripts.

#### Fixed
- **[M-01](audit-202608.md#m-01), `collector.py`: FFT wrap leakage corrupted
  every integrated overall and waveform.** `rfft` was taken on the raw,
  unwindowed block and multiplied by `(jω)^n`. The DFT treats the record as
  periodic. Unless the record is exactly periodic in N samples, there is a
  step discontinuity at the wrap point. Its spectrum is broadband and
  weighted to low frequencies, and `n < 0` amplifies it by `1/ω^|n|`. The
  code comment said that the round trip was lossless. That was true only for
  `n_ord == 0`. Bins 0 and 1 were set to zero, but the leakage stayed in bins
  2, 3, 4 … The spectrum was never affected, because Welch already applies a
  window. The Overall card, the trend, `overall_json`, the input of the
  anomaly detector and the displayed waveform were wrong.
  - Two treatments, because the consumers need different things. **Scalar
    overalls**: Hann taper, and the RMS divided by the window power gain
    `sqrt(mean(w²))`. **Displayed waveform**: a taper is not possible,
    because the envelope would be visible on the trace. It uses
    overlap-save instead: a Tukey `α=0.5` window removes the wrap
    discontinuity, and only the flat middle, where the window is exactly
    1.0, is returned. `time_vec` is truncated to match.
  - **Cost, intentional and documented:** integrated and differentiated
    traces span the middle 50% of the block.
  - Measured (1.0 unit 0-pk sine, fs=32768, N=16384): velocity overall at
    61.0 Hz **+12.25% → +0.05%**. Displacement overall at 61.0 Hz
    **+470.59% → +0.18%**, at 120.7 Hz +777.84% → +0.05%, at 501.0 Hz
    **+4473.76% → +0.00%**. On-bin 500.0 Hz was +0.00% before and after,
    which is why the old suite never saw any of this. Waveform peak,
    displacement at 501.0 Hz: +10176.68% → +0.24%.
  - Taper-width sweep at the worst case (61 Hz displacement): α 0.05 →
    +335.84%, 0.10 → +7.00%, 0.30 → +4.22%, **0.50 → +1.47%**. Reflection
    padding was tried and is much worse (+1918%): it doubles the effective
    near-DC content. Differentiation (n=+1) is verified as not affected,
    worst +0.018%.
- **[M-02](audit-202608.md#m-02), `picoscope.py`: the reported sample rate
  was not the rate in use.** `_start_streaming` calculated `actual_raw_fs`
  correctly from the interval that the driver writes back, and then
  discarded it (`self._actual_samplerate = self.config.samplerate`). The
  comment confused "hide the oversampling ratio" with "hide the actual
  rate". The driver quantises the sample interval to whole microseconds. At
  F_max=2000 the hardware runs at 8333.25 Hz while the app labelled it
  8192: **−1.70%**, and −8.25% at the 50 kHz preset (now removed).
  - **Confirmed on real hardware** (PicoScope 4424A, AWG loopback on
    channel A), with the same captured samples under two labels. A
    commanded 1000.00 Hz tone read 983.062 Hz (−1.694%), and now reads
    1000.012 Hz (+0.001%). Mean |error| across four tones:
    **1.676% → 0.034%**. The rate is reported as a float, because rounding
    would bring back a smaller version of the same error.
- **[M-03](audit-202608.md#m-03), `picoscope.py`: no anti-alias filtering at
  all above F_max = 20 kHz.** `antialias_decimate()` does nothing at factor
  1, and `max(1, int(min(OSR_TARGET, CEILING / samplerate)))` truncated
  toward zero: 1.526 → 1 at 20 kHz, 0.763 → 0 → clamped to 1 at 50 kHz. The
  50 kHz preset also requested 131072 Hz raw, **31% above** the measured
  `STREAMING_CEILING_HZ`. The module docstring says that under this
  condition the driver drops most samples with no error and still reports
  `status='OKAY'`.
  - A general-purpose IEPE accelerometer has a mounted resonance at
    25–80 kHz with 20–30 dB of gain. At F_max=20 kHz an unfiltered 50 kHz
    component folds to 15536 Hz. That is inside the displayed band, it looks
    the same as real signal, and it is *larger* than the real signal because
    of the resonance gain.
  - `_choose_osr()` now uses an explicit `math.floor` and requires
    `osr >= 2`. Only F_max ≤ 10 kHz satisfies `fs*2 <= 100 kHz`, and that is
    the reason for the preset removal above. To change this, increase
    `STREAMING_CEILING_HZ`. That requires a new measurement of the safe
    continuous streaming rate on the target hardware and channel count. A
    maxfreq outside the presets still degrades and does not fail, but it now
    logs a WARNING that names the frequency above which content aliases.
- **[M-04](audit-202608.md#m-04), `collector.py`: the high-pass filter state
  was reset to zero on every block.** `sosfilt` was called with no `zi`.
  This put a start-up transient at the head of every frame of a continuous
  stream. Measured over blocks 1–3 of a 200 Hz tone at a 10 Hz high-pass:
  acceleration waveform peak +9.41% → −0.000%, displacement overall
  +19.15% → +0.017%. With 1000 mV of residual DC offset, acceleration
  overall **+14321.74% → −0.000%**.
  - **Two regimes with different handling, because replay is not a
    stream.** Live streaming filters once for each frame in `receive_data`,
    in order, and carries the state. It caches the result on the
    `VibeSample`, because `process_sample` runs many times on the same
    frame. Replay/browse processes stored frames again, out of order, with
    no state. This is verified bit-identical forward and reverse to 12
    significant figures. Block 0 of a stream still shows real settling,
    because there is no history to carry.
  - **Follow-up, found on hardware:** `sosfilt_zi(sos) * x[0]` is the
    documented idiom of scipy. It is correct when the first sample is the
    baseline. That is true for a step and false for any oscillation. On four
    consecutive real captures the block mean was −0.06…−0.21 mV (the true
    DC), while `x[0]` was between **36…305 mV**. Under `1/ω²` that false
    step dominated: worst-block displacement error **+4297.20%** against a
    settled reference. The state is now seeded from the block mean
    (−2.22%). A warm-up pass (filter the block, then use its final state as
    its initial state) was measured and is *worse* (+61.10%): it assumes a
    periodicity that the block does not have. The synthetic tests of the
    branch missed this, because they used phase-0 sines: the same blind
    spot as the old suite.
- **[M-05](audit-202608.md#m-05), `collector.py`, `monitor/writer.py`,
  `monitor/anomaly.py`: overload and degraded frames were trended, alarmed
  on, and lost their flags on save.** Five gaps made the classic
  false-alarm mechanism. A clipped waveform reads high with harmonic
  distortion. The trend records a step change that did not occur, and the
  detector fires. After a reload, the record looks clean.
  1. The overflow bitmask came from the callback that completed a block.
     Thus the flag of a callback that raised overflow during accumulation
     was discarded. Now the flag is latched with `|=` and cleared on emit.
  2. `update_trend` ran whatever the flags were. Flagged frames are now
     excluded from the trend, but are still displayed and still flagged.
  3. `_read_frame_group` hard-coded `overflow=False` and never set
     `degraded`. Thus the flags that `_write_channel_group` stored were
     never read back.
  4. `monitor/writer.py` had a second, divergent `_write_channel_group`
     that wrote no validity flags. The divergence *was* the defect. Now
     there is one function.
  5. The anomaly hooks never read either flag. `valid_results()` now filters
     both the event evaluation and the baseline adaptation. A clipped frame
     in an EWMA baseline corrupts the reference for ~33 frames, as badly as
     an alarm on it.
- **[M-08](audit-202608.md#m-08), `gui.py`: the acquisition dialog
  calculated the sample rate with 2×, not 2.56×.** It had its own copy of
  the derivation and used the bare Nyquist minimum. At the default
  F_max=2000 it showed 4.1 kS/s, 2049 lines, 1.000 s and half the true
  memory, while the instrument ran at 8.2 kS/s, 4097 lines, 0.500 s. It now
  uses `AcquisitionSettings`. Verified equal across the full preset grid.
- **[M-09](audit-202608.md#m-09), `collector.py`: the PSD cache key did not
  include binsize and samplerate.** A change from 2 Hz to 0.5 Hz bins
  returned the same cached 2049-point, 2 Hz spectrum. The user thought the
  resolution was four times finer, and nothing had changed. Streaming hid
  the defect, because each new `VibeSample` starts with `psd_mv=None`. It
  occurred in browse/offline mode and after a file load.
- **[M-10](audit-202608.md#m-10), `sample.py`: the stated line count and bin
  width did not match the calculated spectrum.** `n_fft_bins` returned
  `blocksize//2 + 1`, while Welch used `nfft = int(samplerate/binsize)` and
  `blocksize = nextpow2(samplerate/binsize) >= nfft`. **40 of 72** preset
  combinations were wrong. The worst was F_max=200/df=20: a real resolution
  of 20.480 Hz (+2.40%), and 17 lines claimed against an actual 13. Fixed
  with `nperseg = blocksize`, and verified again: **0 of 72** mismatch. The
  existing amplitude suite was not affected: at its F_max=10000/df=2 the old
  and new `nperseg` were both already 16384.
- **[M-11](audit-202608.md#m-11), `gui.py`, `collector.py`: the spectrum was
  displayed out to fs/2, where alias rejection is ~12 dB.** The axis, the
  peaks table and `find_peaks` all ran to fs/2 = 1.28 × F_max. That is the
  transition band of the anti-alias filter: −21.8 dB at the folding
  frequency and about 0 dB at fs/2. The F_max = fs/2.56 convention exists so
  that the guard band is never shown. The spectrum is now truncated at F_max
  before peak detection. The info label had also called fs/2 the "AA"
  frequency, which read as a specification that the instrument does not
  meet.
- **[S-09](audit-202608.md#s-09), `picoscope.py`: the ADC overflow warning
  inhibit was inverted, and it flooded the log.**
  `elif ch in self._overflow_warned: remove(ch)` ran exactly when a channel
  was *still* clipping, and armed the warning again every second callback:
  measured **10 warnings from 20 callbacks**. At a 1 ms poll interval, that
  pushes every other diagnostic out of the rotating log during the run
  under diagnosis. The clear-down loop also had to move out of
  `if overflow:`, because a return to zero is the only way to see it.

---

### chore/config-consistency-ci (2026-08-28)

#### Added

- **`.github/workflows/ci.yml`**: the first CI of the project
  ([H-05](audit-202608.md#h-05), part). There was no `.github/` directory:
  300+ tests, and nothing ran them.
  - push + pull_request, `ubuntu-latest`, a matrix over Python 3.10–3.13
    (the range that the new `requires-python` floor admits).
  - checkout → setup-python → `pip install -e ".[dev]"` →
    `ruff check src/ tests/` → `pytest tests/ -q`. `fail-fast: false`. A
    concurrency group cancels superseded runs.
  - It installs `libx11-6`: `_dearpygui.so` of dearpygui links against
    libX11 at load time (confirmed with `ldd`). No GL and no X server are
    necessary, because the suite never calls `create_viewport()`.
  - The native PicoSDK driver is intentionally **not** installed. The suite
    runs against `SimulatedSensor`.
  - **Verified end to end locally**, not assumed: a clean Python 3.12 venv,
    built exactly as CI builds it, with the PicoSDK driver stubbed out and
    `DISPLAY`/`WAYLAND_DISPLAY` unset, gives 300 passed / 10 skipped. The
    `picosdk` `git+https` pin resolved and built a wheel with no special
    handling, so `--no-deps` is not necessary. `dearpygui==2.0.0` publishes
    manylinux wheels for cp310–cp313 (checked against the PyPI JSON API), so
    the wheels cover the whole matrix.
- **`util.py`**: `amplitude_scale(mode)`, `nearest_interval_preset(seconds)`,
  `canonical_hook_type(value)`, `hook_type_label(value)`,
  `ANOMALY_HOOK_LABELS`, `DEFAULT_AMPLITUDE_MODE`,
  `DEFAULT_ANOMALY_HOOK_TYPE`, `DEFAULT_RMS_ALPHA`, `DEFAULT_SPEC_ALPHA`, and
  an explicit `__all__`.
- **`util.py`**: `600: '10 min'` added to `MONITOR_INTERVAL_PRESETS`.
- **`README.md`**: the Contributing section documents the one-time
  `git config core.hooksPath .githooks` install step.
- **Tests**: 7 new files, 135 tests: `test_gui_save_config.py`,
  `test_icons.py`, `test_monitor_pretrigger_scaling.py`,
  `test_sensor_library_integrity.py`, `test_config_contract.py`,
  `test_anomaly_hook_build.py`, `test_util_small_defects.py`.

#### Fixed

- **`.githooks/pre-commit`** ([H-03](audit-202608.md#h-03)): after the
  rebrand moved the package to `src/rev80/`, the hook still ran
  `ruff check vibechecker/` and wrote `vibechecker/_version.py`. ruff exited
  non-zero against a directory that did not exist, so the hook blocked every
  commit for each person who had installed it. It now points at
  `src/ tests/` and `src/rev80/_version.py`.
  - `src/rev80/_version.py` is generated again. It read
    `rc0.4-10-g11a72f4` while `git describe` gives `rc0.5-44-g7bf4712`.
    **Shipped builds reported a version 34 commits behind, so a field bug
    report could not be connected to a build.**
  - The root cause of this unseen decay: the hook is not installed by
    default (`core.hooksPath` is the stock `.git/hooks`). The README now
    documents the install step.

- **`pyproject.toml`** ([H-04](audit-202608.md#h-04)): four defects. Each
  one broke a clean install.
  - `requires-python` was `>=3.8`, two minor versions below the real floor.
    No module uses `from __future__ import annotations`, so Python evaluates
    every annotation at import. PEP 604 `dict | None` in `sensor.py:46` needs
    3.10. `dict[str, Any]` in `config.py:219` and
    `argparse.BooleanOptionalAction` in `__main__.py:17` need 3.9. pip
    installed on 3.8/3.9 with no error, and the app raised `TypeError` on
    the first import. Raised to `>=3.10`. A search for 3.11+/3.12+
    constructs (`tomllib`, `StrEnum`, `ExceptionGroup`, `except*`,
    `TaskGroup`, `typing.Self`, `typing.override`, `itertools.batched`,
    `datetime.UTC`, PEP 695 generics) found none. Thus 3.10 is the correct
    floor, not only a safe one.
  - `dearpygui` was an optional `[gui]` extra. But `gui.py:6` and
    `icons.py:3` import it at module scope, and the `rev80` console script
    reaches both through `__main__:main`. `pip install -e .`, the exact
    instruction in CLAUDE.md, gave a `rev80` command that raised
    ImportError. dearpygui is now a required dependency. `[gui]` stays as an
    empty alias.
  - `pandas` and `matplotlib` were declared runtime dependencies, but no
    module under `src/` imported them. `matplotlib` was already in the
    PyInstaller excludes, which confirms that the runtime never needed it.
    Both are removed. (The standalone `examples/TMS_Digital_Audio.py` and
    `scripts/advanced_plots.py` still use them. They are outside the
    installed package.)
  - `numpy`, `scipy`, `h5py`, `pyyaml`, `plyer` and `pywin32` had no
    constraints ([X-04](audit-202608.md#x-04), part). Thus the contents of a
    shipped installer depended on what PyPI served that day. Lower bounds
    (not pins) are added: the oldest releases that support 3.10 and have the
    APIs in use.

- **`pyproject.toml` / CI reproducibility**: `[tool.ruff.lint]` set only
  `ignore`, never `select`. Thus ruff used its *current default* rule set,
  and that default changes between releases. On the same tree:
  **ruff 0.15.10 → 0 errors, ruff 0.16.5 → 167 errors**, with no code
  change. With `ruff` unbounded in `[dev]`, CI would have failed on an
  unchanged tree at the next ruff release. Fixed at both layers:
  `select = ["E4", "E7", "E9", "F"]` makes the rule set explicit, and
  `ruff>=0.15,<0.17` bounds the version. Both versions now report clean.

- **`gui.py`** ([S-05](audit-202608.md#s-05)): `_on_sb_save_config` called
  `h5py.File(...)`, but `gui.py` did not import `h5py` at module scope. The
  three other users each had a function-local import; this one did not. A
  broad `except Exception` caught the `NameError` and logged it as
  `"failed to patch {session_h5}"`. Thus the **"Save Config" button of the
  session browser was dead code**, and the message sent the user to disk
  permissions. The module-scope import is added, the three redundant local
  imports are removed, and the `except` is narrowed to
  `(OSError, KeyError)`.

- **`icons.py` / `gui.py`**: `test_gui_build` failed on each clone that had
  not run `scripts/build.sh`, with an unclear
  `SystemError: <built-in function pop_container_stack> returned a result
  with an exception set`. `assets/fonts/` is gitignored and build.sh fills
  it, so the font is absent on a new clone and on every CI runner.
  `icons.load()` gave the missing path to `dpg.font()`. The failure inside
  the context manager came out of `pop_container_stack`, which named neither
  the font nor the path, and it stopped all of `_create_gui()`. Now the code
  checks for the file, and uses the DPG default font with a warning when it
  is absent. *This was the existing failure between the suite and green,
  and it blocked CI.*

- **`picoscope.py`**: the PicoSDK *driver* (`libps4000a`) is a native
  install, separate from the `picosdk` Python wrapper. `picosdk/ps4000a.py`
  makes an instance of `Ps4000alib()` at import time, and raises
  `CannotFindPicoSDKError` when the driver is absent. `picoscope.py`
  imported it with no guard, so `import rev80.picoscope` was fatal without
  the driver. Reproduced with a stubbed `find_library`: the **whole suite
  stops** with 3 collection errors, not 3 modules of skips.
  `test_antialias.py` is pure DSP and failed only as a side effect. This
  also contradicted the claim in CLAUDE.md of "offline development and CI
  without hardware". Now the import degrades to
  `PICOSDK_AVAILABLE = False`, as the guard in `__init__.py:9-17` already
  does for the same import. `FindPicoScope()` returns `[]` with a warning.
  Verified: the results are the same with and without the driver.

- **`monitor/controller.py:258`** ([M-07](audit-202608.md#m-07)): the code
  read the sensor sensitivity under `sensitivity_mv_per_eu`, a key that
  exists nowhere in the codebase. `session.sensor_snapshot` holds the
  output of `ScopeSensor.to_dict()`, which writes `sensitivity`. Thus the
  `1.0` default **always** applied: the mV→EU division did not occur, and
  the pre-trigger trend points of each burst were a factor of
  `sensitivity` too large (~10x for a 10.2 mV/g sensor) against the
  post-trigger points on the same continuous plot. `engineering_units` on
  the next line used the correct key. Thus the unit *label* converted and
  the magnitude did not, which is worse than an obvious break. Now the code
  makes the sensor again through `ScopeSensor.from_dict()` once for each
  call, so the field name can be wrong in one place only. The misleading
  comment at `:246` is corrected.

- **`README.md:920` / `CLAUDE.md:127`**: both documented the same wrong
  `sensitivity_mv_per_eu` key. A user who followed the README got a
  `KeyError` in `from_dict`. The next README paragraph said correctly that
  the code divides by `sensitivity`, so the two lines contradicted each
  other. Both are fixed.

- **The sensor library could be destroyed permanently, with no warning**
  ([X-01](audit-202608.md#x-01)). `ScopeSensorRegistry._load_user` caught
  any parse failure with `except Exception: return []`, and `_save_user`
  writes what `_load_user` returned back over the file. `add()` and
  `delete()` both use that load-then-save path. Thus **one unreadable entry
  erased every calibrated sensor definition, and nothing was logged.** Two
  independent triggers reached it. The first was the wrong documented key
  above. The second was `config._atomic_yaml_write`: it used `yaml.dump`
  with the **unsafe default Dumper**, while every reader uses
  `yaml.safe_load`. A load of the `.h5` file of a colleague registers its
  sensors automatically, with no prompt and no type coercion. Thus a
  non-scalar attribute was written as a `!!python/object/apply:` tag, and
  `safe_load` then refused it. Fixed at all three layers:
  1. `config.py:159` → `yaml.safe_dump`. A value that cannot be represented
     now fails at write time with an error, and the existing file stays. This
     also closes a latent escalation: with a writer that emits object tags,
     a future change to `yaml.load` gives arbitrary code execution from a
     shared measurement file. *No RCE today.*
  2. `scope_sensor.py` → `from_dict` coerces every field and rejects
     containers and arbitrary objects, so junk cannot reach the writer.
  3. `scope_sensor_registry.py` → a bad *entry* is logged with file, index
     and content, and skipped. A bad *file* raises, so a read failure can
     never become an overwrite. Read-only callers use `all()`, which
     degrades to `[]` and logs, so a corrupt file cannot stop GUI
     construction.

- **`config.py` / `gui.py` / `headless.py`**
  ([S-07](audit-202608.md#s-07)): the GUI could not represent two monitor
  defaults, and thus rewrote them with no warning.
  - `hook_type`: `config.py:83` seeds `'rms'` (lower case). The GUI combo
    items are capitalised, and both `_on_anom_config_change` and
    `_build_anomaly_hook` compared raw strings, while `headless.py:159` used
    `.lower()`. On a new install, `'rms'` matched neither `('RMS','Both')`
    nor `('Spectral','Both')`. One open of Config→Monitor **hid both hook
    groups, built zero anomaly hooks, and disabled anomaly detection with no
    warning**, while the Enable switch was on. Now the value is canonical
    lower case everywhere, and the capitalised form is only a display label.
  - `interval_s`: `config.py:74` seeds `600`, which was not a preset. The
    widget showed "1 h", and a save wrote `3600.0` back. That **changed a
    10-minute logging interval to hourly with no warning, and discarded 5 of
    every 6 measurements.** Fixed at both ends: `600` is now a preset, and
    the fallback selects the *nearest* preset, not a hardcoded 3600.

- **`headless.py` / `gui.py`** ([S-04](audit-202608.md#s-04)):
  `_build_anomaly_hook` bound `period` only inside the
  `if hook_type in ("rms","both")` branch, but read it in the spectral
  branch. Thus a **Spectral-only configuration raised
  `UnboundLocalError`**. In headless this occurs *after*
  `collector.start_stream()`. The process stops with the PicoScope still
  streaming and not closed: the worst result for an unattended run. The two
  copies fail differently, and that is why the defect survived. `gui.py`
  reads `period` unconditionally and always raises. In `headless.py`,
  `if "spec_ewma_time" in anom_cfg and period > 0` short-circuits, so it
  raises only when that key is present, and the GUI writes exactly that
  key. `period` is now bound first in both copies.

- **The four differences between the two `_build_anomaly_hook` copies are
  removed** ([H-01](audit-202608.md#h-01), part):
  - hook-type casing (above);
  - `warmup` default 30 (GUI) against 10 (headless) → 10, as the seed in
    `config.py`. At 30 the GUI needed a baseline warm-up 3x longer, and
    nothing could fire during it;
  - `spec_n` default 3 (GUI) against 10 (headless) → 10. At 3 the GUI fired
    on a third of the evidence that headless required;
  - the EWMA-alpha fallbacks, hardcoded separately in each copy, are now
    `util.DEFAULT_RMS_ALPHA` / `DEFAULT_SPEC_ALPHA`.

- **`_pico_loader.py:24`** ([X-06](audit-202608.md#x-06)): it calculated
  `Path(__file__).parent.parent / 'drivers'` → `src/drivers`, which does not
  exist. `_paths.py:25` already gets this right with three `.parent`s.
  `ensure_pico_dlls_loadable()` returned `False` in development with no
  message, the bundled DLLs were never registered, and picosdk searched
  `%PATH%` instead. Frozen builds use the `sys._MEIPASS` branch and were not
  affected. Now the function uses `_paths.resource_path('drivers')`, because
  the duplication was the bug. It logs a warning on Windows when it returns
  False.

- **`collector.py:1187,1224`** ([H-08](audit-202608.md#h-08), part): the
  deprecated `datetime.utcnow()` is replaced with
  `datetime.now(timezone.utc).replace(tzinfo=None)`. The result is
  intentionally **naive**, to match the semantics of `utcnow()` exactly.
  See follow-ups.

- **`AMPLITUDE_SCALE.get()` fallback inconsistency**
  ([H-08](audit-202608.md#h-08), part): five call sites used two different
  defaults. The live path used `np.sqrt(2)` (`collector.py:231`, `:550`).
  The reload path used `1.0` (`collector.py:992`, `:1147`,
  `monitor/controller.py:267`). An unrecognised mode rebuilt a loaded trend
  **1.414x off** against the live trend on the same plot. All five now call
  `util.amplitude_scale()`. The fallback is `'0-P'`, because every call site
  already normalises with `or '0-P'` before the lookup. Unknown modes are
  logged. A test asserts that no `AMPLITUDE_SCALE.get()` is left anywhere in
  `src/`.

- **`util.py`** ([H-07](audit-202608.md#h-07), part): there was no
  `__all__`, so `from rev80.util import *` in `rev80/__init__.py` exported
  `np` and every imported name again at the top level. An explicit
  `__all__` is added. `data_dir` is in the list on purpose. It is imported
  into `util` from `rev80._paths`, and six call sites in
  `gui.py`/`headless.py` use it as `rev80.data_dir()`. Without it they
  would fail at runtime, not at import.

- **18 ruff errors** cleared (unused imports/variables, one `E401`)
  ([H-03](audit-202608.md#h-03)). The five unsafe `F841`s were fixed by
  hand. `old_sr` in `test_vibechecker.py:186` was kept and is now *asserted
  on*: `test_load_offline_adjusts_maxfreq` captured the samplerate before
  the load but never compared against it, so the "adjusts" behaviour of its
  name was not verified. No `noqa` was added.

#### Notes for the next person

- **`.python-version` names a virtualenv, not an interpreter**
  ([H-08](audit-202608.md#h-08), item 5). This branch changed it to `3.13`
  for a short time, because the literal `vibecheck` looked like a stale
  string. That premise was wrong: `vibecheck` is a real pyenv-virtualenv
  that holds every project dependency, and a virtualenv name there is
  correct pyenv-virtualenv usage. The change selected a bare interpreter
  with no packages and gave 15 collection errors. It was reverted. The
  `pyproject.toml` changes of the same commit stay.

---

### refactor/event-pipeline (merged 2026-04-29)

Date: the merge commit `c5cba7d` into develop.

#### Changed
- **`collector.py`**: the `callbacks` dict is removed. All consumers now read
  from `frame_cache` through `new_frame_event` and do not receive samples
  directly.
  - `collect_sample()` is rewritten: `new_frame_event.clear()` / `wait()` /
    `frame_cache[-1]`, not a `_one_shot` closure in `callbacks`.
  - `_data_callback()` is simpler: it appends to the cache and sets the
    event. There is no callback fan-out.
- **`collector.py`**: `data_callback` is renamed `_data_callback`
  (internal-only convention).
- **`gui.py`**: internal methods renamed with a leading underscore:
  `display_frame` → `_display_frame`, `poll_new_frames` →
  `_poll_new_frames`, `create_gui` → `_create_gui`.
- **`gui.py`**: the vestigial `callbacks['plots']` registrations are removed
  from `_on_load_file`. The file-load display now goes only through
  `new_frame_event` → `_poll_new_frames`. This removes a latent DPG
  thread-safety bug (a `_display_frame` call from the hardware thread).
- **`gui.py`**: `_display_frame` now calls the trend plot
  (`_update_trend_plot`) unconditionally, so the trend data of a loaded HDF5
  file shows in offline browse mode.
- **`gui.py`**: two duplicate method definitions from a merge are removed:
  `poll_new_frames` (a stale single-quote copy) and `_on_save_click` (the
  old DPG dialog version).
- **`gui.py`**: the duplicate `ACQ_NOTES` widget block in `_create_gui` is
  removed (it caused the DPG "alias already exists" crash on
  `test_gui_build`).
- **Tests**: `frame_cache` reads replace the `callbacks` references in
  `test_vibechecker.py`, `test_multichannel.py`, `test_picoscope.py` and
  `test_scope_sensor.py`.

---

### hotfix/hpf-integration-fix (2026-08-28)

#### Fixed
- **`collector.py`**: high-pass plus integration in `process_sample()` gave
  a large false value (a spurious spike at ~1–2 Hz, reported from the
  field).
  - Root cause 1: the integration transfer function (`(2πf)^n`, applied at
    all three sites: 5-order overalls, PSD, time-domain output) set only the
    exact DC bin to zero. Bin 1 (1x binsize) got the full multiplier on the
    residual near-DC energy and dominated the whole spectrum: 0.313 in/s at
    bin1 against a real 0.747 in/s tone peak in a captured reference file.
  - A first fix weighted the transfer function by the frequency response of
    the high-pass filter (`scipy.signal.sosfreqz`). This decreased bin1 by
    ~50,000x. But it is a smooth multiplication across many bins, not an
    exact removal of one bin. Under circular convolution it acted as a wide
    kernel, and it distorted the time-domain signal badly at both block
    edges.
  - The fix sets bin1 to zero directly and unconditionally (not gated on
    `highpass_enabled`). A zero in one exact FFT bin removes one Fourier
    basis component with no loss and no boundary sensitivity. The bin0 zero
    was already safe for the same reason.
  - Root cause 2 ("edge wobble", found during the work on root cause 1):
    the zero-phase high-pass (`sosfiltfilt`, added in feature/anti-alias)
    doubles the effective filter order through its forward and backward
    pass. For a low cutoff over a short block (10 Hz over a 1 s/4096-sample
    block), it overshot the raw signal by 35–45% at both block edges. The
    high-pass is changed back to causal `sosfilt` (~8–10% start-up
    transient).
  - Verified against real hardware captures (`DEVDATA/hpf-10hz.h5`, 78 Hz /
    0.75 in/s-0P test tone): bin1 is now exactly 0.0, and the overall
    amplitude is 0.760 in/s against an expected ~0.75. The residual edge
    softness decreased from 350%/246% to ~30–55%.
- **Tests**: 4 new regression tests in `test_sample.py`: bin1 set to zero
  for integration whatever `highpass_enabled` is, bin1 not changed for
  differentiation and passthrough, and a limit on the time-domain edge
  overshoot of the causal high-pass.

---

### feature/anti-alias (2026-08-26)

#### Added
- **`picoscope.py`**: a mandatory anti-alias oversample/decimate stage in
  `PicoScopeStream`.
  - Field incident: a high-frequency bearing-fault harmonic aliased into the
    low-frequency band at low apparent power and added false spectral
    energy. The root cause: the ADC ran directly at the target analysis
    rate, with no anti-alias filter.
  - The stage always oversamples the ADC (`effective_osr`, up to 4x, capped
    by `STREAMING_CEILING_HZ`). The ceiling is measured on real hardware:
    continuous `ps4000aRunStreaming`/`GetStreamingLatestValues` drops most
    samples above ~100–250 kHz, depending on the channel count, with no
    error indication. The stage applies a zero-phase anti-alias filter and
    then decimates to `config.samplerate` through the new
    `antialias_decimate()` helper. `DataCollector` and all layers above it
    see no difference.
  - Electrically verified on a PicoScope 4424A with signal-generator
    loopback. A tone above the target Nyquist aliased to a false 125 mV peak
    under naive decimation. The real pipeline suppresses it by 61.9 dB. An
    in-band tone near maxfreq passes with no attenuation.
- **`picoscope.py`**: a second, independent streaming-rate watchdog sets
  `.degraded` when the USB throughput stays below
  `_RATE_DEGRADED_THRESHOLD` of the requested raw rate. This is the same
  silent data-loss mode that the anti-alias work found. The silence
  watchdog cannot see it, because callbacks continue with `status='OKAY'`.
  It never triggers `_try_recover()` on purpose: the cause is a USB/bus
  bandwidth ceiling, not a device hang.
- **`sample.py`**: `VibeSample`/`ChannelResult` get a `degraded: bool`
  field.
- **`tests/test_antialias.py`**: regression tests for
  `antialias_decimate()`: an aliasing tone suppressed >20x against naive
  decimation, factor=1 does nothing, a real low-frequency tone survives
  intact, and channels are handled independently.
- **`tests/test_picoscope.py`**: `TestRateDegradationWatchdog` tests
  `_check_rate_degradation()` with a monkeypatched clock
  (healthy/degraded/recovery), and confirms that `_try_recover()` is never
  called for this condition.

#### Changed
- **`sample.py`** / **`util.py`**: `samplerate` now derives from
  `nextpow2(2.56 * maxfreq)`, not 2x. This gives >=28% Nyquist margin for
  the transition band of the anti-alias filter (the ratio that commercial
  FFT vibration analysers use). `MAXFREQ_PRESETS` loses the 100k/250k/500k
  Hz entries. A hardware measurement showed that these already exceed the
  continuous-streaming ceiling of this PicoScope and corrupt the captured
  data with no warning.
- **`collector.py`**: `receive_data()` copies the `degraded` flag of each
  incoming frame to the `VibeSample`/`ChannelResult` of every channel, and
  stores it in saved `.h5` files with `overflow`. The new
  `DataCollector.stream_degraded` property is the equivalent of
  `is_streaming`.
- **`collector.py`**: the lowpass Butterworth block of `process_sample()`
  is removed (anti-aliasing is now mandatory upstream in `PicoScopeStream`).
  The high-pass filter changes from causal `sosfilt` to zero-phase
  `sosfiltfilt` (reverted in hotfix/hpf-integration-fix, above).
- **`gui.py`**: the Lowpass checkbox and field are removed from the
  acquisition dialog. The status line shows the automatic AA cutoff, not
  the "LP ..." text. A warning line appears when the stream is degraded.

#### Removed
- The user fields `lowpass_enabled`/`lowpass_fc`. They ran after the ADC had
  sampled the signal, so they could never prevent aliasing. Anti-aliasing
  is now mandatory and occurs at capture time.

---

### rebrand-to-rev80 (2026-08-19 – 2026-08-28)

From this branch on, the product name is **Rev80** (formerly vibechecker).
The earlier sections below keep the name "vibechecker" as an accurate
record of the codebase at that time.

#### Changed
- Rebrand vibechecker → Rev80 across the codebase, the packaging and the
  documents.
  - The package moved from `./vibechecker/` to `./src/rev80/` (src layout;
    history kept through `git mv`). All imports changed from
    `from vibechecker` to `from rev80`.
  - `pyproject.toml`: package name `rev80`, entry points
    `rev80`/`rev80-headless`, `where=["src"]`, `pythonpath=["src"]`.
  - The user data directory moved to `~/Documents/Rev80/`. The config
    directory moved to `~/.config/rev80/`.
  - The GUI title and label, the CLI `prog` name, the installer
    (`installer/rev80.iss`), the build spec (`rev80.spec`) and the icons
    (`assets/icons/rev80.ico`/`.svg`) are renamed to match. The README and
    PROGRESS documents are updated.
  - **`_paths.py`** fix: the base of `resource_path()` needed one more
    `.parent` after the src-layout move added a directory level (it
    resolved into `src/`, not the project root). `logger.py` now resolves
    `logging.yaml` relative to its own file, not through `resource_path()`.
- **`build/collect_pico_dlls.py`** / `build.sh`: search a bundled `vendor/`
  folder for the PicoSDK DLLs first. Thus a system-wide PicoSDK install is
  not necessary before a build.
- The repository root is reorganised. Loose documents (`CHANGELOG.md`,
  `PROGRESS.md`, `VibeGui Project.md`) moved into `doc/`. Development
  scripts (`build.sh`, `render_progress.sh` → `render_md.sh`,
  `runtimes.ipynb`) moved into `scripts/`. `rev80.spec` moved into `build/`
  next to `collect_pico_dlls.py`, and its `ROOT` now resolves from the
  parent of `SPECPATH`, so spec-relative paths still point at the
  repository root. The stale `requirements.txt` and `picosdk-install.md`
  are removed.
- `.gitignore`: the PyInstaller build-output exclusion is corrected. The
  reorganisation had made its path stale.
- The project management documents are reviewed: outstanding requirements
  and technical-debt items are updated.

---

### hotfix/welch_leakage (2026-08-18)

#### Fixed
- **`collector.py`**: the Welch window functions (Hann, Blackman-Harris and
  others) cause spectral leakage. It increased the reported overall
  vibration level by a factor that depends on the window (Hann: √(3/2)).
  The overall amplitude now comes from the RMS of an exact-inverse
  time-domain reconstruction, not from a sum of spectral peaks.
  - The 5-order (`-2`…`+2`) mV RMS overalls are now calculated through
    `irfft` of the integration-scaled `rfft`, as
    `sqrt(mean(time_ord**2))`, not `sqrt(sum(psd_ord**2))`. They use the
    same plain, unwindowed `rfft` that the time-domain output step already
    calculates once, so the round trip is lossless.
  - The target-unit overall (step 7) now uses the cached 5-order mV RMS
    column, and does not derive it from the spectrum again.
- **`collector.py`**: `process_sample()` now guards against a resolved
  integration order outside `[-2, 2]`. Before, an out-of-range order
  indexed the wrong overalls column with no warning, and gave false
  scaling. It now logs an error and returns `None` for the frame.

---

### feature/monitor_mode (2026-05-28 – 2026-06-30)

#### Added
- **`monitor/` package**: the Monitor Mode interval datalogger.
  - `gate.py`: `IntervalGate` with snap-to-grid scheduling and burst mode.
  - `session.py`: the `MonitorSession` frozen dataclass (later with
    `acq_snapshot`/`channel_snapshot`/`sensor_snapshot` and
    `cooldown_enabled`/`cooldown_s`).
  - `anomaly.py`: the `AnomalyHook` protocol and a `NullAnomalyHook` stub.
  - `writer.py`: `MonitorWriterThread` (daemon, disk-space guard).
  - `controller.py`: `MonitorController`, which controls the gate, the
    writer and the anomaly hook.
  - `gui.py`: the Monitor card with a config tab and arm/disarm controls
    (relabelled and changed many times in the branch; see Changed).
  - 51+ new tests in `test_monitor_gate.py`, `test_monitor_index.py` and
    `test_monitor_controller.py`.
- Session storage went through several revisions in the branch:
  - v4: monitor captures write the standard metadata+frames HDF5 layout, so
    `collector.load_data()` opens them directly with no adapter. A
    `capture_trigger` root attribute tells monitor files from manual saves.
  - v5 (Phase 2 storage redesign): one `session.h5` for each session
    (`DEVDATA/monitor/{session_id}/`) replaces the per-capture files and the
    SQLite index. `/monitor/{N}/` groups hold interval captures,
    `/burst/{burst_id}/{frame_index}/` groups hold burst events, and the
    `/burst.attrs['burst_list']` JSON lets the browser show the list without
    a load of frame data.
- **Burst capture**: manual (`trigger_burst()`) and anomaly-triggered
  bursts, with a pre-trigger ring buffer.
  - The session browser is rewritten as a modal with two tabs (Monitor /
    Burst). `resize_frame_cache()` now expands the cache before a load, so
    all captures in a session can be browsed, not only the most recent
    `cache_frames`.
  - Alignment fixes made during the branch:
    - The pre-trigger snapshot counted the trigger frame twice.
    - The `_burst_all_results` indices did not align with the pre-trigger
      frames.
    - Burst `rel_time` is relative to the trigger frame (t=0), not to the
      session.
    - The frame cache is resized before burst frames are loaded. Before,
      the default 32-frame cache removed pre-trigger frames with no
      warning.
    - Pre-trigger overalls are calculated at capture time
      (`_compute_pretrigger_overalls()`), not processed again at load.
    - The disk-usage estimate includes the pre-buffer, not only the burst
      duration.
    - Trend unit conversion works again when a loaded session is browsed.
      The session-load path did not connect the sensors, so channels showed
      raw mV.
- **Anomaly detection hooks** (`monitor/anomaly.py`)
  - `RmsThresholdHook`: an EWMA self-calibrating baseline for each channel.
    It triggers when `|current - baseline| / baseline` exceeds a threshold
    for N consecutive frames. It records the start time of the streak, so
    `trigger_time`/`trigger_rel_time` give the anomaly onset, not the
    confirmation frame.
  - `SpectralThresholdHook`: first a stored-baseline bin-by-bin dB
    comparison with an optional fmin/fmax band. Later rewritten to an EWMA
    baseline for each bin, with a percentage threshold and the peak
    frequency in the trigger reason.
  - `CompositeAnomalyHook`: tries each hook in order and returns the first
    event. It sends `reset_baseline()` to all children.
  - `FixedThresholdHook`: independent upper and lower level triggers, with
    unit conversion through `UNIT_TO_SI`.
  - The `ewma_alpha_from_time(tau, dt)` helper lets the user give an EWMA
    setting as a time constant τ (seconds), not as the opaque `alpha`
    value. The GUI shows a live label with the calculated α.
  - Post-burst cooldown replaces arm/disarm. The anomaly hook is given once
    at `start()` and is active for the whole session. After a burst, a
    cooldown deadline stops further triggers, and interval captures
    continue as normal.
  - GUI: an Anomaly Detection section in the Monitor config tab (hook-type
    combo, RMS/Spectral/Fixed-level/cooldown settings groups, tooltips on
    all of them). "Reset Baseline" replaces the Arm/Disarm button.
  - 15+ new tests (`test_monitor_anomaly.py`): warm-up gating,
    consecutive-N triggers, baseline set/reset, composite fall-through,
    streak tracking, cooldown.
- **Headless CLI** (`headless.py`): the interval datalogger without the
  GUI.
  - `python -m vibechecker.headless` / the `vibechecker-headless` console
    script: finds a PicoScope (or `--device sim`), loads the saved device
    config, starts the stream, runs `MonitorController`, prints periodic
    status, and shuts down cleanly on SIGINT/SIGTERM with a session
    summary.
  - The `--headless` flag sends `__main__.py` into headless mode. It uses
    the collector/monitor/sample/picoscope pipeline of the GUI path with no
    change.
  - `--from-file` loads an `.h5` file or a monitor session directory at
    start (GUI and CLI). `--[no-]autodetect` controls device discovery. Its
    default is off when `--from-file` is given.
  - `--init-config` seeds `~/.config/vibechecker/` with `acquisition.yaml`
    and `devices/picoscope-defaults.yaml`.
  - Monitor/anomaly settings made once in the GUI are stored in the device
    config. Headless reads them back as defaults, and CLI arguments
    override them.
  - `dearpygui` is an optional dependency (`pip install -e .` for
    headless-only installs; `pip install -e '.[gui]'` for the GUI).
- **`drivers/install-picoscope4000a-driver.sh`**: a Linux install script for
  the PicoScope driver. After the install it registers `/opt/picoscope/lib`
  with `ldconfig`.
- **`gui.py`**: a Frame info card in the right panel. The timestamp, block
  size and sample rate are always shown. Burst browse adds: the frame time
  relative to the trigger, the burst ID, the trigger type/timestamp and the
  maximum overall of each channel. The session ID shows when a session or
  burst is browsed.
- **`gui.py`**: CommitMono Nerd Font icons in the left panel (card headers,
  action buttons, browse arrows). The first build downloads the font
  automatically, and the frozen app bundles it.
- **`gui.py`**: global keyboard shortcuts: Ctrl+A autoscale, Ctrl+K
  start/stop, Ctrl+S save, Ctrl+O load, Ctrl+Q quit, ←/→ frame browse (live
  only).
- **`gui.py`**: a configurable frame cache depth
  (`AcquisitionSettings.cache_frames`, default 32), with the derived
  recording window and memory use.

#### Changed
- **`config.py`**: the layout is split into `acquisition.yaml`
  (maxfreq/binsize/monitor/anomaly, for each instance),
  `devices/picoscope-<model>-<SN>.yaml` (channels + siggen, for each
  device) and `devices/picoscope-defaults.yaml` (the new-device template).
  `device_config_path()` now takes `(model_name, serial_number)` and makes
  human-readable file names. There is no migration path: delete
  `~/.config/vibechecker` to seed the files again.
- **`collector.py`**: overalls are now always calculated over the full FFT
  spectrum. The `trend_fmin`/`trend_fmax` "Trend Frequency Window"
  band-limit setting is removed completely (dataclass field, config
  default, UI tags, dialog widgets, tests).
- **`collector.py`**: `nperseg` is clamped to the signal length in the
  Welch PSD call, to prevent false warnings on short blocks.
- **`collector.py`**: `_load_v3`/`_load_v4` are merged into one
  `load_data()` method. This fixes a v4 load crash: the old `_load_v4`
  called `_load_v3`, which read a `data` key that v4 trend groups do not
  have.
- Version tooling: a `post-commit` hook wrote the git-describe version.
  It moved later to `pre-commit`, so that `_version.py` is in the commit
  that changes it. The installer version now comes from `_version.py` at
  build time and is not hardcoded in the `.iss` file.
- Build fixes made during the branch:
  - UPX is disabled (it corrupted the PE import table of the frozen
    `python3XX.dll`).
  - `pandas` is removed (it caused a `pytz` version-detection failure in
    frozen builds; the peaks table now uses `list[tuple]`).
  - The Windows filechooser dependency of `plyer` (`win32com`/`pywintypes`)
    is added to the hidden imports.
  - The `pyyaml` hidden-import name is corrected (`yaml`, not `pyyaml`).
  - `dist/` is cleaned, and a running instance is stopped, before a
    rebuild.
  - `assets/` is bundled into the frozen app (the font was missing, which
    caused a crash at start).
  - The PyInstaller cache is not deleted by default now
    (`./build.sh all clean` forces it).
  - The Inno Setup architecture identifier is `x64compatible`.

#### Removed
- `monitor/index.py` (SQLite session index): the single-`session.h5` v5
  layout replaces it.
- Arm/disarm as a user concept. Anomaly detection now runs for the whole
  monitored session, and only the post-burst cooldown gates it.

---

### refactor/mv-domain-trend (2026-05-05)

#### Changed
- **`sample.py`** / **`collector.py`**: `VibeSample` now stores raw mV at
  all stages. All sensitivity conversion, Butterworth filtering and Welch
  PSD calculation moved into `DataCollector.process_sample()`.
  - `VibeSample`: `process()`, `_convert_time_domain()`, `push_sample()`,
    `save()` and `load()` are removed. It gets `overflow: bool` and the
    cached `psd_mv`/`freq_hz`/`_psd_config_key`/
    `overall_ampl_by_integration_order` (5,) mV RMS fields.
  - `ChannelResult` gets an `overflow` field.
  - `receive_data()` becomes a pure mV pass-through (no sensitivity, no
    filter).
  - `process_sample(ch, sample)`: filter → Welch PSD (cached) → 5-order
    overalls (cached) → sensitivity + SI + integration → `ChannelResult`.
  - `process_samples()` becomes the frame dispatcher of the collector. It
    appends to the trend only during streaming, and uses a `-1` cursor index
    in browse mode.
  - Trend storage changes from a dict of lists to
    `dict[int, {rel_times: ndarray, orders: ndarray(M,5)}]`. The new
    `get_trend_for_display()` holds the unit/sensitivity/amplitude-mode
    conversion in one place, so `gui.py` does not import `util` for it.
  - `get_active_eu()` returns `'mV'` immediately when no `ScopeSensor` is
    assigned. This prevents a meaningless unit conversion before the
    sensitivity is known.
  - HDF5 v4: a per-channel `(M,5)` orders matrix and per-channel
    `rel_times`. A v3 file is promoted to the v4 trend structure at load
    (order 0 only).
- **`gui.py`**: the display loop is simpler, around
  `process_samples()`/`get_trend_for_display()`.
  `_compute_channel_result()` is removed. Overflow comes from
  `result.overflow`, not from a bitmask.
- **`picoscope.py`**: `start()` now also calls `_setup_siggen()`. Before,
  only the reconnect path in `_try_recover()` called it, so the signal
  generator did not start on the first `stream.start()` call.
- **`collector.py`**: overalls are calculated over the full FFT spectrum
  unconditionally. (feature/monitor_mode later removed
  `trend_fmin`/`trend_fmax` on this basis.) The HDF5 load paths are merged.

#### Added
- **`gui.py`**: global keyboard shortcuts (Ctrl+A/K/S/O/Q, arrow-key frame
  browse). feature/monitor_mode extended them later.
- **`gui.py`**: a configurable frame cache depth with a
  recording-window/memory display. `DEFAULT_CACHE_FRAMES` comes from
  `config._BUILTIN_DEFAULTS`. feature/monitor_mode extended it later.
- Build tooling: a post-commit hook writes the git-describe version, and the
  installer gets it through `_version.py`. PyInstaller/Inno Setup fixes for
  UPX corruption, a `vibechecker.spec` merge conflict, `pandas`/`plyer`
  bundling, and the `pyyaml` hidden-import name.

---

### feature/windows-build (2026-03-29 – 2026-05-27)

#### Added
- **`_paths.py`**: cross-platform path handling (Phase 1):
  `sys._MEIPASS`-aware `data_dir()`, `log_dir()` and `resource_path()`.
  Standard-library `pathlib` replaces the third-party `path` library in all
  modules. `SAVEDIR`/`DataCollector.datadir` go to
  `~/Documents/vibechecker/data/` in frozen builds.
- **`_pico_loader.py`** / `build/collect_pico_dlls.py`: PicoScope driver
  bundling (Phase 2). A Windows script finds `ps4000a.dll`/`picoipp.dll`
  in the PicoSDK install (registry and default paths), validates the 64-bit
  PE header, and copies them to `drivers/`. `_pico_loader.py` registers
  that directory through `os.add_dll_directory()` before the `picosdk`
  import, for the frozen (`sys._MEIPASS/drivers/`) and the development
  layouts.
- **`vibechecker.spec`** / `installer/vibechecker.iss` / `build.bat` /
  `build.sh`: the PyInstaller + Inno Setup build pipeline (Phase 3). A
  one-dir PyInstaller build bundles `logging.yaml`, the driver DLLs and the
  dearpygui data. The Inno Setup 6 script makes a 64-bit, non-admin install
  to `%LOCALAPPDATA%`, with a soft check that PicoSDK is present and Start
  Menu/desktop shortcuts.
- App icon: a placeholder icon in the PyInstaller spec and the Inno Setup
  script (real artwork later).
- **`README.md`**: new structure for users, contributors and Windows
  builders: a Windows install section (PicoSDK + installer), a
  cross-platform source install section, a Contributing section
  (development environment, project layout, icon change guide), and a full
  prerequisites table (Python, Git for Windows, PicoSDK, Inno Setup).

#### Fixed
- PicoSDK 11.x is detected by the DLL path when the registry key is absent.
- `logging.yaml` moved into `vibechecker/`, so `resource_path()` resolves it
  correctly in development and frozen builds.
- The `scipy` submodule excludes are removed from the PyInstaller spec.
  `scipy.signal` uses `scipy.linalg` internally, and the build failed
  without it.
- Debug `print()` statements are removed from `gui.py`/`__main__.py`. The
  Inno Setup branding (publisher, copyright, license) is updated.
- The Inno Setup Compiler (`ISCC`) lookup uses the correct install
  `APPDATA` directory.
- The icon assets moved to `assets/icons/`.

#### Changed
- **`picoscope.py`**: multi-device enumeration through
  `ps4000aEnumerateUnits` replaces `FindPicoScope`, and opens each device
  by serial number. `PicoScopeStream` gets `_open_unit_by_serial`, so it
  opens the correct device when more than one scope is connected.
- **`picoscope.py`**: `_probe_channel_count` replaces the hand-maintained
  `_channels_for_model` lookup table. It calls `ps4000aSetChannel` for
  channels A–H and counts the successes. Thus a future hardware variant
  reports its channel count with no code change.
- Ruff lint fixes in `picoscope.py`, `sample.py` and `util.py`.

---

### feature/channel-naming (2026-04-03 – 2026-04-13)

#### Added
- **`sample.py`**: `AcquisitionSettings` gets the `channel_names` and
  `channel_target_units` dicts with the `name_for(ch)`/`target_unit_for(ch)`
  helpers, stored in `to_dict`/`from_dict`. Later extended with the
  `channel_amplitude_modes`, `channel_couplings` and
  `channel_voltage_ranges` dicts and their typed accessors
  (`amplitude_mode_for`, `coupling_for`, `voltage_range_for`).
- **`gui.py`**: offline post-analysis mode.
  - `load_data` sets `enabled_channels` and `maxfreq` from the file
    contents.
  - Plot series, axes and the results panel are updated after a load.
  - The connection summary shows "File Loaded" (yellow) with the frame and
    channel count.
  - The trend plot gets a vertical cursor line at the browsed frame.
  - The acquisition buttons are disabled when no device is connected.
- **`gui.py`**: native file dialogs through `plyer.filechooser` (kdialog on
  KDE, native Win32) replace the DPG file dialog. `SAVEDIR` is resolved to
  an absolute path, so the dialog opens in the correct location. The
  browse-waveform controls go through one `_on_browse` dispatcher.
- **`gui.py`**: new design of the Channels tab.
  - Each channel has a collapsing header row (color swatch and name, then
    coupling/range/sensor on a second line). A theme colors it when enabled
    and makes it grey when disabled.
  - The enabled state moved outside the collapsing header, with a
    target-unit/amplitude indicator on the header.
  - An amplitude-mode combo is added for each channel.
  - Color indicators use `drawlist`/`draw_rectangle`, not a `■` glyph (the
    app font did not render it).
- **`util.py`**: the `UI_Elements` tag registry is extended. Named
  constants replace hardcoded `DEVSETUP_*`/`SREG_FIELD_*` strings. New tags
  for the new channel rows (`scope_ch_name_text`, `scope_ch_hdr_theme`,
  `scope_ch_amplitude_mode`).
- The File Handling card gets a multiline Measurement Notes widget. A save
  reads it, and a load fills it.
- Tooling: `ruff` in the development dependencies, with a
  `.githooks/pre-commit` hook (activate with
  `git config core.hooksPath .githooks`). `pyproject.toml` sets
  line-length 120 and ignores E402/E701.

#### Changed
- **`collector.py`**: the HDF5 format changed from v1 → v2 → v3 in the
  branch.
  - v2: metadata moved into `.attrs` (`/acquisition`, per-frame and
    per-channel groups), not child datasets. `_load_v1` is kept for
    backward compatibility.
  - v3: a structured `/metadata/` group. `/metadata/acquisition` holds
    scalars only. `/metadata/scope_sensors/{id}` holds the sensor library,
    with each unique sensor stored once. `/metadata/channels/{ch}` holds
    name/unit/coupling/voltage_range/sensor_id/target_unit/amplitude_mode.
    `/frames/{i}/{ch}/data` stores raw samples only. `/trend/rel_times`
    becomes a shared axis, with `/trend/{ch}/data` for each channel.
    `load_data` calls `_load_v3` only; `_load_v1`/`_load_v2` are removed.
    `save_data` overwrites an existing file and does not return early.
  - Fixed a file-mode bug: the channel list in the config dialog came from
    `enabled_channels`, not from the frame cache. Thus a disabled channel
    disappeared from the dialog completely.
- **`scope_sensor.py`**: the `amplitude_mode` field is removed. It is a
  per-channel acquisition setting, not a sensor property, and it moves to
  `AcquisitionSettings.channel_amplitude_modes`. A load ignores the key in
  old files with no message.
- **`gui.py`**: config dialog scroll fix. The outer window gets
  `no_scrollbar`/`no_scroll_with_mouse`. The tab bar and the content of
  each tab are in their own `child_window`, so each tab scrolls on its own.
  The Close button stays outside the tab area.
- **`sample.py`**: spectral peak detection. The default display count
  increases (3 → 6), with the label "Peak Display". The minimum peak
  distance changes from a value relative to the spectrum length to a fixed
  5 bins.

---

### refactor/queue-handoff (2026-04-08)

#### Changed
- **`collector.py`** / **`gui.py`**: the collector and the GUI are
  decoupled with `threading.Event`. This is the first step of the
  refactor/event-pipeline cleanup above.
  - `DataCollector.new_frame_event`: `data_callback` and
    `reprocess_last_block` set it.
  - `GUI.poll_new_frames`: polls the event on each render tick and takes
    `frame_cache[-1]`.
  - A manual render loop replaces `dpg.start_dearpygui()`.
  - The `callbacks['plots']` registration is removed: the GUI does not
    connect directly to the collector for display. The one-shot capture of
    `collect_sample` still used the `callbacks` dict at this point
    (refactor/event-pipeline removed it later).
  - GUI lag has no effect on the data: the render always shows the latest
    frame and skips the frames between. All frames stay in `frame_cache`
    for browse, whatever the render rate.
- **`gui.py`**: `poll_new_frames` is guarded against a rare `IndexError`
  race, when the hardware thread shifts the deque between `len()` and the
  index. It skips the frame with no message, because new data arrives on
  the next tick.
- **`README.md`** / **`CLAUDE.md`**: the architecture documents describe
  the event-based collector↔GUI decoupling. The event-signal + poll-loop
  pattern replaces the callback diagrams. Stale `sounddevice` references
  are removed.

---

### feature/picoscope (2026-03-13)

Date: commit `cf89848` (Phase 1 backend). The git history has no merge
commit for this branch.

#### Added
- **`vibechecker/picoscope.py`**: PicoScope 4000A acquisition backend
  (Phase 1).
  - `FindPicoScope()`: finds the connected PS4000A units. It returns dicts
    compatible with `VibeSensor` with `unit=['mV']`, the same interface as
    `FindDigiducer`.
  - `PicoScopeStream`: a background polling thread around
    `ps4000aRunStreaming`.
    - It converts ADC counts → mV through `adc2mV` on each driver callback.
    - It accumulates chunks of variable size into exact `blocksize` blocks,
      and then calls `DataCollector.recieve_data`.
    - It implements the `.active / .start() / .stop() / .close()` interface
      (compatible with `sounddevice.InputStream` and `SimulatedSensor`).
    - It handles the USB-only / non-USB3 power states (status codes 282 /
      286).
    - It reads back the achieved sample rate after `ps4000aRunStreaming`
      and updates `AcquisitionSettings.samplerate`.
- **`AcquisitionSettings`**: two new PicoScope fields (`sample.py`):
  - `voltage_range: int = 8`: the PS4000A range index (8 = PS4000A_5V).
  - `coupling: str = 'AC'`: the input coupling of channel A (`'AC'` or
    `'DC'`).
- **`util.py`**: the `SAMPLERATES` list gets PicoScope rates: 100 kHz,
  200 kHz, 500 kHz, 1 MHz.
- **`util.py`**: `'mV'` added to `SUPPORTED_UNITS` / the `UNITS` dict for a
  raw voltage passthrough.
- **`examples/ps4000a_triangle_stream_plot.py`**: a standalone script. It
  generates a 500 Hz triangle wave (0.5 V amplitude, +1.4 V DC offset)
  with the PS4000A signal generator, streams Channel A at 50 kHz for
  100 ms, and makes a Plotly HTML report with a Welch PSD (10 windows,
  50 % overlap) and top-5 peak detection.

#### Changed
- **`sensor.py`**: `VibeSensor.find()` calls `FindPicoScope()`, not
  `FindDigiducer()`. `VibeSensor.connect()` returns a `PicoScopeStream` for
  hardware sensors and a `SimulatedSensor` for the simulation path.
- **`sensor.py`**: the `sounddevice` import and the sounddevice reset
  workaround are removed. The internal `_callback` is renamed
  `_sd_callback` (simulation path only).
- **`collector.py`**: the `sounddevice` import is removed. The
  `PortAudioError` catch in `start_stream()` is broadened to `Exception`.
  The channel extraction of `recieve_data()` is rewritten for
  `(N, channels)` 2-D arrays and 1-D arrays, with a clamp on the channel
  index.
- **`sample.py`**: `VibeSample.get_accel()` puts `convert_units` in a
  try/except. Thus an unsupported conversion (for example `'mV' → 'g'`
  before the sensitivity is applied) passes the raw data through and does
  not raise.
- **`README.md`**: a PicoScope Integration section: the architecture
  change, the new `AcquisitionSettings` fields, the Phase 1 data flow
  diagram and the Phase 2 roadmap.

#### Removed
- `digiducer.py` / `sounddevice` are not used in the main acquisition path
  now. The file stays for reference, and `__init__.py` still exports
  `FindDigiducer`.

---

## [0.0.1] - 2025

Early prototype on the sounddevice/Digiducer path. This version was never
tagged. The CHANGELOG records only the year.

First public snapshot of the **sounddevice / Digiducer** acquisition path,
with:

- the `VibeSensor` / `SimulatedSensor` / `DataCollector` pipeline
- `VibeSample` with Welch FFT, velocity spectrum, HDF5 save/load
- `AcquisitionSettings` with enforced interdependencies
- a `dearpygui` GUI with real-time time-domain and frequency-domain plots
- a Butterworth highpass filter (4th-order SOS, default 10 Hz cutoff)
- simulated bearing-defect signals (`GenerateBearingVibration_SpectralMethod`,
  `GenerateBearingVibration_TemporalMethod`)
- a comprehensive README and a pytest suite
