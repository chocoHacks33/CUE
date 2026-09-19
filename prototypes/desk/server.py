"""Localhost desk prototype for the C-lane.

Standalone. Not touched by any A/B/D file. Serves one page + a WebSocket.
All events (captions, decisions, mode changes) are pushed through the
same CLane instance used in the production release path. DEEPGRAM_API_KEY
stays server-side; the browser never sees it.

Usage:
  cd apps/api && python -m pip install -e ".[dev,desk]"
  cd ../..  &&  python -m prototypes.desk.server --source fixture   # scripted
  cd ../..  &&  python -m prototypes.desk.server --source mic       # laptop mic
  # then open http://127.0.0.1:8765 in a browser.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cue_api.c_lane import CLane  # noqa: E402
from cue_api.policy.explain import plain_reason  # noqa: E402
from cue_api.policy.log import DecisionRecord  # noqa: E402

load_dotenv()

STATIC_DIR = Path(__file__).parent
INDEX_HTML = STATIC_DIR / "index.html"

# ---------------------------------------------------------------- events

def _record_payload(rec: DecisionRecord) -> dict:
    return {**dataclasses.asdict(rec), "plain_reason": plain_reason(rec)}


class Hub:
    """Broadcast helper: routes async events to every connected WebSocket."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 -- dropped client
                await self.unregister(ws)


# ---------------------------------------------------------------- parse dispatch

def _parse_fn_openai():
    """Real OpenAI-backed parse function from the release path."""
    from cue_api.semantics.parser import parse as openai_parse

    def _p(text: str) -> tuple[Any, float]:
        return openai_parse(text)
    return _p


def _parse_fn_stub():
    """Captions-only fallback: never fires a TAKE. Returns a safe HOLD Cue."""
    from cue_api.semantics.parser import (
        Action,
        Cue,
        Intent,
        Scope,
        TemporalIntent,
    )

    def _p(text: str) -> tuple[Any, float]:
        return Cue(
            target_guest_ids=[], scope=Scope.NONE, intent=Intent.NONE,
            temporal_intent=TemporalIntent.UNCERTAIN, action=Action.HOLD,
            evidence_text=text or "",
        ), 0.0
    return _p


def _directing_enabled_from_env() -> bool:
    """Only enable directing when the OpenAI release path is configured."""
    provider = os.environ.get("CUE_PROVIDER", "openai").strip().lower()
    if provider != "openai":
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    return bool(os.environ.get("CUE_MODEL"))


# ---------------------------------------------------------------- CLane bridge

@dataclasses.dataclass
class ProvisionalCarrier:
    """Assembler emits Provisional events. CLane doesn't; we tap the assembler."""
    hub: Hub
    loop: asyncio.AbstractEventLoop

    def push(self, text: str) -> None:
        payload = {"kind": "caption_provisional", "text": text}
        asyncio.run_coroutine_threadsafe(self.hub.broadcast(payload), self.loop)


def _build_lane(hub: Hub, loop: asyncio.AbstractEventLoop,
                directing_enabled: bool, source: str) -> CLane:
    def emit(rec: DecisionRecord) -> None:
        payload = {"kind": "decision", "record": _record_payload(rec),
                   "source_mode": source}
        asyncio.run_coroutine_threadsafe(hub.broadcast(payload), loop)

    parse_fn = _parse_fn_openai() if directing_enabled else _parse_fn_stub()
    return CLane(
        parse_fn=parse_fn,
        emit=emit,
        role_based=True,
        role_map={"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"},
        camera_state_max_age_s=5.0,
        initial_camera="CAM-HOST",
    )


# ---------------------------------------------------------------- FastAPI app

