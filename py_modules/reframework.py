"""Optional REFramework loader for RE Engine games that need it beside HLX FSR 4.

A Steam Deck tester found that Resident Evil Requiem shows an unhandled exception
at startup with HLX FSR 4 unless REFramework's dinput8.dll is loaded. On the tester's
Steam Deck, Proton loaded the DLL from the game folder without a launch option
(PRAGMATA, 2026-11-13); the native-first dinput8 override stays available as a
fallback. This module adds only that DLL, never replaces an existing file, and
removes only the exact bytes it recorded.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

REPO = 'praydog/REFramework-nightly'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
PAGE = f'https://github.com/{REPO}/releases'
ASSET = 'REFramework.zip'
DLL = 'dinput8.dll'
REVISION = 'reframework_revision.txt'
RECORD = 'reframework.json'
MAX_METADATA = 1 << 20
MAX_ARCHIVE = 64 << 20
MAX_DLL = 96 << 20
TAG = re.compile(r'nightly-(\d{1,7})-([0-9a-f]{40})\Z')
DIGEST = re.compile(r'sha256:([0-9a-f]{64})\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
OVERRIDE = 'WINEDLLOVERRIDES="dinput8=n,b" %command%'
ASSET_HOSTS = ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')

# Steam app IDs named by the tester. Requiem and PRAGMATA have been checked on a Steam Deck.
GAMES = {
    '3764200': dict(name='Resident Evil Requiem', tested=True,
                    evidence='A Steam Deck tester confirmed that Resident Evil Requiem needs REFramework\'s loader '
                             'for HLX FSR 4. Without it the game shows an unhandled exception at startup. '
                             'HelixSR 2.0 Model E worked without it.'),
    '2246340': dict(name='Monster Hunter Wilds', tested=False, evidence=None),
    '3357650': dict(name='PRAGMATA', tested=True,
                    evidence='A Steam Deck tester confirmed that PRAGMATA works with HLX FSR 4 and REFramework\'s '
                             'loader on the first try, with no launch option. In Graphics, Upscaling shows AMD FSR3 '
                             'and its description reads "Uses AMD FSR HLX FSR 4 (4.1.2)".'),
    '2638890': dict(name='Onimusha: Way of the Sword', tested=False, evidence=None),
}


def game_entry(game):
    if game.get('source') != 'Steam':
        return None
    return GAMES.get(str(game.get('appid') or ''))


def within(root, path):
    """Return path below root, refusing links in any component."""
    root = Path(root)
    relative = Path(path).relative_to(root)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Loader path escapes the game folder')
    current = root / relative
    while current != root:
        if current.is_symlink():
            raise ValueError('Loader path contains a symlink')
        current = current.parent
    if root.is_symlink():
        raise ValueError('Game folder is a symlink')
    return root / relative


def target_path(folder, main_exe):
    if not main_exe:
        raise ValueError('The game executable was not found, so the loader folder is unknown')
    exe = Path(main_exe)
    directory = within(folder, exe.parent)
    return directory / DLL, (directory / DLL).relative_to(Path(folder)).as_posix()


_hashes = {}


def file_sha(path, cached=False):
    """SHA-256 of a file. Only read-only status may reuse a hash: a same-size
    rewrite inside the filesystem's timestamp granularity keeps the stat key."""
    info = os.stat(path, follow_symlinks=False)
    key = (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if not cached or key not in _hashes:
        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                digest.update(chunk)
        if len(_hashes) > 64:
            _hashes.clear()
        _hashes[key] = digest.hexdigest()
    return _hashes[key]


def _clean(text, limit=100):
    return re.sub(r'[^A-Za-z0-9 ._:+-]', '', str(text))[:limit].strip()


def validate_record(record):
    if (not isinstance(record, dict) or set(record) != {'version', 'file', 'sha256', 'tag', 'revision'}
            or record['version'] != 1 or not isinstance(record['file'], str)
            or not isinstance(record['sha256'], str) or not HEX.fullmatch(record['sha256'])
            or not isinstance(record['tag'], str) or not TAG.fullmatch(record['tag'])
            or not isinstance(record['revision'], str) or record['revision'] != _clean(record['revision'])):
        raise ValueError('Invalid REFramework ownership record; review it manually')
    parts = Path(record['file']).parts
    if Path(record['file']).is_absolute() or '..' in parts or not parts or parts[-1] != DLL:
        raise ValueError('Invalid REFramework ownership record path')
    return record


def _records(companion):
    directory = Path(companion) / 'records'
    for path in (directory, directory / RECORD):
        if path.is_symlink():
            raise ValueError('REFramework record path cannot be a symlink')
    return directory


def read_record(companion):
    path = _records(companion) / RECORD
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise ValueError('Invalid REFramework ownership record')
    return validate_record(json.loads(path.read_text()))


def _sync(directory):
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_record(companion, record):
    directory = _records(companion)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECORD
    if record is None:
        path.unlink(missing_ok=True)
        _sync(directory)
        return
    payload = (json.dumps(validate_record(record), sort_keys=True) + '\n').encode()
    temp = directory / f'.{RECORD}.{uuid.uuid4().hex}.tmp'
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _sync(directory)
    finally:
        temp.unlink(missing_ok=True)


def status(game, data, companion):
    """Read-only loader state for a supported Steam title, or None."""
    entry = game_entry(game)
    if not entry:
        return None
    result = dict(game=entry['name'], tested=entry['tested'], evidence=entry['evidence'], override=OVERRIDE,
                  source=PAGE, state='unavailable', reason='', file=None, tag=None, revision=None)
    try:
        target, relative = target_path(game['folder'], data.get('main_exe'))
        result['file'] = relative
        record = read_record(companion)
        present = os.path.lexists(target)
        if record:
            result.update(tag=record['tag'], revision=record['revision'])
        if present and (target.is_symlink() or not target.is_file()):
            result.update(state='foreign', reason='dinput8.dll is not a regular file. HelixSR leaves it alone.')
        elif record and record['file'] != relative:
            result.update(state='review', reason=f"HelixSR recorded {record['file']}, but the game executable is now in another folder. Review it manually.")
        elif record and not present:
            result.update(state='missing', reason='The dinput8.dll HelixSR added is no longer in the game folder.')
        elif record:
            same = file_sha(target, cached=True) == record['sha256']
            result.update(state='installed' if same else 'changed',
                          reason='' if same else 'dinput8.dll changed after HelixSR added it, for example a newer REFramework. HelixSR leaves it alone.')
        elif present:
            result.update(state='foreign', reason='An existing dinput8.dll is present (REFramework or another mod). HelixSR keeps it and cannot verify its version.')
        else:
            result['state'] = 'absent'
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.update(state='unavailable', reason=str(exc))
    return result


def _urlopen(request, context, timeout):
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def latest_release(context):
    request = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                                                   'User-Agent': 'HelixSR-Decky', 'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with _urlopen(request, context, 20) as response:
            data = response.read(MAX_METADATA + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise ValueError('GitHub is limiting requests right now. Try again in a few minutes.') from exc
        raise ValueError(f'Could not read the latest REFramework release (HTTP {exc.code}).') from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError('Could not reach GitHub to read the latest REFramework release.') from exc
    if len(data) > MAX_METADATA:
        raise ValueError('REFramework release metadata is too large')
    try:
        release = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Malformed REFramework release metadata') from exc
    tag = release.get('tag_name') if isinstance(release, dict) else None
    match = TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match or release.get('draft') or not isinstance(release.get('assets'), list):
        raise ValueError('Unexpected REFramework release metadata')
    assets = [a for a in release['assets'] if isinstance(a, dict) and a.get('name') == ASSET]
    if len(assets) != 1:
        raise ValueError(f'The latest REFramework release has no single {ASSET}')
    asset = assets[0]
    digest = DIGEST.fullmatch(asset.get('digest') or '') if isinstance(asset.get('digest'), str) else None
    size = asset.get('size')
    url = f'https://github.com/{REPO}/releases/download/{tag}/{ASSET}'
    if not digest:
        raise ValueError('GitHub did not publish a SHA-256 digest for REFramework.zip, so it cannot be verified')
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE or asset.get('browser_download_url') != url:
        raise ValueError('Unexpected REFramework download size or location')
    return dict(tag=tag, build=int(match.group(1)), commit=match.group(2), sha256=digest.group(1),
                size=size, url=url, page=f'{PAGE}/tag/{tag}')


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, path):
        self.path = path
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > 3 or not allowed_asset_url(newurl, self.path):
            raise ValueError('Unexpected REFramework download redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def allowed_asset_url(url, path):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.username or parts.password or parts.port is not None
            or parts.netloc.lower() != (parts.hostname or '')):
        return False
    if parts.hostname == 'github.com':
        return parts.path == path and not parts.query
    return parts.hostname in ASSET_HOSTS


def _open_asset(url, context):
    path = urllib.parse.urlsplit(url).path
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _Redirect(path))
    response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'HelixSR-Decky'}), timeout=60)
    if not allowed_asset_url(response.geturl(), path):
        response.close()
        raise ValueError('Unexpected REFramework download destination')
    return response


