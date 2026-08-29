# Branch notes — `fix/measurement-validity`

Measurement-validity defects found by the vibration-engineering audit (F-1 … F-9),
plus one adjacent logging defect (S-09). Written in the style of `doc/CHANGELOG.md`;
fold into that file when this branch is merged.

**Status:** all nine defects fixed. Suite: **422 passed, 1 failed**
(`test_vibechecker.py::test_gui_build` — a missing gitignored font in this
worktree, unrelated to this branch and owned by another workstream).

**Headline capability change:** `MAXFREQ_PRESETS` loses `2e4` and `5e4`.
F_max now tops out at **10 kHz, down from 50 kHz**. See F-3.

---

## Root cause of the whole class: the test suite was degenerate

The existing suite passed completely while the instrument was measurably wrong.

`tests/test_sample.py` sets F_max=10000, binsize=2 → fs=32768, N=16384, so the
bin spacing is exactly 2.000 Hz — then sweeps tones at 500, 1000, 1500 … 9500 Hz,
**every one an exact multiple of 2**. That is the single degenerate case where the
block is genuinely periodic in N samples, the FFT's circular-wrap discontinuity
vanishes, and the integration error is identically zero. `_make_dc` also defaulted
`highpass_enabled=False`, so the filtered path was never exercised by any amplitude
assertion, and the displacement tests asserted only on the spectrum peak (correct)
and never on `result.overall` (not correct).

Phase 1 of this branch was therefore a deliberately **red** commit (`f9a6d43`):
110 tests, 92 failing, before any fix was written.

### The same mistake, made again — and caught

Partway through, real hardware exposed a bug in the F-4 fix itself. Every tone in
the new suite was generated as `sin(2*pi*f*t)`, so **every record started at phase 0**
and `x[0]` equalled the DC level exactly. That is degenerate in precisely the same
way bin-centred frequencies are. The new suite, written to catch the audit's blind
spot, had reproduced it. `tone()` now takes a `phase` argument defaulting to 0.7 rad.
See F-4 follow-up.

---

## Added

- `src/rev80/_dsp.py` — windowing helpers for frequency-domain integration, with
  the measured error tables that justify each choice.
- `AcquisitionSettings.nperseg` and `.binsize_actual` — the Welch segment length
  and the bin width actually delivered.
- `DataCollector.filter_block()`, `.filtered_data_for()`, `.reset_filter_state()`,
  `._seed_zi()` — persistent per-channel high-pass state.
- `gui.derive_acquisition_preview()` — single source of truth for the dialog preview.
- `monitor.anomaly.valid_results()` — shared validity filter for anomaly hooks.
- `tests/test_measurement_validity.py` — 123 tests covering F-1 … F-9 and S-09.

## Changed

- `MAXFREQ_PRESETS`: `[2e2, 5e2, 1e3, 2e3, 5e3, 1e4]` (was `… 2e4, 5e4`).
- `VibeSample.samplerate` / `ChannelResult.samplerate` / HDF5 `samplerate` attr are
  now `float`. The true rate is generally not an integer.
- `n_fft_bins` now counts **displayed** lines (DC…F_max), not the full one-sided
  transform. At the default preset: 1001, not 2049.
- The spectrum info panel reports `binsize_actual` and is labelled `F_max`, not `AA`.
- `monitor/writer.py` no longer has its own copy of `_write_channel_group`.
- CRLF → LF in `picoscope.py` and two `examples/` scripts.

---

## Fixed

### F-1 — FFT wrap leakage corrupted every integrated overall and waveform

`rfft` was taken on the raw, un-windowed block and multiplied by `(j*omega)^n`.
The DFT treats the record as periodic; unless it is exactly periodic in N samples
there is a step discontinuity at the wrap point whose spectrum is broadband and
low-frequency-weighted, and `n < 0` amplifies it by `1/omega^|n|`. The in-code claim
that "the irfft is an exact inverse … so the round-trip is lossless" held only for
`n_ord == 0`. Zeroing bins 0 and 1 left bins 2, 3, 4 … where the leakage still sat.

