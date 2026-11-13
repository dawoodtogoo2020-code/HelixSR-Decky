import { hasOverride } from "./launchOptions";

export type ReframeworkState = {
  game: string; tested: boolean; evidence?: string | null; override: string; source: string; reason: string;
  file: string | null; tag: string | null; revision: string | null;
  state: "absent" | "missing" | "installed" | "changed" | "foreign" | "review" | "unavailable";
};

export const ADD_OVERRIDE = "Add dinput8 launch option (only if needed)";

export const OVERLAY_NATIVE_NOTE = "Scaler installs only. This game uses the native FSR replacement, which has no Scaler overlay. " +
  "Some games name the active upscaler in their own graphics menu: Resident Evil Requiem shows AMD FSR HLX FSR 4, and PRAGMATA's Upscaling description reads Uses AMD FSR HLX FSR 4 (4.1.2). " +
  "For runtime evidence, use Show HelixSR status overlay under More game settings.";

// HLX FSR 4 needs the loader. A native Model E install does not, unless a loader is already there.
export function showReframework(r: ReframeworkState, game: { managed: boolean; route: string | null; installed_variant?: string }): boolean {
  return r.state !== "absent" || !game.managed || game.route !== "direct" || game.installed_variant === "hlx-fsr4-1-2";
}

export function reframeworkText(r: ReframeworkState, launchOptions: string): { headline: string; intro: string; state: string; launch: string } {
  const intro = r.evidence
    || (r.tested ? `A Steam Deck tester confirmed that ${r.game} works with HLX FSR 4 and REFramework's loader.`
      : `A Steam Deck tester reports that ${r.game} needs REFramework's loader for HLX FSR 4, as Resident Evil Requiem does. This game has not been checked with it yet.`);
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
  // A Steam Deck tester found Proton loads the game-folder DLL without an override (PRAGMATA).
  const launch = ["installed", "changed", "foreign"].includes(r.state)
    ? hasOverride(launchOptions, "dinput8")
      ? "Steam launch options include the dinput8 override. It is usually not needed, so you can restore your previous launch options if you like."
      : `No launch option is needed: on the tester's Steam Deck, Proton loaded REFramework from the DLL alone. Only if the game still crashes at startup, ${ADD_OVERRIDE} adds ${r.override} and keeps your other options, such as a Lossless Scaling wrapper.`
    : "No launch option is needed: on the tester's Steam Deck, the DLL alone was enough.";
  return { headline, intro, state, launch };
}
