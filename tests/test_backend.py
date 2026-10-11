"""Offline regression fixtures. Synthetic bytes do not prove game compatibility."""
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import warnings
import zipfile

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import library
import manager
import awareness


def pe(ffx=False, dx12=False, helix=False, machine=0x8664):
    # Minimal PE32+ image with actual export/import tables in one .rdata section.
    data = bytearray(0x1200)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 132, machine, 1, 0, 0, 0, 240, 0x2022)
    optional = 152
    struct.pack_into('<H', data, optional, 0x20b)
    struct.pack_into('<Q', data, optional + 24, 0x140000000)
    struct.pack_into('<II', data, optional + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, optional + 56, 0x2000, 0x200)
    struct.pack_into('<I', data, optional + 108, 16)
    section = optional + 240
    data[section:section + 8] = b'.rdata\0\0'
    struct.pack_into('<IIII', data, section + 8, 0x1000, 0x1000, 0x1000, 0x200)
    struct.pack_into('<I', data, section + 36, 0x40000040)
    def offset(rva):
        return 0x200 + rva - 0x1000
    def cstring(rva, value):
        start = offset(rva)
        payload = value.encode() + b'\0'
        data[start:start + len(payload)] = payload
    if ffx:
        struct.pack_into('<II', data, optional + 112, 0x1000, 0x200)
        struct.pack_into('<IIHHIIIIIII', data, offset(0x1000), 0, 0, 0, 0, 0x1180,
                         1, 4, 4, 0x1040, 0x1060, 0x1080)
        cstring(0x1180, 'fixture.dll')
        cursor = 0x10a0
        for index, name in enumerate(('ffxCreateContext', 'ffxDestroyContext', 'ffxDispatch', 'ffxQuery')):
            struct.pack_into('<I', data, offset(0x1040) + index * 4, 0x1500)
            struct.pack_into('<I', data, offset(0x1060) + index * 4, cursor)
            struct.pack_into('<H', data, offset(0x1080) + index * 2, index)
            cstring(cursor, name)
            cursor += len(name) + 1
    if dx12:
        struct.pack_into('<II', data, optional + 120, 0x1200, 40)
        struct.pack_into('<IIIII', data, offset(0x1200), 0x1240, 0, 0, 0x1260, 0x1250)
        struct.pack_into('<Q', data, offset(0x1240), 0x1280)
        struct.pack_into('<Q', data, offset(0x1250), 0x1280)
        cstring(0x1260, 'd3d12.dll')
        cstring(0x1282, 'D3D12CreateDevice')
    if helix:
        cstring(0x1800, 'HelixSR 1.2.3')
    return bytes(data)


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, (bytes, bytearray)) else data.encode())
    return path


def shortcut(name, exe, start=''):
    def string(k, v):
        return b'\x01' + k.encode() + b'\0' + v.encode() + b'\0'
    return (b'\x00shortcuts\0\x000\0' + string('AppName', name) + string('Exe', exe)
            + string('StartDir', start) + string('LaunchOptions', 'test options') + b'\x08\x08\x08')


