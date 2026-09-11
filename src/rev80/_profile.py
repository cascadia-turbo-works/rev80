"""Stage timing for the acquisition → processing → display pipeline.

Why this exists
---------------
The GUI stuttered on every processing call, worse with every enabled channel,
and the symptom could not distinguish between the three things that turned out
to be causing it: a 512821-tap FIR redesigned per channel per frame on the main
thread, a per-sample Python loop in the vendor ADC conversion holding the GIL
on the hardware thread, and ~164 dearpygui widget create/destroy calls per
channel per frame. All three are linear in channel count, so no amount of
staring at the frame rate separates them. Only per-stage timing does.

Two design constraints, both learned the hard way in this codebase:

* **Near-zero cost when off.** Every call site here sits inside the render loop
  or a driver callback. `timed()` checks one module-level flag and returns a
  shared no-op before it touches a clock. Measured on this machine, net of the
  empty-loop baseline (56.3 ns):

      timed() disabled   442 ns/call
      timed() enabled   3015 ns/call

  At the busiest call site -- `usb.adc2mv`, ~77 driver callbacks/s x 8 channels
  = 616 calls/s -- that is **0.27 ms per wall-second disabled** and 1.9 ms/s
  enabled. Both are far below the resolution of anything being measured, so
  these stay in the shipped code permanently rather than being compiled out.
* **Bounded by construction.** Audit S-02 was an unbounded buffer that became
  an OOM kill: SIGKILL, no traceback, nothing in the log. A diagnostic that
  crashes the app it is diagnosing is worse than no diagnostic, so every stage
  keeps a fixed-length deque and nothing here ever grows without limit.

Usage::

    from rev80 import _profile

    with _profile.timed(_profile.PROC_TOTAL):
        ...

    _profile.enable()
    print(_profile.report())

The stage names are constants rather than free strings so the stream, the
collector and the GUI cannot drift into naming the same stage two ways.
"""

import threading
import time
from collections import deque
from contextlib import contextmanager

__all__ = [
    'enable', 'disable', 'is_enabled', 'reset',
    'timed', 'record', 'snapshot', 'report', 'STAGES',
]

# ---------------------------------------------------------------------------
# Stage names
# ---------------------------------------------------------------------------
# Grouped by thread, because which thread a cost lands on is the whole point:
# main-thread time blocks the mouse, hardware-thread time steals the GIL, and
# the two need completely different fixes.

# Hardware / acquisition thread
USB_POLL      = 'usb.poll'          # ps4000aGetStreamingLatestValues round trip
USB_ADC2MV    = 'usb.adc2mv'        # ADC counts → mV, inside the driver callback
USB_ANTIALIAS = 'usb.antialias'     # Kaiser FIR + decimate to raw_samplerate
INGEST_RECV   = 'ingest.receive'    # DataCollector.receive_data (filter, tach, cache)

# Main / render thread
PROC_TOTAL    = 'proc.total'        # DataCollector.process_samples, all channels
PROC_DECIMATE = 'proc.decimate'     # raw rate → display rate resample
PROC_PSD      = 'proc.psd'          # Welch + the five integration orders
PROC_PEAKS    = 'proc.peaks'        # significance-based peak selection
GUI_DISPLAY   = 'gui.display'       # _display_frame, everything in it
GUI_PEAKS_TBL = 'gui.peaks_table'   # per-channel peaks table refresh
GUI_ENVELOPE  = 'gui.envelope'      # band-pass + Hilbert + envelope spectrum
GUI_RENDER    = 'gui.render'        # dpg.render_dearpygui_frame()
GUI_FRAME     = 'gui.frame'         # whole render-loop body — the true frame period

#: Declaration order is report order: acquisition first, then processing, then
#: display, so a read of the table follows the data.
STAGES = (
    USB_POLL, USB_ADC2MV, USB_ANTIALIAS, INGEST_RECV,
    PROC_TOTAL, PROC_DECIMATE, PROC_PSD, PROC_PEAKS,
    GUI_DISPLAY, GUI_PEAKS_TBL, GUI_ENVELOPE, GUI_RENDER, GUI_FRAME,
)

#: Samples retained per stage for the percentile estimate. 2048 at the default
#: 2 frames/s is ~17 minutes of frame-rate stages and a few seconds of the
#: ~77 Hz driver-callback stages — long enough for a p95 to mean something,
#: short enough that the whole table is well under a megabyte.
RING = 2048


