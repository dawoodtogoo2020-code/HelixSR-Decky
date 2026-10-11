"""Discover installed Steam Wine binaries without executing a runtime."""
import os
from pathlib import Path

from library import steam_roots, text, vdf


def _libraries(root):
    yield root
    try:
        records = vdf(text(root / 'steamapps/libraryfolders.vdf')).get('libraryfolders', {})
        if not isinstance(records, dict):
            return
        # Steam supports both legacy scalar paths and current nested records.
        for key in sorted(records, key=lambda key: (not key.isdigit(), int(key) if key.isdigit() else key)):
            if not key.isdigit():
                continue
            record = records[key]
            value = record.get('path') if isinstance(record, dict) else record
            if isinstance(value, str) and value:
                path = Path(value)
                if path.is_absolute():
                    yield path
    except (OSError, ValueError, RuntimeError):
        return


def _tools(library):
    # One directory level only: never walk arbitrary game or home trees.
    for parent, pattern in ((library / 'steamapps/common', 'Proton*'),
                            (library / 'compatibilitytools.d', '*')):
        try:
            children = sorted(parent.glob(pattern), key=lambda p: (p.name.casefold(), p.name))
            for child in children:
                if child.is_dir():
                    yield child
        except (OSError, RuntimeError):
            continue


def wine_candidates(home):
    """Return resolved executable Wine files, native Steam before Flatpak Steam.

    This only identifies files. A Flatpak runtime may still require its sandbox
    environment to launch; existence does not establish host compatibility.
    """
    result, seen_files, seen_libraries = [], set(), set()
    for root in steam_roots(Path(home).resolve()):
        for library in _libraries(root):
            try:
                library = library.resolve()
                if library in seen_libraries or not library.is_dir():
                    continue
                seen_libraries.add(library)
                for tool in _tools(library):
                    for layout in ('files/bin/wine', 'dist/bin/wine'):
                        candidate = tool / layout
                        try:
                            candidate = candidate.resolve()
                            if (candidate in seen_files or not candidate.is_file() or
                                    (os.name == 'posix' and not os.access(candidate, os.X_OK))):
                                continue
                        except (OSError, RuntimeError):
                            continue
                        seen_files.add(candidate)
                        result.append(candidate)
            except (OSError, RuntimeError):
                continue
    return result
