import type {
  CameraBinding,
  CameraId,
  PairingGrantResponse,
  ProducerPairingClaimResponse,
} from "@cue/contracts";

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

async function producerRequest<T>(
  apiBaseUrl: string,
  producerSecret: string,
  path: string,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(apiBaseUrl)}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-CUE-Producer-Secret": producerSecret,
      "ngrok-skip-browser-warning": "1",
      ...init.headers,
    },
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

export function createPairingGrant(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  cameraId: CameraId,
): Promise<PairingGrantResponse> {
  return producerRequest(apiBaseUrl, producerSecret, `/api/v1/events/${eventId}/pairing`, {
    method: "POST",
    body: JSON.stringify({ cameraId }),
  });
}

export function listPairingClaims(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
): Promise<ProducerPairingClaimResponse[]> {
  return producerRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${eventId}/pairing-claims`,
    { method: "GET" },
  );
}

export function decidePairingClaim(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  claimId: string,
  approved: boolean,
): Promise<ProducerPairingClaimResponse> {
  return producerRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${eventId}/devices/${claimId}/approve`,
    { method: "POST", body: JSON.stringify({ approved }) },
  );
}

export function listCameraBindings(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
): Promise<CameraBinding[]> {
  return producerRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${eventId}/bindings`,
    { method: "GET" },
  );
}
