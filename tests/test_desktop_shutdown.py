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

    def test_production_main_disposes_nested_picker_ui_before_interpreter_exit(self):
        root = Path(os.environ.get('HELIXSR_TEST_TMP', 'D:/Downloads/Codex/hsrtmp' if os.name == 'nt' else tempfile.gettempdir()))
        root.mkdir(parents=True, exist_ok=True)
        script = r"""
import gc, json, os, sys
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import desktop.app as ui

root = Path(sys.argv[1])
folders = [root / 'Game One', root / 'Game Two']
for folder in folders:
    folder.mkdir()
record = {'folders': [], 'launchers': [], 'closed': 0, 'destroyed': False, 'errors': []}

class Backend:
    def __init__(self, **kwargs): pass
    def library(self): return dict(games=[], jobs=[], warnings=[], release={})
    def check_app_updates(self, force=False): return dict(auto_check=False)
    def import_folders(self, values):
        record['folders'] = values
        return self.library()
    def import_launcher(self, source):
        record['launchers'].append(source)
        return self.library()
    def close(self):
        record['closed'] += 1
        return True

class AutomatedWindow(ui.MainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = 0
        self.destroyed.connect(lambda: record.update(destroyed=True))
        self.workflow = QTimer(self)
        self.workflow.setInterval(20)
        self.workflow.timeout.connect(self.advance)
        self.workflow.start()
    def advance(self):
        if self._task or self._modal or self._closing: return
        try:
            if self.stage == 0:
                self.stage = 1
                QTimer.singleShot(20, self.pick_folders)
                self.import_folders()
            elif self.stage in (1, 2):
                source = ('heroic', 'lutris')[self.stage - 1]
                self.stage += 1
                self.launchers.setCurrentIndex(self.launchers.findData(source))
                self.import_button.click()
            elif self.stage == 3:
                self.stage = 4
                assert record['folders'] == [str(f.resolve()) for f in folders]
                assert record['launchers'] == ['heroic', 'lutris']
                self.close()
        except Exception as exc:
            record['errors'].append(str(exc))
            self.receive_shutdown_signal()
    def pick_folders(self):
        dialog = self._active_dialog
        for folder in folders:
            def choose(path=folder):
                picker = dialog._picker
                picker.setDirectory(str(path))
                QTimer.singleShot(30, picker.accept)
            QTimer.singleShot(30, choose)
            dialog.add_button.click()
        dialog.import_button.click()

with patch('desktop.backend.DesktopBackend', Backend), patch.object(ui, 'MainWindow', AutomatedWindow):
    status = ui.main(['--home', str(root), '--settings', str(root / 'settings')])
assert status == 0, status
assert record['destroyed'], record
assert record['closed'] == 1, record
assert QApplication.instance() is None
assert not record['errors'], record
for _ in range(3): gc.collect()
print('PRODUCTION_CLOSE_OK ' + json.dumps(record), flush=True)
"""
        with tempfile.TemporaryDirectory(dir=root, prefix='shutdown-process-') as temp:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TEMP=str(root), TMP=str(root), HELIXSR_TEST_TMP=str(root))
            process = subprocess.run([sys.executable, '-c', script, temp], cwd=Path(__file__).resolve().parents[1],
                                     env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(process.returncode, 0, process.stdout + '\n' + process.stderr)
            self.assertIn('PRODUCTION_CLOSE_OK', process.stdout)
            self.assertNotIn('Fatal Python error', process.stderr)
            self.assertNotIn('QThread: Destroyed while thread', process.stderr)


if __name__ == '__main__':
    unittest.main()
