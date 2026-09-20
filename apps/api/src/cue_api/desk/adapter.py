"""Pure translation: team-stack state and feed items to desk-UI messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DESK_CAMERAS = ("CAM-HOST", "CAM-GUEST", "CAM-WIDE")
DESK_MODES = {"AUTO": "auto", "ASSIST": "assist", "MANUAL_HOLD": "manual"}
CONTROL_MODES = {"auto": "AUTO", "assist": "ASSIST", "manual": "MANUAL_HOLD", "hold": "MANUAL_HOLD"}
REPO_ROOT = Path(__file__).resolve().parents[5]  # desk, cue_api, src, api, apps, repo
DEMO_ROSTER = REPO_ROOT / "config" / "demo_roster.json"
SEMANTIC_ROSTER = Path(__file__).resolve().parents[1] / "semantics" / "roster.json"


def desk_mode(control_mode: str | None) -> str:
    """AUTO, ASSIST and MANUAL_HOLD map one to one.

    SETUP, READY, DEGRADED and ENDED are shown as manual.
    """
    return DESK_MODES.get(str(control_mode or "").upper(), "manual")


def control_mode(desk: str) -> str | None:
    return CONTROL_MODES.get(str(desk or "").lower())


def mode_messages(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    mode = desk_mode(snapshot.get("mode"))
    return [{"type": "mode", "mode": mode}, {"type": "directing", "enabled": mode == "auto"}]


def control_message(snapshot: dict[str, Any], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    """What the page needs to call A's take and mode routes itself: revision and stream epochs."""
    epochs = {
        b["cameraId"]: b["streamEpoch"]
        for b in bindings
        if b.get("cameraId") and b.get("streamEpoch")
    }
    return {
        "type": "control",
        "eventId": snapshot.get("eventId"),
        "mode": snapshot.get("mode"),
        "modeRevision": snapshot.get("modeRevision"),
        "controlGeneration": snapshot.get("controlGeneration"),
        "liveCameraId": snapshot.get("liveCameraId"),
        "pendingDecisionId": snapshot.get("pendingDecisionId"),
        "epochs": epochs,
    }