class _Stage:
    """Running statistics for one pipeline stage.

    Keeps both a bounded ring (for percentiles) and unbounded scalar
    accumulators (for the true count/sum/max, which the ring would otherwise
    lose as it rolls). The scalars are three floats, so "unbounded" here costs
    nothing.
    """

    __slots__ = ('samples', 'n', 'total', 'peak', 'first_t', 'last_t')

    def __init__(self):
        self.samples: deque = deque(maxlen=RING)
        self.n       = 0
        self.total   = 0.0
        self.peak    = 0.0
        self.first_t: float | None = None
        self.last_t:  float | None = None

    def add(self, seconds: float, now: float) -> None:
        self.samples.append(seconds)
        self.n     += 1
        self.total += seconds
        if seconds > self.peak:
            self.peak = seconds
        if self.first_t is None:
            self.first_t = now
        self.last_t = now

    def stats(self) -> dict:
        if not self.n:
            return {'n': 0, 'mean_ms': 0.0, 'p95_ms': 0.0, 'max_ms': 0.0, 'per_s': 0.0}
        ordered = sorted(self.samples)
        # Nearest-rank p95 on the retained window. Deliberately not numpy: this
        # module is imported by the driver callback path and must not pull a
        # heavyweight import in for a percentile of at most RING floats.
        idx = min(len(ordered) - 1, int(0.95 * len(ordered)))
        span = (self.last_t - self.first_t) if (self.first_t is not None
                                                and self.last_t is not None) else 0.0
        return {
            'n':       self.n,
            'mean_ms': (self.total / self.n) * 1e3,
            'p95_ms':  ordered[idx] * 1e3,
            'max_ms':  self.peak * 1e3,
            'per_s':   (self.n / span) if span > 0 else 0.0,
        }


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

#: Read on every timed() call. A plain bool rather than a property or an
#: object attribute so the disabled path is a single LOAD_GLOBAL + POP_JUMP.
ENABLED = False

_lock   = threading.Lock()
_stages: dict[str, _Stage] = {}


class _NullTimer:
    """Shared no-op returned by timed() when profiling is off."""

    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NULL = _NullTimer()


def enable() -> None:
    """Start collecting. Safe to call more than once."""
    global ENABLED
    ENABLED = True


def disable() -> None:
    global ENABLED
    ENABLED = False


def is_enabled() -> bool:
    return ENABLED


def reset() -> None:
    """Discard all collected samples, keeping the enabled state.

    Used by the sweep harness between channel counts so one run's warm-up does
    not contaminate the next one's percentiles.
    """
    with _lock:
        _stages.clear()


def record(stage: str, seconds: float) -> None:
    """Record one duration against `stage`. No-op when disabled."""
    if not ENABLED:
        return
    now = time.perf_counter()
    with _lock:
        st = _stages.get(stage)
        if st is None:
            st = _stages[stage] = _Stage()
        st.add(seconds, now)


@contextmanager
def _timing(stage: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        # In the finally block so a stage that raises is still counted. A stage
        # that only fails fast would otherwise look free.
        record(stage, time.perf_counter() - t0)


def timed(stage: str):
    """Context manager timing the enclosed block against `stage`.

    Returns a shared no-op object when profiling is off — no generator is
    created and no clock is read, which is what makes it safe to leave in the
    render loop and the driver callback permanently.
    """
    if not ENABLED:
        return _NULL
    return _timing(stage)


def snapshot() -> dict:
    """Per-stage statistics, in STAGES order then any unknown stages.

    Shaped like MonitorController.status_snapshot(): a plain dict of plain
    scalars, so a caller can log it, print it, or assert on it without
    knowing anything about this module's internals.
    """
    with _lock:
        known   = [s for s in STAGES if s in _stages]
        unknown = sorted(s for s in _stages if s not in STAGES)
        return {s: _stages[s].stats() for s in known + unknown}


def report(title: str = 'pipeline profile') -> str:
    """The stage table, as a block of text for a log or a terminal."""
    snap = snapshot()
    if not snap:
        return f'{title}: no samples (profiling disabled or never ran)'
    head = (f'{"stage":<16} {"n":>7} {"mean ms":>9} {"p95 ms":>9} '
            f'{"max ms":>9} {"calls/s":>8} {"ms/s":>8}')
    lines = [title, head, '-' * len(head)]
    for stage, st in snap.items():
        # ms/s -- the stage's share of a wall-clock second. This is the column
        # that ranks causes: a 74 ms stage at 2/s and a 1 ms stage at 77/s are
        # both real, and mean alone hides the second one entirely.
        load = st['mean_ms'] * st['per_s']
        lines.append(f'{stage:<16} {st["n"]:>7d} {st["mean_ms"]:>9.3f} '
                     f'{st["p95_ms"]:>9.3f} {st["max_ms"]:>9.3f} '
                     f'{st["per_s"]:>8.1f} {load:>8.1f}')
    return '\n'.join(lines)
