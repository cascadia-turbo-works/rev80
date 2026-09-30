<!-- Staging text from package W1-C1 (picoscope.py, sample.py, _pico_loader.py).
     W2-A moves each section under its E heading in CONTRIBUTING.md and
     deletes doc/_staging/. The headings are the titles of plan section 6.2.
     The last section is a part of E20; merge it with the part from W1-C5. -->

### E1. Streaming ceiling and the raw rate

**Decision.** The ADC streams at most `STREAMING_CEILING_HZ` = 100000 Hz per
channel (`picoscope.py`). The raw rate is fixed at `RAW_SAMPLERATE_HZ` =
25600 Hz (`sample.py`), 2.56 x the top F_max preset (10 kHz). It does not
depend on `maxfreq`. `_choose_osr` gives an oversampling ratio of 3, so the
ADC runs at 76800 Hz per channel (requested).

**Why a ceiling.** Continuous `ps4000aRunStreaming` /
`ps4000aGetStreamingLatestValues` drops most samples above about 100 kHz to
250 kHz per channel. The limit depends on the channel count. The driver
reports `status='OKAY'` and sets no overflow bit, so nothing shows the loss.

- Requested rates of 300 kHz and more: 15 % to 23 % of the samples arrived
  at 4 channels.
- 1 channel: about 34 % arrived when the driver clamped internally near 1 MHz.
- A flat 100 kHz ceiling leaves margin at 1, 2 and 4 channels. At 4 channels
  the range 100 kHz to 200 kHz is borderline.

**Measured on:** PicoScope 4424A (4 channels), during the anti-alias hardware
tests (feature/anti-alias, CHANGELOG 2026-08-26). The delivery ratios above
were recorded in the `picoscope.py` comment only. The repository does not
record the serial number or the exact date.

**Why a fixed raw rate.** Bearing housing resonances, which envelope analysis
uses, are at 2 kHz to 20 kHz. A display F_max of 1 kHz to 2 kHz does not
contain them. A fixed raw rate lets envelope analysis work at every F_max.
At 2.56 x the top preset, every preset decimates by an integer factor:

| F_max preset (Hz) | 200 | 500 | 1000 | 2000 | 5000 | 10000 |
|---|---|---|---|---|---|---|
| display rate (Hz) | 512 | 1280 | 2560 | 5120 | 12800 | 25600 |
| factor from 25600 Hz | 50 | 20 | 10 | 5 | 2 | 1 |

**Validation of the raw rate.** `scripts/validate-streaming-capacity`,
45 s sustained at 3 and 4 channels:

| raw rate | osr | ADC rate per channel | overflow | degraded transitions |
|---|---|---|---|---|
| 25600 Hz | 3 | 76.9 kHz | 0 | 0, at 3 and at 4 channels |
| 40000 Hz | 2 | about 83.3 kHz | 0 | 0, every run |
| 50000 Hz | 2 | 100 kHz (at the ceiling) | 0 | 0 to 2, different in each run |
| 100000 Hz | 1 | 100 kHz (at the ceiling) | 0 | 0, but osr = 1: no anti-alias margin |

- 25600 Hz row: measured 2026-09-09 on a 4424A, s/n 12462/0067
  (CHANGELOG hotfix/RAW_SAMPLERATE). `effective_osr` = 3. The ADC ran at
  76923 Hz per channel against 76800 Hz requested (+0.16 %). At that time
  the interval was requested in whole microseconds, so the block rate was
  25641 Hz. Since the clock-grid snap (E4) it is 25591.81 Hz.
- 40000 Hz, 50000 Hz and 100000 Hz rows: same 4424A. The repository does not
  record the date. 40000 Hz was the highest rate that was clean in every run
  with real anti-alias margin. 50000 Hz sits at the ceiling with no margin
  and was clean in some runs only, on the same hardware and settings. A rate
  that is not repeatable is not a shipped default.
- Only 4 channels were tested. The ceiling is assumed to be independent of
  the channel count for 8-channel devices. This is not measured.

**Rejected alternative.** `RAW_SAMPLERATE_HZ` = 10000 was set for a short
time to decrease GUI lag at 4 channels. The `maxfreq` clamp then limited
F_max to 3906 Hz: the 5 kHz and 10 kHz presets were not available, and the
envelope bandwidth was half. GUI cost is not a reason to lower the raw rate
below what the presets need (see E3 for the real GUI cost).

### E2. Anti-alias kernel

**Decision.** `picoscope._antialias_taps` designs a Kaiser-windowed FIR:
`_AA_STOPBAND_DB` = 100 dB, `_AA_TRANSITION_FRAC` = 0.20. It is not
`scipy.signal.decimate(ftype='fir')`. `collector.decimate_to_rate` uses the
same stopband target (E7).

