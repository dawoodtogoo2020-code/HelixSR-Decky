/** User-facing text for a caught error. Decky 3.3 rejects a failed backend call
 * with an empty-message PyError that keeps the exception only in pythonTraceback. */
export function errorMessage(error: unknown): string {
  const value = (error ?? {}) as { message?: unknown; pythonTraceback?: unknown; name?: unknown };
  if (typeof value.message === "string" && value.message) return value.message;
  if (typeof value.pythonTraceback === "string") {
    const last = value.pythonTraceback.split(/\r?\n/).map(line => line.trim()).filter(Boolean).pop();
    const text = last?.replace(/^[\w.]*(?:Error|Exception):\s*/, "");
    if (text) return text;
  }
  return String(error) || (typeof value.name === "string" && value.name) || "Unknown error";
}
