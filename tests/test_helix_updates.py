"""Latest asset revisions are data, never hardcoded version/size guesses."""
import json
import sys
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import manager
from test_backend import Fixtures
from test_plugin_updates import FakeResponse


def release(version='1.7.0', size=56601341, digest='b' * 64):
    tag = 'v' + version
    return dict(tag_name=tag, html_url=f'https://github.com/{manager.REPO}/releases/tag/{tag}',
                assets=[dict(name=f'HelixSR-{version}.zip', size=size, digest='sha256:' + digest,
                             browser_download_url=f'https://github.com/{manager.REPO}/releases/download/{tag}/HelixSR-{version}.zip')])


class HelixUpdates(Fixtures):
    def check(self, data):
        response = FakeResponse(json.dumps(data).encode(), manager.API)
        response.headers = {'ETag': 'fixture'}
        with patch('manager.https_context', return_value=None), patch('manager.urllib.request.urlopen', return_value=response):
            return self.m.check_update(True)

    def test_replaced_same_version_and_future_different_size_are_accepted(self):
        for ver, size, digest in [('1.7.0', 26037871, 'a' * 64), ('1.7.0', 56601341, 'b' * 64),
                                  ('1.8.0', 71000000, 'c' * 64)]:
            actual = self.check(release(ver, size, digest))
            self.assertEqual((actual['version'], actual['size'], actual['sha256']), (ver, size, digest))
            self.assertIsNone(actual['error'])

    def test_old_cache_policy_forces_refresh_and_drops_etag(self):
        manager.atomic_json(self.m.settings / 'release.json', dict(version='1.7.0', sha256='a' * 64,
            size=26037871, checked_at=time.time(), etag='obsolete'))
        response = FakeResponse(json.dumps(release()).encode(), manager.API)
        response.headers = {}
        with patch('manager.https_context', return_value=None), patch('manager.urllib.request.urlopen', return_value=response) as request:
            actual = self.m.check_update()
        self.assertEqual(actual['size'], 56601341)
        self.assertNotIn('If-none-match', request.call_args.args[0].headers)

    def test_304_is_success_without_failed_at(self):
        actual = self.check(release())
        actual['failed_at'] = 100
        manager.atomic_json(self.m.settings / 'release.json', actual)
        error = urllib.error.HTTPError(manager.API, 304, 'unchanged', {}, None)
        with patch('manager.https_context', return_value=None), patch('manager.urllib.request.urlopen', side_effect=error):
            result = self.m.check_update(True)
        self.assertIsNone(result['error'])
        self.assertNotIn('failed_at', result)

    def test_invalid_metadata_has_visible_error_without_redirect_fallback(self):
        for data in [[], {'tag_name': None}, {'tag_name': 'v1.7.0', 'assets': None},
                     release(size=None), release(size=True), release(size=-1), release(digest='bad')]:
            with self.subTest(data=data):
                actual = self.check(data)
                self.assertTrue(actual['error'])

    def test_corrupt_metadata_does_not_break_local_library_refresh(self):
        (self.m.settings / 'release.json').write_text('{invalid')
        with patch('manager.discover', return_value=([], [])):
            self.assertEqual(self.m.refresh()['games'], [])
        self.assertEqual(self.check(release())['size'], 56601341)

    def test_preparation_and_terms_reject_stale_metadata_with_error(self):
        release_info = dict(version='1.7.0', sha256='a' * 64, error='GitHub unavailable')
        with patch.object(self.m, 'check_update', return_value=release_info), patch('manager.urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'GitHub unavailable'):
                self.m.prepare(self.game, {'id': 'fixture'})
            with self.assertRaisesRegex(ValueError, 'GitHub unavailable'):
                self.m.accept_license(True)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
