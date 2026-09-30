from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MonitorSession:
    session_id: str               # "YYYY-MM-DD-HHMMSS", local time (the same clock as start_time)
    start_time: datetime          # local time
    interval_s: float             # seconds between captures
    pre_buffer_frames: int        # frames taken from the cache at a trigger, trigger frame included
    burst_duration_s: float       # burst length after the trigger, in s
    max_burst_s: float            # upper limit on one burst's length, in s
    session_dir: Path             # directory; session.h5 lives at session_dir/session.h5
    compression: str = 'gzip'
    compression_level: int = 4
    cooldown_enabled: bool = False
    cooldown_s: float = 0.0       # s without anomaly detection after a burst starts
    acquisition_period: float = 0.0  # s per frame; 0.0 means unknown
    # Snapshots taken when the session starts; stored in session.h5 /metadata
    acq_snapshot: dict = field(default_factory=dict)      # AcquisitionSettings.to_dict()
    channel_snapshot: dict = field(default_factory=dict)  # {ch: {name, unit, ...}}
    sensor_snapshot: dict = field(default_factory=dict)   # {sensor_id: ScopeSensor.to_dict()}

    @property
    def session_h5(self) -> Path:
        return self.session_dir / 'session.h5'


def channel_snapshot_for(config, collector) -> dict:
    """Per-channel snapshot for session.h5 /metadata/channels.

    The one builder for both front ends. It records each channel's role, and
    for a tachometer channel its calibration as `tach_*` attributes, so that a
    reader can recompute the shaft speed with another `pulses_per_rev`.
    """
    snapshot: dict = {}
    for ch in config.enabled_channels:
        sc = collector.scope_sensors.get(ch)
        role = config.role_for(ch)
        entry = {
            'name':            config.name_for(ch),
            'unit':            'mV',
            'coupling':        config.coupling_for(ch),
            'voltage_range':   config.voltage_range_for(ch),
            'scope_sensor_id': sc.id if sc else '',
            'target_unit':     config.target_unit_for(ch),
            'amplitude_mode':  config.amplitude_mode_for(ch),
            'role':            role,
        }
        if role == 'tachometer':
            # Flat, with a tach_ prefix: HDF5 attributes are scalars. Same
            # layout as save_data.
            for k, v in collector.tach_settings_for(ch).to_dict().items():
                entry[f'tach_{k}'] = v
        snapshot[str(ch)] = entry
    return snapshot


def sensor_snapshot_for(collector) -> dict:
    """{sensor_id: ScopeSensor.to_dict()} for every sensor in use, deduplicated.

    One entry for each sensor, also when more than one channel uses it.
    """
    snapshot: dict = {}
    for sc in collector.scope_sensors.values():
        if sc is not None and sc.id not in snapshot:
            snapshot[sc.id] = sc.to_dict()
    return snapshot


def pre_buffer_frames_for(pre_buffer_s: float, block_s: float) -> int:
    """Number of frames in `pre_buffer_s` seconds (int(pre_buffer_s / block_s)).

    Minimum 1: a value of 0 would make `frame_cache[-n:]` return the whole
    cache.
    """
    if block_s <= 0:
        return 1
    return max(1, int(float(pre_buffer_s) / float(block_s)))


def required_cache_frames(cache_frames: int, pre_buffer_frames: int) -> int:
    """Frame-cache depth for a burst: max(cache_frames, pre_buffer_frames + 1).

    Both front ends size the cache with this function. `MonitorController`
    takes the last `pre_buffer_frames` frames, trigger frame included, so a
    burst keeps `pre_buffer_frames - 1` pre-trigger frames with any cache
    depth of at least `pre_buffer_frames`. Never shrinks a larger cache.
    """
    return max(int(cache_frames), int(pre_buffer_frames) + 1)


def session_from(*, collector, session_id: str, interval_s: float,
                 pre_buffer_s: float, burst_duration_s: float,
                 max_burst_s: float, output_dir=None,
                 start_time=None, compression: str = 'gzip',
                 compression_level: int = 4,
                 cooldown_enabled: bool = False,
                 cooldown_s: float = 0.0) -> MonitorSession:
    """Build the `MonitorSession` for a run: the one constructor for both front ends.

    Computes `pre_buffer_frames` from `pre_buffer_s` and the frame period, and
    takes the acquisition, channel and sensor snapshots from `collector`.
    `output_dir` is the parent directory; the session gets a `session_id`
    subdirectory in it. None means `data_dir()/monitor`. Callers read
    `max_burst_s` from acquisition.yaml. Keyword-only arguments.
    """
    from datetime import datetime

    import rev80

    cfg = collector.config
    block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 0.0
    # The period of the frames in the frame cache. The burst frame cap uses it.
    frame_s = cfg.raw_blocksize / cfg.raw_samplerate if cfg.raw_samplerate else 0.0
    root = Path(output_dir) if output_dir else rev80.data_dir() / 'monitor'

    return MonitorSession(
        session_id=session_id,
        start_time=start_time or datetime.now(),
        interval_s=float(interval_s),
        pre_buffer_frames=pre_buffer_frames_for(pre_buffer_s, block_s),
        burst_duration_s=float(burst_duration_s),
        max_burst_s=float(max_burst_s),
        session_dir=root / session_id,
        compression=compression,
        compression_level=compression_level,
        cooldown_enabled=bool(cooldown_enabled),
        cooldown_s=float(cooldown_s),
        acquisition_period=float(frame_s),
        acq_snapshot=cfg.to_dict(),
        channel_snapshot=channel_snapshot_for(cfg, collector),
        sensor_snapshot=sensor_snapshot_for(collector),
    )
