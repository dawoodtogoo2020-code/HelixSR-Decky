"""Read-only game files through install, repair, reset and recovery. Synthetic files only.

A privileged user can open a read-only file for writing, so most of these
tests only prove something when they run as a regular user (as CI does). The
descriptor test below holds for any user.
"""
import os
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import fcntl
except ImportError:  # not a POSIX host
    fcntl = None

try:
    from .test_backend import Fixtures, manager, pe, write
except ImportError:
    from test_backend import Fixtures, manager, pe, write


def mode(path):
    return stat.S_IMODE(Path(path).stat().st_mode)


class ReadOnlyFileTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.native.chmod(0o555)
        self.backup = self.native.with_name(self.native.stem + '.original.dll')
        self.saved = self.m.companion(self.game) / 'originals' / self.native.name
        self.tx = self.m.companion(self.game) / 'transaction'

    def replace_native(self, payload):
        # Steam replaces a file; it does not write into the read-only one.
        self.native.unlink()
        write(self.native, payload)
        self.native.chmod(0o555)

    @unittest.skipUnless(fcntl, 'needs POSIX descriptor flags')
    def test_copies_are_synced_through_read_only_descriptors(self):
        synced, real = {}, os.fsync

        def record(descriptor):
            info = os.fstat(descriptor)
            if stat.S_ISREG(info.st_mode):
                synced[info.st_dev, info.st_ino] = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
            return real(descriptor)

        def access(path):
            info = Path(path).stat()
            return synced.get((info.st_dev, info.st_ino))

        self.package()
        with patch.object(manager.os, 'fsync', side_effect=record):
            self.action('install')
            # durable_copy saved the original; copy_atomic wrote the DLL and its backup.
            for path in (self.saved, self.native, self.backup):
                self.assertEqual(access(path), os.O_RDONLY, path.name)
            self.backup.unlink()
            self.action('repair')
            # copy_absent_atomic put the backup back.
            self.assertEqual(access(self.backup), os.O_RDONLY)
        for path in (self.saved, self.backup):
            self.assertEqual(mode(path), 0o555)

    def test_transaction_stranded_by_the_writable_sync_recovers(self):
        # 0.1.50 failed the same way in install and in its own rollback, so the
        # journal, the snapshot and the saved original were all left behind.
        self.package()
        denied = PermissionError(13, 'Permission denied')
        with patch.object(manager.Manager, 'copy_atomic', side_effect=denied):
            with self.assertRaises(PermissionError):
                self.action('install')
        self.assertEqual(manager.load_json(self.tx / 'journal.json')['state'], 'prepared')
        self.assertEqual(mode(self.tx / 'snapshot' / self.native.name), 0o555)
        self.assertEqual(mode(self.saved), 0o555)

        self.action('recover')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.assertFalse(self.tx.exists())
        self.assertFalse(self.saved.exists())
        self.assertFalse(self.m.record(self.game))

        self.action('install')
        self.assertNotEqual(self.native.read_bytes(), self.original)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)

    def test_disable_enable_and_update_keep_the_read_only_original(self):
        self.package()
        self.action('install')
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(mode(self.backup), 0o555)
        self.action('disable')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.action('enable')
        self.action('update')
        self.assertNotEqual(self.native.read_bytes(), self.original)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.assertEqual(list(self.root.rglob('*.helixsr-decky.tmp')), [])

    def test_failed_install_rolls_back_the_read_only_original(self):
        self.package()
        with patch.object(manager.Manager, 'write_managed_json', side_effect=OSError('fixture write failure')):
            with self.assertRaisesRegex(OSError, 'fixture write failure'):
                self.action('install')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.tx.exists())
        self.assertEqual(list(self.root.rglob('*.helixsr-decky.tmp')), [])

    def test_missing_backup_repairs_from_the_read_only_saved_original(self):
        self.package()
        self.action('install')
        self.backup.unlink()
        self.assertEqual(self.m.assess(self.game)['repair_files'], [self.backup.name])
        self.action('repair')
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(mode(self.backup), 0o555)
        self.assertEqual(self.backup.stat().st_nlink, 1)

    def test_reinstall_after_reset_replaces_the_read_only_saved_original(self):
        # Reset keeps the old saved original. The next install saves the
        # current DLL to the same path.
        self.game['build'] = '20383525'
        self.package()
        self.action('install')
        self.game['build'] = '26161058'
        replacement = pe(ffx=True) + b'current game update; not asserted to be stock'
        self.replace_native(replacement)
        self.action('reset')
        self.assertEqual(self.saved.read_bytes(), self.original)
        self.assertEqual(mode(self.saved), 0o555)

        self.action('install')
        self.assertEqual(self.saved.read_bytes(), replacement)
        self.assertEqual(mode(self.saved), 0o555)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), replacement)
        self.assertEqual(mode(self.native), 0o555)
        archived = next((self.m.companion(self.game) / 'records').glob('reset-*'))
        self.assertEqual((archived / 'originals' / self.native.name).read_bytes(), self.original)

    def test_read_only_legacy_install_can_be_imported_and_removed(self):
        # Import first saves the installed DLL, then replaces that copy with the verified original.
        self.replace_native(pe(ffx=True, helix=True))
        write(self.backup, self.original).chmod(0o555)
        self.action('adopt')
        self.assertEqual(self.saved.read_bytes(), self.original)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.assertFalse(self.backup.exists())

    def test_read_only_temporary_copy_left_by_a_crash_is_replaced(self):
        self.package()
        for target in (self.native, self.backup):
            stale = write(target.with_name(target.name + '.helixsr-decky.tmp'), b'partial copy')
            stale.chmod(0o555)
        self.action('install')
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.backup.unlink()
        write(self.backup.with_name(self.backup.name + '.helixsr-decky.tmp'), b'partial copy').chmod(0o555)
        self.action('repair')
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(mode(self.native), 0o555)
        self.assertEqual(list(self.root.rglob('*.helixsr-decky.tmp')), [])

    def test_durable_copy_replaces_a_read_only_copy_and_never_writes_through_a_link(self):
        source = write(self.base / 'source.dll', b'new bytes')
        source.chmod(0o555)
        destination = write(self.base / 'saved/copy.dll', b'old bytes')
        destination.chmod(0o555)
        manager.durable_copy(source, destination)
        self.assertEqual(destination.read_bytes(), b'new bytes')
        self.assertEqual(mode(destination), 0o555)

        outside = write(self.base / 'outside.dll', b'not ours')
        linked = self.base / 'saved/linked.dll'
        self.link(linked, outside)
        manager.durable_copy(source, linked)
        self.assertFalse(linked.is_symlink())
        self.assertEqual(linked.read_bytes(), b'new bytes')
        self.assertEqual(outside.read_bytes(), b'not ours')


if __name__ == '__main__':
    unittest.main()
