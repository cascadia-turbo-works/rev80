# Branch notes — `feature/diagnostic-scalars`

Crest factor and kurtosis on every result. Fold into `doc/CHANGELOG.md` on merge.

**Status:** complete. Suite **701 passed**, ruff clean.

---

## Why

The audit listed these under capability gaps, calling their absence
"disproportionate to their cost": two scalars, a few lines each, computed on
data the pipeline already holds. A broadband overall averages impulsiveness
away completely, so an RMS-only instrument cannot see a bearing defect until it
is severe. Crest factor rises early in a defect's life and falls again once the
defect spalls; kurtosis above ~4 flags repetitive impacts directly.

They are validated against `test/bearing-oracle`'s physically realistic
generator. Against the old ten-cosines signal they could not have been
validated at all — that is the whole reason Phase 2 came first.

## Added

- `_dsp.crest_factor()`, `_dsp.kurtosis()`. Both verified equal to
  `scipy.stats` to machine precision, and both degrade gracefully on a
  constant record instead of dividing by zero.
- `ChannelResult.crest_factor` / `.kurtosis`.
- Trend accumulation: `crest_factor` and `kurtosis` arrays alongside `orders`.
- HDF5 `/trend/{ch}/crest_factor` and `/kurtosis`.
- Monitor writer `scalars_json`, on both the interval and burst paths.
- Result card line "Crest x.xx   Kurt x.xx", with a tooltip explaining how to
  read each and why they are read together.
- `tests/test_diagnostic_scalars.py` — 13 tests.

## Decisions

**Non-excess kurtosis.** Gaussian reads 3.0, not 0.0. This is what
condition-monitoring practice quotes — "kurtosis above 4" is the standard
impulsiveness flag — so returning excess kurtosis would silently shift every
threshold a user might set by 3.

**Computed on `time_data`, the trace being displayed.** Not on the raw block
and specifically *not* on the Hann-tapered array the overall uses: that taper is
an amplitude envelope, so a peak-based statistic taken from it is simply wrong.
Using the returned trace also means the scalars are band-limited exactly like
the overall, and describe the signal the analyst is actually looking at. A test
pins this equality directly.

**Beside `orders`, not inside it.** The trend's `orders` matrix is (M, 5) in mV
RMS and is unit-converted by `get_trend_for_display()`. These scalars are
dimensionless — they are not a sixth integration order, and putting them in that
matrix would have them silently scaled by sensitivity and unit conversion.

**NaN, not 0.0, for "not recorded."** Files written before these existed load
with NaN, which plots as a gap. Zero would read as a measured value of zero.

## Verified

- A pure sine reads crest 1.414 and kurtosis 1.50; Gaussian noise reads 3.0.
- Both are invariant to signal amplitude (0.05 to 250x) and to sensor
  sensitivity (1.0 vs 100.0 mV/EU) — they are ratios, and a scaling error
  anywhere in the chain would show up as a shift here.
- Against the oracle, over 6 matched seeds, severity 0 -> 1 raises kurtosis by
  more than 1.0 and crest factor monotonically, in the regime where the defect
  carries the same RMS as the shaft signal — i.e. exactly the case where the
  broadband overall barely moves. That is the claim these scalars exist to make.
- Monotone in severity across (0.0, 0.5, 1.0) for every seed tested.

## Deliberately NOT done

- **No trend plot for them.** They are accumulated and persisted, and the live
  values are on the card, but the trend plot's two y-axes are unit-based and
  these are dimensionless, so showing them needs a third axis or a separate
  plot. That is a layout decision that belongs with R33, not a drive-by.
- **No alarming on them.** `FixedThresholdHook` is unit-aware and would need a
  dimensionless mode. Kurtosis > 4 is the obvious first band alarm once R39
  settles what the anomaly surface should look like.