**Why not the scipy default.** `scipy.signal.decimate(ftype='fir')` builds a
20q+1-tap FIR with a Hamming window. Its sidelobes are at about -53 dB.
Through the real decimation path at q = 4 the worst stopband was -60.0 dB,
and the passband was 0.29 % off at 0.05 x fs_out. ISO 2954 and analyser
practice expect 80 dB or more. The Hamming kernel limits the usable dynamic
range to about 55 dB to 60 dB, independent of the ADC resolution.

**Measured on:** computed through `antialias_decimate` on the development
PC, no hardware, at q = 4 (32768 Hz to 8192 Hz). CHANGELOG round 2
(2026-08-29).

| design | taps | worst stopband | passband at F_max |
|---|---|---|---|
| Hamming 20q+1 (scipy default) | 81 | -60.0 dB | +0.27 % |
| Kaiser 90 dB, transition 0.20 | 231 | -105.0 dB | +0.00 % |
| Kaiser 100 dB, transition 0.20 (chosen) | 259 | -111.7 dB | +0.00 % |
| Kaiser 100 dB, transition 0.25 | 207 | -112.4 dB | -0.42 % |

- The 0.25 transition saves 52 taps, but it attenuates the passband at F_max.
  The 2.56x convention exists to keep that region flat.
- Block edges: the longer kernel does not decrease accuracy. An in-band tone
  through one block, against the analytic RMS, at every shipped block size:
  Hamming +0.2416 %, Kaiser -0.0001 %. The Hann taper of the overall already
  gives low weight to the block edges, where the start-up transient is.
- Hardware A/B (CHANGELOG round 2): same captured samples, q = 8. The Kaiser
  kernel gives +10.8 dB more rejection at 2600 Hz and +10.3 dB at 3100 Hz,
  where alias leakage is above the capture noise floor. Below the floor the
  two kernels are equal.

### E3. ADC-to-mV conversion

**Decision.** `picoscope._adc_to_mv` converts ADC counts with one vectorised
expression: `int16 -> float64 * v_range / max_adc`. Do not use
`picosdk.functions.adc2mV`.

**Why.** `adc2mV` is a per-sample Python list comprehension:
`[(np.int64(x) * vRange) / maxADC.value for x in bufferADC]`. It runs in
`_streaming_callback`, inside `ps4000aGetStreamingLatestValues`, with the GIL
held. Its time is taken directly from the GUI thread.

**Measured on:** the development PC, `adc2mV` plus the `np.array()` that it
needs, against `_adc_to_mv` (CHANGELOG experimental/profiling, 2026-09-11).

| samples per channel | `adc2mV` | vectorised | speed-up |
|---|---|---|---|
| 4096 | 4.22 ms | 0.021 ms | 201x |
| 19200 | 19.86 ms | 0.052 ms | 382x |
| 38400 | 40.28 ms | 0.112 ms | 361x |

- At about 1.03 us per sample, 1000 samples per callback and 76.9 kHz per
  channel, `adc2mV` used 0.079 CPU-s per wall-second per channel: 0.634 s/s
  at 8 channels.
- p95 main-loop tick latency (target 0.5 ms), from the CHANGELOG:

| channels | 1 | 3 | 4 | 8 |
|---|---|---|---|---|
| `adc2mV` | 1.42 ms | 4.67 ms | 5.75 ms | 5.76 ms |
| vectorised | 0.58 ms | 0.59 ms | 0.59 ms | 0.59 ms |

**Operation order.** Multiply by `v_range`, then divide by `max_adc`. This
is bit-identical to `adc2mV` for every voltage-range index over the full
int16 range. `x * (v_range / max_adc)` is different in the last bit.
`tests/test_adc_conversion.py` asserts both facts.

**Range table.** `_CHANNEL_INPUT_RANGES_MV` is a copy of the table in
`picosdk.functions`, where it is a module-local value. The copy lets the
conversion work when `PICOSDK_AVAILABLE` is False.

### E4. Sample-clock grid

**Decision.** `PicoScopeStream._start_streaming` requests the streaming
interval in ns. It snaps the interval to the nearest point of the
`_TIMEBASE_NS` = 12.5 ns grid, then rounds up to whole ns. At osr = 3 the
request is 13025 ns: 76775.43 Hz at the ADC, 25591.81 Hz after decimation,
-320 ppm from 25600 Hz. The driver writes back the interval that it used, and
that value is the one that everything downstream uses (E5).

**Why not whole microseconds.** 1e6 / 76800 = 13.02 us truncates to 13 us:
76923 Hz, +1603 ppm. Every displayed frequency was 0.16 % high (a 1000 Hz
line read 1001.6 Hz). 25641 Hz is also coprime with every display rate,
which made the resample FIR very long before E7 bounded it.

