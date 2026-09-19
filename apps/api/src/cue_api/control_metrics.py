from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from cue_api.control_contracts import ControlLatencyMetrics, RenderCommand, RenderStatus


class ControlLatencyTracker:
    """Bounded TAKE-to-ACK timing window using the server monotonic clock."""

    def __init__(self, *, window_size: int = 200) -> None:
        if window_size < 1:
            raise ValueError("window_size must be positive")
        self._window_size = window_size
        self._issued_at: dict[str, tuple[str, float]] = {}
        self._applied_ms: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._window_size)
        )
        self._rejected_count: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def issued(self, command: RenderCommand, *, now_s: float | None = None) -> None:
        with self._lock:
            self._issued_at[command.decision_id] = (
                command.event_id,
                now_s if now_s is not None else time.monotonic(),
            )

    def acknowledged(
        self,
        decision_id: str,
        status: RenderStatus,
        *,
        now_s: float | None = None,
    ) -> float | None:
        with self._lock:
            issued = self._issued_at.pop(decision_id, None)
            if issued is None:
                return None
            event_id, started = issued
            if status is not RenderStatus.APPLIED:
                self._rejected_count[event_id] += 1
                return None
            elapsed_ms = max(
                0.0,
                ((now_s if now_s is not None else time.monotonic()) - started) * 1000,
            )
            self._applied_ms[event_id].append(elapsed_ms)
            return elapsed_ms

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]

    def snapshot(self, event_id: str) -> ControlLatencyMetrics:
        with self._lock:
            samples = list(self._applied_ms[event_id])
            return ControlLatencyMetrics(
                applied_count=len(samples),
                rejected_count=self._rejected_count[event_id],
                outstanding_count=sum(
                    1
                    for issued_event_id, _ in self._issued_at.values()
                    if issued_event_id == event_id
                ),
                p50_ms=self._percentile(samples, 0.50),
                p95_ms=self._percentile(samples, 0.95),
                maximum_ms=max(samples) if samples else None,
            )
