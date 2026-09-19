import {
  type CameraId,
  type DecisionOrigin,
  type DecisionReason,
  LOCAL_GENERATION,
  type OperatorMode,
  type ProgramSource,
  type ReceiverReadiness,
  type RejectReason,
  type RenderAck,
  type ShotDecision,
  type SlotReadiness,
  SLATE,
  SWITCHING_CONTRACT_VERSION,
} from "@cue/contracts";

/**
 * The switcher: a pure reducer that decides what the programme canvas shows.
 * Every change, whether from the operator, a future policy, or the health
 * failover, is a ShotDecision run through the same gates (PRD section 10).
 * Nothing here touches the DOM, LiveKit or the network.
 */

/** PRD section 10: normal minimum shot; manual and safety cuts bypass it. */
export const MIN_SHOT_MS = 2500;
/** PRD section 16: fail over within 1.5 s of sustained loss where a safe view exists. */
export const FAILOVER_AFTER_MS = 1500;
/** PRD section 10: a recovered source counts as healthy only after 2 s of frames. */
export const RECOVER_AFTER_MS = 2000;
/** How long a locally issued decision stays valid before the renderer refuses it. */
export const LOCAL_DECISION_TTL_MS = 5000;
/** A switch that has not drawn a frame after this long is acknowledged FAILED and reverted. */
export const ACK_TIMEOUT_MS = 1000;
/** Producer-approved order for a safety cut. The wide view is the safety shot. */
export const DEFAULT_SAFE_ORDER: readonly CameraId[] = ["CAM-WIDE", "CAM-HOST", "CAM-GUEST"];
const MAX_ACKS = 100;

export interface ProgramState {
  source: ProgramSource;
  streamEpoch: number | null;
  videoTrackSid: string | null;
  /** When this source was selected (renderer clock). */
  sinceMs: number;
  reason: DecisionReason | "INITIAL";
  origin: DecisionOrigin | null;
  decisionSequence: number | null;
  /** Set when the canvas has drawn this source. The tally goes red only then. */
  confirmedAtMs: number | null;
}

export interface SwitcherState {
  eventId: string;
  rendererId: string;
  rendererGeneration: number;
  /** Backend control generation from the control snapshot; LOCAL_GENERATION until one arrives. Local decisions always use LOCAL_GENERATION. */
  controlGeneration: string;
  /** Null until the backend supplies a mapping; backend-clock decisions are rejected meanwhile. */
  backendClockOffsetMs: number | null;
  mode: OperatorMode;
  modeRevision: number;
  program: ProgramState;
  /** What was on air before the current programme, for a revert after a failed switch. */
  previousProgram: ProgramState | null;
  safeOrder: readonly CameraId[];
  lastSequenceByGeneration: Readonly<Record<string, number>>;
  nextLocalSequence: number;
  /** A policy decision received in ASSIST mode, waiting for the operator. */
  suggestion: ShotDecision | null;
  renderableSince: Readonly<Partial<Record<CameraId, number>>>;
  programUnhealthySinceMs: number | null;
  /** An APPLIED acknowledgement waiting for the first drawn frame. */
  pendingAck: RenderAck | null;
  /** Newest first, bounded. The decision timeline for the review screen. */
  acks: readonly RenderAck[];
}

export interface Step {
  state: SwitcherState;
  /** An acknowledgement produced by this step, if any. APPLIED acks only appear on confirmDraw. */
  ack: RenderAck | null;
  /** Human-readable lines for the receiver log. */
  log: string[];
}

