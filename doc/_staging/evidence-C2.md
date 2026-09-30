<!-- Staging text from package W1-C2 (collector.py, _dsp.py).
     W2-A moves each section under its E heading in CONTRIBUTING.md and
     deletes doc/_staging/. The E8 subsection headings below are new; the
     code pointers name them exactly. -->

### E7. Resample ratio bound

**Decision.** `collector.decimate_to_rate` resamples the raw-rate block to the
display rate with `scipy.signal.resample_poly` and a Kaiser window at the
hardware stopband target (`picoscope._AA_STOPBAND_DB`). It bounds the
denominator of the up/down **ratio** with `_RESAMPLE_DENOM_LADDER` =
(4, 8, 16, 32, 64, 128, 256). The first cap that lands within
`_RESAMPLE_RATE_TOL` = 1e-3 of the requested rate wins. If no cap does, the
closest ratio is used. The function returns the achieved rate,
`raw_rate * up / down`, and every consumer builds its frequency axis from it,
not from `config.samplerate`.

**Why the bound is necessary.** `resample_poly` designs a FIR of
`2*10*max(up, down)+1` taps on every call. The denominator is therefore a
direct cost multiplier. At the cap of 256 the FIR has 5121 taps.

**Why 1e-3.** The grid-snapped streaming clock of a 4824A is -320 ppm
(3.2e-4) from nominal: 25591.81 Hz against 25600 Hz (see E4). 1e-3 is larger
than this offset, so every shipped F_max preset gets its exact integer
factor. The tolerance bounds only the resample approximation. It does not add
to the clock error, because the returned rate is exact for the ratio used.

**Measured on:** the development PC, `decimate_to_rate` timed on one
12800-sample block. The "hardware" row is the rate that a 4824A reported
before the clock-grid snap (25641 Hz, from a whole-microsecond interval
request). That rate does not occur now. The raw rate of the "simulated" row
is what `SimulatedSensor` reports.

| raw rate (Hz) | up / down | taps | ms per call | output length (samples) |
|---|---|---|---|---|
| 25600.00 (simulated) | 1 / 5 | 101 | 0.64 | 2560 |
| 25641.00 (hardware, ratio not bounded) | 5120 / 25641 | 512821 | 73.62 | 2556 |

- At 8 channels the unbounded case is 589 ms of main-thread work for each
  500 ms frame.
- The output of 2556 samples is less than `nperseg`. Welch then used a
  shorter segment, so the bin width was not the value that the Spectrum tab
  showed.
- With the bound: worst case 1.05 ms for an off-preset F_max; at the
  hardware rate 73.62 ms becomes 0.42 ms, and the output length is 2560
  samples again (CHANGELOG, same entry).

**Rejected alternative.** `Fraction.limit_denominator` applied to each rate
before the division. Both rates are integers, so each reduces to
denominator 1, and the ratio is not bounded at all. This was the shipped
defect.

**Lesson for tests.** The defect is not visible with `SimulatedSensor`,
because 25600 Hz reduces to a small integer factor against every display
rate. A performance claim for this path needs the hardware-realistic rate.

### E8. High-pass filter

`highpass_fc` is the declared lower band edge. The filter is a causal
Butterworth high-pass of order `AcquisitionSettings._BUTTER_ORDER` (4),
applied once at the raw rate by `DataCollector.filter_block`.

#### E8.1. Stateful filter

**Decision.** Two regimes.

- `stateful=True`: consecutive blocks of one live stream. `receive_data`
  filters each block once, in stream order, and carries the final filter
  state (`zi`) into the next block. The state is reset at stream start and
  when the filter configuration changes.
- `stateful=False`: a stored frame on replay, or a frame that is filtered
  again after a configuration change. Replay goes through frames out of
  order, so no state is carried between frames. Each block is seeded from its
  own mean (E8.2). Replay was verified bit-identical forward and reverse to 12
  significant figures (CHANGELOG, `sosfilt` state entry).

**Measured on:** a 200 Hz tone, high-pass at 10 Hz, block 1 of 4 (the
CHANGELOG entry gives blocks 1 to 3). The source (hardware or simulation) is
not recorded. Error against the true value:

| quantity | no `zi` (restart from rest every block) | steady-state `zi`, carried |
|---|---|---|
| waveform peak | +9.41 % | -0.00 % |
| RMS, with 1000 mV DC offset | +14321.74 % | -0.00 % |
| displacement overall | +19.15 % | +0.02 % |
| displacement overall, with DC offset | +1472786.72 % | +0.02 % |

