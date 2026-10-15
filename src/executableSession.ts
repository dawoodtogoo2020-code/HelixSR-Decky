// Ephemeral, in-memory record of the executable the user explicitly chose for
// the currently viewed game. Survives component remounts via the exported
// singleton, but is never persisted and never sourced from backend heuristics.

export interface ExecutableSessionGame {
  id: string;
  managed?: boolean;
  route?: string;
  executable_choices?: { path: string }[];
}

export class ExecutableSession {
  private gameId: string | undefined = undefined;
  private path: string | undefined = undefined;

  selectGame(id: string): void {
    if (id !== this.gameId) {
      this.gameId = id;
      this.path = undefined;
    }
  }

  choose(id: string, path: string): void {
    if (typeof id !== "string" || id.length === 0) {
      throw new TypeError("A game id is required to choose an executable.");
    }
    if (typeof path !== "string" || path.trim().length === 0) {
      throw new TypeError("An executable path must not be empty.");
    }
    this.selectGame(id);
    this.path = path;
  }

  get(id: string): string | undefined {
    return id === this.gameId ? this.path : undefined;
  }

  clear(id: string): void {
    if (id === this.gameId) {
      this.path = undefined;
    }
  }

  reconcile(game: ExecutableSessionGame): void {
    if (!game || game.id !== this.gameId || this.path === undefined) {
      return;
    }
    if (game.managed === true) {
      this.path = undefined;
      return;
    }
    if (game.route !== undefined && game.route !== "optiscaler") {
      this.path = undefined;
      return;
    }
    // Only a provided array is authoritative; an omitted list preserves the choice.
    if (Array.isArray(game.executable_choices)) {
      const selected = this.path;
      const stillOffered = game.executable_choices.some(
        (choice) => choice != null && choice.path === selected,
      );
      if (!stillOffered) {
        this.path = undefined;
      }
    }
  }
}

export const executableSession = new ExecutableSession();
