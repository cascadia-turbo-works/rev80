# feature/peak-selection — significance-based peak selection

Branched off `hotfix/claude-ultrareview`. Three commits: `rev80/peaks.py` + tests,
the collector call site, the GUI control.

`python -m pytest tests/ -q` → **607 passed, 8 skipped** (was 557 + 1).
`python -m ruff check src/ tests/` → clean.

The 7 skips are the real-corpus regression tests. `DEVDATA/` is gitignored, so
they skip unless you point at it:

```bash
REV80_CORPUS_DIR='/path/to/DEVDATA/old castle' pytest tests/test_peak_selection.py
# 57 passed
```

---

## What changed

`collector.process_sample` step 6 was:

```python
peaks, _ = scipy.signal.find_peaks(spectrum_amp, distance=5)
peaks     = np.array(peaks[np.argsort(-spectrum_amp[peaks])])
```

It is now one call to `rev80.peaks.select_peaks`, which passes **array-valued**
`height` and `prominence` derived from a per-bin noise floor estimate. Amplitude
reporting is untouched: the reported value is still the amplitude of the maximum
bin at each peak. `freq` and `spectrum` are untouched. No frequency interpolation.

Ranking stays **by descending amplitude**. Significance decides *whether* a line
is reported; amplitude decides *where it sits in the table*. That is what the
review's sanity list implies (it is the old amplitude order with the rejected
lines deleted), and it is the right split: a 0.2 mV line on a very quiet floor is
real but is not the top line of the spectrum.

## Results on `blower 4 - bearing DE.h5` ch2, frame −1

| | old (top 12 by amplitude) | new (gate, 9.5 dB) |
|---|---|---|
| 1 | 1059 | 1059 |
| 2 | 1974 | 1974 |
| 3 | 1901 | 1901 |
| 4 | 1088 | 1088 |
| 5 | **1982** (4.17 dB) | 1925 |
| 6 | 1925 | **1034** ← sideband |
| 7 | **1967** (4.00 dB) | 570 |
| 8 | **1947** (7.33 dB) | 1782 |
| 9 | **1999** (see below) | 294 |
| 10 | 1034 ← sideband, off a 6-row table | 605 |
| 11 | 570 | 539 |
| 12 | 1782 | 1541 |

44 peaks reported. The 1034 / 1059 / 1088 Hz sideband family — ±25/29 Hz around
the carrier, the bearing-fault signature — is intact. 1947 / 1967 / 1982 Hz are
gone; they stand 4.0–7.3 dB out of their own neighbourhood and only reached the
old top 12 because that stretch of the band is loud (local floor 39.4 mV there
against 9.0 mV overall).

**Corpus-wide, 60 channel-spectra, default 9.5 dB:** count median 40, p10 22,
p90 49, min 16, max 61. Under the old top-10 rule 6.67 % of reported peaks stood
less than 2× above their local floor (18.17 % with a flat-top window); the gate
admits none.

## Where I deviated from the brief, with evidence

**1. Edge-replicated padding is not good enough; the fix is a truncated window.**

The brief said to use edge-replicated padding. Measured against a known floor
(40 trials, ±32 edge bins, width 65):

| edge handling | median \|err\| | p95 \|err\| | mean bias |
|---|---|---|---|
| zero-pad (`scipy.signal.medfilt`) | 2.368 dB | 11.448 dB | −3.568 dB |
| replicate (`mode='nearest'`) | 1.480 dB | 5.246 dB | −0.009 dB |
| reflect | 0.620 dB | 1.844 dB | +0.098 dB |
| truncated window | 0.591 dB | 1.829 dB | +0.050 dB |

Replication removes the bias but not the error: it copies **one** random bin 32
times, and 32 copies of a single exponential draw dominate a 65-sample median.
Reflection and truncation both reuse 32 genuinely independent samples.
`_running_median` uses truncation — at bin *i* the estimate is the median of
every bin actually within ±32 of it. It invents no data and cannot mirror a
strong line back onto itself.

**2. 1999 Hz is excluded, and the brief's sanity list is wrong about it.**

The brief lists 1999 Hz at position 6 and asks for it as a regression target.
It is not in my output, deliberately. That entry was produced *with* the
zero-padding defect: the zero-padded floor under 1999 Hz reads 14.9 mV, giving
an apparent 16.18 dB. The truncated-window floor there is 88.3 mV, giving a true
**0.73 dB** — indistinguishable from its own neighbourhood. It does not enter at
any threshold down to 8 dB. The regression test asserts the other nine in order
and documents why the tenth is absent.

(The brief's own text quotes 5.68 mV / SNR 6.4 for that bin, which is what
`mode='nearest'` gives; that is the number the replicate fix produces, not the
truth.)

**3. Width 65 survives, but the argument for it did not.**

