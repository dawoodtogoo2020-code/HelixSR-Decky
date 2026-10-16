"""Synthetic layout tests only; these are not real game compatibility proof."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from menu_label_profiles import LABEL, WITCHER_XML, patch_witcher3, profile_for


def fixture(label=b'AMD FSR Upscaling', quote=b'"', bom=False, wrapper=True):
    entry = b'<Entry overrideGroup="PostProcess" varId="AAMode" value="5" />'
    if wrapper:
        entry = b'<Entries>' + entry + b'</Entries>'
    option = b'<Option hint="a > b" displayName=' + quote + label + quote + b' id="2">' + entry + b'</Option>'
    raw = (b'<?xml version="1.0" encoding="UTF-8"?>\r\n<UserConfig>\r\n'
           b'<!-- <Option id="2" displayName="AMD FSR Upscaling"/> -->\r\n'
           b'<Var id="Other"><OptionsArray><Option id="2" displayName="AMD FSR Upscaling"/></OptionsArray></Var>\r\n'
           b'<Var tags="graphics; nonLocalizedExceptFirst; pc" id="AAMode"><OptionsArray>'
           b'<Option id="0" displayName="Off"/><Option id="1" displayName="FXAA"/>' + option +
           b'<Option id="3" displayName="DLSS"/><Option id="4" displayName="XeSS"/>'
           b'</OptionsArray></Var>\r\n'
           b'<Var id="FSRFramegen" displayName="AMD FSR 3 Frame Generation"/>\r\n'
           b'</UserConfig>')
    return (b'\xef\xbb\xbf' if bom else b'') + raw, option


class MenuLabelProfiles(unittest.TestCase):
    def test_optional_xml_parsers_are_not_backend_startup_dependencies(self):
        modules = str(Path(__file__).resolve().parents[1] / 'py_modules')
        script = r'''
import builtins
import sys
mode = sys.argv[1]
real_import = builtins.__import__
def without_expat(name, globals=None, locals=None, fromlist=(), level=0):
    if (mode == 'elementtree' and name.startswith('xml.etree')
            or mode == 'expat' and (name in ('pyexpat', 'xml.parsers.expat')
                or name == 'xml.parsers' and 'expat' in fromlist)):
        raise ImportError('fixture: optional XML parser unavailable')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = without_expat
import manager
profile = manager.menu_labels.profile_for({'source': 'Steam', 'appid': '292030'}, 'direct')
assert profile['supported'] is True
try:
    manager.menu_labels.patch_witcher3(b'<xml/>')
except ValueError as exc:
    assert str(exc) == 'Optional menu-label XML parser is unavailable'
else:
    raise AssertionError('missing parser must fail the optional transform closed')
'''
        for mode in ('elementtree', 'expat'):
            with self.subTest(missing=mode):
                completed = subprocess.run(
                    [sys.executable, '-c', script, mode], env={'PYTHONPATH': modules},
                    capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_profile_is_only_exact_steam_direct_target(self):
        game = dict(source='Steam', appid='292030')
        profile = profile_for(game, 'direct')
        self.assertTrue(profile['supported'])
        self.assertEqual(profile['label'], LABEL)
        self.assertEqual(profile['path'], WITCHER_XML)
        self.assertFalse(profile_for(game, 'optiscaler')['supported'])
        self.assertFalse(profile_for(dict(source='Imported', appid='292030'), 'direct')['supported'])
        for appid in ('3357650', '870780', '3669870', '2288340', '', 'unknown'):
            with self.subTest(appid=appid):
                self.assertFalse(profile_for(dict(source='Steam', appid=appid), 'direct')['supported'])
        self.assertFalse(profile_for(None, 'direct')['supported'])

    def test_byte_exact_only_target_with_bom_quotes_and_wrappers(self):
        for bom in (False, True):
            for quote in (b'"', b"'"):
                for wrapper in (False, True):
                    with self.subTest(bom=bom, quote=quote, wrapper=wrapper):
                        raw, option = fixture(quote=quote, bom=bom, wrapper=wrapper)
                        changed = option.replace(b'AMD FSR Upscaling', b'Helix SR')
                        self.assertEqual(patch_witcher3(raw), raw.replace(option, changed, 1))
                        self.assertEqual(raw.count(b'AMD FSR Upscaling'), 3)
                        self.assertEqual(patch_witcher3(raw).count(b'AMD FSR Upscaling'), 2)

    def test_all_allowed_literal_labels(self):
        for label in (b'AMD FSR Upscaling', b'AMD FSR 2', b'AMD FSR 3', b'AMD FSR 3.1', b'FSR 2', b'FSR 3', b'FSR 3.1'):
            raw, option = fixture(label)
            self.assertEqual(patch_witcher3(raw), raw.replace(option, option.replace(label, b'Helix SR'), 1))

    def test_nonascii_outside_target_preserved(self):
        raw, option = fixture()
        raw = raw.replace(b'<UserConfig>', '<UserConfig title="\u00e9\u0627">'.encode())
        self.assertEqual(patch_witcher3(raw), raw.replace(option, option.replace(b'AMD FSR Upscaling', b'Helix SR'), 1))

    def test_unsafe_or_ambiguous_docs(self):
        raw, option = fixture()
        invalid = [
            raw.replace(b'</UserConfig>', b''),
            raw.replace(b'<UserConfig>', b'<!DOCTYPE UserConfig [<!ENTITY x "a">]><UserConfig>'),
            raw.replace(b'<UserConfig>', b'<!ENTITY x "a"><UserConfig>'),
            raw.replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"'),
            raw.replace(b'<UserConfig>', b'<UserConfig title="\xff">'),
            raw.replace(b'<UserConfig>', b'<UserConfig>\x00'),
            raw.replace(b'id="AAMode"', b'id="OtherMode"'),
            raw.replace(b'id="Other"', b'id="AAMode"'),
            raw.replace(b'nonLocalizedExceptFirst', b'nonLocalizedExceptFirstExtra'),
            raw.replace(b'value="5"', b'value="4"'),
            raw.replace(b'varId="AAMode"', b'varId="FSRFramegen"'),
            raw.replace(b'overrideGroup="PostProcess"', b'overrideGroup="Other"'),
            raw.replace(option, option + option),
            raw.replace(option, option.replace(b'id="2"', b'id="3"')),
            raw.replace(option, option.replace(b'id="2"', b'')),
            raw.replace(option, option.replace(b'id="2"', b'id="2" id="2"')),
            raw.replace(option, option.replace(b'displayName="AMD FSR Upscaling"', b'displayName="AMD FSR Upscaling" displayName="AMD FSR 2"')),
            raw.replace(b'<Entries>', b'<Entries><Entry overrideGroup="PostProcess" varId="AAMode" value="5"/>'),
            raw.replace(b'<Entries>', b'<Entries><Unexpected/>'),
            raw.replace(b'<OptionsArray><Option id="0"', b'<OptionsArray/><OptionsArray><Option id="0"'),
            raw.replace(b'<OptionsArray><Option id="0"', b'<OptionsArray><Unexpected/><Option id="0"'),
        ]
        for index, candidate in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                patch_witcher3(candidate)

    def test_normalized_or_unowned_labels_rejected(self):
        for label in (b'Helix SR', b'Unknown FSR', b'AMD FSR&#32;Upscaling', b'AMD FSR\nUpscaling', b'AMD FSR\tUpscaling'):
            raw, _ = fixture(label)
            with self.subTest(label=label), self.assertRaises(ValueError):
                patch_witcher3(raw)

    def test_limits_and_input_type(self):
        for raw in (None, '', bytearray(b'<x/>'), b'', b'x' * (128 * 1024 + 1)):
            with self.subTest(kind=type(raw)), self.assertRaises(ValueError):
                patch_witcher3(raw)

    def test_already_patched_is_not_adopted(self):
        raw, _ = fixture()
        with self.assertRaises(ValueError):
            patch_witcher3(patch_witcher3(raw))


if __name__ == '__main__':
    unittest.main()
