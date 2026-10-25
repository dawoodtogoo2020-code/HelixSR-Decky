export type ReleaseChoiceView = { id: string; label: string; version: string | null };

export const DEFAULT_RELEASE_CHOICE = "reviewed-2.0.0";

export function releaseChoiceLabel(choice: ReleaseChoiceView): string {
  if (choice.id === DEFAULT_RELEASE_CHOICE)
    return `HelixSR ${choice.version || "2.0.0"} (recommended)`;
  if (choice.id === "latest") return "Latest upstream";
  if (choice.id.startsWith("reviewed-") || choice.id.startsWith("compatible-"))
    return `HelixSR ${choice.version || choice.id.split("-").slice(1).join("-")} (older release)`;
  return choice.label;
}

export function releaseChoiceExplanation(id: string): string {
  if (id === DEFAULT_RELEASE_CHOICE)
    return "Recommended 2.0.0 package. Reviewed means its files and installation steps are supported by this plugin. No maintainer approval is needed; game compatibility still varies.";
  if (id === "latest")
    return "Checks the newest upstream release. Installation stays blocked unless that exact release has been reviewed by this plugin.";
  return "Older reviewed release for specific setups. You only need one version. Existing installations are not downgraded automatically.";
}
