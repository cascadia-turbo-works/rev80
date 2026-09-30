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
`pyproject.toml`), because most modules evaluate their annotations at import
time. CI tests Python 3.10, 3.11, 3.12 and 3.13 on Linux (`ubuntu-latest`)
only. The Windows build is in section 10.

On a Linux machine with no desktop, install `libx11-6` first. The compiled
extension of `dearpygui` loads it, and `import dearpygui` fails without it.

```bash
git clone <repo-url>/rev80.git
cd rev80

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install in editable mode with the dev tools (pytest, ruff, pyinstaller, build, ipykernel)
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
file is gitignored. Run `pip install -e .` again after you apply a tag, to
refresh it. A clone with no reachable tag gets the fallback `0.0.0+unknown`.

Dependencies in `pyproject.toml` have lower bounds, not exact pins. CI
installs the newest releases, so no job tests the lower bounds. Two
exceptions:

- **`dearpygui==2.0.0`.** Later versions crash the viewport on Windows.
  Test on Windows before you change the pin.
- **`picosdk`** installs from the vendor repository, pinned to one commit.
  It is not a PyPI package.

`ruff` is bounded (`>=0.15,<0.17`), and `[tool.ruff.lint]` selects the rule
set explicitly (`E4`, `E7`, `E9`, `F`). The default rule set changes between
ruff releases: on one tree, ruff 0.15.10 gave 0 errors and 0.16.5 gave 167.

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
pyproject.toml             Package metadata, dependencies, setuptools_scm, pytest and ruff settings
build/
  rev80.spec               PyInstaller spec; also writes installer/version.iss
  collect_pico_dlls.py     Copies ps4000a.dll and picoipp.dll into drivers/
drivers/                   PicoSDK DLLs for the Windows build (DLLs gitignored);
                           install-picoscope4000a-driver.sh for Linux
installer/rev80.iss        Inno Setup script; includes the generated version.iss
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
  reading or the reading is not `TachResult.is_usable` (quality
  'inconsistent' or 'unsteady'). The RPM trend also records only a usable
  reading (E14.6, E20).
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
- **Burst cap.** The anomaly burst and the manual burst (`trigger_burst()`)
  both clamp their end with `capped_burst_end()` and set the same frame cap:
  `burst_frame_cap(max_burst_s, acquisition_period)` frames after the
  trigger (minimum `MIN_BURST_FRAMES` = 4), plus the pre-trigger frames.
  `session_from()` records `acquisition_period`; without it the cap is 4
  frames and the controller logs a warning. Burst frames and burst results
  are trimmed together, because `_flush_burst` indexes them in parallel
  (E17).
- **`max_burst_s` comes from the config.** Both front ends read it from
  `acquisition.yaml`. Do not put a literal in its place.
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

Both front ends pass `monitor.compression_level` (gzip level 0 to 9,
default 4) to the session. `compression_level` has no widget; set it in
`acquisition.yaml`.

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

Each measurement names its PicoScope model. One serial number is
recorded: 4424A s/n 12462/0067. The project used two 4824A units, and the
records do not show which unit made a 4824A measurement. A 4224A was also
used in the project; no table in this section names it.

Many tables were measured before the raw rate became 25600 Hz nominal. A
table keeps the rate at which it was measured (for example 41666.5 Hz or
8333.25 Hz). It was not measured again at 25600 Hz unless a line says so.

### E1. Streaming ceiling and the raw rate

**Decision.** The ADC streams at most `STREAMING_CEILING_HZ` = 100000 Hz for
each channel (`picoscope.py`). The raw rate is fixed at `RAW_SAMPLERATE_HZ` =
25600 Hz (`sample.py`), 2.56 x the top F_max preset (10 kHz). It does not
depend on `maxfreq`. `_choose_osr` gives an oversampling ratio of 3, so the
ADC runs at 76800 Hz for each channel (requested).

**Why a ceiling.** Continuous `ps4000aRunStreaming` /
`ps4000aGetStreamingLatestValues` drops most samples above about 100 kHz to
250 kHz for each channel. The limit depends on the channel count. The driver
reports `status='OKAY'` and sets no overflow bit, so nothing shows the loss.

- Requested rates of 300 kHz and more: 15 % to 23 % of the samples arrived
  at 4 channels.
- 1 channel: about 34 % arrived when the driver clamped internally near 1 MHz.
- A flat 100 kHz ceiling leaves margin at 1, 2 and 4 channels. At 4 channels
  the range 100 kHz to 200 kHz is borderline.

**Measured on:** PicoScope 4424A, August 2026, during the anti-alias
hardware tests. The serial number is not recorded.

**Why a fixed raw rate.** Bearing housing resonances, which envelope analysis
uses, are at 2 kHz to 20 kHz. A display F_max of 1 kHz to 2 kHz does not
contain them. A fixed raw rate lets envelope analysis work at every F_max.
At 2.56 x the top preset, every preset decimates by an integer factor:

| F_max preset (Hz) | 200 | 500 | 1000 | 2000 | 5000 | 10000 |
|---|---|---|---|---|---|---|
| display rate (Hz) | 512 | 1280 | 2560 | 5120 | 12800 | 25600 |
| factor from 25600 Hz | 50 | 20 | 10 | 5 | 2 | 1 |

**Validation of the raw rate.** `scripts/validate-streaming-capacity`,
45 s sustained at 3 and 4 channels:

| raw rate | osr | ADC rate per channel | overflow | degraded transitions |
|---|---|---|---|---|
| 25600 Hz | 3 | 76.9 kHz | 0 | 0, at 3 and at 4 channels |
| 40000 Hz | 2 | about 83.3 kHz | 0 | 0, every run |
| 50000 Hz | 2 | 100 kHz (at the ceiling) | 0 | 0 to 2, different in each run |
| 100000 Hz | 1 | 100 kHz (at the ceiling) | 0 | 0, but osr = 1: no anti-alias margin |

- 25600 Hz row: measured 2026-09-09 on a 4424A, s/n 12462/0067.
  `effective_osr` = 3. The ADC ran at 76923 Hz for each channel against
  76800 Hz requested (+0.16 %), because the interval was then requested in
  whole microseconds. The block rate was 25641 Hz. With the clock-grid snap
  (E4) it is 25591.81 Hz.
- 40000 Hz, 50000 Hz and 100000 Hz rows: same 4424A. The date is not
  recorded. 40000 Hz was the highest rate that was clean in every run with
  real anti-alias margin. 50000 Hz sits at the ceiling with no margin and was
  clean in some runs only, on the same hardware and settings. A rate that is
  not repeatable is not a shipped default.
- Only 4 channels were tested. The ceiling is assumed to be independent of
  the channel count for 8-channel devices. This is not measured.

**Rejected alternative.** `RAW_SAMPLERATE_HZ` = 10000 Hz, to decrease GUI lag
at 4 channels. The `maxfreq` clamp then limits F_max to 3906 Hz: the 5 kHz
and 10 kHz presets are not available, and the envelope bandwidth is half.
GUI cost is not a reason to lower the raw rate below what the presets need.
E3 and E19 give the real causes of the GUI cost.

### E2. Anti-alias kernel

**Decision.** `picoscope._antialias_taps` designs a Kaiser-windowed FIR:
`_AA_STOPBAND_DB` = 100 dB, `_AA_TRANSITION_FRAC` = 0.20. It is not
`scipy.signal.decimate(ftype='fir')`. `collector.decimate_to_rate` uses the
same stopband target (E7).

**Why not the scipy default.** `scipy.signal.decimate(ftype='fir')` builds a
20q+1-tap FIR with a Hamming window. Its sidelobes are at about -53 dB. ISO
2954 and analyser practice expect 80 dB or more. The Hamming kernel limits
the usable dynamic range to about 55 dB to 60 dB, independent of the ADC
resolution. Two measurements of the Hamming kernel exist:

- **-55.5 dB**: the worst case into the passband, from the August 2026
  audit. The audit does not record the decimation factor or the method.
- **-60.0 dB**: the worst stopband through the real decimation path
  (`antialias_decimate`) at q = 4, in the table below. `picoscope.py` quotes
  this value.

**Measured on:** computed through `antialias_decimate` on the development
PC, no hardware, at q = 4 (32768 Hz to 8192 Hz), 2026-08-29.

| design | taps | worst stopband | passband at F_max |
|---|---|---|---|
| Hamming 20q+1 (scipy default) | 81 | -60.0 dB | +0.27 % |
| Kaiser 90 dB, transition 0.20 | 231 | -105.0 dB | +0.00 % |
| Kaiser 100 dB, transition 0.20 (chosen) | 259 | -111.7 dB | +0.00 % |
| Kaiser 100 dB, transition 0.25 | 207 | -112.4 dB | -0.42 % |

- The Hamming passband error at 0.05 x fs_out was 0.29 %.
- **Rejected: transition 0.25.** It saves 52 taps, but it attenuates the
  passband at F_max. The 2.56x convention exists to keep that region flat.
- Block edges: the longer kernel does not decrease accuracy. An in-band tone
  through one block, against the analytic RMS, at every shipped block size:
  Hamming +0.2416 %, Kaiser -0.0001 %. The Hann taper of the overall already
  gives low weight to the block edges, where the start-up transient is.
- Hardware A/B: PicoScope 4424A, the same captured samples, q = 8. The Kaiser
  kernel gives +10.8 dB more rejection at 2600 Hz and +10.3 dB at 3100 Hz,
  where alias leakage is above the capture noise floor. Below the floor the
  two kernels are equal.

### E3. ADC-to-mV conversion

**Decision.** `picoscope._adc_to_mv` converts ADC counts with one vectorised
expression: `int16 -> float64 * v_range / max_adc`. Do not use
`picosdk.functions.adc2mV`.

**Why.** `adc2mV` is a per-sample Python list comprehension:
`[(np.int64(x) * vRange) / maxADC.value for x in bufferADC]`. It runs in
`_streaming_callback`, inside `ps4000aGetStreamingLatestValues`, with the GIL
held. Its time is taken directly from the GUI thread.

**Measured on:** the development PC, 2026-09-11. `adc2mV` plus the
`np.array()` that it needs, against `_adc_to_mv`:

| samples per channel | `adc2mV` | vectorised | speed-up |
|---|---|---|---|
| 4096 | 4.22 ms | 0.021 ms | 201x |
| 19200 | 19.86 ms | 0.052 ms | 382x |
| 38400 | 40.28 ms | 0.112 ms | 361x |

- At about 1.03 us for each sample, 1000 samples for each callback and
  76.9 kHz for each channel, `adc2mV` used 0.079 CPU-s per wall-second for
  each channel: 0.634 s/s at 8 channels.
- p95 main-loop tick latency (target 0.5 ms):

| channels | 1 | 3 | 4 | 8 |
|---|---|---|---|---|
| `adc2mV` | 1.42 ms | 4.67 ms | 5.75 ms | 5.76 ms |
| vectorised | 0.58 ms | 0.59 ms | 0.59 ms | 0.59 ms |

**Operation order.** Multiply by `v_range`, then divide by `max_adc`. This
is bit-identical to `adc2mV` for every voltage-range index over the full
int16 range. `x * (v_range / max_adc)` is different in the last bit.
`tests/test_adc_conversion.py` asserts both facts.

**Range table.** `_CHANNEL_INPUT_RANGES_MV` is a copy of the table in
`picosdk.functions`, where it is a module-local value. The copy lets the
conversion work when `PICOSDK_AVAILABLE` is False.

### E4. Sample-clock grid

**Decision.** `PicoScopeStream._start_streaming` requests the streaming
interval in ns. It snaps the interval to the nearest point of the
`_TIMEBASE_NS` = 12.5 ns grid, then rounds up to whole ns. At osr = 3 the
request is 13025 ns: 76775.43 Hz at the ADC, 25591.81 Hz after decimation,
-320 ppm from 25600 Hz. The driver writes back the interval that it used, and
that value is the one that everything downstream uses (E5).

**Rejected: whole microseconds.** 1e6 / 76800 = 13.02 us truncates to 13 us:
76923 Hz, +1603 ppm. Every displayed frequency is then 0.16 % high (a
1000 Hz line reads 1001.6 Hz). 25641 Hz is also coprime with every display
rate, which makes the resample FIR very long unless E7 bounds it.

**Rejected: round(1e9 / fs).** The ns grid is not continuous. The driver
floors a request to the grid, so the correct value 13021 ns lands at
13012 ns, one grid point high.

**Measured on:** PicoScope 4824A (serial not recorded), 2026-09-11. Requested
intervals, and the interval that the driver wrote back:

| requested ns | returned ns | rate per channel (Hz) | / osr (Hz) | ppm against 25600 Hz |
|---|---|---|---|---|
| 13021 | 13012 | 76852.14 | 25617.38 | +679 |
| 13020 | 13012 | 76852.14 | 25617.38 | +679 |
| 13015 | 13012 | 76852.14 | 25617.38 | +679 |
| 13013 | 13012 | 76852.14 | 25617.38 | +679 |
| 13012 | 13000 | 76923.08 | 25641.03 | +1603 |
| 13000 | 13000 | 76923.08 | 25641.03 | +1603 |
| 12995 | 12987 | 77071.29 | 25690.43 | +3532 |
| 13025 | 13025 | 76775.43 | 25591.81 | -320 |
| 13026 | 13025 | 76775.43 | 25591.81 | -320 |
| 12500 | 12500 | 80000.00 | 26666.67 | +41667 |

- The reachable points are 12.5 ns apart (12987.5, 13000, 13012.5, 13025):
  an 80 MHz timebase.
- 8e7/1041 and 8e7/1042 are on the two sides of 76800 Hz. 1042 is nearer,
  so -320 ppm is the best that this hardware can do. That is 5x better than
  +1603 ppm.
- The snap is an optimisation only. A device with a different timebase
  floors to its own grid, and the readback reports it.

### E5. Report the achieved rate

**Decision.** `PicoScopeStream._report_samplerate` returns
`actual_raw_fs / effective_osr` as a float. This is the `samplerate` of each
block, of `VibeSample.samplerate` and of the HDF5 frame attribute. It is not
`config.raw_samplerate`. Every frequency axis is built from it.

**Why.** The driver quantises the interval to its own clock grid (E4), so the
achieved rate is generally not the requested rate. A requested-rate label
scales every displayed frequency by requested / achieved.

**Rejected: label the block with the requested rate.** Example from the
period when the raw rate followed F_max: at F_max = 2000 Hz the raw rate was
32768 Hz. The driver rounded 30.5 us down to 30 us: 33333 Hz raw, 8333.33 Hz
after decimation, labelled 8192 Hz (-1.70 %). The CHANGELOG gives this rate
as 8333.25 Hz; both values are recorded. A true 100 Hz tone displayed at
98.3 Hz, and a 60 Hz line read 59.0 Hz. This breaks harmonic families,
sideband spacing and BPFO/BPFI comparison with a nameplate.

**Measured on:** PicoScope 4424A, AWG loopback on channel A, 2026-08-28. The
same captured samples with two labels: a commanded 1000.00 Hz tone read
983.062 Hz (-1.694 %) with the requested rate and 1000.012 Hz (+0.001 %)
with the achieved rate. Mean error over four tones: 1.676 % against
0.034 %.

Keep the rate a float at every step, including persistence. A truncation of
25591.81 Hz to 25591 Hz moves every frequency by 32 ppm (computed).

### E6. Oversampling ratio

**Decision.** `PicoScopeStream._choose_osr(samplerate)` returns
`min(OSR_TARGET, floor(STREAMING_CEILING_HZ / samplerate))` = min(4,
floor(100000 / 25600)) = 3. If that is less than 2 it returns 1 and logs a
warning: `antialias_decimate` does nothing at factor 1, so there is no
anti-alias filter.

**Why the anti-alias filter must not be skipped.** A general-purpose IEPE
accelerometer has a mounted resonance at 25 kHz to 80 kHz, with 20 dB to
30 dB of gain. Example: at a raw rate of 65536 Hz (an F_max of 20 kHz), an
unfiltered 50 kHz component folds to 15536 Hz. That is inside the displayed
band, and it looks like real signal. **Measured on:** not measured; a
calculation from the August 2026 audit.

**Rejected alternative.** `max(1, int(min(OSR_TARGET, CEILING /
samplerate)))`. It truncates 1.526 to 1 at a 20 kHz F_max and 0.763 to 0
(then 1) at a 50 kHz F_max. Both run with no filter, and the 50 kHz F_max
requests 131072 Hz, 31 % above `STREAMING_CEILING_HZ`. The top F_max preset
is 10 kHz, so every preset gets an oversampling ratio of 3.

### E7. Resample ratio bound

**Decision.** `collector.decimate_to_rate` resamples the raw-rate block to the
display rate with `scipy.signal.resample_poly` and a Kaiser window at the
hardware stopband target (`picoscope._AA_STOPBAND_DB`). It bounds the
denominator of the up/down **ratio** with `_RESAMPLE_DENOM_LADDER` =
(4, 8, 16, 32, 64, 128, 256). The first cap that lands within
`_RESAMPLE_RATE_TOL` = 1e-3 of the requested rate wins. If no cap does, the
closest ratio is used. The function returns the achieved rate,
`raw_rate * up / down`. Every consumer builds its frequency axis from it,
not from `config.samplerate`.

**Why the bound is necessary.** `resample_poly` designs a FIR of
`2*10*max(up, down)+1` taps on every call. The denominator is therefore a
direct cost multiplier. At the cap of 256 the FIR has 5121 taps.

**Why 1e-3.** The grid-snapped streaming clock of the 4824A is -320 ppm
(3.2e-4) from nominal: 25591.81 Hz against 25600 Hz (E4). 1e-3 is larger
than this offset, so every shipped F_max preset gets its exact integer
factor. The tolerance bounds only the resample approximation. It does not add
to the clock error, because the returned rate is exact for the ratio used.

**Measured on:** the development PC, 2026-09-11, `decimate_to_rate` timed on
one 12800-sample block. The "hardware" row uses the rate that the 4824A
reported with a whole-microsecond interval request (25641 Hz, E4). The
"simulated" row uses the rate that `SimulatedSensor` reports.

| raw rate (Hz) | up / down | taps | ms per call | output length (samples) |
|---|---|---|---|---|
| 25600.00 (simulated) | 1 / 5 | 101 | 0.64 | 2560 |
| 25641.00 (hardware, ratio not bounded) | 5120 / 25641 | 512821 | 73.62 | 2556 |

- At 8 channels the unbounded case is 589 ms of main-thread work for each
  500 ms frame.
- The output of 2556 samples is less than `nperseg`. Welch then uses a
  shorter segment, so the bin width is not the value that the Spectrum tab
  shows.
- With the bound: worst case 1.05 ms for an off-preset F_max. At the
  hardware rate, 73.62 ms becomes 0.42 ms, and the output length is 2560
  samples.

**Rejected alternative.** `Fraction.limit_denominator` applied to each rate
before the division. Both rates are integers, so each reduces to
denominator 1, and the ratio is not bounded at all.

**Consequence for tests.** The cost is not visible with `SimulatedSensor`,
because 25600 Hz reduces to a small integer factor against every display
rate. A performance claim for this path needs the hardware-realistic rate
(`profile-pipeline --raw-rate`, section 7).

### E8. High-pass filter

`highpass_fc` is the declared lower band edge. The filter is a causal
Butterworth high-pass of order `AcquisitionSettings._BUTTER_ORDER` (4),
applied once at the raw rate by `DataCollector.filter_block`.

#### E8.1. Stateful filter

**Decision.** Two regimes.

- `stateful=True`: consecutive blocks of one live stream. `receive_data`
  filters each block once, in stream order, and carries the final filter
  state (`zi`) into the next block. The state is reset at stream start and
  when the filter configuration changes.
- `stateful=False`: a stored frame on replay, or a frame that is filtered
  again after a configuration change. Replay goes through frames out of
  order, so no state is carried between frames. Each block is seeded from its
  own mean (E8.2). Replay is bit-identical forward and reverse to 12
  significant figures.

**Measured on:** 2026-08-28, a 200 Hz tone, high-pass at 10 Hz, blocks 1 to
3 of a stream. The source (hardware or simulation) is not recorded. Error
against the true value:

| quantity | no `zi` (restart from rest every block) | steady-state `zi`, carried |
|---|---|---|
| waveform peak | +9.41 % | -0.00 % |
| RMS, with 1000 mV DC offset | +14321.74 % | -0.00 % |
| displacement overall | +19.15 % | +0.02 % |
| displacement overall, with DC offset | +1472786.72 % | +0.02 % |

**Rejected alternative: `sosfiltfilt` (zero-phase).** The forward and
backward passes double the effective filter order. With a low knee against
a short block (10 Hz over a 1 s block: 10 knee cycles of margin) the
response rings. On hardware data it overshot the raw signal by 35 % to 45 %
at both block edges, with every `padtype` (2026-08-28).

#### E8.2. Seed from the block mean

**Decision.** A block with no usable history (block 0 of a stream, or any
replayed block) starts from `sosfilt_zi(sos) * mean(x)`, not from
`sosfilt_zi(sos) * x[0]` (`DataCollector._seed_zi`).

**Why.** scipy's documented idiom uses `x[0]`. That is correct when the first
sample is the baseline, as for a step response. A vibration block swings
about its DC level, so `x[0]` is an arbitrary point on the swing. A seed from
`x[0]` tells the filter that the signal sat at that value before the block,
and the filter then decays a step that did not occur. Under 1/omega**2
integration that step dominates the displacement.

**Measured on:** PicoScope 4424A, AWG loopback on channel A, 2026-08-28.
Four consecutive captures, 447.3 Hz tone, 1 Vpp, raw rate 8333.25 Hz, 10 Hz
high-pass. The block mean was -0.06 to -0.21 mV in every block (the true DC).
`x[0]` was 36 to 305 mV. Error against a fully settled continuous-filter
reference, worst block for each row:

| order | `zi * x[0]` | `zi * mean(x)` | warm-up pass |
|---|---|---|---|
| acceleration | +0.39 % | -0.00 % | +0.00 % |
| velocity | +23.01 % | -0.06 % | -0.07 % |
| displacement | +4297.20 % | -2.22 % | +61.10 % |
| waveform | 57.63 % | 0.51 % | 6.37 % |

**Rejected alternative: warm-up pass.** Filter the block once and use its
final state as the initial state. It is worse than the mean (+61.10 % in
displacement), because it assumes that the block is periodic, and it is not.

**Residual error.** The displacement error on an isolated block cannot be
removed. At 447 Hz the doubly integrated result is dominated by near-DC noise
whose continuation is not in the block. This affects block 0 of a stream and
replayed frames only. With carried state, blocks 1 and later match the
settled reference to +/-0.000 %.

#### E8.3. Knee below the band edge

**Decision.** `DataCollector.highpass_knee_hz` designs the Butterworth at a
knee below `highpass_fc`, from `_dsp.butter_knee_for_edge`:

    |H(f)|^2 = (f/fc)^(2N) / (1 + (f/fc)^(2N))
    set |H(f_edge)| = A:
    r  = A^2 / (1 - A^2)
    fc = f_edge * r ** (-1 / (2N))

At order N = 4 and A = `PASSBAND_TOLERANCE` = 0.9, fc = 0.8342 x f_edge. A
10 Hz edge gives an 8.34 Hz knee and -0.915 dB (x0.900) at 10 Hz (design
value).

**Why.** ISO 2954 requires a broadband vibration-severity instrument to be
within +/-10 % of the true amplitude across its declared band, edges
included. A Butterworth designed at the edge is -3 dB (x0.707) there: 29 % low
at the frequency that the standard names as the bottom of the band.

**Why a lower knee is safe.** The overall is band-limited in the frequency
domain (the band mask in `process_sample`). The mask removes sub-band energy
exactly, so the 1/omega**2 increase that a higher knee guards against cannot
reach the integrated result.

**Measured on:** PicoScope 4424A, AWG loopback, 2026-08-29.

| frequency (Hz) | response (dB) |
|---|---|
| 100 | +0.00 |
| 20 | -0.04 |
| 10 | -1.05 (-3.0 with the knee on the edge) |
| 5 | -18.40 |

### E9. Tapers for integration

**Problem.** `process_sample` converts between acceleration, velocity and
displacement: it multiplies the rFFT of the block by `(j*omega)**n` and
transforms back. The DFT treats the block as periodic. Unless the signal is
exactly periodic in N samples, the block has a step at the wrap point. The
spectrum of that step is broadband with most energy at low frequency, and
`(j*omega)**n` with n < 0 amplifies it by 1/omega**|n|, where it is largest.

**Measured on:** synthetic 1.0 g 0-pk sine, fs = 32768 Hz, N = 16384,
displacement overall, no taper (computed offline, not hardware, 2026-08-28):

| tone (Hz) | on a bin? | true RMS | un-tapered | error |
|---|---|---|---|---|
| 500.0 | yes | 7.1645e-08 | 7.1645e-08 | +0.00 % |
| 501.0 | no | 7.1359e-08 | 3.2638e-06 | +4473.76 % |
| 61.0 | no | 4.8136e-06 | 2.7466e-05 | +470.59 % |
| 120.7 | no | 1.2294e-06 | 1.0793e-05 | +777.84 % |

The on-bin row has no error. A test suite that uses only bin-centred tones
cannot find this defect. This is why amplitude tests are off-bin (section
6.1).

**Decision: two treatments.**

- **Scalar overalls** (trend, result card, anomaly detector) need an unbiased
  RMS over the whole record. All five integration orders, order 0 included,
  use a Hann taper, the band mask, the inverse transform, and division by the
  window power gain `sqrt(mean(w**2))` (`_dsp.hann_taper`).
- **Displayed waveform.** A Hann taper would be visible as an amplitude
  envelope on the trace. The waveform uses overlap-save instead: a Tukey
  window (flat in the middle, cosine at the edges) removes the wrap step, and
  only the flat middle is returned (`_dsp.tukey_taper`,
  `_dsp.tukey_keep_slice`). There the window is exactly 1.0, so the samples
  are not changed. `time_vec` is cut to match and keeps the true
  capture-relative times. The trace is band-limited to the same band as the
  overall.

With the tapers: displacement overall at 501.0 Hz +4473.76 % -> +0.00 %; at
61.0 Hz +470.59 % -> +0.18 %; at 120.7 Hz +777.84 % -> +0.05 %; velocity overall at 61.0 Hz +12.25 % ->
+0.05 %.

**Order 0 uses the taper too.** The band mask is a transform-domain multiply,
so it has the same wrap sensitivity as integration. An untapered mask was
rejected: a 30 Hz tone below a 100 Hz lower band edge leaked in at -22 dB and
made the overall +2.70 % high, against -84 dB with the Hann taper (E10).
`tests/test_measurement_validity.py`,
`test_passthrough_overall_recovers_the_tone_rms_off_bin`, keeps the Hann path
for order 0.

**Tukey `alpha`** (`_dsp.WAVEFORM_TUKEY_ALPHA` = 0.5, the fraction of the
block in the cosine tapers, half at each end). Measured waveform peak error
against `alpha`, synthetic tones (same method as the table above; fs and N
are not recorded beside this table):

| alpha | block kept | 61 Hz velocity | 61 Hz displacement | 501 Hz displacement |
|---|---|---|---|---|
| 0.00 | 100 % | +90.22 % | +1149.12 % | +10176.68 % |
| 0.05 | 95 % | +32.75 % | +335.84 % | +18.56 % |
| 0.10 | 90 % | +0.18 % | +7.00 % | +0.85 % |
| 0.30 | 70 % | +0.14 % | +4.22 % | +0.58 % |
| 0.50 | 50 % | +0.10 % | +1.47 % | +0.24 % |

0.5 is the first value that keeps every case below 2 %. The cost: an
integrated or band-limited waveform shows the middle 50 % of the block. A
full-band passthrough (order 0, band covers 0 Hz to fs/2) shows the whole
block.

**Bin 1 on integration.** `_dsp.integrate_rfft` zeroes bin 0 always, and bin
1 for n < 0. One time-domain high-pass pass cannot stop residual near-DC
energy from growing as 1/f**n. On hardware, bin 1 otherwise dominated the
spectrum. `process_sample` zeroes the same bin in the integrated PSD.

### E10. Band RMS

**Decision.** The overall does not use Parseval's theorem on an untapered
rFFT (the sum of the masked bin powers, with weight 2 for each bin except DC
and, for even n, the Nyquist bin). `DataCollector.process_sample` computes
the overall on the Hann-tapered, band-masked rFFT of E9. There is no separate
band RMS function.

**Rejected alternative: untapered Parseval.** With a full mask it equals
`sqrt(mean(x**2))`, and it is exact for in-band content. But its band edge
has the -13 dB first sidelobes of a rectangular window, so out-of-band lines
leak into the overall.

**Measured on:** offline computation over the preset grid, 2026-08-29.

| case | untapered Parseval | Hann path |
|---|---|---|
| 3x tone at 30 Hz, 100 Hz lower band edge | leaks in at -22 dB, overall +2.70 % | rejected by -84 dB |
| other cases measured | not recorded | rejected by -100 to -144 dB |
| worst in-band error over the preset grid | 0 (exact) | 4.9e-4 |

Band rejection matters more for an instrument than the fifth decimal place.

**Hardware check of the band mask:** PicoScope 4424A, AWG loopback, declared
band 10 Hz to 1000 Hz at F_max 2000 Hz, 2026-08-29. 800 Hz +0.0 dB, 950 Hz
-0.0 dB, 1000 Hz -3.1 dB, 1100 Hz -58.2 dB, 1300 Hz -58.6 dB, 1600 Hz
-58.9 dB.

**Why the band mask exists.** Without it the overall covers `highpass_fc` to
fs/2, not to F_max. Content that the user excluded with F_max then reaches
the trend: 2 g RMS at 1500 Hz with a 1000 Hz F_max made the velocity overall
+25 % high, enough to cross an ISO 20816 zone boundary.

### E11. Display rate, block size and line count

**Decision.** In `AcquisitionSettings` (`sample.py`):

- `samplerate` = round(2.56 x `maxfreq`). Nyquist is 1.28 x `maxfreq`, a
  28 % guard band for the anti-alias filter. The `maxfreq` setter clamps to
  `raw_samplerate / 2 / 1.28`, which is the condition
  2.56 x `maxfreq` <= `raw_samplerate`.
- `blocksize` = ceil(`samplerate` / `binsize`): the shortest block whose bin
  is not coarser than `binsize`.
- `nperseg` = `blocksize`: one Welch segment for each frame.
- `n_fft_bins` counts the lines from DC to `maxfreq`, not `nperseg // 2 + 1`.