def build_app(source: str) -> tuple[FastAPI, dict]:
    app = FastAPI(title="CUE desk prototype (C-lane)")
    ctx: dict[str, Any] = {"source": source, "hub": Hub()}

    @app.on_event("startup")
    async def _on_startup() -> None:
        loop = asyncio.get_running_loop()
        ctx["loop"] = loop
        ctx["directing_enabled"] = _directing_enabled_from_env()
        ctx["lane"] = _build_lane(ctx["hub"], loop, ctx["directing_enabled"], source)
        # Seed a healthy camera state so a fresh session can act.
        ctx["lane"].on_camera_state(_default_cams(), now=time.monotonic())
        if source == "fixture":
            ctx["tasks"] = [asyncio.create_task(_fixture_pump(ctx))]
        elif source == "mic":
            ctx["tasks"] = [asyncio.create_task(_mic_pump(ctx))]
        else:
            ctx["tasks"] = []

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        for t in ctx.get("tasks", []):
            t.cancel()
        for t in ctx.get("tasks", []):
            with contextlib.suppress(BaseException):
                await t

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(INDEX_HTML))

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({
            "source": source,
            "directing_enabled": ctx.get("directing_enabled", False),
            "current_camera": ctx["lane"].session.state.current_camera,
        })

    @app.websocket("/ws")
    async def ws(ws: WebSocket) -> None:
        await ws.accept()
        await ctx["hub"].register(ws)
        # Send an initial state snapshot.
        await ws.send_json({
            "kind": "mode",
            "current_camera": ctx["lane"].session.state.current_camera,
            "mode": ctx["lane"].session.state.mode.value,
            "auto_paused": ctx["lane"].session.auto_paused,
            "directing_enabled": ctx["directing_enabled"],
            "source": source,
        })
        if not ctx["directing_enabled"]:
            await ws.send_json({
                "kind": "banner",
                "text": "Captions live. Directing needs the production model.",
            })
        try:
            while True:
                msg = await ws.receive_json()
                _handle_client_message(ctx["lane"], msg)
                await _push_mode(ws, ctx)
        except WebSocketDisconnect:
            pass
        finally:
            await ctx["hub"].unregister(ws)

    return app, ctx


def _handle_client_message(lane: CLane, msg: dict) -> None:
    kind = (msg or {}).get("kind", "")
    now = time.monotonic()
    if kind == "manual_take":
        cam = (msg.get("camera") or "").strip()
        if cam:
            lane.on_manual(f"TAKE {cam}", now)
    elif kind == "hold":
        lane.on_manual("HOLD", now)
    elif kind == "resume_auto":
        lane.on_manual("RESUME_AUTO", now)


async def _push_mode(ws: WebSocket, ctx: dict) -> None:
    lane: CLane = ctx["lane"]
    await ws.send_json({
        "kind": "mode",
        "current_camera": lane.session.state.current_camera,
        "mode": lane.session.state.mode.value,
        "auto_paused": lane.session.auto_paused,
        "directing_enabled": ctx["directing_enabled"],
        "source": ctx["source"],
    })


def _default_cams() -> dict[str, dict]:
    return {
        "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
        "CAM-GUEST": {"role": "guest", "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": ["sarah"], "evidence_age_s": 0.4,
                      "guest_ready": True},
        "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                      "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                      "guest_ready": True},
    }


# ---------------------------------------------------------------- fixture pump

FIXTURE_TIMELINE: list[tuple[float, str, dict | str]] = [
    # (delay_from_start_s, kind, payload)
    (0.5,  "caption_final",     {"text": "Sarah joins us after the break.",
                                 "utterance_id": "utt-1"}),
    (0.6,  "cue",               {"utterance_id": "utt-1"}),
    (3.5,  "caption_final",     {"text": "Please welcome Sarah Tan.", "utterance_id": "utt-2"}),
    (3.6,  "cue",               {"utterance_id": "utt-2"}),
    (6.2,  "caption_final",     {"text": "Sarah, could you answer that?", "utterance_id": "utt-3",
                                 "guest_healthy": False}),
    (6.3,  "cue",               {"utterance_id": "utt-3", "guest_healthy": False}),
    (7.7,  "manual",            "HOLD"),
    (7.75, "caption_final",     {"text": "Sarah, come up.", "utterance_id": "utt-4"}),
    (7.76, "cue",               {"utterance_id": "utt-4"}),
    (8.8,  "manual",            "RESUME_AUTO"),
    (11.4, "caption_final",     {"text": "Please welcome Sarah... actually, Daniel.",
                                 "utterance_id": "utt-5", "correction_to": "daniel"}),
    (11.5, "cue",               {"utterance_id": "utt-5", "correction_to": "daniel"}),
]