The spectrum was never affected — Welch already windows. What was wrong was the
Overall card, the trend, `overall_json`, the anomaly detector's input, and the
displayed waveform.

**Fix.** Two treatments, because the consumers want different things:
- Scalar overalls: Hann taper, RMS divided by the window power gain `sqrt(mean(w²))`.
- Displayed waveform: cannot be tapered (the envelope would be visible). Overlap-save
  instead — Tukey `alpha=0.5` kills the wrap discontinuity, and only the flat middle,
  where the window is exactly 1.0, is returned. `time_vec` truncated to match.
  **Cost: integrated/differentiated traces span the middle 50% of the block.**

Measured (1.0 unit 0-pk sine, fs=32768, N=16384):

| overall | tone | before | after |
|---|---|---|---|
| velocity | 61.0 Hz | +12.25% | +0.05% |
| velocity | 120.7 Hz | +8.08% | +0.01% |
| displacement | 61.0 Hz | +470.59% | +0.18% |
| displacement | 120.7 Hz | +777.84% | +0.05% |
| displacement | 501.0 Hz | +4473.76% | +0.00% |
| displacement | 500.0 Hz (on-bin) | +0.00% | +0.00% |

| waveform peak | tone | before | after |
|---|---|---|---|
| velocity | 61.0 Hz | +90.22% | +0.10% |
| displacement | 61.0 Hz | +1149.12% | +1.47% |
| displacement | 501.0 Hz | +10176.68% | +0.24% |

Taper-width sweep (worst case, 61 Hz displacement): alpha 0.05 → +335.84%,
0.10 → +7.00%, 0.30 → +4.22%, **0.50 → +1.47%**. 0.5 is the first value holding
every case inside 2%. Reflection padding was also tried and is far worse
(+1918% at 61 Hz) — it doubles the effective near-DC content.

Differentiation (n=+1) verified unaffected: worst +0.018%.

### F-2 — the reported sample rate was not the rate actually used

`_start_streaming` computed `actual_raw_fs` correctly from the interval the driver
writes back, then discarded it (`self._actual_samplerate = self.config.samplerate`).
The comment conflated "hide the oversampling ratio" with "hide the actual rate".

| F_max | requested | raw µs | raw actual | true decimated | was reported | error |
|---|---|---|---|---|---|---|
| 200 | 512 | 488 | 2049 | 512.25 | 512 | −0.05% |
| 2000 | 8192 | 30 | 33333 | 8333.25 | 8192 | −1.70% |
| 5000 | 16384 | 15 | 66667 | 16666.75 | 16384 | −1.70% |
| 10000 | 32768 | 10 | 100000 | 33333.33 | 32768 | −1.70% |
| 50000 | 131072 | 7 | 142857 | 142857.00 | 131072 | −8.25% |

**Confirmed on real hardware** (PicoScope 4424A, AWG loopback on channel A). Same
captured samples, two labellings:

| commanded | old label | new label |
|---|---|---|
| 101.00 Hz | 99.379 (−1.605%) | 101.093 (+0.092%) |
| 203.70 Hz | 200.186 (−1.725%) | 203.638 (−0.031%) |
| 447.30 Hz | 439.777 (−1.682%) | 447.360 (+0.013%) |
| 1000.00 Hz | 983.062 (−1.694%) | 1000.012 (+0.001%) |

Mean |error| **1.676% → 0.034%**. A 1 kHz tone read 17 Hz low. Reported as a float;
rounding would reintroduce a smaller version of the same error.

### F-3 — no anti-alias filtering at all above F_max = 20 kHz

