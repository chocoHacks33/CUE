"""Deterministic directing policy for CUE (v3 plan section "Directing logic C owns").

`decide(cue, cameras, state, now)` is a pure function. No network, no LLM,
no globals, no time.time(). The caller passes `now` and gets back a Decision
that names the target camera (or SLATE) plus a short human reason.

Rules encoded here:
- Manual HOLD (mode=HOLD or hold_until in the future) beats every AI decision,
  including late arrivals. Safety failover from an unhealthy live camera to a
  healthy wide (or SLATE) still runs — the plan's "emergency/failure safety
  still works" clause.
- Only NOW + a single resolved target may TAKE a named guest view. FUTURE,
  PAST, NEGATED and UNCERTAIN intents never cut.
- Named TAKE requires a healthy camera whose confirmed_guest_ids includes the
  target and whose evidence_age_s is <= IDENTITY_MAX_AGE_S. Otherwise fall
  back to a healthy wide; if none, SLATE.
- role_based=True skips the identity check and uses `role_map` (guest_id ->
  camera_id). This is the disclosed fallback for when face-id is cut per plan
  stage-4 exit gate.
- scope=group -> healthy wide; otherwise stay.
- Minimum shot MIN_SHOT_S seconds, bypassed only when the incoming cue shares
  the previous decision's utterance_id (in-utterance correction).
- Cue older than CUE_LIFETIME_S seconds is rejected as stale.
- Every Decision carries a non-empty human-readable reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional


MIN_SHOT_S = 2.5
CUE_LIFETIME_S = 3.0
IDENTITY_MAX_AGE_S = 1.5


class Mode(str, Enum):
    AUTO = "AUTO"
    ASSIST = "ASSIST"
    HOLD = "HOLD"


class DecisionAction(str, Enum):
    TAKE = "TAKE"    # cut to camera_id
    STAY = "STAY"    # keep whatever is currently live
    SLATE = "SLATE"  # no healthy source; render slate card


@dataclass
class Decision:
    action: DecisionAction
    camera_id: Optional[str]
    reason: str


@dataclass
class State:
    """Caller-owned decision context, carried across calls.

    Beyond the four fields the v3 plan mentions (current camera, last cut time,
    mode, hold_until), we keep `last_utterance_id` so the same-utterance
    correction override can be evaluated deterministically here.
    """
    current_camera: Optional[str] = None
    last_cut_time: float = 0.0
    mode: Mode = Mode.AUTO
    hold_until: Optional[float] = None
    last_utterance_id: str = ""


# ----- helpers ---------------------------------------------------------------

def _val(x: Any) -> str:
    if x is None:
        return ""
    return x.value if hasattr(x, "value") else str(x)


def _healthy_wide(cameras: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    for cid, c in cameras.items():
        if c.get("role") == "wide" and c.get("healthy"):
            return cid
    return None


def _is_healthy(cameras: Mapping[str, Mapping[str, Any]], cid: Optional[str]) -> bool:
    return bool(cid and cameras.get(cid, {}).get("healthy"))


def _safe_fallback(cameras, state: State, reason: str) -> Decision:
    """Stay if current is healthy; otherwise wide; otherwise SLATE."""
    if _is_healthy(cameras, state.current_camera):
        return Decision(DecisionAction.STAY, state.current_camera, reason)
    wide = _healthy_wide(cameras)
    if wide:
        if wide == state.current_camera:
            return Decision(DecisionAction.STAY, wide, reason + "; wide already live")
        return Decision(DecisionAction.TAKE, wide,
                        reason + "; current unhealthy -> wide fallback")
    return Decision(DecisionAction.SLATE, None,
                    reason + "; no healthy view -> slate")


def _pick_named(target: str, cameras, role_based: bool,
                role_map: Mapping[str, str]) -> tuple[Optional[str], str]:
    if role_based:
        cid = role_map.get(target)
        if cid and _is_healthy(cameras, cid):
            return cid, f"role_based: {target} -> {cid}"
        return None, ""
    for cid, c in cameras.items():
        if not c.get("healthy"):
            continue
        if target not in (c.get("confirmed_guest_ids") or []):
            continue
        age = c.get("evidence_age_s", float("inf"))
        if age > IDENTITY_MAX_AGE_S:
            continue
        return cid, f"fresh identity {target} on {cid} (age {age:.2f}s)"
    return None, ""


def _propose_take(picked: Optional[str], why: str, cameras, state: State,
                  cue, now: float) -> Decision:
    if picked is None:
        return _safe_fallback(cameras, state, why or "no picked camera")
    if picked == state.current_camera:
        return Decision(DecisionAction.STAY, picked, why + " (already live)")
    # Safety exception: if the current camera is unhealthy, min-shot doesn't apply.
    if state.current_camera and not _is_healthy(cameras, state.current_camera):
        return Decision(DecisionAction.TAKE, picked,
                        why + "; current unhealthy, safety failover")
    elapsed = now - state.last_cut_time
    if elapsed < MIN_SHOT_S:
        utt = getattr(cue, "utterance_id", "") or ""
        if utt and utt == state.last_utterance_id:
            return Decision(DecisionAction.TAKE, picked,
                            why + f" (correction re-cut at {elapsed:.2f}s)")
        return Decision(DecisionAction.STAY, state.current_camera,
                        f"min shot {MIN_SHOT_S}s not met ({elapsed:.2f}s); "
                        f"held {state.current_camera}. Would have taken: {why}")
    return Decision(DecisionAction.TAKE, picked, why)


# ----- public API ------------------------------------------------------------

def decide(cue: Optional[Any],
           cameras: Mapping[str, Mapping[str, Any]],
           state: State,
           now: float,
           *,
           role_based: bool = False,
           role_map: Optional[Mapping[str, str]] = None) -> Decision:
    """Pure directing decision.

    cue     -- semantics.parser.Cue (or None); accessed via attribute lookup
               so any duck-typed object with the same field names works.
    cameras -- {camera_id: {role, healthy, epoch, confirmed_guest_ids,
                            evidence_age_s}}
    state   -- Decision context (see State).
    now     -- caller's monotonic-ish clock, seconds.
    """
    role_map = role_map or {}

    # 1. Manual HOLD wins over any AI decision. Safety failover still runs.
    holding = (state.mode == Mode.HOLD
               or (state.hold_until is not None and now < state.hold_until))
    if holding:
        return _safe_fallback(cameras, state, "manual HOLD")

    # 2. No cue -> stay if healthy, else safe fallback.
    if cue is None:
        return _safe_fallback(cameras, state, "no cue")

    # 3. Reject stale cue.
    created = float(getattr(cue, "created_at", 0.0) or 0.0)
    if created > 0 and (now - created) > CUE_LIFETIME_S:
        return _safe_fallback(cameras, state,
                              f"cue stale ({now - created:.2f}s > {CUE_LIFETIME_S}s)")

    # 4. Non-NOW temporal intents never drive a cut.
    temporal = _val(getattr(cue, "temporal_intent", None))
    if temporal != "NOW":
        return _safe_fallback(cameras, state,
                              f"temporal_intent={temporal}, not NOW")

    # 5. Group scope -> wide.
    scope = _val(getattr(cue, "scope", None))
    if scope == "group":
        wide = _healthy_wide(cameras)
        if wide:
            return _propose_take(wide, "group scope -> wide",
                                 cameras, state, cue, now)
        return _safe_fallback(cameras, state, "group scope but no healthy wide")

    # 6. Named TAKE requires exactly one resolved target.
    targets = list(getattr(cue, "target_guest_ids", []) or [])
    if len(targets) != 1:
        return _safe_fallback(cameras, state,
                              f"target count {len(targets)}, need exactly one")
    target = targets[0]

    # 7. Pick a healthy camera showing target (with fresh identity, or role_map).
    picked, why = _pick_named(target, cameras, role_based, role_map)
    if picked:
        return _propose_take(picked, why, cameras, state, cue, now)

    # 8. Fall back to wide, else SLATE.
    wide = _healthy_wide(cameras)
    if wide:
        return _propose_take(wide, f"target {target} unusable -> wide",
                             cameras, state, cue, now)
    return Decision(DecisionAction.SLATE, None,
                    f"target {target} unusable; no healthy wide -> slate")
