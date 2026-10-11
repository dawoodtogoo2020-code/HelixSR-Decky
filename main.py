import asyncio
import sys
from pathlib import Path
import decky

sys.path.insert(0, str(Path(__file__).parent / 'py_modules'))
from manager import Manager
from plugin_updates import PluginUpdates
from launch_receipts import LaunchReceipts


class Plugin:
    async def _main(self):
        self.manager = Manager(decky.DECKY_USER_HOME, decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.api_lock = asyncio.Lock()
        self.plugin_updates = PluginUpdates(decky.DECKY_PLUGIN_SETTINGS_DIR, Path(__file__).parent / 'package.json')
        await asyncio.to_thread(self.plugin_updates.cleanup_installed)
        self.update_task = asyncio.create_task(self._plugin_update_loop())
        self.updating_plugin = False
        decky.logger.info('HelixSR Decky loaded without root permissions')

    async def _unload(self):
        self.update_task.cancel()
        try:
            await self.update_task
        except asyncio.CancelledError:
            pass
        for job in list(self.manager.jobs.values()):
            if job['state'] == 'running':
                self.manager.cancel_job(job['id'])
        if self.manager.worker:
            await asyncio.to_thread(self.manager.worker.join, 15)

    async def _uninstall(self):
        # Game payloads and original files are intentionally retained. Remove per game first.
        pass

    async def _plugin_update_loop(self):
        while True:
            try:
                # due() uses the same thread lock as downloads. Keep the whole
                # check off asyncio's loop so RPCs and cancellation stay usable.
                await asyncio.to_thread(self.plugin_updates.check)
            except Exception as exc:
                decky.logger.warning('Plugin update check failed: %s', exc)
            await asyncio.sleep(60)

    def _allow_game_change(self):
        if self.updating_plugin or self.plugin_updates.pending:
            raise ValueError('Finish or cancel the pending Decky plugin update first')

    async def plugin_update_status(self):
        return await asyncio.to_thread(self.plugin_updates.status)

    async def check_plugin_updates(self, force=True):
        return await asyncio.to_thread(self.plugin_updates.check, bool(force))

    async def set_plugin_auto_check(self, enabled):
        return await asyncio.to_thread(self.plugin_updates.set_auto, enabled)

    async def prepare_plugin_update(self):
        async with self.api_lock:
            if any(job['state'] == 'running' for job in self.manager.jobs.values()) or self.manager.transaction:
                raise ValueError('Wait for the current HelixSR operation before updating the plugin')
            self.updating_plugin = True
            try:
                return await asyncio.to_thread(self.plugin_updates.prepare)
            finally:
                self.updating_plugin = False

    async def cancel_plugin_update(self):
        async with self.api_lock:
            return await asyncio.to_thread(self.plugin_updates.cancel)

    async def resume_plugin_update(self):
        async with self.api_lock:
            return await asyncio.to_thread(self.plugin_updates.resume)

    async def library(self):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.refresh)

    async def game_details(self, gid, executable=None):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.assess_safe, self.manager.get_game(gid), executable=executable)

    async def import_game(self, folder, name):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.import_folder, folder, name)

    async def import_folders(self, folders):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.import_folders, folders)

    async def import_launcher(self, launcher):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.import_launcher, launcher)

    async def forget_game(self, gid):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.forget, gid)

    async def check_updates(self, force=True):
        return await asyncio.to_thread(self.manager.check_update, force)

    async def set_license(self, accepted, token=None):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.accept_license, accepted, token)

    async def remember_launch_options(self, gid, before, after):
        async with self.api_lock:
            self._allow_game_change()
            game = self.manager.get_game(gid)
            return await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).remember, before, after)

    async def owned_launch_options(self, gid, actual=None):
        async with self.api_lock:
            if actual is not None:
                self._allow_game_change()
            game = self.manager.get_game(gid)
            return await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).owned, actual)

    async def prepare_launch_options(self, gid, before, after, restore=False):
        async with self.api_lock:
            self._allow_game_change()
            game = self.manager.get_game(gid)
            return await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).prepare, before, after, restore)

    async def finalize_launch_options(self, gid, nonce, actual):
        async with self.api_lock:
            self._allow_game_change()
            game = self.manager.get_game(gid)
            return await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).finalize, nonce, actual)

    async def prepare(self, gid):
        async with self.api_lock:
            self._allow_game_change()
            return self.manager.start_job('prepare', gid)

    async def job_status(self):
        return [dict(x) for x in self.manager.jobs.values()]

    async def cancel_job(self, jid):
        return self.manager.cancel_job(jid)

    async def preview_action(self, gid, action, dx12_confirmed=False, executable=None):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.preview, gid, action, dx12_confirmed, executable)

    async def preview_latest(self, gid, dx12_confirmed=False, variant_id=None, executable=None):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.preview_latest, gid, dx12_confirmed, variant_id, executable)

    async def install_latest(self, token):
        async with self.api_lock:
            self._allow_game_change()
            return self.manager.execute_latest(token)

    async def apply_action(self, token):
        async with self.api_lock:
            self._allow_game_change()
            return await asyncio.to_thread(self.manager.execute, token)
