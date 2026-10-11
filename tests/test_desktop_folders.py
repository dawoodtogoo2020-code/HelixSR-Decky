"""Real Qt folder selection tests; all fixture directories are isolated and disposable."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
QT = importlib.util.find_spec('PySide6') is not None
if QT:
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
    from desktop.folder_dialog import FolderDialog


@unittest.skipUnless(QT, 'PySide6 Essentials unavailable; folder tests require Qt')
class FolderDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        task_root = Path('D:/Downloads/Codex/hsrtmp') if os.name == 'nt' else Path(tempfile.gettempdir()) / 'helixsr-folder-tests'
        task_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=task_root, prefix='folders-')
        self.root = Path(self.temporary.name)
        self.first = self.root / 'Game One'
        self.second = self.root / 'Game Two'
        self.first.mkdir()
        self.second.mkdir()
        self.dialog = FolderDialog()
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temporary.cleanup()

    def choose(self, folder):
        result = []
        def pick():
            picker = self.dialog._picker
            result.append(picker is not None)
            if picker:
                picker.setDirectory(str(folder))
                # Directory navigation populates QFileSystemModel asynchronously.
                QTimer.singleShot(30, picker.accept)
        QTimer.singleShot(40, pick)
        self.dialog.add_button.click()
        self.assertEqual(result, [True])

    def test_add_two_using_real_single_directory_pickers_then_import(self):
        self.assertFalse(self.dialog.import_button.isEnabled())
        self.choose(self.first)
        self.choose(self.second)
        expected = [str(self.first.resolve()), str(self.second.resolve())]
        self.assertEqual(self.dialog.selectedFiles(), expected)
        self.assertEqual([self.dialog.folders.item(i).text() for i in range(2)], expected)
        self.assertTrue(self.dialog.import_button.isEnabled())
        QTimer.singleShot(20, self.dialog.import_button.click)
        self.assertEqual(self.dialog.exec(), QDialog.Accepted)
        self.assertEqual(self.dialog.selectedFiles(), expected)
        self.assertLessEqual(self.dialog.width(), 1280)
        self.assertLessEqual(self.dialog.height(), 800)

    def test_duplicate_and_invalid_folders_are_not_added(self):
        self.assertTrue(self.dialog.add_folder(self.first))
        self.assertFalse(self.dialog.add_folder(self.first / '..' / 'Game One'))
        self.assertEqual(self.dialog.folders.count(), 1)
        self.assertIn('already listed', self.dialog.notice.text())
        self.assertFalse(self.dialog.add_folder(self.root / 'missing'))
        file_path = self.root / 'not-a-directory.txt'
        file_path.write_text('fixture', encoding='utf-8')
        self.assertFalse(self.dialog.add_folder(file_path))
        self.assertEqual(self.dialog.selectedFiles(), [str(self.first.resolve())])

    def test_remove_selected_and_empty_import_disabled(self):
        self.dialog.add_folder(self.first)
        self.dialog.add_folder(self.second)
        self.dialog.folders.item(0).setSelected(True)
        self.dialog.remove_button.click()
        self.assertEqual(self.dialog.selectedFiles(), [str(self.second.resolve())])
        self.dialog.folders.item(0).setSelected(True)
        self.dialog.remove_button.click()
        self.assertEqual(self.dialog.selectedFiles(), [])
        self.assertFalse(self.dialog.import_button.isEnabled())
        self.assertFalse(self.dialog.remove_button.isEnabled())
        self.dialog.accept()
        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)

    def test_cancel_returns_rejected_and_does_not_write_game_files(self):
        self.dialog.add_folder(self.first)
        self.dialog.add_folder(self.second)
        QTimer.singleShot(20, self.dialog.reject)
        self.assertEqual(self.dialog.exec(), QDialog.Rejected)
        self.assertEqual(list(self.first.iterdir()), [])
        self.assertEqual(list(self.second.iterdir()), [])

    def test_cancel_single_picker_keeps_existing_folder_list(self):
        self.dialog.add_folder(self.first)
        QTimer.singleShot(40, lambda: self.dialog._picker.reject())
        self.dialog.add_button.click()
        self.assertEqual(self.dialog.selectedFiles(), [str(self.first.resolve())])
        self.assertIsNone(self.dialog._picker)
        self.assertTrue(self.dialog.import_button.isEnabled())

    def test_parent_rejection_closes_nested_picker_without_stale_add(self):
        self.dialog.add_folder(self.first)
        observations = []
        def reject_parent():
            observations.append(self.dialog._picker is not None)
            observations.append(not self.dialog.import_button.isEnabled())
            self.dialog.reject()
        QTimer.singleShot(10, self.dialog.add_button.click)
        QTimer.singleShot(60, reject_parent)
        self.assertEqual(self.dialog.exec(), QDialog.Rejected)
        self.assertEqual(observations, [True, True])
        self.assertIsNone(self.dialog._picker)
        self.assertEqual(self.dialog.selectedFiles(), [str(self.first.resolve())])
        self.assertFalse(self.dialog.add_folder(self.second))


if __name__ == '__main__':
    unittest.main()
