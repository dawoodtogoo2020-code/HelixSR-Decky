"""Monitor state, stale health, and owned-controller cleanup."""
import os
import sys
import tempfile
import time
import threading
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

    def test_source_child_uses_current_python_and_helper_script(self):
        directory = Path(self.tmp.name) / 'session'
        with patch.object(status_monitor.sys, 'frozen', False, create=True):
            command = status_monitor.child_command(directory, 'nonce', env={'PATH': '/usr/bin'})
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, 'overlay_helper.py')
        self.assertEqual(command[2:], [str(directory), 'nonce'])

    def test_frozen_decky_uses_host_python_and_sanitized_display_environment(self):
        appdir = '/tmp/.mount_helix/usr'
        supplied = dict(DISPLAY=':0', XAUTHORITY='/run/user/1000/xauth',
                        XDG_SESSION_TYPE='wayland', APPDIR=appdir,
                        PATH=os.pathsep.join((appdir + '/bin', '/usr/bin')),
                        LD_LIBRARY_PATH=appdir + '/lib', PYTHONHOME=appdir)
        child = Mock()
        child.poll.return_value = 0
        with patch.object(status_monitor.sys, 'frozen', True, create=True), \
                patch.object(status_monitor.platform, 'system', return_value='Linux'), \
                patch.object(status_monitor, 'display_environment', return_value=supplied), \
                patch.object(status_monitor, 'private_directory', return_value=Path(self.tmp.name)), \
                patch.object(status_monitor.shutil, 'which', return_value='/usr/bin/python3') as which, \
                patch.object(status_monitor.subprocess, 'Popen', return_value=child) as popen, \
                patch.object(status_monitor.threading, 'Thread', DormantThread):
            value = self.monitor.configure('game', True)
            self.assertTrue(value['enabled'])
            command = popen.call_args.args[0]
            env = popen.call_args.kwargs['env']
            self.assertEqual(command[0], '/usr/bin/python3')
            self.assertEqual(Path(command[1]).name, 'overlay_helper.py')
            self.assertEqual(command[2:], [str(self.monitor.directory), self.monitor.nonce])
            self.assertEqual(which.call_args.kwargs['path'], env['PATH'])
            self.assertEqual(env['PATH'], '/usr/bin')
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('LD_LIBRARY_PATH', env)
            self.assertEqual([env[key] for key in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE')],
                             [supplied[key] for key in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE')])
            self.monitor.configure('game', False)

    def test_frozen_desktop_opt_in_uses_own_child_and_environment(self):
        desktop = status_monitor.StatusMonitor(self.manager, frozen_child=True)
        supplied = dict(DISPLAY=':0', XAUTHORITY='/run/user/1000/xauth',
                        XDG_SESSION_TYPE='wayland', PYTHONHOME='/frozen/python')
        child = Mock()
        child.poll.return_value = 0
        with patch.object(status_monitor.sys, 'frozen', True, create=True), \
                patch.object(status_monitor.platform, 'system', return_value='Linux'), \
                patch.object(status_monitor, 'display_environment', return_value=supplied), \
                patch.object(status_monitor, 'private_directory', return_value=Path(self.tmp.name)), \
                patch.object(status_monitor.subprocess, 'Popen', return_value=child) as popen, \
                patch.object(status_monitor.threading, 'Thread', DormantThread):
            self.assertTrue(desktop.configure('game', True)['enabled'])
            self.assertEqual(popen.call_args.args[0],
                             [sys.executable, '--status-overlay-child', str(desktop.directory), desktop.nonce])
            self.assertEqual(popen.call_args.kwargs['env'], supplied)
            desktop.configure('game', False)

    def test_frozen_decky_missing_host_python_keeps_sampler_and_reports_overlay_limit(self):
        supplied = dict(DISPLAY=':0', PATH='/usr/bin')
        with patch.object(status_monitor.sys, 'frozen', True, create=True), \
                patch.object(status_monitor.platform, 'system', return_value='Linux'), \
                patch.object(status_monitor, 'display_environment', return_value=supplied), \
                patch.object(status_monitor, 'private_directory', return_value=Path(self.tmp.name)), \
                patch.object(status_monitor.shutil, 'which', return_value=None), \
                patch.object(status_monitor.subprocess, 'Popen') as popen, \
                patch.object(status_monitor.threading, 'Thread', DormantThread):
            value = self.monitor.configure('game', True)
            self.assertTrue(value['enabled'])
            self.assertEqual(value['game_id'], 'game')
            self.assertEqual(value['overlay']['state'], 'unavailable')
            self.assertIn('Python', value['overlay']['detail'])
            self.assertTrue(self.monitor.thread.started)
            popen.assert_not_called()
            self.monitor.configure('game', False)

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

    def test_close_during_assessment_prevents_late_hud_and_sampler(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def assess(game, **kwargs):
            entered.set()
            release.wait(1)
            return game
        def configure():
            try:
                self.monitor.configure('game', True)
            except ValueError as exc:
                errors.append(str(exc))
        with patch.object(self.manager, 'assess_safe', side_effect=assess), \
                patch.object(status_monitor.subprocess, 'Popen') as popen:
            worker = threading.Thread(target=configure, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(ValueError, 'configuration is still stopping'):
                self.monitor.close(deadline=time.monotonic() + 0.03)
            release.set()
            worker.join(1)
            popen.assert_not_called()
        self.assertEqual(errors, ['The status monitor is closed'])
        self.assertIsNone(self.monitor.thread)
        self.assertTrue(self.monitor.stop.is_set())

    def test_bounded_close_kills_stubborn_hud_before_slow_sampler(self):
        events = []
        child = Mock()
        child.poll.return_value = None
        child.terminate.side_effect = lambda: events.append('term')
        child.wait.side_effect = status_monitor.subprocess.TimeoutExpired('owned-hud', 0.01)
        def killed():
            events.append('kill')
            child.poll.return_value = -9
        child.kill.side_effect = killed
        sampler = Mock()
        sampler.join.side_effect = lambda timeout: events.append('join')
        sampler.is_alive.return_value = True
        self.monitor.child, self.monitor.thread = child, sampler
        with self.assertRaisesRegex(ValueError, 'still stopping'):
            self.monitor.close(deadline=time.monotonic() + 0.1)
        self.assertEqual(events, ['term', 'kill', 'join'])
        self.assertTrue(self.monitor.closed)

    def test_sample_returning_after_close_does_not_publish_or_write_frame(self):
        record = Path(self.tmp.name) / 'record.json'
        evidence = Mock()
        def sampled():
            self.monitor.request_close()
            return dict(state='output')
        evidence.sample.side_effect = sampled
        self.monitor.child = Mock()
        with patch.object(self.monitor, '_frame') as frame:
            self.monitor._loop(evidence, record, None)
            frame.assert_not_called()
        self.assertEqual(self.monitor.status()['runtime']['state'], 'unverified')

    def test_shutdown_arriving_inside_popen_kills_returned_handle(self):
        child = Mock()
        def create(*args, **kwargs):
            self.monitor.request_close()
            return child
        with patch.object(status_monitor.platform, 'system', return_value='Linux'), \
                patch.object(status_monitor, 'private_directory', return_value=Path(self.tmp.name)), \
                patch.object(status_monitor, 'display_environment', return_value={}), \
                patch.object(status_monitor.subprocess, 'Popen', side_effect=create):
            with self.assertRaisesRegex(ValueError, 'closed'):
                self.monitor.configure('game', True)
        child.kill.assert_called_once()
        self.assertIsNone(self.monitor.thread)


if __name__ == '__main__':
    unittest.main()
