# Rev80

Rev80 is a desktop application for vibration analysis of industrial rotating
equipment. It captures, analyzes and records vibration from IEPE
accelerometers through a PicoScope 4000A USB oscilloscope. It is for plant
managers and maintenance technicians who need the core analysis toolkit
without a dedicated engineering firm.

You can use Rev80 in two ways:

- **Route and spot checks.** Capture a frame, read the overall and the
  spectrum, and save the measurement.
- **Monitor Mode.** Log frames at an interval for hours or months. Anomaly
  detection records a burst of frames when the vibration changes.

> **Rev80** by Rev Engineering, LLC: 80 % of the benefit of academic
> vibration analysis from a dedicated engineering firm, for a fraction of the
> cost.

To build, package or change Rev80, read **[CONTRIBUTING.md](CONTRIBUTING.md)**.

### What the numbers are, and where they stop being trustworthy

Rev80 is an instrument. Each number on the screen has a unit, a band and
conditions. Read these limits before you act on a number:

- The **overall** is measured over the **declared band** only. Two overalls
  over different bands are different measurements. See
  [Declared band and the high-pass edge](#declared-band-and-the-high-pass-edge).
- A frame with ADC **overflow** (clipping) or a **degraded** USB stream is
  shown with a flag, but it is not trended, averaged or used for alarms. See
  [Frames that are not used](#frames-that-are-not-used).
- Nothing above F_max is shown or measured. Below the high-pass band edge,
  the response falls off. See [F_max, bin size, frame length and lines](#f_max-bin-size-frame-length-and-lines).
- A missing reading shows as `--`, never as `0`. See
  [Missing readings](#missing-readings----not-0).
- Each accuracy figure has a measurement method and conditions. Some were
  measured at an older raw rate or in simulation only. See
  [Accuracy and limits](#accuracy-and-limits).

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [The GUI](#the-gui)
- [Measurement settings](#measurement-settings)
- [Reading the results](#reading-the-results)
- [Tachometer](#tachometer)
- [Envelope analysis](#envelope-analysis)
- [Monitor Mode](#monitor-mode)
- [Headless datalogger](#headless-datalogger)
- [Configuration files](#configuration-files)
- [Command reference](#command-reference)
- [Data files](#data-files)
- [Signal generator](#signal-generator)
- [Simulated sensor](#simulated-sensor)
- [Troubleshooting](#troubleshooting)

---

## Install

### Windows

1. Install **PicoSDK 11.1.0.481** (or PicoScope 7 for Windows) from
   [picotech.com/downloads](https://www.picotech.com/downloads).
2. Restart the computer. The restart registers the USB kernel driver.
3. Download **`Rev80Setup-<version>.exe`** from the
   [Releases page](https://github.com/cascadia-turbo-works/rev80/releases).
4. Run the installer. It needs no administrator rights. It creates a Start
   Menu shortcut and an uninstaller.

> **Caution:** The installer does not contain the PicoScope drivers. Without
> PicoSDK, Rev80 starts and runs the simulated sensor, but it does not find a
> scope. The installer warns you when PicoSDK is missing.

> **Note:** The installer is not signed. Windows SmartScreen shows a warning.
> Click *More info*, then *Run anyway*.

### Linux and macOS (pip)

Rev80 needs Python 3.10 or later.

1. Install **PicoSDK** or **PicoScope 7** for your operating system from
   [picotech.com/downloads](https://www.picotech.com/downloads). On Linux you
   can use `sudo ./drivers/install-picoscope4000a-driver.sh` from the source
   tree.
2. Restart the computer.
3. Get the source. The source is closed; contact Rev Engineering for access.
4. Install Rev80 from the source directory:

   ```bash
   pip install .
   ```

   This installs all runtime dependencies, including `picosdk` from a pinned
   git URL. It installs two commands: `rev80` and `rev80-headless`.

5. Start the GUI:

   ```bash
   rev80
   ```

Rev80 starts without the PicoScope driver. The Device tab then shows
"PicoScope driver not found. Install PicoSDK to connect a device." The
simulated sensor stays available.

macOS support is not verified on hardware.

### Linux desktop entry

Use a user-scheme install for a normal desktop. It needs no virtual
environment and no root access.

1. Install the PicoScope driver (one time, needs `sudo`):

   ```bash
   sudo ./drivers/install-picoscope4000a-driver.sh
   ```

2. Install Rev80 into `~/.local/bin`:

   ```bash
   pip install --user .
   ```

3. Add Rev80 to the application menu:

   ```bash
   rev80 --install-desktop-entry
   ```

The command writes `~/.local/share/applications/rev80.desktop` and a set of
PNG icons under `~/.local/share/icons/hicolor/*/apps/rev80.png`. The `Exec=`
line points at the `rev80` script that ran the command. If `~/.local/bin` is
not on your `PATH`, the command prints the line to add to `~/.bashrc` or
`~/.profile`.

To remove the entry:

```bash
rev80 --uninstall-desktop-entry
```

On Windows, the installer creates the Start Menu shortcut.

### Where Rev80 keeps its files

| Purpose | Windows | Linux and macOS |
|---|---|---|
| Measurements (`.h5`) | `~/Documents/Rev80/data/` | `~/Documents/Rev80/data/` |
| Monitor sessions | `~/Documents/Rev80/data/monitor/` | `~/Documents/Rev80/data/monitor/` |
| Logs: `main.log`, `error.log`, `debug.log`, `faulthandler.log` | `~/Documents/Rev80/logs/` | `~/Documents/Rev80/logs/` |
| Configuration and sensor library | `%APPDATA%\rev80\` | `$XDG_CONFIG_HOME/rev80/` (default `~/.config/rev80/`) |

These paths are the same for the installer, a pip install and a source
checkout. `faulthandler.log` records a hard crash (for example a crash in
the PicoScope driver). It is often the only record of that crash.

---

## Quick start

This procedure uses the simulated sensor, so you can do it without a scope.

1. Start the GUI: `rev80`.
2. In the **Device** card, click **Setup**. The **Device** tab of the
   Configuration dialog lists the detected devices.
3. Click **Connect** beside the device.
4. Click the **Channels** tab. Expand a channel. Set **Coupling**, **Range**,
   **Sensor**, **Unit** and **Amplitude**. Select **Enable**.
5. Click the **Acquisition** tab. Set **Freq. Range** (F_max) and
   **Freq. Resolution** (bin size). Read the derived **Sample Rate**,
   **Spectral Lines** and **Acq. Time**.
6. Click **Close**. Rev80 applies all tabs and saves them.
7. In the **Acquisition** card, click **Stopped** to start the stream. The
   button then shows **Running**.
8. Read the result card for each channel in the right column: **Overall**,
   **Crest** and **Kurt**, and the peak table.
9. Click **Running** to stop the stream.
10. In the **File** card, type a note in **Measurement Notes**. Click
    **Save**.

If you have no sensor in the library, add one first. Click **Sensor** in the
**Channels** card, then **Add**. Type the sensitivity in mV per engineering
unit from the calibration certificate.

---

## The GUI

This section describes the controls. The labels come from the source code
(`src/rev80/gui.py`).

### Main window

The main window has three columns.

**Left column (controls):**

| Card | Controls |
|---|---|
| Device | **Setup** opens the Device tab. A colored square shows **Connected** (green), **File Loaded** (yellow) or **Not Connected** (red). |
| Channels | **Setup** opens the Channels tab. **Sensor** opens the Sensors tab. One line for each enabled channel: name, sensor, unit. The **Gen** line shows the signal generator state. |
| Acquisition | **Setup** opens the Acquisition tab. The large button starts and stops the stream: **Stopped** (red), **Waiting** (yellow), **Running** (green). **Single** captures one frame. **Autoscale** fits all plot axes. **Clear Cache** deletes the frame cache and the trend. **Browse Waveforms** steps through the cached frames when the stream is stopped. **Spectrum Setup** shows F_max, bin size, lines, display rate, frame time, window and high-pass. A red "rate degraded" line shows when the USB stream delivers less than the requested rate. |
| Monitor Mode | **Setup** opens the Monitor tab. **Monitor** starts and stops a recording. **Reset Baseline** restarts the anomaly baseline. **Record Burst** starts a manual burst. The status text shows elapsed time, captures, bursts and the time to the next capture. **Load Session** opens the session browser. |
| File | **Save** writes the frame cache to an `.h5` file. **Load** opens an `.h5` file. **Measurement Notes** is saved in the file. |

**Center column (plots):**

- **Spectrum** tab: the amplitude spectrum from 0 Hz to F_max, with peak
  markers and a 1x marker when a tachometer reads.
- **Envelope** tab: shown only when you enable it in the Acquisition tab. See
  [Envelope analysis](#envelope-analysis).
- **Trend** tab: the overall of each channel against time. The axis label
  shows the unit, the amplitude mode and the declared band. Burst trigger
  times show as vertical lines when you load a session.
- **Time Series** plot (below the tabs): the band-limited waveform in the
  display unit.

When two channels have different units, the plots use a second Y axis. Rev80
supports two units on screen. A third unit shares the second axis, and the
log records a warning.

**Right column (results):**

- **Channel Warnings**: shows "Overvoltage Ch X" when a channel clips.
- **Peak Sig., dB**: how far a line must be above its own local noise floor
  to be a peak. Default 9.5 dB.
- **Max Shown**: the maximum number of peaks in the table and on the plot
  (default 50). It does not change which lines are peaks.
- The peak count ("N peaks", "N peaks, showing M", "no significant peaks")
  and the averaging count ("averaging N of M frames").
- **Frame** card: capture time, block size (samples), sample rate (the
  achieved raw rate, Hz). It also shows burst and session data when you
  browse a session.
- One card for each enabled channel: **Overall**, **Crest** and **Kurt**, the
  1x level when a tachometer reads, and the peak table. A tachometer channel
  card shows the shaft speed, the reading quality, the edge count and the
  duty cycle instead.

### Configuration dialog

The dialog has seven tabs. When you open the dialog, Rev80 stops the stream.
**Close** (or `Esc`) applies all tabs, saves them, reconnects the device
once, and starts the stream again if it was running.

| Tab | Controls |
|---|---|
| Device | Detected devices, **Connect** / **Disconnect**, refresh. |
| Channels | For each channel: **Enable**, **Name**, **Coupling** (AC/DC), **Range** (±10 mV to ±20 V), **Sensor**, **Unit**, **Amplitude** (RMS, 0-P, P-P). A tachometer channel shows read-only. |
| Tachometer | **Channel**, **Polarity**, **Threshold** (adaptive/fixed), **Level (mV)**, **Min ampl. (mV)**, **Rate units**, **Reflector (mm)**, **Pulses/rev**, **Start**/**Stop**, and a live plot of the tach signal. See [Tachometer](#tachometer). |
| Sensors | **Sensor Library** list, **Add**, **Delete**. For the selected sensor: **Name**, **Source EU**, **Sensitivity (mV/eu)**, **Notes**. |
| Acquisition | **Freq. Range**, **Freq. Resolution**, **Highpass** and its **Hz**, **Average spectrum**, **Averages**, **Envelope/Demodulation (bearing analysis)**, **Overall Band** with **min** and **max Hz**, **Cache Frames**, **Welch Overlap %**, **FFT Window**. Read-only: **Sample Rate**, **Spectral Lines**, **Acq. Time**, **Avg. Window**, **Rec. Window**, **Memory**. |
| Generate | Signal generator. See [Signal generator](#signal-generator). |
| Monitor | Interval, pre-trigger, burst, output and anomaly settings. See [Monitor Mode](#monitor-mode). |

Settings with no widget are in the YAML files only. See
[Configuration files](#configuration-files).

### Locks during a recording

While a Monitor Mode recording runs, these controls are disabled: all
**Setup** buttons, **Sensor**, **Load**, **Load Session** and
**Clear Cache**. `Ctrl+O` is refused, and the log records why. Stop the
recording to use them again.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+K` | Start or stop the stream |
| `Ctrl+A` | Autoscale all plots |
| `Ctrl+S` | Save the frame cache |
| `Ctrl+O` | Load a file (refused during a recording) |
| `Ctrl+Q` | Quit |
| `Left` / `Right` | Previous / next frame (stream stopped) |
| `Esc` | Close the open dialog |

> **Caution:** `Ctrl+K` stops the stream during a recording too. A recording
> gets no frames while the stream is stopped.

---

## Measurement settings

### F_max, bin size, frame length and lines

Rev80 uses two sample rates:

- The **raw rate** is fixed at 25600 Hz nominal. On a PicoScope 4824A the
  achieved rate is 25591.81 Hz. Rev80 stores frames at this rate, and the
  envelope analysis uses it. F_max does not change it.
- The **display rate** is exactly 2.56 × F_max. Rev80 decimates each frame to
  this rate for the spectrum.

| F_max | Display rate |
|---|---|
| 200 Hz | 512 Hz |
| 500 Hz | 1280 Hz |
| 1000 Hz | 2560 Hz |
| 2000 Hz | 5120 Hz |
| 5000 Hz | 12800 Hz |
| 10000 Hz | 25600 Hz |

The bin size presets are 0.25, 0.5, 1, 2, 5, 10, 20, 50 and 100 Hz. The
frame time is 1 / bin size: 1 s at 1 Hz, 4 s at 0.25 Hz. The number of
spectral lines is F_max / bin size + 1 (0 Hz to F_max). Example: F_max
1000 Hz and 1 Hz bins give 1001 lines and 1.000 s frames.

The spectrum stops at F_max. The band from F_max to half the display rate is
the transition band of the anti-alias filter. There the filter attenuates
aliases by only 21.8 dB at the frequency that folds to F_max, so Rev80 does
not show it.

The frequency axis uses the achieved rate, not the nominal rate. The F_max
control keeps the round value that you selected.

**Cache Frames** sets how many frames Rev80 keeps for browsing, averaging and
the Monitor Mode pre-trigger buffer. A seeded `acquisition.yaml` sets 15.
Without a value from `acquisition.yaml`, the default is 32. **Rec. Window**
and **Memory** in the Acquisition tab show the time and memory that the cache
holds.

### Units, amplitude modes and integration

Each sensor in the library has a **Source EU** and a **Sensitivity** in mV
per EU. Each channel has a target **Unit** and an **Amplitude** mode.

| Quantity | Units |
|---|---|
| Acceleration | `g`, `mm/s2`, `in/s2`, `mil/s2` |
| Velocity | `mm/s`, `in/s`, `mil/s` |
| Displacement | `mm`, `in`, `mil` |
| Raw | `mV` (no sensor assigned) |

When the target unit is a different quantity from the source EU, Rev80
integrates or differentiates in the frequency domain. Example: `g` to `in/s`
is one integration. `g` to `mil` is two.

The amplitude modes are:

- **RMS**.
- **0-P** = RMS × √2.
- **P-P** = RMS × 2√2.

0-P and P-P are the sine-equivalent values, not the true peak of the
waveform. The default mode is 0-P.

### Declared band and the high-pass edge

The overall is the band amplitude from `band_fmin` to `band_fmax`. This is
the **declared band**. Rev80 stores the band with each measurement.

In the Acquisition tab, **Overall Band** offers:

| Preset | Band |
|---|---|
| Full band (HP - F_max) | The high-pass edge to F_max (default) |
| ISO 20816 (10-1000 Hz) | 10 Hz to 1000 Hz |
| ISO 20816 low speed (2-1000 Hz) | 2 Hz to 1000 Hz |

The two ISO bands are the broadband bands of ISO 20816-3. The zone limits of
that standard apply only to a velocity RMS measured over the band that they
assume. Check ISO 20816-3 for which band applies to your machine. You can
also type **min** and **max Hz**. The band is always clipped to F_max.

**Highpass** (default on, 10 Hz) removes DC and drift. The value is the
**band edge**: the lowest frequency where the response is still in
tolerance. It is not the −3 dB **knee**. Rev80 puts the knee of the
4th-order Butterworth filter at 0.834 × the edge (8.34 Hz for a 10 Hz edge).
The design response at the edge is −0.915 dB (about −10 %). ISO 2954 names
10 Hz as the bottom of the declared band.

> **Caution:** Measured on hardware (CHANGELOG, 2026-08-29), the response at
> 10 Hz was −1.05 dB, about 11.4 % low. That is outside a ±10 % tolerance.
> Measure lines near the band edge with care.

### Spectral averaging

**Average spectrum** averages N frames in the power domain (default off,
N = 8). Averaging reduces the scatter of the noise floor by √N. It does not
lower the noise floor. Use it to see a small line in a rough floor.

- The average uses the N most recent valid frames up to the frame on the
  screen. Overflow and degraded frames are skipped.
- N is limited by **Cache Frames**.
- **Avg. Window** shows N × frame time: the time for which the machine must
  be steady.
- If the speed changes during the window, lines spread across bins.

Crest factor and kurtosis are never averaged.

### Peaks

A line is a peak when it is **Peak Sig., dB** above its own local noise
floor. Rev80 estimates the floor for each bin. A line in a quiet part of the
band and a line in a loud part are judged the same way. The peak count is a
result, not a setting.

- The default is 9.5 dB (2.99 × the local floor in amplitude).
- A lower value finds more lines, and more of them are noise.
- A line more than 40 dB below the largest bin in the band is never a peak.
- The peak value is the amplitude of the maximum bin. Rev80 does not
  interpolate the frequency and does not sum energy over bins.
- The table is sorted by amplitude, largest first.

**FFT Window** (default Hann) changes the amplitude of a line between bins.
Flat-top gives better amplitude for calibration. **Welch Overlap %** has no
effect at present, because each frame is one Welch segment.

---

## Reading the results

### Overall, crest factor and kurtosis

- **Overall**: the band amplitude over the declared band, in the channel unit
  and amplitude mode. The label shows the unit, mode and band, for example
  `Overall, in/s 0-P  10-1000 Hz`.
- **Crest**: peak / RMS of the displayed waveform. A pure sine gives 1.41.
  Random noise gives about 3 to 4. Impacts give more.
- **Kurt**: kurtosis of the displayed waveform. Random noise gives 3.0. A
  pure sine gives 1.5. Above about 4 means impulsive: repeated impacts that
  the overall does not show.

Crest factor rises early in the life of a bearing defect. It falls again
when the defect spalls. Read it together with kurtosis, not instead of it.

For an integrated channel (for example `g` to `in/s`), the displayed waveform
is the middle 50 % of the frame. Crest and kurtosis are calculated on that
waveform.

### Frames that are not used

Rev80 shows each frame. It excludes some frames from the trend, the spectral
average, anomaly detection and the anomaly baseline:

| Condition | Cause | What you see |
|---|---|---|
| Overflow | The ADC clipped. The overall reads high and the spectrum has false harmonics. | "Overvoltage Ch X" in **Channel Warnings** |
| Degraded | The USB stream delivered less than the requested rate for a sustained time. | "rate degraded" in the Acquisition card |
| Out of speed window | The shaft speed is outside the speed gate. The amplitude is correct but not comparable. | `[off-speed]` in the headless status line |

Rev80 stores the overflow and degraded flags with each frame, and reads them
back when you load a file.

The speed gate is off by default. Set it in `acquisition.yaml`
(`speed_gate_enabled`, `speed_gate_rpm`, `speed_gate_tolerance_pct`). It
needs a tachometer. With `speed_gate_rpm: null`, the first valid reading
becomes the reference. When the gate is on and there is no speed reading,
the frame is excluded.

Why a speed gate: for a rigid rotor below its first critical speed, the 1x
velocity changes as the cube of the speed. A 3.2 % speed change then moves
the overall by 10 % with no change of condition (calculated, not measured).

### Missing readings: `--`, not `0`

A missing reading is `--`. A `0` is a measured value.

- The shaft speed shows `--` when there is no usable tachometer reading.
- The 1x level is hidden when there is no speed reading, and shows `--` when
  1x is outside the displayed band.
- In a file, a missing shaft speed is stored as `NaN`.

"No signal" and "stopped" are different facts. **No signal** means the tach
block has no usable pulses. **Stopped** means the shaft does not turn. Rev80
cannot yet tell them apart from a flat block (tracked as R45 in
[doc/PROGRESS.md](doc/PROGRESS.md)). Check the machine before you record it
as stopped.

### Accuracy and limits

| Quantity | Value | How measured | Conditions |
|---|---|---|---|
| Shaft speed | ±0.2 % of reading, 300 to 10200 RPM, 1 pulse/rev | AWG loopback, PicoScope 4424A | Raw rate 41666.5 Hz, 2026-09-01. At 25600 Hz the hardware tests passed the same ±0.2 % sweep on 2026-09-18, but the values per point are not recorded. |
| Slowest shaft speed | 180 RPM at 1 s frames, 1 pulse/rev | Calculated | See [Tachometer](#tachometer) |
| Fastest shaft speed at full tach accuracy | About 21900 RPM at 1 pulse/rev | Calculated from the 70-samples-per-pulse limit | Not measured at 25.6 kHz |
| End-to-end amplitude | Within about 1.6 % | Calibrated shaker, 0.1 in/s at 191 Hz, 100 mV/g sensor | Date and scope not recorded. Sensor calibration data is not stored with a measurement (tracked as R38 in [doc/PROGRESS.md](doc/PROGRESS.md)). |
| Anti-alias stopband | −111.7 dB worst case | Calculated through the filter code, no hardware | 2026-08-29 |
| Achieved raw rate | 25591.81 Hz, −320 ppm from 25600 Hz | PicoScope 4824A, s/n 13290/0013 | 2026-09-11. The frequency axis uses the achieved rate. |
| High-pass at the band edge | −1.05 dB at 10 Hz (design −0.915 dB) | Hardware | 2026-08-29 |
| Tach signal floor | Idle input span up to 42.5 mV; threshold 1000 mV | PicoScope 4424A, ±20 V range | Raw rate 41666.5 Hz, 2026-09-01 |

For the measurement tables and the rejected alternatives, read CONTRIBUTING.md,
"Design evidence". For the August 2026 audit that caused many of these
measurements, read [doc/audit-202608.md](doc/audit-202608.md).

---

## Tachometer

A tachometer channel gives the shaft speed. The shaft speed turns a spectrum
into a diagnosis. A line at 162.9 Hz means nothing alone. The same line at
5.43 × shaft speed is typical of a bearing outer race.

Uses:

- **Name the lines.** Slip on a 4-pole 60 Hz motor moves the speed from
  1800 RPM to 1750 RPM between no load and full load. A 5.43 × bearing tone
  then moves 4.5 Hz: 9 bins at 0.5 Hz resolution.
- **Separate electrical from mechanical.** On a 2-pole motor, 2 × line
  frequency is 7200 CPM and 2 × running speed can be 7120 CPM. The repairs
  are different.
- **Keep trends comparable.** Use the speed gate. See
  [Frames that are not used](#frames-that-are-not-used).

### Set up a tachometer

The **Tachometer** tab owns the tachometer channel. The **Channels** tab
shows that channel read-only, and its **Enable** box is locked.

1. Connect the tach to a spare input.
2. In the **Channels** tab, set **Coupling** and **Range** for that input.
   Click **Close**. After you claim the input as the tachometer, the
   Channels tab shows it read-only, and only the device file can change it.
3. Open the **Tachometer** tab.
4. Select the input in **Channel**. Rev80 enables the channel and starts
   the stream, so the plot shows the live signal. **Start** and **Stop**
   start and stop the stream.
6. Set **Polarity** (rising or falling edge).
7. Keep **Threshold** at `adaptive`, unless you have a specific reason.
8. Set **Pulses/rev**. Use 1 where you can.
9. Compare the edges on the plot with the pulses. Read the speed beside
   **Start**/**Stop**.
10. Click **Close** to save.

Wiring and range:

- Use **DC coupling**. AC coupling removes the mean of the signal, and the
  mean of a pulse train is its duty cycle. With AC coupling and a fixed
  threshold, a pulse train above about 55 % duty never reaches the level.
  The machine then reads as having no speed. This was measured on the bench
  at 70 % and 85 % duty. The adaptive threshold avoids this, but DC coupling
  is still correct.
- Select a range with headroom above the pulse height, for example ±10 V for
  a 5 V TTL tach and ±20 V for a 12 V tach or a proximity probe. The
  anti-alias filter adds overshoot at each edge.

The plot shows the raw signal (mV), the threshold, and each detected edge.
The first pulse is at t = 0, so successive frames overlay. If there is no
speed, the plot shows the cause: the pulse is too small, the threshold is in
the wrong place, or AC coupling removes the DC level.

**Min ampl. (mV)** (default 1000 mV): below this peak-to-peak span, the block
has no tach signal. **Reflector (mm)** is the arc length of the tape or key
along the shaft surface (0 = not measured). **Rate units** selects RPM, Hz,
rad/s or deg/s for every shaft speed readout. Files always store RPM.

### Pulses per revolution

One pulse per revolution is the default and the recommended setting. At 1
pulse/rev each interval is exactly one revolution. Encoder division error and
once-per-revolution speed modulation then cancel in each interval. In a model
of a 60-line encoder, the error was 0.0013 % at 1 pulse/rev and 0.091 % at
60 pulses/rev, for any window length (simulated; the conditions are in
CONTRIBUTING.md, "E14.4").

**Pulses/rev** accepts any whole number, for an encoder or keyphasor that is
already on the machine. Rev80 reports a speed only when the frame holds 2
whole revolutions. A higher pulse count has two costs:

- **It does not read a much slower shaft.** At 1 s frames the slowest speed
  is 180 RPM at 1 pulse/rev and 121 RPM at 60 pulses/rev. For a slower
  shaft, use a smaller bin size.
- **It reaches the sample-rate limit.** Edge interpolation needs about 70
  samples for each pulse. Below that, the error increases to about 0.8 %.

| Pulses/rev | Full accuracy up to (at 25591.8 Hz) |
|---|---|
| 1 | about 21900 RPM |
| 6 | about 3660 RPM |
| 60 | about 366 RPM |
| 1024 | about 21 RPM |

These values are calculated from the 70-samples-per-pulse limit. They are
not measured at 25.6 kHz. The raw rate is fixed. The Tachometer tab and the
headless summary show a caution when this limit applies.

### Slowest measurable shaft

The slowest speed at 1 pulse/rev is 180 / frame time, in RPM:

| Bin size | Frame time | Slowest shaft |
|---|---|---|
| 0.25 Hz | 4.00 s | 45 RPM |
| 0.5 Hz | 2.00 s | 90 RPM |
| 1 Hz | 1.00 s | 180 RPM |
| 2 Hz | 0.50 s | 360 RPM |
| 5 Hz | 0.20 s | 900 RPM |
| 10 Hz | 0.10 s | 1800 RPM |

Below this speed the reading is `--`. The Tachometer tab shows the value for
your settings ("Below ... reads as stopped"). This is information, not a
fault: you can set up the tach on a machine that does not turn.

### Reading quality

| Quality | Meaning | Speed shown |
|---|---|---|
| `ok` | Usable reading | Yes |
| `no_signal` | Span below **Min ampl.** | `--` |
| `too_few_edges` | Less than 2 revolutions in the frame | `--` |
| `inconsistent` | Interval spread above 25 %: a missing or extra edge | Yes |
| `unsteady` | Speed change above 1.0 % inside the frame (limit set from simulation only) | Yes |

> **Caution:** An `inconsistent` or `unsteady` reading still shows a speed.
> Rev80 also uses it for the speed gate and the shaft-speed trend. Read the
> quality text before you use the speed.

A tachometer channel has no sensor, no unit, no spectrum and no overall. Its
data is stored as edge times, not as a waveform: about 30 values each second
at 1800 RPM and 1 pulse/rev, against 25600 samples. You cannot change the
threshold after capture. You can change **Pulses/rev** after capture.

A shaft speed always shows its unit. 30 is a plausible RPM, Hz and rad/s.

---

## Envelope analysis

The **Envelope** tab finds rolling-element bearing defects (inner race,
outer race, ball, cage) early, before they show in the overall. To show the
tab, select **Envelope/Demodulation (bearing analysis)** in the Acquisition
tab. It is off by default.

### Why the spectrum does not show the defect

Each time a rolling element passes a defect, it makes a short impact. The
impact rings a structural resonance of the housing, typically between 2 kHz
and 20 kHz. In the spectrum, that energy spreads across the resonance, below
the 1x line and its harmonics. The spectrum of a fresh defect can look
normal.

The impacts repeat at the defect rate. So the amplitude of the resonance
rises and falls at the defect rate. The envelope analysis recovers this
**envelope** and shows it as a line at the defect rate. Sidebands at ±1x
often come with it, from the load zone. Other names for this technique are
PeakVue, enveloped acceleration (gE) and shock pulse.

Rev80 does these steps:

1. Band-pass filter around the resonance. This step removes the 1x.
2. Hilbert magnitude (the instantaneous amplitude).
3. Remove the mean.
4. Amplitude spectrum of the envelope, 0 Hz to 500 Hz.

The envelope uses the raw rate (25600 Hz nominal, 12800 Hz Nyquist). F_max
has no effect on it. The amplitude is in the source EU of the sensor (for
example `g`), not in the channel unit.

### Reading the envelope spectrum

The x axis is **modulation frequency**, not vibration frequency.

- **A line at a bearing defect frequency is the finding.** Calculate BPFO,
  BPFI, BSF or FTF from the bearing geometry and the actual shaft speed.
  A line within 1 % to 2 % of one of them, which a healthy baseline did not
  have, is the signature. Rev80 does not calculate defect frequencies.
- **±1x sidebands around a defect line** confirm it. A defect line with no
  sidebands needs a second look.
- **More harmonics of the defect rate** and a higher floor between them are
  a normal progression as the defect grows.
- **A line at 1x** usually means that the band-pass lets machine vibration
  through. It is usually not a finding.
- **A low floor with no lines** is a healthy bearing. Do not read meaning
  into the texture of the floor.

Trend the defect line over sessions. A line that grows is stronger evidence
than one reading.

### Choosing the demodulation band

The band is the most important setting. Set it in the **Band** fields (low,
high, in Hz).

- **Auto:** With both fields at 0, Rev80 selects a band from the first frame
  and keeps it. **Auto** selects a new band from the current frame and
  writes it into the fields. The search covers a quarter of the raw Nyquist
  up to 0.99 × Nyquist (about 3.2 kHz to 12.7 kHz). The band is a quarter of
  that upper limit wide (about 3.2 kHz). The search uses the band energy, not
  one tall line.
- **Type a band** when you know the resonance, for example from a bump test.
  A housing has more than one resonance. Auto can select a different one.
- **Width:** too narrow loses the sidebands; too wide lets machine lines in
  at the edges.
- The band must be inside 0 Hz to Nyquist and above the highest running-speed
  harmonic of interest.

The info line below the **Band** fields shows the band in use, "(auto)" when
Auto selected it, and the top of the envelope spectrum. A yellow warning
shows when the Nyquist of the data is below 5000 Hz. Then a resonance may
not be in the record. This does not occur at the fixed raw rate. It can
occur for a file recorded at a lower rate.

---

## Monitor Mode

Monitor Mode records frames at an interval into one `session.h5`. Anomaly
detection or the **Record Burst** button records a **burst**: consecutive
frames, with the frames before the trigger.

### Start a recording (GUI)

> **Caution:** Open **Monitor Mode → Setup** once in each GUI session before
> you record or close any Configuration tab. Until you do, the Monitor tab
> holds its built-in values: interval 1 h, pre-trigger 60 s, burst 60 s,
> anomaly detection off, RMS threshold 10 %, warm-up 30 frames. **Monitor**
> uses the values on the tab, and **Close** on any tab saves them to
> `acquisition.yaml`. (Found by reading the code; not verified on screen.)

1. Click **Setup** in the **Monitor Mode** card.
2. Set the Monitor tab. Click **Close**.
3. Click **Monitor**. Rev80 starts the stream if it is stopped.
4. Read the status: `REC hh:mm:ss`, captures, bursts, next capture.
5. Click **Stop** to end the recording. The stream continues.

### Interval captures

At each interval, Rev80 writes one frame to `/monitor/{N}` in `session.h5`.
**Capture interval** offers 5 s, 30 s, 1 min, 5 min, 10 min, 15 min, 1 h,
6 h, 1 day and 2 days. `acquisition.yaml` can hold any value in seconds.

During a burst, Rev80 does not make interval captures. They start again
after the burst.

### Storage

Each stored frame is the raw-rate frame: 25600 samples × 8 bytes = 204.8 kB
for each channel and each second of frame time. F_max has no effect.

The Monitor tab shows an estimate per year of interval captures and per
burst. The estimate counts only the vibration channels. A tachometer channel
stores only edge times, a few values each second, so the estimate does not
count it. The units are decimal: 1 GB = 10^9 bytes, 1 MB = 10^6 bytes,
1 kB = 10^3 bytes.

The estimate assumes that gzip halves the size. This is an assumption, not
a measurement. On `SimulatedSensor` data, gzip level 4 kept 96 % of the raw
size (204800 bytes to 197069 bytes). Plan for the raw size, which is two
times the estimate.

Example: 1 vibration channel, 1 s frames, 10 min interval. This gives 52560
captures a year and about 10.8 GB of raw data. The estimate shows
"~5.4 GB/year". The estimate turns red with a warning icon when it is more
than 10 GB a year, and it adds "(exceeds 50 GB)" when it is more than
50 GB a year. These are warnings, not limits.

### Bursts

A burst starts from an anomaly or from **Record Burst**:

1. Rev80 takes the pre-trigger frames from the frame cache. It enlarges the
   cache to hold them.
2. It records frames for **Burst duration (s)**, limited by `max_burst_s`
   (default 600 s, YAML only).
3. It writes the burst to `/burst/{id}`. For an anomaly, the recorded
   trigger time is the first frame of the anomaly, not the frame that
   confirmed it (up to **Sustained (s)** later).
4. It starts the cooldown, if enabled. The cooldown starts when the burst
   starts.

During a burst, anomaly detection does not trigger, but the baseline
continues to adapt. A burst holds its frames in memory until it ends;
`max_burst_s` limits that memory.

### Anomaly detection

**Enable** turns on the EWMA detectors (RMS; Spectral in headless only). The
fixed-level trigger has its own switches and works when **Enable** is off.

#### RMS (EWMA)

Rev80 keeps an exponentially weighted moving average (EWMA) of the overall of
each channel. It triggers when:

```
|overall − baseline| / baseline  >  rms_pct / 100
```

for **Sustained (s)** seconds. Frames that are not used (see
[Frames that are not used](#frames-that-are-not-used)) do not change the
baseline.

| Setting | GUI label | YAML key | Default |
|---|---|---|---|
| Threshold | Threshold % | `rms_pct` | 50 % |
| Sustained time | Sustained (s) | `rms_s` | 3.0 s (0 = first frame) |
| Baseline time constant | EWMA time (s) | `rms_ewma_time` | 60 s (GUI) |
| Baseline factor | (none) | `rms_alpha` | 0.97 |
| Warm-up | Warmup frames | `warmup` | 10 frames |

`rms_ewma_time` is in seconds. When it is present, it replaces `rms_alpha`.
The GUI writes `rms_ewma_time`. Why 50 %: a 3.2 % speed change can move the
overall by 10 % with no change of condition (see the speed gate).

> **Caution:** An `acquisition.yaml` from an older installation can hold
> `rms_pct: 10.0`. The value in the file replaces the default. Change it to
> `50.0` if you want the current default.

**Reset Baseline** restarts the baseline and the warm-up. Use it after a
process change or a maintenance action.

#### Spectral (headless only)

The spectral detector compares each bin of the spectrum with a per-bin EWMA
baseline. It triggers when **any** bin in the band deviates by more than
`spec_pct` for `spec_n` consecutive frames.

> **Caution:** This detector fires on almost every healthy frame. Each bin
> of a single-segment spectrum scatters by about its own mean value. The GUI
> does not offer it. Headless accepts `hook_type: spectral` and `both`.
> Tracked as R39 in [doc/PROGRESS.md](doc/PROGRESS.md).

| YAML key | Default |
|---|---|
| `spec_pct` | 50 % |
| `spec_n` | 10 frames |
| `spec_alpha` / `spec_ewma_time` | 0.995 / 300 s (GUI) |
| `spec_fmin`, `spec_fmax` | `null` (whole spectrum) |

#### Fixed level

The fixed-level trigger fires at once when the overall crosses a level. It
has no baseline and no warm-up. **Upper limit** and **Lower limit** are
independent.

The level unit must be the same quantity as the channel unit. Rev80 converts
`in/s` to `mm/s`, but it cannot compare `in/s` with `g`. A channel in `mV` or
in a different quantity is skipped, and the log records a warning once.

#### Cooldown

With **Cooldown** on, Rev80 blocks anomaly bursts for **Cooldown period (s)**
(default 300 s) from the start of each burst. Interval captures continue.

### Session browser

Click **Load Session** to open the session browser.

- **Session folder** sets the folder. The default is
  `~/Documents/Rev80/data/monitor/`.
- Click a session to load all its interval captures. The trend shows burst
  times as vertical lines.
- Click a burst to load its frames. The trend starts at the trigger.
- **Save Config** writes the current channel names, sensors, units and
  amplitude modes into the session file. Then it reprocesses the trend.
- **Reprocess** calculates the stored overalls again with the current
  settings.

> **Caution:** **Save Config** changes the session file.

---

## Headless datalogger

`rev80 headless` and `rev80-headless` run Monitor Mode with no GUI. Use them
on a computer with no display, for example in a cabinet.

### First run on a new computer

1. Seed the configuration:

   ```bash
   rev80-headless --init-config
   ```

2. Connect the scope. Check that Rev80 finds it:

   ```bash
   rev80-headless --list-devices
   ```

3. Start once. Rev80 writes `devices/picoscope-<model>-<SN>.yaml` from the
   template and shows the session summary:

   ```bash
   rev80-headless
   ```

4. Press `Ctrl+C` at the prompt.
5. Edit the device file: coupling, range, sensor, unit and name for each
   channel.
6. Edit `acquisition.yaml`: interval, bursts and anomaly settings.
7. Start the unattended run:

   ```bash
   rev80-headless --start-now
   ```

### Run

Before it connects, headless prints a summary: device, channels, display
sample rate, block, resolution, tachometer, monitor and anomaly settings, and
the paths of the configuration files. It then waits for `Enter`.
`--start-now` skips the prompt.

During the run:

- The status line shows elapsed time, capture count, time to the next
  capture, file size, and the shaft speed (`-- RPM` when there is no
  reading). `[off-speed]` shows when the speed gate excludes the frame.
  `[BURST Ns]` shows during a burst.
- Type `t` and `Enter` to start a manual burst.
- `Ctrl+C` or `SIGTERM` stops the recording, flushes the file and closes the
  device. This works with systemd `Restart=on-failure`.
- A write error stops the run.

Headless writes a v6 `session.h5`. Open it with the GUI session browser or
with `rev80 --from-file`.

### Channels

`--channels 0 1` enables the listed channels and saves the selection in the
device file. You do not need to repeat it.

A tachometer channel is different. Its role owns its enabled state. If
`--channels` omits the tachometer, headless drops it for this run only and
logs a warning. Then no speed is recorded, and with the speed gate on, all
frames are excluded from trends and alarms.

### Tachometer in headless

Set up the tachometer in the GUI Tachometer tab. Or edit the device file: set
`role: tachometer` on the channel and fill its `tach:` block. A tachometer
channel with no `tach:` block uses the defaults (adaptive threshold, rising
edge, 1 pulse/rev), and headless logs a warning.

The summary shows the tachometer channel, threshold mode, polarity,
pulses/rev, the slowest shaft for the block, and (above 1 pulse/rev) the
speed up to which full accuracy applies.

### Examples

```bash
# Explicit settings, no prompt (systemd, cron, scripts)
rev80-headless \
  --interval 300 \
  --pre-buffer 30 \
  --burst-duration 120 \
  --output /mnt/nas/vibration \
  --channels 0 1 \
  --maxfreq 1000 \
  --binsize 1 \
  --start-now

# Simulated sensor, no hardware. A tachometer channel in the device
# file gets a pulse train at the same shaft speed as the vibration.
rev80-headless --device sim --interval 10 --start-now
```

---

## Configuration files

Run `rev80 --init-config` to create the configuration folder. It writes
`acquisition.yaml` and `devices/picoscope-defaults.yaml` if they do not
exist. It does not change existing files.

```
~/.config/rev80/                        (%APPDATA%\rev80\ on Windows)
  acquisition.yaml                      acquisition and Monitor Mode settings
  scope_sensors.yaml                    IEPE sensor library
  devices/
    picoscope-defaults.yaml             channel template for a new device
    picoscope-4424A-JY123.yaml          channels and signal generator of one device
```

When a key is missing from `acquisition.yaml`, Rev80 uses the built-in
default. A key in the file always replaces the default.

### `acquisition.yaml`

This file is for the whole computer, not for one device. The GUI and
headless use the same file.

**`acquisition:` section**

| Key | Unit | Seeded value | Widget | Meaning |
|---|---|---|---|---|
| `maxfreq` | Hz | 1000 | Freq. Range | F_max. Limited to 10000 Hz. |
| `binsize` | Hz | 1 | Freq. Resolution | Bin size; frame time = 1 / bin size |
| `fft_window` | | `hann` | FFT Window | `hann`, `blackmanharris`, `flattop`, `hamming`, `boxcar`, `bartlett` |
| `welch_overlap` | fraction | 0.5 | Welch Overlap % | No effect at present (one segment per frame) |
| `highpass_enabled` | | `true` | Highpass | High-pass filter on or off |
| `highpass_fc` | Hz | 10 | Highpass Hz | Band edge of the high-pass |
| `band_fmin`, `band_fmax` | Hz | `null` | Overall Band, min, max Hz | Declared band. `null` = high-pass edge to F_max |
| `trend_max_points` | points | 5000 | YAML only | Trend length |
| `cache_frames` | frames | 15 | Cache Frames | Frame cache depth |
| `speed_gate_enabled` | | `false` | YAML only | Speed gate on or off |
| `speed_gate_rpm` | RPM | `null` | YAML only | Reference speed. `null` = first reading |
| `speed_gate_tolerance_pct` | % | 3.0 | YAML only | Allowed deviation from the reference |
| `rotation_unit` | | `RPM` | Rate units | `RPM`, `Hz`, `rad/s`, `deg/s` |
| `averaging_enabled` | | (false) | Average spectrum | Spectral averaging on or off |
| `n_averages` | frames | (8) | Averages | Frames to average |
| `peak_threshold_db` | dB | (9.5) | Peak Sig., dB | Peak threshold |
| `envelope_enabled` | | (false) | Envelope/Demodulation | Show the Envelope tab |

Values in parentheses are not in a seeded file. The GUI writes them when it
saves.

**`monitor:` section**

| Key | Unit | Seeded value | Widget | Meaning |
|---|---|---|---|---|
| `interval_s` | s | 600 | Capture interval | Time between interval captures |
| `pre_burst_s` | s | 30 | Pre-trigger buffer (s) | Time before the trigger kept in a burst |
| `burst_duration_s` | s | 120 | Burst duration (s) (GUI maximum 600) | Burst length after the trigger |
| `max_burst_s` | s | 600 | YAML only | Upper limit of a burst length |
| `output_dir` | path | `null` | Output directory | `null` = `~/Documents/Rev80/data/monitor/` |
| `compression` | | `gzip` | gzip compression | `gzip` or `none` |
| `compression_level` | | 4 | YAML only; the GUI writes 4 when it saves | gzip level |

**`monitor.anomaly:` section**

| Key | Unit | Seeded value | Widget |
|---|---|---|---|
| `enabled` | | `true` | Enable (Anomaly Detection) |
| `hook_type` | | `rms` | Hook (GUI offers RMS only) |
| `warmup` | frames | 10 | Warmup frames |
| `rms_pct` | % | 50.0 | Threshold % |
| `rms_s` | s | 3.0 | Sustained (s) |
| `rms_alpha` | | 0.97 | YAML only |
| `rms_ewma_time` | s | (none) | EWMA time (s); replaces `rms_alpha` |
| `spec_pct` | % | 50.0 | Headless only |
| `spec_n` | frames | 10 | Headless only |
| `spec_alpha` | | 0.995 | Headless only |
| `spec_ewma_time` | s | (none) | Replaces `spec_alpha` |
| `spec_fmin`, `spec_fmax` | Hz | `null` | Headless only |
| `fixed_upper_enabled`, `fixed_upper_value`, `fixed_upper_unit` | | `false`, 1.0, `in/s` | Upper limit |
| `fixed_lower_enabled`, `fixed_lower_value`, `fixed_lower_unit` | | `false`, 0.05, `in/s` | Lower limit |
| `cooldown_enabled`, `cooldown_s` | s | `false`, 300 | Cooldown, Cooldown period (s) |

If the file holds `hook_type: spectral` or `both`, the GUI shows RMS but
keeps the stored value when it saves.

### `devices/picoscope-defaults.yaml`

Rev80 applies this template to each channel of a device that it sees for the
first time. Channel 0 is enabled. Edit the template before you connect a new
scope.

```yaml
channel:
  enabled: false
  sensor_id: null
  voltage_range: 6          # PS4000A range index; 6 = ±1 V
  coupling: AC
  channel_name: null        # null = 'Ch A', 'Ch B', ...
  target_unit: null         # null = the sensor EU
  amplitude_mode: 0-P
  role: vibration           # or tachometer
  tach: null                # tachometer settings when role is tachometer
siggen:
  enabled: false
  wave_type: PS4000A_SINE
  freq_hz: 1000.0
  pktopk_uv: 1000000        # 1 V peak-to-peak
  offset_uv: 0
```

Range index: 0 = ±10 mV, 1 = ±20 mV, 2 = ±50 mV, 3 = ±100 mV, 4 = ±200 mV,
5 = ±500 mV, 6 = ±1 V, 7 = ±2 V, 8 = ±5 V, 9 = ±10 V, 10 = ±20 V.

### `devices/picoscope-<model>-<SN>.yaml`

Rev80 writes this file when it sees a device for the first time. It holds
the channels and the signal generator of that device. The GUI saves it when
you close the Configuration dialog.

```yaml
channels:
  0:
    enabled: true
    sensor_id: <uuid>       # from scope_sensors.yaml
    voltage_range: 6
    coupling: AC
    channel_name: Motor NDE
    target_unit: in/s
    amplitude_mode: 0-P
    role: vibration
    tach: null
  1:
    enabled: true
    coupling: DC
    voltage_range: 9        # ±10 V for a 5 V TTL tach
    role: tachometer
    tach:                   # written by the Tachometer tab
      pulses_per_rev: 1
      polarity: rising
      threshold_mode: adaptive
      ...
siggen:
  enabled: false
  ...
```

A tachometer channel is always enabled. An unknown `role` value reads as
`vibration`, and the log records a warning.

### `scope_sensors.yaml`

The IEPE sensor library, for all devices. Edit it in the **Sensors** tab, or
by hand. `rev80 --list-sensors` lists it.

```yaml
- id: <uuid>
  name: PCB 352C33 Ch1
  sensitivity: 10.2         # mV per engineering unit
  engineering_units: g
  notes: ''
```

The key is `sensitivity`. When you assign a sensor to a channel, Rev80
divides the signal in mV by `sensitivity` to get the engineering unit. The
display unit and amplitude mode are channel settings, not sensor settings.

### Logging

Rev80 writes `main.log`, `error.log` and `debug.log` to
`~/Documents/Rev80/logs/`. The files rotate. `--debug` also writes verbose
log lines to the console. `faulthandler.log` in the same folder records hard
crashes.

---

## Command reference

`rev80` is the entry point for the GUI, headless and the info commands.
`rev80-headless` is the same as `rev80 headless`. Run `rev80 --help` or
`rev80 headless --help` for the current list.

### `rev80`

| Option | Meaning |
|---|---|
| `--version` | Print the version and exit |
| `--init-config` | Create the default configuration files and exit |
| `--list-devices` | List the connected PicoScopes and exit |
| `--list-sensors` | List the IEPE sensor library and exit |
| `--edit-config` | Open `acquisition.yaml` in `$EDITOR` (then `$VISUAL`, then `nano`) and exit |
| `--install-desktop-entry` | Linux: add the application-menu entry and exit |
| `--uninstall-desktop-entry` | Linux: remove the entry and exit |
| `--from-file PATH` | Open a measurement `.h5`, a `session.h5`, or a session folder at start |
| `--autodetect` / `--no-autodetect` | Connect to the first PicoScope at start. Default: on, off with `--from-file` |
| `--debug` | Verbose logging to the console |
| `--profile` | Time the pipeline stages and log the table at exit. `REV80_PROFILE=1` does the same. |
| `headless ...` | Run the headless datalogger |

Examples:

```bash
rev80 --from-file ~/Documents/Rev80/data/my_run.h5
rev80 --from-file ~/Documents/Rev80/data/monitor/2026-06-02-130000/
rev80 --from-file /mnt/nas/vibration/2026-06-02-130000/session.h5
```

### `rev80 headless` / `rev80-headless`

The four info commands above are also available here.

| Option | Default | Meaning |
|---|---|---|
| `--interval SECS` | `interval_s` from `acquisition.yaml`, else 600 | Capture interval |
| `--pre-buffer SECS` | `pre_burst_s`, else 30 | Pre-trigger time |
| `--burst-duration SECS` | `burst_duration_s`, else 120 | Burst length (limited by `max_burst_s`) |
| `--output DIR` | `output_dir`, else `~/Documents/Rev80/data/monitor/` | Root folder for sessions |
| `--no-compress` | `compression` | No gzip |
| `--start-now` | | Skip the start prompt |
| `--device SERIAL` | first scope found | Serial number (a part is sufficient), or `sim` |
| `--channels N [N ...]` | device file | Channels to enable; saved in the device file |
| `--maxfreq HZ` | `maxfreq` | F_max for this run. Limited to 10000 Hz. |
| `--binsize HZ` | `binsize` | Bin size for this run |
| `--debug` | | Verbose logging to the console |

> **Note:** `--help` gives other defaults for `--interval`, `--pre-buffer`
> and `--burst-duration` (3600, 60 and 60). The code uses the values in this
> table.

---

## Data files

Every stored frame is the raw-rate frame in mV. Analysis settings are not
fixed in the file: after you load a file, you can change the averaging, the
declared band, the unit or the pulses per revolution, and Rev80 calculates
again. Rev80 stores the achieved sample rate as a float.

> **Note for programs that read the files:** A tachometer channel has no
> `data` dataset. Test for `data` before you read it.

### Measurement files (version 5)

**File → Save** writes the frame cache of the enabled channels to one file,
by default in `~/Documents/Rev80/data/`. The file is not compressed.

```
/metadata.attrs                     version = 5, notes
/metadata/acquisition.attrs         acquisition settings (null stored as '')
/metadata/scope_sensors/{id}.attrs  each sensor in use
/metadata/channels/{ch}.attrs       name, unit, coupling, voltage_range,
                                    scope_sensor_id, target_unit,
                                    amplitude_mode, role,
                                    tach_* (tachometer channels only)
/frames/{i}.attrs                   timestamp, rel_time, samplerate, status
/frames/{i}/{ch}.attrs              timestamp, rel_time, samplerate, status,
                                    overflow, degraded
/frames/{i}/{ch}/data               (N,) float64, mV        vibration channels
/frames/{i}/{ch}/edge_times         (E,) float64, s from block start
/frames/{i}/{ch}/pulse_widths       (P,) float64, s          tachometer channels
/frames/{i}/{ch}.attrs (tach)       also rpm (NaN = none), quality, n_edges,
                                    interval_spread, speed_drift_pct,
                                    duty_cycle, pulses_per_rev
/trend/{ch}/rel_times               (M,) float64, s
/trend/{ch}/orders                  (M, 5) float64, mV RMS, integration orders −2 to +2
/trend/{ch}/crest_factor            (M,) float64
/trend/{ch}/kurtosis                (M,) float64
/tach_trend/{ch}/rel_times          (M,) float64, s
/tach_trend/{ch}/rpm                (M,) float64, RPM
```

### Monitor sessions (version 6)

Monitor Mode writes `{output}/{session_id}/session.h5`. The `session_id` is
`YYYY-MM-DD-HHMMSS`: UTC for headless, local time for the GUI.
`start_time` is local time. Frame data is gzip-compressed unless you select
`none`.

```
/metadata.attrs                     file_version = 6, session_id, start_time,
                                    interval_s
/metadata/acquisition.attrs         acquisition settings at start
/metadata/scope_sensors/{id}.attrs  sensors at start
/metadata/channels/{ch}.attrs       channel settings at start (as above)
/monitor/{N}.attrs                  timestamp, rel_time, samplerate, status,
                                    overall_json, peaks_json, band_json,
                                    scalars_json, rpm, speed_ok
/monitor/{N}/{ch}/...               one channel group, as in version 5
/burst.attrs                        burst_list (JSON list of burst summaries)
/burst/{id}.attrs                   trigger_type, trigger_timestamp,
                                    trigger_rel_time, burst_duration_s,
                                    max_overall_json, band_json, scalars_json,
                                    rpm, speed_ok, n_frames, n_pretrigger_frames
/burst/{id}/{k}.attrs               timestamp, rel_time, samplerate, status,
                                    is_pretrigger, overall_json
/burst/{id}/{k}/{ch}/...            one channel group, as in version 5
```

`rpm` is `NaN` when there is no reading. Rev80 opens a file up to the
version that it writes (5 for measurements, 6 for sessions).

---

## Signal generator

The PicoScope 4000A has an arbitrary waveform generator (AWG) on its
front-panel output. Use it for sensor check-out, resonance excitation or
loopback tests. Set it in the **Generate** tab.

| Setting | Values |
|---|---|
| Enable signal generator | on / off |
| Waveform | Sine, Square, Triangle, Ramp Up, Ramp Down, DC |
| Frequency (Hz) | 0 to 20000000 |
| Amplitude pk-pk (mV) | 0 to 4000 |
| Offset (mV) | −2000 to 2000 |

The generator runs continuously from stream start to stream stop. It is
programmed once when the stream starts and has no trigger for each block.
Rev80 saves the settings in the device file and restores them when the same
device connects. The generator has no effect with the simulated sensor.

---

## Simulated sensor

The simulated sensor lets you use Rev80 with no scope. Select it in the
Device tab, or use `--device sim` with headless. `--list-devices` does not
show it.

It generates data at the raw rate (25600 Hz exactly), as the scope does. The
default signal is a machine with a bearing defect:

- Shaft speed 60 Hz (3600 RPM).
- Defect impacts at 5.43 × shaft speed, with 1.5 % slip jitter.
- Each impact rings a 4000 Hz resonance.
- The load zone modulates the impacts at the shaft speed.
- White noise.

When the device file has a tachometer channel, that channel gets a 5 V pulse
train at the same shaft speed.

> **Caution:** The simulated sensor reports exactly 25600 Hz. A real scope
> reports about 25591.8 Hz. A speed or accuracy result from simulation only
> can be wrong on hardware.

Other generators in `simulation.py` (`GenerateTone`, `GenerateNoise`, and the
older spectral and temporal bearing models) are for tests. See
CONTRIBUTING.md.

---

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| The next start fails with `PICO_NOT_FOUND` | The scope stayed open after a crash | Disconnect and connect the USB cable |
| "PicoScope driver not found" in the Device tab; `--list-devices` says the driver is not installed | PicoSDK is not installed | Install PicoSDK. On Linux, run `sudo ./drivers/install-picoscope4000a-driver.sh`. Restart the computer. |
| "No devices found" | USB, power or driver | Check the cable. Run `rev80 --list-devices`. |
| SmartScreen blocks the installer | The installer is not signed | Click *More info*, then *Run anyway* |
| Anomaly bursts at a 10 % change | An old `acquisition.yaml` holds `rms_pct: 10.0` | Set `rms_pct: 50.0`, or set it in the Monitor tab |
| Monitor settings changed to 1 h / 60 s / 60 s after you closed the Configuration dialog | The Monitor tab was not opened in this GUI session (see [Monitor Mode](#monitor-mode)) | Open **Monitor Mode → Setup**, set the values again, click **Close** |
| Shaft speed shows `--` | No signal, too few revolutions in the frame, or a missing tachometer | Read the quality text. Check coupling, range and **Min ampl.** Use a smaller bin size for a slow shaft. |
| "Overvoltage Ch X" | The input clips | Select a larger **Range** |
| "rate degraded" | USB delivers too few samples | Use fewer channels, a different USB port, or no USB hub |
| The monitor records nothing | The stream is stopped | Start the stream. Do not use `Ctrl+K` during a recording. |
| Load, Load Session or Clear Cache is disabled | A recording runs | Stop the recording |
| Crash with no message | A hard crash or a kill by the operating system | Read `~/Documents/Rev80/logs/faulthandler.log` and `error.log` |

---

To build, package or change Rev80, read **[CONTRIBUTING.md](CONTRIBUTING.md)**.
