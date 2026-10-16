"""Offline selection regressions. Synthetic caches do not prove gameplay support."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import manager
from test_backend import Fixtures, pe, write


CHOICE = 'compatible-1.8.1'
DIGEST = 'abab32b16acf2536b39663763c355f3cfd35c4876c90297d6b5481bd9ad03a19'


def release(version='1.9.3', digest='9' * 64):
    tag = 'v' + version
    return dict(version=version, sha256=digest, size=55766339,
                url=f'https://github.com/{manager.REPO}/releases/download/{tag}/HelixSR-{version}.zip',
                page=f'https://github.com/{manager.REPO}/releases/tag/{tag}')


class CompatibilityInstallTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.latest = release()
        self.update = patch.object(self.m, 'check_update', side_effect=lambda *a, **kw: dict(self.latest))
        self.update_mock = self.update.start()
        self.addCleanup(self.update.stop)
        manager.atomic_json(self.m.settings / 'release.json', self.latest)
        self.download = patch('manager.urllib.request.urlopen', side_effect=AssertionError('External download prohibited'))
        self.download_mock = self.download.start()
        self.addCleanup(self.download.stop)
        self.compiler = patch.object(self.m, '_spawn_compiler', side_effect=AssertionError('Compiler prohibited'))
        self.compiler_mock = self.compiler.start()
        self.addCleanup(self.compiler.stop)
        self.addCleanup(self.join_worker)

    def join_worker(self):
        if self.m.worker:
            self.m.worker.join(timeout=30)
            self.assertFalse(self.m.worker.is_alive(), 'Fixture worker did not terminate')

    def selected(self):
        return self.m.release_for_choice(CHOICE)

    def cached(self, version='1.8.1', digest=DIGEST, name='compatible', prepared_at=100):
        source = self.package()
        self.reviewed_package(source)
        folder = self.base / name / ('v' + version)
        folder.parent.mkdir(parents=True, exist_ok=True)
        source.rename(folder)
        record = self.m.cfg['packages'].pop(str(source))
        write(folder / manager.DLL, pe(ffx=True, helix=True) + version.encode() + name.encode())
        record.update(path=str(folder), version=version, release_sha256=digest,
                      prepared_at=prepared_at)
        self.m.cfg['packages'][str(folder)] = record
        self.sync_package_record(folder)
        return folder

    def preview(self):
        return self.m.preview_latest(self.game['id'], release_choice=CHOICE)

    def install(self, preview):
        self.m.accept_license(True, preview['token'])
        started = self.m.execute_latest(preview['token'])
        self.join_worker()
        return self.m.jobs[started['id']]

    def assert_no_preparation(self):
        self.download_mock.assert_not_called()
        self.compiler_mock.assert_not_called()

    def test_choice_is_exact_official_181_and_does_not_replace_latest_discovery(self):
        selected = self.selected()
        self.assertEqual(selected['version'], '1.8.1')
        self.assertEqual(selected['sha256'], DIGEST)
        self.assertEqual(selected['size'], 55766339)
        self.assertEqual(selected['url'], release('1.8.1')['url'])
        self.assertEqual(selected['page'], release('1.8.1')['page'])
        self.update_mock.assert_not_called()
        self.assertEqual(self.m.check_update()['version'], '1.9.3')
        self.assertEqual(manager.load_release(self.m.settings)['version'], '1.9.3')
        self.assert_no_preparation()

    def test_default_older_latest_keeps_original_cached_install_behavior(self):
        self.latest = release('1.8.0', '8' * 64)
        manager.atomic_json(self.m.settings / 'release.json', self.latest)
        expected = self.cached('1.8.0', '8' * 64, 'older')
        self.assertEqual(self.m.release_for_choice()['version'], '1.8.0')
        preview = self.m.preview_latest(self.game['id'])
        self.assertEqual(preview['release_version'], '1.8.0')
        job = self.install(preview)
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(self.m.record(self.game)['version'], '1.8.0')
        self.assertEqual(manager.sha(self.native), manager.sha(expected / manager.DLL))
        self.assert_no_preparation()

    def test_default_latest_modern_release_fails_before_downloading_or_provisioning(self):
        for version in ('1.9.0', '1.9.3', '2.0.0'):
            with self.subTest(version=version):
                self.latest = release(version)
                with self.assertRaisesRegex(ValueError, r'1\.8\.1|compatib'):
                    self.m.preview_latest(self.game['id'])
                with self.assertRaisesRegex(ValueError, r'1\.8\.1|compatib'):
                    self.m.release_for_choice()
        self.assertFalse(self.m.worker)
        self.assertFalse(self.m.companion(self.game).exists())
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assert_no_preparation()

    def test_preview_reports_selected_version_and_keeps_exact_selection(self):
        preview = self.preview()
        self.assertEqual(preview['release_version'], '1.8.1')
        self.assertEqual(preview['release_choice'], CHOICE)
        self.assertEqual(preview['release']['sha256'], DIGEST)
        self.assertIn('/v1.8.1/', preview['license_url'])
        self.assertFalse(preview['license_accepted'])
        reviewed = self.m.previews[preview['token']]
        self.assertEqual(reviewed['release_choice'], CHOICE)
        self.assertEqual(reviewed['release']['sha256'], DIGEST)
        self.assertEqual(reviewed['release']['version'], '1.8.1')
        self.assertEqual(self.m.check_update()['version'], '1.9.3')
        self.assert_no_preparation()

    def test_cached_compatible_job_installs_exact_package_despite_newer_cache(self):
        expected = self.cached()
        future = self.cached('1.9.3', '9' * 64, 'future', 999)
        job = self.install(self.preview())
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(job['reviewed_release']['version'], '1.8.1')
        self.assertEqual(job['reviewed_release']['sha256'], DIGEST)
        self.assertEqual(self.m.record(self.game)['version'], '1.8.1')
        self.assertEqual(manager.sha(self.native), manager.sha(expected / manager.DLL))
        self.assertNotEqual(manager.sha(self.native), manager.sha(future / manager.DLL))
        self.assertEqual(self.m.cfg['license']['version'], '1.8.1')
        self.assertEqual(manager.load_release(self.m.settings)['version'], '1.9.3')
        self.assert_no_preparation()

    def test_latest_discovery_changes_do_not_replace_reviewed_explicit_selection(self):
        expected = self.cached()
        preview = self.preview()
        self.latest = release('1.9.4', '4' * 64)
        manager.atomic_json(self.m.settings / 'release.json', self.latest)
        self.m.accept_license(True, preview['token'])
        self.latest = release('2.0.0', '2' * 64)
        manager.atomic_json(self.m.settings / 'release.json', self.latest)
        started = self.m.execute_latest(preview['token'])
        self.join_worker()
        job = self.m.jobs[started['id']]
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(manager.sha(self.native), manager.sha(expected / manager.DLL))
        self.assertEqual(job['reviewed_release']['sha256'], DIGEST)
        self.assert_no_preparation()

    def test_wrong_digest_cache_cannot_satisfy_pinned_compatible_release(self):
        self.cached(digest='f' * 64, name='replaced')
        job = self.install(self.preview())
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))
        self.compiler_mock.assert_not_called()
        self.download_mock.assert_called_once()

    def test_tampered_review_release_or_choice_is_rejected_before_terms_or_execution(self):
        for field, value in (('sha256', 'f' * 64), ('release_choice', 'latest'),
                             ('url', release()['url']), ('page', release()['page']),
                             ('size', 1)):
            with self.subTest(field=field):
                preview = self.preview()
                reviewed = self.m.previews[preview['token']]
                if field != 'release_choice':
                    reviewed['release'][field] = value
                else:
                    reviewed[field] = value
                with self.assertRaises(ValueError):
                    self.m.accept_license(True, preview['token'])
                self.m.cfg['license'] = manager.license_key(self.selected())
                with self.assertRaises(ValueError):
                    self.m.execute_latest(preview['token'])
                self.assertFalse(self.m.worker)
        self.assert_no_preparation()

    def test_terms_for_latest_or_different_digest_do_not_authorize_compatible_install(self):
        preview = self.preview()
        for terms in (manager.license_key(self.latest),
                      manager.license_key(release('1.8.1', 'f' * 64))):
            with self.subTest(terms=terms):
                self.m.cfg['license'] = terms
                with self.assertRaisesRegex(ValueError, r'terms|accept|Accept'):
                    self.m.execute_latest(preview['token'])
                self.assertFalse(self.m.worker)
        self.assert_no_preparation()

    def test_existing_newer_or_unknown_install_blocks_explicit_downgrade(self):
        assessment = self.m.assess(self.game)
        for managed, legacy in ((True, False), (False, True)):
            for installed in ('1.8.2', '1.9.3', '2.0.0', 'unknown', None):
                with self.subTest(managed=managed, legacy=legacy, installed=installed):
                    data = copy.deepcopy(assessment)
                    data.update(managed=managed, legacy=legacy, installed_version=installed)
                    with patch.object(self.m, 'assess', return_value=data):
                        with self.assertRaisesRegex(ValueError, r'remove|Remove|downgrade|version'):
                            self.preview()
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assert_no_preparation()

    def test_unknown_choice_fails_without_downloading(self):
        for choice in ('1.8.1', 'compatible-1.8.0', '../1.8.1', {'version': '1.8.1'}):
            with self.subTest(choice=choice):
                with self.assertRaises((ValueError, TypeError)):
                    self.m.release_for_choice(choice)
        self.assert_no_preparation()


if __name__ == '__main__':
    unittest.main()
