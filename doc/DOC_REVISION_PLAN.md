# Rev80 documentation revision plan

Status: plan only. The revision work has not started. Do not commit this
file until the owner approves it.

- First version: 2026-09-29, against `main` at `f4e78fb`.
- This version: 2026-09-29, against branch `doc/revision` at `016e610`.
  It adds the owner's decisions, the audit report, and file-disjoint work
  packages for parallel agents.

Line numbers in this plan refer to `f4e78fb`, unless a line says
otherwise. Commits `c67f430` and `016e610` changed `_paths.py`,
`logger.py`, `collector.py` (from about line 1676) and the top of
`doc/CHANGELOG.md` (45 new lines). Before you edit, find each passage by
a search for its text, not by its line number.

---

## 1. Purpose

The documentation grew in patches. A reader who looks for "how does this
work now" often finds "how it used to work, and which bug that caused".
This plan:

1. moves each kind of text to one correct place;
2. removes history from reference text;
3. corrects the claims that are now false;
4. puts the August 2026 audit report under version control as
   `doc/audit-202608.md`, and removes audit IDs from the code and the
   reference documents.

The target reader is a new contributor. That reader needs, in this order:

1. What a component does, and how and when to use it. Keep this short.
2. The evidence for a choice that is not usual, when a reader can
   otherwise "fix" it incorrectly. Keep this, but put it in one place.
3. History of fixed bugs. The reader does not need this in reference
   text. It stays in `doc/CHANGELOG.md`, `doc/PROGRESS.md` and
   `doc/audit-202608.md` only.

---

## 2. Target state (the rules for every work package)

### 2.1 Where each kind of text goes

| Kind of text | Place | Form |
|---|---|---|
| API contract (units, `None` meaning, thread, call order, side effects) | Docstring | 1 line if possible. Maximum 8 lines for a function, 12 lines for a module |
| Invariant that a reader can break by a "clean-up" | Docstring or comment | 1 to 3 sentences in plain words, then a pointer to the evidence section |
| Measured table, rejected alternative, derivation | `CONTRIBUTING.md`, section "Design evidence" | One subsection for each decision, E1 to E20 |
| Operator meaning of a number, limits, configuration | `README.md` | STE prose and tables. Units on every value |
| Environment, layout, build, release, test method | `CONTRIBUTING.md` | Commands that were run |
| Agent guidance: invariants, known-bad areas, "do not" rules | `CLAUDE.md` | One line for each rule, with a pointer to CONTRIBUTING for the evidence |
| Story: what changed, why, measured before and after | `doc/CHANGELOG.md` | Keep a Changelog |
| Client requirements, meetings, status | `doc/PROGRESS.md` | R-numbered tables |
| Audit findings, their status and fixing commits | `doc/audit-202608.md` (new) | One section for each finding ID |

### 2.2 The pointer convention (approved by the owner)

Tables go to CONTRIBUTING "Design evidence". A one-line pointer with the
key number stays beside the constant. Use this form:

```python
_AA_STOPBAND_DB: float = 100.0
# Not scipy's default Hamming kernel (-60 dB measured). Evidence:
# CONTRIBUTING.md, "E2. Anti-alias kernel".
```

Rules for pointers:

- Write the section ID and title. Do not write a URL fragment.
- Keep the one number that shows why the value is not the textbook value.
  Move the table.
- Do not point from code to `doc/CHANGELOG.md` or to
  `doc/audit-202608.md` for evidence. Those files are history. Evidence
  that is still true goes in CONTRIBUTING.

### 2.3 IDs: audit findings, decisions and requirements

A new contributor does not know what "S-03" or "D-6" means. Apply these
rules:

| ID family | Where it came from | In code, README, CONTRIBUTING, CLAUDE.md | In CHANGELOG and PROGRESS |
|---|---|---|---|
| M-01 to M-14, S-01 to S-13, X-01 to X-08, H-01 to H-08, and sub-parts such as S-02a | The August 2026 audit (`doc/audit-202608.md`) | Remove. State the invariant in plain words | Keep only as a link: `[S-02](audit-202608.md#s-02)` |
| F-1 to F-9 | The vibration-engineering reviewer's numbers for M-01 to M-05 and M-08 to M-11 (section 11.3) | Remove. State the invariant in plain words | Replace with the M-number link, once. Keep "F-n" nowhere else |
| D-1, D-2, D-6 (D-3 to D-5 are not used anywhere) | Tachometer design decisions. No file defines them (question Q-1) | Remove. Use plain words: "one pulse per revolution is the default", "a tachometer channel stores edge times, not the waveform", "RMS threshold default 50 %" | Replace with plain words, unless the owner supplies a source that the repository can hold |
| R1 to R49 | `doc/PROGRESS.md` | Keep for open work only (for example R39, R45, R47), as "tracked as R39 in doc/PROGRESS.md". Remove R-numbers of closed work | Keep |

"State the invariant in plain words" means: when an ID marks a rule that
is still true, write the rule. Example: "Stop the monitor before you
close the device, because the writer thread is a daemon and loses queued
captures at exit." Do not write "see S-01".

Before this revision there are 160 ID occurrences of the M, S, X, H, F
and D families in `src/rev80/`, `tests/`, `README.md`, `CONTRIBUTING.md`
and `CLAUDE.md` (13 in `CLAUDE.md`, 7 in `gui.py`, 3 to 6 in several
tests). The target is 0.

### 2.4 What to delete from docstrings and comments

Delete these, after you confirm that the CHANGELOG or the audit file
records them (section 7):

- Paragraphs that contain "This used to", "previously", "was replaced",
  "until Sep 2026", "the old default", "audit found".
- The same rationale when it occurs in more than one place. Keep one copy
  and point to it (section 5.13).
- "Why this module exists" sections that tell the story of a defect.
  Replace with one sentence that says what the module does.

### 2.5 Which audit content goes into the reference documents

Most audit findings are fixed bugs. They stay in `doc/audit-202608.md`
and the CHANGELOG only. Document a finding in README, CONTRIBUTING or
CLAUDE.md only when it drives a design that is special to this
repository. These do:

| Design in the code now | Audit source | Goes to |
|---|---|---|
| Amplitude tests are off-bin, phased, with the high-pass on | M-13, M-01 | CONTRIBUTING "Testing"; CLAUDE.md one line |
| Hann taper and Tukey overlap-save for integration | M-01 | E9 |
| The frequency axis uses the achieved rate | M-02 | E5 |
| Oversample and Kaiser anti-alias filter; F_max top preset 10 kHz | M-03, M-12 | E1, E2, E6 |
| Stateful high-pass, seeded from the block mean | M-04 | E8 |
| Overflow and degraded frames: shown, but not trended, averaged or alarmed on; flags stored and read back; one channel writer | M-05 | CONTRIBUTING 4.3 and 4.5; README 6.2 |
| Declared band; knee below the band edge | M-06, ISO 2954 row | README 5.3; E8.3 |
| Spectrum shown only to F_max | M-11 | README 5.1; E11 |
| Spectral hook not offered in the GUI | M-02 of "Fix these first" | E16.2; tracked as R39 |
| Shutdown order: monitor, then device, then GUI context | S-01 | CONTRIBUTING 4.6; CLAUDE.md |
| Bounded writer queue that drops, burst cap, frames and results trimmed together | S-02 | CONTRIBUTING 4.6; E17; CLAUDE.md |
| One factory for monitor sessions; the remaining copied hook builder | H-01 | CONTRIBUTING 4.7; CLAUDE.md |
| A sensor-library read failure never becomes an overwrite | X-01 | CONTRIBUTING 4.8 |
| Every thread death and hard crash reaches the log | H-07 (excepthook part) | CONTRIBUTING 4.6 |

Everything else in the audit stays out of the reference documents.

### 2.6 ASD-STE100 rules to apply

Apply these rules to all new and revised text, including CHANGELOG,
PROGRESS and the audit file where you rewrite.

1. Write one topic in each sentence.
2. Maximum 20 words in a procedural sentence. Maximum 25 words in a
   descriptive sentence.
3. Maximum 6 sentences in a paragraph.
4. Use the active voice. Use the present tense for facts about the code.
5. In procedures, write one instruction in each step. Start the step with
   a verb in the imperative.
6. Put a warning or a caution before the step it applies to.
7. Use one term for one thing. Use the terminology list in 2.7.
8. Do not use "-ing" forms as nouns or as adjectives where a simple verb
   or noun is possible.
9. Give a unit with every number, including shaft speed.
10. Do not use vague words: "much", "very", "several", "robust",
    "significant", "simply". Give the number.
11. Say how a value was measured: hardware (give the model), AWG
    loopback, or `SimulatedSensor`.

Code identifiers, file names and standard titles are technical names.
STE permits them. Do not reword them.

### 2.7 Terminology list

| Use | Do not use | Meaning |
|---|---|---|
| raw rate | acquisition rate, hardware rate, fixed rate | `raw_samplerate`, nominal 25600 Hz, achieved about 25591.8 Hz on a 4824A |
| display rate | spectrum rate, analysis rate | `samplerate` = 2.56 x `maxfreq` |
| achieved rate | true rate, actual rate, real rate | the rate the driver reports back |
| block | chunk, buffer (for this meaning) | the samples of one channel for one frame |
| frame | capture (for this meaning) | one block from each enabled channel, same time window |
| capture | snapshot | a frame that Monitor Mode stores on the interval |
| burst | event capture | consecutive frames that Monitor Mode stores after a trigger |
| declared band | measurement band, analysis band | `band_fmin` to `band_fmax` |
| band edge | cutoff (for `highpass_fc`) | the frequency where the response is still inside tolerance |
| knee | cutoff, corner | the -3 dB frequency of the Butterworth design |
| tachometer channel | tach input, speed channel | a channel with role `'tachometer'` |
| shaft speed | RPM (as a noun), running rate | the value; write the unit separately |
| no signal | stopped (for a missing reading) | the tach block has no usable pulses |
| stopped | no signal | the shaft does not turn (not detectable today, R45) |
| overall | overall level, broadband value | band amplitude of one channel |
| finding | issue, defect ID | one numbered item of the audit |

---

## 3. Measurements (before)

### 3.1 Method

- Docstrings: Python `ast`, `ast.get_docstring()` on the module and on
  every `FunctionDef`, `AsyncFunctionDef` and `ClassDef`.
- Comments: `tokenize`, `COMMENT` tokens. A "block" is 6 or more
  consecutive comment lines.
- History markers: a line that matches "used to", "previously", "no
  longer", "until Aug/Sep", "retired", "reverted", a month and 2026, an
  audit ID or an R-number. This is a lower bound.
- The scripts are outside the repository, in
  `/tmp/claude-1000/-home-hgg-Documents-reveng-vibration-rev80/b5958310-595c-4da5-8a4d-d63f194c1b1f/scratchpad/`:
  `measure.py <dir>`, `hist.py <dir> ...`, `dump.py <file> <min-lines>`.
  If that directory is not available, section 13.2 gives an equivalent
  one-line check.

### 3.2 Totals (at `f4e78fb`)

