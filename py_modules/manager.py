"""HelixSR package and per-game transactions, run as the Deck user."""
import contextlib
import hashlib
import http.client
import importlib.util
import json
import math
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
from email.utils import parsedate_to_datetime
from functools import lru_cache
from library import discover, discover_launcher, safe_root, scan_tree, text
from discovery_records import normalize_imports
from awareness import awareness, active_processes, text_tail, optiscaler_proxy
from game_guidance import setup_guidance
from operation_lock import operation_lock, game_locked
from host_environment import host_environment
from installation_status import installation_status
import menu_labels
import modern_release
import helix20_release

def release_adapter(record):
    return helix20_release if helix20_release.modern(record) else modern_release

def is_modern(record):
    return helix20_release.modern(record) or modern_release.modern(record)

def output_dll(record):
    return helix20_release.OUTPUT_DLL if helix20_release.modern(record) else 'amd_fidelityfx_dx12.dll'

def manifest_path(record):
    return helix20_release.MANIFEST_PATH if helix20_release.modern(record) else 'helixsr_setup.json'
import helix_settings
from modern_build import build_script as modern_build_script
from compatibility_release import (COMPATIBLE_CHOICE, compatible_release, selection,
                                   validate_compatible_release, require_supported_latest,
                                   reviewed_release, release_choices, release_status)
from build_runtime import wine_candidates
from github_release import web_latest_release
from model_variants import (DEFAULT_VARIANT, catalog, package_selection, same_release,
                            select_variant, valid_variant, variant_label, verify_recipe, verify_outputs)

REPO = 'lonewolf0622/HelixSR'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
DLL = 'amd_fidelityfx_dx12.dll'
NETWORK = ('helixsr_weights.bin', 'helixsr_kernels.pak')
AMD_FG = 'amd_fidelityfx_framegeneration_dx12.dll'
PACKAGE_FILES = NETWORK + (DLL, 'optiscaler/OptiScaler.dll',
                           'optiscaler/OptiScaler.ini', 'optiscaler/fakenvapi.dll',
                           'optiscaler/fakenvapi.ini',
                           'amd-fsr/amd_fidelityfx_upscaler_dx12.dll')
INPUTS = {'nvngx_dlss.dll': 'DLSS', 'libxess.dll': 'XeSS',
          'ffx_fsr2_api_x64.dll': 'FSR 2', 'ffx_fsr2_api_dx12_x64.dll': 'FSR 2'}
ANTI = ('easyanticheat', 'battleye', 'beclient', 'equ8', 'faceit', 'vanguard')


def anti_cheat_name(value):
    # EA uses both spaced and compact names for the same protected launcher.
    compact = re.sub(r'[\s_.-]+', '', value.lower())
    return any(name in compact for name in ANTI + ('eaanticheat', 'eajavelin', 'javelinanticheat'))


def absent_path(path):
    # Only ENOENT proves absence; permission and I/O failures must stay blocked.
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return True
    return False
# Official Steam requirements: https://store.steampowered.com/app/1593500/
DX11_ONLY_STEAM_APPS = {'1593500': 'God of War (2018)'}
LICENSE_REV = 'helixsr-local-nvidia-network-2026-10'
RELEASE_POLICY = 2
AUTO_PACKAGE = object()
CONFIG_LIMIT = 1 << 20


def github_pause(error, now):
    """Honor server backoff; only a proven primary quota permits web fallback."""
    headers = error.headers or {}
    retry = headers.get('Retry-After')
    if retry is not None or error.code == 429:
        try:
            delay = float(retry) if str(retry).isdigit() else parsedate_to_datetime(retry).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            delay = 60
        if not math.isfinite(delay):
            delay = 60
        return 'secondary', now + min(86400, max(60, delay))
    if error.code == 403 and headers.get('X-RateLimit-Remaining') == '0':
        try:
            reset = float(headers.get('X-RateLimit-Reset'))
            if math.isfinite(reset) and now < reset <= now + 86400:
                return 'primary', reset
        except (TypeError, ValueError):
            pass
    return 'blocked', now + 60


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


def license_key(release, variant_id=None):
    if not isinstance(release, dict) or not release.get('version') or not release.get('sha256'):
        return None
    selected = select_variant(variant_id)
    return {'terms': LICENSE_REV, 'version': release['version'], 'release_sha256': release['sha256'],
            'variant_id': selected['id'], 'adapter': selected['adapter']}


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


def check_build_exit(returncode, cancelled, log=''):
    if cancelled:
        raise ValueError('Cancelled')
    if returncode != 0:
        log = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', log[-8000:])
        if 'no Proton or Wine found' in log:
            detail = 'Proton or Wine was not found. Install Proton through Steam and retry.'
        elif 'Permission denied' in log:
            detail = 'Preparation was denied access. Check the game drive permissions and executable support.'
        elif 'No space left on device' in log:
            detail = 'The game drive ran out of space.'
        else:
            lines = [line.strip() for line in log.splitlines() if line.strip()]
            detail = lines[-1][:320] if lines else ''
        raise ValueError('Network build failed. ' + (detail + ' ' if detail else '') +
                         'See the build log for details.')


def select_build_wine(home, env):
    """Only override upstream discovery with a Steam runtime that starts on this host."""
    if platform.system() != 'Linux':
        return None, []
    notes = []
    for candidate in wine_candidates(home)[:12]:
        try:
            probe = subprocess.run([str(candidate), '--version'], env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   encoding='utf-8', errors='replace', timeout=3)
            output = probe.stdout.strip()
            if probe.returncode == 0 and re.search(r'^wine-\S+', output, re.MULTILINE):
                notes.append('Build runtime: ' + str(candidate) + ' (' + output[:120] + ')')
                return candidate, notes
            notes.append('Skipped build runtime: ' + str(candidate) + ': ' + output[:200])
        except (OSError, subprocess.TimeoutExpired) as error:
            notes.append('Skipped build runtime: ' + str(candidate) + ': ' + str(error)[:200])
    return None, notes


