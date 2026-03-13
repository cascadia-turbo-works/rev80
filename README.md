# vibechecker

A Python desktop application for capturing, analyzing, and recording vibration data from industrial rotating equipment. Designed for predictive maintenance workflows using MEMS accelerometers connected via USB audio interfaces (Digiducer) or USB DAQ hardware.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Running the App](#running-the-app)
- [Architecture](#architecture)
- [Module Reference](#module-reference)
- [Data Pipeline](#data-pipeline)
- [AcquisitionSettings](#acquisitionsettings)
- [VibeSample](#vibesample)
- [Simulated Sensor](#simulated-sensor)
- [Data Storage](#data-storage)
- [Configuration](#configuration)
- [Testing](#testing)

---

## Features

- Real-time time-domain and frequency-domain plots
- Welch-based power spectral density estimation with automatic peak detection
- Velocity spectrum derived from acceleration via frequency-domain integration
- Single-shot and continuous streaming capture modes
- 4th-order Butterworth highpass filter (default 10 Hz cutoff) for DC removal
- HDF5 file save/load for post-processing and archiving
- Simulated sensor for offline development and testing without hardware
- Configurable units: Earth gravity (g), metric (mm/s²), imperial (in/s²)

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd vibegui

# Install in editable mode
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

**Dependencies:** `numpy`, `scipy`, `pandas`, `dearpygui`, `sounddevice`, `h5py`, `pyyaml`, `matplotlib`, `path`

---

## Running the App

```bash
# Standard launch
python -m vibechecker

# With debug logging to console
python -m vibechecker --debug
```

---

## Architecture

The app is structured as a linear data pipeline with no message bus. Each layer hands data directly to the next via registered callbacks.

```text
┌──────────────────────────────────────────────┐
│  VibeSensor  (sensor.py)                     │
│  sounddevice.InputStream  OR                 │
│  SimulatedSensor daemon thread               │
│  → scales raw float32 by per-channel factor  │
│  → fires callback(dict) on every block       │
└────────────────────┬─────────────────────────┘
                     │ dict: {status, rel_time,
                     │        timestamp, unit, data}
                     ▼
┌──────────────────────────────────────────────┐
│  DataCollector  (collector.py)               │
│  → selects channel                           │
│  → optional Butterworth highpass filter      │
│  → wraps result in VibeSample                │
│  → routes to Queue (single-shot)             │
│     or registered callbacks (streaming)      │
└────────────────────┬─────────────────────────┘
                     │ VibeSample
                     ▼
┌──────────────────────────────────────────────┐
│  GUI  (gui.py)  — dearpygui                  │
│  → display_sample() registered as callback   │
│  → calls sample.get_accel() + sample.fft()   │
│  → updates line series, axis limits,         │
│     peak table                               │
└──────────────────────────────────────────────┘
                     │
                     ▼ (on save)
┌──────────────────────────────────────────────┐
│  HDF5 files  in  DEVDATA/                    │
│  VibeSample.save() / VibeSample.load()       │
└──────────────────────────────────────────────┘
```

---

## Module Reference

| Module | Responsibility |
| --- | --- |
| `__main__.py` | Entry point — logging setup, `GUI` instantiation, main loop, cleanup |
| `logger.py` | YAML-configured logging (`logging.yaml`); writes to `log/`; global exception hook |
| `util.py` | Constants (`SAMPLERATES`, `BLOCKSIZES`, `MAXFREQS`, `BINSIZES`, `UNITS`), unit conversion helpers, `UI_Elements` dearpygui tag registry, `NoDevicesFound` / `FormatError` exceptions |
| `sensor.py` | `VibeSensor` dataclass — wraps a sounddevice `InputStream`; `VibeSensor.find()` enumerates hardware + simulation fallback |
| `digiducer.py` | `FindDigiducer()` — probes sounddevice device list for Digiducer USB audio hardware; decodes sensitivity and scale factors from device name string |
| `sample.py` | `AcquisitionSettings` — blocksize/samplerate/maxfreq/binsize with enforced interdependencies; `VibeSample` — time-domain block with HDF5 I/O, Welch FFT, unit conversion |
| `collector.py` | `DataCollector` — state machine: connect/disconnect, start/stop stream, single-shot queue capture, Butterworth filter, callback registry |
| `simulation.py` | `SimulatedSensor` (threading-based fake stream) + signal generators: `GenerateTone`, `GenerateNoise`, `GenerateBearingVibration_SpectralMethod`, `GenerateBearingVibration_TemporalMethod` |
| `gui.py` | `GUI` class — full dearpygui layout, sensor selection UI, acquisition settings controls, streaming buttons, plot updates, file I/O dialogs |

---

## Data Pipeline

### 1. Acquisition — `VibeSensor` (`sensor.py`)

`VibeSensor` wraps a `sounddevice.InputStream` configured with:

| Parameter | Source |
| --- | --- |
| `device_id` | Detected hardware or simulation flag |
| `channels` | Fixed at 2 (stereo) |
| `samplerate` | `AcquisitionSettings.samplerate` |
| `blocksize` | `AcquisitionSettings.blocksize` |
| `dtype` | `float32` |

On each audio block the sounddevice callback fires `VibeSensor._callback`, which:

1. Parses the sounddevice status flags into a human-readable string
2. Multiplies raw `float32` data by per-channel `scale` factors
3. Packages a dict `{status, rel_time, timestamp, unit, data}` and passes it to the registered `callback`

**Device discovery** — `VibeSensor.find()` calls `FindDigiducer()` and falls back to `SimulatedSensor` if no hardware is found.

### 2. Digiducer Device Encoding — `digiducer.py`

Digiducer devices encode hardware parameters in the sounddevice device name string:

```text
Model_Format_SerialNumber_Sensitivity_Sensitivity_CalibrationDate
```

| Format code | Meaning | Scale formula |
| --- | --- | --- |
| `1` | Acceleration output | `855400.0 / sensitivity[ch]` |
| `2` | Voltage, 100 mV/g | `8388608.0 / sensitivity[ch]` |
| `3` | Voltage, 50 mV ref | `8388608.0 / sensitivity[ch]` (adjusted) |

On non-Windows systems the default host API is used; on Windows, WDM-KS is preferred for reliable sample rate control.

### 3. Preprocessing — `DataCollector` (`collector.py`)

`DataCollector.recieve_data(samp)`:

1. Extracts the configured channel (0 or 1) from the 2-channel block
2. Optionally applies a **4th-order Butterworth highpass filter** (default `butter_fc = 10 Hz`) using SOS coefficients for numerical stability — guards against DC offset and sub-Nyquist cutoff violations
3. Wraps the result in a `VibeSample`
4. Routes:
   - **Streaming mode** → fires all registered `callbacks` (GUI update path)
   - **Single-shot mode** → puts sample in `self.queue` and stops the stream

### 4. Analysis — `VibeSample.fft()` (`sample.py`)

Spectral estimation uses `scipy.signal.welch` with:

- **Window:** Hann
- **Overlap:** 50%
- **Bin size:** controlled by `AcquisitionSettings.binsize` (Hz), which sets `nperseg`

**Velocity spectrum** (when `integrate=True`) divides the acceleration PSD by `(2πf)²` (frequency-domain integration), then converts units via `AcquisitionSettings.units`.

Peak detection returns the top N peaks above a prominence threshold.

### 5. Visualisation — `GUI.display_sample()` (`gui.py`)

On every streaming block:

- `sample.get_accel(config)` → DataFrame with `['time', 'signal']` columns + RMS scalar
- `sample.fft(config)` → DataFrame with spectral columns + peak index list
- `dpg.set_value(tag, [x, y])` updates dearpygui line series in-place
- Axis limits and peak table rows are refreshed

---

## AcquisitionSettings

`AcquisitionSettings` (`sample.py`) enforces interdependencies between four parameters. **Always use the public setters** — do not write to `_fs`, `_ns` etc. directly.

| Property | Description | Valid values |
| --- | --- | --- |
| `samplerate` | ADC sample rate (Hz) | `SAMPLERATES` list |
| `blocksize` | Samples per acquisition block | Powers of 2, 256 – 262144 |
| `maxfreq` | Upper frequency limit for FFT display (Hz) | `MAXFREQS` list |
| `binsize` | Frequency resolution of FFT (Hz) | `BINSIZES` list |
| `channel` | Which of the two input channels to process | `0` or `1` |
| `units` | Engineering unit for output | `'g'`, `'mm'`, `'in'` |
| `integrate` | Return velocity spectrum instead of acceleration | `bool` |
| `butter_fc` | Highpass filter cutoff (Hz); `None` disables filter | `float` or `None` |

**Automatic adjustments:**

- Setting `maxfreq` → raises `samplerate` to at least `2 × maxfreq` if needed
- Setting `binsize` → raises `blocksize` to the next power of 2 that satisfies `samplerate / blocksize ≤ binsize`

---

## VibeSample

`VibeSample` (`sample.py`) is the central data object. It holds one block of filtered, scaled time-domain samples and exposes analysis methods.

```python
sample.data          # numpy.ndarray float64, shape (N,)
sample.samplerate    # int — Hz
sample.unit          # str — 'g', 'mm', or 'in'
sample.timestamp     # datetime
sample.rel_time      # float — seconds since stream start
sample.status        # str — 'OKAY', 'UNDERRUN', etc.

sample.get_accel(config)  # → DataFrame ['time', 'signal'] + RMS
sample.fft(config)        # → DataFrame ['freq', 'signal', ...] + peak indices
sample.save(path)         # → HDF5 file
sample.load(path)         # → VibeSample (class method)
```

---

## Simulated Sensor

`VibeSensor.simulated()` returns a sensor with `is_simulation=True`. When `DataCollector.connect_sensor()` calls `sensor.connect()`, a `SimulatedSensor` daemon thread is returned instead of a sounddevice stream. The simulation generates bearing-defect vibration signals (running rate + fault-order harmonics) useful for offline UI and algorithm development without physical hardware.

Available generators in `simulation.py`:

| Generator | Description |
| --- | --- |
| `GenerateTone(freq, samplerate, duration)` | Pure sinusoid |
| `GenerateNoise(samplerate, duration)` | White Gaussian noise |
| `GenerateBearingVibration_SpectralMethod(...)` | Bearing fault signal assembled in frequency domain |
| `GenerateBearingVibration_TemporalMethod(...)` | Bearing fault signal assembled in time domain |

---

## Data Storage

Samples are saved as HDF5 (`.h5`) files in the `DEVDATA/` directory.

```python
sample.save("DEVDATA/my_measurement")
# → writes DEVDATA/my_measurement_2024-01-15T14-32-00.h5
#   (colons replaced by hyphens for FAT32 compatibility)

loaded = VibeSample.load("DEVDATA/my_measurement_2024-01-15T14-32-00.h5")
```

HDF5 datasets stored per file: `data`, `samplerate`, `unit`, `timestamp`, `rel_time`, `status`, `label`.

---

## Configuration

No persistent config file — settings live in the `AcquisitionSettings` object and are reset on each launch. Hardware is auto-detected via `VibeSensor.find()` on startup; device selection and all acquisition parameters are adjustable from the GUI sidebar.

Logging is configured via `logging.yaml` in the project root. Log files are written to `log/`.

---

## Testing

Tests are parametrized over all detected sensors (including `SimulatedSensor`) and run without physical hardware.

```bash
# Run all tests
pytest tests/

# Single file
pytest tests/test_sample.py

# Single test
pytest tests/test_vibechecker.py::test_save

# Filter by keyword
pytest tests/ -k "stream"
```
