import { isCameraId, type CameraId } from "./index";
import type { ReceiverReadiness } from "./readiness";

export const CONTROL_MODES = [
  "SETUP",
  "READY",
  "ASSIST",
  "AUTO",
  "MANUAL_HOLD",
  "DEGRADED",
  "ENDED",
] as const;
export type ControlMode = (typeof CONTROL_MODES)[number];

export type ControlRole = "DIRECTOR" | "OBSERVER";
export type RenderStatus = "APPLIED" | "REJECTED" | "FAILED";
export type RenderTarget = "CAMERA" | "SLATE";

export interface ControlSessionResponse {
  token: string;
  role: ControlRole;
  expiresInSeconds: number;
}

export interface ControlSnapshot {
  eventId: string;
  controlGeneration: string;
  mode: ControlMode;
  modeRevision: number;
  decisionSequence: number;
  liveCameraId: CameraId | null;
  liveStreamEpoch: number | null;
  pendingDecisionId: string | null;
}

export interface RenderCommand {
  decisionId: string;
  eventId: string;
  controlGeneration: string;
  decisionSequence: number;
  modeRevision: number;
  target: RenderTarget;
  cameraId: CameraId | null;
  streamEpoch: number | null;
  reasonCode: string;
  createdAtMs: number;
  expiresAtMs: number;
}

export interface RenderAcknowledgement {
  decisionId: string;
  controlGeneration: string;
  decisionSequence: number;
  status: RenderStatus;
  actualTarget: RenderTarget;
  actualCameraId: CameraId | null;
  actualStreamEpoch: number | null;
  appliedAtMs: number;
  detail?: string | null;
}

export interface RenderReconciliation {
  controlGeneration: string;
  actualTarget: RenderTarget;
  actualCameraId: CameraId | null;
  actualStreamEpoch: number | null;
  reportedAtMs: number;
}

export interface ControlMutationResponse {
  state: ControlSnapshot;
  renderCommand: RenderCommand | null;
}

export interface ControlLatencyMetrics {
  appliedCount: number;
  rejectedCount: number;
  outstandingCount: number;
  p50Ms: number | null;
  p95Ms: number | null;
  maximumMs: number | null;
}

export type ControlServerMessage =
  | { type: "control.authenticated"; role: ControlRole; eventId: string }
  | { type: "control.state"; state: ControlSnapshot }
  | { type: "render.command"; command: RenderCommand }
  | { type: "receiver.readiness"; readiness: ReceiverReadiness }
  | { type: "control.pong" }
  | { type: "control.error"; code: string; message?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

export function isControlSnapshot(value: unknown): value is ControlSnapshot {
  if (!isRecord(value)) return false;
  return (
    typeof value.eventId === "string" &&
    typeof value.controlGeneration === "string" &&
    CONTROL_MODES.includes(value.mode as ControlMode) &&
    isNonNegativeInteger(value.modeRevision) &&
    isNonNegativeInteger(value.decisionSequence) &&
    (value.liveCameraId === null ||
      (typeof value.liveCameraId === "string" && isCameraId(value.liveCameraId))) &&
    (value.liveStreamEpoch === null ||
      (isNonNegativeInteger(value.liveStreamEpoch) && value.liveStreamEpoch >= 1)) &&
    (value.pendingDecisionId === null || typeof value.pendingDecisionId === "string")
  );
}

export function isRenderCommand(value: unknown): value is RenderCommand {
  if (!isRecord(value)) return false;
  const common =
    typeof value.decisionId === "string" &&
    typeof value.eventId === "string" &&
    typeof value.controlGeneration === "string" &&
    isNonNegativeInteger(value.decisionSequence) &&
    value.decisionSequence >= 1 &&
    isNonNegativeInteger(value.modeRevision) &&
    (value.target === "CAMERA" || value.target === "SLATE") &&
    typeof value.reasonCode === "string" &&
    isNonNegativeInteger(value.createdAtMs) &&
    isNonNegativeInteger(value.expiresAtMs) &&
    value.expiresAtMs > value.createdAtMs;
  if (!common) return false;
  if (value.target === "SLATE") return value.cameraId === null && value.streamEpoch === null;
  return (
    typeof value.cameraId === "string" &&
    isCameraId(value.cameraId) &&
    isNonNegativeInteger(value.streamEpoch) &&
    value.streamEpoch >= 1
  );
}

export function commandIsCurrent(
  command: RenderCommand,
  state: ControlSnapshot,
  nowMs: number,
): boolean {
  return (
    command.eventId === state.eventId &&
    command.controlGeneration === state.controlGeneration &&
    command.modeRevision === state.modeRevision &&
    command.expiresAtMs >= nowMs
  );
}
