"""HelixSR package and per-game transactions, run as the Deck user."""
import contextlib
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import platform
import ssl
from functools import lru_cache
from library import discover, discover_launcher, safe_root, scan_tree, text
from awareness import awareness, active_processes, text_tail

REPO = 'lonewolf0622/HelixSR'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
DLL = 'amd_fidelityfx_dx12.dll'
NETWORK = ('helixsr_weights.bin', 'helixsr_kernels.pak')
AMD_FG = 'amd_fidelityfx_framegeneration_dx12.dll'
INPUTS = {'nvngx_dlss.dll': 'DLSS', 'libxess.dll': 'XeSS',
          'ffx_fsr2_api_x64.dll': 'FSR 2', 'ffx_fsr2_api_dx12_x64.dll': 'FSR 2'}
ANTI = ('easyanticheat', 'battleye', 'beclient', 'equ8', 'faceit', 'vanguard')
LICENSE_REV = 'helixsr-local-nvidia-network-2026-10'
RELEASE_POLICY = 2


def load_release(settings):
    try:
        value = load_json(Path(settings) / 'release.json')
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def validate_release(release):
    if not isinstance(release, dict):
        raise ValueError('Invalid upstream release metadata')
    tag = 'v' + release.get('version', '') if isinstance(release.get('version'), str) else ''
    version(tag)
    digest, size = release.get('sha256'), release.get('size')
    if (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
            or type(size) is not int or not 0 < size <= 512 << 20
            or release.get('url') != f'https://github.com/{REPO}/releases/download/{tag}/HelixSR-{tag[1:]}.zip'
            or release.get('page') != f'https://github.com/{REPO}/releases/tag/{tag}'):
        raise ValueError('Invalid official release URL, size or SHA256 digest')
    return release


