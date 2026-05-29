import time
from collections import deque
from datetime import datetime, timezone

import yaml

import vibechecker
from vibechecker.monitor.anomaly import AnomalyEvent, AnomalyHook, NullAnomalyHook
from vibechecker.monitor.gate import IntervalGate
from vibechecker.monitor.index import SessionIndex
from vibechecker.monitor.session import MonitorSession
from vibechecker.monitor.writer import MonitorWriterThread

log = vibechecker.get_logger(__name__)


class MonitorController:
    """Gate, anomaly detection, and write dispatch for Monitor Mode.

    Called from the GUI thread via ``on_results(results, frame_cache)``
    after each call to ``collector.process_samples()``.
    """

    def __init__(self) -> None:
        self._session:      MonitorSession | None      = None
        self._gate:         IntervalGate | None        = None
        self._index:        SessionIndex | None        = None
        self._writer:       MonitorWriterThread | None = None
        self._anomaly_hook: AnomalyHook                = NullAnomalyHook()
        self._armed         = False
        self._start_mono    = 0.0
        self._capture_count = 0

        # Burst state
        self._in_burst:        bool      = False
        self._burst_end_mono:  float     = 0.0
        self._burst_capture_id: str      = ''
        self._burst_frames:    list[dict] = []
        self._burst_results:   list      = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_armed(self) -> bool:
        return self._armed

    def start(self, session: MonitorSession,
              anomaly_hook: AnomalyHook | None = None) -> None:
        if self._armed:
            self.stop()

        self._session = session
        session.output_dir.mkdir(parents=True, exist_ok=True)

        self._index = SessionIndex(session.output_dir)
        self._index.set_meta('session_id', session.session_id)
        self._index.set_meta('start_time', session.start_time.isoformat())
        self._index.set_meta('interval_s', str(session.interval_s))

        self._start_mono = time.monotonic()
        self._gate = IntervalGate(session.interval_s, self._start_mono)
        self._writer = MonitorWriterThread(session, self._index)
        self._writer.start()

        self._anomaly_hook = anomaly_hook or NullAnomalyHook()
        self._capture_count = 0
        self._in_burst = False
        self._burst_frames = []
        self._burst_results = []
        self._armed = True

        log.info(
            f'Monitor armed: session={session.session_id} '
            f'interval={session.interval_s}s'
        )

    def stop(self) -> None:
        if not self._armed:
            return
        self._armed = False

        # Flush any partial burst
        if self._in_burst and self._burst_frames:
            now = time.monotonic()
            rel_time = now - self._start_mono
            self._flush_burst(self._burst_results, rel_time)

        if self._writer:
            self._writer.stop()
        if self._index and self._session:
            self._write_session_yaml()
            self._index.close()

        log.info(f'Monitor disarmed. Captures saved: {self._capture_count}')

    def on_results(self, results: list, frame_cache: deque) -> None:
        """Called from GUI thread after process_samples(). Non-blocking."""
        if not self._armed or not results:
            return

        now      = time.monotonic()
        rel_time = now - self._start_mono

        if self._in_burst:
            self._handle_burst_frame(results, frame_cache, now, rel_time)
            return

        # Check anomaly hook
        event: AnomalyEvent | None = self._anomaly_hook.on_results(results, frame_cache)
        if event is not None:
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
        elapsed   = (now - self._start_mono) if self._armed else 0.0
        time_next = self._gate.time_to_next(now) if self._gate else 0.0
        depth     = self._writer.queue_depth if self._writer else 0
        db_bytes  = self._index.total_bytes() if self._index else 0
        err       = self._writer.error if self._writer else None
        return {
            'armed':          self._armed,
            'elapsed_s':      elapsed,
            'capture_count':  self._capture_count,
            'queue_depth':    depth,
            'total_bytes':    db_bytes,
            'next_capture_s': time_next,
            'in_burst':       self._in_burst,
            'error':          str(err) if err else None,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_interval(self, results: list, frame_cache: deque,
                          rel_time: float) -> None:
        capture_id = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')
        latest     = dict(frame_cache[-1]) if frame_cache else {}
        self._enqueue(capture_id, [latest], results, 'interval', rel_time)

    def _start_burst(self, event: AnomalyEvent, results: list,
                     frame_cache: deque, now: float, rel_time: float) -> None:
        self._in_burst        = True
        self._burst_end_mono  = now + event.burst_duration_s
        self._burst_capture_id = (
            datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S') + '_burst'
        )
        self._burst_results = list(results)

        # Snapshot pre-trigger frames
        n = self._session.pre_buffer_frames if self._session else 1
        pre = list(frame_cache)[-n:] if frame_cache else []
        self._burst_frames = [dict(f) for f in pre]

        log.warning(
            f'Monitor: anomaly burst triggered on ch{event.channel} — {event.reason}'
        )

    def _handle_burst_frame(self, results: list, frame_cache: deque,
                             now: float, rel_time: float) -> None:
        latest = dict(frame_cache[-1]) if frame_cache else {}
        self._burst_frames.append(latest)

        # Retrigger check
        event: AnomalyEvent | None = self._anomaly_hook.on_results(results, frame_cache)
        if event is not None and self._session:
            self._gate.enter_burst(
                event.burst_duration_s,
                now=now,
                max_burst_s=self._session.max_burst_s,
            )
            self._burst_end_mono = self._gate._burst_end  # sync

        if now >= self._burst_end_mono:
            self._flush_burst(results, rel_time)

    def _flush_burst(self, results: list, rel_time: float) -> None:
        self._in_burst = False
        if self._burst_frames:
            self._enqueue(
                self._burst_capture_id,
                self._burst_frames,
                self._burst_results or results,
                'burst',
                rel_time,
            )
        self._burst_frames    = []
        self._burst_results   = []
        self._burst_capture_id = ''
        if self._gate and self._session:
            self._gate.exit_burst(time.monotonic())

    def _enqueue(self, capture_id: str, frames: list, results: list,
                 trigger: str, rel_time: float) -> None:
        item = {
            'capture_id': capture_id,
            'frames':     frames,
            'results':    results,
            'trigger':    trigger,
            'rel_time':   rel_time,
            'timestamp':  datetime.now(timezone.utc).isoformat(),
        }
        if self._writer and self._writer.enqueue(item):
            self._capture_count += 1

    def _write_session_yaml(self) -> None:
        if not self._session:
            return
        summary = {
            'session_id':    self._session.session_id,
            'start_time':    self._session.start_time.isoformat(),
            'stop_time':     datetime.now(timezone.utc).isoformat(),
            'interval_s':    self._session.interval_s,
            'capture_count': self._capture_count,
            'output_dir':    str(self._session.output_dir),
        }
        path = self._session.output_dir / 'session.yaml'
        with open(path, 'w') as f:
            yaml.dump(summary, f, default_flow_style=False)
        log.info(f'Session summary: {path}')
