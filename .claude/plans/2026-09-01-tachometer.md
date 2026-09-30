# Tachometer support for Rev80 — requirements, implementation, verification

Greenfield specification by the `vibration-engineer` agent against `develop` @ `474f086`.
All measurements were produced against the real code in this tree, not a model of it.
Scratchpad scripts regenerate every table:
`/tmp/claude-1000/-home-hgg-Documents-reveng-code-vibegui/0e715a24-8057-4a63-90ba-f25b5cdbfad7/scratchpad/`
— `pulse.py`, `timing.py`, `hp.py`, `accouple.py`, `thresh.py`, `floor.py`, `estim.py`,
`phase.py`, `smear.py`, `final.py`, `gate.py`, `perf.py`, `tachasvib.py`.

## Correction to a stated architecture fact

The stored rate is **not** 40 000 Hz. `PicoScopeStream._start_streaming` requests
`40000 × osr(2) = 80000`, computes `sample_interval_us = int(1e6/80000) = 12`, and the
driver delivers `1e6/12 = 83333` Hz raw, which `_report_samplerate` divides by the OSR
to give **41 666.5 Hz** — the float that lands in `VibeSample.samplerate` and the HDF5
frame attrs. `SimulatedSensor` reports exactly 40 000.

Edge quantisation is therefore **24.00 µs on hardware, 25.00 µs in CI**.

> Any RPM computed from `RAW_SAMPLERATE_HZ` instead of `sample.samplerate` reads
> **4.166% high on real hardware — 1800 RPM displays as 1875.0** — and is exactly
> correct in CI. This is the single easiest way to ship a wrong tachometer with a
> green suite.

---

# Revision 2 — owner decisions and hardware close-out (2026-08-31)

Reviewed and accepted. Four changes to the spec above, and the §3.4 unknowns are now
measured on the 4424A (serial 12462/0067) with AWG loopback on channel A.

## D-1. `RmsThresholdHook` default: 10% → **50%**

Not a tach change; a correction to a shipped default that the §1.1(c) table exposed.
10% is crossed by a 3.2% speed swing alone, so on any load-following machine the hook
was measuring load. 50% is the level at which a *broadband RMS* rise means something on
its own without a speed reference.

Where a tach is present, the speed gate is the more certain trigger and the hook can be
tightened per-installation. Where no tach is fitted — common, and often impractical to
retrofit — detection has to come from envelope/demodulation techniques or hard
thresholds (`FixedThresholdHook`) instead. Note the spectral hook remains unwired from
`GUI_ANOMALY_HOOK_TYPES` (R39) pending revisit; that decision is unchanged here.

Update both the `config.py` default and the `_build_anomaly_hook` defaults **in both
copies**, or `tests/test_anomaly_hook_build.py` fails — which is the test doing its job.

## D-2. Store **edge times**, not the tach waveform. Speed change invalidates; it does not get corrected.

Supersedes §1.6's "store the raw waveform as a channel" and the §1.3 order-tracking plan.

Storing per-frame edge arrival times gives everything the waveform was being kept for:
`pulses_per_rev` is still a post-hoc divisor, within-block speed variation is derivable
from the interval sequence, and a shaft-angle vector for any future order work is an
interpolation of the edge times. What is given up is re-thresholding after capture —
acceptable, because the GUI tach waveform view (§2.7 item 3) exists to get the threshold
right at commissioning, and the quality flag records whether it was.

Storage: ~30 float64 per second against 41 666 — **a factor of ~1400** on that channel,
which matters most for exactly the long unattended sessions where it would otherwise
dominate the file. (For precision: the stored rate is 41 666.5 Hz; 83 333 Hz is the
pre-decimation ADC rate and never reaches storage.)

**Order-normalised resampling is dropped, not deferred.** Bearing analysis is performed
at steady state; a smeared spectrum should be *rejected*, not corrected. So instead of a
constant-angle resampling path:

- Compute within-block speed drift from the edge intervals.
- Above the threshold, mark the frame — the same way `overflow` and `degraded` already
  mark it — so it is excluded from trend, baseline adaptation and anomaly evaluation,
  displayed and flagged rather than hidden.

This removes the whole §1.3 order-tracking cost — no angle vector, no parallel resampling
path, no second axis type through `peaks`, `_dsp`, the declared band and the HDF5 attrs.
`ChannelResult.freq` stays Hz, permanently.

**Two distinct statistics, not one.** §1.5's `interval_spread` (max deviation / median)
is tuned to catch a *miscounted edge* and must stay at `INTERVAL_SPREAD_MAX = 0.25`.
Speed drift is a monotonic trend, not an outlier, and needs its own metric:

```
speed_drift_pct = 100 * (median(first-half intervals) / median(second-half intervals) - 1)
SPEED_DRIFT_MAX_PCT = 1.0
# Within-block shaft-speed change above which the frame is flagged unsteady and
# excluded from trend, baseline and alarm evaluation (still displayed, still stored).
# From the smearing table in section 1.3, 1.0 s block, bearing tone at 5.43x:
#     drift over block   peak height   smear @0.25 Hz bins
#        0.1 %             100.6 %        0 bins
#        0.5 %              94.4 %        4 bins
#        1.0 %              93.8 %        9 bins   <- threshold
#        2.0 %              82.6 %       18 bins
#        5.0 %              69.6 %       46 bins
# 1.0 % keeps peak-height error under ~6 % and smear under ~10 bins. A mains-fed
# motor at steady load sits below 0.1 %; this fires on VFD ramps and load steps,
# which is exactly the population whose spectra should not be trusted.
```

A separate metric also means the two failures are distinguishable on screen: `INCONSISTENT`
(miscounted edge — suspect the sensor) versus `UNSTEADY` (machine is changing speed —
suspect the measurement moment).

## D-3. Headless refuses tach channels, and it goes in PROGRESS

§2.9 stands as written. Add to `doc/PROGRESS.md` as an open requirement — tach support in
`rev80-headless` is deferred, not rejected, and the refusal is a safety measure rather
than a design position.

## D-4. HDF5 revised for D-2

Replacing the §2.5 tach layout. No raw tach waveform dataset:

```
/frames/{i}/{ch}/edge_times      (E,) float64  seconds from block start
              .attrs             rpm            float, NaN = no reading
                                 quality        str
                                 n_edges        int
                                 interval_spread  float
                                 speed_drift_pct  float
                                 samplerate     float   (the rate edges were resolved at)
/frames/{i}/{ch}                 NO 'data' dataset -- readers must branch on role
```

`_write_channel_group` is currently the single unified writer for both `collector.py` and
`monitor/writer.py`, so the role branch goes in exactly one place. Every reader that
assumes `'data'` exists must be found and branched — `_read_frame_group`,
`reprocess_session_trend`, `load_monitor_session`, and the monitor pre-trigger path.
`ChannelResult.speed_ok` gains a sibling `speed_steady`.

## D-6. Plan around **1 pulse/rev**. Unwire ppr from the GUI; keep the divide internally.

The preponderance of installations is a single reflective tape or one keyway. Multi-pulse
is a convenience for an operator who notices they are getting several reflections or
notches — a PTO spline (6 teeth) is the one plausible case, a 24-tooth spline is
imaginable but not worth supporting. In every such case the technician detects and fixes
the setup themselves.

**Decision:** plan around 1 ppr. Remove the pulses/rev widget from the channel config
(step 9). Keep `TachSettings.pulses_per_rev` and the divide in `estimate_rpm` so the
capability can be restored without rework, but nothing in the UI can set it to anything
but 1.

Considered and rejected: detecting multi-modal pulse periods to infer ppr automatically.
Multiple reflectors are not equally spaced in practice (two at 180°, three at 120° is the
exception, not the rule), so the bimodality is real and detectable — but it is a flag for
a setup the operator will find and fix anyway, and not worth the code.

### What this decision removes

**The minimum-revolutions question dissolves.** It was raised because `MIN_EDGES = 3`
gates on *pulses*, which at 60 ppr is 0.05 of a revolution. Measured — 60-line encoder,
±0.05° division error, 0.5% once-per-rev speed modulation, 40 random start phases:

| revolutions observed | pulses | mean err | worst err |
|---|---|---|---|
| 0.05 | 3 | 0.580% | 1.898% |
| 0.10 | 6 | 0.470% | 1.304% |
| 0.25 | 15 | 0.344% | 0.869% |
| 0.50 | 30 | 0.260% | 0.704% |
| **1.00** | 60 | **0.091%** | 0.383% |
| 2.00 | 120 | 0.091% | 0.383% |
| 10.0 | 600 | 0.091% | 0.383% |
| 20.0 | 1200 | 0.091% | 0.383% |

Error falls until exactly one revolution and is then **flat** — more pulses buy nothing.
Both dominant error sources are once-per-rev and cancel over a whole revolution, not by
collecting more samples within a partial one.

At 1 ppr the same table collapses: 3 pulses (2 revolutions) gives **0.0013%**, 70× better
than 60 ppr reaches at any window length, because *every interval is itself one whole
revolution* — the cancellation is by construction rather than by averaging.

So `MIN_EDGES = 3` is already the right gate: at 1 ppr it is 2 revolutions. **No
revolutions constant and no new user-facing config.** A revolutions gate
(`MIN_REVS_PER_FRAME = 1`) becomes necessary only if ppr is ever re-exposed, and that is
recorded here rather than built.

**The ≥70-samples-per-pulse accuracy ceiling stops binding.** At 1 ppr it sits at
36 000 RPM. The channel-config warning planned for step 9 is no longer needed.

### What it does not remove — and a correction

The block-length limit stays, and the table in §1.2 is **wrong by 3×**. To guarantee
`MIN_EDGES = 3` rising edges in a block of duration T regardless of start phase requires
`T >= 3 x period`, not 1 — so the minimum is `180/T` RPM, not `60/T`:

| binsize | T_block | min RPM @1 ppr (corrected) | §1.2 claimed |
|---|---|---|---|
| 0.25 Hz | 4.00 s | **45** | 15 |
| 0.5 Hz | 2.00 s | **90** | 30 |
| 1 Hz | 1.00 s | **180** | 60 |
| 2 Hz | 0.50 s | **360** | 120 |
| 5 Hz | 0.20 s | **900** | 300 |
| 10 Hz | 0.10 s | **1800** | 600 |

At 10 Hz bins nothing below 1800 RPM can be measured at all. This still needs surfacing
in the UI (step 9) — it is the one remaining case where a legitimate setup silently
reports no reading.

### Implementation notes for the ppr change

- `TachSettings.pulses_per_rev` stays, default 1. The divide in `estimate_rpm` stays.
- **Do not silently clamp a non-1 value to 1.** A hand-edited YAML carrying `ppr: 6`
  clamped to 1 would read 6× high with nothing on screen to say so — precisely the
  silent-wrong-number class this project keeps finding. Honour the value and log a
  warning that it is an unsupported path.
- GUI (step 9): no pulses/rev widget.
- `tach.py`'s `MIN_EDGES` comment should state the revolutions equivalence, and the module
  docstring should record the measured table above so a future re-exposure of ppr starts
  from the number rather than re-deriving it.

## D-7. GUI shape: a dedicated Tachometer tab (supersedes §2.7)

**Order cursors are dropped from this plan.** The 1x speed will feed richer features
later; for now the requirement is to *display* it.

**Instead: a 1x vibration level on each channel result card**, above the frequency peaks,
shown only when a tach is present and reading. It reports the spectrum amplitude at the
**nearest bin** to 1x -- no interpolation and no energy summation, matching the existing
peak-reporting convention.

**A dedicated Tachometer tab owns the tach.** Tach setup is a commissioning activity done
once per installation, not a monitoring one, so the diagnostic view belongs where the
settings are: adjust threshold -> watch edges move -> confirm RPM, all on one screen.
Closing it leaves only the derivatives (RPM card, trend, 1x level) on the main display,
which solves "hide the waveform once it works" structurally rather than with a toggle the
operator has to manage.

The tab carries:
- Which channel is the tachometer (this screen **owns** the role).
- The tach calibration: polarity, threshold mode and level, min amplitude.
- A **live plot of the tach channel** with the computed threshold drawn as a horizontal
  line and the detected edges marked. A bare scope trace does not say *why* detection
  failed; threshold plus edges does.
- The current RPM and the quality word (`ok` / `no_signal` / `too_few_edges` /
  `inconsistent` / `unsteady`), on the same screen as the settings that produce them.
- The minimum measurable RPM for the current binsize, as **information, not validation**.

**One writer, not two.** The channel-setup tab no longer has a role dropdown. A channel
claimed by the tach tab shows that in its summary line and does not open its normal
settings (a tachometer has no sensor and no engineering unit, so those controls are
meaningless on it). Two screens able to set the role could disagree; one cannot.

### Min RPM is a machine state, not an instrument fault

Below `180/T_block` RPM the tach cannot resolve a rate. That is **not** a degraded or
error state: it should read as **"motor stopped"**, a machine state that can be consumed
and acted on later. Specifically:

- It never blocks configuration. An operator must be able to set the tach up against a
  machine that is not running, using their best guess.
- The tach tab shows the floor for the current binsize so the operator knows what they
  are choosing, and nothing more.
- It is surfaced in words ("stopped or below 180 RPM"), not as a fault.

**Honest limit, and worth knowing before this is relied on.** A stopped shaft and a
disconnected cable can be indistinguishable. Both give a flat block:

| tach state | block appearance | distinguishable? |
|---|---|---|
| stopped, reflector away from sensor | flat near 0 | **no** -- same as a dead cable |
| stopped, reflector parked at sensor | flat at the high rail | yes |
| turning below the floor | pulses present, < MIN_EDGES | yes (`too_few_edges`) |
| disconnected / dead | flat near 0 | **no** -- same as stopped |

So `no_signal` cannot be reported as "stopped" without lying in the disconnected case.
A reliable stopped state needs *history* -- a good reading that then ceased is a stop; a
channel that never read is a setup problem -- which is a small state machine and belongs
with whatever consumes the state, not in `tach.py`. Recorded, not built.

### Verified: a dearpygui modal does not block the render loop

The design above depends on a live plot updating inside the config dialog. Measured
directly (60 manual `render_dearpygui_frame()` calls with a modal window shown, pushing
new data into a series inside it each frame):

    modal shown:            True
    render frames advanced: 60 / 60
    series updates applied: 60 / 60

So the modal blocks *input* to other windows -- which is what is wanted while the
operator is configuring -- but not rendering. `GUI.run()` drives its own
`render_dearpygui_frame()` loop, the same pattern the probe used, and the data feed comes
from the collector's frame cache filled by the acquisition thread, independent of the
dialog. **The Tachometer tab can be a modal dialog with a live plot.**

### Tach waveform plot: pulse-aligned, not free-running

Shift the time axis so the **first detected pulse lands at t = 0**. A free-running trace
jitters frame to frame by up to a whole period, which makes it hard to see whether the
threshold sits where you want it; pulse-aligned, successive frames overlay and the
adjustment is legible.

X limits `[-2T, (pulse_count + 2) * T]` with `T = 1/shaft_hz`, so there is a couple of
periods of lead-in before the first pulse and the same after the last. Y autoscales.

### Rotation-rate units are user-selectable, and always labelled

RPM, Hz, rad/s, deg/s. Note `rad/s` **is** angular frequency: omega = 2*pi*f, so the two
are one option, labelled `rad/s (omega)` to be findable by either name.

From the shaft rate f in rev/s:

    RPM    = f * 60
    Hz     = f
    rad/s  = 2*pi*f
    deg/s  = 360 * f

The unit string is displayed **everywhere the rate appears** -- tach tab, RPM card, trend
axis, monitor card -- so a number can never be read in the wrong unit. This is the same
discipline the amplitude side already follows.

### Reflector size and surface velocity -- deferred, and why (R46)

With reflector arc length L, duty cycle d and shaft rate f, the reflector subtends d of a
revolution, so circumference C = L/d, radius r = L/(2*pi*d), and

    v = omega * r = 2*pi*f * L/(2*pi*d) = f * L / d

The tape doubles as a shaft-diameter measurement, so surface speed comes out without
anyone measuring the shaft -- directly useful on rollers, belts and web handling.

**Blocked: duty cycle is not currently captured.** `detect_edges` finds only the active
edge (one polarity), and `TachResult` carries no pulse width. This needs closing-edge
detection, a width field on `TachResult`, and a persistence decision, since D-2 stores
rising edge times only. Tracked as R46 rather than folded into this step.

Accuracy caveat to measure before it ships: an optical tach's spot has finite width, so
the sensor sees the reflector for its arc *plus* roughly the spot diameter. That inflates
d and therefore under-reads both r and v, worst on a small shaft with a wide spot. The
AWG can stand in for a known duty to quantify it.

### 1x level: measure the nearest-bin cost

The reported 1x can under-read, because the shaft rate generally falls between bins and
the nearest bin can be up to half a bin away. Measure the worst case for a Hann-windowed
line at half-bin offset and record it beside the code; if it is large at coarse binsize,
say so on the card rather than silently reporting a low number.

## D-5. Hardware close-out — §3.4 unknowns now measured

4424A serial 12462/0067, AWG loopback channel A. Existing `tests/test_picoscope_hw.py`:
**9 passed**.

**Reported samplerate — confirmed.** `41666.5 Hz` at every voltage range, exactly as
predicted from `int(1e6/80000) = 12 µs`. The 4.166% trap is real and the revert-check
guarding it is mandatory. Note also that `raw_blocksize` is derived from the nominal
40 000, so a "1.0 s" block is 40 000 samples = **0.96 s** at the true rate.

**Front-end noise — `MIN_PULSE_AMPLITUDE_V = 1.0` confirmed, no longer provisional.**
Measured with the AWG idle, 40 000-sample block, DC coupled:

| range | noise mV RMS | block span mV | margin to 1.0 V |
|---|---|---|---|
| ±1 V | 0.372 | 2.93 | 342× |
| ±2 V | 0.514 | 3.90 | 256× |
| ±5 V | 0.870 | 8.35 | 120× |
| ±10 V | 3.607 | 28.34 | 35× |
| ±20 V | 5.091 | 42.51 | **23.5×** |

The real front end is ~16× quieter than the pessimistic model the constant was set from
(5.09 mV RMS at ±20 V against 80 mV assumed). 1.0 V stands: 23.5× above the worst
measured noise span and 2× below the ≥2 V swing of any real logic-level tach.

**RPM accuracy — meets every requirement with margin.** AWG square, 2 Vpp at 1 V offset
(the 4424A generator is a ±2 V part — 5 Vpp at 2.5 V offset returns
`PICO_SIGGEN_OFFSET_VOLTAGE`), DC coupled, ±5 V range, adaptive threshold:

| AWG Hz | true RPM | measured | error RPM | error % | edges | spread |
|---|---|---|---|---|---|---|
| 5 | 300 | 299.508 | −0.492 | −0.164 | 5 | 0.0001 |
| 10 | 600 | 600.153 | +0.153 | +0.026 | 10 | 0.0001 |
| 30 | 1800 | 1800.383 | +0.383 | +0.021 | 29 | 0.0003 |
| 60 | 3600 | 3599.818 | −0.182 | −0.005 | 57 | 0.0004 |
| 100 | 6000 | 6001.106 | +1.106 | +0.018 | 96 | 0.0010 |
| 170 | 10200 | 10204.025 | +4.025 | +0.040 | 163 | 0.0024 |

Worst case 0.164% at 300 RPM; ≤0.04% everywhere above. Against the 3000 ppm (0.3%) that
line-naming needs, this passes at every speed. **Correction to the §1.2 claim:** the
simulated table predicted ≤0.2 RPM at 1 ppr across the range; hardware gives 4.0 RPM at
10 200 RPM. Error scales with speed, so the honest claim is **±0.2% of reading**, not a
fixed RPM figure. Some of that residual is AWG frequency setting, not the detector —
interval spread stays ≤0.0024, so the pulse train itself is clean and the error is
systematic rather than jitter.

