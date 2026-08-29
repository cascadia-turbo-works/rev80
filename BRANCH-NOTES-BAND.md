# Branch notes — `fix/declared-band`

Round 2 of the vibration-engineering audit remediation: M-06 (band-limited
overall), M-12 (anti-alias stopband), and the ISO 2954 band-edge finding.
Written in the style of `doc/CHANGELOG.md`; fold into that file on merge.

**Status:** complete. Suite **668 passed, 0 skipped** (a PicoScope 4424A was
attached, so the 9 usually-skipped hardware tests ran and passed). ruff clean.
Every fix revert-checked: reverting it makes the new tests fail.

---

## The shape of the defect

F-1 fixed *how* the overall was computed. It did not fix *what it was computed
over*. The overall was `sqrt(mean(x**2))` of the whole filtered block, so its
band was `highpass_fc … fs/2` — and `fs/2` is 1.28x–2.56x `maxfreq` depending
on where the power-of-two rounding in `AcquisitionSettings.samplerate` lands,
**2.048x at the 500/1000/2000 Hz presets**. Meanwhile F-9 had already truncated
the *spectrum* at `maxfreq`. So the number on the result card and the picture
next to it described different bands, and nothing recorded which.

Two consequences, both quantified by the audit and both now reproduced:

* Content the user explicitly excluded via F_max still reached the trend —
  2 g RMS at 1500 Hz outside a 1000 Hz F_max inflated reported overall velocity
  from 3.00 to 3.74 mm/s (+25%), enough to move a machine from ISO 20816 zone B
  to zone C on a reading that should never have included it.
* Overalls were not comparable across sessions taken at different F_max, which
  silently invalidates long-horizon trending — the thing the app exists to do.

---

## Added

- `AcquisitionSettings.band_fmin` / `.band_fmax` (`None` = derive) with
  `.band_fmin_resolved`, `.band_fmax_resolved`, `.band`. Defaults are
  `highpass_fc … maxfreq`, and the upper edge is clamped to `maxfreq` so a
  stored band can never reintroduce the guard band.
- `util.ISO_BAND_PRESETS` — ISO 20816 10–1000 Hz and low-speed 2–1000 Hz.
- `ChannelResult.band_fmin` / `.band_fmax` / `.band`.
- `_dsp.band_mask()`, `_dsp.band_rms()`, `_dsp.butter_knee_for_edge()`,
  `_dsp.PASSBAND_TOLERANCE`.
- `DataCollector.highpass_knee_hz()`.
- `picoscope._antialias_taps()` — cached Kaiser kernel design.
- `gui.GUI._band_suffix()`, `._band_preset_label()`, `._on_band_preset()`.
- `tests/test_declared_band.py` — 46 tests, all off-bin and phase-shifted.

## Changed

- **All five integration orders share one masked, Hann-tapered path.** Order 0
  previously skipped the taper, correctly, on the grounds that a passthrough
  performs no transform-domain multiply and so has no wrap discontinuity to
  suppress. Band-limiting removes that premise: the mask *is* such a multiply,
  hence a circular convolution in time.
- The band joins the PSD cache key, for the reason binsize did in M-09.
- The displayed waveform is masked to the same band as the overall.
- `AcquisitionSettings.copy()` now round-trips through `to_dict`/`from_dict`
  and deep-copies the per-channel dicts. It previously copied only maxfreq and
  binsize, silently dropping everything else (audit H-08).
- `monitor/writer.py` `_compute_overall_peaks()` returns a third `band_json`,
  written on both the interval and burst paths.

## Test expectation changed

`test_passthrough_overall_exact_for_off_bin_tone` asserted
`overall == sqrt(mean(data**2))` to 1e-9. It now asserts the tone's true RMS,
`A/sqrt(2)`, to the same 1e-9, and is renamed accordingly.

This is a better assertion, not a weaker one. An off-bin tone spans a
non-integer number of cycles, so the raw record RMS carries a ~0.1%
partial-cycle bias — here +0.097% — that depends on where the block happened to
start and is not a property of the signal. The tapered estimate lands on
`A/sqrt(2)`; the raw record RMS does not. The test now pins both facts.

---

## Fixed

### M-06 — the overall was not band-limited

The mask is applied to the rFFT before integration, and the bin-0/bin-1 zeroing
inside `integrate_rfft` is kept as a floor for bands starting below one bin.

**Windowed vs un-windowed, measured.** An un-tapered transform plus Parseval was
the obvious choice for order 0 — it is exact, and reproduces the old full-band
`sqrt(mean(x**2))` to machine precision. It was rejected on measurement:
restricting an un-tapered transform to a set of bins gives that band a
*rectangular window's* edge, with −13 dB first sidelobes.

| case (3x tone outside the band)   | un-tapered | Hann   |
|---|---|---|
| 30 Hz against a 100 Hz lower edge | +2.70%     | +0.00% |
| 1500 Hz against a 1000 Hz edge    | +0.06%     | +0.00% |

Rejection of the out-of-band tone: **−22 dB un-tapered, −84 to −144 dB Hann**.
The Hann path costs 4.9e-4 worst-case in-band error across the preset grid.
Band rejection is what an instrument needs here; the fifth decimal place is not.

### ISO 2954 — the high-pass −3 dB point sat on the declared band edge

A 4th-order Butterworth designed *at* 10 Hz is −3 dB there, i.e. reads 29% low
at the very frequency the standard names as the bottom of its declared band.
`highpass_fc` is now the declared edge and the knee is placed below it:

    A      = 0.9                      # +/-10% amplitude tolerance
    r      = A**2 / (1 - A**2)        # = 4.2632
    f_knee = f_edge * r ** (-1/(2N))

