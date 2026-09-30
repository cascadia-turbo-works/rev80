# Contributing to Rev80

This guide is for developers. It gives the development environment, the
project layout, the architecture, the design evidence for the constants, the
test method, and the build and release procedures. For installation,
operation, configuration and the meaning of the results, see
**[README.md](README.md)**.

## Contents

1. Development environment
2. Moving the checkout
3. Project layout
4. Architecture
5. Design evidence
6. Testing
7. Profiling
8. Rendering docs to PDF
9. Replacing the app icon
10. Building the Windows installer
11. Automated releases
12. Documentation rules

---

## 1. Development environment

Use Linux or macOS. Python 3.10 is the minimum (`requires-python` in
`pyproject.toml`). CI tests Python 3.10, 3.11, 3.12 and 3.13.

```bash
git clone <repo-url>/rev80.git
cd rev80

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install in editable mode with the dev tools (pytest, ruff, pyinstaller, build)
pip install -e ".[dev]"

# Enable the git hooks (once for each clone). The hook runs the same ruff
# check as CI, and nothing else.
git config core.hooksPath .githooks

# Lint: the exact command that CI and the pre-commit hook run
python -m ruff check src/ tests/

# Run the test suite from the repository root (no hardware necessary)
python -m pytest tests/ -q

# Start the app from the source tree
python -m rev80
```

`pytest` finds the package through `pythonpath = ["src"]` in
`pyproject.toml`. It does not use the installed package. Thus the tests pass
even when the editable install is broken (see section 2).

The version is not stamped by a commit hook. `setuptools_scm` writes
`src/rev80/_version.py` at build or install time from `git describe`. The
file is gitignored.

Do not start the GUI from an automated session or a test. The test suite
creates a dearpygui context but never a viewport, so it needs no display.

---

## 2. Moving the checkout

Three things outside the repository are bound to its **absolute path**. They
break silently when the checkout moves. Do all of these steps together:

```bash
cd <new-path>

# 1. Re-point the editable install. If you do not, `import rev80` and both
#    console scripts fail with ModuleNotFoundError, but pytest still passes.
pyenv local <env>                  # or: source .venv/bin/activate
python -c "import sys; print(sys.prefix)"   # confirm the correct environment FIRST
pip install -e ".[dev]"

# 2. Re-enable the git hooks. Use the relative path. An absolute
#    core.hooksPath silently disables every hook after a move.
git config core.hooksPath .githooks

# 3. Verify
rev80 --list-sensors               # must not raise ModuleNotFoundError
git config --get core.hooksPath    # must print: .githooks
```

`.python-version` and `.vscode/` are gitignored. Each checkout owns its own
development environment, and `git clone` does not copy them. Use `mv` to
move a checkout, or make them again by hand. If a `vibechecker` distribution
from before the rename is installed, remove it with
`pip uninstall vibechecker`. `pip install -e .` does not remove it.

No file in the repository contains an absolute path. The user data
(`~/.config/rev80/`, `~/Documents/Rev80/data/`, `~/Documents/Rev80/logs/`,
the desktop entry) does not depend on the checkout path.

---

## 3. Project layout

```
src/rev80/                 The Python package (module table below)
  logging.yaml             Logging configuration (package data)
  monitor/                 Monitor Mode
  assets/fonts/            CommitMono Nerd Font (gitignored; scripts/fetch_font.sh copies it here)
  assets/icons/hicolor/    Linux icon PNGs, 16 to 256 px (scripts/make_icons.sh)
assets/
  fonts/                   CommitMono Nerd Font, tracked (the source of the copy above)
  icons/rev80.svg          App icon source artwork
  icons/rev80.ico          Windows icon for the installer and the exe
build/
  rev80.spec               PyInstaller build spec
  collect_pico_dlls.py     Copies the PicoSDK DLLs into drivers/
drivers/                   PicoSDK DLLs for the Windows build (DLLs gitignored);
                           install-picoscope4000a-driver.sh for Linux
installer/rev80.iss        Inno Setup script
scripts/
  build.sh                 Build pipeline (Git Bash); see section 10
  fetch_font.sh            Copies the tracked font into src/rev80/assets/fonts/
  make_icons.sh            Makes rev80.ico and the hicolor PNGs from the SVG
  render_md.sh             Renders one Markdown file to PDF
  render_docs.sh           Renders the four published docs to doc/*.pdf
  profile-pipeline         Per-stage timing sweep; see section 7
  validate-streaming-capacity  Continuous-streaming stress test on hardware
  advanced_plots.py        Cell-by-cell exploration of an .h5 file
  runtimes.ipynb           Notebook of run-time measurements
examples/                  Stand-alone vendor and exploration scripts; not part of the package
tests/                     pytest suite; see section 6
.githooks/pre-commit       ruff check src/ tests/ (blocks the commit on failure)
.github/workflows/         ci.yml (every branch push and PR), release.yml (v* tags)
.claude/agents/            Agent prompts (technical writer, vibration engineer)
doc/
  CHANGELOG.md             What changed and why, with measured before and after
  PROGRESS.md              Client meetings and R-numbered requirements
  audit-202608.md          The August 2026 instrument audit: findings, status, fixing commits
  *.pdf                    Gitignored build artifacts; see section 8
```

### 3.1 Modules

