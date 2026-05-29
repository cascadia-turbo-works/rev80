from dataclasses import dataclass
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
    output_dir: Path              # where to write HDF5 files + index.sqlite
    compression: str = 'gzip'
    compression_level: int = 4
