# Rev80 — GUI responsiveness: profiling harness, then the three fixes it justifies

Branch: `experimental/profiling` off `develop`.

## Context

Since the mandatory Kaiser anti-alias filter and oversampled streaming landed
(`effective_osr = 3`, ADC driven at ~76.8 kHz/channel against a 25.6 kHz
`RAW_SAMPLERATE_HZ`), the GUI stutters: mouse movement and button interaction
freeze briefly on every pipeline processing call. Bearable at 3 enabled
channels, progressively worse to 8, on the 4824A attached to this machine.

The bottleneck was unknown, so the ask was to profile and study before fixing.
That study is done and is summarised below — three independent causes, each
**linear in channel count**, which is why the symptom alone could not
discriminate between them. All three numbers below were measured in this
session on this machine.

This is also **not a throughput problem**, which matches the observation that
processing never gets ahead of acquisition and the queue never bogs down. The
ring cache is designed to skip to the latest frame, so a main-thread overrun
shows up as latency and jank, never as a backlog. That is precisely why looking
at queue depth found nothing.

The constraint on everything below: **the numbers this app displays are the
product.** Every fix here is either provably bit-identical or ships with an
equality test, and the harness produces the before/after table.

---

## What the profiling found

### Cause 1 — `decimate_to_rate` designs a 512,821-tap FIR, every call, on hardware only

**73.6 ms per channel per frame.** `_start_streaming` (`picoscope.py:699`)
requests the streaming interval in **microseconds** and *truncates*:
`int(1e6 / 76800) = 13 µs`. The driver therefore runs at 76 923 Hz, and
`_report_samplerate` correctly reports `76923 / 3 = 25641.0` Hz.

`Fraction(5120, 25641)` is coprime, so `collector.decimate_to_rate`
(`collector.py:26`) calls `resample_poly(up=5120, down=25641)`, and scipy
designs a `2*10*max(up,down)+1` = **512 821-tap** filter on every single call.
Verified:

| raw rate | up / down | taps | ms/call | out length |
|---|---|---|---|---|
| 25600.00 (simulated) | 1 / 5 | 101 | **0.64** | 2560 |
| 25641.00 (real hardware) | 5120 / 25641 | 512 821 | **73.62** | **2556** |

Two consequences, both important:

- It is a **115× cost multiplier that only exists on real hardware.**
  `SimulatedSensor` reports exactly 25600, so CI, every offline test, and my
  own first benchmark all measured 0.64 ms and saw nothing. This is the
  "green CI is not evidence" pattern again, in the performance domain.
- The 2556-vs-2560 output silently trips scipy's `nperseg > input length`
  fallback in Welch, so the delivered bin width and line count differ from
  what the Spectrum tab advertises. That is a **measurement** defect, not just
  a speed one.

At 3 channels this is a 221 ms main-thread block twice a second — "noticeable
but bearable". At 8 channels it is 589 ms against a 500 ms frame period.

### Cause 2 — `picosdk.functions.adc2mV` is a per-sample Python loop holding the GIL

**200–380× slower than the vectorized equivalent**, run inside the driver
callback (`picoscope.py:856`, called synchronously from
`ps4000aGetStreamingLatestValues`). The vendor helper is literally:

```python
bufferV = [(np.int64(x) * vRange) / maxADC.value for x in bufferADC]
```

| chunk (samples/ch) | `adc2mV` + `np.array` | vectorized | speedup |
|---|---|---|---|
| 4 096  |  4.22 ms | 0.021 ms | 201× |
| 19 200 | 19.86 ms | 0.052 ms | 382× |
| 38 400 | 40.28 ms | 0.112 ms | 361× |

≈1.03 µs/sample × 76 923 Hz × N channels:

| channels | 1 | 3 | 4 | 8 |
|---|---|---|---|---|
| CPU-seconds per wall-second | 0.079 | 0.238 | 0.317 | **0.634** |

