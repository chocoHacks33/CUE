"""Identity confirmation and expiry.

One good frame is not an identity. The ledger requires repeated consistent
observations on the same track before it will say CONFIRMED, and every identity
it holds has an expiry, an epoch and a track it dies with.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cue_api.guests.face_matching import MatchThresholds
from cue_api.guests.types import ObservationStatus

#: PRD starting value. Measure and tune; this is not a proven outcome.
DEFAULT_IDENTITY_TTL_MS = 1500


@dataclass
class _TrackIdentity:
    guest_id: str
    consecutive_confirmations: int
    first_seen_ms: int
    last_seen_ms: int


@dataclass
class IdentityAssertion:
    status: ObservationStatus
    guest_id: str | None
    consecutive_confirmations: int
    expires_at_ms: int


@dataclass
class IdentityLedger:
    thresholds: MatchThresholds = field(default_factory=MatchThresholds)
    identity_ttl_ms: int = DEFAULT_IDENTITY_TTL_MS
    _identities: dict[str, _TrackIdentity] = field(default_factory=dict, repr=False)

    def observe_candidate(
        self,
        track_key: str,
        guest_id: str,
        now_ms: int,
    ) -> IdentityAssertion:
        """Record one candidate match and say whether it is confirmed yet."""
        existing = self._identities.get(track_key)
        gap_too_long = (
            existing is not None
            and now_ms - existing.last_seen_ms > self.thresholds.confirmation_window_ms
        )

        if existing is None or existing.guest_id != guest_id or gap_too_long:
            # A different candidate on the same track restarts the count: a
            # flicker between two guests must not accumulate towards either.
            existing = _TrackIdentity(
                guest_id=guest_id,
                consecutive_confirmations=1,
                first_seen_ms=now_ms,
                last_seen_ms=now_ms,
            )
        else:
            existing.consecutive_confirmations += 1
            existing.last_seen_ms = now_ms

        self._identities[track_key] = existing
        confirmed = existing.consecutive_confirmations >= self.thresholds.confirmations_required
        return IdentityAssertion(
            status=ObservationStatus.CONFIRMED if confirmed else ObservationStatus.PROVISIONAL,
            guest_id=guest_id,
            consecutive_confirmations=existing.consecutive_confirmations,
            expires_at_ms=now_ms + self.identity_ttl_ms,
        )

    def observe_non_identity(self, track_key: str) -> None:
        """An unknown, ambiguous or low-quality frame drops the track's identity.

        Evidence has to be current. Keeping yesterday's confirmation alive
        through a frame we could not read is exactly how a wrong-person cut
        happens.
        """
        self._identities.pop(track_key, None)

    def forget_track(self, track_key: str) -> None:
        self._identities.pop(track_key, None)

    def forget_camera(self, camera_id: str) -> int:
        """Drop every identity on a camera: re-publish, reframe or lost track."""
        doomed = [key for key in self._identities if key.startswith(f"{camera_id}:")]
        for key in doomed:
            del self._identities[key]
        return len(doomed)

    def forget_guest(self, guest_id: str) -> int:
        """Consent withdrawal removes the guest from live evidence at once."""
        doomed = [
            key for key, identity in self._identities.items() if identity.guest_id == guest_id
        ]
        for key in doomed:
            del self._identities[key]
        return len(doomed)

    def prune(self, now_ms: int) -> int:
        """Remove identities whose last supporting observation has expired."""
        doomed = [
            key
            for key, identity in self._identities.items()
            if now_ms - identity.last_seen_ms > self.identity_ttl_ms
        ]
        for key in doomed:
            del self._identities[key]
        return len(doomed)

    def current(self, track_key: str, now_ms: int) -> IdentityAssertion | None:
        identity = self._identities.get(track_key)
        if identity is None:
            return None
        expires_at_ms = identity.last_seen_ms + self.identity_ttl_ms
        if now_ms > expires_at_ms:
            del self._identities[track_key]
            return None
        confirmed = identity.consecutive_confirmations >= self.thresholds.confirmations_required
        return IdentityAssertion(
            status=ObservationStatus.CONFIRMED if confirmed else ObservationStatus.PROVISIONAL,
            guest_id=identity.guest_id,
            consecutive_confirmations=identity.consecutive_confirmations,
            expires_at_ms=expires_at_ms,
        )

    def __len__(self) -> int:
        return len(self._identities)
