import { describe, expect, it } from "vitest";

import {
  IDENTITY_TTL_MS,
  parseGuestRecord,
  parseIdentityReadiness,
  parseVisualObservation,
  requiresOperatorConfirmation,
  supportsNamedTake,
  type VisualObservation,
} from "./guests";

const OBSERVED_AT = 1758294000185;

/**
 * Mirrors `packages/contracts/fixtures/visual-observation.confirmed.json`.
 * The fixture bytes themselves are parsed in
 * `apps/web/src/guests/guestContract.test.ts`; these cases exercise the rules.
 */
function confirmedObservation(): Record<string, unknown> {
  return {
    guestContractVersion: "0.1.0",
    observationId: "obs-cam-guest-3-4821",
    eventId: "hackmit-demo",
    cameraId: "CAM-GUEST",
    streamEpoch: 3,
    trackKey: "CAM-GUEST:3:face-7",
    frameSequence: 4821,
    status: "CONFIRMED",
    subject: { guestId: "guest-sarah", displayName: "Sarah", referenceVersion: 2 },
    box: { x: 0.41, y: 0.22, width: 0.17, height: 0.3 },
    quality: {
      passed: true,
      score: 0.82,
      faceWidthRatio: 0.17,
      sharpness: 0.71,
      brightness: 0.54,
      detectorScore: 0.93,
      failedChecks: [],
    },
    match: {
      calibratedConfidence: 0.94,
      calibrationId: "sface-cosine-provisional-v1",
      calibrationStatus: "PROVISIONAL_DEFAULT",
      margin: 0.21,
      similarity: 0.58,
      runnerUpGuestId: "guest-daniel",
      consecutiveConfirmations: 3,
    },
    provenance: {
      pipelineVersion: "cue-guests/0.1.0",
      detector: "opencv-yunet",
      detectorVersion: "2023mar",
      embedder: "opencv-sface",
      embedderVersion: "2021dec",
      galleryVersion: 7,
    },
    timing: {
      capturedAtMs: 1758294000120,
      observedAtMs: OBSERVED_AT,
      expiresAtMs: OBSERVED_AT + IDENTITY_TTL_MS,
      clockDomain: "WORKER_MONOTONIC_MAPPED",
      clockUncertaintyMs: 35,
    },
    usableForNamedTake: true,
  };
}

function activeGuest(): Record<string, unknown> {
  return {
    guestContractVersion: "0.1.0",
    guestId: "guest-sarah",
    eventId: "hackmit-demo",
    displayName: "Sarah",
    aliases: ["Sarah L"],
    status: "ACTIVE",
    consent: {
      granted: true,
      grantedAtMs: 1758293400000,
      scope: "EVENT",
      purposes: ["LIVE_IDENTIFICATION", "RECORDING", "CLOUD_RELAY"],
      withdrawnAtMs: null,
      recordedBy: "B",
    },
    referenceVersion: 2,
    referenceCount: 3,
    meanReferenceQuality: 0.79,
    storage: "MEMORY_ONLY",
    updatedAtMs: 1758293460000,
  };
}

function mutate(patch: (draft: Record<string, unknown>) => void): unknown {
  const draft = confirmedObservation();
  patch(draft);
  return draft;
}

const confirmed = parseVisualObservation(confirmedObservation());

describe("observation validation", () => {
  it("accepts a confirmed observation of a consenting guest", () => {
    expect(confirmed.subject.guestId).toBe("guest-sarah");
    expect(confirmed.timing.expiresAtMs - confirmed.timing.observedAtMs).toBe(IDENTITY_TTL_MS);
  });

  it("rejects a named guest on an unknown observation", () => {
    expect(() =>
      parseVisualObservation(
        mutate((draft) => {
          draft.status = "UNKNOWN";
          draft.usableForNamedTake = false;
        }),
      ),
    ).toThrow(/must not name a guest/);
  });

  it("rejects a named take that is not confirmed", () => {
    expect(() =>
      parseVisualObservation(mutate((draft) => (draft.status = "PROVISIONAL"))),
    ).toThrow(/Only a CONFIRMED observation/);
  });

  it("rejects a confidence reported without a calibration", () => {
    expect(() =>
      parseVisualObservation(
        mutate((draft) => {
          (draft.match as Record<string, unknown>).calibrationStatus = "UNCALIBRATED";
        }),
      ),
    ).toThrow(/uncalibrated match/);
  });

  it("rejects an expiry that precedes the observation", () => {
    expect(() =>
      parseVisualObservation(
        mutate((draft) => {
          const timing = draft.timing as Record<string, unknown>;
          timing.expiresAtMs = (timing.observedAtMs as number) - 1;
        }),
      ),
    ).toThrow(/cannot expire before/);
  });

  it("rejects a box outside the normalised range", () => {
    expect(() =>
      parseVisualObservation(
        mutate((draft) => {
          (draft.box as Record<string, unknown>).width = 1.4;
        }),
      ),
    ).toThrow(/normalised/);
  });

  it("rejects an unrecognised camera ID", () => {
    expect(() =>
      parseVisualObservation(mutate((draft) => (draft.cameraId = "CAM-EXTRA"))),
    ).toThrow(/Unknown camera ID/);
  });

  it("rejects a contract version it does not implement", () => {
    expect(() =>
      parseVisualObservation(mutate((draft) => (draft.guestContractVersion = "0.2.0"))),
    ).toThrow(/Unsupported guest contract version/);
  });
});

