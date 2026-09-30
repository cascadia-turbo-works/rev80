import time
from collections import deque
from datetime import datetime

import rev80
from rev80.monitor.anomaly import AnomalyEvent, AnomalyHook, NullAnomalyHook
from rev80.monitor.gate import IntervalGate
from rev80.monitor.session import MonitorSession
from rev80.scope_sensor import ScopeSensor
from rev80.monitor.writer import MonitorWriterThread

log = rev80.get_logger(__name__)


class MonitorController:
    """Gate, anomaly detection, and write dispatch for Monitor Mode.

    Lifecycle: start(session, anomaly_hook) / stop(). The hook given to
    start() is active for the whole session; there is no arm step.

    Call ``on_results(results, frame_cache)`` after each call to
    ``collector.process_samples()``, from the same thread (the GUI render
    loop or the headless loop).
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
        self._burst_pre_overalls:   list[str]  = []  # overall_json per pre-trigger frame
        self._burst_pretrigger:     int       = 0
        self._burst_trigger_ts:     str       = ''   # ISO local timestamp at trigger
        self._burst_trigger_rel:    float     = 0.0  # session rel_time at trigger
        self._burst_onset_ts:       str       = ''   # ISO local anomaly onset; '' if none
        self._last_frame_cache:     deque | None = None
        self._last_frame:           dict | None  = None
        self._last_results:         list         = []

        # Resource trail. An OOM kill leaves no traceback, so a session logs
        # memory, threads, burst retention and queue depth every
        # TRAIL_INTERVAL_S. The log then shows the ramp before the kill.
        self._last_trail_mono: float = 0.0

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
        self._in_burst           = False
        self._burst_frames       = []
        self._burst_results      = []
        self._burst_all_results  = []
        self._burst_pre_overalls = []
        self._last_frame_cache   = None
        self._last_frame         = None
        self._last_results       = []
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
        now_local = datetime.now()
        self._in_burst            = True
        self._burst_end_mono      = self.capped_burst_end(
            now, self._session.burst_duration_s, self._session.max_burst_s,
            burst_start=now)
        self._burst_id            = now_local.strftime('%Y-%m-%d-%H%M%S')
        self._burst_trigger_ts    = now_local.isoformat()
        self._burst_trigger_rel   = now - self._start_mono
        self._burst_onset_ts      = ''
        self._burst_results       = []
        # The trigger frame is the last frame that on_results processed. It
        # goes at index n_pretrigger, which load_monitor_burst uses as t=0.
        # Frames that arrived after it have no results yet, so they are not
        # included.
        n = self._session.pre_buffer_frames
        pre = self._frames_up_to_last_seen()[-n:]
        self._burst_frames     = [dict(f) for f in pre]
        self._burst_pretrigger = max(0, len(self._burst_frames) - 1)
        self._burst_pre_overalls = self._compute_pretrigger_overalls(
            self._burst_frames[:self._burst_pretrigger]
        )
        # One results entry per frame: _flush_burst and the burst cap use
        # the two lists in parallel.
        if self._burst_frames:
            self._burst_all_results = (
                [[]] * self._burst_pretrigger + [list(self._last_results)])
        else:
            self._burst_all_results = []
        self._set_burst_frame_cap(self._session.burst_duration_s)
        self._gate.enter_burst(self._session.burst_duration_s, now, self._session.max_burst_s)
        self._start_cooldown(now)
        log.info('Monitor burst triggered manually')

    def _frames_up_to_last_seen(self) -> list[dict]:
        """Cached frames, oldest first, that end at the last processed frame.

        Returns an empty list when on_results has not seen a frame, or when
        that frame has left the cache.
        """
        if not self._last_frame_cache or self._last_frame is None:
            return []
        frames = list(self._last_frame_cache)
        for i in range(len(frames) - 1, -1, -1):
            if frames[i] is self._last_frame:
                return frames[:i + 1]
        return []

    # ------------------------------------------------------------------
    # Main callback
    # ------------------------------------------------------------------

    #: Floor on retained burst frames, so a pathological acquisition_period
    #: cannot produce a zero-length burst.
    MIN_BURST_FRAMES: int = 4

    @staticmethod
    def burst_frame_cap(max_burst_s: float, acquisition_period: float) -> int:
        """Frames that one burst may keep: max_burst_s / acquisition_period + 1.

        Never fewer than MIN_BURST_FRAMES. A burst holds all its frames and
        results in memory until the flush, about 2.26 MB/s on 4 channels at
        any F_max and binsize, so this cap prevents an OOM kill. Evidence:
        CONTRIBUTING.md, "E17. Burst memory".
        """
        if acquisition_period <= 0:
            return MonitorController.MIN_BURST_FRAMES
        n = int(float(max_burst_s) / float(acquisition_period)) + 1
        return max(MonitorController.MIN_BURST_FRAMES, n)

    @staticmethod
    def capped_burst_end(now: float, duration_s: float,
                         max_burst_s: float, burst_start: float) -> float:
        """Burst end time, clamped to burst_start + max_burst_s (all in s).

        A max_burst_s of 0 or None means no limit, not a zero-length burst.
        """
        end = now + float(duration_s)
        if max_burst_s and max_burst_s > 0:
            end = min(end, float(burst_start) + float(max_burst_s))
        return end

    #: How often the unattended resource trail is written, in seconds.
    #: Slow on purpose — this is a trend to read after the fact, not telemetry.
    TRAIL_INTERVAL_S: float = 300.0

    def _log_resource_trail(self, now: float) -> None:
        """Periodically record memory, threads, retention and queue depth.

        Never raises: a diagnostic that takes down the session it is
        diagnosing is worse than no diagnostic.
        """
        if now - self._last_trail_mono < self.TRAIL_INTERVAL_S:
            return
        self._last_trail_mono = now
        try:
            from rev80.logger import format_resource_snapshot, resource_snapshot
            writer = getattr(self, '_writer', None)
            log.info(
                'monitor trail: %s',
                format_resource_snapshot(
                    resource_snapshot(),
                    burst_frames=len(self._burst_frames),
                    queue=getattr(writer, 'queue_depth', -1),
                    captures=self._capture_count,
                ),
            )
        except Exception:                                    # noqa: BLE001
            log.debug('resource trail failed', exc_info=True)

    def on_results(self, results: list, frame_cache: deque) -> None:
        """Handle one frame's results. Call after process_samples(). Does not block."""
        if not self._recording or not results:
            return

        # For trigger_burst(): the cache, the frame these results belong to,
        # and the results themselves.
        self._last_frame_cache = frame_cache
        self._last_frame       = frame_cache[-1] if frame_cache else None
        self._last_results     = list(results)
        now      = time.monotonic()
        rel_time = now - self._start_mono

        self._log_resource_trail(now)

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
        dropped   = self._writer.dropped if self._writer else 0
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
            # Captures lost because the writer queue was full.
            'dropped_captures': dropped,
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
        timestamp_str = datetime.now().isoformat()
        latest        = dict(frame_cache[-1]) if frame_cache else {}
        self._enqueue(
            frames     = [latest],
            results    = results,
            trigger    = 'interval',
            rel_time   = rel_time,
            timestamp  = timestamp_str,
        )

    def _compute_pretrigger_overalls(self, frames: list[dict]) -> list[str]:
        """Build overall_json strings for pre-trigger frames from cached mV overalls.

        VibeSamples already have overall_ampl_by_integration_order populated from
        live processing.  Apply forward scaling using the session channel/sensor
        snapshot to produce target-EU values matching the rest of overall_json.
        """
        import json as _json
        from rev80.util import UNIT_TO_SI, amplitude_scale, integration_steps

        session = self._session
        if session is None:
            return ['{}'] * len(frames)

        ch_snap   = session.channel_snapshot   # {str(ch): {scope_sensor_id, ...}}
        sens_snap = session.sensor_snapshot    # {sensor_id: ScopeSensor.to_dict()}

        # Rebuild ScopeSensor objects with from_dict(). Do not read the dict
        # keys here: the field names must be defined in ScopeSensor only.
        sensors: dict = {}
        for _sid, _cfg in sens_snap.items():
            try:
                sensors[_sid] = ScopeSensor.from_dict(_cfg)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning('monitor: unusable sensor snapshot for %s (%s) — '
                            'pre-trigger overalls for its channels stay in mV', _sid, exc)

        out: list[str] = []
        for frame_dict in frames:
            overall: dict[str, float] = {}
            for ch, sample in frame_dict.items():
                if not isinstance(ch, int):
                    continue
                if getattr(sample, 'tach', None) is not None:
                    # A tachometer channel has no overall. Including it
                    # writes 0.0, and the loaded session shows a trend line
                    # at zero for that channel.
                    continue
                ch_cfg  = ch_snap.get(str(ch), {})
                sid     = ch_cfg.get('scope_sensor_id')

                scope_s   = sensors.get(sid) if sid else None
                sens_mv   = scope_s.sensitivity if scope_s else 1.0
                sensor_eu = scope_s.engineering_units if scope_s else 'mV'
                target_u  = ch_cfg.get('target_unit') or sensor_eu
                amp_mode  = ch_cfg.get('amplitude_mode', '0-P') or '0-P'

                n_steps = integration_steps(sensor_eu, target_u)
                col     = max(0, min(4, n_steps + 2))
                src_si  = UNIT_TO_SI.get(sensor_eu, 1.0)
                tgt_si  = UNIT_TO_SI.get(target_u,  1.0)
                amp_f   = amplitude_scale(amp_mode)
                scale   = src_si / tgt_si / sens_mv

                raw_mv = float(sample.overall_ampl_by_integration_order[col])
                overall[str(ch)] = raw_mv * scale * amp_f
            out.append(_json.dumps(overall))
        return out

    def _start_burst(self, event: AnomalyEvent, results: list,
                     frame_cache: deque, now: float, rel_time: float) -> None:
        self._in_burst            = True
        # Through the shared clamp, so max_burst_s applies to this path.
        max_burst_s = self._session.max_burst_s if self._session else 0.0
        self._burst_end_mono      = self.capped_burst_end(
            now, event.burst_duration_s, max_burst_s, burst_start=now)
        # t = 0 is the stored frame at n_pretrigger: frame_cache[-1], the
        # frame that confirms the anomaly. The trigger time describes that
        # frame, on the same clock as the interval captures. The onset that
        # the hook reports can be earlier; it is stored as onset_timestamp.
        now_local = datetime.now()
        self._burst_id            = now_local.strftime('%Y-%m-%d-%H%M%S')
        self._burst_trigger_ts    = now_local.isoformat()
        self._burst_trigger_rel   = rel_time
        self._burst_onset_ts      = event.trigger_time.isoformat()
        self._burst_results       = list(results)

        # Snapshot pre-trigger frames.  frame_cache[-1] is the trigger frame;
        # n_pretrigger is its index so load_monitor_burst can use it as t=0.
        n = self._session.pre_buffer_frames if self._session else 1
        pre = list(frame_cache)[-n:] if frame_cache else []
        self._burst_frames     = [dict(f) for f in pre]
        self._burst_pretrigger = max(0, len(self._burst_frames) - 1)
        # Pre-compute overalls for pre-trigger frames from their cached mV values.
        self._burst_pre_overalls = self._compute_pretrigger_overalls(
            self._burst_frames[:self._burst_pretrigger]
        )
        # Pad all_results: trigger frame at n_pretrigger, empties for pre-trigger.
        self._burst_all_results = [[]] * self._burst_pretrigger + [list(results)]
        self._set_burst_frame_cap(event.burst_duration_s)

        self._start_cooldown(now)

        log.warning(
            f'Monitor: anomaly burst triggered on ch{event.channel} — {event.reason}'
        )

    def _set_burst_frame_cap(self, duration_s: float) -> None:
        """Set the frame cap of the burst that starts now. Both burst paths use it.

        The cap is burst_frame_cap() for the frames after the trigger, plus
        the pre-trigger frames, so that a burst of max_burst_s keeps all its
        pre-trigger frames. Call it after _burst_pretrigger is set.
        """
        session = self._session
        max_burst_s = session.max_burst_s if session else 0.0
        period = float(getattr(session, 'acquisition_period', 0.0) or 0.0)
        if period <= 0:
            log.warning(
                'Monitor: the session has no frame period, so a burst keeps '
                'only %d frames. Build the session with session_from().',
                self.MIN_BURST_FRAMES)
            self._max_burst_frames = self.MIN_BURST_FRAMES
        else:
            self._max_burst_frames = (
                self.burst_frame_cap(max_burst_s or duration_s, period)
                + self._burst_pretrigger)
        self._warned_burst_cap = False

    def _start_cooldown(self, now: float) -> None:
        """Arm the post-burst cooldown gate, if enabled for this session."""
        if self._session is not None and self._session.cooldown_enabled:
            self._cooldown_until_mono = now + self._session.cooldown_s

    def _handle_burst_frame(self, results: list, frame_cache: deque,
                             now: float, rel_time: float) -> None:
        latest = dict(frame_cache[-1]) if frame_cache else {}
        self._burst_frames.append(latest)
        self._burst_all_results.append(list(results))

        # Hard cap on retention. The two lists are indexed together by
        # _flush_burst, so they must be trimmed together or every overall
        # lands against the wrong waveform.
        cap = getattr(self, '_max_burst_frames', 0)
        if cap and len(self._burst_frames) > cap:
            if not getattr(self, '_warned_burst_cap', False):
                self._warned_burst_cap = True
                log.warning(
                    'Monitor: burst retention hit its %d-frame cap — oldest '
                    'frames are being dropped. The burst is running longer '
                    'than max_burst_s allows for.', cap,
                )
            drop = len(self._burst_frames) - cap
            del self._burst_frames[:drop]
            del self._burst_all_results[:drop]
            self._burst_pretrigger = max(0, self._burst_pretrigger - drop)

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
                pre_overalls       = self._burst_pre_overalls,
                trigger            = 'burst',
                rel_time           = self._burst_trigger_rel,   # trigger time, not flush time
                timestamp          = self._burst_trigger_ts,    # trigger timestamp
                burst_id           = self._burst_id,
                n_pretrigger       = self._burst_pretrigger,
                onset_timestamp    = self._burst_onset_ts,
            )
            self._burst_count += 1
        self._burst_frames       = []
        self._burst_results      = []
        self._burst_all_results  = []
        self._burst_pre_overalls = []
        self._burst_id           = ''
        self._burst_pretrigger   = 0
        self._burst_trigger_ts   = ''
        self._burst_trigger_rel  = 0.0
        self._burst_onset_ts     = ''
        if self._gate and self._session:
            self._gate.exit_burst(time.monotonic())

    def _enqueue(self, frames: list, results: list, trigger: str,
                 rel_time: float, timestamp: str,
                 burst_id: str = '', n_pretrigger: int = 0,
                 all_results: list | None = None,
                 pre_overalls: list | None = None,
                 onset_timestamp: str = '') -> None:
        item: dict = {
            'frames':       frames,
            'results':      results,
            'all_results':  all_results or [],
            'pre_overalls': pre_overalls or [],
            'trigger':      trigger,
            'rel_time':     rel_time,
            'timestamp':    timestamp,
        }
        if trigger != 'interval':
            item['burst_id']           = burst_id
            item['n_pretrigger_frames'] = n_pretrigger
            if onset_timestamp:
                item['onset_timestamp'] = onset_timestamp

        if self._writer and self._writer.enqueue(item):
            if trigger == 'interval':
                self._capture_count += 1
