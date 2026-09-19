"""Person B's guest, consent and visual-observation routes.

Hosted by A's FastAPI app on D's Mac. These routes accept observations and
consent decisions. They never accept or emit a camera command.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from cue_api.contracts import CameraId
from cue_api.guests.contracts import (
    GalleryEntry,
    GalleryResponse,
    GuestEnrolmentRequest,
    GuestListResponse,
    GuestRecord,
    InvalidationRequest,
    ObservationSnapshot,
    PurgeReceipt,
    ReferenceSubmission,
    VisualObservation,
)
from cue_api.guests.observations import ObservationStore, StaleEpochError
from cue_api.guests.registry import ConsentError, GuestNotFoundError, GuestRegistry
from cue_api.settings import Settings

# Query parameters carry the same camelCase spelling as the JSON contracts.
EVENT_ID_QUERY = Query(
    alias="eventId",
    min_length=3,
    max_length=48,
    pattern=r"^[a-z0-9][a-z0-9-]*$",
)


def _default_clock() -> int:
    return int(time.time() * 1000)


def build_guest_router(
    settings: Settings,
    registry: GuestRegistry,
    observations: ObservationStore,
    clock: Callable[[], int] = _default_clock,
) -> APIRouter:
    def require_operator(
        x_cue_bootstrap_secret: str | None = Header(default=None),
    ) -> None:
        """Stage 1 reuses A's admission guard; A replaces it with real sessions."""
        expected = settings.cue_bootstrap_secret.get_secret_value()
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guest enrolment is not configured",
            )
        if not x_cue_bootstrap_secret or not secrets.compare_digest(
            x_cue_bootstrap_secret,
            expected,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid guest operator credential",
            )

    router = APIRouter(prefix="/api/v1", tags=["guests"], dependencies=[Depends(require_operator)])

    @router.post(
        "/guests",
        response_model=GuestRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def enrol_guest(payload: GuestEnrolmentRequest) -> GuestRecord:
        try:
            return registry.enrol(
                event_id=payload.event_id,
                display_name=payload.display_name,
                aliases=payload.aliases,
                consent_granted=payload.consent_granted,
                consent_purposes=payload.consent_purposes,
                recorded_by=payload.recorded_by,
                guest_id=payload.guest_id,
                now_ms=clock(),
            )
        except ConsentError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/guests", response_model=GuestListResponse)
    def list_guests(event_id: str = EVENT_ID_QUERY) -> GuestListResponse:
        return GuestListResponse(
            event_id=event_id,
            gallery_version=registry.gallery_version,
            guests=registry.list_guests(event_id),
        )

    @router.post(
        "/guests/{guest_id}/references",
        response_model=GuestRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def add_reference(guest_id: str, payload: ReferenceSubmission) -> GuestRecord:
        try:
            return registry.add_reference(
                event_id=payload.event_id,
                guest_id=guest_id,
                embedding=payload.embedding,
                quality=payload.quality,
                embedder=payload.embedder,
                embedder_version=payload.embedder_version,
                captured_at_ms=payload.captured_at_ms,
                now_ms=clock(),
            )
        except GuestNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ConsentError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    @router.delete("/guests/{guest_id}", response_model=PurgeReceipt)
    def withdraw_consent(guest_id: str, event_id: str = EVENT_ID_QUERY) -> PurgeReceipt:
        now_ms = clock()
        try:
            _, deleted = registry.withdraw(event_id=event_id, guest_id=guest_id, now_ms=now_ms)
        except GuestNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        dropped = observations.drop_guest(event_id=event_id, guest_id=guest_id)
        return PurgeReceipt(
            event_id=event_id,
            guest_ids=[guest_id],
            references_deleted=deleted,
            observations_dropped=dropped,
            purged_at_ms=now_ms,
        )

    @router.delete("/guests", response_model=PurgeReceipt)
    def purge_event(event_id: str = EVENT_ID_QUERY) -> PurgeReceipt:
        guest_ids, deleted = registry.purge_event(event_id=event_id)
        dropped = observations.drop_event(event_id=event_id)
        return PurgeReceipt(
            event_id=event_id,
            guest_ids=guest_ids,
            references_deleted=deleted,
            observations_dropped=dropped,
            purged_at_ms=clock(),
        )

    @router.get("/vision/gallery", response_model=GalleryResponse)
    def read_gallery(event_id: str = EVENT_ID_QUERY) -> GalleryResponse:
        """Worker-only. Carries embeddings, so it never reaches a browser."""
        gallery_version, entries = registry.gallery(event_id)
        return GalleryResponse(
            event_id=event_id,
            gallery_version=gallery_version,
            entries=[
                GalleryEntry(
                    guest_id=guest_id,
                    display_name=display_name,
                    reference_version=reference_version,
                    embeddings=embeddings,
                )
                for guest_id, display_name, reference_version, embeddings in entries
            ],
        )

    @router.post(
        "/vision/observations",
        response_model=VisualObservation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def record_observation(observation: VisualObservation) -> VisualObservation:
        guest_id = observation.subject.guest_id
        if guest_id is not None and not registry.is_identifiable(observation.event_id, guest_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Guest {guest_id} is not an identifiable consenting guest; "
                    "refresh the gallery and resubmit without an identity"
                ),
            )
        try:
            return observations.record(observation)
        except StaleEpochError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/vision/observations", response_model=ObservationSnapshot)
    def read_observations(event_id: str = EVENT_ID_QUERY) -> ObservationSnapshot:
        return observations.snapshot(
            event_id=event_id,
            now_ms=clock(),
            gallery_version=registry.gallery_version,
        )

    @router.post("/vision/invalidate", response_model=ObservationSnapshot)
    def invalidate(payload: InvalidationRequest) -> ObservationSnapshot:
        observations.invalidate(
            event_id=payload.event_id,
            camera_id=payload.camera_id,
            current_stream_epoch=payload.current_stream_epoch,
            reason=payload.reason,
        )
        return observations.snapshot(
            event_id=payload.event_id,
            now_ms=clock(),
            gallery_version=registry.gallery_version,
        )

    @router.get("/vision/tallies")
    def read_tallies(event_id: str = EVENT_ID_QUERY) -> dict[str, object]:
        """Status counts for B's identity report. Not per-face history."""
        return {
            "eventId": event_id,
            "galleryVersion": registry.gallery_version,
            "epochs": {
                camera_id.value: observations.current_epoch(
                    event_id=event_id,
                    camera_id=camera_id,
                )
                for camera_id in CameraId
            },
            "statusCounts": observations.tallies(event_id=event_id),
        }

    return router