**The AC-coupling failure — reproduced electrically, and it is the duty cycle.**
`ps4000aSetSigGenArbitrary` and `ps4000aSigGenFrequencyToPhase` are both present in the
wrapper (the other §3.4 unknown — resolved), so a non-50%-duty waveform is achievable.
30 Hz, 4096-point arbitrary waveform, ±5 V range, fixed threshold placed at 1000 mV,
the correct midpoint for the DC-coupled signal:

| duty | AC min mV | AC max mV | fixed threshold | adaptive |
|---|---|---|---|---|
| 5% | −292 | 2106 | 1801.7 | 1801.7 |
| 30% | −852 | 1684 | 1801.7 | 1801.7 |
| 50% | −1263 | 1354 | 1801.4 | 1801.7 |
| **70%** | −1647 | **980** | **FAIL — 0 edges** | 1801.7 |
| **85%** | −1915 | **750** | **FAIL — 0 edges** | 1801.7 |

DC-coupled, every duty and both threshold modes return 1801.7. AC-coupled, the signal
maximum falls monotonically with duty and crosses below the fixed threshold between 50%
and 70% — the predicted ~55% crossover. **The adaptive threshold returned 1801.7 RPM in
all ten conditions**, invariant to duty and coupling alike.

This is the electrical proof behind D-2's defaults and behind §1.4's enforced DC
coupling. It promotes hardware tests 1 and 3 from "to be written" to "measured, and the
regression test should assert these numbers".

(1801.7 against a true 1800.0 is +0.094%, the arbitrary waveform's frequency
quantisation at 4096 points, not detector error — the built-in square at the same
frequency reads 1800.383.)

**Still not measured, and still open:** crosstalk between a tach channel and an adjacent
IEPE channel (§3.3 item 5), the 16→14 bit resolution cost in real noise-floor dB (item
6), the 4-channel sustained run with a tach in the mix (item 7), and a real
proximity-probe keyphasor on ±20 V. Items 5 and 6 need a second cable and a terminated
input; item 7 needs three accelerometers. The keyphasor remains the sensor type least
safe to declare working without one in hand.


---

# Part 1 — Requirements

## 1.1 What tachometer support is for

Shaft speed is the denominator that turns a spectrum into a diagnosis. Four uses, in
descending order of how often they decide a work order:

**(a) Naming the lines.** A line at 162.9 Hz is meaningless; 5.43× shaft is a bearing
outer race. Slip on a 4-pole 60 Hz motor moves 1800 → 1750 RPM between no load and
full load (2.8%); a 5.43× BPFO moves 6.1 Hz, which at 0.5 Hz bins is 12 bins from
where the analyst is looking. This justifies the feature on its own.

**(b) Separating electrical from mechanical.** On a 2-pole motor, 2× line frequency is
7200 CPM exactly and 2× running speed is 2×3560 = 7120 CPM. 80 CPM apart, completely
different repairs (loose rotor bar / stator eccentricity vs misalignment). Needs
running speed to better than ~40 RPM, and cannot be done by assuming nameplate.

**(c) Making trends comparable.** For a rigid rotor below its first critical
(`x ∝ ω²`, so `v = ωx ∝ ω³`):

| speed deviation | 1× velocity change, below critical | at/above critical |
|---|---|---|
| 0.5% | +1.5% | +0.5% |
| 1.0% | +3.0% | +1.0% |
| 2.0% | +6.1% | +2.0% |
| **3.2%** | **+10.0%** | +3.2% |
| 5.0% | +15.8% | +5.0% |
| 10.0% | +33.1% | +10.0% |

The shipped `RmsThresholdHook` default is 10% deviation over 3 consecutive frames.
**A 3.2% speed change alone crosses it.** A typical induction motor's no-load-to-full-load
slip swing is ~2%, a +6% apparent rise on a machine whose condition has not changed.
On any VFD-driven or load-following machine the shipped anomaly detector is currently
measuring load, not condition. Speed gating is the fix.

**(d) Order-normalised analysis.** Deferred — §1.3.

## 1.2 Accuracy required, in RPM and orders

Measured end-to-end for the Part 2 design (analog pulse → ADC 83 333 Hz → Kaiser
decimate → Schmitt at 50% of block span → sub-sample interpolation → median of
intervals), 1.0 s block, 200 µs pulse, 2 mV RMS noise, 24 pulse phases per row:

| true RPM | ppr | nearest-sample err | ppm | sub-sample err | ppm |
|---|---|---|---|---|---|
| 300 | 1 | 0.011 | 36 | **0.0037** | 12 |
| 600 | 1 | 0.050 | 84 | **0.0084** | 14 |
| 1800 | 1 | 0.151 | 84 | **0.149** | 83 |
| 3600 | 1 | 2.291 | 636 | **0.176** | 49 |
| 1800 | 2 | 1.146 | 636 | **0.088** | 49 |
| 1800 | 6 | 3.745 | 2080 | **0.564** | 314 |
| 10000 | 1 | 0.040 | 4 | **0.042** | 4 |
| 600 | 60 | 4.764 | 7940 | **0.553** | 922 |

Against the requirements:

- **Naming the lines** needs ¼ bin at the highest order of interest: at 1800 RPM,
  0.5 Hz bins, 5.43× → shaft right to 5.5 RPM (3000 ppm). Delivered 0.15 RPM —
  **200× margin**.
- **Electrical vs mechanical** needs ~40 RPM at 3600. Delivered 0.18 RPM — **220× margin**.
- **Trend comparability** needs the speed *window* tight (3%), not the reading.
  Delivered accuracy is 0.005% of the window. Not limiting.
- **Order analysis** (deferred) needs the order axis stable to a fraction of a bin at
  high order. 83 ppm at 1800 RPM puts a 10th-order line 0.025 Hz off — 8.2×10⁻⁴ order
  against a 0.25 Hz bin's 8.3×10⁻³ order. **Tach accuracy is 10× better than the finest
  bin; within-block speed variation is what limits order analysis, not the tach.**

Sub-sample interpolation is in the first cut: one line of arithmetic, 2–9× at every
ppr above 1, and it turns a 60-pulse encoder at 600 RPM from 0.79% error into 0.09%.

**Documented resolution claim:** ~~±0.2 RPM at 1 ppr~~ — **superseded by D-5 hardware
measurement**. Error scales with speed; the honest claim is **±0.2% of reading** at 1 ppr
from 300 to 10 200 RPM (measured worst case 0.164% at 300 RPM, 0.040% at 10 200).

**Lower limit.** ~~Table below~~ — **corrected, see D-6.** It was wrong by 3x: it
assumed one edge per period suffices, but guaranteeing `MIN_EDGES = 3` rising edges
*regardless of start phase* needs a block spanning three periods, so the floor is
`180/T_block` RPM, not `60/T_block`. At 1 ppr (D-6):

| binsize | T_block | slowest shaft @1 ppr | (superseded claim) |
|---|---|---|---|
| 0.25 Hz | 4.00 s | **45** | 15 |
| 0.5 Hz | 2.00 s | **90** | 30 |
| 1 Hz | 1.00 s | **180** | 60 |
| 2 Hz | 0.50 s | **360** | 120 |
| 5 Hz | 0.20 s | **900** | 300 |
| 10 Hz | 0.10 s | **1800** | 600 |

At 10 Hz bins nothing below 1800 RPM can be read. This is the one case where a
legitimate setup returns no reading, and step 9 must surface it.

A real usability constraint created by binding the tach window to display `binsize`.
**It must be shown in the UI**, not discovered — 10 Hz bins on a 1-ppr keyphasor and a
500 RPM fan otherwise gives "no tach signal" with no explanation.

**Upper limit.** Set by pulse width, not RPM: ~4 samples per pulse at 41 666 Hz →
~10 000 pulses/s → 600 000 RPM at 1 ppr, 10 000 RPM at 60 ppr, **586 RPM at 1024 ppr**.
A high-line-count encoder is the failing case and the UI must say so.

## 1.3 What ships now, and what the codebase is not ready for

### Speed-gated alarming — **yes, first cut.** The codebase is ready.

The one seam is `monitor/anomaly.py:valid_results()`, which already exists to answer
exactly this question and is already called by every hook and both baseline-adaptation
paths. A `speed_ok` flag on `ChannelResult` plus one clause there is a five-line change
at a seam built for it.

Crucially it does **not** touch `_build_anomaly_hook`, copy-pasted between `gui.py` and
`headless.py` and pinned by `tests/test_anomaly_hook_build.py` asserting the copies'
defaults match (audit H-01). Putting the gate in `AcquisitionSettings` and testing it in
`valid_results()` keeps both copies byte-identical. **If the gate is instead added as a
hook parameter, H-01 turns one bug into two.** That is the reason for the seam choice.

### Order-normalised analysis — ~~phase 2~~ **DROPPED — see D-2**

> Superseded. Order resampling is not deferred, it is dropped: a smeared spectrum is
> rejected via `SPEED_DRIFT_MAX_PCT`, not corrected. The smearing table below is retained
> because it is what sets that threshold.

Bearing tone at 5.43× on an 1800 RPM shaft, speed ramping linearly across the block:

| speed drift | peak line height | half-power width @0.25 Hz bins (4 s block) |
|---|---|---|
| 0%/s | 100.0% | ~1.5 bins (reference) |
| 0.1%/s | 100.6% | 0.0 Hz / 0 bins |
| 0.5%/s | 94.4% | 1.00 Hz / 4 bins |
| 1.0%/s | 93.8% | 2.25 Hz / 9 bins |
| 2.0%/s | 82.6% | 4.50 Hz / 18 bins |
| 5.0%/s | 69.6% | 11.50 Hz / 46 bins |

