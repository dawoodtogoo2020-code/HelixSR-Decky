const INVALID_LAUNCH_OPTIONS_MESSAGE = 'Steam returned invalid launch options. Reopen the game and try again.';
const LAUNCH_OPTIONS_TIMEOUT_MESSAGE = 'Steam did not provide live launch options';

type AppDetailsListener = (detail: unknown) => void;
type AppDetailsSubscription = { unregister(): void };

function releaseSubscription(subscription: unknown): void {
  try {
    if ((typeof subscription !== 'object' && typeof subscription !== 'function') || subscription === null) {
      return;
    }
    const unregister = (subscription as { unregister?: unknown }).unregister;
    if (typeof unregister === 'function') {
      unregister.call(subscription);
    }
  } catch {
    // Cleanup failures must not change an already settled result.
  }
}

function readStrLaunchOptions(detail: unknown): { ok: true; value: string } | { ok: false } {
  if (typeof detail !== 'object' || detail === null) {
    return { ok: false };
  }
  let value: unknown;
  try {
    value = (detail as { strLaunchOptions?: unknown }).strLaunchOptions;
  } catch {
    return { ok: false };
  }
  if (typeof value !== 'string') {
    return { ok: false };
  }
  return { ok: true, value };
}

export function readLaunchOptions(
  register: (listener: AppDetailsListener) => AppDetailsSubscription,
  timeoutMs: number = 5000,
): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    let settled = false;
    let registering = true;
    let released = false;
    let subscription: unknown = undefined;
    let timer: ReturnType<typeof setTimeout> | undefined = undefined;

    const release = (): void => {
      // A synchronous callback settles before register returns its subscription;
      // cleanup is deferred until the subscription has been assigned.
      if (released || registering) {
        return;
      }
      released = true;
      const current = subscription;
      subscription = undefined;
      releaseSubscription(current);
    };

    const settle = (complete: () => void): void => {
      if (settled) {
        return;
      }
      settled = true;
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      complete();
      release();
    };

    const listener: AppDetailsListener = (detail) => {
      if (settled) {
        return;
      }
      const result = readStrLaunchOptions(detail);
      if (result.ok) {
        const value = result.value;
        settle(() => resolve(value));
      } else {
        settle(() => reject(new Error(INVALID_LAUNCH_OPTIONS_MESSAGE)));
      }
    };

    timer = setTimeout(() => {
      timer = undefined;
      settle(() => reject(new Error(LAUNCH_OPTIONS_TIMEOUT_MESSAGE)));
    }, timeoutMs);

    let registered: unknown;
    try {
      registered = register(listener);
    } catch (error) {
      registering = false;
      settle(() => reject(error));
      return;
    }

    registering = false;
    subscription = registered;
    if (settled) {
      release();
    }
  });
}
