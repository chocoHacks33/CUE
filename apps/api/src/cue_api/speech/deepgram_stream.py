"""Bridge A's DecodedAudioChunk into Deepgram and out through C's assembler.

C-lane ingress boundary. On the input side we take A's Stage-1 media
contract (cue_api.media_contracts.DecodedAudioChunk + PcmContinuityGuard).
On the output side we push audio bytes to Deepgram and pipe its
transcript messages through cue_api.speech.assembler.Assembler. Every
emitted event is stamped with A's audio_epoch and a sample_offset window
mapped back to A's original sample rate, so downstream consumers can
correlate transcripts with camera state and other epoch-scoped events.

The Deepgram connection is dependency-injected as a duck-typed object with
one method: ``send_media(bytes)``. Tests hand in a fake and the module
touches no network. Resampling to Deepgram's target rate happens exactly
once at the boundary; if A's input rate already matches, we pass bytes
through unchanged. On sustained absence of transcripts a SPEECH_DOWN
event is emitted so DirectorSession can pause AUTO; a subsequent chunk
that resumes forward progress emits SPEECH_UP.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal, Protocol

from cue_api.media_contracts import (
    DecodedAudioChunk,
    PcmContinuityGuard,
    SampleFormat,
)
from cue_api.speech.assembler import (
    Assembler,
    Event,
    FinalUtterance,
    Provisional,
)

DEFAULT_TARGET_RATE = 16_000
DEFAULT_SPEECH_DOWN_TIMEOUT_S = 5.0


class DeepgramConnection(Protocol):
    """Minimal surface the bridge needs. The real one comes from deepgram-sdk."""

    def send_media(self, pcm: bytes) -> None: ...


SpeechEventKind = Literal[
    "provisional", "final_utterance", "speech_down", "speech_up",
]


@dataclass
class SpeechEvent:
    """One event emitted by the bridge for downstream consumers."""
    kind: SpeechEventKind
    text: str = ""
    utterance_id: str = ""
    audio_epoch: int = 0
    sample_offset_start: int | None = None
    sample_offset_end: int | None = None


class DeepgramStream:
    """Owns A-side continuity, resampling, DG plumbing, assembler routing."""

    def __init__(
        self,
        connection: DeepgramConnection,
        assembler: Assembler,
        *,
        target_sample_rate: int = DEFAULT_TARGET_RATE,
        speech_down_timeout_s: float = DEFAULT_SPEECH_DOWN_TIMEOUT_S,
    ) -> None:
        self._conn = connection
        self._assembler = assembler
        self._target_rate = target_sample_rate
        self._down_timeout_s = speech_down_timeout_s
        self._guard = PcmContinuityGuard()
        self._current_epoch = 0
        self._epoch_start_sample_offset: int | None = None  # A-rate offset
        self._epoch_input_rate = 0
        self._last_chunk_at: float | None = None
        self._last_dg_msg_at: float | None = None
        self._speech_down = False
        self._last_provider_error: str | None = None
        self.provider_failure_count = 0
        self.rejected_reasons: list[str] = []
        self.resamples: int = 0

    # ---- inputs from A -------------------------------------------------

    def feed(self, chunk: DecodedAudioChunk, *, now: float) -> list[SpeechEvent]:
        """Consume one PCM chunk from A. Returns any generated events."""
        events: list[SpeechEvent] = []

        cont = self._guard.accept(chunk)
        if not cont.accepted:
            self.rejected_reasons.append(cont.reason or "unknown")
            return events

        if chunk.audio_epoch != self._current_epoch:
            self._on_new_epoch(chunk)

        pcm = self._to_target_pcm(chunk)
        try:
            self._conn.send_media(pcm)
        except Exception as error:  # noqa: BLE001 -- provider failure must not stop media
            self.provider_failure_count += 1
            self._last_provider_error = type(error).__name__
            self._last_chunk_at = now
            if not self._speech_down:
                self._speech_down = True
                events.append(SpeechEvent(kind="speech_down", audio_epoch=self._current_epoch))
            return events
        self._last_chunk_at = now
        # Fresh audio; if transcripts resume the next DG message will bring
        # us back up. The SPEECH_UP event fires on the DG-message path
        # below, not here, so we don't announce recovery before there's
        # any real transcript evidence.
        return events

    # ---- inputs from Deepgram ------------------------------------------

    def on_deepgram_message(self, msg: dict, *, now: float) -> list[SpeechEvent]:
        """Route a Deepgram message dict through the assembler."""
        tagged = dict(msg)
        tagged["audio_epoch"] = self._current_epoch
        asm_events = self._assembler.feed(tagged, now=now)

        events: list[SpeechEvent] = []
        # Any message from Deepgram counts as speech pipeline life;
        # emit SPEECH_UP once if we had reported down.
        if self._speech_down:
            self._speech_down = False
            events.append(SpeechEvent(
                kind="speech_up", audio_epoch=self._current_epoch,
            ))
        self._last_dg_msg_at = now
        self._last_provider_error = None
        events.extend(self._to_speech_event(e) for e in asm_events)
        return events

    # ---- housekeeping ---------------------------------------------------

    def tick(self, now: float) -> list[SpeechEvent]:
        """Check timeouts / speech-down. Also drains assembler's tick()."""
        events: list[SpeechEvent] = []
        asm_events = self._assembler.tick(now)
        events.extend(self._to_speech_event(e) for e in asm_events)
        if self._should_speech_down(now):
            self._speech_down = True
            events.append(SpeechEvent(
                kind="speech_down", audio_epoch=self._current_epoch,
            ))
        return events

    def reset(self, new_epoch: int) -> None:
        """Caller-initiated reset (e.g. before a WebSocket reconnect)."""
        self._current_epoch = new_epoch
        self._epoch_start_sample_offset = None
        self._epoch_input_rate = 0
        self._assembler.reset(new_epoch)
        self._speech_down = False
        # PcmContinuityGuard auto-resets on the next chunk's audio_epoch.

    # ---- read-only introspection (mostly for tests) --------------------

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    @property
    def speech_down(self) -> bool:
        return self._speech_down

    @property
    def last_provider_error(self) -> str | None:
        return self._last_provider_error

    # ---- internals -----------------------------------------------------

    def _on_new_epoch(self, chunk: DecodedAudioChunk) -> None:
        self._current_epoch = chunk.audio_epoch
        self._epoch_start_sample_offset = chunk.sample_offset
        self._epoch_input_rate = chunk.sample_rate_hz
        self._assembler.reset(chunk.audio_epoch)
        self._speech_down = False

    def _to_target_pcm(self, chunk: DecodedAudioChunk) -> bytes:
        if (
            chunk.sample_rate_hz == self._target_rate
            and chunk.channels == 1
            and chunk.sample_format == SampleFormat.S16LE
        ):
            return chunk.data
        self.resamples += 1
        return _resample_to_target(chunk, self._target_rate)

    def _should_speech_down(self, now: float) -> bool:
        if self._speech_down or self._last_chunk_at is None:
            return False
        # Reference: the most recent DG message, or the first chunk if
        # we haven't heard from Deepgram at all yet.
        reference = self._last_dg_msg_at or self._last_chunk_at
        return (now - reference) > self._down_timeout_s

    def _to_speech_event(self, e: Event) -> SpeechEvent:
        if isinstance(e, Provisional):
            return SpeechEvent(
                kind="provisional", text=e.text,
                audio_epoch=self._current_epoch,
            )
        if isinstance(e, FinalUtterance):
            start_off, end_off = self._map_offsets(e)
            return SpeechEvent(
                kind="final_utterance", text=e.text,
                utterance_id=e.utterance_id,
                audio_epoch=e.audio_epoch,
                sample_offset_start=start_off,
                sample_offset_end=end_off,
            )
        raise TypeError(f"unknown assembler event: {type(e).__name__}")

    def _map_offsets(self, u: FinalUtterance) -> tuple[int | None, int | None]:
        if self._epoch_start_sample_offset is None or self._epoch_input_rate == 0:
            return None, None
        base = self._epoch_start_sample_offset
        rate = self._epoch_input_rate
        s = int(round(u.started_at * rate)) + base if u.started_at is not None else None
        e = int(round(u.ended_at * rate)) + base if u.ended_at is not None else None
        return s, e


