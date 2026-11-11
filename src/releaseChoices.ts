export type ReleaseChoiceView = { id: string; label: string; version: string | null };

export const DEFAULT_RELEASE_CHOICE = "reviewed-2.0.0";
// HLX releases are explicit opt-ins next to the recommended Model E package.
export const PRERELEASE_CHOICES = ["reviewed-3.3.0", "reviewed-3.2.0"];

/** A prerelease opt-in belongs to the game it was chosen for, never the next game opened. */
export function releaseChoiceForGame(remembered: string, rememberedFor: string | undefined, gameId: string): string {
  return PRERELEASE_CHOICES.includes(remembered) && rememberedFor !== gameId ? DEFAULT_RELEASE_CHOICE : remembered;
}

export function releaseChoiceLabel(choice: ReleaseChoiceView): string {
  if (PRERELEASE_CHOICES.includes(choice.id)) return choice.label;
  if (choice.id === DEFAULT_RELEASE_CHOICE)
    return `HelixSR ${choice.version || "2.0.0"} (recommended)`;
  if (choice.id === "latest") return "Latest upstream";
  if (choice.id.startsWith("reviewed-") || choice.id.startsWith("compatible-"))
    return `HelixSR ${choice.version || choice.id.split("-").slice(1).join("-")} (older release)`;
  return choice.label;
}

export function releaseChoiceExplanation(id: string): string {
  if (id === "reviewed-3.3.0")
    return "Reviewed HelixSR 3.3.0 release with HLX FSR 4 (FSR 4.1.2 Lite). With Scaler you can also select HLX FSR 4 Full, the full FSR 4.1.2 network: sharper and slower. Model E stays on 2.0.0. The game’s input and the frame generation provider are separate choices.";
  if (id === "reviewed-3.2.0")
    return "This reviewed prerelease includes HLX FSR 4 using AMD’s FSR 4.1.2 Lite model. The game’s input and the frame generation provider are separate choices.";
  if (id === DEFAULT_RELEASE_CHOICE)
    return "Recommended 2.0.0 package. Reviewed means its files and installation steps are supported by this plugin. No maintainer approval is needed; game compatibility still varies.";
  if (id === "latest")
    return "Checks the newest upstream release. Installation stays blocked unless that exact release has been reviewed by this plugin.";
  return "Older reviewed release for specific setups. You only need one version. Existing installations are not downgraded automatically.";
}