| Scope | Files | Lines | Docstrings | Docstring lines | Docstring words | Comment lines | Comment blocks >= 6 lines |
|---|---|---|---|---|---|---|---|
| `src/rev80/` | 29 | 16368 | 379 | 2582 | 18843 | 2618 | 94 (1145 lines) |
| `tests/` | 44 | 12702 | 547 | 2083 | 16544 | 851 | 10 (84 lines) |

Distribution of docstring length in `src/rev80/`:

| Length | Count |
|---|---|
| 1 line | 165 |
| 2 to 5 lines | 46 |
| 6 to 14 lines | 124 |
| 15 to 29 lines | 34 |
| 30 lines or more | 10 |

Function and class docstrings longer than 8 lines: 71 in `src/rev80/`,
16 in `tests/`. Module docstrings longer than 12 lines: 8 in
`src/rev80/`, 20 in `tests/`.

Markdown files:

| File | Lines | Words |
|---|---|---|
| `README.md` | 1093 | 9330 |
| `CONTRIBUTING.md` | 349 | 2111 |
| `CLAUDE.md` | 358 | 5778 |
| `doc/PROGRESS.md` | 358 | 5959 |
| `doc/CHANGELOG.md` | 2177 (2222 at `016e610`) | 23818 |
| `doc/VibeGui Project.md` | 325 | raw client notes |
| `.claude/agents/technical-writer.md` | 131 | agent prompt |
| `.claude/agents/vibration-engineer.md` | 125 | agent prompt |
| Audit report (HTML, not in the repository) | 529 lines as text | 6095 |

Longest `PROGRESS.md` table rows: 2357, 2289 and 1898 characters (R43,
R44, R32).

### 3.3 Modules, largest documentation first

| Module | Lines | Docstring lines | Comment lines | Blocks >= 6 (lines) | History-marker lines | Audit-ID occurrences |
|---|---|---|---|---|---|---|
| `gui.py` | 5173 | 385 | 508 | 9 (70) | 21 | 7 |
| `collector.py` | 2211 | 394 | 398 | 17 (174) | 11 | 3 (+3 F, 3 D) |
| `picoscope.py` | 1165 | 155 | 346 | 11 (203) | 7 | 0 |
| `tach.py` | 737 | 262 | 196 | 11 (145) | 6 | 1 (+1 D) |
| `sample.py` | 686 | 191 | 194 | 9 (128) | 11 | 2 (+2 F) |
| `util.py` | 802 | 57 | 221 | 11 (124) | 5 | 1 |
| `peaks.py` | 383 | 153 | 106 | 5 (81) | <5 | 0 |
| `simulation.py` | 545 | 80 | 136 | 6 (77) | 6 | 2 (+1 D) |
| `monitor/anomaly.py` | 537 | 138 | 17 | 0 | <5 | 1 |
| `monitor/controller.py` | 520 | 68 | 74 | 2 (15) | 7 | 4 |
| `_dsp.py` | 216 | 116 | 24 | 2 (22) | <5 | 0 |
| `headless.py` | 783 | 79 | 59 | 2 (13) | 5 | 2 |
| `config.py` | 432 | 77 | 59 | 1 (6) | <5 | 2 |
| `_profile.py` | 259 | 71 | 40 | 2 (16) | <5 | 1 |
| `envelope.py` | 163 | 52 | 34 | 1 (8) | <5 | 0 |
| `monitor/writer.py` | 389 | 23 | 48 | 1 (6) | <5 | 1 (+1 D) |
| `monitor/session.py` | 154 | 53 | 14 | 1 (7) | <5 | 1 |
| `logger.py` | 219 | 50 | 15 | 0 | 5 | 4 |
| `icons.py` | 92 | 8 | 39 | 1 (36) | <5 | 0 |
| others (10 files) | 1102 | 229 | 124 | 3 (21) | <5 | 6 |

### 3.4 The 15 longest docstrings in `src/rev80/`

| Lines | Words | Location | Main content |
|---|---|---|---|
| 155 | 1338 | `tach.py:1` module | 6 evidence tables, one-pulse-per-revolution rationale, stale rate figures |
| 50 | 434 | `peaks.py:1` module | defect story, rejected alternatives |
| 46 | 361 | `collector.py:46` `decimate_to_rate` | contract (8 lines), 512821-tap defect story and table |
| 43 | 303 | `_profile.py:1` module | defect story, overhead table, usage |
| 40 | 241 | `monitor/anomaly.py:78` `RmsThresholdHook` | parameters, omega-cubed table, old default |
| 38 | 263 | `_dsp.py:1` module | wrap-error table, taper choice |
| 36 | 332 | `peaks.py:184` `_running_median` | edge-bias defect, 4-way comparison table |
| 32 | 258 | `collector.py:506` `_seed_zi` | seed-from-mean table (measured at 8333.25 Hz) |
| 32 | 227 | `collector.py:452` `filter_block` | stateful rule, `sosfiltfilt` rejection, table |
| 30 | 257 | `envelope.py:1` module | bearing physics (README material), chain |
| 29 | 233 | `config.py:354` `channel_role_state` | three rules, drift story |
| 28 | 249 | `monitor/anomaly.py:33` `valid_results` | three exclusion reasons |
| 28 | 239 | `picoscope.py:834` `_choose_osr` | old expression story, resonance argument |
| 28 | 222 | `monitor/controller.py:167` `burst_frame_cap` | defect story, memory table |
| 25 | 203 | `sample.py:302` `samplerate` | `nextpow2` story, 5-smooth rates |

### 3.5 Targets (after)

| Measure | Before | Target |
|---|---|---|
| `src/rev80/` docstring lines | 2582 | 1000 or fewer |
| `src/rev80/` comment lines | 2618 | 1400 or fewer |
| `src/rev80/` comment blocks >= 6 lines | 94 | 20 or fewer (tables of values, for example `UNIT_TO_SI`, are permitted) |
| Function and class docstrings > 8 lines in `src/rev80/` | 71 | 0, except where section 5 permits it with a reason |
| Module docstrings > 12 lines | 8 (`src`), 20 (`tests`) | 0 |
| History-marker lines in `src/rev80/` | 106 or more | 0 |
| ID occurrences (M, S, X, H, F, D) in code and reference docs | 160 | 0 |
| `tests/` docstring lines | 2083 | 1300 or fewer |
| `CLAUDE.md` | 358 lines, 5778 words | 200 lines or fewer |
| `README.md` | 1093 lines | about 1000 lines, internals removed, operator content added |
| `CONTRIBUTING.md` | 349 lines | about 1100 lines (it receives the evidence) |
| Stale claims listed in section 4 | about 60 items | 0 |

The line counts are guides, not goals. Do not delete a contract to reach
a number.

---

## 4. Stale and conflicting claims (verified against the code)

Each item was checked at `f4e78fb`. Section 4.8 lists the changes from
`c67f430` and `016e610`. Each item is assigned to one work package in
section 12.

### 4.1 Rate-dependent figures from the 40000 Hz period

`MIN_SAMPLES_PER_PULSE = 70` is a count of samples. The front ends
compute the limit from the achieved rate (`gui.py:929-931`,
`headless.py:351-352`). The text still gives the values for 41666.5 Hz.
At 25591.8 Hz, 70 samples for each pulse is a pulse rate of 366 Hz.

| Pulses/rev | Text says | Correct at 25591.8 Hz |
|---|---|---|
| 1 | 36000 RPM | about 21900 RPM |
| 6 | 6000 RPM | about 3660 RPM |
| 60 | 600 RPM | about 366 RPM |
| 1024 | 35 RPM | about 21 RPM |

Places: `tach.py:89-93`, `tach.py:135-136`, `tach.py:310-314`,
`README.md:616-617`, `CLAUDE.md` (Key modules and Tachometer sections),
`doc/PROGRESS.md` R43, `doc/CHANGELOG.md` entry of 2026-09-18.

Other figures from the 40000 Hz period:

- `tach.py:33-36`: raw rate 40000 Hz, achieved 41666.5 Hz, 12 us
  interval. Now: 25600 Hz nominal, about 25591.8 Hz achieved, 12.5 ns
  grid (`picoscope.py:767-800`, `sample.py:50`).
- Storage ratio of tach edge times: `collector.py:146` and `CLAUDE.md` say
  "~30 float64 per second against 41666". Now 25600 samples, a ratio of
  about 850, not 1400. Also `doc/PROGRESS.md` R43 and
  `tests/test_tach_persistence.py:4`.
- `tests/test_simulation_tach.py:21`: `RAW_FS = 40000.0` is "what
  `_RawRateView` presents". `_RawRateView` presents `raw_samplerate`
  (25600 Hz). Correct the comment. Do not change the value in a
  documentation commit.
- `sample.py:39-42`: "the app-rate block arrives at 25641 Hz". The
  clock-grid snap changed that to 25591.8 Hz.

### 4.2 `CLAUDE.md`

| Line or section | Says | Code says |
|---|---|---|
| 27 | run tests "from vibegui/ directory" | repository root |
| 30, and `CONTRIBUTING.md:175` | `pytest tests/test_vibechecker.py::test_save` | no such test; pytest runs nothing. Use `test_save_load_roundtrip` (`tests/test_vibechecker.py:123`) |
| Commands | "those 9 tests" in `test_picoscope_hw.py` | 27 tests collected |
| Architecture diagram | `receive_data` does "mV -> EU"; GUI calls `VibeSample.process()` | the sample stays in mV (`collector.py:826`); `VibeSample` has no `process()` method |
| Data flow, 2nd bullet | the high-pass "is applied later, in `process_sample()`" | `receive_data` applies it, stateful, once for each frame (`collector.py:820`). `process_sample` filters again only on replay or after a filter-config change |
| Several | "32-frame ring cache" | the dataclass default is 32 (`config.py:31`), but `acquisition.yaml` seeds 15 (`config.py:85`), and the GUI (`gui.py:3645`) and headless (`headless.py:523`) load it |
| Tachometer section | "~30 float64 per second against 41666"; "600 RPM at 60 ppr" | see 4.1 |
| 91, logger row | "rotating log files written to `log/`"; "`log/faulthandler.log`" | `~/Documents/Rev80/logs/` in every install (`c67f430`) |

### 4.3 `README.md`

