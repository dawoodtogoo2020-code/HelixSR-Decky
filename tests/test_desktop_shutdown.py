"""Production event-loop disposal and folder-import notification regressions."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
QT = importlib.util.find_spec('PySide6') is not None
if QT:
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication, QDialog
    from desktop.app import MainWindow, dispose_window


class ImportBackend:
    def __init__(self, error=False):
        self.error = error
        self.imported = []

    def library(self):
        return dict(games=[], jobs=[], warnings=[], release={})

    def check_app_updates(self, force=False):
        return dict(auto_check=False)

    def import_folders(self, folders):
        if self.error:
            raise ValueError('Fixture import failed')
        self.imported = list(folders)
        return self.library()

    def close(self):
        return True


@unittest.skipUnless(QT, 'PySide6 Essentials unavailable; shutdown tests require Qt')
class DesktopShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def settle(self, window):
        deadline = time.monotonic() + 3
        quiet = 0
        while time.monotonic() < deadline:
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            quiet = quiet + 1 if window._task is None else 0
            if quiet > 20:
                return
            time.sleep(.002)
        self.fail('UI operation did not finish')

    def run_import(self, error):
        root = Path(os.environ.get('HELIXSR_TEST_TMP', 'D:/Downloads/Codex/hsrtmp' if os.name == 'nt' else tempfile.gettempdir()))
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix='shutdown-import-') as temp:
            folders = [Path(temp) / 'Game One', Path(temp) / 'Game Two']
            for folder in folders:
                folder.mkdir()
            backend = ImportBackend(error)
            window = MainWindow(backend, auto_load=False)
            window.show()
            window._notify('An old completed installation')
            def select_and_accept():
                dialog = window._active_dialog
                for folder in folders:
                    dialog.add_folder(folder)
                dialog.import_button.click()
            QTimer.singleShot(30, select_and_accept)
            window.import_folders()
            self.settle(window)
            if error:
                self.assertIn('Fixture import failed', window.notice.text())
                self.assertNotIn('Imported 2', window.notice.text())
                self.assertEqual(backend.imported, [])
            else:
                self.assertEqual(window.notice.text(), 'Imported 2 game folders.')
                self.assertEqual(backend.imported, [str(folder.resolve()) for folder in folders])
            window.close()
            self.settle(window)
            dispose_window(self.app, window)

    def test_successful_folder_import_replaces_stale_job_notice(self):
        self.run_import(False)

    def test_failed_folder_import_never_reports_completion(self):
        self.run_import(True)

    def test_repeated_production_processes_dispose_full_ui_workflows(self):
        root = Path(os.environ.get('HELIXSR_TEST_TMP', 'D:/Downloads/Codex/hsrtmp' if os.name == 'nt' else tempfile.gettempdir()))
        root.mkdir(parents=True, exist_ok=True)
        # Each process reaches Python finalization. In-process widget tests alone
        # cannot catch fatal C-extension reference-count failures during exit.
        script = """
import gc
from PySide6.QtWidgets import QApplication
from desktop.app import main
status = main(['--smoke-test', '--smoke-cycles', '3'])
assert status == 0, status
assert QApplication.instance() is None
for _ in range(3):
    gc.collect()
print('FINAL_GC_OK', flush=True)
"""
        env = dict(os.environ, TEMP=str(root), TMP=str(root), HELIXSR_TEST_TMP=str(root))
        for attempt in range(5):
            with self.subTest(process=attempt):
                process = subprocess.run([sys.executable, '-c', script],
                                         cwd=Path(__file__).resolve().parents[1],
                                         env=env, capture_output=True, text=True, timeout=70)
                self.assertEqual(process.returncode, 0, process.stdout + '\n' + process.stderr)
                self.assertIn('PRODUCTION_STRESS_OK', process.stdout)
                self.assertIn('FINAL_GC_OK', process.stdout)
                self.assertNotIn('Fatal Python error', process.stderr)
                self.assertNotIn('QThread: Destroyed while thread', process.stderr)


if __name__ == '__main__':
    unittest.main()
