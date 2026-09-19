export const CONTRACT_VERSION = "0.1.0" as const;

export const CAMERA_IDS = ["CAM-HOST", "CAM-GUEST", "CAM-WIDE"] as const;
export type CameraId = (typeof CAMERA_IDS)[number];

export const CAMERA_ROLES = ["HOST", "GUEST", "WIDE"] as const;
export type CameraRole = (typeof CAMERA_ROLES)[number];

export type AudioPolicy = "MASTER" | "DISABLED";

export interface CameraContract {
  cameraId: CameraId;
  role: CameraRole;
  audioPolicy: AudioPolicy;
  owner: "A" | "B" | "C";
}

export const CAMERA_CONTRACTS: Readonly<Record<CameraId, CameraContract>> = {
  "CAM-HOST": {
    cameraId: "CAM-HOST",
    role: "HOST",
    audioPolicy: "MASTER",
    owner: "A",
  },
  "CAM-GUEST": {
    cameraId: "CAM-GUEST",
    role: "GUEST",
    audioPolicy: "DISABLED",
    owner: "B",
  },
  "CAM-WIDE": {
    cameraId: "CAM-WIDE",
    role: "WIDE",
    audioPolicy: "DISABLED",
    owner: "C",
  },
};

export interface PublisherTokenRequest {
  eventId: string;
  cameraId: CameraId;
  displayName: string;
}

export interface PublisherTokenResponse {
  contractVersion: typeof CONTRACT_VERSION;
  serverUrl: string;
  participantToken: string;
  participantIdentity: string;
  roomName: string;
  camera: CameraContract;
  expiresInSeconds: number;
}

export function isCameraId(value: string): value is CameraId {
  return CAMERA_IDS.includes(value as CameraId);
}

export function mayPublishMicrophone(cameraId: CameraId): boolean {
  return CAMERA_CONTRACTS[cameraId].audioPolicy === "MASTER";
}

// ---------------------------------------------------------------------------
// Receiver (D's Mac) contracts. Receivers subscribe only; they never publish.
// ---------------------------------------------------------------------------

export const RECEIVER_ROLES = ["DIRECTOR", "OBSERVER"] as const;
export type ReceiverRole = (typeof RECEIVER_ROLES)[number];

export interface ReceiverTokenRequest {
  eventId: string;
  displayName: string;
  receiverRole: ReceiverRole;
}

export interface ReceiverTokenResponse {
  contractVersion: typeof CONTRACT_VERSION;
  serverUrl: string;
  participantToken: string;
  participantIdentity: string;
  roomName: string;
  receiverRole: ReceiverRole;
  expiresInSeconds: number;
}

/**
 * Metadata the API embeds in every publisher token. LiveKit exposes it as
 * `participant.metadata`; publishers cannot edit it (canUpdateOwnMetadata is
 * false). Receivers use it, never tile order or display name, to decide which
 * camera slot a participant belongs to.
 */
export interface PublisherMetadata {
  contractVersion: string;
  eventId: string;
  cameraId: CameraId;
  role: CameraRole;
  audioPolicy: AudioPolicy;
  streamEpoch: number;
}

/**
 * Parse and validate publisher metadata. Returns null for anything that is
 * missing, malformed, names an unknown camera, or contradicts the server-owned
 * camera contract. A null result means "do not attach this participant".
 */
export function parsePublisherMetadata(raw: string | null | undefined): PublisherMetadata | null {
  if (!raw) return null;

  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;

  const candidate = value as Record<string, unknown>;
  const { cameraId, eventId, contractVersion, streamEpoch, role, audioPolicy } = candidate;

  if (typeof cameraId !== "string" || !isCameraId(cameraId)) return null;
  if (typeof eventId !== "string" || eventId.length === 0) return null;
  if (typeof contractVersion !== "string" || contractVersion.length === 0) return null;
  if (typeof streamEpoch !== "number" || !Number.isInteger(streamEpoch) || streamEpoch < 1) {
    return null;
  }

  const contract = CAMERA_CONTRACTS[cameraId];
  if (role !== contract.role || audioPolicy !== contract.audioPolicy) return null;

  return {
    contractVersion,
    eventId,
    cameraId,
    role: contract.role,
    audioPolicy: contract.audioPolicy,
    streamEpoch,
  };
}
