import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.backend import DesktopBackend
from test_backend import pe


class DesktopBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.settings = self.home / 'desktop-config'

    def service(self):
        backend = DesktopBackend(self.home, self.settings)
        self.addCleanup(backend.close)
        return backend

    def test_xdg_settings_are_separate_from_decky(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / 'xdg')}):
            backend = DesktopBackend(self.home)
            self.addCleanup(backend.close)
        self.assertEqual(backend.settings, self.home / 'xdg' / 'helixsr-desktop')

    def test_corrupt_settings_preserved_and_library_usable(self):
        self.settings.mkdir()
        (self.settings / 'settings.json').write_text('{broken')
        backend = self.service()
        self.assertEqual(len(list(self.settings.glob('settings.json.corrupt-*'))), 1)
        self.assertIn('preserved', backend.library()['warnings'][0])
        self.assertEqual(backend.manager.cfg['imports'], [])

    def test_invalid_structures_recovered(self):
        self.settings.mkdir()
        (self.settings / 'settings.json').write_text(json.dumps({'imports': ['invalid']}))
        self.assertEqual(self.service().manager.cfg['imports'], [])

    def test_malformed_packages_quarantined_actual_scan_and_selection_work(self):
        self.settings.mkdir()
        game = self.home / 'Game'
        game.mkdir()
        (game / 'Game.exe').write_bytes(pe(dx12=True))
        (game / 'amd_fidelityfx_upscaler_dx12.dll').write_bytes(pe(ffx=True))
        prepared = self.home / 'prepared'
        prepared.mkdir()
        (prepared / 'amd_fidelityfx_dx12.dll').write_bytes(pe(ffx=True, helix=True))
        good = dict(path=str(prepared), version='1.2.3', prepared_at=1,
                    files={'amd_fidelityfx_dx12.dll': 'a' * 64}, release_sha256='b' * 64)
        bad_values = [dict(prepared_at='broken'), dict(prepared_at=True),
            dict(prepared_at=float('inf')), dict(prepared_at=-1),
            dict(files=[]), dict(files={}), dict(files={'../escape.dll': 'a' * 64}),
            dict(files={'/absolute.dll': 'a' * 64}), dict(files={'a\\b.dll': 'a' * 64}),
            dict(files={'./a.dll': 'a' * 64}), dict(files={'a.dll': 'broken'}),
            dict(version='1.2.3-beta'), dict(release_sha256='broken')]
        packages = {'good': good}
        for index, bad in enumerate(bad_values):
            packages[f'bad-{index}'] = dict(good, **bad)
        original = json.dumps(dict(imports=[dict(folder=str(game), name='Game')], packages=packages))
        (self.settings / 'settings.json').write_text(original)
        backend = self.service()
        with patch('manager.active_processes', return_value=[]):
            library = backend.library()
        self.assertEqual(len(library['games']), 1)
        self.assertEqual(backend.manager.cfg['packages'], {'good': good})
        self.assertEqual(backend.manager.package(backend.manager.get_game(library['games'][0]['id']))[2], good)
        self.assertTrue(any('Invalid prepared' in item for item in library['warnings']))
        backup = next(self.settings.glob('settings.json.corrupt-*'))
        self.assertEqual(backup.read_text(), original)
        saved = json.loads((self.settings / 'settings.json').read_text())
        self.assertEqual(saved['packages'], {'good': good})
        self.assertEqual(saved['imports'][0]['folder'], str(game))

    def test_root_game_writes_refused_before_manager(self):
        backend = self.service()
        with patch('desktop.backend.os.geteuid', return_value=0, create=True), \
                patch.object(backend.manager, 'execute') as execute:
            with self.assertRaisesRegex(ValueError, 'normal user'):
                backend.apply_action('review-token')
            execute.assert_not_called()

    def test_manager_owns_preview_and_execution(self):
        backend = self.service()
        with patch.object(backend.manager, 'preview', return_value={'token': 'x'}) as preview:
            self.assertEqual(backend.preview_action('game', 'disable'), {'token': 'x'})
            preview.assert_called_once_with('game', 'disable', False)
        with patch('desktop.backend.os.geteuid', return_value=1000, create=True), \
                patch.object(backend.manager, 'execute', return_value={'message': 'disabled'}) as execute:
            self.assertEqual(backend.apply_action('x')['message'], 'disabled')
            execute.assert_called_once_with('x')

    def test_jobs_do_not_wait_for_service_lock(self):
        backend = self.service()
        backend.manager.jobs['x'] = {'id': 'x', 'state': 'running', 'result': {'value': 1}}
        result = []
        with backend.lock:
            reader = threading.Thread(target=lambda: result.extend(backend.jobs()))
            reader.start()
            reader.join(1)
            self.assertFalse(reader.is_alive())
        result[0]['result']['value'] = 2
        self.assertEqual(backend.manager.jobs['x']['result']['value'], 1)

    def test_close_cancels_without_deleting_records(self):
        backend = self.service()
        record = self.home / 'install.json'
        record.write_text('retain')
        backend.manager.jobs['x'] = {'id': 'x', 'state': 'running'}
        with patch.object(backend.manager, 'cancel_job') as cancel:
            self.assertTrue(backend.close())
            cancel.assert_called_once_with('x')
        self.assertEqual(record.read_text(), 'retain')
        with self.assertRaisesRegex(ValueError, 'closed'):
            backend.library()


if __name__ == '__main__':
    unittest.main()
