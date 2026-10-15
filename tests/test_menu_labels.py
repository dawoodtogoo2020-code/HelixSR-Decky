"""Synthetic managed-menu transactions. No real games/assets/network are used."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from test_backend import Fixtures, write
from test_menu_label_profiles import fixture
import manager
import menu_labels
from menu_label_profiles import WITCHER_XML, patch_witcher3


class MenuTransactions(unittest.TestCase):
    setUp = Fixtures.setUp
    package = Fixtures.package
    action = Fixtures.action

    def prepare(self):
        self.game.update(source='Steam', appid='292030', name='The Witcher 3')
        self.original, _ = fixture()
        self.menu = write(self.root / WITCHER_XML, self.original)
        self.package()
        self.action('install')
        self.process_patch = patch('menu_labels.process_scan_ready', return_value=None)
        self.process_patch.start()
        self.addCleanup(self.process_patch.stop)

    def state(self):
        return self.m.assess(self.game)['menu_labels']

    def test_off_by_default_and_unmanaged_never_mutates(self):
        self.game.update(source='Steam', appid='292030')
        original, _ = fixture()
        menu = write(self.root / WITCHER_XML, original)
        state = self.state()
        self.assertFalse(state['enabled'])
        self.assertFalse(state['available'])
        with self.assertRaises(ValueError):
            self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(menu.read_bytes(), original)

    def test_enable_preview_is_read_only_then_disable_restores_exact_bytes(self):
        self.prepare()
        self.assertFalse(self.state()['enabled'])
        before = self.m.record(self.game)
        preview = self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertEqual(self.m.record(self.game), before)
        self.assertIn(str(Path(WITCHER_XML)), preview['files'])
        self.m.execute(preview['token'])
        self.assertEqual(self.menu.read_bytes(), patch_witcher3(self.original))
        self.assertTrue(self.state()['enabled'])
        self.assertTrue(self.m.record(self.game)['enabled'])
        self.action('labels_disable')
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertFalse(self.state()['enabled'])
        self.assertTrue(self.m.record(self.game)['enabled'])
        self.action('labels_enable')
        self.assertEqual(self.menu.read_bytes(), patch_witcher3(self.original))

    def test_injector_disable_and_remove_also_restore_menu(self):
        self.prepare()
        for action in ('disable', 'remove'):
            with self.subTest(action=action):
                if not self.m.record(self.game):
                    self.action('install')
                elif not self.m.record(self.game)['enabled']:
                    self.action('enable')
                self.action('labels_enable')
                self.action(action)
                self.assertEqual(self.menu.read_bytes(), self.original)
                if action == 'disable':
                    self.assertFalse(self.m.record(self.game)['menu_labels']['enabled'])

    def test_update_preserves_user_opt_in_and_never_changes_quality_modes(self):
        self.prepare()
        self.action('labels_enable')
        changed = self.menu.read_bytes()
        self.action('update')
        self.assertEqual(self.menu.read_bytes(), changed)
        self.assertTrue(self.state()['enabled'])
        self.assertIn(b'FSRFramegen', changed)

    def test_menu_drift_after_preview_never_gets_overwritten(self):
        self.prepare()
        token = self.m.preview(self.game['id'], 'labels_enable')['token']
        foreign = self.original + b'<!-- another mod -->'
        write(self.menu, foreign)
        before = self.m.record(self.game)
        with self.assertRaises(ValueError):
            self.m.execute(token)
        self.assertEqual(self.menu.read_bytes(), foreign)
        self.assertEqual(self.m.record(self.game), before)

    def test_external_edit_when_enabled_blocks_toggle_and_injector_removal(self):
        self.prepare()
        self.action('labels_enable')
        foreign = self.menu.read_bytes() + b'<!-- changed -->'
        write(self.menu, foreign)
        self.assertFalse(self.state()['available'])
        for action in ('labels_disable', 'disable', 'remove'):
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], action)
        self.assertEqual(self.menu.read_bytes(), foreign)

    def test_damaged_original_blocks_restore_before_binary_changes(self):
        self.prepare()
        self.action('labels_enable')
        backup = self.m.checked_menu_original(self.game, str(Path(WITCHER_XML)))
        write(backup, b'changed original')
        live = self.menu.read_bytes()
        native = self.native.read_bytes()
        with self.assertRaises(ValueError):
            self.action('labels_disable')
        self.assertEqual(self.menu.read_bytes(), live)
        self.assertEqual(self.native.read_bytes(), native)

    def test_write_failure_rolls_back_bytes_receipt_and_new_backup(self):
        self.prepare()
        before = self.m.record(self.game)
        token = self.m.preview(self.game['id'], 'labels_enable')['token']
        real_write = self.m.write_managed_bytes
        def fail_after_write(path, payload):
            real_write(path, payload)
            raise OSError('fixture write failure')
        with patch.object(self.m, 'write_managed_bytes', side_effect=fail_after_write):
            with self.assertRaises(OSError):
                self.m.execute(token)
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertEqual(self.m.record(self.game), before)
        self.assertFalse(self.m.checked_menu_original(self.game, str(Path(WITCHER_XML))).exists())
        self.assertFalse(self.m.recovery_available(self.game))

    def test_running_unknown_process_and_build_guards(self):
        self.prepare()
        with patch('manager.active_processes', return_value=[{'pid':42}]):
            self.assertFalse(self.state()['available'])
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], 'labels_enable')
        with patch('menu_labels.process_scan_ready', side_effect=ValueError('unknown process view')):
            self.assertFalse(self.state()['available'])
            with self.assertRaisesRegex(ValueError, 'unknown process'):
                self.m.preview(self.game['id'], 'labels_enable')
        rec = self.m.record(self.game)
        rec['game_build'] = '111'
        manager.atomic_json(self.m.record_path(self.game), rec)
        self.game['build'] = '222'
        with self.assertRaises(ValueError):
            self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(self.menu.read_bytes(), self.original)

    def test_unverified_games_cannot_be_enabled_by_spoofing_a_name(self):
        self.prepare()
        for appid in ('3357650','870780','3669870','2288340','3321460','unknown'):
            self.game.update(appid=appid, name='The Witcher 3')
            self.assertFalse(self.state()['supported'])
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], 'labels_enable')

    def test_hardlinked_resource_is_not_accepted(self):
        self.prepare()
        other = write(self.base / 'other.xml', self.original)
        self.menu.unlink()
        os.link(other, self.menu)
        with self.assertRaises(ValueError):
            self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(other.read_bytes(), self.original)

    def test_existing_hardlinked_original_is_not_adopted_even_with_matching_bytes(self):
        self.prepare()
        other = write(self.base / 'other-original.xml', self.original)
        original = self.m.checked_menu_original(self.game, str(Path(WITCHER_XML)))
        original.parent.mkdir(parents=True, exist_ok=True)
        os.link(other, original)
        self.assertFalse(self.state()['available'])
        with self.assertRaisesRegex(ValueError, 'hardlink'):
            self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertEqual(other.read_bytes(), self.original)

    def test_committed_cleanup_failure_retains_original_and_healthy_receipt(self):
        self.prepare()
        token = self.m.preview(self.game['id'], 'labels_enable')['token']
        real_remove = manager.shutil.rmtree
        failures = 0
        def fail_cleanup_once(path, *args, **kwargs):
            nonlocal failures
            if Path(path).name == 'transaction' and failures == 0:
                failures += 1
                raise OSError('fixture postcommit cleanup failure')
            return real_remove(path, *args, **kwargs)
        with patch('manager.shutil.rmtree', side_effect=fail_cleanup_once):
            with self.assertRaises(OSError):
                self.m.execute(token)
        self.assertTrue(self.state()['enabled'])
        self.assertTrue(self.state()['available'])
        self.assertEqual(self.m.checked_menu_original(self.game, str(Path(WITCHER_XML))).read_bytes(), self.original)
        self.action('labels_disable')
        self.assertEqual(self.menu.read_bytes(), self.original)

    def test_unknown_process_view_blocks_all_tracked_menu_restores(self):
        self.prepare()
        self.action('labels_enable')
        live = self.menu.read_bytes()
        before = self.m.record(self.game)
        with patch('menu_labels.process_scan_ready', side_effect=ValueError('unknown process view')):
            for action in ('labels_disable', 'disable', 'remove', 'update'):
                with self.assertRaisesRegex(ValueError, 'unknown process'):
                    self.m.preview(self.game['id'], action)
        self.assertEqual(self.menu.read_bytes(), live)
        self.assertEqual(self.m.record(self.game), before)

    def test_unknown_process_view_keeps_recovery_journal_and_files(self):
        self.prepare()
        self.action('labels_enable')
        rec = self.m.record(self.game)
        rel = str(Path(WITCHER_XML))
        tx = self.m.companion(self.game) / 'transaction'
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='labels_disable',
            before={rel: rec['current'][rel]}, previous=rec))
        live = self.menu.read_bytes()
        with patch('menu_labels.process_scan_ready', side_effect=ValueError('unknown process view')):
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], 'recover')
            with self.assertRaises(ValueError):
                self.m.rollback(self.game)
        self.assertTrue((tx / 'journal.json').is_file())
        self.assertEqual(self.menu.read_bytes(), live)

    def test_old_client_restored_receipt_reconciles_stale_flag_without_writing(self):
        self.prepare()
        self.action('labels_enable')
        self.action('disable')
        rec = self.m.record(self.game)
        rec['menu_labels']['enabled'] = True  # Old clients preserve unfamiliar flags.
        manager.atomic_json(self.m.record_path(self.game), rec)
        self.assertFalse(self.state()['enabled'])
        self.assertEqual(self.m.record(self.game), rec)
        self.action('enable')
        self.assertFalse(self.state()['enabled'])
        self.assertTrue(self.state()['available'])
        self.action('labels_enable')
        self.assertTrue(self.state()['enabled'])
        self.action('labels_disable')
        self.assertEqual(self.menu.read_bytes(), self.original)

    def test_external_restore_without_matching_current_receipt_stays_blocked(self):
        self.prepare()
        self.action('labels_enable')
        rec = self.m.record(self.game)
        write(self.menu, self.original)
        self.assertFalse(self.state()['available'])
        with self.assertRaises(ValueError):
            self.m.preview(self.game['id'], 'labels_enable')
        self.assertEqual(self.m.record(self.game), rec)
        self.assertEqual(self.menu.read_bytes(), self.original)

    def interrupted_enable(self):
        before = self.m.record(self.game)
        token = self.m.preview(self.game['id'], 'labels_enable')['token']
        real_write = self.m.write_managed_bytes
        def fail_after_write(path, payload):
            real_write(path, payload)
            raise OSError('fixture interrupted write')
        with patch.object(self.m, 'write_managed_bytes', side_effect=fail_after_write), \
                patch.object(self.m, 'rollback', side_effect=ValueError('deferred recovery')):
            with self.assertRaisesRegex(ValueError, 'deferred recovery'):
                self.m.execute(token)
        self.assertTrue(self.m.recovery_available(self.game))
        self.assertEqual(self.m.record(self.game), before)
        return before

    def test_fresh_manager_recovery_removes_only_exact_journal_owned_new_backup(self):
        self.prepare()
        before = self.interrupted_enable()
        original = self.m.checked_menu_original(self.game, str(Path(WITCHER_XML)))
        self.assertEqual(original.read_bytes(), self.original)
        self.m = manager.Manager(self.m.home, self.m.settings)
        self.m.entries = {self.game['id']: self.game}
        self.action('recover')
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertEqual(self.m.record(self.game), before)
        self.assertFalse(original.exists())
        self.assertFalse(self.m.recovery_available(self.game))
        self.action('labels_enable')
        self.assertTrue(self.state()['enabled'])

    def test_recovery_preserves_unknown_new_backup_bytes(self):
        self.prepare()
        before = self.interrupted_enable()
        original = self.m.checked_menu_original(self.game, str(Path(WITCHER_XML)))
        write(original, b'unknown partial copy')
        self.action('recover')
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertEqual(self.m.record(self.game), before)
        self.assertEqual(original.read_bytes(), b'unknown partial copy')
        with self.assertRaisesRegex(ValueError, 'backup conflicts'):
            self.action('labels_enable')

    def test_invalid_new_original_journal_stops_before_any_recovery_write(self):
        self.prepare()
        self.interrupted_enable()
        tx = self.m.companion(self.game) / 'transaction'
        journal = manager.load_json(tx / 'journal.json')
        journal['new_menu_original']['path'] = 'outside.xml'
        manager.atomic_json(tx / 'journal.json', journal)
        live = self.menu.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ownership journal'):
            self.m.rollback(self.game)
        self.assertEqual(self.menu.read_bytes(), live)
        self.assertTrue(self.m.recovery_available(self.game))


if __name__ == '__main__':
    unittest.main()
