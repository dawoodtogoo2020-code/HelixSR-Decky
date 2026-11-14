"""Red Dead Redemption 2 loads Scaler as winmm.dll. Synthetic files do not prove game runtime."""
import json
import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import game_guidance
import manager
import scaler_proxy
from optiscaler_setup import override_status

from unittest.mock import patch

import helix20_release
import modern_release

try:
    from . import test_helix20_install as helix20_fixtures
    from .test_backend import Fixtures, pe, write
except ImportError:
    import test_helix20_install as helix20_fixtures
    from test_backend import Fixtures, pe, write

RDR2 = '1174180'
LAUNCH = 'WINEDLLOVERRIDES="winmm=n,b" SteamDeck=0 %command%'


class ScalerProxyNameTests(unittest.TestCase):
    def test_rdr2_uses_winmm_and_other_games_keep_dxgi(self):
        rdr2 = dict(source='Steam', appid=RDR2)
        self.assertEqual(scaler_proxy.for_game(rdr2), 'winmm.dll')
        self.assertEqual(scaler_proxy.for_game(dict(source='Steam', appid='292030')), 'dxgi.dll')
        # Only a Steam app ID identifies the game; an imported folder keeps the default.
        self.assertEqual(scaler_proxy.for_game(dict(source='Imported', appid=RDR2)), 'dxgi.dll')

    def test_existing_installs_keep_their_recorded_name(self):
        rdr2 = dict(source='Steam', appid=RDR2)
        self.assertEqual(scaler_proxy.chosen(rdr2, {'route': 'optiscaler'}), 'dxgi.dll', 'records before 0.1.48 used dxgi.dll')
        self.assertEqual(scaler_proxy.chosen(rdr2, {'route': 'optiscaler', 'proxy': 'winmm.dll'}), 'winmm.dll')
        self.assertEqual(scaler_proxy.chosen(rdr2, {}), 'winmm.dll', 'a new install uses the game name')
        with self.assertRaisesRegex(ValueError, 'unknown Scaler proxy'):
            scaler_proxy.recorded({'proxy': '../dxgi.dll'})

    def test_remap_renames_only_optiscaler(self):
        pairs = (('helixsr-scaler/OptiScaler.dll', 'dxgi.dll'), ('helixsr-scaler/fakenvapi.dll', 'fakenvapi.dll'))
        self.assertEqual(scaler_proxy.remap(pairs, 'winmm.dll'),
                         (('helixsr-scaler/OptiScaler.dll', 'winmm.dll'), ('helixsr-scaler/fakenvapi.dll', 'fakenvapi.dll')))
        self.assertEqual(scaler_proxy.remap(pairs, 'dxgi.dll'), pairs)

    def test_status_names_launch_option_and_tester_warnings(self):
        rdr2 = dict(source='Steam', appid=RDR2)
        status = scaler_proxy.status(rdr2, {})
        self.assertEqual((status['file'], status['dll'], status['env'], status['mismatch']), ('winmm.dll', 'winmm', ['SteamDeck=0'], False))
        self.assertIn('Select DirectX 12 in the game before applying this launch option.', status['warnings'])
        self.assertIn('Only apply this override if you know what you are doing.', status['warnings'])
        self.assertFalse(status['tested'])
        old = scaler_proxy.status(rdr2, {'route': 'optiscaler'})
        self.assertEqual((old['file'], old['needed'], old['mismatch'], old['env']), ('dxgi.dll', 'winmm.dll', True, []))

    def test_launch_override_status_checks_winmm_and_steamdeck(self):
        env = ('SteamDeck=0',)
        self.assertEqual(override_status(LAUNCH, 'winmm', env), 'correct')
        self.assertEqual(override_status('WINEDLLOVERRIDES="winmm=n,b" %command%', 'winmm', env), 'incomplete')
        # After %command% the assignment is a game argument, not the game's environment.
        self.assertEqual(override_status('WINEDLLOVERRIDES="winmm=n,b" %command% SteamDeck=0', 'winmm', env), 'incomplete')
        self.assertEqual(override_status('WINEDLLOVERRIDES="winmm=n,b SteamDeck=0" %command%', 'winmm', env), 'conflict')
        self.assertEqual(override_status('WINEDLLOVERRIDES="dxgi=n,b" %command%', 'winmm', env), 'missing')
        self.assertEqual(override_status('WINEDLLOVERRIDES="dxgi=n,b" %command%'), 'correct')


