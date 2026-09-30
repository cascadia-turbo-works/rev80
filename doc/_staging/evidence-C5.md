<!-- Staging text from package W1-C5 (monitor/*.py, headless.py, config.py,
     sensor.py). W2-A moves each section under its E heading in
     CONTRIBUTING.md and deletes doc/_staging/. The tables are copied from the
     docstrings at 2e22023. The numbers are not changed. -->

### E16. Anomaly thresholds (part from `monitor/anomaly.py`)

<!-- W2-A: merge with the E16.2 text in evidence-C4.md. -->

#### E16.1. RMS threshold 50 %

**Decision.** `RmsThresholdHook(rms_threshold_pct=50.0)`. The same default is
in `config._BUILTIN_ACQ['monitor']['anomaly']['rms_pct']`, in
`headless._build_anomaly_hook` and in `gui._build_anomaly_hook`.

**Why.** For a rigid rotor below its first critical speed, the 1x velocity
changes as omega cubed. The shaft-speed change alone moves the overall:

| Shaft-speed change | 1x velocity change |
|---|---|
| 0.5 % | +1.5 % |
| 1.0 % | +3.0 % |
| 2.0 % | +6.1 % |
| 3.2 % | +10.0 % (the threshold before it became 50 %) |
| 5.0 % | +15.8 % |
| 10.0 % | +33.1 % |

**Measured on:** not measured. The table is the calculation
(1 + d)^3 - 1. It was checked again for this revision: 1.032^3 = 1.0991.

- A slip change of about 2 % between no load and full load on an induction
  motor gives +6 % with no change in condition.
- On a VFD or a load-following machine, a 10 % threshold measures load, not
  condition.
- 50 % is a level at which a broadband RMS rise means something without a
  speed reference. With a tachometer, the speed gate (E20) removes the
  off-speed frames, and a site can set a lower threshold.
- Without a tachometer, detection must come from envelope analysis or from
  fixed limits (`FixedThresholdHook`).

**Operator note (for README).** An `acquisition.yaml` seeded before the
change can still hold `rms_pct: 10.0`. The file value wins.

**EWMA constants.** `baseline_alpha` 0.97 (RMS) is a time constant of about
33 frames (half-life about 23 frames). `baseline_alpha` 0.995 (spectral) is a
time constant of about 200 frames (half-life about 138 frames). The earlier
docstrings called these values half-lives; that was not correct.
`ewma_alpha_from_time(tau, dt)` returns exp(-dt / tau); at tau = 30 s and
dt = 1 s it is 0.967.

### E17. Burst memory

**Decision.** `MonitorController.burst_frame_cap(max_burst_s,
acquisition_period)` = int(max_burst_s / acquisition_period) + 1, minimum
`MIN_BURST_FRAMES` = 4. `_handle_burst_frame` trims `_burst_frames` and
`_burst_all_results` together, because `_flush_burst` reads them by the same
index.

**Why.** A burst keeps every frame and every `ChannelResult` in memory until
the flush at its end. Without a cap an unattended burst grows until the OOM
killer stops the process: SIGKILL, no traceback, no log line.

**Measured on:** 4 channels through the real pipeline at
`RAW_SAMPLERATE_HZ` = 25600 Hz. The byte count is the deep ndarray size
reachable from one retained frame and its `ChannelResult`s. The source did
not record whether the stream was hardware or `SimulatedSensor`, or the
date. The same table is in the CHANGELOG `fix/stability-cluster` entry.

| binsize | frame period | raw block | retained | multiple |
|---|---|---|---|---|
| 0.5 Hz | 2.000 s | 1.638 MB | 4.517 MB | 2.76x |
| 1.0 Hz | 1.000 s | 0.819 MB | 2.259 MB | 2.76x |
| 2.0 Hz | 0.500 s | 0.410 MB | 1.130 MB | 2.76x |

- The multiple does not change, because a retained frame is the raw-rate
  block plus its derived views.
- Growth is 2.26 MB/s on 4 channels (about 8.1 GB/h), independent of F_max
  and binsize. Stored frames are raw-rate, so a lower F_max does not reduce
  it.
- At the default `max_burst_s` of 600 s the cap limits one burst to about
  1.36 GB.

**Open defect (found in this revision, not fixed).**
`MonitorController._start_burst` passes
`self._session.acquisition_period`, but `MonitorSession` has no such field.
The value is therefore 0.0, and the cap is `MIN_BURST_FRAMES` (4 frames). An
anomaly burst keeps only its last 4 frames; the pre-trigger frames are
dropped at the first burst frame. Reproduced with a real `MonitorSession`
(pre_buffer_frames 30, cache 31 frames): 30 frames after the trigger, 4
frames after the first burst frame. `tests/test_bounded_resources.py` sets
`_max_burst_frames` by hand and does not test this wiring. The manual path
(`trigger_burst`) does not set `_max_burst_frames` at all.

### E20. Speed gate (part from `monitor/anomaly.py`)

<!-- W2-A: merge with the E20 text from sample.py in evidence-C1.md. -->

**Where it is applied.** `DataCollector.speed_ok()` evaluates the gate and
sets `ChannelResult.speed_ok`. `monitor.anomaly.valid_results()` applies it,
with the `overflow` and `degraded` flags, and it is the only place that does.
Every hook (`RmsThresholdHook`, `SpectralThresholdHook`,
`FixedThresholdHook`, `CompositeAnomalyHook`) calls it in `on_results`, and
the two EWMA hooks also call it in `update_baseline`.

**Rejected alternative.** A speed-gate parameter on each hook. That needs a
change in `_build_anomaly_hook`, which is still copied in `gui.py` and
`headless.py`, and two copies of one rule drift.

**Why flagged frames are also kept out of the baseline.** One bad frame in
an EWMA baseline with alpha 0.97 affects the reference for about 33 frames
(the time constant), in the same way that an alarm on it is false now.
