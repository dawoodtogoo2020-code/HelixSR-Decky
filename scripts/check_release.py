"""Check the complete release asset set before publishing. No files are extracted."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
from plugin_updates import semver, validate_zip


SOURCE_PREFIX = 'HelixSR-Decky-source'
SOURCE_REQUIRED = {
    'src/index.tsx', 'package.json', 'plugin.json', 'main.py',
    'scripts/package.py', 'pnpm-lock.yaml', 'LICENSE',
}


def _check_source(path, version):
    seen, files = set(), set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = member.name
            parts = PurePosixPath(name).parts
            canonical = '/'.join(parts)
            if (not parts or parts[0] != SOURCE_PREFIX
                    or PurePosixPath(name).is_absolute() or '..' in parts
                    or '\\' in name or ':' in name
                    or (name != canonical and not (member.isdir() and name == canonical + '/'))
                    or canonical in seen
                    or not (member.isfile() or member.isdir())
                    or (len(parts) == 1 and not member.isdir())):
                raise ValueError('Unsafe source archive member: ' + name)
            seen.add(canonical)
            relative = '/'.join(parts[1:])
            if (set(parts[1:]) & {'.git', 'node_modules', 'dist', 'release', '__pycache__'}
                    or PurePosixPath(relative).suffix.lower() in
                    {'.dll', '.exe', '.so', '.bin', '.pak', '.pyc', '.zip'}):
                raise ValueError('Generated or binary payload in source archive: ' + name)
            if member.isfile():
                files.add(relative)
            if relative == 'package.json' and member.isfile():
                if member.size > 64 << 10:
                    raise ValueError('Oversized source package manifest')
                package = json.load(archive.extractfile(member))
                if (not isinstance(package, dict) or package.get('name') != 'helixsr-decky'
                        or package.get('version') != version):
                    raise ValueError('Source package identity or version mismatch')
        missing = SOURCE_REQUIRED - files
        if missing:
            raise ValueError('Incomplete source archive: ' + ', '.join(sorted(missing)))


def check_release(release_dir, version=None, source_root=ROOT):
    """Validate assets and install links; return the verified asset filenames."""
    release_dir, source_root = Path(release_dir), Path(source_root)
    if version is None:
        version = json.loads((source_root / 'package.json').read_text(encoding='utf-8'))['version']
    semver(version)
    runtime = f'HelixSR-Decky-{version}.zip'
    source = f'HelixSR-Decky-{version}-source.tar.gz'
    expected = {runtime, source, 'SHA256SUMS'}
    actual = {path.name for path in release_dir.iterdir()}
    if actual != expected or any(not path.is_file() or path.is_symlink() for path in release_dir.iterdir()):
        raise ValueError('Release must contain exactly: ' + ', '.join(sorted(expected)))

    hashes = {}
    for line in (release_dir / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *]([^/\\]+)', line)
        if not match or match[2] in hashes:
            raise ValueError('Invalid or duplicate SHA256SUMS entry')
        hashes[match[2]] = match[1].lower()
    if set(hashes) != {runtime, source}:
        raise ValueError('SHA256SUMS must cover exactly the runtime and source assets')
    for name, expected_hash in hashes.items():
        digest = hashlib.sha256()
        with (release_dir / name).open('rb') as payload:
            for chunk in iter(lambda: payload.read(1 << 20), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            raise ValueError('SHA256 mismatch: ' + name)

    validate_zip(release_dir / runtime, version)
    with zipfile.ZipFile(release_dir / runtime) as archive:
        manifest = json.loads(archive.read('HelixSR-Decky/package.json'))
        if manifest.get('type') != 'module':
            raise ValueError('Runtime package must declare ESM module type')
    _check_source(release_dir / source, version)
    url = (f'https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/'
           f'download/v{version}/{runtime}')
    for name in ('README.md', 'INSTALL_GUIDE.md'):
        if url not in (source_root / name).read_text(encoding='utf-8'):
            raise ValueError(f'{name} must link the current runtime ZIP: {url}')
    return sorted(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release_dir', type=Path)
    args = parser.parse_args()
    try:
        assets = check_release(args.release_dir)
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Release check failed: {error}\n')
    print('Release check passed: ' + ', '.join(assets))


if __name__ == '__main__':
    main()
