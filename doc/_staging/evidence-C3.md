<!-- Staging text from package W1-C3 (tach.py).
     W2-A moves each section under its E heading in CONTRIBUTING.md and
     deletes doc/_staging/. The E14.1 and E14.3 titles match pointers that
     collector.py, util.py and simulation.py already contain.
     evidence-C4.md has a short E14.1 part (from util.py) with the
     1515 mV / kurtosis 15.94 figures; merge it into E14.1.
     Source of every table: src/rev80/tach.py at 8bd106c, unless a line
     says otherwise. -->

## E14. Tachometer

`src/rev80/tach.py` finds the edges of a tachometer pulse train and
calculates the shaft speed. Each subsection gives one decision, the value,
the evidence and the conditions of the measurement.

Most tables in this section were measured on 2026-09-01. On that date the
raw rate was 40000 Hz nominal. The driver rounded the sample interval to
12 us, so the achieved rate on hardware was 41666.5 Hz (83333/2 Hz), and
the ADC ran at about 83.3 kHz per channel (oversampling ratio 2). Since
2026-09-09 the raw rate is 25600 Hz nominal. The achieved rate is about
25591.8 Hz on the 12.5 ns clock grid (E4), and the oversampling ratio is 3.
The tables were not measured again at 25600 Hz, except where a line says so.

The code takes the rate from the sample (`VibeSample.samplerate`), never
from `RAW_SAMPLERATE_HZ`. With the constant, every shaft speed was 4.166 %
high on hardware at the 41666.5 Hz rate and correct in CI. See E5.

### E14.1. No high-pass on a tachometer channel

**Decision.** `DataCollector.receive_data` finds the edges of a tachometer
channel on the raw mV block. The Butterworth high-pass does not run on that
channel.

**Evidence.** A 5.00 V pulse train, 1.0 s block, edges at a 2.5 V
threshold:

| Shaft speed (RPM) | Pulse width | Duty | Raw high / low (mV) | After high-pass (mV) | Raw edges | High-pass edges |
|---|---|---|---|---|---|---|
| 300 | 1 ms | 0.5 % | 5440 / -440 | 5420 / -1124 | 6 | 6 |
| 1800 | 200 us | 0.6 % | 5441 / -465 | 5442 / -585 | 31 | 31 |
| 1800 | 5 ms | 15 % | 5440 / -440 | 5891 / -3390 | 31 | 108 |
| 3600 | 10 ms | 60 % | 5440 / -440 | 3961 / -5341 | 61 | 60 |

At 15 % duty the high-pass overshoot on each falling edge crosses the
threshold again. An 1800 RPM shaft then reads 6270 RPM.

**Measured on:** 2026-09-01 (CHANGELOG "feature/tachometer (R43)", step 4),
raw rate 40000 Hz nominal. The source does not record whether the pulse
train was synthetic or from hardware.

### E14.2. Accuracy

**Result.** +/-0.2 % of reading at 1 pulse per revolution, from 300 RPM to
10200 RPM. The error increases with speed in RPM, so the claim is a
percentage of reading, not a fixed RPM value.

AWG square wave into channel A, DC coupled, +/-5 V range, 2 Vpp at 1 V
offset, adaptive threshold:

| AWG (Hz) | True (RPM) | Measured (RPM) | Error (RPM) | Error (%) | Edges | Spread |
|---|---|---|---|---|---|---|
| 5 | 300 | 299.508 | -0.492 | -0.164 | 5 | 0.0001 |
| 10 | 600 | 600.153 | +0.153 | +0.026 | 10 | 0.0001 |
| 30 | 1800 | 1800.383 | +0.383 | +0.021 | 29 | 0.0003 |
| 60 | 3600 | 3599.818 | -0.182 | -0.005 | 57 | 0.0004 |
| 100 | 6000 | 6001.106 | +1.106 | +0.018 | 96 | 0.0010 |
| 170 | 10200 | 10204.025 | +4.025 | +0.040 | 163 | 0.0024 |

Identification of spectral lines needs 0.3 %.

**Measured on:** PicoScope 4424A, s/n 12462/0067, AWG loopback on
channel A, achieved rate 41666.5 Hz, 2026-09-01.

