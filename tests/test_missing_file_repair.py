"""Safe recovery of absent managed payloads from an exact recorded package."""

from pathlib import Path
import os
from unittest.mock import patch

try:
    from .test_backend import Fixtures, manager, write
except ImportError:
    from test_backend import Fixtures, manager, write


class MissingFileRepairTests(Fixtures):
    def install_direct(self):
        self.package()
        self.action('install')
        return self.m.record(self.game)

    def install_scaler(self):
        choice = self.dual_executables()
        self.package()
        token = self.m.preview(self.game['id'], 'install', executable=choice)['token']
        self.m.execute(token)
        return self.m.record(self.game)

    def test_missing_replaced_native_dll_repairs_from_exact_recorded_package(self):
        receipt = self.install_direct()
        installed = self.native.read_bytes()
        original = self.m.companion(self.game) / 'originals/amd_fidelityfx_upscaler_dx12.dll'
        self.assertEqual(original.read_bytes(), self.original)
        self.native.unlink()

        assessed = self.m.assess(self.game)
        self.assertTrue(assessed['repair_eligible'])
        self.assertEqual(assessed['repair_files'], ['amd_fidelityfx_upscaler_dx12.dll'])
        self.assertTrue(assessed['installation_status']['can_repair'])
        preview = self.m.preview(self.game['id'], 'repair')
        self.assertEqual(preview['files'], ['amd_fidelityfx_upscaler_dx12.dll'])
        result = self.m.execute(preview['token'])

        self.assertIn('Repair completed', result['message'])
        self.assertEqual(self.native.read_bytes(), installed)
        self.assertEqual(self.m.record(self.game)['baseline'], receipt['baseline'])
        self.assertEqual(self.m.record(self.game)['package_selection'], receipt['package_selection'])

    def test_missing_added_scaler_dll_repairs_without_rewriting_other_files(self):
        receipt = self.install_scaler()
        missing = self.root / 'DX12/HelixSR/amd_fidelityfx_upscaler_dx12.amd.dll'
        expected = missing.read_bytes()
        untouched = self.root / 'DX12/dxgi.dll'
        before = untouched.read_bytes()
        missing.unlink()

        preview = self.m.preview(self.game['id'], 'repair')
        self.assertEqual(preview['files'], [str(missing.relative_to(self.root))])
        self.m.execute(preview['token'])

        self.assertEqual(missing.read_bytes(), expected)
        self.assertEqual(untouched.read_bytes(), before)
        self.assertEqual(self.m.record(self.game)['baseline'], receipt['baseline'])

    def test_changed_other_mod_file_blocks_repair_and_is_preserved(self):
        self.install_direct()
        self.native.unlink()
        changed = self.root / manager.NETWORK[0]
        write(changed, b'other mod bytes')

        assessed = self.m.assess(self.game)
        self.assertFalse(assessed['repair_eligible'])
        with self.assertRaisesRegex(ValueError, 'Managed files changed'):
            self.m.preview(self.game['id'], 'repair')
        self.assertEqual(changed.read_bytes(), b'other mod bytes')
        self.assertFalse(self.native.exists())

    def test_running_game_and_steam_update_guards_still_block_repair(self):
        self.install_direct()
        self.native.unlink()
        with patch('manager.active_processes', return_value=[{'pid': 42}]):
            assessed = self.m.assess(self.game)
            self.assertFalse(assessed['repair_eligible'])
            with self.assertRaisesRegex(ValueError, 'Game is running'):
                self.m.preview(self.game['id'], 'repair')

        manifest = write(self.base / 'appmanifest.acf',
            '"AppState" { "StateFlags" "2" "buildid" "100" }')
        self.game.update(source='Steam', appid='42', library=str(self.base),
                         manifest=str(manifest), build='100')
        with self.assertRaisesRegex(ValueError, 'Steam install/update is not complete'):
            self.m.preview(self.game['id'], 'repair')

    def test_build_change_and_missing_exact_cache_are_actionable_blockers(self):
        self.game['build'] = '100'
        self.install_direct()
        self.native.unlink()
        self.game['build'] = '101'
        details = self.m.assess(self.game)
        self.assertFalse(details['repair_eligible'])
        with self.assertRaisesRegex(ValueError, 'Steam build changed'):
            self.m.preview(self.game['id'], 'repair')

        self.game['build'] = '100'
        self.m.cfg['packages'].clear()
        details = self.m.assess(self.game)
        self.assertFalse(details['repair_eligible'])
        self.assertTrue(any('recorded checksum-verified package' in reason
                            for reason in details['reasons']))

    def test_repair_write_failure_rolls_back_to_missing_and_keeps_receipt(self):
        receipt = self.install_direct()
        self.native.unlink()
        token = self.m.preview(self.game['id'], 'repair')['token']
        original_copy = self.m.copy_absent_atomic

        def fail_after_copy(source, destination, expected=None):
            original_copy(source, destination, expected)
            raise OSError('synthetic repair failure')

        with patch.object(self.m, 'copy_absent_atomic', side_effect=fail_after_copy):
            with self.assertRaisesRegex(OSError, 'synthetic repair failure'):
                self.m.execute(token)
        self.assertFalse(self.native.exists())
        self.assertEqual(self.m.record(self.game), receipt)
        self.assertFalse((self.m.companion(self.game) / 'transaction').exists())

    def test_file_appearing_during_repair_is_never_overwritten(self):
        receipt = self.install_direct()
        self.native.unlink()
        token = self.m.preview(self.game['id'], 'repair')['token']
        real_link = os.link

        def race(source, destination, *args, **kwargs):
            write(destination, b'foreign mod arrived during repair')
            return real_link(source, destination, *args, **kwargs)

        with patch('manager.os.link', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Recovery conflict'):
                self.m.execute(token)
        self.assertEqual(self.native.read_bytes(), b'foreign mod arrived during repair')
        self.assertEqual(self.m.record(self.game), receipt)
        self.assertTrue(self.m.recovery_available(self.game))
        with self.assertRaisesRegex(ValueError, 'Recovery conflict'):
            self.action('recover')
        self.assertEqual(self.native.read_bytes(), b'foreign mod arrived during repair')

    def test_wrong_repair_bytes_never_commit_or_rewrite_receipt(self):
        receipt = self.install_direct()
        self.native.unlink()
        token = self.m.preview(self.game['id'], 'repair')['token']

        def wrong_copy(source, destination, expected):
            self.m.track_write(destination, manager.hashlib.sha256(b'wrong repair bytes').hexdigest())
            write(destination, b'wrong repair bytes')

        with patch.object(self.m, 'copy_absent_atomic', side_effect=wrong_copy):
            with self.assertRaisesRegex(ValueError, 'does not match installation record'):
                self.m.execute(token)
        self.assertFalse(self.native.exists())
        self.assertEqual(self.m.record(self.game), receipt)


if __name__ == '__main__':
    import unittest
    unittest.main()