| Module | Responsibility |
|---|---|
| `__main__.py` | `rev80` console script: info commands, `--version`, the `headless` subcommand, GUI start with `try/finally` around `run()` |
| `__init__.py` | Package exports and `__version__` |
| `_paths.py` | Path resolution for an editable checkout, a pip install and a frozen bundle: `resource_path()`, `project_path()`, `data_dir()`, `log_dir()` |
| `_pico_loader.py` | Windows only: adds the PicoSDK DLL directory to the search path before `picosdk` is imported |
| `_profile.py` | Per-stage pipeline timing (`--profile`, `REV80_PROFILE=1`); see section 7 |
| `_dsp.py` | Tapers, band mask, frequency-domain integration, knee placement, crest factor, kurtosis |
| `logger.py` | Logging from `logging.yaml` into `log_dir()`; `install_excepthooks()` |
| `util.py` | Presets, unit taxonomy and SI conversion, amplitude modes, anomaly-hook labels, `UI_Elements` tag registry |
| `icons.py` | Icon-font registry for dearpygui |
| `desktop.py` | Linux: install and remove the `.desktop` launcher entry and icon |
| `sensor.py` | `VibeSensor`: device metadata; `find()` lists PicoScopes; `simulated()`; `connect()` returns the stream |
| `picoscope.py` | `FindPicoScope()`; `PicoScopeStream`: streaming thread, ADC-to-mV, overflow latch, oversample and anti-alias filter, watchdogs, signal generator |
| `simulation.py` | `SimulatedSensor` and the signal generators |
| `scope_sensor.py` | `ScopeSensor`: IEPE sensor name, sensitivity (mV per EU), engineering units, UUID, notes |
| `scope_sensor_registry.py` | `ScopeSensorRegistry`: the YAML sensor library |
| `config.py` | Config directory, YAML load and save (atomic), built-in defaults, `channel_role_state()` |
| `sample.py` | `AcquisitionSettings`, `VibeSample`, `ChannelResult` |
| `collector.py` | `DataCollector`: stream lifecycle, ingestion, high-pass, frame cache, processing, trend, HDF5 save and load; `decimate_to_rate()`; `_write_channel_group()` |
| `tach.py` | Tachometer edge detection and shaft-speed estimate: `TachSettings`, `TachResult` |
| `peaks.py` | Spectral peak selection against a local noise floor |
| `envelope.py` | Envelope (demodulation) spectrum and `suggest_band()` |
| `gui.py` | `GUI`: dearpygui layout, render loop, dialogs, plots, file I/O, monitor card, session browser |
| `headless.py` | `rev80 headless` / `rev80-headless`: the interval datalogger with no GUI |
| `monitor/session.py` | `MonitorSession` and the shared session factory: `session_from()`, `channel_snapshot_for()`, `sensor_snapshot_for()`, `pre_buffer_frames_for()`, `required_cache_frames()` |
| `monitor/gate.py` | `IntervalGate`: capture schedule on a fixed grid; burst entry and exit |
| `monitor/anomaly.py` | `AnomalyHook` protocol; RMS, spectral, fixed and composite hooks; `valid_results()` |
| `monitor/controller.py` | `MonitorController`: interval captures, bursts, pre-trigger frames, burst cap |
| `monitor/writer.py` | `MonitorWriterThread`: daemon thread that writes `session.h5` |

---

## 4. Architecture

### 4.1 Threads and data flow

```text
Acquisition thread                         Main thread (GUI render loop or headless loop)
──────────────────                         ──────────────────────────────────────────────
PicoScopeStream  (or SimulatedSensor)
  ADC counts -> mV (_adc_to_mv)
  overflow latch, one bit per channel
  anti-alias FIR + decimate -> raw rate
        │ dict: status, overflow_mask, degraded, rel_time,
        │       timestamp, unit, channels, data (mV), samplerate
        ▼
DataCollector.receive_data()
  for each channel: VibeSample, in mV
    vibration:  causal high-pass, state carried
    tachometer: edge detection, no high-pass
  frame_cache.append(frame)
  new_frame_event.set()  ───────────────▶  wait for new_frame_event
                                           DataCollector.process_samples()
                                             decimate to display rate, Welch PSD,
                                             integration, band, peaks, overall,
                                             crest factor, kurtosis
                                             -> list[ChannelResult]
                                           display (GUI) or print (headless)
                                           MonitorController.on_results()  ──▶ MonitorWriterThread
                                                                                -> session.h5
```

- `collector.py`, `sample.py`, `picoscope.py` and `monitor/` do not import
  dearpygui. The acquisition thread never touches a widget.
- On hardware, the stream calls `DataCollector.receive_data` directly.
  `SimulatedSensor` calls it through `VibeSensor._callback`.
- The frame cache is a `deque`. Its depth is `AcquisitionSettings.cache_frames`:
  the dataclass default is 32 (`config.DEFAULT_CACHE_FRAMES`), but a seeded
  `acquisition.yaml` holds 15, and both front ends load that file.
- When the main thread is slower than the data, it processes only the newest
  frame. Earlier frames stay in the cache for browsing.
- `DataCollector.current_frame()` returns the same frame that
  `process_samples()` processes, for consumers that need the raw
  `VibeSample` (the Envelope tab).
- The GUI gives results to the monitor only for live frames
  (`GUI._monitor_accepts_frames()`). During a recording, the GUI refuses a
  file load, a session browse and a cache clear.

### 4.2 Two sample rates

`AcquisitionSettings` (`sample.py`) holds two independent rate pairs.

| Pair | Values | Set by | Used by |
|---|---|---|---|
| Raw rate | `raw_samplerate` = `RAW_SAMPLERATE_HZ` = 25600 Hz nominal; `raw_blocksize` | Fixed. Not user-configurable | `PicoScopeStream`, `SimulatedSensor`, `VibeSample`, HDF5 files, envelope analysis |
| Display rate | `samplerate` = 2.56 x `maxfreq`; `blocksize` = ceil(`samplerate` / `binsize`) | `maxfreq` and `binsize` setters | Spectrum tab, `ChannelResult` |

Rules:

- `samplerate`, `blocksize`, `nperseg`, `binsize_actual`, `n_fft_bins`,
  `acquisition_period` and the resolved band values are read-only derived
  properties. Use the public setters. Do not write the private `_fm` or `_df`
  attributes, also when you build settings from an HDF5 file.