A mains-fed motor at steady load drifts well under 0.1%/s and order tracking buys
nothing measurable. A VFD ramp or load-following pump at 1–5%/s loses 6–30% of peak
height and smears a bearing tone across 9–46 bins at the finest resolution — precisely
the setting chosen to resolve sidebands. Real, and for a specific class of machine.

Cost in this codebase is why it defers:

- Needs a per-sample **shaft angle vector** — edges resolved across block boundaries and
  interpolated between them, a stateful path with the same live-vs-replay determinism
  problem `filter_block` solved with two regimes.
- Needs the vibration signal resampled onto a constant-angle grid: a path parallel to
  `_decimated_for`, with its own anti-alias design and measured error table.
- `ChannelResult` is frozen and its `freq` field is documented as Hz at every consumer.
  `peaks.select_peaks`, `_dsp.band_mask`, `_dsp.band_rms`, `ISO_BAND_PRESETS`, the
  declared-band machinery, the trend, `FixedThresholdHook`'s unit conversion and the
  HDF5 band attrs all assume a Hz axis. An order axis is a second axis type through all
  of them.

~~Phase 1 must store the tach waveform as a channel.~~ **Superseded by D-2:** store edge
times. The angle vector, were it ever wanted, is an interpolation of those — at 1/1400th
the storage.

### Phase reference for balancing — **no, and explicitly out of scope.**

Measured on the shipped high-pass (causal 4th-order Butterworth, knee 8.342 Hz via
`butter_knee_for_edge`), phase at 1×:

| RPM | 1× (Hz) | \|H\| | phase (deg) | consequence |
|---|---|---|---|---|
| 300 | 5.00 | 0.128 | −95.6 | trim weight 96° out of place |
| 600 | 10.00 | 0.900 | +143.4 | 143° out |
| 900 | 15.00 | 0.996 | +87.7 | 88° out |
| 1200 | 20.00 | 1.000 | +64.2 | 64° out |
| 1800 | 30.00 | 1.000 | +42.1 | 42° out |
| 3600 | 60.00 | 1.000 | +20.9 | 21° out |

An analyst acting on a balancing phase from this instrument puts the trim weight
21°–143° from where it belongs — and the *amplitude* is right, so nothing on screen says
the phase is wrong. The balance gets worse and the rotor takes the blame. A
"reads healthy on a failing machine" defect, refused rather than approximated.

Beyond the high-pass: `welch(..., scaling='spectrum')` returns power, so phase is
discarded before any consumer exists; `ChannelResult` carries no complex spectrum;
`detrend='linear'` is applied per segment. (Not a problem: `decimate_to_rate`'s
`resample_poly` measured **+0.00°** 1× phase shift at every F_max preset — it
compensates its own group delay.)

Balancing is a synchronous-time-average path with the high-pass phase deconvolved or
bypassed, a trial-weight workflow, influence coefficients, a polar plot and a documented
lag convention. Phase 3, if ever.

## 1.4 Sensor types and what each implies

`antialias_decimate` (Kaiser, 100 dB stopband, 131 taps at factor 2) applies to *every*
channel including the tach. Measured on a 5.00 V trapezoidal pulse train, 1800 RPM,
40 pulse phases swept:

| pulse width | width / T_sample | peak min | peak max | undershoot | samples >2.5 V |
|---|---|---|---|---|---|
| 20 µs | 0.83 | **1.570 V** | 3.820 V | −0.698 V | 0–1 |
| 50 µs | 2.08 | 5.635 V | 5.880 V | −0.273 V | 2–3 |
| 100 µs | 4.17 | 5.401 V | 5.607 V | −0.379 V | 4–5 |
| 200 µs | 8.33 | 5.254 V | 5.441 V | −0.465 V | 8–9 |
| 1 ms | 41.67 | 5.195 V | 5.440 V | −0.440 V | 41–42 |
| 5 ms | 208.33 | 5.195 V | 5.440 V | −0.440 V | 208–209 |

The pulse-width floor sits between 20 and 50 µs; per the owner's settled decision this
is a setup error, noted once here, and no guard is designed for it. Second: Gibbs
overshoot puts a 5.00 V pulse at up to **5.88 V** and rings to **−0.70 V** in stored
data. Created downstream of the ADC in float64, so it does not clip and does not set the
overflow bit — but a threshold cannot sit near the pulse top, and the range must be
chosen for the *physical* amplitude, not the stored one.

**Optical / laser with reflective tape.** 0–5 V or 0–12 V TTL, source-powered. Pulse
width set by tape width and standoff, typically 0.5–5 ms. Two failure modes diagnosed by
interval consistency rather than amplitude: tape wrapped too far round the shaft raises
duty cycle enough to matter (below), and a tape join gives a second smaller pulse per
rev. Coupling **DC**, range **±10 V** for 5 V TTL (headroom over the 5.88 V overshoot),
**±20 V** for 12 V.

**Proximity probe / keyphasor.** Driver-powered from −24 V, output typically −2 to
−18 V DC, keyway notch appearing as a positive-going excursion (gap increases) or a key
projection as negative-going. Large DC standing level, negative, up to 18 V, polarity
installation-dependent. Coupling **DC mandatory**, range **±20 V**, **polarity
configurable**. This sensor makes both settings non-optional.

**Encoder, N pulses/rev.** 0–5 V TTL, high rate. `pulses_per_rev` divides once. 60 ppr
comfortable to 10 000 RPM; 1024 ppr caps at 586 RPM and the UI must refuse rather than
silently miscount.

### Coupling: the finding that decides the default

The scope's AC coupling is a ~1 Hz single-pole high-pass. On a pulse train it removes the
mean, and the mean is the duty cycle. Measured, 1800 RPM, 5.00 V pulse, 1.0 s block,
fixed 2.50 V threshold vs adaptive at 50% of the block's own span:

| duty | coupling | block max / min | fixed 2.50 V | adaptive 50% | true |
|---|---|---|---|---|---|
| 5% | DC | 5.00 / 0.00 | 30 OK | 30 OK | 30 |
| 5% | AC | 4.77 / −0.28 | 30 OK | 30 OK | 30 |
| 30% | AC | 3.61 / −1.61 | 30 OK | 30 OK | 30 |
| 50% | AC | 2.63 / −2.63 | 30 OK (130 mV margin) | 30 OK | 30 |
| **60%** | **AC** | **2.13 / −3.13** | **0 — BAD** | **30 OK** | **30** |
| **80%** | **AC** | **1.09 / −4.08** | **0 — BAD** | **30 OK** | **30** |

> **An AC-coupled tach channel with duty cycle above ~55% and a fixed 2.50 V threshold
> reports zero edges. RPM reads 0 or "stopped" on a machine turning at 1800 RPM, with no
> error, no warning, and a perfectly healthy-looking vibration spectrum beside it.** The
> analyst concludes the machine is down and closes the route point.

Therefore: **tach channels are DC-coupled** (enforced, reason in the tooltip), **and**
the default threshold is adaptive at 50% of block span with Schmitt hysteresis, which
survives every case in the table including AC coupling at 80% duty. Belt and braces,
because the failure is silent.

### The adaptive threshold needs a floor — and its measurement

An adaptive threshold on a flat line finds the noise and counts it. 1.0 s block,
N = 41 666:

| input | block span (mean) | span p99 | phantom edges/block, adaptive 50% + 10% hyst |
|---|---|---|---|
| noise 0.61 mV RMS (1 LSB @±5 V, 14-bit) | 5.1 mV | 5.8 mV | 9129 → **547 752 "RPM"** |
| noise 2.0 mV RMS | 16.7 mV | 18.8 mV | 9161 |
| noise 5.0 mV RMS | 41.9 mV | 46.7 mV | 9099 |
| noise 20 mV RMS | 168 mV | 189 mV | 9109 |
| noise 80 mV RMS | 673 mV | — | — |

A ratio test (span/MAD) was evaluated and **rejected**: noise sits at span/MAD ≈ 12.5,
and a 50%-duty pulse train with 80 mV noise sits at **9.3** — below the noise. The ratio
test fails on exactly the signal it must accept.

The gate is an absolute minimum span:

```
MIN_PULSE_AMPLITUDE_V = 1.0
# Below this peak-to-peak span in a block, the channel is declared to have no
# tach signal and RPM is reported as None -- never as 0.0.
#
# Measured block span (1.0 s, N=41666) of pure Gaussian noise, which is what a
# disconnected or stopped-and-flat tach input looks like:
#     noise RMS   span mean   span p99
#      0.61 mV      5.1 mV      5.8 mV     (1 LSB at +-5 V, 14-bit)
#      2.0  mV     16.7 mV     18.8 mV
#      5.0  mV     41.9 mV     46.7 mV
#     20.0  mV    168   mV    189   mV
#     80.0  mV    673   mV      --        (pessimistic +-20 V front end)
# 1.00 V clears the worst modelled case by 1.4x and still accepts any real
# logic-level tach, whose swing is >= 2 V by definition. Without this gate an
# adaptive threshold on pure noise returns ~9100 edges/block -- 547 752 RPM.
```

The distinction between `rpm = None` and `rpm = 0.0` is load-bearing: "I cannot see a
tach signal" and "the shaft is stopped" are different facts leading to different actions.

## 1.5 Estimator choice and its measurement

1800 RPM, 1.0 s block, 200 repetitions per row, first-to-last (≡ mean of intervals) vs
median of intervals:

| case | first-to-last | median-of-intervals |
|---|---|---|
| clean | −0.02 ± 0.00 | −0.15 ± 0.00 |
| + 0.5% cycle jitter | −0.01 ± **0.43** | −0.05 ± 1.78 |
| + 2% cycle jitter | +0.04 ± **1.74** | −0.62 ± 7.42 |
| **one edge dropped** | **−62.09** | **−0.15** |
| **one spurious extra edge** | **+62.05** | **−0.15** |
| **three edges dropped** | **−179.39 ± 19.42** | **−0.15** |

