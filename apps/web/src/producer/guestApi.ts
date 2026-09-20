import {
  type IdentityReadiness,
  type ObservationSnapshot,
  parseIdentityReadiness,
  parseObservationSnapshot,
} from "@cue/contracts";

/**
 * Operator-side reads of B's guest routes. The event is passed as `eventId`:
 * that is the FastAPI alias on B's routes, and `event_id` is a 422. The Stage 3
 * evidence poll had that wrong and was never exercised live; this module is
 * the one place the URL shape lives.
 */

type FetchLike = typeof fetch;

export type GuestResource = "observations" | "readiness";

export function guestQueryUrl(apiBaseUrl: string, resource: GuestResource, eventId: string): string {
  return `${apiBaseUrl.replace(/\/+$/, "")}/api/v1/guests/${resource}?eventId=${encodeURIComponent(eventId)}`;
}

function operatorHeaders(bootstrapSecret: string): Record<string, string> {
  return { "X-CUE-Bootstrap-Secret": bootstrapSecret, "ngrok-skip-browser-warning": "1" };
}

export async function fetchObservations(
  apiBaseUrl: string,
  bootstrapSecret: string,
  eventId: string,
  fetchImpl: FetchLike = fetch,
): Promise<ObservationSnapshot> {
  const response = await fetchImpl(guestQueryUrl(apiBaseUrl, "observations", eventId), {
    headers: operatorHeaders(bootstrapSecret),
  });
  if (!response.ok) throw new Error(`observations ${response.status}`);
  return parseObservationSnapshot(await response.json());
}

/** B's verdict on what identity may do, computed per request; never cache it. */
export async function fetchIdentityReadiness(
  apiBaseUrl: string,
  bootstrapSecret: string,
  eventId: string,
  fetchImpl: FetchLike = fetch,
): Promise<IdentityReadiness> {
  const response = await fetchImpl(guestQueryUrl(apiBaseUrl, "readiness", eventId), {
    headers: operatorHeaders(bootstrapSecret),
  });
  if (!response.ok) throw new Error(`readiness ${response.status}`);
  return parseIdentityReadiness(await response.json());
}
