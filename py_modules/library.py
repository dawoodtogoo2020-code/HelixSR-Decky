"""Local library discovery. No shells, launcher execution or credential reads."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct


_DISCOVERY_SOURCES = frozenset({
    'steam', 'steam-shortcuts', 'heroic', 'legendary', 'lutris', 'imported',
})

# Public launcher choices. Values are the metadata collectors enabled for a scan.
LAUNCHER_SOURCES = {
    'heroic': frozenset({'heroic'}),
    'lutris': frozenset({'lutris'}),
    'legendary': frozenset({'legendary'}),
    'steam-shortcuts': frozenset({'steam-shortcuts'}),
    'all-launchers': frozenset({'heroic', 'lutris', 'legendary', 'steam-shortcuts'}),
}


def text(path, limit=2 << 20):
    try:
        with Path(path).open('rb') as f:
            return f.read(limit).decode('utf-8', errors='replace')
    except OSError:
        return ''


def vdf(source):
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', re.sub(r'(?m)^\s*//.*$', '', source))
    stack, root, key = [], {}, None
    current = root
    for word, brace in tokens:
        if brace == '{':
            if key is None:
                raise ValueError('Malformed VDF')
            child = {}
            current[key] = child
            stack.append(current)
            current, key = child, None
        elif brace == '}':
            if not stack or key is not None:
                raise ValueError('Malformed VDF')
            current, key = stack.pop(), None
        else:
            word = word.replace('\\"', '"').replace('\\\\', '\\')
            if key is None:
                key = word
            else:
                current[key], key = word, None
    if stack or key is not None:
        raise ValueError('Incomplete VDF')
    return root


def binary_vdf(data):
    """Steam shortcuts subset, bounded nesting and input size."""
    pos = 0

    def cstring():
        nonlocal pos
        end = data.find(b'\0', pos)
        if end < 0:
            raise ValueError('Truncated shortcut')
        out = data[pos:end].decode('utf-8', errors='replace')
        pos = end + 1
        return out

    def obj(depth=0):
        nonlocal pos
        if depth > 20:
            raise ValueError('Shortcut nesting limit')
        out = {}
        while pos < len(data):
            kind = data[pos]
            pos += 1
            if kind == 8:
                return out
            key = cstring()
            if kind == 0:
                value = obj(depth + 1)
            elif kind == 1:
                value = cstring()
            elif kind in (2, 3):
                if pos + 4 > len(data):
                    raise ValueError('Truncated shortcut value')
                value = struct.unpack_from('<I' if kind == 2 else '<f', data, pos)[0]
                pos += 4
            elif kind == 7:
                if pos + 8 > len(data):
                    raise ValueError('Truncated shortcut value')
                value = struct.unpack_from('<Q', data, pos)[0]
                pos += 8
            else:
                raise ValueError('Unsupported shortcut value type')
            out[key] = value
        raise ValueError('Truncated shortcut object')

    return obj()


def read_json(path):
    try:
        return json.loads(text(path))
    except (ValueError, TypeError):
        return {}


def read_launcher_json(path, source, warnings):
    """Read existing launcher metadata and distinguish absence from parse failure."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(text(path))
    except (ValueError, TypeError):
        warnings.append(f'{source}: Cannot parse {path}')
        return {}


def safe_root(path):
    """Only actual game directories, never system/home-wide roots."""
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.is_absolute() or not p.is_dir():
        raise ValueError('Select an existing absolute game folder')
    p = p.resolve()
    denied = [Path('/'), Path('/home'), Path.home().resolve(), Path('/usr'), Path('/etc'),
              Path('/var'), Path('/tmp'), Path('/run'), Path('/opt')]
    if p in denied or len(p.parts) < 3:
        raise ValueError('Select the individual game folder')
    if any(p == x or x in p.parents for x in (Path('/etc'), Path('/usr'), Path('/proc'), Path('/sys'), Path('/dev'))):
        raise ValueError('System directories cannot be imported')
    return p