def camera_state_messages(readiness: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One camera_state per desk camera from the compositor's readiness report."""
    slots = {
        s.get("cameraId"): s for s in ((readiness or {}).get("slots") or []) if isinstance(s, dict)
    }
    out = []
    for cam in DESK_CAMERAS:
        slot = slots.get(cam)
        if not slot:
            out.append(
                {
                    "type": "camera_state",
                    "camera": cam,
                    "ready": False,
                    "note": "No compositor report",
                }
            )
            continue
        ready = bool(slot.get("renderable"))
        age = slot.get("lastFrameAgeMs")
        if ready:
            note = f"{int(age)} ms ago" if isinstance(age, int | float) else "Ready"
        elif slot.get("videoTrackSid"):
            note = str(slot.get("state") or "stalled").replace("-", " ")
        else:
            note = "No publisher"
        out.append({"type": "camera_state", "camera": cam, "ready": ready, "note": note})
    return out


def manual_decision(camera_id: str, seq: int) -> dict[str, Any]:
    """The compositor cut to a camera and no policy decision explains it: an operator take."""
    return {
        "type": "decision",
        "record": {
            "decision_seq": seq,
            "action": "TAKE",
            "camera_id": camera_id,
            "reason": f"manual TAKE {camera_id}",
            "plain_reason": "You took the " + camera_id.replace("CAM-", "").lower() + " camera.",
            "accepted": True,
        },
    }


def decision_message(item: dict[str, Any]) -> dict[str, Any] | None:
    """A posted DecisionEvent (C's wire shape, camelCase) goes to the desk as the record itself."""
    event = item.get("event")
    if not isinstance(event, dict):
        return None
    return {"type": "decision", "record": event}


def caption_messages(item: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(item.get("text") or "").strip()
    if not text:
        return []
    final = bool(item.get("final") or item.get("speechFinal"))
    result: dict[str, Any] = {
        "text": text,
        "is_final": bool(item.get("final")),
        "speech_final": bool(item.get("speechFinal")),
    }
    if item.get("confidence") is not None:
        result["confidence"] = item["confidence"]
    if item.get("words"):
        result["words"] = item["words"]
    return [
        {"type": "caption_final" if final else "caption_provisional", "text": text},
        {"type": "deepgram_result", "result": result},
    ]


def feed_item_messages(item: dict[str, Any]) -> list[dict[str, Any]]:
    kind = item.get("kind")
    if kind == "caption":
        return caption_messages(item)
    if kind == "decision":
        message = decision_message(item)
        return [message] if message else []
    if kind == "deepgram_config":
        return [{"type": "deepgram_config", "config": item.get("config") or {}}]
    if kind == "caption_status":
        return [
            {
                "type": "caption_status",
                "connected": bool(item.get("connected")),
                "label": item.get("label"),
            }
        ]
    if kind == "latency":
        return [
            {"type": "latency", "first_ms": item.get("first_ms"), "final_ms": item.get("final_ms")}
        ]
    return []


def load_roster(
    demo_path: Path = DEMO_ROSTER, fallback_path: Path = SEMANTIC_ROSTER
) -> list[dict[str, Any]]:
    """C's frozen demo roster, else C's semantic roster. Camera comes from `camera_hint`."""
    for path in (demo_path, fallback_path):
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        guests = data.get("guests") if isinstance(data, dict) else None
        if isinstance(guests, list):
            return [g for g in guests if isinstance(g, dict)]
    return []


def roster_message(guests: list[dict[str, Any]]) -> dict[str, Any]:
    out = []
    for g in guests:
        entry: dict[str, Any] = {
            "name": g.get("name") or g.get("id"),
            "role": g.get("role") or "Guest",
        }
        if g.get("camera_hint") in DESK_CAMERAS:
            entry["camera"] = g["camera_hint"]
        out.append(entry)
    return {"type": "roster", "guests": out}


def deepgram_config_message(
    posted: dict[str, Any] | None, guests: list[dict[str, Any]]
) -> dict[str, Any]:
    keyterms: list[str] = []
    for g in guests:
        for name in [g.get("name"), *list(g.get("aliases") or [])]:
            if name and name not in keyterms:
                keyterms.append(str(name))
    config = dict((posted or {}).get("config") or {})
    config.setdefault("model", "nova-3")
    config.setdefault("keyterms", keyterms)
    return {"type": "deepgram_config", "config": config}


def head_messages(
    snapshot: dict[str, Any],
    readiness: dict[str, Any] | None,
    bindings: list[dict[str, Any]],
    guests: list[dict[str, Any]],
    deepgram_config: dict[str, Any] | None,
    caption_connected: bool,
    last_decision: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"type": "source", "source": "mic"},
        *mode_messages(snapshot),
        {
            "type": "caption_status",
            "connected": caption_connected,
            "label": "Deepgram via C's live lane"
            if caption_connected
            else "No captions yet: start C's live lane with --desk-feed",
        },
        deepgram_config_message(deepgram_config, guests),
        roster_message(guests),
        control_message(snapshot, bindings),
        *camera_state_messages(readiness),
    ]
    if last_decision:
        message = decision_message(last_decision)
        if message:
            msgs.append(message)
    return msgs


def diff_messages(
    prev: dict[str, Any] | None,
    cur: dict[str, Any],
    prev_readiness: dict[str, Any] | None,
    readiness: dict[str, Any] | None,
    prev_bindings: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    seq: int,
) -> tuple[list[dict[str, Any]], int]:
    """Control and readiness changes between ticks. Returns messages and the next manual seq."""
    msgs: list[dict[str, Any]] = []
    prev = prev or {}
    if desk_mode(prev.get("mode")) != desk_mode(cur.get("mode")):
        msgs.extend(mode_messages(cur))
    if control_message(prev, prev_bindings) != control_message(cur, bindings):
        msgs.append(control_message(cur, bindings))
    live, was = cur.get("liveCameraId"), prev.get("liveCameraId")
    if live and live != was and cur.get("pendingDecisionId") is None:
        seq += 1
        msgs.append(manual_decision(live, seq))
    # camera_state_messages handles a missing report, so "no report" to "no report" is no change.
    before = {m["camera"]: m for m in camera_state_messages(prev_readiness)}
    for m in camera_state_messages(readiness):
        if before.get(m["camera"]) != m:
            msgs.append(m)
    return msgs, seq
