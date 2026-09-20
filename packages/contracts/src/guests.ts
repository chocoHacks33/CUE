/**
 * Person B — guest consent, visual identity and observation contracts.
 *
 * B produces observations. B never produces camera commands: nothing in this
 * file describes a cut, a take or a programme source.
 */
import { type CameraId, isCameraId } from "./index";

export const GUEST_CONTRACT_VERSION = "0.1.0" as const;

/** Observation outcomes. Only CONFIRMED may support a named close-up. */
export const OBSERVATION_STATUSES = [
  "CONFIRMED",
  "PROVISIONAL",
  "AMBIGUOUS",
  "UNKNOWN",
  "LOW_QUALITY",
  "NO_FACE",
] as const;
export type ObservationStatus = (typeof OBSERVATION_STATUSES)[number];

/**
 * How the score to confidence mapping was obtained. A raw similarity is never a
 * calibrated confidence, and a provisional default is not a measured result.
 */
export const CALIBRATION_STATUSES = [
  "MEASURED",
  "PROVISIONAL_DEFAULT",
  "UNCALIBRATED",
] as const;
export type CalibrationStatus = (typeof CALIBRATION_STATUSES)[number];

/** Worker timestamps are mapped into the backend domain with stated uncertainty. */
export const CLOCK_DOMAINS = ["WORKER_MONOTONIC_MAPPED", "BACKEND_WALL"] as const;
export type ClockDomain = (typeof CLOCK_DOMAINS)[number];

export const GUEST_STATUSES = ["ENROLLING", "ACTIVE", "WITHDRAWN"] as const;
export type GuestStatus = (typeof GUEST_STATUSES)[number];

export const CONSENT_PURPOSES = [
  "LIVE_IDENTIFICATION",
  "RECORDING",
  "CLOUD_RELAY",
] as const;
export type ConsentPurpose = (typeof CONSENT_PURPOSES)[number];

/** PRD starting value. Measure and tune; this is not a proven outcome. */
export const IDENTITY_TTL_MS = 1500;

export interface NormalisedBox {
  /** Left edge as a fraction of frame width, 0..1. */
  x: number;
  /** Top edge as a fraction of frame height, 0..1. */
  y: number;
  width: number;
  height: number;
}

export interface ObservationQuality {
  passed: boolean;
  /** Aggregate 0..1 capture quality. Not an identity confidence. */
  score: number;
  faceWidthRatio: number;
  sharpness: number;
  brightness: number;
  detectorScore: number;
  failedChecks: string[];
}

export interface ObservationMatch {
  /** Null whenever no usable calibration exists. Never a raw similarity. */
  calibratedConfidence: number | null;
  calibrationId: string;
  calibrationStatus: CalibrationStatus;
  /** Best minus runner-up in raw score space. Diagnostic, not a probability. */
  margin: number | null;
  /** Raw cosine similarity. Diagnostic only; policy must not gate on it. */
  similarity: number | null;
  runnerUpGuestId: string | null;
  consecutiveConfirmations: number;
}

export interface ObservationSubject {
  /** Null for UNKNOWN, AMBIGUOUS, LOW_QUALITY and NO_FACE. */
  guestId: string | null;
  /** Only ever a consenting enrolled guest's name. Never a seat label. */
  displayName: string | null;
  referenceVersion: number | null;
}

export interface ObservationProvenance {
  pipelineVersion: string;
  detector: string;
  detectorVersion: string;
  embedder: string;
  embedderVersion: string;
  galleryVersion: number;
}

export interface ObservationTiming {
  /** Estimated capture time; null when the source gave no usable estimate. */
  capturedAtMs: number | null;
  observedAtMs: number;
  expiresAtMs: number;
  clockDomain: ClockDomain;
  clockUncertaintyMs: number;
}

export interface VisualObservation {
  guestContractVersion: typeof GUEST_CONTRACT_VERSION;
  observationId: string;
  eventId: string;
  cameraId: CameraId;
  /** Advances on re-publish, webcam change or ambiguous reconnect. */
  streamEpoch: number;
  /** Local track association inside one camera epoch. Not a LiveKit SID. */
  trackKey: string;
  frameSequence: number;
  status: ObservationStatus;
  subject: ObservationSubject;
  box: NormalisedBox | null;
  quality: ObservationQuality;
  match: ObservationMatch | null;
  provenance: ObservationProvenance;
  timing: ObservationTiming;
  /** B's own gate. The policy owner still applies its own gates on top. */
  usableForNamedTake: boolean;
}

