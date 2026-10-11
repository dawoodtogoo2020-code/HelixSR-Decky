"""Monitor state, stale health, and owned-controller cleanup."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import status_monitor


class DormantThread:
    def __init__(self, *args, **kwargs):
        self.started = False

    def start(self):
        self.started = True

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


class ManagerStub:
    def __init__(self, root):
        self.home = root
        self.root = Path(root)
        self.game = dict(folder=str(root), target=str(root), targets=[], main_exe='game.exe',
                         managed=True, enabled=True, route='direct', name='Game')
        self.calls = []

    def get_game(self, gid):
        self.calls.append(('get', gid))
        if gid != 'game':
            raise ValueError('Game disappeared')
        return self.game

    def assess_safe(self, game, executable=None):
        self.calls.append(('assess', executable))
        return game

    def record_path(self, game):
        return self.root / 'record.json'


class StatusMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ManagerStub(self.tmp.name)
        self.monitor = status_monitor.StatusMonitor(self.manager)

    def test_boolean_and_game_id_validation(self):
        with self.assertRaisesRegex(ValueError, 'boolean'):
            self.monitor.configure('game', 1)
        with self.assertRaisesRegex(ValueError, 'Select a game'):
            self.monitor.configure(None, True)
        self.assertEqual(self.manager.calls, [])
        self.assertFalse(self.monitor.status()['enabled'])

    def test_cached_status_and_stale_override_do_not_mutate_source(self):
        with self.monitor.lock:
            self.monitor.value = dict(enabled=True, game_id='game', _sampled=time.monotonic(),
                runtime=dict(state='output', label='Neural output reported this session'),
                overlay=dict(state='mapped', responding=True, visible_verified=False))
        fresh = self.monitor.status()
        self.assertEqual(fresh['runtime']['state'], 'output')
        fresh['runtime']['state'] = 'tampered'
        self.assertEqual(self.monitor.status()['runtime']['state'], 'output')
        with self.monitor.lock:
            self.monitor.value['_sampled'] = time.monotonic() - 7
        stale = self.monitor.status()
        self.assertEqual(stale['runtime']['state'], 'unavailable')
        self.assertEqual(stale['overlay']['state'], 'stale')
        self.assertFalse(stale['overlay']['responding'])
        self.assertEqual(self.monitor.value['runtime']['state'], 'output')
        self.assertNotIn('_sampled', stale)

    def test_non_linux_configure_keeps_sampler_and_reports_overlay_limit(self):
        with patch.object(status_monitor.platform, 'system', return_value='Windows'), \
             patch.object(status_monitor.threading, 'Thread', DormantThread):
            value = self.monitor.configure('game', True)
            self.assertTrue(value['enabled'])
            self.assertEqual(value['game_id'], 'game')
            self.assertEqual(value['overlay']['state'], 'unavailable')
            self.assertFalse(value['overlay']['visible_verified'])
            self.assertEqual(self.monitor.configure('game', False)['overlay']['state'], 'disabled')
        self.assertEqual(self.manager.calls, [('get', 'game'), ('assess', None)])

    def test_child_outage_replaces_previous_healthy_overlay(self):
        child = Mock()
        child.poll.return_value = 1
        self.monitor.child = child
        self.monitor.directory = Path(self.tmp.name)
        self.monitor.nonce = 'owned-session'
        with self.monitor.lock:
            self.monitor.value['overlay'] = dict(state='mapped', responding=True, visible_verified=False)
        with patch('overlay_helper.read_private', side_effect=FileNotFoundError):
            self.monitor._health(1)
        value = self.monitor.status()['overlay']
        self.assertEqual(value['state'], 'unavailable')
        self.assertFalse(value['responding'])
        self.monitor.child = None
        self.monitor.directory = None

    def test_close_is_idempotent_and_cleans_only_owned_files_and_child(self):
        directory = Path(self.tmp.name) / 'session'
        directory.mkdir()
        for name in ('frame.json', 'ack.json', 'frame.tmp', 'ack.tmp'):
            (directory / name).write_text('{}')
        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = 0
        self.monitor.child = child
        self.monitor.directory = directory
        self.monitor.close()
        self.assertFalse(directory.exists())
        child.terminate.assert_called_once()
        self.monitor.close()
        child.terminate.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'closed'):
            self.monitor.configure('game', True)

    def test_hung_sampler_still_terminates_owned_hud_before_retry(self):
        thread = Mock()
        thread.is_alive.return_value = True
        child = Mock()
        child.poll.return_value = None
        self.monitor.thread = thread
        self.monitor.child = child
        with self.assertRaisesRegex(ValueError, 'still stopping'):
            self.monitor.close()
        child.terminate.assert_called_once()
        self.assertIsNone(self.monitor.child)
        thread.is_alive.return_value = False
        self.monitor.close()

    def test_living_helper_without_ack_has_finite_startup_deadline(self):
        child = Mock()
        child.poll.return_value = None
        self.monitor.child = child
        self.monitor.directory = Path(self.tmp.name)
        self.monitor.nonce = 'owned-session'
        self.monitor.started_at = time.monotonic() - 5
        with patch('overlay_helper.read_private', side_effect=FileNotFoundError):
            self.monitor._health(1)
        self.assertEqual(self.monitor.status()['overlay']['state'], 'unavailable')
        child.terminate.assert_called_once()
        self.monitor.child = None
        self.monitor.directory = None


if __name__ == '__main__':
    unittest.main()
