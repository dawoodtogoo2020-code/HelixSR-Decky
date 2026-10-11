"""Fresh builds must keep separate model outputs even when upstream embeds by default."""
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import manager
import model_variants
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
import json, hashlib, struct
from pathlib import Path
out = Path(sys.argv[1])
for name in ('helixsr_weights.bin', 'helixsr_kernels.pak'):
    (out / name).write_bytes(b'fixture model bytes ' * 128)
blob = b'synthetic shader ' * 128
(out / 'helixsr_kernels.pak').write_bytes(b'HXSRKPAK' + struct.pack('<II', 2, 1)
    + struct.pack('<32sII', b'synthetic', 56, len(blob)) + blob)
(out / 'helixsr_setup.json').write_text(json.dumps(dict(
    source_sha256='be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e',
    ptx_target='sm_89', shaders=1, wave64=False,
    weights_sha256=hashlib.sha256((out / 'helixsr_weights.bin').read_bytes()).hexdigest())))
target = out / 'amd_fidelityfx_dx12.dll'
if '--separate-files' not in sys.argv and target.exists():
    target.write_bytes(target.read_bytes() + b'embedded fixture')
    (out / 'helixsr_weights.bin').unlink()
    (out / 'helixsr_kernels.pak').unlink()
    print('now carries the network')
else:
    print('separate model files ready')
'''

# The guarded upstream Wine/DXC layout, with no downloads or real shader build.
WINE_BLOCK = r'''DATA="$HERE/compiler $ ' data"
mkdir -p "$DATA/dxc-win/bin/x64"
die() { printf '%s\n' "$*"; exit 1; }
WINE=""
# official Proton first, then custom Proton builds, then a system Wine
for p in "$HOME"/.local/share/Steam/steamapps/common/Proton*/files/bin/wine; do
    if [ -x "$p" ]; then WINE="$p"; break; fi
