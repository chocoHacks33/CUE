from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Path, Response, status
from fastapi.middleware.cors import CORSMiddleware

from cue_api.admission import AdmissionCode, AdmissionError, AdmissionStore
from cue_api.contracts import (
    CAMERA_CONTRACTS,
    CameraBindingResponse,
    HealthResponse,
    PairingClaimRequest,
    PairingClaimResponse,
    PairingDecisionRequest,
    PairingExchangeResponse,
    PairingGrantRequest,
    PairingGrantResponse,
    PairingStatusRequest,
    PairingStatusResponse,
    ProducerPairingClaimResponse,
    PublisherTokenRequest,
    PublisherTokenResponse,
    ReceiverTokenRequest,
    ReceiverTokenResponse,
    TopologyResponse,
)
from cue_api.control import ControlSessionStore, ControlStore
from cue_api.control_socket import ControlHub, build_control_router, build_control_websocket
from cue_api.guests import GuestRegistry, ObservationStore, build_guest_router
from cue_api.guests.identity_evidence import IdentityEvidence, gather
from cue_api.livekit_tokens import (
    LiveKitPublisherTokenIssuer,
    LiveKitReceiverTokenIssuer,
    PublisherTokenIssuer,
    ReceiverTokenIssuer,
)
from cue_api.readiness import ReadinessStore
from cue_api.settings import Settings

EventIdPath = Annotated[
    str,
    Path(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9-]*$"),
]


