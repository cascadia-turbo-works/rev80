# vibechecker

A Python desktop application for capturing, analyzing, and recording vibration data from industrial rotating equipment. Designed for predictive maintenance workflows using IEPE accelerometers and voltage-output sensors connected via USB oscilloscopes (PicoScope 4000A series) or USB audio interfaces (Digiducer legacy).

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Running the App](#running-the-app)
- [Architecture](#architecture)
- [Module Reference](#module-reference)
- [Data Pipeline](#data-pipeline)
- [AcquisitionSettings](#acquisitionsettings)
- [VibeSample and ChannelResult](#vibesample-and-channelresult)
- [ScopeSensor](#scopesensor)
- [Signal Generator](#signal-generator)
- [Simulated Sensor](#simulated-sensor)
- [Data Storage](#data-storage)
- [Configuration and Persistence](#configuration-and-persistence)
- [PicoScope Integration](#picoscope-integration)
- [Testing](#testing)
- [Building for Windows](#building-for-windows)

---

## Features

- Real-time time-domain and frequency-domain plots across multiple simultaneous channels
- Welch-based power spectral density with configurable window (Hann, Blackman-Harris, Flattop, Hamming, etc.)
- Velocity and displacement spectra derived from acceleration via frequency-domain integration
- Single-shot and continuous streaming capture modes
- Per-channel 4th-order Butterworth highpass and lowpass filters
- Configurable IEPE sensor library: sensitivity (mV/EU), modality, engineering units
- PicoScope 4000A built-in signal generator for excitation testing
- HDF5 file save/load for post-processing and archiving
- 32-frame acquisition cache with backward browse
- Trend plot: overall vibration amplitude over time per channel
- Simulated sensor (bearing-defect signal generator) for offline development and CI testing
- Configurable amplitude modes: RMS, 0-P, P-P
- Configurable units: acceleration (g, mm/s², in/s²), velocity (mm/s, in/s, mil/s), displacement (mm, in, mil)

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd vibegui

# Or install dependencies directly
pip install -r requirements.txt

# Install in editable mode
pip install -e .
```

**Dependencies:** `numpy`, `scipy`, `pandas`, `dearpygui==2.0.0`, `sounddevice`, `h5py`, `pyyaml`, `matplotlib`, `picosdk`

The `picosdk` package requires the PicoScope 4000A driver (`ps4000a.dll` / `.so`) to be present on the system path for hardware operation.

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

The app is a linear pipeline with no message bus. Each layer hands data directly to the next via registered callbacks.

```text
┌──────────────────────────────────────────────────────────┐
│  PicoScopeStream  (picoscope.py)                         │
│  OR  SimulatedSensor  (simulation.py)                    │
│                                                          │
│  → polls hardware at blocksize intervals                 │
│  → ADC counts → mV via adc2mV()                         │
│  → fires callback(dict) with all channels                │
└───────────────────────────┬──────────────────────────────┘
                            │  dict: {status, rel_time,
                            │         timestamp, unit,
                            │         channels, data,
                            │         overflow_mask}
                            ▼
┌──────────────────────────────────────────────────────────┐
│  DataCollector  (collector.py)                           │
│  → per-channel mV → EU via ScopeSensor.sensitivity      │
│  → per-channel Butterworth highpass + lowpass filter     │
│  → wraps each channel in VibeSample                      │
│  → appends frame dict to 32-frame ring cache             │
│  → fans out to GUI callbacks                             │
│  → accumulates trend (overall amplitude per channel)     │
└───────────────────────────┬──────────────────────────────┘
                            │  frame dict: {ch: VibeSample, …}
                            ▼
┌──────────────────────────────────────────────────────────┐
│  VibeSample.process(config)  (sample.py)                 │
│  → Welch FFT with configurable window and overlap        │
│  → frequency-domain integration (accel → vel → disp)    │
│  → peak detection                                        │
│  → returns ChannelResult (frozen dataclass)              │
└───────────────────────────┬──────────────────────────────┘
                            │  ChannelResult
                            ▼
┌──────────────────────────────────────────────────────────┐
│  GUI  (gui.py)  — dearpygui                              │
│  → updates time-domain and spectrum line series          │
│  → updates peak table, trend plot, overall amplitude     │
│  → no axis auto-fit; Autoscale button fits on demand     │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼ (on save)
┌──────────────────────────────────────────────────────────┐
│  HDF5 files  in  DEVDATA/                                │
│  DataCollector.save_data() / load_data()                 │
│  multi-channel layout: /frames/{i}/channels/{ch}/…       │
└──────────────────────────────────────────────────────────┘
```

---

## Module Reference

| Module | Responsibility |
| --- | --- |
| `__main__.py` | Entry point — logging setup, `GUI` instantiation, main loop, cleanup |
| `logger.py` | YAML-configured logging (`logging.yaml`); writes to `log/`; global exception hook |
| `util.py` | Constants (`MAXFREQ_PRESETS`, `BINSIZE_PRESETS`, `UNITS`, `AMPLITUDE_MODES`), unit taxonomy and SI conversion, integration order helpers, `UI_Elements` DPG tag registry, exceptions |
| `sensor.py` | `VibeSensor` dataclass — device metadata; `find()` enumerates hardware PicoScopes only; `simulated()` returns a test sensor; `connect()` returns the appropriate stream |
| `picoscope.py` | `FindPicoScope()` — enumerates PS4000A units; `PicoScopeStream` — polling thread, ADC→mV, overflow detection, watchdog recovery, signal generator setup |
| `scope_sensor.py` | `ScopeSensor` dataclass — IEPE sensor metadata: name, sensitivity (mV/EU), engineering units, amplitude mode, UUID |
| `scope_sensor_registry.py` | `ScopeSensorRegistry` — YAML-backed CRUD for user sensor library and per-channel assignments; persists signal generator config |
| `sample.py` | `AcquisitionSettings` — spectrum and filter config with derived properties; `VibeSample` — single-channel time-domain block with HDF5 I/O and `process()` → `ChannelResult`; `ChannelResult` — frozen display-ready result |
| `collector.py` | `DataCollector` — multi-channel acquisition state machine: stream lifecycle, per-channel filter application, 32-frame ring cache, trend accumulation, HDF5 save/load |
| `simulation.py` | `SimulatedSensor` (daemon thread) + signal generators: `GenerateTone`, `GenerateNoise`, `GenerateBearingVibration_SpectralMethod`, `GenerateBearingVibration_TemporalMethod` |
| `gui.py` | `GUI` class — dearpygui three-column layout, channel config panel, sensor library, spectrum and time-domain plots, trend plots, file I/O |

---

## Data Pipeline

### 1. Acquisition — `PicoScopeStream` (`picoscope.py`)

`PicoScopeStream` is a background polling thread that wraps `ps4000aRunStreaming`. On each poll:

1. Converts ADC counts → mV via `adc2mV()` for all enabled channels
2. Detects ADC overflow per channel via the overflow bitmask
3. Accumulates mV samples in a `(blocksize × N_channels)` buffer
4. When the buffer fills, fires the registered callback with:

```python
{
    'status':        str,           # 'OKAY', 'OVERFLOW', etc.
    'overflow_mask': int,           # bitmask, one bit per channel
    'rel_time':      float,         # seconds since stream start
    'timestamp':     datetime,
    'unit':          ['mV', ...],   # one entry per channel
    'channels':      [0, 1, ...],   # enabled channel indices
    'data':          ndarray,       # shape (blocksize, N_channels), mV
}
```

A watchdog thread monitors for >5 s silence and attempts up to 3 reconnect cycles automatically.

**Device discovery** — `VibeSensor.find()` calls `FindPicoScope()` and returns hardware-only results. `SimulatedSensor` is excluded; use `VibeSensor.simulated()` for offline development and testing.

### 2. Preprocessing — `DataCollector` (`collector.py`)

`DataCollector.receive_data(frame)` runs in the hardware callback thread:

1. For each enabled channel, extracts the channel column from `frame['data']`
2. Converts mV → engineering units using `ScopeSensor.sensitivity` (if a sensor is assigned)
3. Optionally applies a **4th-order Butterworth highpass** filter (default 10 Hz cutoff) using SOS coefficients for numerical stability
4. Optionally applies a **4th-order Butterworth lowpass** filter
5. Wraps each channel's data in a `VibeSample`
6. Assembles a frame dict `{ch: VibeSample, 'overflow': mask}` and appends it to a 32-frame ring cache
7. Fires registered GUI callbacks with the frame dict

### 3. Spectral Analysis — `VibeSample.process()` (`sample.py`)

`VibeSample.process(config)` returns a `ChannelResult`:

- **Welch PSD** — `scipy.signal.welch` with configurable window function, 50% overlap, and bin size controlled by `AcquisitionSettings.binsize`
- **Frequency-domain integration** — when the assigned `ScopeSensor.engineering_units` modality differs from the target display unit, integration is applied by multiplying the spectrum by `(1j·2πf)^n` where `n` is the number of integration steps (negative = integrate, positive = differentiate)
- **Peak detection** — `scipy.signal.find_peaks` sorted descending by amplitude
- **Overall amplitude** — broadband RMS/0-P/P-P computed from time-domain data

### 4. Visualisation — `GUI.display_frame()` (`gui.py`)

On every streaming block, for each active channel:

- Calls `sample.process(config)` → `ChannelResult`
- Updates time-domain and spectrum line series via `dpg.set_value()`
- Updates peak table and trend plot
- Axis limits are **not** automatically adjusted; press **Autoscale** to fit all axes on demand

---

## AcquisitionSettings

`AcquisitionSettings` (`sample.py`) centralises spectrum, filter, and channel config. Use the public properties — do not write to private `_` attributes directly.

### Spectrum settings

| Property | Description |
| --- | --- |
| `maxfreq` | Upper frequency of interest (Hz) — drives `samplerate` selection |
| `binsize` | Frequency resolution of Welch FFT (Hz) — drives `blocksize` selection |
| `samplerate` | **Derived** — minimum samplerate ≥ 2 × maxfreq |
| `blocksize` | **Derived** — next power of 2 satisfying samplerate / blocksize ≤ binsize |
| `acquisition_period` | **Derived** — blocksize / samplerate (seconds) |
| `n_fft_bins` | **Derived** — number of Welch output bins |
| `fft_window` | Welch window function: `'hann'` (default), `'blackmanharris'`, `'flattop'`, `'hamming'`, `'boxcar'`, `'bartlett'` |
| `welch_overlap` | Welch segment overlap fraction (default 0.5) |

### Filter settings

| Property | Description |
| --- | --- |
| `highpass_enabled` | Enable 4th-order Butterworth highpass filter |
| `highpass_fc` | Highpass cutoff frequency (Hz) |
| `lowpass_enabled` | Enable 4th-order Butterworth lowpass filter |
| `lowpass_fc` | Lowpass cutoff frequency (Hz) |

### Channel settings

| Property | Description |
| --- | --- |
| `enabled_channels` | List of active channel indices |
| `channel_voltage_ranges` | Dict `{ch: range_index}` — PS4000A voltage range per channel |
| `channel_couplings` | Dict `{ch: 'AC'|'DC'}` — input coupling per channel |

Helper methods: `voltage_range_for(ch)`, `coupling_for(ch)`, `copy()`.

---

## VibeSample and ChannelResult

### VibeSample

`VibeSample` (`sample.py`) holds one block of time-domain samples for a single channel.

```python
sample.data          # numpy.ndarray float64, shape (N,)
sample.samplerate    # int — Hz
sample.unit          # str — engineering unit string
sample.modality      # str — 'acceleration', 'velocity', 'displacement', 'raw'
sample.timestamp     # datetime
sample.rel_time      # float — seconds since stream start
sample.status        # str — 'OKAY', 'OVERFLOW', etc.

sample.process(config)   # → ChannelResult
sample.save(path)        # → HDF5 file
sample.load(path)        # → VibeSample (class method)
```

### ChannelResult

`ChannelResult` is a frozen dataclass returned by `VibeSample.process()`. It is the canonical display-ready result for one channel at one instant.

```python
result.channel      # int
result.unit         # str — display unit
result.time_data    # ndarray — time-domain signal in display units
result.time_vec     # ndarray — time axis (seconds)
result.freq         # ndarray — full Welch frequency axis (Hz)
result.spectrum     # ndarray — PSD in display units
result.peaks        # ndarray — indices into freq/spectrum arrays
result.overall      # float — broadband amplitude (RMS/0-P/P-P per config)
result.timestamp    # datetime
result.rel_time     # float
result.status       # str
```

The `freq` and `spectrum` arrays cover the **full Welch output range** (up to Nyquist). `maxfreq` governs samplerate selection and broadband energy integration but does not crop the displayed spectrum.

---

## ScopeSensor

`ScopeSensor` (`scope_sensor.py`) describes an IEPE sensor connected to one PicoScope channel.

```python
sensor.name               # str — user label (e.g., 'PCB 352C33 Ch1')
sensor.engineering_units  # str — source modality (e.g., 'g', 'mm/s')
sensor.sensitivity        # float — mV per engineering unit (e.g., 10.2 for 10.2 mV/g)
sensor.target_unit        # str | None — display unit override
sensor.amplitude_mode     # str — 'RMS', '0-P', or 'P-P'
sensor.id                 # str — UUID, used as persistent key
sensor.notes              # str — freeform
```

Sensors are managed through `ScopeSensorRegistry` and assigned to channels via the GUI Channel Config panel. When a sensor is assigned, `DataCollector` divides incoming mV data by `sensitivity` to produce engineering units before creating `VibeSample` objects.

---

## Signal Generator

The PicoScope 4000A has a built-in arbitrary waveform generator (AWG) on its AUX output. `vibechecker` exposes this through the **Generate** config tab.

| Setting | Description |
| --- | --- |
| Enabled | Enable/disable AWG output |
| Waveform | Sine, Square, Triangle, DC voltage, Ramp Up/Down |
| Frequency (Hz) | Output frequency |
| Amplitude (mV pk-pk) | Peak-to-peak voltage |
| Offset (mV) | DC offset |

**Timing:** The signal generator runs **continuously** from stream start to stream stop. It is programmed once when `start()` is called (`_setup_siggen()` → `ps4000aSetSigGenBuiltIn` with `PS4000A_SIGGEN_NONE` trigger source = free-running). There is no per-block triggering; the AWG and the ADC acquisition run independently and simultaneously.

Signal generator settings are persisted to `~/.config/vibechecker/channel_assignments.yaml` under a `siggen:` key and restored automatically when the same device reconnects.

---

## Simulated Sensor

`VibeSensor.simulated()` returns a `VibeSensor` with `is_simulation=True`. When connected, it starts a `SimulatedSensor` daemon thread that generates synthetic bearing-defect vibration data at the configured samplerate and blocksize.

`SimulatedSensor` is **excluded from `VibeSensor.find()`** — it will never appear in the hardware device list. Use `VibeSensor.simulated()` directly in tests and offline development.

Available generators in `simulation.py`:

| Generator | Description |
| --- | --- |
| `GenerateTone(config, ampl, freq, phase)` | Pure sinusoid |
| `GenerateNoise(config, ampl)` | White Gaussian noise |
| `GenerateBearingVibration_SpectralMethod(config)` | Bearing fault signal assembled in frequency domain (exponential noise floor + running harmonics + bearing-fault sidebands) |
| `GenerateBearingVibration_TemporalMethod(config)` | Bearing fault signal assembled in time domain (noise + harmonics with phase variation) |

The default source for `SimulatedSensor` is `GenerateBearingVibration_TemporalMethod`. The source can be overridden at construction for targeted unit testing.

---

## Data Storage

Samples are saved as HDF5 (`.h5`) files in the `DEVDATA/` directory. The multi-channel layout is:

```
/frames/{i}/
    meta/
        timestamp, rel_time, samplerate, status
    channels/{ch}/
        data, unit, modality, coupling
/trend/{ch}/
    rel_times, overall
```

```python
collector.save_data("DEVDATA/my_run")
# → writes DEVDATA/my_run_2024-01-15T14-32-00.h5
#   (colons replaced by hyphens for FAT32 compatibility)

collector.load_data("DEVDATA/my_run_2024-01-15T14-32-00.h5")
```

---

## Configuration and Persistence

### Sensor library

User-defined IEPE sensors are stored in `~/.config/vibechecker/scope_sensors.yaml` as a list of `ScopeSensor` dicts. Managed via `ScopeSensorRegistry`.

### Channel assignments

Per-channel sensor assignments and input settings are stored in `~/.config/vibechecker/channel_assignments.yaml`:

```yaml
"0":
  enabled: true
  sensor_id: <uuid>
  voltage_range: 10
  coupling: AC
"1":
  enabled: false
  sensor_id: null
siggen:
  enabled: true
  wave_type: PS4000A_SINE
  freq_hz: 100.0
  pktopk_uv: 500000
  offset_uv: 0
```

Assignments are restored automatically when the device reconnects. `save_channel_assignments()` reads before writing to preserve non-channel keys (e.g. `siggen`). Writes are atomic (tempfile + `os.replace`) to prevent corruption.

### Logging

Logging is configured via `vibechecker/logging.yaml`. In development, log files are written to `log/`. In a frozen Windows build, logs are written to `~/Documents/vibechecker/logs/`.

---

## PicoScope Integration

`vibechecker` targets the **PicoScope 4000A series** as its primary acquisition hardware via the `picosdk` Python bindings.

### Key implementation details

| Component | Role |
| --- | --- |
| `FindPicoScope()` | Opens each unit in sequence; reads model, serial, build date, channel count via `ps4000aGetUnitInfo`; returns dicts compatible with `VibeSensor(**dev)` |
| `PicoScopeStream` | Background thread: `ps4000aRunStreaming` → streaming callback → ADC→mV → accumulator → app callback |

**Resilience features:**
- USB power-source fallback: if `ps4000aOpenUnit` fails, retries with `ps4000aChangePowerSource`
- Up to 5 open attempts with 1–2 s delay (extended delay after `PICO_NOT_RESPONDING`)
- Watchdog: if no data arrives for 5 s, attempts up to 3 reconnect cycles before raising
- Overflow logging rate-limited to once per 2 s per channel to avoid log spam

### Dependencies

```bash
pip install picosdk
```

The PicoScope 4000A driver (`ps4000a.dll` on Windows, `libps4000a.so` on Linux) must be present on the system path.

---

## Testing

Tests use `VibeSensor.simulated()` directly and run without physical hardware.

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

Hardware-specific tests in `tests/test_picoscope_hw.py` skip automatically when no PicoScope is detected (`VibeSensor.find()` returns empty).

---

## Building for Windows

Produces a self-contained one-directory executable and a standalone installer (`.exe`) via PyInstaller and Inno Setup. The build must run on a **64-bit Windows machine** with the PicoScope connected and PicoSDK installed — cross-compilation from Linux is not supported.

### Prerequisites

1. **PicoSDK** — install from [picotech.com/downloads](https://www.picotech.com/downloads).
   The installer places `ps4000a.dll` and `picoipp.dll` in `C:\Program Files\Pico Technology\SDK\lib\`.
   **Reboot after installation** so Windows registers the USB kernel driver before the first connection attempt.

2. **Inno Setup 6** — install from [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php).
   A non-admin (per-user) install to `%LOCALAPPDATA%\Programs\Inno Setup 6\` is fine; the build scripts find it automatically.

3. **Python 64-bit** and project dependencies:
   ```bash
   pip install -e ".[dev]" pyinstaller
   ```

### Build

From Git Bash (or PowerShell with `build.bat`):

```bash
# Full pipeline: collect DLLs → PyInstaller → Inno Setup installer
./build.sh

# Individual steps
./build.sh dlls         # collect PicoScope DLLs into drivers/ only
./build.sh pyinstaller  # PyInstaller only (skips DLL collection)
./build.sh installer    # Inno Setup only (requires dist/ to exist)
```

### Output

| Path | Description |
| --- | --- |
| `dist/vibechecker/vibechecker.exe` | Standalone executable (run directly, no install needed) |
| `installer/Output/VibecheckerSetup-<version>.exe` | Windows installer with Start Menu shortcut and uninstaller |

### Runtime paths (installed app)

| Purpose | Location |
| --- | --- |
| Data files (`.h5`) | `~/Documents/vibechecker/data/` |
| Log files | `~/Documents/vibechecker/logs/` |
| Config / sensor library | `%APPDATA%\vibechecker\` |

### Known constraints

- **64-bit only** — PicoSDK DLLs are 64-bit; 32-bit Python will not work.
- **DearPyGui pinned to 2.0.0** — versions above 2.0.0 have a known viewport initialisation crash on Windows.
- **PicoSDK USB kernel driver** — the bundled `ps4000a.dll` is the user-mode library; the USB kernel driver must be installed separately via the PicoSDK installer. Vibechecker will launch without it but will show a "PicoScope driver not found" message in the device dialog.
- **Code signing** — the installer is unsigned; Windows SmartScreen will warn on first run. Right-click → Run anyway, or sign the installer with a certificate for distribution.
