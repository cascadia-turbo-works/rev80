from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MonitorSession:
    session_id: str               # "{YYYY-MM-DD-HHMMSS}_{sanitized_serial}"
    start_time: datetime          # local time
    interval_s: float             # seconds between captures
    pre_buffer_frames: int        # number of frames to prepend before burst trigger
    burst_duration_s: float       # how long burst capture runs after anomaly trigger
    max_burst_s: float            # maximum burst extension cap
    session_dir: Path             # directory; session.h5 lives at session_dir/session.h5
    compression: str = 'gzip'
    compression_level: int = 4
    cooldown_enabled: bool = False
    cooldown_s: float = 0.0       # blocks new anomaly-triggered bursts for this long after one fires
    # Snapshots captured at arm time — embedded in session.h5
    acq_snapshot: dict = field(default_factory=dict)      # AcquisitionSettings.to_dict()
    channel_snapshot: dict = field(default_factory=dict)  # {ch: {name, unit, ...}}
    sensor_snapshot: dict = field(default_factory=dict)   # {sensor_id: ScopeSensor.to_dict()}

    @property
    def session_h5(self) -> Path:
        return self.session_dir / 'session.h5'


def channel_snapshot_for(config, collector) -> dict:
    """Build the per-channel snapshot embedded in `session.h5`'s metadata.

    **The single builder**, shared by the GUI's `_start_recording` and by
    headless. Both had their own copy of this dict literal and neither
    recorded the channel's role, which is the third instance of audit H-01's
    shape in the monitor path -- one rule written twice, drifting, with
    nothing asserting the copies agree.

    The role matters here because a session is read back long after the run:
    without it, the only way to tell a tachometer channel from a vibration one
    is that its capture group has no `data` dataset, which is inferring intent
    from a storage detail. A tach channel also carries its calibration, so the
    shaft speed stays re-derivable at a different `pulses_per_rev` -- the same
    reason `DataCollector.save_data` stores it in a measurement file.
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
            # Flattened with a tach_ prefix rather than nested, because HDF5
            # attrs are scalars -- the same layout save_data uses.
            for k, v in collector.tach_settings_for(ch).to_dict().items():
                entry[f'tach_{k}'] = v
        snapshot[str(ch)] = entry
    return snapshot


def sensor_snapshot_for(collector) -> dict:
    """{sensor_id: ScopeSensor.to_dict()} for every sensor in use, deduplicated.

    One entry per unique sensor however many channels share it. Both front
    ends had their own copy of this loop.
    """
    snapshot: dict = {}
    for sc in collector.scope_sensors.values():
        if sc is not None and sc.id not in snapshot:
            snapshot[sc.id] = sc.to_dict()
    return snapshot


def pre_buffer_frames_for(pre_buffer_s: float, block_s: float) -> int:
    """How many acquired frames cover `pre_buffer_s` of lead-in.

    Floors at 1: a burst with no pre-trigger context at all is never what was
    meant, and 0 would make `frame_cache[-n:]` return the whole cache.
    """
    if block_s <= 0:
        return 1
    return max(1, int(float(pre_buffer_s) / float(block_s)))


def required_cache_frames(cache_frames: int, pre_buffer_frames: int) -> int:
    """Frame-cache depth needed to serve a burst's pre-trigger window.

    **The `+ 1` is load-bearing and was missing from headless.**
    `MonitorController` slices `frame_cache[-n:]` for the pre-trigger window
    and the trigger frame then becomes `burst_frames[n]`, so a cache of
    exactly n yields n-1 true pre-trigger frames -- the trigger frame has
    taken one of the slots. Nothing reports the achieved count, so the
    shortfall is silent, which is why this is a function and not a line
    written out twice.

    Never shrinks a cache that is already larger.
    """
    return max(int(cache_frames), int(pre_buffer_frames) + 1)


def session_from(*, collector, session_id: str, interval_s: float,
                 pre_buffer_s: float, burst_duration_s: float,
                 max_burst_s: float, output_dir=None,
                 start_time=None, compression: str = 'gzip',
                 compression_level: int = 4,
                 cooldown_enabled: bool = False,
                 cooldown_s: float = 0.0) -> MonitorSession:
    """Build a `MonitorSession` from a collector and the session parameters.

    **The single constructor**, used by `gui._start_recording` and
    `headless._build_session`. They previously listed all fourteen fields
    each, and two had drifted: `max_burst_s` was a hardcoded 600.0 literal in
    both -- making the `acquisition.yaml` setting of the same name dead while
    the headless summary still printed it -- and the frame-cache sizing that
    has to match `pre_buffer_frames` differed by one (see
    `required_cache_frames`).

    `output_dir` is the *parent* directory; the session gets its own
    `session_id` subdirectory under it. None means the default data dir.

    Keyword-only on purpose: fourteen positional fields is how the two copies
    drifted without anyone noticing.
    """
    from datetime import datetime

    import rev80

    cfg = collector.config
    block_s = cfg.blocksize / cfg.samplerate if cfg.samplerate else 0.0
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
        acq_snapshot=cfg.to_dict(),
        channel_snapshot=channel_snapshot_for(cfg, collector),
        sensor_snapshot=sensor_snapshot_for(collector),
    )