export interface GuestConsent {
  granted: boolean;
  grantedAtMs: number;
  /** Consent is scoped to one event and is never carried into another. */
  scope: "EVENT";
  purposes: ConsentPurpose[];
  withdrawnAtMs: number | null;
  recordedBy: string;
}

/**
 * The public view of an enrolled guest. Reference embeddings are deliberately
 * absent: they never leave the Mac runtime through this shape.
 */
export interface GuestRecord {
  guestContractVersion: typeof GUEST_CONTRACT_VERSION;
  guestId: string;
  eventId: string;
  displayName: string;
  aliases: string[];
  status: GuestStatus;
  consent: GuestConsent;
  referenceVersion: number;
  referenceCount: number;
  meanReferenceQuality: number | null;
  storage: "MEMORY_ONLY";
  updatedAtMs: number;
}

export function isObservationStatus(value: unknown): value is ObservationStatus {
  return OBSERVATION_STATUSES.includes(value as ObservationStatus);
}

/** An identity assertion is only as good as its expiry. */
export function isIdentityFresh(observation: VisualObservation, nowMs: number): boolean {
  return nowMs <= observation.timing.expiresAtMs;
}

/**
 * The single question the directing policy asks B: may this observation support
 * a named close-up right now, on this camera epoch?
 */
export function supportsNamedTake(
  observation: VisualObservation,
  nowMs: number,
  currentStreamEpoch: number,
): boolean {
  return (
    observation.usableForNamedTake &&
    observation.status === "CONFIRMED" &&
    observation.subject.guestId !== null &&
    observation.quality.passed &&
    observation.streamEpoch === currentStreamEpoch &&
    isIdentityFresh(observation, nowMs)
  );
}

