import { describe, expect, it } from "vitest";

import {
  isProgramSource,
  isRenderAck,
  isShotDecision,
  type RenderAck,
  type ShotDecision,
  SWITCHING_CONTRACT_VERSION,
} from "./switching";

const decision: ShotDecision = {
  contractVersion: SWITCHING_CONTRACT_VERSION,
  eventId: "hackmit-demo",
  sequence: 4,
  controlGeneration: 0,
  modeRevision: 3,
  origin: "OPERATOR",
  target: "CAM-GUEST",
  targetStreamEpoch: 1,
  reason: "MANUAL_TAKE",
  evidence: null,
  clockDomain: "renderer-monotonic",
  createdAtMs: 1000,
  expiresAtMs: 6000,
};

const ack: RenderAck = {
  contractVersion: SWITCHING_CONTRACT_VERSION,
  eventId: "hackmit-demo",
  decisionSequence: 4,
  controlGeneration: 0,
  rendererId: "renderer-1",
  rendererGeneration: 1,
  outcome: "APPLIED",
  rejectReason: null,
  renderedSource: "CAM-GUEST",
  renderedStreamEpoch: 1,
  renderedVideoTrackSid: "TR_1",
  modeRevision: 4,
  clockDomain: "renderer-monotonic",
  atMs: 1040,
};

describe("switching contracts", () => {
  it("recognises the three cameras and the slate as programme sources", () => {
    expect(isProgramSource("CAM-HOST")).toBe(true);
    expect(isProgramSource("SLATE")).toBe(true);
    expect(isProgramSource("CAM-4")).toBe(false);
    expect(isProgramSource(null)).toBe(false);
  });

  it("validates a shot decision", () => {
    expect(isShotDecision(decision)).toBe(true);
    expect(isShotDecision({ ...decision, target: "CAM-9" })).toBe(false);
    expect(isShotDecision({ ...decision, reason: "BECAUSE" })).toBe(false);
    expect(isShotDecision({ ...decision, origin: "MODEL" })).toBe(false);
    expect(isShotDecision({ ...decision, clockDomain: "wall" })).toBe(false);
    expect(isShotDecision({ ...decision, contractVersion: "9.9.9" })).toBe(false);
  });

  it("validates a render acknowledgement", () => {
    expect(isRenderAck(ack)).toBe(true);
    expect(isRenderAck({ ...ack, outcome: "MAYBE" })).toBe(false);
    expect(isRenderAck({ ...ack, rejectReason: "GUT_FEELING" })).toBe(false);
    expect(isRenderAck({ ...ack, renderedSource: "CAM-9" })).toBe(false);
    expect(isRenderAck({ ...ack, clockDomain: "backend" })).toBe(false);
  });
});
