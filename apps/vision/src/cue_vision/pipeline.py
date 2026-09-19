"""The observation pipeline: frame in, observations out.

Nothing in this module selects a camera, requests a cut or ranks a shot. It
reports what it saw, how well it saw it and how long that remains true.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from cue_vision.calibration import PROVISIONAL_CALIBRATION, Calibration
from cue_vision.gallery import ReferenceGallery, normalise
from cue_vision.ledger import DEFAULT_IDENTITY_TTL_MS, IdentityLedger
from cue_vision.matching import MatchDecision, MatchThresholds, match
from cue_vision.quality import QualityPolicy, QualityVerdict, assess
from cue_vision.tracking import LocalTracker
from cue_vision.types import (
    CalibrationStatus,
    DecodedFrame,
    Embedding,
    FaceDetection,
    ObservationStatus,
)
from cue_vision.version import PIPELINE_VERSION, VISION_CONTRACT_VERSION


class FaceDetector(Protocol):
    name: str
    version: str

    def detect(self, frame: DecodedFrame) -> list[FaceDetection]: ...


class FaceEmbedder(Protocol):
    name: str
    version: str
    dimension: int

    def embed(self, frame: DecodedFrame, detection: FaceDetection) -> Embedding: ...


@dataclass(frozen=True)
class Observation:
    """One face on one frame, in the shared visual-observation vocabulary."""

    observation_id: str
    event_id: str
    camera_id: str
    stream_epoch: int
    track_key: str
    frame_sequence: int
    status: ObservationStatus
    guest_id: str | None
    display_name: str | None
    reference_version: int | None
    box: dict[str, float] | None
    quality: QualityVerdict
    similarity: float | None
    margin: float | None
    runner_up_guest_id: str | None
    calibrated_confidence: float | None
    calibration_id: str
    calibration_status: CalibrationStatus
    consecutive_confirmations: int
    gallery_version: int
    detector: str
    detector_version: str
    embedder: str
    embedder_version: str
    captured_at_ms: int | None
    observed_at_ms: int
    expires_at_ms: int
    clock_uncertainty_ms: int
    usable_for_named_take: bool

    def to_contract(self) -> dict[str, object]:
        """The exact payload the backend and the producer UI validate."""
        return {
            "visionContractVersion": VISION_CONTRACT_VERSION,
            "observationId": self.observation_id,
            "eventId": self.event_id,
            "cameraId": self.camera_id,
            "streamEpoch": self.stream_epoch,
            "trackKey": self.track_key,
            "frameSequence": self.frame_sequence,
            "status": self.status.value,
            "subject": {
                "guestId": self.guest_id,
                "displayName": self.display_name,
                "referenceVersion": self.reference_version,
            },
            "box": dict(self.box) if self.box else None,
            "quality": self.quality.as_contract(),
            "match": {
                "calibratedConfidence": _round_or_none(self.calibrated_confidence),
                "calibrationId": self.calibration_id,
                "calibrationStatus": self.calibration_status.value,
                "margin": _round_or_none(self.margin),
                "similarity": _round_or_none(self.similarity),
                "runnerUpGuestId": self.runner_up_guest_id,
                "consecutiveConfirmations": self.consecutive_confirmations,
            },
            "provenance": {
                "pipelineVersion": PIPELINE_VERSION,
                "detector": self.detector,
                "detectorVersion": self.detector_version,
                "embedder": self.embedder,
                "embedderVersion": self.embedder_version,
                "galleryVersion": self.gallery_version,
            },
            "timing": {
                "capturedAtMs": self.captured_at_ms,
                "observedAtMs": self.observed_at_ms,
                "expiresAtMs": self.expires_at_ms,
                "clockDomain": "WORKER_MONOTONIC_MAPPED",
                "clockUncertaintyMs": self.clock_uncertainty_ms,
            },
            "usableForNamedTake": self.usable_for_named_take,
        }

    def as_log_record(self) -> dict[str, object]:
        """Diagnostics without the subject's name, for shareable logs."""
        record = asdict(self)
        record.pop("display_name", None)
        record["quality"] = self.quality.as_contract()
        record["status"] = self.status.value
        record["calibration_status"] = self.calibration_status.value
        return record


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@dataclass
class VisionPipeline:
    event_id: str
    detector: FaceDetector
    embedder: FaceEmbedder
    gallery: ReferenceGallery = field(default_factory=ReferenceGallery.empty)
    quality_policy: QualityPolicy = field(default_factory=QualityPolicy)
    thresholds: MatchThresholds = field(default_factory=MatchThresholds)
    calibration: Calibration = PROVISIONAL_CALIBRATION
    identity_ttl_ms: int = DEFAULT_IDENTITY_TTL_MS
    #: Mapping A's worker clock onto the backend clock is never exact.
    clock_uncertainty_ms: int = 50
    #: More faces than this in one frame is a group shot, not a named close-up.
    max_faces_per_frame: int = 4
    tracker: LocalTracker = field(default_factory=LocalTracker)
    ledger: IdentityLedger = field(init=False)

    def __post_init__(self) -> None:
        self.ledger = IdentityLedger(
            thresholds=self.thresholds,
            identity_ttl_ms=self.identity_ttl_ms,
        )

    def set_gallery(self, gallery: ReferenceGallery) -> None:
        """Adopt a refreshed gallery; anyone removed from it loses their identity."""
        known = {guest.guest_id for guest in gallery.guests}
        for guest in self.gallery.guests:
            if guest.guest_id not in known:
                self.ledger.forget_guest(guest.guest_id)
        self.gallery = gallery

    def invalidate_camera(self, camera_id: str, reason: str) -> int:
        """Re-publish, webcam change, reframe or lost track: evidence is void."""
        self.tracker.reset_camera(camera_id)
        return self.ledger.forget_camera(camera_id)

    def forget_guest(self, guest_id: str) -> int:
        return self.ledger.forget_guest(guest_id)

    def observe(self, frame: DecodedFrame) -> list[Observation]:
        now_ms = frame.received_at_ms
        self.ledger.prune(now_ms)

        detections = list(self.detector.detect(frame))[: self.max_faces_per_frame]
        if not detections:
            for track_key in self.tracker.expired_keys(frame.camera_id, frame.stream_epoch, now_ms):
                self.ledger.forget_track(track_key)
            return [self._no_face_observation(frame, now_ms)]

        track_keys = self.tracker.assign(
            frame.camera_id,
            frame.stream_epoch,
            detections,
            now_ms,
        )
        for track_key in self.tracker.expired_keys(frame.camera_id, frame.stream_epoch, now_ms):
            self.ledger.forget_track(track_key)

        observations: list[Observation] = []
        for detection, track_key in zip(detections, track_keys, strict=True):
            observations.append(self._observe_face(frame, detection, track_key, now_ms))
        return observations

    def _observe_face(
        self,
        frame: DecodedFrame,
        detection: FaceDetection,
        track_key: str,
        now_ms: int,
    ) -> Observation:
        verdict = assess(frame, detection, self.quality_policy)
        box = detection.box.normalised(frame.width, frame.height)

        if not verdict.passed:
            # An unreadable face is an abstention, not a weaker guess.
            self.ledger.observe_non_identity(track_key)
            return self._build(
                frame,
                track_key,
                now_ms,
                status=ObservationStatus.LOW_QUALITY,
                quality=verdict,
                box=box,
            )

        embedding = normalise(self.embedder.embed(frame, detection))
        result = match(embedding, self.gallery, self.thresholds)

        if result.decision is not MatchDecision.CANDIDATE:
            self.ledger.observe_non_identity(track_key)
            status = (
                ObservationStatus.AMBIGUOUS
                if result.decision is MatchDecision.AMBIGUOUS
                else ObservationStatus.UNKNOWN
            )
            return self._build(
                frame,
                track_key,
                now_ms,
                status=status,
                quality=verdict,
                box=box,
                similarity=result.similarity,
                margin=result.margin,
                runner_up_guest_id=result.runner_up_guest_id,
            )

        assert result.guest_id is not None
        assertion = self.ledger.observe_candidate(track_key, result.guest_id, now_ms)
        confirmed = assertion.status is ObservationStatus.CONFIRMED
        return self._build(
            frame,
            track_key,
            now_ms,
            status=assertion.status,
            quality=verdict,
            box=box,
            guest_id=result.guest_id,
            display_name=result.display_name,
            reference_version=result.reference_version,
            similarity=result.similarity,
            margin=result.margin,
            runner_up_guest_id=result.runner_up_guest_id,
            consecutive_confirmations=assertion.consecutive_confirmations,
            expires_at_ms=assertion.expires_at_ms,
            usable_for_named_take=confirmed,
        )

    def _no_face_observation(self, frame: DecodedFrame, now_ms: int) -> Observation:
        empty_quality = QualityVerdict(
            passed=False,
            score=0.0,
            face_width_ratio=0.0,
            sharpness=0.0,
            brightness=0.0,
            detector_score=0.0,
            failed_checks=("no_face_detected",),
        )
        return self._build(
            frame,
            f"{frame.camera_id}:{frame.stream_epoch}:no-face",
            now_ms,
            status=ObservationStatus.NO_FACE,
            quality=empty_quality,
            box=None,
        )

    def _build(
        self,
        frame: DecodedFrame,
        track_key: str,
        now_ms: int,
        *,
        status: ObservationStatus,
        quality: QualityVerdict,
        box: dict[str, float] | None,
        guest_id: str | None = None,
        display_name: str | None = None,
        reference_version: int | None = None,
        similarity: float | None = None,
        margin: float | None = None,
        runner_up_guest_id: str | None = None,
        consecutive_confirmations: int = 0,
        expires_at_ms: int | None = None,
        usable_for_named_take: bool = False,
    ) -> Observation:
        return Observation(
            observation_id=f"{frame.camera_id}:{frame.stream_epoch}:{frame.sequence}:{track_key}",
            event_id=self.event_id,
            camera_id=frame.camera_id,
            stream_epoch=frame.stream_epoch,
            track_key=track_key,
            frame_sequence=frame.sequence,
            status=status,
            guest_id=guest_id,
            display_name=display_name,
            reference_version=reference_version,
            box=box,
            quality=quality,
            similarity=similarity,
            margin=margin,
            runner_up_guest_id=runner_up_guest_id,
            calibrated_confidence=(
                self.calibration.confidence(similarity) if guest_id is not None else None
            ),
            calibration_id=self.calibration.calibration_id,
            calibration_status=self.calibration.status,
            consecutive_confirmations=consecutive_confirmations,
            gallery_version=self.gallery.version,
            detector=self.detector.name,
            detector_version=self.detector.version,
            embedder=self.embedder.name,
            embedder_version=self.embedder.version,
            captured_at_ms=frame.captured_at_ms,
            observed_at_ms=now_ms,
            expires_at_ms=(
                expires_at_ms if expires_at_ms is not None else now_ms + self.identity_ttl_ms
            ),
            clock_uncertainty_ms=self.clock_uncertainty_ms,
            usable_for_named_take=usable_for_named_take,
        )
