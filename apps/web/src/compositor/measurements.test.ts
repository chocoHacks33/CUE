import { describe, expect, it } from "vitest";

import {
  CUT_GATE,
  cutGate,
  type CutSample,
  FAILOVER_GATE,
  failoverGate,
  type FailoverSample,
  latencyStats,
  percentile,
} from "./measurements";

function cut(index: number, pressToRender: number, origin: CutSample["origin"] = "OPERATOR"): CutSample {
  const requestedAtMs = index * 5000;
  return {
    key: `local.${index}`,
    origin,
    source: "CAM-GUEST",
    via: "local",
    requestedAtMs,
    decidedAtMs: requestedAtMs + 2,
    drawnAtMs: requestedAtMs + pressToRender,
  };
}

function failover(index: number, lossToDrawn: number | null): FailoverSample {
  const lossStartMs = index * 10_000;
  return {
    key: `local.${100 + index}`,
    from: "CAM-GUEST",
    target: "CAM-WIDE",
    reason: "FAILOVER_SAFE",
    lossStartMs,
    cutIssuedMs: lossStartMs + 1500,
    lastFrameAgeAtCutMs: 2500,
    drawnAtMs: lossToDrawn === null ? null : lossStartMs + lossToDrawn,
  };
}

describe("percentiles", () => {
  it("uses nearest rank and copes with empty input", () => {
    expect(percentile([], 95)).toBeNull();
    expect(percentile([10], 95)).toBe(10);
    expect(percentile([5, 1, 3, 2, 4], 50)).toBe(3);
    expect(percentile([5, 1, 3, 2, 4], 95)).toBe(5);
    const twenty = Array.from({ length: 20 }, (_, i) => i + 1);
    expect(percentile(twenty, 95)).toBe(19);
  });

  it("summarises count, p50, p95, max and mean", () => {
    expect(latencyStats([])).toEqual({ count: 0, p50: null, p95: null, max: null, mean: null });
    expect(latencyStats([100, 200, 300, 400])).toEqual({ count: 4, p50: 200, p95: 400, max: 400, mean: 250 });
  });
});

describe("manual switching gate", () => {
  it("is insufficient until 30 operator cuts exist, and ignores policy and safety cuts", () => {
    const samples = [
      ...Array.from({ length: 29 }, (_, i) => cut(i, 120)),
      cut(40, 90, "POLICY"),
      cut(41, 90, "SAFETY"),
    ];
    const result = cutGate(samples);
    expect(result.status).toBe("insufficient");
    expect(result.stats.count).toBe(29);
    expect(result.detail).toBe(`29/${CUT_GATE.minCuts} operator cuts so far`);
  });

  it("passes when p95 press-to-render is within 300 ms", () => {
    const samples = Array.from({ length: 30 }, (_, i) => cut(i, 100 + i * 5));
    const result = cutGate(samples);
    expect(result.status).toBe("pass");
    expect(result.stats.p95).toBe(240);
    expect(result.decisionToRender.p95).toBe(238);
  });

  it("fails on a slow tail even when the median is fine", () => {
    const samples = Array.from({ length: 30 }, (_, i) => cut(i, i >= 28 ? 900 : 80));
    const result = cutGate(samples);
    expect(result.status).toBe("fail");
    expect(result.stats.p50).toBe(80);
    expect(result.detail).toContain("exceeds 300 ms");
  });
});

describe("failover gate", () => {
  it("needs ten completed trials and reports trials that never drew", () => {
    const samples = [...Array.from({ length: 9 }, (_, i) => failover(i, 1600)), failover(9, null)];
    const result = failoverGate(samples);
    expect(result.status).toBe("insufficient");
    expect(result.incomplete).toBe(1);
    expect(result.detail).toBe(`9/${FAILOVER_GATE.minTrials} completed failovers, 1 never drew`);
  });

  it("passes when every failover lands within the limit and reports time from the last frame", () => {
    const samples = Array.from({ length: 10 }, (_, i) => failover(i, 1400 + i * 5));
    const result = failoverGate(samples);
    expect(result.status).toBe("pass");
    expect(result.stats.max).toBe(1445);
    // last frame age at the cut (2500) plus cut-to-drawn (lossToDrawn - 1500).
    expect(result.fromLastFrame.max).toBe(2500 + (1445 - 1500));
  });

  it("fails on the slowest trial, not the average", () => {
    const samples = Array.from({ length: 10 }, (_, i) => failover(i, i === 3 ? 1800 : 1450));
    const result = failoverGate(samples);
    expect(result.status).toBe("fail");
    expect(result.detail).toContain("slowest 1800 ms");
  });

  it("fails when a trial never drew, even if the others were fast", () => {
    const samples = [...Array.from({ length: 10 }, (_, i) => failover(i, 1400)), failover(10, null)];
    expect(failoverGate(samples).status).toBe("fail");
  });
});
