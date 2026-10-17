"""Verified private tools for the unchanged official converter."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile

PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-unknown-linux-gnu-install_only.tar.gz'
PYTHON_SHA256 = 'f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5'
DXC_URL = 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip'
DXC_SHA256 = 'a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241'
# Exact CPython 3.12 Linux x86_64 wheel from https://pypi.org/pypi/numpy/2.5.3/json
NUMPY_VERSION = '2.5.3'
NUMPY_WHEEL = 'numpy-2.5.3-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
NUMPY_URL = 'https://files.pythonhosted.org/packages/65/af/aa78d1a88805456e212b65461354cd943197fb9acecc4c90fd12295123a3/' + NUMPY_WHEEL
NUMPY_SHA256 = 'b7e18c623bb5c95acb3b3328861272816ba199fb531921c5d6d0b675f1fde9e3'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def fetch(url, destination, expected):
    subprocess.run(['curl', '-fL', '--retry', '0', '--connect-timeout', '30',
                    '--max-time', '300', '-o', str(destination), url], check=True)
    if digest(destination) != expected:
        raise ValueError('Build dependency archive hash mismatch')


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if rel == 'verified-tools.json':
            continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()) or not path.exists():
                raise ValueError('Unsafe dependency symlink')
            result[rel] = dict(link=os.readlink(path))
        elif path.is_file():
            result[rel] = dict(sha256=digest(path), mode=path.stat().st_mode & 0o777)
        elif not path.is_dir():
            raise ValueError('Unsafe dependency entry')
    return result


def valid_cache(root, identity, required):
    if root.is_symlink() or not root.is_dir():
        return False
    try:
        receipt = root / 'verified-tools.json'
        if receipt.is_symlink() or receipt.stat().st_size > 8 << 20:
            return False
        record = json.loads(receipt.read_text())
        return (record.get('identity') == identity and bool(record.get('files'))
                and all((root / name).is_file() for name in required)
                and record['files'] == inventory(root))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def cached_tool(data, identity, required, populate):
    """Publish complete generations atomically without replacing older tools."""
    cache = data / 'verified-build-tools'
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        raise ValueError('Unsafe dependency cache')
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    for candidate in sorted(cache.glob(key + '-*')):
        if valid_cache(candidate, identity, required):
            return candidate
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=cache))
    try:
        populate(staging)
        if not all((staging / name).is_file() for name in required):
            raise ValueError('Incomplete dependency extraction')
        files = inventory(staging)
        with (staging / 'verified-tools.json').open('w') as target:
            json.dump(dict(identity=identity, files=files), target, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        if not valid_cache(staging, identity, required):
            raise ValueError('Dependency validation failed')
        destination = cache / (key + '-' + uuid.uuid4().hex)
        os.replace(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def install_numpy(python, wheel, env):
    if digest(wheel) != NUMPY_SHA256:
        raise ValueError('NumPy wheel hash mismatch')
    subprocess.run([str(python), '-I', '-B', '-m', 'pip', '--isolated', 'install',
                    '--disable-pip-version-check', '--no-index', '--no-deps',
                    '--no-cache-dir', '--no-compile', '--force-reinstall', str(wheel)],
                   env=env, check=True)
    subprocess.run([str(python), '-I', '-B', '-c',
                    'import numpy, pathlib, sys; '
                    'assert sys.version_info[:3] == (3, 12, 15); '
                    'assert numpy.__version__ == ' + repr(NUMPY_VERSION) + '; '
                    'assert pathlib.Path(numpy.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); '
                    'assert float(numpy.arange(3).sum()) == 3.0'], env=env, check=True)


def prepare_python(data, env):
    def populate(root):
        archive, wheel = root / 'python.tar.gz', root / NUMPY_WHEEL
        fetch(PYTHON_URL, archive, PYTHON_SHA256)
        with tarfile.open(archive) as source:
            source.extractall(root, filter='data')
        archive.unlink()
        fetch(NUMPY_URL, wheel, NUMPY_SHA256)
        install_numpy(root / 'python/bin/python3', wheel, env)
        wheel.unlink()
    return cached_tool(data, dict(python=PYTHON_SHA256, numpy=NUMPY_SHA256, schema=1),
                       ['python/bin/python3', 'python/lib/libpython3.12.so.1.0'], populate)


def prepare_dxc(data):
    def populate(root):
        archive = root / 'dxc.zip'
        fetch(DXC_URL, archive, DXC_SHA256)
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                name = Path(info.filename.replace(chr(92), '/'))
                if name.parts[:2] != ('bin', 'x64') or info.is_dir():
                    continue
                if '..' in name.parts or name.is_absolute() or info.file_size > 128 << 20:
                    raise ValueError('Unsafe DXC archive')
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError('Duplicate DXC archive entry')
                target.write_bytes(source.read(info))
        archive.unlink()
    return cached_tool(data, dict(dxc=DXC_SHA256, schema=1),
                       ['bin/x64/' + name for name in ('dxc.exe', 'dxcompiler.dll', 'dxil.dll')], populate)


def run(here):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    data = Path(env['XDG_DATA_HOME']) / 'HelixSR'
    data.mkdir(parents=True, exist_ok=True)
    python = prepare_python(data, env) / 'python/bin/python3'
    dxc = prepare_dxc(data) / 'bin/x64/dxc.exe'
    env.update(HELIXSR_BUILD_DATA=str(data), HELIXSR_BUILD_DXC=str(dxc))
    launcher = data / ('dxc-launch-' + uuid.uuid4().hex + '.sh')
    launcher.write_text(r'''#!/usr/bin/env bash
set -euo pipefail
args=()
for arg in "$@"; do
    case "$arg" in /*) args+=("Z:$(printf '%s' "$arg" | tr / '\\')") ;; *) args+=("$arg") ;; esac
done
WINEPREFIX="$HELIXSR_BUILD_DATA/wineprefix" WINEDEBUG=-all exec "$HELIXSR_BUILD_WINE" "$HELIXSR_BUILD_DXC" "${args[@]}"
''')
    launcher.chmod(0o700)
    try:
        subprocess.run([str(python), '-B', str(here / 'setup/helixsr_setup.py'), str(here),
                        '--dxc', str(launcher), '--yes', '--separate-files', '--no-fg'], env=env, check=True)
    finally:
        launcher.unlink(missing_ok=True)


def build_script():
    if getattr(sys, 'frozen', False):
        # PyInstaller module __file__ points to bytecode; sys.executable is the
        # GUI bootloader. Bundle our source explicitly and use host Python.
        resource = Path(sys._MEIPASS) / 'bootstrap/modern_build.py'
        interpreter = shutil.which('python3', path=os.defpath)
        if not interpreter:
            raise ValueError('Install system Python 3 before preparing HelixSR')
    else:
        resource = Path(__file__)
        interpreter = sys.executable
    if not resource.is_file():
        raise ValueError('HelixSR build bootstrap resource is missing; reinstall the application')
    source = resource.read_text(encoding='utf-8')
    return ('#!/usr/bin/env bash\nset -euo pipefail\n'
            ': "${HELIXSR_BUILD_WINE:?No working installed Proton or Wine was found}"\n'
            ': "${XDG_DATA_HOME:?Missing private dependency directory}"\n'
            'HERE=$(cd "$(dirname "$0")" && pwd)\n'
            + shlex.quote(interpreter) + ' - "$HERE" <<\'PY_HELIX_BOOTSTRAP\'\n'
            + source + '\nPY_HELIX_BOOTSTRAP\n')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
