import type { CameraBinding, CameraId, PairingClaimStatus, ProducerPairingClaimResponse } from "@cue/contracts";

/** Pure helpers for the producer's pairing panel. No fetch, no DOM. */

export function claimNeedsDecision(status: PairingClaimStatus): boolean {
  return status === "PENDING";
}

export function claimIsLive(status: PairingClaimStatus): boolean {
  return status === "PENDING" || status === "APPROVED" || status === "ISSUING";
}

/** Order claims so the ones waiting for the producer come first, then by camera. */
export function sortClaims(claims: readonly ProducerPairingClaimResponse[]): ProducerPairingClaimResponse[] {
  const rank: Record<PairingClaimStatus, number> = {
    PENDING: 0,
    APPROVED: 1,
    ISSUING: 1,
    EXCHANGED: 2,
    REJECTED: 3,
    EXPIRED: 4,
  };
  return [...claims].sort((a, b) => {
    const byRank = rank[a.status] - rank[b.status];
    if (byRank !== 0) return byRank;
    return a.camera.cameraId.localeCompare(b.camera.cameraId);
  });
}

export function bindingForCamera(
  bindings: readonly CameraBinding[],
  cameraId: CameraId,
): CameraBinding | null {
  return bindings.find((binding) => binding.cameraId === cameraId) ?? null;
}

export function formatExpiry(expiresInSeconds: number): string {
  if (expiresInSeconds <= 0) return "expired";
  if (expiresInSeconds < 60) return `${expiresInSeconds} s`;
  return `${Math.floor(expiresInSeconds / 60)} min ${expiresInSeconds % 60} s`;
}
