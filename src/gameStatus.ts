type GameState = {
  compatibility: string; managed: boolean; enabled: boolean; legacy: boolean;
  recovery_available?: boolean; executable_selection_needed?: boolean; installed_version?: string;
};

export function gameStatus(game: GameState) {
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
