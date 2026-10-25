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

    def test_missing_owned_file_explanation_does_not_suggest_admin_access(self):
        reason = 'Managed files changed; ownership needs review before further changes: dxgi.dll (current state: missing)'
        status = installation_status(self.game(compatibility='blocked', managed=True, enabled=True, reasons=[reason]))
        self.assertEqual(status['issues'][0]['title'], 'Installed file missing')
        self.assertFalse(status['can_modify'])
        self.assertIn('not a game ownership or administrator check', status['issues'][0]['steps'][0])

    def test_safe_missing_file_repair_explains_steam_verify_and_exposes_action(self):
        reason = 'Managed files changed; ownership needs review before further changes: plugin.dll (current state: missing)'
        status = installation_status(self.game(compatibility='blocked', managed=True, enabled=True,
            repair_eligible=True, repair_files=['plugin.dll'], reasons=[reason]))
        self.assertTrue(status['can_repair'])
        self.assertEqual(status['issues'][0]['code'], 'managed_files_missing')
        steps = '\n'.join(status['issues'][0]['steps'])
        self.assertIn('Steam verification checks files owned by the game', steps)
        self.assertIn('exact checksum-verified package', steps)

    def test_steam_build_review_shows_ids_and_relative_file_states_without_unblocking(self):
        reason = 'Steam build changed; installation needs review'
        report = dict(recorded_build='123456', current_build='789012', files=[
            dict(path='amd_fidelityfx_dx12.dll', state='installed bytes match'),
            dict(path='HelixSR/helixsr.log', state='saved-original bytes match'),
            dict(path='HelixSR/config.ini', state='retained configuration'),
            dict(path='other.dll', state='externally changed'),
            dict(path='missing.dll', state='missing'),
        ], omitted_files=2)
        reasons = [reason, 'Steam download staging exists for this game', RUNNING_REASON]
        game = self.game(compatibility='blocked', managed=True, enabled=True,
                         reasons=reasons, steam_build_review=report)
        status = installation_status(game)
        self.assertEqual(status['state'], 'review')
        self.assertFalse(status['can_modify'])
        self.assertTrue(status['selectable'])
        self.assertEqual(game['reasons'], reasons)
        self.assertEqual([issue['code'] for issue in status['issues']],
                         ['steam_build_changed', 'steam_update', 'game_running'])
        self.assertTrue(all(issue['blocking'] for issue in status['issues']))
        self.assertEqual(status['issues'][0]['reason'], reason)
        steps = '\n'.join(status['issues'][0]['steps'])
        self.assertIn('Recorded Steam build: 123456; current Steam build: 789012', steps)
        for entry in report['files']:
            self.assertIn(entry['path'], steps)
            self.assertIn(entry['state'], steps)
        self.assertIn('2 more recorded files omitted', steps)
        for phrase in ('Remove would restore saved originals', 'Steam file verification',
                       'does not reconcile', 'game_build', 'installation receipts',
                       'close the game normally', 'refresh'):
            self.assertIn(phrase, steps)

    def test_steam_build_review_missing_or_untrusted_details_never_claims_clear(self):
        reason = 'Steam build changed; installation needs review'
        for report in (None, {}, dict(recorded_build='123', current_build='456', files=[
                dict(path='/home/deck/private.dll', state='missing'),
                dict(path='..\\private.dll', state='missing'),
                dict(path='C:\\private.dll', state='missing')])):
            with self.subTest(report=report):
                game = self.game(compatibility='blocked', managed=True, reasons=[reason])
                if report is not None:
                    game['steam_build_review'] = report
                status = installation_status(game)
                self.assertEqual(status['state'], 'review')
                self.assertFalse(status['can_modify'])
                steps = '\n'.join(status['issues'][0]['steps'])
                self.assertIn('file changes stay blocked', steps)
                self.assertIn('does not reconcile', steps)
                self.assertNotIn('private.dll', steps)
                if report in (None, {}):
                    self.assertNotIn('Recorded Steam build:', steps)


if __name__ == '__main__':
    unittest.main()