`antialias_decimate()` is a no-op at factor 1, so `osr == 1` means no anti-alias
filter exists. `max(1, int(min(OSR_TARGET, CEILING / samplerate)))` truncated
toward zero: 1.526 → 1 at 20 kHz, 0.763 → 0 → clamped to 1 at 50 kHz. The 50 kHz
preset additionally requested 131072 Hz raw, **31% above** the measured
`STREAMING_CEILING_HZ`, the exact condition the module docstring says makes the
driver silently drop most samples while reporting `status='OKAY'`.

A general-purpose IEPE accelerometer has a mounted resonance at 25–80 kHz with
20–30 dB of gain. At F_max=20 kHz an unfiltered 50 kHz component folds to 15536 Hz —
inside the displayed band, indistinguishable from real signal, and *larger* than the
real signal because of the resonance gain.

**Fix.** `_choose_osr()` uses explicit `math.floor` and requires `osr >= 2`.
Only F_max ≤ 10 kHz satisfies `fs*2 <= 100 kHz`, hence:

> **PRESETS REMOVED: 20 kHz and 50 kHz.** User-approved. Overrule by raising
> `STREAMING_CEILING_HZ`, which requires re-measuring the safe continuous
> streaming rate on the target hardware and channel count.

A maxfreq outside the presets still degrades rather than failing, but now logs a
WARNING naming the frequency above which content will alias.

### F-4 — high-pass filter state reset to zero on every block

`sosfilt` was called with no `zi`, so the filter restarted from rest at every block.
The comment correctly rejects `sosfiltfilt` (a real prior bug — see the
`hotfix/hpf-integration-fix` entry) but the replacement reintroduced the problem.

Measured, 200 Hz tone, 10 Hz high-pass, blocks 1–3 of a continuous stream:

| | before | after |
|---|---|---|
| acceleration waveform peak | +9.41% | −0.000% |
| displacement overall | +19.15% | +0.017% |
| acceleration overall, 1000 mV DC offset | +14321.74% | −0.000% |
| displacement overall, 1000 mV DC offset | +1472786.72% | +0.017% |

**Two regimes, handled distinctly, because replay is not a stream.** Live streaming
filters once per frame in `receive_data`, in order, carrying state; the result is
cached on the `VibeSample` because `process_sample` is called repeatedly on the same
frame. Replay/browse re-processes stored frames out of order and carries no state —
verified bit-identical forward and reverse to 12 significant figures.

Block 0 of a stream still shows genuine settling; there is no history to carry.

#### F-4 follow-up — seed from block DC, not `x[0]` (found by hardware)

`sosfilt_zi(sos) * x[0]` is scipy's documented idiom and is correct when the first
sample represents the baseline — true for a step, false for anything oscillatory.
On four consecutive real captures the block mean was −0.06…−0.21 mV (the true DC)
while `x[0]` ranged over **36…305 mV**. Worst-block error vs a fully-settled
continuous-filter reference:

| order | `zi * x[0]` | `zi * mean(x)` | warm-up pass |
|---|---|---|---|
| acceleration | +0.39% | −0.00% | +0.00% |
| velocity | +23.01% | −0.06% | −0.07% |
| displacement | +4297.20% | **−2.22%** | +61.10% |
| waveform peak | 57.63% | **0.51%** | 6.37% |

A warm-up pass (filter the block, reuse its final state as its initial state) was
measured and is **worse** than the mean — it imposes a periodic assumption the block
does not satisfy. Mean-seeding landed.

Streaming blocks 1+ match the settled reference to ±0.000%. Residual displacement
error on an isolated block is irreducible: at 447 Hz the doubly-integrated result is
dominated by near-DC noise whose continuation is not present in one block.

### F-5 — overload/degraded frames trended, alarmed on, and stripped on save

Four independent gaps, together the classic spurious-alarm mechanism: a clipped
waveform reads high with harmonic distortion, the trend records a step change that
never happened, the detector fires — and on reload the record looks clean.

1. The overflow bitmask was read from whichever callback completed a block; a
   callback that raised overflow mid-accumulation had its flag discarded. Now
   latched with `|=` and cleared on emit.
