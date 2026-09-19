import { CAMERA_IDS, type CameraId, isCameraId } from "./index";
import type { ProgramSource } from "./switching";

/**
 * Receiver readiness: what the active Mac compositor tells the backend about
 * what it can actually render right now (v3 plan section 5, "Readiness" row).
 * Produced by D, consumed by A's backend and C's policy. Every timestamp is in
 * the renderer's own monotonic clock; the backend must not compare it with its
 * own clock without an explicit mapping.
 */

export const READINESS_CONTRACT_VERSION = "0.1.0" as const;

export type SlotReadinessState =
  | "waiting"
  | "publisher-connected"
  | "subscribing"
  | "video-ready"
  | "stalled";

export interface SlotReadiness {
  cameraId: CameraId;
  publisherIdentity: string | null;
  streamEpoch: number | null;
  videoTrackSid: string | null;
  audioTrackSid: string | null;
  /** At least one decoded frame has arrived for the current video track. */
  decoded: boolean;
  /** Decoded and not stalled: the compositor could draw this source now. */
  renderable: boolean;
  lastFrameAgeMs: number | null;
  /** Frame count advanced since the previous snapshot. False on the first snapshot. */
  framesProgressing: boolean;
  frameCount: number;
  width: number;
  height: number;
  state: SlotReadinessState;
}

export interface MasterAudioReadiness {
  cameraId: CameraId;
  trackSid: string | null;
  attached: boolean;
  playbackAllowed: boolean;
}

export interface ReceiverReadiness {
  contractVersion: typeof READINESS_CONTRACT_VERSION;
  eventId: string;
  /** Stable for the life of the browser tab. A second tab is a different renderer. */
  rendererId: string;
  /** Increments every time this renderer (re)connects. Old ACKs carry an old generation. */
  rendererGeneration: number;
  receiverIdentity: string | null;
  connected: boolean;
  clockDomain: "renderer-monotonic";
  reportedAtMs: number;
  /** The source currently drawn to the programme canvas: a camera, the slate, or null before the compositor starts. */
  currentSource: ProgramSource | null;
  masterAudio: MasterAudioReadiness;
  /** Always exactly the three camera IDs, in CAMERA_IDS order. */
  slots: SlotReadiness[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Structural check for a readiness payload received over the wire. */
export function isReceiverReadiness(value: unknown): value is ReceiverReadiness {
  if (!isRecord(value)) return false;
  if (value.contractVersion !== READINESS_CONTRACT_VERSION) return false;
  if (typeof value.eventId !== "string" || typeof value.rendererId !== "string") return false;
  if (typeof value.rendererGeneration !== "number" || typeof value.reportedAtMs !== "number") {
    return false;
  }
  if (value.clockDomain !== "renderer-monotonic" || typeof value.connected !== "boolean") {
    return false;
  }
  if (
    value.currentSource !== null &&
    value.currentSource !== "SLATE" &&
    !(typeof value.currentSource === "string" && isCameraId(value.currentSource))
  ) {
    return false;
  }
  if (!isRecord(value.masterAudio) || typeof value.masterAudio.attached !== "boolean") return false;
  if (!Array.isArray(value.slots) || value.slots.length !== CAMERA_IDS.length) return false;
  return value.slots.every(
    (slot, index) =>
      isRecord(slot) &&
      slot.cameraId === CAMERA_IDS[index] &&
      typeof slot.decoded === "boolean" &&
      typeof slot.renderable === "boolean" &&
      typeof slot.frameCount === "number",
  );
}