def ident(source, folder):
    return source + ':' + hashlib.sha256(str(folder).encode()).hexdigest()[:16]


def steam_roots(home):
    h = Path(home)
    return [h / '.local/share/Steam', h / '.steam/steam', h / '.steam/root',
            h / '.var/app/com.valvesoftware.Steam/.local/share/Steam']


def lutris_database(path, warnings, max_rows=10000):
    """Read the small installed-Wine-game subset from an existing pga.db."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > 256 << 20:
            raise ValueError('database size limit')
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                                     timeout=0.1)
        try:
            connection.execute('PRAGMA query_only = ON')
            connection.execute('PRAGMA busy_timeout = 100')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(games)')}
            required = {'name', 'directory', 'configpath', 'installed', 'runner'}
            if not required <= columns:
                raise ValueError('unsupported games schema')
            rows = connection.execute(
                "SELECT name, directory, configpath FROM games "
                "WHERE installed = 1 AND runner = 'wine' AND configpath IS NOT NULL "
                "LIMIT ?", (max_rows + 1,)).fetchall()
        finally:
            connection.close()
        if len(rows) > max_rows:
            warnings.append(f'Lutris: {path}: installed game row limit exceeded')
            rows = rows[:max_rows]
    except (OSError, sqlite3.Error, ValueError):
        warnings.append(f'Lutris: Cannot read {path}')
        return None

    records = {}
    for name, directory, configpath in rows:
        if (not isinstance(configpath, str) or not configpath or
                Path(configpath).name != configpath or '/' in configpath or '\\' in configpath):
            warnings.append('Lutris: invalid installed game config path')
            continue
        if directory and not isinstance(directory, str):
            warnings.append(f'Lutris: {configpath}: game directory must be text')
            continue
        records[configpath] = {
            'name': name if isinstance(name, str) and name.strip() else configpath,
            'directory': directory or '',
        }
    return records


def discover(home, imported=(), sources=None):
    """Discover local games, optionally restricting which metadata sources are read."""
    if sources is None:
        enabled = _DISCOVERY_SOURCES
    else:
        try:
            enabled = frozenset({sources}) if isinstance(sources, str) else frozenset(sources)
        except TypeError:
            raise ValueError('Discovery sources must be names') from None
    unknown = enabled - _DISCOVERY_SOURCES
    if unknown:
        raise ValueError('Unknown discovery source: ' + ', '.join(sorted(map(str, unknown))))
    entries, seen, warnings, libraries, shortcuts_seen = {}, set(), [], {}, set()

    def add(source, folder, name, **metadata):
        try:
            p = safe_root(folder)
        except ValueError as e:
            warnings.append(f'{source}: {name}: {e}')
            return
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        gid = metadata.pop('id', ident(source, p))
        entries[gid] = dict(id=gid, name=str(name), folder=key, source=source, **metadata)

    for root in steam_roots(home) if enabled & {'steam', 'steam-shortcuts'} else ():
        if not root.is_dir():
            continue
        if 'steam' in enabled:
            paths = [root]
            try:
                records = vdf(text(root / 'steamapps/libraryfolders.vdf')).get('libraryfolders', {})
                for value in records.values():
                    if isinstance(value, dict) and value.get('path'):
                        paths.append(Path(value['path']))
                    elif isinstance(value, str) and Path(value).is_absolute():
                        paths.append(Path(value))
            except ValueError:
                warnings.append(f'Cannot parse {root}/steamapps/libraryfolders.vdf')
            for lib in paths:
                lib = lib.resolve()
                if str(lib) in libraries:
                    continue
                libraries[str(lib)] = True
                for manifest in sorted((lib / 'steamapps').glob('appmanifest_*.acf')):
                    try:
                        app = vdf(text(manifest)).get('AppState', {})
                        appid, directory = app.get('appid', ''), app.get('installdir', '')
                        if not appid.isdigit() or not directory or '/' in directory or '\\' in directory:
                            continue
                        # Installed Steam compatibility tools are not game-library entries.
                        if re.match(r'^(?:Proton(?: |$)|SteamLinuxRuntime|Steam Linux Runtime|Steamworks Shared|SteamVR)', directory):
                            continue
                        add('Steam', lib / 'steamapps/common' / directory, app.get('name', directory),
                            id='steam:' + appid, appid=appid, manifest=str(manifest),
                            state=int(app.get('StateFlags', 0)), build=app.get('buildid', ''),
                            library=str(lib), bytes_to_download=app.get('BytesToDownload', '0'),
                            bytes_downloaded=app.get('BytesDownloaded', '0'))
                    except (ValueError, OSError):
                        warnings.append(f'Cannot read {manifest.name}')
        for shortcuts in (root / 'userdata').glob('*/config/shortcuts.vdf') if 'steam-shortcuts' in enabled else ():
            if str(shortcuts.resolve()) in shortcuts_seen:
                continue
            shortcuts_seen.add(str(shortcuts.resolve()))
            try:
                data = shortcuts.read_bytes()
                if len(data) > 8 << 20:
                    raise ValueError('Shortcut file size limit')
                records = binary_vdf(data).get('shortcuts', {})
                for s in records.values():
                    if not isinstance(s, dict):
                        continue
                    name = s.get('AppName', s.get('appname', 'Steam shortcut'))
                    exe = str(s.get('Exe', s.get('exe', ''))).strip('"')
                    start = str(s.get('StartDir', s.get('startdir', ''))).strip('"')
                    shortcut_id = s.get('appid', s.get('AppId'))
                    metadata = dict(launch_options=s.get('LaunchOptions', ''))
                    if isinstance(shortcut_id, int):
                        metadata['appid'] = str(shortcut_id & 0xffffffff)
                    p = Path(exe)
                    # Wrappers/URIs are deliberately unresolved; no command execution.
                    if p.is_absolute() and p.suffix.lower() == '.exe' and p.is_file():
                        add('Steam shortcut', p.parent, name, **metadata)
                    elif start and Path(start).is_dir() and any(Path(start).glob('*.exe')):
                        add('Steam shortcut', start, name, **metadata)
                    else:
                        warnings.append(f'Steam shortcut: {name}: launcher/wrapper unresolved; import game folder')
            except (OSError, ValueError):
                warnings.append('A Steam shortcut file could not be parsed')

    h = Path(home)
    heroics = [h / '.config/heroic', h / '.var/app/com.heroicgameslauncher.hgl/config/heroic']
    for heroic in heroics if 'heroic' in enabled else ():
        for source in [heroic / 'gog_store/installed.json', heroic / 'nile_config/installed.json',
                       heroic / 'legendaryConfig/legendary/installed.json']:
            data = read_launcher_json(source, 'Heroic', warnings)
            games = data.get('installed', data.get('games', data)) if isinstance(data, dict) else data
            if isinstance(games, dict):
                games = list(games.values())
            if isinstance(games, (list, tuple)):
                for g in games:
                    if isinstance(g, dict):
                        folder = g.get('install_path', g.get('installPath'))
                        if folder is not None and not isinstance(folder, (str, os.PathLike)):
                            warnings.append('Heroic: install path must be text')
                        elif folder:
                            fallback = Path(folder).name
                            add('Heroic', folder, g.get('title', g.get('name', fallback)))
    legendary_files = [h / '.config/legendary/installed.json',
                       h / '.var/app/com.heroicgameslauncher.hgl/config/legendary/installed.json']
    for legendary in legendary_files if 'legendary' in enabled else ():
        data = read_launcher_json(legendary, 'Legendary', warnings)
        for g in data.values() if isinstance(data, dict) else []:
            if not isinstance(g, dict) or 'install_path' not in g:
                continue
            folder = g['install_path']
            if folder is not None and not isinstance(folder, (str, os.PathLike)):
                warnings.append('Legendary: install path must be text')
            elif folder:
                add('Legendary', folder, g.get('title', Path(folder).name))
    # Minimal scalar YAML extraction. No arbitrary YAML tags or code loading.
    native_db = h / '.local/share/lutris/pga.db'
    flatpak_db = h / '.var/app/net.lutris.Lutris/data/lutris/pga.db'
    lutris_roots = [
        (h / '.config/lutris/games', native_db),
        (h / '.local/share/lutris/games', native_db),
        (h / '.var/app/net.lutris.Lutris/config/lutris/games', flatpak_db),
        (h / '.var/app/net.lutris.Lutris/data/lutris/games', flatpak_db),
    ]
    lutris_records = {}
    for lutris, database in lutris_roots if 'lutris' in enabled else ():
        if database not in lutris_records:
            lutris_records[database] = lutris_database(database, warnings)
        for config in lutris.glob('*.yml'):
            source = text(config, 128 << 10)
            exe = re.search(r'(?m)^\s+exe:\s*[\'"]?([^\r\n]+?)\s*$', source)
            name = re.search(r'(?m)^name:\s*(.+)$', source)
            working = re.search(r'(?m)^\s+working_dir:\s*[\'"]?([^\r\n]+?)\s*$', source)
            prefix = re.search(r'(?m)^\s+prefix:\s*[\'"]?([^\r\n]+?)\s*$', source)
            database_records = lutris_records[database]
            if database_records is not None and config.stem not in database_records:
                continue
            record = (database_records or {}).get(config.stem, {})
            title = record.get('name') or (name[1].strip('"\'') if name else config.stem)
            resolved = None
            if exe:
                value = exe[1].strip().strip('"\'')
                executable = Path(value)
                if executable.is_absolute():
                    candidates = [executable]
                else:
                    bases = [record.get('directory', '')]
                    bases.extend(match[1].strip().strip('"\'') for match in (working, prefix) if match)
                    candidates = []
                    for base in bases:
                        if not base:
                            continue
                        base_path = h / base[2:] if base.startswith('~/') else Path(base)
                        if base_path.is_absolute():
                            candidates.append(base_path / executable)
                        else:
                            warnings.append(f'Lutris: {title}: relative base path ignored')
                resolved = next((p for p in candidates
                                 if p.suffix.lower() == '.exe' and p.is_file()), None)
            if resolved:
                add('Lutris', resolved.parent, title)
            elif record or (exe and Path(exe[1].strip().strip('"\'')).suffix.lower() == '.exe'):
                warnings.append(f'Lutris: {title}: Windows executable unresolved; import game folder')
    for record in imported if 'imported' in enabled else ():
        if isinstance(record, dict) and record.get('folder'):
            add('Imported', record['folder'], record.get('name', Path(record['folder']).name))
    return sorted(entries.values(), key=lambda x: x['name'].lower()), list(dict.fromkeys(warnings))


def discover_launcher(home, key):
    """Discover records for one supported launcher choice without running it."""
    try:
        sources = LAUNCHER_SOURCES[key]
    except (KeyError, TypeError):
        raise ValueError('Unknown launcher source: ' + str(key)) from None
    return discover(home, sources=sources)


def scan_tree(folder, depth=9, max_files=50000):
    root, result, count = Path(folder).resolve(), [], 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        p = Path(directory)
        level = len(p.relative_to(root).parts)
        dirs[:] = [d for d in dirs if d.lower() not in ('helixsr', '.git', 'node_modules')
                   and not (p / d).is_symlink()] if level < depth else []
        names = [n for n in files if not (p / n).is_symlink()]
        count += len(names)
        if count > max_files:
            raise ValueError('Game scan file limit exceeded')
        result.append((p, names))
    return result