Measured effect on a 60 Hz-style main loop while a background thread does this
work at the real callback cadence (p95 tick latency against a 0.5 ms target):

| channels | 1 | 3 | 4 | 8 |
|---|---|---|---|---|
| `adc2mV` | 1.42 ms | 4.67 ms | 5.75 ms | **5.76 ms** |
| vectorized | 0.58 ms | 0.59 ms | 0.59 ms | **0.59 ms** |

The replacement is **bit-identical** — verified `np.array_equal` → True, max
diff 0.0, over voltage-range indices 0/5/7/9/13 on random int16 — provided the
operation order is preserved (multiply by `vRange`, *then* divide by `maxADC`;
not a pre-divided scale factor).

This also explains a past workaround: `doc/CHANGELOG.md:503` records
`RAW_SAMPLERATE_HZ` being lowered "to relieve GUI lag while streaming 4
channels". Lowering the rate reduced the sample count through this loop. Once
this is fixed, that trade may be reclaimable.

### Cause 3 — the peaks table is destroyed and rebuilt every frame, per channel

`_update_fft_peaks_table` (`gui.py:417-432`) is called once per vibration
channel per frame from both branches of `_update_freq_plot` (`gui.py:590`,
`gui.py:596`) — so it runs even with zero peaks. Each call does
`delete_item` on every existing child, then re-adds 2 columns and one
`table_row` + 2 `add_text` per row. `select_peaks`' own docstring puts the
corpus median at 40 peaks, against a display cap of 50.

At 40 rows that is **~164 widget create/destroy operations per channel per
frame**, plus a full DPG table layout pass:

| channels | peaks-table ops | other per-ch DPG calls | total |
|---|---|---|---|
| 1 | ~164 | ~30 | ~225 |
| 4 | ~656 | ~120 | ~810 |
| 8 | ~1 312 | ~240 | ~1 585 |

Roughly 80 % of all per-frame DPG traffic, strictly linear in channel count.
Every plot *series* is correctly `set_value` on a pre-existing item; this table
is the only per-frame widget churn.

### Smaller, confirmed, worth taking while we are here

- `peaks._running_median` (`peaks.py:184`) — 1.24 ms/channel/frame, ~10 ms at
  8 ch. The `scipy.ndimage.median_filter` pass is the real cost; the Python
  edge loop then **discards 64 values that pass already computed**.
- `_schedule_status_timeout` (`gui.py:287`) constructs a new `threading.Timer`
  — an OS thread — on **every frame** while streaming (`gui.py:1099`).
- `_update_envelope_plot` (`gui.py:495`) is gated on `config.envelope_enabled`
  but **not** on the Envelope tab being the selected tab, despite its docstring
  claiming exactly that. With envelope on and the user on the Spectrum tab, the
  full `butter` design + `sosfiltfilt` + `hilbert` + `suggest_band` convolve
  chain (~2.8 ms/ch, plus 1.4–1.9 ms when the band is auto) runs for a plot
  nobody can see. `suggest_band` is also recomputed every frame.
- `_update_frame_info` (`gui.py:1024`) sets a container `height=` every frame,
  forcing a DPG relayout; `_update_browse_label` does 4 `configure_item(enabled=)`
  per frame. Constant cost, but free to fix.
- No display downsampling anywhere: at the 10 kHz / 0.25 Hz preset the GUI
  boxes ~740 000 Python floats per frame via `.tolist()`. Not today's problem
  at the default preset (~50 000 at 8 ch) — noted, not fixed here.

---

## Plan

### Step 1 — Branch and the timing primitive

`git checkout -b experimental/profiling` off `develop`.

New `src/rev80/_profile.py` (~130 lines) — the one place timing lives. There is
currently **no** `perf_counter`, `timeit` or `cProfile` anywhere in `src/`,
`tests/` or `scripts/`, so this is new ground, not a second system.

