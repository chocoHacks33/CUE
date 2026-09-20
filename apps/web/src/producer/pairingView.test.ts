import type { CameraBinding, ProducerPairingClaimResponse } from "@cue/contracts";
import { describe, expect, it } from "vitest";

import { bindingForCamera, claimIsLive, claimNeedsDecision, formatExpiry, sortClaims } from "./pairingView";

function claim(
  cameraId: ProducerPairingClaimResponse["camera"]["cameraId"],
  status: ProducerPairingClaimResponse["status"],
): ProducerPairingClaimResponse {
  const role = cameraId === "CAM-HOST" ? "HOST" : cameraId === "CAM-GUEST" ? "GUEST" : "WIDE";
  const owner = cameraId === "CAM-HOST" ? "A" : cameraId === "CAM-GUEST" ? "B" : "C";
  return {
    contractVersion: "0.1.0",
    claimId: `claim-${cameraId}-${status}`,
    verificationCode: "AMBER-42",
    camera: { cameraId, role, audioPolicy: cameraId === "CAM-HOST" ? "MASTER" : "DISABLED", owner },
    status,
    expiresInSeconds: 100,
    displayName: "Someone",
    deviceLabel: "A laptop",
  };
}

describe("pairing view helpers", () => {
  it("only pending claims need a decision", () => {
    expect(claimNeedsDecision("PENDING")).toBe(true);
    expect(claimNeedsDecision("APPROVED")).toBe(false);
    expect(claimNeedsDecision("EXCHANGED")).toBe(false);
  });

  it("treats exchanged, rejected and expired claims as finished", () => {
    expect(claimIsLive("PENDING")).toBe(true);
    expect(claimIsLive("ISSUING")).toBe(true);
    expect(claimIsLive("EXCHANGED")).toBe(false);
    expect(claimIsLive("REJECTED")).toBe(false);
    expect(claimIsLive("EXPIRED")).toBe(false);
  });

  it("puts pending claims first, then by camera ID", () => {
    const sorted = sortClaims([
      claim("CAM-WIDE", "EXCHANGED"),
      claim("CAM-WIDE", "PENDING"),
      claim("CAM-HOST", "PENDING"),
      claim("CAM-GUEST", "REJECTED"),
    ]);
    expect(sorted.map((c) => `${c.camera.cameraId}:${c.status}`)).toEqual([
      "CAM-HOST:PENDING",
      "CAM-WIDE:PENDING",
      "CAM-WIDE:EXCHANGED",
      "CAM-GUEST:REJECTED",
    ]);
  });

  it("finds the binding for a camera or returns null", () => {
    const binding: CameraBinding = {
      contractVersion: "0.1.0",
      eventId: "hackmit-demo",
      cameraId: "CAM-HOST",
      participantIdentity: "publisher:hackmit-demo:CAM-HOST",
      deviceSessionId: "dev-1",
      displayName: "Person A",
      currentVideoTrackSid: null,
      streamEpoch: 1,
      bindingRevision: 0,
    };
    expect(bindingForCamera([binding], "CAM-HOST")).toBe(binding);
    expect(bindingForCamera([binding], "CAM-GUEST")).toBeNull();
  });

  it("formats expiry for the operator", () => {
    expect(formatExpiry(0)).toBe("expired");
    expect(formatExpiry(45)).toBe("45 s");
    expect(formatExpiry(125)).toBe("2 min 5 s");
  });
});