**Why not round(1e9 / fs).** The ns grid is not continuous. The driver
floors a request to the grid, so the correct value 13021 ns lands at
13012 ns, one grid point high.

**Measured on:** PicoScope 4824A, s/n 13290/0013 (CHANGELOG
experimental/profiling, 2026-09-11). Requested intervals, and the interval
that the driver wrote back:

| requested ns | returned ns | rate per channel (Hz) | / osr (Hz) | ppm against 25600 Hz |
|---|---|---|---|---|
| 13021 | 13012 | 76852.14 | 25617.38 | +679 |
| 13020 | 13012 | 76852.14 | 25617.38 | +679 |
| 13015 | 13012 | 76852.14 | 25617.38 | +679 |
| 13013 | 13012 | 76852.14 | 25617.38 | +679 |
| 13012 | 13000 | 76923.08 | 25641.03 | +1603 |
| 13000 | 13000 | 76923.08 | 25641.03 | +1603 |
| 12995 | 12987 | 77071.29 | 25690.43 | +3532 |
| 13025 | 13025 | 76775.43 | 25591.81 | -320 |
| 13026 | 13025 | 76775.43 | 25591.81 | -320 |
| 12500 | 12500 | 80000.00 | 26666.67 | +41667 |

- The reachable points are 12.5 ns apart (12987.5, 13000, 13012.5, 13025):
  an 80 MHz timebase.
- 8e7/1041 and 8e7/1042 are on the two sides of 76800 Hz. 1042 is nearer,
  so -320 ppm is the best that this hardware can do. That is 5x better than
  +1603 ppm.
- The snap is an optimisation only. A device with a different timebase
  floors to its own grid, and the readback reports it.

### E5. Report the achieved rate

**Decision.** `PicoScopeStream._report_samplerate` returns
`actual_raw_fs / effective_osr` as a float. This is the `samplerate` of each
block, of `VibeSample.samplerate` and of the HDF5 frame attribute. It is not
`config.raw_samplerate`. Every frequency axis is built from it.

**Why.** The driver quantises the interval to its own clock grid (E4), so the
achieved rate is generally not the requested rate. A requested rate scales
every displayed frequency by requested / achieved.

**Measured on:** the example below is from before the raw/display split,
when the raw rate followed F_max. At F_max = 2000 Hz the raw
rate was 32768 Hz. The driver rounded 30.5 us down to 30 us: 33333 Hz raw,
8333.33 Hz after decimation, labelled 8192 Hz (-1.70 %; the CHANGELOG writes
8333.25 Hz). A true 100 Hz tone displayed at 98.3 Hz, and a 60 Hz line read
59.0 Hz. This breaks harmonic families, sideband spacing and BPFO/BPFI
comparison with a nameplate.

- Hardware check (CHANGELOG fix/measurement-validity, 2026-08-28):
  PicoScope 4424A, AWG loopback on channel A, same captured
  samples with two labels. A commanded 1000.00 Hz tone read 983.062 Hz
  (-1.694 %) with the requested rate and 1000.012 Hz (+0.001 %) with the
  achieved rate. Mean error over four tones: 1.676 % to 0.034 %.
- Keep the rate a float at every step, including persistence. Truncating
  25591.81 Hz to 25591 Hz moves every frequency by 32 ppm (computed).

### E6. Oversampling ratio

**Decision.** `PicoScopeStream._choose_osr(samplerate)` returns
`min(OSR_TARGET, floor(STREAMING_CEILING_HZ / samplerate))` = min(4,
floor(100000 / 25600)) = 3. If that is less than 2 it returns 1 and logs a
warning: `antialias_decimate` does nothing at factor 1, so there is no
anti-alias filter.

**Why the anti-alias filter must not be skipped.** A general-purpose IEPE
accelerometer has a mounted resonance at 25 kHz to 80 kHz, with 20 dB to
30 dB of gain. At F_max = 20 kHz (raw rate 65536 Hz at that time) an
unfiltered 50 kHz component folds to 15536 Hz. That is inside the displayed
band, and it looks like real signal (calculation from the August 2026 audit, not measured).

**Rejected alternative.** `max(1, int(min(OSR_TARGET, CEILING /
samplerate)))` truncated 1.526 to 1 at F_max = 20 kHz and 0.763 to 0 (then 1)
at 50 kHz. Both top presets ran with no filter, and the 50 kHz preset
requested 131072 Hz, 31 % above `STREAMING_CEILING_HZ`. Those presets were
removed; the top preset is now 10 kHz.

### E11. Display rate, block size and line count

**Decision.** In `AcquisitionSettings` (`sample.py`):