First-to-last is 4× tighter under real torsional jitter and **catastrophic** under a
single miscounted edge — 3.4% error, reading as a speed change large enough to
invalidate everything downstream. Median-of-intervals is immune to miscounts at the cost
of a small quantisation bias (−0.15 RPM, 83 ppm) removed by interpolation.

**Median of intervals is the reported estimator**, with a consistency metric alongside:

| case | p50 | p99 |
|---|---|---|
| clean | 0.001 | 0.001 |
| 0.5% jitter | 0.016 | 0.025 |
| 2% jitter | 0.064 | **0.096** |
| **one dropped edge** | **1.000** | 1.000 |
| **one extra edge** | **0.998** | 0.998 |

```
INTERVAL_SPREAD_MAX = 0.25
# max|interval - median interval| / median interval, above which the RPM
# reading is flagged 'inconsistent'. Measured (1800 RPM, 1.0 s block, 200 reps):
#     clean                 p50 0.001   p99 0.001
#     0.5% cycle jitter     p50 0.016   p99 0.025
#     2%   cycle jitter     p50 0.064   p99 0.096   <- worst legitimate case
#     one dropped edge      p50 1.000
#     one spurious edge     p50 0.998
# 0.25 sits 2.6x above the worst legitimate shaft jitter and 4x below a single
# miscounted edge, which is the only failure this is trying to name.
```

## 1.6 What must persist for reproducibility six months on

**Stored, because it changes the number:** ~~the raw tach waveform~~ **the per-frame edge
times** (D-2); `pulses_per_rev`; polarity; threshold mode and, if
fixed, its level; `min_amplitude_v`; hysteresis fraction; channel coupling and voltage
range (already stored); achieved `samplerate` (already stored per frame). Plus derived
per-frame RPM, edge count and quality flag as a cross-check.

**Deliberately not stored:** direction of rotation, and angular offset from tach pulse to
a reference axis. Neither changes the RPM, both are consumed only by balancing and
order-tracking angle origins, and neither has a consumer that would validate them.
**An unvalidated metadata field that looks authoritative and is silently wrong is worse
than an absent one** — the same argument `ChannelResult.band_fmin` makes for not
defaulting to a plausible band. Add them with the code that checks them.

Because the waveform is stored, RPM is a *view* on stored data in exactly the sense
CLAUDE.md requires: change `pulses_per_rev` after loading and the RPM recomputes. The
stored per-frame RPM is a cross-check, not the source of truth.

## 1.7 Explicitly out of scope

- **Headless.** Settled by the owner — but see §2.9: headless must be made *safe*, not
  merely feature-less.
- **Balancing / phase reference.** §1.3, with the phase table as the argument.
- **Order-normalised analysis, order spectra, order trending.** §1.3. Forward
  compatibility preserved by storing the waveform.
- **Synchronous time averaging.** Same dependencies as balancing.
- **Cross-block edge continuity.** Phase 1 detects per block, making live and replay
  bit-identical for free and costing the min-RPM table in §1.2. A cheap phase-1.5
  refinement (use the previous frame's last edge for the boundary interval only, which
  replay reproduces exactly from the ordered cache) is noted, not built.
- **Multiple tach channels / gearbox multi-shaft.** Needs order ratios and a
  machine-train model — a different feature.
- **Narrow-pulse guards, warnings, hysteresis tuning.** Settled; floor documented once
  in §1.4 and nowhere else.
- **Direction and angular offset.** §1.6.

## 1.8 The four-input tradeoff

**Throughput: none.** `picoscope.py`'s `STREAMING_CEILING_HZ` comment records 40 kHz /
osr 2 / ~83.3 kHz per channel as clean with 0 overflow and 0 rate-degradation events at
both 3 and 4 simultaneous channels, sustained 45 s, repeatably. A tach as 3rd or 4th
channel is inside the already-validated envelope.

**Resolution: real, magnitude unknown without hardware.** `_set_max_resolution` gives
16-bit at ≤1 enabled channel and 14-bit at 2–4. A user running one accelerometer at
16-bit who adds a tach drops to 14-bit — nominally 12 dB of ADC dynamic range on the
*vibration* channel. Whether that is visible above the 4424A's front-end noise is a
hardware question (§3.3 item 6) and must not be asserted from the bit count. Documented
as a caveat; the answer belongs next to the constant once measured.

Recommendation is unchanged by either: on a 4-input instrument, 2 accelerometers + 1 tach
leaves a spare, and a tach on a variable-speed machine is worth more than a third point.

---

# Part 2 — Implementation plan

## 2.1 Where edge detection runs, and why

**In `DataCollector.receive_data`, on the raw mV column, before `filter_block`, and
`filter_block` is skipped entirely for tach channels.**

**(1) The high-pass destroys a tach signal.** Every channel currently goes through
`filter_block(ch, data, samplerate, stateful=True)`. Measured, 5.00 V pulse train,
1.0 s block, edges at a 2.5 V threshold:

| RPM | width | duty | raw hi/lo (mV) | after HP (mV) | raw edges | HP edges |
|---|---|---|---|---|---|---|
| 300 | 1 ms | 0.5% | 5440 / −440 | 5420 / −1124 | 6 | 6 |
| 1800 | 200 µs | 0.6% | 5441 / −465 | 5442 / −585 | 31 | 31 |
| **1800** | **5 ms** | **15%** | 5440 / −440 | 5891 / −3390 | **31** | **108** |
| **3600** | **10 ms** | **60%** | 5440 / −440 | **3961** / −5341 | **61** | **60** |

At 15% duty the high-pass overshoot on each falling edge re-crosses the threshold and the
shaft reads **6270 RPM instead of 1800** — a 3.5× overspeed on a machine that is fine. At
60% duty it drops the peak from 5440 to 3961 mV and drops an edge. `filtered_data_for`
would then cache that wreckage on the sample and hand it to replay.

**(2) `receive_data` runs exactly once per frame, in stream order** — the same property
the high-pass state carry requires, so the tach result can be cached on the `VibeSample`
with no risk of double application. `process_sample` is called many times per frame and
in arbitrary order when browsing.

**(3) Cost is negligible.** A vectorised Schmitt detector measured **0.090 ms** on a
1.0 s block (N=41 666) and **0.202 ms** on a 4.0 s block, against block periods of 1.0 s
and 4.0 s. The naive Python loop is 6.1 / 11.7 ms — 68× and 58× slower, and also *wrong*:
it reports a spurious edge at sample 1 whenever a block starts mid-pulse. The vectorised
form requires an actual crossing. **Use it; the block-start partial pulse is a test case.**

The tach is **not** exempted from `antialias_decimate`. Exempting it would give 12 µs
instead of 24 µs resolution but break the one-samplerate-per-frame invariant that
`VibeSample.samplerate`, `_write_channel_group`, the HDF5 frame attrs and every reader
depend on. Measured cost of not exempting: zero for pulses ≥50 µs, against a timing
budget already met with 50–300× margin.

## 2.2 New module: `src/rev80/tach.py`

Pure functions plus two dataclasses. No I/O, no DPG, no collector. ~200 lines with the
measured tables in place.

```python
MIN_PULSE_AMPLITUDE_V: float = 1.0
HYSTERESIS_FRAC:       float = 0.10
INTERVAL_SPREAD_MAX:   float = 0.25
MIN_EDGES:             int   = 3

@dataclass(frozen=True)
class TachSettings:
    pulses_per_rev:  int   = 1
    polarity:        str   = 'rising'      # 'rising' | 'falling'
    threshold_mode:  str   = 'adaptive'    # 'adaptive' | 'fixed'
    threshold_v:     float = 2.5           # only when mode == 'fixed'
    min_amplitude_v: float = MIN_PULSE_AMPLITUDE_V
    hysteresis_frac: float = HYSTERESIS_FRAC
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> 'TachSettings': ...   # coerced like ScopeSensor.from_dict

@dataclass(frozen=True)
class TachResult:
    channel:         int
    rpm:             float | None      # None == no usable reading. NEVER 0.0.
    quality:         str               # 'ok'|'no_signal'|'too_few_edges'|'inconsistent'
    n_edges:         int
    span_v:          float
    interval_spread: float
    pulses_per_rev:  int
    samplerate:      float
    rel_time:        float
    edge_times_s:    np.ndarray
    @property
    def shaft_hz(self) -> float | None: ...

def detect_edges(x_mv, samplerate, settings) -> np.ndarray:   # float sample indices
def estimate_rpm(edge_idx, samplerate, settings, ch, rel_time) -> TachResult
def tach_result(x_mv, samplerate, ch, rel_time, settings) -> TachResult
```

`detect_edges`: invert `x` when `polarity == 'falling'` (one place, once); compute
`span = max − min`; return empty if `span < min_amplitude_v`; place `hi/lo` at
`mid ± hysteresis_frac/2 × span` (adaptive) or `threshold_v ± hysteresis_frac/2 × span`
(fixed); find rising crossings of `hi` and falling of `lo`, keeping a rising crossing
only when it is the first after a falling one; linear-interpolate each kept crossing
between its two straddling samples.

`estimate_rpm` divides by `pulses_per_rev` **exactly once**, here and nowhere else:
`rpm = 60 / (median(diff(edges))/samplerate) / ppr`.

`samplerate` is a required argument, never defaulted from `RAW_SAMPLERATE_HZ`. There is
a test for that (§3.1).

## 2.3 Data model changes

### `sample.py` — `AcquisitionSettings`

```python
channel_roles: dict = field(default_factory=dict)   # {ch: 'vibration'|'tachometer'}

speed_gate_enabled:       bool         = False
speed_gate_rpm:           float | None = None   # None = latch from first valid frame
speed_gate_tolerance_pct: float        = 3.0

def role_for(self, ch: int) -> str:            # default 'vibration'
@property
def tach_channels(self) -> list[int]:
@property
def vibration_channels(self) -> list[int]:
```

`speed_gate_*` go into `to_dict`/`from_dict` (scalars). `channel_roles` does **not** —
per-channel dicts live in `/metadata/channels`, matching `channel_names` and friends.

