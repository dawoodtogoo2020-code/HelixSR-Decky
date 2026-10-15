"""Synthetic cleanup regressions; no games, downloads, or model generation."""
import os
import unittest
from unittest.mock import patch
from test_backend import Fixtures, pe, write
import manager


class OptiScalerCleanupTests(unittest.TestCase):
    setUp = Fixtures.setUp
    package = Fixtures.package
    action = Fixtures.action

    def install_opti(self, original_config=None):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        if original_config:
            write(self.root / 'fakenvapi.ini', original_config)
        self.package()
        self.action('install')

    def snapshot(self):
        return {p.relative_to(self.base).as_posix(): p.read_bytes()
                for p in self.base.rglob('*') if p.is_file()}

    def assert_blocked_without_writes(self):
        before = self.snapshot()
        self.assertFalse(self.m.assess_safe(self.game)['installation_status']['can_restore'])
        for action in ('disable', 'remove', 'update', 'enable'):
            with self.assertRaises((OSError, ValueError)):
                self.m.preview(self.game['id'], action)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.m.record(self.game))

    def test_missing_introduced_proxy_can_remove_without_touching_user_files(self):
        self.install_opti()
        user_file = write(self.root / 'user.txt', b'keep user bytes')
        (self.root / 'dxgi.dll').unlink()
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        self.assertTrue(data['installation_status']['can_restore'])
        self.action('remove')
        self.assertFalse(self.m.record(self.game))
        self.assertEqual(user_file.read_bytes(), b'keep user bytes')
        self.assertEqual((self.root / 'nvngx_dlss.dll').read_bytes(), pe())

    def test_missing_introduced_configuration_can_disable_then_remove(self):
        self.install_opti()
        (self.root / 'OptiScaler.ini').unlink()
        self.assertTrue(self.m.assess(self.game)['installation_status']['can_restore'])
        self.action('disable')
        self.assertFalse(self.m.record(self.game)['enabled'])
        self.action('remove')
        self.assertFalse(self.m.record(self.game))

    def test_preexisting_configuration_original_is_restored_exactly(self):
        original = b'; user original\r\n[Settings]\r\nKeep=true\r\n'
        self.install_opti(original)
        (self.root / 'dxgi.dll').unlink()
        self.action('remove')
        self.assertEqual((self.root / 'fakenvapi.ini').read_bytes(), original)

    def test_missing_proxy_does_not_allow_foreign_binary(self):
        self.install_opti()
        (self.root / 'dxgi.dll').unlink()
        write(self.root / 'fakenvapi.dll', b'foreign mod bytes')
        self.assert_blocked_without_writes()

    def test_missing_proxy_does_not_allow_changed_original_backup(self):
        self.install_opti(b'[Settings]\nKeep=true\n')
        (self.root / 'dxgi.dll').unlink()
        write(self.m.companion(self.game) / 'originals/fakenvapi.ini', b'changed')
        self.assert_blocked_without_writes()

    def test_post_preview_change_refuses_before_any_write(self):
        self.install_opti()
        (self.root / 'dxgi.dll').unlink()
        token = self.m.preview(self.game['id'], 'remove')['token']
        write(self.root / 'fakenvapi.dll', b'changed after review')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.m.execute(token)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.m.record(self.game))

    def test_missing_proxy_never_unlocks_install_update_or_enable(self):
        self.install_opti()
        (self.root / 'dxgi.dll').unlink()
        for action in ('install', 'update', 'enable'):
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], action)

    def test_running_game_still_blocks_cleanup(self):
        self.install_opti()
        (self.root / 'dxgi.dll').unlink()
        with patch('manager.active_processes', return_value=[{'pid': 42}]):
            self.assert_blocked_without_writes()

    def test_directory_cannot_be_treated_as_an_absent_file(self):
        self.install_opti()
        path = self.root / 'dxgi.dll'
        path.unlink()
        path.mkdir()
        self.assert_blocked_without_writes()

    def test_hardlink_cannot_be_treated_as_owned_bytes(self):
        self.install_opti()
        path = self.root / 'dxgi.dll'
        outside = write(self.base / 'linked.dll', path.read_bytes())
        path.unlink()
        os.link(outside, path)
        self.assert_blocked_without_writes()

    def test_symlink_is_rejected_before_restoration(self):
        self.install_opti()
        path = self.root / 'dxgi.dll'
        outside = write(self.base / 'foreign.dll', b'foreign')
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError as exc:
            self.skipTest('Platform does not permit synthetic symlinks: ' + str(exc))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.m.preview(self.game['id'], 'remove')
        self.assertEqual(self.snapshot(), before)

    def test_build_change_and_staging_still_block_cleanup(self):
        self.install_opti()
        (self.root / 'dxgi.dll').unlink()
        receipt = self.m.record(self.game)
        receipt['game_build'] = '111'
        manager.atomic_json(self.m.record_path(self.game), receipt)
        self.game['build'] = '222'
        self.assert_blocked_without_writes()
        manifest = write(self.base / 'library/steamapps/appmanifest_123.acf',
                         '"AppState" { "StateFlags" "4" "buildid" "111" }')
        self.game.update(source='Steam', appid='123', manifest=str(manifest),
                         library=str(self.base / 'library'), build='111')
        write(self.base / 'library/steamapps/downloading/123/partial', b'active update')
        self.assert_blocked_without_writes()


if __name__ == '__main__':
    unittest.main()