export function createSwitcher(init: {
  eventId: string;
  rendererId: string;
  rendererGeneration: number;
  now: number;
  safeOrder?: readonly CameraId[];
}): SwitcherState {
  return {
    eventId: init.eventId,
    rendererId: init.rendererId,
    rendererGeneration: init.rendererGeneration,
    controlGeneration: LOCAL_GENERATION,
    backendClockOffsetMs: null,
    mode: "ASSIST",
    modeRevision: 1,
    program: {
      source: SLATE,
      streamEpoch: null,
      videoTrackSid: null,
      sinceMs: init.now,
      reason: "INITIAL",
      origin: null,
      decisionSequence: null,
      confirmedAtMs: null,
    },
    previousProgram: null,
    safeOrder: init.safeOrder ?? DEFAULT_SAFE_ORDER,
    lastSequenceByGeneration: {},
    nextLocalSequence: 1,
    suggestion: null,
    renderableSince: {},
    programUnhealthySinceMs: null,
    pendingAck: null,
    acks: [],
  };
}

export function isLive(state: SwitcherState): boolean {
  return state.program.confirmedAtMs !== null;
}

function slotFor(readiness: ReceiverReadiness | null, cameraId: CameraId): SlotReadiness | null {
  return readiness?.slots.find((slot) => slot.cameraId === cameraId) ?? null;
}

function pushAck(acks: readonly RenderAck[], ack: RenderAck): RenderAck[] {
  return [ack, ...acks].slice(0, MAX_ACKS);
}

function makeAck(
  state: SwitcherState,
  decision: ShotDecision,
  outcome: RenderAck["outcome"],
  rejectReason: RejectReason | null,
  now: number,
  program: ProgramState,
): RenderAck {
  return {
    contractVersion: SWITCHING_CONTRACT_VERSION,
    eventId: state.eventId,
    decisionSequence: decision.sequence,
    controlGeneration: decision.controlGeneration,
    issuerDecisionId: decision.issuerDecisionId,
    rendererId: state.rendererId,
    rendererGeneration: state.rendererGeneration,
    outcome,
    rejectReason,
    renderedSource: program.source,
    renderedStreamEpoch: program.streamEpoch,
    renderedVideoTrackSid: program.videoTrackSid,
    modeRevision: state.modeRevision,
    clockDomain: "renderer-monotonic",
    atMs: now,
  };
}

function localDecision(
  state: SwitcherState,
  origin: DecisionOrigin,
  target: ProgramSource,
  targetStreamEpoch: number | null,
  reason: DecisionReason,
  now: number,
  evidence: string | null = null,
): { state: SwitcherState; decision: ShotDecision } {
  // Never reuse a sequence the renderer has already consumed for generation 0.
  const sequence = Math.max(
    state.nextLocalSequence,
    (state.lastSequenceByGeneration[LOCAL_GENERATION] ?? 0) + 1,
  );
  const decision: ShotDecision = {
    contractVersion: SWITCHING_CONTRACT_VERSION,
    eventId: state.eventId,
    sequence,
    controlGeneration: LOCAL_GENERATION,
    issuerDecisionId: null,
    modeRevision: state.modeRevision,
    origin,
    target,
    targetStreamEpoch,
    reason,
    evidence,
    clockDomain: "renderer-monotonic",
    createdAtMs: now,
    expiresAtMs: now + LOCAL_DECISION_TTL_MS,
  };
  return { state: { ...state, nextLocalSequence: sequence + 1 }, decision };
}

function expiryInRendererClock(state: SwitcherState, decision: ShotDecision): number | null {
  if (decision.clockDomain === "renderer-monotonic") return decision.expiresAtMs;
  if (state.backendClockOffsetMs === null) return null;
  return decision.expiresAtMs + state.backendClockOffsetMs;
}

/**
 * Run one decision through every gate. Rejections acknowledge immediately.
 * An applied decision changes the programme intent and parks an APPLIED
 * acknowledgement until the canvas confirms the first drawn frame.
 */
