type LibraryGame = {
  compatibility: string;
  managed?: boolean;
  recovery_available?: boolean;
  executable_selection_needed?: boolean;
  installation_status?: { selectable: boolean };
};

export function librarySelectable(game: LibraryGame) {
  return game.installation_status?.selectable ?? (game.compatibility === "candidate" ||
    !!game.managed || !!game.recovery_available || !!game.executable_selection_needed);
}

export function libraryStatus(games: LibraryGame[] | undefined, loading = false, failed = false) {
  const total = games?.length || 0;
  const unavailable = games?.filter(g => !librarySelectable(g)).length || 0;
  const candidates = games?.filter(g => g.compatibility === "candidate").length || 0;
  if (failed) return {summary: "Library scan failed", hint: games
    ? `Showing the previous scan (${total} games). Fix the error below, then refresh the library.`
    : "The library could not be read. Fix the error below, then refresh the library."};
  if (loading || !games) return {summary: games ? "Refreshing library…" : "Detecting installed games…", hint: ""};
  return {
    summary: `${total} games found · ${candidates} installation candidates · ${unavailable} unavailable`,
    hint: !total
      ? "No installed game folders were found. Check Discovery notes below. Open Steam and check that your library drive is mounted, then refresh. For other launchers, use Import Games From or import the individual game folder."
      : unavailable === total
      ? "Your games were found, but none is available for installation yet. Select a game to review its reason and next step."
      : unavailable ? "Some games are unavailable for installation. Select them to review their reasons." : "",
  };
}
