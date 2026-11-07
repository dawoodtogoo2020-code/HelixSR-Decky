"""Native stale-receipt recovery. Synthetic files do not prove game runtime."""
import json
import os
from pathlib import Path
from unittest.mock import patch

try:
    from .test_backend import Fixtures, manager, pe, write
except ImportError:
    from test_backend import Fixtures, manager, pe, write


class SetupResetTests(Fixtures):
    def stale_install(self, new_build=True):
        self.game['build'] = '20383525'
        self.package()
        self.action('install')
        self.receipt = self.m.record(self.game)
        if new_build:
            self.game['build'] = '26161058'
        self.replacement = pe(ffx=True) + b'current game update; not asserted to be stock'
        write(self.native, self.replacement if new_build else self.original)
        return self.m.assess(self.game)

    def test_cyberpunk_style_reset_preserves_current_dll_and_archives_old_record(self):
        data = self.stale_install()
        self.assertTrue(data['reset_eligible'])
        self.assertTrue(data['installation_status']['can_reset'])
        self.assertFalse(data['installation_status']['can_modify'])
        self.assertEqual(data['setup_guidance']['action'], 'reset')
        token = self.m.preview(self.game['id'], 'reset')
        self.assertNotIn(self.native.name, token['files'])
        self.assertIn(self.native.name, token['preserved_files'])
        self.assertIn('does not verify', token['warning'])
        self.m.execute(token['token'])
        self.assertEqual(self.native.read_bytes(), self.replacement)
        self.assertEqual(self.m.record(self.game), {})
        for rel, baseline in self.receipt['baseline'].items():
            if baseline is None:
                self.assertFalse((self.root / rel).exists())
        archives = list((self.m.companion(self.game) / 'records').glob('reset-*'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(json.loads((archives[0] / 'install.json').read_text()), self.receipt)
        self.assertEqual((archives[0] / 'originals' / self.native.name).read_bytes(), self.original)
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'candidate')

    def test_new_install_and_remove_restore_new_baseline_not_old_build(self):
        self.stale_install()
        self.action('reset')
        preview = self.m.preview(self.game['id'], 'install')
        self.assertIn('replaces the current native DLL', preview['warning'])
        self.assertIn('cannot prove the DLL is stock', preview['warning'])
        self.action('install')
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.replacement)
        archived = next((self.m.companion(self.game) / 'records').glob('reset-*'))
        self.assertEqual((archived / 'originals' / self.native.name).read_bytes(), self.original)

    def test_same_build_steam_restored_original_can_reset(self):
        self.stale_install(new_build=False)
        self.action('reset')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.assess(self.game)['managed'])

    def test_never_retire_receipt_while_native_helix_is_still_present(self):
        self.stale_install()
        write(self.native, pe(ffx=True, helix=True))
        data = self.m.assess(self.game)
        self.assertFalse(data['reset_eligible'])
        self.assertIn('Verify game files in Steam', data['reset_reason'])
        with self.assertRaisesRegex(ValueError, 'Verify game files'):
            self.action('reset')
        self.assertEqual(self.m.record(self.game), self.receipt)

    def test_unknown_added_file_is_not_deleted(self):
        self.stale_install()
        changed = write(self.root / manager.NETWORK[0], b'foreign modifications')
        with self.assertRaisesRegex(ValueError, 'Another tool changed'):
            self.action('reset')
        self.assertEqual(changed.read_bytes(), b'foreign modifications')
        self.assertEqual(self.m.record(self.game), self.receipt)

    def test_missing_added_files_allowed_but_missing_native_requires_verification(self):
        self.stale_install()
        (self.root / manager.NETWORK[0]).unlink()
        self.assertTrue(self.m.assess(self.game)['reset_eligible'])
        self.native.unlink()
        with self.assertRaisesRegex(ValueError, 'Verify game files'):
            self.action('reset')

    def test_running_update_and_interrupted_transaction_block_reset(self):
        self.stale_install()
        with patch('manager.active_processes', return_value=[{'pid': 42}]):
            with self.assertRaisesRegex(ValueError, 'Close the game'):
                self.action('reset')
        manifest = write(self.base / 'appmanifest.acf',
            '"AppState" { "StateFlags" "2" "buildid" "26161058" }')
        self.game.update(source='Steam', appid='42', library=str(self.base), manifest=str(manifest))
        with self.assertRaisesRegex(ValueError, 'Steam install/update'):
            self.action('reset')
        write(manifest, '"AppState" { "StateFlags" "4" "buildid" "26161058" }')
        write(self.m.companion(self.game) / 'transaction/journal.json', '{}')
        with self.assertRaisesRegex(ValueError, 'interrupted transaction'):
            self.action('reset')

    def test_changed_dll_or_manifest_after_preview_invalidates_reset(self):
        self.stale_install()
        token = self.m.preview(self.game['id'], 'reset')['token']
        write(self.native, self.replacement + b'changed again')
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)
        manifest = write(self.base / 'appmanifest.acf',
            '"AppState" { "StateFlags" "4" "buildid" "26161058" }')
        self.game.update(source='Steam', appid='42', library=str(self.base), manifest=str(manifest))
        token = self.m.preview(self.game['id'], 'reset')['token']
        write(manifest, '"AppState" { "StateFlags" "4" "buildid" "26161059" }')
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)
        self.assertEqual(self.m.record(self.game), self.receipt)

    def test_hardlinks_block_reset(self):
        self.stale_install()
        os.link(self.native, self.root / 'alias.dll')
        with self.assertRaises(ValueError):
            self.action('reset')

    def test_symlinks_block_reset(self):
        self.stale_install()
        saved = self.root / 'other.dll'
        self.native.rename(saved)
        self.link(self.native, saved)
        with self.assertRaises(ValueError):
            self.action('reset')

    def test_changed_or_missing_saved_original_blocks_archive_and_reset(self):
        self.stale_install()
        original = self.m.companion(self.game) / 'originals' / self.native.name
        write(original, b'damaged backup')
        with self.assertRaisesRegex(ValueError, 'Saved original needs review'):
            self.action('reset')
        self.assertEqual(self.native.read_bytes(), self.replacement)

    def test_failure_during_cleanup_restores_exact_pre_reset_files_and_receipt(self):
        self.stale_install()
        before = {rel: (self.root / rel).read_bytes() for rel in self.receipt['current']}
        unlink = self.m.unlink_managed
        def fail_after_unlink(path):
            unlink(path)
            raise OSError('synthetic reset failure')
        with patch.object(self.m, 'unlink_managed', side_effect=fail_after_unlink):
            with self.assertRaisesRegex(OSError, 'synthetic reset failure'):
                self.action('reset')
        self.assertEqual(self.m.record(self.game), self.receipt)
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in before}, before)
        self.assertFalse(self.m.recovery_available(self.game))

    def test_failure_after_receipt_retirement_rolls_back(self):
        self.stale_install()
        atomic = manager.atomic_json
        def fail_result(path, value):
            if Path(path).name == 'result.json':
                raise OSError('synthetic receipt failure')
            return atomic(path, value)
        with patch('manager.atomic_json', side_effect=fail_result):
            with self.assertRaisesRegex(OSError, 'synthetic receipt failure'):
                self.action('reset')
        self.assertEqual(self.m.record(self.game), self.receipt)
        self.assertEqual(self.native.read_bytes(), self.replacement)
        self.assertTrue((self.root / manager.NETWORK[0]).is_file())

    def test_archive_failure_never_retires_record_or_deletes_payload(self):
        self.stale_install()
        with patch.object(self.m, 'archive_reset', side_effect=OSError('archive failed')):
            with self.assertRaisesRegex(OSError, 'archive failed'):
                self.action('reset')
        self.assertEqual(self.m.record(self.game), self.receipt)
        self.assertTrue((self.root / manager.NETWORK[0]).is_file())

    def test_external_change_during_archive_is_preserved_and_requires_recovery(self):
        self.stale_install()
        archive = self.m.archive_reset
        def change_during_archive(*args):
            result = archive(*args)
            write(self.native, self.replacement + b'external change')
            return result
        with patch.object(self.m, 'archive_reset', side_effect=change_during_archive):
            with self.assertRaisesRegex(ValueError, 'Recovery conflict'):
                self.action('reset')
        self.assertEqual(self.native.read_bytes(), self.replacement + b'external change')
        self.assertEqual(self.m.record(self.game), self.receipt)
        self.assertTrue(self.m.recovery_available(self.game))

    def test_committed_reset_recovery_does_not_restore_old_build(self):
        self.stale_install()
        rmtree = manager.shutil.rmtree
        def fail_transaction_cleanup(path, *args, **kwargs):
            if Path(path).name == 'transaction':
                raise OSError('synthetic cleanup failure')
            return rmtree(path, *args, **kwargs)
        with patch('manager.shutil.rmtree', side_effect=fail_transaction_cleanup):
            with self.assertRaisesRegex(OSError, 'synthetic cleanup failure'):
                self.action('reset')
        self.assertEqual(self.m.record(self.game), {})
        self.assertTrue(self.m.recovery_available(self.game))
        self.action('recover')
        self.assertEqual(self.native.read_bytes(), self.replacement)
        self.assertEqual(self.m.record(self.game), {})
        self.assertFalse(self.m.recovery_available(self.game))

    def test_healthy_install_cannot_be_reset(self):
        self.package()
        self.action('install')
        self.assertFalse(self.m.assess(self.game)['reset_eligible'])
        with self.assertRaises(ValueError):
            self.action('reset')

    def test_menu_patch_is_not_orphaned(self):
        self.stale_install()
        receipt = dict(self.receipt, menu_labels={'enabled': True})
        manager.atomic_json(self.m.record_path(self.game), receipt)
        self.assertFalse(self.m.assess(self.game)['reset_eligible'])
        with self.assertRaisesRegex(ValueError, 'menu-label'):
            self.action('reset')
