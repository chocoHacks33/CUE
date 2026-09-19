"""Booth demo: laptop mic -> Deepgram streaming -> assembler -> Cue -> decide -> live TUI.

Dev-only. This is NOT the release path. It exists so C can drive the whole
lane from a real microphone during the booth, with the Ollama fallback
handling semantic interpretation when the OpenAI key is not on this
machine. See docs/results/C-stage0.md for the provider policy.

Windows-focused: uses msvcrt for keypresses. On macOS/Linux keys will
simply do nothing (mic + Deepgram + display still work). No dependency
on a specific OS beyond that.

Deps (installed via the "demo" extra in apps/api/pyproject.toml):
  deepgram-sdk>=7,<8   -- listen.v1 WebSocket streaming (SDK v7 API)
  rich>=13,<15         -- live terminal UI
  sounddevice>=0.4,<1  -- PortAudio-backed mic capture; installs cleanly on
                          Windows via wheels

Docs consulted for the exact SDK call names (verified 2026-09-19):
  Live streaming:   https://developers.deepgram.com/docs/live-streaming-audio
  Interim results:  https://developers.deepgram.com/docs/interim-results
  UtteranceEnd:     https://developers.deepgram.com/docs/utterance-end
  Endpointing:      https://developers.deepgram.com/docs/endpointing
  Python SDK:       https://github.com/deepgram/deepgram-python-sdk (v7 README)

Command to start (from repo root, apps/api's venv activated):
  python scripts/live_demo.py

Flags:
  --simulate "text"   Skip mic and Deepgram; feed one FinalUtterance
                      through the parser and director. Useful for
                      validating the semantic + directing path without
                      speaking. Exits after one decision.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.request
from dataclasses import replace
from pathlib import Path

# Load .env so CUE_PROVIDER / CUE_MODEL / DEEPGRAM_API_KEY are visible.
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cue_api.policy.director import (
    Decision,
    DecisionAction,
    Mode,
    State,
    decide,
)
from cue_api.semantics.parser import Cue
from cue_api.speech.assembler import (
    Assembler,
    Event,
    FinalUtterance,
    Provisional,
)

PROVIDER = os.environ.get("CUE_PROVIDER", "openai").strip().lower()
CUE_MODEL = os.environ.get("CUE_MODEL", "").strip()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")

ROLE_MAP = {"sarah": "CAM-GUEST", "daniel": "CAM-GUEST"}


# ---------------------------------------------------------------- cameras / state

def make_cameras(guest_ready: bool) -> dict[str, dict]:
    """Fake state matching the shape decide() expects. All healthy; role_based."""
    return {
        "CAM-HOST": {
            "role": "host", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0, "guest_ready": True,
        },
        "CAM-GUEST": {
            "role": "guest", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0,
            "guest_ready": guest_ready,
        },
        "CAM-WIDE": {
            "role": "wide", "healthy": True, "epoch": 1,
            "confirmed_guest_ids": [], "evidence_age_s": 999.0, "guest_ready": True,
        },
    }


# ---------------------------------------------------------------- interpret dispatch

def interpret(text: str, utt_id: str, created_at: float) -> Cue:
    if PROVIDER == "ollama":
        return _interpret_via_ollama(text, utt_id, created_at)
    return _interpret_via_openai(text, utt_id, created_at)


def _interpret_via_openai(text: str, utt_id: str, created_at: float) -> Cue:
    from cue_api.semantics.parser import parse
    cue, _ = parse(text)
    cue.utterance_id = utt_id
    cue.created_at = created_at
    return cue


def _interpret_via_ollama(text: str, utt_id: str, created_at: float) -> Cue:
    """Route through scripts/ollama_parser (fast mode) so booth and bench
    share the same code path and prompt-prefix cache lookups.
    """
    if not CUE_MODEL:
        raise RuntimeError("CUE_MODEL is empty but CUE_PROVIDER=ollama")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ollama_parser import parse_via_ollama
    cue, _ms, _tokens = parse_via_ollama(text, CUE_MODEL, fast=True)
    cue.utterance_id = utt_id
    cue.created_at = created_at
    return cue


# ---------------------------------------------------------------- roster keyterms

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


# ---------------------------------------------------------------- rich display

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


class DemoView:
    """Owns the mutable display state and knows how to render it."""

    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self.provisional = ""
        self.final_text = ""
        self.temporal = ""
        self.target = ""
        self.evidence = ""
        self.decision_label = "(waiting)"
        self.decision_style = "white"
        self.camera_id = ""
        self.reason = "listening..."
        self.asr_ms: float | None = None
        self.cue_ms: float | None = None
        self.total_ms: float | None = None
        self.guest_ready = True
        self.mode = Mode.AUTO

    def set_decision(self, d: Decision) -> None:
        self.decision_label, self.decision_style = _label_and_style(d)
        self.camera_id = d.camera_id or ""
        self.reason = d.reason

    def render(self) -> Panel:
        header = Text.from_markup(
            f"[bold]CUE booth demo[/bold]  "
            f"provider=[cyan]{self.provider}[/cyan]  "
            f"model=[cyan]{self.model or '(unset)'}[/cyan]"
        )

        transcript = Group(
            Text(f"provisional: {self.provisional}", style="dim"),
            Text.from_markup(f"[bold]final:[/bold]        {self.final_text}"),
        )

        cue_line = Text.from_markup(
            f"[bold]intent:[/bold]       {self.temporal}    "
            f"[bold]target:[/bold] {self.target}"
        )
        evidence_line = Text(f"evidence:    {self.evidence}", style="dim")

        decision_line = Text.assemble(
            ("DECISION:    ", "bold"),
            (self.decision_label, f"bold {self.decision_style}"),
            "  ",
            (self.camera_id, "bold"),
        )
        reason_line = Text(f"reason:      {self.reason}")

        def ms(x: float | None) -> str:
            return "-" if x is None else f"{x:5.0f} ms"

        latency_line = Text.from_markup(
            f"[bold]latency:[/bold]     "
            f"speech->transcript {ms(self.asr_ms)}   "
            f"transcript->cue {ms(self.cue_ms)}   "
            f"total {ms(self.total_ms)}"
        )

        status = Text.from_markup(
            f"guest_ready=[{'green' if self.guest_ready else 'red'}]"
            f"{self.guest_ready}[/]   "
            f"mode=[{'red' if self.mode == Mode.HOLD else 'green'}]"
            f"{self.mode.value}[/]   "
            f"[dim]keys: R=guest_ready  H=HOLD  Q=quit[/dim]"
        )

        body = Group(
            transcript, Text(""),
            cue_line, evidence_line, Text(""),
            decision_line, reason_line, Text(""),
            latency_line,
        )
        return Panel(
            Group(Align.center(header), Text(""), body, Text(""), status),
            title="CUE C-lane",
            border_style="cyan",
            padding=(1, 2),
        )


def _label_and_style(d: Decision) -> tuple[str, str]:
    if d.action == DecisionAction.TAKE:
        if d.camera_id == "CAM-WIDE":
            return "WIDE", "bright_blue"
        return "TAKE", "bright_green"
    if d.action == DecisionAction.STAY:
        return "STAY", "yellow"
    return "SLATE", "red"


# ---------------------------------------------------------------- keypresses

def _poll_key() -> str | None:
    """Windows-only non-blocking keypress. Returns lowercase char or None."""
    try:
        import msvcrt
    except ImportError:
        return None
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getch()
    try:
        return ch.decode("utf-8", errors="ignore").lower()
    except Exception:  # noqa: BLE001 -- stray bytes from arrow/function keys
        return None


# ---------------------------------------------------------------- simulate mode

def run_simulate(text: str, view: DemoView) -> int:
    """Feed one FinalUtterance through interpret + decide, print result once."""
    console = Console()
    view.final_text = text
    view.provisional = ""

    now_wall = time.perf_counter()
    fake = FinalUtterance(
        utterance_id="sim-1", audio_epoch=1, text=text, words=[],
        started_at=now_wall - 1.0, ended_at=now_wall,
    )
    t0 = time.perf_counter()
    cue = interpret(fake.text, fake.utterance_id, t0)
    t1 = time.perf_counter()
    view.temporal = getattr(cue.temporal_intent, "value", str(cue.temporal_intent))
    view.target = ",".join(cue.target_guest_ids) or "(none)"
    view.evidence = cue.evidence_text
    view.cue_ms = (t1 - t0) * 1000

    state = State(current_camera="CAM-HOST", last_cut_time=-100.0,
                  mode=view.mode, last_utterance_id="")
    d = decide(cue, make_cameras(view.guest_ready), state, now=t1,
               role_based=True, role_map=ROLE_MAP)
    t2 = time.perf_counter()
    view.set_decision(d)
    view.asr_ms = 0.0
    view.total_ms = (t2 - t0) * 1000
    console.print(view.render())
    return 0


# ---------------------------------------------------------------- live mode

def run_live(view: DemoView) -> int:  # pragma: no cover -- requires mic
    """Full pipeline: mic -> Deepgram -> Assembler -> interpret -> decide."""
    import sounddevice as sd
    from deepgram import DeepgramClient
    from deepgram.core.events import EventType

    console = Console()

    if not os.environ.get("DEEPGRAM_API_KEY"):
        console.print("[red]DEEPGRAM_API_KEY is not set in .env; cannot stream.[/red]")
        return 2

    sample_rate = 16000
    channels = 1
    audio_epoch = 1
    assembler = Assembler(timeout_s=1.2, audio_epoch=audio_epoch)
    state = State(current_camera="CAM-HOST", last_cut_time=-100.0,
                  mode=view.mode, last_utterance_id="")

    # Timing
    t_last_final_seg: dict[str, float] = {"t": time.perf_counter()}

    # Cross-thread queues
    msg_q: queue.Queue = queue.Queue()
    stop_evt = threading.Event()

    def on_message(message, **_kwargs):
        msg_q.put({"kind": "dg", "at": time.perf_counter(), "msg": message})

    def on_open(*_a, **_kw):
        msg_q.put({"kind": "log", "text": "deepgram: connection open"})

    def on_close(*_a, **_kw):
        msg_q.put({"kind": "log", "text": "deepgram: connection closed"})

    def on_error(err, **_kw):
        msg_q.put({"kind": "log", "text": f"deepgram error: {type(err).__name__}"})

    dg_client = DeepgramClient()
    connect_kwargs = {
        "model": "nova-3", "language": "en-US",
        "encoding": "linear16", "sample_rate": str(sample_rate), "channels": str(channels),
        "smart_format": "true", "interim_results": "true",
        "endpointing": "300", "utterance_end_ms": "1000", "vad_events": "true",
    }
    keyterms = _roster_keyterms()
    if keyterms:
        connect_kwargs["keyterm"] = keyterms

    audio_q: queue.Queue = queue.Queue(maxsize=64)

    def audio_cb(indata, _frames, _time_info, _status):
        try:
            audio_q.put_nowait(bytes(indata))
        except queue.Full:
            pass  # drop under pressure; a stale chunk isn't worth blocking on

    with dg_client.listen.v1.connect(**connect_kwargs) as connection:
        connection.on(EventType.OPEN, on_open)
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.CLOSE, on_close)
        connection.on(EventType.ERROR, on_error)
        connection.start_listening()

        def sender():
            while not stop_evt.is_set():
                try:
                    chunk = audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    connection.send_media(chunk)
                except Exception:  # noqa: BLE001 -- socket closed mid-send is not fatal
                    return
        t_sender = threading.Thread(target=sender, daemon=True)
        t_sender.start()

        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=int(sample_rate * 0.1),
            dtype="int16", channels=channels, callback=audio_cb,
        ), Live(
            view.render(), console=console, refresh_per_second=8, screen=False,
        ) as live:
                while not stop_evt.is_set():
                    # Keyboard
                    k = _poll_key()
                    if k == "q":
                        stop_evt.set()
                        break
                    if k == "r":
                        view.guest_ready = not view.guest_ready
                    if k == "h":
                        view.mode = Mode.AUTO if view.mode == Mode.HOLD else Mode.HOLD
                        state = replace(state, mode=view.mode)

                    # Drain a few messages this tick.
                    for _ in range(16):
                        try:
                            item = msg_q.get_nowait()
                        except queue.Empty:
                            break
                        if item["kind"] == "log":
                            view.reason = item["text"]
                            continue
                        dmsg = item["msg"]
                        payload = dmsg.model_dump()
                        payload["audio_epoch"] = audio_epoch
                        # Track last-final wall time for the ASR latency stat.
                        if payload.get("type") == "Results" and payload.get("is_final"):
                            t_last_final_seg["t"] = item["at"]
                        # Update provisional preview from any interim we see.
                        if payload.get("type") == "Results":
                            alt0 = (payload.get("channel") or {}).get("alternatives") or [{}]
                            interim = alt0[0].get("transcript", "") if alt0 else ""
                            if interim and not payload.get("is_final"):
                                view.provisional = interim
                        events = assembler.feed(payload, now=item["at"])
                        _handle_events(events, view, state, t_last_final_seg)
                    live.update(view.render())
                    time.sleep(0.05)

        stop_evt.set()
    return 0


def _handle_events(events: list[Event], view: DemoView, state: State,
                   t_last_final_seg: dict) -> None:
    for e in events:
        if isinstance(e, Provisional):
            view.provisional = e.text
        elif isinstance(e, FinalUtterance):
            t_final = time.perf_counter()
            view.final_text = e.text
            view.provisional = ""
            # Interpret
            t_before = time.perf_counter()
            cue = interpret(e.text, e.utterance_id, e.ended_at or t_final)
            t_after = time.perf_counter()
            view.temporal = getattr(cue.temporal_intent, "value", str(cue.temporal_intent))
            view.target = ",".join(cue.target_guest_ids) or "(none)"
            view.evidence = cue.evidence_text
            # Decide
            d = decide(cue, make_cameras(view.guest_ready), state, now=t_after,
                       role_based=True, role_map=ROLE_MAP)
            t_decide = time.perf_counter()
            view.set_decision(d)
            # Latencies
            view.asr_ms = (t_final - t_last_final_seg["t"]) * 1000
            view.cue_ms = (t_after - t_before) * 1000
            view.total_ms = (t_decide - t_last_final_seg["t"]) * 1000


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="CUE booth demo (dev-only).")
    ap.add_argument("--simulate", metavar="TEXT",
                    help="skip mic/Deepgram; feed one FinalUtterance and exit.")
    args = ap.parse_args(argv)

    if PROVIDER == "ollama":
        # Banner: printed once, before Rich takes over the screen.
        print("DEV MODEL (local). Production uses OpenAI.")

    view = DemoView(provider=PROVIDER, model=CUE_MODEL)

    if args.simulate is not None:
        return run_simulate(args.simulate, view)
    return run_live(view)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
