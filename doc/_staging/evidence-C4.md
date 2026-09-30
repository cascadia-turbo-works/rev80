# Evidence from package W1-C4 (peaks.py, envelope.py, simulation.py, util.py)

Staging text for `CONTRIBUTING.md`, section 5 "Design evidence". Package
W2-A moves it. The tables are copied from the docstrings and comments at
`8bd106c`. The numbers are not changed. Where the source did not record a
condition, this file says so.

---

## E12. Peak selection

Source: `src/rev80/peaks.py` (module docstring, the constants, and
`local_noise_floor`, `select_peaks`, `_running_median` at `8bd106c`).

### E12.1. Method

Decision: report a bin when it stands `threshold_db` above its own local
noise floor. Do not report a fixed top-N by absolute amplitude. The count of
peaks is an output. Rank the reported lines by amplitude. The reported
amplitude is the amplitude of the maximum bin. Energy is not summed across
the bins of a peak (owner decision).

Measured on: the recorded `old castle` corpus, 60 channel-spectra (20 `.h5`
files x 3 channels). The capture hardware and the capture date are not
recorded in the source. The example file is `blower 4 - bearing DE.h5`,
channel 2.

Why a ranking by absolute amplitude fails:

- The local noise floor is not flat. Across the 60 channel-spectra it varies
  by up to 7x inside one spectrum.
- On `blower 4 - bearing DE.h5` ch2 the median local floor is 9.0 mV over
  the full spectrum, but 39.4 mV over 1890-2000 Hz.
- A top-N by amplitude ranked by the loudness of the neighbourhood: 6 of
  the top 12 lines of that spectrum came from the 110 Hz stretch at the top
  of the band. Some were ripple, not lines: 1982 Hz sat 2.2x above its local
  floor, 1967 Hz 1.6x.
- The sidebands at 1034 Hz and 1088 Hz (+/-25 Hz and +/-29 Hz around the
  1059 Hz carrier, the bearing-fault signature) ranked 10th and 4th. At a
  display count of 6 the sideband family was broken up and removed from the
  table.

The method, in one `scipy.signal.find_peaks` call:

1. Estimate the local noise floor for each bin (`local_noise_floor`).
2. Pass array-valued `height` and `prominence`, derived from that floor.
3. Report every bin that passes. The user setting is a significance
   threshold in dB.

Rank by amplitude, not by significance: the table answers "how big is it".
A 0.2 mV line on a quiet floor is not the top line of the spectrum.

Floor estimator (`local_noise_floor`): a running median of bin power, not of
amplitude, because the median-to-mean correction is a statement about power.
A median, not a mean, keeps the discrete lines out of the estimate: with the
corpus median gap of 22 bins between significant peaks, a 65-bin window
holds about three lines, in less than a fifth of its samples.

Median-to-mean correction (`median_to_mean_ratio`): with one Welch segment
the bin power is exponential and the ratio is `ln 2`. With N segments it is
`Gamma(N, 1/N)`:

| Segments | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| median/mean | 0.693 | 0.839 | 0.913 | 0.956 | 0.978 |

The app runs one segment (`nperseg == blocksize`), so the ratio is `ln 2`
in every preset. The general form stays because that invariant belongs to
`AcquisitionSettings`, not to the statistics. A wrong ratio biases the whole
floor by up to 3.1 dB, in the direction that admits noise.

The four admission terms (`select_peaks`):

- The bin rises `threshold_db` above its local floor.
- The bin is not more than `ABSOLUTE_FLOOR_DB` below the largest bin in the
  band.
- The prominence is at least `PROMINENCE_RATIO` x the height threshold,
  inside +/-`wlen`/2 bins.
- The bin is the tallest such bin within `peak_distance_bins`.

The prominence term has the most value of the four. `height` alone admits
shoulders and ripple on a broad hump, because each sample of the hump clears
the same threshold.

Count of peaks at the default threshold (9.5 dB), over the 60 corpus
channel-spectra: median 40, p10 23, p90 50, minimum 16, maximum 63.