**Rejected alternative: power-of-two rate and block.** `samplerate` =
nextpow2(2.56 x `maxfreq`) and `blocksize` = nextpow2(`samplerate` /
`binsize`). With `RAW_SAMPLERATE_HZ` = 25600 Hz the top preset rounds to
32768 Hz, more than the raw data. `decimate_to_rate` then returns the block
at 25600 Hz while the dialog shows 32.8 kS/s, and `n_fft_bins` and
`binsize_actual` come from a rate that does not exist. A power-of-two block
also makes a frame up to 2x longer than 1/`binsize`. Measured worst-case
frame-length overshoot over the 54 preset combinations: 56.2 % with
power-of-two sizes, 17.2 % with the current rule (2026-09-09).

**Rejected alternative: Welch nfft different from the block.** Welch with
`nfft = int(samplerate / binsize)` while `blocksize` is larger gives a line
count and a bin width that are not the ones that the UI shows. 40 of 72
preset combinations of that time (8 F_max x 9 binsize) were wrong. Examples:
F_max = 200 Hz, df = 20 Hz showed 17 lines against 13 real lines at
20.48 Hz; F_max = 2000 Hz, df = 5 Hz showed 1025 lines against 820
(2026-08-28).

**Block sizes that are not exact.** Computed with the current code over all
54 combinations of `MAXFREQ_PRESETS` and `BINSIZE_PRESETS`, 2026-09-29. In
43 combinations `binsize_actual` equals `binsize`. In 11 it is finer, and in
10 of these 11 `blocksize` is not 5-smooth (it has a prime factor above 5):

