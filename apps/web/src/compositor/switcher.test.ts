import {
  CAMERA_IDS,
  type CameraId,
  READINESS_CONTRACT_VERSION,
  type ReceiverReadiness,
  type ShotDecision,
  SWITCHING_CONTRACT_VERSION,
} from "@cue/contracts";
import { describe, expect, it } from "vitest";

import {
  acceptSuggestion,
  ACK_TIMEOUT_MS,
  confirmDraw,
  createSwitcher,
  evaluateDecision,
  expirePendingAck,
  FAILOVER_AFTER_MS,
  isLive,
  MIN_SHOT_MS,
  operatorHold,
  operatorResume,
  operatorSlate,
  operatorTake,
  RECOVER_AFTER_MS,
  resetForGeneration,
  runHealthCheck,
  type SwitcherState,
  syncControlState,
} from "./switcher";

const EVENT = "hackmit-demo";

type SlotSpec = { renderable: boolean; epoch?: number; sid?: string };

function readinessWith(spec: Partial<Record<CameraId, SlotSpec>>, now = 0): ReceiverReadiness {
  return {
    contractVersion: READINESS_CONTRACT_VERSION,
    eventId: EVENT,
    rendererId: "renderer-test",
    rendererGeneration: 1,
    receiverIdentity: "receiver:x",
    connected: true,
    clockDomain: "renderer-monotonic",
    reportedAtMs: now,
    currentSource: null,
    masterAudio: { cameraId: "CAM-HOST", trackSid: null, attached: false, playbackAllowed: true },
    slots: CAMERA_IDS.map((cameraId) => {
      const s = spec[cameraId];
      return {
        cameraId,
        publisherIdentity: s ? `publisher:${cameraId}` : null,
        streamEpoch: s ? (s.epoch ?? 1) : null,
        videoTrackSid: s ? (s.sid ?? `TR_${cameraId}`) : null,
        audioTrackSid: null,
        decoded: Boolean(s),
        renderable: s?.renderable ?? false,
        lastFrameAgeMs: s?.renderable ? 20 : null,
        framesProgressing: s?.renderable ?? false,
        frameCount: s ? 100 : 0,
        width: 1280,
        height: 720,
        state: s ? (s.renderable ? "video-ready" : "stalled") : "waiting",
      };
    }),
  };
}

const allHealthy = readinessWith({
  "CAM-HOST": { renderable: true },
  "CAM-GUEST": { renderable: true },
  "CAM-WIDE": { renderable: true },
});

function fresh(now = 0): SwitcherState {
  return createSwitcher({ eventId: EVENT, rendererId: "renderer-test", rendererGeneration: 1, now });
}

let policySequence = 100;
function policyDecision(
  state: SwitcherState,
  target: ShotDecision["target"],
  now: number,
  overrides: Partial<ShotDecision> = {},
): ShotDecision {
  policySequence += 1;
  return {
    contractVersion: SWITCHING_CONTRACT_VERSION,
    eventId: EVENT,
    sequence: policySequence,
    controlGeneration: state.controlGeneration,
    issuerDecisionId: null,
    modeRevision: state.modeRevision,
    origin: "POLICY",
    target,
    targetStreamEpoch: target === "SLATE" ? null : 1,
    reason: "POLICY_INTRODUCE_GUEST",
    evidence: "please welcome Sarah",
    clockDomain: "renderer-monotonic",
    createdAtMs: now,
    expiresAtMs: now + 3000,
    ...overrides,
  };
}

/** Bring a fresh switcher to a confirmed live shot on CAM-HOST at t=0. */
function liveOnHost(): SwitcherState {
  let { state } = operatorTake(fresh(), "CAM-HOST", allHealthy, 0);
  ({ state } = confirmDraw(state, { source: "CAM-HOST", videoTrackSid: "TR_CAM-HOST" }, 40));
  return state;
}

describe("start state", () => {
  it("starts on the slate in ASSIST and is not live until the slate is drawn", () => {
    const state = fresh();
    expect(state.mode).toBe("ASSIST");
    expect(state.program.source).toBe("SLATE");
    expect(isLive(state)).toBe(false);
    const drawn = confirmDraw(state, { source: "SLATE", videoTrackSid: null }, 30);
    expect(isLive(drawn.state)).toBe(true);
    expect(drawn.ack).toBeNull();
  });
});