class Rdr2ScalerInstallTests(Fixtures):
    def setUp(self):
        super().setUp()
        # As in test_helix20_install: generated-output verification is covered by the release adapter tests.
        self.enterContext(patch.object(helix20_release, 'verify_outputs', return_value=None))
        self.enterContext(patch.object(modern_release, 'verify_outputs', return_value=None))

    def scaler_game(self):
        helix20_fixtures.Helix20InstallTests.scaler_game(self)

    def modern20_package(self):
        return helix20_fixtures.Helix20InstallTests.modern20_package(self)

    def rdr2(self):
        self.game.update(source='Steam', appid=RDR2, name='Red Dead Redemption 2')
        self.scaler_game()
        self.modern20_package()

    def files(self):
        return {p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()}

    def test_fresh_install_loads_scaler_as_winmm_through_its_lifecycle(self):
        self.rdr2()
        data = self.m.assess(self.game)
        self.assertEqual(data['scaler_proxy']['file'], 'winmm.dll')
        preview = self.m.preview(self.game['id'], 'install')
        self.assertIn('winmm.dll', preview['files'])
        self.assertNotIn('dxgi.dll', preview['files'])
        self.m.execute(preview['token'])

        rec = self.m.record(self.game)
        self.assertEqual((rec['route'], rec['proxy']), ('optiscaler', 'winmm.dll'))
        package = Path(next(iter(self.m.cfg['packages'])))
        self.assertEqual(manager.sha(self.root / 'winmm.dll'), manager.sha(package / 'helixsr-scaler/OptiScaler.dll'))
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertTrue(self.m.matches_installed_payload(self.game, rec, self.m.cfg['packages'][str(package)]))

        installed = self.m.assess(self.game)
        self.assertEqual(installed['compatibility'], 'candidate', installed['reasons'])
        self.assertEqual(installed['optiscaler']['setup']['missing'], [])
        self.assertTrue(any('winmm launch override: missing' in check for check in installed['optiscaler']['setup']['checks']))
        self.assertEqual(installed['setup_guidance']['action'], 'launch')
        self.assertIn('WINEDLLOVERRIDES="winmm=n,b" and SteamDeck=0', installed['setup_guidance']['steps'][0])

        self.game['launch_options'] = LAUNCH
        ready = self.m.assess(self.game)
        self.assertEqual(ready['optiscaler']['setup']['override'], 'correct')
        self.assertEqual(ready['setup_guidance']['action'], 'play')

        # Repair restores the same file name from the recorded package.
        (self.root / 'winmm.dll').unlink()
        broken = self.m.assess(self.game)
        self.assertEqual(broken['repair_files'], ['winmm.dll'])
        self.m.execute(self.m.preview(self.game['id'], 'repair')['token'])
        self.assertEqual(manager.sha(self.root / 'winmm.dll'), manager.sha(package / 'helixsr-scaler/OptiScaler.dll'))

        self.action('disable')
        self.assertFalse((self.root / 'winmm.dll').exists())
        self.action('enable')
        self.assertTrue((self.root / 'winmm.dll').is_file())
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.action('update')
        self.assertEqual(self.m.record(self.game)['proxy'], 'winmm.dll')
        self.action('remove')
        self.assertEqual(self.files(), {'nvngx_dlss.dll', 'Example.exe'})

    def test_winmm_copied_in_by_hand_blocks_install_and_is_kept(self):
        self.rdr2()
        manual = write(self.root / 'winmm.dll', pe() + b'OptiScaler copied in by hand')
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        self.assertTrue(any('winmm.dll' in reason for reason in data['reasons']))
        self.assertTrue(any('delete it before installing' in note for note in data['setup_guidance']['notes']))
        with self.assertRaisesRegex(ValueError, 'Existing unmanaged injector'):
            self.m.preview(self.game['id'], 'install')
        self.assertEqual(manual.read_bytes(), pe() + b'OptiScaler copied in by hand')
        self.assertFalse(self.m.record(self.game))

    def test_existing_dxgi_install_keeps_dxgi_and_explains_how_to_switch(self):
        self.scaler_game()
        self.modern20_package()
        self.action('install')  # installed before the game was identified, as 0.1.47 did for RDR2
        self.game.update(source='Steam', appid=RDR2, name='Red Dead Redemption 2')
        self.assertNotIn('proxy', self.m.record(self.game))
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'candidate', data['reasons'])
        self.assertEqual((data['scaler_proxy']['file'], data['scaler_proxy']['mismatch']), ('dxgi.dll', True))
        self.assertTrue(any('Remove and restore originals' in note for note in data['setup_guidance']['notes']))
        self.action('update')
        self.assertTrue((self.root / 'dxgi.dll').is_file())
        self.assertFalse((self.root / 'winmm.dll').exists())
        self.action('remove')
        self.action('install')
        self.assertEqual(self.m.record(self.game)['proxy'], 'winmm.dll')
        self.assertTrue((self.root / 'winmm.dll').is_file())
        self.assertFalse((self.root / 'dxgi.dll').exists())

    def test_other_games_still_install_dxgi_without_a_proxy_field(self):
        self.game.update(source='Steam', appid='292030', name='The Witcher 3')
        self.scaler_game()
        self.modern20_package()
        self.action('install')
        self.assertTrue((self.root / 'dxgi.dll').is_file())
        self.assertFalse((self.root / 'winmm.dll').exists())
        self.assertNotIn('proxy', self.m.record(self.game))
        self.assertEqual(self.m.assess(self.game)['scaler_proxy']['env'], [])

    def test_reset_after_a_game_update_removes_winmm(self):
        self.rdr2()
        self.game['build'] = '100'
        self.action('install')
        self.game['build'] = '101'
        data = self.m.assess(self.game)
        self.assertTrue(data['reset_eligible'], data['reset_reason'])
        review = self.m.preview(self.game['id'], 'reset')
        self.assertIn('winmm.dll', review['files'])
        self.m.execute(review['token'])
        self.assertEqual(self.files(), {'nvngx_dlss.dll', 'Example.exe'})
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'candidate')

    def test_unknown_recorded_proxy_blocks_file_changes(self):
        self.rdr2()
        self.action('install')
        path = self.m.record_path(self.game)
        rec = json.loads(path.read_text())
        rec['proxy'] = 'version.dll'
        path.write_text(json.dumps(rec))
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        self.assertTrue(any('unknown Scaler proxy' in reason for reason in data['reasons']))
        self.assertTrue((self.root / 'winmm.dll').is_file())


class GuidanceTests(unittest.TestCase):
    def test_launch_step_names_winmm_and_steamdeck(self):
        game = dict(source='Steam', appid=RDR2, route='optiscaler', compatibility='candidate', managed=True, enabled=True,
                    installation_status={'can_modify': True}, optiscaler={'setup': {'override': 'missing'}})
        game['scaler_proxy'] = scaler_proxy.status(game, {'proxy': 'winmm.dll'})
        result = game_guidance.setup_guidance(game)
        self.assertIn('Only apply this override if you know what you are doing.', result['notes'][0])
        self.assertIn('not been checked on a Steam Deck', result['notes'][0])
        self.assertIn('select DirectX 12 in the game first', result['steps'][0])


if __name__ == '__main__':
    unittest.main()