`ABSOLUTE_FLOOR_DB = -40.0`: floor-relative significance alone promotes
high-pass roll-off residue. On `blower 4 - bearing DE.h5` ch2 the 1 Hz bin
(0.21 mV) and the 14 Hz bin (2.67 mV) sit on a quiet floor and reach SNR
ranks 9 and 6. The absolute term costs almost nothing: the median gated peak
count is 40 at -40 dB against 41 at -50 dB.

`PROMINENCE_RATIO = 2/3`: at the default 9.5 dB threshold, height is 2.99x
the floor and prominence is 1.99x the floor. This is the (3x, 2x) pair that
the corpus study selected. The ratio keeps the pair when the user moves the
threshold.

`PROMINENCE_WLEN_BINS = 41`: always pass `wlen` with `prominence`.
Unbounded, `find_peaks` walks out to the base of the nearest taller
neighbour, which on a 2001-bin spectrum can be most of the band away.
Measured on the ch2 top 12, minimum prominence/amplitude:

| `wlen` (bins) | 11 | 21 | 41 | 81 | 201 | unbounded |
|---|---|---|---|---|---|---|
| min prominence/amplitude | 0.366 | 0.561 | 0.561 | 0.561 | 0.561 | 0.561 |

At 11 bins the real prominence is truncated. From about 4x `distance`
upward the value is safe; 41 limits the cost. `select_peaks` uses
`max(PROMINENCE_WLEN_BINS, 4 * distance + 1)`.

Rejected alternatives:

- `width=`: no discrimination. On the ch2 spectrum, noise-ripple maxima
  (amplitude < 1.5x floor) have a median width of 1.87 bins. Real lines
  (> 5x floor) have 2.10 bins, p10 1.84. The distributions overlap almost
  fully.
- `threshold=`: it compares a sample with its two immediate neighbours
  only. This is too noisy at these SNRs (corpus median peak/floor: 13.2 dB).
- Energy summed across the bins of a peak: out of scope by owner decision.

### E12.2. Floor width

Decision: `FLOOR_MEDIAN_WIDTH_BINS = 65`.

Measured on: the `old castle` corpus. Each file holds 16 frames of the same
machine in the same state. The reference floor is the average of the 16
power spectra (16-fold lower bin-power variance), median-filtered with a
31-bin window. The single-frame estimator was scored against that reference
over 20 files x 3 channels x 4 frames.

| Width (bins) | Median abs. error (dB) | p95 abs. error (dB) |
|---|---|---|
| 17 | 1.522 | 4.694 |
| 31 | 1.097 | 3.185 |
| 45 | 1.039 | 3.074 |
| 65 | 1.085 | 3.354 |
| 91 | 1.181 | 3.856 |
| 129 | 1.326 | 4.553 |
| 257 | 1.705 | 6.572 |

The optimum is a flat basin from 31 to 65 bins. 45 bins is the minimum; 65
bins costs 0.05 dB more, which is less than the 1.0 dB noise of the estimate.
Below 31 bins the window does not average down the exponential bin-power
scatter. Above 91 bins it smears real floor structure, which changes over
tens of bins on this machinery.

Rejected: a synthetic spectrum with a smooth floor prefers 129 bins. The
synthetic floor is too smooth to be a guide; the value comes from the
recorded corpus.

### E12.3. Edge handling

Decision: `_running_median` uses a truncated window at the two band edges.
At bin *i* the result is the median of the bins within +/-width//2 of *i*
that exist.

Why `scipy.signal.medfilt` (zero padding) is not used: near an edge, the
padded zeros displace real samples from the lower half of the window, so the
statistic moves from the local median toward the local minimum. Measured on
`blower 4 - bearing DE.h5` ch2, where the true floor at the top of the band
is 39.4 mV, the zero-padded estimate reads 32.8 mV at 1995 Hz, 14.9 mV at
1999 Hz and 5.68 mV at 2000 Hz. 1999 Hz then shows an SNR of 6.44 against a
true SNR of 2.93: ordinary ripple is admitted as a strong line. The bias is
one-sided (always down) and always at the band edges.

