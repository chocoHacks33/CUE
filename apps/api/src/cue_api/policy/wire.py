"""Wire adapter for C-lane decisions -> A's control transport shape.

C's DecisionRecord is a dataclass optimised for internal logging. A's
existing API models are pydantic BaseModels with an alias generator that
serialises snake_case -> camelCase, and every top-level payload carries a
``contractVersion`` field. This module bridges the two so decisions can
cross the wire in a shape A's client (D's Mac browser) can consume
without a per-field translation table.

Kept in cue_api.policy (C-owned) so no A/B/D file changes are required.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from cue_api.contracts import CONTRACT_VERSION
from cue_api.policy.explain import plain_reason
from cue_api.policy.log import DecisionRecord


class _Wire(BaseModel):
    """Base: camelCase on the wire, snake_case in Python (matches A's contracts.py)."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WireTranscriptSpan(_Wire):
    utterance_id: str
    text: str
    started_at: float | None = None
    ended_at: float | None = None


class WireCueSummary(_Wire):
    target_guest_ids: list[str]
    scope: str
    temporal_intent: str
    action_pre_validate: str


class WireCameraConsidered(_Wire):
    camera_id: str
    role: str
    healthy: bool
    guest_ready: bool | None = None
    evidence_age_s: float | None = None
    picked: bool = False
    rejection_reason: str | None = None


class DecisionEvent(_Wire):
    """One control-transport message carrying a C-lane decision.

    Field names match A's convention (camelCase on the wire) and a
    contractVersion is included so the client can gate on schema drift.
    ``source`` is exactly "LIVE" or "FIXTURE" — the fixture cue producer
    always emits "FIXTURE". ``identity`` is "ROLE_BASED" or "VERIFIED"
    per the DecisionRecord it was adapted from.

    NOTE: adding ``identity`` to the wire is a schema extension. It is
    additive (default "ROLE_BASED") so a client that ignores the field
    still works. A: please confirm you accept this on the wire, or ask
    me to strip it in ``to_wire`` — the field stays on my record either
    way. See docs/results/C-stage4.md open requests.
    """
    contract_version: str = CONTRACT_VERSION
    kind: Literal["decision"] = "decision"
    at: float
    decision_seq: int
    mode_revision: int
    action: str
    camera_id: str | None
    reason: str
    plain_reason: str
    transcript_span: WireTranscriptSpan | None = None
    cue_summary: WireCueSummary | None = None
    cameras_considered: list[WireCameraConsidered] = []
    latencies_ms: dict[str, float] = {}
    identity: Literal["ROLE_BASED", "VERIFIED"] = "ROLE_BASED"
    source: Literal["LIVE", "FIXTURE"] = "LIVE"


def to_wire(record: DecisionRecord, *, source_override: str | None = None) -> DecisionEvent:
    """Adapt a DecisionRecord into the A-facing DecisionEvent envelope."""
    ts = _adapt_transcript_span(record.transcript_span)
    cs = _adapt_cue_summary(record.cue_summary)
    cams = [_adapt_camera(c) for c in (record.cameras_considered or [])]
    source: str = source_override or record.source or "LIVE"
    if source not in ("LIVE", "FIXTURE"):
        source = "LIVE"
    identity = getattr(record, "identity", "ROLE_BASED")
    if identity not in ("ROLE_BASED", "VERIFIED"):
        identity = "ROLE_BASED"
    return DecisionEvent(
        at=record.at,
        decision_seq=record.decision_seq,
        mode_revision=record.mode_revision,
        action=record.action,
        camera_id=record.camera_id,
        reason=record.reason,
        plain_reason=plain_reason(record),
        transcript_span=ts,
        cue_summary=cs,
        cameras_considered=cams,
        latencies_ms=dict(record.latencies_ms or {}),
        identity=identity,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
    )


def to_wire_json(record: DecisionRecord, *, source_override: str | None = None) -> str:
    """Serialise a DecisionRecord directly to A-shaped JSON (camelCase)."""
    return to_wire(record, source_override=source_override).model_dump_json(by_alias=True)


# ------------------------------------------------------------------ helpers

def _adapt_transcript_span(d: dict[str, Any] | None) -> WireTranscriptSpan | None:
    if not d:
        return None
    return WireTranscriptSpan(
        utterance_id=str(d.get("utterance_id", "") or ""),
        text=str(d.get("text", "") or ""),
        started_at=_maybe_float(d.get("started_at")),
        ended_at=_maybe_float(d.get("ended_at")),
    )


def _adapt_cue_summary(d: dict[str, Any] | None) -> WireCueSummary | None:
    if not d:
        return None
    return WireCueSummary(
        target_guest_ids=list(d.get("target_guest_ids") or []),
        scope=str(d.get("scope", "") or ""),
        temporal_intent=str(d.get("temporal_intent", "") or ""),
        action_pre_validate=str(d.get("action_pre_validate", "") or ""),
    )


def _adapt_camera(d: dict[str, Any]) -> WireCameraConsidered:
    return WireCameraConsidered(
        camera_id=str(d.get("camera_id", "")),
        role=str(d.get("role", "")),
        healthy=bool(d.get("healthy", False)),
        guest_ready=d.get("guest_ready"),
        evidence_age_s=_maybe_float(d.get("evidence_age_s")),
        picked=bool(d.get("picked", False)),
        rejection_reason=d.get("rejection_reason"),
    )


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
