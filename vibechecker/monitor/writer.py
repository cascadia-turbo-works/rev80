import queue
import shutil
import threading
import h5py
import numpy as np

import vibechecker
from vibechecker.monitor.index import SessionIndex
from vibechecker.monitor.session import MonitorSession

log = vibechecker.get_logger(__name__)

_DISK_GUARD_BYTES: int = 1 * 1024 ** 3  # 1 GiB
_QUEUE_WARN_DEPTH: int = 50
_FILE_VERSION: int = 4  # v4-compatible — loadable by collector.load_data()


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


class MonitorWriterThread:
    """Daemon thread that persists monitor captures to disk without blocking acquisition."""

    def __init__(self, session: MonitorSession, index: SessionIndex):
        self._session = session
        self._index   = index
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='MonitorWriter'
        )
        self._error: Exception | None = None
        self._warned_depth = False

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

    def _write(self, item: dict) -> None:
        session = self._session

        free = shutil.disk_usage(session.output_dir).free
        if free < _DISK_GUARD_BYTES:
            log.error(
                f'MonitorWriter: disk space below 1 GiB '
                f'({free / 1e9:.2f} GiB free) — stopping monitor'
            )
            self._error = OSError('Insufficient disk space')
            self._stop_event.set()
            return

        capture_id    = item['capture_id']
        frames        = item['frames']    # list[dict[int, VibeSample]]
        results       = item['results']   # list[ChannelResult]
        trigger       = item['trigger']
        rel_time      = float(item['rel_time'])
        timestamp_str = item['timestamp']

        h5_path = session.output_dir / f'{capture_id}.h5'

        with h5py.File(h5_path, 'w') as f:
            # ── /metadata (v4-compatible) ─────────────────────────────
            meta_grp = f.create_group('metadata')
            meta_grp.attrs['version']         = _FILE_VERSION
            meta_grp.attrs['notes']           = ''
            meta_grp.attrs['session_id']      = session.session_id
            meta_grp.attrs['capture_id']      = capture_id
            meta_grp.attrs['capture_trigger'] = trigger

            # /metadata/acquisition — AcquisitionSettings snapshot
            acq_grp = meta_grp.create_group('acquisition')
            for k, v in session.acq_snapshot.items():
                if k in ('channel_names', 'channel_target_units', 'channel_amplitude_modes'):
                    continue  # stored per-channel below
                acq_grp.attrs[k] = '' if v is None else v

            # /metadata/scope_sensors — sensor library at arm time
            ss_grp = meta_grp.create_group('scope_sensors')
            for sid, sdict in session.sensor_snapshot.items():
                sg = ss_grp.create_group(sid)
                for k, v in sdict.items():
                    sg.attrs[k] = v

            # /metadata/channels — per-channel config at arm time
            ch_grp = meta_grp.create_group('channels')
            for ch_str, cdict in session.channel_snapshot.items():
                cg = ch_grp.create_group(str(ch_str))
                for k, v in cdict.items():
                    cg.attrs[k] = v

            # ── /frames (v4 layout) ───────────────────────────────────
            frames_grp = f.create_group('frames')
            for i, frame_dict in enumerate(frames):
                fg = frames_grp.create_group(str(i))
                ch_samples = {k: v for k, v in frame_dict.items() if isinstance(k, int)}
                if not ch_samples:
                    continue
                first = next(iter(ch_samples.values()))
                fg.attrs['timestamp']  = first.timestamp
                fg.attrs['rel_time']   = float(first.rel_time)
                fg.attrs['samplerate'] = int(first.samplerate)
                fg.attrs['status']     = str(first.status)
                for ch, sample in sorted(ch_samples.items()):
                    _write_channel_group(
                        fg, ch, sample,
                        compression=session.compression,
                        compression_opts=session.compression_level,
                    )

        # Build SQLite metadata from ChannelResults
        n_channels = len(results)
        samplerate = results[0].samplerate if results else 0
        overall    = {str(r.channel): float(r.overall) for r in results}
        peaks: dict[str, list] = {}
        for r in results:
            top10 = [
                (float(r.freq[i]), float(r.spectrum[i]))
                for i in r.peaks[:10]
                if i < len(r.freq)
            ]
            peaks[str(r.channel)] = top10

        self._index.add_capture(
            capture_id=capture_id,
            timestamp=timestamp_str,
            rel_time=rel_time,
            trigger=trigger,
            n_channels=n_channels,
            samplerate=samplerate,
            overall=overall,
            peaks=peaks,
        )
        log.debug(
            f'MonitorWriter: saved {capture_id} '
            f'({trigger}, {len(frames)} frame(s))'
        )
