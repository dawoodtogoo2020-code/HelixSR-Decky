"""Strict HelixSR 2.0 release-adapter tests; no setup code is executed."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import helix20_release as release


def dxil():
    data = bytearray(44)
    data[:4] = b'DXBC'
    struct.pack_into('<III', data, 24, len(data), 1, 36)
    data[36:40] = b'DXIL'
    return bytes(data)


def aligned(value):
    return (value + 255) & ~255


def archive(entries):
    names = sorted(entries)
    head = 12 + sum(4 + len(name.encode()) + 16 for name in names)
    offset = aligned(head)
    index, positions = bytearray(), []
    for name in names:
        data = entries[name]
        encoded = name.encode()
        index += struct.pack('<I', len(encoded)) + encoded + struct.pack('<QQ', offset, len(data))
        positions.append((offset, data))
        offset = aligned(offset + len(data))
    result = bytearray(offset)
    result[:12] = b'HXFGARC1' + struct.pack('<I', len(names))
    result[12:12 + len(index)] = index
    for offset, data in positions:
        result[offset:offset + len(data)] = data
    return bytes(result)


def weights_pack():
    count = 67
    head = 12 + count * 20
    offset = aligned(head)
    rows, positions = bytearray(), []
    for block_id in range(count):
        rows += struct.pack('<IQQ', block_id, offset, 1)
        positions.append(offset)
        offset = aligned(offset + 1)
    result = bytearray(offset)
    result[:12] = b'HXFGWPK1' + struct.pack('<I', count)
    result[12:12 + len(rows)] = rows
    for offset in positions:
        result[offset] = 1
    return bytes(result)


class Helix20ReleaseTests(unittest.TestCase):
    def setUp(self):
        scratch = (Path(__file__).resolve().parents[1].parent.parent / 'work'
                   if os.name == 'nt' else Path(tempfile.gettempdir()))
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data=b'fixture'):
        path = self.root.joinpath(*Path(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def identity(self, names, limit=128 << 20):
        return release._identity(self.root, names, limit)

    def test_release_identity_and_version_mapping_are_exact(self):
        value = dict(version=release.MODERN_VERSION, sha256=release.RELEASE_SHA256,
                     size=release.RELEASE_SIZE, url=release.RELEASE_URL, page=release.RELEASE_PAGE)
        self.assertTrue(release.modern(value))
        self.assertIs(release.validate_release(value), value)
        for key, changed in [('version', '2.0.1'), ('size', release.RELEASE_SIZE + 1),
                             ('sha256', '0' * 64), ('url', release.RELEASE_PAGE)]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'identity changed'):
                release.validate_release(dict(value, **{key: changed}))
        self.assertFalse(release.modern({'version': '1.9.3'}))

    def test_recipe_pins_whole_setup_tree_base_dll_and_static_tree(self):
        self.write('helixsr-setup.sh')
        self.write('setup/one.py')
        base = self.write(release.OUTPUT_DLL, b'MZ-base')
        self.write('HelixSR-fsrfg/helixsr.ini')
        self.write('HelixSR-fsrfg/helixsr-fg/nvexec64.dll')
        self.write('helixsr-scaler/OptiScaler.dll')
        recipe_names = ['helixsr-setup.sh', 'setup/one.py']
        static_names = release._static_names(self.root)
        patches = (
            patch.object(release, 'RECIPE_FILE_COUNT', len(recipe_names)),
            patch.object(release, 'RECIPE_SHA256', self.identity(recipe_names, 4 << 20)),
            patch.object(release, 'STATIC_FILE_COUNT', len(static_names)),
            patch.object(release, 'STATIC_SHA256', self.identity(static_names)),
            patch.object(release, 'BASE_DLL_SIZE', base.stat().st_size),
            patch.object(release, 'BASE_DLL_SHA256', hashlib.sha256(base.read_bytes()).hexdigest()),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            model = release.verify_recipe(self.root)
            self.assertEqual(model['adapter'], 'separate-network-v1')
            self.write('setup/unreviewed.py')
            with self.assertRaisesRegex(ValueError, 'recipe changed'):
                release.verify_recipe(self.root)

    def network(self):
        weights = b'w' * 37
        blobs = [dxil() for _ in release.KERNEL_NAMES]
        table_size = 16 + 40 * len(blobs)
        offset = table_size
        rows = []
        for name, blob in zip(release.KERNEL_NAMES, blobs):
            rows.append(struct.pack('<32sII', name, offset, len(blob)))
            offset += len(blob)
        pak = b'HXSRKPAK' + struct.pack('<II', 2, len(blobs)) + b''.join(rows) + b''.join(blobs)
        base = b'MZ' + b'b' * 62
        embedded = base + weights + pak + b'HXSRNET1' + struct.pack('<QQQ', len(weights), len(pak), 1)
        self.write(release.OUTPUT_DLL, embedded)
        manifest = dict(source_sha256=release.SOURCE_SHA256, ptx_target='sm_89',
                        shaders=len(release.KERNEL_NAMES), wave64=True, fp32=True, fp32h=True,
                        weights_sha256=hashlib.sha256(weights).hexdigest())
        return base, weights, pak, manifest

    def test_embedded_network_validates_base_weights_full_kernel_set_and_dxil(self):
        base, weights, _, manifest = self.network()
        with patch.object(release, 'BASE_DLL_SIZE', len(base)), \
                patch.object(release, 'BASE_DLL_SHA256', hashlib.sha256(base).hexdigest()), \
                patch.object(release, 'WEIGHTS_SIZE', len(weights)), \
                patch.object(release, 'WEIGHTS_SHA256', hashlib.sha256(weights).hexdigest()):
            release._verify_network(self.root, manifest)
            path = self.root / release.OUTPUT_DLL
            data = bytearray(path.read_bytes())
            first_shader = len(base) + len(weights) + 16 + 40 * len(release.KERNEL_NAMES)
            data[first_shader:first_shader + 4] = b'NOPE'
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'DXIL'):
                release._verify_network(self.root, manifest)

    def fg_archive(self, version, missing_variant=False):
        count = release.FG_KERNEL_COUNTS[version]
        lines, entries = [], {}
        for index in range(count):
            kernel = f'k{index:04d}'
            lines.append(f'kernel 0000000000000000 1 {kernel} {kernel}/{kernel}.cso params 0 block 1 1 1')
            entries[f'kernels\\{kernel}\\{kernel}.cso'] = dxil()
            variants = ('w64', 'fp32') if missing_variant and index == 0 else ('w64', 'fp32', 'w64_fp32')
            for variant in variants:
                name = f'{kernel}/{kernel}_{variant}.cso'
                lines.append(f'  variant {variant} {name}')
                entries['kernels\\' + name.replace('/', '\\')] = dxil()
        table_name = 'kernels\\kernels-v2.txt' if version == '310.9.16' else 'kernels\\kernels.txt'
        entries[table_name] = ('\n'.join(lines) + '\n').encode()
        entries['kernels\\vkreset.cso'] = dxil()
        entries['weights\\weights.pack'] = weights_pack()
        entries['source.txt'] = f'nvngx_dlssg {version} {release.FG_SOURCES[version]}\n'.encode()
        if version == '310.3':
            entries['fgprog.txt'] = b'program'
            entries['fgprog.small.txt'] = b'small program'
        data = archive(entries)
        name = f'{version}.bin'
        self.write(name, data)
        summary = dict(source_sha256=release.FG_SOURCES[version], source_version=version,
                       files=len(entries), archive_bytes=len(data),
                       archive_sha256=hashlib.sha256(data).hexdigest())
        return name, summary

    def test_both_frame_generation_modes_require_complete_archives_and_variants(self):
        for version in release.FG_SOURCES:
            with self.subTest(version=version):
                name, summary = self.fg_archive(version)
                release._verify_fg_archive(self.root, name, version, summary)
        name, summary = self.fg_archive('310.3', missing_variant=True)
        with self.assertRaisesRegex(ValueError, 'kernel table is incomplete'):
            release._verify_fg_archive(self.root, name, '310.3', summary)

    def test_payload_contract_is_unique_and_keeps_fg_beside_embedded_dll(self):
        files = release.payload_files()
        self.assertEqual(len(files), len(set(files)))
        for required in (release.OUTPUT_DLL, release.MANIFEST_PATH, release.FG_MANIFEST_PATH,
                         release.NGX_RECEIPT_PATH,
                         'HelixSR-fsrfg/helixsr-fg/hxfg_data.bin',
                         'HelixSR-fsrfg/helixsr-fg/310.9.16/hxfg_data.bin'):
            self.assertIn(required, files)
        pairs = release.scaler_pairs()
        self.assertEqual(len({target for _, target in pairs}), len(pairs))
        self.assertIn(('HelixSR-fsrfg/helixsr-fg/hxfg_data.bin',
                       'HelixSR-fsrfg/helixsr-fg/hxfg_data.bin'), pairs)
        self.assertEqual(pairs[-1], (release.AMD_UPSCALER_SOURCE,
                                     release.AMD_UPSCALER_RUNTIME))
        self.assertEqual(release.direct_pairs()[0], (release.OUTPUT_DLL, '{dll}'))
        self.assertEqual(set(release.mutable_configs()), set(release.MUTABLE_CONFIGS))

    def test_configuration_selects_embedded_upscaler_and_helix_frame_generation(self):
        template = ('[Upscalers]\nDx12Upscaler=auto\n\n[FrameGen]\n'
                    'FGInput=auto\nFGNvngxReplacement=auto\n')
        configured = release.configuration(template, template)
        parsed = release.parse_config(configured)
        self.assertEqual(parsed.get('Upscalers', 'Dx12Upscaler'), 'auto')
        self.assertEqual(parsed.get('FrameGen', 'FGInput'), 'nvngxfg')
        self.assertEqual(parsed.get('FrameGen', 'FGNvngxReplacement'), 'HelixSR')

        existing = template.replace('Dx12Upscaler=auto', 'Dx12Upscaler=fsr22').replace(
            'FGInput=auto', 'FGInput=xefg').replace('FGNvngxReplacement=auto', 'FGNvngxReplacement=None')
        self.assertEqual(release.configuration(existing, template), existing)

        old = template.replace('Dx12Upscaler=auto', 'Dx12Upscaler=dlss').replace(
            'FGNvngxReplacement=auto', 'FGNvngxReplacement=FFX')
        migrated = release.parse_config(release.configuration(old, template, '1.9.3'))
        self.assertEqual(migrated.get('Upscalers', 'Dx12Upscaler'), 'auto')
        self.assertEqual(migrated.get('FrameGen', 'FGInput'), 'nvngxfg')
        self.assertEqual(migrated.get('FrameGen', 'FGNvngxReplacement'), 'HelixSR')


class OfficialArchiveTests(unittest.TestCase):
    package = Path(r'D:\Downloads\Codex\HelixSR-2.0.0-audit\extracted\HelixSR-2.0.0')

    @unittest.skipUnless(package.is_dir(), 'verified official archive is not available')
    def test_official_recipe_and_static_payload_are_pinned(self):
        self.assertEqual(release.verify_recipe(self.package)['recipe_sha256'], release.RECIPE_SHA256)
        generated = {release.OUTPUT_DLL, release.MANIFEST_PATH, release.FG_MANIFEST_PATH,
                     release.NGX_RECEIPT_PATH, *release._FG_FILES[1:]}
        for name in release.payload_files():
            if name not in generated:
                self.assertTrue((self.package / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()
