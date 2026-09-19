from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from livekit import api

from cue_api.contracts import CAMERA_CONTRACTS, CONTRACT_VERSION, CameraId, ReceiverRole
from cue_api.settings import Settings


@dataclass(frozen=True)
class IssuedPublisherToken:
    token: str
    participant_identity: str
    room_name: str
    expires_in_seconds: int


class PublisherTokenIssuer(Protocol):
    def issue(self, event_id: str, camera_id: CameraId, display_name: str) -> IssuedPublisherToken:
        """Issue one publisher credential using a server-owned camera contract."""


class LiveKitPublisherTokenIssuer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def issue(self, event_id: str, camera_id: CameraId, display_name: str) -> IssuedPublisherToken:
        if not self._settings.livekit_configured:
            raise RuntimeError("LiveKit is not configured")

        contract = CAMERA_CONTRACTS[camera_id]
        room_name = f"cue-{event_id}"
        participant_identity = f"publisher:{event_id}:{camera_id.value}"
        expires_in_seconds = self._settings.cue_token_ttl_minutes * 60
        publish_sources = ["camera"]
        if contract.audio_policy.value == "MASTER":
            publish_sources.append("microphone")

        metadata = json.dumps(
            {
                "contractVersion": CONTRACT_VERSION,
                "eventId": event_id,
                "cameraId": camera_id.value,
                "role": contract.role.value,
                "audioPolicy": contract.audio_policy.value,
                "streamEpoch": 1,
            },
            separators=(",", ":"),
        )

        token = (
            api.AccessToken(
                self._settings.livekit_api_key,
                self._settings.livekit_api_secret.get_secret_value(),
            )
            .with_identity(participant_identity)
            .with_name(display_name)
            .with_metadata(metadata)
            .with_ttl(timedelta(seconds=expires_in_seconds))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_publish_sources=publish_sources,
                    can_subscribe=False,
                    can_publish_data=False,
                    can_update_own_metadata=False,
                )
            )
            .to_jwt()
        )

        return IssuedPublisherToken(
            token=token,
            participant_identity=participant_identity,
            room_name=room_name,
            expires_in_seconds=expires_in_seconds,
        )


@dataclass(frozen=True)
class IssuedReceiverToken:
    token: str
    participant_identity: str
    room_name: str
    expires_in_seconds: int


class ReceiverTokenIssuer(Protocol):
    def issue(
        self, event_id: str, receiver_role: ReceiverRole, display_name: str
    ) -> IssuedReceiverToken:
        """Issue one subscribe-only credential for a receiver session."""


class LiveKitReceiverTokenIssuer:
    """Subscribe-only grants for D's Mac.

    The token cannot publish, so a receiver can never add the Mac's camera or
    microphone to the room even by mistake. Every session gets a distinct
    identity so a second browser tab never impersonates the active receiver.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def issue(
        self, event_id: str, receiver_role: ReceiverRole, display_name: str
    ) -> IssuedReceiverToken:
        if not self._settings.livekit_configured:
            raise RuntimeError("LiveKit is not configured")

        room_name = f"cue-{event_id}"
        session_id = secrets.token_hex(4)
        participant_identity = f"receiver:{event_id}:{receiver_role.value.lower()}:{session_id}"
        expires_in_seconds = self._settings.cue_token_ttl_minutes * 60

        metadata = json.dumps(
            {
                "contractVersion": CONTRACT_VERSION,
                "eventId": event_id,
                "receiverRole": receiver_role.value,
                "sessionId": session_id,
            },
            separators=(",", ":"),
        )

        token = (
            api.AccessToken(
                self._settings.livekit_api_key,
                self._settings.livekit_api_secret.get_secret_value(),
            )
            .with_identity(participant_identity)
            .with_name(display_name)
            .with_metadata(metadata)
            .with_ttl(timedelta(seconds=expires_in_seconds))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=False,
                    can_subscribe=True,
                    can_publish_data=False,
                    can_update_own_metadata=False,
                )
            )
            .to_jwt()
        )

        return IssuedReceiverToken(
            token=token,
            participant_identity=participant_identity,
            room_name=room_name,
            expires_in_seconds=expires_in_seconds,
        )
