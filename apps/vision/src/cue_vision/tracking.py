"""Short-lived local face tracking inside one camera epoch.

Tracks exist only to accumulate consistent evidence about the same face across a
few frames. A track is not an identity, and a track key never survives an epoch
change, so a guest who moves to another camera does not carry their old label.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cue_vision.types import FaceDetection, PixelBox


@dataclass
class _Track:
    key: str
    box: PixelBox
    last_seen_ms: int


@dataclass
class LocalTracker:
    #: Overlap needed to treat a detection as the same face as last frame.
    min_iou: float = 0.3
    #: A track unseen for longer than this is gone, and its identity with it.
    track_ttl_ms: int = 800
    _tracks: dict[tuple[str, int], list[_Track]] = field(default_factory=dict, repr=False)
    # Monotonic per camera, never per epoch: a reset or an epoch change must not
    # hand out a key that an in-flight observation is still carrying.
    _counters: dict[str, int] = field(default_factory=dict, repr=False)

    def assign(
        self,
        camera_id: str,
        stream_epoch: int,
        detections: list[FaceDetection],
        now_ms: int,
    ) -> list[str]:
        """Return one stable track key per detection, in detection order."""
        self._drop_superseded_epochs(camera_id, stream_epoch)
        scope = (camera_id, stream_epoch)
        tracks = [
            track
            for track in self._tracks.get(scope, [])
            if now_ms - track.last_seen_ms <= self.track_ttl_ms
        ]

        assigned: list[str] = []
        claimed: set[str] = set()
        for detection in detections:
            best_track: _Track | None = None
            best_iou = self.min_iou
            for track in tracks:
                if track.key in claimed:
                    continue
                iou = detection.box.intersection_over_union(track.box)
                if iou >= best_iou:
                    best_track, best_iou = track, iou

            if best_track is None:
                self._counters[camera_id] = self._counters.get(camera_id, 0) + 1
                best_track = _Track(
                    key=f"{camera_id}:{stream_epoch}:face-{self._counters[camera_id]}",
                    box=detection.box,
                    last_seen_ms=now_ms,
                )
                tracks.append(best_track)
            else:
                best_track.box = detection.box
                best_track.last_seen_ms = now_ms

            claimed.add(best_track.key)
            assigned.append(best_track.key)

        self._tracks[scope] = tracks
        return assigned

    def expired_keys(self, camera_id: str, stream_epoch: int, now_ms: int) -> list[str]:
        scope = (camera_id, stream_epoch)
        return [
            track.key
            for track in self._tracks.get(scope, [])
            if now_ms - track.last_seen_ms > self.track_ttl_ms
        ]

    def reset_camera(self, camera_id: str) -> None:
        for scope in [scope for scope in self._tracks if scope[0] == camera_id]:
            del self._tracks[scope]

    def _drop_superseded_epochs(self, camera_id: str, stream_epoch: int) -> None:
        stale = [
            scope for scope in self._tracks if scope[0] == camera_id and scope[1] != stream_epoch
        ]
        for scope in stale:
            del self._tracks[scope]
