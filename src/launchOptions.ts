export function proxyOptions(before: string): string {
  const matches = [...before.matchAll(/(?:^|\s)WINEDLLOVERRIDES=("[^"]*"|'[^']*'|[^\s]+)/g)];
  if (matches.length > 1) throw new Error("Multiple DLL overrides need review. Preserve your existing launch options.");
  const match = matches[0];
  if (match) {
    const value = match[1].replace(/^["']|["']$/g, "");
    if (value.split(";").some(rule => rule.split("=")[0].split(",").some(name => name.trim().toLowerCase().replace(/\.dll$/, "") === "dxgi"))) {
      throw new Error("An existing dxgi override needs review. Preserve it and check OptiScaler.log.");
    }
    if (/[\$`\\*\n\r]/.test(value)) throw new Error("This DLL override contains shell syntax or a wildcard and needs manual review.");
    const result = before.replace(match[0], match[0].replace(/WINEDLLOVERRIDES=.*$/, `WINEDLLOVERRIDES="${value};dxgi=n,b"`));
    if (result.includes("%command%")) return result;
    // An environment assignment plus arguments still needs Steam's command.
    return result.replace(/(WINEDLLOVERRIDES="[^"]*")/, "$1 %command%");
  }
  const command = before.includes("%command%") ? before : `%command%${before.trim() ? ` ${before.trim()}` : ""}`;
  return `WINEDLLOVERRIDES="dxgi=n,b" ${command}`;
}