- Stage name constants, so stream, collector and GUI all name stages identically.
- `@contextmanager timed(stage)` + `record(stage, seconds)`. **Zero cost when
  off**: a module-level `ENABLED` flag checked first, returning a shared no-op
  singleton without touching the clock.
- Per-stage `collections.deque(maxlen=...)` plus running count/sum/max, behind
  one `threading.Lock` taken only when enabled. Fixed size by construction —
  profiling must not become the next S-02.
- `snapshot()` → `{stage: (n, mean_ms, p95_ms, max_ms, calls_per_s)}` and
  `report()` → a formatted table.

Follow the two established conventions rather than inventing new ones:
`MonitorController.status_snapshot()` (`monitor/controller.py:284`) for the
stats-dict shape, and `logger.format_resource_snapshot()` (`logger.py:165`) for
the rate-limited `log.info` line format (it already takes `**extra` kwargs).

Enabled by `rev80 --profile` and `REV80_PROFILE=1`, wired in `__main__.py`
beside the existing `--debug` flag. Note `logging.yaml` already routes DEBUG to
`log/debug.log` unconditionally, so the report needs no new handler.

### Step 2 — Instrument the stage boundaries

Wrap, changing no logic:

| Stage | Where | Thread |
|---|---|---|
| `usb.poll` | `ps4000aGetStreamingLatestValues`, `picoscope.py:973` | hw |
| `usb.adc2mv` | the per-channel conversion loop, `picoscope.py:844-858` | hw (driver cb) |
| `usb.antialias` | `antialias_decimate()`, `picoscope.py:888` | hw |
| `ingest.receive` | `receive_data`, `collector.py:698` | hw |
| `proc.total` | `process_samples`, `collector.py:1284` | main |
| `proc.decimate` | `_decimated_for`, `collector.py:776` | main |
| `proc.psd` | `_psd_and_overalls_for`, `collector.py:794` | main |
| `proc.peaks` | `select_peaks`, `peaks.py:293` | main |
| `gui.display` | `_display_frame`, `gui.py:1095` | main |
| `gui.peaks_table` | `_update_fft_peaks_table`, `gui.py:417` | main |
| `gui.envelope` | `_update_envelope_plot`, `gui.py:495` | main |
| `gui.render` | `dpg.render_dearpygui_frame()`, `gui.py:4859` | main |
| `gui.frame` | the whole loop body — true frame period / FPS | main |

`gui.render` next to `proc.total` is what makes the diagnosis unambiguous
going forward: a long `gui.render` with a short `proc.total` means the hardware
thread is stealing the GIL (Cause 2); the reverse means main-thread DSP
(Causes 1 and 3).

Report `effective_samplerate` and `.degraded` from the existing
`_check_rate_degradation` window (`picoscope.py:1007`) alongside the table
rather than adding a second rate estimator. `collector.py:158-159` already
declares `_last_frame_t` / `_lag_warn_t`, assigned in `__init__` and never read
anywhere — wire them up here or delete them.

### Step 3 — A repeatable harness

New `scripts/profile-pipeline`, executable, no `.py` extension, `sys.path`
insert of `src/` — a direct sibling of `scripts/validate-streaming-capacity`
and in its style:

```
scripts/profile-pipeline --channels 1,2,3,4,6,8 --seconds 30
                         [--simulated | --hardware] [--envelope] [--maxfreq 2000] [--cprofile]
```

- Sweeps channel counts, prints the per-stage table per count plus a ms/frame
  vs. channels summary.
- `--hardware` additionally prints `effective_samplerate`, `degraded` and
  overflow counts, so USB delivery is measured rather than assumed.
- `--cprofile` writes a `pstats` file per channel count for drill-down.
- Reuses the canonical streaming-loop shape already used by
  `tests/test_picoscope_hw.py:461` and `validate-streaming-capacity:99`.

