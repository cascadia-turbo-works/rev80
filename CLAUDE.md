# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**vibechecker** — a Python desktop GUI for capturing, analyzing, and recording vibration data from industrial rotating equipment. It targets industrial machinery predictive maintenance using IEPE accelerometers connected to a **PicoScope 4000A** USB oscilloscope. A `SimulatedSensor` is available for offline development and CI without hardware.

## Commands

```bash
# Run the GUI
python -m vibechecker
python -m vibechecker --debug   # with console debug logging

# Install dependencies
pip install -e .

# Run all tests (from vibegui/ directory)
pytest tests/

# Run a single test file
pytest tests/test_sample.py

# Run a single test by name
pytest tests/test_vibechecker.py::test_save

# Run tests matching a keyword
pytest tests/ -k "stream"
```

Tests are parametrized over all detected sensors (including `SimulatedSensor`), so they run without physical hardware.

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
| `util.py` | Constants (`MAXFREQ_PRESETS`, `BINSIZE_PRESETS`), unit taxonomy and SI conversion, amplitude mode scaling, `UI_Elements` tag registry |
| `sensor.py` | `VibeSensor` dataclass — device metadata; `find()` enumerates PicoScopes; `simulated()` returns test sensor; `connect()` returns the appropriate stream |
| `picoscope.py` | `FindPicoScope()` enumeration; `PicoScopeStream` acquisition thread — drives the ADC oversampled and applies a mandatory zero-phase anti-alias filter + decimate (`antialias_decimate()`) down to the fixed raw acquisition rate (`AcquisitionSettings.raw_samplerate`, not the `maxfreq`-driven display `samplerate`); silence watchdog/recovery; a second, independent watchdog flags sustained USB streaming-rate degradation (`.degraded`) without triggering recovery; per-channel coupling and voltage range config; AWG signal generator control |
| `scope_sensor.py` | `ScopeSensor` dataclass — IEPE sensor metadata: name, sensitivity (mV/EU), engineering units |
| `scope_sensor_registry.py` | `ScopeSensorRegistry` — YAML-backed global sensor library (`scope_sensors.yaml`); CRUD by ID/name; loaded from `~/.config/vibechecker/` |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators (`GenerateTone`, bearing-defect) for offline dev/test |
| `sample.py` | `AcquisitionSettings` — two independent rate pairs: fixed `raw_samplerate`/`raw_blocksize` (`RAW_SAMPLERATE_HZ`, what's actually acquired/stored) and derived `samplerate`/`blocksize` (from `maxfreq`/`binsize`, display/Spectrum-tab only); per-channel names, target units, amplitude modes, couplings, voltage ranges. `VibeSample` (HDF5 I/O, at the raw rate; `process()` → `ChannelResult`, at the display rate) |
| `collector.py` | `DataCollector` — stream lifecycle, per-channel zero-phase Butterworth highpass filter (falls back to causal for short blocks), channel→`ScopeSensor` assignment (mV→EU), 32-frame ring cache, trend accumulation, `new_frame_event` signal, HDF5 save/load |
| `config.py` | OS-aware device config directory (`~/.config/vibechecker/` on Linux, `%APPDATA%/vibechecker/` on Windows); per-device YAML persistence with atomic writes; default config fallback |
| `gui.py` | `GUI` class — dearpygui 3-panel layout (controls / plots / results), `_poll_new_frames()` render loop, config dialogs (Device/Channels/Sensor/Spectrum/Siggen), spectrum FFT window/preset controls, per-channel result cards, trend plot, HDF5 file load/save |
| `logger.py` | YAML-configured logging; rotating log files written to `log/` |
| `_paths.py` | Runtime-safe path resolution — editable checkout, non-editable pip install, and PyInstaller frozen bundle all resolve correctly; `resource_path()`, `data_dir()`, `log_dir()` |
| `_pico_loader.py` | Windows-only: registers PicoSDK DLL search path before `picosdk` import |
| `desktop.py` | Linux-only: `install()`/`uninstall()` a `~/.local/share/applications/rev80.desktop` launcher entry + icon, driven by `rev80 --install-desktop-entry` / `--uninstall-desktop-entry` |

### Data flow details

- `VibeSensor._callback` is the hardware stream callback; it scales raw ADC counts to mV via per-channel voltage range and packages a dict keyed by channel index. `SimulatedSensor` mirrors this: it generates and reports at `raw_samplerate` (via `simulation._RawRateView`, which presents `config` at its raw rate to the signal generators), not the display rate, so offline dev/CI exercises the same raw/display split real hardware does.
- `DataCollector.receive_data` looks up the `ScopeSensor` assigned to each channel, converts mV→EU via `sensitivity`, then wraps each channel in a `VibeSample` at the raw acquisition rate (carrying the frame's `overflow` and `degraded` flags). The per-channel Butterworth highpass filter is applied later, in `process_sample()`, still at the raw rate; anti-aliasing for the acquisition Nyquist is not applied here at all — it happens upstream in `PicoScopeStream`, before the ADC's own Nyquist limit can fold high-frequency content into the passband, and is not user-configurable.
- `DataCollector._data_callback` appends the frame to a 32-frame ring cache (deque) and sets `new_frame_event`. All consumers — GUI render loop, `collect_sample`, tests — read from `frame_cache` via `new_frame_event`; there is no separate callbacks fan-out. `DataCollector.current_frame()` returns the same `{ch: VibeSample}` dict as whatever `process_samples()` would currently process (respecting the streaming-vs-browse cursor), for a consumer — the Envelope tab — that needs the raw `VibeSample` rather than a decimated `ChannelResult`.
- `DataCollector.process_sample()` decimates the raw-rate `VibeSample` down to the display rate (`collector.decimate_to_rate()` — rational-ratio `scipy.signal.resample_poly`, reusing the hardware anti-alias filter's Kaiser stopband design; cached on the sample) before computing `scipy.signal.welch` with configurable window/overlap. Cross-modality conversion (accel↔vel↔disp) uses frequency-domain integration via `(2πf)^n` scaling. Returns a `ChannelResult` frozen dataclass — its `time_data`/`samplerate` are display-rate. `DataCollector.eu_scaled_raw(ch, sample)` instead returns the highpass-filtered signal in the sensor's own EU *at the raw rate*, skipping decimation — this is what envelope/demodulation analysis (`gui.py`'s `_update_envelope_plot`) reads, so a low `maxfreq` never limits envelope bandwidth.
- Data is saved as HDF5 (`.h5`) into `_paths.data_dir()` — always `~/Documents/Rev80/data/`, in development and frozen builds alike (`./DEVDATA` is test scratch space only, hardcoded independently in `tests/`). File names include an ISO timestamp with `:` replaced by `-` for FAT32 compatibility. Every stored frame is the raw-rate capture, independent of `maxfreq`.

### AcquisitionSettings interdependencies

Two independent rate pairs, not one:

- **Raw/acquisition** — `raw_samplerate` is fixed (`RAW_SAMPLERATE_HZ` in `sample.py`, 40 kHz by default; not `maxfreq`-derived, not user-configurable). `raw_blocksize` is derived from it and `acquisition_period`. This is what `PicoScopeStream`/`SimulatedSensor` actually produce, what `VibeSample`/HDF5 hold, and what envelope analysis (`DataCollector.eu_scaled_raw`) reads.
- **Display** — `samplerate`/`blocksize` keep their original formula and meaning: changing `maxfreq` auto-adjusts `samplerate` (`nextpow2(2.56 * maxfreq)` — guarantees Nyquist >= 1.28x maxfreq, the margin the mandatory anti-alias filter needs); changing `binsize` auto-adjusts `blocksize` to the next power of two. This is what the Acquisition dialog's "Sample Rate" field shows and what the Spectrum tab's Welch PSD runs at — `DataCollector` decimates the raw signal down to it in `process_sample()`.

These are enforced in the setters — do not bypass them by setting private `_fm`/`_df` directly. `maxfreq`'s setter also clamps to what `raw_samplerate` can back (`<= raw_samplerate/2/1.28`) and logs a warning if a caller (e.g. `headless.py --maxfreq`) asks for more.

There is no user-facing `lowpass_enabled`/`lowpass_fc` — anti-aliasing is mandatory at both rates and automatic: `PicoScopeStream` anti-alias filters down to `raw_samplerate` at capture time; `DataCollector.decimate_to_rate()` anti-alias filters again down to `samplerate` (display) before Welch, reusing the same Kaiser stopband target. `highpass_enabled`/`highpass_fc` remain user-configurable (an unrelated DC/drift-removal control, applied once at the raw rate).

`PicoScopeStream` drives the ADC above `raw_samplerate` by an oversampling ratio (`effective_osr`, up to 4x) capped by `STREAMING_CEILING_HZ` (a measured safe continuous-USB-streaming ceiling — see `picoscope.py`), then filters and decimates back down to `raw_samplerate`/`raw_blocksize`; this is invisible to `AcquisitionSettings`/`DataCollector`/the GUI, all of which only ever see `raw_samplerate`/`raw_blocksize` on the acquisition side.

Per-channel fields (`channel_names`, `channel_target_units`, `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges`) are dicts keyed by channel index (0-based). They are independent of each other and of the global acquisition parameters.

### Simulated sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. `VibeSensor.connect()` checks this flag and returns a `SimulatedSensor` instead of a hardware stream. The simulation generates bearing-defect signals with configurable running rate and fault multiples, at the raw acquisition rate (`simulation._RawRateView` presents `config` at `raw_samplerate`/`raw_blocksize` to the generator functions) — useful for offline UI/algorithm development, and exercises the raw/display decimation path the same way real hardware does.

## Persistence

### HDF5 measurement files (v3 format)

Saved to `~/Documents/Rev80/data/*.h5` (via `_paths.data_dir()`). Layout:

```
/metadata/
    sensor_library/     ← ScopeSensor definitions used during capture
    channels/           ← per-channel AcquisitionSettings snapshot
/trend/
    time                ← shared time axis for all channels
    ch{N}/overall       ← per-channel overall amplitude trend
/ch{N}/
    time                ← raw time-domain data
    data
    attrs: timestamp, sensor_id, sample_rate, …
```

Do not write to `_fs`/`_ns` private attributes when constructing replay `AcquisitionSettings` from HDF5 — use the public setters.

### Device config

Per-device YAML at `~/.config/vibechecker/devices/{sanitized_serial}.yaml` (Linux) or `%APPDATA%\vibechecker\devices\` (Windows). Loaded on device connect; saved on disconnect or explicit GUI action. Stores: channel assignments, acquisition settings, signal generator config.

`~/.config/vibechecker/devices/default.yaml` is the template applied to a device seen for the first time.

### Sensor library

`~/.config/vibechecker/scope_sensors.yaml` — global IEPE sensor definitions shared across all devices. Managed via `ScopeSensorRegistry`. Each entry: `{id, name, sensitivity, engineering_units}` — `sensitivity` is mV per engineering unit, and the key name must match `ScopeSensor.to_dict()` exactly (documenting it as `sensitivity_mv_per_eu` made `from_dict` raise `KeyError`, which was swallowed and silently erased the whole sensor library — audit X-01). The display/integration target unit is a per-channel setting (`channel_target_units`), not part of the sensor definition.

## Offline analysis

`.h5` files can be loaded without hardware present (File → Load in GUI). The GUI enters browse mode: ← → buttons step through stored frames, each re-processed through `VibeSample.process()` using the settings snapshot embedded in the file. No `DataCollector` or stream is required.

## Build / packaging

```bash
./scripts/build.sh   # run from Git Bash (Windows or Linux), from the repo root
```

Build pipeline (Windows): collect PicoSDK DLLs → PyInstaller (`build/rev80.spec`, one-dir bundle) → Inno Setup installer (`installer/rev80.iss`, non-admin install).

Linux desktop install: `pip install --user .` (places `rev80`/`rev80-headless` in `~/.local/bin`) then `rev80 --install-desktop-entry` (writes an XDG `.desktop` entry + icon under `~/.local/share/`; see `desktop.py`). No separate build step — this is the same wheel as any other pip install.

`_paths.py` must be used for all resource and data directory lookups — it handles the `sys._MEIPASS` path difference in frozen builds. Bundled resource files (e.g. `logging.yaml`, the icon font) must physically live under `src/rev80/` and be declared in `pyproject.toml`'s `[tool.setuptools.package-data]` to survive a non-editable `pip install`.
