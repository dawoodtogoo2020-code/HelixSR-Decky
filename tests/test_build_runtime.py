"""Isolated Steam runtime discovery, with no installed Steam dependency."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))
import build_runtime
import library


class WineDiscoveryTests(unittest.TestCase):
    def setUp(self):
        work = PLUGIN.parent.parent / 'work'
        work.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='wine-', dir=work)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.native, self.alias, self.alias2, self.flatpak = library.steam_roots(self.home)

    def wine(self, base, name='Proton Test', layout='files', custom=False, executable=True):
        parent = 'compatibilitytools.d' if custom else 'steamapps/common'
        path = base / parent / name / layout / 'bin/wine'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture', encoding='utf-8')
        path.chmod(0o755 if executable else 0o644)
        return path.resolve()

    def metadata(self, root, entries):
        path = root / 'steamapps/libraryfolders.vdf'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entries, encoding='utf-8')

    def quoted(self, path):
        return str(path).replace('\\', '\\\\').replace('"', '\\"')

    def test_native_external_library_only_supports_spaces_quotes_and_old_layout(self):
        external = self.base / "External library's games"
        expected = self.wine(external, 'Proton 7', 'dist')
        self.metadata(self.native, '"libraryfolders" { "1" { "path" "' + self.quoted(external) + '" } }')
        original_home = os.environ.get('HOME')
        self.assertEqual(build_runtime.wine_candidates(self.home), [expected])
        self.assertEqual(os.environ.get('HOME'), original_home)

    def test_flatpak_only_default_external_and_custom_tools(self):
        default = self.wine(self.flatpak, 'Proton 9')
        custom = self.wine(self.flatpak, 'GE-Proton Test', custom=True)
        external = self.base / 'Flatpak External'
        additional = self.wine(external, 'Proton Experimental', 'dist')
        self.metadata(self.flatpak, '"libraryfolders" { "1" "' + self.quoted(external) + '" }')
        self.assertEqual(build_runtime.wine_candidates(self.home), [default, custom, additional])

    def test_native_precedes_flatpak_and_tool_order_is_deterministic(self):
        flatpak = self.wine(self.flatpak, 'Proton 0')
        z = self.wine(self.native, 'Proton Z')
        a = self.wine(self.native, 'Proton A')
        expected = [a, z, flatpak]
        self.assertEqual(build_runtime.wine_candidates(self.home), expected)
        self.assertEqual(build_runtime.wine_candidates(self.home), expected)

    def test_duplicate_metadata_paths_are_deduplicated(self):
        external = self.base / 'external'
        expected = self.wine(external)
        quoted = self.quoted(external)
        self.metadata(self.native, '"libraryfolders" { "1" "' + quoted + '" "2" { "path" "' + quoted + '" } }')
        self.metadata(self.flatpak, '"libraryfolders" { "1" "' + quoted + '" }')
        self.assertEqual(build_runtime.wine_candidates(self.home), [expected])

    def test_native_alias_root_and_both_layouts_are_supported(self):
        modern = self.wine(self.alias2, layout='files')
        legacy = self.wine(self.alias2, layout='dist')
        self.assertEqual(build_runtime.wine_candidates(self.home), [modern, legacy])

    def test_numeric_library_order_and_nonnumeric_metadata_are_respected(self):
        second = self.base / 'second'
        tenth = self.base / 'tenth'
        ignored = self.base / 'ignored'
        a = self.wine(second)
        b = self.wine(tenth)
        self.wine(ignored)
        self.metadata(self.native, '"libraryfolders" { "10" "' + self.quoted(tenth) +
                      '" "2" "' + self.quoted(second) + '" "contentstatsid" "' +
                      self.quoted(ignored) + '" }')
        self.assertEqual(build_runtime.wine_candidates(self.home), [a, b])

    def test_symlink_roots_tools_and_external_libraries_resolve_and_deduplicate(self):
        expected = self.wine(self.native)
        external = self.base / 'external'
        additional = self.wine(external, 'Proton External')
        linked_external = self.base / 'linked external'
        self.alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.alias.symlink_to(self.native, target_is_directory=True)
            linked_external.symlink_to(external, target_is_directory=True)
            (self.native / 'compatibilitytools.d').mkdir()
            (self.native / 'compatibilitytools.d/alias').symlink_to(expected.parents[2], target_is_directory=True)
        except OSError as error:
            self.skipTest('Directory symlinks unavailable: ' + str(error))
        self.metadata(self.native, '"libraryfolders" { "1" "' + self.quoted(linked_external) + '" }')
        self.assertEqual(build_runtime.wine_candidates(self.home), [expected, additional])

    def test_malformed_or_wrong_shape_metadata_preserves_default_candidates(self):
        expected = self.wine(self.native)
        for data in ('"libraryfolders" { "1" {', '"libraryfolders" "wrong shape"'):
            with self.subTest(data=data):
                self.metadata(self.native, data)
                self.assertEqual(build_runtime.wine_candidates(self.home), [expected])

    def test_invalid_relative_missing_and_unrelated_candidates_are_ignored(self):
        self.wine(self.native, 'Ordinary Game')
        missing = self.native / 'steamapps/common/Proton Missing/files/bin'
        missing.mkdir(parents=True)
        directory = self.native / 'steamapps/common/Proton Directory/files/bin/wine'
        directory.mkdir(parents=True)
        self.metadata(self.native, '"libraryfolders" { "1" { "path" { "bad" "value" } } "2" "relative" "3" "' + self.quoted(self.base / 'missing') + '" }')
        self.assertEqual(build_runtime.wine_candidates(self.home), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX execute permission semantics')
    def test_posix_nonexecutables_are_ignored(self):
        self.wine(self.native, executable=False)
        self.assertEqual(build_runtime.wine_candidates(self.home), [])

    def test_discovery_never_runs_candidate(self):
        expected = self.wine(self.native)
        with patch('subprocess.run', side_effect=AssertionError('Must not execute')):
            self.assertEqual(build_runtime.wine_candidates(self.home), [expected])


if __name__ == '__main__':
    unittest.main()