> **`AcquisitionSettings.copy()` will silently drop `channel_roles` unless its explicit
> tuple is edited.** That tuple is `('channel_voltage_ranges', 'channel_couplings',
> 'channel_names', 'channel_target_units', 'channel_amplitude_modes')`. Forgetting it is
> audit H-08 exactly. A copied settings object turns a tach back into a vibration channel
> and processes a pulse train as vibration. **Test that `copy()` round-trips
> `channel_roles`, and revert-check it.**

### `sample.py` — `ChannelResult` (frozen; new fields with defaults)

```python
rpm:      float | None = None   # shaft speed at this frame's capture instant
speed_ok: bool         = True   # within the declared window (or gating off)
```

`speed_ok` defaults `True` so every existing construction site, fixture and reconstructed
result is unaffected.

### `sample.py` — `VibeSample`

```python
tach: 'TachResult | None' = field(default=None, repr=False)
_tach_config_key: tuple | None = field(default=None, repr=False)
```

Cached like `psd_mv`/`filtered_mv`, keyed on `(samplerate, TachSettings.to_dict() tuple)`,
so changing `pulses_per_rev` after load invalidates and recomputes.

### `util.py`

```python
CHANNEL_ROLES = ('vibration', 'tachometer')
DEFAULT_CHANNEL_ROLE = 'vibration'
```
Both into `__all__`.

### `config.py`

Extend `_BUILTIN_CHANNEL_TEMPLATE` with `'role': 'vibration'` and a nested `'tach'` block
of `TachSettings` defaults. Extend `_BUILTIN_ACQ['acquisition']` with the three
`speed_gate_*` keys. `_merge_device` / `_merge_acquisition` fill missing keys from the
template, so old config files upgrade silently and correctly.

## 2.4 `collector.py`

**`receive_data`**, per channel:

```python
role = self.config.role_for(ch)
if role == 'tachometer':
    # No high-pass: measured, it triples the edge count at 15% duty
    # (31 -> 108 edges, 1800 RPM reads 6270). See tach.py.
    filtered = None
    tach = rev80.tach.tach_result(data, samplerate, ch, samp['rel_time'],
                                  self.tach_settings.get(ch, TachSettings()))
else:
    filtered = self.filter_block(ch, data, samplerate, stateful=True)
    tach = None
```

**New state and API:**

```python
self.tach_settings: dict[int, TachSettings] = {}
self.tach_trend: dict[int, dict[str, np.ndarray]] = {}
self._speed_ref_rpm: float | None = None

def set_tach_settings(self, ch, settings: TachSettings | None) -> None
def tach_for(self, ch, sample) -> TachResult          # cache-or-recompute, for replay
def current_rpm(self) -> float | None
def speed_ok(self, rpm: float | None) -> bool         # the gate, one place
def get_rpm_trend(self) -> dict[int, tuple[list, list]]
```

`speed_ok` is the *only* place the gate is evaluated:

```python
def speed_ok(self, rpm):
    if not self.config.speed_gate_enabled:
        return True
    if rpm is None:
        return False     # fail closed
    ref = self.config.speed_gate_rpm or self._speed_ref_rpm
    ...
```

> **Fail closed on a missing tach reading.** If gating is on and the tach goes dead
> mid-session (cable pulled, tape peeled, LED aged out), every subsequent frame is
> `speed_ok = False`, excluded from anomaly evaluation and baseline adaptation, and
> flagged on screen. Treating "no speed reading" as "speed is fine" leaves an unattended
> monitor alarming on load-driven swings it can no longer see — the exact false-alarm
> mechanism the gate exists to remove.

**`process_samples`** iterates `config.vibration_channels`, not `enabled_channels`. Tach
channels never produce a `ChannelResult`. Each vibration result carries
`rpm=self.current_rpm()` and `speed_ok=self.speed_ok(rpm)`.

**Trend asymmetry, deliberate.** `process_samples` continues to exclude only
`overflow or degraded` from `self.trend`, and additionally records the frame's RPM.
`valid_results()` additionally excludes `not speed_ok`. Overflow and degraded mean *the
number is wrong*; speed-out-of-window means *the number is right but not comparable*.
Discarding it from the trend would throw away the amplitude-vs-speed relationship, which
is itself diagnostic; discarding it from alarming is mandatory. Comment it, or the next
reader will "fix" it.

**`init_trend_channels`** and **`get_trend_for_display`** iterate `vibration_channels`.
`tach_trend` is separate from `trend` because RPM must never run through `UNIT_TO_SI`,
`amplitude_scale` or `integration_steps` — the same reason `crest_factor` and `kurtosis`
sit beside `orders` rather than as columns of it.

**`reset_channel_config(num_channels)`** must also prune `channel_roles` and
`tach_settings` for `ch >= num_channels`, or moving from a 4-channel to a 2-channel scope
leaves channel 3's tach role on an index the new device uses for vibration.

**`reprocess_session_trend`** must skip tach channels, or it writes a fabricated
`overall_json` entry and the reconstructed trend grows an extra line.

**`eu_scaled_raw`** must refuse a tach channel — no `ScopeSensor`, no EU; current code
would silently divide by `sensitivity=1.0` and return mV labelled `'mV'`. Raise or return
`None`, but do not return something plausible.

## 2.5 HDF5

**Measurement file: `_FILE_VERSION` 4 → 5.** All additive. **The per-frame layout below
is superseded by D-4** — a tach channel stores `edge_times`, not `data`:

```
/metadata/channels/{ch}.attrs   role                 'vibration' | 'tachometer'
                                tach_pulses_per_rev  int
                                tach_polarity        str
                                tach_threshold_mode  str
                                tach_threshold_v     float
                                tach_min_amplitude_v float
                                tach_hysteresis_frac float
/metadata/acquisition.attrs     speed_gate_enabled / speed_gate_rpm / speed_gate_tolerance_pct
/frames/{i}.attrs               rpm            float, NaN = no reading
                                rpm_quality    str
                                rpm_channel    int, -1 = none
/tach_trend/{ch}/rel_times      (M,) float64
/tach_trend/{ch}/rpm            (M,) float64, NaN = not recorded
```

Readers use `.get(..., default)` and `if key in grp`, as `crest_factor`/`kurtosis` do, so
a v5 reader reads v4 files with `role='vibration'` everywhere — correct, since they
contain none.

**Why bump when the change is additive.** The reverse direction is a wrong number: an
older build reading a v5 file takes the `version >= 4` branch, restores the tach as a
vibration channel, computes a bogus overall on a square wave, trends it, and reports
crest factor 5.0 / kurtosis 15.9 on it (measured, §2.10). Bump **and** add a
forward-compatibility guard in `_restore_metadata`:

```python
if version > self._FILE_VERSION:
    log.warning("File version %d is newer than this build supports (%d); "
                "some channels may be misinterpreted.", version, self._FILE_VERSION)
```
Worth having independently of the tach.

**Monitor session: `_FILE_VERSION` 5 → 6.** Add `gate_grp.attrs['rpm_json']`
(`{ch: rpm|null}`) beside `overall_json`/`scalars_json`, mirroring
`_compute_overall_peaks`. Same for burst frames.

(The two counters are independently numbered and both currently read 5; pre-existing and
confusing. Note in CHANGELOG; do not renumber here.)

## 2.6 Simulation

`SimulatedSensor._sample()` currently does `np.tile(signal, (n_ch, 1)).T` — **every
channel gets the identical signal**, so a simulated tach is impossible today. Largest
single change outside the collector.

```python
self.channel_sources: dict[int, tuple] = {}   # {ch: (fn, *args)}; empty -> current tile
```
`_sample()` generates per column from `channel_sources.get(ch, self.source)`. With the
dict empty, behaviour is byte-identical to today, so no existing test moves.

```python
def GenerateTachPulse(config, rpm=1800.0, pulses_per_rev=1, width_s=200e-6,
                      amplitude_v=5.0, polarity='rising', offset_v=0.0,
                      jitter_pct=0.0, phase_s=0.0, seed=None) -> np.ndarray  # mV

def GenerateMachineWithTach(config, running_rate=60.0, severity=1.0, ppr=1,
                            seed=None) -> dict[int, np.ndarray]
```

`GenerateMachineWithTach` must produce a tach pulse train **phase-coherent with the
vibration's shaft rate**, sharing `running_rate` and shaft phase with
`GenerateBearingVibration`. Without coherence you cannot test that measured RPM matches
the vibration's own 1×, and can never validate order tracking. Same argument
`simulation.py` already makes about pure cosines and envelope analysis: a wrong tach and
a right one both return a plausible number against an incoherent signal.

`VibeSensor.simulated()` needs no change — `_callback` already fits `scale` to the actual
channel count.

## 2.7 GUI

1. **Channel row (`_rebuild_device_channel_rows`)**: Role combo, `Vibration | Tachometer`.
   Tachometer disables the Sensor and Target-Unit combos (a tach has neither), forces
   Coupling to DC with a tooltip carrying the §1.4 table, and reveals a tach sub-panel:
   pulses/rev, polarity, threshold mode, threshold, min amplitude.
2. **Frame info bar (`_update_frame_info`)**: `1798.4 RPM  (29.97 Hz)  ·  30 edges  ·  OK`,
   or `-- RPM  (no tach signal)`, or `1798.4 RPM  ·  INCONSISTENT (spread 0.99)`. Never a
   bare `0`.
3. **Tach waveform view.** Raw tach trace with the computed threshold drawn as a
   horizontal line and detected edges marked. The commissioning tool: when RPM reads
   nothing, the operator must *see* whether the pulse is too small, the threshold is
   misplaced, or the coupling is stripping DC. Without it every tach problem is a support
   call.
4. **Order cursors on the spectrum plot.** Vertical markers at 1×, 2×, … N× from the
   measured RPM, toggleable. Highest-value, lowest-risk consumer of shaft speed in the
   whole feature; needs no resampling.
5. **Peaks table**: an `Order` column, `freq / (rpm/60)`, shown only when `rpm` is valid.
   `_update_fft_peaks_table` already takes `columns` as a list.
