<!-- Staging text from package W1-C6 (gui.py, _profile.py, logger.py, _paths.py,
     scope_sensor*.py, desktop.py, icons.py, __main__.py, __init__.py).
     W2-A moves each section under its E heading in CONTRIBUTING.md and
     deletes doc/_staging/. The headings are the titles of plan section 6.2.
     "E11" and "E19" here are parts; merge them with the parts from W1-C1
     (E11) and W1-C4 (E19). -->

### E18. Profiler overhead

Source: the `_profile.py` module docstring at `2e22023`.

**Decision.** `_profile.timed()` stays in the shipped code, in the render
loop and in the driver callback. When profiling is off, it reads one
module-level flag and returns a shared no-op object. It does not create a
generator and does not read a clock. When profiling is on, each stage keeps
a ring of `RING` = 2048 samples (a `deque` with `maxlen`), so memory cannot
grow without limit.

**Measured on:** "this machine" (the development machine). The source does
not record the CPU, the Python version or the date. The CHANGELOG entry
`experimental/profiling (2026-09-11)` gives the same numbers. The values are
net of the empty-loop baseline (56.3 ns).

| Call | Time per call |
|---|---|
| `timed()`, profiling off | 442 ns |
| `timed()`, profiling on | 3015 ns |

At the busiest call site, `usb.adc2mv`: about 77 driver callbacks/s x 8
channels = 616 calls/s. That is 0.27 ms per wall-clock second with
profiling off, and 1.9 ms/s with profiling on (computed from the table).
The 77 callbacks/s rate is from the source text; the raw rate at the time
of the measurement is not recorded.

**Why a bounded ring.** An unbounded buffer in this app became an OOM kill
(SIGKILL: no traceback, nothing in the log). A diagnostic must not cause the
failure that it is there to find.

**Why per-stage timing exists.** Three causes of GUI stutter were each
linear in the channel count, so the frame rate alone could not separate
them: a 512821-tap FIR designed for each channel and frame on the main
thread (E7), a per-sample Python loop in the vendor ADC conversion on the
acquisition thread (E3), and about 164 widget operations for each channel
and frame in the peaks table (E19). The stages are grouped by thread:
main-thread time blocks the mouse; acquisition-thread time takes the GIL.

**Retention.** 2048 samples are about 17 min of a frame-rate stage at
2 frames/s, and about 27 s of a 77 Hz driver-callback stage (computed).

### E19. GUI render cost (part from gui.py)

Source: the docstrings and comments of `gui._update_fft_peaks_table`,
`gui._update_envelope_plot`, `gui._env_band_for` and
`gui._schedule_status_timeout` at `2e22023`, and the CHANGELOG entry
`experimental/profiling (2026-09-11)`.

**Peaks table: a widget pool, not a rebuild.** `_update_fft_peaks_table`
creates rows on demand, updates them with `set_value`, and hides surplus
rows. It does not delete and rebuild the table for each frame. A frame with
no change pushes nothing.

Cost of the rebuild, computed from the widget count (not timed):

| Item | Count |
|---|---|
| Lines per spectrum, corpus median (`select_peaks`) | 40 |
| Destroyed per channel per frame | 2 columns + 40 rows |
| Created per channel per frame | 2 columns + 40 rows + 80 texts |
| Total widget operations per channel per frame | about 164 |
| At 8 channels, per frame | about 1300 |
| Share of all per-frame dearpygui traffic | about 80 % |

The rebuild also ran from both branches of `_update_freq_plot`, so it ran
with zero peaks too. Measured on: a 4824A with 3 to 8 channels
(CHANGELOG 2026-09-11); the source does not give a time per call.

**Envelope chain: only when the plot is on screen.** With the Envelope tab
enabled but another tab selected, the chain (a `butter` design, a
`sosfiltfilt`, a Hilbert transform) cost about 2.8 ms per channel per frame,
plus 1.4 ms to 1.9 ms when the band is automatic (`suggest_band`). Source:
CHANGELOG 2026-09-11; the machine is not recorded. `_envelope_on_screen()`
queries the plot, not the tab, because an unselected tab shows its header
button and always reports visible. It fails open: on any error it returns
True, because a blank plot with no reason is worse than CPU time.

**Automatic demodulation band: cached per channel.** `suggest_band` runs a
full rFFT of the raw block and an `np.convolve`. The cache key is
(channel, sample rate). Editing the band fields, toggling the Envelope tab,
and the Auto button clear the cache. The cache also keeps the band, and so
the envelope axis, the same from frame to frame.

**Stale-frame watchdog: a deadline, not a timer thread.** The previous code
started a `threading.Timer` for each displayed frame and changed a
dearpygui widget from that thread. Now `_schedule_status_timeout` stores a
deadline (2 x `acquisition_period`) and `_poll_new_frames` checks it on the
render thread at each tick. Rule: no dearpygui call off the render thread.

**Peak display cap.** `_DEFAULT_PEAK_DISPLAY_CAP` = 50 limits the table and
the plot markers only; `rev80.peaks` selects the lines. Sized from the
corpus counts at the default threshold: median 40, p90 49, maximum 61 over
60 channel spectra (source: the comment beside the constant). The corpus
and its date are not recorded.

### E11. Display rate, block size and line count (part from gui.py)

Source: the comment in `gui._update_spectrum_info` at `2e22023`, and audit
finding M-11.

The spectrum, the peaks table and the left-panel label stop at F_max. The
band from F_max to fs/2 (1.28 x F_max) is the anti-alias guard band. Alias
rejection there is not a specification the instrument meets:

| Frequency | Alias rejection |
|---|---|
| The frequency that folds onto F_max | -21.8 dB |
| fs/2 | about 0 dB |

For this reason the left panel labels F_max, not fs/2 as an "AA"
frequency. Measured on: not recorded in the source (audit 2026-08; see
`doc/audit-202608.md`, M-11).
