"""LiveLane: end-to-end async wiring around CLane for the real event.

Composes A's PCM source, my Deepgram bridge, B's visual observations,
D's control transport and my Stage-2 CLane so the full path runs on a
single laptop for HackMIT and on the Mac for the demo.

Chain:

    A.PcmSource            (async iterable of DecodedAudioChunk)
        -> PcmContinuityGuard + resample-to-16k-mono
        -> connection.send_media(bytes)                 (Deepgram)
        -> connection.on(Message) -> CLane.on_transcript_message()
        -> semantics.parser.parse (OpenAI, pinned model)
        -> policy.session.DirectorSession
        -> policy.log.DecisionRecord (+ latency trace)
        -> policy.wire.to_wire(record) -> DecisionEvent
        -> sender.send(event, decision_seq)             (D's transport)
    D.AckReceiver.on_ack(seq, applied, at_ms) -> CLane.on_ack()

All external dependencies are typed as small local ``Protocol``s and
injected. This module never imports A/B/D internals directly, so the
live path can be exercised offline with fakes (see tests) and on the
Mac with the real transports without a Python-level circular import.

Identity mode: if no B-side visual observation provider is wired, the
lane runs with ``role_based=True`` and every DecisionRecord is stamped
``identity="ROLE_BASED"`` so nobody can misread it as face recognition.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from cue_api.c_lane import CLane
from cue_api.media_contracts import (
    DecodedAudioChunk,
    PcmContinuityGuard,
    SampleFormat,
)
from cue_api.policy.log import DecisionRecord
from cue_api.policy.wire import DecisionEvent, to_wire
from cue_api.semantics.parser import Cue
from cue_api.semantics.parser import parse as openai_parse

TARGET_SAMPLE_RATE = 16_000


# ---------------------------------------------------------------- Protocols

@runtime_checkable
class PcmSource(Protocol):
    """A's audio hand-off.

    Implement one of:
      * ``async def stream(self) -> AsyncIterator[DecodedAudioChunk]`` — an
        async generator; LiveLane awaits each chunk.
      * ``def iter_chunks(self) -> Iterable[DecodedAudioChunk]`` — a
        synchronous iterable; LiveLane wraps it in a thread executor.

    At least one of ``stream`` or ``iter_chunks`` MUST be provided.
    """


@runtime_checkable
class CameraStateProvider(Protocol):
    """B+A camera state provider (visual observations + health).

    Returns the ``cameras`` dict CLane expects. Keys are camera IDs
    (``CAM-HOST``, ``CAM-GUEST``, ``CAM-WIDE``); values carry ``role``,
    ``healthy``, ``epoch``, ``confirmed_guest_ids``, ``evidence_age_s``,
    ``guest_ready``. See docs/C-INTEGRATION.md for the contract.
    """

    def cameras(self, now: float) -> Mapping[str, Mapping[str, Any]]: ...


@runtime_checkable
class DecisionSender(Protocol):
    """D's control transport. Serialises the DecisionEvent to the wire."""

    def send(self, event: DecisionEvent, *, decision_seq: int) -> None: ...


@runtime_checkable
class AckReceiver(Protocol):
    """D's ACK callback. LiveLane forwards ACKs into the session."""

    def wait_ack(self) -> tuple[int, bool, float] | None: ...
    """Return (decision_seq, applied, at_monotonic_s) or None if none pending."""


@runtime_checkable
class DeepgramConnection(Protocol):
    """The narrow subset of the deepgram-sdk streaming connection we use."""

    def send_media(self, pcm: bytes) -> None: ...


DeepgramConnectionFactory = Callable[[], "DeepgramSession"]


class DeepgramSession(Protocol):
    """Context manager that yields a ``DeepgramConnection`` and calls the
    ``on_message(msg: dict)`` callback whenever Deepgram sends a Results
    or UtteranceEnd frame. See ``build_deepgram_v1_factory``.
    """

    def __enter__(self) -> DeepgramConnection: ...
    def __exit__(self, *_a: object) -> None: ...


# ---------------------------------------------------------------- resample

def _resample_s16le_mono(
    pcm: bytes, src_rate: int, dst_rate: int,
) -> bytes:
    """Linear resample of 16-bit little-endian mono PCM. No SciPy.

    Only used at the ingress boundary. The mic path already delivers 16 kHz
    mono so this is a no-op there; A's LiveKit path may deliver 48 kHz.
    """
    if src_rate == dst_rate or not pcm:
        return pcm
    import struct
    n = len(pcm) // 2
    if n < 2:
        return pcm
    samples = struct.unpack(f"<{n}h", pcm)
    out_n = int(n * dst_rate / src_rate)
    ratio = (n - 1) / max(1, out_n - 1) if out_n > 1 else 0.0
    out = bytearray(out_n * 2)
    for i in range(out_n):
        pos = i * ratio
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        v = int(samples[lo] * (1 - frac) + samples[hi] * frac)
        v = max(-32768, min(32767, v))
        struct.pack_into("<h", out, i * 2, v)
    return bytes(out)


