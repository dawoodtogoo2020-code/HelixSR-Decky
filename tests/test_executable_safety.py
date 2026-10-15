"""Synthetic anti-cheat fixtures do not prove a title's runtime compatibility."""
import unittest
from pathlib import Path
from test_backend import Fixtures, pe, write


class ExecutableSafetyTests(unittest.TestCase):
    setUp = Fixtures.setUp

    def test_ea_protected_launchers_are_never_offered_or_selected(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        for name in ('EA AntiCheat.exe', 'EAAntiCheat.GameServiceLauncher.exe',
                     'EA_Javelin.exe', 'JavelinAntiCheat.exe'):
            with self.subTest(name=name):
                launcher = write(self.root / name, pe(dx12=True) + b'large helper' * 4096)
                data = self.m.assess(self.game)
                self.assertEqual(Path(data['main_exe']).name, 'Example.exe')
                self.assertNotIn(name, [choice['path'] for choice in data['executable_choices']])
                self.assertEqual(data['compatibility'], 'blocked')
                self.assertIn('Anti-cheat files detected; injection is blocked', data['reasons'])
                with self.assertRaises(ValueError):
                    self.m.assess(self.game, executable=name)
                # Choosing a different executable cannot bypass title protection.
                with self.assertRaisesRegex(ValueError, 'Anti-cheat'):
                    self.m.preview(self.game['id'], 'install', executable='Example.exe')
                launcher.unlink()

    def test_executable_in_ea_anticheat_directory_is_not_a_game(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        helper = write(self.root / 'EA AntiCheat' / 'Runtime.exe', pe(dx12=True) + b'large' * 8192)
        data = self.m.assess(self.game)
        self.assertEqual(data['selected_executable'], 'Example.exe')
        self.assertNotIn(helper.relative_to(self.root).as_posix(), [x['path'] for x in data['executable_choices']])
        self.assertEqual(data['compatibility'], 'blocked')


if __name__ == '__main__':
    unittest.main()
