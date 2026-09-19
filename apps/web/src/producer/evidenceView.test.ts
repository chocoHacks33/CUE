import type { CameraObservationView, VisualObservation } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import { describeEvidence, formatAgeMs } from "./evidenceView";

function observation(overrides: Partial<VisualObservation> = {}): VisualObservation {
  return {
    guestContractVersion: "0.1.0",
    observationId: "obs-1",
    eventId: "hackmit-demo",
    cameraId: "CAM-GUEST",
    streamEpoch: 1,
    trackKey: "t1",
    frameSequence: 10,
    status: "CONFIRMED",
    subject: { guestId: "guest-sarah", displayName: "Sarah Tan", referenceVersion: 1 },
    box: { x: 0.4, y: 0.2, width: 0.2, height: 0.3 },
    quality: { passed: true, score: 0.8, faceWidthRatio: 0.2, sharpness: 0.6, brightness: 0.5, detectorScore: 0.9, failedChecks: [] },
    match: { calibratedConfidence: null, calibrationId: "prov", calibrationStatus: "PROVISIONAL_DEFAULT", margin: 0.1, similarity: 0.5, runnerUpGuestId: null, consecutiveConfirmations: 3 },
    provenance: { pipelineVersion: "0.1", detector: "yunet", detectorVersion: "2023mar", embedder: "sface", embedderVersion: "2021dec", galleryVersion: 1 },
    timing: { capturedAtMs: null, observedAtMs: 1000, expiresAtMs: 2500, clockDomain: "BACKEND_WALL", clockUncertaintyMs: 20 },
    usableForNamedTake: true,
    ...overrides,
  };
}

function view(obs: VisualObservation | null, fresh = true, ageMs: number | null = 400): CameraObservationView {
  return { cameraId: "CAM-GUEST", observation: obs, fresh, ageMs };
}

describe("evidence lines", () => {
  it("names only a confirmed guest and says whether a named take is allowed", () => {
    const line = describeEvidence(view(observation()), 1200, 1);
    expect(line.headline).toBe("Sarah Tan: face match");
    expect(line.tone).toBe("confirmed");
    expect(line.namedTakeOk).toBe(true);
    expect(line.detail).toContain("400 ms ago");
    expect(line.detail).toContain("named take allowed");
    expect(line.detail).toContain("confidence unmeasured");
  });

  it("never shows a percentage", () => {
    const line = describeEvidence(view(observation()), 1200, 1);
    expect(line.headline + line.detail).not.toMatch(/%/);
  });

  it("refuses a named take when the evidence is stale or from another epoch", () => {
    expect(describeEvidence(view(observation(), false, 3000), 4000, 1).namedTakeOk).toBe(false);
    expect(describeEvidence(view(observation(), false, 3000), 4000, 1).tone).toBe("stale");
    const otherEpoch = describeEvidence(view(observation({ streamEpoch: 1 })), 1200, 2);
    expect(otherEpoch.namedTakeOk).toBe(false);
    expect(otherEpoch.detail).toContain("epoch 1, camera now 2");
  });

  it("describes ambiguous, unknown, low quality and no-face without a name", () => {
    expect(describeEvidence(view(observation({ status: "AMBIGUOUS", subject: { guestId: null, displayName: null, referenceVersion: null } })), 1200, 1).headline).toMatch(/ambiguous/);
    expect(describeEvidence(view(observation({ status: "UNKNOWN", subject: { guestId: null, displayName: null, referenceVersion: null } })), 1200, 1).headline).toMatch(/unknown face/);
    expect(describeEvidence(view(observation({ status: "LOW_QUALITY", subject: { guestId: null, displayName: null, referenceVersion: null } })), 1200, 1).headline).toMatch(/too small/);
    expect(describeEvidence(view(observation({ status: "NO_FACE", subject: { guestId: null, displayName: null, referenceVersion: null } })), 1200, 1).headline).toBe("no face in frame");
  });

  it("handles a missing observation", () => {
    expect(describeEvidence(null, 0, null).tone).toBe("none");
    expect(describeEvidence(view(null), 0, 1).headline).toBe("no observation");
  });

  it("formats ages", () => {
    expect(formatAgeMs(null)).toBe("age unknown");
    expect(formatAgeMs(420)).toBe("420 ms ago");
    expect(formatAgeMs(2600)).toBe("2.6 s ago");
  });
});