| Line | Says | Code says |
|---|---|---|
| 89 | `--from-file` takes "a v4 single-measurement .h5 file or a v5 monitor session" | measurement files v5 (`collector.py:1465`), sessions v6 (`monitor/writer.py:17`) |
| 197, 285 | headless writes "v5" `session.h5` | v6 |
| 364 vs 49, 759, 844, 927 | `cache_frames: 15` in the YAML example; "default 32" in four places | a seeded install uses 15 |
| 378, 517 | `rms_pct: 10.0`, table default 10.0 | 50.0 in all code paths (`config.py:108`, `anomaly.py:122`, `headless.py:157`, `gui.py:2998`). Tell the operator that an `acquisition.yaml` seeded before the change still holds 10.0, and the file value wins |
| 469, 770 | logs go to `log/` in development | `~/Documents/Rev80/logs/` in every install (`c67f430`) |
| 502 | "Hook: RMS / Spectral / Both" selector | the GUI offers RMS only (`util.py:772`); headless accepts all three (`headless.py:143-167`) |
| 616-617 | 6000 RPM at 6 ppr, 600 RPM at 60 ppr | see 4.1 |
| 702 | default source `GenerateBearingVibration_TemporalMethod` | `GenerateBearingVibration` (`simulation.py:456`) |
| 693-700 | generator table, 4 entries | also `GenerateBearingVibration`, `GenerateTachPulse`, `GenerateMachineWithTach` |
| 726-728 | diagram: `receive_data` does "mV -> EU" and "Butterworth HP + LP" | no EU conversion at ingestion; no user low-pass |
| 776 | `ScopeSensor` holds "amplitude mode" | per channel (`scope_sensor.py:15-18`) |
| 804 | storage cost tracks `maxfreq` | stored frames are raw-rate; lines 1000-1003 are correct |
| 813 | converts "via `adc2mV()`" | `_adc_to_mv()`; `picoscope.py:339-373` forbids `adc2mV` |
| 840-842 | `receive_data` "Converts mV -> engineering units" | stays mV |
| 941 | `sample.samplerate  # int` | `float` (`sample.py:526`) |
| 973 | spectrum goes to Nyquist; `maxfreq` "does not crop" | cropped at `maxfreq` (`collector.py:1140`) |
| 1009-1025 | "Manual saves (v4 format)" layout | v5; `CLAUDE.md` Persistence layout matches `collector.py:1501-1594` |
| 1039-1054 | session `file_version=5`; frame attributes | v6; also `band_json`, `scalars_json`, `rpm`, `speed_ok` (`monitor/writer.py:272-285`, `331-342`) |
| 1079 | "Up to 5 open attempts" | `_MAX_OPEN_ATTEMPTS = 2` (`picoscope.py:52`) |
| 1081 | overflow log "once per 2 s per channel" | once for each channel for each stream, re-armed when clipping stops or settings change (`picoscope.py:924-949`, `1058`) |
| 1086 | `pip install picosdk` | a pinned git-URL dependency in `pyproject.toml`; `pip install .` installs it |
| 65-101 | CLI reference | omits `--profile`, `--autodetect/--no-autodetect` |

### 4.4 `CONTRIBUTING.md`

| Line | Says | Fact |
|---|---|---|
| 7-15 | table of contents | omits "Automated releases" |
| 131-133 | `assets/rev80.svg`, `assets/rev80.ico` | `assets/icons/rev80.svg`, `assets/icons/rev80.ico`; line 197 is correct |
| 139 | `tests/test_monitor_index.py` | does not exist |
| 114-156 | project layout | omits 20 of 29 modules and most test files |
| 162 | suite "runs in ~50 s" | not measured; 1195 tests collected at `f4e78fb`, more after `c67f430` and `016e610` |
| 175 | `test_vibechecker.py::test_save` | does not exist |
| 292 | "Four things about it" | five bullets follow |

### 4.5 Docstrings, comments and help text

| Location | Says | Fact |
|---|---|---|
| `collector.py:186-198` `DataCollector` | `receive_data` does "mV->EU conversion"; consumers "use self.callbacks" | no conversion; no `callbacks` attribute |
| `collector.py:773-777` `receive_data` | "Applies per-channel mV->EU sensitivity conversion" | it does not |
| `collector.py:1467-1489` `save_data` | "(v4 format)"; `/trend/rel_times` shared, `/trend/{ch}/data` | v5; `/trend/{ch}/rel_times`, `/trend/{ch}/orders`, `/tach_trend`, tach datasets |
| `headless.py:1-7` | "the same v5 format" | v6 |
| `headless.py:708-713` `--help` | interval default "from device config or 3600", pre-buffer 60 s, burst 60 s | from `acquisition.yaml`, fallback 600 s, 30 s, 120 s (`headless.py:513-517`) |
| `logger.py:182-189` `resolve_version` | "_version.py is written by the pre-commit hook" | `setuptools_scm` writes it; the hook runs ruff only |
| `util.py`, amplitude-mode TODO | refers to `VibeSample.process()` | the path is `DataCollector.process_sample()` |
| `picoscope.py:417-436` `PicoScopeStream` | "configure channel A"; "matches sounddevice.InputStream"; "blocksize-worth" | multi-channel; no `sounddevice`; `raw_blocksize` |
| `picoscope.py:439-452` `__init__` | config "provides samplerate, blocksize" | `raw_samplerate`, `raw_blocksize` |
| `tests/test_measurement_validity.py:15-16` | "see BRANCH-NOTES.md" | no such file. Point to `doc/audit-202608.md` for the finding text |

### 4.6 `doc/PROGRESS.md` (owner decisions applied)

- R28 is used twice. R28 stays with "0-P, P-P, RMS selectable per sensor"
  (meeting 2026-03-25). Cache depth (Phase 4, line 268) becomes **R49**,
  with the note "Numbered R28 until Sep 2026." Add both to the
  Requirements Tracker.
- R26: the current status is **Done**. The tracker is correct.
- Meeting tables: a status column there is a snapshot on the meeting
  date. Keep it. Where the tracker has a later status, add "(status on
  this date; see tracker)". The tracker is the single source of current
  status. This applies to R5, R8, R10, R21, R25, R26, R27 at least.
- R34: status **Partially done**. The declared band is done. Machine-class
  selection and the Zone A/B/C/D display and alarms remain.
- R35: status **Done**, with the note "Verified offline; a hardware sweep
  over 10 to 1000 Hz is not recorded."
- R43: correct the rate figures (4.1).
- R44: the requirement text says "Headless currently must refuse". Make
  the text a past-tense requirement; the status is Done.
- R45: "fewer than MIN_EDGES". The gate is `MIN_REVS` (`tach.py:237`).

### 4.7 `doc/CHANGELOG.md`

- There is no `[0.1.2]` section, and there will be none (owner decision:
  the v0.1.2 release build failed; the same content was released as
  0.1.3). Add one line under `[0.1.3]`: "Tag v0.1.2 was not released:
  its build failed on the Windows runner. 0.1.3 contains the same
  content." Do not add a section.
- Header style differs: `## [0.1.0] - 2026-09-01` and
  `## [0.0.1] — early prototype`.
- Two sections have no date: `refactor/event-pipeline (develop)` and
  `feature/picoscope`.
- Subsection names vary: "Measured", "Notes", "Verified electrically",
  "Where it stands now", "Not done, deliberately", "The rule tying live
  and replay together", "Decisions, each pinned by a test", "Still open",
  "Reverted", "Refactored".
- Audit IDs appear as bare text (for example "M-06", "S-02", "F-4").
  Convert them to links (section 2.3).

### 4.8 Changes on `doc/revision` since the first plan

- `c67f430`: `log_dir()` returns `~/Documents/Rev80/logs/` in every
  install. `faulthandler.log` follows. This resolves the first plan's
  corroboration request C-1. Stale now: `README.md` 469-470 and 770,
  `CLAUDE.md` logger row (4.2, 4.3). It also closes audit finding X-08
  for logs (data moved earlier; section 11.3).
- `016e610`: `_restore_metadata(f, max_version=None)`; the session
  loaders pass the writer's version (6). The spurious "File version 6 is
  newer" warning is gone. This item is closed.
- Both commits added entries under `[Unreleased]` in the CHANGELOG. The
  CHANGELOG packages include them.

---

## 5. Changes for each module

Legend: (a) API contract, keep and make short; (b) evidence or
rationale, move to a "Design evidence" section, or keep 1 to 3 lines;
(c) history of a fixed defect, delete (it is in the CHANGELOG or the
audit file); (d) duplicate, delete and keep one copy.

In every module, also remove the IDs of section 2.3. Where the ID marks
a rule that is still true, write the rule.

### 5.1 `tach.py` (262 docstring lines, 196 comment lines)

- Module docstring (155 lines): replace with 6 to 8 lines. Say what the
  module does, that it has no dearpygui, h5py or `DataCollector`
  imports, that all levels are mV, and that `rpm` is `None` and never
  `0.0` when there is no reading.
  - "What is measured, and where" (high-pass bypass, 31 to 108 edges):
    (b) to E14.1.
  - "Timing budget": delete the 40000 Hz text. Move the AWG-loopback
    accuracy table to E14.2, labelled "measured at 41666.5 Hz achieved
    rate, 2026-09-01". Add the result of 2026-09-18 at 25.6 kHz (27
    hardware tests pass at +/-0.2 %).
  - "Sub-sample interpolation" (3-regime table, divide-by-zero note,
    1461.7 mV minimum): (b) to E14.3. Correct the RPM ceilings (4.1).
  - One-pulse-per-revolution section: (b) to E14.4. Replace "D-6" with
    plain words. Keep a 2-line statement at `TachSettings.pulses_per_rev`.
  - "Not built, deliberately" (inferring pulses/rev): (b) to E14.4.
  - Block-length floor text: (d) with `slowest_rpm_for`. Delete.
- `MIN_PULSE_AMPLITUDE_MV` comment (23 lines): keep 2 lines and the
  pointer. Table and the rejected span/MAD test to E14.5.
- `INTERVAL_SPREAD_MAX`, `SPEED_DRIFT_MAX_PCT`: keep 2 lines each. Tables
  to E14.6 (the 93.8 % figure exists only here). Keep the note that
  `SPEED_DRIFT_MAX_PCT` is set from simulation only.
- `MIN_REVS` comment (31 lines): keep 3 lines. Table to E14.4. Delete
  the `MIN_EDGES = 3` history.
- `slowest_rpm_for`: keep the binsize table (API contract;
  `tests/test_tach.py:465-472` checks the same values). Delete the prose
  that repeats the module docstring.
- `MIN_SAMPLES_PER_PULSE`: keep 3 lines. State the unit. Delete the RPM
  figures.
- `estimate_rpm` (19 lines): keep the contract. Median against
  first-to-last (0.15 RPM against 62.09 RPM) to E14.7.

### 5.2 `peaks.py` (153 docstring lines, 106 comment lines)

- Module docstring (50 lines): keep 4 lines. Corpus evidence and
  "tested and rejected" to E12.1.
- `FLOOR_MEDIAN_WIDTH_BINS` comment (30 lines): keep 2 lines. Tuning to
  E12.2.
- `median_to_mean_ratio` (20 lines): keep the contract and the 5-value
  table. Delete the `nperseg == blocksize` paragraph.
- `_running_median` (36 lines, plus a 24-line comment): keep 3 lines.
  Edge-bias table and the 4-way comparison to E12.3. The 0.8 ms speed
  table to E19. Keep the 3-line `2*half+1` comment.
- `local_noise_floor`, `select_peaks`, `peak_distance_bins`: keep the
  contracts. Remove cross-references that repeat the module text.

### 5.3 `collector.py` (394 docstring lines, 398 comment lines)

- `decimate_to_rate` (46 lines): keep 8 lines. "Bounding the ratio" and
  its table to E7. Delete the `limit_denominator` story.
- `role_of_sample`: keep 3 lines.
- `_write_channel_group`: keep "one writer for both file types; tach
  channels store `edge_times`, no `data`". Delete the "previously two
  functions" story. Correct the storage ratio (4.1). Replace "D-2".