| F_max (Hz) | binsize (Hz) | samplerate (Hz) | blocksize | 5-smooth | binsize_actual (Hz) |
|---|---|---|---|---|---|
| 200 | 5 | 512 | 103 | no | 4.971 |
| 200 | 10 | 512 | 52 | no | 9.846 |
| 200 | 20 | 512 | 26 | no | 19.692 |
| 200 | 50 | 512 | 11 | no | 46.545 |
| 200 | 100 | 512 | 6 | yes | 85.333 |
| 500 | 50 | 1280 | 26 | no | 49.231 |
| 500 | 100 | 1280 | 13 | no | 98.462 |
| 1000 | 50 | 2560 | 52 | no | 49.231 |
| 1000 | 100 | 2560 | 26 | no | 98.462 |
| 2000 | 50 | 5120 | 103 | no | 49.709 |
| 2000 | 100 | 5120 | 52 | no | 98.462 |

The GUI offers every `BINSIZE_PRESETS` value at every F_max
(`gui.py`, `_BINSIZE_LABELS`). The blocks that are not 5-smooth are 103
samples or less, so their FFT cost is small.

**Live line count.** `n_fft_bins` is nominal. The live spectrum uses the
achieved rate (E5). At F_max = 10 kHz, df = 0.25 Hz and 25591.81 Hz the live
spectrum has 40013 lines up to F_max against a nominal 40001 (computed with
`decimate_to_rate` and `numpy.fft.rfftfreq`, 2026-09-29).