**Rejected alternative: `sosfiltfilt` (zero-phase).** The forward and
backward passes double the effective filter order. With a low knee against
a short block (10 Hz over a 1 s block: 10 knee cycles of margin) the
response rings. On hardware data it overshot the raw signal by 35 % to 45 %
at both block edges, with every `padtype`. It was tried and reverted
(CHANGELOG, hotfix/hpf-integration-fix).

#### E8.2. Seed from the block mean

**Decision.** A block with no usable history (block 0 of a stream, or any
replayed block) starts from `sosfilt_zi(sos) * mean(x)`, not from
`sosfilt_zi(sos) * x[0]`.

**Why.** scipy's documented idiom uses `x[0]`. That is correct when the first
sample is the baseline, as for a step response. A vibration block swings
about its DC level, so `x[0]` is an arbitrary point on the swing. Seeding with
it tells the filter that the signal sat at that value before the block, and
the filter then decays a step that did not occur. Under 1/omega**2
integration that step dominates the displacement.

**Measured on:** four consecutive captures, PicoScope 4424A, AWG loopback on
channel A, 447.3 Hz tone, 1 Vpp, raw rate 8333.25 Hz (the rate of that
period, before the 25600 Hz raw rate), 10 Hz high-pass. The block mean was
-0.06 to -0.21 mV in every block (the true DC). `x[0]` was 36 to 305 mV.
Error against a fully settled continuous-filter reference, worst block for
each row:

| order | `zi * x[0]` | `zi * mean(x)` | warm-up pass |
|---|---|---|---|
| acceleration | +0.39 % | -0.00 % | +0.00 % |
| velocity | +23.01 % | -0.06 % | -0.07 % |
| displacement | +4297.20 % | -2.22 % | +61.10 % |
| waveform | 57.63 % | 0.51 % | 6.37 % |

**Rejected alternative: warm-up pass.** Filter the block once and use its
final state as the initial state. It is worse than the mean (+61.10 % in
displacement), because it assumes the block is periodic, and it is not.

**Residual error.** The displacement error on an isolated block cannot be
removed. At 447 Hz the doubly integrated result is dominated by near-DC noise
whose continuation is not in the block. This affects block 0 of a stream and
replayed frames only. With carried state, blocks 1 and later match the
settled reference to +/-0.000 %.

#### E8.3. Knee below the band edge

**Decision.** `DataCollector.highpass_knee_hz` designs the Butterworth at a
knee below `highpass_fc`, from `_dsp.butter_knee_for_edge`:

    |H(f)|^2 = (f/fc)^(2N) / (1 + (f/fc)^(2N))
    set |H(f_edge)| = A:
    r  = A^2 / (1 - A^2)
    fc = f_edge * r ** (-1 / (2N))

At order N = 4 and A = `PASSBAND_TOLERANCE` = 0.9, fc = 0.8342 x f_edge. A
10 Hz edge gives an 8.34 Hz knee and -0.915 dB (x0.900) at 10 Hz.

**Why.** ISO 2954 requires a broadband vibration-severity instrument to be
within +/-10 % of the true amplitude across its declared band, edges
included. A Butterworth designed at the edge is -3 dB (x0.707) there: 29 % low
at the frequency that the standard names as the bottom of the band.

**Why a lower knee is safe.** The overall is band-limited in the frequency
domain (the band mask in `process_sample`). The mask removes sub-band energy
exactly, so the 1/omega**2 increase that the higher knee guarded against
cannot reach the integrated result.

**Measured on:** PicoScope 4424A, AWG loopback (CHANGELOG, ISO 2954 entry).

| frequency (Hz) | response (dB) |
|---|---|
| 100 | +0.00 |
| 20 | -0.04 |
| 10 | -1.05 (-3.0 with the knee on the edge) |
| 5 | -18.40 |

### E9. Tapers for integration

**Problem.** `process_sample` converts between acceleration, velocity and
displacement: it multiplies the block's rFFT by `(j*omega)**n` and transforms
back. The DFT treats the block as periodic. Unless the signal is exactly
periodic in N samples, the block has a step at the wrap point. The spectrum
of that step is broadband with most energy at low frequency, and
`(j*omega)**n` with n < 0 amplifies it by 1/omega**|n|, where it is largest.

**Measured on:** synthetic 1.0 g 0-pk sine, fs = 32768 Hz, N = 16384,
displacement overall, no taper (computed offline, not hardware):

| tone (Hz) | on a bin? | true RMS | un-tapered | error |
|---|---|---|---|---|
| 500.0 | yes | 7.1645e-08 | 7.1645e-08 | +0.00 % |
| 501.0 | no | 7.1359e-08 | 3.2638e-06 | +4473.76 % |
| 61.0 | no | 4.8136e-06 | 2.7466e-05 | +470.59 % |
| 120.7 | no | 1.2294e-06 | 1.0793e-05 | +777.84 % |