- The `maxfreq` setter clamps to `raw_samplerate / 2.56` (10000 Hz at the
  nominal raw rate) and logs a warning.
- The driver clock is on a 12.5 ns grid. The achieved raw rate is about
  25591.8 Hz (-320 ppm). `decimate_to_rate()` returns the rate it achieved.
  Every consumer must use that rate, not `config.samplerate`.
- F_max stays the round preset value on the control. The difference is in
  the frequency axis only.
- Anti-aliasing is mandatory at both rates and has no user setting:
  `PicoScopeStream` filters to the raw rate, and `decimate_to_rate()` filters
  to the display rate with the same Kaiser stopband target.
- `PicoScopeStream` runs the ADC at `effective_osr` x the raw rate (up to 4x,
  capped by `STREAMING_CEILING_HZ` = 100000 Hz). Nothing outside
  `picoscope.py` sees the oversampling.
- Per-channel settings (`channel_names`, `channel_target_units`,
  `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges`,
  `channel_roles`) are dicts keyed by channel index (0 = A). They are outside
  the `to_dict`/`from_dict` round trip. **Add each new per-channel dict to the
  tuple in `AcquisitionSettings.copy()`**, or copies lose it silently.

### 4.3 The measurement chain, stage by stage

1. **Acquisition** (`PicoScopeStream`, acquisition thread). The driver
   callback converts ADC counts to mV with the vectorised `_adc_to_mv()`. Do
   not use the vendor `adc2mV` (see E3). An overflow latch records clipping
   for each channel over the whole block. A full block is anti-alias filtered
   and decimated to the raw rate.
2. **Watchdogs** (`PicoScopeStream`). After 5 s with no data, the silence
   watchdog tries up to 3 reconnects. The rate watchdog checks throughput
   every 2 s. If delivery is below 90 % of the requested rate for 2
   consecutive windows, it sets `degraded`. It does not reconnect.
3. **Ingestion** (`receive_data`, acquisition thread). Each channel becomes a
   `VibeSample` at the raw rate, **in mV**, with its `overflow` and `degraded`
   flags. The mV-to-EU divide does not occur here. A vibration channel gets
   the causal Butterworth high-pass (`filter_block(stateful=True)`), once for
   each frame and in stream order. A tachometer channel gets edge detection
   and no high-pass (4.4).
4. **Decimation** (`process_sample`, main thread). `decimate_to_rate()`
   resamples the filtered block to the display rate with a
   denominator-bounded ratio (E7). The result is cached on the sample.
5. **Spectrum.** Welch PSD with one segment (`nperseg == blocksize`), so the
   line count and bin width are those that the UI states.
6. **Averaging** (optional). Power-domain average of the N most recent valid
   frames, up to and including the displayed frame. Overflow and degraded
   frames are not averaged in. The overall is `sqrt(mean(squares))`.
7. **Integration and units.** The PSD is multiplied by (2 pi f)^(2n) for
   integration order n, divided by the sensitivity squared, and scaled to the
   target unit and amplitude mode.
8. **Truncation.** The spectrum stops at `maxfreq`. The guard band above it
   is not shown and not searched for peaks.
9. **Peaks.** `peaks.select_peaks()` reports a line that rises
   `peak_threshold_db` (default 9.5 dB) above its own local noise floor.
10. **Overall.** The RMS over the declared band (`config.band`) for each of
    the five integration orders (-2 to +2), from one Hann-tapered,
    band-masked transform. Order 0 uses the same path, because the band mask
    is also a transform-domain multiply.
11. **Waveform, crest factor, kurtosis.** The displayed trace is band-limited
    to the same band. It uses a Tukey overlap-save window, so integrated or
    band-limited traces show the middle 50 % of the block. Crest factor and
    kurtosis come from this trace and are never averaged.
12. **Trend.** During streaming, valid frames go to the trend. Overflow and
    degraded frames are shown with a flag, but they are not trended, not
    averaged, and not used by the anomaly hooks.

`DataCollector.eu_scaled_raw()` gives the envelope analysis the high-pass
filtered signal in the sensor's own EU **at the raw rate**. It does not
decimate, so a low `maxfreq` does not limit the envelope bandwidth. It
raises `ValueError` for a tachometer channel.

**Replay.** A loaded file goes through the same `process_sample()`. Two
rules make replay show what the live display showed:

- High-pass state: replay filters each frame without carried state, from an
  initial condition seeded from the block mean (`_seed_zi`, E8.2).
- Averaging: one rule for live and browse, the N most recent valid frames up
  to and including the displayed frame.

### 4.4 Tachometer channels in the pipeline

A channel has a role: `'vibration'` (default) or `'tachometer'`. A pulse train
in the vibration path gives a plausible wrong result, not an error. Thus:

- `receive_data` runs edge detection (`tach.tach_result`) in place of the
  high-pass. The high-pass overshoot on each falling edge adds false edges
  (E14.1).
- `process_samples()` iterates `config.vibration_channels`, not
  `enabled_channels`. A tachometer channel produces no `ChannelResult`.
- Shaft speed goes to `tach_trend` (`get_rpm_trend()`), never through
  `UNIT_TO_SI`, `amplitude_scale` or `integration_steps`.
- `rpm` is `None`, never `0.0`, when there is no usable reading. The code
  cannot yet tell "no signal" from "stopped" (tracked as R45 in
  `doc/PROGRESS.md`).
- A reading needs `MIN_REVS` = 2.0 whole revolutions in the block
  (`tach.min_edges_for(ppr)`). One pulse per revolution is the default.
- `tach_for()` recomputes a stored reading from its edge times when the
  calibration changes, because `pulses_per_rev` divides the intervals after
  capture.
