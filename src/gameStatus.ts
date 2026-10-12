type GameState = {
  compatibility: string; managed: boolean; enabled: boolean; legacy: boolean;
  recovery_available?: boolean; executable_selection_needed?: boolean; installed_version?: string;
  dx12_confirmation_needed?: boolean; awareness_deferred?: boolean;
  installation_status?: {
    state: "ready" | "running" | "review" | "unsupported" | "recovery";
    label: string; summary: string; running: boolean; selectable: boolean; can_modify: boolean; can_restore?: boolean;
    issues: {code: string; title: string; reason: string; steps: string[]; blocking: boolean}[];
  };
};

export function installReadiness(game: GameState, dx12Confirmed: boolean) {
  if (game.awareness_deferred) return {allowed: false, reason: "Wait for this game's details to finish loading."};
  if (game.compatibility !== "candidate" || game.installation_status?.can_modify === false || game.recovery_available)
    return {allowed: false, reason: game.installation_status?.summary || "Resolve this game's review reasons, then refresh."};
  if (game.dx12_confirmation_needed && !dx12Confirmed)
    return {allowed: false, reason: "Confirm DirectX 12 above before installing. This does not switch the game's renderer for you."};
  return {allowed: true, reason: ""};
}

type Guidance = {headline: string; steps: string[]; notes: string[]; links: {label: string; url: string}[]};
export function nextStep(guidance: Guidance | undefined, activeJob?: {game: string; message: string}) {
  return activeJob ? {headline: `${activeJob.game}: Installing / preparing HelixSR…`,
    steps: [activeJob.message, "Wait for completion. Progress and cancellation are below; game files cannot be changed during this operation."], notes: [], links: []} : guidance;
}

export function canRestore(game: GameState) {
  return game.installation_status?.can_restore ??
    (game.compatibility === "candidate" && game.managed && game.installation_status?.can_modify !== false);
}

export function gameStatus(game: GameState) {
  if (game.installation_status) {
    const status = game.installation_status;
    const review = status.state === "review" || status.state === "recovery" || status.state === "unsupported";
    const recorded = game.managed ? `Recorded as ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}` : "";
    const summary = status.state === "running"
      ? `${game.managed ? `HelixSR ${game.enabled ? "enabled" : "disabled"} · ` : ""}${status.label} · ${status.summary}`
      : review ? `${status.label}: ${status.summary}${recorded ? ` · ${recorded}` : ""}`
      : game.managed ? `HelixSR ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}`
      : game.legacy ? "Existing HelixSR installation" : "HelixSR is not installed for this game";
    return {label: status.label, summary, review,
      installed: !review && (game.managed || game.legacy),
      color: review ? "#f1ca7e" : game.managed || game.legacy ? "#8ee8bc" : "#c5d1df"};
  }
  const review = game.compatibility !== "candidate" || !!game.recovery_available;
  const label = game.executable_selection_needed ? "Choose executable" : game.recovery_available ? "Recovery needed"
    : review ? "Needs review" : game.managed ? game.enabled ? "Enabled" : "Disabled"
    : game.legacy ? "Existing HelixSR" : "Not installed";
  const recorded = game.managed ? `Recorded as ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}` : "";
  const summary = review ? `HelixSR: ${label}${recorded ? ` · ${recorded}` : ""}`
    : game.managed ? `HelixSR ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}`
    : game.legacy ? "Existing HelixSR installation" : "HelixSR is not installed for this game";
  return { label, summary, review, installed: !review && (game.managed || game.legacy),
    color: review ? "#f1ca7e" : game.managed || game.legacy ? "#8ee8bc" : "#c5d1df" };
}
