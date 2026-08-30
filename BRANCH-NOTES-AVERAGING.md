# Branch notes — `feature/spectral-averaging`

Linear power averaging of the spectrum over N frames, with an enable checkbox
and N in the acquisition dialog. Fold into `doc/CHANGELOG.md` on merge.

**Status:** complete. Suite **734 passed**, ruff clean. Four design decisions
revert-checked; one of them only after a check exposed that nothing pinned it.

---

## Why

Welch's method *is* linear power averaging — splitting a record into K
overlapping segments and averaging their periodograms is the same estimator as
averaging K per-frame spectra. But since the F-8 fix set `nperseg = blocksize`,
Welch runs exactly **one segment per frame**, so there was no averaging anywhere
in the chain and `welch_overlap` had nothing to act on.

Each bin of a single-segment estimate is χ²(2), with a standard deviation equal
to its own mean. That is why the noise floor looks rough, why a small line is
hard to pick out of it, and why the spectral anomaly hook fires on every healthy
frame (R39).

## The rule that ties live and replay together

> The average is the N most recent **valid** frames up to and including the
> frame being displayed.

Live that is the last N received; browsing it is `frames[cursor-N+1 … cursor]`.
One rule, so stepping forward through a loaded file reproduces exactly what the
live display showed at that moment — the same replay-fidelity property F-4
established for the high-pass.

**Nothing is baked into the file.** The HDF5 stores individual raw frames, so a
capture taken with averaging *off* can be given 16 averages after loading, and N
can be changed afterwards and recomputes. The averaging setting is a view on
stored data, not a property of it.

## Added

- `AcquisitionSettings.averaging_enabled` (default **off**), `.n_averages`
  (default 8), and `.n_averages_effective` — the request clamped to
  `cache_frames`, since you cannot average more frames than are retained.
- `ChannelResult.n_averages` — the count **actually achieved**.
- `DataCollector._psd_and_overalls_for()` / `._psd_for()` — the per-frame Welch
  PSD and 5-order overalls, extracted from `process_sample` so the averaging
  accumulator obtains them for earlier frames through exactly that code rather
  than a second copy. Two divergent copies of one path was the direct cause of
  M-05.
- `process_sample(..., history=...)`; `process_samples()` builds the slice.
- Acquisition dialog: "Average spectrum" checkbox, "Averages" spinner, and a
  derived **Avg. Window** field reading `N x 0.5 s = 8 s`, flagged when capped
  by the cache. N alone is hard to reason about; how long the machine must stay
  steady is the thing the analyst needs.
- A live "averaging 12 of 16 frames" line beside the peak count.
- `tests/test_spectral_averaging.py` — 19 tests.

## Decisions, each pinned by a test

**Power domain, never amplitude.** Average |X|², then sqrt at the very end. On
a coherent line the two are identical, which is precisely why this is easy to
get wrong and stay green: it shows up only on the noise floor. For complex
Gaussian noise the power is exponential with mean μ, so the magnitude is
Rayleigh with mean 0.886·√μ — averaging magnitudes converges about **11% low**
and drags every floor bin down. The overall combines the same way, as
`sqrt(mean(squares))`, because it is a power-like quantity too.

> This one is worth recording honestly: the first revert-check pass showed that
> replacing power averaging with amplitude averaging **passed all 17 tests**,
> despite the design note calling it "the one thing that must be right". Two
> tests were added that assert against *both* candidate answers, so the wrong
> one cannot pass.

**Above the per-frame cache, not inside it.** Each frame's `psd_mv` stays cached
exactly as computed; the average is a cheap sum over them. Changing N
invalidates no per-frame work and does not have to join `psd_key`.

**Overloaded records are rejected from the average**, including when the
overloaded record is the one being displayed. A clipped frame reads high with
harmonic distortion; averaging it into an estimate the analyst reads as clean is
the same mistake F-5 fixed for the trend. The waveform, the scalars and the
overflow flag still come from the displayed frame, so nothing is hidden — only
the spectral estimate is protected. This is analyzer practice: reject the
overloaded record, light the overload indicator.

**The reported count is the delivered count.** Early frames and rejected frames
both lower it, so the UI states what was achieved and only shows "of N" when
they differ. Claiming N while delivering fewer is the F-8 failure mode.

**Crest factor and kurtosis are NOT averaged.** Averaging is for steady-state
estimation; those two exist to catch the frame that is *not* steady, so diluting
one impulsive record across sixteen would defeat them entirely.

**Off by default.** It changes what the displayed number means and assumes the
machine is steady across the window.

## Measured

Pure noise plus a 0.30-amplitude line at 300 Hz, 64 frames, F_max 1000 / df 2:

| N | floor CV | 1/√N predicted | floor level | line amplitude |
|---|---|---|---|---|
|  1 | 0.5260 | 0.5260 | 0.03387 | 0.22366 |
|  4 | 0.2248 | 0.2630 | 0.03626 | 0.22183 |
| 16 | 0.1189 | 0.1315 | 0.03740 | 0.21965 |
| 64 | 0.0604 | 0.0657 | 0.03800 | 0.21878 |

Scatter tracks 1/√N (slightly better, since Welch's `detrend='linear'` removes
one more degree of freedom). The line is untouched at −2% across a 64× change.
The floor *level* rises 12% from N=1 to N=64 — that is not drift, it is the
Rayleigh-mean-to-RMS convergence the power-domain argument predicts, and it is
the clearest possible confirmation that the average is being taken correctly.

Timing: a frame is exactly `1/binsize` seconds, so at df=2 Hz sixteen averages
take **8 s** and a minute gives 120 — well past the point of diminishing
returns, since the benefit goes as √N.

## Deliberately NOT done

- **`welch_overlap` is still inert.** Averaging across frames does not overlap
  segments *within* a frame, so the control still has nothing to act on. Making
  it real means either a longer buffered record or overlapping consecutive
  frames, and would roughly double the available averages for the same wall
  time. Worth doing next if averaging proves useful.
- **No averaging on the monitor/recording path.** The monitor stores individual
  frames, which is what makes re-analysis possible; averaging is a display
  setting applied at render. Averaging a burst would be actively wrong.
- **No effect on R39.** The spectral hook reads `ChannelResult.spectrum` and so
  would inherit averaging automatically, which is the prerequisite that makes a
  σ-based band test viable — but the hook remains unwired and its rework is
  still R39's business.