Measured on: synthetic spectra with a known floor, the +/-32 edge bins at
width 65, 40 trials.

| Edge handling | Median abs. error (dB) | p95 abs. error (dB) | Mean bias (dB) |
|---|---|---|---|
| zero-pad (`medfilt`) | 2.368 | 11.448 | -3.568 |
| replicate (`'nearest'`) | 1.480 | 5.246 | -0.009 |
| reflect | 0.620 | 1.844 | +0.098 |
| truncated window | 0.591 | 1.829 | +0.050 |

Rejected alternatives:

- Replication removes the bias but not the error. It copies one random bin
  32 times, and 32 copies of one exponential draw control a 65-sample
  median.
- Reflection uses 32 independent samples, like truncation, and gives almost
  the same error. It can mirror a strong line back across the edge onto
  itself. Truncation invents no data and measured slightly better.

Cost of truncation: the estimate is noisier in the last half-window, because
there is less data there.

`tests/test_peak_selection.py` pins this: the vectorised edge code is
bit-identical to a per-bin `np.median` loop, and a line at the band edge is
not mirrored.

### E12.4. Window nulls

Decision: `WINDOW_FIRST_NULL_BINS`, and `distance = 2 * null + 1`, so the
two flanks of one main lobe are never reported as two peaks.

Measured on: computation. Each window was transformed 64x oversampled, and
the first local minimum was found.

| Window | First null (bins) |
|---|---|
| boxcar | +/-1 |
| hann, hamming, bartlett | +/-2 |
| blackmanharris | +/-4 |
| flattop | +/-5 |

Rejected: a fixed `distance=5`. It is correct for hann only. For boxcar it
merges distinct lines 2 to 4 bins apart.

---

## E19. GUI render cost (part from peaks.py)

Source: the comment in `peaks._running_median` at `8bd106c`.

Decision: compute the edge bins of `_running_median` with a NaN-padded
sliding window and one `np.nanmedian`, not a Python loop of `np.median`
calls (64 calls at width 65). The statistic does not change.

Measured on: a 1001-bin spectrum, width 65. The machine and the date are not
recorded in the source.

| Stage | Time (ms) |
|---|---|
| `median_filter` (interior) | 0.047 |
| edge loop, Python | 1.161 |
| edge loop, vectorised | 0.408 |
| `_running_median` total, before -> after | 1.274 -> 0.563 |

The Python edge loop was 91 % of the cost of the function.

The source comment said "~0.8 ms per channel per frame, so 6.6 ms at 8
channels". These figures do not follow from the table: the table gives a
saving of 0.711 ms per channel per frame, which is 5.7 ms at 8 channels
(computed, not measured). `tests/test_peak_selection.py` says "~10 ms" at 8
channels, which is the total before the change (8 x 1.274 ms = 10.2 ms).
W2-A: use the table values, not the rounded prose.

Equality test: `tests/test_peak_selection.py`,
`test_running_median_bit_identical_to_the_loop`.

---

## E13. Envelope band search

Source: `src/rev80/envelope.py` (`suggest_band`, the module constants and
the module docstring at `8bd106c`).

Decision: `suggest_band` proposes a demodulation band centred on the
strongest high-frequency energy. The user does not have to know the
frequency of the housing resonance to get a first result.

- The search covers 0.25 x top to top only. Below that is machine content
  (1x and harmonics), which demodulation must remove, so a band centred
  there has no use.
- The power spectrum (Hann window) is smoothed over the band width
  (`SUGGEST_BAND_FRAC = 0.25` of top) before the argmax. The band energy,
  not one tall line, selects the centre: one harmonic is not a resonance.
- `top` is `fmax`, or Nyquist when `fmax` is not given, and never above
  0.99 x Nyquist. The contract says: pass the upper edge of the usable band,
  so the suggestion stays out of the anti-alias transition band.
- `BANDPASS_ORDER = 4`, Butterworth, zero-phase (`sosfiltfilt`), so the
  effective order is 8. The source gives this reason: steep enough to reject
  a 1x up to 40 dB above the resonance, and numerically stable as SOS at the
  narrow relative bandwidths of a resonance band. The 40 dB figure is not a
  recorded measurement.
