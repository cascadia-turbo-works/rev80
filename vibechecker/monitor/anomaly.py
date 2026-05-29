from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AnomalyEvent:
    trigger_time: datetime
    channel: int
    reason: str
    burst_duration_s: float


@runtime_checkable
class AnomalyHook(Protocol):
    def on_results(self,
                   results: list,
                   frame_cache) -> 'AnomalyEvent | None': ...


class NullAnomalyHook:
    """Phase 1 stub — never fires."""
    def on_results(self, results: list, frame_cache) -> 'AnomalyEvent | None':
        return None