**The display stops at F_max.** The spectrum, the peaks table and the
left-panel label stop at F_max (`gui._update_spectrum_info`). The band from
F_max to fs/2 (1.28 x F_max) is the anti-alias guard band. Alias rejection
there is not a specification that the instrument meets:

| Frequency | Alias rejection |
|---|---|
| The frequency that folds onto F_max | -21.8 dB |
| fs/2 | about 0 dB |

For this reason the left panel labels F_max, not fs/2 as an "AA" frequency.
**Measured on:** the August 2026 audit. The audit does not record the
method.

### E12. Peak selection

`peaks.select_peaks` reports the spectral lines. The subsections give the
method, the floor estimator width, the band-edge handling and the minimum
peak spacing.

#### E12.1. Method

**Decision.** Report a bin when it stands `threshold_db` above its own local
noise floor. Do not report a fixed top-N by absolute amplitude. The count of
peaks is an output. Rank the reported lines by amplitude. The reported
amplitude is the amplitude of the maximum bin. Energy is not summed across
the bins of a peak (owner decision).

**Measured on:** the recorded `old castle` corpus, 60 channel-spectra (20
`.h5` files x 3 channels). The capture hardware and the capture date are not
recorded. The example file is `blower 4 - bearing DE.h5`, channel 2.

Why a ranking by absolute amplitude fails:

- The local noise floor is not flat. Across the 60 channel-spectra it varies
  by up to 7x inside one spectrum.
- On `blower 4 - bearing DE.h5` ch2 the median local floor is 9.0 mV over
  the full spectrum, but 39.4 mV over 1890 Hz to 2000 Hz.
- A top-N by amplitude ranks by the loudness of the neighbourhood: 6 of the
  top 12 lines of that spectrum came from the 110 Hz stretch at the top of
  the band. Some were ripple, not lines: 1982 Hz sat 2.2x above its local
  floor, 1967 Hz 1.6x.
- The sidebands at 1034 Hz and 1088 Hz (+/-25 Hz and +/-29 Hz around the
  1059 Hz carrier, the bearing-fault signature) ranked 10th and 4th. At a
  display count of 6 the sideband family was broken up and removed from the
  table.

The method, in one `scipy.signal.find_peaks` call:

1. Estimate the local noise floor for each bin (`local_noise_floor`).
2. Pass array-valued `height` and `prominence`, derived from that floor.
3. Report every bin that passes. The user setting is a significance
   threshold in dB.

Rank by amplitude, not by significance: the table answers "how big is it".
A 0.2 mV line on a quiet floor is not the top line of the spectrum.

**Floor estimator** (`local_noise_floor`): a running median of bin power, not
of amplitude, because the median-to-mean correction is a statement about
power. A median, not a mean, keeps the discrete lines out of the estimate:
with the corpus median gap of 22 bins between significant peaks, a 65-bin
window holds about three lines, in less than a fifth of its samples.

A dense line family lifts the floor estimate a little. Lines every 22 bins
put 9 of 65 window samples high. Lift of the floor on synthetic spectra, 20
trials (`tests/test_peak_selection.py`,
`test_strong_lines_barely_lift_the_floor_estimate`):

| Line gap | Median lift | p95 lift |
|---|---|---|
| 11 bins | +2.12 dB | +3.39 dB |
| 22 bins | +0.84 dB | +1.80 dB |
| 44 bins | +0.35 dB | +1.15 dB |
| 88 bins | +0.13 dB | +0.75 dB |

The bias is upward, so a dense family makes the gate reject more lines, not
admit more noise.

**Median-to-mean correction** (`median_to_mean_ratio`): with one Welch
segment the bin power is exponential and the ratio is `ln 2`. With N segments
it is `Gamma(N, 1/N)`:

| Segments | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| median/mean | 0.693 | 0.839 | 0.913 | 0.956 | 0.978 |

The app runs one segment (`nperseg == blocksize`), so the ratio is `ln 2`
in every preset. The general form stays because that invariant belongs to
`AcquisitionSettings`, not to the statistics. A wrong ratio biases the whole
floor by up to 3.1 dB, in the direction that admits noise.

**The four admission terms** (`select_peaks`):

- The bin rises `threshold_db` above its local floor.
- The bin is not more than `ABSOLUTE_FLOOR_DB` below the largest bin in the
  band.
- The prominence is at least `PROMINENCE_RATIO` x the height threshold,
  inside +/-`wlen`/2 bins.
- The bin is the tallest such bin within `peak_distance_bins`.

The prominence term has the most value of the four. `height` alone admits
shoulders and ripple on a broad hump, because each sample of the hump clears
the same threshold.

**Default threshold** (`DEFAULT_THRESHOLD_DB` = 9.5 dB). Mean false alarms
per 2001 bins of pure noise, synthetic flat floor
(`tests/test_peak_selection.py`,
`test_the_default_threshold_sits_above_the_false_alarm_knee`; the trial
count of the table is not recorded, the test uses 20):

| Threshold | Mean false alarms |
|---|---|
| 6.0 dB | 37.9 |
| 9.5 dB | 0.8 |
| 12.0 dB | 0.0 |
| 15.5 dB | 0.0 |

A 6 dB gate would fill a third of the table with noise. At 9.5 dB, a
separate run gave a mean of 0.73 false alarms per 2001 bins over 60
realisations, maximum 3.

**Count of peaks** at the default threshold over the 60 corpus
channel-spectra: median 40, p10 23, p90 50, minimum 16, maximum 63 (from
`peaks.py`). The CHANGELOG (2026-08-29) and the comment beside
`gui._DEFAULT_PEAK_DISPLAY_CAP` give p10 22, p90 49, maximum 61 for the same
corpus. The reason for the difference is not recorded.

`ABSOLUTE_FLOOR_DB = -40.0`: floor-relative significance alone promotes
high-pass roll-off residue. On `blower 4 - bearing DE.h5` ch2 the 1 Hz bin
(0.21 mV) and the 14 Hz bin (2.67 mV) sit on a quiet floor and reach SNR
ranks 9 and 6. The absolute term costs almost nothing: the median gated peak
count is 40 at -40 dB against 41 at -50 dB.

`PROMINENCE_RATIO = 2/3`: at the default 9.5 dB threshold, height is 2.99x
the floor and prominence is 1.99x the floor. This is the (3x, 2x) pair that
the corpus study selected. The ratio keeps the pair when the user moves the
threshold.

`PROMINENCE_WLEN_BINS = 41`: always pass `wlen` with `prominence`.
Unbounded, `find_peaks` walks out to the base of the nearest taller
neighbour, which on a 2001-bin spectrum can be most of the band away.
Measured on the ch2 top 12, minimum prominence/amplitude:

| `wlen` (bins) | 11 | 21 | 41 | 81 | 201 | unbounded |
|---|---|---|---|---|---|---|
| min prominence/amplitude | 0.366 | 0.561 | 0.561 | 0.561 | 0.561 | 0.561 |

At 11 bins the real prominence is truncated. From about 4x `distance`
upward the value is safe; 41 limits the cost. `select_peaks` uses
`max(PROMINENCE_WLEN_BINS, 4 * distance + 1)`.

**Rejected alternatives:**

- `width=`: no discrimination. On the ch2 spectrum, noise-ripple maxima
  (amplitude < 1.5x floor) have a median width of 1.87 bins. Real lines
  (> 5x floor) have 2.10 bins, p10 1.84. The distributions overlap almost
  fully.
- `threshold=`: it compares a sample with its two immediate neighbours
  only. This is too noisy at these SNRs (corpus median peak/floor: 13.2 dB).
- Energy summed across the bins of a peak: out of scope by owner decision.

#### E12.2. Floor width

**Decision.** `FLOOR_MEDIAN_WIDTH_BINS = 65`.

**Measured on:** the `old castle` corpus. Each file holds 16 frames of the
same machine in the same state. The reference floor is the average of the 16
power spectra (16-fold lower bin-power variance), median-filtered with a
31-bin window. The single-frame estimator was scored against that reference
over 20 files x 3 channels x 4 frames.

| Width (bins) | Median abs. error (dB) | p95 abs. error (dB) |
|---|---|---|
| 17 | 1.522 | 4.694 |
| 31 | 1.097 | 3.185 |
| 45 | 1.039 | 3.074 |
| 65 | 1.085 | 3.354 |
| 91 | 1.181 | 3.856 |
| 129 | 1.326 | 4.553 |
| 257 | 1.705 | 6.572 |