- `DataCollector`, `receive_data`: rewrite (4.5).
- `highpass_knee_hz`: keep 2 lines and a pointer to E8.3.
- `filter_block`, `_seed_zi`: keep the stateful/stateless contract (6
  lines in total). Tables and the rejected `sosfiltfilt` and warm-up pass
  to E8.1 and E8.2, with their conditions (4424A, 447.3 Hz loopback,
  8333.25 Hz, 10 Hz high-pass). Replace "F-4".
- `update_trend`, `current_frame`, `speed_ok`, `eu_scaled_raw`: 2 to 5
  lines each. `speed_ok`: keep "fails closed" and "the one place the
  gate is evaluated". Delete the copied-hook paragraph; point to
  `valid_results`.
- `save_data`: delete the stale layout. Point to README "Data files".
- `_restore_metadata` (changed by `016e610`): check that its new
  docstring follows 2.1.
- Comment blocks at 900, 934, 1024, 1049, 1144, 1176, 1859 (11 to 20
  lines each): classify in the package. Replace "F-5", "F-9".

### 5.4 `picoscope.py` (155 docstring lines, 346 comment lines)

- Header comment (lines 1-5): remove "replaces sounddevice.InputStream".
- Import-guard comment (20-27): keep 3 lines. Delete "used to be fatal".
- `STREAMING_CEILING_HZ` block (68-101): keep 3 lines and a pointer.
  Findings and the 40/50/100 kHz table to E1.
