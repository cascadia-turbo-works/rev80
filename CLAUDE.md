# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Rev80** (package `rev80`, formerly `vibechecker`) — a Python desktop GUI for capturing, analyzing, and recording vibration data from industrial rotating equipment. It targets predictive maintenance using IEPE accelerometers connected to a **PicoScope 4000A** USB oscilloscope. A `SimulatedSensor` is available for offline development and CI without hardware, and a **headless** front end (`headless.py`) runs the interval datalogger with no GUI.

This is an *instrument*: the numbers it displays are the product. An August 2026 three-discipline audit found the full test suite passing while the instrument was measurably wrong, because every DSP test excited the chain only at bin-centred frequencies — the one degenerate case where FFT wrap error vanishes. **Green CI is not evidence of measurement correctness here.** See `doc/CHANGELOG.md` for the two remediation rounds and their measured before/after numbers.

## Commands

```bash
# Run the GUI
python -m rev80              # or the installed `rev80` console script
python -m rev80 --debug      # with console debug logging

# Headless interval datalogger (no GUI)
rev80 headless               # or `rev80-headless`

# Info commands
rev80 --list-devices  --list-sensors  --init-config  --edit-config

# Install dependencies (editable checkout)
pip install -e ".[dev]"

# Run all tests (from vibegui/ directory)
pytest tests/

# Single file / single test / by keyword
pytest tests/test_sample.py
pytest tests/test_vibechecker.py::test_save
pytest tests/ -k "stream"

# Lint — this exact invocation is what CI and the pre-commit hook run
ruff check src/ tests/
```

Tests run without physical hardware via `SimulatedSensor`. `tests/test_picoscope_hw.py` self-skips when no scope is attached; when one *is* attached those 9 tests run and give AWG-loopback verification, which is the established way to close out a measurement change.

Install the git hooks once per clone — they are not automatic:

```bash
git config core.hooksPath .githooks
```

The hook runs `ruff check src/ tests/` (blocking), stamps `src/rev80/_version.py` from `git describe`, and re-renders `doc/*.pdf` for any Markdown doc in the commit.

## Architecture

The app follows a layered pipeline:

```
Hardware thread                          Main thread
───────────────                          ───────────────
VibeSensor / SimulatedSensor
        │  (PicoScopeStream or SimulatedSensor callback)
        ▼
DataCollector                            GUI (dearpygui)
  receive_data()                           _poll_new_frames()
    → Butterworth filter                     if new_frame_event:
    → mV → EU via ScopeSensor.sensitivity      grab frame_cache[-1]
    → VibeSample per channel                   VibeSample.process()
    → frame_cache.append()                     _display_frame()
    → new_frame_event.set()  ─────────────→
```

The collector and GUI are decoupled via `threading.Event`. The hardware
thread never touches DPG widgets. When the GUI is slower than the data
rate, it skips to the latest frame — all earlier frames remain in the
32-frame ring cache for browsing.

### Key modules