class Fixtures(unittest.TestCase):
    def setUp(self):
        work = PLUGIN.parent.parent / 'work'
        work.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='backend-tests-', dir=work)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.root = self.base / 'games' / 'Example'
        self.root.mkdir(parents=True)
        write(self.root / 'Example.exe', pe(dx12=True))
        self.native = write(self.root / 'amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        self.original = self.native.read_bytes()
        self.m = manager.Manager(self.home, self.base / 'settings')
        self.game = dict(id='fixture:1', name='Example', folder=str(self.root), source='Imported')
        self.m.entries[self.game['id']] = self.game
        for target in ('manager.active_processes', 'awareness.active_processes'):
            p = patch(target, return_value=[])
            p.start()
            self.addCleanup(p.stop)
        p = patch('manager.os.geteuid', return_value=1000, create=True)
        p.start()
        self.addCleanup(p.stop)

    def package(self):
        folder = self.base / 'prepared' / 'v1.2.3'
        write(folder / manager.DLL, pe(ffx=True, helix=True))
        for name in manager.NETWORK:
            write(folder / name, b'fixture network bytes ' * 128)
        record = dict(path=str(folder), version='1.2.3', files={
            n: manager.sha(folder / n) for n in manager.NETWORK + (manager.DLL,)})
        self.m.cfg['packages'][str(folder)] = record
        return folder

    def action(self, name):
        token = self.m.preview(self.game['id'], name)['token']
        return self.m.execute(token)

    def steam(self, appid='42', build='100', lib=None):
        lib = lib or self.home / '.local/share/Steam'
        directory = lib / 'steamapps/common/SteamGame'
        directory.mkdir(parents=True, exist_ok=True)
        write(directory / 'Game.exe', pe(dx12=True))
        write(directory / 'amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        manifest = write(lib / ('steamapps/appmanifest_' + appid + '.acf'),
            '"AppState" { "appid" "' + appid + '" "name" "Steam Game" '
            '"installdir" "SteamGame" "StateFlags" "4" "buildid" "' + build + '" }')
        return lib, directory, manifest

    def link(self, source, target, directory=False):
        try:
            source.symlink_to(target, target_is_directory=directory)
        except OSError as e:
            self.skipTest('Host cannot create symlink fixture: ' + str(e))


class DiscoveryTests(Fixtures):
    def test_import_folders_two_roots_deduplicates_batch(self):
        second = self.base / 'games' / 'Second'
        write(second / 'Second.exe', pe(dx12=True))
        self.m.import_folders([str(self.root), str(second), str(self.root)])
        self.assertEqual({item['folder'] for item in self.m.cfg['imports']}, {str(self.root), str(second)})
        self.assertEqual(len(self.m.cfg['imports']), 2)
        self.assertEqual(len(self.m.entries), 2)

    def test_import_folders_invalid_root_is_all_or_nothing(self):
        before = json.loads(json.dumps(self.m.cfg))
        with self.assertRaises(ValueError):
            self.m.import_folders([str(self.root), str(self.base / 'missing')])
        self.assertEqual(self.m.cfg, before)
        self.assertFalse((self.m.settings / 'settings.json').exists())

    def test_vdf_modern_and_legacy(self):
        for source in ('"libraryfolders" { "0" { "path" "D:/Games" } }',
                       '"libraryfolders" { "0" "D:/Games" }'):
            self.assertIn('0', library.vdf(source)['libraryfolders'])
        self.assertEqual(library.vdf('"name" "a\\\"b"')['name'], 'a"b')

    def test_vdf_malformed(self):
        for source in ('"key" {', '}', '"key"', '"x" { "y" }'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                library.vdf(source)

    def test_shortcut_binary_and_truncation(self):
        data = shortcut('Game', str(self.root / 'Example.exe'))
        self.assertEqual(library.binary_vdf(data)['shortcuts']['0']['AppName'], 'Game')
        with self.assertRaises(ValueError):
            library.binary_vdf(data[:-3])
        steam = self.home / '.local/share/Steam'
        write(steam / 'userdata/1/config/shortcuts.vdf', data)
        games, warnings_ = library.discover(self.home)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['source'], 'Steam shortcut')
        self.assertEqual(games[0]['launch_options'], 'test options')
        self.assertFalse(warnings_)

    def test_shortcut_unsigned_appid_association(self):
        appid = 0xf1234567
        data = shortcut('Game', str(self.root / 'Example.exe'))
        data = data[:-3] + b'\x02AppId\0' + struct.pack('<I', appid) + data[-3:]
        write(self.home / '.local/share/Steam/userdata/1/config/shortcuts.vdf', data)
        games, warnings_ = library.discover(self.home)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['appid'], str(appid))
        self.assertEqual(games[0]['source'], 'Steam shortcut')
        self.assertFalse(warnings_)

    def test_multilibrary_and_duplicate_root(self):
        root, _, _ = self.steam()
        other, _, _ = self.steam('43', lib=self.base / 'second-library')
        write(root / 'steamapps/libraryfolders.vdf',
              '"libraryfolders" { "0" { "path" "' + root.as_posix() + '" } '
              '"1" "' + other.as_posix() + '" "2" { "path" "' + other.as_posix() + '" } }')
        games, warnings_ = library.discover(self.home)
        self.assertEqual({g['id'] for g in games}, {'steam:42', 'steam:43'})
        self.assertEqual(len(games), 2)
        self.assertFalse(warnings_)

    def test_launchers_and_import_paths(self):
        paths = {}
        for name in ('heroic', 'legendary', 'lutris', 'manual'):
            paths[name] = self.base / 'games' / name
            write(paths[name] / 'Game.exe', pe())
        write(self.home / '.config/heroic/gog_store/installed.json', json.dumps({
            'installed': [{'installPath': str(paths['heroic']), 'title': 'Heroic game'}]}))
        write(self.home / '.config/legendary/installed.json', json.dumps({
            'id': {'install_path': str(paths['legendary']), 'title': 'Legendary game'}}))
        write(self.home / '.config/lutris/games/test.yml',
              'name: Lutris game\ngame:\n  exe: "' + str(paths['lutris'] / 'Game.exe') + '"\n')
        games, _ = library.discover(self.home, [{'folder': str(paths['manual']), 'name': 'Imported game'}])
        self.assertEqual({g['source'] for g in games}, {'Heroic', 'Legendary', 'Lutris', 'Imported'})
        self.m.import_folder(str(paths['manual']), 'Manual')
        self.assertEqual(len(self.m.cfg['imports']), 1)
        with self.assertRaises(ValueError):
            self.m.import_folder(str(self.home))

    def test_safe_root_rejects_home_and_relative(self):
        self.assertEqual(library.safe_root(self.root), self.root.resolve())
        for path in ('.', Path.home(), Path(self.root.anchor)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                library.safe_root(path)

    def test_system_descendant_guard(self):
        # Pure POSIX check is meaningful only on the target OS.
        if os.name != 'posix':
            self.skipTest('POSIX system directories require Linux')
        with self.assertRaises(ValueError):
            library.safe_root('/usr/local')

    def test_scan_and_checked_path_symlink_escape(self):
        outside = self.base / 'outside'
        write(outside / 'Hidden.exe', pe())
        self.link(self.root / 'escape', outside, directory=True)
        self.assertFalse(any('Hidden.exe' in names for _, names in library.scan_tree(self.root)))
        with self.assertRaises(ValueError):
            manager.checked_path(self.root, 'escape/Hidden.exe')

    def test_checked_path_rejects_traversal_and_absolute(self):
        outside = self.base / 'outside'
        for relative in ('../outside/Hidden.exe', str(outside / 'Hidden.exe')):
            with self.assertRaises(ValueError):
                manager.checked_path(self.root, relative)


class ArchiveTests(Fixtures):
    def archive(self, members):
        archive = self.base / 'fixture.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(archive, 'w') as z:
                for name, data in members:
                    z.writestr(name, data)
        return archive

    def test_valid_archive(self):
        archive = self.archive([('folder/file', 'payload')])
        dest = self.base / 'extract'
        manager.safe_extract(archive, dest)
        self.assertEqual((dest / 'folder/file').read_text(), 'payload')

    def test_traversal_and_absolute_archives(self):
        for name in ('../outside', '/absolute', 'D:/drive', '..\\outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manager.safe_extract(self.archive([(name, 'bad')]), self.base / 'extract')

    def test_symlink_and_duplicate_archives(self):
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        for members in ([(info, 'target')], [('same', 'a'), ('same', 'b')]):
            with self.assertRaises(ValueError):
                manager.safe_extract(self.archive(members), self.base / 'extract')

    def test_normalized_duplicate_archive_rejected(self):
        with self.assertRaises(ValueError):
            manager.safe_extract(self.archive([('folder/file', 'a'), ('folder/./file', 'b')]),
                                 self.base / 'extract')


class AssessmentTests(Fixtures):
    def test_native_ffx_plus_dlss_prefers_direct_route(self):
        write(self.root / 'nvngx_dlss.dll', pe())
        data = self.m.assess(self.game)
        self.assertEqual(data['route'], 'direct')
        self.assertEqual(data['inputs'], ['DLSS'])

    def test_runtime_ffx_dll_preferred_over_signed_sdk_duplicate(self):
        duplicate = write(self.root / 'SDK/bin/signed/amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        data = self.m.assess(self.game)
        self.assertEqual(data['targets'], [str(self.native)])
        self.assertNotIn(str(duplicate), data['targets'])

    def test_export_table_beyond_four_megabytes_is_detected(self):
        payload = bytearray(pe(ffx=True, dx12=True))
        raw = payload[0x200:]
        raw_pointer = (4 << 20) + 0x200
        struct.pack_into('<I', payload, 152 + 240 + 20, raw_pointer)
        payload = payload[:0x200] + bytes(raw_pointer - 0x200) + raw
        path = write(self.root / 'late-exports.dll', payload)
        info = manager.pe_info(path)
        self.assertTrue(info['ffx'])
        self.assertTrue(info['dx12'])

    def test_plain_ffx_and_dx12_strings_do_not_establish_tables(self):
        path = write(self.root / 'strings.dll', pe() +
                     b' ffxCreateContext ffxDestroyContext ffxDispatch ffxQuery d3d12.dll')
        info = manager.pe_info(path)
        self.assertFalse(info['ffx'])
        self.assertFalse(info['dx12'])

    def test_wrong_export_name_cannot_pass(self):
        payload = pe(ffx=True).replace(b'ffxQuery\0', b'badQuery\0')
        self.assertFalse(manager.pe_info(write(self.root / 'wrong-export.dll', payload))['ffx'])

    def test_malformed_export_counts_and_rvas_fail_closed(self):
        for name, position, value in (('huge-count', 0x200 + 24, 0xffffffff),
                                      ('invalid-name-table', 0x200 + 32, 0xfffffff0),
                                      ('invalid-name-rva', 0x260, 0xfffffff0),
                                      ('invalid-export-directory', 152 + 112, 0xfffffff0)):
            with self.subTest(name=name):
                payload = bytearray(pe(ffx=True))
                struct.pack_into('<I', payload, position, value)
                info = manager.pe_info(write(self.root / (name + '.dll'), payload))
                self.assertFalse(info['ffx'])
        truncated = write(self.root / 'truncated-table.dll', pe(ffx=True)[:0x220])
        self.assertFalse(manager.pe_info(truncated)['ffx'])

    def test_pe_and_direct_route(self):
        self.assertEqual(manager.pe_info(self.native),
                         dict(arch='x64', dx12=False, ffx=True, helix=False, helix_version=None))
        data = self.m.assess(self.game)
        self.assertEqual((data['route'], data['compatibility']), ('direct', 'candidate'))
        self.assertFalse(data['managed'])

    def test_unsupported_pe_blocks(self):
        write(self.native, pe(ffx=True, machine=0x14c))
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')

    def test_optiscaler_and_unmanaged_injector(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        data = self.m.assess(self.game)
        self.assertEqual((data['route'], data['compatibility']), ('optiscaler', 'candidate'))
        write(self.root / 'dxgi.dll', b'existing unrelated proxy')
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')

    def test_legacy_requires_explicit_adoption_and_original(self):
        write(self.native, pe(ffx=True, helix=True))
        self.assertTrue(self.m.assess(self.game)['legacy'])
        with self.assertRaisesRegex(ValueError, 'Import existing'):
            self.m.preview(self.game['id'], 'remove')
        with self.assertRaisesRegex(ValueError, 'verified original'):
            self.m.preview(self.game['id'], 'adopt')
        write(self.native.with_name(self.native.stem + '.original.dll'), self.original)
        self.action('adopt')
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_anticheat_directories_and_files(self):
        for name, directory in (('EasyAntiCheat', True), ('BEClient_x64.dll', False)):
            path = self.root / name
            path.mkdir() if directory else write(path, b'fixture')
            data = self.m.assess(self.game)
            self.assertEqual(data['compatibility'], 'blocked')
            self.assertTrue(any('Anti-cheat' in r for r in data['reasons']))
            path.rmdir() if directory else path.unlink()

    def test_license_gate_before_background_work(self):
        with patch.object(self.m, 'prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'Accept local'):
                self.m.start_job('prepare', self.game['id'])
            prepare.assert_not_called()
        release = dict(version='1.2.3', sha256='a' * 64)
        with patch.object(self.m, 'check_update', return_value=release):
            self.assertTrue(self.m.accept_license(True))
        self.assertEqual(self.m.cfg['license'],
                         {'terms': manager.LICENSE_REV, 'version': '1.2.3', 'release_sha256': 'a' * 64})
        self.assertFalse(self.m.accept_license(False))

    def test_changed_release_invalidates_license_and_rejects_job(self):
        accepted = dict(version='1.2.3', sha256='a' * 64)
        with patch.object(self.m, 'check_update', return_value=accepted):
            self.m.accept_license(True)
        for release in (dict(version='1.2.4', sha256='b' * 64),
                        dict(version='1.2.3', sha256='b' * 64)):
            with self.subTest(release=release):
                manager.atomic_json(self.m.settings / 'release.json', release)
                self.assertFalse(self.m.refresh()['license_accepted'])
                self.m.entries[self.game['id']] = self.game
                with patch.object(self.m, 'prepare') as prepare:
                    with self.assertRaisesRegex(ValueError, 'Accept local'):
                        self.m.start_job('prepare', self.game['id'])
                    prepare.assert_not_called()

    def test_release_change_during_prepare_rechecks_license_before_download(self):
        accepted = dict(version='1.2.3', sha256='a' * 64)
        with patch.object(self.m, 'check_update', return_value=accepted):
            self.m.accept_license(True)
        changed = dict(version='1.2.4', sha256='b' * 64)
        with patch.object(self.m, 'check_update', return_value=changed), \
                patch('manager.urllib.request.urlopen') as download:
            with self.assertRaisesRegex(ValueError, 'release changed'):
                self.m.prepare(self.game, {'id': 'fixture'})
            download.assert_not_called()


class ReleaseTests(Fixtures):
    def cached_preparation(self):
        folder = self.package()
        release = dict(version='1.2.3', sha256='a' * 64, size=1234,
                       url=f'https://github.com/{manager.REPO}/releases/download/v1.2.3/HelixSR-1.2.3.zip')
        self.m.cfg['packages'][str(folder)]['release_sha256'] = release['sha256']
        self.m.cfg['packages'][str(folder)]['prepared_at'] = 100
        self.m.cfg['license'] = manager.license_key(release)
        return folder, release

    def test_prepare_reuses_verified_same_drive_exact_release_without_download(self):
        folder, release = self.cached_preparation()
        self.assertEqual(folder.stat().st_dev, self.root.stat().st_dev)
        job = {'id': 'fixture-cache'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.urllib.request.urlopen') as download:
            self.m.prepare(self.game, job)
            download.assert_not_called()
        self.assertIn('Reusing', job['message'])
        self.assertFalse((self.m.companion(self.game) / 'staging' / job['id']).exists())

    def test_prepare_different_release_digest_does_not_reuse_cache(self):
        folder, release = self.cached_preparation()
        self.m.cfg['packages'][str(folder)]['release_sha256'] = 'b' * 64
        job = {'id': 'fixture-digest-change'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.shutil.disk_usage', return_value=MagicMock(free=4 << 30)), \
                patch('manager.https_context', return_value=None), \
                patch('manager.urllib.request.urlopen', side_effect=RuntimeError('fixture download boundary')) as download:
            with self.assertRaisesRegex(RuntimeError, 'fixture download boundary'):
                self.m.prepare(self.game, job)
            download.assert_called_once()
        self.assertFalse((self.m.companion(self.game) / 'staging' / job['id']).exists())

    def test_identical_semver_package_selection_uses_latest_prepared_at(self):
        first, _ = self.cached_preparation()
        second = self.base / 'other-cache' / 'v1.2.3'
        second.mkdir(parents=True)
        record = dict(self.m.cfg['packages'][str(first)], path=str(second), prepared_at=200)
        self.m.cfg['packages'][str(second)] = record
        self.assertEqual(self.m.package(self.game)[1], second)
        self.m.cfg['packages'][str(first)]['prepared_at'] = 300
        self.assertEqual(self.m.package(self.game)[1], first)

    def update_with_redirect(self, page):
        response = MagicMock()
        response.url = page
        response.__enter__.return_value = response
        error = manager.urllib.error.HTTPError(manager.API, 403, 'Fixture quota', {}, None)
        with patch('manager.https_context', return_value=None), \
                patch('manager.urllib.request.urlopen', side_effect=[error]) as requests:
            release = self.m.check_update(force=True)
        self.assertEqual(requests.call_count, 1)
        first = requests.call_args_list[0].args[0]
        self.assertEqual(first.full_url, manager.API)
        return release

    def test_api_quota_never_invents_metadata_from_a_latest_tag_redirect(self):
        page = f'https://github.com/{manager.REPO}/releases/tag/v1.7.0'
        release = self.update_with_redirect(page)
        self.assertFalse(release.get('version'))
        self.assertFalse(release.get('sha256'))
        self.assertIn('HTTP 403', release['error'])
        self.assertEqual(manager.load_json(self.m.settings / 'release.json'), release)

    def test_api_quota_cannot_resurrect_obsolete_cached_metadata(self):
        manager.atomic_json(self.m.settings / 'release.json',
                            dict(version='1.6.0', sha256='a' * 64, checked_at=0, error='old cached failure'))
        release = self.update_with_redirect(f'https://github.com/{manager.REPO}/releases/tag/v1.7.0')
        self.assertFalse(release.get('version'))
        self.assertIn('HTTP 403', release['error'])

    def test_unknown_redirect_never_creates_unverified_release(self):
        for page in (f'https://github.com/{manager.REPO}/releases/tag/v9.0.0',
                     'https://example.invalid/releases/tag/v1.7.0'):
            with self.subTest(page=page):
                (self.m.settings / 'release.json').unlink(missing_ok=True)
                release = self.update_with_redirect(page)
                self.assertFalse(release.get('version'))
                self.assertFalse(release.get('sha256'))
                self.assertTrue(release.get('error'))


class AwarenessTests(Fixtures):
    def test_optiscaler_helix_paths_report_configuration_separate_from_runtime(self):
        write(self.root / 'OptiScaler.ini', '[Paths]\nFfxDx12Path=Z:\\games\\HelixSR\\helixsr.dll\n'
              'FfxDx12SRPath=Z:\\games\\HelixSR\\helixsr_upscaler.dll\n')
        data = self.inspect()
        self.assertEqual(data['route'], 'direct')
        self.assertTrue(data['optiscaler']['helix_configured'])
        self.assertTrue(data['optiscaler']['involved'])
        self.assertEqual(data['optiscaler']['runtime'], 'unknown')

    def inspect(self, processes=None):
        with patch('awareness.active_processes', return_value=processes or []):
            return self.m.assess(self.game)

    def mako_fixture(self):
        write(self.home / '.config/mako-render/conf.toml',
              '[[profile]]\nname = "pragmata-codex"\n'
              'frame_generation_enabled = true\nframe_generation_provisioned = false\n'
              '[[profile]]\nname = "other-profile"\nframe_generation_enabled = false\n')

    def mako_flags(self):
        return {e['key']: e['enabled'] for e in self.inspect()['framegen']
                if e['source'] == 'MAKO' and e['meaning'] == 'configured'}

    def test_mako_named_profile_metadata_app_and_process_associations(self):
        self.mako_fixture()
        self.game['appid'] = '42'
        for association in ({'steam_app_id': '42', 'captured_processes': [], 'kind': 'manual'},
                            {'steam_app_id': '99', 'captured_processes': ['Example.exe'], 'kind': 'manual'}):
            with self.subTest(association=association):
                write(self.home / '.config/mako-render/profile-metadata.json',
                      json.dumps({'profiles': {'pragmata-codex': association}}))
                self.assertEqual(self.mako_flags(),
                                 {'frame_generation_enabled': True, 'frame_generation_provisioned': False})

    def test_mako_unassociated_profile_not_applied(self):
        self.mako_fixture()
        self.game['appid'] = '42'
        self.assertEqual(self.mako_flags(), {})
        write(self.home / '.config/mako-render/profile-metadata.json', json.dumps({'profiles': {
            'pragmata-codex': {'steam_app_id': '99', 'captured_processes': ['Other.exe'], 'kind': 'manual'}}}))
        self.assertEqual(self.mako_flags(), {})

    def test_mako_explicit_launch_profile_association(self):
        self.mako_fixture()
        self.game['launch_options'] = 'mako-run --profile pragmata-codex %command%'
        self.assertEqual(self.mako_flags(),
                         {'frame_generation_enabled': True, 'frame_generation_provisioned': False})

    def test_mako_wrapper_exact_app_case_association(self):
        self.mako_fixture()
        self.game['appid'] = '42'
        self.game['launch_options'] = 'sh ~/.lsfg %command%'
        wrapper = ('case "$SteamAppId" in\n142)\n MAKO_PROFILE=other-profile\n ;;\n'
                   '42)\n MAKO_PROFILE=pragmata-codex DISABLE_MAKO=0\n ;;\nesac\n')
        write(self.home / '.lsfg', wrapper)
        self.assertEqual(self.mako_flags(),
                         {'frame_generation_enabled': True, 'frame_generation_provisioned': False})
        self.game['appid'] = '7'
        self.assertEqual(self.mako_flags(), {})

    def test_lsfg_profile_active_in_matches_game_executable(self):
        write(self.home / '.config/lsfg-vk/conf.toml',
              'version = 2\n[[profile]]\nname = "Handheld profile"\n'
              'active_in = ["Example.exe"]\nmultiplier = 2\n'
              '[[profile]]\nname = "Unrelated"\nactive_in = ["Other.exe"]\nmultiplier = 4\n')
        profiles = [e for e in self.inspect()['framegen'] if e['source'] == 'LSFG-VK']
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]['value'], '2')
        self.assertTrue(profiles[0]['enabled'])
        self.assertEqual(profiles[0]['meaning'], 'configured')

    def test_lsfg_unrelated_profile_number_is_not_app_association(self):
        self.game['appid'] = '42'
        write(self.home / '.config/lsfg-vk/conf.toml',
              'version = 2\n[[profile]]\nname = "Preset 42"\n'
              'active_in = ["Other.exe"]\nmultiplier = 3\n')
        profiles = [e for e in self.inspect()['framegen'] if e['source'] == 'LSFG-VK']
        self.assertEqual(profiles, [])

    def test_native_fg_off_preserved_beside_configured_wrapper(self):
        write(self.root / 'GameUserSettings.ini', '[Graphics]\nFrameGeneration=false\n')
        self.game['launch_options'] = 'mako %command%'
        data = self.inspect()
        native = [e for e in data['framegen'] if e['source'] == 'Native game']
        wrapper = [e for e in data['framegen'] if e['source'] == 'MAKO']
        self.assertEqual(len(native), 1)
        self.assertFalse(native[0]['enabled'])
        self.assertEqual(native[0]['meaning'], 'configured')
        self.assertEqual(len(wrapper), 1)
        self.assertIsNone(wrapper[0]['enabled'])
        self.assertEqual(wrapper[0]['meaning'], 'launch route')

    def test_historical_helix_log_without_process_is_unverified(self):
        write(self.root / 'helixsr.log', 'network running\noutput directly\n')
        data = self.inspect()
        self.assertIn('historical', data['helix_runtime'])
        self.assertNotIn('reports neural output', data['helix_runtime'])

    def test_log_without_known_process_start_remains_unverified(self):
        self.package()
        self.action('install')
        write(self.root / 'helixsr.log', 'network running\n')
        data = self.inspect([dict(pid=123, env={}, started_at=0)])
        self.assertNotIn('reports neural output', data['helix_runtime'])

    def test_disabled_managed_record_cannot_claim_current_helix(self):
        self.package()
        self.action('install')
        self.action('disable')
        write(self.root / 'helixsr.log', 'network running\n')
        data = self.inspect([dict(pid=123, env={}, started_at=time.time() - 10)])
        self.assertFalse(data['enabled'])
        self.assertNotIn('reports neural output', data['helix_runtime'])

    def test_enabled_managed_fresh_log_retains_evidence_limits(self):
        self.package()
        self.action('install')
        write(self.root / 'helixsr.log', 'network running\n')
        data = self.inspect([dict(pid=123, env={}, started_at=time.time() - 10)])
        self.assertIn('reports neural output', data['helix_runtime'])
        self.assertIn('visual/stability check required', data['helix_runtime'])


class RecoveryAndOptiScalerRegressionTests(Fixtures):
    def test_new_upstream_fg_dependency_updates_old_records_without_enabling_fg(self):
        self.optiscaler_fixture()
        self.action('install')
        package = self.m.package(self.game)[1]
        write(package / 'amd-fsr' / manager.AMD_FG, b'fixture AMD FG provider')
        with (package / 'optiscaler/OptiScaler.ini').open('a') as f:
            f.write('FfxDx12FGPath=auto\n')
        write(self.root / 'GameUserSettings.ini', '[Graphics]\nFrameGeneration=false\n')
        self.action('update')
        live = self.root / 'HelixSR' / manager.AMD_FG
        rel = str(live.relative_to(self.root))
        self.assertEqual(live.read_bytes(), b'fixture AMD FG provider')
        self.assertIsNone(self.m.record(self.game)['baseline'][rel])
        self.assertIn('FfxDx12FGPath=Z:', (self.root / 'OptiScaler.ini').read_text())
        self.assertIn('FrameGeneration=false', (self.root / 'GameUserSettings.ini').read_text())
        self.action('disable')
        self.assertFalse(live.exists())
        self.action('enable')
        self.assertTrue(live.exists())
        self.action('remove')
        self.assertFalse(live.exists())
        self.assertIn('FrameGeneration=false', (self.root / 'GameUserSettings.ini').read_text())

    def test_new_dependency_never_overwrites_unmanaged_fg_file(self):
        self.optiscaler_fixture()
        self.action('install')
        package = self.m.package(self.game)[1]
        write(package / 'amd-fsr' / manager.AMD_FG, b'new upstream FG')
        live = write(self.root / 'HelixSR' / manager.AMD_FG, b'user FG file')
        with self.assertRaisesRegex(ValueError, 'unmanaged file'):
            self.m.preview(self.game['id'], 'update')
        self.assertEqual(live.read_bytes(), b'user FG file')
        self.action('disable')
        self.assertEqual(live.read_bytes(), b'user FG file')
        self.action('remove')
        self.assertEqual(live.read_bytes(), b'user FG file')

    def test_latest_game_fingerprint_stays_stable_when_preparation_adds_fg_payload(self):
        self.optiscaler_fixture()
        for managed in (False, True):
            with self.subTest(managed=managed):
                if managed:
                    self.action('install')
                before = self.m.fingerprint(self.game, self.m.assess(self.game), include_package=False)
                package = self.m.package(self.game)[1]
                fg = write(package / 'amd-fsr' / manager.AMD_FG, b'new provider prepared later')
                after = self.m.fingerprint(self.game, self.m.assess(self.game), include_package=False)
                self.assertEqual(before, after)
                fg.unlink()

    def optiscaler_fixture(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        package = self.package()
        write(package / 'optiscaler/OptiScaler.dll', b'fixture OptiScaler proxy')
        write(package / 'optiscaler/fakenvapi.dll', b'fixture fakenvapi')
        write(package / 'optiscaler/fakenvapi.ini', '[fixture]\nvalue=1\n')
        write(package / 'optiscaler/OptiScaler.ini',
              '[Upscalers]\nDx12Upscaler=auto\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n')
        write(package / 'amd-fsr/amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))

    def interrupted_fixture(self):
        tx = self.m.companion(self.game) / 'transaction'
        digest = manager.sha(self.native)
        write(tx / 'snapshot' / self.native.name, self.native.read_bytes())
        previous = dict(route='direct', target=str(self.root), targets=[str(self.native)],
                        baseline={self.native.name: digest}, current={self.native.name: digest},
                        enabled=False, version='1.2.3')
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='disable',
            before={self.native.name: digest}, allowed_live={self.native.name: [digest]},
            previous=previous, game_build=self.game.get('build')))
        return tx

    def test_optiscaler_reinstall_with_empty_directory_or_retained_regular_log(self):
        self.optiscaler_fixture()
        for log in (None, b'historical regular helix log'):
            with self.subTest(log=log):
                self.action('install')
                self.action('remove')
                helix = self.root / 'HelixSR'
                helix.mkdir(exist_ok=True)
                if log:
                    write(helix / 'helixsr.log', log)
                self.assertEqual(self.m.assess(self.game)['compatibility'], 'candidate')
                self.action('install')
                self.assertTrue(self.m.record(self.game)['enabled'])
                if log:
                    self.assertEqual((helix / 'helixsr.log').read_bytes(), log)
                self.action('remove')

    def test_foreign_file_and_subdirectory_in_helix_folder_still_block(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        helix = self.root / 'HelixSR'
        foreign = write(helix / 'foreign.dll', b'foreign dependency')
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')
        self.assertEqual(foreign.read_bytes(), b'foreign dependency')
        foreign.unlink()
        foreign_dir = helix / 'foreign-subdirectory'
        foreign_dir.mkdir()
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')
        self.assertTrue(foreign_dir.is_dir())

    def test_symlink_log_in_helix_folder_still_blocks(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        helix = self.root / 'HelixSR'
        helix.mkdir()
        outside = write(self.base / 'outside.log', b'foreign log')
        self.link(helix / 'helixsr.log', outside)
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')
        self.assertEqual(outside.read_bytes(), b'foreign log')

    def test_interrupted_journal_assessment_reports_recovery_available(self):
        self.interrupted_fixture()
        self.assertTrue(self.m.assess(self.game)['recovery_available'])

    def test_refresh_assessment_failure_still_reports_recovery_available(self):
        self.interrupted_fixture()
        self.m.cfg['imports'] = [dict(folder=str(self.root), name='Example')]
        with patch.object(self.m, 'assess', side_effect=ValueError('fixture assessment failure')):
            games = self.m.refresh()['games']
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['compatibility'], 'blocked')
        self.assertTrue(games[0]['recovery_available'])

    def test_recovery_bypasses_broken_assessment_and_uses_previous_route(self):
        tx = self.interrupted_fixture()
        with patch.object(self.m, 'assess', side_effect=ValueError('fixture assessment failure')) as assess:
            preview = self.m.preview(self.game['id'], 'recover')
            self.assertEqual(preview['route'], 'direct')
            result = self.m.execute(preview['token'])
            assess.assert_not_called()
        self.assertIn('recovered', result['message'])
        self.assertFalse(tx.exists())
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_recovery_bypasses_assessment_but_running_game_guard_remains(self):
        tx = self.interrupted_fixture()
        with patch.object(self.m, 'assess', side_effect=ValueError('fixture assessment failure')):
            token = self.m.preview(self.game['id'], 'recover')['token']
            with patch('manager.active_processes', return_value=[{'pid': 123}]):
                with self.assertRaisesRegex(ValueError, 'running'):
                    self.m.execute(token)
        self.assertTrue(tx.exists())
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_recovery_bypasses_assessment_but_steam_update_guard_remains(self):
        lib, root, manifest = self.steam(lib=self.base / 'steam')
        with patch('library.steam_roots', return_value=[lib]):
            self.game = next(g for g in library.discover(self.home)[0] if g['id'] == 'steam:42')
        self.root = root
        self.native = root / 'amd_fidelityfx_upscaler_dx12.dll'
        self.original = self.native.read_bytes()
        self.m.entries[self.game['id']] = self.game
        tx = self.interrupted_fixture()
        write(manifest, manifest.read_text().replace('"StateFlags" "4"', '"StateFlags" "0"'))
        with patch.object(self.m, 'assess', side_effect=ValueError('fixture assessment failure')):
            token = self.m.preview(self.game['id'], 'recover')['token']
            with self.assertRaisesRegex(ValueError, 'download/update'):
                self.m.execute(token)
        self.assertTrue(tx.exists())
        self.assertEqual(self.native.read_bytes(), self.original)


class LatestCoordinatorTests(Fixtures):
    def setUp(self):
        super().setUp()
        self.prepared = self.package()
        release = dict(version='1.2.3', sha256='a' * 64)
        self.m.cfg['packages'][str(self.prepared)]['release_sha256'] = release['sha256']
        self.m.cfg['license'] = manager.license_key(release)
        manager.atomic_json(self.m.settings / 'release.json', release)
        update = patch.object(self.m, 'check_update', return_value=release)
        update.start()
        self.addCleanup(update.stop)
        self.addCleanup(self.join_worker)

    def join_worker(self):
        if self.m.worker:
            self.m.worker.join(timeout=30)
            self.assertFalse(self.m.worker.is_alive(), 'Fixture coordinator worker did not terminate')

    def latest(self):
        token = self.m.preview_latest(self.game['id'])['token']
        job = self.m.execute_latest(token)
        self.join_worker()
        return token, self.m.jobs[job['id']]

    def test_cached_package_latest_install_and_repeat_update(self):
        with patch('manager.urllib.request.urlopen') as download:
            _, first = self.latest()
            self.assertEqual(first['kind'], 'install_latest')
            self.assertEqual(first['state'], 'completed', first.get('message'))
            self.assertTrue(self.m.record(self.game)['enabled'])
            self.assertEqual(manager.sha(self.native), manager.sha(self.prepared / manager.DLL))
            _, second = self.latest()
            self.assertEqual(second['state'], 'completed', second.get('message'))
            self.assertIn('update', second['result']['message'].lower())
            self.assertEqual(manager.sha(self.native), manager.sha(self.prepared / manager.DLL))
            download.assert_not_called()

    def test_game_mutation_during_prepare_refused_and_preserved(self):
        foreign = self.original + b'foreign game update'
        def changed(game, job):
            write(self.native, foreign)
        with patch.object(self.m, 'prepare', side_effect=changed):
            _, job = self.latest()
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.native.read_bytes(), foreign)
        self.assertFalse(self.m.record(self.game))

    def test_cancel_after_prepare_prevents_mutation(self):
        def cancelled(game, job):
            self.m.cancel.set()
        with patch.object(self.m, 'prepare', side_effect=cancelled):
            _, job = self.latest()
        self.assertEqual(job['state'], 'cancelled')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))

    def test_license_refused_before_background_preparation(self):
        self.m.cfg['license'] = None
        with patch.object(self.m, 'prepare') as prepare:
            with self.assertRaises(ValueError):
                token = self.m.preview_latest(self.game['id'])['token']
                self.m.execute_latest(token)
            prepare.assert_not_called()
        self.assertFalse(self.m.worker)

    def test_latest_preview_token_single_use(self):
        _, job = self.latest()
        self.assertEqual(job['state'], 'completed', job.get('message'))
        token = self.m.preview_latest(self.game['id'])['token']
        self.m.execute_latest(token)
        self.join_worker()
        with self.assertRaises(ValueError):
            self.m.execute_latest(token)

    def test_latest_adopts_legacy_then_installs_prepared_version(self):
        write(self.native, pe(ffx=True, helix=True))
        write(self.native.with_name(self.native.stem + '.original.dll'), self.original)
        _, job = self.latest()
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(self.m.record(self.game)['version'], '1.2.3')
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)


class TransactionTests(Fixtures):
    def test_optiscaler_install_disable_enable_remove(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        package = self.package()
        write(package / 'optiscaler/OptiScaler.dll', b'fixture OptiScaler proxy')
        write(package / 'optiscaler/fakenvapi.dll', b'fixture fakenvapi')
        write(package / 'optiscaler/fakenvapi.ini', '[fixture]\nvalue=1\n')
        write(package / 'optiscaler/OptiScaler.ini',
              '[Upscalers]\nDx12Upscaler=auto\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n')
        write(package / 'amd-fsr/amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        self.action('install')
        self.assertEqual(self.m.record(self.game)['route'], 'optiscaler')
        self.assertTrue((self.root / 'dxgi.dll').is_file())
        self.assertIn('Dx12Upscaler=fsr31', (self.root / 'OptiScaler.ini').read_text())
        self.assertEqual(manager.sha(self.root / 'HelixSR/helixsr.dll'), manager.sha(package / manager.DLL))
        self.action('disable')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.action('enable')
        self.assertTrue((self.root / 'dxgi.dll').is_file())
        self.action('remove')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertFalse(self.m.record(self.game))
        self.assertEqual((self.root / 'nvngx_dlss.dll').read_bytes(), pe())

    def test_install_disable_enable_remove_restores_hashes(self):
        package = self.package()
        expected = manager.sha(self.native)
        self.action('install')
        rec = self.m.record(self.game)
        self.assertTrue(rec['enabled'])
        self.assertEqual(manager.sha(self.native), manager.sha(package / manager.DLL))
        for rel, digest in rec['current'].items():
            self.assertEqual(manager.sha(self.root / rel) if digest else None, digest)
        self.action('disable')
        self.assertEqual(manager.sha(self.native), expected)
        self.assertFalse(self.m.record(self.game)['enabled'])
        self.action('enable')
        self.assertEqual(manager.sha(self.native), manager.sha(package / manager.DLL))
        self.action('remove')
        self.assertEqual(manager.sha(self.native), expected)
        self.assertFalse(self.m.record(self.game))
        for name in manager.NETWORK:
            self.assertFalse((self.root / name).exists())

    def test_preview_single_use_and_expiry(self):
        self.package()
        token = self.m.preview(self.game['id'], 'install')['token']
        self.m.previews[token]['expires'] = 0
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.m.execute(token)
        token = self.m.preview(self.game['id'], 'install')['token']
        self.m.execute(token)
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.m.execute(token)

    def test_preview_game_drift(self):
        self.package()
        token = self.m.preview(self.game['id'], 'install')['token']
        write(self.native, self.original + b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.m.execute(token)

    def test_package_drift_after_preview_blocked(self):
        package = self.package()
        token = self.m.preview(self.game['id'], 'install')['token']
        write(package / manager.DLL, pe(ffx=True, helix=True) + b'changed')
        with self.assertRaises(ValueError):
            self.m.execute(token)
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_running_game_execution_blocked(self):
        self.package()
        token = self.m.preview(self.game['id'], 'install')['token']
        with patch('manager.active_processes', return_value=[{'pid': 123}]):
            with self.assertRaisesRegex(ValueError, 'running'):
                self.m.execute(token)

    def test_partial_copy_failure_rolls_back_without_temp_files(self):
        self.package()
        real_copy = manager.shutil.copy2
        failed = [False]
        def copy(src, dst, *args, **kwargs):
            if not failed[0] and Path(dst).name == 'helixsr_weights.bin.helixsr-decky.tmp':
                failed[0] = True
                write(dst, b'partial')
                raise OSError('Synthetic partial-copy failure')
            return real_copy(src, dst, *args, **kwargs)
        with patch('manager.shutil.copy2', side_effect=copy):
            with self.assertRaisesRegex(OSError, 'Synthetic'):
                self.action('install')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))
        self.assertFalse((self.m.companion(self.game) / 'transaction').exists())
        self.assertEqual(list(self.root.rglob('*.helixsr-decky.tmp')), [])

    def test_interrupted_transaction_recovery(self):
        tx = self.m.companion(self.game) / 'transaction'
        relative = self.native.name
        write(tx / 'snapshot' / relative, self.original)
        write(self.native, pe(ffx=True, helix=True))
        original_hash = manager.sha(tx / 'snapshot' / relative)
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='install',
            before={relative: original_hash}, previous={}, game_build=None,
            allowed_live={relative: [original_hash, manager.sha(self.native)]}))
        self.action('recover')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(tx.exists())

    def test_recovery_foreign_live_bytes_refuses_before_any_restore(self):
        tx = self.m.companion(self.game) / 'transaction'
        first, second = self.native.name, 'fixture-config.ini'
        write(tx / 'snapshot' / first, self.original)
        write(tx / 'snapshot' / second, b'baseline config')
        write(self.native, pe(ffx=True, helix=True))
        write(self.root / second, b'foreign game-update bytes')
        before = {rel: manager.sha(tx / 'snapshot' / rel) for rel in (first, second)}
        allowed = {first: [before[first], manager.sha(self.native)], second: [before[second], None]}
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='install',
            before=before, allowed_live=allowed, previous={}, game_build=None))
        live = {rel: (self.root / rel).read_bytes() for rel in (first, second)}
        with self.assertRaises(ValueError):
            self.action('recover')
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in (first, second)}, live)
        self.assertTrue(tx.exists())

    def test_recovery_damaged_snapshot_refuses_before_any_restore(self):
        tx = self.m.companion(self.game) / 'transaction'
        first, second = self.native.name, 'fixture-config.ini'
        write(tx / 'snapshot' / first, self.original)
        write(tx / 'snapshot' / second, b'baseline config')
        before = {rel: manager.sha(tx / 'snapshot' / rel) for rel in (first, second)}
        write(self.native, pe(ffx=True, helix=True))
        write(self.root / second, b'permitted installed config')
        allowed = {rel: [before[rel], manager.sha(self.root / rel)] for rel in (first, second)}
        write(tx / 'snapshot' / second, b'damaged snapshot')
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='install',
            before=before, allowed_live=allowed, previous={}, game_build=None))
        live = {rel: (self.root / rel).read_bytes() for rel in (first, second)}
        with self.assertRaises(ValueError):
            self.action('recover')
        self.assertEqual({rel: (self.root / rel).read_bytes() for rel in (first, second)}, live)
        self.assertTrue(tx.exists())

    def test_recovery_changed_live_acf_build_refuses(self):
        lib, root, manifest = self.steam(lib=self.base / 'steam')
        with patch('library.steam_roots', return_value=[lib]):
            self.game = next(g for g in library.discover(self.home)[0] if g['id'] == 'steam:42')
        self.root = root
        self.m.entries[self.game['id']] = self.game
        native = root / 'amd_fidelityfx_upscaler_dx12.dll'
        tx = self.m.companion(self.game) / 'transaction'
        write(tx / 'snapshot' / native.name, native.read_bytes())
        original_hash = manager.sha(native)
        write(native, pe(ffx=True, helix=True))
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='install',
            before={native.name: original_hash}, allowed_live={native.name: [original_hash, manager.sha(native)]},
            previous={}, game_build='100'))
        write(manifest, manifest.read_text().replace('"100"', '"101"'))
        live = native.read_bytes()
        with self.assertRaises(ValueError):
            self.action('recover')
        self.assertEqual(native.read_bytes(), live)
        self.assertTrue(tx.exists())

    def test_committed_recovery_preserves_install_and_cleans_transaction(self):
        self.package()
        self.action('install')
        rec = self.m.record(self.game)
        tx = self.m.companion(self.game) / 'transaction'
        for rel, expected in rec['baseline'].items():
            if expected:
                write(tx / 'snapshot' / rel, (self.m.companion(self.game) / 'originals' / rel).read_bytes())
        manager.atomic_json(tx / 'journal.json', dict(state='committed', action='install',
            before=rec['baseline'], previous={}, game_build=None,
            committed_current=rec['current'], committed_record=rec,
            allowed_live={rel: [rec['baseline'][rel], current] for rel, current in rec['current'].items()}))
        files = {rel: (self.root / rel).read_bytes() if current else None for rel, current in rec['current'].items()}
        self.action('recover')
        self.assertEqual(self.m.record(self.game), rec)
        self.assertEqual({rel: (self.root / rel).read_bytes() if current else None
                          for rel, current in rec['current'].items()}, files)
        self.assertFalse(tx.exists())

    def test_legacy_journal_without_allowed_live_accepts_only_before_hash(self):
        tx = self.m.companion(self.game) / 'transaction'
        write(tx / 'snapshot' / self.native.name, self.original)
        manager.atomic_json(tx / 'journal.json', dict(state='prepared', action='install',
            before={self.native.name: manager.sha(self.native)}, previous={}))
        write(self.native, pe(ffx=True, helix=True))
        live = self.native.read_bytes()
        with self.assertRaises(ValueError):
            self.action('recover')
        self.assertEqual(self.native.read_bytes(), live)
        write(self.native, self.original)
        self.action('recover')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(tx.exists())

    def test_stale_unmanaged_original_blocks_install_preserves_bytes(self):
        self.package()
        stale = self.native.with_name(self.native.stem + '.original.dll')
        write(stale, b'unmanaged prior backup bytes')
        with self.assertRaises(ValueError):
            self.action('install')
        self.assertEqual(stale.read_bytes(), b'unmanaged prior backup bytes')
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_managed_hash_and_cached_build_drift_blocked(self):
        self.game['build'] = '100'
        self.package()
        self.action('install')
        write(self.native, self.native.read_bytes() + b'changed')
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')
        write(self.native, (self.base / 'prepared/v1.2.3' / manager.DLL).read_bytes())
        self.game['build'] = '101'
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')

    def test_live_manifest_build_drift_blocked_without_refresh(self):
        lib, root, manifest = self.steam(lib=self.base / 'steam')
        with patch('library.steam_roots', return_value=[lib]):
            self.game = next(g for g in library.discover(self.home)[0] if g['id'] == 'steam:42')
        self.root = root
        self.m.entries[self.game['id']] = self.game
        self.package()
        self.action('install')
        write(manifest, manifest.read_text().replace('"100"', '"101"'))
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'blocked')


if __name__ == '__main__':
    unittest.main(verbosity=2)
