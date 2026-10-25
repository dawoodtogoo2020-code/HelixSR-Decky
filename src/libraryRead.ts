type Outcome<T> = { ok: true; value: T } | { ok: false; error: unknown };

interface ReadRequest<T> {
  done: Promise<Outcome<T>>;
  waiters: number;
  generation: number;
}

function unwrap<T>(outcome: Outcome<T>): T {
  if (outcome.ok) return outcome.value;
  throw outcome.error;
}

/**
 * Keeps the last successful library snapshot across panel remounts. Normal
 * reads reuse that snapshot, while refresh() always starts a backend scan.
 * Each caller has its own deadline and stale scans cannot replace a newer
 * refresh or a mutation result supplied through remember().
 */
export class LibraryRead<T> {
  private readonly read: () => Promise<T>;
  private readonly timeoutMs: number;
  private current: ReadRequest<T> | null = null;
  private unconsumed: Outcome<T> | null = null;
  private snapshot: T | undefined;
  private hasSnapshot = false;
  private generation = 0;

  constructor(read: () => Promise<T>, timeoutMs = 30000) {
    this.read = read;
    this.timeoutMs = timeoutMs;
  }

  async get(): Promise<T> {
    if (this.unconsumed) {
      const outcome = this.unconsumed;
      this.unconsumed = null;
      return unwrap(outcome);
    }
    if (this.hasSnapshot) return this.snapshot as T;

    return this.wait(this.current ?? this.start());
  }

  async refresh(): Promise<T> {
    this.unconsumed = null;
    return this.wait(this.start());
  }

  remember(value: T): void {
    this.generation++;
    this.current = null;
    this.unconsumed = null;
    this.snapshot = value;
    this.hasSnapshot = true;
  }

  invalidate(): void {
    this.generation++;
    this.current = null;
    this.unconsumed = null;
    this.snapshot = undefined;
    this.hasSnapshot = false;
  }

  private async wait(request: ReadRequest<T>): Promise<T> {
    request.waiters++;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        const seconds = Math.round(this.timeoutMs / 1000);
        reject(new Error(
          `The library has not responded within ${seconds} seconds. ` +
          "The scan may still be running, or the plugin backend could not start. Press Refresh to retrieve the scan result. If it remains pending, restart Decky and include the HelixSR backend log in a bug report.",
        ));
      }, this.timeoutMs);
    });
    try {
      const outcome = await Promise.race([request.done, deadline]);
      if (request.generation !== this.generation) {
        if (this.current) return this.wait(this.current);
        if (this.hasSnapshot) return this.snapshot as T;
        // A background job can invalidate the cache while every panel is
        // closed. Its old waiter must not republish the pre-job snapshot.
        return this.get();
      }
      return unwrap(outcome);
    } finally {
      clearTimeout(timer);
      request.waiters--;
    }
  }

  private start(): ReadRequest<T> {
    const request = { waiters: 0, generation: ++this.generation } as ReadRequest<T>;
    request.done = Promise.resolve()
      .then(() => this.read())
      .then(
        (value): Outcome<T> => ({ ok: true, value }),
        (error): Outcome<T> => ({ ok: false, error }),
      )
      .then((outcome) => {
        if (request.generation !== this.generation) return outcome;
        if (this.current === request) this.current = null;
        if (outcome.ok) {
          this.snapshot = outcome.value;
          this.hasSnapshot = true;
        } else if (request.waiters === 0) {
          // A late failure is surfaced once instead of becoming unhandled.
          this.unconsumed = outcome;
        }
        return outcome;
      });
    this.current = request;
    return request;
  }
}
