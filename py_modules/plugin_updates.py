"""Updates for the Decky plugin, independent of HelixSR game payloads."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import time
import urllib.request
import uuid
from urllib.parse import urlsplit
import zipfile

from manager import atomic_json, https_context

REPO = 'dawoodtogoo2020-code/HelixSR-Decky'
PAGE = f'https://github.com/{REPO}/releases'
API = f'https://api.github.com/repos/{REPO}/releases?per_page=30'
INTERVAL = 24 * 60 * 60
RETRY = 60 * 60
MAX_ARCHIVE = 16 << 20
PLUGIN_NAME = 'HelixSR Decky'
FOLDER = 'HelixSR-Decky'


def semver(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Unsupported plugin version')
    return tuple(int(x) for x in value.removeprefix('v').split('.'))


def release_info(item):
    if not isinstance(item, dict) or item.get('draft') or not item.get('published_at'):
        raise ValueError('Unpublished plugin release')
    tag = item.get('tag_name')
    numbers = semver(tag)
    version = '.'.join(map(str, numbers))
    # Track numbered beta releases while this plugin is in beta. Stable installs
    # do not opt into experimental prereleases.
    if item.get('prerelease') and numbers[0] != 0:
        raise ValueError('Experimental plugin release')
    if item.get('html_url') != f'{PAGE}/tag/{tag}':
        raise ValueError('Unexpected plugin release page')
    filename = f'{FOLDER}-{version}.zip'
    assets = item.get('assets')
    if not isinstance(assets, list):
        raise ValueError('Plugin release has no assets')
    for asset in assets:
        if not isinstance(asset, dict) or asset.get('name') != filename:
            continue
        url = f'https://github.com/{REPO}/releases/download/{tag}/{filename}'
        digest = asset.get('digest', '')
        size = asset.get('size')
        if (asset.get('browser_download_url') != url or not isinstance(digest, str)
                or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest)
                or type(size) is not int or not 0 < size <= MAX_ARCHIVE):
            raise ValueError('Plugin asset URL, size or SHA-256 is invalid')
        return dict(version=version, page=item['html_url'], url=url,
                    sha256=digest[7:].lower(), size=size, prerelease=bool(item.get('prerelease')))
    raise ValueError('Plugin release ZIP is missing')


def validate_zip(path, version):
    """Validate the whole archive before Decky can replace the installed plugin."""
    with zipfile.ZipFile(path) as archive:
        seen, total = set(), 0
        entries = archive.infolist()
        if not 1 <= len(entries) <= 1000:
            raise ValueError('Invalid plugin ZIP member count')
        for item in entries:
            name = item.filename
            parts = PurePosixPath(name).parts
            canonical = '/'.join(parts) + ('/' if item.is_dir() else '')
            total += item.file_size
            if (not parts or parts[0] != FOLDER or len(parts) < 2
                    or '\\' in name or ':' in name or '..' in parts
                    or PurePosixPath(name).is_absolute() or name != canonical or canonical.rstrip('/') in seen
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1 or total > 64 << 20
                    or item.compress_size and item.file_size / item.compress_size > 1000):
                raise ValueError('Unsafe plugin ZIP')
            seen.add(canonical.rstrip('/'))
        required = {f'{FOLDER}/{name}' for name in ('main.py', 'plugin.json', 'package.json', 'dist/index.js')}
        required.update(f'{FOLDER}/py_modules/{name}.py' for name in ('manager', 'library', 'awareness'))
        if semver(version) >= (0, 1, 1):
            required.add(f'{FOLDER}/py_modules/plugin_updates.py')
        if semver(version) >= (0, 1, 6):
            required.update(f'{FOLDER}/py_modules/{name}.py' for name in
                            ('optiscaler_setup', 'launch_receipts', 'operation_lock', 'host_environment'))
        if semver(version) >= (0, 1, 9):
            required.update(f'{FOLDER}/py_modules/{name}.py' for name in ('model_variants', 'build_runtime'))
        if semver(version) >= (0, 1, 14):
            required.update(f'{FOLDER}/py_modules/{name}.py' for name in
                            ('github_release', '_helix_html', '_helix_html_parser',
                             '_helix_html_entities', '_helix_markupbase'))
            required.update(f'{FOLDER}/licenses/{name}' for name in
                            ('cpython-3.11.17-LICENSE.txt', 'cpython-3.11.17-PROVENANCE.json'))
        if semver(version) >= (0, 1, 29):
            required.add(f'{FOLDER}/py_modules/compatibility_release.py')
        if not required <= seen:
            raise ValueError('Incomplete plugin ZIP')
        for name in ('plugin.json', 'package.json'):
            entry = archive.getinfo(f'{FOLDER}/{name}')
            if entry.file_size > 64 << 10:
                raise ValueError('Oversized plugin manifest')
        manifest = json.loads(archive.read(f'{FOLDER}/plugin.json'))
        package = json.loads(archive.read(f'{FOLDER}/package.json'))
        if (not isinstance(manifest, dict) or manifest.get('name') != PLUGIN_NAME
                or manifest.get('flags') != [] or manifest.get('api_version') != 1
                or not isinstance(package, dict) or package.get('name') != 'helixsr-decky'
                or package.get('version') != version):
            raise ValueError('Plugin ZIP identity, permissions or version mismatch')
        if archive.testzip() is not None:
            raise ValueError('Corrupt plugin ZIP')


class PluginUpdates:
    def __init__(self, settings, package):
        self.settings = Path(settings).resolve()
        self.path = self.settings / 'plugin-updates.json'
        self.stage = self.settings / 'plugin-updates'
        self.current = json.loads(Path(package).read_text())['version']
        semver(self.current)
        self.lock = threading.RLock()
        self.pending = None
        self.pending_release = None
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        self.enabled = saved.get('auto_check', True) if isinstance(saved, dict) else True
        self.enabled = self.enabled if type(self.enabled) is bool else True
        self.release = None
        self.checked_at = self.attempted_at = 0
        self.error = ''
        # Startup checks are cheap metadata requests. Never trust old cached
        # download instructions from a settings file after a plugin reload.

    def status(self):
        with self.lock:
            return dict(current_version=self.current, latest_version=self.release['version'] if self.release else None,
                        update_available=bool(self.release and semver(self.release['version']) > semver(self.current)),
                        auto_check=self.enabled, checked_at=self.checked_at, attempted_at=self.attempted_at,
                        error=self.error, page=self.release['page'] if self.release else PAGE,
                        pending=bool(self.pending))

    def set_auto(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Automatic plugin checks require a boolean')
        with self.lock:
            self.enabled = enabled
            atomic_json(self.path, {'auto_check': enabled})
            return self.status()

    def due(self):
        with self.lock:
            now = time.time()
            return self.enabled and now - self.attempted_at >= RETRY and now - self.checked_at >= INTERVAL

    def check(self, force=False):
        with self.lock:
            now = time.time()
            if not force and not self.due():
                return self.status()
            self.attempted_at = now
            try:
                request = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                    'User-Agent': f'HelixSR-Decky/{self.current}', 'X-GitHub-Api-Version': '2022-11-28'})
                with urllib.request.urlopen(request, timeout=20, context=https_context()) as response:
                    if response.geturl() != API:
                        raise ValueError('Unexpected plugin metadata redirect')
                    raw = response.read((1 << 20) + 1)
                if len(raw) > 1 << 20:
                    raise ValueError('Plugin metadata too large')
                releases = json.loads(raw)
                if not isinstance(releases, list):
                    raise ValueError('Invalid plugin release feed')
                candidates = []
                for item in releases:
                    try:
                        candidates.append(release_info(item))
                    except (ValueError, TypeError):
                        continue
                if not candidates:
                    raise ValueError('No numbered plugin release with a verified ZIP digest is available')
                self.release = max(candidates, key=lambda r: semver(r['version']))
                self.checked_at = now
                self.error = ''
            except (OSError, ValueError, TypeError) as exc:
                self.error = f'Plugin update check failed: {exc}'
            return self.status()

    def prepare(self):
        with self.lock:
            if self.pending:
                raise ValueError('A plugin update is already awaiting Decky confirmation')
            status = self.check(True)
            if status['error'] or not status['update_available']:
                raise ValueError(status['error'] or 'The installed plugin is up to date')
            release = dict(self.release)
            if self.stage.is_symlink():
                raise ValueError('Plugin update directory is a symlink')
            self.stage.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.stage).free < release['size'] * 2 + (16 << 20):
                raise ValueError('Not enough space to stage the plugin update')
            cached = self.stage / f"{FOLDER}-{release['version']}-{release['sha256']}.zip"
            destination = self.stage / f"{FOLDER}-{release['version']}-{release['sha256']}-{uuid.uuid4().hex}.zip"
            if destination.is_symlink():
                raise ValueError('Plugin update artifact is a symlink')
            # A reload or dismissed installer can leave a verified ZIP behind.
            # Reuse it only after checking the fresh release metadata and ZIP.
            if cached.exists() or cached.is_symlink():
                if cached.is_symlink() or not cached.is_file():
                    raise ValueError('Plugin update artifact is not a regular file')
                valid = (cached.stat().st_size == release['size']
                         and hashlib.sha256(cached.read_bytes()).hexdigest() == release['sha256'])
                if valid:
                    try:
                        validate_zip(cached, release['version'])
                    except (ValueError, zipfile.BadZipFile):
                        valid = False
                if valid:
                    os.replace(cached, destination)
                    self.pending = destination
                    self.pending_release = release
                    return self.artifact(release)
                # The exact private staging filename belongs to this updater.
                # A failed cached artifact must not permanently block retries.
                cached.unlink()
            temporary = destination.with_suffix('.download-' + uuid.uuid4().hex)
            try:
                request = urllib.request.Request(release['url'], headers={'User-Agent': f'HelixSR-Decky/{self.current}'})
                digest, count = hashlib.sha256(), 0
                with urllib.request.urlopen(request, timeout=30, context=https_context()) as response:
                    parsed = urlsplit(response.geturl())
                    if parsed.scheme != 'https' or parsed.hostname not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
                        raise ValueError('Unexpected plugin download host')
                    with temporary.open('xb') as output:
                        while chunk := response.read(1 << 20):
                            count += len(chunk)
                            if count > release['size']:
                                raise ValueError('Plugin download exceeds its declared size')
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                if count != release['size'] or digest.hexdigest() != release['sha256']:
                    raise ValueError('Plugin update SHA-256 or size mismatch')
                validate_zip(temporary, release['version'])
                os.replace(temporary, destination)
                self.pending = destination
                self.pending_release = release
                # Decky's local artifact protocol uses a raw absolute filesystem path.
                return self.artifact(release)
            finally:
                temporary.unlink(missing_ok=True)

    def artifact(self, release):
        return dict(artifact='file://' + str(self.pending), name=PLUGIN_NAME,
                    version=release['version'], sha256=release['sha256'], install_type=2)

    def resume(self):
        """Reopen the exact downloaded update, independent of later feed changes."""
        with self.lock:
            if not self.pending or not self.pending_release:
                raise ValueError('No downloaded plugin update; check for updates first')
            release = self.pending_release
            if (self.pending.is_symlink() or not self.pending.is_file()
                    or self.pending.stat().st_size != release['size']
                    or hashlib.sha256(self.pending.read_bytes()).hexdigest() != release['sha256']):
                raise ValueError('Downloaded update changed or is missing. Cancel it and download again')
            validate_zip(self.pending, release['version'])
            return self.artifact(release)

    def cleanup_installed(self):
        """Invalidate orphaned prompts on backend startup, and clean owned ZIPs.

        Decky reads the ZIP into memory before unloading the old backend. A new
        backend can remove these files without interrupting that installation.
        Unconfirmed requests must never become usable again during game work.
        """
        if not self.stage.is_dir() or self.stage.is_symlink():
            return
        for path in self.stage.iterdir():
            match = re.fullmatch(r'HelixSR-Decky-(\d+\.\d+\.\d+)-([0-9a-f]{64})(?:-[0-9a-f]{32})?\.zip', path.name)
            if not match or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
                continue
            version, digest = match.groups()
            try:
                if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                    validate_zip(path, version)
                    path.unlink()
            except (OSError, ValueError, zipfile.BadZipFile):
                continue

    def cancel(self):
        with self.lock:
            if self.pending:
                # An unconfirmed stale Decky prompt can no longer read this ZIP.
                self.pending.unlink(missing_ok=True)
                self.pending = None
                self.pending_release = None
            return self.status()
