/** Bounds UI waits without cancelling or duplicating a pending backend read. */
export class GameDetailsRead<T> {
  private readonly pending = new Map<string, Promise<T>>();
  private readonly read: (id: string, executable?: string) => Promise<T>;
  private readonly timeoutMs: number;

  constructor(read: (id: string, executable?: string) => Promise<T>, timeoutMs = 30000) {
    this.read = read;
    this.timeoutMs = timeoutMs;
  }

  async get(id: string, executable?: string): Promise<T> {
    const key = JSON.stringify([id, executable ?? null]);
    let request = this.pending.get(key);
    if (!request) {
      request = Promise.resolve().then(() => this.read(id, executable));
      this.pending.set(key, request);
      const clear = () => {
        if (this.pending.get(key) === request) this.pending.delete(key);
      };
      // Handle both outcomes even when all UI callers have timed out.
      void request.then(clear, clear);
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([request, new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(
          `Game details have not responded within ${Math.round(this.timeoutMs / 1000)} seconds. ` +
          'Select another game or press Refresh to retry. The backend read may still be running; if it remains pending, restart Decky.',
        )), this.timeoutMs);
      })]);
    } finally {
      clearTimeout(timer);
    }
  }
}
