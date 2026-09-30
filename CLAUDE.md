# CLAUDE.md

This file gives guidance to Claude Code (claude.ai/code) for work in this
repository. It holds the invariants, the reason for each, the known-bad
areas and the "do not" rules. The evidence and the architecture are in
`CONTRIBUTING.md`. The user manual is `README.md`.

## What this is

**Rev80** (package `rev80`) is a vibration analyser for predictive
maintenance. It reads IEPE accelerometers through a **PicoScope 4000A** over
USB. It has a dearpygui GUI and a headless interval datalogger
(`headless.py`). `SimulatedSensor` replaces the hardware for development and
CI.

This is an instrument: the numbers are the product. **Green CI is not
evidence of measurement correctness.** The August 2026 audit found the full
suite passing while the measurements were wrong, because every DSP test used
a bin-centred tone, where the FFT wrap error is zero.

| Document | Holds |
|---|---|
| `CONTRIBUTING.md` | Environment, layout, architecture (section 4), Design evidence E1 to E20 (section 5), testing, build, release, documentation rules (section 12) |
| `README.md` | User manual: operation, configuration files, data-file layouts, accuracy and limits |
| `doc/CHANGELOG.md` | What changed and why, with measured before and after |
| `doc/PROGRESS.md` | Client requirements (R-numbers) and their status |
| `doc/audit-202608.md` | The August 2026 audit record. Do not cite its IDs in code or reference documents |

## Commands

Run all commands from the repository root.

```bash
python -m rev80                # GUI (or the `rev80` console script)
python -m rev80 --debug        # GUI with debug logging to stderr
rev80 headless                 # headless datalogger (also `rev80-headless`)
rev80 headless --help          # all headless options
rev80 --list-sensors           # also: --list-devices --init-config --edit-config --version

pip install -e ".[dev]"        # editable install with the dev tools
git config core.hooksPath .githooks   # once for each clone; relative path

python -m ruff check src/ tests/                          # what CI and the hook run
python -m pytest tests/ -q --ignore=tests/test_picoscope_hw.py
python -m pytest tests/test_vibechecker.py::test_save_load_roundtrip
python -m pytest tests/ -k "stream" --ignore=tests/test_picoscope_hw.py
```

- **Do not start the GUI** or make a dearpygui viewport from an automated
  session. It crashed the user's desktop session once. The tests make a
  dearpygui context but never a viewport.
- `python -m pytest tests/ -q` also runs the tests in
  `tests/test_picoscope_hw.py` when a scope is connected (AWG loopback on
  channel A). Without a scope they skip.
- **Do not run two pytest processes at the same time with a scope
  connected.** Both open the scope, and the hardware tests fail.
- pytest finds the package through `pythonpath = ["src"]`, so the tests pass
  also when the editable install is broken. Moving the checkout breaks the
  install and the hooks: see CONTRIBUTING.md, "2. Moving the checkout".
- The pre-commit hook runs `ruff check src/ tests/` and nothing else. It does
  not stamp the version: `setuptools_scm` writes `src/rev80/_version.py` at
  build or install time, and the file is gitignored.
- `doc/*.pdf` are build artifacts of the release workflow
  (`scripts/render_docs.sh`). Do not commit them. Do not add rendering to the
  hook.

## Architecture

The module map is CONTRIBUTING.md, "3.1 Modules". The thread diagram and the
stage-by-stage chain are "4.1 Threads and data flow" and "4.3 The measurement
chain, stage by stage". The facts that an agent gets wrong most often:

- **Acquisition thread.** `PicoScopeStream` converts ADC counts to mV
  (`_adc_to_mv`), anti-alias filters and decimates to the raw rate, and calls
  `DataCollector.receive_data` directly. `VibeSensor._callback` serves
  `SimulatedSensor` only.
- **`receive_data` keeps the samples in mV.** `VibeSample.unit` is always
  `'mV'`. The mV-to-EU divide occurs in `process_sample()`. The fixed-mV tach
  threshold depends on this.
