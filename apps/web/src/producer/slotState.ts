import {
  CAMERA_IDS,
  type CameraBinding,
  type CameraId,
  type PublisherMetadata,
} from "@cue/contracts";

/**
 * Pure state for the three receiver slots. No LiveKit or DOM imports so it can
 * be unit-tested in Node. Slots are keyed by the server-issued camera ID; a
 * participant lands in a slot only because its server-set metadata says so.
 */

export type VideoState =
  | "waiting"
  | "publisher-connected"
  | "subscribing"
  | "video-ready"
  | "stalled";

export type AudioState = "not-applicable" | "waiting" | "audio-ready" | "playback-blocked";

export interface SlotState {
  cameraId: CameraId;
  publisherIdentity: string | null;
  publisherName: string | null;
  streamEpoch: number | null;
  bindingRevision: number | null;
  videoTrackSid: string | null;
  audioTrackSid: string | null;
  /** Track SIDs seen earlier for this camera ID, newest last. Proves a republish changed the SID, not the camera. */
  previousVideoTrackSids: string[];
  videoState: VideoState;
  audioState: AudioState;
  lastFrameAt: number | null;
  frameCount: number;
  width: number;
  height: number;
  /** Other participants whose metadata also claimed this camera ID. They are never attached. */
  conflictIdentities: string[];
}

export type Slots = Readonly<Record<CameraId, SlotState>>;

/** PRD section 10: one second without a new decoded frame counts as a stall. */
export const STALL_THRESHOLD_MS = 1000;
export const MASTER_AUDIO_CAMERA: CameraId = "CAM-HOST";
const MAX_REMEMBERED_SIDS = 5;

export function emptySlot(cameraId: CameraId): SlotState {
  return {
    cameraId,
    publisherIdentity: null,
    publisherName: null,
    streamEpoch: null,
    bindingRevision: null,
    videoTrackSid: null,
    audioTrackSid: null,
    previousVideoTrackSids: [],
    videoState: "waiting",
    audioState: cameraId === MASTER_AUDIO_CAMERA ? "waiting" : "not-applicable",
    lastFrameAt: null,
    frameCount: 0,
    width: 0,
    height: 0,
    conflictIdentities: [],
  };
}

export function emptySlots(): Slots {
  const slots = {} as Record<CameraId, SlotState>;
  for (const cameraId of CAMERA_IDS) slots[cameraId] = emptySlot(cameraId);
  return slots;
}

export type ClaimResult =
  | { kind: "assigned"; cameraId: CameraId }
  | { kind: "already-assigned"; cameraId: CameraId }
  | { kind: "conflict"; cameraId: CameraId; holder: string }
  | { kind: "unassigned"; reason: string };

export type BindingReconcileResult =
  | { kind: "applied"; cameraId: CameraId; epochAdvanced: boolean }
  | { kind: "unchanged"; cameraId: CameraId }
  | { kind: "stale"; cameraId: CameraId }
  | { kind: "conflict"; cameraId: CameraId; holder: string };

export interface BindingSnapshotResult {
  slots: Slots;
  removedCameraIds: CameraId[];
  results: BindingReconcileResult[];
}

/** Apply A's authoritative transport response after a real track event. */
export function applyAuthoritativeBinding(
  slots: Slots,
  binding: CameraBinding,
  eventId: string,
): { slots: Slots; result: BindingReconcileResult } {
  const cameraId = binding.cameraId;
  const slot = slots[cameraId];
  if (
    binding.eventId !== eventId ||
    (slot.bindingRevision ?? -1) > binding.bindingRevision ||
    (slot.streamEpoch ?? 0) > binding.streamEpoch
  ) {
    return { slots, result: { kind: "stale", cameraId } };
  }
  const sameRevision = slot.bindingRevision === binding.bindingRevision;
  if (
    slot.publisherIdentity !== null &&
    slot.publisherIdentity !== binding.participantIdentity
  ) {
    return {
      slots,
      result: { kind: "conflict", cameraId, holder: slot.publisherIdentity },
    };
  }
  if (
    sameRevision &&
    slot.publisherIdentity === binding.participantIdentity &&
    slot.videoTrackSid === binding.currentVideoTrackSid
  ) {
    return { slots, result: { kind: "unchanged", cameraId } };
  }
  if (sameRevision && slot.publisherIdentity === binding.participantIdentity) {
    return { slots, result: { kind: "stale", cameraId } };
  }

  const epochAdvanced = slot.streamEpoch !== null && binding.streamEpoch > slot.streamEpoch;
  const previousVideoTrackSids = remember(slot.previousVideoTrackSids, slot.videoTrackSid);
  const next: SlotState = {
    ...emptySlot(cameraId),
    publisherIdentity: binding.participantIdentity,
    publisherName: binding.displayName,
    streamEpoch: binding.streamEpoch,
    bindingRevision: binding.bindingRevision,
    videoTrackSid: binding.currentVideoTrackSid,
    previousVideoTrackSids,
    videoState: binding.currentVideoTrackSid ? "subscribing" : "publisher-connected",
    conflictIdentities: [
      ...slot.conflictIdentities,
      ...(slot.publisherIdentity && slot.publisherIdentity !== binding.participantIdentity
        ? [slot.publisherIdentity]
        : []),
    ].filter(
      (identity, index, all) =>
        identity !== binding.participantIdentity && all.indexOf(identity) === index,
    ),
  };
  return {
    slots: { ...slots, [cameraId]: next },
    result: { kind: "applied", cameraId, epochAdvanced },
  };
}

