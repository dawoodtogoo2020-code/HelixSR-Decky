"""Offline regression fixtures. Synthetic bytes do not prove game compatibility."""
import json
import hashlib
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
import model_variants


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
        work = Path(os.environ.get('HELIXSR_TEST_TMP', str(PLUGIN.parent.parent / 'work')))
        work.mkdir(parents=True, exist_ok=True)
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
        write(folder / 'optiscaler/OptiScaler.dll', b'fixture OptiScaler proxy')
        write(folder / 'optiscaler/fakenvapi.dll', b'fixture fakenvapi')
        write(folder / 'optiscaler/fakenvapi.ini', '[fixture]\nvalue=1\n')
        write(folder / 'optiscaler/OptiScaler.ini',
              '[Upscalers]\nDx12Upscaler=auto\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n')
        write(folder / 'amd-fsr/amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        record = dict(path=str(folder), version='1.2.3', files={
            n: manager.sha(folder / n) for n in manager.PACKAGE_FILES})
        self.m.cfg['packages'][str(folder)] = record
        return folder

    def sync_package_record(self, folder):
        record = self.m.cfg['packages'][str(folder)]
        names = list(manager.PACKAGE_FILES)
        framegen = 'amd-fsr/' + manager.AMD_FG
        if (folder / framegen).is_file():
            names.append(framegen)
        record['files'] = {name: manager.sha(folder / name) for name in names}
        if record.get('variant'):
            record['files']['helixsr_setup.json'] = manager.sha(folder / 'helixsr_setup.json')
        return record

    def reviewed_package(self, folder):
        """Synthetic output identity, without storing NVIDIA weights in tests."""
        weights = (folder / manager.NETWORK[0]).read_bytes()
        digest = hashlib.sha256(weights).hexdigest()
        for key, value in [('WEIGHTS_SIZE', len(weights)), ('WEIGHTS_SHA256', digest),
                           ('KERNEL_NAMES', (b'synthetic',))]:
            gate = patch.object(model_variants, key, value)
            gate.start()
            self.addCleanup(gate.stop)
        blob = b'synthetic shader bytes ' * 128
        write(folder / manager.NETWORK[1], b'HXSRKPAK' + struct.pack('<II', 2, 1)
              + struct.pack('<32sII', b'synthetic', 56, len(blob)) + blob)
        write(folder / 'helixsr_setup.json', json.dumps(dict(source_sha256=model_variants.SOURCE_SHA256,
              ptx_target='sm_89', shaders=1, wave64=False, weights_sha256=digest)))
        record = self.m.cfg['packages'][str(folder)]
        record['variant'] = dict(id=model_variants.DEFAULT_VARIANT, adapter=model_variants.ADAPTER,
                                recipe_sha256=next(iter(model_variants.REVIEWED_RECIPES)))
        return self.sync_package_record(folder)

    def companion_package(self, game=None, release_digest='a' * 64, prepared_at=100):
        game = game or self.game
        source = self.package()
        self.reviewed_package(source)
        destination = self.m.companion(game) / 'packages/v1.2.3'
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        record = self.m.cfg['packages'].pop(str(source))
        record.update(path=str(destination), release_sha256=release_digest,
                      prepared_at=prepared_at)
        self.m.cfg['packages'][str(destination)] = record
        manager.atomic_json(self.m.companion(game) / 'records/package.json', record)
        return destination, record

    def action(self, name):
        token = self.m.preview(self.game['id'], name)['token']
        return self.m.execute(token)

    def dual_executables(self):
        self.native.unlink()
        (self.root / 'Example.exe').unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        write(self.root / 'DX11/Game.exe', pe() + b'larger DX11 binary' * 1024)
        write(self.root / 'DX12/Game.exe', pe(dx12=True))
        return 'DX12/Game.exe'

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

    def test_runtime_loader_preferred_over_nested_sr_dll(self):
        self.native.unlink()
        loader = write(self.root / manager.DLL, pe(ffx=True))
        for folder in ('SDK/bin/signed', 'OptiScaler/amd-fsr'):
            with self.subTest(folder=folder):
                duplicate = write(self.root / folder / self.native.name, pe(ffx=True))
                data = self.m.assess(self.game)
                self.assertEqual(data['route'], 'direct')
                self.assertEqual(data['compatibility'], 'candidate')
                self.assertEqual(data['targets'], [str(loader)])
            duplicate.unlink()

    def test_executable_directory_loader_preferred_over_nested_sr_dll(self):
        self.native.unlink()
        (self.root / 'Example.exe').unlink()
        write(self.root / 'Binaries/Win64/Example-Win64-Shipping.exe', pe(dx12=True))
        loader = write(self.root / 'Binaries/Win64' / manager.DLL, pe(ffx=True))
        write(self.root / 'SDK/bin/signed' / self.native.name, pe(ffx=True))
        data = self.m.assess(self.game)
        self.assertEqual(data['route'], 'direct')
        self.assertEqual(data['compatibility'], 'candidate')
        self.assertEqual(data['targets'], [str(loader)])

    def test_same_runtime_tier_prefers_sr_filename_over_loader(self):
        write(self.root / manager.DLL, pe(ffx=True))
        data = self.m.assess(self.game)
        self.assertEqual(data['targets'], [str(self.native)])

    def test_nested_native_targets_remain_fallback_with_sr_filename_preference(self):
        self.native.unlink()
        write(self.root / 'Native' / manager.DLL, pe(ffx=True))
        nested_sr = write(self.root / 'Native' / self.native.name, pe(ffx=True))
        data = self.m.assess(self.game)
        self.assertEqual(data['route'], 'direct')
        self.assertEqual(data['targets'], [str(nested_sr)])
        nested_sr.unlink()
        data = self.m.assess(self.game)
        self.assertEqual(data['route'], 'direct')
        self.assertEqual(data['targets'], [str(self.root / 'Native' / manager.DLL)])

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

    def test_alternate_optiscaler_proxies_block_second_install(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        for name in ('dbghelp.dll', 'd3d12.dll', 'wininet.dll', 'winhttp.dll', 'OptiScaler.asi'):
            with self.subTest(name=name):
                proxy = write(self.root / name, pe() + b'OptiScaler fixture')
                data = self.m.assess(self.game)
                self.assertEqual(data['compatibility'], 'blocked')
                self.assertTrue(any(name in reason for reason in data['reasons']))
                self.assertIn(str(proxy), data['optiscaler']['dlls'])
                with self.assertRaisesRegex(ValueError, 'Existing unmanaged injector'):
                    self.m.preview(self.game['id'], 'install')
                self.assertFalse((self.root / 'dxgi.dll').exists())
                self.assertEqual(proxy.read_bytes(), pe() + b'OptiScaler fixture')
                proxy.unlink()

    def test_ordinary_alternate_proxy_names_are_not_blocked(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        for name in ('dbghelp.dll', 'd3d12.dll', 'wininet.dll', 'winhttp.dll', 'OptiScaler.asi'):
            write(self.root / name, pe())
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'candidate')

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
                         manager.license_key(release))
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
    def test_cancelled_build_exit_reports_cancellation_before_generic_failure(self):
        with self.assertRaisesRegex(ValueError, '^Cancelled$'):
            manager.check_build_exit(-15, True)
        with self.assertRaisesRegex(ValueError, 'Network build failed'):
            manager.check_build_exit(1, False)

    def cached_preparation(self):
        folder = self.package()
        self.reviewed_package(folder)
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
        for name in manager.PACKAGE_FILES + ('helixsr_setup.json',):
            write(second / name, (first / name).read_bytes())
        record = dict(self.m.cfg['packages'][str(first)], path=str(second), prepared_at=200)
        self.m.cfg['packages'][str(second)] = record
        self.assertEqual(self.m.package(self.game)[1], second)
        self.m.cfg['packages'][str(first)]['prepared_at'] = 300
        self.assertEqual(self.m.package(self.game)[1], first)


