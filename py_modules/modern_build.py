"""Launch the official converter unchanged using private, verified build tools.

This is our launcher, not a modified copy of an upstream setup script. The
converter's supported --separate-files option keeps transaction payloads explicit.
"""


def build_script():
    return r'''#!/usr/bin/env bash
set -euo pipefail
: "${HELIXSR_BUILD_WINE:?No working installed Proton or Wine was found}"
: "${XDG_DATA_HOME:?Missing private dependency directory}"
DATA="$XDG_DATA_HOME/HelixSR"
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$DATA"
fetch() {
    curl -fL --retry 0 --connect-timeout 30 --max-time 300 -o "$2.part" "$1"
    printf '%s  %s\n' "$3" "$2.part" | sha256sum -c --status
    mv "$2.part" "$2"
}
PY="$DATA/python/bin/python3"
if [ ! -x "$PY" ]; then
    fetch 'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-unknown-linux-gnu-install_only.tar.gz' "$DATA/python.tar.gz" 'f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5'
    tar -xzf "$DATA/python.tar.gz" -C "$DATA"
    rm "$DATA/python.tar.gz"
fi
if ! "$PY" -c 'import numpy' 2>/dev/null; then
    "$PY" -m pip install --disable-pip-version-check numpy
fi
if [ ! -f "$DATA/dxc-win/bin/x64/dxc.exe" ]; then
    fetch 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip' "$DATA/dxc-win.zip" 'a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241'
    "$PY" - "$DATA/dxc-win.zip" "$DATA/dxc-win" <<'PY_DXC'
import pathlib, sys, zipfile
root = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as archive:
    count = 0
    for info in archive.infolist():
        name = pathlib.PurePosixPath(info.filename.replace(chr(92), '/'))
        if (name.parts[:2] != ('bin', 'x64') or info.is_dir()):
            continue
        if '..' in name.parts or name.is_absolute() or info.file_size > 128 << 20:
            raise SystemExit('Unsafe DXC archive')
        target = root.joinpath(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(info))
        count += 1
    if not count:
        raise SystemExit('Missing DXC files')
PY_DXC
    rm "$DATA/dxc-win.zip"
fi
export HELIXSR_BUILD_DATA="$DATA"
cat > "$DATA/dxc-launch.sh" <<'SH_DXC'
#!/usr/bin/env bash
set -euo pipefail
args=()
for arg in "$@"; do
    case "$arg" in /*) args+=("Z:$(printf '%s' "$arg" | tr / '\\')") ;; *) args+=("$arg") ;; esac
done
WINEPREFIX="$HELIXSR_BUILD_DATA/wineprefix" WINEDEBUG=-all exec "$HELIXSR_BUILD_WINE" "$HELIXSR_BUILD_DATA/dxc-win/bin/x64/dxc.exe" "${args[@]}"
SH_DXC
chmod +x "$DATA/dxc-launch.sh"
exec "$PY" "$HERE/setup/helixsr_setup.py" "$HERE" --dxc "$DATA/dxc-launch.sh" --yes --separate-files --no-fg
'''
