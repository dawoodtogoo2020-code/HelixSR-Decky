"""Synthetic transaction acceptance tests; these do not prove game rendering.

HELIXSR_TEST_PLUGIN can select a controller checkout under integration.
HELIXSR_MODERN_FIXTURE optionally supplies an extracted official 1.9.3 archive;
only its public INI and license text are copied. Without it, representative
controller-authored text fixtures keep the suite offline and self-contained.
Executables/networks are synthetic in both modes.
"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

PLUGIN = Path(os.environ.get('HELIXSR_TEST_PLUGIN', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import manager
import modern_release
import model_variants
from compatibility_release import require_supported_latest
from optiscaler_setup import parse_config
from test_backend import Fixtures, pe, write


SCALER_TEMPLATE = '''; Representative synthetic Scaler settings, not an upstream file.
[Upscalers]
Dx12Upscaler=auto
FfxDx12Path=auto
FfxDx12SRPath=auto
[HelixSR]
FrameGeneration=off
[FrameGen]
Enabled=auto
FGInput=auto
FGOutput=auto
FGNvngxReplacement=auto
[Hotfix]
ShortcutKey=auto
'''


class ModernInstallTests(Fixtures):
    def setUp(self):
        super().setUp()
        location = os.environ.get('HELIXSR_MODERN_FIXTURE')
        self.official = Path(location) if location else None
        gate = patch.object(modern_release, 'verify_outputs', return_value=None)
        self.outputs_gate = gate.start()
        self.addCleanup(gate.stop)

    def scaler_game(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())

    def release(self):
        return dict(version='1.9.3', sha256=modern_release.RELEASE_SHA256,
                    size=modern_release.RELEASE_SIZE, url=modern_release.RELEASE_URL,
                    page=modern_release.RELEASE_PAGE)

    def modern_package(self, suffix='main', prepared=200):
        folder = self.base / 'modern-prepared' / suffix
        for name in modern_release.payload_files():
            if name == manager.DLL:
                value = pe(ffx=True, helix=True)
            elif name.endswith('.ini'):
                value = (self.official / name).read_bytes() if self.official else SCALER_TEMPLATE
            elif '/Licenses/' in name:
                value = ((self.official / name).read_bytes() if self.official
                         else 'Synthetic license fixture for transaction tests: ' + name)
            elif name == 'helixsr_setup.json':
                value = json.dumps({'fp32': True})
            else:
                value = ('synthetic asset ' + name + suffix).encode()
            write(folder / name, value)
        record = dict(path=str(folder), version='1.9.3',
                      release_sha256=modern_release.RELEASE_SHA256, prepared_at=prepared,
                      variant=dict(id='helixsr-model-e', adapter='separate-network-v1',
                                   recipe_sha256=modern_release.RECIPE_SHA256),
                      files={name: manager.sha(folder / name) for name in modern_release.payload_files()})
        self.assertTrue(model_variants.valid_variant(record['variant']))
        self.m.cfg['packages'][str(folder)] = record
        return folder, record

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_fresh_scaler_installs_complete_plan_without_legacy_dependencies(self):
        self.scaler_game()
        folder, _ = self.modern_package()
        preview = self.m.preview(self.game['id'], 'install')
        expected = {dest for _, dest in modern_release.scaler_pairs()}
        expected |= {'OptiScaler.ini', 'HelixSR/helixsr-install.json'}
        self.assertEqual({Path(n).as_posix() for n in preview['files']}, expected)
        self.m.execute(preview['token'])
        for source, dest in modern_release.scaler_pairs():
            self.assertEqual((self.root / dest).read_bytes(), (folder / source).read_bytes(), dest)
        config = parse_config((self.root / 'OptiScaler.ini').read_text())
        self.assertEqual(config.get('Upscalers', 'Dx12Upscaler'), 'dlss')
        self.assertEqual(config.get('HelixSR', 'FrameGeneration'), 'off')
        self.assertFalse((self.root / 'fakenvapi.dll').exists())
        self.assertFalse((self.root / 'fakenvapi.ini').exists())
        self.assertFalse((self.root / 'HelixSR/helixsr_upscaler.dll').exists())
        self.assertEqual(self.m.record(self.game)['version'], '1.9.3')
        self.assertTrue(self.outputs_gate.called)

    def test_managed_18_upgrade_retires_legacy_payload_and_retains_user_fg(self):
        self.scaler_game()
        legacy = self.package()
        self.m.cfg['packages'][str(legacy)]['version'] = '1.8.1'
        self.action('install')
        obsolete = ['fakenvapi.dll', 'fakenvapi.ini', 'HelixSR/helixsr_upscaler.dll',
                    'HelixSR/amd_fidelityfx_upscaler_dx12.amd.dll']
        self.assertTrue(all((self.root / n).exists() for n in obsolete))
        ini = self.root / 'OptiScaler.ini'
        ini.write_text(ini.read_text() + '\n[HelixSR]\nFrameGeneration=on\n'
                       '[FrameGen]\nEnabled=true\nFGInput=nvngxfg\nFGOutput=dlssg\n'
                       'FGNvngxReplacement=Arturs\n[User]\nCustom=preserve this\n')
        self.modern_package()
        self.action('update')
        self.assertEqual(self.m.record(self.game)['version'], '1.9.3')
        self.assertTrue(all(not (self.root / n).exists() for n in obsolete))
        config = parse_config(ini.read_text())
        for key, value in [('Enabled', 'true'), ('FGInput', 'nvngxfg'),
                           ('FGOutput', 'dlssg'), ('FGNvngxReplacement', 'Arturs')]:
            self.assertEqual(config.get('FrameGen', key), value)
        self.assertEqual(config.get('User', 'Custom'), 'preserve this')
        self.assertEqual(config.get('HelixSR', 'FrameGeneration'), 'off')
        self.action('remove')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertTrue(all(not (self.root / n).exists() for n in obsolete))

    def test_disable_enable_uses_exact_installed_cache_and_restores_user_edits(self):
        self.scaler_game()
        installed, record = self.modern_package()
        self.action('install')
        ini = self.root / 'OptiScaler.ini'
        ini.write_text(ini.read_text().replace('ShortcutKey=auto', 'ShortcutKey=123'))
        edited = ini.read_bytes()
        selection = self.m.record(self.game)['package_selection']
        self.action('disable')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.modern_package('newer-distinct-cache', prepared=999)
        self.action('enable')
        self.assertEqual(self.m.record(self.game)['package_selection'], selection)
        self.assertEqual((self.root / 'dxgi.dll').read_bytes(), (installed / 'helixsr-scaler/OptiScaler.dll').read_bytes())
        self.assertEqual(ini.read_bytes(), edited)
        self.action('disable')
        self.m.cfg['packages'].pop(str(installed))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Exact installed package'):
            self.m.preview(self.game['id'], 'enable')
        self.assertEqual(self.snapshot(), before)

    def test_unmanaged_new_scaler_asset_collision_blocks_before_any_write(self):
        self.scaler_game()
        self.modern_package()
        conflict = write(self.root / 'OptiScaler/libxess_fg.dll', b'foreign provider to preserve')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unmanaged file'):
            self.m.preview(self.game['id'], 'install')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(conflict.read_bytes(), b'foreign provider to preserve')
        self.assertFalse(self.m.record(self.game))

    def test_direct_install_disable_enable_remove_restores_original_exactly(self):
        before = self.snapshot()
        package, _ = self.modern_package()
        self.assertEqual(self.m.assess(self.game)['route'], 'direct')
        self.action('install')
        self.assertEqual(self.native.read_bytes(), (package / manager.DLL).read_bytes())
        self.assertEqual(self.native.with_name(self.native.stem + '.original.dll').read_bytes(), self.original)
        self.action('disable')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.action('enable')
        self.assertEqual(self.native.read_bytes(), (package / manager.DLL).read_bytes())
        self.action('remove')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.outputs_gate.called)

    def test_direct_package_missing_modern_asset_or_changed_hash_is_rejected(self):
        folder, record = self.modern_package()
        self.assertIsNotNone(self.m.package(self.game, 'direct'))
        asset = 'helixsr-scaler/OptiScaler/libxess_fg.dll'
        digest = record['files'].pop(asset)
        self.assertIsNone(self.m.package(self.game, 'direct'))
        record['files'][asset] = digest
        write(folder / asset, b'tampered')
        self.assertIsNone(self.m.package(self.game, 'direct'))
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_latest_accepts_only_exact_reviewed_193_release_identity(self):
        release = self.release()
        self.assertIs(require_supported_latest(release), release)
        for key, value in [('sha256', 'f' * 64), ('size', release['size'] + 1),
                           ('url', release['url'] + '?different'), ('page', release['page'] + '/'),
                           ('version', '1.9.4')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_supported_latest(dict(release, **{key: value}))