- The speed gate is evaluated in `DataCollector.speed_ok()` and applied only
  in `monitor.anomaly.valid_results()`. It fails closed when there is no
  reading.
- The Tachometer tab owns the role. The Channels tab shows a claimed channel
  as read-only and locks its Enable checkbox, because `tach_channels`
  filters by `enabled_channels`.

### 4.5 Persistence internals

- **One channel writer.** `collector._write_channel_group()` writes one
  channel of one frame. `DataCollector.save_data()` and
  `MonitorWriterThread` both use it. Do not make a second copy.
- Each channel group stores `overflow` and `degraded` attributes. The
  loaders read them back, so a replayed frame keeps its flags.
- A vibration channel stores `data` (raw rate, mV). A tachometer channel
  stores `edge_times`, `pulse_widths` and summary attributes (`rpm`,
  `quality`, `n_edges`, `interval_spread`, `speed_drift_pct`, `duty_cycle`,
  `pulses_per_rev`), and **no `data`**. Readers must branch on the presence
  of `data`.
- `MonitorWriterThread` does not have the config. It gets the role from
  `role_of_sample(sample)`. Pass `role=` at every `_write_channel_group` call:
  the parameter defaults to `'vibration'`.
- Measurement files: `DataCollector._FILE_VERSION` = 5. Monitor sessions:
  `monitor.writer._FILE_VERSION` = 6. Each loader checks a file against its
  own version limit (`_restore_metadata(f, max_version=...)`).
- `None` in the acquisition attributes is stored as `''` and read back as
  `None`.
- The full file layouts are in README.md, "Data files".

### 4.6 Monitor Mode internals

`MonitorController.on_results()` runs on the main thread after each
`process_samples()`. `IntervalGate` decides if a frame is an interval
capture. The anomaly hook decides if a burst starts. A burst keeps the
pre-trigger frames from the frame cache, the trigger frame, and the frames
that follow. `MonitorWriterThread` writes all of it to one `session.h5`.

Keep these invariants. Each failure is silent:

- **Shutdown order.** `GUI.cleanup()` stops the monitor first, then closes
  the device, then destroys the dearpygui context. Each step has its own
  guard, and `cleanup()` is idempotent. `main()` calls it from `finally`.
  The writer is a daemon thread and loses queued captures at exit. A device
  left open makes the next start fail with `PICO_NOT_FOUND` until the USB
  cable is disconnected and connected again.
- **Render-loop errors.** The loop logs each exception type once. After
  `MAX_CONSECUTIVE_RENDER_ERRORS` (30) consecutive failures it stops through
  `cleanup()`, never around it.
- **Bounded writer queue.** `MAX_QUEUE_DEPTH` = 64 captures. When the queue
  is full, `enqueue()` drops the capture and counts it (`dropped`). It does
  not block, because back-pressure would stop acquisition behind the disk.
- **Disk guard.** Below 1 GiB free, the writer stops the session.
- **Burst cap.** `burst_frame_cap(max_burst_s, acquisition_period)` limits
  the frames that one anomaly burst keeps (minimum `MIN_BURST_FRAMES` = 4).
  Burst frames and burst results are trimmed together, because
  `_flush_burst` indexes them in parallel (E17).
- **`max_burst_s` comes from the config.** Both front ends read it from
  `acquisition.yaml`. Do not put a literal in its place.
- **Known gap.** A manual burst (`trigger_burst()`) does not use
  `capped_burst_end()` and does not set the frame cap. It ends
  `burst_duration_s` after the trigger.
- **Crash evidence.** `install_excepthooks()` installs `sys.excepthook`,
  `threading.excepthook` and `faulthandler`. `faulthandler.log` in
  `~/Documents/Rev80/logs/` is the only record of a SIGSEGV. An
  unattended session also logs memory, thread count, burst retention and
  queue depth every 300 s (`TRAIL_INTERVAL_S`), because an OOM kill leaves no
  traceback.
- The spectral hook is not in the GUI (`GUI_ANOMALY_HOOK_TYPES = ('rms',)`).
  It fires on most healthy frames. Headless still accepts it. Tracked as R39
  in `doc/PROGRESS.md` (E16.2).

### 4.7 Shared logic between the GUI and headless

Both front ends build a monitor session through the same functions. Do not
copy them into a front end:

| Decision | Shared function |
|---|---|
| Channel role, calibration and enabled state from the device YAML | `config.channel_role_state()` |
| Session construction | `monitor.session.session_from()` |
| Channel and sensor snapshots in `session.h5` | `channel_snapshot_for()`, `sensor_snapshot_for()` |
| Pre-trigger frame count | `pre_buffer_frames_for()` |
| Frame-cache depth for a burst (pre-trigger frames + 1 for the trigger frame) | `required_cache_frames()` |

**One copy remains:** `_build_anomaly_hook` exists in `gui.py` and in
`headless.py`. The GUI version reads widgets; the headless version reads a
config dict. `tests/test_anomaly_hook_build.py` tests both copies and checks
that their defaults agree. A change to one copy needs the same change in the
other. The correct fix is a shared factory with a parameter object.

Source-inspection tests (`tests/test_session_from.py`,
`tests/test_headless_tach.py`) read `gui.py` and `headless.py` as text. They
check that `session_from(`, `required_cache_frames(` and
`channel_role_state(` occur, and that `MonitorSession(`,
`max_burst_s=600.0` and `info.get('role')` do not. Do not write these
strings in a comment or docstring of those two files.

### 4.8 How configuration is loaded