6. **Trend plot**: RPM series on a second y-axis from `get_rpm_trend()`.
7. **Monitor card**: speed-gate state and latched reference RPM.
8. `_update_time_plot` / `_update_freq_plot` / `_update_envelope_plot` /
   `_add_channel_series` iterate over results and are automatically safe once tach
   channels produce no `ChannelResult`. `_update_trend_plot` iterates `enabled_channels`
   and must switch to `vibration_channels`.

## 2.8 Monitor

`MonitorController.on_results` needs no change: `results` no longer contains tach
channels, and `frame_cache` does (correctly — the waveform must be written).

Two existing-code hazards:

- **`_compute_pretrigger_overalls`** iterates `frame_dict.items()` for every `int` key and
  reads `sample.overall_ampl_by_integration_order[col]`. For a tach `VibeSample` that
  array is never populated (stays at its `np.zeros(5)` default, since `process_sample`
  never runs on it), so it writes `0.0` into `overall_json`, and `load_monitor_session`
  rebuilds a trend line pinned at zero. **Must skip tach channels.**
- **`monitor/writer.py:_compute_overall_peaks`** is safe once tach channels are excluded
  from results — and is where `rpm_json` gets added.

`_build_anomaly_hook` is **not touched**, in either copy, by design (§1.3).

## 2.9 `headless.py` — required change despite tach being out of scope

Headless builds config from the same `devices/*.yaml` and iterates
`config.enabled_channels`. A device configured in the GUI with a tach on channel D will,
under `rev80-headless`, enable channel D, high-pass a pulse train, compute an overall on
it, trend it, feed it to the anomaly hooks, and record it as a vibration channel.

Measured, 5.00 V / 5% duty pulse train at 1800 RPM through the real `process_sample`:

| RPM | duty | overall (mV) | crest | **kurtosis** | peaks reported |
|---|---|---|---|---|---|
| 1800 | 5% | 1514.9 | 5.00 | **15.94** | 63 |
| 1800 | 10% | 2103.7 | 3.67 | 6.79 | 60 |

Kurtosis 15.9 is a severe-impulsiveness reading. An analyst reviewing an unattended
session sees kurtosis 16, crest 5.0 and 63 spectral peaks and concludes a bearing is
failing badly. And it drifts on nothing: a tach LED ageing from 5.0 V to 4.5 V of pulse
amplitude — no machine change at all — moves that channel's overall by exactly **−10.0%**,
which is the shipped `RmsThresholdHook` threshold, on three consecutive frames, firing a
burst.

**Minimum required change: `headless.py` must read `channel_roles` and refuse to enable
tach-role channels**, with an INFO line saying so. The smallest change consistent with
"no tachometer support in headless" that does not also mean "headless produces a wrong
number".

## 2.10 Assumptions a tach breaks

| assumption | where | what a tach does to it | fix |
|---|---|---|---|
| a `ScopeSensor` with sensitivity and EU | `process_sample`, `eu_scaled_raw`, `get_trend_for_display`, `save_data` | falls back to `sensitivity=1.0`, `eu='mV'` — silently reads raw mV as engineering units, the classic field error | tach never reaches these paths |
| a high-pass filter | `receive_data` → `filter_block` | 31 → 108 edges at 15% duty; 1800 RPM reads 6270 | skip for tach |
| a `ChannelResult` with spectrum, overall, peaks | `process_samples` | 1515 mV overall on a square wave, 63 "peaks" that are its harmonics | tach excluded |
| a crest factor / kurtosis an analyst reads | `ChannelResult` | crest 5.00, **kurtosis 15.94** — reads as a severe bearing fault | same |
| valid for alarming | **`monitor/anomaly.py:valid_results()`** | keeps the tach result; the 10% LED-ageing drift fires a burst | tach excluded; `speed_ok` clause added here |
| valid for trending | `process_samples` | a fifth mV trend line tracking LED brightness | tach excluded |
| an EU-scalable trend | `get_trend_for_display` | `integration_steps('mV','mV') = 0`, plots raw mV alongside in/s | `vibration_channels` |
| a populated `overall_ampl_by_integration_order` | `_compute_pretrigger_overalls` | writes `0.0`; a zero trend line in every loaded session | skip tach |
| one processable channel per HDF5 digit key | `reprocess_session_trend`, `_read_frame_group` | processes the tach as vibration on reprocess | role restored before use; skip in reprocess |
| per-channel dicts enumerated by name | **`AcquisitionSettings.copy()`** | `channel_roles` silently dropped — H-08 recurrence | edit the tuple; test; revert-check |
| per-channel state pruned on device change | `reset_channel_config` | tach role sticks to an index now used for vibration | prune roles + tach settings |
| every channel gets the same simulated signal | `SimulatedSensor._sample` | a simulated tach is impossible | per-channel sources |
| a channel is a vibration channel | `headless.py` | §2.9 | read roles, refuse to enable |

## 2.11 Sequencing — every step leaves the suite green

Branch `feature/tachometer`. Baseline at start: 774 passed / 7 skipped.

1. ✅ **DONE** (`54cbd66`, `8110063`, `e13fa9b`) — **`tach.py` + `tests/test_tach.py`.**
   44 tests, 11/11 invariants revert-checked. Three deviations from the spec above,
   all deliberate:
   - **Units are mV, not V** (`MIN_PULSE_AMPLITUDE_MV = 1000.0`, `threshold_mv`).
     `VibeSample.data` is mV and sensitivity is mV/EU; a volts-named field carried
     through an mV pipeline is a seam waiting to be crossed wrongly.
   - **`no_signal` and `too_few_edges` are separated.** The span gate is answered in
     `tach_result` before detection, so a healthy 2 V pulse train on a shaft too slow
     to fit three pulses in a block is not reported as a dead cable.
   - **A pulse-rate accuracy ceiling was found on the bench** and is not in the spec
     above: below ~40 samples per pulse period *both* interpolated and nearest-sample
     estimates collapse to ~0.8 %, because the median locks onto the modal integer
     period (27.778 samples reads as exactly 28.000). Full accuracy needs **≥ ~70
     samples per pulse, i.e. pulse rate ≲ 600 Hz** — 36 000 RPM at 1 ppr, 600 RPM at
     60 ppr, 35 RPM at 1024 ppr. This binds sooner than pulse width does and the
     channel-config UI must say so (step 9).

   Also measured, closing the "does interpolation survive a ns TTL edge" question: a
   real captured edge carries **exactly one intermediate sample** and the interpolated
   fraction varies over [0.294, 0.707], so sub-sample information is genuinely present.
   Interpolation is worth 4.2× at 208 samples/period and 13.8× at 69, marginally
   *negative* above ~1000 samples/period (both under 0.03 %, so it does not matter).
   Divide-by-zero is unreachable by construction (`y0 <= hi < y1`); measured minimum
   denominator over 2880 real edges was 1461.7 mV.

2. ✅ **DONE** (`2ec1700`) — **`channel_roles`, `speed_gate_*` persistence.** Fields,
   `role_for()`, `tach_channels`/`vibration_channels`, the `copy()` tuple edit, and the
   `config.py` templates. 9/9 invariants revert-checked, including the H-08 trap itself.
   `TachSettings` per-channel persistence is templated (`'tach': None` in the channel
   block) but not yet read or written — that lands with the collector in step 4.

3. ⬜ **NEXT — Simulation.** `channel_sources`, `GenerateTachPulse`, `GenerateMachineWithTach`.
   Existing behaviour byte-identical when `channel_sources` is empty.
4. ⬜ **Collector wiring.** Role-aware `receive_data`; `tach_settings`; `tach_for`;
   `current_rpm`; `process_samples` on `vibration_channels`; `tach_trend`;
   `reset_channel_config` pruning; `eu_scaled_raw` refusal; `reprocess_session_trend`
   skip. End-to-end test against `GenerateMachineWithTach`.
5. ⬜ **Persistence.** v5 measurement file, forward-version warning, `/tach_trend`,
   per-frame `rpm`. Round-trip tests, including re-derived RPM == stored RPM under
   unchanged settings and ≠ under changed `pulses_per_rev`.
6. ⬜ **Speed gate.** `ChannelResult.rpm`/`speed_ok`; `DataCollector.speed_ok`; the
   `valid_results()` clause. Revert-checked tests including fail-closed.
   `_build_anomaly_hook` untouched in both copies; `tests/test_anomaly_hook_build.py`
   must still pass unmodified — that is the check that the seam was chosen right.
7. ⬜ **`headless.py` refusal.** §2.9.
8. ⬜ **Monitor.** `rpm_json` in `session.h5` (v6); `_compute_pretrigger_overalls` skip;
   speed-gate state on the card.
9. ⬜ **GUI.** All of §2.7.
10. ⬜ **Hardware close-out** (§3.3) and docs. `doc/CHANGELOG.md`, `doc/PROGRESS.md`,
    `README.md` updated **in the same commits**, not as a pass at the end.

---

# Part 3 — Verification

## 3.1 What CI can prove, and how not to let it pass degenerately

Traps to design against — each one this suite has already been burned by, in the same shape:

- **On-grid pulse rates.** At the simulated 40 000 Hz, 600 RPM at 1 ppr is exactly 4000.0
  samples per pulse — the tach equivalent of a bin-centred tone, the one case where
  quantisation error vanishes identically. **Parametrise over RPM values giving
  non-integer sample periods** (1793.3, 2617.9, 733.1) **and independently sweep the
  pulse start phase across one sample interval.**
- **50% duty only.** The single duty at which adaptive and fixed thresholds coincide.
  Sweep 1%, 5%, 15%, 30%, 50%, 60%, 80%.
- **Idealised square arrays.** A test on `5.0 * (t % T < w)` never sees the Gibbs
  overshoot or the −0.70 V undershoot. **Push every timing test through
  `antialias_decimate`.**
- **DC-coupled, noise-free only.** Include an AC-coupled case (1-pole 1 Hz high-pass) and
  2 / 20 / 80 mV RMS noise.