The optimum is a flat basin from 31 to 65 bins. 45 bins is the minimum; 65
bins costs 0.05 dB more, which is less than the 1.0 dB noise of the
estimate. Below 31 bins the window does not average down the exponential
bin-power scatter. Above 91 bins it smears real floor structure, which
changes over tens of bins on this machinery.

**Rejected:** a synthetic spectrum with a smooth floor prefers 129 bins. The
synthetic floor is too smooth to be a guide; the value comes from the
recorded corpus.

#### E12.3. Edge handling

**Decision.** `_running_median` uses a truncated window at the two band
edges. At bin *i* the result is the median of the bins within +/-width//2 of
*i* that exist.

**Why `scipy.signal.medfilt` (zero padding) is not used.** Near an edge, the
padded zeros displace real samples from the lower half of the window, so the
statistic moves from the local median toward the local minimum. On
`blower 4 - bearing DE.h5` ch2, where the true floor at the top of the band
is 39.4 mV, the zero-padded estimate reads 32.8 mV at 1995 Hz, 14.9 mV at
1999 Hz and 5.68 mV at 2000 Hz. 1999 Hz then shows an SNR of 6.44 against a
true SNR of 2.93: ordinary ripple is admitted as a strong line. The bias is
one-sided (always down) and always at the band edges.

**Measured on:** synthetic spectra with a known floor, the +/-32 edge bins at
width 65, 40 trials.

| Edge handling | Median abs. error (dB) | p95 abs. error (dB) | Mean bias (dB) |
|---|---|---|---|
| zero-pad (`medfilt`) | 2.368 | 11.448 | -3.568 |
| replicate (`'nearest'`) | 1.480 | 5.246 | -0.009 |
| reflect | 0.620 | 1.844 | +0.098 |
| truncated window | 0.591 | 1.829 | +0.050 |

**Rejected alternatives:**

- Replication removes the bias but not the error. It copies one random bin
  32 times, and 32 copies of one exponential draw control a 65-sample
  median.
- Reflection uses 32 independent samples, like truncation, and gives almost
  the same error. It can mirror a strong line back across the edge onto
  itself. Truncation invents no data and measured slightly better.

Cost of truncation: the estimate is noisier in the last half-window, because
there is less data there.

`tests/test_peak_selection.py` keeps this: the vectorised edge code is
bit-identical to a per-bin `np.median` loop, and a line at the band edge is
not mirrored. The speed of the edge code is in E19.

#### E12.4. Window nulls

**Decision.** `WINDOW_FIRST_NULL_BINS`, and `distance = 2 * null + 1`, so the
two flanks of one main lobe are never reported as two peaks.

**Measured on:** computation. Each window was transformed 64x oversampled,
and the first local minimum was found.

| Window | First null (bins) |
|---|---|
| boxcar | +/-1 |
| hann, hamming, bartlett | +/-2 |
| blackmanharris | +/-4 |
| flattop | +/-5 |

**Rejected:** a fixed `distance=5`. It is correct for hann only. For boxcar
it merges distinct lines 2 to 4 bins apart.

### E13. Envelope band search

**Decision.** `envelope.suggest_band` proposes a demodulation band centred on
the strongest high-frequency energy. The user does not have to know the
frequency of the housing resonance to get a first result.

- The search covers 0.25 x top to top only. Below that is machine content
  (1x and harmonics), which demodulation must remove, so a band centred
  there has no use.
- The power spectrum (Hann window) is smoothed over the band width
  (`SUGGEST_BAND_FRAC = 0.25` of top) before the argmax. The band energy,
  not one tall line, selects the centre: one harmonic is not a resonance.
- `top` is `fmax`, or Nyquist when `fmax` is not given, and never above
  0.99 x Nyquist. The contract: pass the upper edge of the usable band, so
  the suggestion stays out of the anti-alias transition band. The GUI passes
  `gui.envelope_search_fmax(samplerate)` = raw rate / 2.56 (10 kHz at
  25600 Hz nominal).
- `BANDPASS_ORDER = 4`, Butterworth, zero-phase (`sosfiltfilt`), so the
  effective order is 8. The reason in the code: steep enough to reject a 1x
  up to 40 dB above the resonance, and numerically stable as SOS at the
  narrow relative bandwidths of a resonance band. The 40 dB figure is not a
  recorded measurement.
- `DEFAULT_ENVELOPE_FMAX = 500.0` Hz: defect rates and their first
  harmonics are below this value.
- `MIN_USEFUL_NYQUIST_HZ = 5000.0`: below this Nyquist frequency a housing
  resonance (typically 2 kHz to 20 kHz, a literature value, not measured
  here) is probably not in the record.

**Measured on:** nothing. No measurement table exists for the band search.
`tests/test_envelope.py` covers the behaviour. The operator physics of
envelope analysis is in `README.md`, "Envelope analysis".

### E14. Tachometer

`src/rev80/tach.py` finds the edges of a tachometer pulse train and
calculates the shaft speed. Each subsection gives one decision, the value,
the evidence and the conditions of the measurement.

Most tables in this section were measured in September 2026 (2026-09-01) at
a raw rate of 40000 Hz nominal. The driver rounded the sample interval to
12 us, so the achieved rate on hardware was 41666.5 Hz (83333/2 Hz), and the
ADC ran at about 83.3 kHz for each channel (oversampling ratio 2). The raw
rate is now 25600 Hz nominal: about 25591.8 Hz achieved on the 12.5 ns clock
grid (E4), oversampling ratio 3. The tables were not measured again at
25600 Hz, except where a line says so.

The code takes the rate from the sample (`VibeSample.samplerate`), never
from `RAW_SAMPLERATE_HZ`. With the constant, every shaft speed was 4.166 %
high on hardware at the 41666.5 Hz rate and correct in CI (E5).

#### E14.1. No high-pass on a tachometer channel

**Decision.** `DataCollector.receive_data` finds the edges of a tachometer
channel on the raw mV block. The Butterworth high-pass does not run on that
channel, and `process_samples()` makes no `ChannelResult` for it.

**Why no vibration processing.** A pulse train through the vibration path
does not raise an error. It gives a plausible wrong answer. On a 5 % duty
square wave through `DataCollector.process_sample`: overall 1515 mV, crest
factor 5.00, kurtosis 15.94, 63 "peaks". This reads as a failing bearing.

**Why no high-pass.** A 5.00 V pulse train, 1.0 s block, edges at a 2.5 V
threshold:

| Shaft speed (RPM) | Pulse width | Duty | Raw high / low (mV) | After high-pass (mV) | Raw edges | High-pass edges |
|---|---|---|---|---|---|---|
| 300 | 1 ms | 0.5 % | 5440 / -440 | 5420 / -1124 | 6 | 6 |
| 1800 | 200 us | 0.6 % | 5441 / -465 | 5442 / -585 | 31 | 31 |
| 1800 | 5 ms | 15 % | 5440 / -440 | 5891 / -3390 | 31 | 108 |
| 3600 | 10 ms | 60 % | 5440 / -440 | 3961 / -5341 | 61 | 60 |

At 15 % duty the high-pass overshoot on each falling edge crosses the
threshold again. An 1800 RPM shaft then reads 6270 RPM.

**Measured on:** PicoScope 4424A, AWG loopback, 41666.5 Hz, September 2026.

#### E14.2. Accuracy

**Result.** +/-0.2 % of reading at 1 pulse per revolution, from 300 RPM to
10200 RPM. The error increases with shaft speed, so the claim is a
percentage of reading, not a fixed value in RPM. Identification of spectral
lines needs 0.3 %.

AWG square wave into channel A, DC coupled, +/-5 V range, 2 Vpp at 1 V
offset, adaptive threshold:

| AWG (Hz) | True (RPM) | Measured (RPM) | Error (RPM) | Error (%) | Edges | Spread |
|---|---|---|---|---|---|---|
| 5 | 300 | 299.508 | -0.492 | -0.164 | 5 | 0.0001 |
| 10 | 600 | 600.153 | +0.153 | +0.026 | 10 | 0.0001 |
| 30 | 1800 | 1800.383 | +0.383 | +0.021 | 29 | 0.0003 |
| 60 | 3600 | 3599.818 | -0.182 | -0.005 | 57 | 0.0004 |
| 100 | 6000 | 6001.106 | +1.106 | +0.018 | 96 | 0.0010 |
| 170 | 10200 | 10204.025 | +4.025 | +0.040 | 163 | 0.0024 |

**Measured on:** PicoScope 4424A, s/n 12462/0067, AWG loopback on
channel A, achieved rate 41666.5 Hz, 2026-09-01.

**Check at 25600 Hz nominal:** same 4424A, AWG loopback, 2026-09-18. The 27
hardware tests pass. This includes `test_tracks_a_speed_sweep` (the six
points above, assertion +/-0.2 %) and 1, 2 and 6 pulses per revolution
against a 60 Hz square (3600, 1800 and 600 RPM). The per-point errors at
25600 Hz are not recorded. The table above is the 41666.5 Hz result only.

#### E14.3. Interpolation

**Decision.** `_schmitt` interpolates each threshold crossing between the
two samples on each side of it (`_interp`).

**What arrives from the hardware.** A TTL or keyphasor tachometer switches
in nanoseconds, and the scope has no analog anti-alias filter. An ideal
step would put both samples at the rails, and interpolation would give
nearest-sample rounding. The bench shows otherwise. A captured edge has
exactly one intermediate sample (58 samples inside the 10 % to 90 % band,
across 58 transitions of a 30 Hz square). About 8 % Gibbs ringing is on
each side. The interpolated fraction is in the range 0.294 to 0.707, not a
constant, so it carries sub-sample position.

Interpolated against nearest-sample, same captures:

| Pulse rate | Samples per period | Interpolated error | Nearest-sample error | Gain |
|---|---|---|---|---|
| 30 Hz | 1388.9 | 0.021 % | 0.008 % | 0.4x |
| 200 Hz | 208.3 | 0.038 % | 0.160 % | 4.2x |
| 600 Hz | 69.4 | 0.047 % | 0.644 % | 13.8x |
| 1500 Hz | 27.8 | 0.791 % | 0.794 % | 1.0x |
| 3000 Hz | 13.9 | 0.785 % | 0.794 % | 1.0x |

Three regimes:

1. From about 70 to about 1000 samples per period, interpolation is 4x to
   14x better than rounding.
2. Above about 1000 samples per period, interpolation is a little worse
   than rounding. Quantisation there is less than 0.07 %, and dither
   averages it. Both errors are small, and the difference has no effect.
