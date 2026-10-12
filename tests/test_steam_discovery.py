"""Steam library discovery regressions using only temporary local metadata."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import library


def write(path, data='fixture'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding='utf-8')
    return path


def manifest(library_root, appid, directory, name=None):
    game = Path(library_root) / 'steamapps/common' / directory
    write(game / 'Game.exe')
    return write(Path(library_root) / f'steamapps/appmanifest_{appid}.acf',
                 '"AppState" { "appid" "' + str(appid) + '" "name" "' + (name or directory)
                 + '" "installdir" "' + directory + '" "StateFlags" "4" }')


class SteamDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PLUGIN.parent.parent / 'work')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.primary = self.home / '.local/share/Steam'

    def test_malformed_appstate_and_scalar_fields_do_not_hide_healthy_manifest(self):
        manifest(self.primary, '42', 'Healthy')
        for source in ('"AppState" "invalid"',
                       '"AppState" { "appid" "43" "installdir" "Broken" "StateFlags" {} }'):
            with self.subTest(source=source):
                write(self.primary / 'steamapps/appmanifest_43.acf', source)
                games, notes = self.discovery()
                self.assertEqual([g['id'] for g in games], ['steam:42'])
                self.assertTrue(any('invalid game manifest structure' in n for n in notes))

    def test_legacy_statistics_are_not_interpreted_as_library_paths(self):
        manifest(self.primary, '42', 'Healthy')
        write(self.primary / 'steamapps/libraryfolders.vdf',
              '"libraryfolders" { "TimeNextStatsReport" "123" "ContentStatsID" "abc" }')
        games, notes = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:42'])
        self.assertEqual(notes, [])

    def discovery(self, roots=None):
        if roots is None:
            return library.discover(self.home)
        with patch('library.steam_roots', return_value=roots):
            return library.discover(self.home)

    def test_primary_library_manifest_is_discovered(self):
        manifest(self.primary, 10, 'Primary Game')
        games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:10'])
        self.assertFalse(any('no installed game manifests' in note for note in warnings))

    def test_directory_limit_stops_empty_directory_tree_with_clear_error(self):
        root = self.base.resolve()
        tree = [(str(root), [], [])] + [(str(root / str(i)), [], []) for i in range(3)]
        with patch('library.os.walk', return_value=iter(tree)), self.assertRaisesRegex(ValueError, 'directory limit'):
            library.scan_tree(root, max_dirs=3)

    def test_wrong_shaped_shortcuts_do_not_hide_healthy_steam_library(self):
        manifest(self.primary, '42', 'Healthy')
        shortcut = self.primary / 'userdata/1/config/shortcuts.vdf'
        shortcut.parent.mkdir(parents=True)
        shortcut.write_bytes(b'\x01shortcuts\x00unexpected text\x00\x08')
        games, notes = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:42'])
        self.assertTrue(any('shortcut file could not be parsed' in n for n in notes))

    def test_secondary_mounted_library_is_discovered(self):
        sd = self.base / 'run/media/mmcblk0p1/SteamLibrary'
        manifest(sd, 11, 'SD Game')
        write(self.primary / 'steamapps/libraryfolders.vdf',
              '"libraryfolders" { "1" { "path" "' + sd.as_posix() + '" } }')
        games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:11'])
        self.assertFalse(any('unavailable or not mounted' in note for note in warnings))

    def test_flatpak_root_and_duplicate_alias_are_scanned_once(self):
        flatpak = self.home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        manifest(flatpak, 12, 'Flatpak Game')
        games, warnings = self.discovery([flatpak, flatpak])
        self.assertEqual([g['id'] for g in games], ['steam:12'])
        self.assertFalse(any('no installed game manifests' in note for note in warnings))

    def test_malformed_primary_metadata_does_not_hide_valid_other_root(self):
        other = self.home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        write(self.primary / 'steamapps/libraryfolders.vdf', '"libraryfolders" { "1" {')
        manifest(other, 13, 'Other Root')
        games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:13'])
        self.assertTrue(any('library metadata is malformed' in note for note in warnings))

    def test_wrong_shaped_metadata_does_not_hide_primary_manifest(self):
        write(self.primary / 'steamapps/libraryfolders.vdf', '"libraryfolders" "wrong shape"')
        manifest(self.primary, 131, 'Primary Game')
        games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:131'])
        self.assertTrue(any('library metadata has an invalid shape' in note for note in warnings))

    def test_unreadable_library_metadata_keeps_primary_and_reports_secondary_risk(self):
        metadata = write(self.primary / 'steamapps/libraryfolders.vdf', '"libraryfolders" {}')
        manifest(self.primary, 14, 'Primary Still Visible')
        real = library.steam_text

        def blocked(path, limit=2 << 20):
            if Path(path) == metadata:
                return None, 'unreadable'
            return real(path, limit)

        with patch('library.steam_text', side_effect=blocked):
            games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:14'])
        self.assertTrue(any('library metadata unreadable' in note for note in warnings))

    def test_unreadable_manifest_does_not_hide_healthy_manifest(self):
        bad = manifest(self.primary, 15, 'Unreadable Game')
        manifest(self.primary, 16, 'Healthy Game')
        real = library.steam_text

        def blocked(path, limit=2 << 20):
            if Path(path) == bad:
                return None, 'unreadable'
            return real(path, limit)

        with patch('library.steam_text', side_effect=blocked):
            games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:16'])
        self.assertTrue(any('game manifest unreadable' in note for note in warnings))

    def test_missing_secondary_mount_has_actionable_warning(self):
        missing = self.base / 'run/media/mmcblk0p1/SteamLibrary'
        write(self.primary / 'steamapps/libraryfolders.vdf',
              '"libraryfolders" { "1" "' + missing.as_posix() + '" }')
        games, warnings = self.discovery()
        self.assertFalse(games)
        self.assertTrue(any('unavailable or not mounted' in note for note in warnings))

    def test_no_root_and_no_manifests_have_distinct_offline_notes(self):
        games, warnings = self.discovery([])
        self.assertFalse(games)
        self.assertIn('Steam: no supported Steam library root found for this user', warnings)

        self.primary.mkdir(parents=True)
        games, warnings = self.discovery()
        self.assertFalse(games)
        self.assertIn('Steam: no installed game manifests were found; check Steam library mounts', warnings)

    def test_invalid_manifest_path_segments_are_skipped_without_aborting_library(self):
        write(self.primary / 'steamapps/appmanifest_17.acf',
              '"AppState" { "appid" "17" "installdir" "../escape" }')
        manifest(self.primary, 18, 'Healthy Game')
        games, warnings = self.discovery()
        self.assertEqual([g['id'] for g in games], ['steam:18'])
        self.assertTrue(any('invalid game manifest entry: appmanifest_17.acf' in note for note in warnings))

    def test_six_thousand_manifest_scan_is_metadata_only_and_isolates_bad_entry(self):
        """Exercise a large library without creating games or calling Manager assessment."""
        self.primary.mkdir(parents=True)
        steamapps = self.primary / 'steamapps'
        manifests = [steamapps / f'appmanifest_{appid}.acf' for appid in range(10000, 16000)]
        malformed = manifests[3000]
        real_glob = Path.glob
        calls = []

        def generated_glob(path, pattern):
            if path == steamapps and pattern == 'appmanifest_*.acf':
                return iter(manifests)
            return real_glob(path, pattern)

        def generated_text(path, limit=2 << 20):
            path = Path(path)
            calls.append(path)
            if path == steamapps / 'libraryfolders.vdf':
                return '"libraryfolders" {}', None
            if path == malformed:
                return '"AppState" {', None
            appid = path.stem.removeprefix('appmanifest_')
            return ('"AppState" { "appid" "' + appid + '" "installdir" "Game' + appid
                    + '" }'), None

        with patch('library.Path.glob', new=generated_glob), \
                patch('library.steam_text', side_effect=generated_text), \
                patch('library.safe_root', side_effect=lambda folder: Path(folder)):
            games, warnings = self.discovery()
        self.assertEqual(len(games), 5999)
        self.assertEqual(len(calls), 6001)
        self.assertTrue(any('game manifest is malformed' in note for note in warnings))
        self.assertFalse(any('entitlement' in note.lower() for note in warnings))


if __name__ == '__main__':
    unittest.main(verbosity=2)