- **`receive_data` applies the high-pass**, causal `sosfilt` with the state
  carried from block to block, once for each frame in stream order. There is
  no zero-phase path. `process_sample()` filters again only for replay or
  after a filter-config change (stateless, seeded from the block mean).
- **Main thread.** `process_samples()` decimates to the display rate, runs
  Welch with one segment (`nperseg == blocksize`), integrates, finds peaks and
  returns one `ChannelResult` for each vibration channel.
  `MonitorController.on_results()` follows. The acquisition thread never
  touches a widget. `collector.py`, `sample.py`, `picoscope.py` and `monitor/`
  do not import dearpygui.
- The frame cache is a `deque` of `cache_frames` frames: 32 for an
  `AcquisitionSettings()` made in code, 15 from a seeded `acquisition.yaml`.
  Both front ends load that file.
- `DataCollector.eu_scaled_raw()` gives the Envelope tab the high-passed
  signal at the raw rate, not decimated. It raises `ValueError` for a
  tachometer channel.

## Invariants

Each item is silent when it breaks. The evidence is in CONTRIBUTING.md,
section 5, under the title given.

### Rates

- **Two rate pairs.** The raw rate (`raw_samplerate`, `RAW_SAMPLERATE_HZ` =
  25600 Hz, fixed) is what is acquired, stored and used for envelope
  analysis. The display rate (`samplerate` = exactly 2.56 x `maxfreq`) is for
  the spectrum only. See "4.2 Two sample rates".
- **Use the achieved rate.** A 4824A achieves about 25591.8 Hz (-320 ppm,
  12.5 ns clock grid). `decimate_to_rate()` returns the rate it achieved;
  every consumer uses that, not `config.samplerate`. "E4. Sample-clock grid",
  "E5. Report the achieved rate".
- **Keep the resample ratio bounded.** An unbounded ratio against the real
  clock gave a 512821-tap filter and 73.6 ms for each channel and frame on
  hardware, 0.64 ms in simulation. "E7. Resample ratio bound".
- **Anti-aliasing is mandatory and has no user setting**, at both rates. The
  Kaiser kernel reaches -111.7 dB against -60.0 dB for scipy's default
  Hamming kernel. "E2. Anti-alias kernel".
- `samplerate`, `blocksize`, `nperseg`, `binsize_actual`, `n_fft_bins`,
  `acquisition_period` and the resolved band are read-only properties. Use
  the setters. **Do not write `_fm` or `_df`**, also when you build settings
  from an HDF5 file.
- The `maxfreq` setter clamps to `raw_samplerate / 2.56` (10000 Hz) and logs
  a warning. F_max stays the round preset value on the control.
- **Every per-channel dict** (`channel_names`, `channel_target_units`,
  `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges`,
  `channel_roles`) **must be in the tuple in `AcquisitionSettings.copy()`**.
  These dicts are outside the `to_dict`/`from_dict` round trip, so a copy
  loses a dict that is not in the tuple.

### Measurement chain

- **`highpass_fc` is the declared lower band edge, not the -3 dB knee.**
  `highpass_knee_hz()` puts the knee at 0.834 x the edge (order 4). A filter
  designed at the edge reads 29 % low there. "E8.3. Knee below the band edge".
- **The high-pass is stateful in `receive_data` only.** `filter_block(...,
  stateful=True)` must run once for each frame, in order. Replay seeds the
  state from the block mean. "E8.1. Stateful filter", "E8.2. Seed from the
  block mean".
- **The overall is measured over the declared band** (`config.band`) from one
  Hann-tapered, band-masked transform, for all five integration orders,
  order 0 included. "E9. Tapers for integration", "E10. Band RMS".
- **Average in the power domain**: mean of |X|^2, square root at the end.
  An average of magnitudes reads about 11 % low on a noise floor and looks
  correct on a tone.
- **Crest factor and kurtosis come from the displayed trace and are never
  averaged.** They exist to catch the frame that is not steady.