/** Replace local ownership with one complete authoritative binding snapshot. */
export function reconcileAuthoritativeBindings(
  slots: Slots,
  bindings: readonly CameraBinding[],
  eventId: string,
): BindingSnapshotResult {
  let next = slots;
  const results: BindingReconcileResult[] = [];
  const present = new Set<CameraId>();

  for (const binding of bindings) {
    if (binding.eventId !== eventId || present.has(binding.cameraId)) continue;
    present.add(binding.cameraId);
    const applied = applyAuthoritativeBinding(next, binding, eventId);
    next = applied.slots;
    results.push(applied.result);
  }

  const removedCameraIds: CameraId[] = [];
  for (const cameraId of CAMERA_IDS) {
    if (present.has(cameraId)) continue;
    const slot = next[cameraId];
    if (slot.publisherIdentity !== null || slot.videoTrackSid !== null) {
      removedCameraIds.push(cameraId);
    }
    next = {
      ...next,
      [cameraId]: {
        ...emptySlot(cameraId),
        previousVideoTrackSids: remember(slot.previousVideoTrackSids, slot.videoTrackSid),
      },
    };
  }
  return { slots: next, removedCameraIds, results };
}

/**
 * Bind a participant to the slot named by its server metadata. The first
 * participant to claim a camera ID keeps it; later claimants are recorded as
 * conflicts and never attached. Tile order and display name play no part.
 */
export function claimSlot(
  slots: Slots,
  identity: string,
  name: string | null,
  metadata: PublisherMetadata | null,
  eventId: string,
): { slots: Slots; result: ClaimResult } {
  if (!metadata) {
    return { slots, result: { kind: "unassigned", reason: "missing or invalid server metadata" } };
  }
  if (metadata.eventId !== eventId) {
    return {
      slots,
      result: {
        kind: "unassigned",
        reason: `metadata event "${metadata.eventId}" does not match "${eventId}"`,
      },
    };
  }

  const { cameraId } = metadata;
  const slot = slots[cameraId];

  if (slot.publisherIdentity === identity) {
    return {
      slots: {
        ...slots,
        [cameraId]: {
          ...slot,
          publisherName: name,
          streamEpoch: Math.max(slot.streamEpoch ?? metadata.streamEpoch, metadata.streamEpoch),
        },
      },
      result: { kind: "already-assigned", cameraId },
    };
  }

  if (slot.publisherIdentity !== null) {
    const conflictIdentities = slot.conflictIdentities.includes(identity)
      ? slot.conflictIdentities
      : [...slot.conflictIdentities, identity];
    return {
      slots: { ...slots, [cameraId]: { ...slot, conflictIdentities } },
      result: { kind: "conflict", cameraId, holder: slot.publisherIdentity },
    };
  }

  return {
    slots: {
      ...slots,
      [cameraId]: {
        ...slot,
        publisherIdentity: identity,
        publisherName: name,
        streamEpoch: metadata.streamEpoch,
        videoState: "publisher-connected",
        audioState: cameraId === MASTER_AUDIO_CAMERA ? "waiting" : "not-applicable",
        conflictIdentities: slot.conflictIdentities.filter((other) => other !== identity),
      },
    },
    result: { kind: "assigned", cameraId },
  };
}

/** A participant left. Its slot returns to waiting but keeps the camera ID and remembers old SIDs. */
export function releaseParticipant(slots: Slots, identity: string): Slots {
  const next = { ...slots } as Record<CameraId, SlotState>;
  for (const cameraId of CAMERA_IDS) {
    const slot = slots[cameraId];
    if (slot.publisherIdentity === identity) {
      next[cameraId] = {
        ...emptySlot(cameraId),
        previousVideoTrackSids: remember(slot.previousVideoTrackSids, slot.videoTrackSid),
        conflictIdentities: slot.conflictIdentities.filter((other) => other !== identity),
      };
    } else if (slot.conflictIdentities.includes(identity)) {
      next[cameraId] = {
        ...slot,
        conflictIdentities: slot.conflictIdentities.filter((other) => other !== identity),
      };
    }
  }
  return next;
}