done
[ -z "$WINE" ] && command -v wine >/dev/null && WINE=$(command -v wine)
[ -n "$WINE" ] || die "no Proton or Wine found (needed to run the shader compiler); install Proton in Steam or Wine"
DXC="$DATA/dxc-wine.sh"
cat > "$DXC" <<EOF
#!/usr/bin/env bash
args=()
for a in "\$@"; do case "\$a" in /*) args+=("Z:\$(printf '%s' "\$a" | tr / '\\\\')") ;; *) args+=("\$a") ;; esac; done
WINEPREFIX="$DATA/wineprefix" WINEDEBUG=-all exec "$WINE" "$DATA/dxc-win/bin/x64/dxc.exe" "\${args[@]}"
EOF
chmod +x "$DXC"
'''
RUNTIME_SHELL = SHELL.replace('DXC=fixture-compiler\n', WINE_BLOCK)
RUNTIME_CONVERTER = '''import subprocess
import sys
subprocess.run([sys.argv[sys.argv.index('--dxc') + 1], "/tmp/shader $ ' source.hlsl",
                '-E', 'main', 'literal $ value'], check=True)
''' + CONVERTER


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

    def test_changed_runtime_markers_fail_closed(self):
        for marker in ('WINE=""', '# official Proton first', 'cat > "$DXC" <<EOF',
                       'chmod +x "$DXC"', 'WINEDEBUG=-all exec "$WINE"'):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, 'runtime changed'):
                manager.build_only_script(RUNTIME_SHELL.replace(marker, 'changed'), CONVERTER, True)


class RuntimeAndErrorTests(unittest.TestCase):
    def test_unusable_runtime_is_skipped_and_argv_is_not_shell_code(self):
        candidates = [Path('/Steam library/broken/files/bin/wine'),
                      Path('/Steam library/Proton/files/bin/wine')]
        with patch('manager.platform.system', return_value='Linux'), \
                patch('manager.wine_candidates', return_value=candidates), \
                patch('manager.subprocess.run', side_effect=[
                    OSError('not executable on this host'),
                    subprocess.CompletedProcess([], 0, 'wine-9.0\n')]) as run:
            selected, notes = manager.select_build_wine('/home/test', {'PATH': '/usr/bin'})
        self.assertEqual(selected, candidates[1])
        self.assertIn('Skipped build runtime', notes[0])
        self.assertEqual(run.call_args.args[0], [str(candidates[1]), '--version'])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['env'], {'PATH': '/usr/bin'})

    def test_all_probe_failures_keep_upstream_fallback(self):
        with patch('manager.platform.system', return_value='Linux'), \
                patch('manager.wine_candidates', return_value=[Path('/p/wine')]), \
                patch('manager.subprocess.run', side_effect=subprocess.TimeoutExpired('wine', 3)):
            selected, notes = manager.select_build_wine('/home/test', {})
        self.assertIsNone(selected)
        self.assertEqual(len(notes), 1)

    def test_success_exit_without_wine_version_is_not_a_runtime(self):
        with patch('manager.platform.system', return_value='Linux'), \
                patch('manager.wine_candidates', return_value=[Path('/p/wine')]), \
                patch('manager.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'not Wine')):
            self.assertIsNone(manager.select_build_wine('/home/test', {})[0])

    def test_failure_reports_specific_reason_and_bounded_tail(self):
        for log, expected in [('ERROR: no Proton or Wine found', 'Install Proton'),
                              ('bash: helper: Permission denied', 'executable support'),
                              ('No space left on device', 'ran out of space'),
                              ('earlier output\nValueError: shader compilation failed', 'shader compilation failed')]:
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, expected):
                manager.check_build_exit(1, False, log)
        with self.assertRaises(ValueError) as error:
            manager.check_build_exit(1, False, '\x1b[31m' + 'x' * 10000)
        self.assertLess(len(str(error.exception)), 400)
        self.assertNotIn('\x1b', str(error.exception))

    def test_cancellation_precedes_failure_details(self):
        with self.assertRaisesRegex(ValueError, '^Cancelled$'):
            manager.check_build_exit(1, True, 'no Proton or Wine found')

    def test_unknown_runtime_layout_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'compiler runtime changed'):
            manager.build_only_script(SHELL, CONVERTER, True)


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
        for key, value in [('WEIGHTS_SIZE', len(b'fixture model bytes ' * 128)),
                           ('WEIGHTS_SHA256', hashlib.sha256(b'fixture model bytes ' * 128).hexdigest()),
                           ('KERNEL_NAMES', (b'synthetic',))]:
            gate = patch.object(model_variants, key, value)
            gate.start()
            self.addCleanup(gate.stop)
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.https_context', return_value=None), \
                patch('manager.verify_recipe', return_value=dict(id=model_variants.DEFAULT_VARIANT,
                    adapter=model_variants.ADAPTER, recipe_sha256=next(iter(model_variants.REVIEWED_RECIPES)))), \
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

    def test_external_and_flatpak_runtime_reaches_dxc_with_literal_paths(self):
        for flatpak in (False, True):
            with self.subTest(flatpak=flatpak):
                steam = self.home / ('.var/app/com.valvesoftware.Steam/.local/share/Steam' if flatpak
                                     else '.local/share/Steam')
                external = self.base / "external $ ' library"
                wine = external / 'steamapps/common/Proton Fixture/files/bin/wine'
                wine.parent.mkdir(parents=True, exist_ok=True)
                record = self.base / 'wine-arguments.json'
                wine.write_text('#!' + sys.executable + '\n' +
                                'import json, os, sys\n' +
                                'if sys.argv[1:] == ["--version"]:\n'
                                '    print("wine-9.0")\n'
                                'else:\n' +
                                '    from pathlib import Path\n' +
                                '    Path(' + repr(str(record)) + ').write_text(json.dumps({"args": sys.argv[1:], '
                                '"prefix": os.environ["WINEPREFIX"]}))\n', encoding='utf-8')
                wine.chmod(0o755)
                metadata = steam / 'steamapps/libraryfolders.vdf'
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_text('"libraryfolders" { "1" { "path" "' + str(external) + '" } }')
                (_, folder, _), job = self.prepare_fixture(RUNTIME_CONVERTER, RUNTIME_SHELL)
                captured = json.loads(record.read_text())
                self.assertTrue(captured['args'][0].endswith("compiler $ ' data/dxc-win/bin/x64/dxc.exe"))
                self.assertEqual(captured['args'][1:], ["Z:\\tmp\\shader $ ' source.hlsl", '-E', 'main', 'literal $ value'])
                self.assertTrue(captured['prefix'].endswith("compiler $ ' data/wineprefix"))
                self.assertIn('Build runtime: ' + str(wine.resolve()), job['log'])
                self.assertEqual(self.native.read_bytes(), self.original)
                self.assertTrue(all((folder / name).is_file() for name in manager.NETWORK))
                # Force the second iteration to exercise fresh Flatpak discovery.
                metadata.unlink()
                self.m.cfg['packages'].clear()
                shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()