- **Overflow and degraded frames** are shown with a flag, but they are not
  trended, averaged or used by the anomaly hooks. Their flags are stored and
  read back.
- **Replay must show what the live display showed.** Averaging uses one rule
  for live and browse: the N most recent valid frames up to and including
  the displayed frame.

### Tachometer channels

A pulse train in the vibration path does not raise. It gives overall
1515 mV, crest factor 5.00, kurtosis 15.94 and 63 peaks: a failing bearing
that raises no alarm. See CONTRIBUTING.md, "4.4 Tachometer channels in the
pipeline", and README.md, "Tachometer".

- **A tachometer channel gets edge detection in `receive_data` and no
  high-pass.** The high-pass overshoot adds edges: 31 become 108 at 15 %
  duty, and 1800 RPM reads 6270 RPM. "E14.1. No high-pass on a tachometer
  channel".
- **A tachometer channel produces no `ChannelResult`.** `process_samples()`
  iterates `config.vibration_channels`, not `enabled_channels`. Shaft speed
  never goes through `UNIT_TO_SI`, `amplitude_scale` or `integration_steps`.
- **`rpm` is `None`, never `0.0`,** when there is no reading. "No signal" and
  "stopped" are different facts.
- **Only a usable reading** (`TachResult.is_usable`, quality `'ok'`) goes to
  the speed gate and the RPM trend. `'inconsistent'` and `'unsteady'`
  readings have an `rpm` but must not reach a trend, baseline or alarm.
- **The gate is `MIN_REVS` = 2.0 whole revolutions** (`min_edges_for(ppr)`),
  not a fixed edge count. Nine edges of a 6 ppr encoder are 1.33 turns and
  give no reading. "E14.4. One pulse per revolution and `MIN_REVS`".
- **One pulse per revolution is the default and the most accurate case**:
  0.0013 % against 0.091 % for a 60-line encoder. `pulses_per_rev` is
  user-configurable.
- **Adaptive threshold is the default.** AC coupling removes the mean, so
  above about 55 % duty a fixed level is never reached.
- **The Tachometer tab owns the role.** The Channels tab shows a claimed
  channel read-only and locks its Enable checkbox, because `tach_channels`
  filters by `enabled_channels`.
- **Storage is edge times, not the waveform**: about 30 values/s against
  25600 samples/s. `pulses_per_rev` divides after capture, so RPM is a view
  on stored data.
- Accuracy is ±0.2 % of reading, 300 to 10200 RPM, AWG loopback at
  41666.5 Hz. It is not measured again at 25600 Hz. "E14.2. Accuracy".

### Speed gate

- `DataCollector.speed_ok()` evaluates the gate. `monitor.anomaly.valid_results()`
  applies it. **Do not apply it anywhere else**, and not in
  `_build_anomaly_hook` (two copies). "E20. Speed gate".
- **It fails closed**: no usable reading gives `speed_ok = False`.
- A frame outside the window is measured, shown and stored, but not trended,
  used for a baseline or alarmed on.
- The `RmsThresholdHook` default is 50 %, because a 3.2 % speed change alone
  moves the overall 10 %. "E16.1. RMS threshold 50 %".

### Persistence and configuration

- **Readers must branch on the presence of `data`.** A tachometer channel
  group has `edge_times`, `pulse_widths` and summary attributes, and no
  `data`. Layouts: README.md, "Data files".
- **One channel writer.** `collector._write_channel_group()` serves
  `save_data()` and `MonitorWriterThread`. Pass `role=role_of_sample(sample)`
  at every call: the parameter defaults to `'vibration'`, which stores a
  tachometer's whole waveform.
- `DataCollector._FILE_VERSION` = 5 (measurement files);
  `monitor.writer._FILE_VERSION` = 6 (`session.h5`). Each loader checks its
  own limit (`_restore_metadata(f, max_version=...)`).
- `None` in the acquisition attributes is stored as `''` and read back as
  `None`.
