export type PluginArtifact = { artifact: string; name: string; version: string; sha256: string; install_type: number };
type Route = (route: string, ...args: unknown[]) => Promise<unknown>;

// This survives Quick Access unmounts. Downloading is distinct from installing.
export class PluginInstaller {
  target?: PluginArtifact;
  requestId?: string;
  phase: "idle" | "awaiting" | "installing" | "unknown" = "idle";
  message = "";
  private timer?: ReturnType<typeof setTimeout>;
  private busy = false;
  private acceptingPrompt = false;
  private route: Route;
  private changed: () => void;
  constructor(route: Route, changed: () => void) { this.route = route; this.changed = changed; }

  prompt(name: string, version: string, requestId: string, hash: string) {
    if (this.locked || !this.acceptingPrompt) return;
    if (this.target?.name !== name || this.target.version !== version || this.target.sha256 !== hash) return;
    this.requestId = requestId;
    this.phase = "awaiting";
    this.message = `Plugin ${version} downloaded and verified. Press Update in Decky's confirmation to install it.`;
    this.changed();
  }

  started(name: string) {
    if (name !== this.target?.name) return;
    this.phase = "installing";
    this.message = "Decky is installing the plugin. Wait for it to reload.";
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.phase = "unknown";
      this.message = "Decky has not confirmed completion. Keep game changes paused. Close its prompt and restart Decky before retrying.";
      this.changed();
    }, 120000);
    this.changed();
  }

  finished(name: string) {
    if (name !== this.target?.name) return;
    this.clearTimer();
    // A finish event is also emitted after some failed Decky installations.
    this.phase = "unknown";
    this.message = "Decky finished its attempt. Reopen the plugin and verify Current plugin matches the downloaded version. If it does not, restart Decky and retry.";
    this.changed();
  }

  get locked() { return this.phase === "installing" || this.phase === "unknown"; }

  private async dismissRequest() {
    if (!this.requestId) return;
    const id = this.requestId;
    try { await this.route("utilities/cancel_plugin_install", id); }
    catch (error) {
      // Decky's native Cancel consumes the request without emitting an event.
      // Only that precise missing-key error acknowledges an already-gone request.
      const text = error instanceof Error ? error.message : String(error);
      const missing = error instanceof Error && (error.name === "Python KeyError" || error.name === "KeyError");
      if (!missing && text !== `'${id}'` && text !== `KeyError: '${id}'`) throw error;
    }
    if (this.locked) throw new Error("Decky installation has started. Wait for it to finish before retrying.");
    this.requestId = undefined;
  }

  async open(target: PluginArtifact) {
    if (this.busy) throw new Error("Wait for the current installer request.");
    if (this.locked) throw new Error("Installation status is unresolved. Restart Decky before retrying.");
    if (this.target && !this.requestId)
      throw new Error("Decky did not acknowledge its previous prompt. Cancel the downloaded update before starting a new attempt.");
    this.busy = true;
    try {
    await this.dismissRequest();
    this.target = { ...target };
    this.phase = "awaiting";
    this.message = `Plugin ${target.version} downloaded and verified. Confirm Update in Decky to install. Use Open update confirmation if the screen closes.`;
    this.changed();
    try {
      this.acceptingPrompt = true;
      await this.route("utilities/install_plugin", target.artifact, target.name, target.version, target.sha256, target.install_type);
      if (!this.requestId) {
        this.phase = "unknown";
        this.message = "Decky did not acknowledge the confirmation. Keep game changes paused and restart Decky before retrying.";
        this.changed();
        throw new Error(this.message);
      }
    } catch (error) {
      if (!this.locked)
        this.message = `Could not open Decky's confirmation: ${error instanceof Error ? error.message : String(error)}. Your downloaded update is retained; cancel it before starting a new attempt.`;
      this.changed();
      throw error;
    } finally { this.acceptingPrompt = false; }
    } finally { this.busy = false; }
  }

  async cancel(remove: () => Promise<unknown>) {
    if (this.busy) throw new Error("Wait for the current installer request.");
    if (this.locked) throw new Error("Do not cancel files while Decky may be installing. Restart Decky first.");
    this.busy = true;
    try {
    await this.dismissRequest();
    await remove();
    this.target = undefined;
    this.phase = "idle";
    this.message = "Downloaded update cancelled.";
    this.changed();
    } finally { this.busy = false; }
  }

  private clearTimer() { if (this.timer) clearTimeout(this.timer); this.timer = undefined; }
  dispose() { this.clearTimer(); }
}
