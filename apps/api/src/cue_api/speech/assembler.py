"""Deepgram streaming transcript assembler.

Pure. No network, no threads, no globals. `feed(message, now)` returns a list
of events; `reset(new_epoch)` throws away in-flight state.

Deepgram doc sources (verified 2026-09-19):
  https://developers.deepgram.com/docs/interim-results
  https://developers.deepgram.com/docs/utterance-end
  https://developers.deepgram.com/docs/endpointing

Message shapes assumed (field names verbatim from those pages):

  Results (WebSocket message):
    {
      "type": "Results",
      "start": float, "duration": float,
      "is_final": bool, "speech_final": bool,
      "channel": {
        "alternatives": [
          {"transcript": str, "confidence": float,
           "words": [
             {"word": str, "start": float, "end": float,
              "confidence": float, "punctuated_word": str?}
           ]}
        ]
      }
    }

  UtteranceEnd:
    {"type": "UtteranceEnd", "channel": [int, int], "last_word_end": float}

Endpoint semantics (per Deepgram endpointing/utterance-end docs): both
`speech_final: true` on a Results message and a separate `UtteranceEnd`
message signal an endpoint. `is_final` alone finalises a segment's text
but not the utterance.

Caller must tag each message with an `audio_epoch` int so a stream
reconnect (a new Deepgram WebSocket) can invalidate stale in-flight state
without dropping the current utterance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_WHITESPACE = re.compile(r"\s+")


@dataclass
class Provisional:
    """Interim progressive text for UI update. Never becomes final on its own."""
    text: str


@dataclass
class FinalUtterance:
    """One completed utterance, ready for semantic parsing and directing."""
    utterance_id: str
    audio_epoch: int
    text: str
    words: list[dict[str, Any]]
    started_at: float | None
    ended_at: float | None


Event = Provisional | FinalUtterance


class Assembler:
    """Reduces Deepgram Results/UtteranceEnd messages into events."""

    def __init__(
        self,
        timeout_s: float = 1.2,
        audio_epoch: int = 1,
        utterance_id_prefix: str = "utt",
    ) -> None:
        self._timeout_s = timeout_s
        self._audio_epoch = audio_epoch
        self._prefix = utterance_id_prefix
        self._counter = 0
        self._reset_buffer()

    def reset(self, new_epoch: int) -> None:
        """Drop in-flight buffer; subsequent messages must carry the new epoch."""
        self._audio_epoch = new_epoch
        self._reset_buffer()

    def tick(self, now: float) -> list[Event]:
        """Run only the timeout check.

        Callers that go silent (no new Deepgram messages after the last
        is_final=true) can invoke tick() to give the assembler a chance
        to flush the buffered utterance once ``timeout_s`` has elapsed.
        """
        return self._maybe_flush_on_timeout(now)

    def feed(self, message: dict, now: float) -> list[Event]:
        # Drop stale-epoch messages: a delayed WebSocket frame from before a
        # reconnect must not contaminate the current utterance.
        msg_epoch = message.get("audio_epoch")
        if msg_epoch is not None and msg_epoch != self._audio_epoch:
            return []

        events: list[Event] = []
        events.extend(self._maybe_flush_on_timeout(now))

        if message.get("type") == "UtteranceEnd":
            events.extend(self._flush())
            return events

        alt = self._first_alternative(message)
        transcript = (alt.get("transcript") or "").strip()
        words = alt.get("words") or []
        is_final = bool(message.get("is_final"))
        speech_final = bool(message.get("speech_final"))

        if not is_final:
            prov = self._provisional_text(transcript)
            if prov:
                events.append(Provisional(text=prov))
            return events

        self._accumulate(message, transcript, words, now)
        if speech_final:
            events.extend(self._flush())
        return events

    # ------------------------------------------------------------------ helpers

    def _reset_buffer(self) -> None:
        self._segments: list[str] = []
        self._words: list[dict[str, Any]] = []
        self._seg_keys: set[tuple[Any, Any, str]] = set()
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._last_final_at: float | None = None

    def _first_alternative(self, message: dict) -> dict[str, Any]:
        ch = message.get("channel") or {}
        # UtteranceEnd's "channel" is a list; Results' "channel" is an object.
        if isinstance(ch, dict):
            alts = ch.get("alternatives") or []
            if alts:
                return alts[0]
        return {}

    def _provisional_text(self, interim_transcript: str) -> str:
        parts = [*self._segments]
        if interim_transcript:
            parts.append(interim_transcript)
        return _WHITESPACE.sub(" ", " ".join(parts).strip())

    def _accumulate(
        self,
        message: dict,
        transcript: str,
        words: list[dict[str, Any]],
        now: float,
    ) -> None:
        # Dedupe repeat is_final=true messages by (start, duration, transcript).
        seg_key: tuple[Any, Any, str] = (
            message.get("start"),
            message.get("duration"),
            transcript,
        )
        if seg_key in self._seg_keys:
            self._last_final_at = now
            return
        self._seg_keys.add(seg_key)

        if transcript:
            self._segments.append(transcript)

        for w in words:
            self._words.append(dict(w))
            ws = w.get("start")
            we = w.get("end")
            if ws is not None and (self._started_at is None or ws < self._started_at):
                self._started_at = ws
            if we is not None and (self._ended_at is None or we > self._ended_at):
                self._ended_at = we

        if not words:
            seg_start = message.get("start")
            seg_dur = message.get("duration")
            if seg_start is not None:
                if self._started_at is None or seg_start < self._started_at:
                    self._started_at = seg_start
                if seg_dur is not None:
                    seg_end = seg_start + seg_dur
                    if self._ended_at is None or seg_end > self._ended_at:
                        self._ended_at = seg_end

        self._last_final_at = now

    def _maybe_flush_on_timeout(self, now: float) -> list[Event]:
        if self._last_final_at is None:
            return []
        if now - self._last_final_at >= self._timeout_s:
            return self._flush()
        return []

    def _flush(self) -> list[Event]:
        text = _WHITESPACE.sub(" ", " ".join(self._segments).strip())
        if not text:
            self._reset_buffer()
            return []
        self._counter += 1
        event = FinalUtterance(
            utterance_id=f"{self._prefix}-e{self._audio_epoch}-{self._counter}",
            audio_epoch=self._audio_epoch,
            text=text,
            words=list(self._words),
            started_at=self._started_at,
            ended_at=self._ended_at,
        )
        self._reset_buffer()
        return [event]
