import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_MODULES = REPO_ROOT / "py_modules"

if str(PY_MODULES) not in sys.path:
    sys.path.insert(0, str(PY_MODULES))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from discovery_records import normalize_imports
except ImportError:
    from py_modules.discovery_records import normalize_imports

try:
    import library
except ImportError:
    from py_modules import library


class CustomPathLike(os.PathLike):
    def __init__(self, path):
        self._path = path

    def __fspath__(self):
        return self._path


class RaisingPathLike(os.PathLike):
    def __init__(self, exc_cls):
        self._exc_cls = exc_cls

    def __fspath__(self):
        raise self._exc_cls("PathLike conversion failed")


class NormalizerTests(unittest.TestCase):
    def test_normal_list_and_tuple(self):
        records_list = [
            {"folder": "/games/portal", "name": "Portal", "appid": 400},
            {"folder": "/games/half_life", "name": "Half-Life", "custom_key": 42},
        ]
        valid, warnings = normalize_imports(records_list)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(warnings), 0)
        self.assertEqual(valid[0]["folder"], "/games/portal")
        self.assertEqual(valid[0]["name"], "Portal")
        self.assertEqual(valid[0]["appid"], 400)
        self.assertEqual(valid[1]["folder"], "/games/half_life")
        self.assertEqual(valid[1]["name"], "Half-Life")
        self.assertEqual(valid[1]["custom_key"], 42)

        records_tuple = (
            {"folder": "/games/celeste", "name": "Celeste"},
        )
        valid_tuple, warnings_tuple = normalize_imports(records_tuple)
        self.assertEqual(len(valid_tuple), 1)
        self.assertEqual(len(warnings_tuple), 0)
        self.assertEqual(valid_tuple[0]["name"], "Celeste")
        self.assertIsInstance(valid_tuple, list)

    def test_none_input_treated_as_empty(self):
        valid, warnings = normalize_imports(None)
        self.assertEqual(valid, [])
        self.assertEqual(warnings, [])

    def test_invalid_top_level_collections_and_scalars(self):
        invalid_inputs = [
            42,
            3.14,
            "not-a-list",
            True,
            {"folder": "/games/single"},
            {1, 2, 3},
            (x for x in range(3)),
        ]
        for invalid in invalid_inputs:
            valid, warnings = normalize_imports(invalid)
            self.assertEqual(valid, [])
            self.assertGreaterEqual(len(warnings), 1)
            self.assertTrue(all("Imported" in w for w in warnings))

    def test_mixed_records_malformed_folder(self):
        good_1 = {"folder": "/games/good1", "name": "Good 1"}
        good_2 = {"folder": "/games/good2", "name": "Good 2"}
        mixed = [
            good_1,
            {"folder": 42, "name": "Bad Int Folder"},
            {"folder": b"/bytes/folder", "name": "Bad Bytes Folder"},
            {"folder": "/games/with_\0_nul", "name": "Bad NUL Folder"},
            {"folder": "", "name": "Bad Empty Folder"},
            {"name": "Missing Folder Key"},
            "scalar string record",
            123,
            None,
            ["nested list record"],
            good_2,
        ]
        valid, warnings = normalize_imports(mixed)
        self.assertEqual(len(valid), 2)
        self.assertEqual(valid[0]["name"], "Good 1")
        self.assertEqual(valid[1]["name"], "Good 2")
        self.assertGreaterEqual(len(warnings), 8)
        self.assertTrue(all("Imported" in w for w in warnings))

    def test_pathlike_folder_handling(self):
        good_custom = CustomPathLike("/games/custom_path")
        good_pathlib = Path("/games/pathlib_path")
        valid, warnings = normalize_imports([
            {"folder": good_custom, "name": "Custom Path"},
            {"folder": good_pathlib, "name": "Pathlib Path"},
        ])
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(warnings), 0)
        self.assertEqual(valid[0]["folder"], "/games/custom_path")
        self.assertIsInstance(valid[0]["folder"], str)
        self.assertEqual(valid[1]["folder"], str(good_pathlib))
        self.assertIsInstance(valid[1]["folder"], str)

        invalid_pathlikes = [
            CustomPathLike(b"/games/bytes_from_fspath"),
            RaisingPathLike(TypeError),
            RaisingPathLike(ValueError),
            RaisingPathLike(OSError),
        ]
        for bad_pl in invalid_pathlikes:
            v, w = normalize_imports([{"folder": bad_pl, "name": "Bad PathLike"}])
            self.assertEqual(v, [])
            self.assertEqual(len(w), 1)
            self.assertIn("Imported", w[0])

    def test_name_fallback_rules(self):
        records = [
            {"folder": "/games/custom_named", "name": "Custom Name"},
            {"folder": "/games/empty_named", "name": ""},
            {"folder": "/games/none_named", "name": None},
            {"folder": "/games/int_named", "name": 999},
            {"folder": "/games/missing_named"},
            {"folder": "/"},
            {"folder": "/", "name": ""},
            {"folder": "/", "name": None},
            {"folder": "/", "name": "Explicit Root Game"},
        ]
        valid, warnings = normalize_imports(records)
        self.assertEqual(len(valid), len(records))
        self.assertEqual(len(warnings), 0)
        self.assertEqual(valid[0]["name"], "Custom Name")
        self.assertEqual(valid[1]["name"], "empty_named")
        self.assertEqual(valid[2]["name"], "none_named")
        self.assertEqual(valid[3]["name"], "int_named")
        self.assertEqual(valid[4]["name"], "missing_named")
        self.assertEqual(valid[5]["name"], "Imported game")
        self.assertEqual(valid[6]["name"], "Imported game")
        self.assertEqual(valid[7]["name"], "Imported game")
        self.assertEqual(valid[8]["name"], "Explicit Root Game")

    def test_input_nonmutation_and_entry_copy(self):
        original_entry = {"folder": "/games/original", "name": "Original", "extra": [1, 2]}
        records = [original_entry]
        valid, _ = normalize_imports(records)
        self.assertEqual(len(valid), 1)
        self.assertIsNot(valid[0], original_entry)
        self.assertEqual(original_entry, {"folder": "/games/original", "name": "Original", "extra": [1, 2]})
        valid[0]["name"] = "Mutated"
        valid[0]["extra"].append(3)
        self.assertEqual(original_entry["name"], "Original")

    def test_whitespace_preservation(self):
        valid, warnings = normalize_imports([{"folder": "  /games/has spaces/  "}])
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["folder"], "  /games/has spaces/  ")
        self.assertEqual(len(warnings), 0)

    def test_warning_capping_and_trailing_good_retained(self):
        bad_records = [{"folder": 42} for _ in range(25)]
        good_trailing = {"folder": "/games/trailing", "name": "Trailing Good"}
        records = bad_records + [good_trailing]

        valid, warnings = normalize_imports(records)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["name"], "Trailing Good")
        self.assertEqual(len(warnings), 21)
        self.assertTrue(all("Imported" in w for w in warnings))

        twenty_bad = [{"folder": 42} for _ in range(20)]
        valid_twenty, warnings_twenty = normalize_imports(twenty_bad)
        self.assertEqual(valid_twenty, [])
        self.assertEqual(len(warnings_twenty), 20)
        self.assertTrue(all("Imported" in w for w in warnings_twenty))


