"""Build the source-only Decky install ZIP. Run after pnpm build."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'py_modules'))
from plugin_updates import semver, validate_zip
version = json.loads((root / 'package.json').read_text())['version']
semver(version)
out = root.parent / f'HelixSR-Decky-{version}.zip'
allowed = ['main.py', 'plugin.json', 'package.json', 'LICENSE', 'README.md', 'INSTALL_GUIDE.md', 'OPTISCALER_GUIDE.md', 'DESKTOP_GUIDE.md', 'MODEL_VARIANTS.md', 'THIRD_PARTY_NOTICES.md']
license_files = [
    'licenses/decky-api-LGPL-2.1.txt',
    'licenses/react-icons-LICENSE.txt',
    'licenses/font-awesome-free-5-LICENSE.txt',
    'licenses/CC-BY-4.0.txt',
    'licenses/decky-api-1.1.3-source/README.md',
    'licenses/decky-api-1.1.3-source/package.json',
    'licenses/decky-api-1.1.3-source/src/index.ts',
    'licenses/decky-api-1.1.3-source/src/types.ts',
    'licenses/decky-api-1.1.3-source/src/types.d.ts',
]
missing_licenses = [name for name in license_files if not (root / name).is_file()]
if missing_licenses:
    raise SystemExit('Required third-party license/source files missing: ' + ', '.join(missing_licenses))
files = [root / n for n in allowed if (root / n).is_file()]
files += [root / name for name in license_files]
files += list((root / 'dist').rglob('*.js'))
files += list((root / 'py_modules').glob('*.py'))
if not (root / 'dist/index.js').is_file():
    raise SystemExit('Build frontend first')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files):
        z.write(p, 'HelixSR-Decky/' + p.relative_to(root).as_posix())
validate_zip(out, version)
digest = hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix('.zip.sha256').write_text(f'{digest}  {out.name}\n')
print(json.dumps({'path':str(out), 'size':out.stat().st_size, 'sha256':digest,
                  'contents':[p.relative_to(root).as_posix() for p in files]}))