describe("operator take", () => {
  it("applies to a renderable camera but is live only after the first drawn frame", () => {
    const step = operatorTake(fresh(), "CAM-GUEST", allHealthy, 10);
    expect(step.state.program.source).toBe("CAM-GUEST");
    expect(step.state.program.streamEpoch).toBe(1);
    expect(isLive(step.state)).toBe(false);
    expect(step.state.pendingAck?.outcome).toBe("APPLIED");
    expect(step.ack).toBeNull();

    const drawn = confirmDraw(step.state, { source: "CAM-GUEST", videoTrackSid: "TR_CAM-GUEST" }, 55);
    expect(isLive(drawn.state)).toBe(true);
    expect(drawn.ack).toMatchObject({
      outcome: "APPLIED",
      renderedSource: "CAM-GUEST",
      renderedVideoTrackSid: "TR_CAM-GUEST",
      atMs: 55,
      rendererId: "renderer-test",
    });
    expect(drawn.state.acks[0]).toBe(drawn.ack);
  });

  it("rejects a stalled camera and leaves the programme alone", () => {
    const readiness = readinessWith({ "CAM-HOST": { renderable: true }, "CAM-GUEST": { renderable: false } });
    const before = liveOnHost();
    const step = operatorTake(before, "CAM-GUEST", readiness, 100);
    expect(step.ack?.outcome).toBe("REJECTED");
    expect(step.ack?.rejectReason).toBe("NOT_RENDERABLE");
    expect(step.state.program.source).toBe("CAM-HOST");
    expect(isLive(step.state)).toBe(true);
  });

  it("bumps the mode revision on every manual action, applied or rejected", () => {
    const start = fresh();
    const applied = operatorTake(start, "CAM-HOST", allHealthy, 1);
    expect(applied.state.modeRevision).toBe(start.modeRevision + 1);
    const rejected = operatorTake(applied.state, "CAM-HOST", allHealthy, 2);
    expect(rejected.ack?.rejectReason).toBe("ALREADY_ON_AIR");
    expect(rejected.state.modeRevision).toBe(start.modeRevision + 2);
    const held = operatorHold(rejected.state, 3);
    expect(held.state.modeRevision).toBe(start.modeRevision + 3);
    const resumed = operatorResume(held.state, "ASSIST", 4);
    expect(resumed.state.modeRevision).toBe(start.modeRevision + 4);
    const slated = operatorSlate(resumed.state, 5);
    expect(slated.state.modeRevision).toBe(start.modeRevision + 5);
    expect(slated.state.program.source).toBe("SLATE");
  });

  it("manual cuts ignore the minimum shot duration", () => {
    const state = liveOnHost();
    const step = operatorTake(state, "CAM-WIDE", allHealthy, 200);
    expect(step.state.program.source).toBe("CAM-WIDE");
  });

  it("supersedes an unconfirmed switch when the operator cuts again", () => {
    const first = operatorTake(fresh(), "CAM-HOST", allHealthy, 10);
    const second = operatorTake(first.state, "CAM-WIDE", allHealthy, 20);
    expect(second.state.program.source).toBe("CAM-WIDE");
    const superseded = second.state.acks.find((ack) => ack.rejectReason === "SUPERSEDED");
    expect(superseded?.decisionSequence).toBe(first.state.pendingAck?.decisionSequence);
  });
});

