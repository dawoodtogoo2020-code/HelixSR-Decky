from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.system import system_environment, system_status


class DesktopSystemTests(unittest.TestCase):
    def test_host_tools_get_original_environment(self):
        result = system_environment({'APPDIR': '/bundle', 'LD_LIBRARY_PATH': '/bundle/lib',
            'LD_LIBRARY_PATH_ORIG': '/host/lib', 'PYTHONHOME': '/bundle', 'PYTHONPATH': '/bundle',
            'LD_PRELOAD': '/bundle/preload.so', 'PATH': '/usr/bin'})
        self.assertEqual(result['LD_LIBRARY_PATH'], '/host/lib')
        for key in ('PYTHONHOME', 'PYTHONPATH', 'LD_PRELOAD'):
            self.assertNotIn(key, result)
        self.assertEqual(system_environment({'APPIMAGE': '/a', 'LD_LIBRARY_PATH': '/a/lib'}).get('LD_LIBRARY_PATH'), None)

    def test_absent_probe_is_unknown_not_runtime_failure(self):
        with patch('desktop.system.shutil.which', return_value=None), \
                patch('desktop.system.platform.system', return_value='Linux'), \
                patch('desktop.system.platform.machine', return_value='x86_64'), \
                patch('desktop.system.Path.glob', return_value=[]):
            status = system_status()
        self.assertTrue(status['supported_architecture'])
        self.assertIsNone(status['vulkan']['available'])
        self.assertIn('not been checked', status['vulkan']['error'])
        self.assertTrue(any('physical' in note for note in status['notes']))

    def test_non_appimage_environment_preserved(self):
        self.assertEqual(system_environment({'PYTHONHOME': '/custom'}), {'PYTHONHOME': '/custom'})

    def test_bundle_paths_and_qt_plugins_do_not_reach_host(self):
        with patch('os.pathsep', ':'):
            env = system_environment({'APPDIR': '/bundle', 'PATH': '/bundle/bin:/usr/bin',
                'QT_PLUGIN_PATH': '/bundle/plugins', 'QT_QPA_PLATFORM_PLUGIN_PATH': '/bundle/platforms',
                'SSL_CERT_FILE': '/bundle/cert.pem', 'XDG_DATA_DIRS': '/bundle/share:/usr/share'})
        self.assertEqual(env['PATH'], '/usr/bin')
        self.assertEqual(env['XDG_DATA_DIRS'], '/usr/share')
        for key in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'SSL_CERT_FILE'):
            self.assertNotIn(key, env)


if __name__ == '__main__':
    unittest.main()
