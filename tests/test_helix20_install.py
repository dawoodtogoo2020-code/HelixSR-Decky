"""Synthetic transaction coverage for HelixSR 2.0 package migration and settings."""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import helix20_release
import manager
import modern_release
from tests.test_backend import Fixtures, pe, write


INI_20 = '''[Upscalers]\nDx12Upscaler=auto\n[FrameGen]\nEnabled=true\nFGInput=nvngxfg\nFGOutput=auto\nFGNvngxReplacement=HelixSR\n[HelixSR]\nFGPreset=full\nQuickFlow=off\n[XeFG]\nInterpolationCount=1\n[User]\nKeep=exact\n'''
INI_19 = INI_20.replace('FGPreset=full', 'FrameGeneration=off\nFGPreset=full')


class Helix20InstallTests(Fixtures):
    def setUp(self):
        super().setUp()
        # The full generated model and FG archives are separately validated by
        # the release adapter. These transaction fixtures intentionally stub
        # only that expensive generated-output verification.
        gate = patch.object(helix20_release, 'verify_outputs', return_value=None)
        gate.start()
        self.addCleanup(gate.stop)
        old_gate = patch.object(modern_release, 'verify_outputs', return_value=None)
        old_gate.start()
        self.addCleanup(old_gate.stop)

    def scaler_game(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())

    def modern19_package(self):
        folder = self.base / 'prepared-19'
        for name in modern_release.payload_files():
            if name == manager.DLL:
                data = pe(ffx=True, helix=True)
            elif name.endswith('OptiScaler.ini'):
                data = INI_19
            else:
                data = 'fixture ' + name
            write(folder / name, data)
        record = dict(path=str(folder), version='1.9.3', release_sha256=modern_release.RELEASE_SHA256,
                      prepared_at=1, variant=dict(id='helixsr-model-e', adapter='separate-network-v1',
                      recipe_sha256=modern_release.RECIPE_SHA256),
                      files={name: manager.sha(folder / name) for name in modern_release.payload_files()})
        self.m.cfg['packages'][str(folder)] = record
        return folder

    def modern20_package(self, missing=None):
        folder = self.base / 'prepared-20'
        for name in helix20_release.payload_files():
            if name == helix20_release.OUTPUT_DLL:
                data = pe(ffx=True, helix=True)
            elif name.endswith('OptiScaler.ini'):
                data = INI_20
            elif name.endswith('helixsr.ini'):
                data = '[HelixSR]\nMode=fixture\n'
            else:
                data = ('fixture ' + name).encode()
            if name != missing:
                write(folder / name, data)
        files = {name: manager.sha(folder / name) for name in helix20_release.payload_files() if name != missing}
        record = dict(path=str(folder), version='2.0.0', release_sha256=helix20_release.RELEASE_SHA256, prepared_at=2,
                      variant=dict(id='helixsr-model-e', adapter='separate-network-v1',
                      recipe_sha256=helix20_release.RECIPE_SHA256), files=files)
        self.m.cfg['packages'][str(folder)] = record
        return folder, record

    def test_fresh_scaler_install_rejects_missing_fg_payload_before_writes(self):
        self.scaler_game()
        self.modern20_package('HelixSR-fsrfg/helixsr-fg/hxfg_data.bin')
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'Prepare HelixSR on this drive first'):
            self.m.preview(self.game['id'], 'install')
        after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        self.assertFalse(self.m.record(self.game))

    def test_19_to_20_migration_settings_journal_and_restore(self):
        self.scaler_game()
        self.modern19_package()
        self.action('install')
        self.modern20_package()
        self.action('update')
        record = self.m.record(self.game)
        self.assertEqual(record['version'], '2.0.0')
        settings = self.m.game_settings(self.game, record)
        self.assertTrue(settings['available'])
        self.assertIsInstance(self.m.read_owned_config(self.game, 'OptiScaler.ini'), dict)
        self.m.set_game_settings(self.game['id'], {'quick_flow': 'fast'}, settings['revision'])
        changed = (self.root / 'OptiScaler.ini').read_text()
        self.assertIn('QuickFlow=fast', changed)
        self.assertIn('Keep=exact', changed)
        saved = self.m.record(self.game)['saved_configs']['OptiScaler.ini']
        self.assertEqual(saved['sha256'], hashlib.sha256(saved['content'].encode()).hexdigest())
        self.action('update')
        self.action('update')
        self.action('disable')
        self.action('enable')
        self.assertIn('QuickFlow=fast', (self.root / 'OptiScaler.ini').read_text())
        self.action('remove')
        self.assertFalse(self.m.record(self.game))
        self.assertFalse((self.root / 'dxgi.dll').exists())

    def test_settings_stale_revision_and_running_game_are_rejected(self):
        self.scaler_game()
        self.modern20_package()
        self.action('install')
        settings = self.m.game_settings(self.game)
        with self.assertRaisesRegex(ValueError, 'refresh'):
            self.m.set_game_settings(self.game['id'], {'int8': 'on'}, 'stale')
        with patch('manager.active_processes', return_value=[{'pid': 7}]):
            with self.assertRaisesRegex(ValueError, 'Close the game'):
                self.m.set_game_settings(self.game['id'], {'int8': 'on'}, settings['revision'])

    def test_scaler_preseeds_regular_amd_upscaler_and_removal_owns_it(self):
        self.scaler_game()
        package, _ = self.modern20_package()
        self.action('install')
        source = self.root / 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'
        runtime = self.root / helix20_release.AMD_UPSCALER_RUNTIME
        rel = str(runtime.relative_to(self.root))
        record = self.m.record(self.game)
        self.assertEqual(runtime.read_bytes(),
                         (package / helix20_release.AMD_UPSCALER_SOURCE).read_bytes())
        self.assertEqual(source.stat().st_nlink, 1)
        self.assertEqual(runtime.stat().st_nlink, 1)
        self.assertFalse(source.samefile(runtime))
        self.assertIsNone(record['baseline'][rel])
        self.assertEqual(record['current'][rel], manager.sha(runtime))
        self.action('remove')
        self.assertFalse(runtime.exists())
        self.assertFalse(source.exists())

    def test_native_direct_install_copies_only_embedded_dll_and_ini(self):
        package, record = self.modern20_package()
        self.action('install')
        self.assertEqual(self.native.read_bytes(),
                         (package / helix20_release.OUTPUT_DLL).read_bytes())
        self.assertFalse((self.root / 'helixsr.ini').exists())
        self.assertFalse(any((self.root / name).exists() for name in manager.NETWORK))
        self.assertEqual(self.m.record(self.game)['version'], '2.0.0')

    def test_native_direct_missing_runtime_repairs_exact_20_payload(self):
        package, _ = self.modern20_package()
        self.action('install')
        expected = (package / helix20_release.OUTPUT_DLL).read_bytes()
        self.native.unlink()
        details = self.m.assess(self.game)
        self.assertTrue(details['repair_eligible'])
        self.assertEqual(details['repair_files'], ['amd_fidelityfx_upscaler_dx12.dll'])
        self.action('repair')
        self.assertEqual(self.native.read_bytes(), expected)

    def test_scaler_missing_added_runtime_repairs_exact_20_payload(self):
        self.scaler_game()
        package, _ = self.modern20_package()
        self.action('install')
        runtime = self.root / helix20_release.AMD_UPSCALER_RUNTIME
        expected = (package / helix20_release.AMD_UPSCALER_SOURCE).read_bytes()
        runtime.unlink()
        details = self.m.assess(self.game)
        self.assertTrue(details['repair_eligible'])
        self.assertEqual(details['repair_files'], [str(Path(helix20_release.AMD_UPSCALER_RUNTIME))])
        self.action('repair')
        self.assertEqual(runtime.read_bytes(), expected)


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
