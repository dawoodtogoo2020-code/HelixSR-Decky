"""Launcher-filtered discovery regression fixtures."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import library


def write(path, data=b'fixture'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


def shortcut(name, exe):
    def string(key, value):
        return b'\x01' + key.encode() + b'\0' + value.encode() + b'\0'
    return (b'\x00shortcuts\0\x000\0' + string('AppName', name) + string('Exe', exe)
            + string('StartDir', '') + string('LaunchOptions', '') + b'\x08\x08\x08')


def lutris_db(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            'CREATE TABLE games (name, directory, configpath, installed, runner)')
        connection.executemany(
            'INSERT INTO games (name, directory, configpath, installed, runner) '
            'VALUES (?, ?, ?, ?, ?)', rows)
        connection.commit()
    finally:
        connection.close()
    return path


class LauncherDiscoveryTests(unittest.TestCase):
    def setUp(self):
        work = PLUGIN.parent.parent / 'work'
        work.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='launcher-tests-', dir=work)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.games = self.base / 'games'

    def game(self, name):
        folder = self.games / name
        write(folder / f'{name}.exe')
        return folder

    def test_public_launcher_keys_are_stable_and_unknown_is_rejected(self):
        self.assertEqual(set(library.LAUNCHER_SOURCES), {
            'heroic', 'lutris', 'legendary', 'steam-shortcuts', 'all-launchers',
        })
        with self.assertRaisesRegex(ValueError, 'Unknown launcher source'):
            library.discover_launcher(self.home, 'epic')
        with self.assertRaisesRegex(ValueError, 'Unknown discovery source'):
            library.discover(self.home, sources={'epic'})

    def test_native_and_flatpak_records_are_scoped_to_selected_launcher(self):
        heroic_native = self.game('heroic-native')
        heroic_flatpak = self.game('heroic-flatpak')
        heroic_epic = self.game('heroic-epic')
        lutris_native = self.game('lutris-native')
        lutris_flatpak = self.game('lutris-flatpak')
        legendary_native = self.game('legendary-native')
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps({
            'installed': [{'installPath': str(heroic_native), 'title': 'Heroic native'}],
        }))
        write(self.home / '.var/app/com.heroicgameslauncher.hgl/config/heroic/'
              'nile_config/installed.json', json.dumps({
                  'games': [{'install_path': str(heroic_flatpak), 'name': 'Heroic Flatpak'}],
              }))
        write(self.home / '.config/heroic/legendaryConfig/legendary/installed.json', json.dumps({
            'epic': {'install_path': str(heroic_epic), 'title': 'Heroic Epic'},
        }))
        write(self.home / '.config/lutris/games/native.yml',
              f'name: Lutris native\ngame:\n  exe: "{lutris_native / "lutris-native.exe"}"\n')
        write(self.home / '.var/app/net.lutris.Lutris/config/lutris/games/flatpak.yml',
              f'name: Lutris Flatpak\ngame:\n  exe: "{lutris_flatpak / "lutris-flatpak.exe"}"\n')
        write(self.home / '.config/legendary/installed.json', json.dumps({
            'game': {'install_path': str(legendary_native), 'title': 'Legendary native'},
        }))

        heroic, _ = library.discover_launcher(self.home, 'heroic')
        lutris, _ = library.discover_launcher(self.home, 'lutris')
        legendary, _ = library.discover_launcher(self.home, 'legendary')
        self.assertEqual({g['name'] for g in heroic},
                         {'Heroic native', 'Heroic Flatpak', 'Heroic Epic'})
        self.assertEqual({g['source'] for g in heroic}, {'Heroic'})
        self.assertEqual({g['name'] for g in lutris}, {'Lutris native', 'Lutris Flatpak'})
        self.assertEqual({g['source'] for g in lutris}, {'Lutris'})
        self.assertEqual([g['name'] for g in legendary], ['Legendary native'])

    def test_filtering_precedes_dedup_for_folder_also_registered_in_steam(self):
        steam = self.home / '.local/share/Steam'
        shared = steam / 'steamapps/common/Shared'
        write(shared / 'Shared.exe')
        write(steam / 'steamapps/appmanifest_42.acf',
              '"AppState" { "appid" "42" "name" "Steam copy" "installdir" "Shared" }')
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps({
            'installed': [{'installPath': str(shared), 'title': 'Heroic copy'}],
        }))

        automatic, _ = library.discover(self.home)
        selected, _ = library.discover_launcher(self.home, 'heroic')
        self.assertEqual(len(automatic), 1)
        self.assertEqual(automatic[0]['id'], 'steam:42')
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['source'], 'Heroic')
        self.assertEqual(selected[0]['id'], library.ident('Heroic', shared.resolve()))

    def test_duplicate_launcher_paths_keep_first_record_and_stable_id(self):
        shared = self.game('Duplicate')
        payload = {'installed': [{'installPath': str(shared), 'title': 'Native title'}]}
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps(payload))
        payload['installed'][0]['title'] = 'Flatpak title'
        write(self.home / '.var/app/com.heroicgameslauncher.hgl/config/heroic/'
              'gog_store/installed.json', json.dumps(payload))

        games, warnings = library.discover_launcher(self.home, 'heroic')
        self.assertFalse(warnings)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['name'], 'Native title')
        self.assertEqual(games[0]['id'], library.ident('Heroic', shared.resolve()))

    def test_steam_shortcuts_and_all_launchers_exclude_steam_manifests(self):
        shortcut_game = self.game('Shortcut')
        heroic_game = self.game('Heroic')
        steam = self.home / '.local/share/Steam'
        regular = steam / 'steamapps/common/Regular'
        write(regular / 'Regular.exe')
        write(steam / 'steamapps/appmanifest_9.acf',
              '"AppState" { "appid" "9" "name" "Regular" "installdir" "Regular" }')
        write(steam / 'userdata/1/config/shortcuts.vdf',
              shortcut('Shortcut game', str(shortcut_game / 'Shortcut.exe')))
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps({
            'installed': [{'installPath': str(heroic_game), 'title': 'Heroic game'}],
        }))

        shortcuts, _ = library.discover_launcher(self.home, 'steam-shortcuts')
        combined, _ = library.discover_launcher(self.home, 'all-launchers')
        self.assertEqual([g['source'] for g in shortcuts], ['Steam shortcut'])
        self.assertEqual({g['source'] for g in combined}, {'Steam shortcut', 'Heroic'})
        self.assertNotIn('steam:9', {g['id'] for g in combined})

    def test_malformed_records_are_bounded_and_do_not_cross_sources(self):
        steam = self.home / '.local/share/Steam'
        write(steam / 'userdata/1/config/shortcuts.vdf', b'not binary vdf')
        write(self.home / '.config/heroic/gog_store/installed.json', '{bad json')
        write(self.home / '.config/heroic/nile_config/installed.json', json.dumps({
            'installed': [None, 'bad', {}, {'installPath': 'relative/path', 'title': 'Unsafe'}],
        }))
        write(self.home / '.config/lutris/games/bad.yml', 'name: Missing executable\ngame: {}\n')

        heroic, heroic_warnings = library.discover_launcher(self.home, 'heroic')
        shortcuts, shortcut_warnings = library.discover_launcher(self.home, 'steam-shortcuts')
        self.assertFalse(heroic)
        self.assertTrue(any('existing absolute game folder' in w for w in heroic_warnings))
        self.assertFalse(shortcuts)
        self.assertEqual(shortcut_warnings, ['A Steam shortcut file could not be parsed'])

    def test_existing_malformed_json_warns_but_missing_metadata_stays_quiet(self):
        missing, missing_warnings = library.discover_launcher(self.home, 'legendary')
        self.assertFalse(missing)
        self.assertFalse(missing_warnings)

        heroic_file = self.home / '.config/heroic/gog_store/installed.json'
        legendary_file = self.home / '.config/legendary/installed.json'
        write(heroic_file, '{bad json')
        write(legendary_file, '[also bad')
        _, heroic_warnings = library.discover_launcher(self.home, 'heroic')
        _, legendary_warnings = library.discover_launcher(self.home, 'legendary')
        self.assertEqual(heroic_warnings, [f'Heroic: Cannot parse {heroic_file}'])
        self.assertEqual(legendary_warnings, [f'Legendary: Cannot parse {legendary_file}'])

    def test_wrong_typed_paths_warn_and_preserve_valid_launcher_records(self):
        heroic_valid = self.game('heroic-valid')
        legendary_valid = self.game('legendary-valid')
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps({
            'installed': [
                {'installPath': 123}, {'installPath': ['bad']},
                {'installPath': {'bad': 'path'}},
                {'installPath': str(heroic_valid), 'title': 'Heroic valid'},
            ],
        }))
        write(self.home / '.config/legendary/installed.json', json.dumps({
            'bad-number': {'install_path': 123},
            'bad-list': {'install_path': ['bad']},
            'bad-dict': {'install_path': {'bad': 'path'}},
            'valid': {'install_path': str(legendary_valid), 'title': 'Legendary valid'},
        }))

        heroic, heroic_warnings = library.discover_launcher(self.home, 'heroic')
        legendary, legendary_warnings = library.discover_launcher(self.home, 'legendary')
        self.assertEqual([g['name'] for g in heroic], ['Heroic valid'])
        self.assertEqual([g['name'] for g in legendary], ['Legendary valid'])
        self.assertEqual(heroic_warnings, ['Heroic: install path must be text'])
        self.assertEqual(legendary_warnings, ['Legendary: install path must be text'])

    def test_lutris_native_and_flatpak_data_roots_are_discovered(self):
        native = self.game('lutris-data-native')
        flatpak = self.game('lutris-data-flatpak')
        write(self.home / '.local/share/lutris/games/native.yml',
              f'name: Native data root\ngame:\n  exe: "{native / "lutris-data-native.exe"}"\n')
        write(self.home / '.var/app/net.lutris.Lutris/data/lutris/games/flatpak.yml',
              f'name: Flatpak data root\ngame:\n  exe: "{flatpak / "lutris-data-flatpak.exe"}"\n')

        games, warnings = library.discover_launcher(self.home, 'lutris')
        self.assertFalse(warnings)
        self.assertEqual({g['name'] for g in games}, {'Native data root', 'Flatpak data root'})

    def test_lutris_db_associates_name_and_resolves_relative_executables(self):
        directory = self.games / 'db-directory'
        working = self.games / 'working-directory'
        prefix = self.games / 'prefix-directory'
        write(directory / 'bin/Directory.exe')
        write(working / 'bin/Working.exe')
        write(prefix / 'drive_c/Prefix.exe')
        database = lutris_db(self.home / '.local/share/lutris/pga.db', [
            ('Friendly database name', str(directory), 'directory-game', 1, 'wine'),
            ('working-game', '', 'working-game', 1, 'wine'),
            ('prefix-game', '', 'prefix-game', 1, 'wine'),
            ('Ignored non-Wine game', str(self.games), 'ignored', 1, 'linux'),
            ('Ignored uninstalled game', str(self.games), 'uninstalled', 0, 'wine'),
        ])
        config = write(self.home / '.local/share/lutris/games/directory-game.yml',
                       'game:\n  exe: bin/Directory.exe\n')
        write(self.home / '.local/share/lutris/games/working-game.yml',
              f'game:\n  exe: bin/Working.exe\n  working_dir: "{working}"\n  prefix: "{prefix}"\n')
        write(self.home / '.local/share/lutris/games/prefix-game.yml',
              f'game:\n  exe: drive_c/Prefix.exe\n  prefix: "{prefix}"\n')
        write(self.home / '.local/share/lutris/games/ignored.yml',
              'game:\n  exe: Missing.exe\n')
        write(self.home / '.local/share/lutris/games/uninstalled.yml',
              'game:\n  exe: Missing.exe\n')
        before = {p: p.read_bytes() for p in (
            database, config, directory / 'bin/Directory.exe',
            working / 'bin/Working.exe', prefix / 'drive_c/Prefix.exe',
        )}

        games, warnings = library.discover_launcher(self.home, 'lutris')
        self.assertFalse(warnings)
        self.assertEqual({g['name'] for g in games},
                         {'Friendly database name', 'working-game', 'prefix-game'})
        folders = {g['name']: Path(g['folder']) for g in games}
        self.assertEqual(folders['Friendly database name'], (directory / 'bin').resolve())
        self.assertEqual(folders['working-game'], (working / 'bin').resolve())
        self.assertEqual(folders['prefix-game'], (prefix / 'drive_c').resolve())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_lutris_absent_or_corrupt_db_keeps_absolute_yaml_and_metadata_unchanged(self):
        game = self.game('lutris-without-db')
        config = write(self.home / '.local/share/lutris/games/absolute.yml',
                       f'name: Absolute fallback\ngame:\n  exe: "{game / "lutris-without-db.exe"}"\n')
        games, warnings = library.discover_launcher(self.home, 'lutris')
        self.assertEqual([g['name'] for g in games], ['Absolute fallback'])
        self.assertFalse(warnings)

        database = write(self.home / '.local/share/lutris/pga.db', b'not a sqlite database')
        before = {p: p.read_bytes() for p in (database, config, game / 'lutris-without-db.exe')}
        games, warnings = library.discover_launcher(self.home, 'lutris')
        self.assertEqual([g['name'] for g in games], ['Absolute fallback'])
        self.assertEqual(warnings, [f'Lutris: Cannot read {database}'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_lutris_bad_database_paths_warn_without_reading_outside_records(self):
        database = lutris_db(self.home / '.local/share/lutris/pga.db', [
            ('Wrong type', 123, 'wrong-type', 1, 'wine'),
            ('Traversal', str(self.games), '../escape', 1, 'wine'),
            ('Relative directory', 'relative/base', 'relative-base', 1, 'wine'),
        ])
        wrong = write(self.home / '.local/share/lutris/games/wrong-type.yml',
                      'game:\n  exe: Game.exe\n')
        relative = write(self.home / '.local/share/lutris/games/relative-base.yml',
                         'game:\n  exe: Game.exe\n')
        before = {p: p.read_bytes() for p in (database, wrong, relative)}

        games, warnings = library.discover_launcher(self.home, 'lutris')
        self.assertFalse(games)
        self.assertTrue(any('game directory must be text' in item for item in warnings))
        self.assertTrue(any('invalid installed game config path' in item for item in warnings))
        self.assertTrue(any('relative base path ignored' in item for item in warnings))
        self.assertTrue(any('Windows executable unresolved' in item for item in warnings))
        self.assertEqual(before, {p: p.read_bytes() for p in before})


if __name__ == '__main__':
    unittest.main()
