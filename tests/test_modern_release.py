"""Modern release adapter tests; generated networks are synthetic fixtures."""
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
import modern_release as modern
from optiscaler_setup import parse_config


class ModernTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)

    def write(self, name, value):
        path = self.package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)

    def release(self):
        return dict(version='1.9.3', sha256=modern.RELEASE_SHA256,
                    size=136076974, url=modern.RELEASE_URL, page=modern.RELEASE_PAGE)

    def outputs(self, wave64=False, fp32=False):
        weights = b'synthetic Model E weights'
        digest = hashlib.sha256(weights).hexdigest()
        for key, value in dict(WEIGHTS_SIZE=len(weights), WEIGHTS_SHA256=digest).items():
            mock = patch.object(modern, key, value)
            mock.start()
            self.addCleanup(mock.stop)
        names = list(modern.KERNEL_NAMES)
        if wave64:
            names += [n + b'_w64' for n in modern.KERNEL_NAMES]
        if fp32:
            names += [n + b'_fp32' for n in names[:]]
        manifest = dict(source_sha256=modern.SOURCE_SHA256, weights_sha256=digest,
                        ptx_target='sm_89', shaders=len(names), wave64=wave64, fp32=fp32)
        self.write('helixsr_weights.bin', weights)
        self.write('helixsr_setup.json', json.dumps(manifest))
        offset = 16 + len(names) * 40
        table = b''.join(struct.pack('<32sII', n, offset + i, 1) for i, n in enumerate(names))
        self.write('helixsr_kernels.pak', b'HXSRKPAK' + struct.pack('<II', 2, len(names)) + table + b'x' * len(names))
        return manifest

    def test_modern_only_recognizes_exact_version_mappings(self):
        for value in (self.release(), {'version': '1.9.3', 'files': {} }):
            self.assertTrue(modern.modern(value))
        for value in (None, [], '1.9.3', {}, {'version': '1.9.30'}, {'version': 'v1.9.3'}):
            self.assertFalse(modern.modern(value))

    def test_release_exact_identity(self):
        release = self.release()
        self.assertIs(modern.validate_release(release), release)
        for key, value in (('version', '1.9.4'), ('sha256', 'f' * 64), ('size', True),
                           ('size', 136076975), ('url', modern.RELEASE_URL + '?x'),
                           ('page', modern.RELEASE_PAGE + '/')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                modern.validate_release(dict(release, **{key: value}))
        with self.assertRaises(ValueError):
            modern.validate_release(None)

    def test_recipe_hash_and_exact_tree(self):
        for name in modern._RECIPE_FILES:
            self.write(name, 'synthetic ' + name)
        hashes = {n: hashlib.sha256((self.package / n).read_bytes()).hexdigest()
                  for n in modern._RECIPE_FILES}
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        with patch.object(modern, 'RECIPE_SHA256', digest):
            self.assertEqual(modern.verify_recipe(self.package), dict(
                id='helixsr-model-e', adapter='separate-network-v1', recipe_sha256=digest))
            self.write('setup/helixsr_install.py', 'changed')
            with self.assertRaises(ValueError):
                modern.verify_recipe(self.package)
            self.write('setup/new.py', 'unexpected')
            with self.assertRaises(ValueError):
                modern.verify_recipe(self.package)

    def test_missing_recipe_file_is_rejected(self):
        with self.assertRaises(ValueError):
            modern.verify_recipe(self.package)

    def test_all_four_shader_flag_combinations(self):
        for wave64, fp32 in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(wave64=wave64, fp32=fp32):
                self.outputs(wave64, fp32)
                self.assertIsNone(modern.verify_outputs(self.package))

    def test_manifest_flags_identity_and_count_are_strict(self):
        manifest = self.outputs()
        changes = [('wave64', 0), ('fp32', 1), ('shaders', True), ('shaders', 1),
                   ('source_sha256', 'f' * 64), ('weights_sha256', 'f' * 64),
                   ('ptx_target', 'sm_90'), ('extra', True)]
        for key, value in changes:
            self.write('helixsr_setup.json', json.dumps(dict(manifest, **{key: value})))
            with self.subTest(key=key), self.assertRaises(ValueError):
                modern.verify_outputs(self.package)

    def test_duplicate_missing_invalid_and_oversize_manifest_rejected(self):
        manifest = self.outputs()
        for value in ('[]', '{', json.dumps(manifest)[:-1] + ',"fp32":false}',
                      json.dumps({k: v for k, v in manifest.items() if k != 'fp32'}), ' ' * 4097):
            self.write('helixsr_setup.json', value)
            with self.assertRaises(ValueError):
                modern.verify_outputs(self.package)

    def test_weights_hash_and_size_rejected(self):
        self.outputs()
        original = (self.package / 'helixsr_weights.bin').read_bytes()
        for value in (original + b'x', original[:-1], b'z' * len(original)):
            self.write('helixsr_weights.bin', value)
            with self.assertRaises(ValueError):
                modern.verify_outputs(self.package)

    def test_kernel_header_count_and_truncation_rejected(self):
        self.outputs(True, True)
        pak = (self.package / 'helixsr_kernels.pak').read_bytes()
        for value in (b'', b'BADMAGIC' + pak[8:], pak[:8] + struct.pack('<II', 1, 120) + pak[16:],
                      pak[:12] + struct.pack('<I', 1) + pak[16:], pak[:45], pak[:-1], pak + b'x'):
            self.write('helixsr_kernels.pak', value)
            with self.assertRaises(ValueError):
                modern.verify_outputs(self.package)

    def test_kernel_names_offsets_lengths_and_padding_rejected(self):
        self.outputs()
        pak = (self.package / 'helixsr_kernels.pak').read_bytes()
        first = struct.unpack('<32sII', pak[16:56])
        replacements = [(b'wrong', first[1], 1), (first[0], first[1] + 1, 1),
                        (first[0], first[1], 0), (first[0], first[1], 999999),
                        (first[0].split(b'\0')[0] + b'\0bad', first[1], 1)]
        for name, offset, length in replacements:
            self.write('helixsr_kernels.pak', pak[:16] + struct.pack('<32sII', name, offset, length) + pak[56:])
            with self.assertRaises(ValueError):
                modern.verify_outputs(self.package)
        self.write('helixsr_kernels.pak', pak[:56] + struct.pack('<32sII', first[0], first[1] + 1, 1) + pak[96:])
        with self.assertRaises(ValueError):
            modern.verify_outputs(self.package)

    def test_payload_and_pairs_are_fixed_and_unique(self):
        files = modern.payload_files()
        self.assertIsInstance(files, tuple)
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(files), 32)
        pairs = modern.scaler_pairs()
        self.assertEqual(len(pairs), 30)
        self.assertEqual(len(pairs), len({dest.lower() for _, dest in pairs}))
        self.assertIn(('helixsr-scaler/OptiScaler.dll', 'dxgi.dll'), pairs)
        self.assertIn(('amd_fidelityfx_dx12.dll', 'HelixSR/helixsr.dll'), pairs)
        for name in files:
            self.assertFalse(any(n in name.lower() for n in ('readme', 'setup_', 'fakenvapi', 'package.txt')))
        self.assertNotIn('helixsr-scaler/OptiScaler.ini', {s for s, _ in pairs})

    def test_configuration_preserves_alternative_frame_generation(self):
        template = '[Upscalers]\nDx12Upscaler=auto\n[HelixSR]\nFrameGeneration=off\n[FrameGen]\nFGNvngxReplacement=auto\n'
        for provider in ('Nukems', 'Arturs', 'FFX', 'Combo', 'auto', 'HelixSR'):
            source = template.replace('FrameGeneration=off', 'FrameGeneration=on').replace(
                'FGNvngxReplacement=auto', 'FGNvngxReplacement=' + provider)
            source += 'Enabled=true\nFGInput=nvngxfg\nFGOutput=dlssg\n[Other]\nCustom=mine\n'
            result = modern.configuration(source, template)
            config = parse_config(result)
            self.assertEqual(config.get('Upscalers', 'Dx12Upscaler'), 'dlss')
            self.assertEqual(config.get('HelixSR', 'FrameGeneration'), 'off')
            self.assertEqual(config.get('FrameGen', 'FGNvngxReplacement'), 'FFX' if provider == 'HelixSR' else provider)
            for key, value in [('Enabled', 'true'), ('FGInput', 'nvngxfg'), ('FGOutput', 'dlssg')]:
                self.assertEqual(config.get('FrameGen', key), value)
            self.assertEqual(config.get('Other', 'Custom'), 'mine')

    def test_configuration_adds_missing_managed_sections_and_preserves_crlf_bom(self):
        template = '[Upscalers]\nDx12Upscaler=auto\n[HelixSR]\nFrameGeneration=off\n[FrameGen]\nFGNvngxReplacement=auto\n'
        result = modern.configuration('\ufeff[Other]\r\nCustom=value\r\n', template)
        self.assertTrue(result.startswith('\ufeff'))
        self.assertIn('Dx12Upscaler=dlss\r\n', result)
        self.assertEqual(parse_config(result).get('Other', 'Custom'), 'value')

    def test_configuration_misplaced_duplicate_or_drifted_keys_rejected(self):
        template = '[Upscalers]\nDx12Upscaler=auto\n[HelixSR]\nFrameGeneration=off\n[FrameGen]\nFGNvngxReplacement=auto\n'
        for source in (template + '[Other]\nDx12Upscaler=xess\n',
                       template + 'FGNvngxReplacement=HelixSR\n'):
            with self.assertRaises(ValueError):
                modern.configuration(source, template)
        with self.assertRaises(ValueError):
            modern.configuration(template, '[Upscalers]\nDx12Upscaler=auto\n')


