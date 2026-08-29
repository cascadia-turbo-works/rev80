# Branch notes — `feature/envelope-analysis`

Envelope / demodulation analysis. The audit's only "blocks stated purpose"
finding. Fold into `doc/CHANGELOG.md` on merge.

**Status:** complete. Suite **715 passed**, ruff clean. Every design choice
revert-checked.

---

## Why

For rolling-element bearings this is *the* diagnostic, and it was absent
entirely. A defect does not produce a line at the defect rate. Each rolling
element strike produces an impulse; the impulse rings a structural resonance of
the housing, typically 2-20 kHz, far above anything the machine does
mechanically. In the raw spectrum that energy is smeared across the resonance
and sits underneath the 1x and its harmonics, which are orders of magnitude
larger.

What carries the diagnosis is not where the energy is but how it is
*modulated*: the impulses repeat at the defect rate, so the resonance's
amplitude envelope carries a clean line there, with +/-1x sidebands from the
load zone. That shows a fault months before the broadband overall moves.

Every instrument in this class ships it -- CSI PeakVue, SKF gE, B&K envelope.

## Added

- `src/rev80/envelope.py`
  - `envelope_spectrum(x, fs, band, env_fmax)` — band-pass, Hilbert magnitude,
    DC removal, Hann-windowed amplitude spectrum with coherent-gain correction.
  - `suggest_band(x, fs, fmax)` — proposes a demodulation band from the frame.
  - Kept a pure function of `(signal, fs, band)` so it is fully testable
    without dearpygui. That is the lesson of audit H-01, where front-end logic
    living in the GUI diverged from its headless copy in four ways.
- GUI: an **Envelope** plot tab beside Spectrum and Trend, with band lo/hi
  fields, an **Auto** button, and an info line stating the band in use and
  whether it was auto-selected.
- `tests/test_envelope.py` — 14 tests.

## Decisions

**The band-pass is the load-bearing step, not the Hilbert transform.**
Demodulating the full-band signal just recovers the dominant low-frequency
content again — the 1x, which is exactly what this is trying to escape. A test
asserts that a 20x-larger 60 Hz tone outside the band does not reach the
envelope spectrum, and removing the band-pass fails it.

**Zero-phase band-pass.** Group delay would shift the envelope in time relative
to everything else on screen. Unlike the acquisition high-pass, this runs on a
whole stored record rather than across streaming block boundaries, so there is
no state to carry and no edge transient to propagate — the objection that made
the acquisition high-pass causal does not apply here.

**DC removal is mandatory.** The envelope is strictly positive, so its mean is
a large DC term that otherwise dominates bin 0 and leaks across the low end
where the defect harmonics live.

**Auto-band searches only above a quarter of the usable band.** Below that is
machine content, and a band centred there would be worse than useless. It also
smooths over the candidate bandwidth before taking the argmax, so the choice is
driven by where the *band* energy is rather than by a single tall line: a lone
harmonic is not a resonance. Letting it search the whole band fails the test
that it finds the resonance.

**Auto writes its numbers into the fields.** The analyst can see what was
chosen and adjust it, and the band then stays put across frames instead of
silently drifting on every new one.

**`fmax` defaults to the declared band's upper edge**, so a suggested band
never reaches into the anti-alias guard region where the response is not a
measurement. This is a direct dependency on `fix/declared-band`.

## Verified

Against the oracle from `test/bearing-oracle`, with a healthy negative control
on every positive claim — an envelope analyser that returns a line for
everything is worse than none.

- **Analytic case.** A carrier at 2000 Hz modulated at 37 Hz gives an envelope
  line at 37 Hz at >20x the floor, and *no* line at the carrier. Line amplitude
  tracks modulation depth: 0.2 -> 0.8 gives a 4.0x rise (predicted 4.0).
- **Faulted vs healthy**, 4 seeds each: the BPFO line is >8x the floor when
  faulted and <4x when healthy.
- **The feature earns its place.** The BPFO line's SNR in the envelope spectrum
  is more than 3x its SNR in the raw spectrum — asserted directly, so if the
  raw spectrum ever showed it just as well this machinery would fail its own
  test.
- **Load-zone sidebands** at BPFO +/- 1x both clear 3x the floor.
- **Monotone in severity** across 0.25 / 0.5 / 1.0 for every seed.
- **Auto-band** brackets the true 4000 Hz resonance on every seed, and finding
  BPFO still works when the band came from `suggest_band` rather than from
  being told the answer.

End to end through `DataCollector.process_sample` on a severity-1.0 waveform:
auto band **2546-5046 Hz** (resonance at 4000), BPFO expected 325.8 Hz found at
**324.0 Hz** — within one bin at df=2 — at **125x SNR**, with the 1x at 60 Hz
and the lower sideband at 264 Hz as the next lines down. Crest factor 4.39,
kurtosis 4.95 on the same frame.

## Deliberately NOT done

- **No envelope trending or alarming.** The envelope line's amplitude at a
  known defect rate is the obvious thing to trend, but it needs a defect-rate
  input — bearing geometry or a tachometer — which is R6/R24 territory.
- **No band persistence.** The demodulation band is a live view setting, not
  part of the measurement, so it is not written into the `.h5`. If envelope
  results ever get trended that changes, because then the band becomes part of
  what produced the number.
- **The band edges are not drawn on the spectrum plot.** They should be; the
  analyst currently has to read them off the info line. Left with the same
  gap for the declared measurement band, which has the same problem.
- **Fifth plot in a fixed layout.** This lands as a third tab rather than a
  visible panel, which is the pragmatic choice today but strengthens the case
  for R33 (dockable / switchable panels).
