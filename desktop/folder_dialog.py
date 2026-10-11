"""Explicit multi-folder selection without relying on QFileDialog's Directory mode quirks."""
from pathlib import Path
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)


class FolderDialog(QDialog):
    """Collect directories only; callers import selectedFiles after Accepted."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import game folders")
        self.resize(780, 490)
        self.setMinimumSize(580, 360)
        self._picker = None
        self._rejecting = False
        layout = QVBoxLayout(self)
        hint = QLabel("Add each installed game folder, then import the folders listed below. No game files are changed by this dialog.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add folder…")
        self.add_button.clicked.connect(self._choose_folder)
        row.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        self.folders = QListWidget()
        self.folders.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.folders.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.folders.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.folders, 1)
        self.notice = QLabel("No folders added")
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        layout.addWidget(self.notice)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.import_button = self.buttons.button(QDialogButtonBox.Ok)
        self.import_button.setText("Import listed folders")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._update_buttons()

    def selectedFiles(self):
        return [self.folders.item(i).data(Qt.UserRole) for i in range(self.folders.count())]

    def _update_buttons(self):
        self.remove_button.setEnabled(bool(self.folders.selectedItems()) and self._picker is None)
        self.import_button.setEnabled(self.folders.count() > 0 and self._picker is None)
        self.add_button.setEnabled(self._picker is None)

    def add_folder(self, path):
        """Validate and append a directory, preserving canonical full paths."""
        if self._rejecting:
            return False
        try:
            folder = Path(path).expanduser().resolve(strict=True)
            if not folder.is_dir():
                raise ValueError("Select a directory rather than a file")
        except (OSError, RuntimeError, ValueError) as exc:
            self.notice.setText("Could not add this folder: " + str(exc)[:400])
            return False
        full = str(folder)
        key = os.path.normcase(full)
        if any(os.path.normcase(existing) == key for existing in self.selectedFiles()):
            self.notice.setText("This folder is already listed")
            return False
        item = QListWidgetItem(full)
        item.setData(Qt.UserRole, full)
        item.setToolTip(full)
        self.folders.addItem(item)
        self.notice.setText(f"{self.folders.count()} folder(s) ready to import")
        self._update_buttons()
        return True

    def remove_selected(self):
        if self._picker is not None:
            return
        for item in self.folders.selectedItems():
            self.folders.takeItem(self.folders.row(item))
        self.notice.setText(f"{self.folders.count()} folder(s) ready to import" if self.folders.count() else "No folders added")
        self._update_buttons()

    def _choose_folder(self):
        if self._picker is not None or self._rejecting:
            return
        picker = QFileDialog(self, "Add an installed game folder")
        # Standard single-directory selection works consistently across Qt hosts.
        picker.setOption(QFileDialog.DontUseNativeDialog, True)
        picker.setFileMode(QFileDialog.Directory)
        picker.setOption(QFileDialog.ShowDirsOnly, True)
        picker.resize(760, 480)
        existing = self.selectedFiles()
        if existing:
            picker.setDirectory(str(Path(existing[-1]).parent))
        self._picker = picker
        self._update_buttons()
        try:
            accepted = picker.exec() == QDialog.Accepted
            paths = picker.selectedFiles() if accepted else []
        finally:
            self._picker = None
            picker.deleteLater()
        if paths and not self._rejecting:
            self.add_folder(paths[0])
        self._update_buttons()

    def accept(self):
        if not self._rejecting and self._picker is None and self.folders.count():
            super().accept()

    def reject(self):
        self._rejecting = True
        if self._picker is not None:
            self._picker.reject()
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept()