class DiscoveryIntegrationTests(unittest.TestCase):
    def _extract_items(self, result):
        return result[0]

    def _get_field(self, item, field):
        if isinstance(item, dict):
            return item.get(field)
        return getattr(item, field, None)

    def test_discover_imported_integration_healthy_invalid_deduplication(self):
        mixed_records = [
            {"folder": "/games/game_alpha", "name": "Alpha Game", "appid": 100},
            {"folder": 42, "name": "Bad Game 42"},
            {"folder": "/games/game_beta", "name": "Beta Game"},
            {"folder": b"/games/bad_bytes", "name": "Bad Bytes Game"},
            {"folder": "/games/game_alpha", "name": "Alpha Duplicate"},
            {"folder": "/games/bad_\0_nul", "name": "Bad NUL Game"},
            "not a record dict",
            {"folder": ""},
        ]

        with patch.object(library, "safe_root", side_effect=lambda p: Path(p)):
            result = library.discover("unused_home", imported=mixed_records, sources={"imported"})
        self.assertGreater(len(result[1]), 0)
        self.assertTrue(any("Imported" in msg for msg in result[1]))

        games = self._extract_items(result)
        names = [self._get_field(g, "name") for g in games]
        self.assertIn("Alpha Game", names)
        self.assertIn("Beta Game", names)
        self.assertNotIn("Bad Game 42", names)
        self.assertNotIn("Bad Bytes Game", names)
        self.assertNotIn("Bad NUL Game", names)

        folders = [
            str(self._get_field(g, "folder") or self._get_field(g, "root") or self._get_field(g, "path") or "")
            for g in games
        ]
        self.assertEqual(folders.count(str(Path("/games/game_alpha"))), 1)
        self.assertEqual(len(games), 2)

    def test_discover_imported_source_disabled(self):
        records = [{"folder": "/games/game_disabled", "name": "Disabled Game"}]
        with patch.object(library, "safe_root", side_effect=lambda p: Path(p)):
            result = library.discover("unused_home", imported=records, sources=set())
        games = self._extract_items(result)
        self.assertEqual(len(games), 0)

    def test_discover_imported_empty_and_none(self):
        with patch.object(library, "safe_root", side_effect=lambda p: Path(p)):
            res_empty = library.discover("unused_home", imported=(), sources={"imported"})
            res_none = library.discover("unused_home", imported=None, sources={"imported"})
        self.assertEqual(len(self._extract_items(res_empty)), 0)
        self.assertEqual(len(self._extract_items(res_none)), 0)


if __name__ == "__main__":
    unittest.main()
