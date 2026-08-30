# Rev80

A Python desktop application for capturing, analyzing, and recording vibration data from industrial rotating equipment. Designed for predictive maintenance workflows using IEPE accelerometers and voltage-output sensors connected via USB oscilloscopes (PicoScope 4000A series) or USB audio interfaces (Digiducer legacy).

> **Rev80** by Rev Engineering, LLC — solves 80% of your vibration needs for 10% of the cost.

Looking to build, package, or contribute to Rev80? See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

---

## Table of Contents

- [Features](#features)
- [CLI Reference](#cli-reference)
- [Installing on Windows](#installing-on-windows)
- [Installing from Source (any OS)](#installing-from-source-any-os)
- [Configuration and Persistence](#configuration-and-persistence)
- [Monitor Mode](#monitor-mode)
- [Signal Generator](#signal-generator)
- [Simulated Sensor](#simulated-sensor)
- [Architecture](#architecture)
- [Module Reference](#module-reference)
- [Data Pipeline](#data-pipeline)
- [AcquisitionSettings](#acquisitionsettings)
- [VibeSample and ChannelResult](#vibesample-and-channelresult)
- [ScopeSensor](#scopesensor)
- [Data Storage](#data-storage)
- [PicoScope Integration](#picoscope-integration)

---

## Features

- Real-time time-domain and frequency-domain plots across multiple simultaneous channels
- Welch-based power spectral density with configurable window (Hann, Blackman-Harris, Flattop, Hamming, etc.)
- Velocity and displacement spectra derived from acceleration via frequency-domain integration
- Single-shot and continuous streaming capture modes
- Per-channel zero-phase 4th-order Butterworth highpass filter
- Mandatory hardware-level anti-aliasing (oversample + zero-phase decimate) on every capture, plus a streaming-rate watchdog that flags degraded USB throughput
- Configurable IEPE sensor library: sensitivity (mV/EU), modality, engineering units
- PicoScope 4000A built-in signal generator for excitation testing
- HDF5 file save/load for post-processing and archiving (v4 format)
- Configurable frame cache depth (default 32 frames) with backward browse
- Trend plot: overall vibration amplitude over time per channel
- Simulated sensor (bearing-defect signal generator) for offline development and CI testing
- Configurable amplitude modes: RMS, 0-P, P-P
- Configurable units: acceleration (g, mm/s², in/s²), velocity (mm/s, in/s, mil/s), displacement (mm, in, mil)
- **Monitor Mode** — interval datalogger: captures frames at a configurable interval (5 s – 2 days) into a single session HDF5; anomaly-triggered burst capture with three independent detection modes (EWMA-RMS broadband, EWMA-Spectral frequency-shape, and fixed-level upper/lower thresholds); configurable post-burst cooldown gate; manual "Record Burst" button
- **Session browser** — load and browse historical monitor sessions; burst events displayed as vertical markers on the vibration trend

---

## CLI Reference

`rev80` is the single entry point for everything — GUI launch, the headless
datalogger (as a subcommand), and quick info commands that need neither the
GUI nor hardware. `rev80-headless` remains as a standalone shortcut for
`rev80 headless` (handy for systemd units / scripts that only need the
datalogger). Run `rev80 --help` or `rev80 headless --help` for the full,
always-current option list.

```bash
rev80 --version         # print version and exit
rev80 --install-desktop-entry    # Linux only — see Desktop integration below
rev80 --uninstall-desktop-entry
```

### GUI mode

```bash
rev80                                                # launch GUI
rev80 --from-file path/to/file.h5                   # load measurement on startup
rev80 --from-file path/to/session_dir/              # load monitor session on startup
rev80 --debug                                        # verbose logging
```

`--from-file` accepts a v4 single-measurement `.h5` file or a v5 monitor session directory (containing `session.h5`). The GUI opens, displays the data immediately, and the session browser and file browser remain fully functional.

### Info commands

Return immediately — no GUI, no hardware, no heavy imports. Available both
at the top level of `rev80` and under `rev80 headless` / `rev80-headless`:

```bash
rev80 --init-config      # seed config files and exit
rev80 --list-devices     # enumerate connected PicoScopes and exit
rev80 --list-sensors     # show the IEPE sensor library and exit
rev80 --edit-config      # open acquisition.yaml in $EDITOR and exit
```

| Command | Description |
|---|---|
| `--init-config` | Create default config files and list them |
| `--list-devices` | Enumerate connected PicoScope devices |
| `--list-sensors` | Show the IEPE sensor library |
| `--edit-config` | Open `acquisition.yaml` in `$EDITOR` |

### Headless mode

```bash
rev80 headless [options]
# or equivalently:
rev80-headless [options]
```

**Before first use on a new machine, seed the config directory:**

```bash
rev80 headless --init-config
```

This writes `acquisition.yaml` and `devices/picoscope-defaults.yaml` to `~/.config/rev80/` so you can edit them before connecting hardware.

The [info commands](#info-commands) above also work under `rev80 headless` / `rev80-headless`, in addition to the following headless-only options.

**Session options:**

| Option | Default | Description |
|---|---|---|
| `--interval SECS` | 600 | Capture interval in seconds |
| `--pre-buffer SECS` | 30 | Pre-burst buffer duration |
| `--burst-duration SECS` | 120 | Burst capture duration |
| `--output DIR` | `~/Documents/Rev80/data/monitor/` | Output root directory |
| `--no-compress` | — | Disable gzip compression |
| `--start-now` | — | Skip the pre-start confirmation prompt |

**Acquisition options:**

| Option | Default | Description |
|---|---|---|
| `--device SERIAL` | auto-detect | PicoScope serial number, or `sim` |
| `--channels N [N ...]` | from device config | Channel indices to enable (persisted to device config) |
| `--maxfreq HZ` | from `acquisition.yaml` | Max analysis frequency override |
| `--binsize HZ` | from `acquisition.yaml` | Frequency resolution override |
| `--debug` | — | Verbose logging to stderr |

**First-run device config:** On the first run with a new PicoScope, headless generates
`devices/picoscope-<model>-<SN>.yaml` from the defaults template before the confirmation
prompt. Edit it to set channel coupling, voltage range, and sensor assignments, then restart.

**Channel persistence:** `--channels 0 1` updates the `enabled` flag in the saved device
config so the setting is sticky across restarts — you do not need to repeat the flag.

**Confirmation gate:** Before connecting, headless prints a session summary (device, channels,
sample rate, monitor interval, anomaly config, config file paths) and waits for Enter. Use
`--start-now` to bypass this for unattended use (systemd, cron, scripts).

**Example workflows:**

```bash
# First time on a new Pi — seed config, connect scope, generate device config
rev80-headless --init-config
rev80-headless --list-devices
rev80-headless                          # generates device config, shows summary

# Edit settings, then start unattended
nano ~/.config/rev80/acquisition.yaml
nano ~/.config/rev80/devices/picoscope-4424A-JY123.yaml
rev80-headless --start-now

# One-liner with explicit overrides (changes persisted to device config)
rev80-headless --channels 0 1 --interval 300 --start-now

# Simulated sensor — offline testing, no hardware
rev80-headless --device sim --interval 10 --start-now
```

Writes a v5 `session.h5` file loadable by the GUI session browser or `--from-file`. Clean shutdown on `Ctrl+C` or `SIGTERM` (suitable for systemd `Restart=on-failure`).

---

## Installing on Windows

1. Install **PicoSDK 11.1.418** (or PicoScope 7 for Windows) from [picotech.com/downloads](https://www.picotech.com/downloads). **Restart your computer** after installation so Windows registers the USB kernel driver.
2. Run **`Rev80Setup-<version>.exe`** and follow the installer. It creates a Start Menu shortcut and an uninstaller. No admin rights required.

> **SmartScreen warning:** the installer is currently unsigned. Click *More info → Run anyway* to proceed.

### Runtime file locations

| Purpose | Location |
| --- | --- |
| Measurement data (`.h5`) | `~/Documents/Rev80/data/` |
| Log files | `~/Documents/Rev80/logs/` |
| Config / sensor library | `%APPDATA%\rev80\` |

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
   ```

3. Run the app:

   ```bash
   # GUI (default)
   python -m rev80

   # GUI — open directly on a saved measurement or monitor session
   python -m rev80 --from-file ~/Documents/Rev80/data/my_run.h5
   python -m rev80 --from-file ~/Documents/Rev80/data/monitor/2026-06-02-130000/

   # Headless interval datalogger (no display required)
   # `rev80 headless ...` and `rev80-headless ...` are equivalent
   rev80-headless --init-config              # seed config files first
   rev80-headless                            # auto-detect scope, show summary
   rev80-headless --device sim --interval 10 --start-now  # offline test

   # With debug logging to console
   python -m rev80 --debug
   ```

**Runtime dependencies:** `numpy`, `scipy`, `dearpygui==2.0.0`, `h5py`, `pyyaml`, `plyer`, `picosdk`

**Headless (no display) usage:**

```bash
# Seed config on a fresh install
rev80-headless --init-config

# Auto-detect PicoScope — shows summary, waits for Enter
rev80-headless

# Fully explicit, skip prompt (suitable for scripts/systemd)
rev80-headless \
  --interval 300 \
  --pre-buffer 30 \
  --burst-duration 120 \
  --output /mnt/nas/vibration \
  --channels 0 1 \
  --maxfreq 1000 \
  --binsize 1 \
  --start-now

# Simulated sensor (no hardware)
rev80-headless --device sim --interval 10 --start-now
```

Sessions written by the headless mode are identical v5 HDF5 files and can be loaded in the GUI:

```bash
# Open GUI on a specific session directory
python -m rev80 --from-file /mnt/nas/vibration/2026-06-02-130000/

# Or point at the session.h5 directly
python -m rev80 --from-file /mnt/nas/vibration/2026-06-02-130000/session.h5

# Or a regular single-measurement save
python -m rev80 --from-file ~/Documents/Rev80/data/my_measurement.h5
```

The `picosdk` package requires the PicoScope 4000A driver (`ps4000a.dll` / `libps4000a.so`) to be present on the system for hardware use. The app will start without it and show a "driver not found" notice in the device dialog — the simulated sensor is still available.

### Desktop integration (Linux)

For a normal desktop install (not a dev checkout), use a **user-scheme pip
install** — this places the `rev80` / `rev80-headless` console scripts in
`~/.local/bin`, no venv or root required:

```bash
# Install the PicoScope driver (one-time, needs sudo — see drivers/)
sudo ./drivers/install-picoscope4000a-driver.sh

# Install rev80 itself into ~/.local/bin
pip install --user ".[gui]"

# Add a Rev80 entry to your application menu + an icon
rev80 --install-desktop-entry

# Remove it again
rev80 --uninstall-desktop-entry
```

`--install-desktop-entry` writes `~/.local/share/applications/rev80.desktop`
and a set of icon PNGs under `~/.local/share/icons/hicolor/*/apps/rev80.png`
(a fixed-size raster set, not the scalable SVG — Qt/KDE's SVG renderer
doesn't render the source icon correctly, so this sidesteps it entirely),
pointing `Exec=` at the exact `rev80` script that ran the install (works the
same way from a venv). If `~/.local/bin` isn't already on your `PATH`, the
command prints the line to add to `~/.bashrc` / `~/.profile` — most desktop
distros add it by default, so this is usually a no-op. This is Linux-only;
Windows gets a Start Menu shortcut from the [Inno Setup installer](CONTRIBUTING.md#building-the-windows-installer) instead.

---

## Configuration and Persistence

Config lives in the OS-specific config directory:
- **Linux/macOS:** `$XDG_CONFIG_HOME/rev80/` (default: `~/.config/rev80/`)
- **Windows:** `%APPDATA%\rev80\`

Run `rev80 --init-config` (or `rev80-headless --init-config`) to create the
directory and seed all default files. The layout is:

```
~/.config/rev80/
  acquisition.yaml                       # acquisition + monitor settings (instance-wide)
  scope_sensors.yaml                     # IEPE sensor library (shared across all devices)
  devices/
    picoscope-defaults.yaml              # channel template applied to new devices
    picoscope-4424A-JY123.yaml           # per-device channel + siggen config
```

### `acquisition.yaml` — instance-wide settings

Acquisition and monitor settings are shared across all scopes on this machine. Edit this
file to change capture intervals, anomaly thresholds, filter settings, etc.

```yaml
acquisition:
  maxfreq: 1000.0           # Hz — drives sample rate (samplerate = nextpow2(2.56 × maxfreq))
  binsize: 1.0              # Hz — drives FFT block size
  fft_window: hann
  welch_overlap: 0.5
  highpass_enabled: true
  highpass_fc: 10.0         # Hz
  trend_max_points: 5000
  cache_frames: 15

monitor:
  interval_s: 600           # seconds between interval captures
  pre_burst_s: 30           # seconds of pre-trigger data saved with each burst
  burst_duration_s: 120     # seconds of post-trigger burst capture
  max_burst_s: 600          # maximum burst length even if anomaly keeps retriggering
  output_dir: null          # null → ~/Documents/Rev80/data/monitor/
  compression: gzip
  compression_level: 4
  anomaly:
    enabled: true
    hook_type: rms          # rms | spectral | both
    warmup: 10              # frames before EWMA detection activates
    rms_pct: 10.0           # % deviation from EWMA baseline to trigger
    rms_s: 3.0               # seconds signal must stay above threshold before burst fires
    rms_alpha: 0.97          # EWMA smoothing (higher → slower baseline adaptation)
    spec_pct: 50.0           # % mean per-bin deviation from EWMA baseline to trigger
    spec_n: 10                # consecutive frames required for spectral trigger
    spec_alpha: 0.995         # very slow adaptation — spectral baseline changes slowly
    spec_fmin: null           # null = full spectrum; set Hz to restrict band
    spec_fmax: null
    fixed_upper_enabled: false   # burst when overall amplitude rises above this level
    fixed_upper_value: 1.0
    fixed_upper_unit: in/s       # any unit in UNIT_TO_SI; converted automatically
    fixed_lower_enabled: false   # burst when overall amplitude drops below this level
    fixed_lower_value: 0.05
    fixed_lower_unit: in/s
    cooldown_enabled: false      # block re-triggers for this long after a burst fires
    cooldown_s: 300.0
```

### `devices/picoscope-defaults.yaml` — channel template

Applied to every channel when a new device is seen for the first time. Edit this before
connecting a new scope to set your preferred defaults site-wide:

```yaml
channel:
  enabled: false            # only channel 0 is enabled on new devices
  sensor_id: null
  voltage_range: 6          # PS4000A range index (6 = ±1 V)
  coupling: AC
  channel_name: null        # null → defaults to 'Ch A', 'Ch B', …
  target_unit: null         # null → use sensor engineering units
  amplitude_mode: 0-P

siggen:
  enabled: false
  wave_type: PS4000A_SINE
  freq_hz: 1000.0
  pktopk_uv: 1000000        # 1 V pk-pk
  offset_uv: 0
```

### `devices/picoscope-<model>-<SN>.yaml` — per-device channel config

Channel coupling, voltage range, sensor assignments, and signal generator settings for a
specific scope. Generated automatically on first connection; edit to customise each channel.

```yaml
channels:
  0:
    enabled: true
    sensor_id: <uuid>       # from scope_sensors.yaml
    voltage_range: 6        # ±1 V
    coupling: AC
    channel_name: Motor NDE
    target_unit: in/s
    amplitude_mode: 0-P
  1:
    enabled: false
    sensor_id: null
    voltage_range: 6
    coupling: AC
    channel_name: null
    target_unit: null
    amplitude_mode: 0-P
siggen:
  enabled: false
  wave_type: PS4000A_SINE
  freq_hz: 1000.0
  pktopk_uv: 1000000
  offset_uv: 0
```

### `scope_sensors.yaml` — global IEPE sensor library

User-defined IEPE sensors shared across all devices. Add entries here to make sensors
available for assignment in the GUI Channel Config panel or headless config:

```yaml
- id: <uuid>
  name: PCB 352C33 Ch1
  sensitivity: 10.2   # mV per engineering unit
  engineering_units: g
  notes: ''
```

Managed via `ScopeSensorRegistry` — provides CRUD operations. When a sensor is assigned to
a channel, `DataCollector` divides incoming mV by `sensitivity` to produce engineering units.

### Logging

Logging is configured via `src/rev80/logging.yaml`. In development, log files are written
to `log/`. In a frozen Windows build, logs go to `~/Documents/Rev80/logs/`.

---

## Monitor Mode

Monitor Mode turns Rev80 into a continuous interval datalogger with automatic event capture.

### Interval recording

When monitoring is active, the controller records a frame at the configured interval into
`/monitor/{N}/` in `session.h5`. Interval captures continue regardless of whether a burst is
in progress.

### Burst capture

Any trigger source — automatic anomaly detection or the manual **Record Burst** button —
causes the controller to:

1. Snapshot `pre_buffer_s` of raw frames from the ring cache and prepend them to the burst as pre-trigger data.
2. Capture frames at full rate for `burst_duration_s` seconds, writing to `/burst/{id}/`.
3. Tag the t=0 frame (anomaly onset, not detection time) in `burst.attrs` as `trigger_timestamp` / `trigger_rel_time`.
4. Start the cooldown gate to block further automatic triggers for `cooldown_s` seconds.

### Anomaly detection hooks

Three hook types can be used independently or combined (configured by the "Hook: RMS /
Spectral / Both" selector):

#### Broadband EWMA (RMS)

Maintains a per-channel EWMA baseline of the overall broadband amplitude. Triggers when:

```
|current − baseline| / baseline  >  rms_pct / 100
```

…for `rms_s` seconds of sustained deviation. The baseline adapts continuously during normal operation and during burst playback. A warmup period (`warmup` frames) must elapse before triggering is enabled.

| Parameter | Default | Description |
|---|---|---|
| `rms_pct` | 10.0 | % deviation from EWMA baseline |
| `rms_s` | 3.0 | Seconds signal must stay above threshold (0 = first frame) |
| `rms_alpha` | 0.97 | EWMA smoothing factor (higher = slower baseline) |
| `warmup` | 10 | Frames to collect before triggers are enabled |

#### Frequency-shape EWMA (Spectral)

Compares the live PSD against a per-bin EWMA baseline. Triggers when the mean spectral deviation across the monitored frequency band exceeds `spec_pct` for `spec_n` consecutive frames. Useful for detecting new harmonics or bearing-tone shifts that don't change overall amplitude significantly.

| Parameter | Default | Description |
|---|---|---|
| `spec_pct` | 50.0 | % mean per-bin deviation to trigger |
| `spec_n` | 10 | Consecutive frames required |
| `spec_fmin` / `spec_fmax` | null | Restrict band (null = full spectrum) |

Use **Reset Baseline** (monitor card button) to reseed the EWMA from the current frame after a process change, speed change, or restart.

#### Absolute level trigger (Fixed)

Fires immediately (no warmup, no EWMA) when the overall amplitude crosses a fixed level. Accepts any supported unit and converts automatically — a threshold in `in/s` works correctly against a channel reporting `mm/s`.

Upper and lower limits are independent. A channel with no sensor/EU assigned (raw `mV`) logs a one-time warning and is silently skipped.

| Parameter | Description |
|---|---|
| `fixed_upper_enabled` / `fixed_upper_value` / `fixed_upper_unit` | Trigger when amplitude rises above this level |
| `fixed_lower_enabled` / `fixed_lower_value` / `fixed_lower_unit` | Trigger when amplitude falls below this level |

#### Cooldown gate

After any burst fires (automatic or manual), the controller optionally blocks further automatic triggers for `cooldown_s` seconds. Interval captures are unaffected. Use this to prevent a sustained fault from generating many overlapping burst files.

---

## Signal Generator

The PicoScope 4000A has a built-in arbitrary waveform generator (AWG) on its AUX output. Rev80 exposes this through the **Generate** config tab.

| Setting | Description |
| --- | --- |
| Enabled | Enable/disable AWG output |
| Waveform | Sine, Square, Triangle, DC voltage, Ramp Up/Down |
| Frequency (Hz) | Output frequency |
| Amplitude (mV pk-pk) | Peak-to-peak voltage |
| Offset (mV) | DC offset |

**Timing:** The signal generator runs **continuously** from stream start to stream stop — it is programmed once when the stream starts, free-running, with no per-block triggering. The AWG and the ADC acquisition run independently and simultaneously.

Signal generator settings are persisted per-device (see [Configuration and Persistence](#configuration-and-persistence)) and restored automatically when the same device reconnects.

---

## Simulated Sensor

`VibeSensor.simulated()` returns a `VibeSensor` with `is_simulation=True`. When connected, it starts a `SimulatedSensor` daemon thread that generates synthetic bearing-defect vibration data at the configured samplerate and blocksize. Pass `--device sim` (headless) or select the simulated sensor in the GUI's device dialog — no PicoScope hardware required.

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

## Architecture

The pipeline is strictly layered. The hardware thread and the GUI render loop are decoupled via a `threading.Event` — the collector never imports or calls into DPG. All DSP (Welch FFT, filtering, integration) lives in `collector.py`; `gui.py` is a pure presentation layer that consumes pre-computed `ChannelResult` objects.

```text
  Hardware thread                           Main (GUI) thread
  ─────────────────                         ─────────────────────────────────

┌────────────────────────────┐
│  PicoScopeStream           │
│  OR  SimulatedSensor       │
│  → polls hardware          │
│  → ADC → mV → callback     │
└─────────────┬──────────────┘
              │ dict: {status, rel_time,
              │  timestamp, channels, data}
              ▼
┌────────────────────────────┐
│  DataCollector             │
│  receive_data():           │
│  → mV → EU (ScopeSensor)  │
│  → Butterworth HP + LP    │
│  → VibeSample per channel  │
│  → frame_cache.append()   │
│  → new_frame_event.set()  │─ ─ ─ ─ ─ ─ ─▶┌──────────────────────────────┐
└────────────────────────────┘               │  GUI render loop              │
                                             │  _poll_new_frames():          │
                                             │    if event set:              │
                                             │      process_samples()   ←DSP │
                                             │        Welch PSD              │
                                             │        integration (mV→EU)    │
                                             │        peak detection         │
                                             │      → ChannelResult[]        │
                                             │      _display_frame()         │
                                             │        update DPG plots       │
                                             │      monitor.on_results()─────┼──▶┌────────────────────┐
                                             └─────────────┬────────────────┘   │ MonitorController  │
                                                           │                    │ IntervalGate       │
                                                           │ (on save)          │ MonitorWriterThread│
                                                           ▼                    │ → session.h5       │
                                             ┌────────────────────────────┐    └────────────────────┘
                                             │  HDF5 files in data_dir()  │
                                             │  save_data() / load_data() │
                                             │  monitor/{id}/session.h5   │
                                             └────────────────────────────┘
```

**Decoupling properties:**
- `collector.py`, `monitor/`, `sample.py`, `picoscope.py` — zero DPG imports. Any event loop can drive them.
- `new_frame_event` is a `threading.Event` — a stdlib primitive with no GUI dependency.
- `MonitorWriterThread` runs as a daemon thread independent of both the hardware thread and GUI.
- A headless process can replace the GUI by polling `new_frame_event`, calling `process_samples()`, and passing results to `MonitorController` — approximately 50 lines.

When the GUI is slower than the hardware data rate it skips to the latest frame — earlier frames remain in the ring cache (default 32 frames) for browsing. The hardware thread is never blocked by rendering.

---

## Module Reference

| Module | Responsibility |
| --- | --- |
| `__main__.py` | `rev80` CLI entry point — top-level info commands, `--version`, `headless` subcommand dispatch, GUI launch (logging setup, `GUI` instantiation, main loop, cleanup) |
| `desktop.py` | Linux desktop integration — `install()`/`uninstall()` write/remove `~/.local/share/applications/rev80.desktop` + icon, driven by `rev80 --install-desktop-entry` / `--uninstall-desktop-entry` |
| `_paths.py` | Runtime-safe resource/data/log directory resolution — editable checkout, non-editable pip install, and frozen (PyInstaller) builds all resolve correctly; see [Configuration and Persistence](#configuration-and-persistence) |
| `logger.py` | YAML-configured logging (`logging.yaml`); writes to `log/`; global exception hook |
| `util.py` | Constants (`MAXFREQ_PRESETS`, `BINSIZE_PRESETS`, `UNITS`, `AMPLITUDE_MODES`, `MONITOR_INTERVAL_PRESETS`), unit taxonomy and SI conversion, integration order helpers, `UI_Elements` DPG tag registry |
| `icons.py` | CommitMono Nerd Font (Codicons) registry; `load()` registers font with DPG; `IC` dict maps icon names to `\uXXXX` codepoints |
| `sensor.py` | `VibeSensor` dataclass — device metadata; `find()` enumerates hardware PicoScopes only; `simulated()` returns a test sensor; `connect()` returns the appropriate stream |
| `picoscope.py` | `FindPicoScope()` — enumerates PS4000A units; `PicoScopeStream` — polling thread, ADC→mV, overflow detection, anti-alias oversample/decimate (`antialias_decimate()`), streaming-rate degradation watchdog, silence-watchdog recovery, signal generator setup |
| `scope_sensor.py` | `ScopeSensor` dataclass — IEPE sensor metadata: name, sensitivity (mV/EU), engineering units, amplitude mode, UUID |
| `scope_sensor_registry.py` | `ScopeSensorRegistry` — YAML-backed CRUD for user sensor library and per-channel assignments |
| `sample.py` | `AcquisitionSettings` — spectrum, filter, and cache config with derived properties; `VibeSample` — single-channel time-domain block; `ChannelResult` — frozen display-ready result from `process_sample()` |
| `config.py` | OS-aware config directory; per-device YAML persistence (channels, acquisition settings, monitor defaults); atomic writes; fallback to built-in defaults |
| `collector.py` | `DataCollector` — multi-channel acquisition state machine: stream lifecycle, per-channel zero-phase Butterworth highpass filtering, mV→EU conversion, frame ring cache, `new_frame_event` signal, DSP via `process_sample()` / `process_samples()`, trend accumulation, HDF5 save/load, monitor session loaders |
| `simulation.py` | `SimulatedSensor` (daemon thread) + signal generators: `GenerateTone`, `GenerateNoise`, `GenerateBearingVibration_SpectralMethod`, `GenerateBearingVibration_TemporalMethod` |
| `gui.py` | `GUI` class — dearpygui three-column layout with manual render loop (`_poll_new_frames`), all config dialogs, spectrum/time/trend plots, file I/O, monitor card, session browser |
| `monitor/__init__.py` | Re-exports: `MonitorController`, `MonitorSession` |
| `monitor/session.py` | `MonitorSession` frozen dataclass — session parameters, config snapshots, and cooldown settings |
| `monitor/gate.py` | `IntervalGate` — snap-to-grid capture scheduler; burst mode entry/exit; caller-supplied time (unit-testable) |
| `monitor/anomaly.py` | `AnomalyHook` Protocol; `NullAnomalyHook`; `RmsThresholdHook`; `SpectralThresholdHook`; `FixedThresholdHook`; `CompositeAnomalyHook`; `AnomalyEvent` dataclass |
| `monitor/writer.py` | `MonitorWriterThread` — daemon thread; appends interval frames to `/monitor/` and burst frames to `/burst/` in `session.h5`; disk-space guard |
| `monitor/controller.py` | `MonitorController` — owns gate, writer, anomaly hook; anomaly hook supplied at `start()` and active for the full session; `trigger_burst()` for manual burst |

---

## Data Pipeline

### 1. Acquisition — `PicoScopeStream` (`picoscope.py`)

`PicoScopeStream` is a background polling thread that wraps `ps4000aRunStreaming`. The ADC is always driven faster than the requested `maxfreq` — at an oversampling ratio (up to 4×, capped by a measured safe continuous-streaming ceiling for this hardware) — so a zero-phase digital anti-alias filter can reject content above the target Nyquist *before* decimating down to the configured rate; this is mandatory and not user-configurable. On each poll:

1. Converts ADC counts → mV via `adc2mV()` for all enabled channels
2. Detects ADC overflow per channel via the overflow bitmask
3. Accumulates mV samples in a raw, oversampled `(blocksize × effective_osr × N_channels)` buffer
4. Once a full raw block has accumulated, anti-alias filters and decimates it down to `blocksize` samples via `antialias_decimate()`, then fires the registered callback with:

```python
{
    'status':        str,           # 'OKAY', 'OVERFLOW', etc.
    'overflow_mask': int,           # bitmask, one bit per channel
    'degraded':      bool,          # True if sustained USB streaming throughput has fallen below the rate watchdog's threshold
    'rel_time':      float,         # seconds since stream start
    'timestamp':     datetime,
    'unit':          ['mV', ...],   # one entry per channel
    'channels':      [0, 1, ...],   # enabled channel indices
    'data':          ndarray,       # shape (blocksize, N_channels), mV
}
```

A watchdog thread monitors for >5 s silence and attempts up to 3 reconnect cycles automatically. A second, independent watchdog monitors *sustained* USB streaming throughput every 2 s — this catches a different failure mode where the driver silently delivers only a fraction of the requested rate (`status='OKAY'`, no overflow, callbacks keep firing) that the silence watchdog can't see. It only sets `degraded=True` on the stream and logs a warning; it never triggers reconnect, since a bandwidth ceiling isn't fixed by reopening the device.

**Device discovery** — `VibeSensor.find()` calls `FindPicoScope()` and returns hardware-only results. `SimulatedSensor` is excluded; use `VibeSensor.simulated()` for offline development and testing.

### 2. Preprocessing — `DataCollector` (`collector.py`)

`DataCollector.receive_data(frame)` runs in the hardware callback thread:

1. For each enabled channel, extracts the channel column from `frame['data']`
2. Converts mV → engineering units using `ScopeSensor.sensitivity` (if a sensor is assigned)
3. Optionally applies a **4th-order Butterworth highpass** filter (default 10 Hz cutoff), zero-phase (`sosfiltfilt`) when the block is long enough, falling back to causal (`sosfilt`) for very short blocks
4. Wraps each channel's data in a `VibeSample` (anti-aliasing is no longer applied here — it happens upstream in `PicoScopeStream`, before the ADC's own Nyquist limit can fold high-frequency content into the passband)
5. Assembles a frame dict `{ch: VibeSample, 'overflow': mask}` and appends it to the frame ring cache (configurable depth via `AcquisitionSettings.cache_frames`, default 32)
6. Sets `new_frame_event` to signal the GUI render loop

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
| `samplerate` | **Derived** — minimum samplerate ≥ 2.56 × maxfreq (the 28% margin above 2× Nyquist gives the mandatory anti-alias filter a real transition band — same ratio commercial FFT vibration analyzers use) |
| `blocksize` | **Derived** — next power of 2 satisfying samplerate / blocksize ≤ binsize |
| `acquisition_period` | **Derived** — blocksize / samplerate (seconds) |
| `n_fft_bins` | **Derived** — number of Welch output bins |
| `fft_window` | Welch window function: `'hann'` (default), `'blackmanharris'`, `'flattop'`, `'hamming'`, `'boxcar'`, `'bartlett'` |
| `welch_overlap` | Welch segment overlap fraction (default 0.5) |

### Filter settings

| Property | Description |
| --- | --- |
| `highpass_enabled` | Enable 4th-order Butterworth highpass filter (zero-phase) |
| `highpass_fc` | Highpass cutoff frequency (Hz) |

Anti-aliasing is no longer a user-configurable lowpass — it's a mandatory
filter applied at capture time in `PicoScopeStream`, automatically derived
from `maxfreq` (see `samplerate` above). There's no separate cutoff to set.

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
sensor.id                 # str — UUID, used as persistent key
sensor.notes              # str — freeform
```

Sensors are managed through `ScopeSensorRegistry` and assigned to channels via the GUI Channel Config panel. When a sensor is assigned, `DataCollector` divides incoming mV data by `sensitivity` to produce engineering units before creating `VibeSample` objects.

The display/integration target unit and amplitude mode (`RMS`, `0-P`, `P-P`)
are **per-channel** settings (`AcquisitionSettings.channel_target_units` /
`channel_amplitude_modes`), not part of the sensor definition — the same
sensor can be wired to different channels with different targets.

---

## Data Storage

### Manual saves (v4 format)

Single-measurement saves written by **File → Save** or `DataCollector.save_data()`, into `~/Documents/Rev80/data/` by default (`_paths.data_dir()`):

```
~/Documents/Rev80/data/YYYY-MM-DD-HHMMSS.h5
  /metadata/
    .attrs              version=4, notes
    acquisition/        AcquisitionSettings fields
    scope_sensors/      sensor library snapshot
    channels/{ch}/      per-channel config
  /frames/{i}/
    .attrs              timestamp, rel_time, samplerate, status
    {ch}/data           (blocksize,) float64 mV, gzip-compressed
  /trend/{ch}/
    rel_times, orders   (M,5) integration orders matrix
```

```python
collector.save_data(Path("~/Documents/Rev80/data/my_run.h5").expanduser())
collector.load_data(Path("~/Documents/Rev80/data/my_run.h5").expanduser())
```

### Monitor sessions (v5 format)

Monitor Mode writes one `session.h5` per session, appending frames as the interval gate fires, under `~/Documents/Rev80/data/monitor/` by default (`--output` overrides this in headless mode; see [CLI Reference](#cli-reference)):

```
~/Documents/Rev80/data/monitor/{session_id}/session.h5
  /metadata/
    .attrs              file_version=5, session_id, start_time, interval_s
    acquisition/        AcquisitionSettings snapshot at arm time
    scope_sensors/      sensor library at arm time
    channels/{ch}/      per-channel config at arm time
  /monitor/{N}/         one group per interval gate firing (N=0,1,2,…)
    .attrs              timestamp, rel_time, samplerate, status,
                        overall_json, peaks_json
    {ch}/data           (blocksize,) float64 mV, gzip-compressed
  /burst/{burst_id}/    one group per burst event
    .attrs              trigger_type, trigger_timestamp, trigger_rel_time,
                        burst_duration_s, max_overall_json, n_frames,
                        n_pretrigger_frames
    {frame_index}/
      .attrs            timestamp, rel_time, is_pretrigger, overall_json
      {ch}/data
  /burst.attrs          burst_list — JSON array of burst summaries
```

`session_id = "YYYY-MM-DD-HHMMSS"` (UTC). Loaded via the session browser or:

```python
collector.load_monitor_session(session_h5)
collector.load_monitor_burst(session_h5, burst_id)
```

---

## PicoScope Integration

Rev80 targets the **PicoScope 4000A series** as its primary acquisition hardware via the `picosdk` Python bindings.

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

Looking to build, package, or contribute to Rev80? See **[CONTRIBUTING.md](CONTRIBUTING.md)**.
