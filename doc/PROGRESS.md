# Rev80 — Project Progress

This file maps the client meetings, the requirements and the development
phases to commits. The source of the meeting notes is
`doc/VibeGui Project.md`.

- The **Requirements Tracker** near the end of this file gives the current
  status of each requirement. It is the only source of current status.
- A status column in a meeting table gives the status on the meeting date.
  Where the tracker has a later status, the row says "(status on this date;
  see tracker)".
- Links such as [S-02](audit-202608.md#s-02) go to a finding of the
  August 2026 audit, in `doc/audit-202608.md`.

---

## Project Background

Originated 2025-01-23 when a Digiducer-based data collection script was
demonstrated to Carmen at a client site. The goal: replace expensive commercial
vibration analysis tools (e.g. VibeAnalyze, $999) with a purpose-built Python
desktop app targeting industrial predictive maintenance workflows.

---

## Development Phases

### Proto — Initial prototype (Feb – Aug 2025)

Bare-bones data capture and display using the Digiducer USB audio interface.
No HDF5, no velocity spectrum, minimal GUI.

| Date | Commit | Description |
|------|--------|-------------|
| 2025-02-15 | `ae1736e` | Project created |
| 2025-03-05 | `5b017d1` | Project management notes |
| 2025-03-17 | `891d26f` | Backup snapshot |
| 2025-05-20 | `cca1d4e` | Working demo (Digiducer stream + basic plot) |
| 2025-05-20 | `e247dba` | Module init |
| 2025-05-21 | `856f855` | Digiducer abstracted into sensor and logger types |
| 2025-08-12 | `1257994` | First working dearpygui GUI with live stream |
| 2025-08-12 | `a3c2fd1` | Project management |
| 2025-08-12 | `be9e91c` | Bug fix: array dimensions |

---

### Meeting — 2025-01-23: Carmen, first demo

**Requirements captured:**

| # | Requirement | Status |
|---|-------------|--------|
| R1 | Frequency range and bin size selector | ✅ Done — Dec 2025 |
| R2 | Normalize FFT to IPS or g (velocity preferred over acceleration) | ✅ Done — Dec 2025 |
| R3 | Display top peaks | ✅ Done — Dec 2025 |
| R4 | Smoothing | ❌ Not implemented (status on this date; see tracker) |
| R5 | Interactive peak inspection | ❌ Not implemented (status on this date; see tracker) |
| R6 | Running speed harmonics markers | ❌ Not implemented |
| R7 | Bearing fault frequency markers | ❌ Not implemented (status on this date; see tracker) |
| R8 | Metadata: date, company, machine info, bearing types, running rate | ❌ Not implemented (status on this date; see tracker) |
| R9 | Trend: overall vibration over time | ✅ Done — Mar 2026 |
| R10 | Luxury: startup and coastdown trend | ❌ Future (status on this date; see tracker) |

---

### Phase 0 — Digiducer acquisition, GUI polish (Nov – Dec 2025)

Core pipeline stabilised; units, HDF5 persistence, and modular architecture added.

| Date | Commit | Description |
|------|--------|-------------|
| 2025-11-17 | `587e393` | Save button added |
| 2025-11-20 | `e9120d2` | Logging module with YAML config; print statements removed |
| 2025-11-25 | `c8bb0ae` | VibeSample refactored |
| 2025-11-26 | `6049f7f` | Carmen meeting notes — deployment roadmap |
| 2025-12-11 | `22014af` | Units switching; save/load via pickle |
| 2025-12-16 | `10e48a0` | scipy FFT tools; GUI unit and integration controls |
| 2025-12-17 | `580d254` | Logger made universal |
| 2025-12-17 | `383f28e` | File browser fix |
| 2025-12-17 | `14dd5ca` | Unit conversion consistency |
| 2025-12-17–18 | `772214e`–`4424d3d` | AcquisitionSettings upgrade (multi-step) |
| 2025-12-29 | `38f22d3` | Plot units upgrade — units switching throughout GUI |
| 2025-12-29 | `8fb488c` | refactor_util — split into sample, sensor, simulation, digiducer modules |

---

### Meeting — 2025-11-25: Carmen, deployment roadmap

**Phase definitions agreed:**

| Phase | Scope | Budget |
|-------|-------|--------|
| Phase 1 | Development to date (Digiducer era) | $2k |
| Phase 2 | Polish and deploy to Windows | $1k |
| Phase 2b | Integrate BNC DAQ for proximity probes | $1k |
| Phase 3 | Sales | — |

**Requirements from this meeting:**

| # | Requirement | Status |
|---|-------------|--------|
| R11 | Switch between velocity and acceleration in frequency domain | ✅ Done — Dec 2025 (`10e48a0`, `38f22d3`) |
| R12 | IPS zero-to-peak trend analysis | ✅ Done — Jan 2026, extended Mar 2026 |
| R13 | RMS amplitude option | ✅ Done — Mar 2026 (`5872cab`, `1e040d3`) |
| R14 | Two simultaneous sensors (phasing) | ✅ Done — Mar 2026 (multi-channel pipeline) |
| R15 | Proximity probe / DAQ support | 🔄 Partially done — PicoScope replaces BNC DAQ |

---

### Meeting — 2025-12-30: Carmen

**Requirements from this meeting:**

| # | Requirement | Status |
|---|-------------|--------|
| R16 | Overall vibration energy (IPS 0-P) | ✅ Done — Jan 2026 (`ff4b31d`) |
| R17 | Trend plot of overall vibration over time | ✅ Done — Mar 2026 (`cff702e`) |
| R18 | Fix IPS unit scaling (was ~200× wrong) | ✅ Done — Dec 2025 / confirmed Jan 2026 (`e7eddde`) |

---

### Phase 1b — HDF5, FFT validation, overall vibration (Jan 2026)

| Date | Commit | Description |
|------|--------|-------------|
| 2026-01-05 | `dc64e37` | UI_Elements moved to util for global access |
| 2026-01-05 | `e3a988d` | AcquisitionSettings hot-swap while streaming |
| 2026-01-05 | `cde0834` | Reorg and cleanup |
| 2026-01-06 | `32ab828` | HDF5 save/load (replaces pickle) |
| 2026-01-09 | `e76fb4f` | DAQ hardware evaluation notes committed |
| 2026-01-10 | `f0c549e` | ISO timestamp; monotonic `rel_time` per block |
| 2026-01-11 | `e7eddde` | FFT amplitude scaling validated with single-tone tests |
| 2026-01-12 | `ff4b31d` | Overall 0-P vibration display (acceleration and velocity) |
| 2026-01-12 | `fcf9e7e` | Oversample stream for better Welch FFT resolution |
| 2026-01-16 | `70c51db` | uldaq dependency added (MCC USB-1608FS-Plus evaluation) |
| 2026-01-20 | `2f95891` | MCC DAQ code examples |
| 2026-03-09 | `2508756` | MCC DAQ integration work |

---

### Meeting — 2026-01-11

**Notes:**
- Overall 0-P vibration display added and demonstrated
- Bin selector behaves poorly — flagged
- Timestamp now FAT32-compatible (colons replaced by hyphens)
- UI/UX language and jargon should match Alta's tooling
- Demo screenshots needed for website

| # | Requirement | Status |
|---|-------------|--------|
| R19 | Confirm overall vibration values are correct (vs. individual peaks) | ✅ Done — validated `e7eddde` |
| R20 | Fix bin selector behaviour | ✅ Done — Mar 2026 (`a69f14f`, `3fde4bc`) |
| R21 | UI/UX language aligned with Alta | ❌ Ongoing (status on this date; see tracker) |
| R22 | Demo screenshots for website | ❌ Not committed |

---

### Phase 2 — PicoScope 4000A acquisition backend (Mar 2026)

Hardware pivot: replace Digiducer/sounddevice with PicoScope 4000A. Enables
any IEPE sensor (accelerometers, proximity probes, microphones) via standard
BNC input — removes Digiducer hardware dependency.

| Date | Commit | Description |
|------|--------|-------------|
| 2026-03-13 | `cf89848` | **PicoScope 4000A acquisition backend** — `FindPicoScope()`, `PicoScopeStream`, ADC→mV, accumulator, USB power fallback |
| 2026-03-13 | `1b711c9` | Merge feature/picoscope into main |
| 2026-03-13 | `2b9aa38` `d9add87` | Comprehensive README added |
| 2026-03-13 | `91b06ce` | CLAUDE.md architecture guide added |
| 2026-03-16 | `8abb72d` | **IEPE sensor registry, triax support, PicoScope GUI integration** — `ScopeSensor` dataclass, `ScopeSensorRegistry` YAML persistence, per-channel sensitivity (mV/EU), GUI sensor library panel |
| 2026-03-16 | `cd40f63` | Harden PicoScope detection: overvoltage recovery, watchdog (5 s timeout, 3 reconnect attempts) |
| 2026-03-16 | `f03255d` | Fix handle-close between retries; extended delay after `PICO_NOT_RESPONDING` |
| 2026-03-16 | `67ebfd6` | Test: update for new default voltage range |

---

### Phase 2a — Multi-channel EU pipeline and GUI overhaul (Mar 2026)

Full multi-channel data path from hardware to display, with per-channel sensor
assignment, modality-aware integration, and three-column GUI layout.

| Date | Commit | Description |
|------|--------|-------------|
| 2026-03-18 | `0d8911c` | Three-column GUI layout with primary window resizing |
| 2026-03-18 | `0147231` | Modality-aware integration (acc↔vel↔disp via FFT); mV/EU sensitivity pipeline; unit conversion tests |
| 2026-03-19 | `13b1095` | Add mil (1/1000 in) as displacement unit |
| 2026-03-20 | `afa5ce0` | Fix frequency-domain integration using signed exponent |
| 2026-03-24 | `09cea74` | **Multi-channel pipeline, scope sensor registry, EU unit refactor** — PicoScopeStream multi-channel buffers; per-channel mV→EU via ScopeSensor; DataCollector fan-out |
| 2026-03-24 | `4f8897c` | **GUI overhaul** — channel config panel; per-channel status lights; dual-axis plots; scope sensor registry UI |
| 2026-03-24 | `8280bd5` | Test restructure: multi-channel, hardware isolation, new API coverage |
| 2026-03-24 | `5d57ab4` | Fix PicoScope circular buffer wraparound in streaming callback |
| 2026-03-24 | `0ca1251` | Replace Acquire/Configure tabs with streamlined left-panel layout |
| 2026-03-24 | `c70b8f3` | Visual section containers (borders, themed backgrounds) for left panel |
| 2026-03-25 | `cff702e` | **Multi-channel data pipeline** — 32-frame ring cache; `ChannelResult` frozen dataclass; trend store; multi-channel HDF5 layout; browse ←→ buttons |
| 2026-03-25 | `142dc30` | Expanded multi-channel test coverage; TestFrameCache, TestTrend, TestChannelResult |
| 2026-03-25 | `32410b6` | Fix: overflow bitmask; default voltage range 10→7 (10× finer ADC resolution) |
| 2026-03-25 | `23d0902` | Test: overflow key handling, per-channel helpers |
| 2026-03-25 | `e365099` | Per-channel AC/DC coupling; results card sizing; 3 default peaks |
| 2026-03-25 | `5ec3e45` | Fix: reset channel config and plot series on device switch |

---

### Phase 2b — Signal generator, spectrum controls, GUI polish (Mar 2026)

AWG output for excitation testing; FFT window selection; manual axis control;
left-panel redesign; siggen config persistence.

| Date | Commit | Description |
|------|--------|-------------|
| 2026-03-25 | `f74dd41` | **Signal generator UI** — Generate config tab (enable, waveform, freq, amplitude, offset); SimulatedSensor buried (CI/test only via `VibeSensor.simulated()`) |
| 2026-03-25 | `2a05ff9` | FFT window type selector (Hann/Blackman-Harris/Flattop/Hamming/Boxcar/Bartlett) |
| 2026-03-25 | `7e6b89f` | Manual axis control — remove auto-fit on redraw; Autoscale button; Clear Cache button; full Welch frequency range (remove maxfreq display crop) |
| 2026-03-25 | `ffb4121` | Left panel rework — Device card, Channels card, button visibility fix (`width=-1` bug), Load button restored |
| 2026-03-25 | `83a980d` | Card heights (DPG autosize_y fix); toggle button colour theming (idle/waiting/active); autoscale on first acquisition |
| 2026-03-25 | `ef0b560` | Channel Setup and Signal Generator buttons in Channels card |
| 2026-03-25 | `d0c1068` | Device card expanded with model, S/N, ID, channel count |
| 2026-03-25 | `7bc729d` | CH_WARNINGS_SECTION height scales to overflow channel count |
| 2026-03-25 | `eb811b6` | Siggen config persisted to `channel_assignments.yaml`; restored on device connect |
| 2026-03-25 | `7aa69b3` | **Unified VibeSample pipeline** — `process()` replaces `get_accel()` + `fft()`; returns `ChannelResult`; cross-modality FFT integration for physically correct time-domain signal |
| 2026-03-25 | `5872cab` | Amplitude mode selector (RMS / 0-P / P-P) in GUI; Y-axis labels per mode |
| 2026-03-25 | `1e040d3` | Amplitude mode moved to `ScopeSensor` (per-sensor, not global spectrum setting) |
| 2026-03-26 | `a69f14f` | **Modernised AcquisitionSettings** — derived properties (samplerate, blocksize from maxfreq/binsize); explicit highpass/lowpass filter fields; Welch overlap; n_fft_bins; memory_bytes |
| 2026-03-26 | `ad98816` | Lowpass filter added to collector pipeline |
| 2026-03-26 | `3fde4bc` | Spectrum tab redesign — combo presets; live-updating derived fields; filter controls |
| 2026-03-26 | `36db391` | Tests updated for new AcquisitionSettings API |

---

### Meeting — 2026-03-18

| # | Requirement | Status |
|---|-------------|--------|
| R23 | Multi-channel: toggle channels on/off | ✅ Done (`09cea74`, `4f8897c`) |
| R24 | Two-channel phase relationship display | ❌ Not implemented |
| R25 | Time-domain zoom window (e.g. 5 ms) | ❌ Not implemented (status on this date; see tracker) |
| R26 | Track down velocity integration low-frequency noise | 🔄 Partially addressed (`afa5ce0`); warrants further investigation (status on this date; see tracker) |
| R27 | Windows packaging (exe) | ❌ Not implemented (status on this date; see tracker) |

---

### Meeting — 2026-03-25

| # | Requirement | Status |
|---|-------------|--------|
| R28 | 0-P, P-P, RMS selectable per sensor | ✅ Done (`5872cab`, `1e040d3`) |
| R29 | Acquisition settings causing long capture times | ✅ Done — `AcquisitionSettings` derives `samplerate` and `blocksize` from `maxfreq` and `binsize` (`a69f14f`). Since Sep 2026, `samplerate` is exactly 2.56 × `maxfreq`, not rounded up to a power of two (CHANGELOG `hotfix/RAW_SAMPLERATE`) |
| R30 | Displaying wrong bins in spectrum setup | ✅ Done — Spectrum tab redesigned with live derived fields (`3fde4bc`) |

---

### Phase 4 — mV-domain pipeline + trend unit reflow (May 2026)

VibeSample refactored to store raw mV throughout; sensitivity conversion and
Butterworth filtering moved to DataCollector.process_sample. Welch PSD cached
per sample (keyed to filter/welch config); five broadband RMS overalls
(integration orders −2…+2, in mV RMS) cached per sample and stored per trend
timestep as a (M,5) ndarray. Unit/sensitivity/amplitude-mode changes reflow
the trend at display time via DataCollector.get_trend_for_display() — no
clearing required. DataCollector.process_samples() introduced as the single
entry point for frame processing. GUI display loop simplified. HDF5 bumped to
v4 with per-channel orders matrix; v3 files loaded in best-effort degraded mode.

| Date | Commit | Description |
|------|--------|-------------|
| 2026-05-05 | `0c76c9a` | refactor: mV-domain VibeSample + 5-order trend reflow |
| 2026-05-05 | `5fcf09a` | refactor(gui): simplify display loop via process_samples() |
| 2026-05-05 | `3717286` | test: update for mV-domain pipeline |
| 2026-05-05 | `0a1b38c` | feat(gui): configurable frame cache depth with recording-window display |
| 2026-05-27 | `90a97c6` | feat(picoscope): enumerate all connected scopes; hardware channel count probe |

### Requirements added in Phase 4

| # | Source | Requirement |
|---|--------|-------------|
| R49 | May 2026 | Configurable frame cache depth (integer selector in the Acquisition tab), with the recording window and the total memory shown. Numbered R28 until Sep 2026; R28 is the amplitude-mode requirement of 2026-03-25 |

### Phase 5 — GUI responsiveness profiling (Sep 2026)

`experimental/profiling`. The GUI stuttered on every processing call, worse
with every enabled channel, after the mandatory anti-alias filter and
oversampled streaming landed. Built per-stage timing (`src/rev80/_profile.py`,
`rev80 --profile`, `scripts/profile-pipeline`) before changing anything, then
fixed the three causes it indicted: an unbounded raw->display resample ratio
designing a 512821-tap FIR per channel per frame *on hardware only*, the vendor
`adc2mV` per-sample Python loop holding the GIL inside the driver callback, and
a per-channel peaks table destroyed and rebuilt every frame. See
`doc/CHANGELOG.md` for the measured before/after on each.

**The standing tool.** `scripts/profile-pipeline` sweeps channel counts and
prints a per-stage table, simulated or against real hardware. Its `--raw-rate`
defaults to the hardware-realistic clock rather than the nominal one, because
the largest defect found here was invisible at exactly 25600 Hz -- the whole
test suite passed at 0.64 ms per call while the instrument stalled at 73.6.
A performance claim measured only against `SimulatedSensor` is not a
measurement.

### Requirements added in Phase 5

| # | Source | Requirement |
|---|--------|-------------|
| R47 | Sep 2026 | Settling indicator while the measurement chain stabilises |

### Phase 6 — Audit record, documentation revision and defect fixes (Sep 2026)

Branch `doc/revision`. The August 2026 audit report is now
`doc/audit-202608.md`, with the status of each finding on 2026-09-29. The
reference documents (README, CONTRIBUTING, CLAUDE.md, docstrings) were
revised against the code. The defects that the revision found were fixed in
the same branch. The CHANGELOG `[Unreleased]` section gives the measured
before and after for each fix.

| Date | Commit | Description |
|------|--------|-------------|
| 2026-09-29 | `c67f430` | Logs go to `~/Documents/Rev80/logs/` in every install ([X-08](audit-202608.md#x-08)) |
| 2026-09-29 | `016e610` | Each file type is checked against its own version limit (measurement file 5, monitor session 6) |
| 2026-09-29 | `0325acf` | Audit record `doc/audit-202608.md` |
| 2026-09-29 | `81441a5` | A manual burst writes each overall beside its own waveform ([S-06](audit-202608.md#s-06)) |
| 2026-09-29 | `910fedc` | A recording gets live frames only; file access is locked while it runs ([S-03](audit-202608.md#s-03)) |
| 2026-09-29 | `6d5e17e` | "Reprocess session" skips tachometer channels |
| 2026-09-30 | `b7d7a4d` | Both burst paths use `max_burst_s` and the real frame cap ([S-02](audit-202608.md#s-02)) |
| 2026-09-30 | `c4c7156` | A session with compression `'none'` records |
| 2026-09-30 | `3e1b90a` | The resource trail logs the real capture count |
| 2026-09-30 | `aa7eee3` | Headless reads `monitor.compression_level` |
| 2026-09-30 | `ff9c986` | The headless session ID uses local time ([S-10](audit-202608.md#s-10), part) |
| 2026-09-30 | `a8538f0` | The headless shutdown message is correct |
| 2026-09-30 | `21b8ea4` | Headless gives the tachometer full-accuracy limit at the achieved rate |
| 2026-09-30 | `3449161` | An anomaly burst's trigger time describes its t = 0 frame; the onset is stored separately |
| 2026-09-30 | `a94ac6c` | The GUI loads the monitor config into its widgets at startup |
| 2026-09-30 | `34cab9f` | Envelope band limit, degraded-rate text and storage estimate |
| 2026-09-30 | `3e30b2e` | The GUI refuses a stream stop while a recording runs |
| 2026-09-30 | `a9d2757` | The Welch Overlap tooltip says that the overlap has no effect |
| 2026-09-30 | `a51a26d` | An `inconsistent` or `unsteady` tachometer reading counts as no reading: the speed gate fails closed and the RPM trend does not record it |
| 2026-09-30 | `186096e` | `_dsp.band_rms` is removed; it had no caller |
| 2026-09-30 | `59bed55` | GUI sessions use `monitor.compression_level` |

### Requirements added in Phase 6

- R49: the frame-cache requirement of Phase 4, renumbered (it was a second
  R28).
- R50 to R62: the audit findings that are still open after the fixes above.
  The tracker gives each one.
- R63: verify the tachometer speed-drift limit on hardware (found in the
  documentation revision).

---

## Requirements Tracker

This table gives the current status of each requirement that is not closed
in a meeting table above. The CHANGELOG gives the story and the measured
numbers for each change.

| # | Source | Requirement | Status |
|---|--------|-------------|--------|
| R4 | Jan 2025 | Spectral smoothing | ❌ Abandoned |
| R5 | Jan 2025 | Interactive peak inspection (click a peak to identify its frequency) | ✅ Done — crosshairs on the spectrum, time-series and trend plots (`7f9b6a8`) |
| R6 | Jan 2025 | Running-speed harmonic markers on the spectrum | 🔲 TODO — the tachometer channel (R43) gives the shaft speed and a 1x marker. The harmonic overlay is not implemented |
| R7 | Jan 2025 | Bearing fault frequency markers on the spectrum | ❌ Abandoned — deferred as a future capability |
| R8 | Jan 2025 | Measurement metadata (company, machine, bearing types, running rate) | ✅ Done — measurement notes field (`2623d24`) |
| R10 | Jan 2025 | Startup and coastdown trend (luxury) | ✅ Done — trend plot with browse (`cff702e`, `142dc30`) |
| R21 | Jan 2026 | UI/UX language aligned with Alta tooling | ✅ Done — plot labels, dynamic legend, Y-axis units (`7f9b6a8`) |
| R22 | Jan 2026 | Demo screenshots for the website | 🔲 TODO |
| R24 | Mar 2026 | Multi-channel plots: phase relationship, orbit (XY), waterfall, polar. The tachometer channel (R43) is the phase reference for most of them | 🔲 TODO |
| R25 | Mar 2026 | Time-domain zoom window | ✅ Done — the time series is autoscaled to a 300 ms window (`7f9b6a8`) |
| R26 | Mar 2026 | Investigate low-frequency noise in the velocity integration | ✅ Done — integration sign fix (`afa5ce0`) and Welch window leakage fix (`3e4bb59`). The audit later found and fixed the FFT wrap leakage of the integration ([M-01](audit-202608.md#m-01)) |
| R27 | Mar 2026 | Windows packaging (exe) | ✅ Done — Rev80Setup installer (`694146d`, `rev80.iss`, `build.sh`) |
| R28 | Mar 2026 | 0-P, P-P or RMS amplitude mode, selectable for each sensor | ✅ Done (`5872cab`, `1e040d3`). Since `c2622d6` (Apr 2026) the mode is a setting of each channel (`channel_amplitude_modes`), not of each sensor |
| R31 | Aug 2026 | Rebrand vibechecker to Rev80 | ✅ Done (`62dd2c2`) |
| R32 | Aug 2026 | Anti-alias protection. In a field incident, a high-frequency bearing fault aliased into the spectrum at low power | ✅ Done — mandatory oversample, anti-alias FIR and decimation in `PicoScopeStream`; a streaming-rate watchdog; no F_max preset above what the USB stream can carry (`198050a`, `8ee940a`, `64004a3`, merge `01b5832`). Later: at least 2x oversampling (`a7cc288`, [M-03](audit-202608.md#m-03)) and a Kaiser kernel with a −111.7 dB stopband ([M-12](audit-202608.md#m-12)). The top F_max preset is 10 kHz |
| R33 | Aug 2026 | Flexible plot layout or dockable panels (for example spectrum + waveform, or trend + spectrum). Examine dearpygui window docking; if it is not available, examine panel switching or split views | 🔲 TODO |
| R34 | Aug 2026 | ISO 20816-3: evaluate machine vibration on non-rotating parts by velocity RMS over a declared band, with machine classes and Zone A/B/C/D boundaries. The band that applies depends on the machine; check the standard ([M-06](audit-202608.md#m-06), [standards table](audit-202608.md#standards-conformance)) | 🔄 Partially done — the declared band is done, with the presets 'ISO 20816 (10-1000 Hz)' and 'ISO 20816 low speed (2-1000 Hz)', and is stored with the data (CHANGELOG `round 2`). Machine-class selection, the zone display and zone alarms remain |
| R35 | Aug 2026 | ISO 2954 instrument conformance: ±10 % amplitude over 10–1000 Hz, a declared band stored with the data, a response in tolerance at the band edges, overload indication ([M-05](audit-202608.md#m-05), [M-06](audit-202608.md#m-06)) | ✅ Done — declared and stored band; high-pass knee at 0.834 × the band edge (8.34 Hz for 10 Hz); overload frames flagged and excluded. Verified offline; a hardware sweep over 10–1000 Hz is not recorded. The one hardware point at the edge, 10 Hz, read −1.05 dB (2026-08-29) |
| R36 | Aug 2026 | ISO 13373-1/-2 condition-monitoring procedures and data presentation ([standards table](audit-202608.md#standards-conformance)) | 🔲 TODO — the acquisition, channel and sensor configuration is stored with the data (measurement files v5, monitor sessions v6). Remaining: a machine and measurement-point hierarchy with routes, and a flag on a trend that mixes frames of different F_max or band settings |
| R37 | Aug 2026 | ISO 5348 mounting guidance. The mount sets the usable frequency range (stud, then adhesive, then magnet, then handheld probe; a handheld probe is not usable above about 1 kHz) | 🔲 TODO — add mounting guidance to the README. Optional: a mount-type field for each measurement, with a usable-bandwidth warning on the spectrum |
| R38 | Aug 2026 | Calibration traceability (ISO 16063). `ScopeSensor` has a datasheet sensitivity with no calibration date, method or reference | 🔲 TODO — add calibration metadata to the sensor record and store it with each measurement. A calibrated shaker check (0.1 in/s at 191 Hz, 100 mV/g sensor) put the whole chain within about 1.6 % |
| R39 | Aug 2026 | Spectral anomaly hook: fix it or remove it ([S-02](audit-202608.md#s-02), part a) | 🔲 TODO — the GUI does not offer it (`GUI_ANOMALY_HOOK_TYPES`); headless does. It tests each bin against a fixed %, but Welch uses one segment, so each noise-floor bin has a standard deviation equal to its mean, and the hook fires on healthy frames. A fix needs band RMS, a threshold in standard deviations and persistence over the declared band (R34) |
| R40 | Aug 2026 | Sensor-fault detection. A cable disconnected during a run trends a near-zero reading as a valid, healthy measurement ([capability gaps](audit-202608.md#capability-gaps)) | 🔲 TODO — IEPE bias monitoring (8–14 V) is not possible on this hardware: the coupler has a DC blocking capacitor on its output, and the 4000A ranges to ±20 V against a 24 V supply. Proposed software route, no code yet: flag a band RMS below a floor for each sensor, and the open-circuit step. Set the thresholds from measurements |
| R41 | Aug 2026 | Envelope (demodulation) analysis for rolling-element bearings ([capability gaps](audit-202608.md#capability-gaps)) | ✅ Done — `envelope.py`, the Envelope tab and automatic band selection; verified against the simulated bearing model at 125x SNR (`SimulatedSensor`). Remaining: trend and alarm on the envelope line (needs a defect rate, R6 and R24), and the band edges on the spectrum plot |
| R42 | Aug 2026 | Crest factor and kurtosis on the result card, trended and stored ([capability gaps](audit-202608.md#capability-gaps)) | ✅ Done. Remaining: no trend plot (the two trend y-axes have units and these values have none; an R33 decision) and no alarm (`FixedThresholdHook` has units; with R39) |
| R43 | Aug 2026 | Tachometer channel: shaft speed display and trend, order cursors, an Order column in the peaks table, speed-gated alarms. Out of scope: order-normalised resampling and a balancing phase reference | ✅ Done — CHANGELOG `feature/tachometer (R43)`. A channel stores edge times: about 30 values/s against 25600 samples/s. AWG loopback on a 4424A: 300–10200 RPM within ±0.2 %. Full accuracy needs about 70 samples per pulse: at 25591.8 Hz, about 21900 RPM at 1 ppr, 366 RPM at 60 ppr, 21 RPM at 1024 ppr (computed, not measured). Remaining: RPM on the trend plot (R33) |
| R44 | Aug 2026 | Tachometer support in `rev80-headless`. Before this work headless had to refuse a tachometer channel: the vibration path gives a 5 % duty pulse train at 1800 RPM an overall of 1514.9 mV, crest 5.00, kurtosis 15.94 and 63 peaks | ✅ Done — Sep 2026 (CHANGELOG `feature/tachometer — headless runs a tachometer (R44)`). Headless loads the role and calibration, `--channels` keeps the tachometer, and the summary gives the pulses/rev limits. Verified with `--device sim` at 3600 RPM |
| R45 | Sep 2026 | Motor state from the tachometer. A stopped shaft and a disconnected cable can give the same flat block | 🔲 TODO — only a parked reflector (flat at the high rail) and a shaft below the speed floor (pulses, but fewer than `min_edges_for(ppr)`, that is less than `MIN_REVS` = 2 revolutions) are distinguishable. A flat block is `no_signal`, not "stopped". A reliable "stopped" needs history: a channel that read and then ceased is a stop |
| R46 | Sep 2026 | Surface velocity from reflector size and duty cycle: v = f·L/d, with arc length L, duty d and shaft rate f | 🔲 TODO — duty cycle is captured and stored (`TachResult.duty_cycle`, `.pulse_widths_s`, v5). Remaining: a reflector-size input and the readout. The operator allows for the spot width of the sensor; the software applies no correction |
| R47 | Sep 2026 | Settling indicator. The first frame of a stream reads about 2x high on the overall, and is shown, trended and alarmed on ([S-13](audit-202608.md#s-13)) | 🔲 TODO — measure the settling time, then flag the frames in it and exclude them from the trend, baseline and alarms, as `valid_results()` does for overflow frames. Candidates: the IEPE coupler AC-coupling transient (most probable), the anti-alias FIR edge transient, the first-block high-pass state (least probable) |
| R48 | Sep 2026 | CI and release automation on GitHub Actions ([H-05](audit-202608.md#h-05)) | ✅ Done — `ci.yml` (ruff and pytest, Python 3.10–3.13, each branch push and PR) and `release.yml` (a `v*` tag: test gate, wheel, sdist, Windows installer, draft release); `4e6da3e` to `e419f5c`. The tag run for `v0.1.3` (2026-09-18) made the release with the wheel, sdist and installer. The `docs` job (PDFs, added 2026-09-28) has not run for a tag |
| R49 | May 2026 | Configurable frame cache depth, with the recording window and the total memory shown (Phase 4; numbered R28 until Sep 2026) | ✅ Done (`0a1b38c`) |
| R50 | Aug 2026 audit | The session reprocess thread races the render loop ([S-08](audit-202608.md#s-08)) | 🔲 TODO — `GUI._on_sb_reprocess` runs a thread that reloads the session into `DataCollector` and calls dearpygui, with no lock. The render-loop guard now logs the error, so the app does not stop. See R59 |
| R51 | Aug 2026 audit | Session timestamps record no UTC offset ([S-10](audit-202608.md#s-10)) | 🔲 TODO — all stored timestamps are naive local time. When a stored timestamp does not parse, `reprocess_session_trend` uses naive UTC. The session ID uses local time in both front ends since `ff9c986` |
| R52 | Aug 2026 audit | Headless must close the device on every exit path ([S-11](audit-202608.md#s-11)) | 🔲 TODO — `headless.run()` has no `try/finally` and does not call `disconnect_sensor()`, so `ps4000aCloseUnit` does not run. Ctrl+C and SIGTERM run the normal stop; an exception in the loop skips it. Not verified with a PicoScope |
| R53 | Aug 2026 audit | Range-check the acquisition parameters read from a file or config ([X-02](audit-202608.md#x-02)) | 🔲 TODO — `AcquisitionSettings.from_dict` and the `binsize` and `maxfreq` setters accept 0. The render loop logs each error and stops through `cleanup()` after 30 (`MAX_CONSECUTIVE_RENDER_ERRORS`) |
| R54 | Aug 2026 audit | Sanitise the device model name in the config file name ([X-03](audit-202608.md#x-03)) | 🔲 TODO — `config.device_filename()` keeps `/` and `..`. An attack needs hostile USB firmware |
| R55 | Aug 2026 audit | Pin and verify the build inputs ([X-04](audit-202608.md#x-04)) | 🔄 Partially done — lower bounds on the dependencies; the font comes from the tracked file. Remaining: no lockfile; the font download fallback of `scripts/fetch_font.sh` has no checksum; `drivers/install-picoscope4000a-driver.sh` has no `set -euo pipefail` and no key fingerprint check |
| R56 | Aug 2026 audit | Do not close the device handle while the poll thread is in the driver ([X-05](audit-202608.md#x-05)) | 🔲 TODO — `PicoScopeStream.stop()` joins with a 3 s timeout, then calls `ps4000aStop` in all cases. `_streaming_callback` has no upper bound check on `noOfSamples` |
| R57 | Aug 2026 audit | The logging config is in a user-writable directory on a non-admin install ([X-07](audit-202608.md#x-07)) | 🔲 TODO — `logger.py` passes `logging.yaml` to `dictConfig`, which creates any class that the file names. Relevant on shared or managed machines only |
| R58 | Aug 2026 audit | One anomaly-hook builder for both front ends ([H-01](audit-202608.md#h-01)) | 🔄 Partially done — the session factory, channel snapshot and role decision are shared. `_build_anomaly_hook` is still in `gui.py` and `headless.py`; `tests/test_anomaly_hook_build.py` checks that their defaults agree |
| R59 | Aug 2026 audit | A thread-safety contract for `DataCollector` ([H-02](audit-202608.md#h-02)) | 🔲 TODO — `collector.py` has no lock. `910fedc` removes one route (file load during a recording); R50 is another |
| R60 | Aug 2026 audit | Remove the burst-timing skips from the tests ([H-05](audit-202608.md#h-05)) | 🔲 TODO — `tests/test_monitor_session_load.py` has 10 `pytest.skip()` calls keyed on burst timing. On a slow runner they skip and the tests pass |
| R61 | Aug 2026 audit | Split `gui.py` ([H-07](audit-202608.md#h-07)) | 🔲 TODO — 5194 lines. `util.__all__` and the thread excepthook are done |
| R62 | Aug 2026 audit | Unique burst IDs ([H-08](audit-202608.md#h-08), item 4) | 🔲 TODO — the ID has one-second resolution. A second burst in the same second fails `create_group`, and headless stops on the writer error. Not reproduced |
| R63 | Doc revision | Verify the tachometer speed-drift limit on hardware | 🔲 TODO — the `SPEED_DRIFT_MAX_PCT = 1.0` table (CONTRIBUTING E14.6) has no recorded source; the `tach.py` comment says simulation only. Measure it with a controlled speed drift (AWG sweep or a load step on a real machine) and record the conditions |
| R64 | Sep 2026 | Install and run headless on a Raspberry Pi (ARM) | ✅ Done — Sep 2026 (CHANGELOG `build/arm`). dearpygui installs on x86-64 only, so `pip install .` works on a Pi 3 (Debian 13, Python 3.13). The full suite passes there with a 4824A, hardware tests included. CPU and memory for 2 to 8 channels: README, "CPU and memory on a Raspberry Pi 3" |
| R65 | Sep 2026 | Headless must refuse a burst that does not fit in memory | 🔲 TODO — a burst holds its frames in memory until it is written: 3.6 MB/s with 8 channels on a Pi 3. The default 120 s burst needs about 820 MB there, against about 650 MB free, and `max_burst_s` = 600 s needs more than 2 GB. Headless does not compare the burst size with the free memory at start. Measured with a 60 s burst only |
| R66 | Sep 2026 | Headless starts the signal generator from the device file | ✅ Done — Sep 2026 (CHANGELOG `feature/headless-siggen`). Verified with an AWG loopback tachometer at 1800 RPM on a Pi 3 and a 4824A |
| — | Future | Proximity probe support | ✅ Done — scope sensor with EU in displacement units |
| — | Future | Web portal for data sharing | ❌ Abandoned |
| — | Future | MCC DAQ tooling (USB-1608FS-Plus) | ❌ Abandoned — the PicoScope replaces the DAQ for all current use cases |

---

## Architecture Evolution Summary

| Era | Hardware | Key modules | Format |
|-----|----------|-------------|--------|
| Proto (Feb–Aug 2025) | Digiducer USB audio | monolithic | — |
| Phase 0 (Nov–Dec 2025) | Digiducer | sensor, sample, simulation, digiducer | pickle |
| Phase 1b (Jan 2026) | Digiducer | + HDF5, refactored AcquisitionSettings | HDF5 |
| Phase 2 (Mar 2026) | **PicoScope 4000A** | + picoscope, scope_sensor, scope_sensor_registry | HDF5 multi-channel |
| Phase 2a (Mar 2026) | PicoScope | + ChannelResult, multi-channel pipeline, trend | HDF5 multi-channel |
| Phase 2b (Mar 2026) | PicoScope + AWG | + signal generator, Welch controls, derived AcquisitionSettings | HDF5 + YAML config |
| Windows packaging (Mar–May 2026) | PicoScope | + `_paths.py`, `_pico_loader.py`, `build/collect_pico_dlls.py`; PyInstaller + Inno Setup pipeline | HDF5 v4 + frozen one-dir bundle |
| Phase 4 (May 2026) | PicoScope | mV-domain VibeSample, (M,5) trend, process_samples() | HDF5 v4 |
| Monitor Mode (May–Jun 2026) | PicoScope | + `monitor/` (`gate`, `controller`, `writer`, `anomaly`, `session`), `headless.py`; config split into `acquisition.yaml` + `devices/` | HDF5 v4 + one `session.h5` v5 per session |
| Rebrand → Rev80 (Aug 2026) | PicoScope | src-layout move to `src/rev80/`; `doc/` / `scripts/` / `build/` reorg | HDF5 v4; data `~/Documents/Rev80/`, config `~/.config/rev80/` |
| Anti-alias (Aug 2026) | PicoScope 4424A | `picoscope.antialias_decimate()` — mandatory oversample → Kaiser FIR → decimate; streaming-rate degradation watchdog; user-facing lowpass removed | HDF5 v4 + per-frame `degraded` flag |
| Audit round 1 — measurement validity (Aug 2026) | PicoScope | + `_dsp.py`; persistent per-channel high-pass state, Hann/Tukey-tapered integration, `nperseg = blocksize`, true (float) sample rate | HDF5 v4, overflow/degraded read back |
| Audit round 2 — integrity & diagnostics (Aug 2026) | PicoScope | + `envelope.py`, `peaks.py`; declared measurement band, crest factor / kurtosis, `GenerateBearingVibration()` oracle | HDF5 v4 + band, crest/kurtosis trends, `peak_threshold_db` |
| Spectral averaging (Aug 2026) | PicoScope | `_psd_and_overalls_for()`; power-domain averaging over N frames, above the per-frame PSD cache | HDF5 v4 unchanged — the average is a view on stored frames |
| CLI & Linux packaging (Aug 2026) | PicoScope | + `desktop.py` (XDG launcher entry + hicolor icons); unified `rev80` CLI with a `headless` subcommand; `CONTRIBUTING.md` split out; `resource_path()` fixed for non-editable installs | HDF5 v4; `data_dir()` always `~/Documents/Rev80/data`, in dev and frozen builds alike |
| Raw-stream retention (Aug–Sep 2026) | PicoScope | fixed `RAW_SAMPLERATE_HZ` acquisition rate vs. derived display rate (exactly 2.56 × `maxfreq` from Sep); `decimate_to_rate()`, `eu_scaled_raw()`, `current_frame()`, `simulation._RawRateView`, `scripts/validate-streaming-capacity` | HDF5 — every stored frame is the raw-rate capture, independent of `maxfreq` |
| Tachometer (Sep 2026) | PicoScope + optical tach | + `tach.py`, channel roles, speed gate, Tachometer tab, 1× marker, `GenerateTachPulse`/`GenerateMachineWithTach` | HDF5 **v5** — edge times, no `data` on tach channels; `session.h5` **v6** (`rpm`/`speed_ok`) |
