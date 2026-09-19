import { describe, expect, it } from "vitest";

import {
  assembleRecording,
  findInterrupted,
  MemoryRecordingStore,
  newRecordingId,
  type RecordingMeta,
} from "./recordingStore";

function meta(recordingId: string, status: RecordingMeta["status"], startedAt = 1): RecordingMeta {
  return {
    recordingId,
    eventId: "hackmit-demo",
    mimeType: "video/webm",
    startedAt,
    endedAt: status === "recording" ? null : startedAt + 10,
    chunkCount: 0,
    bytes: 0,
    status,
  };
}

describe("recording store", () => {
  it("returns chunks in index order even when appended out of order", async () => {
    const store = new MemoryRecordingStore();
    await store.createRecording(meta("r1", "recording"));
    await store.appendChunk("r1", 2, new Blob(["c"]));
    await store.appendChunk("r1", 0, new Blob(["a"]));
    await store.appendChunk("r1", 1, new Blob(["b"]));

    const chunks = await store.readChunks("r1");
    const text = await new Response(assembleRecording(chunks, "video/webm")).text();
    expect(text).toBe("abc");
  });

  it("assembles into one blob of the declared type", async () => {
    const blob = assembleRecording([new Blob(["ab"]), new Blob(["cd"])], "video/webm;codecs=vp8,opus");
    expect(blob.size).toBe(4);
    expect(blob.type).toBe("video/webm;codecs=vp8,opus");
  });

  it("lists newest first and finds recordings interrupted by a crash", async () => {
    const store = new MemoryRecordingStore();
    await store.createRecording(meta("old", "complete", 1));
    await store.createRecording(meta("crashed", "recording", 2));
    await store.createRecording(meta("active", "recording", 3));

    const list = await store.listRecordings();
    expect(list.map((m) => m.recordingId)).toEqual(["active", "crashed", "old"]);
    expect(findInterrupted(list, "active").map((m) => m.recordingId)).toEqual(["crashed"]);
  });

  it("deletes chunks with the recording", async () => {
    const store = new MemoryRecordingStore();
    await store.createRecording(meta("r1", "complete"));
    await store.appendChunk("r1", 0, new Blob(["a"]));
    await store.deleteRecording("r1");
    expect(await store.readChunks("r1")).toEqual([]);
    expect(await store.listRecordings()).toEqual([]);
  });

  it("refuses chunks for an unknown recording", async () => {
    const store = new MemoryRecordingStore();
    await expect(store.appendChunk("nope", 0, new Blob(["a"]))).rejects.toThrow(/Unknown recording/);
  });

  it("makes sortable, unique-looking IDs", () => {
    const id = newRecordingId(new Date(Date.UTC(2026, 8, 19, 20, 5, 9)));
    expect(id.startsWith("rec-20260919T200509Z-")).toBe(true);
  });
});
