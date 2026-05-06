# vibechecker

A Python desktop application for capturing, analyzing, and recording vibration data from industrial rotating equipment. Designed for predictive maintenance workflows using IEPE accelerometers and voltage-output sensors connected via USB oscilloscopes (PicoScope 4000A series) or USB audio interfaces (Digiducer legacy).

---

## Table of Contents

- [Features](#features)
- [Installing on Windows](#installing-on-windows)
- [Installing from Source (any OS)](#installing-from-source-any-os)
- [Contributing](#contributing)
- [Building the Windows Installer](#building-the-windows-installer)
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
- Configurable frame cache depth (default 32 frames) with backward browse
- Trend plot: overall vibration amplitude over time per channel
- Simulated sensor (bearing-defect signal generator) for offline development and CI testing
- Configurable amplitude modes: RMS, 0-P, P-P
- Configurable units: acceleration (g, mm/s², in/s²), velocity (mm/s, in/s, mil/s), displacement (mm, in, mil)

---

## Installing on Windows

1. Install **PicoSDK 11.1.418** (or PicoScope 7 for Windows) from [picotech.com/downloads](https://www.picotech.com/downloads). **Restart your computer** after installation so Windows registers the USB kernel driver.
2. Run **`VibecheckerSetup-0.1.0.exe`** and follow the installer. It creates a Start Menu shortcut and an uninstaller. No admin rights required.

> **SmartScreen warning:** the installer is currently unsigned. Click *More info → Run anyway* to proceed.

### Runtime file locations

| Purpose | Location |
| --- | --- |
| Measurement data (`.h5`) | `~/Documents/vibechecker/data/` |
| Log files | `~/Documents/vibechecker/logs/` |
| Config / sensor library | `%APPDATA%\vibechecker\` |

---

## Installing from Source (any OS)

Works on Windows, Linux, and macOS. Requires Python 3.10+.

1. Install **PicoSDK** or **PicoScope 7** for your OS from [picotech.com/downloads](https://www.picotech.com/downloads). **Restart your computer** after installation.

2. Get the source and install dependencies:

   ```bash
   git clone <repo-url>/vibegui.git
   cd vibegui

   # Runtime dependencies only
   pip install .

   # Runtime + development tools (pytest, pyinstaller, etc.)
   pip install -e ".[dev]"
   ```

3. Run the app:

   ```bash
   python -m vibechecker

   # With debug logging to console
   python -m vibechecker --debug
   ```

**Runtime dependencies:** `numpy`, `scipy`, `dearpygui==2.0.0`, `h5py`, `pyyaml`, `picosdk`

The `picosdk` package requires the PicoScope 4000A driver (`ps4000a.dll` / `libps4000a.so`) to be present on the system for hardware use. The app will start without it and show a "driver not found" notice in the device dialog — the simulated sensor is still available.

---

## Contributing

### Development environment (Linux / macOS recommended)

```bash
git clone <repo-url>/vibegui.git
cd vibegui

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install in editable mode with dev tools
pip install -e ".[dev]"

# Run the test suite (no hardware required — uses SimulatedSensor)
pytest tests/

# Launch the app against the source tree
python -m vibechecker
```

### Project layout

```
vibechecker/          Python package
  _paths.py           Runtime-safe path resolution (dev vs frozen)
  _pico_loader.py     Windows DLL search path setup for frozen builds
  logging.yaml        Logging configuration (bundled with package)
assets/               App icon source
  vibechecker_icon.svg  Source artwork — edit this to change the icon
  make_icons.sh         Regenerates vibechecker.ico from SVG via Inkscape + ImageMagick
  vibechecker.ico       Multi-resolution icon used by installer and exe
drivers/              PicoScope DLLs (Windows build only, not committed)
installer/            Inno Setup script
tests/                pytest suite
vibechecker.spec      PyInstaller build spec
build.sh              Full build pipeline (Git Bash on Windows)
build.bat             Full build pipeline (cmd.exe on Windows)
```

### Replacing the app icon

Drop a new `assets/vibechecker.ico` in place and rebuild — no changes to `vibechecker.spec` or `installer/vibechecker.iss` are needed. To regenerate the `.ico` from the SVG source:

```bash
# Requires inkscape and imagemagick
cd assets
./make_icons.sh
```

---

## Building the Windows Installer

Produces a self-contained one-directory executable and a standalone installer (`.exe`) via PyInstaller and Inno Setup. **The build must run on a 64-bit Windows machine.**

### Prerequisites

| Tool | Where to get it | Notes |
| --- | --- | --- |
| Python 3.10+ (64-bit) | [python.org](https://www.python.org/downloads/) | Must be 64-bit; add to PATH |
| Git for Windows | [git-scm.com](https://git-scm.com/download/win) | Provides Git Bash for `build.sh` |
| PicoSDK 11.1.418 | [picotech.com/downloads](https://www.picotech.com/downloads) | **Reboot after install** |
| Inno Setup 6 | [jrsoftware.org/isinfo.php](https://jrsoftware.org/isinfo.php) | Per-user install to `%LOCALAPPDATA%` is fine |

Install project dependencies (from Git Bash or cmd.exe):

```bash
pip install -e ".[dev]"
```

### Running the build

```bash
# Full pipeline: collect DLLs → PyInstaller → Inno Setup
./build.sh          # Git Bash
build.bat           # cmd.exe / PowerShell

# Individual steps
./build.sh dlls         # collect PicoScope DLLs into drivers/ only
./build.sh pyinstaller  # PyInstaller only (skips DLL collection)
./build.sh installer    # Inno Setup only (requires dist/ to exist)
```

### Output

| Path | Description |
| --- | --- |
| `dist/vibechecker/vibechecker.exe` | Standalone executable (no install needed) |
| `installer/Output/VibecheckerSetup-<version>.exe` | Installer with Start Menu shortcut and uninstaller |

### Known constraints

- **64-bit only** — PicoSDK DLLs are 64-bit; 32-bit Python will not work.
- **DearPyGui pinned to 2.0.0** — versions above 2.0.0 have a known viewport crash on Windows.
- **USB kernel driver** — `ps4000a.dll` is the user-mode library; the USB kernel driver is installed separately by PicoSDK. Reboot required before first hardware connection.
- **Code signing** — the installer and executable are unsigned; Windows SmartScreen will warn on first run. See `README` code signing notes or sign with `osslsigncode` and a certificate.

---

## Architecture

The app is a linear pipeline. The hardware thread and the GUI render loop are decoupled via a `threading.Event` — the collector never calls into DPG directly.

```text
  Hardware thread                           Main thread
  ─────────────────                         ───────────────────

┌────────────────────────────┐
│  PicoScopeStream           │
│  OR  SimulatedSensor       │
│  → polls hardware          │
│  → ADC → mV → callback     │
└─────────────┬──────────────┘
              │ dict: {status, rel_time,
              │  timestamp, unit, channels,
              │  data, overflow_mask}
              ▼
┌────────────────────────────┐
│  DataCollector             │
│  → mV → EU (ScopeSensor)  │
│  → Butterworth HP + LP    │
│  → VibeSample per channel  │
│  → frame_cache.append()   │
│  → new_frame_event.set()  │─ ─ ─ ─ ─ ─ ─▶┌────────────────────────────┐
└────────────────────────────┘               │  GUI render loop            │
                                             │  _poll_new_frames():         │
                                             │    if event set:            │
                                             │      grab frame_cache[-1]  │
                                             │      process_samples()      │
                                             │      _display_frame()       │
                                             └─────────────┬──────────────┘
                                                           │ (on save)
                                                           ▼
                                             ┌────────────────────────────┐
                                             │  HDF5 files in DEVDATA/    │
                                             │  save_data() / load_data() │
                                             └────────────────────────────┘
```

When the GUI is slower than the hardware data rate, it skips to the latest frame — all earlier frames remain in the ring cache (configurable depth, default 32 frames) for browsing. The hardware thread is never blocked by GUI rendering.

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
| `sample.py` | `AcquisitionSettings` — spectrum, filter, and cache config with derived properties; `VibeSample` — single-channel time-domain block with cached PSD; `ChannelResult` — frozen display-ready result |
| `config.py` | OS-aware config directory; per-device YAML persistence (channels, signal generator, acquisition settings); atomic writes; fallback to built-in defaults |
| `collector.py` | `DataCollector` — multi-channel acquisition state machine: stream lifecycle, per-channel filter application, configurable frame cache (default 32 frames), `new_frame_event` signal for GUI, trend accumulation, HDF5 save/load |
| `simulation.py` | `SimulatedSensor` (daemon thread) + signal generators: `GenerateTone`, `GenerateNoise`, `GenerateBearingVibration_SpectralMethod`, `GenerateBearingVibration_TemporalMethod` |
| `gui.py` | `GUI` class — dearpygui three-column layout with manual render loop (`_poll_new_frames`), channel config panel, sensor library, spectrum and time-domain plots, trend plots, file I/O |

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
6. Assembles a frame dict `{ch: VibeSample, 'overflow': mask}` and appends it to the frame ring cache (configurable depth via `AcquisitionSettings.cache_frames`, default 32)
7. Sets `new_frame_event` to signal the GUI render loop

### 3. Spectral Analysis — `DataCollector.process_sample()` (`collector.py`)

`DataCollector.process_sample(ch, sample)` computes and returns a `ChannelResult`:

- **Welch PSD** — `scipy.signal.welch` with configurable window function, 50% overlap, and bin size controlled by `AcquisitionSettings.binsize`
- **Frequency-domain integration** — when the assigned `ScopeSensor.engineering_units` modality differs from the target display unit, integration is applied by multiplying the spectrum by `(1j·2πf)^n` where `n` is the number of integration steps (negative = integrate, positive = differentiate)
- **Peak detection** — `scipy.signal.find_peaks` sorted descending by amplitude
- **Overall amplitude** — broadband RMS/0-P/P-P computed from time-domain data

### 4. Visualisation — `GUI._poll_new_frames()` / `_display_frame()` (`gui.py`)

The GUI uses a manual render loop (`while dpg.is_dearpygui_running()`). Each tick, `_poll_new_frames()` checks `DataCollector.new_frame_event`. If set, it grabs the latest frame from `frame_cache` and calls `_display_frame()`:

- Calls `DataCollector.process_samples()` → list of `ChannelResult` for each enabled channel
- Updates time-domain and spectrum line series via `dpg.set_value()`
- Updates peak table and trend plot
- If multiple frames arrived since the last tick, only the newest is rendered — earlier frames remain in cache for browsing
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

### Cache settings

| Property | Description |
| --- | --- |
| `cache_frames` | Ring buffer depth in frames (default 32); configurable via GUI Acquisition tab |

Helper methods: `voltage_range_for(ch)`, `coupling_for(ch)`, `name_for(ch)`, `target_unit_for(ch)`, `amplitude_mode_for(ch)`, `copy()`.

---

## VibeSample and ChannelResult

### VibeSample

`VibeSample` (`sample.py`) holds one block of time-domain samples for a single channel.

```python
sample.data                          # numpy.ndarray float64, shape (N,), raw mV samples
sample.samplerate                    # int — Hz
sample.unit                          # str — 'mV' (raw hardware unit)
sample.timestamp                     # str — ISO format timestamp
sample.rel_time                      # float — seconds since stream start
sample.status                        # str — 'OKAY', 'OVERFLOW', etc.
sample.overall_ampl_by_integration_order  # ndarray (5,) — broadband RMS for orders -2..+2

# Cached on first call; re-computed when Welch config changes:
sample.psd_mv                        # numpy.ndarray — Welch PSD (mV RMS)
sample.freq_hz                       # numpy.ndarray — frequency axis (Hz)
```

HDF5 save/load is handled by `DataCollector.save_data()` and `DataCollector.load_data()`, not by VibeSample directly.

### ChannelResult

`ChannelResult` is a frozen dataclass returned by `DataCollector.process_sample(ch, sample)`. It is the canonical display-ready result for one channel at one instant.

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

Config is persisted in the OS-specific config directory:
- **Linux/macOS:** `$XDG_CONFIG_HOME/vibechecker/` (default: `~/.config/vibechecker/`)
- **Windows:** `%APPDATA%\vibechecker\`

### Per-device configuration

Device-specific settings are stored in `devices/{sanitized_serial}.yaml` when the device is disconnected or via explicit GUI action:

```yaml
channels:
  0:
    enabled: true
    sensor_id: <uuid>           # reference to global sensor library
    voltage_range: 7            # PS4000A range index
    coupling: AC
acquisition:
  maxfreq: 2000.0               # Hz
  binsize: 2.0                  # Hz
  cache_frames: 32              # configurable ring buffer depth
  fft_window: hann
  welch_overlap: 0.5
  highpass_enabled: true
  highpass_fc: 10.0             # Hz
  lowpass_enabled: false
  lowpass_fc: 1000.0            # Hz
  trend_max_points: 500
siggen:                          # optional signal generator config
  enabled: true
  wave_type: PS4000A_SINE
  freq_hz: 100.0
  pktopk_uv: 500000
  offset_uv: 0
```

Unknown device? Falls back to `devices/default.yaml` template, then built-in defaults. When reconnecting, the device's saved config is restored.

### Global sensor library

User-defined IEPE sensors are stored in `scope_sensors.yaml` as a list of `ScopeSensor` dicts:

```yaml
- id: <uuid>
  name: PCB 352C33 Ch1
  sensitivity_mv_per_eu: 10.2   # mV/g, mV/(mm/s), etc.
  engineering_units: g          # acceleration modality
  target_unit: in/s             # display unit override (optional)
```

Managed via `ScopeSensorRegistry` — provides CRUD operations and per-channel assignment persistence.

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

