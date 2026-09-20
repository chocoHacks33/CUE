/**
 * Where the pages find the API. On a laptop next to the Mac this is
 * `http://localhost:8000`. On a phone the page arrives through one HTTPS
 * tunnel that also proxies `/api` and `/health` (see vite.config.ts), so the
 * API is the page's own origin. An explicit `VITE_API_BASE_URL` always wins.
 */
export function defaultApiBaseUrl(
  configured: string | undefined,
  location: { protocol: string; hostname: string; origin: string },
): string {
  if (configured && configured.trim()) return configured.trim();
  const host = location.hostname.toLowerCase();
  if (host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "") {
    return "http://localhost:8000";
  }
  return location.origin;
}
