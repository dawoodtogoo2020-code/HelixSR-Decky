"""Embedded-Python discovery without the optional SQLite native extension."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OptionalSQLiteTests(unittest.TestCase):
    def check_discovery(self, failure):
        with tempfile.TemporaryDirectory(dir=os.environ.get('HELIXSR_TEST_TMP')) as directory:
            script = r'''
import builtins, pathlib, sys
sys.path.insert(0, sys.argv[1])
base=pathlib.Path(sys.argv[2]); home=base/'home'; game=base/'games'/'example'
game.mkdir(parents=True); (game/'game.exe').write_bytes(b'synthetic fixture')
steam=home/'.local/share/Steam'; apps=steam/'steamapps'; apps.mkdir(parents=True)
common=apps/'common'/'Example'; common.mkdir(parents=True)
(apps/'appmanifest_123.acf').write_text('"AppState" { "appid" "123" "name" "Example" "installdir" "Example" "StateFlags" "4" }')
configs=home/'.config/lutris/games'; configs.mkdir(parents=True)
(configs/'example.yml').write_text('name: Lutris Example\ngame:\n  exe: "'+str(game/'game.exe')+'"\n')
db=home/'.local/share/lutris/pga.db'; db.parent.mkdir(parents=True); db.write_bytes(b'not opened without sqlite')
real=builtins.__import__; attempted=[]
def limited(name,*args,**kwargs):
    if name in ('sqlite3','_sqlite3'):
        attempted.append(name)
        if sys.argv[3]=='oserror': raise OSError('fixture native library missing')
        raise ModuleNotFoundError('fixture optional extension unavailable')
    return real(name,*args,**kwargs)
builtins.__import__=limited
import manager, library
assert not attempted, 'optional SQLite was imported during backend startup'
entries,warnings=library.discover(home,sources={'steam'})
assert [x['appid'] for x in entries]==['123'], (entries,warnings)
assert not attempted, 'Steam discovery tried to load SQLite'
entries,warnings=library.discover(home,sources={'steam','lutris'})
assert len(entries)==2 and {x['source'] for x in entries}=={'Steam','Lutris'}, (entries,warnings)
assert len([w for w in warnings if 'database support is unavailable' in w])==1, warnings
assert attempted, 'Lutris database fallback was not exercised'
print('STEAM_AND_LUTRIS_DISCOVERY_OK')
'''
            result = subprocess.run([sys.executable, '-B', '-c', script,
                                     str(ROOT / 'py_modules'), directory, failure],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('STEAM_AND_LUTRIS_DISCOVERY_OK', result.stdout)

    def test_missing_sqlite_keeps_backend_steam_and_yaml_discovery_working(self):
        self.check_discovery('missing')

    def test_unloadable_sqlite_native_library_falls_back_to_yaml(self):
        self.check_discovery('oserror')


if __name__ == '__main__':
    unittest.main()
