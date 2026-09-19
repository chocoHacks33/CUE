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

export interface PairingGrantRequest {
  cameraId: CameraId;
}

export interface PairingGrantResponse {
  contractVersion: typeof CONTRACT_VERSION;
  grantId: string;
  pairingToken: string;
  verificationCode: string;
  camera: CameraContract;
  expiresInSeconds: number;
}

export interface PairingClaimRequest {
  pairingToken: string;
  displayName: string;
  deviceLabel: string;
}

export type PairingClaimStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "ISSUING"
  | "EXCHANGED"
  | "EXPIRED";

export interface PairingClaimResponse {
  contractVersion: typeof CONTRACT_VERSION;
  claimId: string;
  claimSecret: string;
  verificationCode: string;
  camera: CameraContract;
  status: PairingClaimStatus;
  expiresInSeconds: number;
}

export interface PairingStatusRequest {
  claimId: string;
  claimSecret: string;
}

export interface PairingStatusResponse {
  contractVersion: typeof CONTRACT_VERSION;
  claimId: string;
  verificationCode: string;
  camera: CameraContract;
  status: PairingClaimStatus;
  expiresInSeconds: number;
}

export interface ProducerPairingClaimResponse extends PairingStatusResponse {
  displayName: string;
  deviceLabel: string;
}

export interface PairingDecisionRequest {
  approved: boolean;
}

export interface PairingExchangeResponse extends PublisherTokenResponse {
  deviceSessionId: string;
  streamEpoch: number;
}

export interface CameraBinding {
  contractVersion: typeof CONTRACT_VERSION;
  eventId: string;
  cameraId: CameraId;
  participantIdentity: string;
  deviceSessionId: string;
  displayName: string;
  currentVideoTrackSid: string | null;
  streamEpoch: number;
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
  deviceSessionId?: string;
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
  const { cameraId, eventId, contractVersion, streamEpoch, role, audioPolicy, deviceSessionId } =
    candidate;

  if (typeof cameraId !== "string" || !isCameraId(cameraId)) return null;
  if (typeof eventId !== "string" || eventId.length === 0) return null;
  if (typeof contractVersion !== "string" || contractVersion.length === 0) return null;
  if (typeof streamEpoch !== "number" || !Number.isInteger(streamEpoch) || streamEpoch < 1) {
    return null;
  }
  if (
    deviceSessionId !== undefined &&
    (typeof deviceSessionId !== "string" || deviceSessionId.length === 0)
  ) {
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
    ...(deviceSessionId ? { deviceSessionId } : {}),
  };
}

export type PixelFormat = "RGB24" | "BGR24" | "RGBA32";
export type SampleFormat = "S16LE" | "F32LE";

export interface DecodedFrameDescriptor {
  eventId: string;
  cameraId: CameraId;
  streamEpoch: number;
  trackSid: string;
  sequence: number;
  width: number;
  height: number;
  strideBytes: number;
  pixelFormat: PixelFormat;
  orientationDegrees: 0 | 90 | 180 | 270;
  mirrored: boolean;
  receivedAtMonotonicS: number;
  captureTimeS: number | null;
}

export interface DecodedAudioDescriptor {
  eventId: string;
  cameraId: "CAM-HOST";
  masterTrackSid: string;
  audioEpoch: number;
  sequence: number;
  sampleRateHz: number;
  channels: 1 | 2;
  sampleFormat: SampleFormat;
  sampleOffset: number;
  sampleFrameCount: number;
  receivedAtMonotonicS: number;
}

export function isDecodedFrameDescriptor(value: unknown): value is DecodedFrameDescriptor {
  if (typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  const pixelFormats: readonly string[] = ["RGB24", "BGR24", "RGBA32"];
  const orientations: readonly number[] = [0, 90, 180, 270];
  const bytesPerPixel = frame.pixelFormat === "RGBA32" ? 4 : 3;
  return (
    typeof frame.eventId === "string" &&
    typeof frame.cameraId === "string" &&
    isCameraId(frame.cameraId) &&
    Number.isInteger(frame.streamEpoch) &&
    (frame.streamEpoch as number) >= 1 &&
    typeof frame.trackSid === "string" &&
    Number.isInteger(frame.sequence) &&
    (frame.sequence as number) >= 0 &&
    Number.isInteger(frame.width) &&
    (frame.width as number) > 0 &&
    Number.isInteger(frame.height) &&
    (frame.height as number) > 0 &&
    Number.isInteger(frame.strideBytes) &&
    pixelFormats.includes(frame.pixelFormat as string) &&
    (frame.strideBytes as number) >= (frame.width as number) * bytesPerPixel &&
    orientations.includes(frame.orientationDegrees as number) &&
    typeof frame.mirrored === "boolean" &&
    typeof frame.receivedAtMonotonicS === "number" &&
    Number.isFinite(frame.receivedAtMonotonicS) &&
    frame.receivedAtMonotonicS >= 0 &&
    (frame.captureTimeS === null || typeof frame.captureTimeS === "number")
  );
}

export function isDecodedAudioDescriptor(value: unknown): value is DecodedAudioDescriptor {
  if (typeof value !== "object" || value === null) return false;
  const audio = value as Record<string, unknown>;
  return (
    typeof audio.eventId === "string" &&
    audio.cameraId === "CAM-HOST" &&
    typeof audio.masterTrackSid === "string" &&
    Number.isInteger(audio.audioEpoch) &&
    (audio.audioEpoch as number) >= 1 &&
    Number.isInteger(audio.sequence) &&
    (audio.sequence as number) >= 0 &&
    Number.isInteger(audio.sampleRateHz) &&
    (audio.sampleRateHz as number) >= 8_000 &&
    (audio.sampleRateHz as number) <= 192_000 &&
    (audio.channels === 1 || audio.channels === 2) &&
    (audio.sampleFormat === "S16LE" || audio.sampleFormat === "F32LE") &&
    Number.isInteger(audio.sampleOffset) &&
    (audio.sampleOffset as number) >= 0 &&
    Number.isInteger(audio.sampleFrameCount) &&
    (audio.sampleFrameCount as number) > 0 &&
    typeof audio.receivedAtMonotonicS === "number" &&
    Number.isFinite(audio.receivedAtMonotonicS) &&
    audio.receivedAtMonotonicS >= 0
  );
}

export * from "./vision";

export * from "./readiness";
