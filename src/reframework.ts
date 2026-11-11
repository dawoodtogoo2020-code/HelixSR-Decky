import { hasOverride } from "./launchOptions";

export type ReframeworkState = {
  game: string; tested: boolean; override: string; source: string; reason: string;
  file: string | null; tag: string | null; revision: string | null;
  state: "absent" | "missing" | "installed" | "changed" | "foreign" | "review" | "unavailable";
};

export const OVERLAY_NATIVE_NOTE = "Scaler installs only. This game uses the native FSR replacement, which has no Scaler overlay. " +
  "Some games name the active upscaler in their own graphics menu; Resident Evil Requiem shows AMD FSR HLX FSR 4. " +
  "For runtime evidence, use Show HelixSR status overlay under More game settings.";

// HLX FSR 4 needs the loader. A native Model E install does not, unless a loader is already there.
export function showReframework(r: ReframeworkState, game: { managed: boolean; route: string | null; installed_variant?: string }): boolean {
  return r.state !== "absent" || !game.managed || game.route !== "direct" || game.installed_variant === "hlx-fsr4-1-2";
}

export function reframeworkText(r: ReframeworkState, launchOptions: string): { headline: string; intro: string; state: string; launch: string } {
  const intro = r.tested
    ? `A Steam Deck tester confirmed that ${r.game} needs REFramework's loader for HLX FSR 4. Without it the game shows an unhandled exception at startup. HelixSR 2.0 Model E worked without it.`
    : `A Steam Deck tester reports that ${r.game} needs REFramework's loader for HLX FSR 4, as Resident Evil Requiem does. This game has not been checked with it yet.`;
  const digits = r.tag?.match(/^nightly-(\d+)/)?.[1];
  const build = digits ? String(Number(digits)) : undefined;
  const states: Record<ReframeworkState["state"], [string, string]> = {
    absent: ["REFramework loader not added", "Add REFramework loader downloads the latest REFramework nightly from GitHub, checks GitHub's SHA-256 digest and adds only dinput8.dll next to the game executable."],
    missing: ["REFramework loader missing", "The dinput8.dll HelixSR added is no longer in the game folder. Add it again, or leave it off."],
    installed: ["REFramework loader added", `Added by HelixSR: REFramework ${build ? `nightly ${build}` : "nightly"}${r.revision ? ` (${r.revision})` : ""} as ${r.file}.`],
    changed: ["dinput8.dll changed", r.reason],
    foreign: ["Existing dinput8.dll kept", r.reason],
    review: ["REFramework loader needs review", r.reason],
    unavailable: ["REFramework loader unavailable", r.reason],
  };
  const [headline, state] = states[r.state];
  const launch = ["installed", "changed", "foreign"].includes(r.state)
    ? hasOverride(launchOptions, "dinput8")
      ? "Steam launch options include the dinput8 override."
      : `Proton also needs the launch option ${r.override}. Review dinput8 launch option shows the before and after, adds it and keeps your other options, such as a Lossless Scaling wrapper.`
    : `Proton also needs the launch option ${r.override} once the loader is added.`;
  return { headline, intro, state, launch };
}