export function evaluateDecision(
  state: SwitcherState,
  decision: ShotDecision,
  readiness: ReceiverReadiness | null,
  now: number,
): Step {
  const label = `#${decision.controlGeneration}.${decision.sequence} ${decision.origin} ${decision.target}`;

  const reject = (reason: RejectReason, consumeSequence = true): Step => {
    const ack = makeAck(state, decision, "REJECTED", reason, now, state.program);
    const lastSequenceByGeneration = consumeSequence
      ? {
          ...state.lastSequenceByGeneration,
          [decision.controlGeneration]: Math.max(
            state.lastSequenceByGeneration[decision.controlGeneration] ?? 0,
            decision.sequence,
          ),
        }
      : state.lastSequenceByGeneration;
    return {
      state: { ...state, lastSequenceByGeneration, acks: pushAck(state.acks, ack) },
      ack,
      log: [`Rejected ${label}: ${reason}`],
    };
  };

  if (decision.eventId !== state.eventId) return reject("WRONG_EVENT", false);
  if (state.mode === "ENDED") return reject("EVENT_ENDED");
  if (
    decision.controlGeneration !== LOCAL_GENERATION &&
    decision.controlGeneration !== state.controlGeneration
  ) {
    return reject("STALE_CONTROL_GENERATION", false);
  }
  const lastSequence = state.lastSequenceByGeneration[decision.controlGeneration] ?? 0;
  if (decision.sequence <= lastSequence) return reject("DUPLICATE_OR_OUT_OF_ORDER", false);

  const expiresAt = expiryInRendererClock(state, decision);
  if (expiresAt === null) return reject("TIMING_UNCERTAIN");
  if (expiresAt <= now) return reject("EXPIRED");
  if (decision.modeRevision !== state.modeRevision) return reject("STALE_MODE_REVISION");

  if (decision.origin === "POLICY") {
    if (state.mode === "MANUAL_HOLD") return reject("OPERATOR_HOLD");
    if (state.mode !== "AUTO") {
      const step = reject("ASSIST_SUGGEST_ONLY");
      return {
        ...step,
        state: { ...step.state, suggestion: decision },
        log: [...step.log, `Suggestion: ${decision.target} (${decision.reason}); press TAKE to accept`],
      };
    }
  }

  let streamEpoch: number | null = null;
  let videoTrackSid: string | null = null;
  if (decision.target === SLATE) {
    if (state.program.source === SLATE) return reject("ALREADY_ON_AIR");
  } else {
    const slot = slotFor(readiness, decision.target);
    if (!slot) return reject("UNKNOWN_TARGET");
    if (!slot.renderable) return reject("NOT_RENDERABLE");
    if (decision.targetStreamEpoch !== null && slot.streamEpoch !== decision.targetStreamEpoch) {
      return reject("EPOCH_MISMATCH");
    }
    streamEpoch = slot.streamEpoch;
    videoTrackSid = slot.videoTrackSid;
    if (state.program.source === decision.target && state.program.streamEpoch === streamEpoch) {
      return reject("ALREADY_ON_AIR");
    }
    if (
      decision.origin === "POLICY" &&
      state.program.source !== SLATE &&
      now - state.program.sinceMs < MIN_SHOT_MS
    ) {
      return reject("MIN_SHOT_DURATION");
    }
  }

  const program: ProgramState = {
    source: decision.target,
    streamEpoch,
    videoTrackSid,
    sinceMs: now,
    reason: decision.reason,
    origin: decision.origin,
    decisionSequence: decision.sequence,
    confirmedAtMs: null,
  };

  let acks = state.acks;
  const log = [
    `Applied ${label}: ${decision.reason}${decision.evidence ? ` (${decision.evidence})` : ""}; waiting for first drawn frame`,
  ];
  if (state.pendingAck) {
    acks = pushAck(acks, { ...state.pendingAck, outcome: "REJECTED", rejectReason: "SUPERSEDED", atMs: now });
    log.push(`Superseded unconfirmed #${state.pendingAck.controlGeneration}.${state.pendingAck.decisionSequence}`);
  }

  return {
    state: {
      ...state,
      program,
      previousProgram: state.program,
      pendingAck: makeAck(state, decision, "APPLIED", null, now, program),
      suggestion: null,
      programUnhealthySinceMs: null,
      lastSequenceByGeneration: {
        ...state.lastSequenceByGeneration,
        [decision.controlGeneration]: decision.sequence,
      },
      acks,
    },
    ack: null,
    log,
  };
}