**The harness must be able to force the simulated sensor to report a
hardware-realistic rate** (e.g. `--raw-rate 25641`). Cause 1 is invisible at
25600, and a harness that cannot reproduce the bug it was built for is worse
than none.

A `--profile` GUI run logs the same table on exit, from inside `cleanup()` —
in the existing guarded ordering, where it can never prevent `ps4000aCloseUnit`.

### Step 4 — The fixes

Each is its own compartmentalized commit carrying its before/after table.

**4a. Request the streaming interval in nanoseconds, and snap decimation to an
exact integer factor.**

- `picoscope.py:699-700`: request `PS4000A_NS` with
  `int(round(1e9 / raw_samplerate))` = 13 021 ns instead of `PS4000A_US` with
  `int(1e6 / raw_samplerate)` = 13 µs. True rate becomes 25 599.67 Hz — a
  **13 ppm** error against today's **1600 ppm**. This is a frequency-axis
  accuracy improvement in its own right, in the exact spirit of
  `_report_samplerate`'s existing docstring. The driver still writes back what
  it used and the code still reads it back, so this degrades gracefully if the
  hardware quantizes coarsely.
- `collector.decimate_to_rate` (`collector.py:26`): bound the rational
  approximation (`Fraction(...).limit_denominator(...)`) so the ratio is always
  a small integer factor. At 25 599.67 → 5120 that is exactly 1/5: 101 taps,
  0.64 ms, output length 2560, and the Welch `nperseg` mismatch disappears.
- The function **already returns the achieved rate**, and `_decimated_for`
  already stores it as `decimated_samplerate`, so the plumbing to report the
  truth exists. Audit that every downstream consumer uses that returned rate
  rather than `config.samplerate`.

**Keep the user-facing controls simple, as decided:** the F_max preset stays
`2000` in the config and in the Acquisition dialog. The 1999.97 Hz is internal —
used for the frequency axis and the derived bin width, where correctness
matters — and is never surfaced as a fiddly number. This is the same treatment
`highpass_fc` already gets: a *declared* edge, with the real value underneath.

New `tests/test_display_rate.py`: at a realistic hardware rate, assert the
decimation factor is integer, the output length equals `blocksize`, the FIR is
bounded (a direct regression test on the 512 821-tap explosion), and the
frequency axis is built from the achieved rate.

**4b. Vectorize the ADC→mV conversion** (`picoscope.py:844-858`). Replace
`adc2mV` with a local `_adc_to_mv()` doing
`chunk.astype(np.float64) * vRange / maxADC` **in that order**, with `vRange`
from a module-level tuple copied from picosdk's `channelInputRanges`. Keep the
existing import-guard shape so the no-SDK path still imports.

New `tests/test_adc_conversion.py`: assert bit-identity with
`picosdk.functions.adc2mV` across every voltage-range index and the int16
extremes including ±32767 and 0; skips when picosdk is unavailable. This is the
revert-check — it fails the moment someone "simplifies" the operation order to
a pre-divided scale factor.

**4c. Stop rebuilding the peaks table every frame** (`gui.py:417-432`). Create
the two columns once, keep a pool of row widgets sized to
`_DEFAULT_PEAK_DISPLAY_CAP`, `set_value` the two texts per row, and
`configure_item(show=...)` the surplus rows instead of deleting them. Also skip
the call entirely when the row contents are unchanged from last frame.

**4d. The small ones**, one commit: hoist the `threading.Timer` in
`_schedule_status_timeout` so it is re-armed rather than reconstructed per
frame; gate `_update_envelope_plot` on the Envelope tab actually being selected
(making its docstring true) and cache `suggest_band` until the band settings
change; drop the per-frame `height=` churn in `_update_frame_info` and
`_update_browse_label` to change-only.

**4e. Vectorize `peaks._running_median`'s edge handling** (`peaks.py:184`).
The truncated-window treatment and its measured error table stay exactly as
documented — only the Python loop goes, and it can reuse the values
`median_filter` already computed instead of discarding 64 of them. Guarded by a
test asserting **exact** equality with the current implementation on random
spectra: this is a measurement path and not one bin may move.

