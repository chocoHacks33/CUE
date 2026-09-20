"""The desk socket and the feed route. Installed once from main.py."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status

from cue_api.contracts import ReceiverRole
from cue_api.desk import adapter
from cue_api.desk.feed import DeskFeedStore

log = logging.getLogger("cue.desk")
TICK_S = 0.25
AUTH_TIMEOUT_S = 5.0


def _json(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    if isinstance(model, dict):
        return model
    dump = getattr(model, "model_dump", None)
    if dump is not None:
        return dump(mode="json", by_alias=True)
    return dict(vars(model))


def _bindings_json(bindings: list[Any]) -> list[dict[str, Any]]:
    out = []
    for b in bindings:
        camera = getattr(b, "camera_id", None)
        epoch = getattr(b, "stream_epoch", None)
        if camera is not None and epoch is not None:
            out.append(
                {"cameraId": str(getattr(camera, "value", camera)), "streamEpoch": int(epoch)}
            )
    return out


def install_desk(
    app: FastAPI,
    *,
    control_store: Any,
    readiness: Any,
    admissions: Any,
    receiver_issuer: Any,
    livekit_url: str,
    require_producer: Callable[[str | None], None],
    feed: DeskFeedStore | None = None,
) -> DeskFeedStore:
    store = feed or DeskFeedStore()

    @app.post("/api/v1/events/{event_id}/desk/feed", status_code=status.HTTP_202_ACCEPTED)
    async def post_feed(
        event_id: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_producer(x_cue_producer_secret)
        items = payload if isinstance(payload, list) else [payload]
        accepted = sum(
            1 for item in items if isinstance(item, dict) and store.publish(event_id, item)
        )
        return {"accepted": accepted, "rejected": len(items) - accepted}

    @app.websocket("/ws")
    async def desk_socket(ws: WebSocket) -> None:
        await ws.accept()
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_S))
        except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            await ws.close(code=4401, reason="auth first")
            return
        event_id = str((first or {}).get("eventId") or "hackmit-demo")
        try:
            if (first or {}).get("type") != "auth":
                raise HTTPException(status_code=401, detail="auth first")
            require_producer(str((first or {}).get("secret") or ""))
        except HTTPException:
            await ws.close(code=4401, reason="producer secret required")
            return

        try:
            issued = receiver_issuer.issue(event_id, ReceiverRole.OBSERVER, "desk")
            await ws.send_json(
                {
                    "type": "livekit",
                    "serverUrl": livekit_url,
                    "participantToken": issued.token,
                    "identity": issued.participant_identity,
                    "roomName": issued.room_name,
                    "expiresInSeconds": issued.expires_in_seconds,
                }
            )
        except Exception as error:  # noqa: BLE001 -- the desk still works without tiles
            await ws.send_json({"type": "livekit", "error": f"{type(error).__name__}: {error}"})

        guests = adapter.load_roster()
        feed_state = store.feed(event_id)
        snapshot = _json(control_store.snapshot(event_id)) or {}
        readiness_json = _json(readiness.current(event_id))
        bindings = _bindings_json(admissions.list_bindings(event_id))
        last_decision = feed_state.decisions[-1] if feed_state.decisions else None
        for message in adapter.head_messages(
            snapshot,
            readiness_json,
            bindings,
            guests,
            feed_state.deepgram_config,
            store.caption_connected(event_id),
            last_decision,
        ):
            await ws.send_json(message)

        handle = store.subscribe(event_id)
        stop = asyncio.Event()

        async def ticker() -> None:
            prev, prev_readiness, prev_bindings = snapshot, readiness_json, bindings
            seq = 0
            connected_before = store.caption_connected(event_id)
            while not stop.is_set():
                await asyncio.sleep(TICK_S)
                try:
                    cur = _json(control_store.snapshot(event_id)) or {}
                    cur_readiness = _json(readiness.current(event_id))
                    cur_bindings = _bindings_json(admissions.list_bindings(event_id))
                except Exception as error:  # noqa: BLE001
                    log.debug("desk tick failed: %s", error)
                    continue
                msgs, seq = adapter.diff_messages(
                    prev, cur, prev_readiness, cur_readiness, prev_bindings, cur_bindings, seq
                )
                connected_now = store.caption_connected(event_id)
                if connected_now != connected_before:
                    msgs.append(
                        {
                            "type": "caption_status",
                            "connected": connected_now,
                            "label": "Deepgram via C's live lane"
                            if connected_now
                            else "Captions stopped",
                        }
                    )
                    connected_before = connected_now
                for message in msgs:
                    await ws.send_json(message)
                prev, prev_readiness, prev_bindings = cur, cur_readiness, cur_bindings

        async def forward_feed() -> None:
            _loop, queue = handle
            while not stop.is_set():
                item = await queue.get()
                for message in adapter.feed_item_messages(item):
                    await ws.send_json(message)

        tasks = [asyncio.create_task(ticker()), asyncio.create_task(forward_feed())]
        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                t = msg.get("type")
                if t == "rate":
                    store.publish(
                        event_id,
                        {
                            "kind": "rating",
                            "decisionSeq": msg.get("decision_seq"),
                            "right": msg.get("right"),
                        },
                    )
                elif t in ("manual_take", "set_mode", "accept_suggestion"):
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": (
                                f"{t} goes through the HTTP routes with the producer "
                                "secret; the desk page does that itself"
                            ),
                        }
                    )
                elif t == "skip_suggestion":
                    pass
                elif t == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as error:  # noqa: BLE001
            log.debug("desk socket closed: %s", error)
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            store.unsubscribe(event_id, handle)

    app.state.desk_feed = store
    return store
