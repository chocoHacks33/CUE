/**
 * The TypeScript half of the consent fixture check.
 *
 * `apps/api/tests/test_guest_contracts.py` validates the same bytes with
 * pydantic, and `apps/api/tests/test_guest_registry.py` checks that the rules
 * the schema cannot express are still enforced where it counts.
 */
import {
  mayEnrolFaceReference,
  parseGuestEnrolmentRequest,
  parseGuestRecord,
  parsePurgeReceipt,
  parseReferenceSubmission,
} from "@cue/contracts";
import { describe, expect, it } from "vitest";

import consentRefusedFixture from "../../../../packages/contracts/fixtures/guest-enrolment-request.consent-refused.json";
import enrolmentFixture from "../../../../packages/contracts/fixtures/guest-enrolment-request.json";
import recordingOnlyFixture from "../../../../packages/contracts/fixtures/guest-enrolment-request.recording-only.json";
import enrollingGuestFixture from "../../../../packages/contracts/fixtures/guest-record.enrolling.json";
import activeGuestFixture from "../../../../packages/contracts/fixtures/guest-record.json";
import withdrawnGuestFixture from "../../../../packages/contracts/fixtures/guest-record.withdrawn.json";
import purgeReceiptFixture from "../../../../packages/contracts/fixtures/purge-receipt.json";
import referenceFixture from "../../../../packages/contracts/fixtures/reference-submission.json";

describe("enrolment requests", () => {
  it("parses a fully consenting enrolment", () => {
    const request = parseGuestEnrolmentRequest(enrolmentFixture);

    expect(request.displayName).toBe("Sarah");
    expect(request.guestId).toBeNull();
    expect(mayEnrolFaceReference(request)).toBe(true);
  });

  it("parses a refused enrolment and still refuses to enrol it", () => {
    const request = parseGuestEnrolmentRequest(consentRefusedFixture);

    // Well-formed on purpose: the schema cannot express a consent decision.
    expect(request.consentGranted).toBe(false);
    expect(mayEnrolFaceReference(request)).toBe(false);
  });

  it("refuses to match a guest who consented only to being filmed", () => {
    const request = parseGuestEnrolmentRequest(recordingOnlyFixture);

    expect(request.consentGranted).toBe(true);
    expect(request.consentPurposes).not.toContain("LIVE_IDENTIFICATION");
    expect(mayEnrolFaceReference(request)).toBe(false);
  });

  it("rejects an enrolment with no recorded purpose at all", () => {
    expect(() =>
      parseGuestEnrolmentRequest({ ...enrolmentFixture, consentPurposes: [] }),
    ).toThrow(/at least one consent purpose/);
  });

  it("rejects a purpose outside the consent vocabulary", () => {
    expect(() =>
      parseGuestEnrolmentRequest({ ...enrolmentFixture, consentPurposes: ["MARKETING"] }),
    ).toThrow(/Unknown consent purpose/);
  });

  it("rejects an enrolment with no name to show", () => {
    expect(() =>
      parseGuestEnrolmentRequest({ ...enrolmentFixture, displayName: "   " }),
    ).toThrow(/needs a display name/);
  });
});

describe("guest lifecycle records", () => {
  it("parses a guest who has consented but has no references yet", () => {
    const guest = parseGuestRecord(enrollingGuestFixture);

    expect(guest.status).toBe("ENROLLING");
    expect(guest.referenceCount).toBe(0);
    expect(guest.meanReferenceQuality).toBeNull();
  });

  it("parses an active guest with references", () => {
    const guest = parseGuestRecord(activeGuestFixture);

    expect(guest.status).toBe("ACTIVE");
    expect(guest.referenceCount).toBe(3);
  });

  it("parses a withdrawn guest with consent dropped and references gone", () => {
    const guest = parseGuestRecord(withdrawnGuestFixture);

    expect(guest.status).toBe("WITHDRAWN");
    expect(guest.consent.granted).toBe(false);
    expect(guest.consent.withdrawnAtMs).not.toBeNull();
    expect(guest.referenceCount).toBe(0);
    expect(guest.referenceVersion).toBe(0);
  });

  it("refuses a withdrawn guest that kept its references", () => {
    expect(() =>
      parseGuestRecord({ ...withdrawnGuestFixture, referenceCount: 2 }),
    ).toThrow(/hold no references/);
  });

  it("never exposes an embedding through any lifecycle stage", () => {
    for (const fixture of [enrollingGuestFixture, activeGuestFixture, withdrawnGuestFixture]) {
      expect(Object.keys(fixture)).not.toContain("embeddings");
      expect(Object.keys(fixture)).not.toContain("references");
    }
  });
});

describe("reference submissions", () => {
  it("parses a 128-d reference that is not unit length", () => {
    const reference = parseReferenceSubmission(referenceFixture);

    expect(reference.embedding).toHaveLength(128);
    const norm = Math.hypot(...reference.embedding);
    // The server normalises; the fixture proves the client is not required to.
    expect(norm).toBeCloseTo(5, 10);
  });

  it("rejects an embedding with no magnitude", () => {
    expect(() =>
      parseReferenceSubmission({ ...referenceFixture, embedding: new Array(128).fill(0) }),
    ).toThrow(/no magnitude/);
  });

  it("rejects a non-finite embedding value", () => {
    const broken = [...referenceFixture.embedding];
    broken[0] = Number.NaN;
    expect(() => parseReferenceSubmission({ ...referenceFixture, embedding: broken })).toThrow(
      /non-finite/,
    );
  });

  it("rejects a quality outside 0..1", () => {
    expect(() => parseReferenceSubmission({ ...referenceFixture, quality: 1.4 })).toThrow(
      /quality must be 0..1/,
    );
  });

  it("carries no photo, only an embedding", () => {
    expect(Object.keys(referenceFixture)).not.toContain("image");
    expect(Object.keys(referenceFixture)).not.toContain("photo");
  });
});

describe("purge receipts", () => {
  it("reports what was actually deleted", () => {
    const receipt = parsePurgeReceipt(purgeReceiptFixture);

    expect(receipt.guestIds).toEqual(["guest-sarah"]);
    expect(receipt.referencesDeleted).toBe(3);
    expect(receipt.observationsDropped).toBe(1);
  });
});