The on-bin row has no error. A test suite that uses only bin-centred tones
cannot find this defect. This is why amplitude tests are off-bin (see
Testing).

**Decision: two treatments.**

- **Scalar overalls** (trend, result card, anomaly detector) need an unbiased
  RMS over the whole record. All five integration orders, order 0 included,
  use a Hann taper, the band mask, the inverse transform, and division by the
  window power gain `sqrt(mean(w**2))` (`_dsp.hann_taper`). Order 0 needs the
  taper too: the band mask is a transform-domain multiply, so it has the same
  wrap sensitivity.
- **Displayed waveform.** A Hann taper would be visible as an amplitude
  envelope on the trace. The waveform uses overlap-save instead: a Tukey
  window (flat in the middle, cosine at the edges) removes the wrap step, and
  only the flat middle is returned (`_dsp.tukey_taper`,
  `_dsp.tukey_keep_slice`). There the window is exactly 1.0, so the samples
  are not changed. `time_vec` is cut to match and keeps the true
  capture-relative times. The trace is band-limited to the same band as the
  overall.

After the change (CHANGELOG, same entry): displacement overall at 501.0 Hz
+4473.76 % -> +0.00 %; at 61.0 Hz +470.59 % -> +0.18 %; velocity overall at
61.0 Hz +12.25 % -> +0.05 %.

**Tukey `alpha`** (`_dsp.WAVEFORM_TUKEY_ALPHA` = 0.5, the fraction of the
block in the cosine tapers, half at each end). Measured waveform peak error
against `alpha`, synthetic tones (same method as the table above; fs and N
are not recorded beside this table):

| alpha | block kept | 61 Hz velocity | 61 Hz displacement | 501 Hz displacement |
|---|---|---|---|---|
| 0.00 | 100 % | +90.22 % | +1149.12 % | +10176.68 % |
| 0.05 | 95 % | +32.75 % | +335.84 % | +18.56 % |
| 0.10 | 90 % | +0.18 % | +7.00 % | +0.85 % |
| 0.30 | 70 % | +0.14 % | +4.22 % | +0.58 % |
| 0.50 | 50 % | +0.10 % | +1.47 % | +0.24 % |

0.5 is the first value that keeps every case below 2 %. The cost: an
integrated or band-limited waveform shows the middle 50 % of the block. A
full-band passthrough (order 0, band covers 0 Hz to fs/2) shows the whole
block.

**Bin 1 on integration.** `_dsp.integrate_rfft` zeroes bin 0 always, and bin
1 for n < 0. One time-domain high-pass pass cannot stop residual near-DC
energy from growing as 1/f**n. On hardware, bin 1 otherwise dominated the
spectrum. `process_sample` zeroes the same bin in the integrated PSD.

### E10. Band RMS

**Decision.** The overall is not computed with `_dsp.band_rms` (Parseval on an
un-tapered rFFT). It uses the Hann-tapered path of E9. `band_rms` has no
caller in `src/`, `tests/` or `scripts/` at `8bd106c`.

**What `band_rms` computes.** The exact RMS of the masked bins of an
un-tapered one-sided rFFT: every bin has weight 2, except DC and (for even n)
the Nyquist bin, which have weight 1. With a full mask it equals
`sqrt(mean(x**2))`.

**Rejected alternative for the overall: un-tapered Parseval.** It is exact
for in-band content, but its band edge has a rectangular window's -13 dB
first sidelobes.

**Measured on:** offline computation over the preset grid (CHANGELOG, band-limited overall
entry).

| case | un-tapered Parseval | Hann path |
|---|---|---|
| 3x tone at 30 Hz, 100 Hz lower band edge | leaks in at -22 dB, overall +2.70 % | rejected by -84 dB |
| other cases measured | not recorded | rejected by -100 to -144 dB |
| worst in-band error over the preset grid | 0 (exact) | 4.9e-4 |

Band rejection matters more for an instrument than the fifth decimal place.

**Hardware check of the band mask** (PicoScope 4424A, AWG loopback, declared
band 10 to 1000 Hz at F_max 2000 Hz): 800 Hz +0.0 dB, 950 Hz -0.0 dB,
1000 Hz -3.1 dB, 1100 Hz -58.2 dB, 1300 Hz -58.6 dB, 1600 Hz -58.9 dB.

**Why the band mask exists.** Without it the overall covered
`highpass_fc` to fs/2, not to F_max. Content that the user excluded with
F_max reached the trend: 2 g RMS at 1500 Hz with a 1000 Hz F_max made the
velocity overall +25 % high, enough to cross an ISO 20816 zone boundary.