/** The canvas drew a frame. If it was the first frame of a pending switch, that is the ACK. */
export function confirmDraw(
  state: SwitcherState,
  drawn: { source: ProgramSource; videoTrackSid: string | null },
  now: number,
): Step {
  if (drawn.source !== state.program.source) return { state, ack: null, log: [] };

  if (state.pendingAck && state.pendingAck.renderedSource === drawn.source) {
    const ack: RenderAck = {
      ...state.pendingAck,
      renderedVideoTrackSid: drawn.videoTrackSid ?? state.pendingAck.renderedVideoTrackSid,
      modeRevision: state.modeRevision,
      atMs: now,
    };
    return {
      state: {
        ...state,
        program: { ...state.program, confirmedAtMs: now },
        pendingAck: null,
        acks: pushAck(state.acks, ack),
      },
      ack,
      log: [
        `LIVE ${drawn.source}: ack #${ack.controlGeneration}.${ack.decisionSequence}, ${Math.round(now - state.program.sinceMs)} ms after decision`,
      ],
    };
  }

  if (state.program.confirmedAtMs === null) {
    return {
      state: { ...state, program: { ...state.program, confirmedAtMs: now } },
      ack: null,
      log: [],
    };
  }
  return { state, ack: null, log: [] };
}

/** Every manual action bumps the mode revision, applied or not, so late decisions cannot undo it. */
function bumpRevision(step: Step): Step {
  return { ...step, state: { ...step.state, modeRevision: step.state.modeRevision + 1 } };
}

export function operatorTake(
  state: SwitcherState,
  cameraId: CameraId,
  readiness: ReceiverReadiness | null,
  now: number,
): Step {
  const slot = slotFor(readiness, cameraId);
  const issued = localDecision(state, "OPERATOR", cameraId, slot?.streamEpoch ?? null, "MANUAL_TAKE", now);
  return bumpRevision(evaluateDecision(issued.state, issued.decision, readiness, now));
}

export function operatorSlate(state: SwitcherState, now: number): Step {
  const issued = localDecision(state, "OPERATOR", SLATE, null, "MANUAL_SLATE", now);
  return bumpRevision(evaluateDecision(issued.state, issued.decision, null, now));
}

/** Accept the parked policy suggestion as a manual take of the same target. */
export function acceptSuggestion(
  state: SwitcherState,
  readiness: ReceiverReadiness | null,
  now: number,
): Step {
  const suggestion = state.suggestion;
  if (!suggestion) return { state, ack: null, log: ["No suggestion to accept"] };
  if (suggestion.target === SLATE) return operatorSlate({ ...state, suggestion: null }, now);
  return operatorTake({ ...state, suggestion: null }, suggestion.target, readiness, now);
}

export function operatorHold(state: SwitcherState, now: number): Step {
  if (state.mode === "MANUAL_HOLD") return { state, ack: null, log: [] };
  return bumpRevision({
    state: { ...state, mode: "MANUAL_HOLD", suggestion: null },
    ack: null,
    log: [`HOLD at ${Math.round(now)}: operator owns ${state.program.source}; policy decisions are ignored, health failover stays on`],
  });
}

export function operatorResume(state: SwitcherState, mode: "ASSIST" | "AUTO", now: number): Step {
  if (state.mode === mode) return { state, ack: null, log: [] };
  return bumpRevision({
    state: { ...state, mode },
    ack: null,
    log: [`Mode ${mode} at ${Math.round(now)}${mode === "AUTO" ? ": policy may execute validated decisions" : ": policy suggests, operator takes"}`],
  });
}