function asRecord(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function asNumber(source: Record<string, unknown>, key: string, path: string): number {
  const value = source[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path}.${key} must be a finite number`);
  }
  return value;
}

function asString(source: Record<string, unknown>, key: string, path: string): string {
  const value = source[key];
  if (typeof value !== "string") throw new Error(`${path}.${key} must be a string`);
  return value;
}

function asNullableNumber(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number | null {
  return source[key] === null ? null : asNumber(source, key, path);
}

function asNullableString(
  source: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  return source[key] === null ? null : asString(source, key, path);
}

function asStringArray(source: Record<string, unknown>, key: string, path: string): string[] {
  const value = source[key];
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new Error(`${path}.${key} must be an array of strings`);
  }
  return value as string[];
}

function parseBox(value: unknown): NormalisedBox | null {
  if (value === null) return null;
  const box = asRecord(value, "box");
  const parsed: NormalisedBox = {
    x: asNumber(box, "x", "box"),
    y: asNumber(box, "y", "box"),
    width: asNumber(box, "width", "box"),
    height: asNumber(box, "height", "box"),
  };
  for (const [key, entry] of Object.entries(parsed)) {
    if (entry < 0 || entry > 1) throw new Error(`box.${key} must be normalised to 0..1`);
  }
  return parsed;
}

/**
 * Runtime validation of the same fixtures the Python side validates. A shared
 * vocabulary is only shared once both runtimes reject the same bad payload.
 */
export function parseVisualObservation(value: unknown): VisualObservation {
  const root = asRecord(value, "observation");
  if (root.guestContractVersion !== GUEST_CONTRACT_VERSION) {
    throw new Error(`Unsupported guest contract version: ${String(root.guestContractVersion)}`);
  }

  const cameraId = asString(root, "cameraId", "observation");
  if (!isCameraId(cameraId)) throw new Error(`Unknown camera ID: ${cameraId}`);

  const status = root.status;
  if (!isObservationStatus(status)) throw new Error(`Unknown status: ${String(status)}`);

  const subject = asRecord(root.subject, "observation.subject");
  const quality = asRecord(root.quality, "observation.quality");
  const provenance = asRecord(root.provenance, "observation.provenance");
  const timing = asRecord(root.timing, "observation.timing");

  const guestId = asNullableString(subject, "guestId", "subject");
  if (guestId !== null && status !== "CONFIRMED" && status !== "PROVISIONAL") {
    throw new Error(`${status} observations must not name a guest`);
  }

  const rawMatch = root.match;
  let match: ObservationMatch | null = null;
  if (rawMatch !== null) {
    const source = asRecord(rawMatch, "observation.match");
    const calibrationStatus = asString(source, "calibrationStatus", "match");
    if (!CALIBRATION_STATUSES.includes(calibrationStatus as CalibrationStatus)) {
      throw new Error(`Unknown calibration status: ${calibrationStatus}`);
    }
    const calibratedConfidence = asNullableNumber(source, "calibratedConfidence", "match");
    if (calibrationStatus === "UNCALIBRATED" && calibratedConfidence !== null) {
      throw new Error("An uncalibrated match cannot report a calibrated confidence");
    }
    match = {
      calibratedConfidence,
      calibrationId: asString(source, "calibrationId", "match"),
      calibrationStatus: calibrationStatus as CalibrationStatus,
      margin: asNullableNumber(source, "margin", "match"),
      similarity: asNullableNumber(source, "similarity", "match"),
      runnerUpGuestId: asNullableString(source, "runnerUpGuestId", "match"),
      consecutiveConfirmations: asNumber(source, "consecutiveConfirmations", "match"),
    };
  }

  const clockDomain = asString(timing, "clockDomain", "timing");
  if (!CLOCK_DOMAINS.includes(clockDomain as ClockDomain)) {
    throw new Error(`Unknown clock domain: ${clockDomain}`);
  }

  const observedAtMs = asNumber(timing, "observedAtMs", "timing");
  const expiresAtMs = asNumber(timing, "expiresAtMs", "timing");
  if (expiresAtMs < observedAtMs) {
    throw new Error("An observation cannot expire before it was observed");
  }

  const usableForNamedTake = root.usableForNamedTake;
  if (typeof usableForNamedTake !== "boolean") {
    throw new Error("observation.usableForNamedTake must be a boolean");
  }
  if (usableForNamedTake && status !== "CONFIRMED") {
    throw new Error("Only a CONFIRMED observation may support a named take");
  }

  const passed = quality.passed;
  if (typeof passed !== "boolean") throw new Error("quality.passed must be a boolean");

  return {
    guestContractVersion: GUEST_CONTRACT_VERSION,
    observationId: asString(root, "observationId", "observation"),
    eventId: asString(root, "eventId", "observation"),
    cameraId,
    streamEpoch: asNumber(root, "streamEpoch", "observation"),
    trackKey: asString(root, "trackKey", "observation"),
    frameSequence: asNumber(root, "frameSequence", "observation"),
    status,
    subject: {
      guestId,
      displayName: asNullableString(subject, "displayName", "subject"),
      referenceVersion: asNullableNumber(subject, "referenceVersion", "subject"),
    },
    box: parseBox(root.box),
    quality: {
      passed,
      score: asNumber(quality, "score", "quality"),
      faceWidthRatio: asNumber(quality, "faceWidthRatio", "quality"),
      sharpness: asNumber(quality, "sharpness", "quality"),
      brightness: asNumber(quality, "brightness", "quality"),
      detectorScore: asNumber(quality, "detectorScore", "quality"),
      failedChecks: asStringArray(quality, "failedChecks", "quality"),
    },
    match,
    provenance: {
      pipelineVersion: asString(provenance, "pipelineVersion", "provenance"),
      detector: asString(provenance, "detector", "provenance"),
      detectorVersion: asString(provenance, "detectorVersion", "provenance"),
      embedder: asString(provenance, "embedder", "provenance"),
      embedderVersion: asString(provenance, "embedderVersion", "provenance"),
      galleryVersion: asNumber(provenance, "galleryVersion", "provenance"),
    },
    timing: {
      capturedAtMs: asNullableNumber(timing, "capturedAtMs", "timing"),
      observedAtMs,
      expiresAtMs,
      clockDomain: clockDomain as ClockDomain,
      clockUncertaintyMs: asNumber(timing, "clockUncertaintyMs", "timing"),
    },
    usableForNamedTake,
  };
}

export function parseGuestRecord(value: unknown): GuestRecord {
  const root = asRecord(value, "guest");
  if (root.guestContractVersion !== GUEST_CONTRACT_VERSION) {
    throw new Error(`Unsupported guest contract version: ${String(root.guestContractVersion)}`);
  }
  if ("references" in root || "embedding" in root || "embeddings" in root) {
    throw new Error("A guest record must never carry reference embeddings");
  }

  const status = asString(root, "status", "guest");
  if (!GUEST_STATUSES.includes(status as GuestStatus)) {
    throw new Error(`Unknown guest status: ${status}`);
  }

  const consent = asRecord(root.consent, "guest.consent");
  if (consent.scope !== "EVENT") throw new Error("Consent must be event-scoped");
  const granted = consent.granted;
  if (typeof granted !== "boolean") throw new Error("consent.granted must be a boolean");
  const withdrawnAtMs = asNullableNumber(consent, "withdrawnAtMs", "consent");
  const referenceCount = asNumber(root, "referenceCount", "guest");
  if (status === "WITHDRAWN") {
    if (granted || withdrawnAtMs === null) {
      throw new Error("A withdrawn guest must record the withdrawal and drop consent");
    }
    // Withdrawal is a deletion, not a flag. A record that still counts
    // references is describing data the guest asked us to destroy.
    if (referenceCount !== 0) {
      throw new Error("A withdrawn guest must hold no references");
    }
  }

  const purposes = asStringArray(consent, "purposes", "consent");
  for (const purpose of purposes) {
    if (!CONSENT_PURPOSES.includes(purpose as ConsentPurpose)) {
      throw new Error(`Unknown consent purpose: ${purpose}`);
    }
  }

  if (root.storage !== "MEMORY_ONLY") {
    throw new Error("Stage 1 keeps references in memory only");
  }

  return {
    guestContractVersion: GUEST_CONTRACT_VERSION,
    guestId: asString(root, "guestId", "guest"),
    eventId: asString(root, "eventId", "guest"),
    displayName: asString(root, "displayName", "guest"),
    aliases: asStringArray(root, "aliases", "guest"),
    status: status as GuestStatus,
    consent: {
      granted,
      grantedAtMs: asNumber(consent, "grantedAtMs", "consent"),
      scope: "EVENT",
      purposes: purposes as ConsentPurpose[],
      withdrawnAtMs,
      recordedBy: asString(consent, "recordedBy", "consent"),
    },
    referenceVersion: asNumber(root, "referenceVersion", "guest"),
    referenceCount,
    meanReferenceQuality: asNullableNumber(root, "meanReferenceQuality", "guest"),
    storage: "MEMORY_ONLY",
    updatedAtMs: asNumber(root, "updatedAtMs", "guest"),
  };
}

export interface CameraObservationView {
  cameraId: CameraId;
  observation: VisualObservation | null;
  /** Computed by the backend against its own clock at read time. */
  fresh: boolean;
  ageMs: number | null;
}

export interface ObservationSnapshot {
  guestContractVersion: typeof GUEST_CONTRACT_VERSION;
  eventId: string;
  nowMs: number;
  galleryVersion: number;
  cameras: CameraObservationView[];
}

export function parseObservationSnapshot(value: unknown): ObservationSnapshot {
  const root = asRecord(value, "snapshot");
  if (root.guestContractVersion !== GUEST_CONTRACT_VERSION) {
    throw new Error(`Unsupported guest contract version: ${String(root.guestContractVersion)}`);
  }

  const cameras = root.cameras;
  if (!Array.isArray(cameras)) throw new Error("snapshot.cameras must be an array");

  return {
    guestContractVersion: GUEST_CONTRACT_VERSION,
    eventId: asString(root, "eventId", "snapshot"),
    nowMs: asNumber(root, "nowMs", "snapshot"),
    galleryVersion: asNumber(root, "galleryVersion", "snapshot"),
    cameras: cameras.map((entry) => {
      const view = asRecord(entry, "snapshot.cameras[]");
      const cameraId = asString(view, "cameraId", "cameras[]");
      if (!isCameraId(cameraId)) throw new Error(`Unknown camera ID: ${cameraId}`);
      const fresh = view.fresh;
      if (typeof fresh !== "boolean") throw new Error("cameras[].fresh must be a boolean");
      return {
        cameraId,
        observation:
          view.observation === null || view.observation === undefined
            ? null
            : parseVisualObservation(view.observation),
        fresh,
        ageMs: asNullableNumber(view, "ageMs", "cameras[]"),
      };
    }),
  };
}

/**
 * What an enrolment operator sends. Consent is recorded in the same request
 * that creates the guest, so there is no window in which a guest exists without
 * a recorded decision.
 */
export interface GuestEnrolmentRequest {
  eventId: string;
  displayName: string;
  aliases: string[];
  /** Null lets the server derive a stable ID from the display name. */
  guestId: string | null;
  consentGranted: boolean;
  consentPurposes: ConsentPurpose[];
  recordedBy: string;
}

/**
 * One enrolment reference, already reduced to an embedding by the machine that
 * holds the photo. The photo itself is never uploaded.
 */
export interface ReferenceSubmission {
  eventId: string;
  embedding: number[];
  quality: number;
  embedder: string;
  embedderVersion: string;
  capturedAtMs: number;
}

/** Deletion has to be observable, or it is only a promise. */
export interface PurgeReceipt {
  eventId: string;
  guestIds: string[];
  referencesDeleted: number;
  observationsDropped: number;
  purgedAtMs: number;
}

/**
 * True only when this request may actually enrol a face reference.
 *
 * The schema cannot express this: a request that refuses consent, or that
 * consents to filming but not to being matched, is still a well-formed request.
 * It is a consent decision, so it lives beside the contract rather than inside
 * it, and the registry enforces the same rule server-side.
 */
export function mayEnrolFaceReference(request: GuestEnrolmentRequest): boolean {
  return request.consentGranted && request.consentPurposes.includes("LIVE_IDENTIFICATION");
}

export function parseGuestEnrolmentRequest(value: unknown): GuestEnrolmentRequest {
  const root = asRecord(value, "enrolment");

  const consentGranted = root.consentGranted;
  if (typeof consentGranted !== "boolean") {
    throw new Error("enrolment.consentGranted must be a boolean");
  }

  const purposes = asStringArray(root, "consentPurposes", "enrolment");
  if (purposes.length === 0) {
    throw new Error("An enrolment must record at least one consent purpose");
  }
  for (const purpose of purposes) {
    if (!CONSENT_PURPOSES.includes(purpose as ConsentPurpose)) {
      throw new Error(`Unknown consent purpose: ${purpose}`);
    }
  }

  const displayName = asString(root, "displayName", "enrolment");
  if (displayName.trim() === "") {
    throw new Error("An enrolment needs a display name");
  }

  return {
    eventId: asString(root, "eventId", "enrolment"),
    displayName,
    aliases: asStringArray(root, "aliases", "enrolment"),
    guestId: asNullableString(root, "guestId", "enrolment"),
    consentGranted,
    consentPurposes: purposes as ConsentPurpose[],
    recordedBy: asString(root, "recordedBy", "enrolment"),
  };
}

export function parseReferenceSubmission(value: unknown): ReferenceSubmission {
  const root = asRecord(value, "reference");

  const embedding = root.embedding;
  if (!Array.isArray(embedding) || embedding.length < 2) {
    throw new Error("reference.embedding must be an array of at least two numbers");
  }
  for (const entry of embedding) {
    if (typeof entry !== "number" || !Number.isFinite(entry)) {
      throw new Error("reference.embedding contains a non-finite value");
    }
  }
  if (embedding.every((entry) => entry === 0)) {
    throw new Error("An embedding with no magnitude cannot be matched");
  }

  const quality = asNumber(root, "quality", "reference");
  if (quality < 0 || quality > 1) throw new Error("reference.quality must be 0..1");

  return {
    eventId: asString(root, "eventId", "reference"),
    embedding: embedding as number[],
    quality,
    embedder: asString(root, "embedder", "reference"),
    embedderVersion: asString(root, "embedderVersion", "reference"),
    capturedAtMs: asNumber(root, "capturedAtMs", "reference"),
  };
}

export function parsePurgeReceipt(value: unknown): PurgeReceipt {
  const root = asRecord(value, "receipt");
  return {
    eventId: asString(root, "eventId", "receipt"),
    guestIds: asStringArray(root, "guestIds", "receipt"),
    referencesDeleted: asNumber(root, "referencesDeleted", "receipt"),
    observationsDropped: asNumber(root, "observationsDropped", "receipt"),
    purgedAtMs: asNumber(root, "purgedAtMs", "receipt"),
  };
}

// ---------------------------------------------------------------------------
// Identity readiness. Stage 4's exit gate, as the producer UI sees it.
//
// The rule this encodes: whenever a name on screen came from a face, the
// disclosure has to be visible. There is no state in which identity is used and
// nothing is said about it, so `disclosure` is never empty.
// ---------------------------------------------------------------------------

export const NAMING_POLICIES = ["NAMED_AUTO", "NAMED_ASSIST", "ROLE_BASED"] as const;
export type NamingPolicy = (typeof NAMING_POLICIES)[number];

export interface IdentityReadiness {
  guestContractVersion: typeof GUEST_CONTRACT_VERSION;
  eventId: string;
  namingPolicy: NamingPolicy;
  /** Pass to the director: true means names come from the roster, not from faces. */
  roleBased: boolean;
  /** False means an operator must confirm every named shot before it airs. */
  unattendedNamingPermitted: boolean;
  calibrationStatus: CalibrationStatus;
  /** Show this whenever identity is in play. Never empty. */
  disclosure: string;
  /** Why the policy is not more permissive. Empty only for NAMED_AUTO. */
  blockingReasons: string[];
  /** Who attested to each hardware check, and which document backs it. */
  attestations: Record<string, string>;
}

export function parseIdentityReadiness(value: unknown): IdentityReadiness {
  const root = asRecord(value, "readiness");

  if (root.guestContractVersion !== GUEST_CONTRACT_VERSION) {
    throw new Error(
      `Unsupported guest contract version: ${String(root.guestContractVersion)}`,
    );
  }

  const namingPolicy = asString(root, "namingPolicy", "readiness");
  if (!NAMING_POLICIES.includes(namingPolicy as NamingPolicy)) {
    throw new Error(`Unknown naming policy: ${namingPolicy}`);
  }

  const calibrationStatus = asString(root, "calibrationStatus", "readiness");
  if (!CALIBRATION_STATUSES.includes(calibrationStatus as CalibrationStatus)) {
    throw new Error(`Unknown calibration status: ${calibrationStatus}`);
  }

  const roleBased = root.roleBased;
  const unattended = root.unattendedNamingPermitted;
  if (typeof roleBased !== "boolean" || typeof unattended !== "boolean") {
    throw new Error("readiness.roleBased and unattendedNamingPermitted must be booleans");
  }

  const disclosure = asString(root, "disclosure", "readiness");
  if (!disclosure.trim()) {
    throw new Error("A readiness with no disclosure cannot be shown to an audience");
  }

  // ROLE_BASED must never claim naming from a face, and unattended naming is
  // only ever permitted by NAMED_AUTO. Contradictions are refused rather than
  // rendered, because the UI would otherwise show a reassuring impossibility.
  if (namingPolicy === "ROLE_BASED" && !roleBased) {
    throw new Error("ROLE_BASED must set roleBased");
  }
  if (namingPolicy !== "NAMED_AUTO" && unattended) {
    throw new Error(`${namingPolicy} cannot permit unattended naming`);
  }
  if (namingPolicy === "NAMED_AUTO" && !unattended) {
    throw new Error("NAMED_AUTO must permit unattended naming");
  }

  const attestations = asRecord(root.attestations ?? {}, "readiness.attestations");
  const signed: Record<string, string> = {};
  for (const [key, entry] of Object.entries(attestations)) {
    if (typeof entry !== "string" || !entry.trim()) {
      throw new Error(`readiness.attestations.${key} must name who attested`);
    }
    signed[key] = entry;
  }

  return {
    guestContractVersion: GUEST_CONTRACT_VERSION,
    eventId: asString(root, "eventId", "readiness"),
    namingPolicy: namingPolicy as NamingPolicy,
    roleBased,
    unattendedNamingPermitted: unattended,
    calibrationStatus: calibrationStatus as CalibrationStatus,
    disclosure,
    blockingReasons: asStringArray(root, "blockingReasons", "readiness"),
    attestations: signed,
  };
}

/** True when the operator must confirm a name before it can air. */
export function requiresOperatorConfirmation(readiness: IdentityReadiness): boolean {
  return readiness.namingPolicy === "NAMED_ASSIST";
}