async def _fixture_pump(ctx: dict) -> None:
    """Replays the scripted demo timeline through CLane.

    Every emitted decision is marked source=FIXTURE on the WebSocket so
    the browser can tag it visually.
    """
    lane: CLane = ctx["lane"]
    hub: Hub = ctx["hub"]
    from cue_api.semantics.parser import (  # local import to keep top clean
        Action,
        Cue,
        Intent,
        Scope,
        TemporalIntent,
    )

    def _cue_for(text: str, utt_id: str, correction_to: str | None = None) -> Cue:
        t = text.lower()
        if correction_to:
            return Cue(
                target_guest_ids=[correction_to], scope=Scope.SINGLE,
                intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
                action=Action.SHOW, evidence_text=text,
                utterance_id=utt_id, created_at=time.monotonic(),
            )
        if "after the break" in t or "joins us" in t:
            return Cue(
                target_guest_ids=["sarah"], scope=Scope.SINGLE,
                intent=Intent.MENTION, temporal_intent=TemporalIntent.FUTURE,
                action=Action.HOLD, evidence_text=text,
                utterance_id=utt_id, created_at=time.monotonic(),
            )
        return Cue(
            target_guest_ids=["sarah"], scope=Scope.SINGLE,
            intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
            action=Action.SHOW, evidence_text=text,
            utterance_id=utt_id, created_at=time.monotonic(),
        )

    started = time.monotonic()
    for delay, kind, payload in FIXTURE_TIMELINE:
        wait = started + delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        if kind == "caption_final":
            assert isinstance(payload, dict)
            await hub.broadcast({
                "kind": "caption_final",
                "text": payload["text"],
                "utterance_id": payload.get("utterance_id", ""),
                "source": "FIXTURE",
            })
            if payload.get("guest_healthy") is False:
                cams = _default_cams()
                cams["CAM-GUEST"]["healthy"] = False
                lane.on_camera_state(cams, now=time.monotonic())
        elif kind == "cue":
            assert isinstance(payload, dict)
            # Reuse the previously broadcast text.
            text = next(
                (p["text"] for d, k, p in FIXTURE_TIMELINE
                 if k == "caption_final" and isinstance(p, dict)
                 and p.get("utterance_id") == payload.get("utterance_id")),
                "",
            )
            cue = _cue_for(text, payload.get("utterance_id", ""),
                           payload.get("correction_to"))
            cue.mode_revision = lane.session.mode_revision
            # Feed directly to the session (skip queue) so the fixture
            # is deterministic irrespective of any live parser latency.
            sd = lane.session.on_cue(
                cue, ctx["last_cams"] if "last_cams" in ctx else _default_cams(),
                time.monotonic(),
                role_based=True,
                role_map={"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"},
            )
            from cue_api.policy.log import record_from_session_decision
            rec = record_from_session_decision(
                sd, at=time.monotonic(), cue=cue,
                cameras_considered=[], source="FIXTURE",
            )
            await hub.broadcast({"kind": "decision", "record": _record_payload(rec),
                                 "source_mode": "fixture"})
        elif kind == "manual":
            assert isinstance(payload, str)
            lane.on_manual(payload, time.monotonic())
        # Keep the last camera state stamped for the cue path.
        ctx["last_cams"] = _default_cams()


# ---------------------------------------------------------------- mic pump (deferred imports)

