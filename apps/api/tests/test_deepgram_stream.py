"""Tests for cue_api.speech.deepgram_stream.

No network. Fake Deepgram connection captures bytes; Deepgram-side
transcripts are exercised with the recorded fixture messages already
under tests/fixtures/deepgram/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cue_api.contracts import CameraId
from cue_api.media_contracts import (
    DecodedAudioChunk,
    SampleFormat,
)
from cue_api.speech.assembler import Assembler
from cue_api.speech.deepgram_stream import (
    DEFAULT_SPEECH_DOWN_TIMEOUT_S,
    DeepgramStream,
    SpeechEvent,
    _resample_to_target,
)

FIXTURES = Path(__file__).parent / "fixtures" / "deepgram"


class FakeConn:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_media(self, pcm: bytes) -> None:
        self.sent.append(pcm)


class FailingConn(FakeConn):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def send_media(self, pcm: bytes) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("Deepgram unavailable")
        super().send_media(pcm)


def _chunk(
    seq: int,
    offset: int,
    *,
    epoch: int = 1,
    rate: int = 16_000,
    channels: int = 1,
    fmt: SampleFormat = SampleFormat.S16LE,
    duration_ms: int = 10,
    track_sid: str | None = None,
) -> DecodedAudioChunk:
    frames = int(rate * duration_ms / 1000)
    data = bytes(frames * channels * fmt.bytes_per_sample)
    return DecodedAudioChunk(
        event_id="event-1",
        camera_id=CameraId.HOST,
        master_track_sid=track_sid or f"track-{epoch}",
        audio_epoch=epoch, sequence=seq,
        sample_rate_hz=rate, channels=channels, sample_format=fmt,
        sample_offset=offset,
        received_at_monotonic_s=0.0,
        data=data,
    )


# ---- input side (A -> Deepgram bytes) --------------------------------------

def test_pass_through_when_input_matches_target_rate_mono_s16le():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    c = _chunk(0, 0, rate=16_000, channels=1, fmt=SampleFormat.S16LE)
    events = ds.feed(c, now=1.0)
    assert events == []
    assert len(conn.sent) == 1
    assert conn.sent[0] == c.data
    assert ds.resamples == 0


def test_resample_from_48k_stereo_produces_16k_mono_bytes():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    c = _chunk(0, 0, rate=48_000, channels=2, duration_ms=10)
    ds.feed(c, now=1.0)
    assert ds.resamples == 1
    # 10 ms of 16 kHz mono int16 = 160 samples * 2 bytes = 320 bytes.
    assert len(conn.sent[0]) == 320


def test_resample_from_44100_hits_expected_length_within_one_sample():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    c = _chunk(0, 0, rate=44_100, channels=1, duration_ms=20)
    ds.feed(c, now=1.0)
    expected = int(16_000 * 20 / 1000)  # 320
    assert abs(len(conn.sent[0]) // 2 - expected) <= 1


def test_f32le_input_is_converted_to_int16():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    c = _chunk(0, 0, rate=16_000, channels=1, fmt=SampleFormat.F32LE)
    ds.feed(c, now=1.0)
    assert ds.resamples == 1
    # 10 ms mono int16 at 16 kHz = 320 bytes.
    assert len(conn.sent[0]) == 320


def test_continuity_guard_rejects_duplicate_sequence():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    ds.feed(_chunk(0, 0), now=1.0)
    ds.feed(_chunk(1, 160), now=1.01)
    ds.feed(_chunk(1, 160), now=1.02)     # duplicate seq
    assert len(conn.sent) == 2
    assert ds.rejected_reasons[-1].startswith("duplicate")


def test_continuity_guard_rejects_stale_epoch():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    ds.feed(_chunk(0, 0, epoch=2), now=1.0)
    ds.feed(_chunk(0, 0, epoch=1), now=1.01)   # older epoch
    assert len(conn.sent) == 1
    assert ds.rejected_reasons[-1] == "stale audio epoch"


def test_continuity_guard_rejects_track_change_inside_epoch():
    conn = FakeConn()
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    ds.feed(_chunk(0, 0, epoch=1, track_sid="TR-a"), now=1.0)
    ds.feed(_chunk(1, 160, epoch=1, track_sid="TR-b"), now=1.01)
    assert len(conn.sent) == 1
    assert "track changed" in ds.rejected_reasons[-1].lower()


# ---- epoch handling --------------------------------------------------------

def test_epoch_advance_resets_assembler_and_records_new_start_offset():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)
    ds.feed(_chunk(0, 0, epoch=1), now=1.0)
    assert ds.current_epoch == 1
    ds.feed(_chunk(0, 96_000, epoch=2), now=1.05)  # new epoch, offset advanced
    assert ds.current_epoch == 2
    assert asm._audio_epoch == 2  # noqa: SLF001


def test_reset_advances_epoch_and_clears_assembler_state():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)
    ds.feed(_chunk(0, 0), now=1.0)
    ds.reset(new_epoch=5)
    assert ds.current_epoch == 5
    assert asm._audio_epoch == 5  # noqa: SLF001


# ---- Deepgram -> assembler routing ----------------------------------------

def _load_dg_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_deepgram_message_pipes_provisional_and_final_out():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)
    # Start an epoch so the assembler will accept messages.
    ds.feed(_chunk(0, 0, epoch=1), now=1.0)
    events: list[SpeechEvent] = []
    for step in _load_dg_fixture("simple_intro")["steps"]:
        if step.get("kind") == "reset":
            ds.reset(step["new_epoch"])
            continue
        events.extend(ds.on_deepgram_message(step["message"], now=step["at"]))
    kinds = [e.kind for e in events]
    assert "provisional" in kinds
    assert kinds.count("final_utterance") == 1


def test_final_utterance_carries_audio_epoch_and_sample_offsets():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)
    # A's chunk sets sample_offset base = 4800 at 48 kHz.
    ds.feed(_chunk(0, 4800, epoch=1, rate=48_000, channels=1), now=1.0)

    events: list[SpeechEvent] = []
    for step in _load_dg_fixture("simple_intro")["steps"]:
        events.extend(ds.on_deepgram_message(step["message"], now=step["at"]))
    (final,) = [e for e in events if e.kind == "final_utterance"]
    assert final.audio_epoch == 1
    # simple_intro's last word ends at ~1.90s (Deepgram audio time).
    # 1.90 s * 48 kHz + 4800 base = 96 000
    assert final.sample_offset_end is not None
    assert abs(final.sample_offset_end - 96_000) < 100
    assert final.sample_offset_start is not None
    assert final.sample_offset_start >= 4800


# ---- speech-down / speech-up ----------------------------------------------

def test_tick_emits_speech_down_after_timeout():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm, speech_down_timeout_s=1.0)
    ds.feed(_chunk(0, 0, epoch=1), now=10.0)
    events = ds.tick(now=10.5)  # inside timeout window
    assert not any(e.kind == "speech_down" for e in events)
    events = ds.tick(now=11.5)  # past timeout window
    assert any(e.kind == "speech_down" for e in events)
    assert ds.speech_down is True


def test_deepgram_message_after_speech_down_emits_speech_up():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm, speech_down_timeout_s=1.0)
    ds.feed(_chunk(0, 0, epoch=1), now=10.0)
    ds.tick(now=11.5)
    assert ds.speech_down is True
    events = ds.on_deepgram_message(
        {"type": "Results", "start": 0.0, "duration": 0.4,
         "is_final": False, "speech_final": False,
         "channel": {"alternatives": [{"transcript": "hi"}]}},
        now=11.7,
    )
    kinds = [e.kind for e in events]
    assert "speech_up" in kinds
    assert ds.speech_down is False


def test_default_speech_down_timeout_five_seconds():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)  # default timeout
    ds.feed(_chunk(0, 0, epoch=1), now=100.0)
    events = ds.tick(now=100.0 + DEFAULT_SPEECH_DOWN_TIMEOUT_S - 0.1)
    assert not any(e.kind == "speech_down" for e in events)
    events = ds.tick(now=100.0 + DEFAULT_SPEECH_DOWN_TIMEOUT_S + 0.1)
    assert any(e.kind == "speech_down" for e in events)


def test_provider_send_failure_degrades_without_crashing_or_repeating_down() -> None:
    conn = FailingConn(failures=2)
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))

    first = ds.feed(_chunk(0, 0), now=10.0)
    second = ds.feed(_chunk(1, 160), now=10.1)

    assert [event.kind for event in first] == ["speech_down"]
    assert second == []
    assert ds.speech_down is True
    assert ds.provider_failure_count == 2
    assert ds.last_provider_error == "TimeoutError"


def test_provider_is_only_up_after_a_real_provider_message() -> None:
    conn = FailingConn(failures=1)
    ds = DeepgramStream(conn, Assembler(audio_epoch=1))
    ds.feed(_chunk(0, 0), now=10.0)
    assert ds.speech_down is True

    assert ds.feed(_chunk(1, 160), now=10.1) == []
    assert ds.speech_down is True
    events = ds.on_deepgram_message(
        {
            "type": "Results",
            "start": 0.0,
            "duration": 0.1,
            "is_final": False,
            "speech_final": False,
            "channel": {"alternatives": [{"transcript": "back"}]},
        },
        now=10.2,
    )
    assert "speech_up" in [event.kind for event in events]
    assert ds.speech_down is False
    assert ds.last_provider_error is None


# ---- resampler unit tests ------------------------------------------------

def test_resample_helper_directly_produces_expected_frame_count():
    c = _chunk(0, 0, rate=44_100, channels=2, duration_ms=50)  # 50 ms stereo
    out = _resample_to_target(c, 16_000)
    # 50 ms of 16 kHz mono int16 = 800 samples * 2 bytes
    assert abs(len(out) // 2 - 800) <= 1
    assert isinstance(out, bytes)


def test_unknown_assembler_event_raises_typeerror():
    conn = FakeConn()
    asm = Assembler(audio_epoch=1)
    ds = DeepgramStream(conn, asm)

    class _Weird:
        pass
    with pytest.raises(TypeError):
        ds._to_speech_event(_Weird())  # noqa: SLF001
