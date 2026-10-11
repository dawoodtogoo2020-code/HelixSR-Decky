"""Fresh builds must keep separate model outputs even when upstream embeds by default."""
import hashlib
import io
import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import manager
from test_backend import Fixtures, pe
from test_plugin_updates import FakeResponse


INVOCATION = '"$PY" "$PKG/helixsr_setup.py" "$TARGET" --dxc "$DXC" "${PASS[@]}"'
SHELL = '''#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PKG="$HERE/setup"
TARGET="$HERE"
PY=@PYTHON@
DXC=fixture-compiler
PASS=("$@")
''' + INVOCATION + '''
# --- games ---
exec "$PY" "$PKG/helixsr_install.py" "$TARGET"
'''

# Models the published 1.8 converter's output choice, using only synthetic bytes.
CONVERTER = '''import sys
from pathlib import Path
out = Path(sys.argv[1])
for name in ('helixsr_weights.bin', 'helixsr_kernels.pak'):
    (out / name).write_bytes(b'fixture model bytes ' * 128)
target = out / 'amd_fidelityfx_dx12.dll'
if '--separate-files' not in sys.argv and target.exists():
    target.write_bytes(target.read_bytes() + b'embedded fixture')
    (out / 'helixsr_weights.bin').unlink()
    (out / 'helixsr_kernels.pak').unlink()
    print('now carries the network')
else:
    print('separate model files ready')
'''


class AdapterTests(unittest.TestCase):
    def test_converter_receives_separate_output_and_game_installer_is_excluded(self):
        script = manager.build_only_script(SHELL, CONVERTER)
        self.assertIn(INVOCATION + ' --separate-files', script)
        self.assertNotIn('helixsr_install.py', script)

    def test_missing_or_ambiguous_boundaries_fail_closed(self):
        for setup in (SHELL.replace('# --- games ---', ''), SHELL + '# --- games ---',
                      SHELL.replace(INVOCATION, 'changed build'),
                      SHELL.replace(INVOCATION, INVOCATION + '\n' + INVOCATION)):
            with self.subTest(setup=setup), self.assertRaisesRegex(ValueError, 'adapter needs review'):
                manager.build_only_script(setup, CONVERTER)

    def test_removed_converter_option_requires_review(self):
        with self.assertRaisesRegex(ValueError, 'network output changed'):
            manager.build_only_script(SHELL, CONVERTER.replace('--separate-files', '--new-output'))


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Requires Linux shell integration')
class FreshPreparationTests(Fixtures):
    def archive(self, converter=CONVERTER, setup=SHELL):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            prefix = 'HelixSR-1.8.0/'
            files = {name: b'fixture dependency' for name in manager.PACKAGE_FILES if name not in manager.NETWORK}
            files.update({manager.DLL: pe(ffx=True, helix=True),
                          'LICENSE': b'fixture license', 'LICENSE-APACHE-2.0': b'fixture license',
                          'THIRD_PARTY_NOTICES.md': b'fixture notices',
                          'helixsr-setup.sh': setup.replace('@PYTHON@', shlex.quote(sys.executable)).encode(),
                          'setup/helixsr_setup.py': converter.encode(),
                          'setup/helixsr_install.py': b'raise SystemExit("upstream game installer must not run")\n'})
            for name, payload in files.items():
                archive.writestr(prefix + name, payload)
        payload = buffer.getvalue()
        release = dict(version='1.8.0', size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                       url=f'https://github.com/{manager.REPO}/releases/download/v1.8.0/HelixSR-1.8.0.zip')
        self.m.cfg['license'] = manager.license_key(release)
        return payload, release

    def prepare_fixture(self, converter=CONVERTER, setup=SHELL):
        payload, release = self.archive(converter, setup)
        response = FakeResponse(payload, release['url'])
        job = {'id': 'fresh-output'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.https_context', return_value=None), \
                patch('manager.urllib.request.urlopen', return_value=response):
            result = self.m.prepare(self.game, job)
        return result, job

    def test_fresh_embedded_default_release_is_prepared_with_separate_files(self):
        (version, folder, record), job = self.prepare_fixture()
        self.assertEqual(version, (1, 8, 0))
        self.assertIn('separate model files ready', job['log'])
        self.assertNotIn('now carries the network', job['log'])
        self.assertEqual((folder / manager.DLL).read_bytes(), pe(ffx=True, helix=True))
        for name in manager.NETWORK:
            self.assertGreaterEqual((folder / name).stat().st_size, 1024)
            self.assertEqual(record['files'][name], manager.sha(folder / name))
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse((self.m.companion(self.game) / 'staging' / job['id']).exists())
        self.assertEqual(self.m.package(self.game)[1], folder)

    def test_success_exit_with_missing_or_truncated_outputs_still_fails(self):
        for tail in ("\n(out / 'helixsr_weights.bin').unlink()\n",
                     "\n(out / 'helixsr_kernels.pak').write_bytes(b'truncated')\n"):
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, 'Generated HelixSR model files'):
                self.prepare_fixture(CONVERTER + tail)
            self.assertEqual(self.native.read_bytes(), self.original)
            self.assertFalse(self.m.cfg.get('packages'))
            companion = self.m.companion(self.game)
            self.assertTrue((companion / 'records/build-fresh-output.log').is_file())
            self.assertFalse((companion / 'staging/fresh-output').exists())

    def test_unknown_layout_stops_before_subprocess_and_preserves_game(self):
        with patch('manager.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError, 'adapter needs review'):
                self.prepare_fixture(setup=SHELL.replace(INVOCATION, 'changed invocation'))
            process.assert_not_called()
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.cfg.get('packages'))


if __name__ == '__main__':
    unittest.main()
