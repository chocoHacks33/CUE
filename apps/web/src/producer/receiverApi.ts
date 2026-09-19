import type { ReceiverTokenRequest, ReceiverTokenResponse } from "@cue/contracts";

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

/** Ask the API on this Mac for a subscribe-only LiveKit credential. */
export async function requestReceiverToken(
  apiBaseUrl: string,
  bootstrapSecret: string,
  request: ReceiverTokenRequest,
  signal?: AbortSignal,
): Promise<ReceiverTokenResponse> {
  const response = await fetch(`${normalizeBaseUrl(apiBaseUrl)}/api/v1/stage0/receiver-token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CUE-Bootstrap-Secret": bootstrapSecret,
      // Free ngrok tunnels return an HTML interstitial to browser requests
      // unless this header is present. Harmless for every other endpoint.
      "ngrok-skip-browser-warning": "1",
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return (await response.json()) as ReceiverTokenResponse;
}
