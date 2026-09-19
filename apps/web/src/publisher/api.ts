import type {
  PublisherTokenRequest,
  PublisherTokenResponse,
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
        "ngrok-skip-browser-warning": "1",
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
