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

export function proxyOptions(before: string): string {
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
    if (rules.some(rule => !/^[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*=(?:n,b|b,n|n|b|)$/.test(rule)))
      throw new Error("This DLL override needs manual review.");
    const dxgi = rules.filter(rule => rule.split("=")[0].split(",").some(name => name.toLowerCase().replace(/\.dll$/, "") === "dxgi"));
    if (dxgi.length) {
      if (dxgi.length !== 1 || dxgi[0].toLowerCase() !== "dxgi=n,b")
        throw new Error("An existing dxgi override needs review. Preserve it and check OptiScaler.log.");
    } else {
      const replacement = `WINEDLLOVERRIDES="${value ? `${value};` : ""}dxgi=n,b"`;
      updated = before.slice(0, override.start) + replacement + before.slice(override.end);
    }
  } else updated = `WINEDLLOVERRIDES="dxgi=n,b"${before ? ` ${before}` : ""}`;
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
