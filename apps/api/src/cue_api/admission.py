from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from cue_api.contracts import CameraId


class AdmissionCode(StrEnum):
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    CONFLICT = "conflict"
    NOT_APPROVED = "not_approved"
    REJECTED = "rejected"
    ALREADY_USED = "already_used"


class AdmissionError(RuntimeError):
    def __init__(self, code: AdmissionCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ClaimStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUING = "ISSUING"
    EXCHANGED = "EXCHANGED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class PairingGrant:
    grant_id: str
    token_digest: str
    event_id: str
    camera_id: CameraId
    verification_code: str
    expires_at: float
    claimed: bool = False


@dataclass(frozen=True)
class DeviceClaim:
    claim_id: str
    secret_digest: str
    event_id: str
    camera_id: CameraId
    display_name: str
    device_label: str
    verification_code: str
    device_session_id: str
    participant_identity: str
    expires_at: float
    status: ClaimStatus = ClaimStatus.PENDING


@dataclass(frozen=True)
class CameraBinding:
    event_id: str
    camera_id: CameraId
    participant_identity: str
    device_session_id: str
    display_name: str
    current_video_track_sid: str | None = None
    stream_epoch: int = 1


@dataclass(frozen=True)
class CreatedGrant:
    grant: PairingGrant
    pairing_token: str
    expires_in_seconds: int


@dataclass(frozen=True)
class CreatedClaim:
    claim: DeviceClaim
    claim_secret: str
    expires_in_seconds: int


_VERIFICATION_COLOURS = ("BLUE", "GREEN", "ORANGE", "PURPLE", "RED", "YELLOW")


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class AdmissionStore:
    """In-memory, event-scoped pairing authority.

    Raw pairing and claim secrets are returned once and only their SHA-256
    digests remain in memory. The producer credential is never included in a
    publisher link. One camera slot can have only one live grant/claim/binding.
    """

    def __init__(
        self,
        *,
        grant_ttl_seconds: int = 120,
        claim_ttl_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._grant_ttl_seconds = grant_ttl_seconds
        self._claim_ttl_seconds = claim_ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._grants_by_digest: dict[str, PairingGrant] = {}
        self._claims: dict[str, DeviceClaim] = {}
        self._bindings: dict[tuple[str, CameraId], CameraBinding] = {}

    def create_grant(self, event_id: str, camera_id: CameraId) -> CreatedGrant:
        now = self._clock()
        with self._lock:
            self._expire(now)
            slot = (event_id, camera_id)
            if slot in self._bindings or self._slot_is_reserved(event_id, camera_id):
                raise AdmissionError(AdmissionCode.CONFLICT, "Camera slot is already reserved")

            pairing_token = f"cuepair_{secrets.token_urlsafe(32)}"
            grant = PairingGrant(
                grant_id=f"grant_{secrets.token_hex(8)}",
                token_digest=_digest(pairing_token),
                event_id=event_id,
                camera_id=camera_id,
                verification_code=(
                    f"{secrets.choice(_VERIFICATION_COLOURS)}-{secrets.randbelow(900) + 100}"
                ),
                expires_at=now + self._grant_ttl_seconds,
            )
            self._grants_by_digest[grant.token_digest] = grant
            return CreatedGrant(grant, pairing_token, self._grant_ttl_seconds)

    def claim(self, pairing_token: str, display_name: str, device_label: str) -> CreatedClaim:
        now = self._clock()
        token_digest = _digest(pairing_token)
        with self._lock:
            self._expire(now)
            grant = self._grants_by_digest.get(token_digest)
            if grant is None:
                raise AdmissionError(AdmissionCode.NOT_FOUND, "Pairing token is invalid")
            if grant.expires_at <= now:
                raise AdmissionError(AdmissionCode.EXPIRED, "Pairing token has expired")
            if grant.claimed:
                raise AdmissionError(AdmissionCode.ALREADY_USED, "Pairing token was already used")

            claim_secret = f"cueclaim_{secrets.token_urlsafe(32)}"
            device_session_id = secrets.token_hex(12)
            claim = DeviceClaim(
                claim_id=f"claim_{secrets.token_hex(8)}",
                secret_digest=_digest(claim_secret),
                event_id=grant.event_id,
                camera_id=grant.camera_id,
                display_name=display_name.strip(),
                device_label=device_label.strip(),
                verification_code=grant.verification_code,
                device_session_id=device_session_id,
                participant_identity=(
                    f"publisher:{grant.event_id}:{grant.camera_id.value}:{device_session_id}"
                ),
                expires_at=now + self._claim_ttl_seconds,
            )
            self._grants_by_digest[token_digest] = replace(grant, claimed=True)
            self._claims[claim.claim_id] = claim
            return CreatedClaim(claim, claim_secret, self._claim_ttl_seconds)

    def decide(self, event_id: str, claim_id: str, approved: bool) -> DeviceClaim:
        now = self._clock()
        with self._lock:
            claim = self._get_claim(claim_id, now)
            if claim.event_id != event_id:
                raise AdmissionError(AdmissionCode.NOT_FOUND, "Pairing claim was not found")
            if claim.status != ClaimStatus.PENDING:
                raise AdmissionError(AdmissionCode.CONFLICT, "Pairing claim was already decided")
            updated = replace(
                claim, status=ClaimStatus.APPROVED if approved else ClaimStatus.REJECTED
            )
            self._claims[claim_id] = updated
            return updated

    def status(self, claim_id: str, claim_secret: str) -> DeviceClaim:
        now = self._clock()
        with self._lock:
            claim = self._get_claim(claim_id, now)
            self._verify_claim_secret(claim, claim_secret)
            return claim

    def begin_exchange(self, claim_id: str, claim_secret: str) -> DeviceClaim:
        now = self._clock()
        with self._lock:
            claim = self._get_claim(claim_id, now)
            self._verify_claim_secret(claim, claim_secret)
            if claim.status == ClaimStatus.PENDING:
                raise AdmissionError(AdmissionCode.NOT_APPROVED, "Producer approval is pending")
            if claim.status == ClaimStatus.REJECTED:
                raise AdmissionError(AdmissionCode.REJECTED, "Producer rejected this device")
            if claim.status in (ClaimStatus.ISSUING, ClaimStatus.EXCHANGED):
                raise AdmissionError(AdmissionCode.ALREADY_USED, "Claim was already exchanged")
            issuing = replace(claim, status=ClaimStatus.ISSUING)
            self._claims[claim_id] = issuing
            return issuing

    def abort_exchange(self, claim_id: str) -> None:
        with self._lock:
            claim = self._claims.get(claim_id)
            if claim and claim.status == ClaimStatus.ISSUING:
                self._claims[claim_id] = replace(claim, status=ClaimStatus.APPROVED)

    def complete_exchange(self, claim_id: str) -> CameraBinding:
        with self._lock:
            claim = self._claims.get(claim_id)
            if claim is None or claim.status != ClaimStatus.ISSUING:
                raise AdmissionError(AdmissionCode.CONFLICT, "Claim is not being exchanged")
            slot = (claim.event_id, claim.camera_id)
            if slot in self._bindings:
                raise AdmissionError(AdmissionCode.CONFLICT, "Camera slot is already occupied")
            binding = CameraBinding(
                event_id=claim.event_id,
                camera_id=claim.camera_id,
                participant_identity=claim.participant_identity,
                device_session_id=claim.device_session_id,
                display_name=claim.display_name,
            )
            self._bindings[slot] = binding
            self._claims[claim_id] = replace(claim, status=ClaimStatus.EXCHANGED)
            return binding

    def list_bindings(self, event_id: str) -> list[CameraBinding]:
        with self._lock:
            return [
                binding
                for (bound_event, _), binding in self._bindings.items()
                if bound_event == event_id
            ]

    def list_claims(self, event_id: str) -> list[DeviceClaim]:
        now = self._clock()
        with self._lock:
            self._expire(now)
            return sorted(
                (claim for claim in self._claims.values() if claim.event_id == event_id),
                key=lambda claim: claim.claim_id,
            )

    def remaining_seconds(self, expires_at: float) -> int:
        return max(0, int(expires_at - self._clock()))

    def record_video_track(
        self,
        event_id: str,
        camera_id: CameraId,
        participant_identity: str,
        track_sid: str,
    ) -> CameraBinding:
        """Attach a new track while keeping the camera ID stable.

        A changed SID is a republish and advances the epoch. A caller cannot
        claim a slot merely by naming its camera ID; identity must match.
        """

        with self._lock:
            slot = (event_id, camera_id)
            binding = self._bindings.get(slot)
            if binding is None or not secrets.compare_digest(
                binding.participant_identity, participant_identity
            ):
                raise AdmissionError(AdmissionCode.NOT_FOUND, "Active binding was not found")
            if binding.current_video_track_sid == track_sid:
                return binding
            next_epoch = binding.stream_epoch
            if binding.current_video_track_sid is not None:
                next_epoch += 1
            updated = replace(
                binding,
                current_video_track_sid=track_sid,
                stream_epoch=next_epoch,
            )
            self._bindings[slot] = updated
            return updated

    def _get_claim(self, claim_id: str, now: float) -> DeviceClaim:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise AdmissionError(AdmissionCode.NOT_FOUND, "Pairing claim was not found")
        if claim.expires_at <= now and claim.status not in (
            ClaimStatus.EXCHANGED,
            ClaimStatus.REJECTED,
        ):
            expired = replace(claim, status=ClaimStatus.EXPIRED)
            self._claims[claim_id] = expired
            raise AdmissionError(AdmissionCode.EXPIRED, "Pairing claim has expired")
        return claim

    @staticmethod
    def _verify_claim_secret(claim: DeviceClaim, claim_secret: str) -> None:
        if not secrets.compare_digest(claim.secret_digest, _digest(claim_secret)):
            raise AdmissionError(AdmissionCode.NOT_FOUND, "Pairing claim was not found")

    def _slot_is_reserved(self, event_id: str, camera_id: CameraId) -> bool:
        if any(
            grant.event_id == event_id and grant.camera_id == camera_id and not grant.claimed
            for grant in self._grants_by_digest.values()
        ):
            return True
        return any(
            claim.event_id == event_id
            and claim.camera_id == camera_id
            and claim.status not in (ClaimStatus.REJECTED, ClaimStatus.EXPIRED)
            for claim in self._claims.values()
        )

    def _expire(self, now: float) -> None:
        self._grants_by_digest = {
            digest: grant
            for digest, grant in self._grants_by_digest.items()
            if grant.claimed or grant.expires_at > now
        }
        for claim_id, claim in list(self._claims.items()):
            if claim.expires_at <= now and claim.status in (
                ClaimStatus.PENDING,
                ClaimStatus.APPROVED,
            ):
                self._claims[claim_id] = replace(claim, status=ClaimStatus.EXPIRED)