async def _mic_pump(ctx: dict) -> None:  # pragma: no cover -- requires a live mic + Deepgram key
    """Laptop mic -> Deepgram Listen v1 -> CLane. Adapted from the booth-demo."""
    hub: Hub = ctx["hub"]
    lane: CLane = ctx["lane"]
    loop = ctx["loop"]

    if not os.environ.get("DEEPGRAM_API_KEY"):
        await hub.broadcast({
            "kind": "banner",
            "text": "No DEEPGRAM_API_KEY. Captions are off. Set it in .env and restart.",
        })
        return

    import queue as _queue

    import sounddevice as sd
    from deepgram import DeepgramClient
    from deepgram.core.events import EventType

    audio_q: _queue.Queue = _queue.Queue(maxsize=64)

    def audio_cb(indata, _frames, _time_info, _status):
        try:
            audio_q.put_nowait(bytes(indata))
        except _queue.Full:
            pass

    dg_client = DeepgramClient()
    connect_kwargs = {
        "model": "nova-3", "language": "en-US",
        "encoding": "linear16", "sample_rate": "16000", "channels": "1",
        "smart_format": "true", "interim_results": "true",
        "endpointing": "300", "utterance_end_ms": "1000", "vad_events": "true",
    }
    keyterms = _roster_keyterms()
    if keyterms:
        connect_kwargs["keyterm"] = keyterms

    def on_message(message, **_kw):
        payload = message.model_dump()
        payload["audio_epoch"] = 1
        # Push a caption event first for the UI, then feed the lane.
        if payload.get("type") == "Results":
            alts = (payload.get("channel") or {}).get("alternatives") or [{}]
            text = alts[0].get("transcript") or ""
            if text:
                asyncio.run_coroutine_threadsafe(
                    hub.broadcast({
                        "kind": ("caption_final" if payload.get("is_final")
                                 else "caption_provisional"),
                        "text": text,
                        "source": "LIVE",
                    }),
                    loop,
                )
        # Feed the lane on the main loop so its state stays single-threaded.
        loop.call_soon_threadsafe(
            lane.on_transcript_message, payload, time.monotonic(),
        )

    with dg_client.listen.v1.connect(**connect_kwargs) as connection:
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.ERROR,
                      lambda err, **_kw: loop.call_soon_threadsafe(
                          asyncio.create_task,
                          hub.broadcast({"kind": "banner",
                                         "text": f"Deepgram error: {type(err).__name__}"}),
                      ))
        connection.start_listening()

        with sd.RawInputStream(
            samplerate=16000, blocksize=1600, dtype="int16",
            channels=1, callback=audio_cb,
        ):
            while True:
                # Ship audio chunks; also tick the lane so timeouts fire.
                try:
                    chunk = audio_q.get(timeout=0.1)
                except _queue.Empty:
                    chunk = None
                if chunk is not None:
                    try:
                        connection.send_media(chunk)
                    except Exception:  # noqa: BLE001 -- socket closed mid-send is not fatal
                        break
                lane.tick(time.monotonic())
                await asyncio.sleep(0)


def _roster_keyterms() -> list[str]:
    """Names + aliases from roster.json for Deepgram nova-3 keyterm boost."""
    roster_path = _SRC / "cue_api" / "semantics" / "roster.json"
    terms: set[str] = set()
    if roster_path.exists():
        data = json.loads(roster_path.read_text())
        for g in data.get("guests", []):
            terms.add(g.get("name", ""))
            for a in g.get("aliases", []) or []:
                terms.add(a)
    return sorted(t for t in terms if t)


# ---------------------------------------------------------------- entrypoint

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="CUE desk prototype (localhost).")
    ap.add_argument("--source", choices=("mic", "fixture"), default="fixture",
                    help="mic: live captions from the laptop mic; "
                         "fixture: replay the scripted demo timeline.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)

    app, _ctx = build_app(args.source)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