describe("policy decisions", () => {
  it("are parked as a suggestion in ASSIST and applied only when the operator accepts", () => {
    const state = liveOnHost();
    const step = evaluateDecision(state, policyDecision(state, "CAM-GUEST", 5000), allHealthy, 5000);
    expect(step.ack?.rejectReason).toBe("ASSIST_SUGGEST_ONLY");
    expect(step.state.suggestion?.target).toBe("CAM-GUEST");
    expect(step.state.program.source).toBe("CAM-HOST");

    const accepted = acceptSuggestion(step.state, allHealthy, 5100);
    expect(accepted.state.program.source).toBe("CAM-GUEST");
    expect(accepted.state.program.origin).toBe("OPERATOR");
    expect(accepted.state.suggestion).toBeNull();
  });

  it("execute in AUTO, subject to the minimum shot duration", () => {
    let { state } = operatorResume(liveOnHost(), "AUTO", 50);
    const early = evaluateDecision(state, policyDecision(state, "CAM-GUEST", 1000), allHealthy, 1000);
    expect(early.ack?.rejectReason).toBe("MIN_SHOT_DURATION");
    state = early.state;

    const later = evaluateDecision(state, policyDecision(state, "CAM-GUEST", MIN_SHOT_MS + 10), allHealthy, MIN_SHOT_MS + 10);
    expect(later.ack).toBeNull();
    expect(later.state.program.source).toBe("CAM-GUEST");
    expect(later.state.program.origin).toBe("POLICY");
  });

  it("are refused during MANUAL HOLD", () => {
    const { state } = operatorHold({ ...liveOnHost(), mode: "AUTO" }, 100);
    const step = evaluateDecision(state, policyDecision(state, "CAM-GUEST", 4000), allHealthy, 4000);
    expect(step.ack?.rejectReason).toBe("OPERATOR_HOLD");
    expect(step.state.program.source).toBe("CAM-HOST");
  });

  it("computed before an operator action are stale and ignored", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 50);
    const late = policyDecision(state, "CAM-GUEST", 3000);
    const { state: afterHold } = operatorHold(state, 3100);
    const { state: afterResume } = operatorResume(afterHold, "AUTO", 3200);
    const step = evaluateDecision(afterResume, late, allHealthy, 3300);
    expect(step.ack?.rejectReason).toBe("STALE_MODE_REVISION");
  });

  it("reject expired, duplicate, wrong-generation and wrong-event decisions", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 50);
    const expired = policyDecision(state, "CAM-GUEST", 4000, { expiresAtMs: 4500 });
    expect(evaluateDecision(state, expired, allHealthy, 5000).ack?.rejectReason).toBe("EXPIRED");

    const ok = policyDecision(state, "CAM-GUEST", 5000);
    const applied = evaluateDecision(state, ok, allHealthy, 5000);
    expect(applied.state.program.source).toBe("CAM-GUEST");
    const replay = evaluateDecision(applied.state, ok, allHealthy, 5001);
    expect(replay.ack?.rejectReason).toBe("DUPLICATE_OR_OUT_OF_ORDER");

    const wrongGeneration = policyDecision(applied.state, "CAM-WIDE", 9000, { controlGeneration: "gen-7" });
    expect(evaluateDecision(applied.state, wrongGeneration, allHealthy, 9000).ack?.rejectReason).toBe(
      "STALE_CONTROL_GENERATION",
    );

    const wrongEvent = policyDecision(applied.state, "CAM-WIDE", 9000, { eventId: "other" });
    expect(evaluateDecision(applied.state, wrongEvent, allHealthy, 9000).ack?.rejectReason).toBe("WRONG_EVENT");
  });

  it("reject backend-clock decisions until a clock mapping exists", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 50);
    const remote = policyDecision(state, "CAM-GUEST", 4000, { clockDomain: "backend", createdAtMs: 999000, expiresAtMs: 1002000 });
    expect(evaluateDecision(state, remote, allHealthy, 4000).ack?.rejectReason).toBe("TIMING_UNCERTAIN");

    const mapped = { ...state, backendClockOffsetMs: 4000 - 999000 };
    const step = evaluateDecision(mapped, { ...remote, sequence: remote.sequence + 1 }, allHealthy, 4000);
    expect(step.state.program.source).toBe("CAM-GUEST");
  });

  it("reject a target whose stream epoch moved on", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 50);
    const readiness = readinessWith({ "CAM-HOST": { renderable: true }, "CAM-GUEST": { renderable: true, epoch: 2 } });
    const step = evaluateDecision(state, policyDecision(state, "CAM-GUEST", 4000, { targetStreamEpoch: 1 }), readiness, 4000);
    expect(step.ack?.rejectReason).toBe("EPOCH_MISMATCH");
  });
});