- Anti-alias kernel block (306-338): keep 2 lines. Table to E2.
- ADC-to-mV block (339-373): keep 4 lines ("do not use `adc2mV`; keep
  the operation order; `tests/test_adc_conversion.py` checks it"). Speed
  table to E3. Remove "see CHANGELOG".
- Clock-grid block in `_start_streaming` (753-800): keep 5 lines. Probe
  table to E4.
- `PicoScopeStream`, `__init__`: rewrite (4.5).
- `_set_max_resolution`: keep.
- `_choose_osr` (28 lines): keep 4 lines. Mounted-resonance argument to
  E6. Delete the old-expression story.
- `_report_samplerate` (19 lines): keep 4 lines. The 98.3 Hz example to
  E5.

### 5.5 `sample.py` (191 docstring lines, 194 comment lines)

- `RAW_SAMPLERATE_HZ` comment (14-49): keep 5 lines. Hardware table to
  E1. Delete "History". Correct the 25641 Hz figure.
- `AcquisitionSettings` docstring: keep. Delete "unchanged from before
  this split" and "no longer".
- Field comments 92-160: one line each. Spectral averaging statistics to
  README 5.4. Delete the band history (it is in the audit file, M-06).
  Speed-gate argument to E20.
- `samplerate`, `blocksize`, `nperseg`, `n_fft_bins`: 2 to 4 lines each.
  Delete the `nextpow2` and "previously" stories. "Every preset rate is
  5-smooth and divides the raw rate" to E11. Replace "F-8", "F-9".
- `VibeSample` field comments: keep "store as float" and one line why.
- `ChannelResult` field comments: one line each.
- `one_x_amplitude`: keep.

### 5.6 `_dsp.py` (116 docstring lines)

- Module docstring (38 lines): keep 6 lines. Wrap-error table to E9.
  Delete "why the pre-existing test suite never caught this".
- `butter_knee_for_edge`: keep the formula and the 0.834 result (6
  lines). "Safe only because the overall is band-limited" to E8.3.
- `band_rms`: keep 6 lines.

### 5.7 `envelope.py` (52 docstring lines)

- Module docstring: the bearing physics duplicates `README.md:638-642`.
  Keep the 4-step chain (8 lines).
- `suggest_band`: keep 6 lines.

### 5.8 `simulation.py` (80 docstring lines, 136 comment lines)

- Pacing comment (135-137): delete.
- Bearing model block (142-171): keep a 6-line list of the 4 physical
  properties. "Pure-tone generators are not an oracle" goes to
  CONTRIBUTING "Testing" (it is a test rule, audit M-14).
- `DEFAULT_RESONANCE_Q` block: keep 3 lines ("Q = 8, not the textbook
  40: at 40 kurtosis reads 3.08 against a healthy 3.09"). Table to E15.
- `GenerateMachineWithTach`, `GenerateTachPulse`: keep the contracts.
  Replace "D-6".

### 5.9 `util.py` (57 docstring lines, 221 comment lines)

- `MAXFREQ_PRESETS` block: keep 2 lines. Delete the 20 kHz and 50 kHz
  history.
- `ISO_BAND_PRESETS` block: operator content to README 5.3. Keep 2
  lines. The comment cites ISO 20816-1; README and PROGRESS cite
  20816-3. State which part defines the band.
- Amplitude-mode TODO: correct (4.5).
- Channel-roles block: keep 2 lines.
- `GUI_ANOMALY_HOOK_TYPES` block: keep 3 lines and "tracked as R39".
  Statistics to E16.2.

### 5.10 `gui.py` (385 docstring lines, 508 comment lines)

- `apply_tach_claim` and `_on_tach_channel_change`: same text twice.
  Keep 5 lines on `apply_tach_claim`. Make the other one line.
- `_schedule_status_timeout`: keep 2 lines.
- `_update_fft_peaks_table`: keep 3 lines. Widget-count evidence to E19.
- `_update_env_fmax_warning`, `_update_envelope_plot`,
  `_envelope_on_screen`: 3 to 5 lines each. Keep "fails open".
- `_discover_devices`: keep (thread rule).
- `cleanup`: keep the order and the guard rule, 5 lines. Replace "S-01".
- Helper near `gui.py:130`: keep "Never duplicate the formula".
- 9 comment blocks, 21 history-marker lines, 7 audit IDs: apply 2.3 and
  2.4.
- Caution: see risk R-3 about strings that tests search for.

### 5.11 `monitor/` and `headless.py`

- `anomaly.valid_results` (28 lines): keep 8 lines. The omega-cubed
  argument to E20. Keep "the only place the speed gate is applied; do
  not add it to `_build_anomaly_hook`, which is still copied in
  `gui.py` and `headless.py`".
- `RmsThresholdHook` (40 lines): parameter list, 12 lines. Table to
  E16.1. Delete "the default was 10 %".
- `SpectralThresholdHook`: add "Not offered in the GUI; tracked as R39."
- `controller.burst_frame_cap` (28 lines): keep 4 lines. Table to E17.
  Replace "S-02a", "S-02b".
- `controller.capped_burst_end`: keep 2 lines.
- `writer._frame_speed`: keep.
- `session.channel_snapshot_for`, `session.session_from`: 4 lines each.
- `headless.py` module docstring: v6. Delete the usage block.
- `headless._apply_channel_config`: keep 5 lines.
- `headless._persist_channel_override`: keep.
- `headless` `--help` strings: correct (4.5).

### 5.12 Smaller modules

- `config.channel_role_state` (29 lines): keep the three rules (9 lines).
- `_profile.py` module (43 lines): keep usage and the two rules (10
  lines). Overhead table to E18.
- `logger.py`: `thread_exception_handler`, `install_excepthooks`: 3
  lines each. Correct `resolve_version` (4.5). Remove "H-07", "X-05",
  "H-03".
- `_pico_loader._drivers_dir`: keep 4 lines. Remove "X-06".
- `_paths.py`: the module docstring and `log_dir` were revised in
  `c67f430`. Check them against 2.1. Remove "X-06" from `project_path`.
- `scope_sensor_registry._load_user`: keep the two rules.
- `sensor._simulate_tach_sources`: keep 5 lines.
- `scope_sensor.py`, `desktop.py`, `gate.py`, `icons.py`, `__main__.py`,
  `__init__.py`: apply 2.3 and 2.4. `icons.py:16` holds a 36-line
  comment block; read it in the package.

### 5.13 Known duplicates (keep one copy)

| Text | Places now | Keep in |
|---|---|---|
| Pulse train through the vibration path: 1515 mV, crest 5.00, kurtosis 15.94, 63 peaks | `util.py:270`, `gui.py:178`, `gui.py:812`, `headless.py:224`, `CLAUDE.md` (2x), PROGRESS R44 | E14.1; one-line pointer in `util.py`; `CLAUDE.md` one line |
| High-pass overshoot: 31 to 108 edges, 1800 RPM reads 6270 | `tach.py:17-29`, `collector.py:808-812`, `CLAUDE.md` (2x) | E14.1; the 2-line comment at `collector.py:808` |
| 3.2 % speed change moves the overall 10 % | `sample.py:98`, `anomaly.py:33`, `anomaly.py:78`, `README.md:570`, `CLAUDE.md` | README 7 (operator view); E20 (table) |
| Tachometer claim policy | `gui.py:178`, `gui.py:812`, `CLAUDE.md` | `gui.apply_tach_claim` |
| "Do not add the speed gate to `_build_anomaly_hook`" | `collector.speed_ok`, `anomaly.valid_results`, `CLAUDE.md` | `anomaly.valid_results`; `CLAUDE.md` |
| HDF5 measurement layout | `collector.save_data`, `README.md:1009`, `CLAUDE.md` | README 13; `CLAUDE.md` points to it |
| Envelope physics | `envelope.py:1`, `README.md:638` | README 8 |
| One pulse per revolution rationale | `tach.py` module, `MIN_REVS`, `README.md:593`, `CLAUDE.md`, CHANGELOG | E14.4, README 7, CHANGELOG |

### 5.14 `tests/`

Test docstrings say what the test proves and why the stimulus is not
degenerate. Keep that. Rules:

1. Keep what is asserted, and why the input is off-bin, phased or
   otherwise realistic.
2. Delete defect stories. One sentence is enough when history explains
   why an assertion changed.
3. Keep "revert-checked: fails with X without the fix".
4. Remove the IDs of section 2.3. `tests/test_measurement_validity.py`
   has 50 F-number references; replace each with the plain-words
   property the test checks.
5. Do not change assertion values, test names or test logic. Text only.

Known items:

- `tests/test_measurement_validity.py`: replace the "BRANCH-NOTES.md"
  reference (4.5). Keep "off-bin, phased, high-pass enabled". Keep 3
  lines of the `DEFAULT_PHASE` comment.
- `tests/test_tach.py`: `HW_FS = 41666.5` and the "4.166 % trap" text
  describe the 40000 Hz period. Correct the comment to say the value is
  a non-nominal rate used to catch code that reads the constant. Do not
  change the value.
- `tests/test_picoscope_hw.py:342`: keep 3 lines.
- `tests/test_peak_selection.py:641`, `:691`: "the docstring's error
  table" becomes "CONTRIBUTING.md, E12.3".
- `tests/test_tach.py:467`: the table stays in `slowest_rpm_for`. No
  change.
- 16 test files have module docstrings of 15 lines or more. Cut each to
  5 lines or fewer.
- Source-inspection tests: see risk R-3.

---

## 6. New outlines for `README.md` and `CONTRIBUTING.md`

### 6.1 `README.md` (end-user manual and vibration-engineering discussion)

The README is also the wheel's long description.

| # | Heading | Content source |
|---|---|---|
| 1 | Rev80 | lines 1-9. Add "What the numbers are, and where they stop being trustworthy", with links to section 6 |
| 2 | Install | |
| 2.1 | Windows | lines 201-211 |
| 2.2 | Linux and macOS (pip) | lines 223-259, 298, corrected |
| 2.3 | Linux desktop entry | lines 300-328 |
| 2.4 | Where Rev80 keeps its files | lines 213-219 and 466-469. One table for all install types: data `~/Documents/Rev80/data/`, logs and `faulthandler.log` `~/Documents/Rev80/logs/` (`c67f430`), config by OS |
| 3 | Quick start | new: connect, set F_max and bin size, read the result card, save. Verified steps only |
| 4 | The GUI | new short tour. Source: `gui.py` labels. Mark which settings have a widget and which are YAML-only (`max_burst_s`) |
| 5 | Measurement settings | |
| 5.1 | F_max, bin size, frame length and lines | lines 876-898 (operator parts); the spectrum stops at F_max |
| 5.2 | Units, amplitude modes and integration | lines 58-59, 853, 991-994 |
| 5.3 | Declared band and the high-pass edge | lines 42, 50, 896, 905; `util.py` ISO band comment; ISO 2954, ISO 20816 |
| 5.4 | Spectral averaging | line 897; `sample.py` averaging comment |
| 5.5 | Peaks | lines 55, 854, 898 |
| 6 | Reading the results | |
| 6.1 | Overall, crest factor and kurtosis | lines 54, 855-856 |
| 6.2 | Frames that are not used: overflow, degraded, out of speed window | `CLAUDE.md` data-flow bullets; `anomaly.valid_results` |
| 6.3 | Missing readings: `--`, not 0 | `CLAUDE.md` tach bullets; README 163 |
| 6.4 | Accuracy and limits | new table: each measured accuracy, how it was measured, date. Sources: tach +/-0.2 %; calibrated shaker 1.6 % (PROGRESS R38); anti-alias -111.7 dB; clock -320 ppm; band edge 10 Hz -1.05 dB on hardware (CHANGELOG round 2) |
| 7 | Tachometer | lines 551-632, corrected (4.1) |
| 8 | Envelope analysis | lines 634-665 |
| 9 | Monitor Mode | lines 473-547, corrected; storage estimate; speed gate |
| 10 | Headless datalogger | lines 110-197 and 261-296, merged |
| 11 | Configuration files | lines 332-464, corrected; one table of every key with unit, default, and "widget or YAML-only" |
| 12 | Command reference | from `--help` output |
| 13 | Data files | lines 998-1062, corrected to v5 and v6, from `CLAUDE.md` Persistence. State "branch on the presence of `data`" |
| 14 | Signal generator | lines 669-683 |
| 15 | Simulated sensor | lines 687-702, corrected, user view |
| 16 | Troubleshooting | new: `PICO_NOT_FOUND` until replug, driver not found, SmartScreen, an old `acquisition.yaml` with `rms_pct: 10.0` |

Move out of README, to CONTRIBUTING section 4: "Architecture"
(706-759), "Module Reference" (763-791), "Data Pipeline" (795-868),
"AcquisitionSettings" API tables (872-929, except operator meaning),
"VibeSample and ChannelResult" (933-973), "ScopeSensor" API (977-994),
"PicoScope Integration" (1066-1089).

### 6.2 `CONTRIBUTING.md` (developer guide and design evidence)

| # | Heading | Content source |
|---|---|---|
| 1 | Development environment | lines 19-42 |
| 2 | Moving the checkout | lines 46-76 |
| 3 | Project layout | lines 112-156, corrected and complete; one module table from `README.md:763-791` and `CLAUDE.md` Key modules; add `doc/audit-202608.md` |
| 4 | Architecture | |
| 4.1 | Threads and data flow | `README.md:706-759`, `CLAUDE.md` diagram, corrected |
| 4.2 | Two sample rates | `CLAUDE.md` "AcquisitionSettings interdependencies"; `AcquisitionSettings` docstring |
| 4.3 | The measurement chain, stage by stage | `README.md:795-868`, corrected; `CLAUDE.md` data-flow bullets; validity flags (2.5) |
| 4.4 | Tachometer channels in the pipeline | `CLAUDE.md` "Tachometer channels" (code parts) |
| 4.5 | Persistence internals | `CLAUDE.md` Persistence; one channel writer; flags stored and read back |
| 4.6 | Monitor Mode internals | `CLAUDE.md` Monitor Mode; queue bounds, burst cap, shutdown order, crash evidence (2.5) |
| 4.7 | Shared logic between the GUI and headless | `CLAUDE.md` copied-hook text; shared factories; the one remaining copy |
| 4.8 | How configuration is loaded | `config.py`; which value wins; 15 against 32 frames; sensor-library read rule (2.5) |
| 4.9 | Internal data structures | `README.md:933-994` |
| 5 | Design evidence | Each subsection: decision, value, table, "Measured on" line (hardware, serial, date, or simulation), rejected alternatives |
| E1 | Streaming ceiling and the raw rate | `picoscope.py:68-101`, `sample.py:14-49`, CHANGELOG 2026-09-09 |
| E2 | Anti-alias kernel | `picoscope.py:306-338` |
| E3 | ADC-to-mV conversion | `picoscope.py:339-373` |
| E4 | Sample-clock grid | `picoscope.py:753-800` |
| E5 | Report the achieved rate | `picoscope._report_samplerate` |
| E6 | Oversampling ratio | `picoscope._choose_osr` |
| E7 | Resample ratio bound | `collector.decimate_to_rate` |
| E8 | High-pass filter: stateful (E8.1), seed from mean (E8.2), knee below the edge (E8.3) | `collector.filter_block`, `_seed_zi`; `_dsp.butter_knee_for_edge` |
| E9 | Tapers for integration | `_dsp.py` module |
| E10 | Band RMS | `_dsp.band_rms` |
| E11 | Display rate, block size and line count | `sample.samplerate`, `blocksize`, `nperseg`, `n_fft_bins` |
| E12 | Peak selection (E12.1 method, E12.2 floor width, E12.3 edge handling, E12.4 window nulls) | `peaks.py` |
| E13 | Envelope band search | `envelope.suggest_band` |
| E14 | Tachometer (E14.1 no high-pass, E14.2 accuracy, E14.3 interpolation, E14.4 one pulse per revolution and `MIN_REVS`, E14.5 signal floor, E14.6 spread and drift limits, E14.7 median estimator) | `tach.py` |
| E15 | Simulation model constants | `simulation.py:142-200` |
| E16 | Anomaly thresholds (E16.1 RMS 50 %, E16.2 spectral hook statistics) | `anomaly.RmsThresholdHook`, `util.py:758-771` |
| E17 | Burst memory | `controller.burst_frame_cap` |
| E18 | Profiler overhead | `_profile.py` module |
| E19 | GUI render cost | `gui._update_fft_peaks_table`, `peaks._running_median` speed table |
| E20 | Speed gate | `sample.py:94-101`, `anomaly.valid_results` |
| 6 | Testing | lines 160-191, corrected; the test rules from `CLAUDE.md` "Working on this codebase"; off-bin testing and why (2.5); why pure-tone generators are not an oracle; hardware tests (27) and AWG loopback; source-inspection tests (R-3) |
| 7 | Profiling | `CLAUDE.md` "Profiling" |
| 8 | Rendering docs to PDF | lines 80-108 (delete 105-108, history) |
| 9 | Replacing the app icon | lines 195-209, corrected |
| 10 | Building the Windows installer | lines 213-275 |
| 11 | Automated releases | lines 279-349 ("five things") |
| 12 | Documentation rules | section 2 of this plan, short form |

---

## 7. Evidence that the CHANGELOG already holds

Before you delete a history paragraph from code, search the CHANGELOG
and the audit file for its key number.

| Key number | In CHANGELOG | In code only |
|---|---|---|
| 512821-tap FIR, 73.62 ms | yes | |
| `adc2mV` 201x to 382x | yes | |
| Q = 40 | yes | |
| `medfilt` zero-pad bias | yes | |
| x[0] seed, +4297 % | yes | |
| `sosfiltfilt` 35-45 % | yes | |
| wrap error +4473 % | yes (also audit M-01) | |
| ~164 widget operations | yes | |
| `threading.Timer` | yes | |
| 13025 ns probe | yes | |
| 6270 RPM | yes | |
| 547752 RPM noise edges | yes | |
| 2.76x burst retention | yes | |
| 1461.7 mV interpolation minimum | | yes: move to E14.3 |
| 93.8 % peak height at 1 % drift | | yes: move to E14.6 |

A table of evidence that is still true goes to CONTRIBUTING even when
the CHANGELOG also has it. The docstring keeps neither.

---

## 8. CHANGELOG and PROGRESS revision approach

### 8.1 `doc/CHANGELOG.md`

1. Do not change facts, numbers, dates or commit hashes. Change
   structure and language only.
2. Normalize version headers to `## [x.y.z] - YYYY-MM-DD`.
3. Add the one-line v0.1.2 note under `[0.1.3]` (4.7). No section.
4. Give each branch section a date. For the two undated sections, use
   the merge date from `git log`, and record the source.
5. Map subsection names to `Added`, `Changed`, `Removed`, `Fixed`,
   `Notes for the next person`. Put "Measured" and "Verified
   electrically" content inside the entry it measures.
6. Convert audit IDs to links: `[M-06](audit-202608.md#m-06)`. Convert
   F-1 to F-9 to their M-numbers (11.3) and link them. Replace D-1, D-2,
   D-6 with plain words (unless Q-1 gives a source).
7. Apply the STE rules (2.6). Keep the technical names.
8. Where an entry gives a figure that is now wrong for the current code
   (the 2026-09-18 RPM ceilings), keep the figure and add a dated
   correction line under it.

### 8.2 `doc/PROGRESS.md`

1. Apply the owner decisions in 4.6.
2. Cut each tracker row to 1 to 3 sentences of requirement and status.
   Move the story to the CHANGELOG (most of it is there) and link to
   the CHANGELOG section. Target: no row longer than 600 characters.
3. Keep exactly five pipes in each 4-column tracker row.
4. Where a requirement came from the audit (R34 to R42, R47), link the
   finding: `[M-06](audit-202608.md#m-06)`.
5. Do not change `doc/VibeGui Project.md`. It is the client's raw notes.
6. The first plan proposed an ID register in PROGRESS. The audit file
   (section 11) replaces it.

---

## 9. `CLAUDE.md` revision

Target: 200 lines or fewer. It stays agent guidance.

Keep:

- What Rev80 is (3 lines), and "green CI is not evidence of measurement
  correctness" (2 lines).
- Commands, corrected (4.2).
- A one-line module map. Point to CONTRIBUTING section 3.
- Invariants, one line each, with a pointer to the evidence section:
  two rates and "use the achieved rate"; the high-pass is causal and
  stateful in `receive_data`; the declared band edge is not the knee;
  averaging in the power domain; crest factor and kurtosis never
  averaged; tachometer channels skip the high-pass and yield no
  `ChannelResult`; `rpm` is `None`, never `0.0`; the speed gate is only
  in `valid_results()` and fails closed; per-channel dicts must be in
  `AcquisitionSettings.copy()`; no `_fm`/`_df` writes; `_paths.py` for
  all paths; readers branch on `data`.
- Known-bad areas, in plain words: the copied `_build_anomaly_hook`;
  R39; R45; R47; the shutdown order; the bounded queue and burst cap.
  No audit IDs.
- The evidence rule (approved): "Measure before you choose a constant.
  Put the table in CONTRIBUTING.md, Design evidence. Put a one-line
  pointer with the key number beside the constant."
- Build and release facts that are not guessable. Point to CONTRIBUTING.
- One line: "The August 2026 audit is `doc/audit-202608.md`. Do not cite
  its IDs in code."

Remove or move:

- Measured numbers beyond one for each invariant: to CONTRIBUTING.
- "(This passage claimed the opposite until Sep 2026.)" notes: keep them
  only for the version hook and `VibeSample` in mV. Remove them in the
  next revision.
- Persistence layout, config file table: point to README.
- Profiling section: to CONTRIBUTING section 7. Keep two one-line rules.

---

## 10. Other `.md` files

- `.claude/agents/technical-writer.md`: change the document table row
  "Docstrings beside constants: the measurement table that justifies the
  value" to the approved rule (2.2). Add rows for
  `doc/audit-202608.md` and CONTRIBUTING "Design evidence". Add the ID
  rule (2.3). Approved by the owner.
- `.claude/agents/vibration-engineer.md`: change "a constant is
  justified by a measurement recorded next to it" to the approved rule.
  Add: "The August 2026 audit is `doc/audit-202608.md`." Approved.
- `doc/VibeGui Project.md`, `.pytest_cache/README.md`, `doc/plans/`: no
  change.
- `pyproject.toml` comments are outside the scope. They hold history.

---

## 11. The audit file `doc/audit-202608.md` (new)

### 11.1 Source

- HTML report: `/tmp/claude-1000/-home-hgg-Documents-reveng-vibration-rev80/b5958310-595c-4da5-8a4d-d63f194c1b1f/scratchpad/audit-202608.html`
  (67235 bytes).
- A text extract is beside it: `audit.txt` in the same directory.
- Report data: 2026-08-28, `develop` at `7bf4712`, 7.0k lines of source,
  3.4k lines of tests, 291 tests passing. Three reviewers: senior
  engineering, security, vibration engineering. 6 critical, 14 high, 19
  medium, 12 low. 43 numbered findings: M-01 to M-14, S-01 to S-13,
  X-01 to X-08, H-01 to H-08.

Caution: the scratch directory is temporary. The package that makes the
audit file must run first, or the coordinator must copy the HTML into
the worktree before the package starts.

### 11.2 Structure of the file

```
# Rev80 instrument audit, August 2026
  Scope and method (branch, commit, date, reviewers, counts)
  How to read this file (status values; line numbers are at 7bf4712)
  Summary table: ID | title | severity | status | fixed by
  ## The finding that reframes the rest (on-bin tests)
  ## Reproduced evidence (the M-01 table)
  ## Measurement validity
  ### M-01
  **FFT wrap leakage corrupts every integrated overall and waveform.**
  Severity, location at 7bf4712, finding text, measured numbers,
  proposed fix, Status, Fixed by
  ...
  ## Stability and data loss (S-01 ... S-13)
  ## Security (X-01 ... X-08)
  ## Structure, tooling and documentation (H-01 ... H-08)
  ## Capability gaps (each with its R-number)
  ## Standards conformance (table, with a "Now" column)
  ## What was sound
  ## Other numbering used for these findings (F-1 to F-9)
```

Rules:

- Make each finding heading the bare ID (`### M-01`), so the anchor is
  `#m-01`. Put the title in bold on the next line. CHANGELOG and
  PROGRESS links depend on this form.
- Keep every measured number and every code location from the report.
  Label the locations "at 7bf4712".
- Rewrite prose in STE where you rewrite. Do not change a number.
- Status values: `Fixed`, `Partly fixed`, `Open (R-nn)`, `Open (not
  tracked)`, `Accepted` (only if the owner says so).
- "Fixed by": commit hash and CHANGELOG section title. Find them with
  `git log --all --oneline --grep=<ID> -E`, with the CHANGELOG, and for
  F-numbered items with the `fix/measurement-validity` section. Confirm
  each by the fix commit's diff, not by the commit message only.

### 11.3 Status map (first pass, from the CHANGELOG and the code)

The package must confirm each row. "Verify" means: the first pass found
no fix, but did not prove that the finding is open.

| ID | Other ID | Status (first pass) | Evidence |
|---|---|---|---|
| M-01 | F-1 | Fixed | CHANGELOG `fix/measurement-validity`; merge `b4a67dc` |
| M-02 | F-2 | Fixed | same; later clock-grid snap (`experimental/profiling`) |
| M-03 | F-3 | Fixed | same; top preset 10 kHz |
| M-04 | F-4 | Fixed | same, including the seed-from-mean follow-up |
| M-05 | F-5 | Fixed | same |
| M-06 | | Fixed | CHANGELOG round 2; merge `76e8f9f` (`fix/declared-band`) |
| M-07 | | Fixed | CHANGELOG `chore/config-consistency-ci` (`monitor/controller.py:258`); merge `ebaa6f9` |
| M-08 | F-6 | Fixed | `fix/measurement-validity` |
| M-09 | F-7 | Fixed | `fix/measurement-validity` |
| M-10 | F-8 | Fixed | `fix/measurement-validity` |
| M-11 | F-9 | Fixed | `fix/measurement-validity` |
| M-12 | | Fixed | CHANGELOG round 2 (Kaiser, -111.7 dB) |
| M-13 | | Fixed | `fix/measurement-validity` root-cause text; `tests/test_measurement_validity.py` |
| M-14 | | Fixed | CHANGELOG round 2; merge `d59470f` (`test/bearing-oracle`) |
| S-01 | | Fixed | CHANGELOG `fix/stability-cluster`; `ae576e2`; merge `e8e24a3` |
| S-02 | | Fixed | `fix/stability-cluster`; merge `e8e24a3`; `max_burst_s` read from config in the 2026-09-21 entry |
| S-03 | | Verify; probably open (not tracked) | `gui.py:1318`: `on_results` is gated on `is_recording` only. No CHANGELOG entry found |
| S-04 | | Fixed | `chore/config-consistency-ci` |
| S-05 | | Fixed | `chore/config-consistency-ci` |
| S-06 | | Verify; probably open (not tracked) | manual path `monitor/controller.py:153` sets `[[]] * pretrigger`; the anomaly path at `:431` adds the trigger frame's results. The CHANGELOG `feature/monitor_mode` mentions earlier alignment fixes, before the audit |
| S-07 | | Fixed | `chore/config-consistency-ci` |
| S-08 | | Verify | no CHANGELOG entry found; see `gui._on_sb_reprocess` |
| S-09 | | Fixed | `fix/measurement-validity` |
| S-10 | | Verify; probably open (not tracked) | `headless.py:554` uses UTC for the session ID; `monitor/controller.py:132` and `:321` use local time |
| S-11 | | Verify | `headless.py` shows `stop_stream()` at 678; no `finally` found by search |
| S-12 | | Fixed | CHANGELOG round 2 |
| S-13 | | Open (R47) | R47 settling indicator |
| X-01 | | Fixed | `chore/config-consistency-ci` |
| X-02 | | Fixed | `fix/stability-cluster` |
| X-03 | | Verify | `config.device_filename` (`config.py:149-156`) |
| X-04 | | Partly fixed | lower bounds in `pyproject.toml`; font checksum (`build/ci`); driver script has no `set -euo pipefail` |
| X-05 | | Verify; probably partly fixed | `fix/stability-cluster` mentions it; `picoscope.py:567-568` still joins with a 3 s timeout |
| X-06 | | Fixed | `chore/config-consistency-ci`; later `_paths.project_path` |
| X-07 | | Open (not tracked) | nothing found |
| X-08 | | Fixed | data: `hotfix/cli-ux-refactor` (`data_dir()` always `~/Documents/Rev80/data`); logs: `c67f430` |
| H-01 | | Partly fixed | three copied pairs extracted (2026-09-21 entries); `_build_anomaly_hook` is still copied |
| H-02 | | Open (not tracked) | no lock in `collector.py` |
| H-03 | | Fixed | hook repaired (`chore/config-consistency-ci`); version from `setuptools_scm` (`fix/stability-cluster`) |
| H-04 | | Fixed | `chore/config-consistency-ci` |
| H-05 | | Partly fixed | CI added (`chore/config-consistency-ci`, R48); conditional skips remain in `tests/test_monitor_session_load.py:200-356` |
| H-06 | | Fixed, then this revision | `CLAUDE.md` rewrites; `build/ci` entry |
| H-07 | | Partly fixed | `threading.excepthook` (`fix/stability-cluster`); `__all__` (`chore/config-consistency-ci`); `gui.py` is not split (5173 lines) |
| H-08 | | Partly fixed | `copy()` (round 2), `utcnow`, amplitude-scale fallback, `.python-version`: fixed. Burst ID of one-second resolution (`monitor/controller.py:135`, `:413`): verify |

Capability gaps map to R-numbers: envelope analysis R41 (done); IEPE
bias R40 (not possible on this hardware); crest factor and kurtosis R42
(done); band alarms R39 and R34; tachometer R43 (done), R6, R24; ISO
zones R34; phase, orbit, waterfall R24.

---

## 12. Work packages

### 12.1 How the packages are cut

The coordinator runs packages in parallel, each in its own git worktree.
To make that safe, each package **owns** its files. No two packages in
the same wave write the same file.

Evidence from the code packages must reach `CONTRIBUTING.md`, which one
package owns. So the code packages write their evidence into their own
staging files, `doc/_staging/evidence-<package>.md`. Package W2-A moves
the staging text into CONTRIBUTING and deletes `doc/_staging/`.

Each code package does three jobs on its files in one pass: correct the
stale claims (section 4), trim and move (section 5), and remove IDs
(section 2.3). One commit for each package. A package can use two
commits if the reviewer asks for it.

### 12.2 Common inputs and rules for every package

- Read sections 2, 4 and 13 of this plan. Read the section for your
  package.
- Base commit: `016e610` on `doc/revision`.
- Do not start the GUI. Do not create a dearpygui viewport.
- Do not edit a file that your package does not own. If you find an error
  in another file, write it in your report.
- In the commit message body: before and after measurements, and
  `path:line` for each claim you kept or moved.
- End the commit message with the attribution line that the coordinator
  gives.

### 12.3 Common verification commands

Run from the worktree root.

```bash
ruff check src/ tests/

# Parallel worktrees: do not run the hardware tests. Two runs compete for
# an attached scope and fail. The final package runs the full suite once.
pytest tests/ -q --ignore=tests/test_picoscope_hw.py

# IDs left in the files you own (expect no output):
grep -nE '\b[MSXH]-[0-9]{2}[a-c]?\b|\bF-[1-9]\b|\bD-[1-6]\b' <your files>

# History left in the files you own (expect no output, or only lines you
# can justify in the report):
grep -niE 'used to|previously|no longer|until (aug|sep)|the old |was (replaced|removed|retired)' <your files>

# Docstring size (scratch scripts; see 3.1):
python3 <scratch>/measure.py src/rev80
```

Equivalent size check when the scratch scripts are not available:

```bash
python3 -c "import ast,sys;[print(p,n.lineno,len(d.splitlines())) for p in sys.argv[1:] for n in [t:=ast.parse(open(p).read())]+[x for x in ast.walk(t) if isinstance(x,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef))] if (d:=ast.get_docstring(n)) and len(d.splitlines())>8]" <your .py files>
```

### 12.4 Waves

| Wave | Packages (parallel inside the wave) | Starts when |
|---|---|---|
| 1 | W1-AUD, W1-C1, W1-C2, W1-C3, W1-C4, W1-C5, W1-C6, W1-T1, W1-T2, W1-RM, W1-CT, W1-PR, W1-AG | at once |
| 2 | W2-A, W2-CL, W2-LOG1 | all of wave 1 is merged |
| 3 | W3-LOG2 | W2-LOG1 is merged |
| 4 | W4-LOG3 | W3-LOG2 is merged |
| 5 | W5-FIN | all packages are merged |

W2-A and W2-CL can run in parallel with the CHANGELOG chain (LOG1 to
LOG3), because they own different files.

### 12.5 File ownership (wave 1)

| Package | Owns (writes) |
|---|---|
| W1-AUD | `doc/audit-202608.md` (new) |
| W1-C1 | `src/rev80/picoscope.py`, `src/rev80/sample.py`, `src/rev80/_pico_loader.py`, `doc/_staging/evidence-C1.md` |
| W1-C2 | `src/rev80/collector.py`, `src/rev80/_dsp.py`, `doc/_staging/evidence-C2.md` |
| W1-C3 | `src/rev80/tach.py`, `doc/_staging/evidence-C3.md` |
| W1-C4 | `src/rev80/peaks.py`, `src/rev80/envelope.py`, `src/rev80/simulation.py`, `src/rev80/util.py`, `doc/_staging/evidence-C4.md` |
| W1-C5 | `src/rev80/monitor/*.py`, `src/rev80/headless.py`, `src/rev80/config.py`, `src/rev80/sensor.py`, `doc/_staging/evidence-C5.md` |
| W1-C6 | `src/rev80/gui.py`, `src/rev80/_profile.py`, `src/rev80/logger.py`, `src/rev80/_paths.py`, `src/rev80/scope_sensor.py`, `src/rev80/scope_sensor_registry.py`, `src/rev80/desktop.py`, `src/rev80/icons.py`, `src/rev80/__main__.py`, `src/rev80/__init__.py`, `doc/_staging/evidence-C6.md` |
| W1-T1 | `tests/test_measurement_validity.py`, `tests/test_declared_band.py`, `tests/test_spectral_averaging.py`, `tests/test_peak_selection.py`, `tests/test_sample.py`, `tests/test_acquisition_settings.py`, `tests/test_display_rate.py`, `tests/test_antialias.py`, `tests/test_adc_conversion.py`, `tests/test_diagnostic_scalars.py`, `tests/test_envelope.py`, `tests/test_bearing_oracle.py`, `tests/test_picoscope.py`, `tests/test_picoscope_hw.py`, `tests/test_one_x.py`, `tests/test_rotation_units.py` |
| W1-T2 | every other file in `tests/` |
| W1-RM | `README.md` |
| W1-CT | `CONTRIBUTING.md` |
| W1-PR | `doc/PROGRESS.md` |
| W1-AG | `.claude/agents/technical-writer.md`, `.claude/agents/vibration-engineer.md` |

Nobody owns `CLAUDE.md` or `doc/CHANGELOG.md` in wave 1.

### 12.6 Package briefs

#### W1-AUD: create `doc/audit-202608.md`

- Inputs: section 11; the HTML report and `audit.txt`; `doc/CHANGELOG.md`;
  `git log`.
- Tasks:
  1. Convert the report to Markdown with the structure in 11.2.
  2. For each of the 43 findings, confirm the status and the fixing
     commits (11.3). Read the diff of each fix commit.
  3. Add the F-1 to F-9 map and the capability-gap R-numbers.
  4. Add a "Now" column to the standards table.
- Done when: 43 finding sections exist with headings `### M-01` to
  `### H-08`; each has a Status and a "Fixed by" or R-number; every
  number from the report is present.
- Verify:
  - `grep -cE '^### [MSXH]-[0-9]{2}$' doc/audit-202608.md` prints 43.
  - `grep -c 'Status' doc/audit-202608.md` is 43 or more.
  - For 10 numbers chosen from the report (for example 4473.8, 1.73,
    8.99, 131072, 15536, 3.74, 2049, 820, 2 GB, 291), grep the new file.
  - No "Verify" status is left. If a status stays uncertain, write
    "Open (not tracked)" and list it in the report for the owner.

#### W1-C1: acquisition code

- Inputs: 4.1, 4.5 (`picoscope.py` rows), 5.4, 5.5, 5.12
  (`_pico_loader.py`); E1-E6 and E11 in 6.2.
- Tasks: correct, trim, move, remove IDs. Write E1-E6 and E11 in
  `doc/_staging/evidence-C1.md`, with the E headings exactly as in 6.2.
- Done when: no docstring in the owned files is longer than 8 lines
  (module: 12), except `AcquisitionSettings`; each moved table is in the
  staging file with a "Measured on" line; each constant with evidence
  has a pointer (2.2).
- Verify: 12.3.

#### W1-C2: processing code

- Inputs: 4.1 (storage ratio), 4.5 (`collector.py` rows), 5.3, 5.6;
  E7-E10 in 6.2.
- Tasks: as W1-C1. Staging: `evidence-C2.md` (E7, E8.1-E8.3, E9, E10).
- Caution: `collector.py` changed in `016e610`. Line numbers after about
  1676 differ from this plan.
- Done when and verify: as W1-C1.

#### W1-C3: tachometer code

- Inputs: 4.1, 5.1; E14 in 6.2.
- Tasks: as W1-C1. Staging: `evidence-C3.md` (E14.1-E14.7). Label every
  table with the rate at which it was measured.
- Done when: the module docstring is 8 lines or fewer; no RPM figure
  that depends on the rate is left in the code.
- Verify: 12.3, and `grep -n '41666\|40000\|600 RPM\|36000' src/rev80/tach.py`
  prints nothing.

#### W1-C4: peaks, envelope, simulation, util

- Inputs: 5.2, 5.7, 5.8, 5.9, 4.5 (`util.py` row); E12, E13, E15 and the
  `_running_median` part of E19 in 6.2.
- Tasks: as W1-C1. Staging: `evidence-C4.md`. Put the `_running_median`
  speed table under the heading "E19. GUI render cost (part from
  peaks.py)".
- Done when and verify: as W1-C1.

#### W1-C5: monitor and front-end logic

- Inputs: 4.5 (`headless.py` rows), 5.11, 5.12 (`config.py`,
  `sensor.py`); E16, E17, E20 in 6.2.
- Tasks: as W1-C1. Staging: `evidence-C5.md`. Correct the `--help`
  strings. Then run `rev80 headless --help` and compare.
- Caution: risk R-3. Do not write `MonitorSession(`, `max_burst_s=600.0`,
  `'max_burst_s':       600.0,` or `info.get('role')` anywhere in
  `headless.py`. Do not add a comment that contains `session_from(`,
  `required_cache_frames(` or `channel_role_state(`.
- Done when and verify: as W1-C1, and
  `pytest tests/test_session_from.py tests/test_headless_tach.py -q`
  passes.

#### W1-C6: GUI and support modules

- Inputs: 4.5 (`logger.py` row), 5.10, 5.12; E18 and the GUI part of
  E19.
- Tasks: as W1-C1. Staging: `evidence-C6.md`. Remove the audit IDs from
  `gui.py` (7), `logger.py` (4) and the other owned files.
- Caution: risk R-3 applies to `gui.py`, as in W1-C5.
- Done when and verify: as W1-C1, and
  `pytest tests/test_session_from.py tests/test_headless_tach.py tests/test_app_lifecycle.py -q`
  passes.

#### W1-T1 and W1-T2: test docstrings

- Inputs: 5.14; 2.3; the E titles in 6.2 (for pointers).
- Tasks: cut docstrings and comments; replace IDs with the property that
  the test checks; correct 4.1 and 4.5 items in the owned files.
- Done when: no module docstring is longer than 5 lines; no ID is left;
  no assertion, name or logic changed.
- Verify: 12.3, and `git diff --stat` shows only the owned files, and
  `git diff -U0 | grep -E '^[-+][^-+#"]' | grep -vE '^\s*[-+]\s*("""|#)'`
  shows no code line change (read every line it prints).

#### W1-RM: README

- Inputs: 4.1, 4.3, 4.8; 6.1; 2.5.
- Tasks: correct every 4.3 item; restructure to 6.1; remove the internal
  sections (they arrive in CONTRIBUTING through W1-CT, which reads them
  from the base commit); write the new operator sections (Quick start,
  GUI tour, Accuracy and limits, Troubleshooting, key table).
- Caution: GUI claims cannot be checked by a GUI run. Trace each label
  in `gui.py`. Write "not verified on screen" in the report for each.
- Done when: the outline in 6.1 exists; no 4.3 claim remains; every
  command was run or is marked as not run.
- Verify: `rev80 --help`, `rev80 headless --help` against section 12;
  the stale-claim grep in W5-FIN step 1 over `README.md`.

#### W1-CT: CONTRIBUTING

- Inputs: 4.4; 6.2; 2; the base versions of `README.md` (sections to
  move) and `CLAUDE.md` (architecture, persistence, monitor, profiling,
  test rules).
- Tasks: sections 1 to 4 and 6 to 12 of 6.2. Create section 5 "Design
  evidence" with each E heading and the line "Filled by package W2-A."
  Do not write evidence text.
- Done when: the outline exists; no 4.4 claim remains; every command was
  run or is marked as not run.
- Verify: run each command in sections 1, 2, 6, 8 that runs on Linux
  without hardware; `pytest --collect-only -q | tail -1` for the test
  count.

#### W1-PR: PROGRESS

- Inputs: 4.1 (R43), 4.6, 8.2; the planned anchor form `#m-01` (11.2).
- Tasks: apply 4.6 and 8.2.
- Done when: R49 exists; R28 has one meaning; row length 600 characters
  or fewer; audit links in the planned form.
- Verify: the five-pipe check in W5-FIN step 5;
  `awk -F'|' '/^\| R/{if(length($0)>600)print NR}' doc/PROGRESS.md`
  prints nothing.

#### W1-AG: agent prompts

- Inputs: 10; 2.2; 2.3.
- Tasks: the edits in section 10.
- Done when: both prompts state the approved evidence rule and name
  `doc/audit-202608.md`.
- Verify: read both files once. They are agent context; keep the
  frontmatter unchanged (`git diff` shows no change above the second
  `---`).

#### W2-A: assemble Design evidence

- Owns: `CONTRIBUTING.md`, `doc/_staging/`.
- Inputs: the six staging files.
- Tasks: move each staging section under its E heading. Merge the two
  E19 parts. Delete `doc/_staging/`.
- Done when: no "Filled by package W2-A." line is left; `doc/_staging/`
  does not exist; every pointer in the code names an existing heading.
- Verify:
  ```bash
  grep -rhoE 'CONTRIBUTING\.md, "E[0-9.]+[^"]*"' src tests | sort -u > /tmp/ptr
  grep -oE '^#+ E[0-9.]+\.? .*' CONTRIBUTING.md
  ```
  Compare the two lists by hand. Each pointer must match a heading.

#### W2-CL: CLAUDE.md

- Owns: `CLAUDE.md`.
- Inputs: section 9; 4.2; the merged README and CONTRIBUTING (for
  pointers).
- Done when: 200 lines or fewer; no audit ID; every pointer resolves.
- Verify: `wc -l CLAUDE.md`; the ID grep in 12.3; each command in the
  Commands section runs.

#### W2-LOG1, W3-LOG2, W4-LOG3: CHANGELOG

- Owns: `doc/CHANGELOG.md` (one package at a time).
- Inputs: 4.7, 8.1, the audit file (for anchors).
- Split: LOG1 = `[Unreleased]` and `[0.1.3]`; LOG2 = `[0.1.0]`;
  LOG3 = sections before `[0.1.0]`.
- Done when: every audit ID in the part is a link; no F-number or
  D-number is left; headers follow 8.1; no number, date or hash changed.
- Verify:
  ```bash
  git diff -U0 doc/CHANGELOG.md | grep -oE '[0-9]+(\.[0-9]+)?' | sort | uniq -c > /tmp/n
  ```
  Compare the removed and added numbers. They must be equal, except
  numbers inside new links and dates added under 8.1 step 4.
  Also check that each `audit-202608.md#...` link names a heading that
  exists in the audit file.

#### W5-FIN: final checks

- Owns: all files, for small fixes only.
- Steps:
  1. `grep -rnE "41666|40000|600 RPM|v4 format|rms_pct: 10|test_save\b|VibeSample.process|self.callbacks|BRANCH-NOTES|log/faulthandler" src tests *.md doc`
     returns only CHANGELOG and audit-file history lines.
  2. The ID grep in 12.3 over `src tests README.md CONTRIBUTING.md CLAUDE.md`
     prints nothing.
  3. Every Markdown link and anchor resolves.
  4. `./scripts/render_docs.sh`, if pandoc and WeasyPrint are installed
     here. If not, say so. Add `doc/audit-202608.md` to the published
     list only if the owner asks (question Q-3).
  5. `awk '/^## Requirements Tracker/{f=1} /^## Architecture/{f=0} f && /^\|/ {n=gsub(/\|/,"|"); if(n!=5) print NR}' doc/PROGRESS.md`
     prints nothing.
  6. `ruff check src/ tests/`; the full `pytest tests/` once, with no
     other run active.
  7. Measure again. Record the result against 3.5.

---

## 13. Risks

| ID | Risk | Control |
|---|---|---|
| R-1 | Evidence is lost in a move | Each code package writes the table to its staging file in the same commit that removes it. W2-A checks that each staging table arrives. Section 7 lists numbers that exist in code only |
| R-2 | A table arrives without its conditions | Each E section has a "Measured on" line. Tables measured at 41666.5 Hz keep that label |
| R-3 | Source-inspection tests read module source, and comments are source. `tests/test_session_from.py:61-107` and `tests/test_headless_tach.py:280-298` assert that `gui.py` and `headless.py` contain `session_from(`, `required_cache_frames(`, `channel_role_state(`, and do not contain `MonitorSession(`, `max_burst_s=600.0`, `'max_burst_s':       600.0,`, `info.get('role')` | Do not write these strings in any docstring or comment of `gui.py` or `headless.py`. Run the two test files in W1-C5 and W1-C6 |
| R-4 | Tests refer to docstring tables in their own text | W1-T1 updates `tests/test_peak_selection.py:641`, `:691` |
| R-5 | A pointer names a heading that a later edit renames | W2-A check; rename a heading only after a search for its ID |
| R-6 | Relative links in README do not resolve on a package index | Accept; the wheel is not on PyPI |
| R-7 | Parallel worktrees edit the same file | File ownership in 12.5. The coordinator rejects a package whose `git diff --stat` shows a file it does not own |
| R-8 | A corrected value is also wrong (tach limits at 25.6 kHz are computed, not measured) | Label them "computed from the 70-samples-per-pulse limit, not measured at 25.6 kHz" |
| R-9 | History is deleted that neither the CHANGELOG nor the audit file holds | Section 7 rule |
| R-10 | STE rewrite changes technical meaning | Do not reword identifiers, units or numbers. The CHANGELOG number check in W2-LOG1 to W4-LOG3 |
| R-11 | ruff fails on a changed docstring | `ruff check` in each package |
| R-12 | `CLAUDE.md` and the agent prompts are agent context | W2-CL and W1-AG get owner review |
| R-13 | This plan and `doc/_staging/` are untracked or temporary; `git add doc/` can commit them | Do not use `git add doc/`. W2-A deletes `doc/_staging/` |
| R-14 | Parallel pytest runs compete for an attached scope | Wave packages run pytest with `--ignore=tests/test_picoscope_hw.py`. W5-FIN runs the full suite once |
| R-15 | The audit HTML is in a temporary directory | W1-AUD runs first, or the coordinator copies the HTML into the worktree |
| R-16 | A finding marked "Fixed" is still open (for example S-06) | W1-AUD confirms each status from the fix diff. It reports each uncertain status to the owner |
| R-17 | Link anchors differ between GitHub and pandoc | The bare-ID heading form (`### M-01` -> `#m-01`) is the same in both. W5-FIN step 3 checks |

---

## 14. Owner answers (2026-09-29)

- **Q-1.** No decision record exists. Replace D-1, D-2 and D-6 with plain
  words everywhere, including the CHANGELOG.
- **Q-2.** Each finding that W1-AUD confirms open gets R50 and up in
  PROGRESS (W1-PR assigns them from the W1-AUD status map). S-06 and S-03
  are fixed now in a separate code package, FIX-S, before W1-C5 and W1-C6.
- **Q-3.** `doc/audit-202608.md` stays in the repository only. Do not
  add it to `scripts/render_docs.sh` or to the release assets.

### 14.1 Schedule change (coordinator)

FIX-S owns `src/rev80/monitor/controller.py`, `src/rev80/gui.py`, new
test files and `doc/CHANGELOG.md` (one `[Unreleased]` entry). Thus wave 1
runs in two parts:

| Part | Packages | Starts when |
|---|---|---|
| 1a | W1-AUD, W1-C1, W1-C2, W1-C3, W1-C4, W1-T1, W1-RM, W1-CT, W1-AG, FIX-S | at once |
| 1b | W1-C5, W1-C6, W1-T2, W1-PR | FIX-S and W1-AUD are merged |

W1-T2 also owns the test files that FIX-S adds.

### 14.2 Coordinator notes for later packages (2026-09-29/30)

Owner answers:
- X-01: Fixed. The prompt before a sensor is added from an opened file is a note, not an open item.
- ISO 20816-3: cite it for the 10-1000 Hz and 2-1000 Hz bands. Do NOT state a speed limit (for example "below 600 r/min") in reference docs. Tell the reader to check the standard.
- E1 "Measured on": 4424A, August 2026 (serial not recorded).
- The 55 %/31 % against 350 %/246 % overshoot figures are removed (`ede37e7`). Do not restore them.
- "Standing assumption" examples in `.claude/agents/technical-writer.md` stay (agent context).
- Envelope band limit (`gui.py` `suggest_band(..., fmax=samplerate / 2.0)`): a code fix (FIX-E) runs after W1-C6 merges.

Code fixes merged: FIX-S (`81441a5`, `910fedc`), FIX-R (`6d5e17e`, reprocess skips tachometer channels).

For W2-A (Design evidence):
- `tests/test_peak_selection.py` holds two tables that exist nowhere else: the floor-lift table for dense lines (11/22/44/88-bin gaps) and the false-alarm table (6.0/9.5/12/15.5 dB). Copy them into E12, then cut the test docstrings to the property.
- E9 must hold the untapered-mask figures (-22 dB / +2.7 % against -84 dB) from `tests/test_measurement_validity.py`.
- E2: `picoscope.py` gives -60.0 dB for the scipy Hamming kernel; the audit gives -55.5 dB worst case. State which measurement each is.
- Merge "E20 (part from sample.py)" with the E20 text from W1-C5, and the two E19 parts.
- Titles already used in pointers: "E8.1. Stateful filter", "E8.2. Seed from the block mean", "E8.3. Knee below the band edge", "E12.1. Method", "E12.2. Floor width", "E12.3. Edge handling", "E12.4. Window nulls", "E13. Envelope band search", "E14.1. No high-pass on a tachometer channel", "E14.3. Interpolation", "E15. Simulation model constants", "E16. Anomaly thresholds", "E19. GUI render cost", "E20. Speed gate".
- `_dsp.band_rms` has no caller. E10 stays; it records why the overall does not use Parseval.

For W2-CL (CLAUDE.md), stale claims:
- `VibeSensor._callback` does not scale ADC counts for hardware; `PicoScopeStream._adc_to_mv` does, and the callback is `DataCollector.receive_data`.
- The collector high-pass is causal `sosfilt` with state carried; there is no zero-phase path.
- `test_measurement_validity.py` is not high-pass-enabled by construction; it is off-bin where a test checks leakage.
- `_dsp.py`, `simulation.py`: the tables moved to CONTRIBUTING.
- Tach storage ratio is about 850 at 25600 Hz, not 1400.
- `_dsp.band_rms` has no caller.

For the LOG packages (CHANGELOG):
- Near the hotfix/RAW_SAMPLERATE entry: "every preset combination is 5-smooth" is false (10 of 54 are not); "24 combinations now exact" may be from an older state (43 now). Add a correction note; do not rewrite the history numbers.
- fix/measurement-validity gives 8333.25 Hz; the audit gives 8333.33 Hz. Both are in E5.

For W1-PR (PROGRESS): R50 and up, in this order, from the audit file: S-08, S-10 (part), S-11, X-02 (part), X-03, X-04 (part), X-05, X-07, H-01 (part), H-02, H-05 (part), H-07 (part), H-08 (part). Then add: Ctrl+K can stop the stream during a recording; `trigger_burst` does not set `_max_burst_frames`; `_dsp.band_rms` has no caller. R34 text: cite ISO 20816-3 without the speed limit.

---

## 15. Not verifiable here

- Tachometer figures at the 25.6 kHz raw rate. The 70-samples limit, the
  interpolation regimes and the 300-10200 RPM table were measured at
  41666.5 Hz. The run of 2026-09-18 at 25.6 kHz passed 27 hardware tests,
  including the sweep at +/-0.2 %, but no one recorded new table values.
  Check on a 4424A with AWG loopback: record the per-point sweep error,
  and generate 6 ppr and 60 ppr pulse trains near 3660 RPM and 366 RPM.
- The v6 `session.h5` layout in a real file. Only v5 sessions exist on
  this machine. Check: run `rev80-headless --device sim --interval 10
  --start-now` for 60 s, then open the file with h5py.
- R35 note: a hardware sweep over 10 to 1000 Hz is not recorded.
- The full test-suite run time.
- All GUI claims. No GUI was started.
- The release workflow `gh release create --draft` step (PROGRESS R48).
- PDF rendering, if pandoc and WeasyPrint are not installed.
