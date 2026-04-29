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
| `picoscope.py` | `FindPicoScope()` enumeration; `PicoScopeStream` acquisition thread; watchdog/recovery; per-channel coupling and voltage range config; AWG signal generator control |
| `scope_sensor.py` | `ScopeSensor` dataclass — IEPE sensor metadata: name, sensitivity (mV/EU), engineering units, optional target unit for frequency-domain integration |
| `scope_sensor_registry.py` | `ScopeSensorRegistry` — YAML-backed global sensor library (`scope_sensors.yaml`); CRUD by ID/name; loaded from `~/.config/vibechecker/` |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators (`GenerateTone`, bearing-defect) for offline dev/test |
| `sample.py` | `AcquisitionSettings` (derived samplerate/blocksize from maxfreq/binsize; per-channel names, target units, amplitude modes, couplings, voltage ranges) + `VibeSample` (HDF5 I/O, `process()` → `ChannelResult`) |
| `collector.py` | `DataCollector` — stream lifecycle, per-channel Butterworth filter bank, channel→`ScopeSensor` assignment (mV→EU), 32-frame ring cache, trend accumulation, `new_frame_event` signal, HDF5 save/load |
| `config.py` | OS-aware device config directory (`~/.config/vibechecker/` on Linux, `%APPDATA%/vibechecker/` on Windows); per-device YAML persistence with atomic writes; default config fallback |
| `gui.py` | `GUI` class — dearpygui 3-panel layout (controls / plots / results), `_poll_new_frames()` render loop, config dialogs (Device/Channels/Sensor/Spectrum/Siggen), spectrum FFT window/preset controls, per-channel result cards, trend plot, HDF5 file load/save |
| `logger.py` | YAML-configured logging; rotating log files written to `log/` |
| `_paths.py` | Runtime-safe path resolution — development vs. PyInstaller frozen bundle; `resource_path()`, `data_dir()`, `log_dir()` |
| `_pico_loader.py` | Windows-only: registers PicoSDK DLL search path before `picosdk` import |

### Data flow details

- `VibeSensor._callback` is the hardware stream callback; it scales raw ADC counts to mV via per-channel voltage range and packages a dict keyed by channel index.
- `DataCollector.receive_data` looks up the `ScopeSensor` assigned to each channel, applies per-channel Butterworth highpass/lowpass filters, converts mV→EU via `sensitivity`, then wraps each channel in a `VibeSample`.
- `DataCollector._data_callback` appends the frame to a 32-frame ring cache (deque) and sets `new_frame_event`. All consumers — GUI render loop, `collect_sample`, tests — read from `frame_cache` via `new_frame_event`; there is no separate callbacks fan-out.
- `VibeSample.process()` uses `scipy.signal.welch` with configurable window/overlap. Cross-modality conversion (accel↔vel↔disp) uses frequency-domain integration via `(2πf)^n` scaling. Returns a `ChannelResult` frozen dataclass.
- Data is saved as HDF5 (`.h5`) into `DEVDATA/`. File names include an ISO timestamp with `:` replaced by `-` for FAT32 compatibility.

### AcquisitionSettings interdependencies

Changing `maxfreq` auto-adjusts `samplerate`; changing `binsize` auto-adjusts `blocksize` to the next power of two. These are enforced in the setters — do not bypass them by setting private `_fs`/`_ns` directly.

Per-channel fields (`channel_names`, `channel_target_units`, `channel_amplitude_modes`, `channel_couplings`, `channel_voltage_ranges`) are dicts keyed by channel index (0-based). They are independent of each other and of the global acquisition parameters.

### Simulated sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. `VibeSensor.connect()` checks this flag and returns a `SimulatedSensor` instead of a hardware stream. The simulation generates bearing-defect signals with configurable running rate and fault multiples — useful for offline UI/algorithm development.

## Persistence

### HDF5 measurement files (v3 format)

Saved to `DEVDATA/*.h5`. Layout:

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

`~/.config/vibechecker/scope_sensors.yaml` — global IEPE sensor definitions shared across all devices. Managed via `ScopeSensorRegistry`. Each entry: `{id, name, sensitivity_mv_per_eu, engineering_units, target_unit}`.

## Offline analysis

`.h5` files can be loaded without hardware present (File → Load in GUI). The GUI enters browse mode: ← → buttons step through stored frames, each re-processed through `VibeSample.process()` using the settings snapshot embedded in the file. No `DataCollector` or stream is required.

## Build / packaging

```bash
# Linux build (Git Bash on Windows for .bat equivalent)
./build.sh

# Windows
build.bat
```

Build pipeline: collect PicoSDK DLLs → PyInstaller (`vibechecker.spec`, one-dir bundle) → Inno Setup installer (`installer/vibechecker.iss`, non-admin install).

`_paths.py` must be used for all resource and data directory lookups — it handles the `sys._MEIPASS` path difference in frozen builds.
