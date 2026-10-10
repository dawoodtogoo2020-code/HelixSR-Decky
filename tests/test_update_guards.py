"""Mutation exclusion and recovery durability regressions, no installed games."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import manager
from test_backend import Fixtures

spec = importlib.util.spec_from_file_location('plugin_main_fixture', ROOT / 'main.py')
backend = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'decky': SimpleNamespace()}):
    spec.loader.exec_module(backend)


class UpdateGuards(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = backend.Plugin()
        self.plugin.api_lock = asyncio.Lock()
        self.plugin.updating_plugin = False
        self.plugin.plugin_updates = SimpleNamespace(pending=None, prepare=MagicMock(return_value={'ready': True}))
        self.plugin.manager = SimpleNamespace(jobs={}, transaction=None, start_job=MagicMock(),
            execute_latest=MagicMock(), execute=MagicMock())

    async def test_pending_plugin_update_blocks_every_game_mutator(self):
        self.plugin.plugin_updates.pending = Path('verified-update.zip')
        for method, args in [('prepare', ('game',)), ('install_latest', ('token',)),
                             ('apply_action', ('token',)), ('remember_launch_options', ('game', '', 'x'))]:
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'pending Decky'):
                await getattr(self.plugin, method)(*args)
        self.plugin.manager.start_job.assert_not_called()
        self.plugin.manager.execute_latest.assert_not_called()
        self.plugin.manager.execute.assert_not_called()

    async def test_worker_or_transaction_prevents_plugin_update(self):
        for jobs, transaction in [({'id': {'state': 'running'}}, None), ({}, ('active',))]:
            self.plugin.manager.jobs, self.plugin.manager.transaction = jobs, transaction
            with self.assertRaisesRegex(ValueError, 'current HelixSR operation'):
                await self.plugin.prepare_plugin_update()
        self.plugin.plugin_updates.prepare.assert_not_called()

    async def test_update_waits_for_an_inflight_mutation_lock(self):
        await self.plugin.api_lock.acquire()
        task = asyncio.create_task(self.plugin.prepare_plugin_update())
        await asyncio.sleep(0)
        self.plugin.plugin_updates.prepare.assert_not_called()
        self.plugin.api_lock.release()
        self.assertEqual(await task, {'ready': True})
        self.assertFalse(self.plugin.updating_plugin)

    async def test_periodic_check_never_calls_a_thread_lock_on_asyncio_loop(self):
        self.plugin.plugin_updates.check = MagicMock()
        self.plugin.plugin_updates.due = MagicMock(side_effect=AssertionError('event-loop lock'))
        async def end_cycle(_):
            raise asyncio.CancelledError
        with patch.object(backend.asyncio, 'sleep', side_effect=end_cycle):
            with self.assertRaises(asyncio.CancelledError):
                await self.plugin._plugin_update_loop()
        self.plugin.plugin_updates.check.assert_called_once_with()
        self.plugin.plugin_updates.due.assert_not_called()


class RecoveryDurability(Fixtures):
    def test_recovery_bytes_are_verified_and_synced_before_live_mutation(self):
        self.package()
        events = []
        original_copy, original_json, original_install = manager.durable_copy, manager.atomic_json, self.m.install_payload
        def copied(src, dst, expected=None):
            original_copy(src, dst, expected)
            events.append(('copy', str(dst)))
        def journal(path, value):
            if Path(path).name == 'journal.json':
                events.append(('journal', value['state']))
            return original_json(path, value)
        def install(*args):
            events.append(('install', None))
            return original_install(*args)
        with patch.object(manager, 'durable_copy', side_effect=copied), patch.object(manager, 'atomic_json', side_effect=journal), patch.object(self.m, 'install_payload', side_effect=install):
            token = self.m.preview(self.game['id'], 'install')['token']
            self.m.execute(token)
        prepared = events.index(('journal', 'prepared'))
        live = events.index(('install', None))
        snapshots = [i for i, e in enumerate(events) if e[0] == 'copy' and 'snapshot' in e[1]]
        originals = [i for i, e in enumerate(events) if e[0] == 'copy' and 'originals' in e[1]]
        self.assertTrue(snapshots and originals)
        self.assertTrue(all(i < prepared for i in snapshots))
        self.assertTrue(all(i < live for i in originals))

    def test_changed_copy_is_rejected_before_durability_claim(self):
        with patch.object(manager.shutil, 'copy2', side_effect=lambda src, dst: Path(dst).write_bytes(b'changed')):
            with self.assertRaisesRegex(ValueError, 'verification'):
                manager.durable_copy(self.native, self.base / 'recovery' / 'native.dll')

    def test_new_directory_entries_and_file_are_synced(self):
        destination = self.base / 'new' / 'nested' / 'native.dll'
        calls = []
        with patch.object(manager, 'sync_directory', side_effect=lambda p: calls.append(Path(p))), patch.object(manager.os, 'fsync') as fsync:
            manager.durable_copy(self.native, destination)
        self.assertEqual(calls, [self.base, self.base / 'new', destination.parent])
        fsync.assert_called_once()
        self.assertEqual(destination.read_bytes(), self.native.read_bytes())


if __name__ == '__main__':
    unittest.main()
