"""Monitor writer — accumulates all session frames into a single session.h5 (file_version=5)."""

import json
import queue
import shutil
import threading

import h5py
import numpy as np

import rev80
from rev80.monitor.session import MonitorSession

log = rev80.get_logger(__name__)

_DISK_GUARD_BYTES: int = 1 * 1024 ** 3  # 1 GiB
_QUEUE_WARN_DEPTH: int = 50
_FILE_VERSION: int = 5


def _write_channel_group(h5_grp, ch: int, sample,
                         compression: str = 'gzip',
                         compression_opts: int = 4) -> None:
    """Write one VibeSample's mV data into an h5py group named str(ch)."""
    cg = h5_grp.create_group(str(ch))
    cg.create_dataset(
        'data',
        data=np.asarray(sample.data, dtype=np.float64),
        compression=compression,
        compression_opts=compression_opts,
    )


def _compute_overall_peaks(results: list) -> tuple[str, str]:
    """Return (overall_json, peaks_json) strings from a list of ChannelResult."""
    overall: dict[str, float] = {}
    peaks: dict[str, list] = {}
    for r in results:
        overall[str(r.channel)] = float(r.overall)
        top10 = [
            (float(r.freq[i]), float(r.spectrum[i]))
            for i in r.peaks[:10]
            if i < len(r.freq)
        ]
        peaks[str(r.channel)] = top10
    return json.dumps(overall), json.dumps(peaks)


