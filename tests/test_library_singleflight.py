"""Concurrent RPC clients share the scan even after one client disconnects."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
spec = importlib.util.spec_from_file_location('helix_scan_plugin', ROOT / 'main.py')
plugin_module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'decky': types.SimpleNamespace()}):
    spec.loader.exec_module(plugin_module)


class LibrarySingleflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnected_waiter_does_not_duplicate_or_cancel_scan(self):
        entered, complete = threading.Event(), threading.Event()
        calls = []

        def refresh():
            calls.append(1)
            entered.set()
            if not complete.wait(2):
                raise RuntimeError('Fixture deadline')
            return {'games': ['healthy']}

        plugin = plugin_module.Plugin()
        plugin.api_lock = asyncio.Lock()
        plugin.manager = types.SimpleNamespace(refresh=refresh)
        first = asyncio.create_task(plugin.library())
        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
        second = asyncio.create_task(plugin.library())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        complete.set()
        self.assertEqual(await second, {'games': ['healthy']})
        self.assertEqual(len(calls), 1)

    async def test_failed_scan_can_be_retried(self):
        plugin = plugin_module.Plugin()
        plugin.api_lock = asyncio.Lock()
        with patch.object(types.SimpleNamespace(), 'refresh', create=True,
                          side_effect=[ValueError('bad source'), {'games': []}]) as read:
            plugin.manager = types.SimpleNamespace(refresh=read)
            with self.assertRaisesRegex(ValueError, 'bad source'):
                await plugin.library()
            self.assertEqual(await plugin.library(), {'games': []})
            self.assertEqual(read.call_count, 2)


if __name__ == '__main__':
    unittest.main()
