import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from desktop import app_updates as updates


class Response(io.BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


def release(version='0.2.0', body=b'AppImage fixture'):
    filename = f'HelixSR-Desktop-{version}-x86_64.AppImage'
    tag = f'desktop-v{version}'
    return dict(tag_name=tag, published_at='2026-10-11', html_url=f'{updates.PAGE}/tag/{tag}',
        assets=[dict(name=filename, size=len(body), digest='sha256:' + hashlib.sha256(body).hexdigest(),
        browser_download_url=f'https://github.com/{updates.REPO}/releases/download/{tag}/{filename}')])


class DesktopUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.updater = updates.AppUpdates(self.tmp.name)

    def test_plugin_tags_and_unsafe_metadata_rejected(self):
        for change in ({'tag_name': 'v0.2.0'}, {'prerelease': True}, {'draft': True}):
            item = release()
            item.update(change)
            with self.assertRaises(ValueError):
                updates.release_info(item)
        for key, value in [('size', True), ('digest', ''), ('browser_download_url', 'https://evil.test/a')]:
            item = release()
            item['assets'][0][key] = value
            with self.assertRaises(ValueError):
                updates.release_info(item)

    def test_feed_selects_latest_desktop_only(self):
        plugin = release('9.9.9')
        plugin['tag_name'] = 'v9.9.9'
        with patch.object(updates, 'https_context', return_value=None), \
                patch.object(updates.urllib.request, 'urlopen', return_value=Response(
                    json.dumps([plugin, release('0.2.0'), release('0.3.0')]).encode(), updates.API)):
            status = self.updater.check(True)
        self.assertEqual(status['latest_version'], '0.3.0')
        self.assertTrue(status['update_available'])

    def download(self, actual, expected=b'AppImage fixture', host='https://release-assets.githubusercontent.com/asset'):
        metadata = release(body=expected)
        responses = [Response(json.dumps([metadata]).encode(), updates.API), Response(actual, host)]
        with patch.object(updates, 'https_context', return_value=None), \
                patch.object(updates.urllib.request, 'urlopen', side_effect=responses):
            return self.updater.download()

    def test_verified_atomic_download_never_executes(self):
        result = self.download(b'AppImage fixture')
        self.assertEqual(Path(result['path']).read_bytes(), b'AppImage fixture')
        self.assertEqual(result['version'], '0.2.0')
        self.assertEqual(list(self.updater.stage.glob('.download-*')), [])

    def test_digest_size_and_redirect_fail_without_artifacts(self):
        for body, host in [(b'wrong content', 'https://github.com/a'),
                (b'AppImage fixtureEXTRA', 'https://github.com/a'),
                (b'AppImage fixture', 'https://evil.test/asset')]:
            with self.assertRaises(ValueError):
                self.download(body, host=host)
            self.assertEqual(list(self.updater.stage.iterdir()), [])

    def test_auto_off_still_allows_manual_check_and_corruption_defaults(self):
        self.updater.set_auto(False)
        with patch.object(updates.urllib.request, 'urlopen') as network:
            self.assertFalse(self.updater.check(False)['auto_check'])
            network.assert_not_called()
        self.updater.path.write_text('{bad')
        self.assertTrue(updates.AppUpdates(self.tmp.name).enabled)


if __name__ == '__main__':
    unittest.main()