describe("health failover", () => {
  function warm(state: SwitcherState, readiness: ReceiverReadiness, at: number): SwitcherState {
    return runHealthCheck(state, readiness, at).state;
  }

  it("fails over to the safety shot after sustained loss, even during HOLD, and acks on draw", () => {
    let state = liveOnHost();
    state = warm(state, allHealthy, 100);
    ({ state } = operatorHold(state, 200));

    const hostDead = readinessWith({ "CAM-HOST": { renderable: false }, "CAM-GUEST": { renderable: true }, "CAM-WIDE": { renderable: true } });
    const t0 = RECOVER_AFTER_MS + 500;
    state = warm(state, hostDead, t0);
    expect(state.program.source).toBe("CAM-HOST");
    state = warm(state, hostDead, t0 + FAILOVER_AFTER_MS - 100);
    expect(state.program.source).toBe("CAM-HOST");

    const step = runHealthCheck(state, hostDead, t0 + FAILOVER_AFTER_MS);
    expect(step.state.program.source).toBe("CAM-WIDE");
    expect(step.state.program.reason).toBe("FAILOVER_SAFE");
    expect(step.state.mode).toBe("MANUAL_HOLD");
    expect(step.log.join(" ")).toContain("unrenderable");

    const drawn = confirmDraw(step.state, { source: "CAM-WIDE", videoTrackSid: "TR_CAM-WIDE" }, t0 + FAILOVER_AFTER_MS + 30);
    expect(drawn.ack?.outcome).toBe("APPLIED");
    expect(drawn.ack?.renderedSource).toBe("CAM-WIDE");
  });

  it("goes to the slate when no safe source qualifies, then recovers after 2 s of health", () => {
    let state = warm(liveOnHost(), allHealthy, 100);
    const allDead = readinessWith({ "CAM-HOST": { renderable: false }, "CAM-GUEST": { renderable: false }, "CAM-WIDE": { renderable: false } });
    state = warm(state, allDead, 1000);
    state = warm(state, allDead, 1000 + FAILOVER_AFTER_MS);
    expect(state.program.source).toBe("SLATE");
    expect(state.program.reason).toBe("FAILOVER_SLATE");

    const wideBack = readinessWith({ "CAM-WIDE": { renderable: true } });
    state = warm(state, wideBack, 5000);
    expect(state.program.source).toBe("SLATE");
    state = warm(state, wideBack, 5000 + RECOVER_AFTER_MS - 1);
    expect(state.program.source).toBe("SLATE");
    state = warm(state, wideBack, 5000 + RECOVER_AFTER_MS);
    expect(state.program.source).toBe("CAM-WIDE");
    expect(state.program.reason).toBe("FAILOVER_RECOVER");
  });

  it("never leaves a slate the operator chose on purpose", () => {
    let state = warm(liveOnHost(), allHealthy, 100);
    ({ state } = operatorSlate(state, 200));
    state = warm(state, allHealthy, 10000);
    expect(state.program.source).toBe("SLATE");
  });

  it("does not pick a source that only just recovered", () => {
    let state = warm(liveOnHost(), readinessWith({ "CAM-HOST": { renderable: true } }), 100);
    const hostDeadWideNew = readinessWith({ "CAM-HOST": { renderable: false }, "CAM-WIDE": { renderable: true } });
    state = warm(state, hostDeadWideNew, 1000);
    state = warm(state, hostDeadWideNew, 1000 + FAILOVER_AFTER_MS);
    expect(state.program.source).toBe("SLATE");
  });

  it("follows a republish of the on-air camera without a decision", () => {
    let state = warm(liveOnHost(), allHealthy, 100);
    const republished = readinessWith({ "CAM-HOST": { renderable: true, epoch: 2, sid: "TR_new" }, "CAM-GUEST": { renderable: true }, "CAM-WIDE": { renderable: true } });
    const step = runHealthCheck(state, republished, 300);
    state = step.state;
    expect(state.program.source).toBe("CAM-HOST");
    expect(state.program.streamEpoch).toBe(2);
    expect(state.program.videoTrackSid).toBe("TR_new");
    expect(step.log.join(" ")).toContain("republished");
  });
});

describe("generations", () => {
  it("a new renderer generation returns to ASSIST and bumps the revision", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 10);
    const reset = resetForGeneration(state, 2);
    expect(reset.mode).toBe("ASSIST");
    expect(reset.rendererGeneration).toBe(2);
    expect(reset.modeRevision).toBe(state.modeRevision + 1);
    expect(reset.pendingAck).toBeNull();
  });

  it("local decisions never reuse a sequence the backend already consumed", () => {
    const { state } = operatorResume(liveOnHost(), "AUTO", 10);
    const remote = policyDecision(state, "CAM-GUEST", 4000, { sequence: 500, controlGeneration: "local" });
    const applied = evaluateDecision(state, remote, allHealthy, 4000);
    expect(applied.state.program.source).toBe("CAM-GUEST");
    const manual = operatorTake(applied.state, "CAM-WIDE", allHealthy, 4100);
    expect(manual.state.program.source).toBe("CAM-WIDE");
    expect(manual.state.pendingAck?.decisionSequence).toBeGreaterThan(500);
  });
});

