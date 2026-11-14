type Token = { start: number; end: number; value: string };

// Only literal shell words are understood. Never evaluate or rewrite shell code.
function words(input: string): Token[] {
  if (typeof input !== "string" || input.length > 16384 || /[\x00-\x1f\x7f$`\\]/.test(input))
    throw new Error("Launch options contain unsupported shell syntax and need manual review.");
  const result: Token[] = [];
  let i = 0;
  while (i < input.length) {
    if (input[i] === " ") { i++; continue; }
    const start = i;
    let value = "", quote = "";
    while (i < input.length) {
      const c = input[i];
      if (quote) {
        if (c === quote) quote = "";
        else value += c;
      } else if (c === "'" || c === '"') quote = c;
      else if (c === " ") break;
      // A leading ~/ names a home-relative wrapper such as Lossless Scaling's
      // ~/.lsfg. It never changes word boundaries, and the word is kept verbatim.
      else if (c === "~" && i === start && input[i + 1] === "/") value += c;
      else {
        if (/[;&|<>()*?\[\]{}#!~]/.test(c)) throw new Error("Ambiguous shell options need manual review.");
        value += c;
      }
      i++;
    }
    if (quote) throw new Error("Malformed launch option quotes need manual review.");
    result.push({start, end: i, value});
  }
  return result;
}

// Proton loads these proxy DLLs from the game folder only with a native-first override.
const OVERRIDES = {
  dxgi: { accepted: ["dxgi=n,b"], review: "An existing dxgi override needs review. Preserve it and check OptiScaler.log." },
  // REFramework's README documents dinput8.dll=n,b; Wine treats both spellings alike.
  dinput8: { accepted: ["dinput8=n,b", "dinput8.dll=n,b"], review: "An existing dinput8 override needs review. Preserve it and check the REFramework loader." },
  // Scaler loads OptiScaler as winmm.dll for games that need it (scaler_proxy.py), such as Red Dead Redemption 2.
  winmm: { accepted: ["winmm=n,b"], review: "An existing winmm override needs review. Preserve it and check OptiScaler.log." },
} as const;
export type OverrideDll = keyof typeof OVERRIDES;

export function hasOverride(options: string, dll: OverrideDll): boolean {
  try {
    const value = words(options).find(t => /^WINEDLLOVERRIDES=/.test(t.value))?.value.slice("WINEDLLOVERRIDES=".length) ?? "";
    return value.split(";").some(rule => (OVERRIDES[dll].accepted as readonly string[]).includes(rule.toLowerCase()));
  } catch { return false; }
}

export function proxyOptions(before: string): string {
  return overrideOptions(before, "dxgi");
}

const ENV = /^([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z0-9_.-]*)$/;

// Adds plain NAME=value assignments right after the DLL override, where Steam passes them to the game.
function withAssignments(before: string, updated: string, env: readonly string[], commandIndex: number): string {
  const original = words(before);
  for (const assignment of env) {
    const match = ENV.exec(assignment);
    if (!match) throw new Error("Unsupported launch assignment: " + assignment);
    const named = original.filter(t => t.value.startsWith(match[1] + "="));
    if (named.length) {
      const t = named[0];
      const index = original.indexOf(t);
      if (named.length !== 1 || t.value !== assignment || before.slice(t.start, t.end) !== assignment
          || (commandIndex >= 0 && index > commandIndex))
        throw new Error(`An existing ${match[1]} setting needs review. Preserve it and set ${assignment} yourself if the game needs it.`);
      continue;
    }
    const override = words(updated).find(t => /^WINEDLLOVERRIDES=/.test(t.value));
    if (!override) throw new Error("DLL override placement needs manual review.");
    updated = updated.slice(0, override.end) + " " + assignment + updated.slice(override.end);
  }
  return updated;
}

export function overrideOptions(before: string, dll: OverrideDll, env: readonly string[] = []): string {
  const { accepted, review } = OVERRIDES[dll];
  const tokens = words(before);
  const assignment = (t: Token) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(before.slice(t.start, t.end));
  if (tokens.some(t => /^[A-Za-z_][A-Za-z0-9_]*=/.test(t.value) && !assignment(t)))
    throw new Error("Quoted assignment names are ambiguous and need manual review.");
  const placeholders = tokens.filter(t => t.value.includes("%command%"));
  if (placeholders.length > 1 || placeholders.some(t => t.value !== "%command%" || before.slice(t.start, t.end) !== "%command%"))
    throw new Error("Ambiguous Steam command placeholders need manual review.");
  const commandIndex = placeholders.length ? tokens.indexOf(placeholders[0]) : -1;
  const assignments = tokens.filter(t => /^WINEDLLOVERRIDES=/.test(t.value));
  if (assignments.length > 1) throw new Error("Multiple DLL overrides need review. Preserve your existing launch options.");
  let leading = 0;
  while (leading < tokens.length && assignment(tokens[leading])) leading++;
  const override = assignments[0];
  let updated = before;
  if (override) {
    const index = tokens.indexOf(override);
    // `env` accepts assignments; arbitrary wrappers may interpret them as arguments.
    const envIndex = tokens[leading]?.value === "env" ? leading : -1;
    const envAssignments = envIndex >= 0 && tokens.slice(envIndex + 1, index).every(assignment);
    if (index >= leading && !(envAssignments && index > envIndex && commandIndex > index))
      throw new Error("DLL override placement needs manual review.");
    const value = override.value.slice("WINEDLLOVERRIDES=".length);
    const rules = value ? value.split(";") : [];
    // A common typo: WINEDLLOVERRIDES="winmm=n,b SteamDeck=0" hides the assignment inside the DLL list.
    if (value.includes(" "))
      throw new Error(`Another setting is inside the WINEDLLOVERRIDES quotes. Close the quotes after the DLL rules, for example WINEDLLOVERRIDES="${dll}=n,b" SteamDeck=0 %command%, then review again.`);
    if (rules.some(rule => !/^[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*=(?:n,b|b,n|n|b|)$/.test(rule)))
      throw new Error("This DLL override needs manual review.");
    const existing = rules.filter(rule => rule.split("=")[0].split(",").some(name => name.toLowerCase().replace(/\.dll$/, "") === dll));
    if (existing.length) {
      if (existing.length !== 1 || !(accepted as readonly string[]).includes(existing[0].toLowerCase()))
        throw new Error(review);
    } else {
      const replacement = `WINEDLLOVERRIDES="${value ? `${value};` : ""}${dll}=n,b"`;
      updated = before.slice(0, override.start) + replacement + before.slice(override.end);
    }
  } else updated = `WINEDLLOVERRIDES="${dll}=n,b"${before ? ` ${before}` : ""}`;
  updated = withAssignments(before, updated, env, commandIndex);
  if (commandIndex >= 0) return updated;
  if (tokens.slice(leading).some(t => /^[A-Za-z_][A-Za-z0-9_]*=/.test(t.value)) ||
      (tokens[leading] && !tokens[leading].value.startsWith("-")))
    throw new Error("Launch options without a Steam command are ambiguous and need manual review.");
  const parsed = words(updated);
  let end = 0;
  for (const token of parsed) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*=/.test(token.value)) break;
    end = token.end;
  }
  return updated.slice(0, end) + " %command%" + updated.slice(end);
}
