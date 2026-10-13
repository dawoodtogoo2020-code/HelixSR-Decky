export type InstallJob = { id: string; kind: string; game: string; state: string;
  message: string; log: string; gid?: string };
export type InstallSubmission = { pending: boolean; gid: string; name: string;
  message: string; error: string };

// Decky may unmount its panel when a confirmation opens. Keep the request and
// any failure outside React so reopening the panel cannot lose either.
export class InstallSession {
  private state: InstallSubmission = { pending: false, gid: "", name: "", message: "", error: "" };
  private listeners = new Set<(state: InstallSubmission) => void>();

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
      this.state.error = error instanceof Error ? error.message : String(error);
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
