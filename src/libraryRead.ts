type Outcome<T> = { ok: true; value: T } | { ok: false; error: unknown };

interface ReadRequest<T> {
  done: Promise<Outcome<T>>;
  waiters: number;
}

function unwrap<T>(outcome: Outcome<T>): T {
  if (outcome.ok) return outcome.value;
  throw outcome.error;
}

/**
 * Shares one in-flight backend library read between callers. Each caller gets
 * its own UI deadline; a scan that outlives every deadline keeps running and
 * its result (or error) is retained until the next get() picks it up.
 */
export class LibraryRead<T> {
  private readonly read: () => Promise<T>;
  private readonly timeoutMs: number;
  private current: ReadRequest<T> | null = null;
  private unconsumed: Outcome<T> | null = null;

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

    const request = this.current ?? this.start();
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
      return unwrap(await Promise.race([request.done, deadline]));
    } finally {
      clearTimeout(timer);
      request.waiters--;
    }
  }

  private start(): ReadRequest<T> {
    const request = { waiters: 0 } as ReadRequest<T>;
    request.done = Promise.resolve()
      .then(() => this.read())
      .then(
        (value): Outcome<T> => ({ ok: true, value }),
        (error): Outcome<T> => ({ ok: false, error }),
      )
      .then((outcome) => {
        if (this.current === request) this.current = null;
        // Nobody is waiting: keep the result for the next get() instead of losing it.
        if (request.waiters === 0) this.unconsumed = outcome;
        return outcome;
      });
    this.current = request;
    return request;
  }
}
