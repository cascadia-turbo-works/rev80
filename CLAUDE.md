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
VibeSensor / SimulatedSensor
        │  (sounddevice InputStream or SimulatedSensor thread)
        ▼
DataCollector          ← owns AcquisitionSettings, Queue, callback registry
        │  (recieve_data → optional Butterworth filter → VibeSample)
        ▼
VibeSample             ← raw time-domain block; computes FFT/Welch via .fft()
        │  (saved/loaded as HDF5 .h5 files in DEVDATA/)
        ▼
GUI (dearpygui)        ← registers callbacks on DataCollector, drives plots
```

### Key modules

| Module | Role |
|---|---|
| `util.py` | Constants (`SAMPLERATES`, `BLOCKSIZES`, `MAXFREQS`, `BINSIZES`), unit conversion, `UI_Elements` tag registry |
| `sensor.py` | `VibeSensor` dataclass — wraps sounddevice stream; `VibeSensor.find()` enumerates hardware + simulation |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators for offline dev/test |
| `sample.py` | `AcquisitionSettings` (blocksize/samplerate/maxfreq/binsize with interdependency enforcement) + `VibeSample` (HDF5 I/O, FFT via Welch, unit conversion) |
| `collector.py` | `DataCollector` — state machine for start/stop streaming, single-shot capture, save/load, trend accumulation |
| `digiducer.py` | `FindDigiducer()` — probes sounddevice for Digiducer USB audio devices |
| `gui.py` | `GUI` class — all dearpygui layout, callbacks wired to `DataCollector` |
| `logger.py` | YAML-configured logging; log files written to `log/` |

### Data flow details

- `VibeSensor._callback` is the sounddevice callback; it scales raw float32 data by per-channel `scale` factors and packages a dict.
- `DataCollector.recieve_data` applies an optional 4th-order Butterworth highpass filter (default `butter_fc=10 Hz`) then wraps the result in a `VibeSample`.
- In streaming mode, `DataCollector.data_callback` fires registered `callbacks` (GUI update functions). In single-shot mode it routes through a `Queue`.
- `VibeSample.fft()` uses `scipy.signal.welch` with a Hann window. Velocity spectrum is derived by dividing acceleration spectrum by `(2πf)²`.
- Data is saved as HDF5 (`.h5`) into `DEVDATA/`. File names include an ISO timestamp with `:` replaced by `-` for FAT32 compatibility.

### AcquisitionSettings interdependencies

Changing `maxfreq` auto-adjusts `samplerate`; changing `binsize` auto-adjusts `blocksize` to the next power of two. These are enforced in the setters — do not bypass them by setting private `_fs`/`_ns` directly.

### Simulated sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. `VibeSensor.connect()` checks this flag and returns a `SimulatedSensor` instead of a sounddevice stream. The simulation generates bearing-defect signals with configurable running rate and fault multiples — useful for offline UI/algorithm development.