class MonitorWriterThread:
    """Daemon thread that accumulates monitor captures into a single session.h5."""

    def __init__(self, session: MonitorSession):
        self._session = session
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='MonitorWriter'
        )
        self._error: Exception | None = None
        self._warned_depth = False
        self._monitor_count: int = 0   # number of interval frames written
        self._burst_count: int = 0     # number of burst events written
        self._h5_initialised = False

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)

    def enqueue(self, item: dict) -> bool:
        depth = self._queue.qsize()
        if depth >= _QUEUE_WARN_DEPTH and not self._warned_depth:
            log.warning(f'MonitorWriter: queue depth {depth} — disk may be slow')
            self._warned_depth = True
        elif depth < _QUEUE_WARN_DEPTH:
            self._warned_depth = False
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            log.error('MonitorWriter: queue full — capture dropped')
            return False

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def error(self) -> Exception | None:
        return self._error

    @property
    def monitor_count(self) -> int:
        return self._monitor_count

    @property
    def burst_count(self) -> int:
        return self._burst_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._write(item)
            except Exception as exc:
                log.error(f'MonitorWriter: write error: {exc}')
                self._error = exc
            finally:
                self._queue.task_done()

    def _ensure_h5(self) -> None:
        """Create session_dir and initialise session.h5 with /metadata on first call."""
        if self._h5_initialised:
            return
        session = self._session
        session.session_dir.mkdir(parents=True, exist_ok=True)

        with h5py.File(session.session_h5, 'w') as f:
            # /metadata
            meta_grp = f.create_group('metadata')
            meta_grp.attrs['file_version'] = _FILE_VERSION
            meta_grp.attrs['session_id']   = session.session_id
            meta_grp.attrs['start_time']   = session.start_time.isoformat()
            meta_grp.attrs['interval_s']   = float(session.interval_s)

            # /metadata/acquisition
            acq_grp = meta_grp.create_group('acquisition')
            for k, v in session.acq_snapshot.items():
                if k in ('channel_names', 'channel_target_units', 'channel_amplitude_modes'):
                    continue
                acq_grp.attrs[k] = '' if v is None else v

            # /metadata/scope_sensors
            ss_grp = meta_grp.create_group('scope_sensors')
            for sid, sdict in session.sensor_snapshot.items():
                sg = ss_grp.create_group(sid)
                for k, v in sdict.items():
                    sg.attrs[k] = v

            # /metadata/channels
            ch_grp = meta_grp.create_group('channels')
            for ch_str, cdict in session.channel_snapshot.items():
                cg = ch_grp.create_group(str(ch_str))
                for k, v in cdict.items():
                    cg.attrs[k] = v

            # /monitor  — interval gate captures accumulate here
            f.create_group('monitor')

            # /burst — burst event captures accumulate here
            burst_grp = f.create_group('burst')
            burst_grp.attrs['burst_list'] = json.dumps([])

        self._h5_initialised = True
        log.info(f'MonitorWriter: created {session.session_h5}')

    def _write(self, item: dict) -> None:
        session = self._session

        # Disk-space guard (check session_dir parent if h5 not yet created)
        if session.session_dir.exists():
            check_dir = session.session_dir
        else:
            check_dir = session.session_dir.parent
            if not check_dir.exists():
                check_dir = check_dir.parent

        try:
            free = shutil.disk_usage(check_dir).free
        except FileNotFoundError:
            free = shutil.disk_usage('/').free

        if free < _DISK_GUARD_BYTES:
            log.error(
                f'MonitorWriter: disk space below 1 GiB '
                f'({free / 1e9:.2f} GiB free) — stopping monitor'
            )
            self._error = OSError('Insufficient disk space')
            self._stop_event.set()
            return

        self._ensure_h5()

        trigger = item.get('trigger', 'interval')
        if trigger == 'interval':
            self._write_interval(item)
        else:
            self._write_burst(item)

    def _write_interval(self, item: dict) -> None:
        """Append one interval gate capture to /monitor/{N}/."""
        session       = self._session
        frames        = item['frames']
        results       = item.get('results', [])
        rel_time      = float(item['rel_time'])
        timestamp_str = item['timestamp']
        overall_json, peaks_json = _compute_overall_peaks(results)

        n = self._monitor_count

        with h5py.File(session.session_h5, 'a') as f:
            mon_grp  = f['monitor']
            gate_grp = mon_grp.create_group(str(n))

            # Extract frame metadata from the first frame
            first_frame = frames[0] if frames else {}
            ch_samples  = {k: v for k, v in first_frame.items() if isinstance(k, int)}
            first_sample = next(iter(ch_samples.values()), None)

            gate_grp.attrs['timestamp']    = timestamp_str
            gate_grp.attrs['rel_time']     = rel_time
            gate_grp.attrs['samplerate']   = int(first_sample.samplerate) if first_sample else 0
            gate_grp.attrs['status']       = str(first_sample.status) if first_sample else ''
            gate_grp.attrs['overall_json'] = overall_json
            gate_grp.attrs['peaks_json']   = peaks_json

            for ch, sample in sorted(ch_samples.items()):
                _write_channel_group(
                    gate_grp, ch, sample,
                    compression=session.compression,
                    compression_opts=session.compression_level,
                )

        self._monitor_count += 1
        log.debug(f'MonitorWriter: interval capture {n} written')

    def _write_burst(self, item: dict) -> None:
        """Append a burst event to /burst/{burst_id}/."""
        session           = self._session
        burst_id          = item.get('burst_id', item.get('capture_id', 'burst'))
        frames            = item['frames']
        results           = item.get('results', [])
        trigger           = item.get('trigger', 'burst')
        rel_time          = float(item['rel_time'])
        timestamp_str     = item['timestamp']
        n_pretrigger        = int(item.get('n_pretrigger_frames', 0))
        all_results: list   = item.get('all_results', [])
        pre_overalls: list  = item.get('pre_overalls', [])  # overall_json strings for pre-trigger frames
        overall_json, _     = _compute_overall_peaks(results)
        n_frames          = len(frames)
        duration_s        = 0.0
        if n_frames >= 2:
            first_frame = frames[0]
            last_frame  = frames[-1]
            first_ch = next((v for k, v in first_frame.items() if isinstance(k, int)), None)
            last_ch  = next((v for k, v in last_frame.items()  if isinstance(k, int)), None)
            if first_ch and last_ch:
                duration_s = float(last_ch.rel_time) - float(first_ch.rel_time)

        with h5py.File(session.session_h5, 'a') as f:
            burst_root = f['burst']

            bid_grp = burst_root.create_group(burst_id)
            bid_grp.attrs['trigger_type']        = trigger
            bid_grp.attrs['trigger_timestamp']   = timestamp_str   # trigger time (UTC ISO)
            bid_grp.attrs['trigger_rel_time']    = rel_time        # session-relative trigger time
            bid_grp.attrs['burst_duration_s']    = duration_s
            bid_grp.attrs['max_overall_json']    = overall_json
            bid_grp.attrs['n_frames']            = n_frames
            bid_grp.attrs['n_pretrigger_frames'] = n_pretrigger

            for frame_index, frame_dict in enumerate(frames):
                ch_samples   = {k: v for k, v in frame_dict.items() if isinstance(k, int)}
                first_sample = next(iter(ch_samples.values()), None)
                is_pre       = 1 if frame_index < n_pretrigger else 0

                fi_grp = bid_grp.create_group(str(frame_index))
                fi_grp.attrs['timestamp']     = first_sample.timestamp if first_sample else timestamp_str
                fi_grp.attrs['rel_time']      = float(first_sample.rel_time) if first_sample else rel_time
                fi_grp.attrs['samplerate']    = int(first_sample.samplerate) if first_sample else 0
                fi_grp.attrs['status']        = str(first_sample.status) if first_sample else ''
                fi_grp.attrs['is_pretrigger'] = is_pre

                if is_pre and frame_index < len(pre_overalls):
                    # Use pre-computed overall from cached mV overalls on the VibeSample
                    fi_grp.attrs['overall_json'] = pre_overalls[frame_index]
                else:
                    frame_results = all_results[frame_index] if frame_index < len(all_results) else []
                    if frame_results:
                        frame_overall, _ = _compute_overall_peaks(frame_results)
                        fi_grp.attrs['overall_json'] = frame_overall

                for ch, sample in sorted(ch_samples.items()):
                    _write_channel_group(
                        fi_grp, ch, sample,
                        compression=session.compression,
                        compression_opts=session.compression_level,
                    )

            # Update /burst.attrs['burst_list']
            existing_json = burst_root.attrs.get('burst_list', '[]')
            if isinstance(existing_json, bytes):
                existing_json = existing_json.decode()
            burst_list = json.loads(existing_json)
            burst_list.append({
                'burst_id':         burst_id,
                'timestamp':        timestamp_str,
                'rel_time':         rel_time,
                'trigger_type':     trigger,
                'max_overall_json': overall_json,
                'duration_s':       duration_s,
            })
            burst_root.attrs['burst_list'] = json.dumps(burst_list)

        self._burst_count += 1
        log.debug(f'MonitorWriter: burst {burst_id} written ({n_frames} frames)')