def license_key(release):
    if not isinstance(release, dict) or not release.get('version') or not release.get('sha256'):
        return None
    return {'terms': LICENSE_REV, 'version': release['version'], 'release_sha256': release['sha256']}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp-' + uuid.uuid4().hex)
    with tmp.open('w', encoding='utf-8') as f:
        f.write(json.dumps(value, indent=2) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    if os.name == 'posix':
        fd = os.open(p.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def durable_directory(path):
    """Persist each new directory entry before a recovery journal depends on it."""
    missing, parent = [], Path(path)
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir()
        sync_directory(directory.parent)


def durable_copy(src, dst, expected=None):
    """Persist verified recovery bytes and every newly created directory entry."""
    src, dst = Path(src), Path(dst)
    durable_directory(dst.parent)
    expected = expected or sha(src)
    shutil.copy2(src, dst)
    if sha(dst) != expected or sha(src) != expected:
        raise ValueError('Recovery copy changed or failed verification')
    # POSIX permits syncing a read-only descriptor, preserving original modes.
    # Windows' CRT requires a writable descriptor for its fsync implementation.
    with dst.open('rb' if os.name == 'posix' else 'r+b') as stream:
        os.fsync(stream.fileno())
    sync_directory(dst.parent)


def https_context():
    # Decky's bundled Python may retain a build-host CA path. Use SteamOS's trust store.
    if os.name == 'posix':
        for path in ('/etc/ssl/certs/ca-certificates.crt', '/etc/ssl/cert.pem'):
            if Path(path).is_file():
                return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {} if default is None else default


def version(value):
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not m:
        raise ValueError('Only stable semantic-version releases are supported')
    return tuple(map(int, m.groups()))


def pe_info(path):
    p = Path(path)
    s = p.stat()
    return _pe_info(str(p), s.st_size, s.st_mtime_ns)


@lru_cache(maxsize=512)
def _pe_info(path, size, modified):
    with Path(path).open('rb') as f:
        data = f.read(4 << 20)
    if data[:2] != b'MZ' or len(data) < 64:
        return dict(arch='not-pe', dx12=False, ffx=False, helix=False)
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    arch = 'unknown'
    if offset + 6 < len(data) and data[offset:offset+4] == b'PE\0\0':
        machine = struct.unpack_from('<H', data, offset + 4)[0]
        arch = 'x64' if machine == 0x8664 else 'unsupported'
    exports, imports = pe_symbols(path, data, offset, size)
    marker = re.search(rb'HelixSR (\d+\.\d+\.\d+)', data)
    return dict(arch=arch, dx12='d3d12.dll' in imports,
                ffx=all(x in exports for x in ['ffxCreateContext', 'ffxDestroyContext', 'ffxDispatch', 'ffxQuery']),
                helix=bool(marker), helix_version=marker.group(1).decode() if marker else None)


def pe_symbols(path, header, offset, size):
    """Read bounded PE tables by RVA, including tables past the initial scan window."""
    exports, imports = set(), set()
    try:
        if offset + 24 > len(header) or header[offset:offset+4] != b'PE\0\0':
            return exports, imports
        sections = struct.unpack_from('<H', header, offset + 6)[0]
        optional_size = struct.unpack_from('<H', header, offset + 20)[0]
        optional = offset + 24
        magic = struct.unpack_from('<H', header, optional)[0]
        dd = 112 if magic == 0x20b else 96 if magic == 0x10b else 0
        table = optional + optional_size
        if not dd or optional_size < dd + 16 or not 1 <= sections <= 96 or table + sections * 40 > len(header):
            return exports, imports
        mappings = []
        for i in range(sections):
            virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', header, table + i * 40 + 8)
            if raw + raw_size > size:
                return exports, imports
            mappings.append((rva, raw_size, raw))
        with Path(path).open('rb') as stream:
            def read_rva(rva, length):
                for start, count, raw in mappings:
                    if start <= rva and rva + length <= start + count:
                        stream.seek(raw + rva - start)
                        out = stream.read(length)
                        if len(out) != length:
                            raise ValueError('Truncated PE table')
                        return out
                raise ValueError('PE RVA outside mapped file data')

            def string_rva(rva):
                for start, count, raw in mappings:
                    if start <= rva < start + count:
                        out = read_rva(rva, min(512, start + count - rva))
                        if b'\0' not in out:
                            raise ValueError('Unterminated PE symbol')
                        return out.split(b'\0', 1)[0].decode('ascii')
                raise ValueError('PE string RVA outside file')

            export_rva, export_size = struct.unpack_from('<II', header, optional + dd)
            if export_rva and export_size >= 40:
                directory = read_rva(export_rva, 40)
                names_count, names_rva = struct.unpack_from('<II', directory, 24)
                # Offset28 is AddressOfFunctions; AddressOfNames is offset32.
                names_rva = struct.unpack_from('<I', directory, 32)[0]
                if names_count > 8192:
                    raise ValueError('PE export name limit')
                names = read_rva(names_rva, names_count * 4) if names_count else b''
                for i in range(names_count):
                    exports.add(string_rva(struct.unpack_from('<I', names, i * 4)[0]))
            import_rva, import_size = struct.unpack_from('<II', header, optional + dd + 8)
            if import_rva:
                for i in range(min(import_size // 20, 512)):
                    entry = read_rva(import_rva + i * 20, 20)
                    if not any(entry):
                        break
                    imports.add(string_rva(struct.unpack_from('<I', entry, 12)[0]).lower())
    except (ValueError, struct.error, UnicodeError):
        return set(), set()
    return exports, imports


def checked_path(root, relative):
    p = Path(root) / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Unsafe managed path')
    current = p
    while current != Path(root):
        if current.is_symlink():
            raise ValueError(f'Symlink in managed path: {relative}')
        current = current.parent
    if Path(root).resolve() not in p.resolve().parents:
        raise ValueError('Managed path escapes game')
    return p


def safe_extract(archive, destination):
    total, seen = 0, set()
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > 30000:
            raise ValueError('Archive member limit')
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            p = PurePosixPath(name)
            normalized = str(p)
            total += info.file_size
            if (p.is_absolute() or '..' in p.parts or ':' in name or not p.parts or
                    stat.S_ISLNK(info.external_attr >> 16) or total > 2 << 30 or normalized in seen or
                    info.compress_size and info.file_size / info.compress_size > 1000):
                raise ValueError('Unsafe or oversized release archive')
            seen.add(normalized)
            target = Path(destination).joinpath(*p.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                mode = info.external_attr >> 16
                target.chmod(0o755 if mode & 0o111 else 0o644)


class Manager:
    def __init__(self, home, settings):
        self.home, self.settings = Path(home), Path(settings)
        self.settings.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.entries, self.previews, self.jobs = {}, {}, {}
        self.worker = None
        self.cancel = threading.Event()
        self.process = None
        self.transaction = None
        self.cfg = load_json(self.settings / 'settings.json', {'imports': [], 'packages': {}, 'license': None})

    def save(self):
        atomic_json(self.settings / 'settings.json', self.cfg)

    def companion(self, game):
        root = safe_root(game['folder'])
        c = root.parent / (root.name + ' Mod Files') / 'HelixSR-Decky'
        if c.is_symlink() or c.parent.is_symlink():
            raise ValueError('Companion directory cannot be a symlink')
        return c

    def record_path(self, game):
        return self.companion(game) / 'records/install.json'

    def record(self, game):
        return load_json(self.record_path(game))

    def package(self, game):
        # Packages remain on the same filesystem as the selected game.
        choices = []
        for key, record in self.cfg.get('packages', {}).items():
            p = Path(record['path'])
            try:
                if p.is_dir() and p.stat().st_dev == Path(game['folder']).stat().st_dev:
                    choices.append((version(record['version']), p, record))
            except (ValueError, OSError):
                continue
        if not choices:
            return None
        return max(choices, key=lambda x: (x[0], x[2].get('prepared_at', 0)))

    def refresh(self):
        entries, warnings = discover(self.home, self.cfg.get('imports', []))
        self.entries = {x['id']: x for x in entries}
        games = []
        for game in entries:
            games.append(self.assess_safe(game, detailed=False))
        release = load_release(self.settings)
        return dict(games=games, warnings=warnings, release=release,
                    license_accepted=bool(self.cfg.get('license')) and self.cfg.get('license') == license_key(release),
                    jobs=list(self.jobs.values()))

    def import_launcher(self, launcher):
        # Read installed records only. Never run a launcher or change its files.
        found, notes = discover_launcher(self.home, launcher)
        before = {entry['folder'] for entry in self.entries.values()}
        result = self.refresh()
        folders = {entry['folder'] for entry in found}
        matched = [game for game in result['games'] if game['folder'] in folders]
        result['launcher_import'] = dict(
            launcher=launcher, found=len(matched),
            added=sum(game['folder'] not in before for game in matched),
            candidates=sum(game['compatibility'] == 'candidate' for game in matched),
            unavailable=sum(game['compatibility'] != 'candidate' for game in matched),
            game_ids=[game['id'] for game in matched], warnings=notes)
        result['warnings'] = list(dict.fromkeys(result['warnings'] + notes))
        return result

    def recovery_available(self, game):
        try:
            return (self.companion(game) / 'transaction/journal.json').is_file()
        except (OSError, ValueError):
            return False

    def assess_safe(self, game, detailed=True):
        try:
            return self.assess(game, detailed=detailed)
        except (OSError, ValueError) as e:
            return dict(**game, compatibility='blocked', reasons=[str(e)], route=None,
                        managed=False, enabled=False, inputs=[],
                        recovery_available=self.recovery_available(game),
                        optiscaler={'present': False, 'involved': False, 'helix_configured': False,
                                    'runtime': 'unknown', 'dlls': []},
                        framegen=[], framegen_summary='No supported per-game evidence',
                        helix_runtime='unknown', launch_options=game.get('launch_options', ''))

    def get_game(self, gid):
        if gid not in self.entries:
            self.refresh()
        if gid not in self.entries:
            raise ValueError('Game disappeared. Refresh library.')
        return self.entries[gid]

    def assess(self, game, detailed=True):
        root = safe_root(game['folder'])
        tree = scan_tree(root)
        names = [(d / n, n.lower()) for d, ns in tree for n in ns]
        inputs = sorted({INPUTS[n] for _, n in names if n in INPUTS})
        targets = [p for p, n in names if n == 'amd_fidelityfx_upscaler_dx12.dll']
        targets = targets or [p for p, n in names if n == DLL]
        exes = [p for p, n in names if n.endswith('.exe') and
                not re.search(r'launcher|crash|setup|redist|unins|helper|easyanticheat|beservice', n)]
        exes.sort(key=lambda p: (p.name.lower().endswith('-win64-shipping.exe'), p.stat().st_size), reverse=True)
        main = exes[0] if exes else None
        runtime_targets = [p for p in targets if p.parent == root or main and p.parent == main.parent]
        if runtime_targets:
            targets = runtime_targets
        direct_legacy = any(pe_info(p)['helix'] for p in targets)
        rec = self.record(game)
        native_api = bool(targets) and all(pe_info(p)['ffx'] for p in targets)
        route = rec.get('route') or ('direct' if native_api else 'optiscaler' if inputs and main else
                                    'direct' if targets else None)
        target = Path(rec['target']) if rec else main.parent if main else None
        reasons, blocked = [], []
        if platform.machine().lower() not in ('x86_64', 'amd64'):
            blocked.append('HelixSR requires an x86_64 host')
        if os.name == 'posix' and os.geteuid() == 0:
            blocked.append('Plugin must run as the Steam user, without root permissions')
        if not route:
            reasons.append('No supported DLSS, XeSS, FSR 2 or native FSR 3.1 DLL detected')
        if route == 'direct':
            for p in targets:
                info = pe_info(p)
                if info['arch'] != 'x64' or not info['ffx']:
                    blocked.append(f'{p.name}: expected x64 FidelityFX API not found')
        if main and pe_info(main)['arch'] != 'x64':
            blocked.append('Main executable is not x64 Windows PE (32-bit, native Linux or unknown architecture)')
        if route == 'optiscaler' and not any(pe_info(p)['dx12'] for p in exes):
            reasons.append('DX12 is not confirmed by executable imports; confirm the game runs DX12 before installation')
        directory_names = [str(d.relative_to(root)).lower() for d, _ in tree]
        if any(any(a in n for a in ANTI) for _, n in names) or any(any(a in n for a in ANTI) for n in directory_names):
            blocked.append('Anti-cheat files detected; injection is blocked')
        if game.get('manifest'):
            from library import vdf
            manifest = vdf(text(game['manifest'])).get('AppState', {})
            state = int(manifest.get('StateFlags', 0))
            game = dict(game, build=manifest.get('buildid', ''), state=state)
            if state != 4:
                blocked.append('Steam install/update is not complete (StateFlags must be 4)')
            downloading = Path(game['library']) / 'steamapps/downloading' / str(game['appid'])
            if downloading.is_dir() and any(downloading.iterdir()):
                blocked.append('Steam download staging exists for this game')
        if route and active_processes(root, game.get('appid', '')):
            blocked.append('Game is running; close it before any file changes')
        legacy = bool(direct_legacy and not rec)
        if not rec and route == 'direct' and not legacy:
            if any(p.with_name(p.stem + '.original.dll').exists() for p in targets):
                blocked.append('Unmanaged original DLL backup exists; review it before installation')
        if not rec and route == 'optiscaler' and target:
            occupied = [n for n in ('dxgi.dll', 'winmm.dll', 'version.dll', 'OptiScaler.ini', 'fakenvapi.dll')
                        if (target / n).exists() or (target / n).is_symlink()]
            helix_dir = target / 'HelixSR'
            # Removal retains runtime logs. An empty/log-only directory contains no injector.
            if helix_dir.is_symlink() or (helix_dir.exists() and
                    (not helix_dir.is_dir() or any(p.name.lower() != 'helixsr.log' or
                     p.is_symlink() or not p.is_file() for p in helix_dir.iterdir()))):
                occupied.append('HelixSR')
            if occupied:
                blocked.append('Existing unmanaged injector/configuration: ' + ', '.join(occupied))
        if legacy:
            reasons.append('Existing direct HelixSR installation: explicit import is required before management')
        if rec:
            if game.get('build') and rec.get('game_build') and game['build'] != rec['game_build']:
                blocked.append('Steam build changed; installation needs review')
            for rel, expected in rec['current'].items():
                p = checked_path(root, rel)
                actual = sha(p) if p.is_file() else None
                if actual != expected:
                    blocked.append('Managed files changed, possibly a game update. Restore through Steam or resolve conflict first: ' + rel)
        # Symlink candidates may hide API files and must never be mutated.
        for p in targets + ([main] if main else []):
            checked_path(root, str(p.relative_to(root)))
        aware = awareness(dict(game, managed=bool(rec), enabled=rec.get('enabled', False)), tree, self.home, route, target)
        package = self.package(game)
        data = dict(game, compatibility='blocked' if blocked else 'candidate' if route else 'unsupported',
                    reasons=blocked + reasons, route=route, inputs=inputs, target=str(target) if target else None,
                    targets=[str(p) for p in targets], main_exe=str(main) if main else None,
                    managed=bool(rec), enabled=rec.get('enabled', False), installed_version=rec.get('version') or
                    next((pe_info(p).get('helix_version') for p in targets if pe_info(p)['helix']), None),
                    legacy=legacy, package_version=package[2]['version'] if package else None,
                    recovery_available=self.recovery_available(game),
                    dx12_confirmation_needed=route == 'optiscaler' and not any(pe_info(p)['dx12'] for p in exes),
                    **aware)
        if not detailed:
            data.pop('logs', None)
        return data

    def import_folder(self, folder, name=''):
        return self.import_folders([folder], name)

    def import_folders(self, folders, name=''):
        if not isinstance(folders, list) or not 1 <= len(folders) <= 100:
            raise ValueError('Choose between one and 100 game folders')
        additions = []
        for folder in folders:
            p = safe_root(folder)
            if not any(n.lower().endswith('.exe') for _, ns in scan_tree(p) for n in ns):
                raise ValueError('No Windows game executable found in folder: ' + str(p))
            additions.append({'folder': str(p), 'name': str(name or p.name)[:200]})
        # Validate the whole selection before saving any import.
        merged = {x['folder']: x for x in self.cfg['imports']}
        merged.update({x['folder']: x for x in additions})
        self.cfg['imports'] = list(merged.values())
        self.save()
        return self.refresh()

    def forget(self, gid):
        g = self.get_game(gid)
        if self.record(g):
            raise ValueError('Remove managed HelixSR before forgetting its folder')
        self.cfg['imports'] = [x for x in self.cfg['imports'] if x['folder'] != g['folder']]
        self.save()
        return self.refresh()

    def accept_license(self, accepted):
        release = self.check_update() if accepted else {}
        if accepted and release.get('error'):
            raise ValueError(release['error'])
        key = license_key(release) if accepted else None
        if accepted and not key:
            raise ValueError('Check upstream release metadata before accepting preparation terms')
        self.cfg['license'] = key
        self.save()
        return bool(accepted)

    def check_update(self, force=False):
        old = load_release(self.settings)
        valid_cache = False
        try:
            validate_release(old)
            valid_cache = old.get('metadata_policy') == RELEASE_POLICY
        except (ValueError, TypeError):
            pass
        if (not force and valid_cache and not old.get('error')
                and isinstance(old.get('checked_at'), (int, float))
                and time.time() - old['checked_at'] < 6 * 3600):
            return old
        headers = {'User-Agent': 'HelixSR-Decky/0.1', 'Accept': 'application/vnd.github+json'}
        if valid_cache and isinstance(old.get('etag'), str):
            headers['If-None-Match'] = old['etag']
        try:
            with urllib.request.urlopen(urllib.request.Request(API, headers=headers), timeout=20, context=https_context()) as response:
                if response.geturl() != API:
                    raise ValueError('Unexpected upstream metadata redirect')
                raw = response.read((2 << 20) + 1)
                if len(raw) > 2 << 20:
                    raise ValueError('Upstream metadata is too large')
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
                    raise ValueError('Expected an official stable HelixSR release')
                tag = data['tag_name']
                if not isinstance(tag, str):
                    raise ValueError('Invalid release tag')
                version(tag)
                release_version = tag.removeprefix('v')
                if not isinstance(data.get('assets'), list):
                    raise ValueError('Invalid upstream assets')
                asset = next((x for x in data['assets'] if isinstance(x, dict)
                              and x.get('name') == f'HelixSR-{release_version}.zip'), None)
                if (not asset or not isinstance(asset.get('digest'), str)
                        or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', asset['digest'])):
                    raise ValueError('Official release lacks a usable SHA256 asset digest')
                current = dict(version=release_version, url=asset['browser_download_url'],
                               sha256=asset['digest'][7:].lower(), size=asset['size'],
                               checked_at=time.time(), etag=response.headers.get('ETag'),
                               page=data['html_url'], error=None, metadata_policy=RELEASE_POLICY,
                               asset_id=asset.get('id'), asset_updated_at=asset.get('updated_at'))
                validate_release(current)
                atomic_json(self.settings / 'release.json', current)
                return current
        except urllib.error.HTTPError as e:
            if e.code == 304 and valid_cache:
                old['checked_at'], old['error'] = time.time(), None
                old.pop('failed_at', None)
                atomic_json(self.settings / 'release.json', old)
                return old
            else:
                old['error'] = f'GitHub returned HTTP {e.code}; reconnect or retry later to check the latest HelixSR'
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as e:
            old['error'] = str(e)
        # A latest-tag redirect cannot prove which same-version ZIP is current.
        # Keep the error visible instead of inventing an obsolete SHA or size.
        if not valid_cache:
            old = {'error': old['error']}
        old['failed_at'] = time.time()
        atomic_json(self.settings / 'release.json', old)
        return old

    def preview_latest(self, gid, dx12_confirmed=False):
        with self.lock:
            game = self.get_game(gid)
            data = self.assess(game)
            if data['compatibility'] != 'candidate':
                raise ValueError('; '.join(data['reasons']))
            if data['dx12_confirmation_needed'] and not dx12_confirmed:
                raise ValueError('Confirm the game uses DirectX 12')
            if data['legacy']:
                # Existing native installations need the same original-file checks as explicit adoption.
                self.previews.pop(self.preview(gid, 'adopt', dx12_confirmed)['token'], None)
            token = uuid.uuid4().hex
            self.previews[token] = dict(game=gid, action='latest', expires=time.time()+120,
                                       fingerprint=self.fingerprint(game, data, include_package=False))
            return dict(token=token, name=game['name'], action='latest', route=data['route'],
                        files=self.planned_paths(game, data, 'latest'),
                        select_upscaler='AMD FSR' if data['route'] == 'direct' else 'DLSS (or XeSS/FSR input)',
                        warning='Download required files, prepare the local network and install or update HelixSR for this game. Existing native HelixSR is imported first. Close the game. Frame generation is preserved.')

    def execute_latest(self, token):
        with self.lock:
            preview = self.previews.get(token)
            if not preview or preview.get('action') != 'latest' or time.time() > preview['expires']:
                raise ValueError('Installation review expired; select Install or Update again')
            job = self.start_job('install_latest', preview['game'], preview)
            self.previews.pop(token, None)
            return job

    def start_job(self, kind, gid, preview=None):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Another operation is running')
            game = self.get_game(gid)
            if kind not in ('prepare', 'install_latest'):
                raise ValueError('Unsupported background operation')
            release = load_release(self.settings)
            if not self.cfg.get('license') or self.cfg.get('license') != license_key(release):
                raise ValueError('Accept local network preparation terms first')
            self.cancel.clear()
            job = {'id': uuid.uuid4().hex, 'kind': kind, 'game': game['name'], 'gid': gid, 'state': 'running',
                   'message': 'Starting', 'started_at': time.time(), 'log': ''}
            self.jobs[job['id']] = job

            def run():
                try:
                    self.prepare(game, job)
                    if kind == 'install_latest':
                        if self.cancel.is_set():
                            raise ValueError('Cancelled before installation')
                        with self.lock:
                            data = self.assess(game)
                            if data['compatibility'] != 'candidate' or self.fingerprint(game, data, include_package=False) != preview['fingerprint']:
                                raise ValueError('Game changed during preparation or is running. Close it and review again.')
                            job['message'] = 'Installing HelixSR and verifying game files'
                            if data['legacy']:
                                self.mutate(game, data, 'adopt')
                                data = self.assess(game)
                            result = self.mutate(game, data, 'update' if self.record(game) else 'install')
                            job['result'] = result
                        job['state'], job['message'] = 'completed', result['message']
                    else:
                        job['state'], job['message'] = 'completed', 'Package and local network verified'
                except Exception as e:
                    job['state'] = 'cancelled' if self.cancel.is_set() else 'failed'
                    job['message'] = str(e)
                finally:
                    job['ended_at'] = time.time()
                    atomic_json(self.companion(game) / 'records' / ('job-' + job['id'] + '.json'), job)
                    self.process = None
            self.worker = threading.Thread(target=run, daemon=True)
            self.worker.start()
            return dict(job)

    def cancel_job(self, jid):
        job = self.jobs.get(jid)
        if not job or job['state'] != 'running':
            return False
        self.cancel.set()
        if self.process and self.process.poll() is None:
            import signal
            os.killpg(self.process.pid, signal.SIGTERM)
        return True

    def prepare(self, game, job):
        if os.name == 'posix' and os.geteuid() == 0:
            raise ValueError('Refusing preparation as root')
        release = self.check_update(True)
        if release.get('error') or not release.get('version'):
            raise ValueError(release.get('error', 'Check upstream updates first'))
        if self.cfg.get('license') != license_key(release):
            raise ValueError('Upstream release changed; review and accept its terms before preparation')
        cached = self.package(game)
        if cached and cached[2]['version'] == release['version'] and cached[2].get('release_sha256') == release['sha256']:
            if all((cached[1] / name).is_file() and sha(cached[1] / name) == digest
                   for name, digest in cached[2]['files'].items()):
                job['message'] = 'Reusing the verified prepared package on this drive'
                return
        companion = self.companion(game)
        work = companion / 'staging' / job['id']
        work.mkdir(parents=True, exist_ok=False)
        archive = work / 'release.zip'
        job['message'] = 'Downloading official release'
        try:
            if shutil.disk_usage(companion).free < (3 << 30):
                raise ValueError('At least 3 GiB free space is required for preparation')
            with urllib.request.urlopen(urllib.request.Request(release['url'], headers={'User-Agent': 'HelixSR-Decky'}), timeout=30, context=https_context()) as response, archive.open('wb') as out:
                size = 0
                while True:
                    if self.cancel.is_set():
                        raise ValueError('Cancelled')
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > release['size']:
                        raise ValueError('Release exceeds advertised size')
                    out.write(chunk)
            if size != release['size'] or sha(archive) != release['sha256']:
                raise ValueError('Release SHA256 or size mismatch; upstream may have replaced the archive. Check for updates and retry')
            safe_extract(archive, work / 'unpacked')
            archive.unlink()
            package = work / 'unpacked' / ('HelixSR-' + release['version'])
            for name in ['LICENSE', 'LICENSE-APACHE-2.0', 'THIRD_PARTY_NOTICES.md', DLL,
                         'helixsr-setup.sh', 'setup/helixsr_setup.py', 'setup/helixsr_install.py',
                         'optiscaler/OptiScaler.dll', 'optiscaler/OptiScaler.ini']:
                if not (package / name).is_file():
                    raise ValueError('Unexpected upstream package layout: ' + name)
            # Apache-licensed setup adaptation: stop before its interactive game installer.
            # Complete official release is kept; compiled parts are never patched here.
            setup = (package / 'helixsr-setup.sh').read_text()
            marker = '# --- games ---'
            if setup.count(marker) != 1:
                raise ValueError('Upstream setup changed; build-only adapter needs review')
            build = package / 'decky-build-only.sh'
            build.write_text(setup.split(marker)[0] + '\n', newline='\n')
            env = dict(os.environ, XDG_DATA_HOME=str(companion / 'dependencies'),
                       TMPDIR=str(work / 'tmp'), PIP_CACHE_DIR=str(companion / 'dependencies/pip'),
                       HELIXSR_FORCE_PORTABLE='1', PYTHONUNBUFFERED='1')
            # PyInstaller's private OpenSSL must not be inherited by system curl/Wine.
            original_ld = env.pop('LD_LIBRARY_PATH_ORIG', '')
            if original_ld:
                env['LD_LIBRARY_PATH'] = original_ld
            else:
                env.pop('LD_LIBRARY_PATH', None)
            env.pop('LD_PRELOAD', None)
            env.pop('PYTHONHOME', None)
            env.pop('PYTHONPATH', None)
            Path(env['TMPDIR']).mkdir()
            logfile = companion / 'records' / ('build-' + job['id'] + '.log')
            logfile.parent.mkdir(parents=True, exist_ok=True)
            job['message'] = 'Building local NVIDIA-derived network; no games are changed'
            with logfile.open('wb') as output:
                self.process = subprocess.Popen(['bash', str(build), '--yes'], cwd=package, env=env,
                                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                                start_new_session=True)
                deadline = time.monotonic() + 900
                while self.process.poll() is None:
                    job['log'] = text_tail(logfile, 8000)
                    if self.cancel.is_set() or time.monotonic() > deadline:
                        import signal
                        os.killpg(self.process.pid, signal.SIGTERM)
                        try:
                            self.process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(self.process.pid, signal.SIGKILL)
                            self.process.wait()
                        raise ValueError('Cancelled' if self.cancel.is_set() else 'Build timed out')
                    time.sleep(0.5)
                job['log'] = text_tail(logfile, 8000)
                if self.process.returncode != 0:
                    raise ValueError('Network build failed. See build log.')
            if self.cancel.is_set():
                raise ValueError('Cancelled')
            for name in NETWORK:
                if not (package / name).is_file() or (package / name).stat().st_size < 1024:
                    raise ValueError('Network output missing or incomplete')
            build.unlink()
            final = companion / 'packages' / ('v' + release['version'])
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                # A changed cache can be rebuilt without overwriting the previous owned path.
                final = final.with_name(final.name + '-' + job['id'][:8])
            os.replace(package, final)
            payloads = NETWORK + (DLL, 'optiscaler/OptiScaler.dll',
                              'optiscaler/OptiScaler.ini', 'optiscaler/fakenvapi.dll', 'optiscaler/fakenvapi.ini',
                              'amd-fsr/amd_fidelityfx_upscaler_dx12.dll')
            if (final / 'amd-fsr' / AMD_FG).is_file():
                payloads += ('amd-fsr/' + AMD_FG,)
            record = dict(version=release['version'], path=str(final), release_sha256=release['sha256'],
                          files={n: sha(final / n) for n in payloads}, prepared_at=time.time())
            self.cfg.setdefault('packages', {})[str(final)] = record
            self.save()
            atomic_json(companion / 'records/package.json', record)
            for n in NETWORK:
                (final / n).chmod(0o600)
        finally:
            # Work is exclusively owned by this job. Logs and successful package remain.
            shutil.rmtree(work, ignore_errors=True)

    def preview(self, gid, action, dx12_confirmed=False):
        with self.lock:
            game = self.get_game(gid)
            if action not in ('install', 'update', 'enable', 'disable', 'remove', 'adopt', 'recover'):
                raise ValueError('Unknown action')
            if action == 'recover':
                journal = self.companion(game) / 'transaction/journal.json'
                if not journal.exists():
                    raise ValueError('No interrupted transaction')
                token = uuid.uuid4().hex
                self.previews[token] = dict(game=gid, action=action, fingerprint=None,
                                           expires=time.time()+120, dx12=False)
                saved = load_json(journal)
                return dict(token=token, action=action, name=game['name'],
                            route=(saved.get('previous') or {}).get('route', 'previous configuration'),
                            files=list(saved.get('before', {})),
                            select_upscaler='previous configuration',
                            warning='Recover the interrupted transaction before any new installation.')
            data = self.assess(game)
            rec = self.record(game)
            if data['compatibility'] != 'candidate':
                raise ValueError('; '.join(data['reasons']))
            if data['dx12_confirmation_needed'] and not dx12_confirmed and action in ('install', 'update'):
                raise ValueError('Confirm that this game is set to DirectX 12')
            if action == 'adopt' and not data['legacy']:
                raise ValueError('Only verified legacy direct installations can be imported')
            if data['legacy'] and action != 'adopt':
                raise ValueError('Import existing direct installation first')
            if action in ('install', 'update', 'enable'):
                package = self.package(game)
                if not package:
                    raise ValueError('Prepare HelixSR on this drive first')
                for n, expected in package[2]['files'].items():
                    if sha(package[1] / n) != expected:
                        raise ValueError('Prepared package changed. Rebuild required.')
            if action == 'install' and rec:
                raise ValueError('Already managed; use update or enable')
            if action in ('disable', 'enable', 'remove', 'update') and not rec:
                raise ValueError('Game is not managed by this plugin')
            if action == 'adopt':
                for target in data['targets']:
                    p = Path(target)
                    orig = p.with_name(p.stem + '.original.dll')
                    if not orig.is_file() or orig.is_symlink() or pe_info(orig)['helix'] or not pe_info(orig)['ffx']:
                        raise ValueError('Legacy installation lacks a verified original FidelityFX DLL')
            token = uuid.uuid4().hex
            fingerprint = self.fingerprint(game, data)
            self.previews[token] = dict(game=gid, action=action, fingerprint=fingerprint,
                                       expires=time.time()+120, dx12=dx12_confirmed)
            return dict(token=token, action=action, name=game['name'], route=data['route'],
                        files=self.planned_paths(game, data, action),
                        select_upscaler='AMD FSR' if data['route'] == 'direct' else 'DLSS (or XeSS/FSR input)',
                        warning='Close the game. Originals are retained for disable/remove. Game settings and frame generation are not changed.',
                        expires_at=time.time()+120)

    def fingerprint(self, game, data, include_package=True):
        # Observe game drift separately from an install's conflict checks.
        # Potential new dependencies must be stable before/after preparation.
        rec = self.record(game)
        paths = list(rec['baseline']) if rec else self.planned_paths(game, data, 'observe')
        if data['route'] == 'optiscaler':
            fg = str((Path(data['target']) / 'HelixSR' / AMD_FG).relative_to(Path(game['folder'])))
            if fg not in paths:
                paths.append(fg)
        files = {}
        for rel in paths:
            p = checked_path(Path(game['folder']), rel)
            files[rel] = sha(p) if p.is_file() else None
        files['manifest'] = sha(game['manifest']) if game.get('manifest') else None
        package = self.package(game)
        if package and include_package:
            files['package_path'] = str(package[1])
            files['package_files'] = {n: sha(package[1] / n) for n in package[2]['files']}
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    def planned_paths(self, game, data, action):
        rec, root = self.record(game), Path(game['folder'])
        if rec:
            paths = list(rec['baseline'])
            package = self.package(game)
            if (action in ('install', 'update', 'enable', 'latest') and data['route'] == 'optiscaler'
                    and (action == 'latest' or package and (package[1] / 'amd-fsr' / AMD_FG).is_file())):
                path = str((Path(data['target']) / 'HelixSR' / AMD_FG).relative_to(root))
                if path not in paths:
                    target = checked_path(root, path)
                    if target.exists() or target.is_symlink():
                        raise ValueError('New upstream file conflicts with an unmanaged file: ' + path)
                    paths.append(path)
            return paths
        if data['route'] == 'direct':
            paths = []
            for target in map(Path, data['targets']):
                paths += [target, target.with_name(target.stem + '.original.dll')]
                paths += [target.parent / n for n in NETWORK]
                paths += [target.parent / 'helixsr-install.json']
            return sorted({str(p.relative_to(root)) for p in paths})
        if data['route'] == 'optiscaler':
            target = Path(data['target'])
            names = ['dxgi.dll', 'OptiScaler.ini', 'fakenvapi.dll', 'fakenvapi.ini',
                     'HelixSR/helixsr.dll', 'HelixSR/helixsr_upscaler.dll',
                     'HelixSR/amd_fidelityfx_upscaler_dx12.amd.dll', 'HelixSR/helixsr-install.json']
            names += ['HelixSR/' + n for n in NETWORK]
            package = self.package(game)
            if action == 'latest' or package and (package[1] / 'amd-fsr' / AMD_FG).is_file():
                names.append('HelixSR/' + AMD_FG)
            return [str((target / n).relative_to(root)) for n in names]
        return []

    def execute(self, token):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Wait for preparation to finish')
            preview = self.previews.pop(token, None)
            if not preview or time.time() > preview['expires']:
                raise ValueError('Preview expired; preview the action again')
            game = self.get_game(preview['game'])
            if active_processes(game['folder'], game.get('appid', '')):
                raise ValueError('Game is running')
            if preview['action'] == 'recover':
                if game.get('manifest'):
                    from library import vdf
                    state = int(vdf(text(game['manifest'])).get('AppState', {}).get('StateFlags', 0))
                    if state != 4:
                        raise ValueError('Wait for Steam download/update completion before recovery')
                self.rollback(game)
                return {'message': 'Interrupted transaction recovered'}
            data = self.assess(game)
            if data['compatibility'] != 'candidate' or self.fingerprint(game, data) != preview['fingerprint']:
                raise ValueError('Game changed since preview; refresh and review again')
            return self.mutate(game, data, preview['action'])

    def mutate(self, game, data, action):
        root, companion = Path(game['folder']), self.companion(game)
        tx = companion / 'transaction'
        if tx.exists():
            raise ValueError('Interrupted transaction exists; recover it first')
        paths = self.planned_paths(game, data, action)
        size = sum((root / p).stat().st_size for p in paths if (root / p).is_file())
        if shutil.disk_usage(root).free < size * 3 + (128 << 20):
            raise ValueError('Insufficient free space for safe file transaction')
        durable_directory(tx)
        before = {}
        previous = self.record(game)
        atomic_json(tx / 'journal.json', {'state': 'snapshotting', 'action': action})
        for rel in paths:
            p = checked_path(root, rel)
            before[rel] = sha(p) if p.is_file() else None
            if p.is_file():
                dst = tx / 'snapshot' / rel
                durable_copy(p, dst, before[rel])
        build = game.get('build')
        if game.get('manifest'):
            from library import vdf
            build = vdf(text(game['manifest'])).get('AppState', {}).get('buildid')
        journal = dict(before=before, previous=json.loads(json.dumps(previous)), action=action,
                       state='prepared', started_at=time.time(), game_build=build,
                       allowed_live={rel: [digest] for rel, digest in before.items()})
        atomic_json(tx / 'journal.json', journal)
        self.transaction = (root, tx, journal)
        try:
            if not previous:
                baseline = {}
                for rel in paths:
                    p = checked_path(root, rel)
                    baseline[rel] = before[rel]
                    if p.is_file():
                        dst = companion / 'originals' / rel
                        durable_copy(p, dst, before[rel])
                previous = dict(route=data['route'], target=data['target'], targets=data['targets'],
                                baseline=baseline, enabled=False, version=None)
            if action == 'adopt':
                # Baseline restores native DLL and removes only identified Helix payload.
                for target in map(Path, data['targets']):
                    rel = str(target.relative_to(root))
                    orig = target.with_name(target.stem + '.original.dll')
                    dst = companion / 'originals' / rel
                    durable_copy(orig, dst)
                    previous['baseline'][rel] = sha(orig)
                    previous['baseline'][str(orig.relative_to(root))] = None
                    for n in NETWORK + ('helixsr-install.json',):
                        previous['baseline'][str((target.parent / n).relative_to(root))] = None
                previous['enabled'], previous['version'] = True, 'legacy'
            elif action in ('disable', 'remove'):
                self.restore_baseline(game, previous)
                previous['enabled'] = False
            elif action in ('install', 'update', 'enable'):
                package = self.package(game)
                if not package:
                    raise ValueError('Prepared package unavailable')
                previous['enabled'], previous['version'] = True, package[2]['version']
                # Extend older managed records for newly introduced dependencies.
                # Their paths were conflict-checked, snapshotted and journaled above.
                for rel in paths:
                    previous['baseline'].setdefault(rel, before[rel])
                self.install_payload(game, data, previous, package[1])
            previous['current'] = {rel: sha(root / rel) if (root / rel).is_file() else None for rel in paths}
            previous['updated_at'], previous['game_build'] = time.time(), game.get('build')
            if game.get('manifest'):
                from library import vdf
                previous['game_build'] = vdf(text(game['manifest'])).get('AppState', {}).get('buildid')
            if action == 'remove':
                self.record_path(game).unlink(missing_ok=True)
            else:
                atomic_json(self.record_path(game), previous)
            atomic_json(companion / 'records' / ('action-' + uuid.uuid4().hex + '.json'),
                        dict(action=action, route=data['route'], version=previous['version'], verified=previous['current'], time=time.time()))
            journal.update(state='committed', committed_current=previous['current'],
                           committed_record=None if action == 'remove' else previous)
            atomic_json(tx / 'journal.json', journal)
            self.transaction = None
            shutil.rmtree(tx)
            if action == 'remove':
                shutil.rmtree(companion / 'originals', ignore_errors=True)
            return dict(message=f'{action.capitalize()} completed and file hashes verified',
                        enabled=previous['enabled'], version=previous['version'])
        except BaseException:
            self.transaction = None
            self.rollback(game)
            raise

    def track_write(self, path, digest):
        if self.transaction is None:
            return
        root, tx, journal = self.transaction
        rel = str(Path(path).relative_to(root))
        if rel not in journal['before']:
            raise ValueError('Transaction attempted an unplanned path: ' + rel)
        allowed = journal['allowed_live'][rel]
        if digest not in allowed:
            allowed.append(digest)
            atomic_json(tx / 'journal.json', journal)

    def unlink_managed(self, path):
        self.track_write(path, None)
        Path(path).unlink(missing_ok=True)
        sync_directory(Path(path).parent)

    def write_managed(self, path, content):
        payload = content.encode('utf-8')
        self.track_write(path, hashlib.sha256(payload).hexdigest())
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        temp = p.with_name(p.name + '.helixsr-decky.tmp')
        try:
            with temp.open('wb') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, p)
            sync_directory(p.parent)
        finally:
            temp.unlink(missing_ok=True)

    def write_managed_json(self, path, value):
        self.write_managed(path, json.dumps(value, indent=2) + '\n')

    def restore_baseline(self, game, rec):
        root, companion = Path(game['folder']), self.companion(game)
        for rel, expected in rec['baseline'].items():
            p = checked_path(root, rel)
            if expected is None:
                self.unlink_managed(p)
            else:
                src = companion / 'originals' / rel
                if sha(src) != expected:
                    raise ValueError('Original file hash mismatch: ' + rel)
                self.copy_atomic(src, p)

    def rollback(self, game):
        root, tx = Path(game['folder']), self.companion(game) / 'transaction'
        journal = load_json(tx / 'journal.json')
        if not journal:
            raise ValueError('Transaction journal missing; manual inspection required')
        if journal.get('state') == 'snapshotting':
            shutil.rmtree(tx)
            return
        if active_processes(root, game.get('appid', '')):
            raise ValueError('Close game before transaction recovery')
        if game.get('manifest') and journal.get('game_build'):
            from library import vdf
            build = vdf(text(game['manifest'])).get('AppState', {}).get('buildid')
            if build != journal['game_build']:
                raise ValueError('Steam build changed during transaction; recovery requires manual review')
        # Validate every path before restoring any path, so conflicts never cause a partial rollback.
        for rel, expected in journal['before'].items():
            p = checked_path(root, rel)
            actual = sha(p) if p.is_file() else None
            allowed = journal.get('allowed_live', {}).get(rel, [expected])
            if journal.get('state') == 'committed':
                allowed = [journal['committed_current'][rel]]
            if actual not in allowed:
                raise ValueError('Recovery conflict; file changed outside transaction: ' + rel)
            if expected is not None and journal.get('state') != 'committed':
                if sha(tx / 'snapshot' / rel) != expected:
                    raise ValueError('Transaction snapshot damaged')
        if journal.get('state') == 'committed':
            if (self.record(game) or None) != journal.get('committed_record'):
                raise ValueError('Committed installation record changed; manual review required')
            shutil.rmtree(tx)
            if journal.get('action') == 'remove':
                shutil.rmtree(self.companion(game) / 'originals', ignore_errors=True)
            return
        for rel, expected in journal['before'].items():
            p = checked_path(root, rel)
            p.with_name(p.name + '.helixsr-decky.tmp').unlink(missing_ok=True)
            if expected is None:
                p.unlink(missing_ok=True)
            else:
                src = tx / 'snapshot' / rel
                if sha(src) != expected:
                    raise ValueError('Transaction snapshot damaged')
                self.copy_atomic(src, p)
        if journal['previous']:
            atomic_json(self.record_path(game), journal['previous'])
        else:
            self.record_path(game).unlink(missing_ok=True)
            shutil.rmtree(self.companion(game) / 'originals', ignore_errors=True)
        shutil.rmtree(tx)

    def copy_atomic(self, src, dst):
        self.track_write(dst, sha(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        temp = dst.with_name(dst.name + '.helixsr-decky.tmp')
        try:
            shutil.copy2(src, temp)
            if sha(src) != sha(temp):
                raise ValueError('Copy verification failed')
            with temp.open('r+b') as f:
                os.fsync(f.fileno())
            os.replace(temp, dst)
            sync_directory(dst.parent)
        finally:
            temp.unlink(missing_ok=True)

    def install_payload(self, game, data, rec, package):
        root = Path(game['folder'])
        if data['route'] == 'direct':
            for target in map(Path, rec['targets']):
                rel = str(target.relative_to(root))
                original = self.companion(game) / 'originals' / rel
                if sha(original) != rec['baseline'][rel]:
                    raise ValueError('Original FidelityFX DLL changed')
                self.copy_atomic(original, target.with_name(target.stem + '.original.dll'))
                self.copy_atomic(package / DLL, target)
                for name in NETWORK:
                    self.copy_atomic(package / name, target.parent / name)
                self.write_managed_json(target.parent / 'helixsr-install.json',
                            {'route': 'direct', 'owner': 'HelixSR Decky', 'helixsr': rec.get('version')})
        else:
            target = Path(rec['target'])
            for source, dest in [('optiscaler/OptiScaler.dll', 'dxgi.dll'),
                                 ('optiscaler/fakenvapi.dll', 'fakenvapi.dll'), ('optiscaler/fakenvapi.ini', 'fakenvapi.ini'),
                                 (DLL, 'HelixSR/helixsr.dll'), (DLL, 'HelixSR/helixsr_upscaler.dll'),
                                 ('amd-fsr/amd_fidelityfx_upscaler_dx12.dll', 'HelixSR/amd_fidelityfx_upscaler_dx12.amd.dll')]:
                self.copy_atomic(package / source, target / dest)
            for name in NETWORK:
                self.copy_atomic(package / name, target / 'HelixSR' / name)
            source = text(package / 'optiscaler/OptiScaler.ini')
            settings = [('Dx12Upscaler', 'fsr31'),
                               ('FfxDx12Path', str(target / 'HelixSR/helixsr.dll').replace('/', '\\')),
                               ('FfxDx12SRPath', str(target / 'HelixSR/helixsr_upscaler.dll').replace('/', '\\'))]
            if (package / 'amd-fsr' / AMD_FG).is_file():
                self.copy_atomic(package / 'amd-fsr' / AMD_FG, target / 'HelixSR' / AMD_FG)
                settings.append(('FfxDx12FGPath', str(target / 'HelixSR' / AMD_FG).replace('/', '\\')))
            for key, value in settings:
                if key.startswith('Ffx'):
                    value = 'Z:' + value
                pattern = r'(?im)^\s*' + re.escape(key) + r'\s*=.*$'
                if not re.search(pattern, source):
                    raise ValueError('Upstream OptiScaler configuration changed: ' + key)
                source = re.sub(pattern, lambda _: key + '=' + value, source)
            self.write_managed(target / 'OptiScaler.ini', source)
            self.write_managed_json(target / 'HelixSR/helixsr-install.json',
                        {'route': 'optiscaler', 'owner': 'HelixSR Decky', 'helixsr': rec.get('version')})
