type GameState = {
  compatibility: string; managed: boolean; enabled: boolean; legacy: boolean;
  recovery_available?: boolean; executable_selection_needed?: boolean; installed_version?: string;
  installation_status?: {
    state: "ready" | "running" | "review" | "unsupported" | "recovery";
    label: string; summary: string; running: boolean; selectable: boolean; can_modify: boolean;
    issues: {code: string; title: string; reason: string; steps: string[]; blocking: boolean}[];
  };
};

export function gameStatus(game: GameState) {
  if (game.installation_status) {
    const status = game.installation_status;
    const review = status.state === "review" || status.state === "recovery" || status.state === "unsupported";
    const recorded = game.managed ? `Recorded as ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}` : "";
    const summary = status.state === "running"
      ? `${game.managed ? `HelixSR ${game.enabled ? "enabled" : "disabled"} · ` : ""}${status.label} · ${status.summary}`
      : review ? `${status.label}: ${status.summary}${recorded ? ` · ${recorded}` : ""}`
      : game.managed ? `HelixSR ${game.enabled ? "enabled" : "disabled"} · ${game.installed_version || "unknown version"}`
      : game.legacy ? "Existing HelixSR installation" : "HelixSR is not enabled";
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
    : game.legacy ? "Existing HelixSR installation" : "HelixSR is not enabled";
  return { label, summary, review, installed: !review && (game.managed || game.legacy),
    color: review ? "#f1ca7e" : game.managed || game.legacy ? "#8ee8bc" : "#c5d1df" };
}
