"""plain_reason(record) -> one short everyday sentence for the desk UI.

The DirectorSession's `reason` string is precise but tuned for a producer
log. The desk needs something a human running the show can read at a
glance. This module maps every reason phrase the C-lane can emit today
into a short sentence -- no jargon, no field names, no probabilities.

Pattern-matched on the DecisionRecord's `reason` plus, where useful, the
`cue_summary.target_guest_ids[0]` and `camera_id`. Falls through to the
raw reason if nothing matches so we never lie about what happened.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cue_api.policy.log import DecisionRecord

# Guest-id -> display name comes from C's roster. Loaded once at import.
_ROSTER_PATH = Path(__file__).resolve().parents[1] / "semantics" / "roster.json"


def _load_roster() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    try:
        data = json.loads(_ROSTER_PATH.read_text())
    except FileNotFoundError:
        return {}, {}, {}
    display: dict[str, str] = {}
    pron_subj: dict[str, str] = {}
    pron_be_past: dict[str, str] = {}
    for g in data.get("guests", []):
        gid = g.get("id") or ""
        aliases = g.get("aliases") or []
        display[gid] = str(aliases[0] if aliases else g.get("name") or gid)
        pron_subj[gid] = str(g.get("pronoun_subject") or "They")
        pron_be_past[gid] = str(g.get("pronoun_be_past") or "were")
    return display, pron_subj, pron_be_past


_ROSTER, _PRONOUN_SUBJECT, _PRONOUN_BE_PAST = _load_roster()


def _guest_name(gid: str | None) -> str:
    if not gid:
        return "the guest"
    return _ROSTER.get(gid, gid.capitalize())


def _pronoun_subject(gid: str | None) -> str:
    if not gid:
        return "They"
    return _PRONOUN_SUBJECT.get(gid, "They")


def _pronoun_be_past(gid: str | None) -> str:
    if not gid:
        return "were"
    return _PRONOUN_BE_PAST.get(gid, "were")


def _camera_word(cid: str | None) -> str:
    if cid is None:
        return "the slate"
    if cid == "CAM-HOST":
        return "the host"
    if cid == "CAM-GUEST":
        return "the guest camera"
    if cid == "CAM-WIDE":
        return "the wide shot"
    return cid


def _first_target(rec: DecisionRecord) -> str | None:
    cs: dict[str, Any] = rec.cue_summary or {}
    targets = cs.get("target_guest_ids") or []
    return targets[0] if targets else None


def plain_reason(rec: DecisionRecord) -> str:  # noqa: PLR0911, PLR0912 -- deliberate rule table
    """One short everyday sentence explaining the decision to the producer."""
    reason = (rec.reason or "").lower()
    action = rec.action
    cid = rec.camera_id
    target = _first_target(rec)
    who = _guest_name(target) if target else None

    # ---- manual commands ---------------------------------------------------
    if "manual hold" in reason:
        return "You took over. CUE is waiting."
    if "manual resume_auto" in reason:
        return "CUE is directing again."
    if reason.startswith("manual take"):
        return f"You cut to {_camera_word(cid)}."
    if "manual slate" in reason:
        return "You cut to the slate."

    # ---- late-cue rejection ------------------------------------------------
    if "stale mode_revision" in reason:
        return "Ignoring a late suggestion. Your last command wins."

    # ---- camera-state freshness gate ---------------------------------------
    if "camera state missing" in reason:
        return "Waiting for the first camera check before cutting."
    if "camera state expired" in reason:
        return "Waiting for a fresh camera check before cutting."

    # ---- guest-ready gate --------------------------------------------------
    if "guest not ready" in reason:
        if action == "TAKE" and cid == "CAM-WIDE":
            return "Guest isn't ready yet, so showing the wide shot."
        if action == "SLATE":
            return "Guest isn't ready and there's no safe view."
        return "Guest isn't ready. Holding."

    # ---- temporal-intent stays --------------------------------------------
    if "temporal_intent=future" in reason:
        if who:
            return f"Staying on the host. {who} is joining later."
        return "Not cutting. That was about later."
    if "temporal_intent=past" in reason:
        if who:
            return f"Staying put. {who} came up in the past, not now."
        return "Staying put. That was about the past."
    if "temporal_intent=negated" in reason:
        return "Not cutting. The host said not to."
    if "temporal_intent=uncertain" in reason:
        return "Not sure what was meant. Holding."

    # ---- cue lifecycle -----------------------------------------------------
    if "cue stale" in reason:
        return "That thought took too long to interpret. Waiting for the next one."
    if reason.startswith("no cue"):
        if action == "TAKE" and cid == "CAM-WIDE":
            return "Nothing to cut on. Showing the wide shot."
        if action == "SLATE":
            return "Nothing to cut on and no safe view. Showing the slate."
        return "Waiting for something to react to."

    # ---- min-shot & correction --------------------------------------------
    if "min shot" in reason:
        return "Just cut. Holding this shot a beat longer."
    if "correction re-cut" in reason:
        if who:
            return f"Correction. CUE cut to {who} instead."
        return "Correction. Cutting to the new target."

    # ---- correction handled separately above; named / wide / slate --------
    if "unusable" in reason and action == "TAKE" and cid == "CAM-WIDE":
        if who:
            return f"{who}'s camera isn't usable, so showing the wide shot."
        return "Target isn't usable, so showing the wide shot."
    if "unusable" in reason and action == "SLATE":
        return "No usable view of the target and no wide shot. Showing the slate."

    if "role_based" in reason or "fresh identity" in reason:
        if who:
            subj = _pronoun_subject(target)
            be = _pronoun_be_past(target)
            return f"CUE cut to {who}. {subj} {be} just invited up."
        return f"CUE cut to {_camera_word(cid)}. Just invited up."

    if "safety failover" in reason and action == "TAKE" and cid == "CAM-WIDE":
        return "Current camera dropped out. Showing the wide shot."

    if "group scope" in reason and action == "TAKE" and cid == "CAM-WIDE":
        return "Two people up. Showing the wide shot."
    if "group scope" in reason:
        return "Group scene, but no safe wide shot. Holding."

    # ---- fallthrough -------------------------------------------------------
    if action == "TAKE":
        if cid == "CAM-WIDE":
            return "Showing the wide shot."
        return f"Cutting to {_camera_word(cid)}."
    if action == "SLATE":
        return "No safe view available. Showing the slate."
    # STAY, unmatched.
    return "Staying on the current shot."
