"""Game folder scans: large games, scan limits and walk order. Synthetic files only.

DeckWiz reported God of War (2018) as "Review required: Game scan file limit
exceeded" on 0.1.50. The scan stopped at 50,000 files, which large games pass.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from .test_backend import Fixtures, library, manager, pe, write
except ImportError:
    from test_backend import Fixtures, library, manager, pe, write

import installation_status


def walk_scan(folder, depth=9):
    """The os.walk scan used up to 0.1.51, without its limits: the reference."""
    root, result = Path(folder).resolve(), []
    for directory, dirs, files in os.walk(root, followlinks=False):
        p = Path(directory)
        level = len(p.relative_to(root).parts)
        dirs[:] = [d for d in dirs if d.lower() not in ('helixsr', '.git', 'node_modules')
                   and not (p / d).is_symlink()] if level < depth else []
        result.append((p, [n for n in files if not (p / n).is_symlink()]))
    return result


def touch_many(folder, count, per_folder=1000):
    for start in range(0, count, per_folder):
        directory = Path(folder) / f'pack{start // per_folder:04d}'
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(start, min(count, start + per_folder)):
            (directory / f'asset{index:07d}.bin').touch()


class ScanTreeTests(Fixtures):
    def test_scan_matches_the_previous_walk_order_and_filters(self):
        outside = self.base / 'outside'
        write(outside / 'Hidden.exe', pe())
        write(self.root / 'Engine/Binaries/Win64/Game-Win64-Shipping.exe', pe(dx12=True))
        write(self.root / 'Engine/Content/Paks/pakchunk0.pak', b'pak')
        write(self.root / 'HelixSR/helixsr.log', 'skipped folder')
        write(self.root / '.git/config', 'skipped folder')
        write(self.root / 'Mods/node_modules/x.js', 'skipped folder')
        write(self.root / 'Redist/vc_redist.x64.exe', pe())
        deep = self.root.joinpath(*[f'd{i}' for i in range(12)])
        write(deep / 'TooDeep.dll', b'below the depth limit')
        os.symlink(outside, self.root / 'LinkedFolder', target_is_directory=True)
        os.symlink(outside / 'Hidden.exe', self.root / 'Linked.exe')
        os.symlink(self.base / 'missing', self.root / 'Broken.dll')
        expected = walk_scan(self.root)
        self.assertEqual(library.scan_tree(self.root), expected)
        names = {n for _, ns in expected for n in ns}
        self.assertIn('Game-Win64-Shipping.exe', names)
        self.assertFalse(names & {'Hidden.exe', 'Linked.exe', 'Broken.dll', 'helixsr.log', 'config', 'x.js', 'TooDeep.dll'})

    def test_more_than_fifty_thousand_files_is_assessed(self):
        # The God of War (2018) case: a large game must still be a candidate.
        touch_many(self.root / 'exec', 60_001)
        data = self.m.assess_safe(self.game)
        self.assertEqual(data['compatibility'], 'candidate', data['reasons'])
        self.assertFalse(any('scan' in reason.lower() for reason in data['reasons']), data['reasons'])
        self.assertEqual(data['route'], 'direct')
        self.assertEqual(sum(len(ns) for _, ns in library.scan_tree(self.root)), 60_003)

    def test_file_limit_names_the_limit_and_explains_the_review(self):
        touch_many(self.root / 'exec', 30, per_folder=10)
        with self.assertRaisesRegex(ValueError, r'^Game scan file limit exceeded: more than 20 files$'):
            library.scan_tree(self.root, max_files=20)
        with patch('manager.scan_tree', side_effect=lambda root: library.scan_tree(root, max_files=20)):
            data = self.m.assess_safe(self.game)
        self.assertEqual(data['compatibility'], 'blocked')
        issue = data['installation_status']['issues'][0]
        self.assertEqual(issue['code'], 'scan_limit')
        self.assertEqual(issue['title'], 'Game folder too large to scan')
        self.assertIn('nothing in it was checked or changed', issue['steps'][0])

    def test_directory_limit_stops_with_a_clear_error(self):
        for index in range(3):
            (self.root / f'empty{index}').mkdir()
        with self.assertRaisesRegex(ValueError, r'^Game scan directory limit exceeded: more than 3 folders$'):
            library.scan_tree(self.root, max_dirs=3)
        self.assertEqual(len(library.scan_tree(self.root, max_dirs=4)), 4)

    def test_default_limits_leave_room_for_large_games(self):
        self.assertGreaterEqual(library.SCAN_MAX_FILES, 1_000_000)
        self.assertGreaterEqual(library.SCAN_MAX_DIRECTORIES, 200_000)

    @unittest.skipIf(os.name != 'posix' or os.geteuid() == 0, 'needs a regular POSIX user')
    def test_unreadable_folder_is_skipped_like_before(self):
        locked = self.root / 'Locked'
        write(locked / 'Inside.dll', b'unreadable')
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        self.assertEqual(library.scan_tree(self.root), walk_scan(self.root))
        self.assertNotIn('Inside.dll', {n for _, ns in library.scan_tree(self.root) for n in ns})

    def test_scan_limit_reasons_are_classified(self):
        for reason in ('Game scan file limit exceeded: more than 1,000,000 files',
                       'Game scan directory limit exceeded: more than 200,000 folders',
                       'Game scan file limit exceeded'):
            self.assertEqual(installation_status._issue(reason)[0], 'scan_limit')

    def test_assessed_names_cover_every_name_assess_reads(self):
        self.assertTrue(set(manager.INPUTS) <= manager.ASSESSED_NAMES)
        self.assertIn(manager.DLL, manager.ASSESSED_NAMES)
        self.assertIn('amd_fidelityfx_upscaler_dx12.dll', manager.ASSESSED_NAMES)
        self.assertTrue(set(manager.OPTISCALER_PROXIES) <= manager.ASSESSED_NAMES)


if __name__ == '__main__':
    unittest.main()