class SharedPackageTests(Fixtures):
    def separate_manager(self):
        shared = manager.Manager(self.home, self.base / 'separate-settings')
        shared.entries[self.game['id']] = self.game
        return shared

    def test_separate_frontend_can_enable_disabled_managed_game_from_companion_record(self):
        package, _ = self.companion_package()
        self.action('install')
        self.action('disable')
        shared = self.separate_manager()
        token = shared.preview(self.game['id'], 'enable')['token']
        result = shared.execute(token)
        self.assertIn('Enable completed', result['message'])
        self.assertEqual(manager.sha(self.native), manager.sha(package / manager.DLL))

    def test_prepare_reuses_verified_companion_cache_from_known_game_on_same_drive(self):
        source = self.base / 'games/Prepared Elsewhere'
        write(source / 'Other.exe', pe(dx12=True))
        source_game = dict(id='fixture:other', name='Other', folder=str(source), source='Imported')
        _, record = self.companion_package(source_game)
        shared = self.separate_manager()
        shared.entries[source_game['id']] = source_game
        release = dict(version='1.2.3', sha256=record['release_sha256'])
        shared.cfg['license'] = manager.license_key(release)
        job = {'id': 'shared-cache'}
        with patch.object(shared, 'check_update', return_value=release), \
                patch('manager.urllib.request.urlopen') as download:
            shared.prepare(self.game, job)
        download.assert_not_called()
        self.assertIn('Reusing', job['message'])

    def test_prepare_prefers_exact_digest_over_newer_same_version_candidate(self):
        matching, release = ReleaseTests.cached_preparation(self)
        newer = self.base / 'newer-cache/v1.2.3'
        for name in manager.PACKAGE_FILES:
            write(newer / name, (matching / name).read_bytes())
        other = dict(self.m.cfg['packages'][str(matching)], path=str(newer),
                     release_sha256='b' * 64, prepared_at=200)
        self.m.cfg['packages'][str(newer)] = other
        job = {'id': 'exact-digest-cache'}
        with patch.object(self.m, 'check_update', return_value=release), \
                patch('manager.urllib.request.urlopen') as download:
            self.m.prepare(self.game, job)
        download.assert_not_called()
        self.assertIn('Reusing', job['message'])

    def test_corrupt_newer_cache_falls_back_to_older_verified_cache(self):
        older = self.package()
        self.m.cfg['packages'][str(older)]['prepared_at'] = 100
        newer = self.base / 'newer-cache/v1.2.3'
        for name in manager.PACKAGE_FILES:
            write(newer / name, (older / name).read_bytes())
        record = dict(self.m.cfg['packages'][str(older)], path=str(newer), prepared_at=200)
        self.m.cfg['packages'][str(newer)] = record
        write(newer / manager.DLL, b'corrupt newer package')
        self.assertEqual(self.m.package(self.game)[1], older)
        self.action('install')
        self.assertEqual(manager.sha(self.native), manager.sha(older / manager.DLL))

    def test_target_companion_is_discovered_before_entries_are_populated(self):
        package, _ = self.companion_package()
        shared = manager.Manager(self.home, self.base / 'empty-entry-settings')
        self.assertEqual(shared.package(self.game)[1], package)

    def test_malformed_json_and_corrupt_known_entry_do_not_hide_target_package(self):
        package, _ = self.companion_package()
        other = self.base / 'games/Malformed'
        write(other / 'Other.exe', pe(dx12=True))
        other_game = dict(id='fixture:malformed', folder=str(other), name='Malformed')
        record_path = self.m.companion(other_game) / 'records/package.json'
        write(record_path, '[' * 2000 + '0' + ']' * 2000)
        shared = manager.Manager(self.home, self.base / 'malformed-entry-settings')
        shared.entries = {'malformed': other_game, 'missing': {'id': 'missing'},
                          'wrong': {'id': 'wrong', 'folder': None}}
        self.assertEqual(shared.package(self.game)[1], package)

    def test_incomplete_companion_manifest_is_not_selected(self):
        _, record = self.companion_package()
        record['files'] = {manager.DLL: record['files'][manager.DLL]}
        manager.atomic_json(self.m.companion(self.game) / 'records/package.json', record)
        shared = self.separate_manager()
        self.assertIsNone(shared.package(self.game))

    def test_changed_shared_payload_is_rejected_before_game_mutation(self):
        package, _ = self.companion_package()
        shared = self.separate_manager()
        write(package / manager.DLL, pe(ffx=True, helix=True) + b'tampered')
        before = self.native.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Prepare HelixSR'):
            shared.preview(self.game['id'], 'install')
        self.assertEqual(self.native.read_bytes(), before)

    def test_companion_record_cannot_escape_owned_packages(self):
        _, record = self.companion_package()
        outside = self.base / 'outside-package'
        outside.mkdir()
        escaped = dict(record, path=str(outside))
        manager.atomic_json(self.m.companion(self.game) / 'records/package.json', escaped)
        self.assertIsNone(self.separate_manager().package(self.game))

    def test_companion_record_cannot_follow_package_symlink(self):
        _, record = self.companion_package()
        outside = self.base / 'outside-package'
        outside.mkdir()
        link = self.m.companion(self.game) / 'packages/v9.9.9'
        self.link(link, outside, directory=True)
        linked = dict(record, path=str(link), version='9.9.9')
        manager.atomic_json(self.m.companion(self.game) / 'records/package.json', linked)
        self.assertIsNone(self.separate_manager().package(self.game))

    def test_companion_record_rejects_intermediate_payload_and_records_symlinks(self):
        package, _ = self.companion_package()
        optiscaler = package / 'optiscaler'
        outside_payloads = self.base / 'outside-optiscaler'
        optiscaler.rename(outside_payloads)
        self.link(optiscaler, outside_payloads, directory=True)
        self.assertIsNone(self.separate_manager().package(self.game))

        optiscaler.unlink()
        outside_payloads.rename(optiscaler)
        records = self.m.companion(self.game) / 'records'
        outside_records = self.base / 'outside-records'
        records.rename(outside_records)
        self.link(records, outside_records, directory=True)
        self.assertIsNone(self.separate_manager().package(self.game))

    def test_incomplete_config_manifest_is_rejected_before_game_mutation(self):
        package = self.package()
        self.m.cfg['packages'][str(package)]['files'] = {
            manager.DLL: manager.sha(package / manager.DLL)}
        before = self.native.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Prepare HelixSR'):
            self.m.preview(self.game['id'], 'install')
        self.assertEqual(self.native.read_bytes(), before)

    def test_unknown_package_route_is_rejected(self):
        self.package()
        with self.assertRaisesRegex(ValueError, 'Unknown package route'):
            self.m.package(self.game, 'unexpected')


