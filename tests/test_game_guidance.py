"""Onboarding guidance cannot grant compatibility or claim runtime success."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from game_guidance import setup_guidance, DD2_GUIDE


class GameGuidanceTests(unittest.TestCase):
    def game(self, **changes):
        return dict(dict(compatibility='candidate', route='optiscaler', managed=False,
                         enabled=False, source='Steam', appid='2054970', name="Dragon's Dogma 2"), **changes)

    def test_fresh_game_has_install_instruction_not_unexplained_disabled_status(self):
        value = setup_guidance(self.game())
        self.assertEqual(value['action'], 'install')
        self.assertIn('not installed', value['headline'])
        self.assertIn('confirm the file changes', value['steps'][0])

    def test_dd2_prerequisite_is_advisory_not_a_compatibility_override(self):
        game = self.game()
        value = setup_guidance(game)
        self.assertIn('REFramework', value['notes'][0])
        self.assertIn('does not install or verify', value['notes'][0])
        self.assertIn('not a verified Steam Deck', value['notes'][0])
        self.assertEqual(value['links'][0]['url'], DD2_GUIDE)
        self.assertEqual(game['compatibility'], 'candidate')
        self.assertNotIn('setup_guidance', game)

    def test_direct_route_and_other_titles_do_not_inherit_dd2_dependency(self):
        for game in (self.game(route='direct'), self.game(appid='123'), self.game(source='Imported', name='Other game', main_exe='/game/dd2.exe')):
            self.assertEqual(setup_guidance(game)['notes'], [])

    def test_exact_imported_title_and_executable_can_show_advisory(self):
        game = self.game(source='Imported', appid=None, main_exe='/games/DD2/DD2.exe')
        self.assertTrue(setup_guidance(game)['notes'])
        self.assertFalse(setup_guidance(dict(game, main_exe='/games/DD2/other.exe'))['notes'])

    def test_missing_and_ambiguous_override_need_launch_setup_not_enabled_claim(self):
        for override in ('missing', 'unknown', 'conflict'):
            game = self.game(managed=True, enabled=True, optiscaler={'setup': {'override': override}})
            value = setup_guidance(game)
            self.assertEqual(value['action'], 'launch')
            self.assertIn('Finish Proton', value['headline'])
            self.assertIn('not runtime proof', value['steps'][-1])

    def test_correct_override_still_requires_in_game_selection_and_evidence(self):
        value = setup_guidance(self.game(managed=True, enabled=True, optiscaler={'setup': {'override': 'correct'}}))
        self.assertEqual(value['action'], 'play')
        self.assertIn('Check OptiScaler', value['steps'][0])
        self.assertIn('not runtime proof', value['steps'][-1])

    def test_native_route_does_not_require_proxy(self):
        value = setup_guidance(self.game(managed=True, enabled=True, route='direct'))
        self.assertIn('AMD FSR', value['headline'])
        self.assertIn('does not need', value['steps'][0])
        self.assertFalse(value['notes'])

    def test_disabled_install_gets_enable_action_not_reinstallation(self):
        self.assertEqual(setup_guidance(self.game(managed=True))['action'], 'enable')

    def test_blockers_and_incomplete_details_never_show_ready_install_action(self):
        for game in (self.game(compatibility='blocked'), self.game(recovery_available=True), self.game(installation_status={'can_modify': False, 'label': 'Game running'})):
            self.assertEqual(setup_guidance(game)['action'], 'review')
        self.assertEqual(setup_guidance(self.game(awareness_deferred=True))['action'], 'inspect')

    def test_dx12_confirmation_explains_what_toggle_does(self):
        value = setup_guidance(self.game(dx12_confirmation_needed=True))
        self.assertIn('actually runs in DirectX 12', value['steps'][0])
        self.assertIn("plugin's current installation route", value['steps'][0])
        self.assertIn('cannot add DX12', value['steps'][0])
