"""DecisionRecord + append-only JSON Lines logger for the C-lane.

Every producer-visible cut carries evidence, not the model's chain of
thought (plan section 5: "Decision/ACK ... observable evidence only").
The DecisionRecord shape here is what C proposes to A for the internal
control channel and for the operational log.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CameraConsideration:
    """One row in the decision's evidence table."""
    camera_id: str
    role: str
    healthy: bool
    guest_ready: bool | None = None
    evidence_age_s: float | None = None
    picked: bool = False
    rejection_reason: str | None = None


@dataclass
class DecisionRecord:
    """One append-only log entry, corresponding to one SessionDecision.

    Fields are the observable evidence behind a cut, in the shape
    proposed for packages/contracts on A's side.
    """
    at: float                                       # producer clock, seconds
    decision_seq: int
    mode_revision: int
    action: str                                     # TAKE / STAY / SLATE
    camera_id: str | None
    reason: str

    # transcript_span: {utterance_id, text, started_at, ended_at}
    # cue_summary:     {target_guest_ids, scope, temporal_intent, action_pre_validate}
    transcript_span: dict[str, Any] | None = None
    cue_summary: dict[str, Any] | None = None

    # Camera health table considered at decision time.
    cameras_considered: list[dict[str, Any]] = field(default_factory=list)

    # Wall-clock latencies for the pipeline (ms).
    latencies_ms: dict[str, float] = field(default_factory=dict)

    # Provenance so replayed / fixture-driven entries are distinguishable.
    source: str = "LIVE"

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)


class DecisionLogger:
    """Append-only writer. One JSON object per line; UTF-8; LF-terminated."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: DecisionRecord) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.to_json())
            f.write("\n")

    def read_all(self) -> list[dict[str, Any]]:
        """Convenience for tests. Not intended for production callers."""
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out


def record_from_session_decision(
    sd: Any,                       # SessionDecision (duck-typed to keep this module import-light)
    *,
    at: float,
    cue: Any = None,
    cameras_considered: list[CameraConsideration] | None = None,
    latencies_ms: dict[str, float] | None = None,
    source: str = "LIVE",
) -> DecisionRecord:
    """Construct a DecisionRecord from the outputs of DirectorSession."""
    transcript_span = None
    cue_summary = None
    if cue is not None:
        utt = getattr(cue, "utterance_id", "") or ""
        started = getattr(cue, "started_at", None)
        ended = getattr(cue, "ended_at", None) or getattr(cue, "created_at", None)
        text = getattr(cue, "evidence_text", "") or ""
        transcript_span = {
            "utterance_id": utt,
            "text": text,
            "started_at": started,
            "ended_at": ended,
        }
        cue_summary = {
            "target_guest_ids": list(getattr(cue, "target_guest_ids", []) or []),
            "scope": _val(getattr(cue, "scope", None)),
            "temporal_intent": _val(getattr(cue, "temporal_intent", None)),
            "action_pre_validate": _val(getattr(cue, "action", None)),
        }
    return DecisionRecord(
        at=at,
        decision_seq=int(sd.decision_seq),
        mode_revision=int(sd.mode_revision),
        action=_val(sd.action),
        camera_id=sd.camera_id,
        reason=sd.reason,
        transcript_span=transcript_span,
        cue_summary=cue_summary,
        cameras_considered=[dataclasses.asdict(c) for c in (cameras_considered or [])],
        latencies_ms=dict(latencies_ms or {}),
        source=source,
    )


def _val(x: Any) -> str:
    if x is None:
        return ""
    return x.value if hasattr(x, "value") else str(x)
