// A read deadline releases the panel without cancelling backend work. Keep the
// same request until it settles so refresh/remount cannot queue duplicate scans.
export class LibraryRead<T> {
  private pending: Promise<T> | undefined;
  private readonly read: () => Promise<T>;
  private readonly timeoutMs: number;

  constructor(read: () => Promise<T>, timeoutMs = 30000) {
    this.read = read;
    this.timeoutMs = timeoutMs;
  }

  async get(): Promise<T> {
    if (!this.pending) {
      const request = Promise.resolve().then(this.read);
      this.pending = request;
      const settled = () => { if (this.pending === request) this.pending = undefined; };
      request.then(settled, settled);
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        this.pending,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error(
            "The game library has not responded after 30 seconds. A scan may still be running, or the plugin backend could not start. Refresh to check again. If it remains pending, restart Decky and include the HelixSR backend log in a bug report."
          )), this.timeoutMs);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
}
