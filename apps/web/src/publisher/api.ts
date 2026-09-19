import type {
  PairingClaimRequest,
  PairingClaimResponse,
  PairingExchangeResponse,
  PairingStatusRequest,
  PairingStatusResponse,
  PublisherTokenRequest,
  PublisherTokenResponse,
} from "@cue/contracts";

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

const TUNNEL_HEADER = { "ngrok-skip-browser-warning": "1" } as const;

async function postJson<T>(
  apiBaseUrl: string,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(apiBaseUrl)}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...TUNNEL_HEADER },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

export function claimPairing(
  apiBaseUrl: string,
  request: PairingClaimRequest,
  signal?: AbortSignal,
): Promise<PairingClaimResponse> {
  return postJson(apiBaseUrl, "/api/v1/pairing/claim", request, signal);
}

export function readPairingStatus(
  apiBaseUrl: string,
  request: PairingStatusRequest,
  signal?: AbortSignal,
): Promise<PairingStatusResponse> {
  return postJson(apiBaseUrl, "/api/v1/pairing/status", request, signal);
}

export function exchangePairing(
  apiBaseUrl: string,
  request: PairingStatusRequest,
  signal?: AbortSignal,
): Promise<PairingExchangeResponse> {
  return postJson(apiBaseUrl, "/api/v1/pairing/exchange", request, signal);
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function requestPublisherToken(
  apiBaseUrl: string,
  bootstrapSecret: string,
  request: PublisherTokenRequest,
  signal?: AbortSignal,
): Promise<PublisherTokenResponse> {
  const response = await fetch(
    `${normalizeBaseUrl(apiBaseUrl)}/api/v1/stage0/publisher-token`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CUE-Bootstrap-Secret": bootstrapSecret,
        // Free ngrok tunnels return an HTML interstitial to browser requests
        // unless this header is present. Harmless for every other endpoint.
        ...TUNNEL_HEADER,
      },
      body: JSON.stringify(request),
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return (await response.json()) as PublisherTokenResponse;
}