# ---- resampler ----------------------------------------------------------

def _resample_to_target(chunk: DecodedAudioChunk, target_rate: int) -> bytes:
    """Downmix to mono, convert to int16, linear-interp to target rate.

    Deliberately simple. Real production would use a proper filter to
    avoid aliasing; for the prototype and the tests here, linear
    interpolation is enough to prove the epoch/offset accounting.
    """
    src_rate = chunk.sample_rate_hz
    channels = chunk.channels

    # 1) Unpack samples.
    if chunk.sample_format == SampleFormat.S16LE:
        n = len(chunk.data) // 2
        raw = list(struct.unpack(f"<{n}h", chunk.data))
    elif chunk.sample_format == SampleFormat.F32LE:
        n = len(chunk.data) // 4
        floats = struct.unpack(f"<{n}f", chunk.data)
        raw = [int(max(-1.0, min(1.0, f)) * 32767) for f in floats]
    else:  # pragma: no cover
        raise ValueError(f"unsupported sample format: {chunk.sample_format}")

    # 2) Downmix to mono.
    if channels == 1:
        mono = raw
    else:
        mono = [
            sum(raw[i:i + channels]) // channels
            for i in range(0, len(raw), channels)
        ]

    # 3) Resample.
    if src_rate == target_rate:
        resampled = mono
    else:
        ratio = target_rate / src_rate
        out_len = int(len(mono) * ratio)
        resampled = [0] * out_len
        for i in range(out_len):
            src_idx = i / ratio
            base = int(src_idx)
            frac = src_idx - base
            if base + 1 < len(mono):
                resampled[i] = int(mono[base] * (1 - frac) + mono[base + 1] * frac)
            elif base < len(mono):
                resampled[i] = mono[base]

    # 4) Pack back to bytes.
    return struct.pack(f"<{len(resampled)}h", *resampled)
