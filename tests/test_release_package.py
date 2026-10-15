"""Small offline release fixtures, including the source-ZIP install regression."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_release import check_release, SOURCE_PREFIX, SOURCE_REQUIRED


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.release-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.release = self.root / 'release'
        self.release.mkdir()
        self.version = '0.1.25'
        self.runtime = self.release / f'HelixSR-Decky-{self.version}.zip'
        self.source = self.release / f'HelixSR-Decky-{self.version}-source.tar.gz'
        (self.root / 'package.json').write_text(json.dumps({'version': self.version}))
        url = (f'https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/'
               f'download/v{self.version}/{self.runtime.name}')
        for name in ('README.md', 'INSTALL_GUIDE.md'):
            (self.root / name).write_text(f'[Install runtime]({url})\n')
        self.make_runtime()
        self.make_source()
        self.hashes()

    def make_runtime(self, omit=(), module_type='module'):
        modules = ('manager', 'library', 'awareness', 'plugin_updates', 'optiscaler_setup',
                   'launch_receipts', 'operation_lock', 'host_environment', 'model_variants',
                   'build_runtime', 'github_release', '_helix_html', '_helix_html_parser',
                   '_helix_html_entities', '_helix_markupbase')
        entries = {f'py_modules/{name}.py': b'# fixture\n' for name in modules}
        entries.update({
            'main.py': b'pass\n', 'dist/index.js': b'export {};\n',
            'plugin.json': json.dumps({'name': 'HelixSR Decky', 'flags': [], 'api_version': 1}).encode(),
            'package.json': json.dumps({'name': 'helixsr-decky', 'version': self.version,
                                       'type': module_type}).encode(),
            'licenses/cpython-3.11.17-LICENSE.txt': b'fixture license',
            'licenses/cpython-3.11.17-PROVENANCE.json': b'{}',
        })
        with zipfile.ZipFile(self.runtime, 'w') as archive:
            for name, data in entries.items():
                if name not in omit:
                    archive.writestr('HelixSR-Decky/' + name, data)

    def make_source(self, version=None, extra=None, omit=()):
        entries = {name: b'# source fixture\n' for name in SOURCE_REQUIRED if name not in omit}
        if 'package.json' in entries:
            entries['package.json'] = json.dumps({
                'name': 'helixsr-decky', 'version': version or self.version}).encode()
        with tarfile.open(self.source, 'w:gz') as archive:
            for name, data in entries.items():
                info = tarfile.TarInfo(SOURCE_PREFIX + '/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if extra is not None:
                archive.addfile(extra, io.BytesIO(b''))

    def hashes(self):
        lines = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
                 for path in (self.runtime, self.source)]
        (self.release / 'SHA256SUMS').write_text(''.join(lines))

    def check(self):
        return check_release(self.release, source_root=self.root)

    def test_valid_release(self):
        self.assertEqual(len(self.check()), 3)
        self.assertEqual(self.check(), check_release(self.release, self.version, self.root))

    def test_runtime_requires_frontend(self):
        self.make_runtime(omit=('dist/index.js',))
        self.hashes()
        with self.assertRaisesRegex(ValueError, 'Incomplete plugin ZIP'):
            self.check()

    def test_source_zip_accidentally_included(self):
        (self.release / f'HelixSR-Decky-{self.version}-source.zip').write_bytes(b'old source ZIP')
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.check()

    def test_runtime_requires_esm_manifest(self):
        self.make_runtime(module_type='commonjs')
        self.hashes()
        with self.assertRaisesRegex(ValueError, 'ESM module type'):
            self.check()

    def test_bad_hash(self):
        self.runtime.write_bytes(self.runtime.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.check()

    def test_missing_asset(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.check()

    def test_checksum_missing_or_duplicate_asset(self):
        sums = self.release / 'SHA256SUMS'
        line = sums.read_text().splitlines()[0] + '\n'
        for content in (line, line + line):
            with self.subTest(content=content):
                sums.write_text(content)
                with self.assertRaisesRegex(ValueError, 'SHA256SUMS'):
                    self.check()

    def test_source_version_mismatch(self):
        self.make_source(version='0.1.24')
        self.hashes()
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            self.check()

    def test_source_requires_real_source_files(self):
        self.make_source(omit=('src/index.tsx',))
        self.hashes()
        with self.assertRaisesRegex(ValueError, 'Incomplete source archive'):
            self.check()

    def test_source_rejects_unsafe_members(self):
        for name, kind in ((SOURCE_PREFIX + '/../escape', tarfile.REGTYPE),
                           (SOURCE_PREFIX + '/link', tarfile.SYMTYPE),
                           (SOURCE_PREFIX + '/hardlink', tarfile.LNKTYPE),
                           (SOURCE_PREFIX + '//noncanonical', tarfile.REGTYPE)):
            with self.subTest(name=name):
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = 'main.py' if kind != tarfile.REGTYPE else ''
                self.make_source(extra=info)
                self.hashes()
                with self.assertRaisesRegex(ValueError, 'Unsafe source archive'):
                    self.check()

    def test_source_rejects_generated_or_binary_payload(self):
        for relative in ('dist/index.js', 'node_modules/lib/index.js', 'weights.bin', 'OptiScaler.dll'):
            with self.subTest(relative=relative):
                self.make_source(extra=tarfile.TarInfo(SOURCE_PREFIX + '/' + relative))
                self.hashes()
                with self.assertRaisesRegex(ValueError, 'Generated or binary payload'):
                    self.check()

    def test_install_docs_require_current_runtime_link(self):
        for name in ('README.md', 'INSTALL_GUIDE.md'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text(original.replace('0.1.25', '0.1.24'))
                with self.assertRaisesRegex(ValueError, name):
                    self.check()
                path.write_text(original)


if __name__ == '__main__':
    unittest.main()
