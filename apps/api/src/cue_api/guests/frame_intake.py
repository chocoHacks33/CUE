"""Adapting A's decoded frames into the shape B's pipeline analyses.

A owns capture and decoding and hands over `DecodedVideoFrame` through a
capacity-one `LatestFrameSlot`. B owns identity. This module is the only seam
between them, and it is deliberately strict: a frame that is not already upright,
unmirrored and BGR24 is refused rather than silently corrected.

That strictness is the point. Rotating or un-mirroring here would make two owners
responsible for geometry, and a face detector fed a mirrored or rotated frame
does not fail loudly — it returns plausible boxes with landmark geometry that is
quietly wrong, which is exactly the failure this project must not ship.

The other job here is time. A timestamps frames on a monotonic worker clock; the
backend judges freshness on wall time. The two cannot be compared without a
mapping, so `WorkerClock` makes the mapping explicit and carries its own
uncertainty, which every observation then declares as
`clockDomain: WORKER_MONOTONIC_MAPPED`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from cue_api.guests.types import DecodedFrame
from cue_api.media_contracts import DecodedVideoFrame, PixelFormat

#: B analyses BGR24 because that is what OpenCV's YuNet and SFace wrappers take.
REQUIRED_PIXEL_FORMAT = PixelFormat.BGR24


class FrameRejected(ValueError):
    """The frame cannot be analysed as delivered. It is dropped, never patched."""


@dataclass(frozen=True)
class FramePayload:
    """The pixels, kept opaque.

    B's pure-Python core never indexes this; only the OpenCV adapter does. Keeping
    the stride alongside the bytes means the adapter can build a view without
    guessing the row padding.
    """

    data: bytes
    width: int
    height: int
    stride_bytes: int
    pixel_format: PixelFormat

    def __post_init__(self) -> None:
        if len(self.data) != self.stride_bytes * self.height:
            raise ValueError("Payload length does not match stride_bytes * height")

    @property
    def row_bytes(self) -> int:
        """Bytes of actual pixel data per row, ignoring any padding."""
        return self.width * self.pixel_format.bytes_per_pixel

    def packed_bytes(self) -> bytes:
        """The pixels with row padding removed, ready to reshape.

        Kept pure Python so the stride arithmetic is verified by tests on every
        machine, leaving only the numpy reshape on the untested live path.
        """
        row = self.row_bytes
        if self.stride_bytes == row:
            return self.data
        return b"".join(
            self.data[y * self.stride_bytes : y * self.stride_bytes + row]
            for y in range(self.height)
        )


@dataclass(frozen=True)
class WorkerClock:
    """Maps A's monotonic worker clock onto backend wall time.

    The mapping is an anchor pair sampled once, plus an honest uncertainty. It is
    never exact: the two clocks are read at slightly different instants and drift
    apart afterwards.
    """

    wall_reference_ms: int
    monotonic_reference_s: float
    uncertainty_ms: int = 50

    def __post_init__(self) -> None:
        if self.uncertainty_ms < 0:
            raise ValueError("Clock uncertainty cannot be negative")

    @classmethod
    def sample(cls, uncertainty_ms: int = 50) -> WorkerClock:
        """Anchor the two clocks as close together as the interpreter allows."""
        monotonic_s = time.monotonic()
        wall_ms = int(time.time() * 1000)
        return cls(
            wall_reference_ms=wall_ms,
            monotonic_reference_s=monotonic_s,
            uncertainty_ms=uncertainty_ms,
        )

    def to_wall_ms(self, monotonic_s: float) -> int:
        delta_ms = (monotonic_s - self.monotonic_reference_s) * 1000.0
        return self.wall_reference_ms + round(delta_ms)


def adapt(frame: DecodedVideoFrame, clock: WorkerClock) -> DecodedFrame:
    """A's frame as B's frame, or `FrameRejected` explaining why not.

    Every refusal names the owner who can fix it, because a dropped frame that
    nobody can act on is just a silent blind spot.
    """
    if frame.orientation_degrees != 0:
        raise FrameRejected(
            f"{frame.camera_id.value} delivered a frame rotated "
            f"{frame.orientation_degrees} degrees; ingest must rotate it upright "
            "so one owner handles orientation"
        )
    if frame.mirrored:
        raise FrameRejected(
            f"{frame.camera_id.value} delivered a mirrored frame; ingest must "
            "un-mirror it, because mirrored landmark geometry is wrong without "
            "looking wrong"
        )
    if frame.pixel_format is not REQUIRED_PIXEL_FORMAT:
        raise FrameRejected(
            f"{frame.camera_id.value} delivered {frame.pixel_format.value}; "
            f"B analyses {REQUIRED_PIXEL_FORMAT.value} and does not convert"
        )

    captured_at_ms = (
        None if frame.capture_time_s is None else clock.to_wall_ms(frame.capture_time_s)
    )
    return DecodedFrame(
        camera_id=frame.camera_id.value,
        stream_epoch=frame.stream_epoch,
        sequence=frame.sequence,
        width=frame.width,
        height=frame.height,
        received_at_ms=clock.to_wall_ms(frame.received_at_monotonic_s),
        image=FramePayload(
            data=frame.data,
            width=frame.width,
            height=frame.height,
            stride_bytes=frame.stride_bytes,
            pixel_format=frame.pixel_format,
        ),
        pixel_format=frame.pixel_format.value,
        orientation_degrees=0,
        captured_at_ms=captured_at_ms,
    )
