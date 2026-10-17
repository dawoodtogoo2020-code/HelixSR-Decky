"""Offline dependency bootstrap acceptance tests; no downloads or tool execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import shlex
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import modern_build as build


class ModernBuildTests(unittest.TestCase):
    def setUp(self):
        scratch = (Path(__file__).resolve().parents[1].parent.parent / 'work'
                   if os.name == 'nt' else Path(tempfile.gettempdir()))
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, root, name, data=b'fixture'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_interrupted_cache_with_executable_is_not_reused_for_either_tool(self):
        for label, required in [('python', ['python/bin/python3', 'python/lib/libpython3.12.so.1.0']),
                                ('dxc', ['bin/x64/dxc.exe', 'bin/x64/dxcompiler.dll', 'bin/x64/dxil.dll'])]:
            with self.subTest(tool=label):
                data = self.root / label
                identity = dict(tool=label)
                key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                partial = data / 'verified-build-tools' / (key + '-interrupted')
                self.write(partial, required[0], b'old partial executable')
                def populate(stage):
                    for name in required:
                        self.write(stage, name)
                ready = build.cached_tool(data, identity, required, populate)
                self.assertNotEqual(ready, partial)
                self.assertTrue(build.valid_cache(ready, identity, required))
                self.assertEqual((partial / required[0]).read_bytes(), b'old partial executable')
                with patch.object(build, 'inventory', wraps=build.inventory) as scan:
                    self.assertEqual(build.cached_tool(data, identity, required,
                                                      lambda _: self.fail('valid cache rebuilt')), ready)
                    self.assertTrue(scan.called)

    def test_failed_extraction_never_publishes_and_preserves_existing_tools(self):
        old = self.write(self.root, 'python/bin/python3', b'existing dependency')
        def fail(stage):
            self.write(stage, 'python/bin/python3')
            raise RuntimeError('interrupted extraction')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            build.cached_tool(self.root, {'python': 'pin'}, ['python/bin/python3'], fail)
        self.assertEqual(old.read_bytes(), b'existing dependency')
        self.assertEqual(list((self.root / 'verified-build-tools').iterdir()), [])

    def test_mutated_numpy_or_missing_compiler_library_invalidates_receipt(self):
        required = ['python/bin/python3', 'numpy/core.so', 'bin/x64/dxcompiler.dll']
        def populate(stage):
            for name in required:
                self.write(stage, name)
        identity = {'python': 'pin', 'numpy': build.NUMPY_SHA256}
        cache = build.cached_tool(self.root, identity, required, populate)
        self.write(cache, 'numpy/core.so', b'changed installed numpy')
        self.assertFalse(build.valid_cache(cache, identity, required))
        self.write(cache, 'numpy/core.so')
        (cache / required[-1]).unlink()
        self.assertFalse(build.valid_cache(cache, identity, required))

    def test_numpy_verifies_exact_wheel_before_offline_install_and_version_probe(self):
        wheel = self.write(self.root, build.NUMPY_WHEEL)
        with patch.object(build.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'NumPy wheel hash'):
                build.install_numpy(Path('/python'), wheel, {})
            run.assert_not_called()
            with patch.object(build, 'NUMPY_SHA256', build.digest(wheel)):
                build.install_numpy(Path('/python'), wheel, {})
            command = run.call_args_list[0].args[0]
            for arg in ('--no-index', '--no-deps', '--isolated', '--no-compile', '-I', '-B'):
                self.assertIn(arg, command)
            self.assertEqual(command[-1], str(wheel))
            probe = run.call_args_list[1].args[0][-1]
            self.assertIn(repr(build.NUMPY_VERSION), probe)
            self.assertIn('numpy.__file__', probe)

    def test_python_installs_numpy_inside_stage_before_receipt_publication(self):
        def fetch(url, path, expected):
            if url == build.PYTHON_URL:
                with tarfile.open(path, 'w:gz') as archive:
                    for name in ('python/bin/python3', 'python/lib/libpython3.12.so.1.0'):
                        info = tarfile.TarInfo(name)
                        info.size = 3
                        archive.addfile(info, io.BytesIO(b'bin'))
            else:
                path.write_bytes(b'wheel')
        def numpy(python, wheel, env):
            self.assertTrue(python.is_file())
            self.assertFalse((python.parents[2] / 'verified-tools.json').exists())
            self.write(python.parents[2], 'python/lib/python3.12/site-packages/numpy/core.so')
        with patch.object(build, 'fetch', side_effect=fetch), patch.object(build, 'install_numpy', side_effect=numpy):
            cache = build.prepare_python(self.root, {})
        receipt = json.loads((cache / 'verified-tools.json').read_text())
        self.assertEqual(receipt['identity']['numpy'], build.NUMPY_SHA256)
        self.assertIn('python/lib/python3.12/site-packages/numpy/core.so', receipt['files'])
        self.assertFalse((cache / build.NUMPY_WHEEL).exists())

    def test_dxc_requires_both_compiler_libraries_not_only_executable(self):
        def fetch(url, path, expected):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('bin/x64/dxc.exe', b'executable')
        with patch.object(build, 'fetch', side_effect=fetch):
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                build.prepare_dxc(self.root)
        self.assertEqual(list((self.root / 'verified-build-tools').iterdir()), [])

    def test_embedded_bootstrap_keeps_official_converter_arguments(self):
        script = build.build_script()
        self.assertIn('--separate-files', script)
        self.assertIn('--no-fg', script)
        embedded = script.split("<<'PY_HELIX_BOOTSTRAP'\n", 1)[1].rsplit('\nPY_HELIX_BOOTSTRAP', 1)[0]
        compile(embedded, '<bootstrap>', 'exec')

    def test_frozen_bootstrap_uses_bundled_source_and_real_interpreter(self):
        resource = self.write(self.root, 'bootstrap/modern_build.py', b'print("host bootstrap executed")\n')
        host_python = sys.executable
        with patch.object(build.sys, 'frozen', True, create=True), \
                patch.object(build.sys, '_MEIPASS', str(self.root), create=True), \
                patch.object(build.sys, 'executable', '/AppDir/helixsr-desktop'), \
                patch.object(build, '__file__', str(self.root / 'missing-module.pyc')), \
                patch.object(build.shutil, 'which', return_value=host_python) as which:
            script = build.build_script()
        which.assert_called_once_with('python3', path=os.defpath)
        self.assertIn(shlex.quote(host_python) + ' - "$HERE"', script)
        self.assertNotIn('/AppDir/helixsr-desktop', script)
        embedded = script.split("<<'PY_HELIX_BOOTSTRAP'\n", 1)[1].rsplit('\nPY_HELIX_BOOTSTRAP', 1)[0]
        self.assertEqual(embedded, resource.read_text())
        result = subprocess.run([host_python, '-c', embedded], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'host bootstrap executed')

    def test_frozen_missing_interpreter_or_resource_fails_before_build(self):
        with patch.object(build.sys, 'frozen', True, create=True), \
                patch.object(build.sys, '_MEIPASS', str(self.root), create=True):
            with patch.object(build.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(ValueError, 'Install system Python 3'):
                    build.build_script()
            with patch.object(build.shutil, 'which', return_value='/usr/bin/python3'):
                with self.assertRaisesRegex(ValueError, 'bootstrap resource is missing'):
                    build.build_script()

    def test_appimage_build_bundles_bootstrap_source_explicitly(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/build_appimage.py').read_text()
        self.assertIn("'--add-data', str(ROOT / 'py_modules/modern_build.py') + ':bootstrap'", source)


if __name__ == '__main__':
    unittest.main()

