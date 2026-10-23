"""Whole-library regression for per-game failures and optional shared settings."""
from unittest.mock import patch
from test_backend import Fixtures, write


class LibraryFaultIsolationTests(Fixtures):
    def test_import_and_forget_recover_malformed_saved_records(self):
        self.m.cfg['imports'] = [{'name': 'broken'}, dict(self.game)]
        with patch('manager.discover', return_value=([self.game], [])):
            result = self.m.import_folder(str(self.root))
        self.assertEqual(len(self.m.cfg['imports']), 1)
        self.assertEqual(self.m.cfg['imports'][0]['folder'], str(self.root))
        self.assertTrue(any('Imported: entry 1' in warning for warning in result['warnings']))
        self.m.cfg['imports'].append(None)
        with patch('manager.discover', return_value=([], [])):
            result = self.m.forget(self.game['id'])
        self.assertEqual(self.m.cfg['imports'], [])
        self.assertTrue(any('Imported: entry 2' in warning for warning in result['warnings']))

    def test_optional_bad_profiles_do_not_hide_games_or_abort_details(self):
        write(self.home / '.config/mako-render/conf.toml', 'profile = "broken"')
        write(self.home / '.config/lsfg-vk/conf.toml', 'profile = [1, "broken"]')
        write(self.home / '.local/share/Steam/userdata/1/config/localconfig.vdf',
              '"UserLocalConfigStore" "broken"')
        game = dict(self.game, appid='42')
        with patch('manager.discover', return_value=([game], [])):
            rows = self.m.refresh()['games']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['compatibility'], 'candidate')
        details = self.m.assess_safe(game)
        self.assertEqual(details['compatibility'], 'candidate')
        self.assertTrue(details['awareness_warnings'])
        self.assertIn('unknown', details['framegen_summary'])

    def test_corrupt_receipt_keeps_healthy_game_visible(self):
        broken = dict(self.game, id='broken')
        with patch('manager.discover', return_value=([broken, self.game], [])), \
                patch.object(self.m, 'record', side_effect=lambda game: ['invalid'] if game['id'] == 'broken' else {}):
            rows = self.m.refresh()['games']
        self.assertEqual([g['compatibility'] for g in rows], ['blocked', 'candidate'])
        self.assertFalse(rows[0]['installation_status']['can_modify'])
