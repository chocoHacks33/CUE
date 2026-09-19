import type { CameraObservationView, VisualObservation } from "@cue/contracts";
import { supportsNamedTake } from "@cue/contracts";

/**
 * What the operator sees on a camera tile about who is in it (PRD section 12):
 * a name only for a confirmed, consenting guest, with the age and provenance of
 * that evidence, and never a probability percentage.
 */

export type EvidenceTone = "confirmed" | "provisional" | "ambiguous" | "unknown" | "none" | "stale";

export interface EvidenceLine {
  headline: string;
  detail: string;
  tone: EvidenceTone;
  /** B's gate plus freshness and epoch: may this tile support a named close-up right now? */
  namedTakeOk: boolean;
}

export function formatAgeMs(ms: number | null): string {
  if (ms === null) return "age unknown";
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms ago`;
  return `${(ms / 1000).toFixed(1)} s ago`;
}

function calibrationNote(observation: VisualObservation): string {
  const match = observation.match;
  if (!match) return "";
  if (match.calibrationStatus === "MEASURED" && match.calibratedConfidence !== null) {
    return " · calibrated";
  }
  return " · confidence unmeasured";
}

export function describeEvidence(
  view: CameraObservationView | null,
  nowMs: number,
  currentStreamEpoch: number | null,
): EvidenceLine {
  if (!view || !view.observation) {
    return { headline: "no observation", detail: "vision worker has not reported", tone: "none", namedTakeOk: false };
  }
  const observation = view.observation;
  const age = formatAgeMs(view.ageMs);
  const stale = !view.fresh;
  const epochMatches = currentStreamEpoch !== null && observation.streamEpoch === currentStreamEpoch;
  const namedTakeOk =
    !stale && epochMatches && supportsNamedTake(observation, nowMs, currentStreamEpoch ?? -1);

  const name = observation.subject.displayName;
  let headline: string;
  let tone: EvidenceTone;
  switch (observation.status) {
    case "CONFIRMED":
      headline = name ? `${name}: face match` : "confirmed match, name withheld";
      tone = "confirmed";
      break;
    case "PROVISIONAL":
      headline = name ? `${name}? provisional` : "provisional match";
      tone = "provisional";
      break;
    case "AMBIGUOUS":
      headline = "ambiguous: more than one possible match, no name";
      tone = "ambiguous";
      break;
    case "UNKNOWN":
      headline = "unknown face, not an enrolled guest";
      tone = "unknown";
      break;
    case "LOW_QUALITY":
      headline = "face too small or unclear to identify";
      tone = "unknown";
      break;
    case "NO_FACE":
      headline = "no face in frame";
      tone = "none";
      break;
    default:
      headline = String(observation.status);
      tone = "unknown";
  }

  const parts = [age];
  if (stale) parts.push("stale");
  if (!epochMatches && currentStreamEpoch !== null) parts.push(`epoch ${observation.streamEpoch}, camera now ${currentStreamEpoch}`);
  if (observation.status === "CONFIRMED" || observation.status === "PROVISIONAL") {
    parts.push(namedTakeOk ? "named take allowed" : "named take not allowed");
  }
  const detail = parts.join(" · ") + calibrationNote(observation);
  return { headline, detail, tone: stale ? "stale" : tone, namedTakeOk };
}