- **`acquisition.yaml` holds all acquisition settings and the `monitor:`
  block. The device YAML holds `channels` and `siggen` only.** See
  CONTRIBUTING.md, "4.8 How configuration is loaded".
- `max_burst_s` and `compression_level` have no widget. The GUI keeps the
  values from `acquisition.yaml` when it saves. **Do not put a literal in
  their place.**
- The GUI loads the monitor settings into the Monitor-tab widgets at startup.
  Each close of the configuration dialog saves those widgets to
  `acquisition.yaml`.
- **The sensor library must never be overwritten after a failed read.**
  `ScopeSensorRegistry` raises on an unreadable file or invalid YAML, and
  skips a bad entry. The keys are those of `ScopeSensor.to_dict()`:
  `sensitivity` is mV per engineering unit.
- **Use `_paths.py` for every resource and user path.** It handles
  `sys._MEIPASS` in a frozen build. Data: `~/Documents/Rev80/data/`. Logs and
  `faulthandler.log`: `~/Documents/Rev80/logs/`. Config:
  `~/.config/rev80/` (Linux), `%APPDATA%\rev80\` (Windows). `./DEVDATA/` is
  test scratch space only.
- Bundled resource files must be under `src/rev80/` and in
  `[tool.setuptools.package-data]`, or a non-editable install loses them.

### Monitor Mode and shutdown

See CONTRIBUTING.md, "4.6 Monitor Mode internals" and "4.7 Shared logic
between the GUI and headless".

- **Shutdown order: stop the monitor, then close the device, then destroy the
  dearpygui context.** `GUI.cleanup()` guards each step and is idempotent;
  `main()` calls it from `finally`. The writer is a daemon thread and loses
  queued captures at exit. A device left open makes the next start fail with
  `PICO_NOT_FOUND` until the USB cable is connected again.
- **The render loop logs each exception type once** and stops through
  `cleanup()`, never around it, after `MAX_CONSECUTIVE_RENDER_ERRORS` (30).
- **The writer queue is bounded** (`MAX_QUEUE_DEPTH` = 64). When it is full,
  `enqueue()` drops the capture and counts it. It must not block: that stops
  acquisition behind the disk. The count is `MonitorWriterThread.dropped`,
  shown as `dropped_captures` in `status_snapshot()`.
- **Both burst paths use `capped_burst_end()` and `_set_burst_frame_cap()`.**
  Burst frames and burst results are trimmed together, because
  `_flush_burst` indexes them in parallel. Burst memory grows about
  2.26 MB/s on 4 channels; uncapped, that ends in an OOM kill with no
  traceback. "E17. Burst memory".
- **A burst keeps `pre_buffer_frames - 1` pre-trigger frames** plus the
  trigger frame. `required_cache_frames()` adds 1 so the cache holds them.
- **Build every `MonitorSession` through `monitor.session.session_from()`.**
  Use `config.channel_role_state()`, `channel_snapshot_for()`,
  `sensor_snapshot_for()`, `pre_buffer_frames_for()` and
  `required_cache_frames()`. Do not copy them into a front end.
- **Source-inspection tests read `gui.py` and `headless.py` as text.** Do not
  write `MonitorSession(`, `max_burst_s=600.0` or `info.get('role')` in any
  comment or docstring of those files.
- The GUI gives results to the monitor for live frames only. During a
  recording it refuses a file load, a session browse, a cache clear and
  Ctrl+K.
- `install_excepthooks()` installs `sys.excepthook`, `threading.excepthook`
  and `faulthandler`. Most work runs off the main thread, and
  `faulthandler.log` is the only record of a SIGSEGV.

## Known-bad areas and open work

Read these before you change the code nearby. The status is in
`doc/PROGRESS.md`.

- **`_build_anomaly_hook` has two copies**, in `gui.py` (reads widgets) and
  `headless.py` (reads a config dict). Change both, or extract a shared
  factory with a parameter object. `tests/test_anomaly_hook_build.py` tests
  both copies and checks that their defaults agree. Tracked as R58.
- **The spectral anomaly hook fires on most healthy frames.** Welch uses one
  segment, so each bin has a standard deviation equal to its mean. The GUI
  does not offer it (`GUI_ANOMALY_HOOK_TYPES = ('rms',)`); headless does.
  Tracked as R39. "E16.2. Spectral hook statistics".
- **"No signal" and "stopped" are not distinguishable** from a flat block.
  Tracked as R45.
- **The first frame of a stream reads about 2x high** on the overall and is
  shown, trended and alarmed on. Tracked as R47.
- **`DataCollector` has no lock.** The session reprocess thread races the
  render loop. Tracked as R59 and R50.
- **Headless does not close the device on an exception** in its loop.
  Tracked as R52.
- **Burst IDs have one-second resolution.** A second burst in the same second
  fails. Tracked as R62.
- **`tests/test_monitor_session_load.py` skips on burst timing**, so a slow
  runner passes it without a check. Tracked as R60.
- `gui.py` is about 5200 lines. Tracked as R61.
- Other open audit items (R51 to R57) are in `doc/PROGRESS.md`.

## How to work here

- **Put new amplitude assertions in `tests/test_measurement_validity.py`.**
  Its tones are off-bin where a test checks leakage, with a non-zero phase.
  `tests/test_sample.py` is on-bin on purpose. See CONTRIBUTING.md, "6.1
  Rules for measurement tests".
- **Do a revert check for every fix.** Remove the fix and confirm that the
  new test fails.
- **Measure before you choose a constant.** Put the table in CONTRIBUTING.md,
  "5. Design evidence". Put a one-line pointer with the key number beside the
  constant. Pointer form: CONTRIBUTING.md, "12. Documentation rules".
- **Use `GenerateBearingVibration` for crest factor, kurtosis and envelope
  tests.** The pure-tone generators have kurtosis about 3 and cannot show a
  broken envelope analyser.
- **A performance claim from `SimulatedSensor` only is not a measurement.**
  It reports exactly 25600 Hz; hardware does not. `scripts/profile-pipeline`
  uses a hardware-realistic `--raw-rate` by default. See "7. Profiling".
- **A speed change on a measurement path needs an equality test**, not a
  tolerance (`tests/test_adc_conversion.py`, the `_running_median` tests in
  `tests/test_peak_selection.py`).
- **Verify electrically when a scope is connected**: AWG loopback on channel
  A, as in `tests/test_picoscope_hw.py`.
- **Update `doc/CHANGELOG.md`, `doc/PROGRESS.md` and `README.md` in the same
  change as the code.**
- **Do not write audit IDs or decision IDs** in code, `README.md`,
  `CONTRIBUTING.md` or this file. State the rule in plain words. Use an
  R-number only for open work. Do not write fixed-bug history in those files;
  it goes in the CHANGELOG.

## Build and release

The procedures are in CONTRIBUTING.md, "10. Building the Windows installer"
and "11. Automated releases". Facts that the files do not show:

- `./scripts/build.sh` needs 64-bit Windows and Git Bash. Only
  `./scripts/build.sh wheel` runs on other systems.
- **`python -m build` fails from the repository root**: the `build/`
  directory hides the PyPI package. Use `./scripts/build.sh wheel`.
- A `v*` tag on any branch runs `.github/workflows/release.yml` and makes a
  draft release. The legacy `rc0.x` tags do not match.
- **CI installers have no PicoSDK DLLs** (`nodlls`). The user installs
  PicoSDK.
- **The Windows runner must install PicoSDK anyway**: the `setup.py` of
  `picosdk` loads the DLLs at install time and raises `TypeError` without
  them.
- **`fetch-depth: 0` is necessary.** Without tags, `setuptools_scm` gives
  `0.0.0+unknown` and nothing fails except the build-job check for that
  string. A dirty tree adds `+d<date>`.
- dearpygui is pinned to 2.0.0. Do not change the pin without a test on
  Windows.
