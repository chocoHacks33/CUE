import {
  isControlSnapshot,
  isReceiverReadiness,
  isRenderCommand,
  type CameraId,
  type ControlLatencyMetrics,
  type ControlMode,
  type ControlMutationResponse,
  type ControlRole,
  type ControlServerMessage,
  type ControlSessionResponse,
  type RenderAcknowledgement,
  type RenderReconciliation,
  type ReceiverReadiness,
} from "@cue/contracts";

type FetchLike = typeof fetch;

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: string | { code?: string; message?: string };
    };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail?.message) return body.detail.message;
  } catch {
    // Fall through to the status-only message.
  }
  return `Request failed (${response.status})`;
}

async function controlRequest<T>(
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
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

export function requestControlSession(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  role: ControlRole,
  fetchImpl?: FetchLike,
): Promise<ControlSessionResponse> {
  return controlRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/control-sessions`,
    { method: "POST", body: JSON.stringify({ role }) },
    fetchImpl,
  );
}

export function setControlMode(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  mode: ControlMode,
  expectedRevision: number,
  idempotencyKey: string,
  fetchImpl?: FetchLike,
): Promise<ControlMutationResponse> {
  return controlRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/mode`,
    {
      method: "POST",
      body: JSON.stringify({ mode, expectedRevision, idempotencyKey }),
    },
    fetchImpl,
  );
}

export function takeCamera(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  cameraId: CameraId,
  streamEpoch: number,
  expectedRevision: number,
  idempotencyKey: string,
  fetchImpl?: FetchLike,
): Promise<ControlMutationResponse> {
  return controlRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/take`,
    {
      method: "POST",
      body: JSON.stringify({ cameraId, streamEpoch, expectedRevision, idempotencyKey }),
    },
    fetchImpl,
  );
}

export function readControlMetrics(
  apiBaseUrl: string,
  producerSecret: string,
  eventId: string,
  fetchImpl?: FetchLike,
): Promise<ControlLatencyMetrics> {
  return controlRequest(
    apiBaseUrl,
    producerSecret,
    `/api/v1/events/${encodeURIComponent(eventId)}/control-metrics`,
    { method: "GET" },
    fetchImpl,
  );
}

export function controlSocketUrl(apiBaseUrl: string, eventId: string): string {
  const url = new URL(apiBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/api/v1/events/${encodeURIComponent(eventId)}/control`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

export function reconnectDelayMs(attempt: number): number {
  return Math.min(250 * 2 ** Math.max(0, attempt), 4_000);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function parseControlServerMessage(raw: string): ControlServerMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "control.state" && isControlSnapshot(value.state)) {
    return value as unknown as ControlServerMessage;
  }
  if (value.type === "render.command" && isRenderCommand(value.command)) {
    return value as unknown as ControlServerMessage;
  }
  if (value.type === "receiver.readiness" && isReceiverReadiness(value.readiness)) {
    return value as unknown as ControlServerMessage;
  }
  if (
    value.type === "control.authenticated" &&
    (value.role === "DIRECTOR" || value.role === "OBSERVER") &&
    typeof value.eventId === "string"
  ) {
    return value as unknown as ControlServerMessage;
  }
  if (value.type === "control.pong") return { type: "control.pong" };
  if (value.type === "control.error" && typeof value.code === "string") {
    return {
      type: "control.error",
      code: value.code,
      ...(typeof value.message === "string" ? { message: value.message } : {}),
    };
  }
  return null;
}

interface SocketLike {
  readonly readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

type SocketFactory = (url: string) => SocketLike;

export interface ControlSocketOptions {
  apiBaseUrl: string;
  eventId: string;
  token: string;
  onMessage: (message: ControlServerMessage) => void;
  onConnectionChange?: (connected: boolean) => void;
  socketFactory?: SocketFactory;
  schedule?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  cancelScheduled?: (handle: ReturnType<typeof setTimeout>) => void;
}

export class ControlSocketClient {
  private socket: SocketLike | null = null;
  private retryHandle: ReturnType<typeof setTimeout> | null = null;
  private retryAttempt = 0;
  private stopped = true;

  constructor(private readonly options: ControlSocketOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryHandle !== null) {
      (this.options.cancelScheduled ?? clearTimeout)(this.retryHandle);
      this.retryHandle = null;
    }
    this.socket?.close();
    this.socket = null;
    this.options.onConnectionChange?.(false);
  }

  acknowledge(acknowledgement: RenderAcknowledgement): void {
    this.send({ type: "render.ack", ack: acknowledgement });
  }

  reconcile(report: RenderReconciliation): void {
    this.send({ type: "render.reconcile", report });
  }

  reportReadiness(readiness: ReceiverReadiness): void {
    this.send({ type: "receiver.readiness", readiness });
  }

  ping(): void {
    this.send({ type: "control.ping" });
  }

  private send(payload: unknown): void {
    if (!this.socket || this.socket.readyState !== 1) {
      throw new Error("control socket is not connected");
    }
    this.socket.send(JSON.stringify(payload));
  }

  private connect(): void {
    const factory: SocketFactory =
      this.options.socketFactory ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    const socket = factory(controlSocketUrl(this.options.apiBaseUrl, this.options.eventId));
    this.socket = socket;
    socket.onopen = () => {
      socket.send(
        JSON.stringify({ type: "control.authenticate", token: this.options.token }),
      );
    };
    socket.onmessage = (event) => {
      const message = parseControlServerMessage(event.data);
      if (!message) return;
      if (message.type === "control.authenticated") {
        this.retryAttempt = 0;
        this.options.onConnectionChange?.(true);
      }
      this.options.onMessage(message);
    };
    socket.onerror = () => this.options.onConnectionChange?.(false);
    socket.onclose = () => {
      this.options.onConnectionChange?.(false);
      this.socket = null;
      if (this.stopped) return;
      const delay = reconnectDelayMs(this.retryAttempt++);
      this.retryHandle = (this.options.schedule ?? setTimeout)(() => {
        this.retryHandle = null;
        if (!this.stopped) this.connect();
      }, delay);
    };
  }
}
