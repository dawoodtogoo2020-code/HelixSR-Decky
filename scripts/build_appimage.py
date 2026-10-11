"""Build the native code-only x86_64 AppImage on Ubuntu 22.04.

Run in a dedicated build environment after installing requirements-build.txt.
The downloaded build tool is pinned by SHA256 and never enters the app payload.
"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.version import VERSION

TOOL_URL = 'https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage'
TOOL_SHA = '95cbe7cce9717fce90c484e34052ee7c7f1d7635b33c12525b4776826a7d29b6'


def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def build():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('Build on Linux x86_64')
    qt_version = importlib.metadata.version('PySide6-Essentials')
    pinned = re.search(r'^PySide6-Essentials==([0-9.]+)$',
                       (ROOT / 'desktop/requirements-build.txt').read_text(), re.M)
    if not pinned or qt_version != pinned[1] or importlib.metadata.version('shiboken6') != qt_version:
        raise SystemExit('Install the exact reviewed Qt binding pair from requirements-build.txt')
    build_root = ROOT / 'build-desktop'
    if build_root.exists():
        raise SystemExit('Existing desktop build directory; use a clean checkout')
    appdir = build_root / 'HelixSR-Desktop.AppDir'
    appdir.mkdir(parents=True)
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
         '--name', 'helixsr-desktop', '--distpath', str(build_root / 'dist'),
         '--workpath', str(build_root / 'work'), '--specpath', str(build_root),
         '--paths', str(ROOT), '--paths', str(ROOT / 'py_modules'),
         '--hidden-import', 'desktop.backend', '--hidden-import', 'desktop.app_updates',
         '--hidden-import', 'desktop.probe',
         '--hidden-import', 'desktop.system', '--hidden-import', 'manager',
         '--hidden-import', 'library', '--hidden-import', 'awareness',
         '--hidden-import', 'operation_lock', '--hidden-import', 'host_environment', str(ROOT / 'scripts/desktop_entry.py')])
    destination = appdir / 'usr/bin/helixsr-desktop'
    destination.parent.mkdir(parents=True)
    shutil.copytree(build_root / 'dist/helixsr-desktop', destination)
    # Host graphics drivers and libstdc++ must match the host Mesa installation.
    host_libraries = ('libGL.so', 'libEGL.so', 'libGLX.so', 'libGLdispatch.so',
                      'libgbm.so', 'libdrm.so', 'libvulkan.so', 'libstdc++.so',
                      'libgallium', 'libnvidia', 'libcuda', 'libwayland-client.so',
                      'libwayland-cursor.so', 'libwayland-egl.so')
    for path in destination.rglob('*'):
        if (path.is_file() or path.is_symlink()) and path.name.startswith(host_libraries):
            path.unlink()
    internal = destination / '_internal'
    # Qt's X11 cursor dependency is missing on some otherwise supported desktops.
    cursor = Path('/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0')
    if not cursor.is_file():
        raise SystemExit('Install libxcb-cursor0 in the build environment')
    shutil.copy2(cursor.resolve(), internal / cursor.name)
    share = appdir / 'usr/share/helixsr-desktop'
    share.mkdir(parents=True)
    for name in ('LICENSE', 'DESKTOP_GUIDE.md', 'DESKTOP_NOTICES.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, share / name)
    licenses = share / 'licenses'
    licenses.mkdir()
    qt_notices = ROOT / ('licenses/qt-' + qt_version)
    if not (qt_notices / 'qtbase/LICENSES/LGPL-3.0-only.txt').is_file():
        raise SystemExit('Missing reviewed Qt upstream license texts')
    shutil.copytree(qt_notices, licenses / ('Qt-' + qt_version))
    for name in ('PySide6-Essentials', 'shiboken6', 'pyinstaller',
                 'pyinstaller-hooks-contrib', 'altgraph', 'packaging', 'setuptools'):
        dist = importlib.metadata.distribution(name)
        target = licenses / name
        target.mkdir()
        copied = 0
        for entry in dist.files or []:
            rel = Path(str(entry))
            if any(part.lower() in ('licenses', 'license') for part in rel.parts) or rel.name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    out = target / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, out)
                    copied += 1
        # Some Linux Qt wheels omit texts. Reviewed matching upstream texts above
        # are included unconditionally; do not rely on wheel metadata alone.
        if not copied and name not in ('PySide6-Essentials', 'shiboken6'):
            raise SystemExit('Missing bundled license text: ' + name)
    license_url = f'https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE'
    with urllib.request.urlopen(license_url, timeout=30) as response:
        python_license = response.read(1 << 20)
    if not python_license.startswith(b'A. HISTORY'):
        raise SystemExit('Unexpected Python license response')
    (licenses / 'Python-LICENSE.txt').write_bytes(python_license)
    # Include Debian/Ubuntu copyright notices for copied host dependency libraries.
    # These are collected from the actual build image, rather than guessed licenses.
    system_packages = {'libxcb-cursor0'}
    for library in internal.rglob('lib*.so*'):
        for base in (Path('/usr/lib/x86_64-linux-gnu'), Path('/lib/x86_64-linux-gnu')):
            candidate = base / library.name
            if candidate.exists():
                result = subprocess.run(['dpkg-query', '-S', str(candidate)],
                                        capture_output=True, text=True, check=False)
                for line in result.stdout.splitlines():
                    package, _, _ = line.partition(': ')
                    if package:
                        system_packages.add(package.split(':')[0])
    system_notices = licenses / 'system-libraries'
    system_notices.mkdir()
    for package in sorted(system_packages):
        copyright_file = Path('/usr/share/doc') / package / 'copyright'
        if not copyright_file.is_file():
            raise SystemExit('Missing system library copyright notice: ' + package)
        shutil.copy2(copyright_file, system_notices / (package + '-copyright.txt'))
    for source, target in [('helixsr-desktop.desktop', 'helixsr-desktop.desktop'),
                           ('helixsr-desktop.svg', 'helixsr-desktop.svg')]:
        shutil.copy2(ROOT / 'desktop' / source, appdir / target)
    (appdir / '.DirIcon').symlink_to('helixsr-desktop.svg')
    (appdir / 'AppRun').write_text('#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$HERE/usr/bin/helixsr-desktop/helixsr-desktop" "$@"\n')
    (appdir / 'AppRun').chmod(0o755)
    tool = build_root / 'appimagetool.AppImage'
    with urllib.request.urlopen(TOOL_URL, timeout=60) as response, tool.open('xb') as stream:
        total = 0
        while chunk := response.read(1 << 20):
            total += len(chunk)
            if total > 32 << 20:
                raise SystemExit('Build tool exceeded its bound')
            stream.write(chunk)
    if hashlib.sha256(tool.read_bytes()).hexdigest() != TOOL_SHA:
        raise SystemExit('Pinned AppImage build tool changed; review before rebuilding')
    tool.chmod(0o755)
    release = ROOT / 'release-desktop'
    release.mkdir()
    out = release / f'HelixSR-Desktop-{VERSION}-x86_64.AppImage'
    run([str(tool), '--appimage-extract-and-run', str(appdir), str(out)],
        env=dict(os.environ, ARCH='x86_64', SOURCE_DATE_EPOCH=os.environ.get('SOURCE_DATE_EPOCH', '1791676800')))
    out.chmod(0o755)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (release / 'SHA256SUMS').write_text(f'{digest}  {out.name}\n')
    shutil.copy2(ROOT / 'DESKTOP_GUIDE.md', release / 'DESKTOP_GUIDE.md')
    print(json.dumps({'path': str(out), 'version': VERSION, 'size': out.stat().st_size, 'sha256': digest}))
    return out


if __name__ == '__main__':
    build()
