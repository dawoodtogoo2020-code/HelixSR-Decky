"""Reviewed HelixSR 1.8.1 recipe replacement pin and recipe verification guards.

The replacement recipe only changes setup/helixsr_setup.py (an installer branch
that is not run under --separate-files). Whole-archive size/hash verification
remains client preparation's guard; this pin covers source members only.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PY_MODULES = ROOT / 'py_modules'
sys.path.insert(0, str(PY_MODULES))

FIXTURE = ROOT / 'tests' / 'fixtures' / 'reviewed_recipe_1_8_1_replacement.json'
NEW_PIN = '93930e9c131c82fe7810181cc8e6bc81cf18e9203737a9d28d769be5983acaef'
PREVIOUS_PINS = (
    'ac43f9144497a2e9f506d0bb05577328c667d3c657d466f469b9bf13558bb791',
    '712dc923a8149fc0d2fcc6099d2f87df11d77c5999323a41bbc71075c8bd647d',
)
HEX = set('0123456789abcdef')


import model_variants as variants


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _digest_of(hashes):
    return _sha256(json.dumps(hashes, sort_keys=True).encode())


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


class ReviewedReplacementPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_fixture_files_recompute_to_new_exact_pin(self):
        files = self.fixture['files']
        self.assertEqual(_digest_of(files), NEW_PIN)
        self.assertEqual(self.fixture['recipe_sha256'], NEW_PIN)

    def test_fixture_verification_flags(self):
        self.assertIs(self.fixture['source_members_sha256_verified'], True)
        # Deliberate: archive size/hash verification is client preparation's guard.
        self.assertIs(self.fixture['whole_archive_sha256_verified'], False)

    def test_fixture_inventory_matches_recipe_files(self):
        files = self.fixture['files']
        self.assertEqual(len(variants.RECIPE_FILES), 40)
        self.assertEqual(len(set(variants.RECIPE_FILES)), 40)
        self.assertEqual(len(files), 40)
        self.assertEqual(set(files), set(variants.RECIPE_FILES))
        for name, value in files.items():
            self.assertTrue(_is_sha256(value), name)

    def test_new_pin_is_reviewed_and_valid(self):
        self.assertEqual(variants.REVIEWED_RECIPES.get(NEW_PIN), variants.DEFAULT_VARIANT)
        self.assertTrue(variants.valid_variant(dict(
            id=variants.DEFAULT_VARIANT, adapter=variants.ADAPTER, recipe_sha256=NEW_PIN)))

    def test_previous_pins_retained(self):
        for pin in PREVIOUS_PINS:
            self.assertEqual(variants.REVIEWED_RECIPES.get(pin), variants.DEFAULT_VARIANT)
            self.assertTrue(variants.valid_variant(dict(
                id=variants.DEFAULT_VARIANT, adapter=variants.ADAPTER, recipe_sha256=pin)))
        self.assertEqual(len({NEW_PIN, *PREVIOUS_PINS}), 3)

    def test_valid_variant_rejects_malformed_values(self):
        base = dict(id=variants.DEFAULT_VARIANT, adapter=variants.ADAPTER, recipe_sha256=NEW_PIN)
        self.assertFalse(variants.valid_variant(dict(base, adapter='other-adapter')))
        self.assertFalse(variants.valid_variant(dict(base, extra=True)))
        self.assertFalse(variants.valid_variant(dict(base, recipe_sha256='0' * 64)))
        self.assertFalse(variants.valid_variant(dict(base, id='helixsr-unknown')))
        self.assertFalse(variants.valid_variant(None))


class SyntheticRecipeVerificationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.package = Path(self._tmp.name) / 'helixsr'
        self.expected_hashes = {}
        for name in variants.RECIPE_FILES:
            data = ('synthetic placeholder for ' + name + '\n').encode()
            self._write(name, data)
            self.expected_hashes[name] = _sha256(data)
        # Present in packages but intentionally not part of the hashed recipe.
        self._write('setup/helixsr_install.py', b'# synthetic installer\n')
        self.known_digest = _digest_of(self.expected_hashes)

    def _write(self, name, data):
        path = self.package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _permit_known(self):
        return mock.patch.dict(variants.REVIEWED_RECIPES,
                               {self.known_digest: variants.DEFAULT_VARIANT})

    def test_known_digest_is_independently_computed(self):
        self.assertNotIn(self.known_digest, variants.REVIEWED_RECIPES)
        self.assertEqual(variants.recipe_digest(self.package), self.known_digest)

    def test_known_synthetic_recipe_accepted_when_permitted(self):
        with self._permit_known():
            result = variants.verify_recipe(self.package)
            self.assertEqual(result, dict(id=variants.DEFAULT_VARIANT, adapter=variants.ADAPTER,
                                          recipe_sha256=self.known_digest))
            self.assertTrue(variants.valid_variant(result))
        self.assertNotIn(self.known_digest, variants.REVIEWED_RECIPES)
        self.assertFalse(variants.valid_variant(result))

    def _assert_mutation_rejected(self, name):
        self._write(name, (self.package / name).read_bytes() + b'# changed\n')
        with self._permit_known():
            self.assertNotEqual(variants.recipe_digest(self.package), self.known_digest)
            with self.assertRaises(ValueError):
                variants.verify_recipe(self.package)

    def test_shell_wrapper_change_rejected(self):
        self._assert_mutation_rejected('helixsr-setup.sh')

    def test_converter_change_rejected(self):
        self._assert_mutation_rejected('setup/helixsr_setup.py')

    def test_core_source_change_rejected(self):
        self._assert_mutation_rejected('setup/lib/model/model.cpp')

    def test_single_byte_change_rejected(self):
        path = self.package / 'setup/helixsr_setup.py'
        data = bytearray(path.read_bytes())
        data[0] ^= 1
        path.write_bytes(bytes(data))
        with self._permit_known(), self.assertRaises(ValueError):
            variants.verify_recipe(self.package)

    def test_added_setup_member_rejected(self):
        self._write('setup/lib/extra_converter.py', b'# unexpected\n')
        with self._permit_known():
            with self.assertRaises(ValueError):
                variants.recipe_digest(self.package)
            with self.assertRaises(ValueError):
                variants.verify_recipe(self.package)

    def test_missing_setup_member_rejected(self):
        (self.package / 'setup/lib/samplers.py').unlink()
        with self._permit_known():
            with self.assertRaises(ValueError):
                variants.verify_recipe(self.package)

    def test_missing_installer_member_rejected(self):
        (self.package / 'setup/helixsr_install.py').unlink()
        with self._permit_known():
            with self.assertRaises(ValueError):
                variants.verify_recipe(self.package)

    def test_missing_shell_wrapper_rejected(self):
        (self.package / 'helixsr-setup.sh').unlink()
        with self._permit_known():
            with self.assertRaises(ValueError):
                variants.verify_recipe(self.package)

    def test_unknown_recipe_rejected(self):
        self.assertNotIn(self.known_digest, variants.REVIEWED_RECIPES)
        with self.assertRaises(ValueError):
            variants.verify_recipe(self.package)

    def test_unknown_variant_rejected(self):
        with self._permit_known(), self.assertRaises(ValueError):
            variants.verify_recipe(self.package, 'helixsr-unknown')


if __name__ == '__main__':
    unittest.main()
