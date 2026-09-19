import { type CameraId, isCameraId } from "./index";

/**
 * Shot decisions and render acknowledgements (v3 plan section 5, "Decision/ACK"
 * row; PRD section 10). A decision is a request to put a source on the
 * programme. Only the active compositor decides whether it can actually render
 * it, and only its acknowledgement turns the LIVE tally red.
 */

export const SWITCHING_CONTRACT_VERSION = "0.1.0" as const;

export const SLATE = "SLATE" as const;

/** Control generation used for decisions the renderer issues itself. The backend uses opaque strings. */
export const LOCAL_GENERATION = "local" as const;
export type ProgramSource = CameraId | typeof SLATE;

export function isProgramSource(value: unknown): value is ProgramSource {
  return value === SLATE || (typeof value === "string" && isCameraId(value));
}

export const OPERATOR_MODES = [
  "SETUP",
  "READY",
  "ASSIST",
  "AUTO",
  "MANUAL_HOLD",
  "DEGRADED",
  "ENDED",
] as const;
export type OperatorMode = (typeof OPERATOR_MODES)[number];

export const DECISION_ORIGINS = ["OPERATOR", "POLICY", "SAFETY"] as const;
export type DecisionOrigin = (typeof DECISION_ORIGINS)[number];

export const DECISION_REASONS = [
  "MANUAL_TAKE",
  "MANUAL_SLATE",
  "FAILOVER_SAFE",
  "FAILOVER_SLATE",
  "FAILOVER_RECOVER",
  "ACK_TIMEOUT_REVERT",
  "POLICY_INTRODUCE_GUEST",
  "POLICY_HANDOFF",
  "POLICY_RETURN_HOST",
  "POLICY_GROUP_WIDE",
  "POLICY_DEMO",
  "POLICY_REACTION",
] as const;
export type KnownDecisionReason = (typeof DECISION_REASONS)[number];
/** Reason codes are open strings on the wire (the backend and policy add their own); the list above is what the renderer itself emits. */
export type DecisionReason = string;

export type DecisionClockDomain = "renderer-monotonic" | "backend";

export interface ShotDecision {
  contractVersion: typeof SWITCHING_CONTRACT_VERSION;
  eventId: string;
  /** Monotonic within a control generation. LOCAL_GENERATION is the renderer's own issuance. */
  sequence: number;
  controlGeneration: string;
  /** The backend's decision id when the decision came over the control socket; null for local ones. */
  issuerDecisionId: string | null;
  /** Mode revision the issuer computed against. If the operator acted since, this is stale. */
  modeRevision: number;
  origin: DecisionOrigin;
  target: ProgramSource;
  /** Required for a camera target. The renderer rejects a mismatch with the live epoch. */
  targetStreamEpoch: number | null;
  reason: DecisionReason;
  /** Observable evidence for the decision log, such as a transcript span. Never model reasoning. */
  evidence: string | null;
  clockDomain: DecisionClockDomain;
  createdAtMs: number;
  /** Set by the issuer; the renderer never extends it. */
  expiresAtMs: number;
}

export const REJECT_REASONS = [
  "WRONG_EVENT",
  "EVENT_ENDED",
  "STALE_CONTROL_GENERATION",
  "DUPLICATE_OR_OUT_OF_ORDER",
  "TIMING_UNCERTAIN",
  "EXPIRED",
  "STALE_MODE_REVISION",
  "OPERATOR_HOLD",
  "ASSIST_SUGGEST_ONLY",
  "UNKNOWN_TARGET",
  "NOT_RENDERABLE",
  "EPOCH_MISMATCH",
  "ALREADY_ON_AIR",
  "MIN_SHOT_DURATION",
  "SUPERSEDED",
  "ACK_TIMEOUT",
] as const;
export type RejectReason = (typeof REJECT_REASONS)[number];

/** FAILED: the decision was accepted but the source never drew a frame in time. */
export type AckOutcome = "APPLIED" | "REJECTED" | "FAILED";

export interface RenderAck {
  contractVersion: typeof SWITCHING_CONTRACT_VERSION;
  eventId: string;
  decisionSequence: number;
  controlGeneration: string;
  issuerDecisionId: string | null;
  rendererId: string;
  rendererGeneration: number;
  outcome: AckOutcome;
  rejectReason: RejectReason | null;
  /** What is on the programme canvas after handling this decision. */
  renderedSource: ProgramSource;
  renderedStreamEpoch: number | null;
  renderedVideoTrackSid: string | null;
  /** The renderer's mode revision at acknowledgement time. */
  modeRevision: number;
  clockDomain: "renderer-monotonic";
  /** APPLIED: when the first frame of the new source was drawn. REJECTED: when it was evaluated. */
  atMs: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isShotDecision(value: unknown): value is ShotDecision {
  if (!isRecord(value)) return false;
  if (value.contractVersion !== SWITCHING_CONTRACT_VERSION) return false;
  if (typeof value.eventId !== "string" || typeof value.sequence !== "number") return false;
  if (typeof value.controlGeneration !== "string" || typeof value.modeRevision !== "number") return false;
  if (value.issuerDecisionId !== null && typeof value.issuerDecisionId !== "string") return false;
  if (!DECISION_ORIGINS.includes(value.origin as DecisionOrigin)) return false;
  if (!isProgramSource(value.target)) return false;
  if (value.targetStreamEpoch !== null && typeof value.targetStreamEpoch !== "number") return false;
  if (typeof value.reason !== "string" || value.reason.length === 0) return false;
  if (value.evidence !== null && typeof value.evidence !== "string") return false;
  if (value.clockDomain !== "renderer-monotonic" && value.clockDomain !== "backend") return false;
  return typeof value.createdAtMs === "number" && typeof value.expiresAtMs === "number";
}

export function isRenderAck(value: unknown): value is RenderAck {
  if (!isRecord(value)) return false;
  if (value.contractVersion !== SWITCHING_CONTRACT_VERSION) return false;
  if (typeof value.eventId !== "string" || typeof value.decisionSequence !== "number") return false;
  if (typeof value.controlGeneration !== "string") return false;
  if (value.issuerDecisionId !== null && typeof value.issuerDecisionId !== "string") return false;
  if (typeof value.rendererId !== "string" || typeof value.rendererGeneration !== "number") return false;
  if (value.outcome !== "APPLIED" && value.outcome !== "REJECTED" && value.outcome !== "FAILED") return false;
  if (value.rejectReason !== null && !REJECT_REASONS.includes(value.rejectReason as RejectReason)) {
    return false;
  }
  if (!isProgramSource(value.renderedSource)) return false;
  if (typeof value.modeRevision !== "number" || value.clockDomain !== "renderer-monotonic") return false;
  return typeof value.atMs === "number";
}
