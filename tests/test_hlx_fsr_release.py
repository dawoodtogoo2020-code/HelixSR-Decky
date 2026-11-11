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
        release = hlx.release()
        self.assertEqual(hlx.validate_release(release), release)
        for change in ({'version': '3.1.0'}, {'sha256': 'f' * 64}, {'size': True},
                       {'url': 'https://example.com/HelixSR-3.2.0.zip'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                hlx.validate_release(dict(release, **change))
        variant = model_variants.select_variant(hlx.VARIANT_ID)
        self.assertEqual(variant['release_choices'], ['reviewed-3.2.0'])
        self.assertEqual(model_variants.select_variant()['id'], 'helixsr-model-e')
        receipt = dict(id=hlx.VARIANT_ID, adapter=hlx.ADAPTER, recipe_sha256=hlx.RECIPE_SHA256)
        self.assertTrue(model_variants.valid_variant(receipt))
        self.assertFalse(model_variants.valid_variant(dict(receipt, id='helixsr-model-e')))
        self.assertFalse(model_variants.valid_variant(dict(receipt, recipe_sha256=hlx.RELEASE_SHA256)))

    def test_model_e_scaffold_and_changed_hlx_or_notices_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'HLX-FSR4').mkdir()
            with self.assertRaisesRegex(ValueError, 'Model E release'):
                model_variants.verify_recipe(p)
            with self.assertRaisesRegex(ValueError, '3.2.0'):
                model_variants.verify_recipe(p, hlx.VARIANT_ID)
            files = {hlx.MANIFEST_PATH: b'sdk receipt', hlx.OUTPUT_DLL: b'prebuilt', 'LICENSE': b'notice'}
            pins = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in files.items()}
            for name, data in files.items():
                (p / name).write_bytes(data)
            with patch.object(hlx, 'PINS', pins):
                self.assertEqual(model_variants.verify_recipe(p, hlx.VARIANT_ID)['id'], hlx.VARIANT_ID)
                for name, data in files.items():
                    with self.subTest(name=name):
                        (p / name).write_bytes(b'x' * len(data))
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            hlx.verify_outputs(p)
                        (p / name).write_bytes(data)

    def test_routes_install_their_own_verified_providers(self):
        self.assertEqual(hlx.direct_pairs(), ((hlx.OUTPUT_DLL, '{dll}'),))
        scaler = {dest: src for src, dest in hlx.scaler_pairs()}
        native = 'OptiScaler/amd_fidelityfx_upscaler_dx12.amd.dll'
        wrapper = 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'
        self.assertEqual(hlx.PINS[scaler[wrapper]], hlx.PINS[hlx.OUTPUT_DLL])
        self.assertNotEqual(hlx.PINS[scaler[native]], hlx.PINS[scaler[wrapper]])
        self.assertIn('OptiScaler/amd_fidelityfx_framegeneration_dx12.dll', scaler)
        self.assertEqual(scaler['dxgi.dll'], 'helixsr-scaler/OptiScaler.dll')
        self.assertTrue({'LICENSE', 'THIRD_PARTY_NOTICES.md', hlx.MANIFEST_PATH} <= set(hlx.payload_files()))
        self.assertTrue(set(scaler.values()) <= set(hlx.payload_files()))
        self.assertFalse(any('helixsr.dll' in n or 'helixsr-fg/' in n for n in scaler))

    def test_independent_sr_and_fg_selectors_and_retained_settings(self):
        src = TEMPLATE.replace('\n', '\r\n')
        config = hlx.configuration(src, src)
        state = hlx.read_settings(config)
        self.assertEqual((state['family'], state['upscaler'], state['provider']), ('hlx-fsr', 'hlx-fsr', 'off'))
        xess = hlx.update_settings(config, {'provider': 'xess', 'multiplier': 3})
        native = hlx.update_settings(xess, {'upscaler': 'fsr'})
        self.assertEqual(hlx.configuration(native, src, previous_version='3.2.0'), native)
        self.assertIn('[Menu]\r\nShortcutKey=0x2D\r\n', native)
        self.assertEqual(parse_config(native).get('FSR', 'UpscalerIndex'), '1')
        self.assertEqual(hlx.read_settings(native)['provider'], 'xess')
        self.assertEqual(hlx.read_settings(native)['multiplier'], 3)
        self.assertEqual(hlx.read_settings(hlx.update_settings(native, {'provider':'fsr', 'multiplier':2}))['provider'], 'fsr')
        for changes in ({'provider':'helixsr'}, {'upscaler':'helixsr'}, {'model':'full'}, {'quick_flow':'fast'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                hlx.update_settings(config, changes)

    def test_upscaler_overlay_is_available_for_hlx_without_touching_its_upscaler(self):
        src = TEMPLATE.replace('\n', '\r\n')
        config = hlx.configuration(src, src)
        self.assertEqual(hlx.read_settings(config)['overlay'], 'off')
        on = hlx.update_settings(config, {'overlay': 'upscaler'})
        state = hlx.read_settings(on)
        self.assertEqual((state['overlay'], state['upscaler'], state['provider']), ('upscaler', 'hlx-fsr', 'off'))
        self.assertEqual(parse_config(on).get('Menu', 'ShowFps'), 'true')
        self.assertEqual(parse_config(on).get('Menu', 'FpsOverlayType'), '1')

    def test_migration_fails_before_discarding_helix_fg_or_custom_sr(self):
        active = TEMPLATE.replace('Enabled=auto', 'Enabled=true').replace(
            'FGInput=auto', 'FGInput=nvngxfg').replace('FGNvngxReplacement=auto','FGNvngxReplacement=HelixSR')
        with self.assertRaisesRegex(ValueError, 'before upgrading'):
            hlx.configuration(active, TEMPLATE, previous_version='2.0.0')
        for key in ('FfxDx12SRPath', 'FfxDx12Path', 'OptiDllPath'):
            custom = TEMPLATE.replace('FfxDx12SRPath=auto', key + '=custom.dll')
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                hlx.configuration(custom, TEMPLATE)
        native_fg = TEMPLATE.replace('Enabled=auto','Enabled=true').replace(
            'FGInput=auto', 'FGInput=upscaler').replace('FGOutput=auto','FGOutput=fsrfg')
        self.assertEqual(hlx.read_settings(hlx.configuration(native_fg, TEMPLATE, '2.0.0'))['provider'], 'fsr')
