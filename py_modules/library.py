"""Local library discovery. No shells, launcher execution or credential reads."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct


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


def discover(home, imported=()):
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

    for root in steam_roots(home):
        if not root.is_dir():
            continue
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
        for shortcuts in (root / 'userdata').glob('*/config/shortcuts.vdf'):
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
    for heroic in heroics:
        for source in [heroic / 'gog_store/installed.json', heroic / 'nile_config/installed.json',
                       heroic / 'legendaryConfig/legendary/installed.json']:
            data = read_json(source)
            games = data.get('installed', data.get('games', data)) if isinstance(data, dict) else data
            if isinstance(games, dict):
                games = games.values()
            if isinstance(games, (list, tuple)) or hasattr(games, '__iter__'):
                for g in games:
                    if isinstance(g, dict):
                        folder = g.get('install_path', g.get('installPath'))
                        if folder:
                            add('Heroic', folder, g.get('title', g.get('name', Path(folder).name)))
    for legendary in [h / '.config/legendary/installed.json', h / '.var/app/com.heroicgameslauncher.hgl/config/legendary/installed.json']:
        data = read_json(legendary)
        for g in data.values() if isinstance(data, dict) else []:
            if isinstance(g, dict) and g.get('install_path'):
                add('Legendary', g['install_path'], g.get('title', Path(g['install_path']).name))
    # Minimal scalar YAML extraction. No arbitrary YAML tags or code loading.
    for lutris in [h / '.config/lutris/games', h / '.var/app/net.lutris.Lutris/config/lutris/games']:
        for config in lutris.glob('*.yml'):
            source = text(config, 128 << 10)
            exe = re.search(r'(?m)^\s+exe:\s*[\'"]?([^\r\n]+?)\s*$', source)
            name = re.search(r'(?m)^name:\s*(.+)$', source)
            if exe:
                p = Path(exe[1].strip().strip('"\''))
                if p.is_absolute() and p.is_file() and p.suffix.lower() == '.exe':
                    add('Lutris', p.parent, name[1].strip('"\'') if name else config.stem)
    for record in imported:
        add('Imported', record['folder'], record.get('name', Path(record['folder']).name))
    return sorted(entries.values(), key=lambda x: x['name'].lower()), list(dict.fromkeys(warnings))


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
