import { describe, expect, it } from "vitest";

import { CAMERA_IDS } from "./index";
import { isReceiverReadiness, READINESS_CONTRACT_VERSION, type ReceiverReadiness } from "./readiness";

function sample(): ReceiverReadiness {
  return {
    contractVersion: READINESS_CONTRACT_VERSION,
    eventId: "hackmit-demo",
    rendererId: "renderer-1",
    rendererGeneration: 1,
    receiverIdentity: "receiver:hackmit-demo:director:abcd1234",
    connected: true,
    clockDomain: "renderer-monotonic",
    reportedAtMs: 12345.6,
    currentSource: null,
    masterAudio: { cameraId: "CAM-HOST", trackSid: null, attached: false, playbackAllowed: true },
    slots: CAMERA_IDS.map((cameraId) => ({
      cameraId,
      publisherIdentity: null,
      streamEpoch: null,
      videoTrackSid: null,
      audioTrackSid: null,
      decoded: false,
      renderable: false,
      lastFrameAgeMs: null,
      framesProgressing: false,
      frameCount: 0,
      width: 0,
      height: 0,
      state: "waiting" as const,
    })),
  };
}

describe("receiver readiness contract", () => {
  it("accepts a well-formed snapshot", () => {
    expect(isReceiverReadiness(sample())).toBe(true);
  });

  it("requires exactly three slots in camera order", () => {
    const short = { ...sample(), slots: sample().slots.slice(0, 2) };
    expect(isReceiverReadiness(short)).toBe(false);
    const reordered = { ...sample(), slots: [...sample().slots].reverse() };
    expect(isReceiverReadiness(reordered)).toBe(false);
  });

  it("rejects an unknown current source or clock domain", () => {
    expect(isReceiverReadiness({ ...sample(), currentSource: "CAM-4" })).toBe(false);
    expect(isReceiverReadiness({ ...sample(), clockDomain: "wall" })).toBe(false);
  });

  it("rejects a different contract version", () => {
    expect(isReceiverReadiness({ ...sample(), contractVersion: "0.0.1" })).toBe(false);
  });

  it("rejects non-objects", () => {
    expect(isReceiverReadiness(null)).toBe(false);
    expect(isReceiverReadiness([])).toBe(false);
    expect(isReceiverReadiness("{}")).toBe(false);
  });
});