3. Below about 40 samples per period, both give about 0.8 % error. The
   median locks on the most frequent integer period (27.778 samples reads
   as 28.000). The compressed 0.29 to 0.71 transfer cannot recover the
   fraction.

**Measured on:** PicoScope 4424A, s/n 12462/0067, bench captures, achieved
rate 41666.5 Hz, 2026-09-01. The samples-per-period column is consistent
with 41666.7 Hz.

**Limit that follows: `MIN_SAMPLES_PER_PULSE = 70`.** Full accuracy needs
70 samples or more for each pulse period. The limit is a count of samples,
so the shaft speed where it applies changes with the raw rate and with the
pulses per revolution. The front ends calculate it. `gui._update_tach_tab`
uses the achieved rate of the sample. `headless._tach_summary_lines` uses
the nominal `config.raw_samplerate` in the start summary, and headless logs
the limit again at the achieved rate after the first frame.

| Pulses/rev | At 41666.5 Hz (measured rate, 2026-09-01) | At 25591.8 Hz (now) |
|---|---|---|
| 1 | about 35700 RPM | about 21900 RPM |
| 6 | about 5950 RPM | about 3660 RPM |
| 60 | about 595 RPM | about 366 RPM |
| 1024 | about 35 RPM | about 21 RPM |

The 25591.8 Hz column is computed from the 70-samples-per-pulse limit, not
measured at 25.6 kHz.

**Not isolated.** Which stage limits the edge bandwidth is not known.
`antialias_decimate` is the only low-pass after the ADC and is the
probable cause. But a pure step between two 83 kHz ADC samples would
spread symmetrically and carry no sub-sample information, so a stage
before it also contributes. The design uses the measured effect, not the
cause. At 25600 Hz the oversampling ratio and the anti-alias filter are
different, so the regimes can move. This is not measured.

**Consequence for tests.** An ideal rectangle is a degenerate stimulus, not
a conservative one: no sample lands in the hysteresis band, and
interpolation has nothing to interpolate. Accuracy tests must send their
signals through `antialias_decimate` or use a finite-rise pulse
(`make_ramped_pulses` in `tests/test_tach.py`). In `simulation.py`,
`TACH_RISE_SAMPLES = 1.5` models the one intermediate sample that a real TTL
edge has on a 4424A. Otherwise the tests measure quantisation.

**Divide by zero in `_interp`.** It cannot occur. An edge needs a decided
low state before it, so `y0 <= hi < y1` and the denominator is positive.
The minimum denominator across 2880 real edges was 1461.7 mV. The guard in
the code is for defence only.

**Vectorised detection.** The vectorised Schmitt trigger took 0.090 ms on a
1.0 s block, against 6.1 ms for a sample-by-sample loop (2026-09-01, raw
rate 40000 Hz nominal; hardware or simulation is not recorded). The loop
also reported a false edge at sample 1 when a block started during a
pulse. The vectorised form needs a real low-to-high crossing.

#### E14.4. One pulse per revolution and `MIN_REVS`

**Decision.** One pulse per revolution is the default and the recommended
configuration. `pulses_per_rev` is configurable, because an encoder or a
keyphasor that is already on a machine cannot be changed. The minimum data
for a reading is `MIN_REVS = 2.0` whole revolutions, not a fixed edge
count. `min_edges_for(ppr)` converts it to rising edges:
`ceil(MIN_REVS * ppr) + 1`. At 1 pulse per revolution this is 3 edges.

**Why 1 pulse per revolution is accurate.** At 1 pulse per revolution each
interval is exactly one revolution. The two largest error sources cancel
inside each interval: encoder division error and once-per-revolution speed
modulation (load zone, misalignment, reciprocating load). Above 1 pulse per
revolution they cancel only after one whole revolution.

60-line encoder, +/-0.05 deg division error, 0.5 % once-per-revolution
speed modulation, 40 random start phases:

| Revolutions | Pulses | Mean error | Worst error |
|---|---|---|---|
| 0.05 | 3 | 0.580 % | 1.898 % |
| 0.25 | 15 | 0.344 % | 0.869 % |
| 0.50 | 30 | 0.260 % | 0.704 % |
| 1.00 | 60 | 0.091 % | 0.383 % |
| 2.00 | 120 | 0.091 % | 0.383 % |
| 20.0 | 1200 | 0.091 % | 0.383 % |

The error is flat from one revolution. More pulses do not help. The same
test at 1 pulse per revolution gives 0.0013 % from three edges, 70x better
than 60 pulses per revolution at any window length.

**Measured on:** PicoScope 4424A, AWG loopback, 41666.5 Hz, September 2026.

**Why `MIN_REVS` is 2.0, not 1.0.**

- The table shows that one revolution is sufficient above 1 pulse per
  revolution. At 1 pulse per revolution, one revolution is one interval.
  A median and a spread need two intervals. 2.0 satisfies both conditions
  with one gate.
- The drift test (`_MIN_EDGES_FOR_DRIFT`) compares the two halves of the
  block. With 2.0, each half spans one revolution, so once-per-revolution
  modulation cancels in each half. With 1.0, a steady shaft with a load
  zone would read as 'unsteady'.

**Hardware check at 25600 Hz nominal:** 4424A, AWG loopback, 2026-09-18. A
5 Hz square in a 1 s block gives about 5 rising edges. At 1 pulse per
revolution it reads 300 RPM. At 6 pulses per revolution the block holds 0.8
of a revolution, and the reading is `None` with quality 'too_few_edges'.

**Slowest shaft.** A block must contain whole pulse periods at any start
phase, so the floor is `min_edges_for(ppr) * 60 / ppr / T_block` RPM.
`slowest_rpm_for` holds the table for 1 pulse per revolution, and
`tests/test_tach.py` checks it. A finer encoder does not read a much slower
shaft: at a 1 s block the floor is 180 RPM at 1 pulse per revolution and
121 RPM at 60. To read a slower shaft, use a longer block (a smaller
binsize).

**Rejected: find pulses per revolution from the pulse periods.** Reflectors
with unequal spacing already give 'inconsistent' from the interval-spread
test, when the two gaps differ by more than about 90 deg of shaft rotation.
A pair with almost equal spacing reads an exact integer multiple of the
speed. A technician who knows the machine sees that error immediately.

#### E14.5. Signal floor

**Decision.** `MIN_PULSE_AMPLITUDE_MV = 1000.0`. A block with a smaller
peak-to-peak span has no tachometer signal. The quality is 'no_signal' and
`rpm` is `None`, never 0.0.

**Evidence.** AWG idle, 40000-sample block (0.96 s at 41666.5 Hz), DC
coupled. This is a disconnected input, or a stopped input with a flat
level:

| Range | Noise (mV RMS) | Block span (mV) | Margin to 1000 mV |
|---|---|---|---|
| +/-1 V | 0.372 | 2.93 | 342x |
| +/-2 V | 0.514 | 3.90 | 256x |
| +/-5 V | 0.870 | 8.35 | 120x |
| +/-10 V | 3.607 | 28.34 | 35x |
| +/-20 V | 5.091 | 42.51 | 23.5x |

1000 mV is 23.5x above the largest measured span. It is half of the 2 V
minimum swing of a logic-level tachometer. Without the gate, an adaptive
threshold on noise gives about 9100 edges per block, which is 547752 RPM.

**Rejected: a span/MAD ratio test.** Noise gives a ratio of about 12.5. A
50 % duty pulse train with 80 mV noise gives 9.3, which is below the noise.
The test rejects the signal that it must accept.

**Measured on:** PicoScope 4424A, s/n 12462/0067, achieved rate
41666.5 Hz, 2026-09-01. Not measured again at 25600 Hz.

#### E14.6. Spread and drift limits

**`INTERVAL_SPREAD_MAX = 0.25`.** The spread is
max|interval - median| / median. Above 0.25 the quality is 'inconsistent':
one edge is missing or extra, which is a sensor problem.

1800 RPM, 1.0 s block, 200 repetitions:

| Case | p50 | p99 |
|---|---|---|
| clean | 0.001 | 0.001 |
| 0.5 % cycle jitter | 0.016 | 0.025 |
| 2 % cycle jitter (worst legitimate case) | 0.064 | 0.096 |
| one edge missing | 1.000 | |
| one extra edge | 0.998 | |

0.25 is 2.6x above the worst legitimate jitter and 4x below one wrong edge
count.

An 'inconsistent' or 'unsteady' reading keeps its `rpm`, but
`TachResult.is_usable` is False. The speed gate
(`DataCollector.current_rpm(usable_only=True)`) and the RPM trend use only a
usable reading, so the gate fails closed on such a frame. The frame is still shown and stored.

**`SPEED_DRIFT_MAX_PCT = 1.0`.** Above a 1.0 % speed change inside one
block, the quality is 'unsteady'. Bearing analysis needs steady state. The
code rejects a smeared spectrum; it does not correct it. For this reason
there is no order-resampling path. Bearing tone at 5.43x shaft speed, 1.0 s
block:

| Drift over block | Peak height | Smear at 0.25 Hz bins |
|---|---|---|
| 0.1 % | 100.6 % | 0 bins |
| 0.5 % | 94.4 % | 4 bins |
| 1.0 % (the limit) | 93.8 % | 9 bins |
| 2.0 % | 82.6 % | 18 bins |
| 5.0 % | 69.6 % | 46 bins |

At 1.0 % the peak-height error is less than about 6 % and the smear is less
than about 10 bins. A mains-fed motor at steady load drifts less than
0.1 %. The limit operates on VFD ramps and load steps.

**Measured on:** the spread table: PicoScope 4424A, AWG loopback,
41666.5 Hz, September 2026. The drift table: source not recorded; the comment
beside `SPEED_DRIFT_MAX_PCT` in `tach.py` says simulation only. PROGRESS R63
verifies the drift limit on hardware.

#### E14.7. Median estimator

**Decision.** `estimate_rpm` uses the median of the intervals, not the time
from the first edge to the last edge.

Error in RPM at 1800 RPM, 200 repetitions:

| Case | First-to-last | Median of intervals |
|---|---|---|
| clean | -0.02 +/- 0.00 | -0.15 +/- 0.00 |
| 0.5 % cycle jitter | -0.01 +/- 0.43 | -0.05 +/- 1.78 |
| 2 % cycle jitter | +0.04 +/- 1.74 | -0.62 +/- 7.42 |
| one edge missing | -62.09 | -0.15 |
| one extra edge | +62.05 | -0.15 |
| three edges missing | -179.39 +/- 19.42 | -0.15 |

