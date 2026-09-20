"""Standalone end-to-end runner for the C-lane on one laptop.

Wires the laptop mic through a synthetic ``DecodedAudioChunk`` stream
(mimicking A's LiveKit path with the ``DecodedAudioChunk`` contract)
into LiveLane. Camera state is faked with role_based=True so identity
mode is stamped ``ROLE_BASED`` on every decision.

Requires two secrets in .env:
    OPENAI_API_KEY   the semantic parser
    DEEPGRAM_API_KEY the ASR

Missing either -> exit(2) with a clear message.

Usage::

    python scripts/live_lane.py --source mic
    python scripts/live_lane.py --source mic --log-decisions decisions.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import queue as _queue
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "apps" / "api" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

load_dotenv()

# Local project imports go after sys.path setup.
from cue_api.c_lane_live import (  # noqa: E402
    LiveLane, TARGET_SAMPLE_RATE,
)
from cue_api.contracts import CameraId  # noqa: E402
from cue_api.media_contracts import (  # noqa: E402
    DecodedAudioChunk, SampleFormat,
)
from cue_api.policy.log import DecisionLogger  # noqa: E402
from cue_api.policy.wire import DecisionEvent  # noqa: E402

MIC_BLOCK_SAMPLES = 480    # 30 ms per block at 16 kHz


class FakeCameraProvider:
    """Fixed healthy camera state so a single laptop can drive decisions."""

    def cameras(self, now: float) -> dict[str, dict]:
        return {
            "CAM-HOST": {"role": "host", "healthy": True, "epoch": 1,
                         "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                         "guest_ready": True},
            "CAM-GUEST": {"role": "guest", "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": [
                              "sarah", "daniel", "priya", "maya", "alex", "jordan", "kai",
                          ],
                          "evidence_age_s": 0.4, "guest_ready": True},
            "CAM-WIDE": {"role": "wide", "healthy": True, "epoch": 1,
                         "confirmed_guest_ids": [],
                         "evidence_age_s": 999.0, "guest_ready": True},
        }


class MicPcmSource:
    """Wrap sounddevice into A's DecodedAudioChunk stream contract.

    We synthesise event_id / master_track_sid / audio_epoch / sequence /
    sample_offset locally; the real ingress on the Mac uses A's LiveKit
    adapter but ships the SAME DecodedAudioChunk to LiveLane. Nothing else
    changes.
    """

    def __init__(self, *, device: str | None = None) -> None:
        import sounddevice as sd
        self._sd = sd
        self._device = device
        self._q: _queue.Queue = _queue.Queue(maxsize=64)
        self._next_seq = 0
        self._next_offset = 0

    def _pick_device(self) -> int | None:
        sd = self._sd
        devs = sd.query_devices()
        default_in, _ = sd.default.device
        spec = self._device
        if spec is None or spec == "":
            return default_in
        try:
            return int(spec)
        except (TypeError, ValueError):
            needle = str(spec).lower()
            for i, d in enumerate(devs):
                if needle in (d.get("name", "") or "").lower():
                    return i
        return default_in

    async def stream(self):
        sd = self._sd
        chosen = self._pick_device()
        loop = asyncio.get_running_loop()

        def cb(indata, _frames, _time_info, status):
            if status:
                print(f"mic: sd status: {status}", flush=True)
            try:
                self._q.put_nowait(bytes(indata))
            except _queue.Full:
                pass

        stream = sd.RawInputStream(
            samplerate=TARGET_SAMPLE_RATE, blocksize=MIC_BLOCK_SAMPLES,
            dtype="int16", channels=1, callback=cb, device=chosen,
        )
        with stream:
            print(
                f"live_lane: mic open device={chosen} "
                f"rate={TARGET_SAMPLE_RATE} block={MIC_BLOCK_SAMPLES}samples",
                flush=True,
            )
            while True:
                chunk = await loop.run_in_executor(None, self._q.get)
                self._next_seq += 1
                chunk_obj = DecodedAudioChunk(
                    event_id="live-lane-demo",
                    camera_id=CameraId.HOST,
                    master_track_sid="mic-track-0",
                    audio_epoch=1,
                    sequence=self._next_seq,
                    sample_rate_hz=TARGET_SAMPLE_RATE,
                    channels=1,
                    sample_format=SampleFormat.S16LE,
                    sample_offset=self._next_offset,
                    received_at_monotonic_s=time.monotonic(),
                    data=chunk,
                )
                self._next_offset = chunk_obj.end_sample_offset
                yield chunk_obj


class StdoutSender:
    """Prints each DecisionEvent as a JSON line to stdout. D swaps this out."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._decisions = DecisionLogger(log_path) if log_path else None

    def send(self, event: DecisionEvent, *, decision_seq: int) -> None:
        line = event.model_dump_json(by_alias=True)
        print(line, flush=True)
        # Optional: also emit a compact single-liner into stderr for humans.
        try:
            d = json.loads(line)
            print(
                f"# decision seq={decision_seq} rev={d.get('modeRevision')} "
                f"action={d.get('action')} camera={d.get('cameraId')} "
                f"plain={d.get('plainReason')!r}",
                file=sys.stderr, flush=True,
            )
        except Exception:  # noqa: BLE001 -- best-effort human line
            pass


