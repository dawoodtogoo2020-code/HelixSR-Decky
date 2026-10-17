"""Synthetic transaction acceptance tests; these do not prove game rendering.

HELIXSR_TEST_PLUGIN can select a controller checkout under integration.
HELIXSR_MODERN_FIXTURE optionally supplies an extracted official 1.9.3 archive;
only its public INI and license text are copied. Without it, representative
controller-authored text fixtures keep the suite offline and self-contained.
Executables/networks are synthetic in both modes.
"""
import json
import io
import contextlib
import os
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

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
        self.real_verify_outputs = modern_release.verify_outputs
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

    def assert_repeated_migrated_update(self, original_fake=None):
        self.scaler_game()
        fake = self.root / 'fakenvapi.ini'
        if original_fake is not None:
            write(fake, original_fake)
        before = self.snapshot()
        legacy = self.package()
        self.m.cfg['packages'][str(legacy)]['version'] = '1.8.1'
        self.action('install')
        edited_fake = b'[Settings]\nLegacyUserChoice=preserve in records\n'
        write(fake, edited_fake)
        baseline = self.m.record(self.game)['baseline']['fakenvapi.ini']
        self.modern_package()
        self.action('update')
        migrated = self.m.record(self.game)
        self.assertEqual(migrated['baseline']['fakenvapi.ini'], baseline)
        self.assertEqual(migrated['saved_configs']['fakenvapi.ini']['content'].encode(), edited_fake)
        if original_fake is None:
            self.assertFalse(fake.exists())
        else:
            self.assertEqual(fake.read_bytes(), original_fake)
        # Retiring editability must not permit adopting later foreign changes.
        write(fake, b'[Settings]\nForeignChange=true\n')
        for action in ('update', 'disable', 'remove'):
            with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                self.m.preview(self.game['id'], action)
        if original_fake is None:
            fake.unlink()
        else:
            write(fake, original_fake)
            backup = self.m.companion(self.game) / 'originals/fakenvapi.ini'
            write(backup, b'[Settings]\nChangedBackup=true\n')
            unchanged = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'Original file hash mismatch'):
                self.action('update')
            self.assertEqual(self.snapshot(), unchanged)
            self.assertEqual(self.m.record(self.game), migrated)
            write(backup, original_fake)
        ini = self.root / 'OptiScaler.ini'
        write(ini, ini.read_bytes() + b'\n[User]\nAfterMigration=keep me\n')
        self.modern_package('updated', prepared=999)
        for action in ('update', 'update', 'disable', 'enable'):
            self.action(action)
            record = self.m.record(self.game)
            self.assertEqual(record['baseline']['fakenvapi.ini'], baseline)
            self.assertEqual(record['saved_configs']['fakenvapi.ini']['content'].encode(), edited_fake)
            if original_fake is None:
                self.assertFalse(fake.exists())
            else:
                self.assertEqual(fake.read_bytes(), original_fake)
            if action != 'disable':
                self.assertEqual(parse_config(ini.read_text()).get('User', 'AfterMigration'), 'keep me')
        self.action('remove')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.m.record(self.game))

    def test_migrated_update_repeats_without_retired_introduced_config(self):
        self.assert_repeated_migrated_update()

    def test_migrated_update_preserves_retired_original_and_edit_history(self):
        self.assert_repeated_migrated_update(b'; original bytes\r\n[Settings]\r\nEnable=false\r\n')

    def assert_scaler_downgrade_requires_restore(self, legacy_history=False):
        self.scaler_game()
        before = self.snapshot()
        legacy = self.package()
        self.m.cfg['packages'][str(legacy)]['version'] = '1.8.1'
        if legacy_history:
            self.action('install')
        modern, _ = self.modern_package()
        self.action('update' if legacy_history else 'install')
        record = self.m.record(self.game)
        unchanged = self.snapshot()
        # The cached update path must enforce the same restriction as the
        # explicit compatibility download flow, before starting a journal.
        self.m.cfg['packages'].pop(str(modern))
        message = 'Remove HelixSR to restore original files first'
        with self.assertRaisesRegex(ValueError, message):
            self.m.preview(self.game['id'], 'update')
        data = self.m.assess(self.game)
        package = self.m.package(self.game, 'optiscaler')
        self.assertEqual(package[2]['version'], '1.8.1')
        for action in ('install', 'update', 'enable', 'latest'):
            with self.assertRaisesRegex(ValueError, message):
                self.m.planned_paths(self.game, data, action, package=package)
        with self.assertRaisesRegex(ValueError, message):
            self.m.mutate(self.game, data, 'update', package=package)
        self.assertEqual(self.snapshot(), unchanged)
        self.assertEqual(self.m.record(self.game), record)
        self.assertFalse((self.m.companion(self.game) / 'transaction').exists())
        self.action('remove')
        self.assertEqual(self.snapshot(), before)
        self.action('install')
        self.assertEqual(self.m.record(self.game)['version'], '1.8.1')
        self.assertFalse((self.root / 'OptiScaler/libxess_fg.dll').exists())
        self.action('remove')
        self.assertEqual(self.snapshot(), before)

    def test_fresh_modern_scaler_downgrade_requires_restore(self):
        self.assert_scaler_downgrade_requires_restore()

    def test_migrated_modern_scaler_downgrade_requires_restore(self):
        self.assert_scaler_downgrade_requires_restore(legacy_history=True)

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

    def test_prepare_rejects_legacy_output_contract_for_modern_release(self):
        release = self.release()
        self.m.cfg['license'] = manager.license_key(release, 'helixsr-model-e')
        before = self.snapshot()
        def extract(_archive, destination):
            package = destination / 'HelixSR-1.9.3'
            for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md', manager.DLL,
                         'helixsr-setup.sh', 'setup/helixsr_setup.py', 'setup/helixsr_install.py',
                         'helixsr-scaler/OptiScaler.dll', 'helixsr-scaler/OptiScaler.ini']:
                write(package / name, 'synthetic input')
            for name in manager.NETWORK:
                write(package / name, b'x' * 2048)
            write(package / 'helixsr_setup.json', json.dumps({'legacy': True}))
        def spawn(*args, **kwargs):
            self.m.process = MagicMock(returncode=0)
            self.m.process.poll.return_value = 0
        response = io.BytesIO(b'fixture')
        release['size'] = len(response.getvalue())
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(self.m, 'release_for_choice', return_value=release))
            stack.enter_context(patch.object(self.m, 'package', return_value=None))
            stack.enter_context(patch.object(manager.urllib.request, 'urlopen', return_value=response))
            stack.enter_context(patch.object(manager, 'sha', return_value=release['sha256']))
            stack.enter_context(patch.object(manager, 'safe_extract', side_effect=extract))
            stack.enter_context(patch.object(manager, 'verify_recipe', return_value={'recipe_sha256': modern_release.RECIPE_SHA256}))
            stack.enter_context(patch.object(manager, 'select_build_wine', return_value=(Path('/fake/wine'), [])))
            stack.enter_context(patch.object(self.m, '_spawn_compiler', side_effect=spawn))
            legacy = stack.enter_context(patch.object(manager, 'verify_outputs'))
            modern = stack.enter_context(patch.object(modern_release, 'verify_outputs', side_effect=ValueError('Modern output contract rejected')))
            with self.assertRaisesRegex(ValueError, 'Modern output contract rejected'):
                self.m.prepare(self.game, {'id': 'invalid-modern-output', 'log': ''})
            modern.assert_called_once()
            legacy.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.m.companion(self.game) / 'records/package.json').exists())
        self.assertFalse((self.m.companion(self.game) / 'staging/invalid-modern-output').exists())

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

    def test_modern_cache_requires_exact_archive_and_release_specific_recipe(self):
        self.scaler_game()
        folder, record = self.modern_package()
        self.assertIsNotNone(self.m.package(self.game, 'optiscaler'))
        old_recipe = next(digest for digest in model_variants.REVIEWED_RECIPES
                          if digest != modern_release.RECIPE_SHA256)
        old_variant = dict(record['variant'], recipe_sha256=old_recipe)
        self.assertTrue(model_variants.valid_variant(old_variant))
        missing_digest = dict(record)
        missing_digest.pop('release_sha256')
        missing_variant = dict(record)
        missing_variant.pop('variant')
        invalid = [('unreviewed archive', dict(record, release_sha256='f' * 64)),
                   ('missing archive identity', missing_digest),
                   ('legacy recipe', dict(record, variant=old_variant)),
                   ('missing recipe identity', missing_variant)]
        before = self.snapshot()
        for label, candidate in invalid:
            with self.subTest(identity=label):
                self.m.cfg['packages'][str(folder)] = candidate
                self.outputs_gate.reset_mock()
                self.assertIsNone(self.m._package_record(candidate, self.game))
                self.assertIsNone(self.m.package(self.game, 'optiscaler'))
                with self.assertRaisesRegex(ValueError, 'Prepare HelixSR on this drive first'):
                    self.m.preview(self.game['id'], 'install')
                self.outputs_gate.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.m.record(self.game))
        self.m.cfg['packages'][str(folder)] = record
        self.assertIsNotNone(self.m.package(self.game, 'optiscaler'))

    def test_modern_cache_cannot_select_legacy_output_validation_by_manifest(self):
        folder, record = self.modern_package()
        write(folder / 'helixsr_setup.json', json.dumps(dict(
            source_sha256=model_variants.SOURCE_SHA256, ptx_target='sm_89',
            shaders=len(model_variants.KERNEL_NAMES), wave64=False,
            weights_sha256=model_variants.WEIGHTS_SHA256)))
        record['files']['helixsr_setup.json'] = manager.sha(folder / 'helixsr_setup.json')
        self.outputs_gate.side_effect = self.real_verify_outputs
        # Even a successful legacy validator cannot validate modern output.
        with patch.object(manager, 'verify_outputs', return_value=None) as legacy_verifier:
            self.assertIsNone(self.m.package(self.game, 'direct'))
            legacy_verifier.assert_not_called()
        self.assertTrue(self.outputs_gate.called)
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_latest_accepts_only_exact_reviewed_193_release_identity(self):
        release = self.release()
        self.assertIs(require_supported_latest(release), release)
        for key, value in [('sha256', 'f' * 64), ('size', release['size'] + 1),
                           ('url', release['url'] + '?different'), ('page', release['page'] + '/'),
                           ('version', '1.9.4')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_supported_latest(dict(release, **{key: value}))
