"""Reviewed archive/model identity, separate provider selection and upgrade guards."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import hlx_fsr_release as hlx
import model_variants
from optiscaler_setup import parse_config


TEMPLATE = ('[Upscalers]\nDx12Upscaler=auto\n[FSR]\nUpscalerIndex=auto\n'
            '[FrameGen]\nEnabled=auto\nFGInput=auto\nFGOutput=auto\nFGNvngxReplacement=auto\n'
            '[XeFG]\nInterpolationCount=auto\n[Libraries]\nFfxDx12SRPath=auto\n'
            '[Menu]\nShortcutKey=0x2D\n')


class HlxReleaseTests(unittest.TestCase):
    def test_release_and_model_receipt_are_separate_identities(self):
        release = hlx.V320.release()
        self.assertEqual(hlx.V320.validate_release(release), release)
        for change in ({'version': '3.1.0'}, {'sha256': 'f' * 64}, {'size': True},
                       {'url': 'https://example.com/HelixSR-3.2.0.zip'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                hlx.V320.validate_release(dict(release, **change))
        variant = model_variants.select_variant(hlx.VARIANT_ID)
        self.assertEqual(variant['release_choices'], ['reviewed-3.3.0'], '3.3.0 replaced the 3.2.0 prerelease')
        self.assertEqual(model_variants.select_variant()['id'], 'helixsr-model-e')
        receipt = dict(id=hlx.VARIANT_ID, adapter=hlx.ADAPTER, recipe_sha256=hlx.V320.RECIPE_SHA256)
        self.assertTrue(model_variants.valid_variant(receipt))
        self.assertFalse(model_variants.valid_variant(dict(receipt, id='helixsr-model-e')))
        self.assertFalse(model_variants.valid_variant(dict(receipt, recipe_sha256=hlx.V320.RELEASE_SHA256)))

    def test_model_e_scaffold_and_changed_hlx_or_notices_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'HLX-FSR4').mkdir()
            with self.assertRaisesRegex(ValueError, 'Model E release'):
                model_variants.verify_recipe(p)
            with self.assertRaisesRegex(ValueError, '3.3.0'):
                model_variants.verify_recipe(p, hlx.VARIANT_ID)
            files = {hlx.MANIFEST_PATH: b'sdk receipt', hlx.OUTPUT_DLL: b'prebuilt', 'LICENSE': b'notice'}
            pins = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in files.items()}
            for name, data in files.items():
                (p / name).write_bytes(data)
            with patch.object(hlx.V320, 'PINS', pins):
                self.assertEqual(model_variants.verify_recipe(p, hlx.VARIANT_ID)['id'], hlx.VARIANT_ID)
                for name, data in files.items():
                    with self.subTest(name=name):
                        (p / name).write_bytes(b'x' * len(data))
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            hlx.V320.verify_outputs(p)
                        (p / name).write_bytes(data)

    def test_routes_install_their_own_verified_providers(self):
        self.assertEqual(hlx.V320.direct_pairs(), ((hlx.OUTPUT_DLL, '{dll}'),))
        scaler = {dest: src for src, dest in hlx.V320.scaler_pairs()}
        native = 'OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll'
        wrapper = 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'
        self.assertEqual(hlx.V320.PINS[scaler[wrapper]], hlx.V320.PINS[hlx.OUTPUT_DLL])
        self.assertNotEqual(hlx.V320.PINS[scaler[native]], hlx.V320.PINS[scaler[wrapper]])
        self.assertIn('OptiScaler/amd_fidelityfx_framegeneration_dx12.dll', scaler)
        self.assertEqual(scaler['dxgi.dll'], 'helixsr-scaler/OptiScaler.dll')
        self.assertTrue({'LICENSE', 'THIRD_PARTY_NOTICES.md', hlx.MANIFEST_PATH} <= set(hlx.V320.payload_files()))
        self.assertTrue(set(scaler.values()) <= set(hlx.V320.payload_files()))
        self.assertFalse(any('helixsr.dll' in n or 'helixsr-fg/' in n for n in scaler))

    def test_independent_sr_and_fg_selectors_and_retained_settings(self):
        src = TEMPLATE.replace('\n', '\r\n')
        config = hlx.V320.configuration(src, src)
        state = hlx.V320.read_settings(config)
        self.assertEqual((state['family'], state['upscaler'], state['provider']), ('hlx-fsr', 'hlx-fsr', 'off'))
        xess = hlx.V320.update_settings(config, {'provider': 'xess', 'multiplier': 3})
        native = hlx.V320.update_settings(xess, {'upscaler': 'fsr'})
        self.assertEqual(hlx.V320.configuration(native, src, previous_version='3.2.0'), native)
        self.assertIn('[Menu]\r\nShortcutKey=0x2D\r\n', native)
        self.assertEqual(parse_config(native).get('FSR', 'UpscalerIndex'), '1')
        self.assertEqual(hlx.V320.read_settings(native)['provider'], 'xess')
        self.assertEqual(hlx.V320.read_settings(native)['multiplier'], 3)
        self.assertEqual(hlx.V320.read_settings(hlx.V320.update_settings(native, {'provider':'fsr', 'multiplier':2}))['provider'], 'fsr')
        for changes in ({'provider':'helixsr'}, {'upscaler':'helixsr'}, {'model':'full'}, {'quick_flow':'fast'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                hlx.V320.update_settings(config, changes)

    def test_upscaler_overlay_is_available_for_hlx_without_touching_its_upscaler(self):
        src = TEMPLATE.replace('\n', '\r\n')
        config = hlx.V320.configuration(src, src)
        self.assertEqual(hlx.V320.read_settings(config)['overlay'], 'off')
        on = hlx.V320.update_settings(config, {'overlay': 'upscaler'})
        state = hlx.V320.read_settings(on)
        self.assertEqual((state['overlay'], state['upscaler'], state['provider']), ('upscaler', 'hlx-fsr', 'off'))
        self.assertEqual(parse_config(on).get('Menu', 'ShowFps'), 'true')
        self.assertEqual(parse_config(on).get('Menu', 'FpsOverlayType'), '1')

    def test_migration_fails_before_discarding_helix_fg_or_custom_sr(self):
        active = TEMPLATE.replace('Enabled=auto', 'Enabled=true').replace(
            'FGInput=auto', 'FGInput=nvngxfg').replace('FGNvngxReplacement=auto','FGNvngxReplacement=HelixSR')
        with self.assertRaisesRegex(ValueError, 'before upgrading'):
            hlx.V320.configuration(active, TEMPLATE, previous_version='2.0.0')
        for key in ('FfxDx12SRPath', 'FfxDx12Path', 'OptiDllPath'):
            custom = TEMPLATE.replace('FfxDx12SRPath=auto', key + '=custom.dll')
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                hlx.V320.configuration(custom, TEMPLATE)
        native_fg = TEMPLATE.replace('Enabled=auto','Enabled=true').replace(
            'FGInput=auto', 'FGInput=upscaler').replace('FGOutput=auto','FGOutput=fsrfg')
        self.assertEqual(hlx.V320.read_settings(hlx.V320.configuration(native_fg, TEMPLATE, '2.0.0'))['provider'], 'fsr')


class Hlx330Tests(unittest.TestCase):
    """HelixSR 3.3.0: the same HLX FSR 4 provider plus HLX FSR 4 Full as a Scaler custom upscaler."""

    def test_both_releases_are_reviewed_with_their_own_pins(self):
        import compatibility_release as releases
        self.assertEqual(set(hlx.RELEASES), {'3.2.0', '3.3.0'})
        self.assertNotEqual(hlx.V320.RECIPE_SHA256, hlx.V330.RECIPE_SHA256)
        for release in hlx.RELEASES.values():
            receipt = dict(id=hlx.VARIANT_ID, adapter=hlx.ADAPTER, recipe_sha256=release.RECIPE_SHA256)
            self.assertTrue(model_variants.valid_variant(receipt))
            self.assertIs(hlx.for_record({'version': release.MODERN_VERSION}), release)
        self.assertEqual(hlx.output_sha256s(), {hlx.V320.OUTPUT_SHA256, hlx.V330.OUTPUT_SHA256} | hlx.V330.REPLACED_OUTPUTS)
        choice = releases.reviewed_release('reviewed-3.3.0')
        self.assertEqual((choice['version'], choice['sha256'], choice['size']),
                         ('3.3.0', hlx.V330.RELEASE_SHA256, hlx.V330.RELEASE_SIZE))
        self.assertEqual(releases.require_supported_latest(choice), choice)
        with self.assertRaisesRegex(ValueError, 'replaced the archive'):
            releases.require_supported_latest(dict(choice, sha256='0' * 64))
        labels = {c['id']: c['label'] for c in releases.release_choices()}
        self.assertEqual(labels['reviewed-3.3.0'], 'HelixSR 3.3.0 (HLX FSR 4 and HLX FSR 4 Full)')
        self.assertNotIn('reviewed-3.2.0', labels, 'the 3.2.0 prerelease is no longer offered')
        self.assertEqual(releases.selection('reviewed-3.2.0'), 'reviewed-3.2.0', 'existing 3.2.0 installs keep an identity')
        with self.assertRaises(ValueError):
            hlx.for_record({'version': '2.0.0'})

    def test_full_is_a_scaler_payload_never_a_direct_one(self):
        full = 'OptiScaler/custom/HLX FSR 4 Full/ffx/amd_fidelityfx_upscaler_dx12.dll'
        destinations = dict(hlx.V330.scaler_pairs()).values()
        self.assertIn(full, destinations)
        self.assertIn('OptiScaler/custom/HLX FSR 4 Full/ffx/hlx_fsr4.ini', destinations)
        self.assertNotIn(full, dict(hlx.V320.scaler_pairs()).values())
        self.assertEqual(hlx.V330.direct_pairs(), ((hlx.OUTPUT_DLL, '{dll}'),))
        self.assertFalse(any('ffx_vk' in name or name.startswith(('HelixSR/', 'setup/')) for name in hlx.V330.PINS),
                         'Vulkan-only and unbuilt HLX DLSS / Preset K files are not installed')

    def test_full_selection_reads_writes_and_is_refused_by_320(self):
        state = hlx.V330.read_settings(hlx.V330.configuration(TEMPLATE, TEMPLATE))
        self.assertEqual((state['upscaler'], state['full_available'], state['release']), ('hlx-fsr', True, '3.3.0'))
        full = hlx.V330.update_settings(TEMPLATE, {'upscaler': 'hlx-fsr-full'})
        self.assertEqual(parse_config(full)['Upscalers']['Dx12Upscaler'], 'HLX FSR 4 Full')
        self.assertEqual(hlx.V330.read_settings(full)['upscaler'], 'hlx-fsr-full')
        back = hlx.V330.update_settings(full, {'upscaler': 'hlx-fsr'})
        self.assertEqual((parse_config(back)['Upscalers']['Dx12Upscaler'], parse_config(back)['FSR']['UpscalerIndex']), ('ffx', '0'))
        self.assertEqual(hlx.V330.read_settings(hlx.V330.update_settings(full, {'upscaler': 'fsr'}))['upscaler'], 'fsr')
        self.assertFalse(hlx.V320.read_settings(TEMPLATE)['full_available'])
        self.assertEqual(hlx.V320.read_settings(full)['upscaler'], 'unsupported')
        with self.assertRaisesRegex(ValueError, 'Unsupported HLX FSR upscaler'):
            hlx.V320.update_settings(TEMPLATE, {'upscaler': 'hlx-fsr-full'})

    def test_upgrades_keep_settings_and_a_downgrade_cannot_keep_full(self):
        native = hlx.V320.update_settings(hlx.V320.configuration(TEMPLATE, TEMPLATE), {'upscaler': 'fsr', 'overlay': 'upscaler'})
        upgraded = hlx.V330.configuration(native, TEMPLATE, previous_version='3.2.0')
        self.assertEqual(upgraded, native, 'a 3.2.0 user keeps every Scaler setting on 3.3.0')
        full = hlx.V330.update_settings(native, {'upscaler': 'hlx-fsr-full'})
        self.assertEqual(hlx.V330.configuration(full, TEMPLATE, previous_version='3.3.0'), full)
        downgraded = hlx.V320.configuration(full, TEMPLATE, previous_version='3.3.0')
        self.assertEqual(hlx.V320.read_settings(downgraded)['upscaler'], 'hlx-fsr')
        self.assertEqual(hlx.V320.read_settings(downgraded)['overlay'], 'upscaler')
        from_20 = hlx.V330.configuration(native.replace('UpscalerIndex=1', 'UpscalerIndex=auto'), TEMPLATE, previous_version='2.0.0')
        self.assertEqual(hlx.V330.read_settings(from_20)['upscaler'], 'hlx-fsr', 'other releases are re-pinned to HLX')


class Hlx330RepublishedTests(unittest.TestCase):
    """Upstream rebuilt HelixSR-3.3.0.zip in place on 2026-11-12 (three HLX DLLs changed)."""

    def test_current_pins_are_the_20261112_asset(self):
        self.assertEqual((hlx.V330.RELEASE_SHA256, hlx.V330.RELEASE_SIZE),
                         ('7d6c0a4adeb5237004fc6fbe211d39705d62d49f23c51cc8f4ea987281d0a56b', 279492763))
        self.assertEqual(hlx.V330.OUTPUT_SHA256, '4b90351a93cdfb055fb1f2b7224e0cb26fa6aecf3e5ef491acaf6f89dbb7da3b')
        self.assertEqual(hlx.V330.PINS[hlx.SCALER_DIR + 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'],
                         hlx.V330.PINS[hlx.OUTPUT_DLL])
        self.assertEqual(hlx.V330.PINS[hlx.FULL_DIR + 'amd_fidelityfx_upscaler_dx12.dll'][1],
                         '1808af1ae4a495c9eb6e7b0c745532c45d5d1c85a0e6c917f949efe726c9c61b')

    def test_replaced_20261111_build_is_recognized_but_never_installed(self):
        self.assertEqual(len(hlx.V330.REPLACED_RECIPES), 1)
        old = next(iter(hlx.V330.REPLACED_RECIPES))
        self.assertNotEqual(old, hlx.V330.RECIPE_SHA256)
        self.assertTrue(model_variants.valid_variant(dict(id=hlx.VARIANT_ID, adapter=hlx.ADAPTER, recipe_sha256=old)))
        self.assertIn('143164cf365335d6abaa8a72707c06b6586ce487b22e61284aaba44b169e4108', hlx.output_sha256s())
        self.assertEqual(hlx.V330.release()['sha256'], hlx.V330.RELEASE_SHA256)
        with self.assertRaisesRegex(ValueError, 'replaced the archive'):
            hlx.V330.validate_release(dict(hlx.V330.release(),
                                           sha256='4d87481061db0f499112041b38da5aebfc86e7f9ca3c7b1894258f20452d9045',
                                           size=279494747))
