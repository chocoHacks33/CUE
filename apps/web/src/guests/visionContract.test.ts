/**
 * The TypeScript half of the shared fixture check.
 *
 * These are the same bytes `apps/api/tests/test_guest_contracts.py` and
 * `apps/vision/tests/test_observation_contract.py` validate.
 */
import { parseGuestRecord, parseVisualObservation, supportsNamedTake } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import ambiguousFixture from "../../../../packages/contracts/fixtures/visual-observation.ambiguous.json";
import confirmedFixture from "../../../../packages/contracts/fixtures/visual-observation.confirmed.json";
import guestFixture from "../../../../packages/contracts/fixtures/guest-record.json";

import { calibrationDisclosure, summariseEvidence } from "./evidence";

const confirmed = parseVisualObservation(confirmedFixture);
const ambiguous = parseVisualObservation(ambiguousFixture);

describe("shared fixtures", () => {
  it("parses the confirmed observation the Python side also validates", () => {
    expect(confirmed.cameraId).toBe("CAM-GUEST");
    expect(confirmed.subject.guestId).toBe("guest-sarah");
    expect(confirmed.match?.calibrationStatus).toBe("PROVISIONAL_DEFAULT");
  });

  it("keeps the ambiguous observation anonymous and unusable", () => {
    expect(ambiguous.subject.guestId).toBeNull();
    expect(ambiguous.usableForNamedTake).toBe(false);
    expect(ambiguous.match?.calibratedConfidence).toBeNull();
  });

  it("parses the guest record without ever seeing an embedding", () => {
    const guest = parseGuestRecord(guestFixture);
    expect(guest.storage).toBe("MEMORY_ONLY");
    expect(Object.keys(guest)).not.toContain("embeddings");
  });
});

describe("evidence summary for the producer UI", () => {
  const fresh = confirmed.timing.observedAtMs + 100;

  it("offers a name only when the gate actually passes", () => {
    const summary = summariseEvidence(
      { cameraId: "CAM-GUEST", observation: confirmed, fresh: true, ageMs: 100 },
      fresh,
      confirmed.streamEpoch,
    );

    expect(summary.tone).toBe("ready");
    expect(summary.namedTakeAllowed).toBe(true);
    expect(summary.guestName).toBe("Sarah");
  });

  it("never names anyone once the evidence has expired", () => {
    const summary = summariseEvidence(
      { cameraId: "CAM-GUEST", observation: confirmed, fresh: false, ageMs: 9000 },
      confirmed.timing.expiresAtMs + 9000,
      confirmed.streamEpoch,
    );

    expect(summary.tone).toBe("stale");
    expect(summary.guestName).toBeNull();
    expect(summary.namedTakeAllowed).toBe(false);
  });

  it("flags evidence from a superseded epoch", () => {
    const summary = summariseEvidence(
      { cameraId: "CAM-GUEST", observation: confirmed, fresh: true, ageMs: 40 },
      fresh,
      confirmed.streamEpoch + 1,
    );

    expect(summary.tone).toBe("stale");
    expect(summary.reason).toContain("epoch");
  });

  it("explains an abstention instead of hiding it", () => {
    const summary = summariseEvidence(
      { cameraId: "CAM-GUEST", observation: ambiguous, fresh: true, ageMs: 40 },
      ambiguous.timing.observedAtMs,
      ambiguous.streamEpoch,
    );

    expect(summary.tone).toBe("abstained");
    expect(summary.headline).toBe("Two candidates");
    expect(summary.namedTakeAllowed).toBe(false);
  });

  it("reports an empty camera as absent rather than negative evidence", () => {
    const summary = summariseEvidence(
      { cameraId: "CAM-WIDE", observation: null, fresh: false, ageMs: null },
      fresh,
      1,
    );

    expect(summary.tone).toBe("absent");
    expect(summary.namedTakeAllowed).toBe(false);
  });

  it("discloses that the confidence comes from a provisional mapping", () => {
    const disclosure = calibrationDisclosure({
      cameraId: "CAM-GUEST",
      observation: confirmed,
      fresh: true,
      ageMs: 40,
    });

    expect(disclosure).toContain("provisional");
  });
});

describe("named take gate agrees with the fixture", () => {
  it("accepts the confirmed fixture on its own epoch", () => {
    expect(
      supportsNamedTake(confirmed, confirmed.timing.observedAtMs, confirmed.streamEpoch),
    ).toBe(true);
  });

  it("refuses the ambiguous fixture", () => {
    expect(
      supportsNamedTake(ambiguous, ambiguous.timing.observedAtMs, ambiguous.streamEpoch),
    ).toBe(false);
  });
});
