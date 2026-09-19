import {
  CAMERA_IDS,
  type CameraId,
  READINESS_CONTRACT_VERSION,
  type ReceiverReadiness,
  type SlotReadiness,
} from "@cue/contracts";

import { frameAgeMs, MASTER_AUDIO_CAMERA, type Slots } from "./slotState";

export interface ReadinessContext {
  eventId: string;
  rendererId: string;
  rendererGeneration: number;
  receiverIdentity: string | null;
  connected: boolean;
  audioPlaybackAllowed: boolean;
  audioAttached: boolean;
  /** Null until the Stage 2 compositor draws a source. */
  currentSource: CameraId | null;
}

/**
 * Pure: turn the receiver's slot state into the readiness payload the backend
 * consumes. `previous` lets the snapshot say whether frames are still
 * progressing, which is the PRD's "decoded-frame progression" health signal.
 */
export function buildReadiness(
  slots: Slots,
  now: number,
  context: ReadinessContext,
  previous: ReceiverReadiness | null,
): ReceiverReadiness {
  const previousCounts = new Map<CameraId, number>(
    previous?.slots.map((slot) => [slot.cameraId, slot.frameCount]) ?? [],
  );

  const slotReadiness: SlotReadiness[] = CAMERA_IDS.map((cameraId) => {
    const slot = slots[cameraId];
    const decoded = slot.videoTrackSid !== null && slot.frameCount > 0;
    const before = previousCounts.get(cameraId);
    return {
      cameraId,
      publisherIdentity: slot.publisherIdentity,
      streamEpoch: slot.streamEpoch,
      videoTrackSid: slot.videoTrackSid,
      audioTrackSid: slot.audioTrackSid,
      decoded,
      renderable: decoded && slot.videoState === "video-ready",
      lastFrameAgeMs: frameAgeMs(slot, now),
      framesProgressing: before !== undefined && slot.frameCount > before,
      frameCount: slot.frameCount,
      width: slot.width,
      height: slot.height,
      state: slot.videoState,
    };
  });

  const host = slots[MASTER_AUDIO_CAMERA];
  return {
    contractVersion: READINESS_CONTRACT_VERSION,
    eventId: context.eventId,
    rendererId: context.rendererId,
    rendererGeneration: context.rendererGeneration,
    receiverIdentity: context.receiverIdentity,
    connected: context.connected,
    clockDomain: "renderer-monotonic",
    reportedAtMs: now,
    currentSource: context.currentSource,
    masterAudio: {
      cameraId: MASTER_AUDIO_CAMERA,
      trackSid: host.audioTrackSid,
      attached: context.audioAttached,
      playbackAllowed: context.audioPlaybackAllowed,
    },
    slots: slotReadiness,
  };
}