| Module | Role |
|---|---|
| `util.py` | Constants (`MAXFREQ_PRESETS`, `BINSIZE_PRESETS`, `ISO_BAND_PRESETS`, `GUI_ANOMALY_HOOK_TYPES`), unit taxonomy and SI conversion, amplitude mode scaling, `UI_Elements` tag registry |
| `sensor.py` | `VibeSensor` dataclass — device metadata; `find()` enumerates PicoScopes; `simulated()` returns test sensor; `connect()` returns the appropriate stream |
| `picoscope.py` | `FindPicoScope()` enumeration; `PicoScopeStream` acquisition thread — drives the ADC oversampled and applies a mandatory **linear-phase Kaiser FIR** anti-alias filter + decimate (`antialias_decimate()`, `_antialias_taps()`; measured −111.7 dB stopband against −60.0 dB for scipy's default Hamming kernel) down to the fixed raw acquisition rate (`AcquisitionSettings.raw_samplerate`, not the `maxfreq`-driven display `samplerate`); silence watchdog/recovery; a second, independent watchdog flags sustained USB streaming-rate degradation (`.degraded`) without triggering recovery; per-channel coupling and voltage range config; AWG signal generator control |
| `scope_sensor.py` | `ScopeSensor` dataclass — IEPE sensor metadata: name, sensitivity (mV/EU), engineering units |
| `scope_sensor_registry.py` | `ScopeSensorRegistry` — YAML-backed global sensor library (`scope_sensors.yaml`); CRUD by ID/name; loaded from `~/.config/rev80/` |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators (`GenerateTone`, bearing-defect) for offline dev/test |
| `sample.py` | `AcquisitionSettings` — two independent rate pairs: fixed `raw_samplerate`/`raw_blocksize` (`RAW_SAMPLERATE_HZ`, what's actually acquired/stored) and derived `samplerate`/`blocksize`/`nperseg`/band (from `maxfreq`/`binsize`, display/Spectrum-tab only); declared band; averaging; per-channel names, target units, amplitude modes, couplings, voltage ranges. `VibeSample` (one channel's raw block at the raw rate, with cached PSD/decimated/filtered data) + `ChannelResult` (frozen display result, display-rate) |
| `_dsp.py` | Windowing and band helpers, each carrying the measured error table that justifies it: `hann_taper`/`tukey_taper`, `band_mask`, `band_rms`, `integrate_rfft`, `butter_knee_for_edge`, `crest_factor`, `kurtosis` |
| `peaks.py` | Significance-based spectral peak selection — per-bin local noise floor via a running median, feeding array-valued `height`/`prominence` into one `find_peaks` call. A line is reported when it stands above **its own** neighbourhood, not by top-N amplitude |
| `envelope.py` | Envelope (demodulation) analysis — `envelope_spectrum()` (band-pass → Hilbert magnitude → DC removal → amplitude spectrum) and `suggest_band()`. The band-pass, not the Hilbert transform, is the load-bearing step. Reads the raw-rate signal via `DataCollector.eu_scaled_raw()`, not the maxfreq-decimated `ChannelResult`, so a low display `maxfreq` never limits what it can see |
| `collector.py` | `DataCollector` — stream lifecycle, per-channel zero-phase Butterworth highpass filter (falls back to causal for short blocks), channel→`ScopeSensor` assignment (mV→EU), 32-frame ring cache, trend accumulation, `new_frame_event` signal, HDF5 save/load |
| `config.py` | OS-aware device config directory (`~/.config/rev80/` on Linux, `%APPDATA%/rev80/` on Windows); per-device YAML persistence with atomic writes; default config fallback |
| `gui.py` | `GUI` class — dearpygui 3-panel layout (controls / plots / results), `_poll_new_frames()` render loop, config dialogs (Device/Channels/Sensor/Spectrum/Siggen), spectrum FFT window/preset controls, per-channel result cards, trend plot, HDF5 file load/save |
| `logger.py` | YAML-configured logging; rotating log files written to `log/`. `sys.excepthook` is installed — but **`threading.excepthook` is not**, so exceptions escaping the acquisition, simulation and writer threads never reach the log (audit H-07) |
| `headless.py` | No-GUI front end: interval datalogger, anomaly hooks, session summary. ~640 lines. Shares no code with the GUI's copy of the same logic — see the H-01 warning below |
| `monitor/controller.py` | `MonitorController` — interval/burst state machine, pre-trigger ring buffer, anomaly dispatch |
| `monitor/writer.py` | `MonitorWriterThread` — daemon thread accumulating captures into one `session.h5` (v5) |
| `monitor/gate.py` | `IntervalGate` — snap-to-grid capture scheduler; burst entry/exit with `max_burst_s` |
| `monitor/anomaly.py` | `RmsThresholdHook`, `SpectralThresholdHook`, `FixedThresholdHook`, `CompositeAnomalyHook`, `valid_results()` |
| `_paths.py` | Runtime-safe path resolution — editable checkout, non-editable pip install, and PyInstaller frozen bundle all resolve correctly; `resource_path()`, `data_dir()`, `log_dir()` |
| `_pico_loader.py` | Windows-only: registers PicoSDK DLL search path before `picosdk` import |
| `desktop.py` | Linux-only: `install()`/`uninstall()` a `~/.local/share/applications/rev80.desktop` launcher entry + icon, driven by `rev80 --install-desktop-entry` / `--uninstall-desktop-entry` |

### Data flow details

- `VibeSensor._callback` is the hardware stream callback; it scales raw ADC counts to mV via per-channel voltage range and packages a dict keyed by channel index. `SimulatedSensor` mirrors this: it generates and reports at `raw_samplerate` (via `simulation._RawRateView`, which presents `config` at its raw rate to the signal generators), not the display rate, so offline dev/CI exercises the same raw/display split real hardware does.
- `DataCollector.receive_data` looks up the `ScopeSensor` assigned to each channel, converts mV→EU via `sensitivity`, then wraps each channel in a `VibeSample` at the raw acquisition rate (carrying the frame's `overflow` and `degraded` flags). The per-channel Butterworth highpass filter is applied later, in `process_sample()`, still at the raw rate; anti-aliasing for the acquisition Nyquist is not applied here at all — it happens upstream in `PicoScopeStream`, before the ADC's own Nyquist limit can fold high-frequency content into the passband, and is not user-configurable.
- `DataCollector._data_callback` appends the frame to a 32-frame ring cache (deque) and sets `new_frame_event`. All consumers — GUI render loop, `collect_sample`, tests — read from `frame_cache` via `new_frame_event`; there is no separate callbacks fan-out. `DataCollector.current_frame()` returns the same `{ch: VibeSample}` dict as whatever `process_samples()` would currently process (respecting the streaming-vs-browse cursor), for a consumer — the Envelope tab — that needs the raw `VibeSample` rather than a decimated `ChannelResult`.
- `DataCollector.process_sample()` (not `VibeSample.process()`) decimates the raw-rate `VibeSample` down to the display rate (`collector.decimate_to_rate()` — rational-ratio `scipy.signal.resample_poly`, reusing the hardware anti-alias filter's Kaiser stopband design; cached on the sample) and produces the `ChannelResult`. Per frame: Welch PSD (one segment — `nperseg == blocksize`), optional averaging over N frames, five integration orders, spectrum truncated at `maxfreq`, peaks, overall, waveform, crest factor and kurtosis. `ChannelResult.time_data`/`.samplerate` are display-rate. `DataCollector.eu_scaled_raw(ch, sample)` instead returns the highpass-filtered signal in the sensor's own EU *at the raw rate*, skipping decimation entirely — this is what envelope/demodulation analysis (`gui.py`'s `_update_envelope_plot`) reads, so a low `maxfreq` never limits envelope bandwidth.
- **Everything scalar is measured over the declared band** (`config.band`), applied as a mask on the rFFT. All five integration orders share one masked, Hann-tapered path — including order 0, because the mask is itself a transform-domain multiply and carries the same circular-wrap sensitivity the taper exists to control.
- **Averaging is in the power domain**: average |X|², sqrt at the end; the overall combines as `sqrt(mean(squares))`. Averaging magnitudes converges ~11% low on a noise floor and is invisible on a coherent line — the trap that passed 17 tests before two were added to catch it.
- **Crest factor and kurtosis are computed on the displayed trace and never averaged.** Averaging is for steady-state estimation; those exist to catch the frame that is *not* steady.
- Overflow / degraded frames are excluded from the trend, from anomaly evaluation and baselines, and from the spectral average — but are still displayed, flagged.
- Data is saved as HDF5 (`.h5`) into `_paths.data_dir()` — always `~/Documents/Rev80/data/`, in development and frozen builds alike (`./DEVDATA` is test scratch space only, hardcoded independently in `tests/`). File names include an ISO timestamp with `:` replaced by `-` for FAT32 compatibility. Every stored frame is the raw-rate capture, independent of `maxfreq`.

### AcquisitionSettings interdependencies

Two independent rate pairs, not one:

- **Raw/acquisition** — `raw_samplerate` is fixed (`RAW_SAMPLERATE_HZ` in `sample.py`, 40 kHz by default; not `maxfreq`-derived, not user-configurable). `raw_blocksize` is derived from it and `acquisition_period`. This is what `PicoScopeStream`/`SimulatedSensor` actually produce, what `VibeSample`/HDF5 hold, and what envelope analysis (`DataCollector.eu_scaled_raw`) reads.
- **Display** — `samplerate`/`blocksize` keep their original formula and meaning: changing `maxfreq` auto-adjusts `samplerate` (`nextpow2(2.56 * maxfreq)` — guarantees Nyquist >= 1.28x maxfreq, the margin the mandatory anti-alias filter needs); changing `binsize` auto-adjusts `blocksize` to the next power of two. This is what the Acquisition dialog's "Sample Rate" field shows and what the Spectrum tab's Welch PSD runs at — `DataCollector` decimates the raw signal down to it in `process_sample()`. `samplerate`, `blocksize`, `nperseg`, `binsize_actual`, `n_fft_bins` and `band_*_resolved` are all **read-only derived properties**.

These are enforced in the setters — do not bypass them by setting private `_fm`/`_df` directly (the read-only-property design makes it impossible anyway). `maxfreq`'s setter also clamps to what `raw_samplerate` can back (`<= raw_samplerate/2/1.28`) and logs a warning if a caller (e.g. `headless.py --maxfreq`) asks for more.

There is no user-facing `lowpass_enabled`/`lowpass_fc` — anti-aliasing is mandatory at both rates and automatic: `PicoScopeStream` anti-alias filters down to `raw_samplerate` at capture time; `DataCollector.decimate_to_rate()` anti-alias filters again down to `samplerate` (display) before Welch, reusing the same Kaiser stopband target.

`highpass_fc` is the **declared lower band edge**, not the filter's −3 dB knee. A 4th-order Butterworth designed *at* 10 Hz reads 29% low at 10 Hz — the very frequency ISO 2954 names as the bottom of the declared band — so `DataCollector.highpass_knee_hz()` places the knee below it at `f_edge × (A²/(1−A²))^(−1/2N)`, i.e. `0.834 × f_edge` at order 4. The filter is **causal with state carried across streaming blocks**, applied once at the raw rate; `sosfiltfilt` was tried and reverted (it doubles the effective order and overshot both block edges by 35–45%). `highpass_enabled`/`highpass_fc` remain user-configurable (an unrelated DC/drift-removal control).

`band_fmin`/`band_fmax` declare the band the overall is measured over (`None` = derive: `highpass_fc … maxfreq`, clamped to `maxfreq` so the anti-alias guard band can never re-enter). `averaging_enabled`/`n_averages` control spectral averaging, clamped by `cache_frames`.

`PicoScopeStream` drives the ADC above `raw_samplerate` by an oversampling ratio (`effective_osr`, up to 4x) capped by `STREAMING_CEILING_HZ` (a measured safe continuous-USB-streaming ceiling — see `picoscope.py`), then filters and decimates back down to `raw_samplerate`/`raw_blocksize`; this is invisible to `AcquisitionSettings`/`DataCollector`/the GUI, all of which only ever see `raw_samplerate`/`raw_blocksize` on the acquisition side.

Per-channel fields (`channel_names`, `channel_target_units`, `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges`) are dicts keyed by channel index (0-based). They are independent of each other and of the global acquisition parameters.

### Simulated sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. `VibeSensor.connect()` checks this flag and returns a `SimulatedSensor` instead of a hardware stream, generating at the raw acquisition rate (`simulation._RawRateView` presents `config` at `raw_samplerate`/`raw_blocksize` to the generator functions) — the same rate `PicoScopeStream` reports, so offline dev/CI exercises the raw/display decimation path the same way real hardware does.

The default generator is `simulation.GenerateBearingVibration()` — a physically realistic defect model: an impulse train at the defect rate, each impulse ringing a structural resonance, amplitude-modulated at the shaft rate by the load zone, with cumulative slip jitter. `severity=0` is the healthy negative control, and `seed=` makes a block reproducible.

**This matters for testing.** The older pure-tone generators (kept for regression coverage) are ten cosines plus white noise — kurtosis ≈ 3, no impulsiveness, no resonance carrier, no sidebands. They cannot validate crest factor, kurtosis or envelope analysis even in principle: a broken envelope analyser and a correct one both return "nothing here" on pure cosines. Two constants in the model are set from measurement rather than the textbook — see the tables in `simulation.py`.

## Persistence

### HDF5 measurement files (`_FILE_VERSION = 4`)

Saved to `~/Documents/Rev80/data/*.h5` (via `_paths.data_dir()`). Layout:

```
/metadata.attrs                    version, notes
/metadata/acquisition.attrs        AcquisitionSettings.to_dict() — maxfreq, binsize,
                                   fft_window, welch_overlap, band_fmin/band_fmax,
                                   averaging_enabled/n_averages, peak_threshold_db,
                                   highpass_*, trend_max_points, cache_frames
                                   (None is stored as '' and read back as None)
/metadata/scope_sensors/{id}.attrs one group per unique sensor used
/metadata/channels/{ch}.attrs      name, unit, coupling, voltage_range,
                                   scope_sensor_id, target_unit
/frames/{i}.attrs                  timestamp, rel_time, samplerate (raw rate), status
/frames/{i}/{ch}/data              (N,) float64  + overflow / degraded attrs
/trend/{ch}/rel_times              (M,) float64
/trend/{ch}/orders                 (M,5) float64 — mV RMS, integration orders -2…+2
/trend/{ch}/crest_factor           (M,) float64  — dimensionless, NaN = not recorded
/trend/{ch}/kurtosis               (M,) float64
```

Because individual raw frames are stored, analysis settings are **not baked in**: a file captured with averaging off can be given N averages after loading, and the declared band can be changed and recomputed. Anything derived is a view on stored data.

Monitor sessions are a separate `session.h5` (`_FILE_VERSION = 5`, `monitor/writer.py`) with `/metadata`, `/monitor/{n}` (interval captures) and `/burst/{id}` groups.

Do not write to `_fm`/`_df` private attributes when constructing replay `AcquisitionSettings` from HDF5 — use the public setters.

### Device config

Config lives in `$XDG_CONFIG_HOME/rev80/` (default `~/.config/rev80/`) on Linux, `%APPDATA%\rev80\` on Windows:

| File | Role |
|---|---|
| `acquisition.yaml` | instance-wide defaults — acquisition settings **and the whole `monitor:` / `monitor.anomaly:` block**. The primary tuning surface for unattended runs. |
| `devices/picoscope-{model}-{serial}.yaml` | per-device channel assignments, acquisition settings, siggen config. Loaded on connect, saved on disconnect or explicit GUI action. |
| `devices/picoscope-defaults.yaml` | template applied to a device seen for the first time. |
| `scope_sensors.yaml` | global IEPE sensor library (below). |

Seed a fresh install with `rev80 --init-config`.

### Sensor library

`~/.config/rev80/scope_sensors.yaml` — global IEPE sensor definitions shared across all devices. Managed via `ScopeSensorRegistry`. Each entry: `{id, name, sensitivity, engineering_units}` — `sensitivity` is mV per engineering unit, and the key name must match `ScopeSensor.to_dict()` exactly (documenting it as `sensitivity_mv_per_eu` made `from_dict` raise `KeyError`, which was swallowed and silently erased the whole sensor library — audit X-01). The display/integration target unit is a per-channel setting (`channel_target_units`), not part of the sensor definition.

## Monitor Mode (`monitor/`, `headless.py`)

The unattended datalogger, and the newest ~1800 lines. Two front ends drive it: the GUI's monitor card and `headless.py`.

`MonitorController.on_results()` is called from the render loop each frame. `IntervalGate` decides whether this frame is a scheduled capture; anomaly hooks decide whether to open a **burst** — a run of consecutive frames retained around an event, with a pre-trigger ring buffer so the lead-up is kept too. `MonitorWriterThread` accumulates everything into one `session.h5` off-thread.

**Known-bad areas — read before changing anything here.** These are open audit findings, not hypotheticals:

- **S-01 (critical)** `GUI.cleanup()` does not call `self._monitor.stop()`, and the writer is a daemon thread, so the interpreter kills it — possibly mid-`h5py.File(…, 'a')` — with items still queued. `GUI.run()`'s loop body has no `try/except` and `__main__.main()` has no `try/finally`, so any render-loop exception skips `cleanup()` entirely and `ps4000aCloseUnit` never runs; the next launch gets `PICO_NOT_FOUND` until the USB is replugged.
- **S-02 (critical)** The writer queue is `queue.Queue()` with **no maxsize**, so its `except queue.Full` branch is unreachable and `enqueue` always returns True — the UI counts captures that were never written. `_start_burst()` (the anomaly path) never calls `gate.enter_burst()`, so `max_burst_s` is not enforced there, and `_burst_frames.append()` has no cap. Together: OOM on a long unattended run, which is SIGKILL and leaves nothing in the log.
- **H-01** `_build_anomaly_hook` is copy-pasted between `gui.py` and `headless.py` and has already diverged. One bug there is two bugs. `tests/test_anomaly_hook_build.py` tests **both copies** and asserts their defaults match — keep it that way, or extract the shared factory it keeps recommending.
- The **spectral** anomaly hook is unwired from the GUI (`GUI_ANOMALY_HOOK_TYPES`) because it fires on essentially every healthy frame: it tests every bin against a fixed %, while Welch runs one segment so each bin is χ²(2) with σ equal to its own mean. Still reachable from headless. Fix-or-remove is tracked as **R39**.

## Working on this codebase

- **New amplitude assertions go in `tests/test_measurement_validity.py`**, which is off-bin, phase-shifted (`DEFAULT_PHASE = 0.7`) and high-pass-enabled by construction. `tests/test_sample.py` is deliberately on-bin — do not add amplitude assertions there.
- **Revert-check every fix**: confirm the new test actually fails without it. This has caught two cases where a stated invariant was pinned by nothing.
- **Measure before choosing a constant**, and record the table next to it. `picoscope.py`, `_dsp.py`, `peaks.py` and `simulation.py` all follow this; two constants there contradict the textbook value and the measurement is why.
- **Verify electrically when hardware is attached.** AWG loopback on channel A, as in `tests/test_picoscope_hw.py`, is how measurement changes get closed out.
- Keep `doc/CHANGELOG.md`, `doc/PROGRESS.md` and `README.md` current **in the same change**, not as a later pass. `CONTRIBUTING.md` holds dev-environment, layout and build instructions.

## Offline analysis

`.h5` files can be loaded without hardware present (File → Load in GUI). The GUI enters browse mode: ← → buttons step through stored frames, each re-processed through `DataCollector.process_sample()` using the settings snapshot embedded in the file.

Replay must reproduce what the live display showed. Two places enforce it, and both are load-bearing:

- **High-pass state.** Streaming filters once per frame in order, carrying `zi`; replay re-processes frames out of order and so filters statelessly from a settled initial condition seeded from the block mean. Verified bit-identical forward and reverse.
- **Spectral averaging.** The average is the N most recent *valid* frames up to and including the frame being displayed — `frames[cursor-N+1 … cursor]` when browsing, the last N received when live. One rule, so stepping forward through a file reproduces the live view.

## Build / packaging

```bash
./scripts/build.sh   # run from Git Bash (Windows or Linux), from the repo root
```

Build pipeline (Windows): collect PicoSDK DLLs → PyInstaller (`build/rev80.spec`, one-dir bundle) → Inno Setup installer (`installer/rev80.iss`, non-admin install).

Linux desktop install: `pip install --user .` (places `rev80`/`rev80-headless` in `~/.local/bin`) then `rev80 --install-desktop-entry` (writes an XDG `.desktop` entry + icon under `~/.local/share/`; see `desktop.py`). No separate build step — this is the same wheel as any other pip install.

`_paths.py` must be used for all resource and data directory lookups — it handles the `sys._MEIPASS` path difference in frozen builds. Bundled resource files (e.g. `logging.yaml`, the icon font) must physically live under `src/rev80/` and be declared in `pyproject.toml`'s `[tool.setuptools.package-data]` to survive a non-editable `pip install`.
