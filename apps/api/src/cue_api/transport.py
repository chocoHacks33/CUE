from __future__ import annotations

from dataclasses import dataclass

from cue_api.admission import AdmissionStore, CameraBinding
from cue_api.contracts import CameraId, TransportOutcome
from cue_api.guests.observations import ObservationStore


@dataclass(frozen=True)
class TransportMutation:
    binding: CameraBinding
    outcome: TransportOutcome
    epoch_advanced: bool
    observation_dropped: bool


class TransportCoordinator:
    """Join trusted LiveKit track events to bindings and identity invalidation.

    D's receiver will call this adapter from real track subscribed/unsubscribed
    events. It contains no LiveKit or browser imports, so A can verify reconnect
    ordering before the Stage 2 compositor is merged.
    """

    def __init__(self, admissions: AdmissionStore, observations: ObservationStore) -> None:
        self._admissions = admissions
        self._observations = observations

    def attach_video(
        self,
        *,
        event_id: str,
        camera_id: CameraId,
        participant_identity: str,
        track_sid: str,
    ) -> TransportMutation:
        before = self._admissions.get_binding(event_id, camera_id)
        updated = self._admissions.record_video_track(
            event_id,
            camera_id,
            participant_identity,
            track_sid,
        )
        epoch_advanced = updated.stream_epoch > before.stream_epoch
        changed = updated.current_video_track_sid != before.current_video_track_sid
        dropped = False
        if epoch_advanced:
            dropped = self._observations.invalidate(
                event_id=event_id,
                camera_id=camera_id,
                current_stream_epoch=updated.stream_epoch,
                reason="video track republished",
            )
        return TransportMutation(
            binding=updated,
            outcome=(
                TransportOutcome.REPUBLISHED
                if epoch_advanced
                else TransportOutcome.ATTACHED
            ),
            epoch_advanced=epoch_advanced,
            observation_dropped=dropped if changed else False,
        )

    def detach_video(
        self,
        *,
        event_id: str,
        camera_id: CameraId,
        participant_identity: str,
        track_sid: str,
    ) -> TransportMutation:
        updated, detached = self._admissions.release_video_track(
            event_id,
            camera_id,
            participant_identity,
            track_sid,
        )
        dropped = False
        if detached:
            dropped = self._observations.invalidate(
                event_id=event_id,
                camera_id=camera_id,
                current_stream_epoch=updated.stream_epoch,
                reason="video track detached",
            )
        return TransportMutation(
            binding=updated,
            outcome=(
                TransportOutcome.DETACHED
                if detached
                else TransportOutcome.STALE_DETACH_IGNORED
            ),
            epoch_advanced=False,
            observation_dropped=dropped,
        )