- `samplerate` = round(2.56 x `maxfreq`). Nyquist is 1.28 x `maxfreq`, a
  28 % guard band for the anti-alias filter. The `maxfreq` setter clamps to
  `raw_samplerate / 2 / 1.28`, which is the condition
  2.56 x `maxfreq` <= `raw_samplerate`.
- `blocksize` = ceil(`samplerate` / `binsize`): the shortest block whose bin
  is not coarser than `binsize`.
- `nperseg` = `blocksize`: one Welch segment per frame.
- `n_fft_bins` counts the lines from DC to `maxfreq`, not `nperseg // 2 + 1`.

**Rejected alternative: power-of-two rate and block.** `samplerate` was
nextpow2(2.56 x `maxfreq`), and `blocksize` was nextpow2(`samplerate` /
`binsize`). With `RAW_SAMPLERATE_HZ` = 25600 Hz the top preset rounded to
32768 Hz, more than the raw data. `decimate_to_rate` then returned the block
at 25600 Hz while the dialog showed 32.8 kS/s, and `n_fft_bins` and
`binsize_actual` came from a rate that did not exist. A power-of-two block
also made a frame up to 2x longer than 1/`binsize`. Measured worst-case
frame-length overshoot over the 54 preset combinations: 56.2 % before,
17.2 % after (CHANGELOG hotfix/RAW_SAMPLERATE).

**Rejected alternative: Welch nfft different from the block.** Welch used
`nfft = int(samplerate / binsize)` while `blocksize` was larger. The line
count and bin width were not the ones that the UI showed. 40 of 72 preset
combinations at that time (8 F_max x 9 binsize) were wrong. Examples:
F_max = 200 Hz, df = 20 Hz showed 17 lines against 13 real lines at 20.48 Hz;
F_max = 2000 Hz, df = 5 Hz showed 1025 lines against 820 (CHANGELOG fix/measurement-validity, 2026-08-28).

**Block sizes that are not exact.** Computed with the current code over all
54 combinations of `MAXFREQ_PRESETS` and `BINSIZE_PRESETS`, 2026-09-29. In
43 combinations `binsize_actual` equals `binsize`. In 11 it is finer, and in
10 of these 11 `blocksize` is not 5-smooth (it has a prime factor above 5):

| F_max (Hz) | binsize (Hz) | samplerate (Hz) | blocksize | 5-smooth | binsize_actual (Hz) |
|---|---|---|---|---|---|
| 200 | 5 | 512 | 103 | no | 4.971 |
| 200 | 10 | 512 | 52 | no | 9.846 |
| 200 | 20 | 512 | 26 | no | 19.692 |
| 200 | 50 | 512 | 11 | no | 46.545 |
| 200 | 100 | 512 | 6 | yes | 85.333 |
| 500 | 50 | 1280 | 26 | no | 49.231 |
| 500 | 100 | 1280 | 13 | no | 98.462 |
| 1000 | 50 | 2560 | 52 | no | 49.231 |
| 1000 | 100 | 2560 | 26 | no | 98.462 |
| 2000 | 50 | 5120 | 103 | no | 49.709 |
| 2000 | 100 | 5120 | 52 | no | 98.462 |

The GUI offers every `BINSIZE_PRESETS` value at every F_max
(`gui.py`, `_BINSIZE_LABELS`). The blocks that are not 5-smooth are 103
samples or less, so the FFT cost is not important.

**Live line count.** `n_fft_bins` is nominal. The live spectrum uses the
achieved rate (E5). At F_max = 10 kHz, df = 0.25 Hz and 25591.81 Hz the live
spectrum has 40013 lines up to F_max against a nominal 40001 (computed with
`decimate_to_rate` and `numpy.fft.rfftfreq`, 2026-09-29).

### E20. Speed gate (part from `sample.py`)

<!-- W2-A: merge with the E20 text from anomaly.valid_results (W1-C5). -->

**Decision.** `AcquisitionSettings.speed_gate_enabled`, `speed_gate_rpm` and
`speed_gate_tolerance_pct` (default 3.0 %) declare a shaft-speed window. A
frame outside it is measured, shown and stored, but it is not trended, not
used for baseline adaptation and not alarmed on. Its amplitude is correct
but not comparable. The gate is off by default, because it needs a
tachometer. `speed_gate_rpm` = None latches the reference from the first
valid frame.

**Why.** For a rigid rotor below its first critical speed, the 1x velocity
changes as omega cubed. A shaft-speed change of 3.2 % alone moves the
overall by 10 %, which was the `RmsThresholdHook` threshold before it became
50 %. Without the gate, on a VFD or a load-following machine, the anomaly
detector measures load, not condition. (Source: the `sample.py` field comment;
calculation, not measured.)
