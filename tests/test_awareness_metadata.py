"""Optional local metadata must not turn a game refresh into a parser failure."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import awareness


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')
    return path


class AwarenessMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PLUGIN.parent.parent / 'work')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.game = Path(self.tmp.name) / 'games/Example'
        write(self.game / 'Example.exe', 'fixture')
        self.steam = self.home / '.local/share/Steam'

    def test_launch_options_handles_string_midsection_and_reports_warning(self):
        config = write(self.steam / 'userdata/1/config/localconfig.vdf',
                       '"UserLocalConfigStore" "unexpected text"')
        warnings = []
        with patch('awareness.steam_roots', return_value=[self.steam]):
            value = awareness.launch_options(self.home, '42', warnings)
        self.assertEqual(value, '')
        self.assertEqual(warnings, [f'Steam launch options have an invalid VDF structure: {config}'])

    def test_launch_options_retains_valid_vdf_behavior(self):
        write(self.steam / 'userdata/1/config/localconfig.vdf',
              '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { '
              '"42" { "LaunchOptions" "mako --profile deck %command%" } } } } } }')
        warnings = []
        with patch('awareness.steam_roots', return_value=[self.steam]):
            value = awareness.launch_options(self.home, '42', warnings)
        self.assertEqual(value, 'mako --profile deck %command%')
        self.assertFalse(warnings)

    def test_profile_records_rejects_non_list_entries_and_unhashable_names(self):
        warnings = []
        self.assertEqual(awareness.profile_records('profile = "not a list"', warnings, 'MAKO profile data'), [])
        self.assertEqual(warnings, ['MAKO profile data has an invalid profile list'])

        warnings = []
        records = awareness.profile_records(
            '[[profile]]\nname = ["not", "text"]\nmultiplier = 2\n',
            warnings, 'LSFG-VK profile data')
        self.assertEqual(records, [{'multiplier': 2}])
        self.assertEqual(warnings, ['LSFG-VK profile data profile name must be text'])

        warnings = []
        self.assertEqual(awareness.profile_records('profile = [1, "bad"]', warnings, 'LSFG-VK profile data'), [])
        self.assertEqual(warnings, [
            'LSFG-VK profile data has a non-mapping profile entry',
            'LSFG-VK profile data has a non-mapping profile entry',
        ])

    def test_awareness_keeps_unknown_state_when_optional_metadata_is_invalid(self):
        write(self.steam / 'userdata/1/config/localconfig.vdf',
              '"UserLocalConfigStore" "unexpected text"')
        write(self.home / '.config/mako-render/conf.toml', 'profile = "bad"')
        write(self.home / '.config/lsfg-vk/conf.toml', 'profile = [1, "bad"]')
        game = dict(id='steam:42', name='Example', folder=str(self.game), source='Steam', appid='42')
        with patch('awareness.steam_roots', return_value=[self.steam]), \
                patch('awareness.active_processes', return_value=[]):
            result = awareness.awareness(game, [(self.game, ['Example.exe'])], self.home, 'direct', self.game)
        self.assertEqual(result['framegen'], [])
        self.assertEqual(result['framegen_summary'], 'Frame-generation configuration unavailable; state unknown')
        self.assertTrue(any('Steam launch options have an invalid VDF structure' in item
                            for item in result['awareness_warnings']))
        self.assertTrue(any('MAKO profile data has an invalid profile list' in item
                            for item in result['awareness_warnings']))
        self.assertTrue(any('LSFG-VK profile data has a non-mapping profile entry' in item
                            for item in result['awareness_warnings']))

    def test_awareness_keeps_valid_mako_and_lsfg_profile_evidence(self):
        write(self.home / '.config/mako-render/conf.toml',
              '[[profile]]\nname = "deck"\nframe_generation_enabled = true\n')
        write(self.home / '.config/lsfg-vk/conf.toml',
              '[[profile]]\nname = "deck lsfg"\nactive_in = ["Example.exe"]\nmultiplier = 2\n')
        game = dict(id='steam:42', name='Example', folder=str(self.game), source='Steam', appid='42',
                    launch_options='mako --profile deck %command%')
        with patch('awareness.active_processes', return_value=[]):
            result = awareness.awareness(game, [(self.game, ['Example.exe'])], self.home, 'direct', self.game)
        evidence = {(item['source'], item['key']): item['enabled'] for item in result['framegen']}
        self.assertTrue(evidence[('MAKO', 'frame_generation_enabled')])
        self.assertTrue(evidence[('LSFG-VK', 'multiplier')])
        self.assertFalse(result['awareness_warnings'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