describe("backend control sync", () => {
  it("adopts the backend's generation, mode and revision and drops pending work on a new generation", () => {
    const pending = operatorTake(fresh(), "CAM-HOST", allHealthy, 10);
    expect(pending.state.pendingAck).not.toBeNull();
    const synced = syncControlState(pending.state, { controlGeneration: "gen-a", mode: "AUTO", modeRevision: 9 }, 20);
    expect(synced.state.controlGeneration).toBe("gen-a");
    expect(synced.state.mode).toBe("AUTO");
    expect(synced.state.modeRevision).toBe(9);
    expect(synced.state.pendingAck).toBeNull();
    expect(synced.state.acks[0]?.rejectReason).toBe("STALE_CONTROL_GENERATION");
  });

  it("executes a backend policy command in AUTO once the clock is mapped", () => {
    let { state } = syncControlState(liveOnHost(), { controlGeneration: "gen-a", mode: "AUTO", modeRevision: 3 }, 50);
    state = { ...state, backendClockOffsetMs: -1_000_000 };
    const command = policyDecision(state, "CAM-GUEST", 5000, {
      controlGeneration: "gen-a",
      modeRevision: 3,
      issuerDecisionId: "dec-42",
      clockDomain: "backend",
      createdAtMs: 1_005_000,
      expiresAtMs: 1_009_000,
    });
    const step = evaluateDecision(state, command, allHealthy, 5000);
    expect(step.state.program.source).toBe("CAM-GUEST");
    const drawn = confirmDraw(step.state, { source: "CAM-GUEST", videoTrackSid: "TR_CAM-GUEST" }, 5040);
    expect(drawn.ack?.issuerDecisionId).toBe("dec-42");
    expect(drawn.ack?.controlGeneration).toBe("gen-a");
  });

  it("is a no-op when nothing changed", () => {
    const state = liveOnHost();
    expect(syncControlState(state, { controlGeneration: state.controlGeneration, mode: state.mode, modeRevision: state.modeRevision }, 1).state).toBe(state);
  });
});

describe("failed acknowledgement", () => {
  it("fails a switch that never drew and reverts to the previous source", () => {
    let state = runHealthCheck(liveOnHost(), allHealthy, 100).state;
    const step = operatorTake(state, "CAM-GUEST", allHealthy, 200);
    state = step.state;
    expect(state.pendingAck).not.toBeNull();

    expect(expirePendingAck(state, allHealthy, 200 + ACK_TIMEOUT_MS - 1).ack).toBeNull();
    const expired = expirePendingAck(state, allHealthy, 200 + ACK_TIMEOUT_MS);
    expect(expired.ack?.outcome).toBe("FAILED");
    expect(expired.ack?.rejectReason).toBe("ACK_TIMEOUT");
    expect(expired.state.program.source).toBe("CAM-HOST");
    expect(expired.state.program.reason).toBe("ACK_TIMEOUT_REVERT");
  });

  it("falls back to the slate when nothing else is renderable", () => {
    const step = operatorTake(fresh(), "CAM-GUEST", allHealthy, 200);
    const nothing = readinessWith({});
    const expired = expirePendingAck(step.state, nothing, 200 + ACK_TIMEOUT_MS);
    expect(expired.ack?.outcome).toBe("FAILED");
    expect(expired.state.program.source).toBe("SLATE");
  });
});

describe("stage 4 failure scenarios", () => {
  it("a HOLD applied locally before the backend answers rejects a policy command computed against the old revision", () => {
    // Backend and renderer agree on AUTO at revision 5; the backend issues a cut against revision 5.
    const { state: synced } = syncControlState(liveOnHost(), { controlGeneration: "gen-1", mode: "AUTO", modeRevision: 5 }, 100);
    const late = policyDecision(synced, "CAM-GUEST", 3000, { controlGeneration: "gen-1", modeRevision: 5 });
    // The operator presses HOLD; the compositor applies it at once, without waiting for the backend.
    const { state: holding } = operatorHold(synced, 3050);
    expect(holding.mode).toBe("MANUAL_HOLD");
    expect(holding.modeRevision).toBe(6);
    // The in-flight command lands afterwards and is refused; the shot does not change.
    const step = evaluateDecision(holding, late, allHealthy, 3060);
    expect(step.ack?.rejectReason).toBe("STALE_MODE_REVISION");
    expect(step.state.program.source).toBe("CAM-HOST");
    // The backend then confirms HOLD at revision 6: no change, nothing lost.
    const confirmed = syncControlState(step.state, { controlGeneration: "gen-1", mode: "MANUAL_HOLD", modeRevision: 6 }, 3100);
    expect(confirmed.state).toBe(step.state);
  });

  it("a backend snapshot adopted as ASSIST after a reconnect parks a policy command instead of cutting", () => {
    // The backend still says AUTO at revision 7, but the compositor adopts ASSIST (modeToAdopt) after the reconnect.
    const { state } = syncControlState(liveOnHost(), { controlGeneration: "gen-2", mode: "ASSIST", modeRevision: 7 }, 100);
    const command = policyDecision(state, "CAM-GUEST", 4000, { controlGeneration: "gen-2", modeRevision: 7 });
    const step = evaluateDecision(state, command, allHealthy, 4000);
    expect(step.ack?.rejectReason).toBe("ASSIST_SUGGEST_ONLY");
    expect(step.state.suggestion?.target).toBe("CAM-GUEST");
    expect(step.state.program.source).toBe("CAM-HOST");
  });
});
