/**
 * Incremental persistence for programme recordings (PRD section 11): ordered
 * chunks, including the first one that carries the container initialisation
 * data, are written as they arrive so a crash keeps everything up to the last
 * chunk. The interface is small so tests use the memory store and the browser
 * uses IndexedDB.
 */

export type RecordingStatus = "recording" | "complete" | "interrupted";

export interface RecordingMeta {
  recordingId: string;
  eventId: string;
  mimeType: string;
  startedAt: number;
  endedAt: number | null;
  chunkCount: number;
  bytes: number;
  status: RecordingStatus;
}

export interface RecordingStore {
  createRecording(meta: RecordingMeta): Promise<void>;
  appendChunk(recordingId: string, index: number, blob: Blob): Promise<void>;
  updateRecording(meta: RecordingMeta): Promise<void>;
  listRecordings(): Promise<RecordingMeta[]>;
  readChunks(recordingId: string): Promise<Blob[]>;
  deleteRecording(recordingId: string): Promise<void>;
}

export class MemoryRecordingStore implements RecordingStore {
  private readonly metas = new Map<string, RecordingMeta>();
  private readonly chunks = new Map<string, Map<number, Blob>>();

  async createRecording(meta: RecordingMeta): Promise<void> {
    this.metas.set(meta.recordingId, { ...meta });
    this.chunks.set(meta.recordingId, new Map());
  }

  async appendChunk(recordingId: string, index: number, blob: Blob): Promise<void> {
    const bucket = this.chunks.get(recordingId);
    if (!bucket) throw new Error(`Unknown recording ${recordingId}`);
    bucket.set(index, blob);
  }

  async updateRecording(meta: RecordingMeta): Promise<void> {
    if (!this.metas.has(meta.recordingId)) throw new Error(`Unknown recording ${meta.recordingId}`);
    this.metas.set(meta.recordingId, { ...meta });
  }

  async listRecordings(): Promise<RecordingMeta[]> {
    return [...this.metas.values()].sort((a, b) => b.startedAt - a.startedAt);
  }

  async readChunks(recordingId: string): Promise<Blob[]> {
    const bucket = this.chunks.get(recordingId);
    if (!bucket) return [];
    return [...bucket.entries()].sort((a, b) => a[0] - b[0]).map(([, blob]) => blob);
  }

  async deleteRecording(recordingId: string): Promise<void> {
    this.metas.delete(recordingId);
    this.chunks.delete(recordingId);
  }
}

/** Concatenate ordered chunks into one file. Chunks alone are not playable; the whole is. */
export function assembleRecording(chunks: readonly Blob[], mimeType: string): Blob {
  return new Blob([...chunks], { type: mimeType });
}

/** Recordings that were still "recording" when the page died. Found on the next load. */
export function findInterrupted(recordings: readonly RecordingMeta[], activeId: string | null): RecordingMeta[] {
  return recordings.filter((meta) => meta.status === "recording" && meta.recordingId !== activeId);
}

export function newRecordingId(now: Date): string {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const salt = Math.random().toString(36).slice(2, 6);
  return `rec-${stamp}-${salt}`;
}

// ---------------------------------------------------------------------------
// IndexedDB implementation (browser only)
// ---------------------------------------------------------------------------

const DB_NAME = "cue-programme";
const DB_VERSION = 1;
const META_STORE = "recordings";
const CHUNK_STORE = "chunks";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"));
  });
}

function transactionDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
  });
}

export async function openIndexedDbRecordingStore(): Promise<RecordingStore> {
  if (typeof indexedDB === "undefined") throw new Error("IndexedDB is not available");
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(DB_NAME, DB_VERSION);
    open.onupgradeneeded = () => {
      const database = open.result;
      if (!database.objectStoreNames.contains(META_STORE)) {
        database.createObjectStore(META_STORE, { keyPath: "recordingId" });
      }
      if (!database.objectStoreNames.contains(CHUNK_STORE)) {
        const chunks = database.createObjectStore(CHUNK_STORE, { keyPath: ["recordingId", "index"] });
        chunks.createIndex("byRecording", "recordingId", { unique: false });
      }
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error ?? new Error("Could not open IndexedDB"));
    open.onblocked = () => reject(new Error("IndexedDB open blocked by another tab"));
  });

  return {
    async createRecording(meta) {
      const tx = db.transaction(META_STORE, "readwrite");
      tx.objectStore(META_STORE).put(meta);
      await transactionDone(tx);
    },
    async appendChunk(recordingId, index, blob) {
      const tx = db.transaction(CHUNK_STORE, "readwrite");
      tx.objectStore(CHUNK_STORE).put({ recordingId, index, blob, createdAt: Date.now() });
      await transactionDone(tx);
    },
    async updateRecording(meta) {
      const tx = db.transaction(META_STORE, "readwrite");
      tx.objectStore(META_STORE).put(meta);
      await transactionDone(tx);
    },
    async listRecordings() {
      const tx = db.transaction(META_STORE, "readonly");
      const all = await request(tx.objectStore(META_STORE).getAll() as IDBRequest<RecordingMeta[]>);
      return all.sort((a, b) => b.startedAt - a.startedAt);
    },
    async readChunks(recordingId) {
      const tx = db.transaction(CHUNK_STORE, "readonly");
      const rows = await request(
        tx.objectStore(CHUNK_STORE).index("byRecording").getAll(recordingId) as IDBRequest<
          { index: number; blob: Blob }[]
        >,
      );
      return rows.sort((a, b) => a.index - b.index).map((row) => row.blob);
    },
    async deleteRecording(recordingId) {
      const tx = db.transaction([META_STORE, CHUNK_STORE], "readwrite");
      tx.objectStore(META_STORE).delete(recordingId);
      const chunkStore = tx.objectStore(CHUNK_STORE);
      const keys = await request(
        chunkStore.index("byRecording").getAllKeys(recordingId) as IDBRequest<IDBValidKey[]>,
      );
      for (const key of keys) chunkStore.delete(key);
      await transactionDone(tx);
    },
  };
}
