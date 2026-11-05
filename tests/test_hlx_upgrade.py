"""Exercise owned game transactions using small pinned stand-ins for both releases."""
from unittest.mock import patch

try:
    from .test_backend import Fixtures, manager, pe, write
    from .test_hlx_fsr_release import TEMPLATE, hlx
    from . import test_helix20_install
except ImportError:
    from test_backend import Fixtures, manager, pe, write
    from test_hlx_fsr_release import TEMPLATE, hlx
    import test_helix20_install


class HlxUpgradeTests(Fixtures):
    def setUp(self):
        super().setUp()
        # Use the production verification path with a small, local fixture manifest.
        folder = self.base / 'prepared-hlx'
        pins = {}
        for name in hlx.payload_files():
            data = 'fixture ' + name
            if name == hlx.SCALER_INI:
                data = TEMPLATE
            elif name == hlx.OUTPUT_DLL:
                data = pe(ffx=True) + b'HLX FSR 4 (4.1.2)'
            path = write(folder / name, data)
            pins[name] = (path.stat().st_size, manager.sha(path))
        gate = patch.object(hlx, 'PINS', pins)
        gate.start()
        self.addCleanup(gate.stop)
        old = patch.object(test_helix20_install.helix20_release, 'verify_outputs', return_value=None)
        old.start()
        self.addCleanup(old.stop)
        self.hlx_dir = folder
        self.hlx_record = dict(path=str(folder), version='3.2.0', release_sha256=hlx.RELEASE_SHA256,
                               variant=hlx.verify_recipe(folder), prepared_at=32,
                               files={n: digest for n, (_, digest) in pins.items()})
        self.m.cfg['variant_packages_v1'] = {str(folder): self.hlx_record}

    def review_hlx(self):
        return self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID,
                                     release_choice='reviewed-3.2.0')

    def install_hlx(self):
        review = self.review_hlx()
        token = review['token']
        self.m.accept_license(True, token)
        job = self.m.execute_latest(token)
        self.m.worker.join(10)
        result = self.m.jobs[job['id']]
        self.assertEqual(result['state'], 'completed', result['message'])

    def test_direct_upgrade_switches_fallback_repairs_and_restores_after_disable(self):
        self.package()
        self.action('install')
        legacy = self.native.with_name(self.native.stem + '.original.dll')
        fallback = self.native.with_name(self.native.stem + '.amd.dll')
        self.assertEqual(legacy.read_bytes(), self.original)
        self.action('disable')
        self.install_hlx()
        self.assertFalse(legacy.exists())
        self.assertEqual(self.m.record(self.game)['variant']['id'], hlx.VARIANT_ID)
        self.assertEqual(fallback.read_bytes(), self.original)
        self.assertEqual(self.native.read_bytes(), (self.hlx_dir / hlx.OUTPUT_DLL).read_bytes())
        self.assertEqual((self.m.companion(self.game) / 'originals' / self.native.name).read_bytes(), self.original)
        fallback.unlink()
        self.action('repair')
        self.assertEqual(fallback.read_bytes(), self.original)
        self.action('disable')
        self.assertFalse(fallback.exists())
        self.assertEqual(self.native.read_bytes(), self.original)
        self.action('enable')
        self.assertFalse(legacy.exists())
        self.assertEqual(fallback.read_bytes(), self.original)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(fallback.exists())

    def test_changed_cache_refuses_repair_and_preserves_game(self):
        self.install_hlx()
        self.native.unlink()
        notice = self.hlx_dir / 'LICENSE'
        write(notice, b'corrupt')
        self.hlx_record['files']['LICENSE'] = manager.sha(notice)
        before = {p.name: manager.sha(p) for p in self.root.iterdir() if p.is_file()}
        self.assertFalse(self.m.assess(self.game)['repair_eligible'])
        with self.assertRaises(ValueError):
            self.action('repair')
        self.assertEqual({p.name: manager.sha(p) for p in self.root.iterdir() if p.is_file()}, before)

    def test_scaler_upgrade_preserves_xess_settings_and_supersedes_legacy_sr(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        test_helix20_install.Helix20InstallTests.modern20_package(self)
        self.action('install')
        revision = self.m.game_settings(self.game)['revision']
        self.m.set_game_settings(self.game['id'], {'provider': 'xess', 'multiplier': 3}, revision)
        self.install_hlx()
        state = self.m.game_settings(self.game)
        self.assertEqual((state['upscaler'], state['provider'], state['multiplier']), ('hlx-fsr', 'xess', 3))
        self.assertFalse((self.root / test_helix20_install.helix20_release.OUTPUT_DLL).exists())
        self.assertIn('Keep=exact', (self.root / 'OptiScaler.ini').read_text())
        self.action('disable')
        self.action('enable')
        self.assertEqual(self.m.game_settings(self.game)['multiplier'], 3)
        self.action('remove')
        self.assertEqual({p.name for p in self.root.rglob('*') if p.is_file()}, {'nvngx_dlss.dll', 'Example.exe'})

    def test_unknown_hlx_wrapper_cannot_become_game_original(self):
        wrapper = pe(ffx=True) + b'HLX FSR 4 (4.1.2) old payload'
        write(self.native, wrapper)
        with self.assertRaisesRegex(ValueError, 'original x64 native FidelityFX|HLX FSR 4 drop-in'):
            self.review_hlx()
        self.assertEqual(self.native.read_bytes(), wrapper)
        self.assertFalse(self.native.with_name(self.native.stem + '.amd.dll').exists())
        self.assertFalse(self.m.record(self.game))

    def test_upstream_hlx_dropin_blocks_every_direct_model_before_game_writes(self):
        # Upstream's manual drop-in: game DLL renamed to .amd.dll, HLX DLL in its place.
        fallback = write(self.native.with_name(self.native.stem + '.amd.dll'), self.original)
        dropin = pe(ffx=True) + b'HLX FSR 4 (4.1.2) from upstream setup'
        write(self.native, dropin)
        self.package()
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        self.assertTrue(any('HLX FSR 4 drop-in' in reason for reason in data['reasons']))
        self.assertTrue(any('Unmanaged original DLL backup' in reason for reason in data['reasons']))
        with self.assertRaisesRegex(ValueError, 'HLX FSR 4 drop-in'):
            self.m.preview(self.game['id'], 'install')
        with self.assertRaisesRegex(ValueError, 'HLX FSR 4 drop-in'):
            self.review_hlx()
        self.assertEqual((self.native.read_bytes(), fallback.read_bytes()), (dropin, self.original))
        self.assertFalse(self.native.with_name(self.native.stem + '.original.dll').exists())
        self.assertFalse(self.m.record(self.game))

    def test_stray_amd_fallback_beside_native_dll_is_an_unmanaged_backup(self):
        write(self.native.with_name(self.native.stem + '.amd.dll'), b'other installer backup')
        self.package()
        with self.assertRaisesRegex(ValueError, 'Unmanaged original DLL backup'):
            self.m.preview(self.game['id'], 'install')
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_unmanaged_legacy_provider_blocks_scaler_before_any_game_writes(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        old = write(self.root / test_helix20_install.helix20_release.OUTPUT_DLL, pe(ffx=True))
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        with self.assertRaisesRegex(ValueError, 'override HLX FSR'):
            self.review_hlx()
        self.assertEqual(old.read_bytes(), pe(ffx=True))
        self.assertFalse((self.root / 'dxgi.dll').exists())

    def test_forced_scaler_preserves_native_input_and_rejects_no_input(self):
        self.native.unlink()
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        with self.assertRaisesRegex(ValueError, 'upscaling route'):
            self.review_hlx()
        write(self.native, self.original)
        self.install_hlx()
        self.assertEqual(self.m.record(self.game)['route'], 'optiscaler')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.native.with_name(self.native.stem + '.amd.dll').exists())
        self.action('remove')

    def test_preview_blocks_enabled_or_retained_20_fg_without_saving_a_job(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        test_helix20_install.Helix20InstallTests.modern20_package(self)
        self.action('install')
        with self.assertRaisesRegex(ValueError, 'before upgrading'):
            self.review_hlx()
        self.action('disable')
        with self.assertRaisesRegex(ValueError, 'before upgrading'):
            self.review_hlx()
        self.assertFalse(self.m.record(self.game)['enabled'])
        self.assertFalse(self.m.jobs)