First-to-last is better under torsional jitter. It fails under one wrong
edge count: -62.09 RPM is a 3.4 % error, which looks like a speed change.
Jitter shows in `interval_spread`; a wrong edge count does not. Thus the
median is the correct choice.

**Measured on:** PicoScope 4424A, AWG loopback, 41666.5 Hz, September 2026.

### E15. Simulation model constants

`simulation.GenerateBearingVibration` is the bearing-defect model: an
impulse train at the defect rate, each impulse rings a structural resonance,
amplitude-modulated at the shaft rate, with cumulative slip jitter. Two of
its constants come from measurement, not from the textbook.

#### Resonance Q

**Decision.** `DEFAULT_RESONANCE_Q = 8.0`, not the textbook 40.

Impulsiveness depends on the ratio of the ring-down time constant to the
impulse interval: tau = Q / (pi x f_res). When tau is near one impulse
period, the ring-downs merge into a continuous tone and the signal is not
impulsive.

**Measured on:** `GenerateBearingVibration` (simulation), fs 32768 Hz,
0.5 s block, defect rate 325.8 Hz (period 3.07 ms), 4 kHz resonance, mean of
4 seeds. Not measured again at 25600 Hz.

| Q | tau (ms) | tau/period | Kurtosis, healthy | Kurtosis, severity=1 |
|---|---|---|---|---|
| 3 | 0.24 | 0.08 | 3.09 | 10.41 |
| 5 | 0.40 | 0.13 | 3.09 | 7.21 |
| 8 | 0.64 | 0.21 | 3.09 | 5.28 |
| 10 | 0.80 | 0.26 | 3.09 | 4.63 |
| 15 | 1.19 | 0.39 | 3.09 | 3.81 |
| 25 | 1.99 | 0.65 | 3.09 | 3.27 |
| 40 | 3.18 | 1.04 | 3.09 | 3.08 |

**Rejected: Q = 40**, the textbook value for a lightly damped housing
resonance alone. At this defect rate its ring-down is longer than the gap
between impulses, and kurtosis cannot detect the fault (3.08 against 3.09).
Real bearing signals damp faster through the load path. Q = 8 gives
tau/period = 0.21, inside the 10 % to 30 % range that bearing-simulation
practice uses (no reference is recorded for this range). It separates 5.28
from 3.09, enough for a threshold test.

#### Independent phase for each shaft harmonic

**Decision.** Each of the five shaft harmonics gets its own random phase.

**Rejected: one shared phase.** It is not physical (the harmonics of a real
machine come from different mechanisms). With one shared phase, healthy
kurtosis was 2.03 to 4.00 across seeds (`severity=0`; rate, block length and
seed count not recorded). That range overlaps the faulted range, so a
threshold test becomes unstable.

**Measured on:** `GenerateBearingVibration` through
`_RawRateView(AcquisitionSettings())` (simulation), 25600 Hz, 12800 samples,
seeds 0 to 39, Pearson kurtosis, 2026-09-29. The current model, with
independent phases:

| Severity | Kurtosis min | Kurtosis max | Kurtosis mean |
|---|---|---|---|
| 0.0 (healthy) | 1.54 | 3.04 | 2.18 |
| 1.0 | 3.83 | 6.16 | 4.84 |

The healthy control is sub-Gaussian (kurtosis below 3), because the shaft
harmonics dominate the signal. The two ranges do not overlap.
`tests/test_bearing_oracle.py` gives 3.86 to 6.12 for severity 1.0 over 40
seeds; its conditions are not recorded.

#### Other defaults (no measurement recorded)

- `DEFAULT_RUNNING_RATE_HZ = 60.0` (3600 RPM), `DEFAULT_BEARING_MULTIPLE =
  5.43` (outer race; non-integer, as real bearing geometry is),
  `DEFAULT_RESONANCE_HZ = 4000.0`: "a mid-size induction motor".
- `DEFAULT_SLIP = 0.015`: rolling elements slip by 1 % to 2 %. Slip is a
  cumulative random walk, not independent jitter for each impulse, because a
  random walk gives smearing that increases with harmonic order.
- `severity=1.0` scales the defect to about the RMS of the shaft signal.

### E16. Anomaly thresholds

The monitor hooks are in `monitor/anomaly.py`. The GUI offers the RMS hook
only.

#### E16.1. RMS threshold 50 %

**Decision.** `RmsThresholdHook(rms_threshold_pct=50.0)`. The same default is
in `config._BUILTIN_ACQ['monitor']['anomaly']['rms_pct']`, in
`headless._build_anomaly_hook` and in `gui._build_anomaly_hook`.

**Why.** For a rigid rotor below its first critical speed, the 1x velocity
changes as omega cubed. The shaft-speed change alone moves the overall:

| Shaft-speed change | 1x velocity change |
|---|---|
| 0.5 % | +1.5 % |
| 1.0 % | +3.0 % |
| 2.0 % | +6.1 % |
| 3.2 % | +10.0 % |
| 5.0 % | +15.8 % |
| 10.0 % | +33.1 % |

**Measured on:** not measured. The table is the calculation
(1 + d)^3 - 1. Check: 1.032^3 = 1.0991.

- **Rejected: a 10 % threshold.** A 3.2 % speed change alone reaches it. A
  slip change of about 2 % between no load and full load on an induction
  motor gives +6 % with no change in condition. On a VFD or a
  load-following machine, a 10 % threshold measures load, not condition.
- 50 % is a level at which a broadband RMS rise means something without a
  speed reference. With a tachometer, the speed gate (E20) removes the
  off-speed frames, and a site can set a lower threshold.
- Without a tachometer, detection must come from envelope analysis or from
  fixed limits (`FixedThresholdHook`).

A key in `acquisition.yaml` wins over the built-in default (section 4.8).

**EWMA constants.** `baseline_alpha` 0.97 (RMS) is a time constant of about
33 frames (half-life about 23 frames). `baseline_alpha` 0.995 (spectral) is a
time constant of about 200 frames (half-life about 138 frames).
`ewma_alpha_from_time(tau, dt)` returns exp(-dt / tau); at tau = 30 s and
dt = 1 s it is 0.967.

#### E16.2. Spectral hook statistics

**Decision.** The GUI offers the RMS hook only (`util.GUI_ANOMALY_HOOK_TYPES
= ('rms',)`). Headless still accepts `spectral` and `both`
(`headless._build_anomaly_hook`). Fix or removal is tracked as R39 in
`doc/PROGRESS.md`.

**Why** (statistics, not a recorded measurement):

- `SpectralThresholdHook` fires on
  `np.any(|spec - baseline| / baseline > threshold)` over every bin in the
  band.
- Welch runs one segment (`nperseg == blocksize`), so each noise-floor bin
  is chi-squared with 2 degrees of freedom, with a standard deviation equal
  to its own mean.
- The probability that one of about 2000 bins exceeds 1.5x its mean is
  about 1.0 on healthy data. `consecutive_n` then only delays the trigger.
- `DataCollector.process_sample` sets bins 0 and 1 to zero for integration,
  so on a velocity or displacement channel they deviate by about 1e12 and
  fire on every frame.

A return to the GUI is a one-line change in `util.py`.

### E17. Burst memory

**Decision.** `_set_burst_frame_cap` limits the frames that one burst keeps.
Both burst paths (anomaly, `_start_burst`; manual, `trigger_burst`) call it.
The cap is `burst_frame_cap(max_burst_s, acquisition_period)` =
int(max_burst_s / acquisition_period) + 1 frames after the trigger, minimum
`MIN_BURST_FRAMES` = 4, plus the pre-trigger frames of the burst.
`acquisition_period` is the frame period of the session
(`raw_blocksize / raw_samplerate`, set by `session_from()`). If a session has
no frame period, the cap is `MIN_BURST_FRAMES` and the controller logs a
warning. `_handle_burst_frame` trims `_burst_frames` and
`_burst_all_results` together, because `_flush_burst` reads them by the same
index. Both paths also clamp the burst end to `max_burst_s` with
`capped_burst_end()`.

**Why.** A burst keeps every frame and every `ChannelResult` in memory until
the flush at its end. Without a cap an unattended burst grows until the OOM
killer stops the process: SIGKILL, no traceback, no log line.

**Measured on:** 4 channels through the real pipeline at
`RAW_SAMPLERATE_HZ` = 25600 Hz, August 2026. The byte count is the deep
ndarray size reachable from one retained frame and its `ChannelResult`s.
Hardware or `SimulatedSensor` is not recorded.

| binsize | frame period | raw block | retained | multiple |
|---|---|---|---|---|
| 0.5 Hz | 2.000 s | 1.638 MB | 4.517 MB | 2.76x |
| 1.0 Hz | 1.000 s | 0.819 MB | 2.259 MB | 2.76x |
| 2.0 Hz | 0.500 s | 0.410 MB | 1.130 MB | 2.76x |

- The multiple does not change, because a retained frame is the raw-rate
  block plus its derived views.
- Growth is 2.26 MB/s on 4 channels (about 8.1 GB/h), independent of F_max
  and binsize. Stored frames are raw-rate, so a lower F_max does not reduce
  it.
- At the default `max_burst_s` of 600 s the frames after the trigger hold
  about 1.36 GB (computed). The pre-trigger frames add to this.

`tests/test_monitor_burst_cap.py` keeps the cap on both paths.

### E18. Profiler overhead

**Decision.** `_profile.timed()` stays in the shipped code, in the render
loop and in the driver callback. When profiling is off, it reads one
module-level flag and returns a shared no-op object. It does not create a
generator and does not read a clock. When profiling is on, each stage keeps
a ring of `RING` = 2048 samples (a `deque` with `maxlen`), so memory cannot
grow without limit.

**Measured on:** the development machine, 2026-09-11. The CPU and the
Python version are not recorded. The values are net of the empty-loop
baseline (56.3 ns).

| Call | Time per call |
|---|---|
| `timed()`, profiling off | 442 ns |
| `timed()`, profiling on | 3015 ns |

At the busiest call site, `usb.adc2mv`: about 77 driver callbacks/s x 8
channels = 616 calls/s. That is 0.27 ms per wall-clock second with
profiling off, and 1.9 ms/s with profiling on (computed from the table).
The rate of 77 callbacks/s comes from the same measurement; its raw rate is
not recorded.

**Why a bounded ring.** An unbounded buffer in this app becomes an OOM kill
(SIGKILL: no traceback, nothing in the log). A diagnostic must not cause the
failure that it is there to find. 2048 samples are about 17 min of a
frame-rate stage at 2 frames/s, and about 27 s of a 77 Hz driver-callback
stage (computed).

