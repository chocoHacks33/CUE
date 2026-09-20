"""Offline exercises for cue_api.c_lane_live.LiveLane.

Uses a fake DeepgramSession + fake PCM source + fake sender so the whole
async run loop can be exercised without network or a mic. Verifies the
integration: PCM -> DG (fake) -> CLane -> DecisionEvent -> sender + the
latency trace fields land in the DecisionRecord.
"""
from __future__ import annotations

import asyncio
import contextlib
import time

from cue_api.c_lane_live import TARGET_SAMPLE_RATE, LiveLane
from cue_api.contracts import CameraId
from cue_api.media_contracts import DecodedAudioChunk, SampleFormat
from cue_api.policy.wire import DecisionEvent
from cue_api.semantics.parser import (
    Action,
    Cue,
    Intent,
    Scope,
    TemporalIntent,
)


class FakeConn:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_media(self, pcm: bytes) -> None:
        self.sent.append(pcm)


class FakeSession:
    """Yields a FakeConn context manager. Not a real Deepgram session."""

    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> FakeConn:
        return self._conn

    def __exit__(self, *_a):
        return False


class FakePcmSource:
    def __init__(self, chunks: list[DecodedAudioChunk]) -> None:
        self._chunks = chunks

    async def stream(self):
        for c in self._chunks:
            yield c
            await asyncio.sleep(0)


class FakeCameras:
    def cameras(self, now: float) -> dict[str, dict]:
        return {
            "CAM-HOST":  {"role": "host",  "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                          "guest_ready": True},
            "CAM-GUEST": {"role": "guest", "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": ["sarah", "daniel"],
                          "evidence_age_s": 0.4, "guest_ready": True},
            "CAM-WIDE":  {"role": "wide",  "healthy": True, "epoch": 1,
                          "confirmed_guest_ids": [], "evidence_age_s": 999.0,
                          "guest_ready": True},
        }


class CapturingSender:
    def __init__(self) -> None:
        self.events: list[DecisionEvent] = []
        self.seqs: list[int] = []

    def send(self, event: DecisionEvent, *, decision_seq: int) -> None:
        self.events.append(event)
        self.seqs.append(decision_seq)


def _mono_chunk(seq: int, offset: int) -> DecodedAudioChunk:
    samples = 480  # 30 ms at 16k
    return DecodedAudioChunk(
        event_id="test-event",
        camera_id=CameraId.HOST,
        master_track_sid="track-a",
        audio_epoch=1,
        sequence=seq,
        sample_rate_hz=TARGET_SAMPLE_RATE,
        channels=1,
        sample_format=SampleFormat.S16LE,
        sample_offset=offset,
        received_at_monotonic_s=0.0,
        data=b"\x00\x00" * samples,
    )


def _parse_daniel_now(_text: str):
    return Cue(
        target_guest_ids=["daniel"], scope=Scope.SINGLE,
        intent=Intent.INTRODUCE, temporal_intent=TemporalIntent.NOW,
        action=Action.SHOW, evidence_text=_text,
    ), 5.0


def test_pcm_pumped_to_deepgram_send_media():
    conn = FakeConn()

    async def _main() -> None:
        chunks = [_mono_chunk(1, 0), _mono_chunk(2, 480), _mono_chunk(3, 960)]
        src = FakePcmSource(chunks)
        lane = LiveLane(
            pcm_source=src,
            deepgram_factory=lambda: FakeSession(conn),
            camera_state=FakeCameras(),
            sender=CapturingSender(),
            parse_fn=_parse_daniel_now,
            role_based=True,
            role_map={"daniel": "CAM-GUEST"},
        )
        stop = asyncio.Event()

        async def stopper():
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(lane.run(stop_event=stop), stopper())

    asyncio.run(_main())
    assert len(conn.sent) == 3


def test_final_deepgram_message_produces_take_and_stamps_latency():
    conn = FakeConn()
    sender = CapturingSender()

    async def _main() -> None:
        src = FakePcmSource([_mono_chunk(1, 0)])
        lane = LiveLane(
            pcm_source=src,
            deepgram_factory=lambda: FakeSession(conn),
            camera_state=FakeCameras(),
            sender=sender,
            parse_fn=_parse_daniel_now,
            role_based=True,
            role_map={"daniel": "CAM-GUEST"},
        )
        stop = asyncio.Event()
        runner = asyncio.create_task(lane.run(stop_event=stop))
        # camera_state pump ticks every 100 ms; wait so first snapshot lands.
        await asyncio.sleep(0.15)

        # In production, DeepgramStream maps stream-time word timings onto
        # the producer clock. Here we mirror that by picking a word.end
        # value close to time.monotonic() so cue.created_at is not stale
        # by DirectorSession's CUE_LIFETIME_S=3s check. Also spoof
        # audio_seconds_sent to match so final_ms comes out positive.
        now = time.monotonic()
        lane._audio_seconds_sent = now  # noqa: SLF001 -- test-only clock align
        lane.on_deepgram_message({
            "type": "Results",
            "is_final": True, "speech_final": True,
            "audio_epoch": 1, "start": now - 0.05, "duration": 0.03,
            "channel": {"alternatives": [{
                "transcript": "Please welcome Daniel.",
                "words": [
                    {"word": "Daniel", "start": now - 0.05,
                     "end": now - 0.02, "confidence": 0.9},
                ],
            }]},
        }, now=now)

        await asyncio.sleep(0.05)
        stop.set()
        with contextlib.suppress(BaseException):
            await runner

    asyncio.run(_main())
    assert sender.events, "expected at least one DecisionEvent"
    ev = sender.events[-1]
    assert ev.action == "TAKE"
    assert ev.camera_id == "CAM-GUEST"
    assert "final_ms" in ev.latencies_ms
    assert "cue_decide_ms" in ev.latencies_ms
    assert ev.identity == "ROLE_BASED"
    # The sentinel is gone; make sure no test-only leftover key crept in.
    assert "_identity" not in ev.latencies_ms


def test_bad_pcm_continuity_is_dropped_without_wedging_loop():
    conn = FakeConn()

    async def _main() -> None:
        good = _mono_chunk(1, 0)
        dup = _mono_chunk(1, 0)  # same sequence -> continuity guard rejects
        src = FakePcmSource([good, dup, _mono_chunk(2, 480)])
        lane = LiveLane(
            pcm_source=src,
            deepgram_factory=lambda: FakeSession(conn),
            camera_state=FakeCameras(),
            sender=CapturingSender(),
            parse_fn=_parse_daniel_now,
        )
        stop = asyncio.Event()

        async def stopper():
            await asyncio.sleep(0.1)
            stop.set()

        await asyncio.gather(lane.run(stop_event=stop), stopper())

    asyncio.run(_main())
    assert len(conn.sent) == 2
