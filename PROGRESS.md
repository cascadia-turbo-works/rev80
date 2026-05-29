# vibechecker — Project Progress

Maps client meetings, stated requirements, and development phases from
`VibeGui Project.md` to git commits. Useful for tracking what has been
delivered and what remains.

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
| R4 | Smoothing | ❌ Not implemented |
| R5 | Interactive peak inspection | ❌ Not implemented |
| R6 | Running speed harmonics markers | ❌ Not implemented |
| R7 | Bearing fault frequency markers | ❌ Not implemented |
| R8 | Metadata: date, company, machine info, bearing types, running rate | ❌ Not implemented |
| R9 | Trend: overall vibration over time | ✅ Done — Mar 2026 |
| R10 | Luxury: startup and coastdown trend | ❌ Future |

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
| R21 | UI/UX language aligned with Alta | ❌ Ongoing |
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
| R25 | Time-domain zoom window (e.g. 5 ms) | ❌ Not implemented |
| R26 | Track down velocity integration low-frequency noise | 🔄 Partially addressed (`afa5ce0`); warrants further investigation |
| R27 | Windows packaging (exe) | ❌ Not implemented |

---

### Meeting — 2026-03-25

| # | Requirement | Status |
|---|-------------|--------|
| R28 | 0-P, P-P, RMS selectable per sensor | ✅ Done (`5872cab`, `1e040d3`) |
| R29 | Acquisition settings causing long capture times | ✅ Done — `AcquisitionSettings` now derives `samplerate`/`blocksize` from `maxfreq`/`binsize` with correct power-of-2 arithmetic (`a69f14f`) |
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
| R28 | May 2026 | Configurable frame cache depth (integer selector in Acquisition config tab) with live recording-window and total-memory derived displays |

---

## Open Requirements / Backlog

Items captured from meetings or todo lists that have not yet been implemented:

| # | Source | Requirement |
|---|--------|-------------|
| R4 | Jan 2025 | Spectral smoothing |
| R5 | Jan 2025 | Interactive peak inspection (click peak → identify frequency) |
| R6 | Jan 2025 | Running speed harmonic markers on spectrum |
| R7 | Jan 2025 | Bearing fault frequency markers on spectrum |
| R8 | Jan 2025 | Measurement metadata (company, machine, bearing types, running rate) |
| R10 | Jan 2025 | Startup / coastdown trend (luxury) |
| R21 | Jan 2026 | UI/UX language aligned with Alta tooling |
| R22 | Jan 2026 | Demo screenshots for website |
| R24 | Mar 2026 | Two-channel phase relationship display |
| R25 | Mar 2026 | Time-domain zoom window |
| R26 | Mar 2026 | Velocity integration low-frequency noise investigation |
| R27 | Mar 2026 | Windows packaging (exe) |
| — | Future | Sexy web portal for data sharing |
| — | Future | Proximity probe / DAQ integration (prox probes need only one integration step) |

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
| Phase 4 (May 2026) | PicoScope | mV-domain VibeSample, (M,5) trend, process_samples() | HDF5 v4 |
