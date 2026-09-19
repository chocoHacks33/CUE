/**
 * Pure helpers for the recorder. No DOM access so they can be unit-tested; the
 * component injects `MediaRecorder.isTypeSupported` at runtime.
 */

/** Ordered preference. PRD section 11: prefer a tested WebM/VP8/Opus combination on Chromium. */
export const RECORDING_MIME_CANDIDATES = [
  "video/webm;codecs=vp8,opus",
  "video/webm;codecs=vp9,opus",
  "video/webm",
  "video/mp4",
] as const;

export function pickRecordingMimeType(
  isTypeSupported: (type: string) => boolean,
  candidates: readonly string[] = RECORDING_MIME_CANDIDATES,
): string | null {
  for (const candidate of candidates) {
    if (isTypeSupported(candidate)) return candidate;
  }
  return null;
}

/** File extension for the container actually produced. Never rename a WebM to .mp4. */
export function extensionForMimeType(mimeType: string): "webm" | "mp4" | "bin" {
  const container = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";
  if (container === "video/webm" || container === "audio/webm") return "webm";
  if (container === "video/mp4" || container === "audio/mp4") return "mp4";
  return "bin";
}

function twoDigits(value: number): string {
  return value.toString().padStart(2, "0");
}

export function recordingFileName(label: string, mimeType: string, when: Date): string {
  const safeLabel = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "clip";
  const stamp =
    `${when.getFullYear()}${twoDigits(when.getMonth() + 1)}${twoDigits(when.getDate())}-` +
    `${twoDigits(when.getHours())}${twoDigits(when.getMinutes())}${twoDigits(when.getSeconds())}`;
  return `cue-${safeLabel}-${stamp}.${extensionForMimeType(mimeType)}`;
}

export function totalBytes(chunks: readonly { size: number }[]): number {
  return chunks.reduce((sum, chunk) => sum + chunk.size, 0);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  return `${twoDigits(Math.floor(totalSeconds / 60))}:${twoDigits(totalSeconds % 60)}`;
}