@unittest.skipUnless(os.environ.get('HELIXSR_MODERN_FIXTURE'), 'official archive fixture not configured')
class OfficialFixtureTests(unittest.TestCase):
    def setUp(self):
        self.package = Path(os.environ['HELIXSR_MODERN_FIXTURE'])

    def test_official_recipe_is_pinned(self):
        self.assertEqual(modern.verify_recipe(self.package)['recipe_sha256'], modern.RECIPE_SHA256)

    def test_official_static_payload_is_complete(self):
        generated = {'helixsr_weights.bin', 'helixsr_kernels.pak', 'helixsr_setup.json'}
        for name in modern.payload_files():
            if name not in generated:
                self.assertTrue((self.package / name).is_file(), name)

    def test_official_configuration_preserves_unmanaged_defaults(self):
        template = (self.package / 'helixsr-scaler/OptiScaler.ini').read_text(encoding='utf-8-sig')
        before = parse_config(template)
        after = parse_config(modern.configuration(template, template))
        for section in before.sections():
            for key, value in before.items(section):
                if (section, key) not in {('Upscalers', 'dx12upscaler'), ('HelixSR', 'framegeneration')}:
                    self.assertEqual(after.get(section, key), value, (section, key))
        self.assertEqual(after.get('Upscalers', 'Dx12Upscaler'), 'dlss')


if __name__ == '__main__':
    unittest.main()