Config files are in `$XDG_CONFIG_HOME/rev80/` (default `~/.config/rev80/`)
on Linux and `%APPDATA%\rev80\` on Windows.

| File | Holds |
|---|---|
| `acquisition.yaml` | All acquisition settings, and the `monitor:` and `monitor.anomaly:` blocks |
| `devices/picoscope-{model}-{serial}.yaml` | Channels (sensor, range, coupling, name, target unit, amplitude mode, role, tach calibration) and signal generator. No acquisition settings |
| `devices/picoscope-defaults.yaml` | Channel and signal-generator template for a new device |
| `scope_sensors.yaml` | The sensor library |

Precedence:

1. `config.ensure_config_dir()` writes each file that does not exist, from
   the built-ins in `config.py`. It does not change an existing file.
2. `load_acquisition_config()` fills missing keys from the built-ins. A key
   in the file always wins. For example, a file seeded when the RMS
   threshold default was 10 % still holds `rms_pct: 10.0`.
3. `AcquisitionSettings.from_dict()` takes the `acquisition:` block. Missing
   keys fall back to the dataclass defaults. Thus `cache_frames` is 15 from
   a seeded file, but 32 for an `AcquisitionSettings()` made in code.
4. Headless command-line options override the file for that run.
   `--channels` is also saved to the device file.
5. `save_device_config()` writes only `channels` and `siggen`.

`monitor.compression_level` is in the seeded file but is not read. Sessions
always use gzip level 4.

**Sensor library.** `ScopeSensorRegistry` saves the list that it read, so a
read failure must never become an overwrite. An unreadable file, invalid
YAML, or a top level that is not a list raises an exception. A bad entry is
logged and skipped, and the other entries are kept. The keys are those of
`ScopeSensor.to_dict()`: `sensitivity` is mV per engineering unit.

### 4.9 Internal data structures

**`VibeSample`** (`sample.py`): one block of one channel at the raw rate.

| Field | Meaning |
|---|---|
| `data` | `ndarray` float64, raw mV |
| `samplerate` | `float`, achieved raw rate in Hz |
| `unit` | Always `'mV'` |
| `status`, `overflow`, `degraded` | Validity of the block |
| `timestamp` (property), `rel_time` | ISO time; seconds from stream start |
| `overall_ampl_by_integration_order` | `(5,)` mV RMS for orders -2 to +2, set by processing |
| `filtered_mv`, `decimated_mv`, `psd_mv`, `freq_hz` | Caches, each keyed to the config that made it |
| `tach` | `TachResult` on a tachometer channel, else `None` |

**`ChannelResult`** (`sample.py`): frozen display result for one channel and
one frame, made by `DataCollector.process_sample()`.

| Field | Meaning |
|---|---|
| `unit` | Target display unit |
| `time_data`, `time_vec`, `samplerate` | Displayed trace at the achieved display rate |
| `freq`, `spectrum` | Spectrum up to `maxfreq`, in the target unit and amplitude mode |
| `peaks` | Indices into `freq`/`spectrum`, largest first |
| `overall`, `band_fmin`, `band_fmax` | Band amplitude and its declared band |
| `crest_factor`, `kurtosis` | From `time_data`, never averaged |
| `n_averages` | Frames in the average; 1 = no averaging |
| `rpm`, `speed_ok` | Shaft speed in RPM (`None` = no reading); speed-gate result |
| `overflow`, `degraded`, `status`, `timestamp`, `rel_time` | From the sample |

**`ScopeSensor`** (`scope_sensor.py`): `name`, `engineering_units` (the
quantity, for example `'g'` or `'mm/s'`), `sensitivity` (mV per EU), `id`
(UUID), `notes`. The target unit and the amplitude mode are per-channel
settings, not sensor fields.

**PicoScope open and recovery.** `FindPicoScope()` opens each unit and reads
model, serial and channel count. Opening tries `_MAX_OPEN_ATTEMPTS` = 2
times, and retries with `ps4000aChangePowerSource` when the unit reports a
USB power problem. The overflow warning is logged once for each channel for
each stream, and again after clipping stops and starts again.

---

## 5. Design evidence

Each subsection gives one decision: the value, the measured table, a
"Measured on" line (hardware model and date, AWG loopback, or
`SimulatedSensor`), and the rejected alternatives. Code comments point here
by section ID and title.

### E1. Streaming ceiling and the raw rate

Filled by package W2-A.

### E2. Anti-alias kernel

Filled by package W2-A.

### E3. ADC-to-mV conversion

Filled by package W2-A.

### E4. Sample-clock grid

Filled by package W2-A.

### E5. Report the achieved rate

Filled by package W2-A.

### E6. Oversampling ratio

Filled by package W2-A.

### E7. Resample ratio bound

Filled by package W2-A.

### E8. High-pass filter

Filled by package W2-A.

#### E8.1. Stateful filter

Filled by package W2-A.

#### E8.2. Seed from the block mean

Filled by package W2-A.

#### E8.3. Knee below the band edge

Filled by package W2-A.

### E9. Tapers for integration

Filled by package W2-A.

### E10. Band RMS

Filled by package W2-A.

### E11. Display rate, block size and line count

Filled by package W2-A.

### E12. Peak selection

Filled by package W2-A.

#### E12.1. Method

Filled by package W2-A.

#### E12.2. Floor width

Filled by package W2-A.

#### E12.3. Edge handling

Filled by package W2-A.

#### E12.4. Window nulls

Filled by package W2-A.

### E13. Envelope band search

Filled by package W2-A.

### E14. Tachometer

Filled by package W2-A.

#### E14.1. No high-pass on a tachometer channel

Filled by package W2-A.

#### E14.2. Accuracy

Filled by package W2-A.

#### E14.3. Interpolation

Filled by package W2-A.

#### E14.4. One pulse per revolution and `MIN_REVS`

Filled by package W2-A.

#### E14.5. Signal floor

Filled by package W2-A.

#### E14.6. Spread and drift limits

Filled by package W2-A.

#### E14.7. Median estimator

Filled by package W2-A.

### E15. Simulation model constants

Filled by package W2-A.

### E16. Anomaly thresholds

Filled by package W2-A.

#### E16.1. RMS threshold 50 %

Filled by package W2-A.

#### E16.2. Spectral hook statistics

Filled by package W2-A.

### E17. Burst memory

Filled by package W2-A.

### E18. Profiler overhead

Filled by package W2-A.

### E19. GUI render cost

Filled by package W2-A.

### E20. Speed gate

Filled by package W2-A.

---

## 6. Testing

The suite runs without hardware. It uses `VibeSensor.simulated()` and
synthetic signals. Tests that write `.h5` files use `./DEVDATA/` (set in the
test files, not by the app). You can delete that directory at any time.

```bash
# All tests. With a PicoScope connected, this also runs the hardware tests.
python -m pytest tests/ -q