def build_only_script(setup, converter, runtime_override=False):
    """Keep local network files separate and stop before upstream game writes."""
    marker = '# --- games ---'
    invocation = '"$PY" "$PKG/helixsr_setup.py" "$TARGET" --dxc "$DXC" "${PASS[@]}"'
    if setup.count(marker) != 1:
        raise ValueError('Upstream setup changed; build-only adapter needs review')
    script = setup.split(marker)[0]
    if script.count(invocation) != 1 or '--separate-files' not in converter:
        raise ValueError('Upstream network output changed; build-only adapter needs review')
    if runtime_override:
        wine_start = 'WINE=""\n# official Proton first, then custom Proton builds, then a system Wine'
        wine_end = '[ -n "$WINE" ] || die "no Proton or Wine found (needed to run the shader compiler); install Proton in Steam or Wine"'
        wrapper_start = 'cat > "$DXC" <<EOF\n'
        wrapper_end = '\nEOF\nchmod +x "$DXC"'
        wrapper_command = 'WINEPREFIX="$DATA/wineprefix" WINEDEBUG=-all exec "$WINE" "$DATA/dxc-win/bin/x64/dxc.exe"'
        if (script.count(wine_start) != 1 or script.count(wine_end) != 1 or
                script.count(wrapper_start) != 1 or script.count(wrapper_end) != 1 or
                script.count(wrapper_command) != 1):
            raise ValueError('Upstream compiler runtime changed; build-only adapter needs review')
        script = script.replace(wine_start, 'WINE="${HELIXSR_BUILD_WINE:-}"\n'
                                'if [ -n "$WINE" ]; then\n'
                                '    [ -x "$WINE" ] || die "selected Proton or Wine is not executable"\n'
                                'else\n' + wine_start)
        script = script.replace(wine_end, wine_end + '\nfi')
        # A quoted heredoc plus inherited environment keeps arbitrary library
        # and companion paths out of shell source, including quotes and dollars.
        begin = script.index(wrapper_start)
        end = script.index(wrapper_end, begin) + len(wrapper_end)
        wrapper = r'''export HELIXSR_BUILD_WINE="$WINE" HELIXSR_BUILD_DATA="$DATA"
cat > "$DXC" <<'HELIXSR_DECKY_DXC'
#!/usr/bin/env bash
args=()
for a in "$@"; do
    case "$a" in
        /*) args+=("Z:$(printf '%s' "$a" | tr / '\\')") ;;
        *) args+=("$a") ;;
    esac
done
WINEPREFIX="$HELIXSR_BUILD_DATA/wineprefix" WINEDEBUG=-all exec "$HELIXSR_BUILD_WINE" "$HELIXSR_BUILD_DATA/dxc-win/bin/x64/dxc.exe" "${args[@]}"
HELIXSR_DECKY_DXC
chmod +x "$DXC"'''
        script = script[:begin] + wrapper + script[end:]
    # 1.8 embeds the network into its DLL and removes the separate files by default.
    # Request its supported separate output at the converter, not the shell CLI.
    return script.replace(invocation, invocation + ' --separate-files') + '\n'


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
        self.process_guard = threading.Lock()
        self.closing = threading.Event()
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

    def checked_menu_path(self, game, relative):
        return checked_path(safe_root(game['folder']), relative)

    def checked_menu_original(self, game, relative):
        return checked_path(self.companion(game), str(Path('originals') / relative))

    def menu_process_guard(self, game):
        if self.closing.is_set():
            raise ValueError('The HelixSR plugin is closing; menu changes are paused')
        menu_labels.process_scan_ready()
        if active_processes(game['folder'], game.get('appid', '')):
            raise ValueError('Game is running; close it before changing menu labels')

    def menu_change_guard(self, game, paths):
        if str(Path(menu_labels.WITCHER_XML)) in paths:
            self.menu_process_guard(game)

    def menu_status(self, game, data, rec, detailed=True):
        try:
            return menu_labels.inspect(self, game, data, rec, detailed)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            saved = rec.get('menu_labels')
            return dict(supported=False, available=False,
                        enabled=isinstance(saved, dict) and saved.get('enabled') is True,
                        reason=str(exc), label=menu_labels.LABEL, resource_sha256=None,
                        experimental=True)

    def mutable_config_paths(self, game, rec):
        # Configurations tracked by this installation are editable. Older installs
        # could capture an existing fakenvapi.ini: prove its saved original before
        # accepting edits, so removal can still restore the exact prior file.
        if rec.get('route') != 'optiscaler':
            return []
        root = Path(game['folder'])
        target = Path(rec['target'])
        if not isinstance(rec.get('baseline'), dict) or not isinstance(rec.get('current'), dict):
            raise ValueError('Invalid configuration ownership record')
        # Modern Scaler retires fakenvapi.ini by restoring its baseline. Keep
        # its ownership and saved-edit history, but no longer read it as an
        # active editable config (it can legitimately be absent).
        names = ('OptiScaler.ini',) if is_modern(rec) else ('OptiScaler.ini', 'fakenvapi.ini')
        if helix20_release.modern(rec):
            names += ('HelixSR-fsrfg/helixsr.ini',)
        paths = [str((target / name).relative_to(root)) for name in names]
        mutable = []
        for rel in paths:
            if rel not in rec['current'] or rel not in rec['baseline']:
                continue
            original = rec['baseline'][rel]
            if original is not None:
                backup = checked_path(self.companion(game), str(Path('originals') / rel))
                if not backup.is_file() or sha(backup) != original:
                    raise ValueError('Original configuration backup missing or changed: ' + rel)
            mutable.append(rel)
        return mutable

    def read_owned_config(self, game, rel):
        p = checked_path(Path(game['folder']), rel)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(p, flags), 'rb') as f:
            info = os.fstat(f.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_size > CONFIG_LIMIT
                    or os.name == 'posix' and info.st_uid != os.getuid()):
                raise ValueError('Unsafe managed configuration: ' + rel)
            raw = f.read(CONFIG_LIMIT + 1)
        if len(raw) > CONFIG_LIMIT:
            raise ValueError('Managed configuration is too large: ' + rel)
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('Managed configuration must be UTF-8: ' + rel) from exc
        if '\x00' in content:
            raise ValueError('Invalid managed configuration: ' + rel)
        from optiscaler_setup import parse_config
        parse_config(content)
        return dict(content=content, sha256=hashlib.sha256(raw).hexdigest())

    def retained_config(self, rec, rel):
        container = rec.get('saved_configs', {})
        current, baseline = rec.get('current', {}), rec.get('baseline', {})
        allowed = {str(Path(rel).parent / name) for name in ('OptiScaler.ini', 'fakenvapi.ini')}
        if helix20_release.modern(rec):
            base = Path(rel).parent
            if base.name == 'HelixSR-fsrfg':
                base = base.parent
            allowed |= {str(base / 'OptiScaler.ini'), str(base / 'fakenvapi.ini'),
                        str(base / 'HelixSR-fsrfg/helixsr.ini')}
        if (not isinstance(container, dict) or not isinstance(current, dict) or not isinstance(baseline, dict)
                or any(k not in allowed or k not in current or k not in baseline for k in container)):
            raise ValueError('Invalid retained configuration record')
        saved = container.get(rel)
        if saved is None:
            return None
        if not isinstance(saved, dict) or not isinstance(saved.get('content'), str):
            raise ValueError('Invalid retained configuration: ' + rel)
        raw = saved['content'].encode('utf-8')
        if (len(raw) > CONFIG_LIMIT or b'\x00' in raw
                or hashlib.sha256(raw).hexdigest() != saved.get('sha256')):
            raise ValueError('Retained configuration hash mismatch: ' + rel)
        from optiscaler_setup import parse_config
        parse_config(saved['content'])
        return saved['content']

    @staticmethod
    def _symlink_in_path(path):
        path = Path(path)
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                return True
        return False

    def _package_record(self, record, game, owner=None):
        """Validate untrusted package metadata without changing either game."""
        if not isinstance(record, dict):
            return None
        if 'variant' in record and not valid_variant(record['variant']):
            return None
        if is_modern(record) and (
                record.get('release_sha256') != release_adapter(record).RELEASE_SHA256
                or not valid_variant(record.get('variant'))
                or record['variant']['recipe_sha256'] != release_adapter(record).RECIPE_SHA256):
            return None
        if 'variant' in record and (not isinstance(record.get('files'), dict)
                                    or manifest_path(record) not in record['files']):
            return None
        path, release_digest = record.get('path'), record.get('release_sha256')
        prepared = record.get('prepared_at', 0)
        files = record.get('files')
        if (not isinstance(path, str) or not path or '\x00' in path
                or not Path(path).is_absolute()
                or not isinstance(record.get('version'), str)
                or type(prepared) not in (int, float)
                or (type(prepared) is float and not math.isfinite(prepared)) or prepared < 0
                or ('release_sha256' in record and (not isinstance(release_digest, str)
                    or not re.fullmatch(r'[a-fA-F0-9]{64}', release_digest)))
                or (owner is not None and not isinstance(release_digest, str))
                or not isinstance(files, dict) or not files):
            return None
        try:
            parsed_version = version(record['version'])
        except ValueError:
            return None
        path = Path(path)
        try:
            if (not path.is_dir() or self._symlink_in_path(path)
                    or path.stat().st_dev != Path(game['folder']).stat().st_dev):
                return None
            if owner is not None:
                package_root = Path(owner) / 'packages'
                if self._symlink_in_path(package_root):
                    return None
                resolved, resolved_root = path.resolve(), package_root.resolve()
                if resolved.parent != resolved_root or not set(release_adapter(record).payload_files() if is_modern(record) else PACKAGE_FILES).issubset(files):
                    return None
            for name, digest in files.items():
                if (not isinstance(name, str) or not name or '\x00' in name or '\\' in name or ':' in name
                        or not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest)):
                    return None
                relative = PurePosixPath(name)
                if (relative.is_absolute() or '..' in relative.parts or '.' in relative.parts
                        or relative.as_posix() != name or name == '.'):
                    return None
                payload = path.joinpath(*relative.parts)
                if (self._symlink_in_path(payload)
                        or (owner is not None and not payload.is_file())
                        or (payload.exists() and not payload.is_file())):
                    return None
            framegen = path / 'amd-fsr' / AMD_FG
            if framegen.is_symlink() or (framegen.is_file() and 'amd-fsr/' + AMD_FG not in files):
                return None
        except OSError:
            return None
        return parsed_version, path, record

    def _verify_package_payloads(self, package, route=None):
        """Prove every payload an operation may consume is in the recorded manifest."""
        if route not in (None, 'direct', 'optiscaler'):
            raise ValueError('Unknown package route')
        path, record = package[1], package[2]
        required = set(release_adapter(record).payload_files() if is_modern(record) else
                       PACKAGE_FILES if route in (None, 'optiscaler') else NETWORK + (DLL,))
        if record.get('variant'):
            required.add(manifest_path(record))
        if not required.issubset(record['files']):
            return False
        framegen_name = 'amd-fsr/' + AMD_FG
        framegen = path / 'amd-fsr' / AMD_FG
        if framegen.is_file():
            required.add(framegen_name)
        try:
            verified = all(not self._symlink_in_path(path / name)
                       and (path / name).is_file() and sha(path / name) == record['files'][name]
                       for name in record['files'])
            if verified and record.get('variant'):
                if is_modern(record):
                    release_adapter(record).verify_outputs(path)
                else:
                    verify_outputs(path)
                api = pe_info(path / output_dll(record))
                verified = api['arch'] == 'x64' and bool(api['ffx'])
            return verified
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            return False

    def package(self, game, route=None, release=None, variant_id=None, selection=None, installed=None):
        # Packages remain on the same filesystem as the selected game.
        selected = select_variant(variant_id)
        choices = []
        for namespace in ('packages', 'variant_packages_v1'):
            records = self.cfg.get(namespace, {})
            if not isinstance(records, dict):
                continue
            for record in records.values():
                candidate = self._package_record(record, game)
                if candidate:
                    choices.append((*candidate, 0))
        # A separate frontend has separate settings, but package records are kept
        # beside games. Read records only from games already discovered/imported.
        seen = set()
        known_games = [game] + list(self.entries.values())
        for known in known_games:
            try:
                companion = self.companion(known)
                record_path = companion / 'records/package.json'
                key = str(record_path)
                if key in seen:
                    continue
                seen.add(key)
                records = []
                if (not self._symlink_in_path(record_path) and record_path.is_file()
                        and record_path.stat().st_size <= 1 << 20):
                    try:
                        records.append(load_json(record_path))
                    except (OSError, ValueError, TypeError, RecursionError):
                        pass
                indexed = self.package_index(companion / 'records/packages-v1.json')
                if indexed is not None:
                    records.extend(indexed)
                for record in records:
                    candidate = self._package_record(record, game, companion)
                    if candidate:
                        choices.append((*candidate, 1))
            except (ValueError, OSError, RecursionError, KeyError, TypeError):
                continue
        if release is not None:
            choices = [choice for choice in choices
                       if choice[2].get('version') == release.get('version')
                       and choice[2].get('release_sha256') == release.get('sha256')
                       and valid_variant(choice[2].get('variant'))]
        # Legacy caches remain usable for recovery/enable, without claiming model
        # provenance. Future release caches must carry a reviewed variant identity.
        choices = [choice for choice in choices
                   if (valid_variant(choice[2].get('variant'))
                       and choice[2]['variant']['id'] == selected['id'])
                   or ('variant' not in choice[2] and choice[0] <= (1, 8, 1)
                       and selected['id'] == DEFAULT_VARIANT)]
        if selection is not None:
            choices = [choice for choice in choices if package_selection(choice[2]) == selection]
        elif installed is not None:
            choices = [choice for choice in choices if choice[2]['version'] == installed.get('version')
                       and self.matches_installed_payload(game, installed, choice[2])]
            if len({package_selection(choice[2]) for choice in choices}) != 1:
                return None
        if not choices:
            return None
        choices.sort(key=lambda x: (x[0], x[2].get('prepared_at', 0), x[3]), reverse=True)
        return next((choice[:3] for choice in choices
                     if self._verify_package_payloads(choice[:3], route)), None)

    def package_index(self, path):
        try:
            if self._symlink_in_path(path) or not path.is_file() or path.stat().st_size > 1 << 20:
                return None
            index = load_json(path)
            records = index.get('packages') if isinstance(index, dict) and index.get('schema') == 1 else None
            return records if isinstance(records, list) and len(records) <= 256 else None
        except (ValueError, OSError, RecursionError, TypeError):
            return None

    def matches_installed_payload(self, game, installed, package_record):
        """Recover an old enabled install's identity from its owned output hashes."""
        if not installed.get('enabled'):
            return False
        try:
            root = Path(game['folder'])
            pairs = []
            if installed['route'] == 'direct':
                for target in map(Path, installed['targets']):
                    pairs.append((str(target.relative_to(root)), output_dll(package_record)))
                    if not helix20_release.modern(package_record):
                        pairs.extend((str((target.parent / name).relative_to(root)), name) for name in NETWORK)
            elif installed['route'] == 'optiscaler' and is_modern(package_record):
                game_target = Path(installed['target'])
                pairs = [(str((game_target / dest).relative_to(root)), source)
                         for source, dest in release_adapter(package_record).scaler_pairs()
                         if not dest.endswith('.ini')]
            elif installed['route'] == 'optiscaler':
                game_target = Path(installed['target'])
                target = game_target / 'HelixSR'
                pairs = [(str((target / name).relative_to(root)), DLL)
                         for name in ('helixsr.dll', 'helixsr_upscaler.dll')]
                pairs += [(str((target / name).relative_to(root)), name) for name in NETWORK]
                pairs += [(str((game_target / 'dxgi.dll').relative_to(root)), 'optiscaler/OptiScaler.dll'),
                          (str((game_target / 'fakenvapi.dll').relative_to(root)), 'optiscaler/fakenvapi.dll'),
                          (str((target / 'amd_fidelityfx_upscaler_dx12.amd.dll').relative_to(root)),
                           'amd-fsr/amd_fidelityfx_upscaler_dx12.dll')]
                fg_rel = str((target / AMD_FG).relative_to(root))
                fg_hash = package_record['files'].get('amd-fsr/' + AMD_FG)
                if installed['current'].get(fg_rel) != fg_hash:
                    return False
                if fg_hash:
                    pairs.append((fg_rel, 'amd-fsr/' + AMD_FG))
            return bool(pairs) and all(installed['current'].get(rel) == package_record['files'][name]
                                       for rel, name in pairs)
        except (ValueError, TypeError, KeyError):
            return False

    def refresh(self):
        started = time.monotonic()
        entries, warnings = discover(self.home, self.cfg.get('imports', []))
        games = []
        for game in entries:
            games.append(self.assess_safe(game, detailed=False))
        self.entries = {x['id']: x for x in entries}
        release = release_status(load_release(self.settings))
        return dict(games=games, warnings=warnings, release=release,
                    release_choices=release_choices(), scanned_at=time.time(),
                    scan_seconds=round(time.monotonic() - started, 3),
                    model_catalog=catalog(),
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

    def assess_safe(self, game, detailed=True, executable=None):
        try:
            return self.assess(game, detailed=detailed, executable=executable)
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as e:
            # A malformed receipt or other per-game metadata must block this
            # entry, not discard the entire library. Actions still reassess.
            reason = str(e)
            if isinstance(e, (TypeError, AttributeError, KeyError)):
                reason = 'Game metadata has an unexpected format; review diagnostics before changing files: ' + type(e).__name__ + ': ' + reason
            data = dict(game, compatibility='blocked', reasons=[reason], route=None,
                        managed=False, enabled=False, inputs=[],
                        executable_choices=[], selected_executable=None, executable_selection_needed=False,
                        recovery_available=self.recovery_available(game),
                        optiscaler={'present': False, 'involved': False, 'helix_configured': False,
                                    'runtime': 'unknown', 'dlls': []},
                        framegen=[], framegen_summary='No supported per-game evidence',
                        helix_runtime='unknown', launch_options=game.get('launch_options', ''))
            data['installation_status'] = installation_status(data)
            data['setup_guidance'] = setup_guidance(data)
            return data

    def get_game(self, gid):
        if gid not in self.entries:
            self.refresh()
        if gid not in self.entries:
            raise ValueError('Game disappeared. Refresh library.')
        return self.entries[gid]

    def assess(self, game, detailed=True, executable=None):
        root = safe_root(game['folder'])
        tree = scan_tree(root)
        names = [(d / n, n.lower()) for d, ns in tree for n in ns]
        inputs = sorted({INPUTS[n] for _, n in names if n in INPUTS})
        targets = [p for p, n in names if n in ('amd_fidelityfx_upscaler_dx12.dll', DLL)]
        exes = [p for p, n in names if n.endswith('.exe') and
                not re.search(r'launcher|crash|setup|redist|unins|helper|beservice', n) and
                not anti_cheat_name(n) and
                not any(anti_cheat_name(part) for part in p.relative_to(root).parts[:-1])]
        exes.sort(key=lambda p: (p.name.lower().endswith('-win64-shipping.exe'), p.stat().st_size), reverse=True)
        main = exes[0] if exes else None
        rec = self.record(game)
        if rec.get('route') == 'direct':
            # Existing installations retain their owned targets, even if a
            # newer discovery heuristic would choose another native DLL.
            targets = [checked_path(root, str(Path(p).relative_to(root))) for p in rec['targets']]
        else:
            runtime_targets = [p for p in targets if p.parent == root or main and p.parent == main.parent]
            if runtime_targets:
                targets = runtime_targets
            # Prefer runtime locations before the SR filename, so bundled SDK
            # or injector copies cannot displace the game's native loader DLL.
            sr_targets = [p for p in targets if p.name.lower() == 'amd_fidelityfx_upscaler_dx12.dll']
            targets = sr_targets or targets
        # Missing owned DLLs remain in target evidence and are blocked by the
        # receipt's file hashes below, without losing managed state to a PE read.
        probe_targets = [p for p in targets if p.is_file()] if rec.get('route') == 'direct' else targets
        direct_legacy = any(pe_info(p)['helix'] for p in probe_targets)
        native_api = bool(probe_targets) and all(pe_info(p)['ffx'] for p in probe_targets)
        route = rec.get('route') or ('direct' if native_api else 'optiscaler' if inputs and main else
                                    'direct' if targets else None)
        if not rec and self.cfg.get('route_preferences', {}).get(game['id']) == 'optiscaler' and main:
            route = 'optiscaler'
        # Native API discovery uses the original heuristic independently of an
        # OptiScaler executable choice. An existing receipt owns its target.
        eligible = []
        if not rec and route == 'optiscaler':
            for candidate in exes:
                checked_path(root, str(candidate.relative_to(root)))
                info = pe_info(candidate)
                if info['arch'] == 'x64':
                    eligible.append(dict(path=candidate.relative_to(root).as_posix(), dx12=info['dx12']))
        if executable is not None:
            if rec or route != 'optiscaler':
                raise ValueError('Executable selection is only available for unmanaged OptiScaler games')
            if not isinstance(executable, str) or not executable:
                raise ValueError('Select an eligible game executable')
            chosen = checked_path(root, executable)
            relative = chosen.relative_to(root).as_posix()
            if relative not in {choice['path'] for choice in eligible}:
                raise ValueError('Selected executable is not an eligible scanned x64 game executable')
            main = chosen
        elif rec and rec.get('route') == 'optiscaler' and rec.get('selected_executable'):
            main = checked_path(root, rec['selected_executable'])
            if not main.is_file():
                main = None
        target = Path(rec['target']) if rec else main.parent if main else None
        reasons, blocked = [], []
        dx11_title = DX11_ONLY_STEAM_APPS.get(str(game.get('appid', ''))) if game.get('source') == 'Steam' else None
        if dx11_title:
            reasons.append(f'{dx11_title} uses DirectX 11 only. This plugin currently installs HelixSR only through its validated DirectX 12 route. Upstream HelixSR 2.0 Scaler supports DirectX 11 upscaling, but that route is not enabled here.')
        if platform.machine().lower() not in ('x86_64', 'amd64'):
            blocked.append('HelixSR requires an x86_64 host')
        if os.name == 'posix' and os.geteuid() == 0:
            blocked.append('Plugin must run as the Steam user, without root permissions')
        if not route:
            reasons.append('No supported DLSS, XeSS, FSR 2 or native FSR 3.1 DLL detected')
        if route == 'direct':
            for p in probe_targets:
                info = pe_info(p)
                if info['arch'] != 'x64' or not info['ffx']:
                    blocked.append(f'{p.name}: expected x64 FidelityFX API not found')
        if main and pe_info(main)['arch'] != 'x64' and not rec:
            blocked.append('Main executable is not x64 Windows PE (32-bit, native Linux or unknown architecture)')
        if not dx11_title and route == 'optiscaler' and not (main and pe_info(main)['dx12']):
            reasons.append('DX12 is not confirmed by executable imports; confirm the game runs DX12 before installation')
        directory_names = [str(d.relative_to(root)).lower() for d, _ in tree]
        if any(anti_cheat_name(n) for _, n in names) or any(anti_cheat_name(n) for n in directory_names):
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
            # Other managers can leave OptiScaler under a different supported
            # alias. Installing dxgi beside it could load two copies. Only
            # identified aliases conflict; ordinary game d3d12 DLLs are valid.
            occupied += [p.name for p, _ in names if p.parent == target and
                         p.name not in occupied and optiscaler_proxy(p)]
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
        steam_build_review = None
        restore_eligible = False
        if rec:
            if game.get('build') and rec.get('game_build') and game['build'] != rec['game_build']:
                blocked.append('Steam build changed; installation needs review')
                def build_id(value):
                    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{1,24}', value) else 'unavailable'
                steam_build_review = dict(recorded_build=build_id(rec['game_build']),
                                          current_build=build_id(game['build']), files=[],
                                          omitted_files=max(0, len(rec['current']) - 20))
            def file_review(rel, state):
                if steam_build_review is not None and len(steam_build_review['files']) < 20:
                    steam_build_review['files'].append(dict(path=rel, state=state))
            mutable = self.mutable_config_paths(game, rec)
            restore_blocked = list(blocked)
            missing_introduced = []
            for rel, expected in rec['current'].items():
                p = checked_path(root, rel)
                try:
                    info = p.lstat()
                except FileNotFoundError:
                    info = None
                if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    reason = ('Unsafe managed configuration: ' if rel in mutable else
                              'Unsafe managed file type or hardlink: ') + rel
                    blocked.append(reason)
                    restore_blocked.append(reason)
                    continue
                absent_introduced = (rec.get('route') == 'optiscaler' and expected is not None
                                     and rel in rec['baseline'] and rec['baseline'][rel] is None
                                     and absent_path(p))
                if rel in mutable:
                    self.retained_config(rec, rel)
                    if rec.get('enabled') and expected is not None and not absent_introduced:
                        try:
                            self.read_owned_config(game, rel)
                        except (OSError, ValueError) as exc:
                            blocked.append(str(exc))
                            restore_blocked.append(str(exc))
                        file_review(rel, 'retained configuration')
                        continue
                actual = sha(p) if p.is_file() else None
                file_review(rel, 'missing' if actual is None else
                            'saved-original bytes match' if actual == rec['baseline'].get(rel) else
                            'installed bytes match' if actual == expected else 'externally changed')
                if actual != expected:
                    state = ('missing' if actual is None else 'matches recorded original'
                             if actual == rec['baseline'].get(rel) else 'different bytes')
                    reason = ('Managed files changed; ownership needs review before further changes: '
                              + rel + ' (current state: ' + state + ')')
                    blocked.append(reason)
                    if absent_introduced:
                        missing_introduced.append(rel)
                    else:
                        restore_blocked.append(reason)
            # Only cleanup can reconcile already absent files that this install
            # introduced. Other ownership/build/process guards are unchanged.
            restore_eligible = bool(missing_introduced and not restore_blocked
                                    and set(rec['baseline']) == set(rec['current']))
        # Symlink candidates may hide API files and must never be mutated.
        for p in targets + ([main] if main else []):
            checked_path(root, str(p.relative_to(root)))
        if detailed:
            aware = awareness(dict(game, managed=bool(rec), enabled=rec.get('enabled', False)), tree, self.home, route, target)
        else:
            # Library rows only need the compatibility assessment. Read logs,
            # shared launcher/FG settings and runtime evidence when a game is
            # inspected, never once per entry in a large installed library.
            # Process and transaction safety checks above remain fresh.
            aware = dict(awareness_deferred=True,
                         optiscaler=dict(present=None, involved=route == 'optiscaler',
                                         helix_configured=None, runtime='not inspected', dlls=[]),
                         framegen=[], framegen_summary='Select this game to inspect frame-generation evidence',
                         helix_runtime='not inspected', processes=[],
                         launch_options=game.get('launch_options', ''))
        # A library row needs compatibility and recorded installation state,
        # not a cross-library search and rehash of every prepared model. Details
        # and every mutation retain the full, fresh package verification.
        package = self.package(game, route) if detailed else None
        data = dict(game, compatibility='blocked' if blocked else 'unsupported' if dx11_title else 'candidate' if route else 'unsupported',
                    reasons=blocked + reasons, route=route, inputs=inputs, target=str(target) if target else None,
                    targets=[str(p) for p in targets], main_exe=str(main) if main else None,
                    renderer_unsupported=bool(dx11_title), executable_choices=[] if dx11_title else eligible,
                    executable_selection_needed=bool(not dx11_title and eligible and not rec and blocked == [
                        'Main executable is not x64 Windows PE (32-bit, native Linux or unknown architecture)']),
                    selected_executable=(main.relative_to(root).as_posix() if main else
                                         rec.get('selected_executable')) if route == 'optiscaler' else None,
                    managed=bool(rec), enabled=rec.get('enabled', False), installed_version=rec.get('version') or
                    next((pe_info(p).get('helix_version') for p in probe_targets if pe_info(p)['helix']), None),
                    legacy=legacy, package_version=package[2]['version'] if package else None,
                    installed_model=variant_label(rec.get('variant')) if rec or legacy else None,
                    installed_variant=rec.get('variant', {}).get('id') if valid_variant(rec.get('variant')) else None,
                    recovery_available=self.recovery_available(game), steam_build_review=steam_build_review,
                    restore_eligible=restore_eligible,
                    dx12_confirmation_needed=not dx11_title and route == 'optiscaler' and not (main and pe_info(main)['dx12']),
                    **aware)
        if not detailed:
            data.pop('logs', None)
        data['installation_status'] = installation_status(data)
        data['setup_guidance'] = setup_guidance(data)
        data['menu_labels'] = self.menu_status(game, data, rec, detailed)
        if detailed:
            data['helix_settings'] = self.game_settings(game, rec)
        return data

    def game_settings(self, game, rec=None):
        rec = self.record(game) if rec is None else rec
        if not (rec.get('enabled') and rec.get('version') == '2.0.0' and rec.get('route') == 'optiscaler'):
            return dict(available=False, reason='Install HelixSR 2.0 with the Scaler route to edit these settings.')
        try:
            rel = str((Path(rec['target']) / 'OptiScaler.ini').relative_to(Path(game['folder'])))
            if rel not in self.mutable_config_paths(game, rec):
                raise ValueError('Settings file is not owned by this installation')
            source = self.read_owned_config(game, rel)
            return dict(available=True, revision=source['sha256'],
                        **helix_settings.read_settings(source['content']))
        except (ValueError, OSError) as exc:
            return dict(available=False, reason=str(exc))

    def set_game_settings(self, gid, changes, revision):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Wait for preparation to finish')
            game = self.get_game(gid)
            with operation_lock(self.companion(game)):
                data = self.assess(game)
                rec = self.record(game)
                current = self.game_settings(game, rec)
                if not current.get('available'):
                    raise ValueError(current.get('reason', 'Settings unavailable'))
                if current['revision'] != revision:
                    raise ValueError('Settings changed; refresh before saving')
                if data['compatibility'] != 'candidate' or active_processes(game['folder'], game.get('appid', '')):
                    raise ValueError('Close the game and resolve installation warnings before changing settings')
                rel = str((Path(rec['target']) / 'OptiScaler.ini').relative_to(Path(game['folder'])))
                source = self.read_owned_config(game, rel)
                if source['sha256'] != revision:
                    raise ValueError('Settings changed; refresh before saving')
                updated = helix_settings.update_settings(source['content'], changes)
                self.mutate(game, data, 'settings', None, settings=(rel, updated))
                return self.assess_safe(game)

    def set_installation_route(self, gid, route):
        if route not in ('auto', 'optiscaler'):
            raise ValueError('Unknown installation route')
        with self.lock:
            game = self.get_game(gid)
            with operation_lock(self.companion(game)):
                data = self.assess(game)
                if data.get('managed') or data.get('legacy'):
                    raise ValueError('Remove HelixSR and restore originals before changing installation route')
                if active_processes(game['folder'], game.get('appid', '')) or self.recovery_available(game):
                    raise ValueError('Close the game and resolve pending recovery first')
                self.cfg.setdefault('route_preferences', {})[gid] = route
                self.save()
                return self.assess_safe(game)

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
        existing, warnings = normalize_imports(self.cfg.get('imports'))
        merged = {x['folder']: x for x in existing}
        merged.update({x['folder']: x for x in additions})
        self.cfg['imports'] = list(merged.values())
        self.save()
        result = self.refresh()
        result['warnings'] = list(dict.fromkeys(warnings + result['warnings']))
        return result

    def forget(self, gid):
        g = self.get_game(gid)
        if self.record(g):
            raise ValueError('Remove managed HelixSR before forgetting its folder')
        existing, warnings = normalize_imports(self.cfg.get('imports'))
        self.cfg['imports'] = [x for x in existing if x['folder'] != g['folder']]
        self.save()
        result = self.refresh()
        result['warnings'] = list(dict.fromkeys(warnings + result['warnings']))
        return result

    def accept_license(self, accepted, token=None):
        reviewed = None
        if accepted and token:
            reviewed = self.previews.get(token)
            if not reviewed or reviewed.get('action') != 'latest' or time.time() > reviewed['expires']:
                raise ValueError('Installation review expired; review the change again')
        release = (self.reviewed_install_release(reviewed) if reviewed else self.check_update()) if accepted else {}
        if accepted and release.get('error'):
            raise ValueError(release['error'])
        selected = None
        if accepted and token:
            reviewed = self.previews.get(token)
            if not reviewed or reviewed.get('action') != 'latest' or time.time() > reviewed['expires']:
                raise ValueError('Installation review expired; review the change again')
            if not same_release(release, reviewed['release']):
                raise ValueError('Upstream release changed since review; review Install or Update again')
            selected = reviewed['variant_id']
        key = license_key(release, selected) if accepted else None
        if accepted and not key:
            raise ValueError('Check upstream release metadata before accepting preparation terms')
        self.cfg['license'] = key
        self.save()
        return bool(accepted)

    def release_for_choice(self, choice=None, force=False):
        """Latest discovery stays independent from an explicitly selected archive."""
        if selection(choice) != 'latest':
            return require_supported_latest(reviewed_release(choice))
        release = self.check_update(force)
        if release.get('error') or not release.get('version'):
            raise ValueError(release.get('error') or 'Check upstream updates first')
        return require_supported_latest(release)

    def reviewed_install_release(self, preview):
        choice = selection(preview.get('release_choice'))
        release = self.release_for_choice(choice)
        if choice == COMPATIBLE_CHOICE:
            validate_compatible_release(preview['release'])
        if not same_release(release, preview['release']):
            raise ValueError('Upstream release changed since review; review Install or Update again')
        return release

    def check_update(self, force=False):
        old = load_release(self.settings)
        now = time.time()
        valid_cache = False
        try:
            validate_release(old)
            valid_cache = old.get('metadata_policy') == RELEASE_POLICY
        except (ValueError, TypeError):
            pass
        if (not force and valid_cache and not old.get('error')
                and isinstance(old.get('checked_at'), (int, float))
                and 0 <= now - old['checked_at'] < 6 * 3600):
            return old
        pause = old.get('api_retry_at')
        paused = (type(pause) in (int, float) and math.isfinite(pause)
                  and now < pause <= now + 86400
                  and old.get('api_limit_kind') in ('primary', 'secondary', 'blocked'))
        if paused:
            if old['api_limit_kind'] == 'primary':
                web_retry = old.get('web_retry_at')
                if (type(web_retry) in (int, float) and math.isfinite(web_retry)
                        and now < web_retry <= now + 86400):
                    return old
                # Avoid repeated page requests from rapid clicks while retaining a
                # freshly verified result across application restarts.
                if (valid_cache and not old.get('error')
                        and type(old.get('checked_at')) in (int, float)
                        and 0 <= now - old['checked_at'] < 30):
                    return old
                return self._web_update(old, valid_cache, pause)
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
                               metadata_source='github-api',
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
            if e.code in (403, 429):
                kind, retry_at = github_pause(e, now)
                old.update(api_limit_kind=kind, api_retry_at=retry_at)
                if kind == 'primary':
                    return self._web_update(old, valid_cache, retry_at)
                old['error'] = (f'GitHub returned HTTP {e.code}; '
                                + ('its request limit is active. ' if kind == 'secondary'
                                   else 'access to its update API was denied. ')
                                + 'Retry later; reconnecting may not help.')
            else:
                old['error'] = f'GitHub returned HTTP {e.code}; retry later to check the latest HelixSR'
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as e:
            old['error'] = str(e)
        if not valid_cache:
            old = {key: old[key] for key in ('error', 'api_retry_at', 'api_limit_kind') if key in old}
        old['failed_at'] = time.time()
        atomic_json(self.settings / 'release.json', old)
        return old

    def _web_update(self, old, valid_cache, retry_at):
        now = time.time()
        web_retry = old.get('web_retry_at')
        if (type(web_retry) in (int, float) and math.isfinite(web_retry)
                and now < web_retry <= now + 86400):
            old.update(api_limit_kind='primary', api_retry_at=retry_at)
            atomic_json(self.settings / 'release.json', old)
            return old
        try:
            current = web_latest_release(context=https_context())
            validate_release(current)
            current.update(checked_at=time.time(), etag=None, error=None,
                           metadata_policy=RELEASE_POLICY, metadata_source='github-web',
                           api_limit_kind='primary', api_retry_at=retry_at)
            atomic_json(self.settings / 'release.json', current)
            return current
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as error:
            failed = dict(old) if valid_cache else {}
            now = time.time()
            web_retry = now + 30
            if isinstance(error, urllib.error.HTTPError) and error.code in (403, 429):
                _, web_retry = github_pause(error, now)
            failed.update(error=f'GitHub API request limit reached; official release verification failed: {error}',
                          failed_at=now, api_limit_kind='primary', api_retry_at=retry_at,
                          web_retry_at=web_retry)
            atomic_json(self.settings / 'release.json', failed)
            return failed

    def preview_latest(self, gid, dx12_confirmed=False, variant_id=None, executable=None, release_choice=None):
        with self.lock:
            selected = select_variant(variant_id)
            choice = selection(release_choice)
            release = self.release_for_choice(choice)
            if release.get('error') or not release.get('version'):
                raise ValueError(release.get('error') or 'Check upstream updates first')
            game = self.get_game(gid)
            data = self.assess(game, executable=executable)
            if choice != 'latest' and (data.get('managed') or data.get('legacy')):
                installed = data.get('installed_version')
                try:
                    newer = version(installed) > version(release['version'])
                except (ValueError, TypeError):
                    newer = True
                if newer:
                    raise ValueError('Compatibility installation would downgrade a newer or unverified HelixSR installation. '
                                     'Remove it with its owning manager first; no files were changed.')
            if data['compatibility'] != 'candidate':
                raise ValueError('; '.join(data['reasons']))
            self.validate_install_executable(data)
            if data['dx12_confirmation_needed'] and not dx12_confirmed:
                raise ValueError('Confirm the game uses DirectX 12')
            if data['legacy']:
                # Existing native installations need the same original-file checks as explicit adoption.
                self.previews.pop(self.preview(gid, 'adopt', dx12_confirmed)['token'], None)
            token = uuid.uuid4().hex
            self.previews[token] = dict(game=gid, action='latest', expires=time.time()+120,
                                       release=dict(release), release_choice=choice, variant_id=selected['id'],
                                       executable=data['selected_executable'] if not data['managed'] and data['route'] == 'optiscaler' else None,
                                       selected_executable=data['selected_executable'],
                                       dx12=dx12_confirmed,
                                       fingerprint=self.fingerprint(game, data, include_package=False))
            return dict(token=token, name=game['name'], action='latest', route=data['route'],
                        selected_executable=data['selected_executable'],
                        model=selected['label'], variant_id=selected['id'], release_version=release['version'],
                        release=dict(release), release_choice=choice,
                        license_url=f'https://github.com/{REPO}/blob/v{release["version"]}/LICENSE',
                        license_accepted=self.cfg.get('license') == license_key(release, selected['id']),
                        files=self.planned_paths(game, data, 'latest', release=release),
                        select_upscaler='AMD FSR' if data['route'] == 'direct' else 'DLSS (or XeSS/FSR input)',
                        warning=('You explicitly selected the reviewed HelixSR 1.8.1 compatibility release. '
                                 'This does not install the latest upstream 1.9 Scaler engine. '
                                 if choice == COMPATIBLE_CHOICE else '') +
                                'Download required files, prepare the local network and install or update HelixSR for this game. Existing native HelixSR is imported first. Close the game. Frame generation is preserved.')

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
            if self.closing.is_set():
                raise ValueError('The HelixSR manager is closing')
            if self.worker and self.worker.is_alive():
                raise ValueError('Another operation is running')
            game = self.get_game(gid)
            if kind not in ('prepare', 'install_latest'):
                raise ValueError('Unsupported background operation')
            choice = selection(preview.get('release_choice') if preview else None)
            release = self.reviewed_install_release(preview) if preview and choice != 'latest' else load_release(self.settings)
            if preview and not same_release(release, preview['release']):
                raise ValueError('Upstream release changed since review; review Install or Update again')
            selected = select_variant(preview.get('variant_id') if preview else None)
            if not self.cfg.get('license') or self.cfg.get('license') != license_key(release, selected['id']):
                raise ValueError('Accept local network preparation terms first')
            self.cancel.clear()
            job = {'id': uuid.uuid4().hex, 'kind': kind, 'game': game['name'], 'gid': gid, 'state': 'running',
                   'message': 'Starting', 'started_at': time.time(), 'log': '',
                   'variant_id': selected['id'], 'reviewed_release': dict(release), 'release_choice': choice}
            self.jobs[job['id']] = job

            def run():
                operation = contextlib.ExitStack()
                try:
                    operation.enter_context(operation_lock(self.companion(game)))
                    prepared_package = self.prepare(game, job)
                    if kind == 'install_latest':
                        if self.cancel.is_set():
                            raise ValueError('Cancelled before installation')
                        with self.lock:
                            data = self.assess(game, executable=preview.get('executable'))
                            if data['compatibility'] != 'candidate' or self.fingerprint(game, data, include_package=False) != preview['fingerprint']:
                                raise ValueError('Game changed during preparation or is running. Close it and review again.')
                            job['message'] = 'Installing HelixSR and verifying game files'
                            if data['legacy']:
                                self.mutate(game, data, 'adopt')
                                data = self.assess(game)
                            if not prepared_package:
                                raise ValueError('Verified prepared package unavailable after preparation')
                            result = self.mutate(game, data,
                                                 'update' if self.record(game) else 'install',
                                                 prepared_package)
                            job['result'] = result
                        job['state'], job['message'] = 'completed', result['message']
                    else:
                        job['state'], job['message'] = 'completed', 'Package and local network verified'
                except Exception as e:
                    job['state'] = 'cancelled' if self.cancel.is_set() else 'failed'
                    job['message'] = str(e)
                finally:
                    job['ended_at'] = time.time()
                    try:
                        atomic_json(self.companion(game) / 'records' / ('job-' + job['id'] + '.json'), job)
                    finally:
                        self.process = None
                        operation.close()
            self.worker = threading.Thread(target=run, daemon=True)
            with self.process_guard:
                if self.closing.is_set():
                    self.cancel.set()
                    self.jobs.pop(job['id'], None)
                    raise ValueError('The HelixSR manager is closing')
                self.worker.start()
            return dict(job)

    def request_shutdown(self):
        # Never wait on the long preparation/transaction lock to close admission.
        self.closing.set()
        self.cancel.set()

    def _spawn_compiler(self, args, **kwargs):
        with self.process_guard:
            if self.closing.is_set() or self.cancel.is_set():
                raise ValueError('Cancelled before compiler startup')
            if kwargs.get('start_new_session') is not True:
                raise ValueError('Compiler requires its own process session')
            self.process = subprocess.Popen(args, **kwargs)
            if self.closing.is_set() and self.process.poll() is None:
                # Shutdown raced with Popen. This exact newly created session
                # is ours; do not leave it alive after the unload deadline.
                import signal
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
            return self.process

    def cancel_job(self, jid):
        job = self.jobs.get(jid)
        if not job or job['state'] != 'running':
            return False
        self.cancel.set()
        if self.process and self.process.poll() is None:
            import signal
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
        return True

    @game_locked
    def prepare(self, game, job):
        if os.name == 'posix' and os.geteuid() == 0:
            raise ValueError('Refusing preparation as root')
        release = self.release_for_choice(job.get('release_choice'), True)
        if selection(job.get('release_choice')) == COMPATIBLE_CHOICE:
            validate_compatible_release(job.get('reviewed_release'))
        if release.get('error') or not release.get('version'):
            raise ValueError(release.get('error', 'Check upstream updates first'))
        selected = select_variant(job.get('variant_id'))
        if self.cfg.get('license') != license_key(release, selected['id']):
            raise ValueError('Upstream release changed; review and accept its terms before preparation')
        if job.get('reviewed_release') and not same_release(release, job['reviewed_release']):
            raise ValueError('Upstream release changed since review; review Install or Update again')
        cached = self.package(game, release=release, variant_id=selected['id'])
        if cached:
            job['message'] = 'Reusing the verified prepared package on this drive'
            return cached
        companion = self.companion(game)
        index_path = companion / 'records/packages-v1.json'
        if self._symlink_in_path(index_path) or self._symlink_in_path(companion / 'packages'):
            raise ValueError('Prepared package records cannot use symlink directories')
        if index_path.exists() and (not index_path.is_file() or index_path.stat().st_size > 1 << 20):
            raise ValueError('Prepared package index is unsafe or too large; review its installation records')
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
            modern = is_modern(release)
            layout = (['LICENSE', 'THIRD_PARTY_NOTICES.md', output_dll(release),
                       'helixsr-setup.sh', 'setup/helixsr_setup.py', 'setup/helixsr_install.py',
                       'helixsr-scaler/OptiScaler.dll', 'helixsr-scaler/OptiScaler.ini'] if modern else
                      ['LICENSE', 'LICENSE-APACHE-2.0', 'THIRD_PARTY_NOTICES.md', DLL,
                         'helixsr-setup.sh', 'setup/helixsr_setup.py', 'setup/helixsr_install.py',
                         'optiscaler/OptiScaler.dll', 'optiscaler/OptiScaler.ini'])
            for name in layout:
                if not (package / name).is_file():
                    raise ValueError('Unexpected upstream package layout: ' + name)
            # Apache-licensed setup adaptation: stop before its interactive game installer.
            # Complete official release is kept; compiled parts are never patched here.
            setup = (package / 'helixsr-setup.sh').read_text()
            build = package / 'decky-build-only.sh'
            converter = (package / 'setup/helixsr_setup.py').read_text()
            model = verify_recipe(package, selected['id'])
            env = dict(os.environ, XDG_DATA_HOME=str(companion / 'dependencies'),
                       TMPDIR=str(work / 'tmp'), PIP_CACHE_DIR=str(companion / 'dependencies/pip'),
                       HELIXSR_FORCE_PORTABLE='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
            env = host_environment(env)
            env.pop('HELIXSR_BUILD_WINE', None)
            env.pop('HELIXSR_BUILD_DATA', None)
            job['message'] = 'Checking installed Proton for local preparation'
            build_wine, runtime_notes = select_build_wine(self.home, env)
            if self.cancel.is_set():
                raise ValueError('Cancelled')
            if build_wine:
                env['HELIXSR_BUILD_WINE'] = str(build_wine)
            if modern and not build_wine:
                raise ValueError('No working installed Proton or Wine was found for shader compilation')
            build.write_text(modern_build_script() if modern else
                             build_only_script(setup, converter, bool(build_wine)), newline='\n')
            Path(env['TMPDIR']).mkdir()
            logfile = companion / 'records' / ('build-' + job['id'] + '.log')
            logfile.parent.mkdir(parents=True, exist_ok=True)
            job['message'] = 'Building local NVIDIA-derived network; no games are changed'
            with logfile.open('wb') as output:
                if runtime_notes:
                    output.write(('\n'.join(runtime_notes) + '\n').encode('utf-8'))
                    output.flush()
                self._spawn_compiler(['bash', str(build), '--yes'], cwd=package, env=env,
                                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                                start_new_session=True)
                deadline = time.monotonic() + 900
                while self.process.poll() is None:
                    job['log'] = text_tail(logfile, 8000)
                    if self.cancel.is_set() or time.monotonic() > deadline:
                        import signal
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(self.process.pid, signal.SIGTERM)
                        try:
                            self.process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(self.process.pid, signal.SIGKILL)
                            self.process.wait()
                        raise ValueError('Cancelled' if self.cancel.is_set() else 'Build timed out')
                    time.sleep(0.5)
                job['log'] = text_tail(logfile, 8000)
                check_build_exit(self.process.returncode, self.cancel.is_set(), job['log'])
            if self.cancel.is_set():
                raise ValueError('Cancelled')
            for name in (() if helix20_release.modern(release) else NETWORK):
                if not (package / name).is_file() or (package / name).stat().st_size < 1024:
                    raise ValueError('Generated HelixSR model files are missing or incomplete. '
                                     'See the build log; this is not an internet connection error.')
            if modern:
                release_adapter(release).verify_outputs(package)
            else:
                verify_outputs(package)
            api = pe_info(package / output_dll(release))
            if api['arch'] != 'x64' or not api['ffx']:
                raise ValueError('Prepared HelixSR DLL has an unsupported installation interface')
            build.unlink()
            final = companion / 'packages' / (selected['id'] + '-v' + release['version']
                                              + '-' + release['sha256'][:12] + '-' + model['recipe_sha256'][:12])
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                # A changed cache can be rebuilt without overwriting the previous owned path.
                final = final.with_name(final.name + '-' + job['id'][:8])
            os.replace(package, final)
            payloads = release_adapter(release).payload_files() if modern else PACKAGE_FILES + ('helixsr_setup.json',)
            if (final / 'amd-fsr' / AMD_FG).is_file():
                payloads += ('amd-fsr/' + AMD_FG,)
            record = dict(version=release['version'], path=str(final), release_sha256=release['sha256'],
                          files={n: sha(final / n) for n in payloads}, prepared_at=time.time(), variant=model)
            namespace = 'packages' if selected['id'] == DEFAULT_VARIANT else 'variant_packages_v1'
            self.cfg.setdefault(namespace, {})[str(final)] = record
            self.save()
            # Older managers must never discover a future non-default model as
            # an ordinary latest package through their legacy pointer/settings.
            if selected['id'] == DEFAULT_VARIANT:
                atomic_json(companion / 'records/package.json', record)
            records = self.package_index(index_path)
            if records is None and index_path.is_file():
                durable_copy(index_path, index_path.with_name('packages-v1-corrupt-' + job['id'] + '.json'))
            records = records or []
            records = [r for r in records if self._package_record(r, game, companion)
                       and r.get('path') != record['path']]
            atomic_json(index_path, dict(schema=1, packages=(records + [record])[-256:]))
            for n in payloads:
                (final / n).chmod(0o600)
            return version(record['version']), final, record
        finally:
            # Work is exclusively owned by this job. Logs and successful package remain.
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def action_compatible(data, action):
        # An unsupported renderer can still restore owned originals. Any other
        # assessment blocker (build, hashes, process, staging) remains decisive.
        return (data['compatibility'] == 'candidate' or
                action in ('disable', 'remove') and data.get('restore_eligible')
                and data.get('managed') and not data.get('recovery_available') or
                action in ('disable', 'remove') and data['compatibility'] == 'unsupported'
                and data.get('renderer_unsupported') and data.get('managed'))

    def preview(self, gid, action, dx12_confirmed=False, executable=None):
        with self.lock:
            game = self.get_game(gid)
            if action not in ('install', 'update', 'enable', 'disable', 'remove', 'adopt', 'recover') + menu_labels.ACTIONS:
                raise ValueError('Unknown action')
            if action == 'recover':
                journal = self.companion(game) / 'transaction/journal.json'
                if not journal.exists():
                    raise ValueError('No interrupted transaction')
                saved = load_json(journal)
                self.menu_change_guard(game, saved.get('before', {}))
                token = uuid.uuid4().hex
                self.previews[token] = dict(game=gid, action=action, fingerprint=None,
                                           expires=time.time()+120, dx12=False)
                saved = load_json(journal)
                return dict(token=token, action=action, name=game['name'],
                            route=(saved.get('previous') or {}).get('route', 'previous configuration'),
                            files=list(saved.get('before', {})),
                            select_upscaler='previous configuration',
                            warning='Recover the interrupted transaction before any new installation.')
            data = self.assess(game, executable=executable)
            rec = self.record(game)
            self.menu_change_guard(game, rec.get('baseline', {}))
            package = None
            if not self.action_compatible(data, action):
                raise ValueError('; '.join(data['reasons']))
            if action in menu_labels.ACTIONS:
                menu_labels.plan(self, game, data, rec, action)
            if action in ('install', 'update', 'enable'):
                self.validate_install_executable(data)
            if data['dx12_confirmation_needed'] and not dx12_confirmed and action in ('install', 'update'):
                raise ValueError('Confirm that this game is set to DirectX 12')
            if action == 'adopt' and not data['legacy']:
                raise ValueError('Only verified legacy direct installations can be imported')
            if data['legacy'] and action != 'adopt':
                raise ValueError('Import existing direct installation first')
            if action in ('install', 'update', 'enable'):
                if 'variant' in rec and not valid_variant(rec['variant']):
                    raise ValueError('Installed model identity needs review; use Update HelixSR with a supported model or remove it')
                package = self.package(game, data['route'],
                                       variant_id=rec['variant']['id'] if valid_variant(rec.get('variant')) else None,
                                       selection=rec.get('package_selection') if action == 'enable' else None,
                                       installed=rec if action == 'enable' else None)
                if not package:
                    raise ValueError('Exact installed package is unavailable; use Update HelixSR and review the change'
                                     if action == 'enable' else 'Prepare HelixSR on this drive first')
                if not self._verify_package_payloads(package, data['route']):
                    raise ValueError('Prepared package manifest is incomplete or changed. Rebuild required.')
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
            fingerprint = self.fingerprint(game, data, package=package)
            self.previews[token] = dict(game=gid, action=action, fingerprint=fingerprint,
                                       package_selection=package_selection(package[2]) if action in ('install', 'update', 'enable') else None,
                                       executable=data['selected_executable'] if not data['managed'] and data['route'] == 'optiscaler' else None,
                                       selected_executable=data['selected_executable'],
                                       expires=time.time()+120, dx12=dx12_confirmed)
            return dict(token=token, action=action, name=game['name'], route=data['route'],
                        selected_executable=data['selected_executable'],
                        files=self.planned_paths(game, data, action, package),
                        select_upscaler=(menu_labels.LABEL if action == 'labels_enable' else 'AMD FSR') if data['route'] == 'direct' else 'DLSS (or XeSS/FSR input)',
                        warning=('Cosmetic menu label only; it does not prove HelixSR is running. '
                                 'Close the game. Original menu bytes are restored when this option or HelixSR is disabled. '
                                 'Quality modes and frame-generation labels are unchanged.' if action in menu_labels.ACTIONS else
                                 'Close the game. Originals are retained for disable/remove. '
                                 'Owned OptiScaler configuration edits are preserved in installation records; '
                                 'enable restores them and update pins only HelixSR backend/provider paths. '
                                 'Game settings, overlay hotkeys and frame-generation choices are preserved.'
                                 if data['route'] == 'optiscaler' else
                                 'Close the game. Originals are retained for disable/remove. '
                                 'Game settings and frame generation are not changed.'),
                        expires_at=time.time()+120)

    def validate_install_executable(self, data):
        if data['route'] == 'optiscaler' and (not data.get('main_exe')
                or pe_info(Path(data['main_exe']))['arch'] != 'x64'):
            raise ValueError('Reviewed OptiScaler executable is missing or is not x64 Windows PE; disable/remove remain available')

    def fingerprint(self, game, data, include_package=True, package=AUTO_PACKAGE):
        # Observe game drift separately from an install's conflict checks.
        # Potential new dependencies must be stable before/after preparation.
        rec = self.record(game)
        paths = list(rec['baseline']) if rec else self.planned_paths(game, data, 'observe')
        if data['route'] == 'optiscaler':
            fg = str((Path(data['target']) / 'HelixSR' / AMD_FG).relative_to(Path(game['folder'])))
            if fg not in paths:
                paths.append(fg)
        files = {}
        files['route'] = data['route']
        files['target'] = data.get('target')
        files['selected_executable'] = data.get('selected_executable')
        executable = data.get('main_exe')
        files['executable_sha256'] = sha(executable) if executable and Path(executable).is_file() else None
        files['installation_record'] = rec
        files['menu_resource_sha256'] = data.get('menu_labels', {}).get('resource_sha256')
        for rel in paths:
            p = checked_path(Path(game['folder']), rel)
            files[rel] = sha(p) if p.is_file() else None
        files['manifest'] = sha(game['manifest']) if game.get('manifest') else None
        if package is AUTO_PACKAGE:
            package = self.package(game, data['route'])
        if package and include_package:
            files['package_path'] = str(package[1])
            files['package_identity'] = package_selection(package[2])
            files['package_files'] = {n: sha(package[1] / n) for n in package[2]['files']}
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    def planned_paths(self, game, data, action, package=AUTO_PACKAGE, release=None):
        rec, root = self.record(game), Path(game['folder'])
        if package is AUTO_PACKAGE:
            package = self.package(game, data['route'])
        payload = release or (package[2] if package else {})
        modern = is_modern(payload)
        if helix20_release.modern(payload) and data['route'] == 'direct' and action in ('install', 'update', 'enable', 'latest'):
            paths = list(rec.get('baseline', {}))
            for target in map(Path, data['targets']):
                additions = [target, target.with_name(target.stem + '.original.dll'), target.parent / 'helixsr-install.json']
                for path in additions:
                    rel = str(path.relative_to(root))
                    if rel not in paths:
                        if path != target and (path.exists() or path.is_symlink()):
                            raise ValueError('New upstream file conflicts with an unmanaged file: ' + rel)
                        paths.append(rel)
            return paths
        if (data['route'] == 'optiscaler' and is_modern(rec) and payload and not modern
                and action in ('install', 'update', 'enable', 'latest')):
            raise ValueError('Updating modern Scaler to legacy HelixSR is unsupported. '
                             'Remove HelixSR to restore original files first, then install the compatibility release.')
        if modern and data['route'] == 'optiscaler' and action in ('install', 'update', 'enable', 'latest'):
            target = Path(data['target'])
            names = [dest for _, dest in release_adapter(payload).scaler_pairs()] + ['OptiScaler.ini', 'HelixSR/helixsr-install.json']
            paths = list(rec.get('baseline', {}))
            for name in names:
                rel = str((target / name).relative_to(root))
                if rel not in paths:
                    path = checked_path(root, rel)
                    if path.exists() or path.is_symlink():
                        raise ValueError('New upstream file conflicts with an unmanaged file: ' + rel)
                    paths.append(rel)
            return paths
        if rec:
            paths = list(rec['baseline'])
            if action == 'labels_enable':
                rel = str(Path(menu_labels.WITCHER_XML))
                if rel not in paths:
                    paths.append(rel)
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
            with operation_lock(self.companion(game)):
                return self._execute_reviewed(game, preview)

    def _execute_reviewed(self, game, preview):
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
        data = self.assess(game, executable=preview.get('executable'))
        rec = self.record(game)
        self.menu_change_guard(game, rec.get('baseline', {}))
        if preview['action'] in menu_labels.ACTIONS:
            menu_labels.plan(self, game, data, rec, preview['action'])
        package = None
        if preview['action'] in ('install', 'update', 'enable'):
            package = self.package(game, data['route'],
                                   variant_id=rec['variant']['id'] if valid_variant(rec.get('variant')) else None,
                                   selection=preview.get('package_selection'))
        if (not self.action_compatible(data, preview['action'])
                or self.fingerprint(game, data, package=package) != preview['fingerprint']):
            raise ValueError('Game changed since preview; refresh and review again')
        return self.mutate(game, data, preview['action'], package)

    @game_locked
    def mutate(self, game, data, action, package=AUTO_PACKAGE, settings=None):
        root, companion = Path(game['folder']), self.companion(game)
        tx = companion / 'transaction'
        if tx.exists():
            raise ValueError('Interrupted transaction exists; recover it first')
        label_plan = menu_labels.plan(self, game, data, self.record(game), action) if action in menu_labels.ACTIONS else None
        self.menu_change_guard(game, self.record(game).get('baseline', {}))
        if package is AUTO_PACKAGE:
            rec = self.record(game)
            package = None
            if action in ('install', 'update', 'enable'):
                package = self.package(game, data['route'],
                                       variant_id=rec['variant']['id'] if valid_variant(rec.get('variant')) else None,
                                       selection=rec.get('package_selection') if action == 'enable' else None,
                                       installed=rec if action == 'enable' else None)
        paths = self.planned_paths(game, data, action, package)
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
                if data['route'] == 'optiscaler':
                    previous['selected_executable'] = data['selected_executable']
            if label_plan:
                rel = label_plan['path']
                expected = (menu_labels.digest(label_plan['original']) if action == 'labels_enable'
                            else previous['current'][rel])
                if before[rel] != expected or sha(root / rel) != before[rel]:
                    raise ValueError('Menu resource changed during transaction')
                if rel not in previous['baseline']:
                    if before[rel] is None:
                        raise ValueError('Menu original disappeared before transaction')
                    original_path = self.checked_menu_original(game, rel)
                    if original_path.exists():
                        if menu_labels.digest(menu_labels.read_resource(original_path)) != before[rel]:
                            raise ValueError('Menu original backup conflicts with current source')
                    else:
                        journal['new_menu_original'] = dict(path=rel, sha256=before[rel])
                        atomic_json(tx / 'journal.json', journal)
                        durable_copy(root / rel, original_path, before[rel])
                    previous['baseline'][rel] = before[rel]
                self.write_managed_bytes(root / rel, label_plan['payload'])
                previous['menu_labels'] = dict(enabled=action == 'labels_enable',
                    profile=label_plan['profile'], path=rel,
                    original_sha256=previous['baseline'][rel],
                    patched_sha256=(menu_labels.digest(label_plan['payload']) if action == 'labels_enable'
                                    else previous['menu_labels']['patched_sha256']))
            elif action == 'settings':
                if not settings or settings[0] not in self.mutable_config_paths(game, previous):
                    raise ValueError('Invalid settings transaction')
                self.write_managed(root / settings[0], settings[1])
                previous.setdefault('saved_configs', {})[settings[0]] = dict(
                    content=settings[1], sha256=hashlib.sha256(settings[1].encode('utf-8')).hexdigest())
            elif action == 'adopt':
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
                if action == 'disable' and not previous.get('package_selection'):
                    # Preserve a legacy enabled installation's exact cache before
                    # restoring its baseline. Already-disabled ambiguous records
                    # require an explicit update instead of a guessed upgrade.
                    with contextlib.suppress(ValueError, OSError, TypeError, KeyError):
                        installed = self.package(game, data['route'], installed=previous)
                        if installed:
                            previous['package_selection'] = package_selection(installed[2])
                self.retain_configs(game, previous, action)
                self.restore_baseline(game, previous)
                previous['enabled'] = False
                if isinstance(previous.get('menu_labels'), dict):
                    previous['menu_labels']['enabled'] = False
            elif action in ('install', 'update', 'enable'):
                if not package:
                    raise ValueError('Prepared package unavailable')
                self.retain_configs(game, previous, action)
                previous['enabled'], previous['version'] = True, package[2]['version']
                if package[2].get('variant'):
                    previous['variant'] = package[2]['variant']
                else:
                    previous.pop('variant', None)
                previous['package_selection'] = package_selection(package[2])
                previous['release_sha256'] = package[2].get('release_sha256')
                # Extend older managed records for newly introduced dependencies.
                # Their paths were conflict-checked, snapshotted and journaled above.
                for rel in paths:
                    previous['baseline'].setdefault(rel, before[rel])
                if helix20_release.modern(package[2]):
                    self.install_payload(game, data, previous, package, previous_version=(journal.get('previous') or {}).get('version'))
                else:
                    self.install_payload(game, data, previous, package)
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
                        dict(action=action, route=data['route'], version=previous['version'],
                             variant=previous.get('variant'), package_selection=previous.get('package_selection'),
                             verified=previous['current'], time=time.time()))
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

    def retain_configs(self, game, rec, action):
        if not rec.get('enabled'):
            return
        saved = dict(rec.get('saved_configs', {}))
        for rel in self.mutable_config_paths(game, rec):
            if (action in ('disable', 'remove') and rec['baseline'][rel] is None
                    and absent_path(checked_path(Path(game['folder']), rel))):
                continue
            saved[rel] = self.read_owned_config(game, rel)
        if saved:
            # These are installation records, never disposable rollback backups.
            atomic_json(self.companion(game) / 'records' / ('config-' + uuid.uuid4().hex + '.json'),
                        dict(action=action, configurations=saved, time=time.time()))
            rec['saved_configs'] = saved

    def unlink_managed(self, path):
        self.track_write(path, None)
        try:
            Path(path).unlink()
        except FileNotFoundError:
            # Already absent paths can also have an absent parent directory.
            # No directory entry changed, so there is nothing to persist.
            return
        sync_directory(Path(path).parent)

    def write_managed(self, path, content):
        self.write_managed_bytes(path, content.encode('utf-8'))

    def write_managed_bytes(self, path, payload):
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
        # Validate all saved originals before the first write. A changed backup
        # must never cause a partial restore, even when some files are absent.
        for rel, expected in rec['baseline'].items():
            if expected is not None:
                src = checked_path(companion, str(Path('originals') / rel))
                if not src.is_file() or sha(src) != expected:
                    raise ValueError('Original file hash mismatch: ' + rel)
        for rel, expected in rec['baseline'].items():
            p = checked_path(root, rel)
            if expected is None:
                self.unlink_managed(p)
            else:
                src = checked_path(companion, str(Path('originals') / rel))
                if sha(src) != expected:
                    raise ValueError('Original file hash mismatch: ' + rel)
                self.copy_atomic(src, p)

    @game_locked
    def rollback(self, game):
        root, tx = Path(game['folder']), self.companion(game) / 'transaction'
        journal = load_json(tx / 'journal.json')
        if not journal:
            raise ValueError('Transaction journal missing; manual inspection required')
        new_menu_original = menu_labels.new_original_intent(journal)
        self.menu_change_guard(game, journal.get('before', {}))
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
        if new_menu_original and self.record(game) == journal['previous']:
            original = self.checked_menu_original(game, new_menu_original['path'])
            # An exact journal-owned copy can be discarded after rollback.
            # Unknown partial or subsequently edited bytes remain for review.
            try:
                known = menu_labels.digest(menu_labels.read_resource(original)) == new_menu_original['sha256']
            except (OSError, ValueError):
                known = False
            if known:
                original.unlink()
                sync_directory(original.parent)
        shutil.rmtree(tx)

    def copy_atomic(self, src, dst, expected=None):
        source_hash = sha(src)
        if expected is not None and source_hash != expected:
            raise ValueError('Prepared package changed during installation')
        expected = expected or source_hash
        self.track_write(dst, expected)
        dst.parent.mkdir(parents=True, exist_ok=True)
        temp = dst.with_name(dst.name + '.helixsr-decky.tmp')
        try:
            shutil.copy2(src, temp)
            if sha(src) != expected or sha(temp) != expected:
                raise ValueError('Copy verification failed')
            with temp.open('r+b') as f:
                os.fsync(f.fileno())
            os.replace(temp, dst)
            sync_directory(dst.parent)
        finally:
            temp.unlink(missing_ok=True)

    def install_payload(self, game, data, rec, package, previous_version=None):
        root = Path(game['folder'])
        package_path, package_record = package[1], package[2]
        if data['route'] == 'direct':
            if helix20_release.modern(package_record):
                # The native FSR route provides SR only; DLSS FG needs Scaler and a DLSS FG game.
                keep = {str(p.relative_to(root)) for target in map(Path, rec['targets'])
                        for p in (target, target.with_name(target.stem + '.original.dll'), target.parent / 'helixsr-install.json')}
                obsolete = {rel: digest for rel, digest in rec['baseline'].items() if rel not in keep}
                if obsolete:
                    self.restore_baseline(game, {'baseline': obsolete})
            for target in map(Path, rec['targets']):
                rel = str(target.relative_to(root))
                original = self.companion(game) / 'originals' / rel
                if sha(original) != rec['baseline'][rel]:
                    raise ValueError('Original FidelityFX DLL changed')
                self.copy_atomic(original, target.with_name(target.stem + '.original.dll'))
                source_dll = output_dll(package_record)
                self.copy_atomic(package_path / source_dll, target, package_record['files'][source_dll])
                for name in (() if helix20_release.modern(package_record) else NETWORK):
                    self.copy_atomic(package_path / name, target.parent / name, package_record['files'][name])
                self.write_managed_json(target.parent / 'helixsr-install.json',
                            {'route': 'direct', 'owner': 'HelixSR Decky', 'helixsr': rec.get('version'),
                             'variant': rec.get('variant'), 'package_selection': rec.get('package_selection')})
        elif is_modern(package_record):
            target = Path(rec['target'])
            settings_path = package_path / 'helixsr-scaler/OptiScaler.ini'
            settings_bytes = settings_path.read_bytes()
            if hashlib.sha256(settings_bytes).hexdigest() != package_record['files']['helixsr-scaler/OptiScaler.ini']:
                raise ValueError('Prepared package changed during installation')
            template = settings_bytes.decode('utf-8')
            source = self.retained_config(rec, str((target / 'OptiScaler.ini').relative_to(root)))
            adapter = release_adapter(package_record)
            configured = (adapter.configuration(template if source is None else source, template, previous_version=previous_version)
                          if helix20_release.modern(package_record) else
                          adapter.configuration(template if source is None else source, template))
            pairs = release_adapter(package_record).scaler_pairs()
            modern_paths = {str((target / dest).relative_to(root)) for _, dest in pairs}
            modern_paths |= {str((target / name).relative_to(root)) for name in ('OptiScaler.ini', 'HelixSR/helixsr-install.json')}
            # Retire only old owned payloads through the same journal and saved originals.
            obsolete = {rel: digest for rel, digest in rec['baseline'].items()
                        if rel not in modern_paths and rel not in (menu_labels.WITCHER_XML,)}
            if obsolete:
                self.restore_baseline(game, {'baseline': obsolete})
            for source, dest in pairs:
                self.copy_atomic(package_path / source, target / dest, package_record['files'][source])
            if helix20_release.modern(package_record):
                rel = str((target / 'HelixSR-fsrfg/helixsr.ini').relative_to(root))
                retained = self.retained_config(rec, rel)
                if retained is not None:
                    self.write_managed(target / 'HelixSR-fsrfg/helixsr.ini', retained)
            self.write_managed(target / 'OptiScaler.ini', configured)
            self.write_managed_json(target / 'HelixSR/helixsr-install.json',
                        {'route': 'optiscaler', 'owner': 'HelixSR Decky', 'helixsr': rec.get('version'),
                         'variant': rec.get('variant'), 'package_selection': rec.get('package_selection')})
        else:
            target = Path(rec['target'])
            settings_path = package_path / 'optiscaler/OptiScaler.ini'
            settings_bytes = settings_path.read_bytes()
            if hashlib.sha256(settings_bytes).hexdigest() != package_record['files']['optiscaler/OptiScaler.ini']:
                raise ValueError('Prepared package changed during installation')
            template = settings_bytes.decode('utf-8')
            source = self.retained_config(rec, str((target / 'OptiScaler.ini').relative_to(root)))
            source = template if source is None else source
            settings = [('Dx12Upscaler', 'fsr31'),
                        ('FfxDx12Path', 'Z:' + str(target / 'HelixSR/helixsr.dll').replace('/', '\\')),
                        ('FfxDx12SRPath', 'Z:' + str(target / 'HelixSR/helixsr_upscaler.dll').replace('/', '\\'))]
            if (package_path / 'amd-fsr' / AMD_FG).is_file():
                settings.append(('FfxDx12FGPath', 'Z:' + str(target / 'HelixSR' / AMD_FG).replace('/', '\\')))
            from optiscaler_setup import pin_config
            configured_source = pin_config(source, template, settings)
            for source, dest in [('optiscaler/OptiScaler.dll', 'dxgi.dll'),
                                 ('optiscaler/fakenvapi.dll', 'fakenvapi.dll'),
                                 (DLL, 'HelixSR/helixsr.dll'), (DLL, 'HelixSR/helixsr_upscaler.dll'),
                                 ('amd-fsr/amd_fidelityfx_upscaler_dx12.dll', 'HelixSR/amd_fidelityfx_upscaler_dx12.amd.dll')]:
                self.copy_atomic(package_path / source, target / dest, package_record['files'][source])
            fake_rel = str((target / 'fakenvapi.ini').relative_to(root))
            fake = self.retained_config(rec, fake_rel)
            if fake is None and rec['baseline'].get(fake_rel) is not None:
                # Fresh installs retain a standalone fakenvapi configuration
                # instead of replacing the user's existing settings with defaults.
                existing = self.read_owned_config(game, fake_rel)
                if existing['sha256'] != rec['baseline'][fake_rel]:
                    raise ValueError('Existing configuration changed during installation: ' + fake_rel)
                fake = existing['content']
            if fake is None:
                self.copy_atomic(package_path / 'optiscaler/fakenvapi.ini', target / 'fakenvapi.ini',
                                 package_record['files']['optiscaler/fakenvapi.ini'])
            else:
                self.write_managed(target / 'fakenvapi.ini', fake)
            for name in NETWORK:
                self.copy_atomic(package_path / name, target / 'HelixSR' / name, package_record['files'][name])
            if (package_path / 'amd-fsr' / AMD_FG).is_file():
                name = 'amd-fsr/' + AMD_FG
                self.copy_atomic(package_path / name, target / 'HelixSR' / AMD_FG, package_record['files'][name])
            self.write_managed(target / 'OptiScaler.ini', configured_source)
            self.write_managed_json(target / 'HelixSR/helixsr-install.json',
                        {'route': 'optiscaler', 'owner': 'HelixSR Decky', 'helixsr': rec.get('version'),
                         'variant': rec.get('variant'), 'package_selection': rec.get('package_selection')})
