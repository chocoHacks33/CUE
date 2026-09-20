import type { RenderAck, RenderCommand } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import {
  ackToAcknowledgement,
  backendClockOffsetMs,
  commandToDecision,
  idempotencyKey,
  originForReasonCode,
  reconciliationFor,
} from "./controlAdapter";

const command: RenderCommand = {
  decisionId: "dec-1",
  eventId: "hackmit-demo",
  controlGeneration: "gen-a",
  decisionSequence: 11,
  modeRevision: 5,
  target: "CAMERA",
  cameraId: "CAM-GUEST",
  streamEpoch: 3,
  reasonCode: "MANUAL_TAKE",
  createdAtMs: 1_700_000_000_000,
  expiresAtMs: 1_700_000_005_000,
};

describe("command adapter", () => {
  it("turns a backend camera command into a backend-clock decision", () => {
    const decision = commandToDecision(command);
    expect(decision).toMatchObject({
      sequence: 11,
      controlGeneration: "gen-a",
      issuerDecisionId: "dec-1",
      modeRevision: 5,
      origin: "OPERATOR",
      target: "CAM-GUEST",
      targetStreamEpoch: 3,
      reason: "MANUAL_TAKE",
      clockDomain: "backend",
      expiresAtMs: 1_700_000_005_000,
    });
  });

  it("maps a slate command and policy reason codes", () => {
    const slate = commandToDecision({ ...command, target: "SLATE", cameraId: null, streamEpoch: null, reasonCode: "POLICY_NO_HEALTHY_CAMERA" });
    expect(slate.target).toBe("SLATE");
    expect(slate.targetStreamEpoch).toBeNull();
    expect(slate.origin).toBe("POLICY");
    expect(originForReasonCode("FAILOVER_SAFE")).toBe("SAFETY");
    expect(originForReasonCode("FIXTURE_CONFIRMED_GUEST")).toBe("POLICY");
  });
});

describe("acknowledgement adapter", () => {
  const ack: RenderAck = {
    contractVersion: "0.1.0",
    eventId: "hackmit-demo",
    decisionSequence: 11,
    controlGeneration: "gen-a",
    issuerDecisionId: "dec-1",
    rendererId: "renderer-x",
    rendererGeneration: 2,
    outcome: "APPLIED",
    rejectReason: null,
    renderedSource: "CAM-GUEST",
    renderedStreamEpoch: 3,
    renderedVideoTrackSid: "TR_1",
    modeRevision: 5,
    clockDomain: "renderer-monotonic",
    atMs: 12_345,
  };

  it("converts renderer time back to wall time and reports the actual target", () => {
    const offset = backendClockOffsetMs(12_000, 1_700_000_000_000);
    const out = ackToAcknowledgement(ack, offset);
    expect(out).toEqual({
      decisionId: "dec-1",
      controlGeneration: "gen-a",
      decisionSequence: 11,
      status: "APPLIED",
      actualTarget: "CAMERA",
      actualCameraId: "CAM-GUEST",
      actualStreamEpoch: 3,
      appliedAtMs: 1_700_000_000_345,
      detail: null,
    });
  });

  it("carries the reject reason as detail and never acknowledges local decisions", () => {
    const rejected = ackToAcknowledgement({ ...ack, outcome: "REJECTED", rejectReason: "NOT_RENDERABLE", renderedSource: "SLATE" }, 0);
    expect(rejected?.status).toBe("REJECTED");
    expect(rejected?.detail).toBe("NOT_RENDERABLE");
    expect(rejected?.actualTarget).toBe("SLATE");
    expect(ackToAcknowledgement({ ...ack, issuerDecisionId: null }, 0)).toBeNull();
  });

  it("builds a reconciliation report from the programme", () => {
    expect(reconciliationFor({ source: "CAM-WIDE", streamEpoch: 2 }, "gen-a", 1000.6)).toEqual({
      controlGeneration: "gen-a",
      actualTarget: "CAMERA",
      actualCameraId: "CAM-WIDE",
      actualStreamEpoch: 2,
      reportedAtMs: 1001,
    });
    expect(reconciliationFor({ source: "SLATE", streamEpoch: null }, "gen-a", 5).actualTarget).toBe("SLATE");
  });

  it("produces idempotency keys the backend accepts", () => {
    const key = idempotencyKey("take", 1_700_000_000_000, "ab12");
    expect(key).toMatch(/^[A-Za-z0-9._:-]{8,96}$/);
    expect(idempotencyKey("m", 1, "")).toMatch(/^[A-Za-z0-9._:-]{8,96}$/);
  });
});
