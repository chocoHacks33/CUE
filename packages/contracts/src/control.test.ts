import { describe, expect, it } from "vitest";

import { commandIsCurrent, isControlSnapshot, isRenderCommand } from "./control";

const state = {
  eventId: "hackmit-demo",
  controlGeneration: "generation-1",
  mode: "ASSIST" as const,
  modeRevision: 4,
  decisionSequence: 10,
  liveCameraId: "CAM-HOST" as const,
  liveStreamEpoch: 2,
  pendingDecisionId: null,
};

const command = {
  decisionId: "decision-11",
  eventId: "hackmit-demo",
  controlGeneration: "generation-1",
  decisionSequence: 11,
  modeRevision: 4,
  cameraId: "CAM-GUEST" as const,
  streamEpoch: 3,
  reasonCode: "FIXTURE_TAKE",
  createdAtMs: 1_000,
  expiresAtMs: 3_000,
};

describe("Stage 2 control contracts", () => {
  it("accepts versioned state and render commands", () => {
    expect(isControlSnapshot(state)).toBe(true);
    expect(isRenderCommand(command)).toBe(true);
    expect(commandIsCurrent(command, state, 2_000)).toBe(true);
  });

  it("rejects an old generation, old revision and expired command", () => {
    expect(commandIsCurrent({ ...command, controlGeneration: "old" }, state, 2_000)).toBe(false);
    expect(commandIsCurrent({ ...command, modeRevision: 3 }, state, 2_000)).toBe(false);
    expect(commandIsCurrent(command, state, 3_001)).toBe(false);
  });

  it("rejects malformed or targetless state", () => {
    expect(isControlSnapshot({ ...state, liveCameraId: "CAM-UNKNOWN" })).toBe(false);
    expect(isRenderCommand({ ...command, expiresAtMs: command.createdAtMs })).toBe(false);
  });
});

