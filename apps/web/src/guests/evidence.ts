/**
 * Person B's evidence semantics for the producer UI.
 *
 * D renders the panel; B decides what the evidence means. Keeping that decision
 * here stops the UI from inventing a friendlier reading of an abstention.
 */
import type { CameraObservationView, ObservationSnapshot } from "@cue/contracts";
import { supportsNamedTake } from "@cue/contracts";

export type EvidenceTone = "ready" | "provisional" | "abstained" | "stale" | "absent";

export interface EvidenceSummary {
  cameraId: string;
  tone: EvidenceTone;
  /** Short line for the camera tile. */
  headline: string;
  /** Why the system reached that verdict, in the operator's words. */
  reason: string;
  ageMs: number | null;
  /** True only when B will stand behind a named close-up right now. */
  namedTakeAllowed: boolean;
  /** Present only when a consenting guest has actually been confirmed. */
  guestName: string | null;
}

const NO_EVIDENCE: Omit<EvidenceSummary, "cameraId"> = {
  tone: "absent",
  headline: "No evidence",
  reason: "No observation has arrived for this camera on its current epoch.",
  ageMs: null,
  namedTakeAllowed: false,
  guestName: null,
};

export function summariseEvidence(
  view: CameraObservationView,
  nowMs: number,
  currentStreamEpoch: number,
): EvidenceSummary {
  const observation = view.observation;
  if (!observation) return { cameraId: view.cameraId, ...NO_EVIDENCE };

  const base = {
    cameraId: view.cameraId,
    ageMs: view.ageMs,
    guestName: null as string | null,
  };

  if (observation.streamEpoch !== currentStreamEpoch) {
    return {
      ...base,
      tone: "stale",
      headline: "Superseded",
      reason: `Evidence is from stream epoch ${observation.streamEpoch}; the camera is on ${currentStreamEpoch}.`,
      namedTakeAllowed: false,
    };
  }

  if (!view.fresh) {
    return {
      ...base,
      tone: "stale",
      headline: "Expired",
      reason: "The identity expired. A late observation does not become fresh by arriving late.",
      namedTakeAllowed: false,
    };
  }

  switch (observation.status) {
    case "CONFIRMED": {
      const allowed = supportsNamedTake(observation, nowMs, currentStreamEpoch);
      return {
        ...base,
        tone: allowed ? "ready" : "abstained",
        headline: allowed ? (observation.subject.displayName ?? "Confirmed") : "Held back",
        reason: allowed
          ? `Confirmed over ${observation.match?.consecutiveConfirmations ?? 0} consistent observations.`
          : "Confirmed, but a gate rejected it at read time.",
        namedTakeAllowed: allowed,
        guestName: allowed ? observation.subject.displayName : null,
      };
    }
    case "PROVISIONAL":
      return {
        ...base,
        tone: "provisional",
        headline: "Gathering evidence",
        reason: `${observation.match?.consecutiveConfirmations ?? 0} consistent observations so far; not enough to name anyone.`,
        namedTakeAllowed: false,
      };
    case "AMBIGUOUS":
      return {
        ...base,
        tone: "abstained",
        headline: "Two candidates",
        reason: "Two enrolled guests score too closely to be separated. The system abstains.",
        namedTakeAllowed: false,
      };
    case "UNKNOWN":
      return {
        ...base,
        tone: "abstained",
        headline: "Not an enrolled guest",
        reason: "A face was seen, but it matches nobody who consented to be identified.",
        namedTakeAllowed: false,
      };
    case "LOW_QUALITY":
      return {
        ...base,
        tone: "abstained",
        headline: "Cannot read this face",
        reason: `Quality gate failed: ${observation.quality.failedChecks.join(", ") || "unspecified"}.`,
        namedTakeAllowed: false,
      };
    case "NO_FACE":
      return {
        ...base,
        tone: "absent",
        headline: "No face in frame",
        reason: "The camera is decoding, but no face was detected.",
        namedTakeAllowed: false,
      };
  }
}

export function summariseSnapshot(
  snapshot: ObservationSnapshot,
  epochs: Readonly<Record<string, number>>,
): EvidenceSummary[] {
  return snapshot.cameras.map((view) =>
    summariseEvidence(view, snapshot.nowMs, epochs[view.cameraId] ?? view.observation?.streamEpoch ?? 0),
  );
}

/**
 * The calibration disclosure the results write-up and the demo both need.
 * A provisional anchor must never be presented as a measured accuracy.
 */
export function calibrationDisclosure(view: CameraObservationView): string | null {
  const status = view.observation?.match?.calibrationStatus;
  if (!status) return null;
  if (status === "MEASURED") return "Confidence from a measured calibration.";
  if (status === "PROVISIONAL_DEFAULT") {
    return "Confidence uses a provisional default mapping, not a measured calibration.";
  }
  return "No calibration: no confidence is claimed.";
}
