import type { CameraId } from "@cue/contracts";

type AsyncTask<T> = () => Promise<T>;

/**
 * LiveKit can deliver publish/unpublish callbacks close together. Keep each
 * camera's backend mutations in callback order while allowing different
 * cameras to progress independently.
 */
export class CameraTransportSequencer {
  private readonly tails = new Map<CameraId, Promise<void>>();

  enqueue<T>(cameraId: CameraId, task: AsyncTask<T>): Promise<T> {
    const previous = this.tails.get(cameraId) ?? Promise.resolve();
    const result = previous.catch(() => undefined).then(task);
    const tail = result.then(
      () => undefined,
      () => undefined,
    );
    this.tails.set(cameraId, tail);
    void tail.then(() => {
      if (this.tails.get(cameraId) === tail) this.tails.delete(cameraId);
    });
    return result;
  }

  async drain(): Promise<void> {
    await Promise.all([...this.tails.values()]);
  }
}

