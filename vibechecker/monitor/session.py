from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MonitorSession:
    session_id: str               # "{YYYY-MM-DD-HHMMSS}_{sanitized_serial}"
    start_time: datetime          # UTC
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