The brief's justification — "65 spans ~3 peaks so the median stays in the floor"
— is an argument, not a measurement, and a smooth synthetic spectrum actually
prefers 129. So I measured on the real corpus. Each file holds 16 frames of the
same machine in the same state; averaging the 16 power spectra cuts the
exponential bin-power variance 16-fold, and median-filtering that average with a
31-bin window gives a much lower-variance reference floor than any single frame
can. Scoring single-frame estimators against it, all 20 files × 3 channels ×
4 frames:

| width | median \|err\| | p95 \|err\| |
|---|---|---|
| 17 | 1.522 dB | 4.694 dB |
| 31 | 1.097 dB | 3.185 dB |
| **45** | **1.039 dB** | 3.074 dB |
| 65 | 1.085 dB | 3.354 dB |
| 91 | 1.181 dB | 3.856 dB |
| 129 | 1.326 dB | 4.553 dB |
| 257 | 1.705 dB | 6.572 dB |

A broad flat basin from 31 to 65. 45 is the minimum; 65 costs 0.05 dB against
it, far below the 1.0 dB noise of the estimate itself. Above 91 the median
smears real floor structure — this machinery's floor genuinely changes over tens
of bins. I kept 65 because it is inside the basin and it is the value the review
discussed; 45 would be defensible and no better in practice.

**4. `ln 2` and the segment count.** `nperseg == blocksize`, so there is exactly
one Welch segment in every shipped preset and `ln 2` is exact. It is still
derived rather than assumed (`median_to_mean_ratio(n)` = Gamma(n) median / n;
0.693, 0.839, 0.913, 0.956, 0.978 for 1/2/4/8/16 segments). At 16 segments the
error would be 1.5 dB, one-sided, in the direction that admits noise.

## Confirmed from the brief

* `wlen` is mandatory with `prominence`. A single broad hump spanning the band
  has unbounded prominence 34.6 and `wlen=41` prominence 0.032 — unbounded, the
  apex looks like the most prominent thing in the spectrum. `wlen` is
  `max(41, 4*distance+1)` so flat-top's `distance=11` still gets 45.
* `distance` from the window's measured first null: boxcar ±1, hann/hamming/
  bartlett ±2, blackmanharris ±4, flattop ±5 (re-measured in the test suite, not
  copied). Two boxcar tones 3 bins apart are merged into one by `distance=5` and
  correctly reported as two by `distance=3`.
* The −40 dB absolute gate earns its place; without it, highpass roll-off residue
  on a near-zero floor ranks near the top.
* `width=` and `threshold=` were re-tested and are not used.

## The default threshold

9.5 dB is defended by a false-alarm cliff, not by taste. On pure noise
(2001 bins, no lines at all) the reported count is:

| threshold | mean false alarms |
|---|---|
| 6.0 dB | 37.9 |
| 9.5 dB | 0.8 |
| 12.0 dB | 0.0 |

A 6 dB gate would fill a third of the table with noise. 9.5 dB is just past the
knee.

## Where this is still guessing

* **Nobody has labelled these spectra.** "44 peaks pass" is not "44 peaks
  matter". The gate is calibrated against *noise*, which is measurable, not
  against *diagnostic relevance*, which is not. Every claim above is of the form
  "this line does / does not stand out of its own neighbourhood".
* **`k_p = 2/3 · k_h` is a ratio I chose** so that the recommended (3×, 2×) pair
  falls out at the default and scales with the knob. It was not independently
  optimised; nothing was measured that separates, say, 0.6 from 0.7.
* **Broad features are rejected on purpose, and that is a real cost.** With
  `wlen=41`, a 40-bin-σ hump's apex has prominence 7 against a requirement of
  144 and never reaches the table. That is right for a line table and wrong if
  you want broadband resonances flagged; they remain visible in the plot only.
  A test asserts this so the behaviour cannot drift silently.
* **Dense line families lift the floor ~1–2 dB.** Lines every 22 bins (the
  corpus's median gap) lift it +0.84 dB median / +1.80 dB p95; every 11 bins,
  +2.12 / +3.39. The bias is upward, so the gate turns *conservative* inside a
  dense harmonic family rather than credulous — but a genuine line buried in one
  is harder to admit than the same line in open band.
* **The corpus is one site, one machine class, all `F_max` 2000 / `df` 1 / hann,
  all mV.** The width and threshold constants are tuned on that. The floor width
  is in bins, which is the right unit (a window's main lobe is a fixed number of
  bins regardless of `df`), but nothing here has been checked against a different
  `F_max`/`df` preset on real hardware.
* **The 16-frame reference floor used for width tuning is not ground truth**, it
  is a lower-variance estimate that shares the estimator's own median-filter
  assumptions. It cannot detect a bias common to both.
