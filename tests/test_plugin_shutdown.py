"""Owned-process fault injection only; no Decky restart or real game mutation."""
import asyncio
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
from manager import Manager
from status_monitor import StatusMonitor
from operation_lock import operation_lock
import plugin_shutdown


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = Manager(self.tmp.name, Path(self.tmp.name) / 'settings')
        self.monitor = StatusMonitor(self.manager)
        self.logger = Mock()

    async def shutdown(self, **kwargs):
        task = asyncio.create_task(asyncio.sleep(100))
        await plugin_shutdown.shutdown_plugin(self.manager, self.monitor, task, self.logger, **kwargs)
        self.assertTrue(task.cancelled())
        self.assertTrue(self.manager.closing.is_set())
        self.assertTrue(self.manager.cancel.is_set())
        self.assertTrue(self.monitor.closed)

    async def test_idle_shutdown_and_main_entry_close_admission(self):
        spec = importlib.util.spec_from_file_location('shutdown_main_fixture', ROOT / 'main.py')
        backend = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'decky': SimpleNamespace(logger=self.logger)}):
            spec.loader.exec_module(backend)
        plugin = backend.Plugin()
        plugin.manager, plugin.status_monitor = self.manager, self.monitor
        plugin.update_task = asyncio.create_task(asyncio.sleep(100))
        start = time.monotonic()
        await plugin._unload()
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(plugin.updating_plugin)
        plugin.updating_plugin = False  # A previously running update's finally block.
        with self.assertRaisesRegex(ValueError, 'closing'):
            plugin._allow_game_change()
        self.assertTrue(plugin.update_task.cancelled())
        with self.assertRaisesRegex(ValueError, 'closing'):
            self.manager.start_job('prepare', 'nonexistent')

    async def test_slow_monitor_does_not_delay_worker_cancel_or_budget(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.manager.worker = threading.Thread(target=release.wait, daemon=True)
        self.manager.worker.start()
        self.manager.jobs['job'] = dict(id='job', state='running')
        def slow_close(**kwargs):
            self.assertTrue(self.manager.cancel.is_set())
            release.wait(1)
        with patch.object(self.monitor, 'close', side_effect=slow_close):
            start = time.monotonic()
            await self.shutdown(budget=0.12)
            self.assertLess(time.monotonic() - start, 0.5)
        release.set()
        self.manager.worker.join(1)
        self.logger.warning.assert_called()

    async def test_stubborn_owned_compiler_escalates_within_budget(self):
        child = Mock(pid=54321)
        child.poll.return_value = None
        self.manager.process = child
        signals = []
        def killpg(pid, sig):
            signals.append((pid, sig))
            if sig == signal.SIGKILL:
                child.poll.return_value = -9
        with patch.object(signal, 'SIGKILL', 9, create=True), \
                patch.object(plugin_shutdown.os, 'name', 'posix'), \
                patch.object(plugin_shutdown.os, 'getpgid', return_value=child.pid, create=True), \
                patch.object(plugin_shutdown.os, 'getsid', return_value=child.pid, create=True), \
                patch.object(plugin_shutdown.os, 'killpg', side_effect=killpg, create=True):
            await self.shutdown(budget=0.2, grace=0.02)
        self.assertEqual(signals, [(child.pid, signal.SIGTERM), (child.pid, 9)])

    async def test_active_transaction_files_and_lock_are_retained(self):
        journal = Path(self.tmp.name) / 'journal.json'
        game = Path(self.tmp.name) / 'game.dll'
        journal.write_bytes(b'{"state":"prepared"}')
        game.write_bytes(b'original-game')
        self.manager.transaction = ('root', 'tx', journal)
        release, ready = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        companion = Path(self.tmp.name) / 'companion'
        def transaction():
            with operation_lock(companion):
                ready.set()
                release.wait(2)
        self.manager.worker = threading.Thread(target=transaction, daemon=True)
        self.manager.worker.start()
        self.assertTrue(ready.wait(1))
        await self.shutdown(budget=0.08)
        self.assertEqual(journal.read_bytes(), b'{"state":"prepared"}')
        self.assertEqual(game.read_bytes(), b'original-game')
        self.assertEqual(self.manager.transaction, ('root', 'tx', journal))
        with self.assertRaisesRegex(ValueError, 'Another HelixSR manager'):
            with operation_lock(companion):
                self.fail('Active transaction lock was released by shutdown')
        release.set()
        self.manager.worker.join(1)

    async def test_preparation_released_after_unload_cannot_spawn(self):
        ready, release = threading.Event(), threading.Event()
        errors = []
        def delayed_preparation():
            ready.set()
            release.wait(1)
            try:
                self.manager._spawn_compiler(['bash', 'owned-build'], start_new_session=True)
            except ValueError as exc:
                errors.append(str(exc))
        self.manager.worker = threading.Thread(target=delayed_preparation, daemon=True)
        self.manager.worker.start()
        self.assertTrue(ready.wait(1))
        with patch('manager.subprocess.Popen') as popen:
            await self.shutdown(budget=0.08)
            release.set()
            self.manager.worker.join(1)
            popen.assert_not_called()
        self.assertEqual(errors, ['Cancelled before compiler startup'])

    async def test_default_budget_returns_before_loader_five_second_kill(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.manager.worker = threading.Thread(target=release.wait, daemon=True)
        self.manager.worker.start()
        start = time.monotonic()
        await self.shutdown()
        self.assertLess(time.monotonic() - start, 4.8)
        release.set()
        self.manager.worker.join(1)


class OwnedProcessTests(unittest.TestCase):
    def test_non_session_or_exited_handle_is_never_signalled(self):
        child = Mock(pid=54321)
        child.poll.return_value = None
        with patch.object(plugin_shutdown.os, 'name', 'posix'), \
                patch.object(plugin_shutdown.os, 'getpgid', return_value=123, create=True), \
                patch.object(plugin_shutdown.os, 'getsid', return_value=123, create=True), \
                patch.object(plugin_shutdown.os, 'killpg', create=True) as kill:
            self.assertFalse(plugin_shutdown.signal_compiler(child, signal.SIGTERM))
            child.poll.return_value = 0
            self.assertFalse(plugin_shutdown.signal_compiler(child, signal.SIGTERM))
            kill.assert_not_called()

    def test_shutdown_during_popen_kills_only_new_owned_session(self):
        with tempfile.TemporaryDirectory() as root:
            manager = Manager(root, Path(root) / 'settings')
            child = Mock(pid=54321)
            child.poll.return_value = None
            def create(*args, **kwargs):
                manager.request_shutdown()
                return child
            with patch.object(signal, 'SIGKILL', 9, create=True), \
                    patch('manager.subprocess.Popen', side_effect=create), \
                    patch('manager.os.killpg', create=True) as kill:
                self.assertIs(manager._spawn_compiler(['bash', 'owned-build'], start_new_session=True), child)
                kill.assert_called_once_with(child.pid, signal.SIGKILL)

    @unittest.skipUnless(os.name == 'posix', 'Real session ownership requires Linux')
    def test_real_owned_process_group_ignores_term_then_is_killed(self):
        child = subprocess.Popen([sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'],
            start_new_session=True, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertTrue(plugin_shutdown.signal_compiler(child, signal.SIGTERM))
            self.assertIsNone(child.poll())
            self.assertTrue(plugin_shutdown.signal_compiler(child, signal.SIGKILL))
            child.wait(timeout=2)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            child.stdout.close()


if __name__ == '__main__':
    unittest.main()