- `DEFAULT_ENVELOPE_FMAX = 500.0` Hz: defect rates and their first
  harmonics are below this value.
- `MIN_USEFUL_NYQUIST_HZ = 5000.0`: below this Nyquist frequency a housing
  resonance (typically 2-20 kHz, a literature value, not measured here) is
  probably not in the record.

Measured on: nothing. The source has no measurement table for the band
search. `tests/test_envelope.py` covers the behaviour.

Open point for W2-A and the owner: `gui.py:563` calls
`suggest_band(signal, samplerate, fmax=samplerate / 2.0)`, which is the raw
Nyquist (about 12796 Hz at 25591.8 Hz). The suggestion can therefore reach
up to 0.99 x Nyquist, inside the anti-alias transition band above 10 kHz.
This does not agree with the `suggest_band` contract.

Operator physics (impulses ring a housing resonance; the envelope carries
the defect rate with +/-1x sidebands; CSI PeakVue, SKF gE and B&K envelope
analysis are the same method) is README material. `README.md` "Envelope
analysis" holds it.

---

## E14. Tachometer (part from util.py)

For E14.1. Source: the channel-roles comment in `src/rev80/util.py` at
`8bd106c`. The same numbers are in `CLAUDE.md` and `headless.py`.

A pulse train through the vibration path does not raise an error. It gives
a plausible wrong answer. Measured on a 5 % duty square wave through
`DataCollector.process_sample`: overall 1515 mV, crest factor 5.00,
kurtosis 15.94, 63 "peaks". This reads as a failing bearing.

---

## E15. Simulation model constants

Source: `src/rev80/simulation.py` (the bearing-model comment block,
`DEFAULT_RESONANCE_Q`, and the shaft-phase comment in
`GenerateBearingVibration` at `8bd106c`).

### Resonance Q

Decision: `DEFAULT_RESONANCE_Q = 8.0`, not the textbook 40.

Impulsiveness depends on the ratio of the ring-down time constant to the
impulse interval: tau = Q / (pi x f_res). When tau is near one impulse
period, the ring-downs merge into a continuous tone and the signal is not
impulsive.

Measured on: `GenerateBearingVibration` (simulation), fs 32768 Hz, 0.5 s
block, defect rate 325.8 Hz (period 3.07 ms), 4 kHz resonance, mean of 4
seeds. The raw rate is now 25600 Hz; this table was not measured again at
that rate.

| Q | tau (ms) | tau/period | Kurtosis, healthy | Kurtosis, severity=1 |
|---|---|---|---|---|
| 3 | 0.24 | 0.08 | 3.09 | 10.41 |
| 5 | 0.40 | 0.13 | 3.09 | 7.21 |
| 8 | 0.64 | 0.21 | 3.09 | 5.28 |
| 10 | 0.80 | 0.26 | 3.09 | 4.63 |
| 15 | 1.19 | 0.39 | 3.09 | 3.81 |
| 25 | 1.99 | 0.65 | 3.09 | 3.27 |
| 40 | 3.18 | 1.04 | 3.09 | 3.08 |

Rejected: Q = 40, the textbook value for a lightly damped housing resonance
alone. At this defect rate its ring-down is longer than the gap between
impulses, and kurtosis cannot detect the fault (3.08 against 3.09). Real
bearing signals damp faster through the load path. Q = 8 gives
tau/period = 0.21, inside the 10-30 % range that bearing-simulation practice
uses (the source gives no reference for this range). It separates 5.28 from
3.09, enough for a threshold test.

### Independent phase for each shaft harmonic

Decision: each of the five shaft harmonics gets its own random phase.

Measured on: `GenerateBearingVibration` (simulation), `severity=0`. Rate and
block length are not recorded in the source.

| Harmonic phases | Healthy kurtosis across seeds |
|---|---|
| one shared phase | 2.03 to 4.00 (seed count not recorded) |
| independent phases | 2.68 to 3.16 (40 seeds) |

