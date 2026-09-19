import type {
  CameraId,
  EventEndReceipt,
  TransportMutationResponse,
} from "@cue/contracts";

type FetchLike = typeof fetch;

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

async function request<T>(
  apiBaseUrl: string,
  producerSecret: string,
  path: string,
  init: RequestInit,
  fetchImpl: FetchLike = fetch,
): Promise<T> {
  const response = await fetchImpl(`${normalizeBaseUrl(apiBaseUrl)}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-CUE-Producer-Secret": producerSecret,
      "ngrok-skip-browser-warning": "1",
      ...init.headers,
    },
  });
  if (!response.ok) throw new Error(`Transport request failed (${response.status})`);
  return (await response.json()) as T;
}

function mutateVideoTrack(
  action: "video-attached" | "video-detached",
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  cameraId: CameraId,
  participantIdentity: string,
  trackSid: string,
  fetchImpl?: FetchLike,
): Promise<TransportMutationResponse> {
  return request(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/transport/${action}`,
    {
      method: "POST",
      body: JSON.stringify({ cameraId, participantIdentity, trackSid }),
    },
    fetchImpl,
  );
}

export function attachVideoTrack(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  cameraId: CameraId,
  participantIdentity: string,
  trackSid: string,
  fetchImpl?: FetchLike,
): Promise<TransportMutationResponse> {
  return mutateVideoTrack(
    "video-attached",
    apiBaseUrl,
    producerSecret,
    eventId,
    cameraId,
    participantIdentity,
    trackSid,
    fetchImpl,
  );
}

export function detachVideoTrack(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  cameraId: CameraId,
  participantIdentity: string,
  trackSid: string,
  fetchImpl?: FetchLike,
): Promise<TransportMutationResponse> {
  return mutateVideoTrack(
    "video-detached",
    apiBaseUrl,
    producerSecret,
    eventId,
    cameraId,
    participantIdentity,
    trackSid,
    fetchImpl,
  );
}

export function endEvent(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  fetchImpl?: FetchLike,
): Promise<EventEndReceipt> {
  return request(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/end`,
    { method: "POST" },
    fetchImpl,
  );
}
