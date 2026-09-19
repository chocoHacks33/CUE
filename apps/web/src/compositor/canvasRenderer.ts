/**
 * Pure drawing helpers for the programme canvas (PRD section 11): fixed
 * 1280x720, hard cuts, aspect ratio preserved with letterbox or pillarbox,
 * never stretched, never mirrored.
 */

export const PROGRAM_WIDTH = 1280;
export const PROGRAM_HEIGHT = 720;

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Fit a source inside the destination, centred, preserving aspect ratio. */
export function fitContain(
  srcWidth: number,
  srcHeight: number,
  dstWidth = PROGRAM_WIDTH,
  dstHeight = PROGRAM_HEIGHT,
): Rect {
  if (srcWidth <= 0 || srcHeight <= 0) {
    return { x: 0, y: 0, width: dstWidth, height: dstHeight };
  }
  const scale = Math.min(dstWidth / srcWidth, dstHeight / srcHeight);
  const width = Math.round(srcWidth * scale);
  const height = Math.round(srcHeight * scale);
  return {
    x: Math.round((dstWidth - width) / 2),
    y: Math.round((dstHeight - height) / 2),
    width,
    height,
  };
}

export type DrawResult = "drawn" | "no-frame";

/** Draw the current frame of a video element. Returns "no-frame" if it has nothing decodable yet. */
export function drawVideoFrame(ctx: CanvasRenderingContext2D, video: HTMLVideoElement): DrawResult {
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height || video.readyState < 2) return "no-frame";
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, PROGRAM_WIDTH, PROGRAM_HEIGHT);
  const rect = fitContain(width, height);
  ctx.drawImage(video, rect.x, rect.y, rect.width, rect.height);
  return "drawn";
}

/** The safe picture when no camera is usable. Static, obviously not a camera. */
export function drawSlate(ctx: CanvasRenderingContext2D, lines: readonly string[]): void {
  ctx.fillStyle = "#05070d";
  ctx.fillRect(0, 0, PROGRAM_WIDTH, PROGRAM_HEIGHT);
  ctx.fillStyle = "#1b2238";
  ctx.fillRect(0, PROGRAM_HEIGHT / 2 - 2, PROGRAM_WIDTH, 4);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  lines.forEach((line, index) => {
    ctx.fillStyle = index === 0 ? "#f5f7ff" : "#8d95b3";
    ctx.font = index === 0 ? "700 56px system-ui, sans-serif" : "500 28px system-ui, sans-serif";
    ctx.fillText(line, PROGRAM_WIDTH / 2, PROGRAM_HEIGHT / 2 - 60 + index * 64);
  });
}

/** PRD section 11: background throttling and overload are monitored faults, not silent ones. */
export const DRAW_INTERVAL_BUDGET_MS = 250;

export function isThrottled(intervalMs: number, budgetMs = DRAW_INTERVAL_BUDGET_MS): boolean {
  return intervalMs > budgetMs;
}