def _to_s16le_mono(chunk: DecodedAudioChunk) -> bytes:
    """Normalise a DecodedAudioChunk to 16 kHz mono S16LE bytes."""
    pcm = chunk.data
    if chunk.sample_format is SampleFormat.F32LE:
        import struct
        n = len(pcm) // 4
        floats = struct.unpack(f"<{n}f", pcm)
        pcm = struct.pack(
            f"<{n}h",
            *(max(-32768, min(32767, int(f * 32767))) for f in floats),
        )
    if chunk.channels == 2:
        # Mono downmix: (L + R) / 2 in-place.
        import struct
        n_pairs = len(pcm) // 4
        stereo = struct.unpack(f"<{n_pairs * 2}h", pcm)
        mono = [((stereo[i * 2] + stereo[i * 2 + 1]) >> 1) for i in range(n_pairs)]
        pcm = struct.pack(f"<{n_pairs}h", *mono)
    if chunk.sample_rate_hz != TARGET_SAMPLE_RATE:
        pcm = _resample_s16le_mono(pcm, chunk.sample_rate_hz, TARGET_SAMPLE_RATE)
    return pcm


# ---------------------------------------------------------------- LiveLane

class LiveLane:
    """Owns the async loop that drives CLane end-to-end.

    Not a Deepgram client itself — the SDK connection is injected as a
    factory so tests use a fake and the Mac uses the real one.
    """

    def __init__(
        self,
        *,
        pcm_source: PcmSource,
        deepgram_factory: DeepgramConnectionFactory,
        camera_state: CameraStateProvider | None,
        sender: DecisionSender,
        ack_receiver: AckReceiver | None = None,
        parse_fn: Callable[[str], tuple[Cue, float]] | None = None,
        role_based: bool = True,
        role_map: Mapping[str, str] | None = None,
        initial_camera: str = "CAM-HOST",
        camera_state_max_age_s: float = 1.5,
    ) -> None:
        if not (hasattr(pcm_source, "stream") or hasattr(pcm_source, "iter_chunks")):
            raise TypeError("pcm_source must implement stream() or iter_chunks()")
        self._pcm_source = pcm_source
        self._dg_factory = deepgram_factory
        self._camera_state = camera_state
        self._sender = sender
        self._ack_receiver = ack_receiver
        self._role_based = role_based
        self._role_map = dict(role_map or {})
        self._continuity = PcmContinuityGuard()
        # Latency trace: track the wallclock arrival of the *last* Deepgram
        # final Results frame. When a decision emits we compute cue_decide_ms
        # from monotonic time; final_ms comes from audio_seconds_sent minus
        # the record's own transcript_span.ended_at.
        self._last_final_wall_s: float | None = None
        self._audio_seconds_sent = 0.0
        # CLane is composed lazily so build_lane can inject its ownership.
        self._clane = CLane(
            parse_fn=parse_fn or self._default_parse_fn(),
            emit=self._on_decision,
            role_based=role_based,
            role_map=role_map or {},
            camera_state_max_age_s=camera_state_max_age_s,
            initial_camera=initial_camera,
        )

    # ---- read-only ------------------------------------------------

    @property
    def clane(self) -> CLane:
        return self._clane

    # ---- runtime ---------------------------------------------------

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Drive the pipeline until stop_event is set (or PCM source ends)."""
        stop = stop_event or asyncio.Event()
        with self._dg_factory() as dg_conn:
            tasks: list[asyncio.Task] = []
            tasks.append(asyncio.create_task(self._pump_camera_state(stop)))
            tasks.append(asyncio.create_task(self._pump_ack(stop)))
            tasks.append(asyncio.create_task(
                self._pump_pcm(dg_conn, stop),
                name="livelane-pcm",
            ))
            try:
                await stop.wait()
            finally:
                for t in tasks:
                    t.cancel()
                for t in tasks:
                    with contextlib.suppress(BaseException):
                        await t

    # ---- inbound: Deepgram Results/UtteranceEnd -------------------

    def on_deepgram_message(self, msg: dict, now: float) -> None:
        """Public hook the injected DeepgramSession calls per WS frame."""
        # Latency trace: stash the wallclock arrival of the last Deepgram
        # final frame so _on_decision can compute cue_decide_ms.
        try:
            if msg.get("type") == "Results" and (
                msg.get("is_final") or msg.get("speech_final")
            ):
                alt = ((msg.get("channel") or {}).get("alternatives") or [{}])[0]
                if alt.get("words"):
                    self._last_final_wall_s = now
        except Exception:  # noqa: BLE001 -- trace is best-effort
            pass
        # Forward the message through CLane; the assembler emits
        # FinalUtterance events into the SemanticQueue.
        self._clane.on_transcript_message(msg, now)

    # ---- private: pump PCM ----------------------------------------

    async def _pump_pcm(
        self, dg_conn: DeepgramConnection, stop: asyncio.Event,
    ) -> None:
        async for chunk in self._iter_pcm():
            if stop.is_set():
                return
            cont = self._continuity.accept(chunk)
            if not cont.accepted:
                # A logs the reason; we drop and keep going so a single bad
                # chunk never wedges the loop.
                continue
            pcm = _to_s16le_mono(chunk)
            if not pcm:
                continue
            try:
                dg_conn.send_media(pcm)
            except Exception:  # noqa: BLE001 -- dg down; the SPEECH_DOWN gate on Session covers this
                await asyncio.sleep(0.05)
                continue
            self._audio_seconds_sent += (
                len(pcm) // 2
            ) / TARGET_SAMPLE_RATE
            # Fire CLane tick to flush the assembler on utterance-end silence.
            self._clane.tick(time.monotonic())

    async def _iter_pcm(self) -> AsyncIterator[DecodedAudioChunk]:
        stream_fn = getattr(self._pcm_source, "stream", None)
        if stream_fn is not None:
            async for chunk in stream_fn():
                yield chunk
            return
        # Sync iterable fallback: pull in a thread to keep the loop free.
        iter_fn: Callable[[], Iterable[DecodedAudioChunk]] = self._pcm_source.iter_chunks
        it = iter(iter_fn())
        loop = asyncio.get_running_loop()
        while True:
            try:
                chunk = await loop.run_in_executor(None, next, it)  # type: ignore[arg-type]
            except StopIteration:
                return
            yield chunk

    # ---- private: camera state pump ------------------------------

    async def _pump_camera_state(self, stop: asyncio.Event) -> None:
        if self._camera_state is None:
            return
        while not stop.is_set():
            now = time.monotonic()
            cams = dict(self._camera_state.cameras(now))
            if cams:
                self._clane.on_camera_state(cams, now)
            await asyncio.sleep(0.1)

    # ---- private: ack pump ---------------------------------------

    async def _pump_ack(self, stop: asyncio.Event) -> None:
        if self._ack_receiver is None:
            return
        while not stop.is_set():
            ack = self._ack_receiver.wait_ack()
            if ack is None:
                await asyncio.sleep(0.02)
                continue
            seq, applied, at = ack
            trace_key = f"seq={seq}"
            self._trace.setdefault(trace_key, {})["ack_at_monotonic_s"] = at
            self._clane.on_ack(seq, applied, at)

    # ---- outbound: decision -> wire -> D -------------------------

    def _on_decision(self, record: DecisionRecord) -> None:
        # Timeline stamped into DecisionRecord.latencies_ms:
        #   final_ms       = audio_seconds_sent - transcript_span.ended_at
        #                    (audio-time latency of Deepgram's last committed
        #                    word; robust to real-time clock skew).
        #   cue_decide_ms  = decision_emitted_at - _last_final_wall_s
        #                    (wall-clock cost of parser + policy per decision).
        # ack_ms is stamped later by scripts/latency_report.py from the
        # decision log + ACK log; see that script for aggregation.
        span = record.transcript_span or {}
        last_word_end = span.get("ended_at") if isinstance(span, dict) else None
        if last_word_end is not None:
            audio_lat_s = self._audio_seconds_sent - float(last_word_end)
            if audio_lat_s >= 0:
                record.latencies_ms["final_ms"] = audio_lat_s * 1000
        if self._last_final_wall_s is not None:
            record.latencies_ms["cue_decide_ms"] = max(
                0.0, (time.monotonic() - self._last_final_wall_s) * 1000,
            )
        # ROLE_BASED tag lives inside latencies_ms as a sentinel key so we
        # don't have to change DecisionRecord's shape. Consumers can read
        # `record.latencies_ms.get("_identity")` (1.0 or 0.0) if present.
        record.latencies_ms.setdefault(
            "_identity", 1.0 if self._role_based else 0.0,
        )
        event = to_wire(record)
        try:
            self._sender.send(event, decision_seq=record.decision_seq)
        except Exception:  # noqa: BLE001 -- transport down; session already logged
            pass

    # ---- private: helpers ----------------------------------------

    @staticmethod
    def _default_parse_fn() -> Callable[[str], tuple[Cue, float]]:
        """Wrap semantics.parser.parse with the pinned model + 2.5 s cap.

        The 2.5 s cap comes from the plan (safe-shot ceiling). ``parse``
        already returns a safe HOLD on any exception; we just add a hard
        timeout using ``asyncio.wait_for`` in a helper thread so a stuck
        HTTP call never wedges the queue.
        """

        def _bounded(utterance: str) -> tuple[Cue, float]:
            t0 = time.perf_counter()
            model = os.environ.get("CUE_MODEL")
            if not model:
                # Refuse to run without a pinned model; the parse function
                # returns a safe HOLD instead of quietly using a default.
                from cue_api.semantics.parser import (
                    Action,
                    Intent,
                    Scope,
                    TemporalIntent,
                )
                return Cue(
                    target_guest_ids=[], scope=Scope.NONE, intent=Intent.NONE,
                    temporal_intent=TemporalIntent.UNCERTAIN, action=Action.HOLD,
                    evidence_text="ERROR: CUE_MODEL not set",
                ), (time.perf_counter() - t0) * 1000
            return openai_parse(utterance, model=model)

        return _bounded