**Explicitly not doing**, because the data does not support it: adaptive
streaming rate by channel count, capping the channel enable count, or moving
`process_samples()` off the render thread. The first two trade away measurement
capability to work around a Python loop and a coprime fraction. The third is
invasive — it would change the `new_frame_event` contract that browse mode,
`collect_sample`, the monitor and the tests all depend on — and 4a alone removes
~589 ms of the ~610 ms main-thread budget at 8 channels. If the harness still
shows a hitch after 4a–4e, that gets its own branch and its own plan.

### Step 5 — Documentation, in the same change

- `doc/CHANGELOG.md` — an entry per fix with its measured before/after.
- `doc/PROGRESS.md` — the profiling harness as a standing tool, **plus a new
  requirement R47** (next free number):

  > **R47 | Sep 2026 | Settling indicator during filter/coupler stabilisation.**
  > The first frame of a stream reads conspicuously high — approximately 2× on
  > the overall — and is trended and alarmed on as though it were valid. Real
  > analysers display "acquiring"/"settling" and withhold the reading until the
  > chain has stabilised. Candidates to separate before fixing: the IEPE
  > coupler's own AC-coupling RC transient after `ps4000aRunStreaming` (real
  > electrical signal, which no digital filter can remove), the `resample_poly`
  > anti-alias FIR edge transient, and the first-block high-pass state — noting
  > `filter_block` already seeds from the block mean via `_seed_zi`
  > (`collector.py:429`), so that last one is the least likely of the three.
  > Measure the settling time rather than assuming it, then withhold or flag
  > frames inside it — and exclude them from the trend, the baseline and
  > anomaly evaluation the same way overflow/degraded frames already are.

- `CLAUDE.md` — a short *Profiling* subsection under "Working on this codebase"
  naming `scripts/profile-pipeline` and `rev80 --profile`, and stating the two
  rules this work establishes: a performance change to a measurement path ships
  with an equality test, and **a performance claim measured only against
  `SimulatedSensor` is not a measurement** — Cause 1 was invisible at 25600 Hz.
- `README.md` — update the §43 streaming-watchdog text and the
  `_report_samplerate` docstring for the ns-units change.
- A comment at `_adc_to_mv` recording the measured table and *why* the vendor
  helper is not used, or someone will "fix" it back.

---

## Verification

1. `scripts/profile-pipeline --simulated --raw-rate 25641 --channels 1,2,3,4,6,8
   --seconds 20` before and after each fix. The forced rate is what makes the
   offline run representative; the per-stage table is the evidence.
2. `scripts/profile-pipeline --hardware --channels 1,2,3,4,6,8` on the attached
   4824A (`0ce9:1202`, present on this machine), confirming
   `effective_samplerate` holds at the requested rate and `degraded` never sets
   — i.e. the speedup did not come from dropping samples.
3. **The acceptance criterion is subjective and has to be checked as such:** run
   the GUI at 8 channels on the 4824A and move the mouse and click buttons.
   `gui.frame` p95 should sit near the monitor frame period instead of spiking.
4. `pytest tests/` green, plus the three new tests.
5. `pytest tests/test_picoscope_hw.py` with the scope attached — the 9
   AWG-loopback tests are how a change touching acquisition gets closed out, and
   4a changes the sample clock, so this is mandatory rather than optional here.
6. Revert-check every fix: confirm `test_adc_conversion.py`, `test_display_rate.py`
   and the `_running_median` equality test each fail without their fix, and that
   `tests/test_antialias.py`, `tests/test_measurement_validity.py` and
   `tests/test_spectral_averaging.py` still pass untouched. **No displayed number
   may move except the frequency axis, which gets more accurate** — quantify that
   shift explicitly rather than asserting it is negligible.
7. `ruff check src/ tests/`.