describe("named take gate", () => {
  const now = OBSERVED_AT + 100;

  it("accepts a fresh confirmed observation on the current epoch", () => {
    expect(supportsNamedTake(confirmed, now, confirmed.streamEpoch)).toBe(true);
  });

  it("refuses an expired identity", () => {
    expect(supportsNamedTake(confirmed, confirmed.timing.expiresAtMs + 1, 3)).toBe(false);
  });

  it("refuses evidence from a superseded stream epoch", () => {
    expect(supportsNamedTake(confirmed, now, confirmed.streamEpoch + 1)).toBe(false);
  });

  it("refuses a confirmed observation whose quality gate failed", () => {
    const degraded: VisualObservation = {
      ...confirmed,
      quality: { ...confirmed.quality, passed: false },
    };
    expect(supportsNamedTake(degraded, now, confirmed.streamEpoch)).toBe(false);
  });

  it("refuses an observation with no subject", () => {
    const anonymous: VisualObservation = {
      ...confirmed,
      subject: { guestId: null, displayName: null, referenceVersion: null },
    };
    expect(supportsNamedTake(anonymous, now, confirmed.streamEpoch)).toBe(false);
  });
});

describe("guest record validation", () => {
  it("parses a consenting active guest", () => {
    const guest = parseGuestRecord(activeGuest());
    expect(guest.status).toBe("ACTIVE");
    expect(guest.consent.scope).toBe("EVENT");
    expect(guest.storage).toBe("MEMORY_ONLY");
  });

  it("refuses a record that carries reference embeddings", () => {
    const draft = activeGuest();
    draft.embeddings = [[0.1, 0.2]];
    expect(() => parseGuestRecord(draft)).toThrow(/never carry reference embeddings/);
  });

  it("refuses a withdrawn guest that still claims consent", () => {
    const draft = activeGuest();
    draft.status = "WITHDRAWN";
    expect(() => parseGuestRecord(draft)).toThrow(/withdrawn guest/);
  });

  it("refuses consent that is not event-scoped", () => {
    const draft = activeGuest();
    (draft.consent as Record<string, unknown>).scope = "FOREVER";
    expect(() => parseGuestRecord(draft)).toThrow(/event-scoped/);
  });

  it("refuses a purpose outside the consent vocabulary", () => {
    const draft = activeGuest();
    (draft.consent as Record<string, unknown>).purposes = ["MARKETING"];
    expect(() => parseGuestRecord(draft)).toThrow(/Unknown consent purpose/);
  });
});

describe("identity readiness", () => {
  const readiness = {
    guestContractVersion: "0.1.0",
    eventId: "hackmit-demo",
    namingPolicy: "ROLE_BASED",
    roleBased: true,
    unattendedNamingPermitted: false,
    calibrationStatus: "PROVISIONAL_DEFAULT",
    disclosure:
      "Cameras are chosen by role, not by face recognition. Nothing on screen is identified by face.",
    blockingReasons: ["no identity report exists"],
    attestations: {},
  };

  const mutate = (change: (draft: Record<string, unknown>) => void) => {
    const draft = { ...readiness } as Record<string, unknown>;
    change(draft);
    return draft;
  };

  it("parses the role-based default the backend reports today", () => {
    const parsed = parseIdentityReadiness(readiness);

    expect(parsed.namingPolicy).toBe("ROLE_BASED");
    expect(parsed.roleBased).toBe(true);
    expect(parsed.unattendedNamingPermitted).toBe(false);
    expect(parsed.blockingReasons).toHaveLength(1);
  });

  it("parses a fully evidenced NAMED_AUTO", () => {
    const parsed = parseIdentityReadiness(
      mutate((draft) => {
        draft.namingPolicy = "NAMED_AUTO";
        draft.roleBased = false;
        draft.unattendedNamingPermitted = true;
        draft.calibrationStatus = "MEASURED";
        draft.blockingReasons = [];
        draft.attestations = { macRuntimeGate: "D — docs/results/b-media-check.md" };
      }),
    );

    expect(parsed.namingPolicy).toBe("NAMED_AUTO");
    expect(parsed.attestations.macRuntimeGate).toContain("b-media-check.md");
  });

  it("refuses a readiness with no disclosure, which could not be shown", () => {
    expect(() => parseIdentityReadiness(mutate((draft) => (draft.disclosure = "   ")))).toThrow(
      /disclosure/,
    );
  });

  it("refuses unattended naming outside NAMED_AUTO", () => {
    expect(() =>
      parseIdentityReadiness(mutate((draft) => (draft.unattendedNamingPermitted = true))),
    ).toThrow(/cannot permit unattended naming/);
  });

  it("refuses NAMED_AUTO that does not permit unattended naming", () => {
    expect(() =>
      parseIdentityReadiness(
        mutate((draft) => {
          draft.namingPolicy = "NAMED_AUTO";
          draft.roleBased = false;
        }),
      ),
    ).toThrow(/must permit unattended naming/);
  });

  it("refuses ROLE_BASED that does not set roleBased", () => {
    expect(() => parseIdentityReadiness(mutate((draft) => (draft.roleBased = false)))).toThrow(
      /must set roleBased/,
    );
  });

  it("rejects an unknown naming policy", () => {
    expect(() =>
      parseIdentityReadiness(mutate((draft) => (draft.namingPolicy = "PROBABLY_FINE"))),
    ).toThrow(/Unknown naming policy/);
  });

  it("rejects an attestation that names nobody", () => {
    expect(() =>
      parseIdentityReadiness(mutate((draft) => (draft.attestations = { macRuntimeGate: "  " }))),
    ).toThrow(/must name who attested/);
  });

  it("tells the UI when the operator has to confirm", () => {
    const assist = parseIdentityReadiness(
      mutate((draft) => {
        draft.namingPolicy = "NAMED_ASSIST";
        draft.roleBased = false;
      }),
    );

    expect(requiresOperatorConfirmation(assist)).toBe(true);
    expect(requiresOperatorConfirmation(parseIdentityReadiness(readiness))).toBe(false);
  });
});
