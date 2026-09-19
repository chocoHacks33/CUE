/**
 * The TypeScript half of the observation fixture check.
 *
 * These are the same bytes `apps/api/tests/test_guest_contracts.py` validates.
 * The pipeline that emits them is Stage 2, but the vocabulary is frozen now, so
 * both runtimes have to agree on it before anyone writes against it.
 */
import { parseVisualObservation, supportsNamedTake } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import ambiguousFixture from "../../../../packages/contracts/fixtures/visual-observation.ambiguous.json";
import confirmedFixture from "../../../../packages/contracts/fixtures/visual-observation.confirmed.json";

const confirmed = parseVisualObservation(confirmedFixture);
const ambiguous = parseVisualObservation(ambiguousFixture);

describe("observation fixtures", () => {
  it("parses the confirmed observation the Python side also validates", () => {
    expect(confirmed.cameraId).toBe("CAM-GUEST");
    expect(confirmed.subject.guestId).toBe("guest-sarah");
    expect(confirmed.match?.calibrationStatus).toBe("PROVISIONAL_DEFAULT");
  });

  it("keeps the ambiguous observation anonymous and unusable", () => {
    expect(ambiguous.subject.guestId).toBeNull();
    expect(ambiguous.subject.displayName).toBeNull();
    expect(ambiguous.usableForNamedTake).toBe(false);
    expect(ambiguous.match?.calibratedConfidence).toBeNull();
  });
});

describe("named take gate", () => {
  it("accepts the confirmed fixture on its own epoch", () => {
    expect(
      supportsNamedTake(confirmed, confirmed.timing.observedAtMs, confirmed.streamEpoch),
    ).toBe(true);
  });

  it("refuses it once the identity has expired", () => {
    expect(supportsNamedTake(confirmed, confirmed.timing.expiresAtMs + 1, confirmed.streamEpoch)).toBe(
      false,
    );
  });

  it("refuses it on a superseded stream epoch", () => {
    expect(
      supportsNamedTake(confirmed, confirmed.timing.observedAtMs, confirmed.streamEpoch + 1),
    ).toBe(false);
  });

  it("refuses the ambiguous fixture", () => {
    expect(
      supportsNamedTake(ambiguous, ambiguous.timing.observedAtMs, ambiguous.streamEpoch),
    ).toBe(false);
  });
});
