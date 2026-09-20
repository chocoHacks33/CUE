import type { DecisionOrigin, ProgramSource } from "@cue/contracts";

/**
 * Stage 4 measurements (v3 plan section 9): cut latency and failover timing,
 * computed from the switcher's own acknowledgements. Pure; the panel collects
 * the samples and this module scores them. Renderer clock throughout.
 */

/** Plan section 9, manual switching: at least 30 cuts, p95 TAKE-to-render under 300 ms. */
export const CUT_GATE = { minCuts: 30, p95MaxMs: 300 } as const;
/** Plan section 9, failover: 10 deliberate failures, safe cut within 1.5 s of sustained loss detection. */
export const FAILOVER_GATE = { minTrials: 10, maxMs: 1500 } as const;

export interface CutSample {
  /** `${controlGeneration}.${decisionSequence}` of the applied decision. */
  key: string;
  origin: DecisionOrigin;
  source: ProgramSource;
  /** Local decisions are issued by the renderer; backend ones arrive as render commands. */
  via: "local" | "backend";
  /** When the operator pressed TAKE. Policy and safety cuts have no press; it equals decidedAtMs. */
  requestedAtMs: number;
  /** When the switcher accepted the decision. */
  decidedAtMs: number;
  /** When the first frame of the new source was drawn: the APPLIED acknowledgement. */
  drawnAtMs: number;
}

export interface FailoverSample {
  key: string;
  from: ProgramSource;
  target: ProgramSource;
  reason: string;
  /** When the on-air source was first reported unrenderable (the readiness stall is already past). */
  lossStartMs: number;
  /** When the switcher issued the safety cut, once the loss had lasted FAILOVER_AFTER_MS. */
  cutIssuedMs: number;
  /** Age of the failed source's last decoded frame at the cut, from readiness. */
  lastFrameAgeAtCutMs: number | null;
  /** When the safety picture was first drawn; null until acknowledged. */
  drawnAtMs: number | null;
}

export interface LatencyStats {
  count: number;
  p50: number | null;
  p95: number | null;
  max: number | null;
  mean: number | null;
}

export type GateStatus = "pass" | "fail" | "insufficient";

export interface GateResult {
  status: GateStatus;
  detail: string;
}

/** Nearest-rank percentile; p in [0, 100]. Null on an empty list. */
export function percentile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length);
  return sorted[Math.min(sorted.length, Math.max(1, rank)) - 1];
}

export function latencyStats(values: readonly number[]): LatencyStats {
  if (values.length === 0) return { count: 0, p50: null, p95: null, max: null, mean: null };
  const sum = values.reduce((total, value) => total + value, 0);
  return {
    count: values.length,
    p50: percentile(values, 50),
    p95: percentile(values, 95),
    max: Math.max(...values),
    mean: sum / values.length,
  };
}

export function pressToRenderMs(sample: CutSample): number {
  return sample.drawnAtMs - sample.requestedAtMs;
}

export function decisionToRenderMs(sample: CutSample): number {
  return sample.drawnAtMs - sample.decidedAtMs;
}

/** Manual switching gate over operator cuts only. Policy and safety cuts are reported, not counted. */
export function cutGate(
  samples: readonly CutSample[],
  gate: { minCuts: number; p95MaxMs: number } = CUT_GATE,
): GateResult & { stats: LatencyStats; decisionToRender: LatencyStats } {
  const operator = samples.filter((sample) => sample.origin === "OPERATOR");
  const stats = latencyStats(operator.map(pressToRenderMs));
  const decisionToRender = latencyStats(operator.map(decisionToRenderMs));
  if (stats.count < gate.minCuts) {
    return {
      status: "insufficient",
      detail: `${stats.count}/${gate.minCuts} operator cuts so far`,
      stats,
      decisionToRender,
    };
  }
  const p95 = stats.p95 ?? 0;
  if (p95 <= gate.p95MaxMs) {
    return {
      status: "pass",
      detail: `p95 ${Math.round(p95)} ms over ${stats.count} cuts (limit ${gate.p95MaxMs} ms)`,
      stats,
      decisionToRender,
    };
  }
  return {
    status: "fail",
    detail: `p95 ${Math.round(p95)} ms over ${stats.count} cuts exceeds ${gate.p95MaxMs} ms`,
    stats,
    decisionToRender,
  };
}

/**
 * Failover gate: loss detection to safe picture drawn. Trials that never drew are
 * counted separately; a failover that did not land is not a fast failover.
 */
export function failoverGate(
  samples: readonly FailoverSample[],
  gate: { minTrials: number; maxMs: number } = FAILOVER_GATE,
): GateResult & { stats: LatencyStats; fromLastFrame: LatencyStats; incomplete: number } {
  const complete = samples.filter(
    (sample): sample is FailoverSample & { drawnAtMs: number } => sample.drawnAtMs !== null,
  );
  const incomplete = samples.length - complete.length;
  const stats = latencyStats(complete.map((sample) => sample.drawnAtMs - sample.lossStartMs));
  const fromLastFrame = latencyStats(
    complete
      .filter((sample) => sample.lastFrameAgeAtCutMs !== null)
      .map((sample) => (sample.lastFrameAgeAtCutMs ?? 0) + (sample.drawnAtMs - sample.cutIssuedMs)),
  );
  if (stats.count < gate.minTrials) {
    return {
      status: "insufficient",
      detail: `${stats.count}/${gate.minTrials} completed failovers${incomplete ? `, ${incomplete} never drew` : ""}`,
      stats,
      fromLastFrame,
      incomplete,
    };
  }
  const max = stats.max ?? 0;
  if (incomplete === 0 && max <= gate.maxMs) {
    return {
      status: "pass",
      detail: `slowest ${Math.round(max)} ms over ${stats.count} failovers (limit ${gate.maxMs} ms)`,
      stats,
      fromLastFrame,
      incomplete,
    };
  }
  return {
    status: "fail",
    detail: incomplete
      ? `${incomplete} failover(s) never drew a safe picture`
      : `slowest ${Math.round(max)} ms over ${stats.count} failovers exceeds ${gate.maxMs} ms`,
    stats,
    fromLastFrame,
    incomplete,
  };
}
