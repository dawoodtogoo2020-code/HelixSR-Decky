"""Cleanup remains valid when a user has already removed the introduced directory."""
import shutil
import unittest
from unittest.mock import patch
from test_backend import Fixtures, pe, write
import manager


class AbsentDirectoryCleanupTests(unittest.TestCase):
    setUp = Fixtures.setUp
    package = Fixtures.package
    action = Fixtures.action

    def prepare_absent_directory(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        self.package()
        self.action('install')
        target = self.root / 'HelixSR'
        self.assertTrue(target.is_relative_to(self.base))
        shutil.rmtree(target)
        self.assertTrue(self.m.assess(self.game)['installation_status']['can_restore'])

    def test_remove_after_entire_introduced_directory_is_already_absent(self):
        self.prepare_absent_directory()
        self.action('remove')
        self.assertFalse(self.m.record(self.game))
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertTrue((self.root / 'nvngx_dlss.dll').is_file())

    def test_disable_then_remove_after_introduced_directory_is_absent(self):
        self.prepare_absent_directory()
        self.action('disable')
        self.assertFalse(self.m.record(self.game)['enabled'])
        self.action('remove')
        self.assertFalse(self.m.record(self.game))

    def test_unlink_syncs_only_an_actual_deletion_and_propagates_sync_errors(self):
        absent = self.root / 'missing-parent' / 'file.dll'
        with patch('manager.sync_directory') as sync:
            self.m.unlink_managed(absent)
            sync.assert_not_called()
        live = write(self.root / 'file.dll', b'fixture')
        with patch('manager.sync_directory', side_effect=PermissionError('fixture denied')):
            with self.assertRaises(PermissionError):
                self.m.unlink_managed(live)


if __name__ == '__main__':
    unittest.main()