At N=4 that is `f_knee = 0.8342 * f_edge`, so a 10 Hz edge designs at 8.34 Hz
and reads −0.915 dB (x0.900) at 10 Hz.

Lowering the knee is only safe **because of M-06**: the frequency-domain mask
removes sub-band energy exactly, so the `1/omega**2` blow-up the higher knee was
implicitly guarding against cannot reach the integrated result. Land the mask
first; these two are not independent.

### M-12 — anti-alias stopband was ~55 dB against an ~80 dB expectation

`scipy.signal.decimate(ftype='fir')` builds a 20q+1 tap FIR with a **Hamming**
window, sidelobes at about −53 dB. Measured end to end at q=4: **−60.0 dB**
worst case, and the passband already 0.29% off at 0.05·fs_out.

| design                    | taps | worst stopband | passband @ F_max |
|---|---|---|---|
| hamming 20q+1 (previous)  |  81  |    −60.0 dB    |     +0.27%       |
| kaiser 90 dB,  tw 0.20    | 231  |   −105.0 dB    |     +0.00%       |
| **kaiser 100 dB, tw 0.20**| **259** | **−111.7 dB** |  **+0.00%**   |
| kaiser 100 dB, tw 0.25    | 207  |   −112.4 dB    |     −0.42%      |

The wider 0.25 transition saves 52 taps but starts eating the passband at
F_max — exactly the region the 2.56x oversampling convention exists to keep flat.

**The longer kernel costs nothing at block edges**, which was the obvious worry
given it runs per block. Measured on one block against the analytic RMS, at
every shipped blocksize: hamming **+0.2416%**, kaiser **−0.0001%**. The
overall's Hann taper already de-weights the edges where the start-up transient
lives, and the flatter passband wins by more than the longer transient costs.

---

## Hardware verification

PicoScope 4424A, AWG loopback on channel A, 1.0 Vpp sine (354 mV RMS). The
siggen emits one tone at a time, so band exclusion is verified as a sweep across
the edge rather than by summing two tones.

**A. Band exclusion** — F_max 2000 Hz, declared band 10–1000 Hz:

| tone | overall | vs in-band |
|---|---|---|
|  800 Hz | 354.185 mV | +0.0 dB |
|  950 Hz | 354.081 mV | −0.0 dB |
| 1000 Hz | 246.702 mV | −3.1 dB |
| 1100 Hz |   0.437 mV | **−58.2 dB** |
| 1300 Hz |   0.416 mV | −58.6 dB |
| 1600 Hz |   0.400 mV | −58.9 dB |

A measured 58 dB cliff at the declared edge, where everything up to fs/2 was
previously counted. The −3.1 dB at 1000 Hz is the tone sitting on the inclusive
edge itself.

**B. High-pass at the declared edge** — F_max 200 Hz, HP edge 10 Hz:

| tone | overall | vs 100 Hz |
|---|---|---|
| 100 Hz | 354.164 mV | +0.00 dB |
|  20 Hz | 352.537 mV | −0.04 dB |
|  10 Hz | 313.996 mV | **−1.05 dB** |
|   5 Hz |  42.581 mV | −18.40 dB |

−1.05 dB at the declared edge against the −3.0 dB the old design gave and the
−0.915 dB predicted; the 0.14 dB residual is the AC coupling's own ~1 Hz corner,
which is in series with the digital filter. Rejection below the edge is
unaffected.

**C. Anti-alias A/B on identical captured samples** — the same raw array
decimated twice, q=8, so the kernel is the only variable:

| tone | folds to | hamming | kaiser | improvement |
|---|---|---|---|---|
| 2600 Hz | 1566.7 Hz | 0.4237 mV | 0.1216 mV | **+10.8 dB** |
| 3100 Hz | 1066.7 Hz | 0.4327 mV | 0.1317 mV | **+10.3 dB** |
| 4700 Hz |  533.3 Hz | 0.1473 mV | 0.1472 mV | +0.0 dB |
| 6300 Hz | 2033.3 Hz | 0.1058 mV | 0.1057 mV | +0.0 dB |

Where alias leakage rises above the capture's own noise floor the Kaiser kernel
buys ~10 dB. The +0.0 dB rows are not a null result: both kernels are under the
floor there (~0.10–0.15 mV, essentially constant with tone frequency, which is
what identifies it as a floor rather than as alias). The bench figure of
−60 → −111.7 dB is the fuller picture; this is the part of it this instrument
can actually see.

---

## Deliberately NOT done here

- **ISO 20816 zone A/B/C/D limits.** The band work is the prerequisite and is
  now in place; machine-class selection and zone display are R34.
- **Re-adding the 20 kHz preset.** The Kaiser kernel's steeper transition is
  what the F-3 notes said would buy it back, but that needs its own hardware
  measurement against `STREAMING_CEILING_HZ`, not an inference from this one.
- **Band-limiting the spectrum.** The spectrum is still shown from DC to F_max;
  only the overall and the waveform are band-limited. Showing the analyst the
  content the overall excluded is the right default — but the band edges are not
  drawn on the plot, and probably should be.
- **Carrying anti-alias filter state across blocks.** `resample_poly` has no
  state interface, so each block still starts the FIR from rest. Measured as
  costing nothing at present (see above), but it is the same class of defect
  F-4 fixed for the high-pass, and it would matter if the taper ever changed.
