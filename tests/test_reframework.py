"""REFramework loader for RE Engine games: verified download, absent-only install, exact removal."""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from test_backend import Fixtures, pe
import reframework

TAG = 'nightly-01438-f00d6bee503125180621a6666779499f9a30881d'


def archive(files=None):
    files = files if files is not None else {'dinput8.dll': pe(), 'reframework_revision.txt': b'f00d6be\n'}
    wire = io.BytesIO()
    with zipfile.ZipFile(wire, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return wire.getvalue()


def metadata(wire, **changes):
    asset = dict(name='REFramework.zip', size=len(wire), digest='sha256:' + hashlib.sha256(wire).hexdigest(),
                 browser_download_url=f'https://github.com/praydog/REFramework-nightly/releases/download/{TAG}/REFramework.zip')
    asset.update(changes.pop('asset', {}))
    release = dict(tag_name=TAG, draft=False, assets=[asset, dict(name='VR.zip', size=10)])
    release.update(changes)
    return json.dumps(release).encode()


class Response(io.BytesIO):
    def __init__(self, data, url='https://release-assets.githubusercontent.com/x'):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class ReleaseTests(unittest.TestCase):
    def read(self, payload):
        with patch.object(reframework, '_urlopen', return_value=Response(payload)):
            return reframework.latest_release(None)

    def test_latest_release_requires_github_digest_size_and_exact_asset_url(self):
        wire = archive()
        release = self.read(metadata(wire))
        self.assertEqual((release['build'], release['sha256'], release['size']),
                         (1438, hashlib.sha256(wire).hexdigest(), len(wire)))
        for changes, message in [(dict(asset=dict(digest=None)), 'SHA-256'),
                                 (dict(asset=dict(digest='md5:abc')), 'SHA-256'),
                                 (dict(asset=dict(size=reframework.MAX_ARCHIVE + 1)), 'size or location'),
                                 (dict(asset=dict(browser_download_url='https://example.com/REFramework.zip')), 'size or location'),
                                 (dict(tag_name='latest'), 'Unexpected'),
                                 (dict(draft=True), 'Unexpected')]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.read(metadata(wire, **changes))
        with self.assertRaisesRegex(ValueError, 'no single'):
            self.read(json.dumps(dict(tag_name=TAG, draft=False, assets=[])).encode())

    def test_rate_limit_and_network_errors_are_plain_messages(self):
        error = urllib.error.HTTPError(reframework.API, 403, 'rate limited', {}, None)
        with patch.object(reframework, '_urlopen', side_effect=error), self.assertRaisesRegex(ValueError, 'limiting'):
            reframework.latest_release(None)
        with patch.object(reframework, '_urlopen', side_effect=urllib.error.URLError('offline')), \
                self.assertRaisesRegex(ValueError, 'Could not reach GitHub'):
            reframework.latest_release(None)

    def test_asset_redirects_are_limited_to_the_release_path_and_github_asset_hosts(self):
        path = f'/praydog/REFramework-nightly/releases/download/{TAG}/REFramework.zip'
        self.assertTrue(reframework.allowed_asset_url('https://github.com' + path, path))
        self.assertTrue(reframework.allowed_asset_url('https://release-assets.githubusercontent.com/a?sig=1', path))
        for url in ['http://github.com' + path, 'https://github.com/other/repo/file.zip', 'https://evil.example/x',
                    'https://user@release-assets.githubusercontent.com/x', 'https://release-assets.githubusercontent.com:444/x']:
            self.assertFalse(reframework.allowed_asset_url(url, path), url)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, data):
        path = self.dir / 'REFramework.zip'
        path.write_bytes(data)
        return path

    def test_extract_returns_only_a_64_bit_dll_and_clean_revision(self):
        payload, revision = reframework.extract(self.write(archive({'dinput8.dll': pe(), 'reframework_revision.txt': b'f00d6be<script>\n'})))
        self.assertEqual(payload, pe())
        self.assertEqual(revision, 'f00d6bescript')
        for files, message in [({'dinput8.dll': pe(), 'openvr_api.dll': b'x'}, 'layout'),
                               ({'reframework_revision.txt': b'x'}, 'layout'),
                               ({'dinput8.dll': b'not a dll' * 100}, 'Windows DLL'),
                               ({'dinput8.dll': pe(machine=0x14c)}, '64-bit')]:
            with self.subTest(files=list(files)), self.assertRaisesRegex(ValueError, message):
                reframework.extract(self.write(archive(files)))
        with self.assertRaisesRegex(ValueError, 'valid archive'):
            reframework.extract(self.write(b'not a zip'))

    def test_download_checks_size_and_digest_before_keeping_the_archive(self):
        wire = archive()
        release = dict(url=f'https://github.com/praydog/REFramework-nightly/releases/download/{TAG}/REFramework.zip',
                       size=len(wire), sha256=hashlib.sha256(wire).hexdigest())
        destination = self.dir / 'cache' / 'a.zip'
        with patch.object(reframework, '_open_asset', return_value=Response(wire[:-1] + b'x')), \
                self.assertRaisesRegex(ValueError, 'digest'):
            reframework.download(release, destination, None)
        self.assertFalse(destination.exists())
        with patch.object(reframework, '_open_asset', return_value=Response(wire + b'extra')), \
                self.assertRaisesRegex(ValueError, 'larger'):
            reframework.download(release, destination, None)
        with patch.object(reframework, '_open_asset', return_value=Response(wire)):
            self.assertEqual(reframework.download(release, destination, None).read_bytes(), wire)
        with patch.object(reframework, '_open_asset', side_effect=AssertionError('cached copy is reused')):
            reframework.download(release, destination, None)
        self.assertEqual(sorted(p.name for p in destination.parent.iterdir()), ['a.zip'])

    def test_install_never_replaces_and_remove_needs_the_recorded_bytes(self):
        target = self.dir / 'dinput8.dll'
        digest = reframework.install(target, pe())
        self.assertEqual(target.read_bytes(), pe())
        with self.assertRaisesRegex(ValueError, 'appeared'):
            reframework.install(target, pe(ffx=True))
        self.assertEqual(target.read_bytes(), pe())
        record = dict(sha256=digest)
        target.write_bytes(pe(ffx=True))
        with self.assertRaisesRegex(ValueError, 'changed'):
            reframework.remove(target, record)
        self.assertTrue(target.exists())
        target.write_bytes(pe())
        reframework.remove(target, record)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.iterdir()), [])


class ManagerTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.game.update(source='Steam', appid='3764200', name='Resident Evil Requiem')
        self.wire = archive()
        self.dll = self.root / 'dinput8.dll'

    def transport(self, wire=None):
        wire = wire or self.wire
        self.enterContext(patch.object(reframework, '_urlopen', side_effect=lambda *a: Response(metadata(wire))))
        self.enterContext(patch.object(reframework, '_open_asset', side_effect=lambda *a: Response(wire)))

    def state(self):
        return self.m.assess(self.game)['reframework']

    def add(self):
        review = self.m.reframework_preview(self.game['id'])
        return self.m.install_reframework(self.game['id'], self.m.fetch_reframework(review['sha256']))

    def test_only_named_steam_titles_are_offered(self):
        self.assertEqual(self.state()['state'], 'absent')
        self.assertTrue(self.state()['tested'])
        self.game['appid'] = '2246340'
        self.assertFalse(self.state()['tested'])
        self.game['appid'] = '1091500'
        self.assertIsNone(self.state())
        self.game.update(appid='3764200', source='Imported')
        self.assertIsNone(self.state())
        with self.assertRaisesRegex(ValueError, 'not offered'):
            self.m.reframework_preview(self.game['id'])

    def test_review_names_the_exact_build_and_install_adds_only_the_verified_dll(self):
        self.transport()
        review = self.m.reframework_preview(self.game['id'])
        self.assertEqual((review['tag'], review['file'], review['sha256']),
                         (TAG, 'dinput8.dll', hashlib.sha256(self.wire).hexdigest()))
        self.assertFalse(self.dll.exists(), 'review changes nothing')
        before = sorted(p.name for p in self.root.iterdir())
        data = self.m.install_reframework(self.game['id'], self.m.fetch_reframework(review['sha256']))
        self.assertEqual(self.dll.read_bytes(), pe())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), sorted(before + ['dinput8.dll']))
        self.assertEqual(data['reframework']['state'], 'installed')
        self.assertEqual((data['reframework']['tag'], data['reframework']['revision']), (TAG, 'f00d6be'))
        self.assertEqual(self.native.read_bytes(), self.original, 'game files are untouched')
        with self.assertRaisesRegex(ValueError, 'already set up'):
            self.m.reframework_preview(self.game['id'])

        data = self.m.remove_reframework(self.game['id'])
        self.assertFalse(self.dll.exists())
        self.assertEqual(data['reframework']['state'], 'absent')
        self.assertIsNone(reframework.read_record(self.m.companion(self.game)))

    def test_existing_or_changed_loaders_are_left_alone(self):
        self.transport()
        self.dll.write_bytes(b'someone else\'s REFramework')
        self.assertEqual(self.state()['state'], 'foreign')
        with self.assertRaisesRegex(ValueError, 'existing dinput8.dll'):
            self.m.reframework_preview(self.game['id'])
        with self.assertRaisesRegex(ValueError, 'no record'):
            self.m.remove_reframework(self.game['id'])
        self.assertEqual(self.dll.read_bytes(), b'someone else\'s REFramework')

        self.dll.unlink()
        self.add()
        self.dll.write_bytes(b'newer REFramework copied by the user')
        self.assertEqual(self.state()['state'], 'changed')
        with self.assertRaisesRegex(ValueError, 'leaves it alone'):
            self.m.remove_reframework(self.game['id'])
        self.assertEqual(self.dll.read_bytes(), b'newer REFramework copied by the user')

    def test_only_the_current_archive_is_kept_in_the_cache(self):
        self.transport()
        cache = self.m.settings / 'reframework'
        cache.mkdir(parents=True)
        (cache / ('0' * 64 + '.zip')).write_bytes(b'older nightly')
        self.add()
        self.assertEqual([p.name for p in cache.iterdir()], [hashlib.sha256(self.wire).hexdigest() + '.zip'])

    def test_missing_loader_can_be_added_again(self):
        self.transport()
        self.add()
        self.dll.unlink()
        self.assertEqual(self.state()['state'], 'missing')
        self.add()
        self.assertEqual(self.state()['state'], 'installed')

    def test_running_game_newer_build_and_racing_file_block_install(self):
        self.transport()
        review = self.m.reframework_preview(self.game['id'])
        fetched = self.m.fetch_reframework(review['sha256'])
        with patch('manager.active_processes', return_value=[{'pid': 1}]), \
                self.assertRaisesRegex(ValueError, 'Close the game'):
            self.m.install_reframework(self.game['id'], fetched)
        with self.assertRaisesRegex(ValueError, 'newer REFramework build'):
            self.m.fetch_reframework('0' * 64)
        with patch.object(reframework, 'install', side_effect=ValueError('A dinput8.dll appeared')), \
                self.assertRaisesRegex(ValueError, 'appeared'):
            self.m.install_reframework(self.game['id'], fetched)
        self.assertIsNone(reframework.read_record(self.m.companion(self.game)), 'no ownership for a file HelixSR did not write')
        self.assertFalse(self.dll.exists())

    def test_symlinked_loader_is_never_followed(self):
        outside = self.base / 'outside.dll'
        outside.write_bytes(b'outside')
        self.dll.symlink_to(outside)
        self.assertEqual(self.state()['state'], 'foreign')
        self.assertEqual(outside.read_bytes(), b'outside')

    def test_tampered_record_is_refused(self):
        self.transport()
        self.add()
        path = self.m.companion(self.game) / 'records' / reframework.RECORD
        record = json.loads(path.read_text())
        record['file'] = '../outside/dinput8.dll'
        path.write_text(json.dumps(record))
        self.assertEqual(self.state()['state'], 'unavailable')
        with self.assertRaisesRegex(ValueError, 'record path'):
            self.m.remove_reframework(self.game['id'])
        self.assertTrue(self.dll.exists())


if __name__ == '__main__':
    unittest.main()
