"""D's desk adapter: pure translation, the feed store, and the socket over a bare app with fakes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cue_api.desk import adapter
from cue_api.desk.feed import DeskFeedStore
from cue_api.desk.feed_client import DeskFeedSender, caption_from_deepgram
from cue_api.desk.routes import install_desk

EVENT = "hackmit-demo"


def snapshot(**over):
    base = {
        "eventId": EVENT,
        "controlGeneration": "gen-1",
        "mode": "ASSIST",
        "modeRevision": 4,
        "decisionSequence": 2,
        "liveCameraId": "CAM-HOST",
        "liveStreamEpoch": 1,
        "pendingDecisionId": None,
    }
    base.update(over)
    return base


def readiness(host=True, guest=True, wide=False):
    def slot(cam, ok):
        return {
            "cameraId": cam,
            "renderable": ok,
            "videoTrackSid": f"TR_{cam}" if ok or cam != "CAM-WIDE" else None,
            "lastFrameAgeMs": 33 if ok else 2400,
            "state": "video-ready" if ok else "stalled",
            "decoded": ok,
            "framesProgressing": ok,
        }

    return {
        "reportedAtMs": 1000,
        "slots": [slot("CAM-HOST", host), slot("CAM-GUEST", guest), slot("CAM-WIDE", wide)],
    }


# ---------------------------------------------------------------- pure


def test_modes_map_both_ways():
    assert [
        adapter.desk_mode(m) for m in ("AUTO", "ASSIST", "MANUAL_HOLD", "SETUP", "ENDED", None)
    ] == ["auto", "assist", "manual", "manual", "manual", "manual"]
    assert [adapter.control_mode(m) for m in ("auto", "assist", "manual", "hold", "x")] == [
        "AUTO",
        "ASSIST",
        "MANUAL_HOLD",
        "MANUAL_HOLD",
        None,
    ]


def test_camera_state_from_readiness_and_without_a_report():
    states = {m["camera"]: m for m in adapter.camera_state_messages(readiness())}
    assert states["CAM-HOST"]["ready"] and "ms ago" in states["CAM-HOST"]["note"]
    assert not states["CAM-WIDE"]["ready"] and states["CAM-WIDE"]["note"] == "No publisher"
    assert all(
        not m["ready"] and m["note"] == "No compositor report"
        for m in adapter.camera_state_messages(None)
    )


def test_captions_and_decisions_from_feed_items():
    prov = adapter.feed_item_messages({"kind": "caption", "text": "Sarah, please", "final": False})
    assert [m["type"] for m in prov] == ["caption_provisional", "deepgram_result"]
    fin = adapter.feed_item_messages(
        {"kind": "caption", "text": "Sarah, please come up.", "final": True, "confidence": 0.93}
    )
    assert fin[0] == {"type": "caption_final", "text": "Sarah, please come up."}
    assert fin[1]["result"]["confidence"] == 0.93 and fin[1]["result"]["is_final"] is True
    event = {
        "decisionSeq": 9,
        "action": "TAKE",
        "cameraId": "CAM-GUEST",
        "reason": "policy",
        "plainReason": "She was invited up.",
    }
    assert adapter.feed_item_messages({"kind": "decision", "event": event}) == [
        {"type": "decision", "record": event}
    ]
    assert adapter.feed_item_messages({"kind": "caption", "text": "   "}) == []


def test_diff_reports_mode_control_manual_take_and_camera_changes():
    a, b = snapshot(), snapshot(mode="MANUAL_HOLD", liveCameraId="CAM-GUEST", modeRevision=5)
    msgs, seq = adapter.diff_messages(
        a,
        b,
        readiness(),
        readiness(wide=True),
        [{"cameraId": "CAM-HOST", "streamEpoch": 1}],
        [{"cameraId": "CAM-HOST", "streamEpoch": 2}],
        0,
    )
    types = [m["type"] for m in msgs]
    assert types[:2] == ["mode", "directing"] and "control" in types
    manual = next(m for m in msgs if m["type"] == "decision")["record"]
    assert manual["camera_id"] == "CAM-GUEST" and manual["reason"].startswith("manual") and seq == 1
    assert [m["camera"] for m in msgs if m["type"] == "camera_state"] == ["CAM-WIDE"]
    # A live change while a policy render is pending is not an operator take.
    msgs, seq = adapter.diff_messages(
        b, snapshot(liveCameraId="CAM-WIDE", pendingDecisionId="d-1"), None, None, [], [], seq
    )
    assert not [m for m in msgs if m["type"] == "decision"] and seq == 1


def test_roster_comes_from_the_frozen_demo_roster_with_cameras():
    guests = adapter.load_roster()
    assert guests and any(g.get("camera_hint") for g in guests)
    roster = adapter.roster_message(guests)
    sarah = next(g for g in roster["guests"] if g["name"] == "Sarah Tan")
    assert sarah["camera"] == "CAM-GUEST"
    config = adapter.deepgram_config_message(None, guests)["config"]
    assert (
        config["model"] == "nova-3"
        and "Sarah Tan" in config["keyterms"]
        and "Ms Tan" in config["keyterms"]
    )


def test_feed_store_is_bounded_and_tracks_caption_liveness():
    store = DeskFeedStore()
    assert store.publish(EVENT, {"kind": "nope"}) is False
    for i in range(250):
        store.publish(EVENT, {"kind": "caption", "text": f"c{i}", "final": True}, now=100.0)
    assert len(store.feed(EVENT).captions) == 200
    assert store.caption_connected(EVENT, now=105.0) and not store.caption_connected(
        EVENT, now=120.0
    )
    store.publish(EVENT, {"kind": "caption_status", "connected": False})
    assert not store.caption_connected(EVENT, now=101.0)


def test_caption_from_deepgram_and_sender_posts_wire_json():
    frame = {
        "type": "Results",
        "is_final": True,
        "speech_final": True,
        "channel": {
            "alternatives": [
                {
                    "transcript": " Please welcome Sarah. ",
                    "confidence": 0.9,
                    "words": [
                        {
                            "word": "please",
                            "punctuated_word": "Please",
                            "confidence": 0.99,
                            "start": 0.1,
                        }
                    ],
                }
            ]
        },
    }
    item = caption_from_deepgram(frame)
    assert (
        item["text"] == "Please welcome Sarah."
        and item["final"]
        and item["speechFinal"]
        and item["confidence"] == 0.9
    )
    assert item["words"] == [{"word": "please", "punctuated_word": "Please", "confidence": 0.99}]
    assert caption_from_deepgram({"type": "UtteranceEnd"}) is None

    posted = []
    inner = []

    class Feed:
        def post(self, item):
            posted.append(item)

    class Inner:
        def send(self, event, *, decision_seq):
            inner.append(decision_seq)

    class Event:
        def model_dump_json(self, by_alias=True):
            return json.dumps({"decisionSeq": 3, "action": "TAKE", "cameraId": "CAM-GUEST"})

    DeskFeedSender(Feed(), Inner()).send(Event(), decision_seq=3)
    assert (
        inner == [3]
        and posted[0]["kind"] == "decision"
        and posted[0]["event"]["cameraId"] == "CAM-GUEST"
    )


# ---------------------------------------------------------------- socket


class FakeControl:
    def __init__(self):
        self.snap = snapshot()

    def snapshot(self, event_id):
        return dict(self.snap)


class FakeReadiness:
    def __init__(self):
        self.report = readiness()

    def current(self, event_id):
        return self.report


class FakeAdmissions:
    def list_bindings(self, event_id):
        return [
            SimpleNamespace(camera_id="CAM-HOST", stream_epoch=1),
            SimpleNamespace(camera_id="CAM-GUEST", stream_epoch=3),
        ]


class FakeIssuer:
    def issue(self, event_id, role, display_name):
        assert role.value == "OBSERVER" and display_name == "desk"
        return SimpleNamespace(
            token="tok", participant_identity="desk-1", room_name=event_id, expires_in_seconds=600
        )


def require_producer(secret):
    if secret != "prod":
        raise HTTPException(status_code=401, detail="producer secret required")


@pytest.fixture
def desk():
    app = FastAPI()
    control, ready = FakeControl(), FakeReadiness()
    store = install_desk(
        app,
        control_store=control,
        readiness=ready,
        admissions=FakeAdmissions(),
        receiver_issuer=FakeIssuer(),
        livekit_url="wss://lk.example",
        require_producer=require_producer,
    )
    return TestClient(app), control, ready, store


def drain_types(ws, count):
    return [ws.receive_json()["type"] for _ in range(count)]


def test_socket_refuses_without_the_producer_secret(desk):
    client, *_ = desk
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "secret": "wrong", "eventId": EVENT})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401


def test_socket_sends_the_head_then_live_changes_and_feed_items(desk):
    client, control, ready, store = desk
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "secret": "prod", "eventId": EVENT})
        first = ws.receive_json()
        assert (
            first["type"] == "livekit"
            and first["participantToken"] == "tok"
            and first["serverUrl"] == "wss://lk.example"
        )
        head = [ws.receive_json() for _ in range(10)]
        types = [m["type"] for m in head]
        assert types == [
            "source",
            "mode",
            "directing",
            "caption_status",
            "deepgram_config",
            "roster",
            "control",
            "camera_state",
            "camera_state",
            "camera_state",
        ]
        assert next(m for m in head if m["type"] == "control")["epochs"] == {
            "CAM-HOST": 1,
            "CAM-GUEST": 3,
        }
        assert next(m for m in head if m["type"] == "mode")["mode"] == "assist"

        client.post(
            f"/api/v1/events/{EVENT}/desk/feed",
            json=[{"kind": "caption", "text": "Sarah, please come up.", "final": True}],
            headers={"X-CUE-Producer-Secret": "prod"},
        )
        got = [ws.receive_json() for _ in range(2)]
        assert (
            got[0] == {"type": "caption_final", "text": "Sarah, please come up."}
            and got[1]["type"] == "deepgram_result"
        )

        control.snap = snapshot(mode="AUTO", liveCameraId="CAM-GUEST", modeRevision=5)
        ready.report = readiness(wide=True)
        seen = {}
        for _ in range(6):
            m = ws.receive_json()
            seen.setdefault(m["type"], []).append(m)
            if (
                "camera_state" in seen
                and "decision" in seen
                and "mode" in seen
                and "control" in seen
            ):
                break
        assert seen["mode"][0]["mode"] == "auto" and seen["control"][0]["modeRevision"] == 5
        assert seen["decision"][0]["record"]["camera_id"] == "CAM-GUEST"
        assert seen["camera_state"][0]["camera"] == "CAM-WIDE" and seen["camera_state"][0]["ready"]

        ws.send_json({"type": "rate", "decision_seq": 1, "right": True})
        ws.send_json({"type": "manual_take", "camera": "CAM-HOST"})
        # The posted caption also flips caption liveness, so a caption_status may precede the reply.
        replies = [ws.receive_json() for _ in range(3)]
        error = next(m for m in replies if m["type"] == "error")
        assert "HTTP routes" in error["error"]
        assert all(m["type"] in ("error", "caption_status") for m in replies)
    assert store.feed(EVENT).ratings[-1]["right"] is True


def test_feed_route_requires_the_producer_secret_and_counts(desk):
    client, *_ = desk
    assert (
        client.post(
            f"/api/v1/events/{EVENT}/desk/feed", json={"kind": "caption", "text": "x"}
        ).status_code
        == 401
    )
    r = client.post(
        f"/api/v1/events/{EVENT}/desk/feed",
        json=[{"kind": "caption", "text": "x", "final": True}, {"kind": "bogus"}],
        headers={"X-CUE-Producer-Secret": "prod"},
    )
    assert r.status_code == 202 and r.json() == {"accepted": 1, "rejected": 1}


def test_no_report_to_no_report_emits_no_camera_state():
    msgs, _ = adapter.diff_messages(snapshot(), snapshot(), None, None, [], [], 0)
    assert msgs == []
    msgs, _ = adapter.diff_messages(snapshot(), snapshot(), None, readiness(), [], [], 0)
    assert [m["camera"] for m in msgs if m["type"] == "camera_state"] == [
        "CAM-HOST",
        "CAM-GUEST",
        "CAM-WIDE",
    ]
