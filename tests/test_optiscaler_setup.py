import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from optiscaler_setup import configuration, override_status, pin_config, setup_report


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'OptiScaler.ini'
        self.template = '[Upscalers]\nDx12Upscaler=auto\n[Paths]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n'
        self.settings = [('Dx12Upscaler', 'fsr31'), ('FfxDx12Path', 'Z:' + str(self.root / 'HelixSR/helixsr.dll').replace('/', '\\')),
                         ('FfxDx12SRPath', 'Z:' + str(self.root / 'HelixSR/helixsr_upscaler.dll').replace('/', '\\'))]

    def report(self):
        return setup_report(self.root, 'optiscaler', 'WINEDLLOVERRIDES="dxgi=n,b" %command%', [self.root / 'dxgi.dll'])

    def test_exact_backend_and_both_paths_required(self):
        source = pin_config(self.template, self.template, self.settings)
        self.config.write_text(source)
        self.assertTrue(self.report()['configured'])
        self.config.write_text(source.replace('Dx12Upscaler=fsr31', 'Dx12Upscaler=xess'))
        self.assertFalse(self.report()['configured'])
        self.config.write_text(source.replace('helixsr_upscaler.dll', 'other.dll'))
        self.assertFalse(self.report()['configured'])
        self.assertFalse(setup_report(self.root, 'direct', '')['configured'])

    def test_missing_input_and_custom_shortcut_are_actionable(self):
        self.config.write_text(pin_config(self.template, self.template, self.settings) +
                               '[Inputs]\nEnableDlssInputs=false\n[Nvapi]\nOverrideNvapiDll=false\nNvapiPath=custom.dll\n[Menu]\nShortcutKey=0x24\n')
        (self.root / 'nvapi64.dll').write_bytes(b'existing game file')
        report = self.report()
        text = '\n'.join(report['checks'])
        self.assertIn('DLSS input is disabled', text)
        self.assertIn('NVAPI handling is disabled', text)
        self.assertIn('existing nvapi64.dll', text)
        self.assertIn('Custom NvapiPath', text)
        self.assertIn('ShortcutKey=0x24', text)
        self.assertIn('supported FSR or XeSS input', text)
        self.assertIn('Frame generation is separate', text)
        self.assertEqual((self.root / 'nvapi64.dll').read_bytes(), b'existing game file')

    def test_override_distinguishes_missing_conflict_correct_and_unknown(self):
        for source, expected in [('', 'missing'), ('WINEDLLOVERRIDES="d3d11=n;dxgi=n,b" %command%', 'correct'),
                                 ('WINEDLLOVERRIDES="dxgi=b" %command%', 'conflict'),
                                 ('%command% WINEDLLOVERRIDES="dxgi=n,b"', 'unknown'),
                                 ('WINEDLLOVERRIDES="$RULE" %command%', 'unknown'),
                                 ('WINEDLLOVERRIDES="dxgi=n,b', 'unknown')]:
            with self.subTest(source=source):
                self.assertEqual(override_status(source), expected)

    def test_section_edits_preserve_other_bytes_and_insert_missing_keys(self):
        source = '; comment\r\n[Upscalers]\r\nDx12Upscaler=xess\r\n[Menu]\r\nShortcutKey=0x24\r\n[FrameGen]\r\nEnabled=false\r\n'
        result = pin_config(source, self.template, self.settings)
        self.assertIn('[Paths]\r\n', result)
        self.assertIn('FfxDx12Path=Z:', result.split('[Paths]\r\n')[1])
        self.assertIn('[Menu]\r\nShortcutKey=0x24\r\n[FrameGen]\r\nEnabled=false\r\n', result)
        self.assertTrue(result.startswith('; comment\r\n[Upscalers]\r\nDx12Upscaler=fsr31'))

    def test_misplaced_duplicate_and_malformed_settings_refuse(self):
        for source in ('[Other]\nDx12Upscaler=xess\n', self.template + '[Other]\nDx12Upscaler=xess\n',
                       self.template + '[Upscalers]\nDx12Upscaler=xess\n', '[broken\nDx12Upscaler=auto\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                pin_config(source, self.template, self.settings)

    def test_bom_commented_headers_and_colon_settings_preserve_choices(self):
        source = '\ufeff[Upscalers] ; chosen backend\r\nDx12Upscaler: xess\r\n[Paths]\r\nFfxDx12Path=auto\r\nFfxDx12SRPath=auto\r\n[Menu]\r\nShortcutKey=0x24\r\n'
        result = pin_config(source, self.template, self.settings)
        self.assertTrue(result.startswith('\ufeff[Upscalers] ; chosen backend\r\nDx12Upscaler=fsr31\r\n'))
        self.assertIn('[Menu]\r\nShortcutKey=0x24\r\n', result)

    def test_unusual_value_separators_do_not_create_phantom_lines(self):
        source = self.template + '[Menu]\nValue=hello\u2028Dx12Upscaler=keep\x0cworld\n'
        result = pin_config(source, self.template, self.settings)
        self.assertIn('Value=hello\u2028Dx12Upscaler=keep\x0cworld\n', result)

    def test_indented_key_like_continuation_is_preserved_or_refused(self):
        source = '[Upscalers]\nOther=value\n    Dx12Upscaler=continuation\n[Paths]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n'
        with self.assertRaisesRegex(ValueError, 'structure|safely'):
            pin_config(source, self.template, self.settings)

    def test_special_file_read_is_nonblocking_and_refused(self):
        self.config.write_text(self.template)
        real_open = os.open
        with patch('optiscaler_setup.os.open', wraps=real_open) as opened, patch('optiscaler_setup.stat.S_ISREG', return_value=False):
            self.assertIn('not a regular file', configuration(self.config)[1])
        if hasattr(os, 'O_NONBLOCK'):
            self.assertTrue(opened.call_args.args[1] & os.O_NONBLOCK)

    def test_duplicate_diagnostic_keys_do_not_claim_configured(self):
        self.config.write_text(self.template + '[Other]\nDx12Upscaler=fsr31\n')
        report = self.report()
        self.assertFalse(report['configured'])
        self.assertIn('Repeated setting', '\n'.join(report['checks']))

    def test_20_layout_and_frame_generation_are_configuration_evidence_only(self):
        import json
        from helix20_release import scaler_pairs
        for _, destination in scaler_pairs():
            path = self.root / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'payload')
        marker = self.root / 'HelixSR/helixsr-install.json'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'helixsr': '2.0.0'}))
        self.config.write_text('[Upscalers]\nDx12Upscaler=auto\n[FrameGen]\n'
                               'FGInput=nvngxfg\nFGNvngxReplacement=HelixSR\n')
        report = self.report()
        self.assertTrue(report['configured'])
        self.assertTrue(report['framegen_configured'])
        self.assertEqual(report['framegen_evidence'], 'configured; runtime unverified')
        self.assertFalse(report['missing'])
        self.assertIn('do not prove frame generation ran', '\n'.join(report['checks']))

        selected = self.config.read_text()
        self.config.write_text(selected + 'Enabled=false\n[Other]\nEnabled=true\n')
        disabled = self.report()
        self.assertFalse(disabled['framegen_configured'])
        self.assertEqual(disabled['framegen_evidence'], 'not selected; runtime unknown')
        self.config.write_text(selected)

        self.config.write_text(self.config.read_text().replace('FGInput=nvngxfg', 'FGInput=xefg'))
        report = self.report()
        self.assertTrue(report['configured'])
        self.assertFalse(report['framegen_configured'])
        self.assertEqual(report['framegen_evidence'], 'not selected; runtime unknown')


if __name__ == '__main__':
    unittest.main()
