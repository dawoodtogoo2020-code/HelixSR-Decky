"""Regression coverage for the small, text-only HelixSR settings editor."""
import sys
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import helix_settings


SOURCE = '''; user comment\r\n[FrameGen]\r\nEnabled=true\r\nFGInput=nvngxfg\r\nFGOutput=auto\r\nFGNvngxReplacement=HelixSR\r\n[HelixSR]\r\nFGPreset=full\r\nQuickFlow=off\r\n[ XeFG ]\r\nInterpolationCount=1\r\n[Upscalers]\r\nDx12Upscaler=auto\r\n[User]\r\nEnabled=keep-this\r\nCustom=unchanged\r\n'''


class HelixSettingsTests(unittest.TestCase):
    def test_rejects_unknown_fields_and_exact_types_including_bool_multiplier(self):
        for changes in ({'unknown': 'x'}, {'multiplier': True}, {'multiplier': '3'},
                        {'provider': 1}, ['provider']):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'setting'):
                helix_settings.update_settings(SOURCE, changes)

    def test_preserves_bom_crlf_comments_and_unrelated_enabled_key(self):
        updated = helix_settings.update_settings('\ufeff' + SOURCE, {'quick_flow': 'fast'})
        self.assertTrue(updated.startswith('\ufeff; user comment\r\n'))
        self.assertNotIn('\n', updated.replace('\r\n', ''))
        self.assertIn('[User]\r\nEnabled=keep-this\r\nCustom=unchanged\r\n', updated)
        self.assertIn('[HelixSR]\r\nFGPreset=full\r\nQuickFlow=fast\r\n', updated)

    def test_quickflow_requires_full_model_and_three_x_requires_xess(self):
        light = SOURCE.replace('FGPreset=full', 'FGPreset=c')
        with self.assertRaisesRegex(ValueError, 'QuickFlow requires Full'):
            helix_settings.update_settings(light, {'quick_flow': 'fast'})
        with self.assertRaisesRegex(ValueError, '3x is supported only'):
            helix_settings.update_settings(SOURCE, {'multiplier': 3})
        xess = SOURCE.replace('FGInput=nvngxfg', 'FGInput=upscaler').replace('FGOutput=auto', 'FGOutput=xefg')
        self.assertIn('InterpolationCount=2', helix_settings.update_settings(xess, {'multiplier': 3}))

    def test_unsupported_provider_is_reported_and_preserved_when_unrelated_setting_changes(self):
        unsupported = SOURCE.replace('FGNvngxReplacement=HelixSR', 'FGNvngxReplacement=Other')
        self.assertEqual(helix_settings.read_settings(unsupported)['provider'], 'unsupported')
        updated = helix_settings.update_settings(unsupported, {'int8': 'on'})
        self.assertIn('FGNvngxReplacement=Other', updated)
        self.assertIn('Int8=on', updated)

    def test_upscaler_switches_between_model_e_and_integrated_amd_fsr_without_losing_custom_state(self):
        source = SOURCE + '[Libraries]\nFfxDx12SRPath=Z:\\old-wrapper.dll\n[FSR]\nUpscalerIndex=0\nCustomTone=keep\n'
        fsr = helix_settings.update_settings(source, {'upscaler': 'fsr'})
        self.assertEqual(helix_settings.read_settings(fsr)['upscaler'], 'fsr')
        self.assertIn('Dx12Upscaler=ffx', fsr)
        self.assertIn('FfxDx12SRPath=auto', fsr)
        self.assertIn('UpscalerIndex=1', fsr)
        self.assertIn('CustomTone=keep', fsr)
        self.assertIn('[User]\r\nEnabled=keep-this\r\nCustom=unchanged\r\n', fsr)
        model_e = helix_settings.update_settings(fsr, {'upscaler': 'helixsr'})
        self.assertEqual(helix_settings.read_settings(model_e)['upscaler'], 'helixsr')
        self.assertIn('UpscalerIndex=0', model_e)
        self.assertIn('CustomTone=keep', model_e)


if __name__ == '__main__':
    unittest.main(verbosity=2)
