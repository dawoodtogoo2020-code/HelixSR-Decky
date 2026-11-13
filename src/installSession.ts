export type InstallJob = { id: string; kind: string; game: string; state: string;
  message: string; log: string; gid?: string; started_at?: number; ended_at?: number };
export type InstallSubmission = { pending: boolean; gid: string; name: string;
  message: string; error: string };

// Decky may unmount its panel when a confirmation opens. Keep the request and
// any failure outside React so reopening the panel cannot lose either.
export class InstallSession {
  private state: InstallSubmission = { pending: false, gid: "", name: "", message: "", error: "" };
  private listeners = new Set<(state: InstallSubmission) => void>();
  private describe: (error: unknown) => string;
  constructor(describe = (error: unknown) => error instanceof Error ? error.message : String(error)) { this.describe = describe; }

  get snapshot(): InstallSubmission { return { ...this.state }; }

  subscribe(listener: (state: InstallSubmission) => void): () => void {
    this.listeners.add(listener);
    this.deliver(listener);
    return () => { this.listeners.delete(listener); };
  }

  private deliver(listener: (state: InstallSubmission) => void) {
    try { listener(this.snapshot); } catch { /* A closed panel must not abort installation. */ }
  }

  private publish() { this.listeners.forEach(listener => this.deliver(listener)); }

  clearError() { this.state.error = ""; this.publish(); }

  async start(gid: string, name: string, task: () => Promise<void>): Promise<boolean> {
    if (this.state.pending) return false;
    this.state = { pending: true, gid, name, error: "",
      message: "Starting HelixSR installation. Waiting for the backend; you do not need to press Install again." };
    this.publish();
    try {
      await task();
      return true;
    } catch (error) {
      this.state.error = this.describe(error);
      return false;
    } finally {
      this.state.pending = false;
      this.state.message = "";
      this.publish();
    }
  }
}

export class JobTracker {
  private current: InstallJob[] = [];
  private generation = 0;
  get revision(): number { return this.generation; }
  get jobs(): InstallJob[] { return this.current.map(job => ({ ...job })); }

  update(next: InstallJob[], expectedRevision?: number): boolean {
    if (expectedRevision !== undefined && expectedRevision !== this.generation) return false;
    this.current = next.map(job => {
      const old = this.current.find(previous => previous.id === job.id);
      // A delayed running snapshot must never undo completion of the same job.
      return { ...(old && ["completed", "failed", "cancelled"].includes(old.state)
        && job.state === "running" ? old : job) };
    });
    this.generation++;
    return true;
  }
}

/**
 * The selected game's latest job, when it failed and has not been dismissed. A failed
 * install or update otherwise only shows a short toast, and the panel falls back to the
 * old status ("Not installed" or the previous model) with no reason on screen.
 */
export function lastFailedJob(jobs: InstallJob[], game: { id: string; name: string } | undefined,
                              dismissed: ReadonlySet<string>): InstallJob | undefined {
  if (!game) return undefined;
  const mine = jobs.filter(job => job.gid ? job.gid === game.id : job.game === game.name);
  if (!mine.length) return undefined;
  const latest = mine.reduce((a, b) => (b.started_at ?? 0) >= (a.started_at ?? 0) ? b : a);
  return latest.state === "failed" && !dismissed.has(latest.id) ? latest : undefined;
}
