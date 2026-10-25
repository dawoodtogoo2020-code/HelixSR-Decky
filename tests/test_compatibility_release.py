import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))

import compatibility_release as cr  # noqa: E402


def expected_identity():
    return {
        "version": "1.8.1",
        "url": "https://github.com/lonewolf0622/HelixSR/releases/download/v1.8.1/HelixSR-1.8.1.zip",
        "page": "https://github.com/lonewolf0622/HelixSR/releases/tag/v1.8.1",
        "sha256": "abab32b16acf2536b39663763c355f3cfd35c4876c90297d6b5481bd9ad03a19",
        "size": 55766339,
        "metadata_source": "reviewed-compatibility-release",
        "license_url": "https://github.com/lonewolf0622/HelixSR/blob/v1.8.1/LICENSE",
    }


class ConstantsAndSelectionTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(cr.COMPATIBLE_CHOICE, "compatible-1.8.1")
        self.assertEqual(cr.COMPATIBLE_VERSION, "1.8.1")

    def test_valid_selections(self):
        self.assertEqual(cr.selection(), "latest")
        self.assertEqual(cr.selection(None), "latest")
        self.assertEqual(cr.selection("latest"), "latest")
        self.assertEqual(cr.selection("compatible-1.8.1"), "compatible-1.8.1")

    def test_bad_selections(self):
        bad = [
            True, False, 0, 1, 1.8, [], ["latest"], {}, {"choice": "latest"},
            "", "Latest", " latest", "compatible-1.8.1 ", "COMPATIBLE-1.8.1",
            "1.8.1", "v1.8.1", "compatible-1.9.3", "1.9.3",
            "https://github.com/lonewolf0622/HelixSR/releases/download/v1.8.1/HelixSR-1.8.1.zip",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                cr.selection(value)


class CompatibleReleaseTests(unittest.TestCase):
    def test_exact_identity(self):
        self.assertEqual(cr.compatible_release(), expected_identity())

    def test_returns_new_independent_copy(self):
        first = cr.compatible_release()
        second = cr.compatible_release()
        self.assertIsNot(first, second)
        first["sha256"] = "0" * 64
        first["url"] = "https://example.invalid/evil.zip"
        del first["size"]
        self.assertEqual(cr.compatible_release(), expected_identity())
        self.assertEqual(second, expected_identity())

    def test_validate_accepts_identity_and_returns_copy(self):
        release = cr.compatible_release()
        validated = cr.validate_compatible_release(release)
        self.assertEqual(validated, release)
        self.assertIsNot(validated, release)
        self.assertIsInstance(validated, dict)

    def test_validate_keeps_extra_manager_metadata(self):
        release = expected_identity()
        release["published_at"] = "2026-01-01T00:00:00Z"
        release["asset_name"] = "HelixSR-1.8.1.zip"
        validated = cr.validate_compatible_release(release)
        self.assertEqual(validated["asset_name"], "HelixSR-1.8.1.zip")

    def test_validate_without_descriptive_fields(self):
        release = expected_identity()
        del release["metadata_source"]
        del release["license_url"]
        self.assertEqual(cr.validate_compatible_release(release), release)

    def test_validate_rejects_wrong_identity(self):
        cases = {
            "version": ["1.9.3", "v1.8.1", "1.8.0", None, (1, 8, 1)],
            "url": [
                "https://github.com/lonewolf0622/HelixSR/releases/download/v1.9.3/HelixSR-1.9.3.zip",
                "https://example.invalid/HelixSR-1.8.1.zip",
                "http://github.com/lonewolf0622/HelixSR/releases/download/v1.8.1/HelixSR-1.8.1.zip",
                None,
            ],
            "page": ["https://github.com/lonewolf0622/HelixSR/releases/tag/v1.9.3", None],
            "sha256": [
                "0" * 64,
                "ABAB32B16ACF2536B39663763C355F3CFD35C4876C90297D6B5481BD9AD03A19",
                "abab32b16acf2536b39663763c355f3cfd35c4876c90297d6b5481bd9ad03a1",
                None,
            ],
            "size": [55766340, 0, -1, "55766339", 55766339.0, True, False, None],
            "metadata_source": ["github-latest", "", None],
            "license_url": ["https://github.com/lonewolf0622/HelixSR/blob/v1.9.3/LICENSE", None],
        }
        for key, values in cases.items():
            for value in values:
                release = expected_identity()
                release[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    cr.validate_compatible_release(release)

    def test_validate_rejects_missing_identity_fields(self):
        for key in ("version", "url", "page", "sha256", "size"):
            release = expected_identity()
            del release[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                cr.validate_compatible_release(release)

    def test_validate_rejects_non_mapping(self):
        for value in (None, "compatible-1.8.1", [], list(expected_identity().items())):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cr.validate_compatible_release(value)


class LatestGuardTests(unittest.TestCase):
    def test_supported_old_latest_passes_unchanged(self):
        for version in ("1.8.1", "1.8.0", "1.7.12", "0.9.0"):
            release = {"version": version, "url": "https://example.invalid/a.zip", "extra": [1]}
            snapshot = {"version": version, "url": "https://example.invalid/a.zip", "extra": [1]}
            with self.subTest(version=version):
                self.assertIs(cr.require_supported_latest(release), release)
                self.assertEqual(release, snapshot)

    def test_unsupported_newer_versions(self):
        for version in ("1.9.0", "1.10.0", "2.1.0", "10.0.0", "1.8.2"):
            with self.subTest(version=version):
                with self.assertRaises(ValueError) as ctx:
                    cr.require_supported_latest({"version": version})
                message = str(ctx.exception)
                self.assertIn(version, message)
                self.assertIn("not yet reviewed", message)
                self.assertIn("Check for a plugin update", message)
                self.assertIn("HelixSR 2.0.0 (recommended)", message)

    def test_malformed_versions(self):
        bad = [
            None, 181, 1.8, True, ["1.8.1"], "", "1.8", "1", "1.8.1.0",
            "v1.8.1", "V1.9.3", "01.8.1", "1.08.1", "1.8.01", "1.8.1-beta",
            "1.9.3-rc.1", "1.8.1+build", " 1.8.1", "1.8.1 ", "1.8.1\n",
            "1..1", "a.b.c", "-1.8.1", "１.8.1", "1.8.١",
        ]
        for version in bad:
            with self.subTest(version=version), self.assertRaises(ValueError):
                cr.require_supported_latest({"version": version})

    def test_missing_version_or_non_mapping(self):
        for release in ({}, {"url": "https://example.invalid/a.zip"}, None, "1.8.1", [("version", "1.8.1")]):
            with self.subTest(release=release), self.assertRaises(ValueError):
                cr.require_supported_latest(release)

    def test_compatible_identity_passes_latest_guard(self):
        release = cr.compatible_release()
        self.assertIs(cr.require_supported_latest(release), release)


class _Recorder:
    active = False
    events = []


def _audit(event, args):
    if not _Recorder.active:
        return
    if event.startswith(("socket.", "urllib.", "http.", "subprocess.", "os.system", "os.remove", "shutil.")):
        _Recorder.events.append((event, args))
    elif event == "open" and args:
        path = str(args[0])
        if not (path.endswith((".py", ".pyc")) or "__pycache__" in path):
            _Recorder.events.append((event, args))


_HOOK_INSTALLED = False


class ImportSideEffectTests(unittest.TestCase):
    def test_import_has_no_network_or_file_side_effects(self):
        global _HOOK_INSTALLED
        if not _HOOK_INSTALLED:
            sys.addaudithook(_audit)
            _HOOK_INSTALLED = True
        _Recorder.events = []
        _Recorder.active = True
        try:
            module = importlib.reload(cr)
            module.selection("compatible-1.8.1")
            module.validate_compatible_release(module.compatible_release())
            module.require_supported_latest({"version": "1.8.1"})
        finally:
            _Recorder.active = False
        self.assertEqual(_Recorder.events, [])

    def test_no_manager_or_network_imports(self):
        source = Path(cr.__file__).read_text(encoding="utf-8")
        for name in ("urllib", "socket", "requests", "http", "subprocess", "manager", "sqlite3", "time", "datetime"):
            with self.subTest(name=name):
                self.assertNotRegex(source, rf"^\s*(import|from)\s+[\w.]*{name}", )


if __name__ == "__main__":
    unittest.main()