class SteamBuildReviewTests(Fixtures):
    def changed_build(self):
        self.game['build'] = '100'
        self.package()
        self.action('install')
        self.game['build'] = '200'

    def test_build_review_is_read_only_and_all_file_actions_stay_blocked(self):
        self.changed_build()
        before = self.native.read_bytes()
        record = self.m.record_path(self.game).read_bytes()
        data = self.m.assess(self.game)
        report = data['steam_build_review']
        self.assertEqual((report['recorded_build'], report['current_build']), ('100', '200'))
        self.assertTrue(any(row['state'] == 'installed bytes match' for row in report['files']))
        for action in ('update', 'remove', 'disable', 'enable'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'Steam build changed'):
                self.m.preview(self.game['id'], action)
        self.assertFalse(data['installation_status']['can_modify'])
        self.assertEqual(self.native.read_bytes(), before)
        self.assertEqual(self.m.record_path(self.game).read_bytes(), record)
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_restored_original_is_reported_without_clearing_build_guard(self):
        self.changed_build()
        self.native.write_bytes(self.original)
        data = self.m.assess(self.game)
        row = next(row for row in data['steam_build_review']['files'] if row['path'] == self.native.name)
        self.assertEqual(row['state'], 'saved-original bytes match')
        self.assertFalse(data['installation_status']['can_modify'])
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_unexplained_replacement_is_reported_and_preserved(self):
        self.changed_build()
        replacement = self.original + b'new unexplained bytes'
        self.native.write_bytes(replacement)
        data = self.m.assess(self.game)
        row = next(row for row in data['steam_build_review']['files'] if row['path'] == self.native.name)
        self.assertEqual(row['state'], 'externally changed')
        self.assertFalse(data['installation_status']['can_modify'])
        self.assertEqual(self.native.read_bytes(), replacement)