2. `update_trend` ran regardless of the flags. Flagged frames are now excluded from
   the trend (still displayed, still flagged).
3. `_read_frame_group` hard-coded `overflow=False` and never set `degraded`, so the
   flags `_write_channel_group` had faithfully stored were never read back.
4. `monitor/writer.py` had a second, divergent `_write_channel_group` that wrote no
   validity flags at all. The divergence *was* the defect; they are now one function.
5. The anomaly hooks never read either flag. `valid_results()` is applied to both
   event evaluation and baseline adaptation — letting a clipped frame into an EWMA
   baseline poisons the reference for ~33 frames just as surely as firing on it.

### F-6 — acquisition dialog computed the sample rate with 2×, not 2.56×

The dialog duplicated the derivation and used the bare Nyquist minimum. At the
default F_max=2000 it advertised 4.1 kS/s, 2049 lines, 1.000 s and half the true
memory while the instrument ran at 8.2 kS/s, 4097 lines, 0.500 s. Now delegates to
`AcquisitionSettings`; verified equal across the full preset grid.

### F-7 — PSD cache key omitted binsize and samplerate

Switching 2 Hz → 0.5 Hz bins returned the identical cached 2049-point, 2 Hz
spectrum. Masked while streaming (each new `VibeSample` starts with `psd_mv=None`),
so it bit in browse/offline mode and after loading a file.

### F-8 — stated line count and bin width did not match the computed spectrum

`n_fft_bins` returned `blocksize//2 + 1` but Welch used `nfft = int(samplerate/binsize)`
while `blocksize = nextpow2(samplerate/binsize) >= nfft`. **40 of 72** preset
combinations were wrong; worst F_max=200/df=20 → real resolution 20.480 Hz (+2.40%),
17 lines claimed against an actual 13. Fixed with `nperseg = blocksize`; re-verified
**0 of 72** mismatch. The existing amplitude suite was unaffected — at its
F_max=10000/df=2 the old and new `nperseg` were already both 16384.

### F-9 — spectrum displayed out to fs/2, where alias rejection is ~12 dB

The axis, the peaks table and `find_peaks` all ran to fs/2 = 1.28 × F_max — the
anti-alias filter's transition band, −21.8 dB at the folding frequency and
effectively 0 dB at fs/2. Truncated at F_max before peak-finding. The info label
called fs/2 the "AA" frequency, which read as a spec the instrument does not meet;
now "F_max".

### S-09 — ADC overflow warning flooded the log

`elif ch in self._overflow_warned: remove(ch)` fired precisely when a channel was
*still* clipping, re-arming the warning every other callback: measured **10 warnings
from 20 callbacks**. At a 1 ms poll interval that rolls every other diagnostic out of
the rotating log during exactly the run being diagnosed. The loop also had to move
out of `if overflow:` — clear-down can only be seen when the mask returns to zero.

---

## Test expectations changed

| Test | Change | Why |
|---|---|---|
| `test_acquisition_settings.py::test_n_fft_bins` | Was `n_fft_bins == blocksize // 2 + 1`; now asserts the stated line count and bin width match a real `scipy.signal.welch` call across the full 72-combination grid, counting only lines ≤ F_max. | The old form merely restated the implementation, so it locked in F-8 and could never fail. |
| `test_f7_psd_cache_invalidates_on_binsize_change` | Direction reversed: 0.5 → 8.0 Hz (coarser) instead of 2.0 → 0.5 (finer). | Asking a stored 0.5 s record for 0.5 Hz bins is physically impossible, so the original direction could not distinguish a stale cache from correct behaviour. Confirmed the rewritten test still fails against the pre-fix collector. |
| `test_f7_psd_cache_invalidates_on_samplerate_change` | Asserts on bin width instead of `freq[-1]`. | After F-9, `freq[-1]` is capped at F_max for every configuration. |
| `test_f1_passthrough_overall_unchanged` | Compares against the record's exact RMS, not `A/√2`. | An off-bin tone spans a non-integer number of cycles, so its true RMS differs from `A/√2` by ~0.06% for physical reasons. |
| `tone()` helper | Gained `phase`, default 0.7 rad. | Every test started at phase 0, making `x[0]` equal the DC level — the degenerate case that hid the F-4 seeding bug. |

