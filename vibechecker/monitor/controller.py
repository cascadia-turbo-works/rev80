import time
from collections import deque
from datetime import datetime, timezone

import vibechecker
from vibechecker.monitor.anomaly import AnomalyEvent, AnomalyHook, NullAnomalyHook
from vibechecker.monitor.gate import IntervalGate
from vibechecker.monitor.session import MonitorSession
from vibechecker.monitor.writer import MonitorWriterThread

log = vibechecker.get_logger(__name__)


class MonitorController:
    """Gate, anomaly detection, and write dispatch for Monitor Mode.

    Recording lifecycle: start(session, anomaly_hook) / stop(). The anomaly
    hook is supplied at session start and active for the whole session — there
    is no separate arm/disarm step; config alone controls detection.

    Called from the GUI thread via ``on_results(results, frame_cache)``
    after each call to ``collector.process_samples()``.
    """

    def __init__(self) -> None:
        self._session:      MonitorSession | None      = None
        self._gate:         IntervalGate | None        = None
        self._writer:       MonitorWriterThread | None = None
        self._anomaly_hook: AnomalyHook                = NullAnomalyHook()
        self._recording     = False
        self._start_mono    = 0.0
        self._capture_count = 0
        self._burst_count   = 0
        self._cooldown_until_mono: float = 0.0

        # Burst state
        self._in_burst:             bool      = False
        self._burst_end_mono:       float     = 0.0
        self._burst_id:             str       = ''
        self._burst_frames:         list[dict] = []
        self._burst_results:        list      = []
        self._burst_all_results:    list[list] = []  # per-frame results during burst
        self._burst_pretrigger:     int       = 0
        self._burst_trigger_ts:     str       = ''   # ISO UTC timestamp at trigger
        self._burst_trigger_rel:    float     = 0.0  # session rel_time at trigger
        self._last_frame_cache:     deque | None = None

    # ------------------------------------------------------------------
    # Public API — recording lifecycle
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """True when a session is running (writer thread active)."""
        return self._recording

    def start(self, session: MonitorSession,
              anomaly_hook: AnomalyHook | None = None) -> None:
        """Start a new recording session. Stops any running session first.

        Anomaly detection is controlled entirely by `anomaly_hook` — pass
        `None` (or a `NullAnomalyHook`) to record without detection. There is
        no separate arm/disarm step; the hook built from config at session
        start is active for the whole session.
        """
        if self._recording:
            self.stop()

        self._session = session
        self._start_mono = time.monotonic()
        self._gate = IntervalGate(session.interval_s, self._start_mono)
        self._writer = MonitorWriterThread(session)
        self._writer.start()

        self._capture_count = 0
        self._burst_count   = 0
        self._in_burst          = False
        self._burst_frames      = []
        self._burst_results     = []
        self._burst_all_results = []
        self._recording     = True
        self._cooldown_until_mono = 0.0

        self._anomaly_hook = anomaly_hook if anomaly_hook is not None else NullAnomalyHook()

        log.info(
            f'Monitor recording started: session={session.session_id} '
            f'interval={session.interval_s}s'
        )

    def stop(self) -> None:
        """Stop the recording session and flush the writer."""
        if not self._recording:
            return
        self._recording = False

        # Flush any partial burst
        if self._in_burst and self._burst_frames:
            now      = time.monotonic()
            rel_time = now - self._start_mono
            self._flush_burst(self._burst_results, rel_time)

        if self._writer:
            self._writer.stop()

        log.info(
            f'Monitor stopped. Captures: {self._capture_count}, '
            f'Bursts: {self._burst_count}'
        )

    # ------------------------------------------------------------------
    # Public API — manual burst trigger
    # ------------------------------------------------------------------

    def trigger_burst(self) -> None:
        """Manually force a burst capture immediately. Noop if not recording or mid-burst."""
        if not self._recording or self._session is None or self._in_burst:
            return
        now = time.monotonic()
        utc_now = datetime.now(timezone.utc)
        self._in_burst            = True
        self._burst_end_mono      = now + self._session.burst_duration_s
        self._burst_id            = utc_now.strftime('%Y-%m-%d-%H%M%S')
        self._burst_trigger_ts    = utc_now.isoformat()
        self._burst_trigger_rel   = now - self._start_mono
        self._burst_results       = []
        # Snapshot pre-trigger frames from last seen frame cache
        n = self._session.pre_buffer_frames
        if self._last_frame_cache:
            pre = list(self._last_frame_cache)[-n:]
            self._burst_frames     = [dict(f) for f in pre]
            self._burst_pretrigger = len(self._burst_frames)
        else:
            self._burst_frames     = []
            self._burst_pretrigger = 0
        self._gate.enter_burst(self._session.burst_duration_s, now, self._session.max_burst_s)
        self._start_cooldown(now)
        log.info('Monitor burst triggered manually')

    # ------------------------------------------------------------------
    # Main callback
    # ------------------------------------------------------------------

    def on_results(self, results: list, frame_cache: deque) -> None:
        """Called from GUI thread after process_samples(). Non-blocking."""
        if not self._recording or not results:
            return

        self._last_frame_cache = frame_cache  # for trigger_burst() pre-trigger snapshot
        now      = time.monotonic()
        rel_time = now - self._start_mono

        if self._in_burst:
            self._handle_burst_frame(results, frame_cache, now, rel_time)
            return

        # Skip anomaly detection while a post-burst cooldown is active —
        # interval captures continue as normal.
        in_cooldown = (
            self._session is not None and self._session.cooldown_enabled
            and now < self._cooldown_until_mono
        )
        if not in_cooldown:
            event: AnomalyEvent | None = self._anomaly_hook.on_results(results, frame_cache)
            if event is not None:
                # Write trigger frame to interval trend before entering burst
                self._gate.mark_captured(now)
                self._capture_interval(results, frame_cache, rel_time)
                self._start_burst(event, results, frame_cache, now, rel_time)
                return

        # Normal interval gate
        if self._gate.should_capture(now):
            self._gate.mark_captured(now)
            self._capture_interval(results, frame_cache, rel_time)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status_snapshot(self) -> dict:
        now       = time.monotonic()
        elapsed   = (now - self._start_mono) if self._recording else 0.0
        time_next = self._gate.time_to_next(now) if self._gate else 0.0
        depth     = self._writer.queue_depth if self._writer else 0
        err       = self._writer.error if self._writer else None
        session   = self._session
        if session and session.session_h5.exists():
            total_bytes = session.session_h5.stat().st_size
        else:
            total_bytes = 0
        burst_remaining = max(0.0, self._burst_end_mono - now) if self._in_burst else 0.0
        return {
            'elapsed_s':        elapsed,
            'capture_count':    self._capture_count,
            'burst_count':      self._burst_count,
            'next_capture_s':   time_next,
            'queue_depth':      depth,
            'total_bytes':      total_bytes,
            'error':            str(err) if err else None,
            'is_in_burst':       self._in_burst,
            'burst_remaining_s': burst_remaining,
            'baseline':          self._anomaly_hook.baseline_snapshot()
                                 if hasattr(self._anomaly_hook, 'baseline_snapshot') else {},
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_interval(self, results: list, frame_cache: deque,
                          rel_time: float) -> None:
        timestamp_str = datetime.now(timezone.utc).isoformat()
        latest        = dict(frame_cache[-1]) if frame_cache else {}
        self._enqueue(
            frames     = [latest],
            results    = results,
            trigger    = 'interval',
            rel_time   = rel_time,
            timestamp  = timestamp_str,
        )

    def _start_burst(self, event: AnomalyEvent, results: list,
                     frame_cache: deque, now: float, rel_time: float) -> None:
        utc_now = datetime.now(timezone.utc)
        self._in_burst            = True
        self._burst_end_mono      = now + event.burst_duration_s
        self._burst_id            = utc_now.strftime('%Y-%m-%d-%H%M%S')
        # Trigger metadata reflects the t=0 frame (anomaly onset), which may
        # precede `now` by however long the hook's confirmation window took.
        self._burst_trigger_ts    = event.trigger_time.isoformat()
        self._burst_trigger_rel   = event.trigger_rel_time
        self._burst_results       = list(results)
        self._burst_all_results   = [list(results)]

        # Snapshot pre-trigger frames
        n = self._session.pre_buffer_frames if self._session else 1
        pre = list(frame_cache)[-n:] if frame_cache else []
        self._burst_frames     = [dict(f) for f in pre]
        self._burst_pretrigger = len(self._burst_frames)

        self._start_cooldown(now)

        log.warning(
            f'Monitor: anomaly burst triggered on ch{event.channel} — {event.reason}'
        )

    def _start_cooldown(self, now: float) -> None:
        """Arm the post-burst cooldown gate, if enabled for this session."""
        if self._session is not None and self._session.cooldown_enabled:
            self._cooldown_until_mono = now + self._session.cooldown_s

    def _handle_burst_frame(self, results: list, frame_cache: deque,
                             now: float, rel_time: float) -> None:
        latest = dict(frame_cache[-1]) if frame_cache else {}
        self._burst_frames.append(latest)
        self._burst_all_results.append(list(results))

        # Keep EWMA adapting during burst but suppress retriggers
        if hasattr(self._anomaly_hook, 'update_baseline'):
            self._anomaly_hook.update_baseline(results)

        if now >= self._burst_end_mono:
            self._flush_burst(results, rel_time)

    def _flush_burst(self, results: list, rel_time: float) -> None:
        self._in_burst = False
        if self._burst_frames:
            self._enqueue(
                frames             = self._burst_frames,
                results            = self._burst_results or results,
                all_results        = self._burst_all_results,
                trigger            = 'burst',
                rel_time           = self._burst_trigger_rel,   # trigger time, not flush time
                timestamp          = self._burst_trigger_ts,    # trigger timestamp
                burst_id           = self._burst_id,
                n_pretrigger       = self._burst_pretrigger,
            )
            self._burst_count += 1
        self._burst_frames       = []
        self._burst_results      = []
        self._burst_all_results  = []
        self._burst_id           = ''
        self._burst_pretrigger   = 0
        self._burst_trigger_ts   = ''
        self._burst_trigger_rel  = 0.0
        if self._gate and self._session:
            self._gate.exit_burst(time.monotonic())

    def _enqueue(self, frames: list, results: list, trigger: str,
                 rel_time: float, timestamp: str,
                 burst_id: str = '', n_pretrigger: int = 0,
                 all_results: list | None = None) -> None:
        item: dict = {
            'frames':      frames,
            'results':     results,
            'all_results': all_results or [],
            'trigger':     trigger,
            'rel_time':    rel_time,
            'timestamp':   timestamp,
        }
        if trigger != 'interval':
            item['burst_id']           = burst_id
            item['n_pretrigger_frames'] = n_pretrigger

        if self._writer and self._writer.enqueue(item):
            if trigger == 'interval':
                self._capture_count += 1
