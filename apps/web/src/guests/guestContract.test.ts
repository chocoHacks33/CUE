/**
 * The TypeScript half of the shared fixture check.
 *
 * These are the same bytes `apps/api/tests/test_guest_contracts.py` validates.
 */
import { parseGuestRecord, parseVisualObservation, supportsNamedTake } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import ambiguousFixture from "../../../../packages/contracts/fixtures/visual-observation.ambiguous.json";
import confirmedFixture from "../../../../packages/contracts/fixtures/visual-observation.confirmed.json";
import guestFixture from "../../../../packages/contracts/fixtures/guest-record.json";

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
