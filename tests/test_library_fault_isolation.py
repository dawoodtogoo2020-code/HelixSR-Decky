"""Whole-library regression for per-game failures and optional shared settings."""
from unittest.mock import patch
from test_backend import Fixtures, write


class LibraryFaultIsolationTests(Fixtures):
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
