import {
  type DecisionOrigin,
  type ProgramSource,
  type RenderAck,
  type RenderAcknowledgement,
  type RenderCommand,
  type RenderReconciliation,
  type ShotDecision,
  SLATE,
  SWITCHING_CONTRACT_VERSION,
} from "@cue/contracts";

/**
 * Pure adapters between A's control-socket shapes (RenderCommand, RenderAcknowledgement,
 * RenderReconciliation) and the renderer's own ShotDecision and RenderAck.
 */

/** A stamps commands in wall-clock milliseconds; the switcher runs on performance.now(). */
export function backendClockOffsetMs(nowRenderer: number, nowWall: number): number {
  return nowRenderer - nowWall;
}

export function originForReasonCode(reasonCode: string): DecisionOrigin {
  const code = reasonCode.toUpperCase();
  if (code.startsWith("MANUAL")) return "OPERATOR";
  if (code.startsWith("FAILOVER") || code.startsWith("SAFETY") || code.startsWith("ACK_TIMEOUT")) {
    return "SAFETY";
  }
  return "POLICY";
}

export function commandToDecision(command: RenderCommand): ShotDecision {
  const target: ProgramSource = command.target === "SLATE" || command.cameraId === null ? SLATE : command.cameraId;
  return {
    contractVersion: SWITCHING_CONTRACT_VERSION,
    eventId: command.eventId,
    sequence: command.decisionSequence,
    controlGeneration: command.controlGeneration,
    issuerDecisionId: command.decisionId,
    modeRevision: command.modeRevision,
    origin: originForReasonCode(command.reasonCode),
    target,
    targetStreamEpoch: target === SLATE ? null : command.streamEpoch,
    reason: command.reasonCode,
    evidence: null,
    clockDomain: "backend",
    createdAtMs: command.createdAtMs,
    expiresAtMs: command.expiresAtMs,
  };
}

/**
 * Only decisions the backend issued get acknowledged to it. Local decisions are
 * reported through reconciliation instead. `offsetMs` is renderer minus wall.
 */
export function ackToAcknowledgement(ack: RenderAck, offsetMs: number): RenderAcknowledgement | null {
  if (ack.issuerDecisionId === null) return null;
  const detail = ack.rejectReason ? ack.rejectReason : null;
  return {
    decisionId: ack.issuerDecisionId,
    controlGeneration: ack.controlGeneration,
    decisionSequence: ack.decisionSequence,
    status: ack.outcome,
    actualTarget: ack.renderedSource === SLATE ? "SLATE" : "CAMERA",
    actualCameraId: ack.renderedSource === SLATE ? null : ack.renderedSource,
    actualStreamEpoch: ack.renderedSource === SLATE ? null : ack.renderedStreamEpoch,
    appliedAtMs: Math.max(0, Math.round(ack.atMs - offsetMs)),
    detail,
  };
}

export function reconciliationFor(
  program: { source: ProgramSource; streamEpoch: number | null },
  controlGeneration: string,
  nowWallMs: number,
): RenderReconciliation {
  return {
    controlGeneration,
    actualTarget: program.source === SLATE ? "SLATE" : "CAMERA",
    actualCameraId: program.source === SLATE ? null : program.source,
    actualStreamEpoch: program.source === SLATE ? null : program.streamEpoch,
    reportedAtMs: Math.max(0, Math.round(nowWallMs)),
  };
}

/** Idempotency keys for A's mutation endpoints: 8 to 96 chars of [A-Za-z0-9._:-]. */
export function idempotencyKey(prefix: string, nowWallMs: number, nonce: string): string {
  const safe = `${prefix}:${Math.round(nowWallMs)}:${nonce}`.replace(/[^A-Za-z0-9._:-]/g, "-");
  return safe.slice(0, 96).padEnd(8, "0");
}
