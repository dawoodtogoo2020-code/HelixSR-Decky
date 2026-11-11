"""The local network is built once per device for a release and model.

Synthetic bytes only: these tests prove reuse, copying and progress reporting,
not SteamOS build speed or image quality.
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manager
import model_variants
from test_backend import pe, write
import test_network_preparation as fresh
from test_plugin_updates import FakeResponse

SD = 'microsd-fixture'
CONVERTER = fresh.CONVERTER


class Harness(fresh.FreshPreparationTests):
    """The fresh-build fixture without re-running its own tests."""

    def archive(self, converter=CONVERTER, setup=fresh.SHELL):
        # Zip timestamps change every second: keep one release identity per test.
        cache = self.__dict__.setdefault('_archives', {})
        if (converter, setup) not in cache:
            cache[converter, setup] = super().archive(converter, setup)
        payload, release = cache[converter, setup]
        self.m.cfg['license'] = manager.license_key(release)
        return payload, release


for _name in [n for n in dir(fresh.FreshPreparationTests) if n.startswith('test')]:
    setattr(Harness, _name, None)


def on_sd(path):
    return SD in Path(path).parts


def fake_same_drive(path, game):
    """Treat the fixture's SD folder as a separate filesystem from everything else."""
    return on_sd(path) == on_sd(game['folder'])


class BuildProgressTests(unittest.TestCase):
    def test_upscaling_and_frame_generation_bars_become_short_progress(self):
        log = ('Build runtime: /fixture/wine (wine-9.0)\n'
               '[helixsr-setup] building the network (this can take several minutes)\n'
               '[helixsr-setup] [#########-----------]   45%  3:12  shaders 57/200\n')
        self.assertEqual(manager.build_progress(log), 'upscaling network 45% (shaders 57/200)')
        log += '[helixsr-fg] [####----------------]   20%  0:41  download 80/400 MB\n'
        self.assertEqual(manager.build_progress(log), 'frame generation 20% (download 80/400 MB)')

    def test_step_lines_and_terminal_noise(self):
        log = ("\x1b[0m[helixsr-fg] downloading NVIDIA's driver package 595.71.05 for the NGX core\r\n"
               '  % Total    % Received\r 12  100M   12 12.0M\r')
        self.assertEqual(manager.build_progress(log),
                         "frame generation: downloading NVIDIA's driver package 595.71.05 for the NGX core")

    def test_before_upstream_output_and_empty_log(self):
        self.assertEqual(manager.build_progress('Build runtime: /fixture/wine (wine-9.0)\n'),
                         'preparing build tools')
        self.assertIsNone(manager.build_progress(''))
        self.assertIsNone(manager.build_progress(None))


