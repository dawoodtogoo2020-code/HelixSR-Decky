"""Regression checks for the additive installation explanation contract."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from installation_status import RUNNING_REASON, installation_status


class InstallationStatusTests(unittest.TestCase):
    def game(self, **changes):
        game = dict(compatibility='candidate', reasons=[], managed=False,
                    enabled=False, legacy=False, recovery_available=False)
        game.update(changes)
        return game

    def test_running_only_is_selectable_and_pauses_changes(self):
        game = self.game(compatibility='blocked', reasons=[RUNNING_REASON],
                         managed=True, enabled=True)
        status = installation_status(game)
        self.assertEqual((status['state'], status['label']), ('running', 'Game running'))
        self.assertEqual(status['summary'], 'File changes paused until the game closes.')
        self.assertTrue(status['running'])
        self.assertTrue(status['selectable'])
        self.assertFalse(status['can_modify'])
        self.assertEqual(status['issues'][0]['reason'], RUNNING_REASON)
        self.assertTrue(status['issues'][0]['blocking'])

    def test_running_with_material_conflicts_keeps_all_issues(self):
        reasons = [RUNNING_REASON, 'Anti-cheat files detected; injection is blocked',
                   'Steam download staging exists for this game',
                   'Managed files changed; ownership needs review before further changes: amd.dll']
        status = installation_status(self.game(compatibility='blocked', reasons=reasons))
        self.assertEqual(status['state'], 'review')
        self.assertTrue(status['running'])
        self.assertEqual([i['reason'] for i in status['issues']], reasons)
        self.assertEqual([i['code'] for i in status['issues']],
                         ['game_running', 'anti_cheat', 'steam_update', 'managed_files_changed'])
        self.assertTrue(all(i['blocking'] for i in status['issues']))
        self.assertIn('Anti-cheat', status['summary'])
        self.assertFalse(status['can_modify'])

    def test_recovery_takes_priority_without_losing_running_or_staging(self):
        status = installation_status(self.game(compatibility='blocked', recovery_available=True,
                                               reasons=[RUNNING_REASON, 'Steam download staging exists for this game']))
        self.assertEqual(status['state'], 'recovery')
        self.assertEqual([i['code'] for i in status['issues']],
                         ['recovery_needed', 'game_running', 'steam_update'])
        self.assertTrue(status['running'])
        self.assertFalse(status['can_modify'])

    def test_running_with_dx12_advice_is_still_running(self):
        status = installation_status(self.game(compatibility='blocked', reasons=[RUNNING_REASON,
            'DX12 is not confirmed by executable imports; confirm the game runs DX12 before installation']))
        self.assertEqual(status['state'], 'running')
        self.assertEqual(status['issues'][1]['code'], 'dx12_unconfirmed')
        self.assertFalse(status['issues'][1]['blocking'])

    def test_process_observation_pauses_changes_without_changing_raw_reasons(self):
        game = self.game(processes=[{'pid': 42}])
        status = installation_status(game)
        self.assertEqual(game['reasons'], [])
        self.assertEqual(status['state'], 'running')
        self.assertFalse(status['can_modify'])
        self.assertEqual(status['issues'][0]['code'], 'game_running')

    def test_unknown_error_keeps_exact_diagnostic_and_generic_step(self):
        reason = 'Unable to inspect /games/example: unexpected filesystem error'
        status = installation_status(self.game(compatibility='blocked', reasons=[reason]))
        self.assertEqual(status['state'], 'review')
        self.assertEqual(status['summary'], reason)
        self.assertEqual(status['issues'][0]['reason'], reason)
        self.assertFalse(any('delete' in step.lower() or 'chmod' in step.lower()
                             for step in status['issues'][0]['steps']))


if __name__ == '__main__':
    unittest.main()