class ReleaseMetadataTests(Fixtures):
    def separate_manager(self):
        return manager.Manager(self.home, self.m.settings)

    def official(self, digest='a', size=56650779):
        return dict(version='1.8.1', sha256=digest * 64, size=size,
                    url=f'https://github.com/{manager.REPO}/releases/download/v1.8.1/HelixSR-1.8.1.zip',
                    page=f'https://github.com/{manager.REPO}/releases/tag/v1.8.1')

    def quota(self, headers=None, code=403):
        return manager.urllib.error.HTTPError(manager.API, code, 'Fixture quota',
            headers if headers is not None else {'X-RateLimit-Remaining': '0',
                                               'X-RateLimit-Reset': str(time.time() + 3600)}, None)

    def test_primary_quota_uses_verified_web_metadata_and_survives_restart(self):
        with patch('manager.urllib.request.urlopen', side_effect=self.quota()) as api, \
                patch('manager.web_latest_release', return_value=self.official()) as web:
            release = self.m.check_update(force=True)
            again = self.separate_manager().check_update(force=True)
        self.assertIsNone(release['error'])
        self.assertEqual(release['metadata_source'], 'github-web')
        self.assertIsNone(release['etag'])
        self.assertEqual(release, again)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(web.call_count, 1)

    def test_primary_quota_rechecks_same_version_digest_and_size_after_click_cooldown(self):
        old = self.official()
        old.update(metadata_policy=manager.RELEASE_POLICY, checked_at=time.time() - 31,
                   api_limit_kind='primary', api_retry_at=time.time() + 3600, error=None)
        manager.atomic_json(self.m.settings / 'release.json', old)
        with patch('manager.urllib.request.urlopen') as api, \
                patch('manager.web_latest_release', return_value=self.official('b', 56650780)):
            release = self.m.check_update(force=True)
        api.assert_not_called()
        self.assertEqual(release['sha256'], 'b' * 64)
        self.assertEqual(release['size'], 56650780)

    def test_failed_web_verification_preserves_error_and_does_not_promote_cache(self):
        old = self.official()
        old.update(metadata_policy=manager.RELEASE_POLICY, error=None)
        manager.atomic_json(self.m.settings / 'release.json', old)
        with patch('manager.urllib.request.urlopen', side_effect=self.quota()), \
                patch('manager.web_latest_release', side_effect=ValueError('Missing digest')):
            release = self.m.check_update(force=True)
        self.assertIn('verification failed', release['error'])
        self.assertEqual(release['sha256'], old['sha256'])
        self.assertNotIn('checked_at', release)

    def test_secondary_quota_honors_retry_after_without_web_fallback(self):
        with patch('manager.urllib.request.urlopen', side_effect=self.quota({'Retry-After': '120'}, 429)) as api, \
                patch('manager.web_latest_release') as web:
            release = self.m.check_update(force=True)
            self.separate_manager().check_update(force=True)
        self.assertEqual(release['api_limit_kind'], 'secondary')
        self.assertIn('request limit', release['error'])
        self.assertEqual(api.call_count, 1)
        web.assert_not_called()

    def test_web_failure_has_persistent_click_cooldown(self):
        with patch('manager.urllib.request.urlopen', side_effect=self.quota()) as api, \
                patch('manager.web_latest_release', side_effect=ValueError('Missing digest')) as web:
            release = self.m.check_update(force=True)
            again = self.separate_manager().check_update(force=True)
        self.assertEqual(release, again)
        self.assertGreater(release['web_retry_at'], time.time())
        self.assertEqual(api.call_count, 1)
        self.assertEqual(web.call_count, 1)

    def test_web_secondary_limit_keeps_original_primary_reset(self):
        reset = time.time() + 3600
        with patch('manager.urllib.request.urlopen', side_effect=self.quota({
                'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(reset)})) as api, \
                patch('manager.web_latest_release', side_effect=self.quota({'Retry-After': '120'}, 429)) as web:
            release = self.m.check_update(force=True)
            again = self.separate_manager().check_update(force=True)
        self.assertEqual(release, again)
        self.assertEqual(release['api_retry_at'], reset)
        self.assertGreater(release['web_retry_at'], time.time() + 110)
        self.assertLess(release['web_retry_at'], reset)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(web.call_count, 1)

    def test_new_api_quota_cannot_bypass_longer_web_retry_deadline(self):
        old = dict(error='Web limit', api_limit_kind='primary', api_retry_at=time.time() - 1,
                   web_retry_at=time.time() + 120)
        manager.atomic_json(self.m.settings / 'release.json', old)
        with patch('manager.urllib.request.urlopen', side_effect=self.quota()) as api, \
                patch('manager.web_latest_release') as web:
            release = self.m.check_update(force=True)
        self.assertEqual(release['web_retry_at'], old['web_retry_at'])
        self.assertGreater(release['api_retry_at'], old['api_retry_at'])
        self.assertEqual(api.call_count, 1)
        web.assert_not_called()

    def test_generic_or_malformed_403_never_uses_web_fallback(self):
        for headers in ({}, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': 'nan'},
                        {'X-RateLimit-Remaining': '1', 'X-RateLimit-Reset': str(time.time() + 3600)}):
            with self.subTest(headers=headers):
                (self.m.settings / 'release.json').unlink(missing_ok=True)
                with patch('manager.urllib.request.urlopen', side_effect=self.quota(headers)), \
                        patch('manager.web_latest_release') as web:
                    release = self.m.check_update(force=True)
                self.assertIn('HTTP 403', release['error'])
                self.assertNotIn('version', release)
                web.assert_not_called()

    def test_429_missing_retry_after_uses_minimum_backoff(self):
        kind, retry = manager.github_pause(self.quota({}, 429), 1000)
        self.assertEqual((kind, retry), ('secondary', 1060))

    def test_expired_api_quota_returns_to_api_and_clears_backoff(self):
        old = self.official()
        old.update(metadata_policy=manager.RELEASE_POLICY, checked_at=0,
                   api_limit_kind='primary', api_retry_at=time.time() - 1, error=None)
        manager.atomic_json(self.m.settings / 'release.json', old)
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.geturl.return_value = manager.API
        response.read.return_value = json.dumps(dict(tag_name='v1.8.1', html_url=old['page'],
            assets=[dict(name='HelixSR-1.8.1.zip', browser_download_url=old['url'],
                         digest='sha256:' + old['sha256'], size=old['size'])])).encode()
        with patch('manager.urllib.request.urlopen', return_value=response), \
                patch('manager.web_latest_release') as web:
            release = self.m.check_update(force=True)
        self.assertEqual(release['metadata_source'], 'github-api')
        self.assertNotIn('api_retry_at', release)
        web.assert_not_called()

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
        self.assertFalse(data['optiscaler']['helix_configured'])
        self.assertFalse(data['optiscaler']['involved'])
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

    def test_enabled_managed_fresh_log_is_not_current_output_proof(self):
        self.package()
        self.action('install')
        write(self.root / 'helixsr.log', 'network running\n')
        data = self.inspect([dict(pid=123, env={}, started_at=time.time() - 10)])
        self.assertNotIn('reports neural output', data['helix_runtime'])
        self.assertIn('current runtime unverified', data['helix_runtime'])


class RecoveryAndOptiScalerRegressionTests(Fixtures):
    def test_new_upstream_fg_dependency_updates_old_records_without_enabling_fg(self):
        self.optiscaler_fixture()
        self.action('install')
        package = self.m.package(self.game)[1]
        write(package / 'amd-fsr' / manager.AMD_FG, b'fixture AMD FG provider')
        with (package / 'optiscaler/OptiScaler.ini').open('a') as f:
            f.write('FfxDx12FGPath=auto\n')
        self.sync_package_record(package)
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
        self.sync_package_record(package)
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
        self.reviewed_package(self.prepared)
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

    def competing_package(self, folder, version_, digest, prepared_at):
        for name in manager.PACKAGE_FILES:
            write(folder / name, (self.prepared / name).read_bytes())
        write(folder / manager.DLL, pe(ffx=True, helix=True) + version_.encode())
        record = dict(path=str(folder), version=version_, release_sha256=digest,
                      prepared_at=prepared_at,
                      files={name: manager.sha(folder / name) for name in manager.PACKAGE_FILES})
        self.m.cfg['packages'][str(folder)] = record
        return folder

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

    def test_latest_installs_exact_official_release_when_newer_cache_exists(self):
        future = self.competing_package(self.base / 'future/v9.9.9', '9.9.9', 'f' * 64, 500)
        _, job = self.latest()
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(manager.sha(self.native), manager.sha(self.prepared / manager.DLL))
        self.assertNotEqual(manager.sha(self.native), manager.sha(future / manager.DLL))

    def test_latest_installs_exact_digest_when_same_version_asset_was_replaced(self):
        replaced = self.competing_package(self.base / 'replaced/v1.2.3', '1.2.3', 'b' * 64, 500)
        _, job = self.latest()
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(manager.sha(self.native), manager.sha(self.prepared / manager.DLL))
        self.assertNotEqual(manager.sha(self.native), manager.sha(replaced / manager.DLL))

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

    def test_latest_preserves_explicit_executable_and_target(self):
        choice = self.dual_executables()
        preview = self.m.preview_latest(self.game['id'], executable=choice)
        self.assertEqual(preview['selected_executable'], choice)
        job = self.m.execute_latest(preview['token'])
        self.join_worker()
        self.assertEqual(self.m.jobs[job['id']]['state'], 'completed', self.m.jobs[job['id']]['message'])
        self.assertTrue((self.root / 'DX12/dxgi.dll').is_file())
        self.assertFalse((self.root / 'DX11/dxgi.dll').exists())

    def test_latest_rejects_executable_byte_change_before_mutation(self):
        choice = self.dual_executables()
        preview = self.m.preview_latest(self.game['id'], executable=choice)
        original_prepare = self.m.prepare
        def changed_prepare(*args):
            prepared = original_prepare(*args)
            with (self.root / choice).open('ab') as stream:
                stream.write(b'changed after review')
            return prepared
        with patch.object(self.m, 'prepare', side_effect=changed_prepare):
            job = self.m.execute_latest(preview['token'])
            self.join_worker()
        self.assertEqual(self.m.jobs[job['id']]['state'], 'failed')
        self.assertFalse((self.root / 'DX12/dxgi.dll').exists())
        self.assertFalse(self.m.record(self.game))

    def test_latest_adopts_legacy_then_installs_prepared_version(self):
        write(self.native, pe(ffx=True, helix=True))
        write(self.native.with_name(self.native.stem + '.original.dll'), self.original)
        _, job = self.latest()
        self.assertEqual(job['state'], 'completed', job.get('message'))
        self.assertEqual(self.m.record(self.game)['version'], '1.2.3')
        self.action('remove')
        self.assertEqual(self.native.read_bytes(), self.original)


class TransactionTests(Fixtures):
    def test_missing_managed_native_target_retains_recorded_state_and_blocks_changes(self):
        self.package()
        self.action('install')
        for enabled in (True, False):
            if not enabled:
                self.action('disable')
            with self.subTest(enabled=enabled):
                receipt = self.m.record(self.game)
                live_bytes = self.native.read_bytes()
                self.native.unlink()
                try:
                    data = self.m.assess_safe(self.game)
                    self.assertTrue(data['managed'])
                    self.assertEqual(data['route'], 'direct')
                    self.assertEqual(data['enabled'], enabled)
                    self.assertEqual(data['installed_version'], receipt['version'])
                    self.assertEqual(data['targets'], receipt['targets'])
                    self.assertEqual(data['compatibility'], 'blocked')
                    self.assertIn('Managed files changed; ownership needs review before further changes: '
                                  + self.native.name + ' (current state: missing)', data['reasons'])
                    for action in ('update', 'remove', 'disable', 'enable'):
                        with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                            self.m.preview(self.game['id'], action)
                    self.assertEqual(self.m.record(self.game), receipt)
                    self.assertFalse(self.native.exists())
                finally:
                    self.native.write_bytes(live_bytes)
        self.action('remove')

    def test_managed_nested_native_targets_survive_new_discovery_preference(self):
        nested = self.root / 'SDK/bin/signed' / self.native.name
        nested.parent.mkdir(parents=True)
        self.native.rename(nested)
        self.package()
        self.action('install')
        receipt = self.m.record(self.game)
        self.assertEqual(receipt['targets'], [str(nested)])
        # Older discovery could select this nested SR DLL even alongside an
        # ordinary root loader. Its receipt must continue to own only the SR DLL.
        unrelated = write(self.root / manager.DLL, pe() + b'ordinary game loader')
        unrelated_bytes = unrelated.read_bytes()
        for action in ('update', 'disable', 'remove'):
            with self.subTest(action=action):
                data = self.m.assess(self.game)
                self.assertEqual(data['compatibility'], 'candidate')
                self.assertEqual(data['route'], 'direct')
                self.assertEqual(data['targets'], receipt['targets'])
                self.action(action)
                self.assertEqual(unrelated.read_bytes(), unrelated_bytes)
                if action == 'update':
                    self.assertEqual(self.m.record(self.game)['targets'], receipt['targets'])
                    self.assertEqual(self.m.record(self.game)['baseline'], receipt['baseline'])
                else:
                    self.assertEqual(nested.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))

    def test_log_discovery_checks_each_directory_once_and_preserves_unique_logs(self):
        logfile = write(self.root / 'HelixSR/helixsr.log', 'fixture network running\n')
        tree = [(self.root, [f'asset-{n}.bin' for n in range(1000)]),
                (logfile.parent, ['helixsr.log'])]
        with patch('awareness.safe_log', wraps=awareness.safe_log) as checks:
            data = awareness.awareness(self.game, tree, self.home, 'direct', self.root)
        self.assertLessEqual(checks.call_count, 3 * len(tree))
        self.assertEqual([item['path'] for item in data['logs']], [str(logfile)])
        self.assertIn('fixture network running', data['logs'][0]['excerpt'])

    def test_library_refresh_is_offline_and_defers_package_verification_until_details(self):
        self.package()
        with patch('manager.discover', return_value=([self.game], [])), \
                patch.object(self.m, 'package', wraps=self.m.package) as packages, \
                patch('manager.awareness', wraps=awareness.awareness) as evidence_scan, \
                patch('manager.urllib.request.urlopen', side_effect=OSError('offline')):
            library_data = self.m.refresh()['games'][0]
            self.assertEqual(library_data['compatibility'], 'candidate')
            self.assertIsNone(library_data['package_version'])
            packages.assert_not_called()
            evidence_scan.assert_not_called()
            self.assertTrue(library_data['awareness_deferred'])
            self.assertIsNone(library_data['optiscaler']['present'])
            self.assertEqual(library_data['framegen'], [])
            details = self.m.assess(self.game)
            evidence_scan.assert_called_once()
            self.assertEqual(details['package_version'], '1.2.3')
            self.assertEqual(details['compatibility'], library_data['compatibility'])
            packages.assert_called_once()
            self.action('install')
            self.action('disable')
            self.action('enable')
            self.action('remove')
            self.assertEqual(self.native.read_bytes(), self.original)

    def test_library_summary_retains_anti_cheat_running_and_owned_hash_guards(self):
        self.package()
        self.action('install')
        with patch('manager.discover', return_value=([self.game], [])):
            write(self.root / 'EasyAntiCheat/protected.txt', 'fixture')
            data = self.m.refresh()['games'][0]
            self.assertEqual(data['compatibility'], 'blocked')
            self.assertTrue(any('Anti-cheat' in reason for reason in data['reasons']))
            (self.root / 'EasyAntiCheat/protected.txt').unlink()
            with patch('manager.active_processes', return_value=[{'pid': 42}]):
                self.assertEqual(self.m.refresh()['games'][0]['compatibility'], 'blocked')
            write(self.native, b'externally changed')
            data = self.m.refresh()['games'][0]
            self.assertEqual(data['compatibility'], 'blocked')
            self.assertTrue(any('Managed files changed' in reason for reason in data['reasons']))
            self.assertFalse(data['installation_status']['can_restore'])

    def test_failed_shortcut_scan_does_not_abort_other_library_entries(self):
        broken = dict(self.game, id='shortcut:broken', source='Steam shortcut', launch_options='%command%')
        original_assess = self.m.assess
        def assess(game, **kwargs):
            if game['id'] == broken['id']:
                raise ValueError('Game scan file limit exceeded')
            return original_assess(game, **kwargs)
        with patch('manager.discover', return_value=([broken, self.game], [])), patch.object(self.m, 'assess', side_effect=assess):
            rows = self.m.refresh()['games']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['compatibility'], 'blocked')
        self.assertEqual(rows[0]['launch_options'], '%command%')
        self.assertIn('Game scan file limit exceeded', rows[0]['reasons'])
        self.assertEqual(rows[1]['compatibility'], 'candidate')

    def test_invalid_receipt_shapes_block_game_instead_of_aborting_library(self):
        for invalid in (['invalid'], {'route': 'direct'}, {'route': 'optiscaler', 'target': {}}):
            with self.subTest(receipt=invalid), patch.object(self.m, 'record', return_value=invalid):
                data = self.m.assess_safe(self.game, detailed=False)
                self.assertEqual(data['compatibility'], 'blocked')
                self.assertFalse(data['installation_status']['can_modify'])
                self.assertTrue(data['reasons'])

    def test_god_of_war_2018_is_unsupported_even_with_dlss_and_dx12_confirmation(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        self.game.update(source='Steam', appid='1593500', name='God of War')
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'unsupported')
        self.assertFalse(data['dx12_confirmation_needed'])
        self.assertFalse(data['executable_choices'])
        status = data['installation_status']
        self.assertEqual(status['label'], 'Unsupported')
        self.assertIn('DirectX 11', status['summary'])
        self.assertIn('plugin currently installs HelixSR only through its validated DirectX 12 route', status['summary'])
        self.assertIn('Upstream HelixSR 2.0 Scaler supports DirectX 11 upscaling', status['summary'])
        self.assertEqual(status['issues'][0]['title'], 'DX11 route not verified')
        self.assertIn('Upstream HelixSR 2.0 Scaler supports DirectX 11 upscaling', status['issues'][0]['steps'][0])
        self.assertFalse(status['can_modify'])
        self.assertFalse(status['can_restore'])
        for action in ('install', 'update', 'enable', 'adopt'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'DirectX 11'):
                self.m.preview(self.game['id'], action, dx12_confirmed=True)
        with patch.object(self.m, 'check_update', return_value=dict(version='1.8.1')):
            with self.assertRaisesRegex(ValueError, 'DirectX 11'):
                self.m.preview_latest(self.game['id'], dx12_confirmed=True)
        self.assertFalse(self.m.previews)
        self.assertFalse(self.m.record(self.game))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_god_of_war_2018_can_restore_owned_install_but_never_reenable(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        self.package()
        self.action('install')
        self.game.update(source='Steam', appid='1593500', name='God of War')
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'unsupported')
        self.assertTrue(data['installation_status']['selectable'])
        self.assertTrue(data['installation_status']['can_restore'])
        for action in ('update', 'enable'):
            with self.assertRaisesRegex(ValueError, 'DirectX 11'):
                self.m.preview(self.game['id'], action, dx12_confirmed=True)
        self.action('disable')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        with self.assertRaisesRegex(ValueError, 'DirectX 11'):
            self.m.preview(self.game['id'], 'enable', dx12_confirmed=True)
        self.action('remove')
        self.assertFalse(self.m.record(self.game))
        self.assertTrue((self.root / 'nvngx_dlss.dll').is_file())

    def test_unsupported_renderer_does_not_bypass_restore_hash_or_running_guards(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        self.package()
        self.action('install')
        self.game.update(source='Steam', appid='1593500', name='God of War')
        preview = self.m.preview(self.game['id'], 'remove')
        with patch('manager.active_processes', return_value=[{'pid': 42}]):
            data = self.m.assess(self.game)
            self.assertEqual(data['compatibility'], 'blocked')
            self.assertFalse(data['installation_status']['can_restore'])
            with self.assertRaises(ValueError):
                self.m.execute(preview['token'])
        write(self.root / 'dxgi.dll', b'changed by another mod')
        for action in ('disable', 'remove'):
            with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                self.m.preview(self.game['id'], action)
        self.assertFalse(self.m.assess(self.game)['installation_status']['can_restore'])
        self.assertEqual((self.root / 'dxgi.dll').read_bytes(), b'changed by another mod')
        self.assertTrue(self.m.record(self.game))

    def test_selected_executable_requires_own_dx12_evidence(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        write(self.root / 'Game.exe', pe() + b'largest DX11 binary' * 1024)
        write(self.root / 'UnusedDX12.exe', pe(dx12=True))
        data = self.m.assess(self.game)
        self.assertEqual(Path(data['main_exe']).name, 'Game.exe')
        self.assertTrue(data['dx12_confirmation_needed'])

    def test_dx12_confirmation_is_recorded_for_the_exact_optiscaler_executable(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        write(self.root / 'Example.exe', pe())
        self.package()
        with self.assertRaisesRegex(ValueError, 'Confirm that this game is set to DirectX 12'):
            self.m.preview(self.game['id'], 'install')
        preview = self.m.preview(self.game['id'], 'install', dx12_confirmed=True)
        self.m.execute(preview['token'])
        record = self.m.record(self.game)
        self.assertEqual(record['dx12_confirmation']['selected_executable'], 'Example.exe')
        self.assertEqual(record['dx12_confirmation']['executable_sha256'], manager.sha(self.root / 'Example.exe'))
        self.assertFalse(self.m.assess(self.game)['dx12_confirmation_needed'])
        self.m.preview(self.game['id'], 'update')
        write(self.root / 'Example.exe', pe() + b'changed executable bytes')
        self.assertTrue(self.m.assess(self.game)['dx12_confirmation_needed'])
        with self.assertRaisesRegex(ValueError, 'Confirm that this game is set to DirectX 12'):
            self.m.preview(self.game['id'], 'update')
        preview = self.m.preview(self.game['id'], 'update', dx12_confirmed=True)
        self.m.execute(preview['token'])
        record = self.m.record(self.game)
        self.assertEqual(record['dx12_confirmation']['executable_sha256'], manager.sha(self.root / 'Example.exe'))
        self.assertFalse(self.m.assess(self.game)['dx12_confirmation_needed'])
        record.pop('dx12_confirmation')
        manager.atomic_json(self.m.record_path(self.game), record)
        self.assertTrue(self.m.assess(self.game)['dx12_confirmation_needed'])

    def test_confirmed_executable_hash_uses_the_stat_identity_cache(self):
        executable = self.root / 'Example.exe'
        with patch('manager.sha', wraps=manager.sha) as digest:
            self.assertEqual(manager.confirmed_executable_sha(executable), manager.confirmed_executable_sha(executable))
        self.assertEqual(digest.call_count, 1)

    def test_unused_dx12_is_not_automatically_selected_without_example(self):
        self.native.unlink()
        (self.root / 'Example.exe').unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        write(self.root / 'Game.exe', pe() + b'largest DX11 binary' * 1024)
        write(self.root / 'UnusedDX12.exe', pe(dx12=True))
        data = self.m.assess(self.game)
        self.assertEqual(data['selected_executable'], 'Game.exe')
        self.assertTrue(data['dx12_confirmation_needed'])
        self.assertEqual({x['path'] for x in data['executable_choices']}, {'Game.exe', 'UnusedDX12.exe'})

    def test_dual_folder_choice_survives_install_update_disable_remove(self):
        choice = self.dual_executables()
        self.package()
        default = self.m.assess(self.game)
        self.assertEqual(default['selected_executable'], 'DX11/Game.exe')
        self.assertTrue(default['dx12_confirmation_needed'])
        data = self.m.assess(self.game, executable=choice)
        self.assertEqual(Path(data['target']), self.root / 'DX12')
        self.assertFalse(data['dx12_confirmation_needed'])
        preview = self.m.preview(self.game['id'], 'install', executable=choice)
        self.assertEqual(preview['selected_executable'], choice)
        self.m.execute(preview['token'])
        receipt = self.m.record(self.game)
        self.assertEqual(receipt['selected_executable'], choice)
        self.assertFalse(self.m.assess(self.game)['executable_choices'])
        self.assertFalse((self.root / 'DX11/dxgi.dll').exists())
        self.action('update')
        self.assertEqual(self.m.record(self.game)['baseline'], receipt['baseline'])
        self.assertEqual(self.m.record(self.game)['target'], receipt['target'])
        self.action('disable')
        self.assertFalse((self.root / 'DX12/dxgi.dll').exists())
        self.action('remove')
        self.assertFalse(self.m.record(self.game))

    def test_prepared_choice_rejects_executable_byte_change(self):
        choice = self.dual_executables()
        self.package()
        token = self.m.preview(self.game['id'], 'install', executable=choice)['token']
        with (self.root / choice).open('ab') as stream:
            stream.write(b'changed after review')
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)
        self.assertFalse((self.root / 'DX12/dxgi.dll').exists())

    def test_invalid_executable_choices_are_rejected(self):
        self.dual_executables()
        write(self.root / 'Launcher.exe', pe(dx12=True))
        write(self.root / 'Small32.exe', pe(machine=0x14c))
        for choice in ('../outside.exe', str(self.root / 'DX12/Game.exe'),
                       'Launcher.exe', 'Small32.exe', 'missing.exe', '', 12):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                self.m.assess(self.game, executable=choice)

    def test_invalid_default_exposes_alternative_without_bypassing_other_blocks(self):
        self.native.unlink()
        (self.root / 'Example.exe').unlink()
        write(self.root / 'Game32.exe', pe(machine=0x14c) + b'large default' * 1024)
        write(self.root / 'DX12/Game.exe', pe(dx12=True))
        write(self.root / 'DX12/nvngx_dlss.dll', pe())
        default = self.m.assess(self.game)
        self.assertEqual(default['compatibility'], 'blocked')
        self.assertTrue(default['executable_selection_needed'])
        selected = self.m.assess(self.game, executable='DX12/Game.exe')
        self.assertEqual(selected['compatibility'], 'candidate')
        write(self.root / 'easyanticheat.dll', b'protected')
        self.assertFalse(self.m.assess(self.game)['executable_selection_needed'])
        self.assertEqual(self.m.assess(self.game, executable='DX12/Game.exe')['compatibility'], 'blocked')

    def test_symlink_executable_choice_is_rejected(self):
        choice = self.dual_executables()
        self.link(self.root / 'Alias.exe', self.root / choice)
        with self.assertRaises(ValueError):
            self.m.assess(self.game, executable='Alias.exe')

    def test_direct_and_managed_executable_overrides_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unmanaged OptiScaler'):
            self.m.assess(self.game, executable='Example.exe')
        choice = self.dual_executables()
        self.package()
        self.m.execute(self.m.preview(self.game['id'], 'install', executable=choice)['token'])
        with self.assertRaisesRegex(ValueError, 'unmanaged OptiScaler'):
            self.m.assess(self.game, executable=choice)

    def test_missing_executable_does_not_block_cleanup_or_migrate_old_record(self):
        choice = self.dual_executables()
        self.package()
        self.m.execute(self.m.preview(self.game['id'], 'install', executable=choice)['token'])
        (self.root / choice).unlink()
        with self.assertRaisesRegex(ValueError, 'executable is missing'):
            self.m.preview(self.game['id'], 'update', True)
        self.action('disable')
        self.action('remove')
        self.m.execute(self.m.preview(self.game['id'], 'install', True)['token'])
        receipt = self.m.record(self.game)
        receipt.pop('selected_executable')
        manager.atomic_json(self.m.record_path(self.game), receipt)
        (self.root / 'DX11/Game.exe').unlink()
        self.action('disable')
        self.assertNotIn('selected_executable', self.m.record(self.game))
        self.action('remove')

    def install_overlay_fixture(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        package = self.package()
        self.action('install')
        return package

    def edit_overlay_fixture(self):
        config = self.root / 'OptiScaler.ini'
        content = config.read_bytes().replace(b'Dx12Upscaler=fsr31', b'Dx12Upscaler=xess')
        content = content.replace(b'FfxDx12Path=Z:', b'FfxDx12Path=user:')
        content = content.replace(b'\n', b'\r\n')
        content += b'; user comment\r\n[FrameGeneration]\r\nFGType=none\r\nEnabled=false\r\n[Menu]\r\nOverlayMenuKey=0x24\r\n'
        write(config, content)
        fake = b'; user NVAPI choices\r\n[Settings]\r\nEnable=true\r\n'
        write(self.root / 'fakenvapi.ini', fake)
        return content, fake

    def test_overlay_update_preserves_choices_and_only_pins_backend_paths(self):
        self.install_overlay_fixture()
        baseline = self.m.record(self.game)['baseline']
        edited, fake = self.edit_overlay_fixture()
        preview = self.m.preview(self.game['id'], 'update')
        self.assertIn('configuration edits are preserved', preview['warning'])
        self.m.execute(preview['token'])
        result = (self.root / 'OptiScaler.ini').read_bytes()
        expected = edited.replace(b'Dx12Upscaler=xess', b'Dx12Upscaler=fsr31').replace(b'FfxDx12Path=user:', b'FfxDx12Path=Z:')
        self.assertEqual(result, expected)
        self.assertEqual((self.root / 'fakenvapi.ini').read_bytes(), fake)
        self.assertEqual(self.m.record(self.game)['baseline'], baseline)

    def test_preexisting_fakenvapi_settings_survive_install_update_and_restore(self):
        path = self.root / 'fakenvapi.ini'
        original = b'; existing choices\r\n[Settings]\r\nEnable=false\r\n'
        write(path, original)
        self.install_overlay_fixture()
        self.assertEqual(path.read_bytes(), original)
        receipt = self.m.record(self.game)
        self.assertEqual(receipt['baseline']['fakenvapi.ini'], hashlib.sha256(original).hexdigest())
        edited = original + b'CustomOption=kept\r\n'
        write(path, edited)
        self.assertEqual(self.m.assess(self.game)['compatibility'], 'candidate')
        self.action('update')
        self.assertEqual(path.read_bytes(), edited)
        self.action('disable')
        self.assertEqual(path.read_bytes(), original)
        self.action('enable')
        self.assertEqual(path.read_bytes(), edited)
        self.action('remove')
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.m.record(self.game))
        records = list((self.m.companion(self.game) / 'records').glob('config-*.json'))
        self.assertTrue(any(manager.load_json(p)['configurations']['fakenvapi.ini']['content'].encode() == edited
                            for p in records))

    def test_legacy_preexisting_fakenvapi_edit_is_not_binary_ownership_conflict(self):
        # Older installers overwrote a pre-existing INI with their defaults.
        original = b'[Settings]\nEnable=false\n'
        path = write(self.root / 'fakenvapi.ini', original)
        package = self.install_overlay_fixture()
        write(path, (package / 'optiscaler/fakenvapi.ini').read_bytes())
        receipt = self.m.record(self.game)
        receipt['current']['fakenvapi.ini'] = manager.sha(path)
        manager.atomic_json(self.m.record_path(self.game), receipt)
        edited = b'[Settings]\nEnable=true\n'
        write(path, edited)
        self.action('update')
        self.assertEqual(path.read_bytes(), edited)
        self.action('remove')
        self.assertEqual(path.read_bytes(), original)

    def test_preexisting_config_missing_or_changed_original_still_blocks(self):
        original = b'[Settings]\nEnable=false\n'
        path = write(self.root / 'fakenvapi.ini', original)
        self.install_overlay_fixture()
        edited = b'[Settings]\nEnable=true\n'
        write(path, edited)
        backup = self.m.companion(self.game) / 'originals/fakenvapi.ini'
        receipt = self.m.record(self.game)
        for content in (None, b'[Settings]\nForeign=true\n'):
            with self.subTest(content=content):
                backup.unlink(missing_ok=True)
                if content is not None:
                    write(backup, content)
                for action in ('update', 'disable', 'remove'):
                    with self.assertRaisesRegex(ValueError, 'Original configuration backup'):
                        self.m.preview(self.game['id'], action)
                self.assertEqual(path.read_bytes(), edited)
                self.assertEqual(self.m.record(self.game), receipt)

    def test_disabled_preexisting_config_change_is_not_accepted(self):
        path = write(self.root / 'fakenvapi.ini', b'[Settings]\nEnable=false\n')
        self.install_overlay_fixture()
        self.action('disable')
        edited = b'[Settings]\nAnotherMod=true\n'
        write(path, edited)
        for action in ('enable', 'update', 'remove'):
            with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                self.m.preview(self.game['id'], action)
        self.assertEqual(path.read_bytes(), edited)

    def test_preexisting_config_symlinked_original_directory_blocks(self):
        path = write(self.root / 'fakenvapi.ini', b'[Settings]\nEnable=false\n')
        self.install_overlay_fixture()
        originals = self.m.companion(self.game) / 'originals'
        moved = originals.with_name('originals-held')
        originals.rename(moved)
        try:
            try:
                originals.symlink_to(moved, target_is_directory=True)
            except OSError:
                self.skipTest('Directory symlinks unavailable on this host')
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                self.m.preview(self.game['id'], 'update')
            self.assertTrue(path.is_file())
        finally:
            if originals.is_symlink():
                originals.unlink()
            moved.rename(originals)

    def test_verified_original_restoration_is_explained_but_not_unblocked(self):
        self.package()
        self.action('install')
        write(self.native, self.original)
        data = self.m.assess(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        issue = next(i for i in data['installation_status']['issues'] if i['code'] == 'managed_files_changed')
        self.assertEqual(issue['title'], 'Original file restored')
        self.assertIn('(current state: matches recorded original)', issue['reason'])
        for action in ('update', 'disable', 'remove'):
            with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                self.m.preview(self.game['id'], action)
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_configuration_record_failure_preserves_edited_live_files(self):
        self.install_overlay_fixture()
        edited, fake = self.edit_overlay_fixture()
        prior = self.m.record(self.game)
        original = manager.atomic_json
        def fail_config(path, value):
            if Path(path).name.startswith('config-'):
                raise OSError('configuration record storage failed')
            return original(path, value)
        with patch('manager.atomic_json', side_effect=fail_config), self.assertRaisesRegex(OSError, 'storage failed'):
            self.action('disable')
        self.assertEqual((self.root / 'OptiScaler.ini').read_bytes(), edited)
        self.assertEqual((self.root / 'fakenvapi.ini').read_bytes(), fake)
        self.assertEqual(self.m.record(self.game), prior)

    def test_update_failure_rolls_back_exact_configuration_and_record(self):
        self.install_overlay_fixture()
        edited, fake = self.edit_overlay_fixture()
        prior = self.m.record(self.game)
        original = self.m.copy_atomic
        failed = False
        def fail_after_copy(source, dest, digest=None):
            nonlocal failed
            original(source, dest, digest)
            if not failed:
                failed = True
                raise OSError('payload replacement failed')
        with patch.object(self.m, 'copy_atomic', side_effect=fail_after_copy), self.assertRaisesRegex(OSError, 'replacement failed'):
            self.action('update')
        self.assertEqual((self.root / 'OptiScaler.ini').read_bytes(), edited)
        self.assertEqual((self.root / 'fakenvapi.ini').read_bytes(), fake)
        self.assertEqual(self.m.record(self.game), prior)

    def test_malformed_saved_configuration_container_blocks(self):
        self.install_overlay_fixture()
        rec = self.m.record(self.game)
        for invalid in (None, [], {'unknown.ini': {'content': '', 'sha256': 'a' * 64}},
                        {'dxgi.dll': {'content': '', 'sha256': 'a' * 64}}):
            rec['saved_configs'] = invalid
            manager.atomic_json(self.m.record_path(self.game), rec)
            self.assertEqual(self.m.assess_safe(self.game)['compatibility'], 'blocked')

    def test_malformed_configuration_blocks_and_misplaced_key_never_changes_payload(self):
        self.install_overlay_fixture()
        config = self.root / 'OptiScaler.ini'
        config.write_text('[Upscalers]\nDx12Upscaler=fsr31\nDx12Upscaler=xess\n')
        with self.assertRaises(ValueError):
            self.action('disable')
        config.write_text('[Other]\nDx12Upscaler=xess\n')
        before = config.read_bytes()
        proxy = (self.root / 'dxgi.dll').read_bytes()
        with self.assertRaisesRegex(ValueError, 'misplaced'):
            self.action('update')
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual((self.root / 'dxgi.dll').read_bytes(), proxy)

    def test_overlay_disable_enable_remove_keeps_configuration_records(self):
        self.install_overlay_fixture()
        edited, fake = self.edit_overlay_fixture()
        self.action('disable')
        rec = self.m.record(self.game)
        self.assertFalse((self.root / 'OptiScaler.ini').exists())
        self.assertEqual(rec['saved_configs']['OptiScaler.ini']['content'].encode(), edited)
        self.action('enable')
        restored = (self.root / 'OptiScaler.ini').read_bytes()
        self.assertIn(b'OverlayMenuKey=0x24\r\n', restored)
        self.assertIn(b'FGType=none\r\nEnabled=false\r\n', restored)
        self.assertEqual((self.root / 'fakenvapi.ini').read_bytes(), fake)
        self.action('remove')
        self.assertFalse(self.m.record(self.game))
        records = list((self.m.companion(self.game) / 'records').glob('config-*.json'))
        contents = [manager.load_json(path)['configurations']['OptiScaler.ini']['content'].encode() for path in records]
        self.assertIn(edited, contents)
        self.assertIn(restored, contents)
        self.assertFalse((self.root / 'OptiScaler.ini').exists())

    def test_overlay_edit_after_preview_blocks_without_discarding_edit(self):
        self.install_overlay_fixture()
        token = self.m.preview(self.game['id'], 'disable')['token']
        edited, _ = self.edit_overlay_fixture()
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)
        self.assertEqual((self.root / 'OptiScaler.ini').read_bytes(), edited)

    def test_overlay_binary_and_network_drift_still_block(self):
        self.install_overlay_fixture()
        for rel in ('dxgi.dll', 'fakenvapi.dll', 'HelixSR/helixsr_weights.bin'):
            with self.subTest(rel=rel):
                path = self.root / rel
                original = path.read_bytes()
                write(path, original + b'tamper')
                with self.assertRaisesRegex(ValueError, 'Managed files changed'):
                    self.m.preview(self.game['id'], 'remove')
                write(path, original)

    def test_overlay_invalid_utf8_oversized_configs_block_but_missing_introduced_config_can_restore(self):
        self.install_overlay_fixture()
        path = self.root / 'OptiScaler.ini'
        original = path.read_bytes()
        for content in (b'\xff', b'x' * (manager.CONFIG_LIMIT + 1), b'key=\x00'):
            with self.subTest(content_length=len(content)):
                write(path, content)
                with self.assertRaises(ValueError):
                    self.m.preview(self.game['id'], 'disable')
        path.unlink()
        data = self.m.assess(self.game)
        self.assertTrue(data['installation_status']['can_restore'])
        for action in ('update', 'enable'):
            with self.assertRaises(ValueError):
                self.m.preview(self.game['id'], action)
        self.m.preview(self.game['id'], 'disable')
        write(path, original)

    def test_overlay_symlink_and_hardlink_configs_block(self):
        self.install_overlay_fixture()
        path = self.root / 'OptiScaler.ini'
        outside = write(self.base / 'foreign.ini', path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            pass
        else:
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                self.m.preview(self.game['id'], 'disable')
            path.unlink()
        os.link(outside, path)
        with self.assertRaisesRegex(ValueError, 'Unsafe managed configuration'):
            self.m.preview(self.game['id'], 'disable')

    def test_retained_config_change_after_preview_blocks_enable(self):
        self.install_overlay_fixture()
        self.edit_overlay_fixture()
        self.action('disable')
        token = self.m.preview(self.game['id'], 'enable')['token']
        rec = self.m.record(self.game)
        saved = rec['saved_configs']['OptiScaler.ini']
        saved['content'] += '; another edit\n'
        import hashlib
        saved['sha256'] = hashlib.sha256(saved['content'].encode()).hexdigest()
        manager.atomic_json(self.m.record_path(self.game), rec)
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)

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

    def test_package_drift_during_copy_rolls_back_without_unverified_bytes(self):
        package = self.package()
        token = self.m.preview(self.game['id'], 'install')['token']
        real_copy = manager.shutil.copy2
        changed = [False]
        def copy(src, dst, *args, **kwargs):
            if not changed[0] and Path(src) == package / manager.DLL:
                changed[0] = True
                write(src, b'changed between verification and copy')
            return real_copy(src, dst, *args, **kwargs)
        with patch('manager.shutil.copy2', side_effect=copy):
            with self.assertRaisesRegex(ValueError, 'Copy verification failed'):
                self.m.execute(token)
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))
        self.assertFalse((self.m.companion(self.game) / 'transaction').exists())

    def test_execute_keeps_the_verified_package_selected_for_its_fingerprint(self):
        selected = self.package()
        self.m.cfg['packages'][str(selected)]['prepared_at'] = 100
        token = self.m.preview(self.game['id'], 'install')['token']
        real_fingerprint = self.m.fingerprint
        added = [False]
        def fingerprint(*args, **kwargs):
            result = real_fingerprint(*args, **kwargs)
            if not added[0]:
                added[0] = True
                newer = self.base / 'appeared-after-fingerprint/v1.2.3'
                for name in manager.PACKAGE_FILES:
                    write(newer / name, (selected / name).read_bytes())
                write(newer / manager.DLL, pe(ffx=True, helix=True) + b'newer valid payload')
                record = dict(self.m.cfg['packages'][str(selected)], path=str(newer), prepared_at=200)
                record['files'] = {name: manager.sha(newer / name) for name in manager.PACKAGE_FILES}
                self.m.cfg['packages'][str(newer)] = record
            return result
        with patch.object(self.m, 'fingerprint', side_effect=fingerprint):
            self.m.execute(token)
        self.assertEqual(manager.sha(self.native), manager.sha(selected / manager.DLL))

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
