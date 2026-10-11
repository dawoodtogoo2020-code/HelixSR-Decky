"""Verify standalone AppImage releases independently of game/plugin updates."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

from manager import atomic_json, https_context
from .version import VERSION

REPO = 'dawoodtogoo2020-code/HelixSR-Decky'
PAGE = f'https://github.com/{REPO}/releases'
API = f'https://api.github.com/repos/{REPO}/releases?per_page=100'
MAX_IMAGE = 512 << 20
INTERVAL = 24 * 3600
RETRY = 3600


def semver(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Invalid desktop version')
    return tuple(map(int, value.split('.')))


def release_info(item):
    if not isinstance(item, dict) or item.get('draft') or item.get('prerelease') or not item.get('published_at'):
        raise ValueError('Unpublished or experimental desktop release')
    tag = item.get('tag_name', '')
    if not isinstance(tag, str) or not tag.startswith('desktop-v'):
        raise ValueError('Not a desktop release')
    version = tag[len('desktop-v'):]
    semver(version)
    if item.get('html_url') != f'{PAGE}/tag/{tag}':
        raise ValueError('Unexpected desktop release page')
    filename = f'HelixSR-Desktop-{version}-x86_64.AppImage'
    if not isinstance(item.get('assets'), list):
        raise ValueError('Missing desktop assets')
    matches = [x for x in item['assets'] if isinstance(x, dict) and x.get('name') == filename]
    if len(matches) != 1:
        raise ValueError('Expected exactly one desktop AppImage')
    asset = matches[0]
    url = f'https://github.com/{REPO}/releases/download/{tag}/{filename}'
    size, digest = asset.get('size'), asset.get('digest')
    if (asset.get('browser_download_url') != url or type(size) is not int
            or not 0 < size <= MAX_IMAGE or not isinstance(digest, str)
            or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest)):
        raise ValueError('Desktop asset URL, size or SHA-256 is invalid')
    return dict(version=version, filename=filename, url=url, size=size,
                sha256=digest[7:].lower(), page=item['html_url'])


class AppUpdates:
    def __init__(self, settings):
        self.settings = Path(settings).resolve()
        self.path = self.settings / 'app-updates.json'
        self.stage = self.settings / 'app-updates'
        self.lock = threading.RLock()
        self.current = VERSION
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        self.enabled = saved.get('auto_check', True) if isinstance(saved, dict) else True
        if type(self.enabled) is not bool:
            self.enabled = True
        self.release = None
        self.error = ''
        self.checked_at = self.attempted_at = 0

    def status(self):
        with self.lock:
            latest = self.release['version'] if self.release else None
            return dict(current_version=self.current, latest_version=latest,
                current=self.current, latest=latest, update_available=bool(latest and semver(latest) > semver(self.current)),
                auto_check=self.enabled, checked_at=self.checked_at, attempted_at=self.attempted_at,
                error=self.error, page=self.release['page'] if self.release else PAGE,
                release=dict(self.release) if self.release else None)

    def set_auto(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Automatic desktop update checks require a boolean')
        with self.lock:
            self.enabled = enabled
            atomic_json(self.path, {'auto_check': enabled})
            return self.status()

    def check(self, force=False):
        with self.lock:
            now = time.time()
            if not force and (not self.enabled or now - self.attempted_at < RETRY or now - self.checked_at < INTERVAL):
                return self.status()
            self.attempted_at = now
            try:
                request = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                    'User-Agent': f'HelixSR-Desktop/{self.current}', 'X-GitHub-Api-Version': '2022-11-28'})
                with urllib.request.urlopen(request, timeout=20, context=https_context()) as response:
                    if response.geturl() != API:
                        raise ValueError('Unexpected desktop metadata redirect')
                    raw = response.read((4 << 20) + 1)
                if len(raw) > 4 << 20:
                    raise ValueError('Desktop metadata too large')
                items = json.loads(raw)
                if not isinstance(items, list):
                    raise ValueError('Invalid desktop release feed')
                candidates = []
                for item in items:
                    try:
                        candidates.append(release_info(item))
                    except (ValueError, TypeError):
                        continue
                if not candidates:
                    raise ValueError('No official desktop release with a verified AppImage digest is available')
                self.release = max(candidates, key=lambda x: semver(x['version']))
                self.checked_at, self.error = now, ''
            except (OSError, ValueError, TypeError, http.client.HTTPException) as exc:
                self.error = f'Desktop update check failed: {exc}'
            return self.status()

    def download(self):
        with self.lock:
            status = self.check(True)
            if status['error'] or not status['update_available']:
                raise ValueError(status['error'] or 'The desktop application is up to date')
            release = dict(self.release)
            if self.stage.is_symlink():
                raise ValueError('Desktop update directory cannot be a symlink')
            self.stage.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.stage).free < release['size'] + (16 << 20):
                raise ValueError('Not enough space to download the desktop AppImage')
            destination = self.stage / (release['filename'] + '-' + uuid.uuid4().hex + '.AppImage')
            temporary = self.stage / ('.download-' + uuid.uuid4().hex)
            try:
                request = urllib.request.Request(release['url'], headers={'User-Agent': f'HelixSR-Desktop/{self.current}'})
                digest, count = hashlib.sha256(), 0
                with urllib.request.urlopen(request, timeout=30, context=https_context()) as response:
                    parsed = urlsplit(response.geturl())
                    if (parsed.scheme != 'https' or parsed.hostname not in
                            ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
                            or parsed.username or parsed.password or parsed.port not in (None, 443)):
                        raise ValueError('Unexpected desktop download host')
                    with temporary.open('xb') as output:
                        while chunk := response.read(1 << 20):
                            count += len(chunk)
                            if count > release['size']:
                                raise ValueError('Desktop download exceeds its declared size')
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                if count != release['size'] or digest.hexdigest() != release['sha256']:
                    raise ValueError('Desktop update SHA-256 or size mismatch')
                os.chmod(temporary, 0o700)
                os.replace(temporary, destination)
                return dict(path=str(destination), version=release['version'], sha256=release['sha256'], size=count)
            finally:
                temporary.unlink(missing_ok=True)
