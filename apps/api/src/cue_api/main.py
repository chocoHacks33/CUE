from __future__ import annotations

import secrets

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from cue_api.contracts import (
    CAMERA_CONTRACTS,
    HealthResponse,
    PublisherTokenRequest,
    PublisherTokenResponse,
    ReceiverTokenRequest,
    ReceiverTokenResponse,
    TopologyResponse,
)
from cue_api.guests import GuestRegistry, ObservationStore, build_guest_router
from cue_api.livekit_tokens import (
    LiveKitPublisherTokenIssuer,
    LiveKitReceiverTokenIssuer,
    PublisherTokenIssuer,
    ReceiverTokenIssuer,
)
from cue_api.settings import Settings


def create_app(
    settings: Settings | None = None,
    token_issuer: PublisherTokenIssuer | None = None,
    receiver_token_issuer: ReceiverTokenIssuer | None = None,
    guest_registry: GuestRegistry | None = None,
    observation_store: ObservationStore | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    issuer = token_issuer or LiveKitPublisherTokenIssuer(app_settings)
    receiver_issuer = receiver_token_issuer or LiveKitReceiverTokenIssuer(app_settings)
    registry = guest_registry or GuestRegistry()
    observations = observation_store or ObservationStore()

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
        allow_headers=["Content-Type", "X-CUE-Bootstrap-Secret", "ngrok-skip-browser-warning"],
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

    app.include_router(build_guest_router(app_settings, registry, observations))

    return app


app = create_app()
