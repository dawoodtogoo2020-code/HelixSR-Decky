"""Selected launcher import integration; no real installed games are modified."""
import copy
import json
from unittest.mock import patch
import unittest

from test_backend import Fixtures, pe, write


class LauncherImport(Fixtures):
    def heroic(self, records):
        return write(self.home / '.config/heroic/gog_store/installed.json',
                     json.dumps({'installed': records}))

    def test_import_reports_candidates_without_installing_or_saving_folders(self):
        other = self.base / 'games' / 'Unsupported'
        write(other / 'Game.exe', pe())
        self.heroic([{'installPath': str(self.root), 'title': 'Supported'},
                     {'installPath': str(other), 'title': 'Unsupported'}])
        self.m.entries.clear()
        before_cfg = copy.deepcopy(self.m.cfg)
        before_files = {str(p): p.read_bytes() for root in (self.root, other)
                        for p in root.rglob('*') if p.is_file()}
        result = self.m.import_launcher('heroic')
        report = result['launcher_import']
        self.assertEqual((report['found'], report['added'], report['candidates'],
                          report['unavailable']), (2, 2, 1, 1))
        self.assertEqual(set(report['game_ids']), {g['id'] for g in result['games']})
        self.assertTrue(all(g['source'] == 'Heroic' for g in result['games']))
        self.assertTrue(all(not g['managed'] for g in result['games']))
        self.assertEqual(self.m.cfg, before_cfg)
        self.assertEqual({str(p): p.read_bytes() for root in (self.root, other)
                          for p in root.rglob('*') if p.is_file()}, before_files)
        again = self.m.import_launcher('heroic')['launcher_import']
        self.assertEqual((again['found'], again['added']), (2, 0))
        self.assertEqual(len(self.m.entries), 2)

    def test_selected_launcher_duplicate_preserves_steam_identity(self):
        _, directory, _ = self.steam()
        self.heroic([{'installPath': str(directory), 'title': 'Heroic copy'}])
        self.m.refresh()
        result = self.m.import_launcher('heroic')
        report = result['launcher_import']
        self.assertEqual((report['found'], report['added'], report['candidates']), (1, 0, 1))
        self.assertEqual(report['game_ids'], ['steam:42'])
        self.assertEqual(len(result['games']), 1)
        self.assertEqual(result['games'][0]['source'], 'Steam')
        self.assertEqual(result['games'][0]['appid'], '42')

    def test_source_counts_do_not_include_other_launchers_or_manual_folders(self):
        other = self.base / 'games' / 'Legendary'
        write(other / 'Game.exe', pe(dx12=True))
        write(self.home / '.config/legendary/installed.json', json.dumps({
            'id': {'install_path': str(other), 'title': 'Legendary game'}}))
        self.m.import_folder(str(self.root), 'Manual')
        result = self.m.import_launcher('lutris')
        self.assertEqual(result['launcher_import']['found'], 0)
        self.assertEqual(result['launcher_import']['game_ids'], [])
        self.assertEqual({g['source'] for g in result['games']}, {'Imported', 'Legendary'})

    def test_invalid_source_is_rejected_before_refresh(self):
        before = copy.deepcopy(self.m.entries)
        with patch.object(self.m, 'refresh') as refresh:
            with self.assertRaises(ValueError):
                self.m.import_launcher('unknown-launcher')
        refresh.assert_not_called()
        self.assertEqual(self.m.entries, before)

    def test_malformed_launcher_report_retains_usable_steam_library(self):
        self.steam()
        write(self.home / '.config/heroic/gog_store/installed.json', '{broken')
        result = self.m.import_launcher('heroic')
        self.assertEqual(result['launcher_import']['found'], 0)
        self.assertTrue(result['launcher_import']['warnings'])
        self.assertTrue(result['warnings'])
        self.assertEqual([g['id'] for g in result['games']], ['steam:42'])


if __name__ == '__main__':
    unittest.main()