def download(release, destination, context, cancelled=lambda: False):
    """Download the archive to destination and verify GitHub's size and digest."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == release['size'] and file_sha(destination) == release['sha256']:
        return destination
    temp = destination.with_name(destination.name + f'.{uuid.uuid4().hex}.part')
    digest, total = hashlib.sha256(), 0
    try:
        try:
            with _open_asset(release['url'], context) as response, open(temp, 'xb') as out:
                for chunk in iter(lambda: response.read(1 << 20), b''):
                    if cancelled():
                        raise ValueError('REFramework download cancelled')
                    total += len(chunk)
                    if total > release['size']:
                        raise ValueError('REFramework download is larger than GitHub reported')
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        except (urllib.error.URLError, OSError) as exc:
            raise ValueError('Could not download REFramework from GitHub.') from exc
        if total != release['size'] or digest.hexdigest() != release['sha256']:
            raise ValueError('REFramework download did not match GitHub\'s SHA-256 digest')
        os.replace(temp, destination)
        return destination
    finally:
        temp.unlink(missing_ok=True)


def check_dll(payload):
    if len(payload) < 0x200 or payload[:2] != b'MZ':
        raise ValueError('REFramework dinput8.dll is not a Windows DLL')
    offset = struct.unpack_from('<I', payload, 0x3c)[0]
    if offset + 24 > len(payload) or payload[offset:offset + 4] != b'PE\0\0':
        raise ValueError('REFramework dinput8.dll is not a Windows DLL')
    machine, characteristics = struct.unpack_from('<H', payload, offset + 4)[0], struct.unpack_from('<H', payload, offset + 22)[0]
    if machine != 0x8664 or not characteristics & 0x2000:
        raise ValueError('REFramework dinput8.dll is not a 64-bit Windows DLL')


def extract(archive):
    """Return (dll bytes, revision) from the monolithic REFramework.zip."""
    try:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if (len(infos) > 8 or len(set(names)) != len(names) or DLL not in names
                    or any(n not in (DLL, REVISION) for n in names)):
                raise ValueError('Unexpected REFramework archive layout; only dinput8.dll is installed from REFramework.zip')
            for info in infos:
                if (info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.file_size > MAX_DLL
                        or info.compress_size and info.file_size / info.compress_size > 200):
                    raise ValueError('Unsafe REFramework archive member')
            payload = z.read(DLL)
            revision = _clean(z.read(REVISION).decode('ascii', 'replace')) if REVISION in names else ''
    except zipfile.BadZipFile as exc:
        raise ValueError('REFramework.zip is not a valid archive') from exc
    check_dll(payload)
    return payload, revision


def install(target, payload):
    """Create target from payload without replacing anything that exists."""
    target = Path(target)
    expected = hashlib.sha256(payload).hexdigest()
    temp = target.with_name(f'.{DLL}.helixsr-decky-{uuid.uuid4().hex}.tmp')
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if file_sha(temp) != expected:
            raise ValueError('REFramework loader copy failed verification')
        try:
            os.link(temp, target)
        except FileExistsError as exc:
            raise ValueError('A dinput8.dll appeared in the game folder; HelixSR left it unchanged') from exc
        except OSError:
            # Some removable-drive filesystems lack hard links. O_EXCL still
            # refuses an existing file; a partial copy is removed on failure.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if file_sha(target) != expected:
                    raise ValueError('REFramework loader copy failed verification')
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        _sync(target.parent)
    finally:
        temp.unlink(missing_ok=True)
    return expected


def remove(target, record):
    target = Path(target)
    if not os.path.lexists(target):
        return
    if target.is_symlink() or not target.is_file() or file_sha(target) != record['sha256']:
        raise ValueError('dinput8.dll changed after HelixSR added it, so HelixSR leaves it alone')
    target.unlink()
    _sync(target.parent)