# All tests except the hardware file
python -m pytest tests/ -q --ignore=tests/test_picoscope_hw.py

# One file, one test, or a keyword
python -m pytest tests/test_monitor_session_load.py
python -m pytest tests/test_vibechecker.py::test_save_load_roundtrip
python -m pytest tests/ -k "stream"

# Count the tests
python -m pytest --collect-only -q | tail -1
```

On 2026-09-30, 1223 tests were collected. 27 of them are in
`tests/test_picoscope_hw.py`. A run without the hardware file took 79 s on the
development machine (1188 passed, 8 skipped).

> **Caution:** Do not run two pytest processes at the same time with a scope
> connected. Both open the scope, and the hardware tests then fail.

### 6.1 Rules for measurement tests

Green CI is not evidence that the instrument is correct. The August 2026
audit found the full suite passing while the measurements were wrong,
because every DSP test used a bin-centred tone. A bin-centred tone makes the
FFT wrap error zero and hides integration and leakage defects.

- **Put new amplitude assertions in `tests/test_measurement_validity.py`.**
  Its tones are off-bin where a test checks leakage, and start at a non-zero
  phase. `tests/test_sample.py` is on-bin on purpose. Do not add amplitude
  assertions there.
- **Do a revert check for every fix.** Remove the fix and confirm that the
  new test fails.
- **A speed change on a measurement path needs an equality test,** not a
  tolerance. `tests/test_adc_conversion.py` and the `_running_median` tests
  in `tests/test_peak_selection.py` assert bit-identity against the code
  they replaced.
- **A performance claim from `SimulatedSensor` only is not a measurement.**
  `SimulatedSensor` reports exactly 25600 Hz. Hardware reports a rate that
  does not reduce to a small ratio (E7).
- **Pure-tone generators are not an oracle.** `GenerateTone` and the two
  older bearing generators are sums of cosines plus white noise: kurtosis
  about 3, no impulses, no resonance, no sidebands. A broken envelope
  analyser and a correct one give the same result on them. Use
  `GenerateBearingVibration` (`severity=0` is the healthy control, `seed=`
  makes a block repeatable) for crest factor, kurtosis and envelope tests.
  For tachometer tests, use `GenerateMachineWithTach` or
  `machine_with_tach_sources`, so the pulses are locked to the shaft of the
  vibration signal.
- **Measure before you choose a constant.** Put the table in section 5 of
  this file. Put a one-line pointer with the key number beside the constant.

### 6.2 Hardware tests and AWG loopback

`tests/test_picoscope_hw.py` skips itself when no PicoScope is connected.
With a PicoScope 4000A connected and the AWG output looped back to channel A,
its 27 tests check the chain electrically. Use this run to close out a
change to the measurement chain.

### 6.3 Test files

| Area | Files |
|---|---|
| Settings and rates | `test_acquisition_settings.py`, `test_display_rate.py`, `test_config.py`, `test_config_contract.py` |
| Measurement accuracy | `test_measurement_validity.py`, `test_declared_band.py`, `test_spectral_averaging.py`, `test_diagnostic_scalars.py`, `test_sample.py` (on-bin) |
| Acquisition | `test_antialias.py`, `test_adc_conversion.py`, `test_picoscope.py` (mocked driver), `test_picoscope_hw.py` (hardware) |
| Peaks, envelope, simulation | `test_peak_selection.py`, `test_envelope.py`, `test_bearing_oracle.py`, `test_simulation_tach.py` |
| Collector and files | `test_vibechecker.py`, `test_multichannel.py`, `test_scope_sensor.py`, `test_sensor_library_integrity.py`, `test_file_version_check.py`, `test_paths.py` |
| Tachometer and speed | `test_tach.py`, `test_tach_claim.py`, `test_tach_pipeline.py`, `test_tach_persistence.py`, `test_speed_gate.py`, `test_one_x.py`, `test_rotation_units.py`, `test_headless_tach.py` |
| Monitor Mode | `test_monitor_gate.py`, `test_monitor_anomaly.py`, `test_monitor_controller.py`, `test_monitor_session_load.py`, `test_monitor_pretrigger_scaling.py`, `test_monitor_tach_storage.py`, `test_monitor_live_only.py`, `test_manual_burst_alignment.py`, `test_reprocess_session_tach.py`, `test_session_from.py`, `test_anomaly_hook_build.py` |
| Lifecycle and resources | `test_app_lifecycle.py`, `test_bounded_resources.py`, `test_crash_evidence.py` |
| GUI and small items | `test_gui_save_config.py`, `test_icons.py`, `test_util_small_defects.py` |

The GUI tests create a dearpygui context, but never a viewport.

---

## 7. Profiling

`src/rev80/_profile.py` times thirteen pipeline stages, from the driver
callback to `render_dearpygui_frame()`. When profiling is off, each timer is
a shared no-op (overhead: E18).

```bash
rev80 --profile                          # log the stage table at exit
REV80_PROFILE=1 rev80                    # the same, for a desktop launcher
./scripts/profile-pipeline               # channel-count sweep, simulated
./scripts/profile-pipeline --hardware --channels 1,3,4,8
./scripts/profile-pipeline --help        # all options
```

The stages are grouped by thread:

| Thread | Stages | Effect |
|---|---|---|
| Acquisition | `usb.poll`, `usb.adc2mv`, `usb.antialias`, `ingest.receive` | Takes the GIL from the main thread |
| Main | `proc.total`, `proc.decimate`, `proc.psd`, `proc.peaks`, `gui.display`, `gui.peaks_table`, `gui.envelope`, `gui.render`, `gui.frame` | Blocks the mouse and the display |

The two need different fixes. Compare `gui.render` with `proc.total` to find
which one is the problem. The stages nest: `usb.poll` contains everything
the app callback does, and `proc.total` contains `proc.decimate`,
`proc.psd` and `proc.peaks`. Subtract nested stages; do not add them.

`profile-pipeline` uses a hardware-realistic `--raw-rate` by default, not
25600 Hz. Pass `--raw-rate 25600` to see the numbers that CI sees.

---

## 8. Rendering docs to PDF

The PDFs of `README.md`, `CONTRIBUTING.md`, `doc/PROGRESS.md` and
`doc/CHANGELOG.md` are **build artifacts**. They are gitignored. The `docs`
job in `.github/workflows/release.yml` renders them and attaches them to each
GitHub Release, so each PDF matches one version. Do not commit PDFs, and do
not add rendering to the git hook.

You do not need the toolchain to develop or commit. To make a PDF locally:

```bash
./scripts/render_docs.sh                  # all four -> doc/*.pdf
./scripts/render_md.sh doc/CHANGELOG.md   # one file -> doc/CHANGELOG.pdf
```

The scripts need `pandoc` and `weasyprint` on `PATH`. WeasyPrint needs Pango:

```bash
# Debian/Ubuntu
sudo apt-get install pandoc libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
pip install "weasyprint==69.0"     # the version that the release workflow uses
```

`doc/audit-202608.md` is not rendered and is not a release asset.

---

## 9. Replacing the app icon

1. Edit `assets/icons/rev80.svg`.
2. From the repository root, run `./scripts/make_icons.sh`. It needs
   Inkscape and ImageMagick (`convert`).
3. Commit the updated `src/rev80/assets/icons/hicolor/*/apps/rev80.png`.
4. Move `rev80.ico` from the repository root to `assets/icons/rev80.ico`.
   The script writes it to the root, and `build/rev80.spec` reads it from
   `assets/icons/`.
5. Delete the intermediate `assets/icons/{16,32,48,64}.png` files. They are
   gitignored.

You do not need to change `build/rev80.spec`, `installer/rev80.iss` or
`desktop.py`.

---

## 10. Building the Windows installer

The build makes a one-directory executable with PyInstaller and an installer
with Inno Setup. **A full build must run on 64-bit Windows.** Only the
`wheel` target runs on other systems.

### 10.1 Prerequisites

| Tool | Source | Notes |
|---|---|---|
| Python 3.10+ (64-bit) | [python.org](https://www.python.org/downloads/) | Must be 64-bit. Add it to `PATH` |
| Git for Windows | [git-scm.com](https://git-scm.com/download/win) | Supplies Git Bash for `scripts/build.sh` |
| PicoSDK 11.1 (64-bit) | [picotech.com/downloads](https://www.picotech.com/downloads) | The release workflow uses 11.1.0.481. Restart Windows before the first connection to a scope |
| Inno Setup 6 | [jrsoftware.org](https://jrsoftware.org/isinfo.php) | A per-user install in `%LOCALAPPDATA%` is permitted |

Install the project from Git Bash or `cmd.exe`:

```bash
pip install -e ".[dev]"
```

### 10.2 Running the build

Run from the repository root:

```bash
./scripts/build.sh              # font -> version -> DLLs -> PyInstaller -> Inno Setup

./scripts/build.sh dlls         # collect the PicoSDK DLLs into drivers/ only
./scripts/build.sh pyinstaller  # PyInstaller only
./scripts/build.sh installer    # Inno Setup only (dist/ must exist)
./scripts/build.sh wheel        # wheel + sdist; runs on any OS

# Flags, in any position
./scripts/build.sh all clean    # delete the PyInstaller cache first
./scripts/build.sh all nodlls   # no DLLs: a driver-less bundle (what CI builds)
```

Every target first runs `scripts/fetch_font.sh` and `pip install -e . --no-deps`
(to refresh `_version.py`). Thus the build changes the editable install of
the active environment to point at this checkout.

`build/collect_pico_dlls.py` finds `ps4000a.dll` and `picoipp.dll` from the
PicoSDK install (registry), from `PICO_DLL_DIR`, or from `vendor/pico/`.

> **`python -m build` does not work from the repository root.** The
> repository's `build/` directory hides the `build` package from PyPI, so
> `python -m build` fails with *No module named build.__main__*. Use
> `./scripts/build.sh wheel`. It runs the frontend from a temporary
> directory, with the interpreter resolved to an absolute path.

### 10.3 Output

| Path | Contents |
|---|---|
| `dist/rev80/rev80.exe` | Stand-alone executable (no installation necessary) |
| `installer/Output/Rev80Setup-<version>.exe` | Installer with Start Menu shortcut and uninstaller |
| `dist/rev80-<version>-py3-none-any.whl` | Python wheel |
| `dist/rev80-<version>.tar.gz` | Source distribution |

### 10.4 Constraints

- **64-bit only.** The PicoSDK DLLs are 64-bit.
- **dearpygui is pinned to 2.0.0** in `pyproject.toml`. Do not change the pin
  without a test on Windows.
- **USB kernel driver.** `ps4000a.dll` is the user-mode library. PicoSDK
  installs the kernel driver separately and needs a restart before the first
  connection to a scope.
- **No code signing.** Windows SmartScreen shows a warning at the first
  start. Sign with `osslsigncode` and a certificate if necessary.
- **A local full build needs Windows.** PyInstaller does not cross-compile,
  and the PicoSDK DLLs are for Windows. Tagged releases build on GitHub
  runners (section 11).

---

## 11. Automated releases

A push of a `vX.Y.Z` tag runs
[`.github/workflows/release.yml`](.github/workflows/release.yml). It builds
the installer, the wheel and sdist, and the PDFs of the four published docs.
It attaches them to a **draft** GitHub Release. Examine the draft, then
publish it by hand. The exe is not signed.

```bash
git tag v0.2.0
git push origin v0.2.0
# -> test gate -> wheel (ubuntu) + installer (windows) + docs (ubuntu) -> draft release
```

`workflow_dispatch` runs the same jobs on any ref without a release. The
`release` job runs only for a tag.

Five facts about the workflow:

- **CI installers are driver-less by choice.** The build passes `nodlls`, so
  no DLLs are bundled. The user installs PicoSDK, and the installer warns if
  it is missing. A local `./scripts/build.sh` still bundles `ps4000a.dll`
  and `picoipp.dll`. `rev80.spec` bundles `drivers/` also when it is empty,
  and `_pico_loader.ensure_pico_dlls_loadable()` warns but does not raise.
  To ship the DLLs, remove `nodlls`. The Pico redistribution licence
  controls that decision.
- **PicoSDK is installed on the Windows runner.** This is a different
  requirement from bundling. The `setup.py` of `picosdk` loads the native
  DLLs at **install** time. Without the SDK, `find_library()` returns
  `None`, `ctypes.WinDLL(None)` raises `TypeError` (its `except OSError`
  does not catch it), and `pip install` fails:

  ```
  TypeError: argument of type 'NoneType' is not iterable
  ERROR: Failed to build 'picosdk' when getting requirements to build wheel
  ```

  On Linux the same line is `cdll.LoadLibrary(None)`, which is legal. Thus
  the ubuntu jobs install `picosdk` and a Windows job cannot without the SDK.
  A pre-installed wrapper does not help: the dependency is a git URL, so pip
  runs `setup.py` again. The workflow installs the SDK silently
  (`/quiet /norestart`, cached by version) and adds its `lib` directory to
  `PATH`. No restart is necessary: the restart registers the USB kernel
  driver, and no scope is connected to a runner.
- **A tag trigger ignores branches.** Any `v*` tag on any branch builds a
  draft. The legacy `rc0.x` tags do not match `v*`.
- **The version comes from `git describe`.** Every build job checks out with
  `fetch-depth: 0`. Without tags, `setuptools_scm` falls back to
  `0.0.0+unknown`, and the release ships `Rev80Setup-0.0.0+unknown.exe` with
  no failure. Both build jobs fail if they find that string. A dirty tree
  adds a `+d<date>` suffix; for this reason `_version.py`,
  `installer/version.iss`, the DLLs and the copied font are gitignored.
- **The wheel is a release asset, not a PyPI package.** `picosdk` is a git
  URL dependency, and PyPI refuses those.

### 11.1 Rehearsing a release

Use a throwaway tag first. Check that the installer job log shows a real
version, not the fallback:

```bash
git tag v0.0.1rcx && git push origin v0.0.1rcx
# ...then delete the draft release and:
git push origin :v0.0.1rcx && git tag -d v0.0.1rcx
```

The `gh release create --draft` step runs only on a tag. A branch run or a
manual run does not test it.

---

## 12. Documentation rules

| Text | Place |
|---|---|
| API contract: units, `None` meaning, thread, call order | Docstring. One line if possible; maximum 8 lines for a function, 12 for a module |
| An invariant that a "clean-up" can break | Docstring or comment: 1 to 3 sentences, then a pointer to section 5 |
| Measured table, rejected alternative, derivation | This file, section 5 |
| Operator meaning of a number, limits, configuration | `README.md`, with a unit on every value |
| Environment, layout, build, release, test method | This file. Run each command before you document it |
| Agent rules and known-bad areas | `CLAUDE.md`, one line for each rule |
| What changed, why, measured before and after | `doc/CHANGELOG.md` (Keep a Changelog) |
| Client requirements, meetings, status | `doc/PROGRESS.md` |
| Audit findings and their status | `doc/audit-202608.md` |

- **Pointer form.** Beside a constant, keep the one number that shows why
  the value is not the textbook value, then point to the section:

  ```python
  _AA_STOPBAND_DB: float = 100.0
  # Not scipy's default Hamming kernel (-60 dB measured). Evidence:
  # CONTRIBUTING.md, "E2. Anti-alias kernel".
  ```

  Write the section ID and title, not a URL fragment. Do not point from code
  to the CHANGELOG or the audit file for evidence; those files are history.
- **IDs.** Do not write audit finding IDs or design-decision IDs in code,
  `README.md`, this file or `CLAUDE.md`. State the rule in plain words. Use
  R-numbers only for open work ("tracked as R39 in `doc/PROGRESS.md`").
- **No history in reference text.** "Used to", "previously" and "until Sep
  2026" go to the CHANGELOG, not to docstrings or this file.
- **Same change.** Update `doc/CHANGELOG.md`, `doc/PROGRESS.md` and
  `README.md` in the same commit as the code.
- **Language.** Write in ASD-STE100 Simplified Technical English: one topic
  in each sentence, maximum 20 words in a procedure step and 25 in a
  description, active voice, a unit on every number (also shaft speed), and
  the measurement method for every measured value (hardware model, AWG
  loopback, or `SimulatedSensor`).