class OneTimeBuildTests(Harness):
    def setUp(self):
        super().setUp()
        drive = patch.object(manager.Manager, '_same_drive', staticmethod(fake_same_drive))
        drive.start()
        self.addCleanup(drive.stop)
        folder = self.base / SD / 'games' / 'Other'
        write(folder / 'Other.exe', pe(dx12=True))
        self.sd_game = dict(id='fixture:sd', name='Other', folder=str(folder), source='Imported')
        self.m.entries[self.sd_game['id']] = self.sd_game

    def prepare_sd(self):
        """Prepare the SD-card game with the release the internal game used; nothing may download or build."""
        _, release = self.archive()
        job = {'id': 'sd-output'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.urllib.request.urlopen', side_effect=AssertionError('downloaded')) as download, \
                patch('manager.subprocess.Popen', side_effect=AssertionError('built')):
            result = self.m.prepare(self.sd_game, job)
        return result, job, download

    def test_other_drive_package_is_copied_and_verified_without_download_or_build(self):
        (_, internal, internal_record), _ = self.prepare_fixture()
        self.assertIsNone(self.m.package(self.sd_game), 'installs never consume another drive')
        (version, copied, record), job, download = self.prepare_sd()
        download.assert_not_called()
        self.assertEqual(job['message'], manager.COPY_MESSAGE)
        self.assertEqual(version, (1, 8, 0))
        self.assertTrue(on_sd(copied))
        self.assertEqual(copied.parent, self.m.companion(self.sd_game) / 'packages')
        self.assertEqual(record['files'], internal_record['files'])
        self.assertEqual(record['variant'], internal_record['variant'])
        self.assertEqual(self.m.package(self.sd_game)[1], copied)
        self.assertEqual(self.m.package(self.game)[1], internal, 'the source package stays in place')
        self.assertFalse((self.m.companion(self.sd_game) / 'staging' / job['id']).exists())
        # The next SD game reuses the SD copy directly.
        again = {'id': 'sd-again'}
        _, release = self.archive()
        with patch.object(self.m, 'check_update', return_value=release):
            self.assertEqual(self.m.prepare(self.sd_game, again)[1], copied)
        self.assertIn('Reusing', again['message'])

    def corrupting_copy(self, name):
        real = shutil.copyfile

        def copy(source, target, **kwargs):
            result = real(source, target, **kwargs)
            if Path(target).name == name:
                Path(target).write_bytes(b'altered during copy ' * 128)
            return result
        return copy

    def build_sd(self, copy=None):
        payload, release = self.archive()
        job = {'id': 'sd-build'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.https_context', return_value=None), \
                patch('manager.verify_recipe', return_value=dict(id=model_variants.DEFAULT_VARIANT,
                      adapter=model_variants.ADAPTER, recipe_sha256=next(iter(model_variants.REVIEWED_RECIPES)))), \
                patch('manager.urllib.request.urlopen', return_value=FakeResponse(payload, release['url'])) as download, \
                patch('manager.shutil.copyfile', side_effect=copy or shutil.copyfile):
            result = self.m.prepare(self.sd_game, job)
        return result, job, download

    def test_copy_that_fails_verification_falls_back_to_a_local_build(self):
        self.prepare_fixture()
        (_, folder, _), job, download = self.build_sd(self.corrupting_copy(manager.NETWORK[0]))
        download.assert_called_once()
        self.assertTrue(on_sd(folder))
        self.assertIn('Could not reuse the package built on another drive', job['log'])
        self.assertIn('did not match its verified record', job['log'])
        self.assertNotEqual((folder / manager.NETWORK[0]).read_bytes(), b'altered during copy ' * 128)
        self.assertFalse((self.m.companion(self.sd_game) / 'staging' / job['id']).exists())

    def test_record_from_an_older_plugin_falls_back_to_a_local_build(self):
        (_, internal, _), _ = self.prepare_fixture()
        companion = self.m.companion(self.game)
        for name in ('package.json', 'packages-v1.json'):
            (companion / 'records' / name).unlink()
        write(internal / 'older-extra.txt', b'recorded by an older plugin')
        record = self.m.cfg['packages'][str(internal)]
        record['files']['older-extra.txt'] = manager.sha(internal / 'older-extra.txt')
        (_, folder, _), job, download = self.build_sd()
        download.assert_called_once()
        self.assertIn('recorded by an older plugin version', job['log'])
        self.assertTrue(on_sd(folder))

    def test_unverifiable_source_is_never_copied(self):
        (_, internal, _), _ = self.prepare_fixture()
        (internal / manager.NETWORK[0]).write_bytes(b'changed after preparation ' * 128)
        (_, folder, _), job, download = self.build_sd()
        download.assert_called_once()
        self.assertNotIn('Could not reuse', job['log'])
        self.assertTrue(on_sd(folder))

    def test_links_inside_a_package_stop_the_copy(self):
        source = self.base / 'link-package'
        write(source / 'real.bin', b'bytes')
        (source / 'link.bin').symlink_to(source / 'real.bin')
        with self.assertRaisesRegex(ValueError, 'link or special file: link.bin'):
            manager.Manager._package_tree(source)

    def test_hlx_releases_do_not_look_for_copies(self):
        with patch.object(manager.hlx_fsr_release, 'modern', return_value=True), \
                patch.object(self.m, 'other_drive_package') as search, \
                patch.object(self.m, 'release_for_choice', return_value=dict(version='3.2.0', sha256='c' * 64)), \
                patch('manager.select_variant', return_value=dict(id='hlx')), \
                patch('manager.require_model_release'), \
                patch('manager.license_key', return_value='accepted'), \
                patch.object(self.m, 'package', return_value=None), \
                patch.object(self.m, '_download_and_build', side_effect=RuntimeError('fixture build boundary')):
            self.m.cfg['license'] = 'accepted'
            with self.assertRaisesRegex(RuntimeError, 'fixture build boundary'):
                self.m.prepare(self.sd_game, {'id': 'hlx'})
        search.assert_not_called()


class SharedToolsAndProgressTests(Harness):
    def test_every_game_builds_with_the_device_tool_cache(self):
        probe = CONVERTER + "\nimport os\nprint('tools=' + os.environ['XDG_DATA_HOME'])\n"
        _, job = self.prepare_fixture(probe)
        self.assertIn('tools=' + str(self.m.tools), job['log'])
        self.assertEqual(self.m.tools, self.base / 'settings' / 'build-tools')
        self.assertFalse((self.m.companion(self.game) / 'dependencies').exists())

    def test_tool_cache_falls_back_to_the_game_folder_when_space_is_short(self):
        companion = self.m.companion(self.game)
        with patch('manager.shutil.disk_usage', return_value=MagicMock(free=1 << 30)):
            self.assertEqual(self.m.build_tools_home(companion), companion / 'dependencies')
        self.assertEqual(self.m.build_tools_home(companion), self.m.tools)

    def test_job_message_shows_upstream_progress_while_building(self):
        probe = ("import time\n"
                 "print('[helixsr-setup] [##########----------]   50%  0:10  shaders 100/200', flush=True)\n"
                 "time.sleep(1.6)\n" + CONVERTER)
        _, job = self.prepare_fixture(probe)
        self.assertTrue(job['message'].startswith(manager.BUILD_MESSAGE))
        self.assertIn('Progress: upscaling network 50% (shaders 100/200)', job['message'])

    def test_silent_build_is_stopped_after_the_idle_limit(self):
        probe = "import time\ntime.sleep(60)\n" + CONVERTER
        with patch.object(manager, 'BUILD_IDLE_SECONDS', 1):
            with self.assertRaisesRegex(ValueError, 'no build output'):
                self.prepare_fixture(probe)
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse((self.m.companion(self.game) / 'staging/fresh-output').exists())


class DesktopToolLocationTests(unittest.TestCase):
    def test_default_desktop_tools_live_in_the_xdg_cache(self):
        from desktop.backend import DesktopBackend
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / 'xdg'),
                                         'XDG_CACHE_HOME': str(home / 'cache')}):
                backend = DesktopBackend(home)
            try:
                self.assertEqual(backend.manager.tools, home / 'cache' / 'helixsr-desktop' / 'build-tools')
            finally:
                backend.close()
            explicit = DesktopBackend(home, home / 'explicit')
            try:
                self.assertEqual(explicit.manager.tools, home / 'explicit' / 'build-tools')
            finally:
                explicit.close()


if __name__ == '__main__':
    unittest.main()