Rejected: one shared phase. It is not physical (the harmonics of a real
machine come from different mechanisms), and the healthy range overlaps the
faulted range, so a threshold test becomes unstable.

The 2.68-3.16 range above does not agree with the model as it is now.
Measured by W1-C4 on 2026-09-29 with `GenerateBearingVibration` through
`_RawRateView(AcquisitionSettings())` (simulation, 25600 Hz, 12800 samples,
seeds 0 to 39, Pearson kurtosis):

| Severity | Kurtosis min | Kurtosis max | Kurtosis mean |
|---|---|---|---|
| 0.0 (healthy) | 1.54 | 3.04 | 2.18 |
| 1.0 | 3.83 | 6.16 | 4.84 |

The healthy control is sub-Gaussian (kurtosis below 3), because the shaft
harmonics dominate the signal. `doc/CHANGELOG.md` gives the same 1.54-3.04
range. The two ranges do not overlap at this rate. W2-A: use this table,
not the 2.68-3.16 figure.

### Other defaults (no measurement recorded)

- `DEFAULT_RUNNING_RATE_HZ = 60.0` (3600 RPM), `DEFAULT_BEARING_MULTIPLE =
  5.43` (outer race; non-integer, as real bearing geometry is),
  `DEFAULT_RESONANCE_HZ = 4000.0`: "a mid-size induction motor".
- `DEFAULT_SLIP = 0.015`: rolling elements slip by 1 % to 2 %. Slip is a
  cumulative random walk, not independent jitter for each impulse, because a
  random walk gives smearing that increases with harmonic order.
- `severity=1.0` scales the defect to about the RMS of the shaft signal.

---

## E16. Anomaly thresholds (part from util.py)

For E16.2. Source: the `GUI_ANOMALY_HOOK_TYPES` comment in
`src/rev80/util.py` at `8bd106c`. Tracked as R39 in `doc/PROGRESS.md`.

Decision: the GUI offers the RMS hook only (`GUI_ANOMALY_HOOK_TYPES =
('rms',)`). Headless still accepts `spectral` and `both`
(`headless.py:162`).

Reason (statistics, not a recorded measurement):

- `SpectralThresholdHook` fires on
  `np.any(|spec - baseline| / baseline > threshold)` over every bin in the
  band.
- Welch runs one segment (`nperseg == blocksize`), so each noise-floor bin
  is chi-squared with 2 degrees of freedom, with a standard deviation equal
  to its own mean.
- The probability that one of about 2000 bins exceeds 1.5x its mean is
  about 1.0 on healthy data. `consecutive_n` then only delays the trigger.
- Bins 0 and 1 are set to zero for integration (`collector.py:1124-1128`),
  so on a velocity or displacement channel they deviate by about 1e12 and
  fire on every frame.

A return to the GUI is a one-line change in `util.py`.

---

## Testing (part from simulation.py)

For CONTRIBUTING section 6, "Testing". Source: the bearing-model comment
block in `src/rev80/simulation.py` at `8bd106c`.

Pure-tone generators are not an oracle. `GenerateTone`,
`GenerateBearingVibration_SpectralMethod` and
`GenerateBearingVibration_TemporalMethod` are ten cosines plus Gaussian
white noise: kurtosis about 3, no impulses, no resonance carrier, no
modulation sidebands, no slip. Crest factor, kurtosis and envelope analysis
depend on exactly these properties. A broken envelope analyser and a correct
one both return "nothing here" on pure cosines. Use
`GenerateBearingVibration` (with `severity=0` as the healthy negative
control) for diagnostic tests. The pure-tone generators stay for regression
tests of the older paths.

The same rule applies to the tachometer: a tach pulse train that is not
locked to the shaft of the vibration signal validates nothing. Use
`GenerateMachineWithTach` or `machine_with_tach_sources`.

A zero-rise rectangular tach pulse is a degenerate stimulus: no sample lands
in the hysteresis band, and sub-sample interpolation has nothing to
interpolate. `TACH_RISE_SAMPLES = 1.5` models the one intermediate sample
that a real TTL edge has on a 4424A (evidence in E14.3).
