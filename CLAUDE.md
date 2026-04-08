# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**vibechecker** — a Python desktop GUI for capturing, analyzing, and recording vibration data from industrial rotating equipment. It targets industrial machinery predictive maintenance using MEMS accelerometers (Digiducer via USB audio interface or MCC USB-1608FS-Plus DAQ).

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
  receive_data()                           poll_new_frames()
    → Butterworth filter                     if new_frame_event:
    → VibeSample per channel                   grab frame_cache[-1]
    → frame_cache.append()                     VibeSample.process()
    → new_frame_event.set()  ─────────────→    display_frame()
```

The collector and GUI are decoupled via `threading.Event`. The hardware
thread never touches DPG widgets. When the GUI is slower than the data
rate, it skips to the latest frame — all earlier frames remain in the
32-frame ring cache for browsing.

### Key modules

| Module | Role |
|---|---|
| `util.py` | Constants (`MAXFREQ_PRESETS`, `BINSIZE_PRESETS`), unit taxonomy and SI conversion, `UI_Elements` tag registry |
| `sensor.py` | `VibeSensor` dataclass — device metadata; `find()` enumerates PicoScopes; `simulated()` returns test sensor; `connect()` returns the appropriate stream |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators for offline dev/test |
| `sample.py` | `AcquisitionSettings` (derived samplerate/blocksize from maxfreq/binsize) + `VibeSample` (HDF5 I/O, `process()` → `ChannelResult`) |
| `collector.py` | `DataCollector` — stream lifecycle, per-channel filters, 32-frame ring cache, trend accumulation, `new_frame_event` signal, HDF5 save/load |
| `digiducer.py` | `FindDigiducer()` — legacy Digiducer USB audio device discovery |
| `gui.py` | `GUI` class — dearpygui layout, `poll_new_frames()` render loop, plots and config dialogs |
| `logger.py` | YAML-configured logging; log files written to `log/` |

### Data flow details

- `VibeSensor._callback` is the hardware stream callback; it scales raw data by per-channel `scale` factors and packages a dict.
- `DataCollector.receive_data` applies per-channel Butterworth highpass/lowpass filters (configurable, default HP 10 Hz) then wraps each channel in a `VibeSample`.
- `DataCollector.data_callback` appends the frame to a 32-frame ring cache and sets `new_frame_event`. The GUI's `poll_new_frames()` checks this event each render tick and displays the latest frame. Programmatic consumers (e.g. `collect_sample` one-shot) still use the `callbacks` dict directly.
- `VibeSample.process()` uses `scipy.signal.welch` with configurable window/overlap. Cross-modality conversion (accel/vel/disp) uses frequency-domain integration via `(2*pi*f)^n` scaling.
- Data is saved as HDF5 (`.h5`) into `DEVDATA/`. File names include an ISO timestamp with `:` replaced by `-` for FAT32 compatibility.

### AcquisitionSettings interdependencies

Changing `maxfreq` auto-adjusts `samplerate`; changing `binsize` auto-adjusts `blocksize` to the next power of two. These are enforced in the setters — do not bypass them by setting private `_fs`/`_ns` directly.

### Simulated sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. `VibeSensor.connect()` checks this flag and returns a `SimulatedSensor` instead of a hardware stream. The simulation generates bearing-defect signals with configurable running rate and fault multiples — useful for offline UI/algorithm development.
