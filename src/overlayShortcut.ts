// Scaler stores a Windows virtual-key code, even when the game runs under Proton.
export function overlayShortcut(raw?: string): { key: string | null; label: string } {
  const value = (raw || "auto").trim().toLowerCase();
  if (value === "auto") return { key: "Insert", label: "Insert (default)" };
  if (value === "-1") return { key: null, label: "Shortcut disabled in Scaler" };
  const code = /^(?:0x[0-9a-f]+|\d+)$/.test(value) ? Number(value) : NaN;
  const names: Record<number, string> = { 8: "Backspace", 9: "Tab", 13: "Enter", 19: "Pause", 20: "Caps Lock",
    27: "Escape", 32: "Space", 33: "Page Up", 34: "Page Down", 35: "End", 36: "Home",
    37: "Left", 38: "Up", 39: "Right", 40: "Down", 45: "Insert", 46: "Delete" };
  const key = names[code] || (code >= 112 && code <= 135 ? `F${code - 111}`
    : (code >= 48 && code <= 57) || (code >= 65 && code <= 90) ? String.fromCharCode(code) : null);
  return { key, label: key || `Custom key (${raw})` };
}