export function markEnded(state: SwitcherState): SwitcherState {
  return { ...state, mode: "ENDED", suggestion: null };
}

/** A new renderer generation (tab restart, reconnect) never resumes AUTO and forgets pending work. */
export function resetForGeneration(state: SwitcherState, rendererGeneration: number): SwitcherState {
  return {
    ...state,
    rendererGeneration,
    mode: state.mode === "ENDED" ? "ENDED" : "ASSIST",
    modeRevision: state.modeRevision + 1,
    suggestion: null,
    pendingAck: null,
    programUnhealthySinceMs: null,
    renderableSince: {},
  };
}

/**
 * The backend's control snapshot is authoritative while the control link is up:
 * adopt its generation, mode and revision. A generation change drops pending work.
 */
export function syncControlState(
  state: SwitcherState,
  snapshot: { controlGeneration: string; mode: OperatorMode; modeRevision: number },
  now: number,
): Step {
  const generationChanged = snapshot.controlGeneration !== state.controlGeneration;
  const changed =
    generationChanged ||
    snapshot.mode !== state.mode ||
    snapshot.modeRevision !== state.modeRevision;
  if (!changed) return { state, ack: null, log: [] };

  const log: string[] = [];
  let acks = state.acks;
  let pendingAck = state.pendingAck;
  if (generationChanged) {
    log.push(`Backend control generation ${snapshot.controlGeneration} (was ${state.controlGeneration}); pending work dropped`);
    if (pendingAck) {
      acks = pushAck(acks, { ...pendingAck, outcome: "REJECTED", rejectReason: "STALE_CONTROL_GENERATION", atMs: now });
      pendingAck = null;
    }
  }
  if (snapshot.mode !== state.mode) log.push(`Backend mode ${snapshot.mode} (revision ${snapshot.modeRevision})`);
  return {
    state: {
      ...state,
      controlGeneration: snapshot.controlGeneration,
      mode: snapshot.mode,
      modeRevision: snapshot.modeRevision,
      suggestion: generationChanged ? null : state.suggestion,
      pendingAck,
      acks,
    },
    ack: null,
    log,
  };
}

/**
 * A switch that never drew a frame is a failed render, not a live cut. Acknowledge
 * it FAILED and go back to what was on air, or to a safe source, or to the slate.
 */
export function expirePendingAck(
  state: SwitcherState,
  readiness: ReceiverReadiness | null,
  now: number,
  timeoutMs = ACK_TIMEOUT_MS,
): Step {
  const pending = state.pendingAck;
  if (!pending || now - state.program.sinceMs < timeoutMs) return { state, ack: null, log: [] };

  const failed: RenderAck = { ...pending, outcome: "FAILED", rejectReason: "ACK_TIMEOUT", atMs: now };
  const log = [`FAILED #${pending.controlGeneration}.${pending.decisionSequence}: ${pending.renderedSource} drew no frame within ${timeoutMs} ms`];
  let next: SwitcherState = { ...state, pendingAck: null, acks: pushAck(state.acks, failed) };

  const previous = next.previousProgram;
  let target: ProgramSource = SLATE;
  let epoch: number | null = null;
  if (previous && previous.source !== SLATE) {
    const slot = slotFor(readiness, previous.source);
    if (slot?.renderable) {
      target = previous.source;
      epoch = slot.streamEpoch;
    }
  }
  if (target === SLATE && readiness) {
    const candidate = safeCandidate(next, readiness, now, next.program.source);
    if (candidate) {
      target = candidate.cameraId;
      epoch = candidate.streamEpoch;
    }
  }
  const issued = localDecision(next, "SAFETY", target, epoch, "ACK_TIMEOUT_REVERT", now, `reverting after failed switch to ${pending.renderedSource}`);
  const step = evaluateDecision(issued.state, issued.decision, readiness, now);
  return { state: step.state, ack: failed, log: [...log, ...step.log] };
}