def create_app(
    settings: Settings | None = None,
    token_issuer: PublisherTokenIssuer | None = None,
    receiver_token_issuer: ReceiverTokenIssuer | None = None,
    guest_registry: GuestRegistry | None = None,
    observation_store: ObservationStore | None = None,
    identity_evidence: Callable[[], IdentityEvidence] | None = None,
    admission_store: AdmissionStore | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    issuer = token_issuer or LiveKitPublisherTokenIssuer(app_settings)
    receiver_issuer = receiver_token_issuer or LiveKitReceiverTokenIssuer(app_settings)
    registry = guest_registry or GuestRegistry()
    observations = observation_store or ObservationStore()
    admissions = admission_store or AdmissionStore(
        grant_ttl_seconds=app_settings.cue_pairing_ttl_seconds,
        claim_ttl_seconds=app_settings.cue_claim_ttl_seconds,
    )
    control_store = ControlStore()
    control_sessions = ControlSessionStore()
    control_hub = ControlHub()
    readiness_store = ReadinessStore()

    app = FastAPI(
        title="CUE API",
        version="0.0.1",
        description="Control-plane foundation for the CUE live director.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        # ngrok-skip-browser-warning: free ngrok tunnels serve an HTML interstitial to
        # browser user agents unless the request carries this header.
        allow_headers=[
            "Content-Type",
            "X-CUE-Bootstrap-Secret",
            "X-CUE-Producer-Secret",
            "ngrok-skip-browser-warning",
        ],
    )

    def require_stage0_admission(presented_secret: str | None) -> None:
        """Shared Stage 0 guard for publisher and receiver credentials."""
        expected_secret = app_settings.cue_bootstrap_secret.get_secret_value()
        if not expected_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stage 0 admission is not configured",
            )
        if not presented_secret or not secrets.compare_digest(presented_secret, expected_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Stage 0 admission secret",
            )
        if not app_settings.livekit_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LiveKit is not configured",
            )

    def require_producer(presented_secret: str | None) -> None:
        expected_secret = app_settings.producer_secret
        if not expected_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Producer admission is not configured",
            )
        if not presented_secret or not secrets.compare_digest(presented_secret, expected_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid producer credential",
            )

    def raise_admission(error: AdmissionError) -> None:
        status_by_code = {
            AdmissionCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
            AdmissionCode.EXPIRED: status.HTTP_410_GONE,
            AdmissionCode.REJECTED: status.HTTP_403_FORBIDDEN,
            AdmissionCode.CONFLICT: status.HTTP_409_CONFLICT,
            AdmissionCode.NOT_APPROVED: status.HTTP_409_CONFLICT,
            AdmissionCode.ALREADY_USED: status.HTTP_409_CONFLICT,
        }
        raise HTTPException(status_code=status_by_code[error.code], detail=str(error)) from error

    @app.get("/health/live", response_model=HealthResponse)
    def health_live() -> HealthResponse:
        return HealthResponse(status="ok", livekit_configured=app_settings.livekit_configured)

    @app.get("/health/ready", response_model=HealthResponse)
    def health_ready(response: Response) -> HealthResponse:
        ready = app_settings.livekit_configured
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="ready" if ready else "not-ready",
            livekit_configured=ready,
        )

    @app.get("/api/v1/topology", response_model=TopologyResponse)
    def topology() -> TopologyResponse:
        return TopologyResponse(cameras=list(CAMERA_CONTRACTS.values()))

    @app.post(
        "/api/v1/stage0/publisher-token",
        response_model=PublisherTokenResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_publisher_token(
        payload: PublisherTokenRequest,
        x_cue_bootstrap_secret: str | None = Header(default=None),
    ) -> PublisherTokenResponse:
        require_stage0_admission(x_cue_bootstrap_secret)

        try:
            issued = issuer.issue(payload.event_id, payload.camera_id, payload.display_name)
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Publisher token service is unavailable",
            ) from error

        return PublisherTokenResponse(
            server_url=app_settings.livekit_url,
            participant_token=issued.token,
            participant_identity=issued.participant_identity,
            room_name=issued.room_name,
            camera=CAMERA_CONTRACTS[payload.camera_id],
            expires_in_seconds=issued.expires_in_seconds,
        )

    @app.post(
        "/api/v1/stage0/receiver-token",
        response_model=ReceiverTokenResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_receiver_token(
        payload: ReceiverTokenRequest,
        x_cue_bootstrap_secret: str | None = Header(default=None),
    ) -> ReceiverTokenResponse:
        """Subscribe-only credential for D's Mac receiver. It can never publish."""
        require_stage0_admission(x_cue_bootstrap_secret)

        try:
            issued = receiver_issuer.issue(
                payload.event_id, payload.receiver_role, payload.display_name
            )
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Receiver token service is unavailable",
            ) from error

        return ReceiverTokenResponse(
            server_url=app_settings.livekit_url,
            participant_token=issued.token,
            participant_identity=issued.participant_identity,
            room_name=issued.room_name,
            receiver_role=payload.receiver_role,
            expires_in_seconds=issued.expires_in_seconds,
        )

    @app.post(
        "/api/v1/events/{event_id}/pairing",
        response_model=PairingGrantResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_pairing_grant(
        event_id: EventIdPath,
        payload: PairingGrantRequest,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> PairingGrantResponse:
        """Create a short-lived capability for exactly one server-owned camera slot."""
        require_producer(x_cue_producer_secret)
        try:
            created = admissions.create_grant(event_id, payload.camera_id)
        except AdmissionError as error:
            raise_admission(error)
        return PairingGrantResponse(
            grant_id=created.grant.grant_id,
            pairing_token=created.pairing_token,
            verification_code=created.grant.verification_code,
            camera=CAMERA_CONTRACTS[created.grant.camera_id],
            expires_in_seconds=created.expires_in_seconds,
        )

    @app.post(
        "/api/v1/pairing/claim",
        response_model=PairingClaimResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def claim_pairing(payload: PairingClaimRequest) -> PairingClaimResponse:
        """Consume a single-use pairing token. Camera role comes only from the token."""
        try:
            created = admissions.claim(
                payload.pairing_token,
                payload.display_name,
                payload.device_label,
            )
        except AdmissionError as error:
            raise_admission(error)
        claim = created.claim
        return PairingClaimResponse(
            claim_id=claim.claim_id,
            claim_secret=created.claim_secret,
            verification_code=claim.verification_code,
            camera=CAMERA_CONTRACTS[claim.camera_id],
            status=claim.status.value,
            expires_in_seconds=created.expires_in_seconds,
        )

    @app.post("/api/v1/pairing/status", response_model=PairingStatusResponse)
    def pairing_status(payload: PairingStatusRequest) -> PairingStatusResponse:
        try:
            claim = admissions.status(payload.claim_id, payload.claim_secret)
        except AdmissionError as error:
            raise_admission(error)
        return PairingStatusResponse(
            claim_id=claim.claim_id,
            status=claim.status.value,
            verification_code=claim.verification_code,
            camera=CAMERA_CONTRACTS[claim.camera_id],
            expires_in_seconds=admissions.remaining_seconds(claim.expires_at),
        )

    @app.get(
        "/api/v1/events/{event_id}/pairing-claims",
        response_model=list[ProducerPairingClaimResponse],
    )
    def list_pairing_claims(
        event_id: EventIdPath,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> list[ProducerPairingClaimResponse]:
        require_producer(x_cue_producer_secret)
        return [
            ProducerPairingClaimResponse(
                claim_id=claim.claim_id,
                status=claim.status.value,
                verification_code=claim.verification_code,
                camera=CAMERA_CONTRACTS[claim.camera_id],
                expires_in_seconds=admissions.remaining_seconds(claim.expires_at),
                display_name=claim.display_name,
                device_label=claim.device_label,
            )
            for claim in admissions.list_claims(event_id)
        ]

    @app.post(
        "/api/v1/events/{event_id}/devices/{claim_id}/approve",
        response_model=ProducerPairingClaimResponse,
    )
    def decide_pairing_claim(
        event_id: EventIdPath,
        claim_id: str,
        payload: PairingDecisionRequest,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> ProducerPairingClaimResponse:
        require_producer(x_cue_producer_secret)
        try:
            claim = admissions.decide(event_id, claim_id, payload.approved)
        except AdmissionError as error:
            raise_admission(error)
        return ProducerPairingClaimResponse(
            claim_id=claim.claim_id,
            status=claim.status.value,
            verification_code=claim.verification_code,
            camera=CAMERA_CONTRACTS[claim.camera_id],
            expires_in_seconds=admissions.remaining_seconds(claim.expires_at),
            display_name=claim.display_name,
            device_label=claim.device_label,
        )

    @app.post(
        "/api/v1/pairing/exchange",
        response_model=PairingExchangeResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def exchange_pairing(payload: PairingStatusRequest) -> PairingExchangeResponse:
        if not app_settings.livekit_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LiveKit is not configured",
            )
        try:
            claim = admissions.begin_exchange(payload.claim_id, payload.claim_secret)
        except AdmissionError as error:
            raise_admission(error)
        try:
            issued = issuer.issue(
                claim.event_id,
                claim.camera_id,
                claim.display_name,
                participant_identity=claim.participant_identity,
                stream_epoch=1,
                device_session_id=claim.device_session_id,
            )
            if (
                issued.participant_identity != claim.participant_identity
                or issued.room_name != f"cue-{claim.event_id}"
            ):
                raise RuntimeError("Token issuer returned a mismatched binding")
            binding = admissions.complete_exchange(claim.claim_id)
        except AdmissionError as error:
            admissions.abort_exchange(claim.claim_id)
            raise_admission(error)
        except Exception as error:  # noqa: BLE001 - restore claim after any issuer failure
            admissions.abort_exchange(claim.claim_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Publisher token service is unavailable",
            ) from error

        return PairingExchangeResponse(
            server_url=app_settings.livekit_url,
            participant_token=issued.token,
            participant_identity=issued.participant_identity,
            room_name=issued.room_name,
            camera=CAMERA_CONTRACTS[claim.camera_id],
            expires_in_seconds=issued.expires_in_seconds,
            device_session_id=binding.device_session_id,
            stream_epoch=binding.stream_epoch,
        )

    @app.get(
        "/api/v1/events/{event_id}/bindings",
        response_model=list[CameraBindingResponse],
    )
    def list_camera_bindings(
        event_id: EventIdPath,
        x_cue_producer_secret: str | None = Header(default=None),
    ) -> list[CameraBindingResponse]:
        require_producer(x_cue_producer_secret)
        return [
            CameraBindingResponse.model_validate(binding.__dict__)
            for binding in admissions.list_bindings(event_id)
        ]

    app.include_router(
        build_guest_router(
            app_settings,
            registry,
            observations,
            evidence=identity_evidence or gather,
        )
    )
    app.include_router(
        build_control_router(
            control_store,
            control_sessions,
            control_hub,
            readiness_store,
            require_producer,
        )
    )
    app.add_api_websocket_route(
        "/api/v1/events/{event_id}/control",
        build_control_websocket(control_store, control_sessions, control_hub, readiness_store),
    )
    app.state.control_store = control_store
    app.state.control_sessions = control_sessions
    app.state.readiness_store = readiness_store

    return app


app = create_app()