class BuildDeepgramFactory:
    """Factory that returns a Deepgram v1 streaming context manager.

    Adapts the deepgram-sdk 7.x nova-3 listen client into the
    DeepgramSession protocol LiveLane consumes. Every WS message is
    forwarded to a callback which routes into LiveLane.on_deepgram_message.
    """

    def __init__(
        self,
        *,
        lane: LiveLane,
        model: str = "nova-3",
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
    ) -> None:
        self._lane = lane
        self._model = model
        self._endpointing_ms = endpointing_ms
        self._utterance_end_ms = utterance_end_ms

    def __call__(self):  # -> DeepgramSession
        from deepgram import DeepgramClient
        from deepgram.core.events import EventType
        client = DeepgramClient()
        connect_kwargs = {
            "model": self._model, "language": "en-US",
            "encoding": "linear16", "sample_rate": str(TARGET_SAMPLE_RATE),
            "channels": "1", "smart_format": "true",
            "interim_results": "true",
            "endpointing": str(self._endpointing_ms),
            "utterance_end_ms": str(self._utterance_end_ms),
            "vad_events": "true",
        }
        cm = client.listen.v1.connect(**connect_kwargs)
        return _DeepgramSessionAdapter(
            cm, EventType, self._lane, self._model, self._endpointing_ms,
        )


class _DeepgramSessionAdapter:
    """Wraps the deepgram-sdk context manager into DeepgramSession shape."""

    def __init__(self, cm, EventType, lane, model, endpointing_ms):
        self._cm = cm
        self._et = EventType
        self._lane = lane
        self._model = model
        self._endpointing_ms = endpointing_ms
        self._conn = None
        self._listen_future = None

    def __enter__(self):
        self._conn = self._cm.__enter__()

        def on_message(message, **_kw):
            payload = message.model_dump()
            payload["audio_epoch"] = 1
            self._lane.on_deepgram_message(payload, time.monotonic())

        self._conn.on(self._et.OPEN, lambda *_a, **_k: print(
            "live_lane: deepgram open", flush=True,
        ))
        self._conn.on(self._et.MESSAGE, on_message)
        loop = asyncio.get_event_loop()
        self._listen_future = loop.run_in_executor(
            None, self._conn.start_listening,
        )
        print(
            f"live_lane: deepgram listen.v1 model={self._model} "
            f"endpointing={self._endpointing_ms} ms",
            flush=True,
        )
        return self._conn

    def __exit__(self, *args):
        with contextlib.suppress(Exception):
            if self._listen_future is not None:
                self._listen_future.cancel()
        return self._cm.__exit__(*args)


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"live_lane: {name} not set. Set it in .env or export it.",
              file=sys.stderr, flush=True)
        sys.exit(2)
    return v


async def _run(args: argparse.Namespace) -> int:
    if args.source != "mic":
        print("live_lane: only --source mic is supported in this runner",
              file=sys.stderr)
        return 2

    _require_env("OPENAI_API_KEY")
    _require_env("DEEPGRAM_API_KEY")
    if not os.environ.get("CUE_MODEL"):
        print("live_lane: CUE_MODEL not set — parser will safe-HOLD every "
              "utterance. Set CUE_MODEL to enable directing.",
              file=sys.stderr)

    log_path = Path(args.log_decisions) if args.log_decisions else None
    sender = StdoutSender(log_path)
    pcm_source = MicPcmSource(device=args.input_device)
    camera = FakeCameraProvider()
    lane = LiveLane(
        pcm_source=pcm_source,
        deepgram_factory=lambda: BuildDeepgramFactory(
            lane=lane,  # noqa: F821 -- populated below
            model=args.dg_model,
            endpointing_ms=args.endpointing_ms,
            utterance_end_ms=args.utterance_end_ms,
        )(),
        camera_state=camera,
        sender=sender,
        role_based=True,
        role_map={
            "sarah": "CAM-GUEST", "daniel": "CAM-GUEST", "priya": "CAM-GUEST",
            "maya": "CAM-GUEST", "alex": "CAM-GUEST", "jordan": "CAM-GUEST",
            "kai": "CAM-GUEST",
        },
    )
    print(
        "live_lane: LiveLane wired (role_based, identity=ROLE_BASED). "
        f"CUE_MODEL={os.environ.get('CUE_MODEL', 'unset')}",
        flush=True,
    )
    stop = asyncio.Event()
    try:
        await lane.run(stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Standalone C-lane live pipeline (single-laptop demo).",
    )
    ap.add_argument("--source", choices=("mic",), default="mic")
    ap.add_argument("--input-device", dest="input_device", default=None,
                    help="sounddevice input device index or name substring")
    ap.add_argument("--dg-model", dest="dg_model", default="nova-3")
    ap.add_argument("--endpointing-ms", dest="endpointing_ms",
                    type=int, default=300)
    ap.add_argument("--utterance-end-ms", dest="utterance_end_ms",
                    type=int, default=1000)
    ap.add_argument("--log-decisions", default=None,
                    help="append DecisionRecord JSONL for latency_report.py")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