- **`rpm == 0`.** Assert `rpm is None` for no signal. A test asserting `== 0` passes for
  both "no signal" and a broken detector returning zero.
- **`RAW_SAMPLERATE_HZ`.** Feed a block tagged `samplerate=41666.5` (the real hardware
  value) and assert the returned RPM is the true one, not 1.0417× it. This fails today
  for any implementation that reaches for the constant, and is the only thing standing
  between the field and a 4.2% speed error.

**Placement, per house rules:**

- `tests/test_tach.py` — edge detection mechanics: hysteresis, min-span gate, polarity
  applied once, ppr applied once, quality flags, the block-start partial-pulse case,
  `rpm is None` for noise, vectorised/loop divergence.
- **`tests/test_measurement_validity.py`** — all RPM *accuracy* assertions. Timing
  assertions belong in the file that is off-grid and phase-swept by construction.
  Reproduce the §1.2 table as a parametrised test with tolerances set from it
  (`< 0.6` for 60-ppr @600 RPM, `< 0.2` for 1 ppr).
- `tests/test_sample.py` — nothing. It is deliberately on-bin.
- `tests/test_tach_pipeline.py` (new) — role plumbing: a tach channel yields no
  `ChannelResult`, is absent from `get_trend_for_display` and `valid_results`, is not
  high-passed, survives `copy()`, is pruned by `reset_channel_config`.
- `tests/test_monitor_anomaly.py` — speed gate: a `speed_ok=False` frame neither fires nor
  adapts the baseline; `rpm is None` with gating on fails closed.
- `tests/test_vibechecker.py` + new `tests/test_tach_persistence.py` — v5 round-trip;
  re-derived RPM equals stored RPM under unchanged settings; changing `pulses_per_rev`
  after load changes the RPM (proving it is a view, not baked in); a v4 file loads with
  `role='vibration'`.
- `tests/test_anomaly_hook_build.py` — **must pass unmodified**, proving the speed gate
  did not touch either copy of `_build_anomaly_hook`.

**Revert-checks required:**

| invariant | remove this | expected failure |
|---|---|---|
| tach bypasses the high-pass | the role branch in `receive_data` | 108 edges instead of 31 at 15% duty; RPM 6270 vs 1800 |
| adaptive threshold | force `threshold_mode='fixed'`, AC-coupled 60% duty | 0 edges, `rpm is None` where 1800 expected |
| min-span gate | set `min_amplitude_v = 0` | ~9100 edges on a noise-only block |
| median, not first-to-last | swap estimator, drop one edge | −62 RPM at 1800 |
| ppr applied once | remove the divide | RPM off by exactly `ppr` |
| `samplerate` from the sample | substitute `RAW_SAMPLERATE_HZ` | 1875.0 instead of 1800.0 |
| `speed_ok` in `valid_results` | remove the clause | out-of-window frame adapts baseline and can fire |
| `copy()` carries roles | remove `'channel_roles'` from the tuple | copied settings process the tach as vibration |
| tach out of results | revert `vibration_channels` | kurtosis 15.94 appears on a channel card |

## 3.2 Simulation-based end-to-end (CI, no hardware)

`GenerateMachineWithTach` on 2 channels through a real `SimulatedSensor` + `DataCollector`:

- measured RPM matches the generator's `running_rate × 60` to within 0.2 RPM;
- measured RPM matches the 1× peak located in the *vibration* channel's own spectrum —
  the coherence check, which proves the tach is reading the same shaft, and is impossible
  without the phase-coherent generator;
- the vibration channel's `ChannelResult` is unchanged from a run with the tach absent, to
  floating-point equality (proving the tach path is inert for vibration);
- with `severity=0` and `jitter_pct=2`, quality stays `'ok'` and `interval_spread` stays
  below 0.10, matching §1.5.

## 3.3 What needs the 4424A and AWG loopback

Add to `tests/test_picoscope_hw.py`, self-skipping as the rest do.

1. **Baseline accuracy.** AWG `PS4000A_SQUARE`, 30.000 Hz, 5 Vpp, 2.5 V offset → channel
   A, **DC-coupled, ±10 V**. Assert RPM = 1800 ± 0.5. The AWG's DDS clock is orders of
   magnitude better than the requirement.
2. **Sweep.** AWG 5 → 170 Hz (300 → 10 200 RPM at 1 ppr). Assert tracking within 0.1% at
   every point — the electrical version of the §1.2 table.
3. **The AC-coupling failure, reproduced electrically.** Same square wave, channel A set
   to **AC**. Assert a fixed 2.50 V threshold returns `quality == 'no_signal'` **and** the
   adaptive threshold still returns 1800 ± 0.5. The electrical proof of the headline
   finding and the justification for the default. (The 4424A's built-in square is 50%
   duty; a non-50% crossing can be synthesised with `PS4000A_RAMP_UP` plus an offset, or
   with `ps4000aSetSigGenArbitrary` if the wrapper exposes it — §3.4.)
4. **Pulse-width floor sanity.** Drive fast enough for ~50 µs highs; confirm detection.
   Confirm once that ~20 µs is not detected, matching §1.4. Documented once; no guard built.
5. **Crosstalk.** Square wave into channel A; channel B shorted or 50 Ω terminated;
   measure B's spectrum for a 30 Hz line and harmonics. Report in mV. Above ~1 mV this
   becomes a cabling instruction in the manual, not a code change.
6. **Resolution cost of the extra channel.** Fixed AWG sine on channel A alone (16-bit)
   and again with channel B enabled (14-bit). Compare measured noise floor over the
   declared band, report the difference in dB. **This decides whether "a tach costs a bit
   of dynamic range" is a real caveat or a theoretical one, and it must be measured, not
   inferred from the bit count.** Record next to `_set_max_resolution`.
7. **Four-channel sustained run.** 3 vibration + 1 tach, 45 s, per
   `scripts/validate-streaming-capacity`. Assert 0 overflow and 0 rate-degradation
   transitions.

## 3.4 What could not be verified without hardware

Each has a constant or a claim resting on it:

- ~~**The 4424A's real front-end noise.**~~ **MEASURED — D-5.** 5.09 mV RMS at ±20 V;
  `MIN_PULSE_AMPLITUDE_V = 1.0` confirmed with 23.5× margin.
- *(original text, for the record)* The 4424A's real front-end noise at ±5 V and ±20 V. `MIN_PULSE_AMPLITUDE_V = 1.0` is
  set from a *modelled* 0.61–80 mV RMS range (worst-case span 0.71 V). If real ±20 V noise
  exceeds ~120 mV RMS the constant needs revisiting. **Measure and record the table beside
  the constant before closing out.**
- ~~**The 4424A's true AC-coupling corner.**~~ **MEASURED — D-5**, and the duty-cycle
  failure is reproduced electrically at 70% and 85%.
- *(original text, for the record)* The 4424A's true AC-coupling corner, modelled as 1-pole 1 Hz. The 60%-duty failure is
  qualitatively insensitive to the exact corner (mean removal, not droop, does the damage),
  but the §1.4 numbers are modelled and should be re-measured.
- ~~**Whether the AWG can produce a non-50% duty waveform.**~~ **RESOLVED — D-5.**
  `SetSigGenBuiltIn` takes no duty parameter, but `ps4000aSetSigGenArbitrary` and
  `ps4000aSigGenFrequencyToPhase` are both present and were used to prove the mechanism.
- *(original text, for the record)* Whether `ps4000aSetSigGenBuiltIn` exposes a duty-cycle parameter.
  `_setup_siggen` passes none. Hardware test 3 needs a non-50% waveform; if the built-in
  generator cannot produce one, `ps4000aSetSigGenArbitrary` is the fallback and its
  availability in the `picosdk` wrapper is unverified.
- **The 16 → 14 bit cost** in real noise-floor dB (test 6). Do not ship the caveat as a
  number until measured.
- **Channel-to-channel crosstalk** on this hardware (test 5).
- **A real proximity-probe keyphasor** on ±20 V: whether the notch pulse, at ±20 V's
  2.44 mV LSB and against real driver noise, clears the 1.0 V gate with margin. The sensor
  type least safe to declare working on simulation alone.
- **Whether the driver's `int(1e6/80000) = 12 µs` rounding is stable** across firmware
  revisions. It is what makes the stored rate 41 666.5, and the RPM scale factor depends on
  `sample.samplerate` tracking it. `test_reported_samplerate_matches_actual_hardware_rate`
  already covers the mechanism; the tach adds a second consumer.

---

## Verdict

Safe to build as specified, in the order given, with these conditions:

- **The high-pass bypass for tach channels is not optional and not a refinement.** It is
  the difference between 1800 and 6270 RPM at 15% duty, and must be in the same commit
  that first routes a tach signal into `receive_data`.
- **The adaptive threshold is the default and fixed is the exception**, because the fixed
  threshold's failure under AC coupling is silent, reads as a stopped machine, and is
  reproducible on the bench (hardware test 3).
- **Speed gating goes in `valid_results()` and nowhere else**, so `_build_anomaly_hook`
  stays byte-identical in both copies and audit H-01 does not double.
- **`headless.py` must refuse tach-role channels** even though tachometry is out of scope
  there. Out of scope means "does not do it", not "does it wrong and reports kurtosis 15.9".
- **Order analysis and balancing phase are refused, with the measured tables as the
  reason**, and the forward path is preserved solely by storing the tach waveform.
- ~~`MIN_PULSE_AMPLITUDE_V` is provisional~~ — **now measured on hardware (D-5)** and
  confirmed at 1.0 V with 23.5× margin.
- **`SPEED_DRIFT_MAX_PCT = 1.0` (D-2) is the one constant still set from simulation**;
  it wants a load-step on a real machine to confirm.

Hardware tests 1, 3, 6 and 7 are the close-out set. 1 and 3 verify the two decisions
carrying field risk; 6 supplies the one caveat currently stated without a number; 7
confirms the throughput claim still holds with a tach in the mix.