---

## Hardware verification

PicoScope 4424A (s/n 12462/0067), AWG loopback. **The loopback is on channel A
(index 0)**, not channel two. F-1 and F-2 verified against it — see the tables above.

### The IEPE accelerometer was not live

No channel showed an IEPE bias voltage: DC-coupled at ±10 V range, all four channels
read **−21…+6 mV**, not the 10–14 V a powered IEPE sensor shows. No 47 Hz content
anywhere. The Hardy Shaker reference (0.30 in/s @ 47 Hz, 100 mV/g) could **not** be
checked.

This is itself evidence for the audit's separate finding that the app has **no
sensor-fault detection**: a disconnected or unpowered accelerometer produces a
near-zero reading that the app would trend as a healthy, very quiet machine. There is
no bias-voltage check anywhere in the codebase.

**TODO — calibrated-chain verification, not yet run.** When the coupler and shaker
are powered:
1. DC-couple the sensor channel and confirm bias is 10–14 V. If it reads ≈0 mV the
   coupler is not powered and any subsequent number is meaningless — stop.
2. AC-couple, sensitivity 100 mV/g, EU `g`, target unit `in/s`, at 47 Hz.
3. **Establish whether the 0.30 in/s reference is RMS, 0-pk or pk-pk and set the
   amplitude mode to match** (the app defaults to `0-P`). An RMS reference compared
   against a 0-P reading shows a 1.414× discrepancy that looks exactly like a
   sensitivity-path scaling bug; "fixing" that would break a correct conversion.
4. Expected at 0.30 in/s 0-pk: 0.2295 g 0-pk → 22.95 mV 0-pk at the ADC.
5. 47 Hz is off-bin at df=2 (23.5 bins) — a real-hardware off-bin check of F-1,
   stronger than the synthetic case.
6. Compare `overall` against the spectrum peak at the same amplitude mode; for a
   dominant single tone they should agree, and a mismatch would mean the overall and
   spectrum paths have diverged, which is what F-1 was about.

---

## Recommended follow-ups (deliberately NOT implemented here)

Out of scope for this branch:

- **Band-limited / ISO 20816 overall** — needs a config surface and a product decision.
- **Steeper Kaiser anti-alias kernel** — would let `STREAMING_CEILING_HZ` buy back the
  20 kHz preset removed in F-3.
- **Physically realistic simulated bearing signal.**
- **IEPE bias-fault detection** — see the hardware section above; the app currently
  cannot tell a disconnected sensor from a quiet machine.
- Capability gaps: envelope/demodulation, order tracking, crest factor / kurtosis,
  phase, waterfall, TSA, cepstrum.
- **`.gitattributes` with `* text=auto eol=lf`** to stop CRLF returning from Windows
  CI. Not added here to avoid colliding with the packaging/CI workstream.
- `doc/CHANGELOG.md` is CRLF and was deliberately left alone — another workstream has
  uncommitted changes in it.

## Waveform limitation to be aware of

For integrated or differentiated display units, `ChannelResult.time_data` now covers
the **middle 50%** of the block (overlap-save). `time_vec` is truncated to match and
still carries true capture-relative timestamps. Passthrough units are unaffected and
still return the full record. `gui.py`'s fixed time-axis window is anchored to where
the trace actually starts. If a full-length integrated waveform is ever required, the
alternative is time-domain integration with `sosfilt` state carried across blocks —
which would need the same streaming-vs-replay split that F-4 introduced.