**Result at 25600 Hz nominal (2026-09-18, CHANGELOG "configurable
pulses/rev"):** same 4424A, AWG loopback, 27 hardware tests pass. This
includes `test_tracks_a_speed_sweep` (the six points above, assertion
+/-0.2 %) and 1, 2 and 6 pulses per revolution against a 60 Hz square
(3600, 1800 and 600 RPM). The per-point errors at 25600 Hz were not
recorded. The table above is the 41666.5 Hz result only.

### E14.3. Interpolation

**Decision.** `_schmitt` interpolates each threshold crossing between the
two samples on each side of it (`_interp`).

**What arrives from the hardware.** A TTL or keyphasor tachometer switches
in nanoseconds, and the scope has no analog anti-alias filter. An ideal
step would put both samples at the rails, and interpolation would give
nearest-sample rounding. The bench shows otherwise. A captured edge has
exactly one intermediate sample (58 samples inside the 10 % to 90 % band,
across 58 transitions of a 30 Hz square). About 8 % Gibbs ringing is on
each side. The interpolated fraction is in the range 0.294 to 0.707, not a
constant, so it carries sub-sample position.

Interpolated against nearest-sample, same captures:

| Pulse rate | Samples per period | Interpolated error | Nearest-sample error | Gain |
|---|---|---|---|---|
| 30 Hz | 1388.9 | 0.021 % | 0.008 % | 0.4x |
| 200 Hz | 208.3 | 0.038 % | 0.160 % | 4.2x |
| 600 Hz | 69.4 | 0.047 % | 0.644 % | 13.8x |
| 1500 Hz | 27.8 | 0.791 % | 0.794 % | 1.0x |
| 3000 Hz | 13.9 | 0.785 % | 0.794 % | 1.0x |

Three regimes:

1. From about 70 to about 1000 samples per period, interpolation is 4x to
   14x better than rounding.
2. Above about 1000 samples per period, interpolation is a little worse
   than rounding. Quantisation there is less than 0.07 %, and dither
   averages it. Both errors are small, and the difference has no effect.
3. Below about 40 samples per period, both give about 0.8 % error. The
   median locks on the most frequent integer period (27.778 samples reads
   as 28.000). The compressed 0.29 to 0.71 transfer cannot recover the
   fraction.

**Limit that follows: `MIN_SAMPLES_PER_PULSE = 70`.** Full accuracy needs
70 samples or more for each pulse period. The limit is a count of samples,
so the shaft speed where it applies changes with the raw rate and with the
pulses per revolution. The front ends calculate it: `gui._update_tach_tab`
from the achieved rate of the sample, `headless._tach_summary_lines` from
the nominal `config.raw_samplerate` (a 320 ppm difference).

| Pulses/rev | At 41666.5 Hz (measured rate, 2026-09-01) | At 25591.8 Hz (now) |
|---|---|---|
| 1 | about 35700 RPM | about 21900 RPM |
| 6 | about 5950 RPM | about 3660 RPM |
| 60 | about 595 RPM | about 366 RPM |
| 1024 | about 35 RPM | about 21 RPM |

The 25591.8 Hz column is computed from the 70-samples-per-pulse limit, not
measured at 25.6 kHz. The texts before this revision gave the rounded
41666.5 Hz values (36000, 6000, 600 and 35 RPM) as current values. They
are not.

**Not isolated.** Which stage limits the edge bandwidth is not known.
`antialias_decimate` is the only low-pass after the ADC and is the
probable cause. But a pure step between two 83 kHz ADC samples would
spread symmetrically and carry no sub-sample information, so a stage
before it also contributes. The design uses the measured effect, not the
cause. At 25600 Hz the oversampling ratio and the anti-alias filter are
different, so the regimes can move. This is not measured.

**Consequence for tests.** An ideal rectangle is a degenerate stimulus, not
a conservative one. Accuracy tests must send their signals through
`antialias_decimate` or use a finite-rise pulse (`make_ramped_pulses`,
`simulation.TACH_RISE_SAMPLES`). Otherwise they measure quantisation.

**Divide by zero in `_interp`.** It cannot occur. An edge needs a decided
low state before it, so `y0 <= hi < y1` and the denominator is positive.
The minimum denominator across 2880 real edges was 1461.7 mV. The guard in
the code is for defence only.

**Vectorised detection.** The vectorised Schmitt trigger took 0.090 ms on a
1.0 s block, against 6.1 ms for a sample-by-sample loop (2026-09-01, raw
rate 40000 Hz nominal; the source does not say hardware or simulation). The
loop also reported a false edge at sample 1 when a block started during a
pulse. The vectorised form needs a real low-to-high crossing.

**Measured on:** PicoScope 4424A, s/n 12462/0067, bench captures, achieved
rate 41666.5 Hz, 2026-09-01 (the samples-per-period column is consistent
with 41666.7 Hz).

**Unreconciled figure.** A comment in `_schmitt` said that interpolation is
"worth 2-9x accuracy at every pulses_per_rev above 1" and changes a 60-line
encoder at 600 RPM "from 0.79% error into 0.09%". The table above gives
4.2x to 13.8x, and 0.644 % to 0.047 % at the 600 Hz pulse rate. The
0.79 % matches regime 3, and 0.09 % matches the encoder table in E14.4.
The source of the comment figures is not recorded. This revision removed
them from the code.

### E14.4. One pulse per revolution and `MIN_REVS`

**Decision.** One pulse per revolution is the default and the recommended
configuration. `pulses_per_rev` is configurable, because an encoder or a
keyphasor that is already on a machine cannot be changed. The minimum data
for a reading is `MIN_REVS = 2.0` whole revolutions, not a fixed edge
count. `min_edges_for(ppr)` converts it to rising edges:
`ceil(MIN_REVS * ppr) + 1`. At 1 pulse per revolution this is 3 edges.

**Why 1 pulse per revolution is accurate.** At 1 pulse per revolution each
interval is exactly one revolution. The two largest error sources cancel
inside each interval: encoder division error and once-per-revolution speed
modulation (load zone, misalignment, reciprocating load). Above 1 pulse per
revolution they cancel only after one whole revolution.

Model: 60-line encoder, +/-0.05 deg division error, 0.5 %
once-per-revolution speed modulation, 40 random start phases:

| Revolutions | Pulses | Mean error | Worst error |
|---|---|---|---|
| 0.05 | 3 | 0.580 % | 1.898 % |
| 0.25 | 15 | 0.344 % | 0.869 % |
| 0.50 | 30 | 0.260 % | 0.704 % |
| 1.00 | 60 | 0.091 % | 0.383 % |
| 2.00 | 120 | 0.091 % | 0.383 % |
| 20.0 | 1200 | 0.091 % | 0.383 % |

The error is flat from one revolution. More pulses do not help. The same
test at 1 pulse per revolution gives 0.0013 % from three edges, 70x better
than 60 pulses per revolution at any window length.

**Why `MIN_REVS` is 2.0, not 1.0.**

- The table shows that one revolution is sufficient above 1 pulse per
  revolution. At 1 pulse per revolution, one revolution is one interval.
  A median and a spread need two intervals. 2.0 satisfies both conditions
  with one gate.
- The drift test (`_MIN_EDGES_FOR_DRIFT`) compares the two halves of the
  block. With 2.0, each half spans one revolution, so once-per-revolution
  modulation cancels in each half. With 1.0, a steady shaft with a load
  zone would read as 'unsteady'.

**Hardware check (2026-09-18, 4424A, AWG loopback, 25600 Hz nominal).** A
5 Hz square in a 1 s block gives about 5 rising edges. At 1 pulse per
revolution it reads 300 RPM. At 6 pulses per revolution the block holds 0.8
of a revolution, and the reading is `None` with quality 'too_few_edges'.

**Measured on:** 2026-09-01 (CHANGELOG "feature/tachometer (R43)",
"Changed"). The source says "measured" but names no hardware and no sample
rate. The injected division error and modulation suggest a synthetic
signal. The owner must confirm.

**Slowest shaft.** A block must contain whole pulse periods at any start
phase, so the floor is `min_edges_for(ppr) * 60 / ppr / T_block` RPM.
`slowest_rpm_for` holds the table for 1 pulse per revolution, and
`tests/test_tach.py` checks it. A finer encoder does not read a much slower
shaft: at a 1 s block the floor is 180 RPM at 1 pulse per revolution and
121 RPM at 60. To read a slower shaft, use a longer block (a smaller
binsize).

**Rejected: find pulses per revolution from the pulse periods.** Reflectors
with unequal spacing already give 'inconsistent' from the interval-spread
test, when the two gaps differ by more than about 90 deg of shaft rotation.
A pair with almost equal spacing reads an exact integer multiple of the
speed. A technician who knows the machine sees that error immediately.

### E14.5. Signal floor

**Decision.** `MIN_PULSE_AMPLITUDE_MV = 1000.0`. A block with a smaller
peak-to-peak span has no tachometer signal. The quality is 'no_signal' and
`rpm` is `None`, never 0.0.

**Evidence.** AWG idle, 40000-sample block (0.96 s at 41666.5 Hz), DC
coupled. This is a disconnected input, or a stopped input with a flat
level:

| Range | Noise (mV RMS) | Block span (mV) | Margin to 1000 mV |
|---|---|---|---|
| +/-1 V | 0.372 | 2.93 | 342x |
| +/-2 V | 0.514 | 3.90 | 256x |
| +/-5 V | 0.870 | 8.35 | 120x |
| +/-10 V | 3.607 | 28.34 | 35x |
| +/-20 V | 5.091 | 42.51 | 23.5x |

1000 mV is 23.5x above the largest measured span. It is half of the 2 V
minimum swing of a logic-level tachometer. Without the gate, an adaptive
threshold on noise gives about 9100 edges per block, which is 547752 RPM.

**Rejected: a span/MAD ratio test.** Noise gives a ratio of about 12.5. A
50 % duty pulse train with 80 mV noise gives 9.3, which is below the noise.
The test rejects the signal that it must accept.

**Measured on:** PicoScope 4424A, s/n 12462/0067, achieved rate
41666.5 Hz, 2026-09-01. Not measured again at 25600 Hz.

### E14.6. Spread and drift limits

**`INTERVAL_SPREAD_MAX = 0.25`.** The spread is
max|interval - median| / median. Above 0.25 the quality is 'inconsistent':
one edge is missing or extra, which is a sensor problem.

1800 RPM, 1.0 s block, 200 repetitions:

| Case | p50 | p99 |
|---|---|---|
| clean | 0.001 | 0.001 |
| 0.5 % cycle jitter | 0.016 | 0.025 |
| 2 % cycle jitter (worst legitimate case) | 0.064 | 0.096 |
| one edge missing | 1.000 | |
| one extra edge | 0.998 | |

0.25 is 2.6x above the worst legitimate jitter and 4x below one wrong edge
count.

**`SPEED_DRIFT_MAX_PCT = 1.0`.** Above a 1.0 % speed change inside one
block, the quality is 'unsteady'. Bearing analysis needs steady state. The
code rejects a smeared spectrum; it does not correct it. This is why there
is no order-resampling path. Bearing tone at 5.43x shaft speed, 1.0 s
block:

| Drift over block | Peak height | Smear at 0.25 Hz bins |
|---|---|---|
| 0.1 % | 100.6 % | 0 bins |
| 0.5 % | 94.4 % | 4 bins |
| 1.0 % (the limit) | 93.8 % | 9 bins |
| 2.0 % | 82.6 % | 18 bins |
| 5.0 % | 69.6 % | 46 bins |

At 1.0 % the peak-height error is less than about 6 % and the smear is less
than about 10 bins. A mains-fed motor at steady load drifts less than
0.1 %. The limit operates on VFD ramps and load steps.

**Measured on:** 2026-09-01; the source does not record the sample rate.
The drift table is simulation: the source says that `SPEED_DRIFT_MAX_PCT`
is the only constant in `tach.py` that is set from simulation, not from
the bench. Confirm it with a load step on a real machine. The source does
not say how the spread table was measured. The "only constant" statement
implies the bench, but the injected jitter and edge errors suggest a
synthetic signal. The owner must confirm.

### E14.7. Median estimator

**Decision.** `estimate_rpm` uses the median of the intervals, not the time
from the first edge to the last edge.

Error in RPM at 1800 RPM, 200 repetitions:

| Case | First-to-last | Median of intervals |
|---|---|---|
| clean | -0.02 +/- 0.00 | -0.15 +/- 0.00 |
| 0.5 % cycle jitter | -0.01 +/- 0.43 | -0.05 +/- 1.78 |
| 2 % cycle jitter | +0.04 +/- 1.74 | -0.62 +/- 7.42 |
| one edge missing | -62.09 | -0.15 |
| one extra edge | +62.05 | -0.15 |
| three edges missing | -179.39 +/- 19.42 | -0.15 |

First-to-last is better under torsional jitter. It fails under one wrong
edge count: -62.09 RPM is a 3.4 % error, which looks like a speed change.
Jitter shows in `interval_spread`; a wrong edge count does not. Thus the
median is the correct choice.

**Measured on:** 2026-09-01 (CHANGELOG "feature/tachometer (R43)"). The
source does not record the sample rate, or whether the signal was
synthetic or from the bench. The injected jitter and edge errors suggest a
synthetic signal. The owner must confirm.
