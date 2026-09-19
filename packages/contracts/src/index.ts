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