function remember(previous: string[], sid: string | null): string[] {
  if (!sid) return previous;
  return [...previous, sid].slice(-MAX_REMEMBERED_SIDS);
}

export function setVideoTrack(slots: Slots, cameraId: CameraId, trackSid: string): Slots {
  const slot = slots[cameraId];
  if (slot.videoTrackSid === trackSid) return slots;
  return {
    ...slots,
    [cameraId]: {
      ...slot,
      videoTrackSid: trackSid,
      previousVideoTrackSids: remember(slot.previousVideoTrackSids, slot.videoTrackSid),
      videoState: "subscribing",
      lastFrameAt: null,
      frameCount: 0,
      width: 0,
      height: 0,
    },
  };
}

export function clearVideoTrack(slots: Slots, cameraId: CameraId): Slots {
  const slot = slots[cameraId];
  if (slot.videoTrackSid === null) return slots;
  return {
    ...slots,
    [cameraId]: {
      ...slot,
      videoTrackSid: null,
      previousVideoTrackSids: remember(slot.previousVideoTrackSids, slot.videoTrackSid),
      videoState: slot.publisherIdentity ? "publisher-connected" : "waiting",
      lastFrameAt: null,
      frameCount: 0,
      width: 0,
      height: 0,
    },
  };
}

export function setAudioTrack(
  slots: Slots,
  cameraId: CameraId,
  trackSid: string,
  playbackAllowed: boolean,
): Slots {
  const slot = slots[cameraId];
  return {
    ...slots,
    [cameraId]: {
      ...slot,
      audioTrackSid: trackSid,
      audioState: playbackAllowed ? "audio-ready" : "playback-blocked",
    },
  };
}

export function clearAudioTrack(slots: Slots, cameraId: CameraId): Slots {
  const slot = slots[cameraId];
  if (slot.audioTrackSid === null) return slots;
  return {
    ...slots,
    [cameraId]: {
      ...slot,
      audioTrackSid: null,
      audioState: cameraId === MASTER_AUDIO_CAMERA ? "waiting" : "not-applicable",
    },
  };
}

/** Browser autoplay policy changed. Only slots with an attached audio track are affected. */
export function setAudioPlayback(slots: Slots, playing: boolean): Slots {
  let changed = false;
  const next = { ...slots } as Record<CameraId, SlotState>;
  for (const cameraId of CAMERA_IDS) {
    const slot = slots[cameraId];
    if (slot.audioTrackSid === null) continue;
    const audioState: AudioState = playing ? "audio-ready" : "playback-blocked";
    if (slot.audioState !== audioState) {
      next[cameraId] = { ...slot, audioState };
      changed = true;
    }
  }
  return changed ? next : slots;
}

/** A decoded frame arrived for this camera's currently attached track. */
export function markFrame(
  slots: Slots,
  cameraId: CameraId,
  now: number,
  width: number,
  height: number,
): Slots {
  const slot = slots[cameraId];
  if (slot.videoTrackSid === null) return slots;
  return {
    ...slots,
    [cameraId]: {
      ...slot,
      lastFrameAt: now,
      frameCount: slot.frameCount + 1,
      width,
      height,
      videoState: "video-ready",
    },
  };
}

/** Mark slots stalled when frames stop arriving. A later frame returns them to video-ready. */
export function applyStallCheck(slots: Slots, now: number, thresholdMs = STALL_THRESHOLD_MS): Slots {
  let changed = false;
  const next = { ...slots } as Record<CameraId, SlotState>;
  for (const cameraId of CAMERA_IDS) {
    const slot = slots[cameraId];
    if (
      slot.videoState === "video-ready" &&
      slot.lastFrameAt !== null &&
      now - slot.lastFrameAt > thresholdMs
    ) {
      next[cameraId] = { ...slot, videoState: "stalled" };
      changed = true;
    }
  }
  return changed ? next : slots;
}

export function frameAgeMs(slot: SlotState, now: number): number | null {
  return slot.lastFrameAt === null ? null : Math.max(0, now - slot.lastFrameAt);
}

/**
 * Decide whether the receiver should subscribe to a publication. Camera video
 * from any bound publisher: yes. Microphone: only CAM-HOST's master track.
 * Anything else, including a second audio track from any source: no.
 */
export function shouldSubscribe(
  metadata: PublisherMetadata | null,
  source: string,
  eventId: string,
): boolean {
  if (!metadata || metadata.eventId !== eventId) return false;
  if (source === "camera") return true;
  if (source === "microphone") {
    return metadata.cameraId === MASTER_AUDIO_CAMERA && metadata.audioPolicy === "MASTER";
  }
  return false;
}