**Why per-stage timing exists.** Three causes of GUI stutter were each
linear in the channel count, so the frame rate alone could not separate
them: a 512821-tap FIR designed for each channel and frame on the main
thread (E7), a per-sample Python loop in the vendor ADC conversion on the
acquisition thread (E3), and about 164 widget operations for each channel
and frame in the peaks table (E19). Section 7 gives the stage list.

### E19. GUI render cost

The render thread does all dearpygui work. Each decision below removes
main-thread work that grows with the channel count.

**Peaks table: a widget pool, not a rebuild.** `_update_fft_peaks_table`
creates rows on demand, updates them with `set_value`, and hides surplus
rows. It does not delete and rebuild the table for each frame. A frame with
no change pushes nothing. Cost of a rebuild, computed from the widget count
(not timed):

| Item | Count |
|---|---|
| Lines per spectrum, corpus median (`select_peaks`) | 40 |
| Destroyed per channel per frame | 2 columns + 40 rows |
| Created per channel per frame | 2 columns + 40 rows + 80 texts |
| Total widget operations per channel per frame | about 164 |
| At 8 channels, per frame | about 1300 |
| Share of all per-frame dearpygui traffic | about 80 % |

The rebuild ran from both branches of `_update_freq_plot`, so it also ran
with zero peaks. **Measured on:** a 4824A with 3 to 8 channels, 2026-09-11;
no time for each call is recorded.

**Running median edges: vectorised.** `peaks._running_median` computes the
edge bins (E12.3) with a NaN-padded sliding window and one `np.nanmedian`,
not a Python loop of `np.median` calls (64 calls at width 65). The statistic
does not change. **Measured on:** a 1001-bin spectrum, width 65; the machine
and the date are not recorded.

| Stage | Time (ms) |
|---|---|
| `median_filter` (interior) | 0.047 |
| edge loop, Python | 1.161 |
| edge loop, vectorised | 0.408 |
| `_running_median` total, loop -> vectorised | 1.274 -> 0.563 |

The Python edge loop was 91 % of the cost of the function. The saving is
0.711 ms for each channel and frame, 5.7 ms at 8 channels (computed from
the table). The total with the loop at 8 channels is 10.2 ms (8 x 1.274 ms).
`tests/test_peak_selection.py`,
`test_running_median_bit_identical_to_the_loop`, is the equality test.

**Envelope chain: only when the plot is on screen.** With the Envelope tab
enabled but another tab selected, the chain (a `butter` design, a
`sosfiltfilt`, a Hilbert transform) costs about 2.8 ms for each channel and
frame, plus 1.4 ms to 1.9 ms when the band is automatic (`suggest_band`).
**Measured on:** 2026-09-11; the machine is not recorded.
`_envelope_on_screen()` queries the plot, not the tab, because an unselected
tab shows its header button and always reports visible. It fails open: on
any error it returns True, because a blank plot with no reason is worse than
CPU time.

**Automatic demodulation band: cached for each channel.** `suggest_band`
runs a full rFFT of the raw block and an `np.convolve`. The cache key is
(channel, sample rate). An edit of the band fields, a toggle of the
Envelope tab, and the Auto button clear the cache. The cache also keeps the
band, and so the envelope axis, the same from frame to frame.

**Stale-frame watchdog: a deadline, not a timer thread.**
`_schedule_status_timeout` stores a deadline (2 x `acquisition_period`), and
`_poll_new_frames` checks it on the render thread at each tick. Rejected: a
`threading.Timer` for each displayed frame, because it changes a dearpygui
widget from another thread. Rule: no dearpygui call off the render thread.

**Peak display cap.** `_DEFAULT_PEAK_DISPLAY_CAP` = 50 limits the table and
the plot markers only; `rev80.peaks` selects the lines. The value comes from
the corpus counts at the default threshold (E12.1), so in the normal case
nothing is hidden.

### E20. Speed gate

**Decision.** `AcquisitionSettings.speed_gate_enabled`, `speed_gate_rpm` and
`speed_gate_tolerance_pct` (default 3.0 %) declare a shaft-speed window. A
frame outside it is measured, shown and stored, but it is not trended, not
used for baseline adaptation and not alarmed on. Its amplitude is correct
but not comparable. The gate is off by default, because it needs a
tachometer. `speed_gate_rpm` = None latches the reference from the first
valid reading.

**Why.** For a rigid rotor below its first critical speed, the 1x velocity
changes as omega cubed. A shaft-speed change of 3.2 % alone moves the
overall by 10 % (E16.1; calculation, not measured). Without the gate, on a
VFD or a load-following machine, the anomaly detector measures load, not
condition.

**Where it is applied.** `DataCollector.speed_ok()` evaluates the gate and
sets `ChannelResult.speed_ok`. It fails closed: no reading, or a reading
that is not `TachResult.is_usable` (E14.6), gives False.
`monitor.anomaly.valid_results()` applies it, with the `overflow` and
`degraded` flags, and it is the only place that does. Every hook
(`RmsThresholdHook`, `SpectralThresholdHook`, `FixedThresholdHook`,
`CompositeAnomalyHook`) calls it in `on_results`, and the two EWMA hooks
also call it in `update_baseline`.

**Rejected alternative.** A speed-gate parameter on each hook. That needs a
change in `_build_anomaly_hook`, which is still copied in `gui.py` and
`headless.py`, and two copies of one rule drift.

**Why flagged frames are also kept out of the baseline.** One bad frame in
an EWMA baseline with alpha 0.97 affects the reference for about 33 frames
(the time constant). A baseline that learns from it is as wrong as an alarm
on it.

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
| PicoSDK 11.1.0.481 (64-bit) | [picotech.com/downloads](https://www.picotech.com/downloads) | The release workflow uses the same version. Restart Windows before the first connection to a scope |
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
./scripts/build.sh installer    # Inno Setup only (the PyInstaller step must have run)
./scripts/build.sh wheel        # wheel + sdist; runs on any OS

# Flags, in any position
./scripts/build.sh all clean    # delete the PyInstaller cache first
./scripts/build.sh all nodlls   # no DLLs: a driver-less bundle (what CI builds)
```

Every target first runs `scripts/fetch_font.sh` and `pip install -e . --no-deps`
(to refresh `_version.py`). Thus the build changes the editable install of
the active environment to point at this checkout.

`build/collect_pico_dlls.py` copies `ps4000a.dll` and `picoipp.dll` into
`drivers/`. It searches these directories in this order, and the first match
wins:

1. The `InstallPath` registry value of PicoSDK, plus `\lib`. PicoSDK 11.x
   writes no registry value.
2. `C:\Program Files\Pico Technology\SDK\lib`, then the `(x86)` equivalent.
3. The directory in the `PICO_DLL_DIR` environment variable.
4. `vendor/pico/` in the repository (gitignored).

A full build without `nodlls` stops if a DLL is missing or is not 64-bit.

The PyInstaller step (`build/rev80.spec`) reads the version from
`_version.py` and writes `installer/version.iss`. `installer/rev80.iss`
includes that file and packs `dist/rev80/`. Thus the `installer` target needs
the output of the PyInstaller step.

> **`python -m build` does not work from the repository root.** The
> repository's `build/` directory hides the `build` package from PyPI, so
> `python -m build` fails with *No module named build.__main__*. Use
> `./scripts/build.sh wheel`. It runs the frontend from a temporary
> directory, with the interpreter resolved to an absolute path.

### 10.3 Output

| Path | Contents |
|---|---|
| `dist/rev80/rev80.exe` | Stand-alone executable (no installation necessary) |
| `dist/rev80/_internal/` | Python runtime, `rev80/logging.yaml`, `assets/`, `drivers/` (PyInstaller 6 layout; `sys._MEIPASS` points here) |
| `installer/Output/Rev80Setup-<version>.exe` | Installer with Start Menu shortcut, optional desktop shortcut and uninstaller |
| `dist/rev80-<version>-py3-none-any.whl` | Python wheel |
| `dist/rev80-<version>.tar.gz` | Source distribution |

The installer needs no admin rights. A per-user install goes to
`%LOCALAPPDATA%\Programs\Rev80`; a dialog permits an install for all users.
The uninstaller does not delete the user data in `Documents\Rev80\` or the
configuration in `%APPDATA%\rev80\`. If PicoSDK is not found, the installer
asks the user to continue or stop.

### 10.4 Constraints

- **64-bit only.** The PicoSDK DLLs are 64-bit.
- **dearpygui is pinned to 2.0.0** in `pyproject.toml`, because later versions
  crash the viewport on Windows. Do not change the pin without a test on
  Windows.
- **USB kernel driver.** `ps4000a.dll` is the user-mode library. PicoSDK
  installs the kernel driver separately and needs a restart before the first
  connection to a scope.
- **Windows 10 version 1809 (build 17763) or later.** `MinVersion` in
  `installer/rev80.iss` sets it.
- **UPX stays off** in `build/rev80.spec`. UPX compression of
  `python3XX.dll` makes the exe fail at start with "LoadLibrary failed".
- **Do not change `AppId`** in `installer/rev80.iss`. Setup uses it to find
  an earlier install for upgrade and uninstall.
- **The frozen interpreter is the build interpreter.** The release workflow
  uses Python 3.12 (x64). A change of that version changes what users run.
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

`workflow_dispatch` runs the same jobs on any ref without a release. It is
available only when `release.yml` is on the default branch. The `release`
job runs only for a tag.

Five facts about the workflow:

- **CI installers are driver-less by choice.** The build passes `nodlls`, so
  no DLLs are bundled. The user installs PicoSDK, and the installer warns if
  it is missing. A local `./scripts/build.sh` still bundles `ps4000a.dll`
  and `picoipp.dll`. In a checkout, `drivers/` is never empty: it holds the
  tracked `.gitkeep`, `.gitignore` and `install-picoscope4000a-driver.sh`.
  Thus `rev80.spec` always bundles `drivers/`, and
  `_pico_loader.ensure_pico_dlls_loadable()` registers it with no warning.
  `picosdk` then finds `ps4000a.dll` with `ctypes.util.find_library`, which
  searches `PATH`. To ship the DLLs, remove `nodlls`. The Pico
  redistribution licence controls that decision.
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
git tag v0.0.1rc1 && git push origin v0.0.1rc1
# ...then delete the draft release and:
git push origin :v0.0.1rc1 && git tag -d v0.0.1rc1
```

The tag must be a valid PEP 440 version after the `v`. On a commit tagged
`v0.0.1rcx`, `setuptools_scm` 10.3.4 stops with *Can't parse version from
tag*.

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