function safeCandidate(
  state: SwitcherState,
  readiness: ReceiverReadiness,
  now: number,
  exclude: ProgramSource,
): { cameraId: CameraId; streamEpoch: number | null } | null {
  for (const cameraId of state.safeOrder) {
    if (cameraId === exclude) continue;
    const slot = slotFor(readiness, cameraId);
    const since = state.renderableSince[cameraId];
    if (!slot || !slot.renderable || since === undefined) continue;
    if (now - since < RECOVER_AFTER_MS) continue;
    return { cameraId, streamEpoch: slot.streamEpoch };
  }
  return null;
}

/**
 * Health failover (PRD sections 10 and 13). Runs on every readiness tick.
 * Works in every mode including MANUAL_HOLD: a dead source is replaced by the
 * approved safety shot, or the slate when nothing is usable. Never shows a
 * frozen frame as live.
 */
export function runHealthCheck(
  state: SwitcherState,
  readiness: ReceiverReadiness | null,
  now: number,
): Step {
  if (!readiness || state.mode === "ENDED") return { state, ack: null, log: [] };

  const renderableSince: Partial<Record<CameraId, number>> = { ...state.renderableSince };
  for (const slot of readiness.slots) {
    if (slot.renderable) {
      if (renderableSince[slot.cameraId] === undefined) renderableSince[slot.cameraId] = now;
    } else {
      delete renderableSince[slot.cameraId];
    }
  }
  let next: SwitcherState = { ...state, renderableSince };
  const log: string[] = [];

  if (next.program.source === SLATE) {
    if (next.program.reason !== "FAILOVER_SLATE") return { state: next, ack: null, log };
    const candidate = safeCandidate(next, readiness, now, SLATE);
    if (!candidate) return { state: next, ack: null, log };
    const issued = localDecision(
      next,
      "SAFETY",
      candidate.cameraId,
      candidate.streamEpoch,
      "FAILOVER_RECOVER",
      now,
      `${candidate.cameraId} healthy for ${RECOVER_AFTER_MS} ms; leaving failover slate`,
    );
    const step = evaluateDecision(issued.state, issued.decision, readiness, now);
    return { ...step, log: [...log, ...step.log] };
  }

  const liveSlot = slotFor(readiness, next.program.source);
  if (liveSlot && liveSlot.videoTrackSid !== null) {
    if (
      liveSlot.streamEpoch !== next.program.streamEpoch ||
      liveSlot.videoTrackSid !== next.program.videoTrackSid
    ) {
      next = {
        ...next,
        program: {
          ...next.program,
          streamEpoch: liveSlot.streamEpoch,
          videoTrackSid: liveSlot.videoTrackSid,
        },
      };
      log.push(
        `${next.program.source} republished on air: epoch ${liveSlot.streamEpoch}, track ${liveSlot.videoTrackSid}`,
      );
    }
  }

  const healthy = liveSlot?.renderable ?? false;
  if (healthy) {
    return { state: { ...next, programUnhealthySinceMs: null }, ack: null, log };
  }

  const unhealthySince = next.programUnhealthySinceMs ?? now;
  next = { ...next, programUnhealthySinceMs: unhealthySince };
  const outageMs = now - unhealthySince;
  if (outageMs < FAILOVER_AFTER_MS) return { state: next, ack: null, log };

  const candidate = safeCandidate(next, readiness, now, next.program.source);
  const evidence = `${next.program.source} unrenderable for ${Math.round(outageMs)} ms`;
  const issued = candidate
    ? localDecision(next, "SAFETY", candidate.cameraId, candidate.streamEpoch, "FAILOVER_SAFE", now, evidence)
    : localDecision(next, "SAFETY", SLATE, null, "FAILOVER_SLATE", now, evidence);
  const step = evaluateDecision(issued.state, issued.decision, readiness, now);
  return { ...step, log: [...log, ...step.log] };
}
