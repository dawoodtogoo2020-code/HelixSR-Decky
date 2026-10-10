import asyncio
import sys
from pathlib import Path
import decky

sys.path.insert(0, str(Path(__file__).parent / 'py_modules'))
from manager import Manager


class Plugin:
    async def _main(self):
        self.manager = Manager(decky.DECKY_USER_HOME, decky.DECKY_PLUGIN_SETTINGS_DIR)
        self.api_lock = asyncio.Lock()
        decky.logger.info('HelixSR Decky loaded without root permissions')

    async def _unload(self):
        for job in list(self.manager.jobs.values()):
            if job['state'] == 'running':
                self.manager.cancel_job(job['id'])
        if self.manager.worker:
            await asyncio.to_thread(self.manager.worker.join, 15)

    async def _uninstall(self):
        # Game payloads and original files are intentionally retained. Remove per game first.
        pass

    async def library(self):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.refresh)

    async def game_details(self, gid):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.assess_safe, self.manager.get_game(gid))

    async def import_game(self, folder, name):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.import_folder, folder, name)

    async def import_folders(self, folders):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.import_folders, folders)

    async def forget_game(self, gid):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.forget, gid)

    async def check_updates(self, force=True):
        return await asyncio.to_thread(self.manager.check_update, force)

    async def set_license(self, accepted):
        return await asyncio.to_thread(self.manager.accept_license, accepted)

    async def remember_launch_options(self, gid, before, after):
        from manager import atomic_json
        game = self.manager.get_game(gid)
        receipt = self.manager.companion(game) / 'records/launch-options.json'
        if before == after:
            receipt.unlink(missing_ok=True)
            return True
        atomic_json(receipt,
                    {'before': before, 'after': after})
        return True

    async def owned_launch_options(self, gid):
        from manager import load_json
        game = self.manager.get_game(gid)
        return load_json(self.manager.companion(game) / 'records/launch-options.json', None) or None

    async def prepare(self, gid):
        return self.manager.start_job('prepare', gid)

    async def job_status(self):
        return [dict(x) for x in self.manager.jobs.values()]

    async def cancel_job(self, jid):
        return self.manager.cancel_job(jid)

    async def preview_action(self, gid, action, dx12_confirmed=False):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.preview, gid, action, dx12_confirmed)

    async def preview_latest(self, gid, dx12_confirmed=False):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.preview_latest, gid, dx12_confirmed)

    async def install_latest(self, token):
        return self.manager.execute_latest(token)

    async def apply_action(self, token):
        async with self.api_lock:
            return await asyncio.to_thread(self.manager.execute, token)
