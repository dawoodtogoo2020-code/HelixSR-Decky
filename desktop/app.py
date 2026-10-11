"""Native Qt Widgets controller. No browser, Steam RPC, or game writes on selection."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QAbstractItemView, QPushButton, QScrollArea, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from .version import VERSION
from .system import system_environment

PROJECT = "https://github.com/dawoodtogoo2020-code/HelixSR-Decky"
GUIDE = PROJECT + "/blob/main/DESKTOP_GUIDE.md"
BUGS = PROJECT + "/issues"
ACTIVE = {"running", "queued", "cancelling"}
LIMIT = 24000
TERMS = (
    "HelixSR is downloaded from lonewolf0622/HelixSR and retains its freeware terms. "
    "NVIDIA DLSS and generated network files remain subject to NVIDIA's license. "
    "Generated weights and kernels are private local assets and must not be redistributed. "
    "OptiScaler is GPL 3.0; fakenvapi is MIT; AMD FidelityFX retains AMD notices. "
    "Setup scripts are Apache 2.0. Review upstream terms before continuing."
)


def open_external_url(url):
    """Use host tools without passing the bundled Qt/library environment to them."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in url):
        raise ValueError("External links must be plain HTTPS URLs")
    env = system_environment()
    if sys.platform.startswith("win"):
        root = env.get("WINDIR") or env.get("SystemRoot")
        if not root:
            raise RuntimeError("Windows browser launcher is unavailable")
        command = [os.path.join(root, "explorer.exe"), url]
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        executable = shutil.which("xdg-open", path=env.get("PATH"))
        if not executable or not os.path.isabs(executable):
            raise RuntimeError("xdg-open is unavailable. Open this link manually: " + url)
        command, flags = [executable, url], {}
    subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)


def link_label(html, notify):
    label = QLabel(html)
    label.setOpenExternalLinks(False)
    def activate(url):
        try:
            open_external_url(url)
        except Exception as exc:
            notify(str(exc), True)
    label.linkActivated.connect(activate)
    return label


class Task(QThread):
    def __init__(self, call, parent=None):
        super().__init__(parent)
        self.call, self.value, self.error = call, None, None

    def run(self):
        try:
            self.value = self.call()
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class PreviewDialog(QDialog):
    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review game changes")
        self.resize(660, 540)
        layout = QVBoxLayout(self)
        title = QLabel(f"{preview.get('action', 'Install').title()}: {preview.get('name', '')}")
        title.setWordWrap(True)
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(
            f"Route: {preview.get('route', 'unknown')}\n"
            f"Select in game: {preview.get('select_upscaler', 'see guide')}\n\n"
            f"{preview.get('warning', '')}\n\nChanged files:\n" +
            "\n".join(str(p) for p in preview.get('files', []))[:LIMIT] +
            "\n\nTerms and credits:\n" + TERMS
        )
        layout.addWidget(body)
        links = link_label('<a href="https://github.com/lonewolf0622/HelixSR">HelixSR terms and credits</a>', parent._notify)
        layout.addWidget(links)
        self.ack = QCheckBox("I have reviewed the changes and accept the applicable terms")
        layout.addWidget(self.ack)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Confirm changes")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ack.toggled.connect(self.buttons.button(QDialogButtonBox.Ok).setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)


class MainWindow(QMainWindow):
    def __init__(self, backend, auto_load=True):
        super().__init__()
        self.backend = backend
        self._task = None
        self._modal = False
        self._closing = False
        self._closed = False
        self._jobs = []
        self._games = {}
        self._library_loaded = False
        self.game = None
        self.release = {}
        self.app_update = {}
        self._seen_jobs = {}
        self._shutdown_requested = False
        self._active_dialog = None
        self.setWindowTitle(f"HelixSR Desktop {VERSION}")
        self.resize(1000, 700)
        self.setMinimumSize(680, 480)
        self._build()
        self.setStyleSheet("""
            QWidget { background: #202126; color: #e8e8ef; font-size: 14px; }
            QPushButton, QComboBox { padding: 9px; background: #35363e; border-radius: 5px; }
            QPushButton:hover { background: #554679; }
            QPushButton:disabled { color: #898995; background: #2b2c32; }
            QPushButton#primary { background: #7354ae; font-weight: bold; }
            QComboBox#games { border: 2px solid #9b79d2; font-size: 17px; }
            QGroupBox { border: 1px solid #4b4d59; border-radius: 5px; margin-top: 12px; padding: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; }
            QTextEdit, QListWidget { background: #272830; }
        """)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.poll_jobs)
        self.timer.start()
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setInterval(100)
        self.shutdown_timer.timeout.connect(self._process_shutdown)
        self.shutdown_timer.start()
        self.app_update_timer = QTimer(self)
        self.app_update_timer.setInterval(60 * 60 * 1000)
        self.app_update_timer.timeout.connect(self._automatic_app_check)
        self.app_update_timer.start()
        self._controls()
        if auto_load:
            QTimer.singleShot(0, self.refresh)

    def _button(self, label, call, layout):
        button = QPushButton(label)
        button.clicked.connect(call)
        layout.addWidget(button)
        return button

    def _build(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        self.notice = QLabel("Select a game to review its installation status.")
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.setCentralWidget(host)
        page = QWidget()
        content = QVBoxLayout(page)
        self.games = QComboBox()
        self.games.setObjectName("games")
        self.games.setMinimumHeight(48)
        self.games.currentIndexChanged.connect(self.select_game)
        content.addWidget(QLabel("Installed games and installation candidates"))
        content.addWidget(self.games)
        self.status = QLabel("No game selected")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        content.addWidget(self.status)
        self.dx12 = QCheckBox("I have set this game to DirectX 12")
        self.dx12.toggled.connect(self._controls)
        content.addWidget(self.dx12)
        row = QHBoxLayout()
        self.install = self._button("Install HelixSR", self.preview_latest, row)
        self.install.setObjectName("primary")
        self.refresh_button = self._button("Refresh games", self.refresh, row)
        content.addLayout(row)
        row = QHBoxLayout()
        self.actions = {}
        for action in ("enable", "disable", "remove", "adopt", "recover"):
            self.actions[action] = self._button(action.title(), lambda checked=False, a=action: self.preview_action(a), row)
        self.forget = self._button("Forget import", self.forget_game, row)
        content.addLayout(row)
        self.evidence = QTextEdit()
        self.evidence.setReadOnly(True)
        content.addWidget(self.evidence, 1)
        self.launch = QPushButton("Copy manual launch guidance")
        self.launch.clicked.connect(self.copy_launch)
        content.addWidget(self.launch)
        self.unavailable = QListWidget()
        self.unavailable.setMaximumHeight(110)
        content.addWidget(QLabel("Unavailable games and detected reasons"))
        content.addWidget(self.unavailable)
        self.tabs.addTab(page, "Games")
        page = QWidget()
        content = QVBoxLayout(page)
        row = QHBoxLayout()
        self.launchers = QComboBox()
        for label, key in (("All launchers", "all-launchers"), ("Heroic", "heroic"), ("Lutris", "lutris"), ("Legendary", "legendary"), ("Non-Steam", "steam-shortcuts")):
            self.launchers.addItem(label, key)
        content.addWidget(QLabel("Import Games From"))
        row.addWidget(self.launchers)
        self.import_button = self._button("Import Now", self.import_launcher, row)
        content.addLayout(row)
        self.folder_button = self._button("Import game folders", self.import_folders, content)
        hint = QLabel("Choose installed game directories. Imports detect candidates before installation; they do not launch games.")
        hint.setWordWrap(True)
        content.addWidget(hint)
        content.addStretch()
        self.tabs.addTab(page, "Import")
        page = QWidget()
        content = QVBoxLayout(page)
        group = QGroupBox("HelixSR updates (game component)")
        group_layout = QVBoxLayout(group)
        self.helix_status = QLabel("Current game: not selected · Latest: not checked")
        self.helix_status.setWordWrap(True)
        self.helix_status.setTextFormat(Qt.PlainText)
        group_layout.addWidget(self.helix_status)
        self.helix_check = self._button("Check HelixSR updates", lambda: self._run(lambda: self.backend.check_helix_updates(True), self._release_received), group_layout)
        content.addWidget(group)
        group = QGroupBox("Desktop app updates")
        group_layout = QVBoxLayout(group)
        self.app_status = QLabel(f"Current: {VERSION} · Latest: not checked")
        self.app_status.setWordWrap(True)
        self.app_status.setTextFormat(Qt.PlainText)
        group_layout.addWidget(self.app_status)
        row = QHBoxLayout()
        self.app_check = self._button("Check app updates", lambda: self.check_app(True), row)
        self.app_download = self._button("Download verified AppImage", self.download_app, row)
        group_layout.addLayout(row)
        self.auto_check = QCheckBox("Check app updates automatically")
        self.auto_check.toggled.connect(self.set_auto_check)
        group_layout.addWidget(self.auto_check)
        note = QLabel("Downloads are verified and saved. To restart, close this app and launch the downloaded AppImage yourself.")
        note.setWordWrap(True)
        group_layout.addWidget(note)
        content.addWidget(group)
        content.addStretch()
        self.tabs.addTab(page, "Updates")
        page = QWidget()
        content = QVBoxLayout(page)
        self.job_view = QTextEdit()
        self.job_view.setReadOnly(True)
        content.addWidget(self.job_view)
        self.cancel_button = self._button("Cancel active installation", self.cancel_job, content)
        self.tabs.addTab(page, "Progress")
        page = QWidget()
        content = QVBoxLayout(page)
        self.diagnostics = QTextEdit()
        self.diagnostics.setReadOnly(True)
        content.addWidget(self.diagnostics)
        content.addWidget(QLabel("Library discovery warnings"))
        self.library_warning_view = QTextEdit()
        self.library_warning_view.setReadOnly(True)
        self.library_warning_view.setMaximumHeight(180)
        self.library_warning_view.setPlainText("No library warnings")
        content.addWidget(self.library_warning_view)
        self.diagnostic_button = self._button("Refresh system diagnostics", lambda: self._run(self.backend.system_status, lambda v: self.diagnostics.setPlainText(json.dumps(v, indent=2, default=str)[:LIMIT])), content)
        links = link_label(f'<a href="{GUIDE}">Installation guide</a> · <a href="{BUGS}">Report a bug</a>', self._notify)
        content.addWidget(links)
        privacy = QLabel("Review diagnostics for private paths before sharing. Runtime status requires actual game evidence.")
        privacy.setWordWrap(True)
        content.addWidget(privacy)
        self.tabs.addTab(page, "Diagnostics")

    def _notify(self, text, error=False):
        self.notice.setText(str(text)[:2000])
        self.notice.setStyleSheet("color: #ffa7a7" if error else "color: #d9caef")
        self.statusBar().showMessage(str(text)[:500], 15000)

    def _run(self, call, done, allow_modal=False):
        if self._closing or self._task or (self._modal and not allow_modal):
            return False
        task = Task(call, self)
        self._task = task
        def finish():
            self._task = None
            if task.error:
                self._notify(task.error, True)
            elif not self._closing:
                try:
                    done(task.value)
                except Exception as exc:
                    self._notify(str(exc), True)
            task.deleteLater()
            self._controls()
            if self._closing:
                self._finish_close()
        task.finished.connect(finish)
        self._controls()
        task.start()
        return True

    def _controls(self, *_):
        active = any(j.get("state") in ACTIVE for j in self._jobs)
        free = not (self._task or self._modal or self._closing or active)
        game = self.game or {}
        for control in (self.games, self.refresh_button, self.launchers, self.import_button, self.folder_button, self.helix_check, self.app_check, self.auto_check, self.diagnostic_button):
            control.setEnabled(free)
        self.dx12.setVisible(bool(game.get("dx12_confirmation_needed")))
        self.dx12.setEnabled(free)
        confirmed = not game.get("dx12_confirmation_needed") or self.dx12.isChecked()
        candidate = game.get("compatibility") == "candidate" and not game.get("recovery_available")
        self.install.setText("Update HelixSR" if game.get("managed") else "Install HelixSR")
        self.install.setEnabled(free and candidate and confirmed and not game.get("legacy"))
        for action, button in self.actions.items():
            visible = (action == "recover" and game.get("recovery_available")) or (action == "adopt" and game.get("legacy")) or (action in ("enable", "disable", "remove") and game.get("managed"))
            button.setVisible(bool(visible))
            button.setEnabled(free and bool(visible) and (action == "recover" or candidate))
        self.forget.setEnabled(free and game.get("source") == "Imported" and not game.get("managed"))
        self.launch.setEnabled(free and bool(game))
        self.app_download.setEnabled(free and bool(self.app_update.get("update_available")) and not self.app_update.get("error"))
        self.cancel_button.setEnabled(active and not self._task and not self._modal and not self._closing)

    def refresh(self):
        self._run(self.backend.library, self._library_received)

    def _library_received(self, value):
        previous = self.games.currentData()
        self._games = {g["id"]: g for g in value.get("games", [])}
        self.games.blockSignals(True)
        self.games.clear()
        self.unavailable.clear()
        for game in self._games.values():
            if game.get("compatibility") == "candidate" or game.get("managed") or game.get("recovery_available"):
                state = "Enabled" if game.get("enabled") else "Installed" if game.get("managed") or game.get("legacy") else "Not installed"
                self.games.addItem(f"{game.get('name', game['id'])} · {state}", game["id"])
                self.games.setItemData(self.games.count() - 1, QColor("#82dfaf" if state != "Not installed" else "#a2a3af"), Qt.ForegroundRole)
            else:
                self.unavailable.addItem(f"{game.get('name', '')}: {'; '.join(game.get('reasons', [])) or game.get('compatibility', 'unknown')}")
        index = self.games.findData(previous)
        self.games.setCurrentIndex(index if index >= 0 else 0)
        self.games.blockSignals(False)
        self.release = value.get("release", {})
        self._jobs_received(value.get("jobs", []))
        self.select_game()
        warnings = [str(warning) for warning in value.get("warnings", [])]
        warning_text = "\n\n".join(warnings)
        if len(warning_text) > LIMIT:
            warning_text = warning_text[:LIMIT] + "\n\nAdditional warning text omitted to keep diagnostics bounded."
        self.library_warning_view.setPlainText(warning_text or "No library warnings")
        if warnings and not self._library_loaded:
            self._notify(f"{len(warnings)} library warnings. See Diagnostics.")
        self._library_loaded = True
        imported = value.get("launcher_import")
        if imported:
            self._notify(f"Import complete: {imported.get('found', 0)} games found, "
                         f"{imported.get('added', 0)} new, {imported.get('candidates', 0)} installation candidates. "
                         "See Diagnostics for discovery notes.")
        # Cached automatic-check policy belongs to the backend; no silent install.
        QTimer.singleShot(0, lambda: self.check_app(False))

    def select_game(self, *_):
        self.game = self._games.get(self.games.currentData())
        self.dx12.setChecked(False)
        self._render_game()
        if self.game:
            gid = self.game["id"]
            self._run(lambda: self.backend.details(gid), lambda value: self._details_received(gid, value))

    def _details_received(self, gid, value):
        if self.games.currentData() == gid:
            self.game = value
            self._render_game()
        if not self.app_update:
            QTimer.singleShot(0, lambda: self.check_app(False))

    def _render_game(self):
        game = self.game or {}
        state = "Enabled" if game.get("enabled") else "Installed, disabled" if game.get("managed") else "Existing unmanaged installation" if game.get("legacy") else "Not installed"
        self.status.setText(f"HelixSR: {state} · Version: {game.get('installed_version') or 'none'}\n{game.get('folder', '')}")
        self.status.setStyleSheet("color: #82dfaf" if game.get("enabled") or game.get("managed") or game.get("legacy") else "color: #a2a3af")
        opti = game.get("optiscaler") or {}
        text = (f"Route: {game.get('route') or 'none detected'}\n"
                f"OptiScaler installed: {'yes' if opti.get('present') else 'no detected files'}\n"
                f"OptiScaler HelixSR route configured: {'yes' if opti.get('helix_configured') else 'no'}\n"
                f"OptiScaler runtime: {opti.get('runtime', 'unknown')}\n"
                f"HelixSR runtime: {game.get('helix_runtime', 'unknown')}\n\n"
                f"Frame generation: {game.get('framegen_summary', 'unknown')}\n"
                "HelixSR has no frame generation of its own. Configuration and runtime evidence are separate.\n")
        for row in game.get("framegen", []):
            text += f"{row.get('source')}: {row.get('key')}={row.get('value')} · {row.get('meaning', '')}\n"
        text += "\nDetected reasons:\n" + "\n".join(game.get("reasons", []))
        for log in game.get("logs", []):
            text += f"\n\n{log.get('path', '')}\n{str(log.get('excerpt', ''))[:5000]}"
        self.evidence.setPlainText(text[:LIMIT])
        self._release_received(self.release, notify=False)
        self._controls()

    def preview_latest(self):
        if self.game and self.install.isEnabled():
            gid, confirmed = self.game["id"], self.dx12.isChecked()
            self._run(lambda: self.backend.preview_latest(gid, confirmed), lambda p: self._preview_received(p, True))

    def preview_action(self, action):
        if self.game and self.actions[action].isEnabled():
            gid, confirmed = self.game["id"], self.dx12.isChecked()
            self._run(lambda: self.backend.preview_action(gid, action, confirmed), lambda p: self._preview_received(p, False))

    def _preview_received(self, preview, latest):
        if self._modal or self._closing:
            return
        self._modal = True
        self._controls()
        dialog = PreviewDialog(preview, self)
        self._active_dialog = dialog
        if dialog.exec() == QDialog.Accepted:
            def apply():
                if latest:
                    self.backend.accept_license(True)
                    return self.backend.install_latest(preview["token"])
                return self.backend.apply_action(preview["token"])
            self._run(apply, lambda value: self._action_received(value), allow_modal=True)
        self._modal = False
        self._active_dialog = None
        dialog.deleteLater()
        self._controls()

    def _action_received(self, value):
        self._notify(value.get("message", "Operation started"))
        if value.get("id"):
            self._jobs_received(self._jobs + [value])
            self.tabs.setCurrentIndex(3)
        else:
            QTimer.singleShot(0, self.refresh)

    def poll_jobs(self):
        if not self._modal and not self._closing and not self._task and any(j.get("state") in ACTIVE for j in self._jobs):
            self._run(self.backend.jobs, self._jobs_received)

    def _jobs_received(self, jobs):
        was_active = any(j.get("state") in ACTIVE for j in self._jobs)
        self._jobs = jobs or []
        pieces = []
        for job in self._jobs:
            pieces.append(f"{job.get('game', '')}: {job.get('state', '')}\n{job.get('message', '')}\n{str(job.get('log', ''))[-8000:]}")
            if job.get("state") not in ACTIVE and self._seen_jobs.get(job.get("id")) != job.get("state"):
                self._notify(f"{job.get('game', 'Operation')}: {job.get('state')} · {job.get('message', '')}", job.get("state") == "failed")
            self._seen_jobs[job.get("id")] = job.get("state")
        self.job_view.setPlainText("\n\n".join(reversed(pieces))[:LIMIT] or "No active jobs")
        self._controls()
        if was_active and not any(j.get("state") in ACTIVE for j in self._jobs):
            QTimer.singleShot(0, self.refresh)

    def cancel_job(self):
        job = next((j for j in self._jobs if j.get("state") in ACTIVE), None)
        if job:
            self._run(lambda: self.backend.cancel_job(job["id"]), lambda _: self._notify("Cancellation requested. Waiting for the installation to stop safely."))

    def import_launcher(self):
        source = self.launchers.currentData()
        self._run(lambda: self.backend.import_launcher(source), self._library_received)

    def import_folders(self):
        if self._task or self._modal:
            return
        self._modal = True
        self._controls()
        dialog = QFileDialog(self, "Select installed game folders")
        self._active_dialog = dialog
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        for view in dialog.findChildren(QAbstractItemView):
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        accepted = dialog.exec() == QDialog.Accepted
        folders = dialog.selectedFiles() if accepted else []
        self._modal = False
        self._active_dialog = None
        dialog.deleteLater()
        self._controls()
        if folders:
            self._run(lambda: self.backend.import_folders(folders), self._library_received)

    def forget_game(self):
        if self.game and self.forget.isEnabled():
            gid = self.game["id"]
            self._run(lambda: self.backend.forget_game(gid), self._library_received)

    def _release_received(self, value, notify=True):
        self.release = value or {}
        self.helix_status.setText(f"Current game: {(self.game or {}).get('installed_version') or 'not installed'} · Latest: {self.release.get('version') or 'unknown'}\n{self.release.get('error') or ''}")
        if notify and self.release.get("error"):
            self._notify(self.release["error"], True)

    def check_app(self, force=True):
        self._run(lambda: self.backend.check_app_updates(force), lambda value: self._app_received(value, notify=force))

    def _automatic_app_check(self):
        if self.auto_check.isChecked() and not any(j.get("state") in ACTIVE for j in self._jobs):
            # Backend owns the daily cache policy. Timers never force a download.
            self.check_app(False)

    def _app_received(self, value, notify=True):
        self.app_update = value or {}
        self.app_status.setText(f"Current: {self.app_update.get('current', VERSION)} · Latest: {self.app_update.get('latest') or 'unknown'}\n{self.app_update.get('error', '')}")
        self.auto_check.blockSignals(True)
        self.auto_check.setChecked(bool(self.app_update.get("auto_check")))
        self.auto_check.blockSignals(False)
        if notify and self.app_update.get("error"):
            self._notify(self.app_update["error"], True)
        self._controls()

    def set_auto_check(self, enabled):
        self._run(lambda: self.backend.set_app_auto_check(enabled), lambda v: self._app_received(v) if isinstance(v, dict) else None)

    def download_app(self):
        self._run(self.backend.download_app_update, lambda value: self._notify(f"Verified app {value.get('version')}: {value.get('path')} · Close this app before manually launching it."))

    def copy_launch(self):
        game = self.game or {}
        before = game.get("launch_options", "")
        if game.get("route") == "direct":
            guidance = ("Select AMD FSR in the game's upscaling settings. This native replacement does not require an additional proxy launch override. "
                        "Preserve your existing Steam or launcher launch options.\nExisting options:\n" + before)
        elif game.get("route") == "optiscaler":
            guidance = ("Preserve your existing Steam or launcher launch options. For the OptiScaler proxy, merge dxgi=n,b into WINEDLLOVERRIDES manually. "
                        "For empty Steam options use: WINEDLLOVERRIDES=\"dxgi=n,b\" %command%\n"
                        "Do not overwrite an existing dxgi rule without reviewing it.\nExisting options:\n" + before)
        else:
            guidance = ("No supported installation route has been detected. Review the game details and installation guide before changing launch options.\n"
                        "Existing options:\n" + before)
        QApplication.clipboard().setText(guidance)
        self._notify("Manual launch guidance copied. Review and merge with existing options in the launcher.")

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        if self._modal:
            self._notify("Close the review dialog before exiting.")
            return
        self._closing = True
        self.timer.stop()
        self._notify("Stopping active work safely before closing…")
        self._controls()
        if not self._task:
            self._finish_close()

    def receive_shutdown_signal(self, signum=None, frame=None):
        # Python signal handlers only set a flag; Qt operations happen on its timer.
        self._shutdown_requested = True

    def _process_shutdown(self):
        if not self._shutdown_requested or self._closed:
            return
        if self._modal:
            if self._active_dialog:
                self._active_dialog.reject()
            return
        self._shutdown_requested = False
        self.close()

    def _finish_close(self):
        if self._task or self._closed:
            return
        task = Task(self.backend.close, self)
        self._task = task
        def finish():
            if task.error:
                self._closing = False
                self._task = None
                self._notify(task.error, True)
                self.timer.start()
                self._controls()
            elif task.value is False:
                self._task = None
                self._notify("Installation is still stopping. Keeping the app open until its worker exits.")
                QTimer.singleShot(1500, self._finish_close)
            else:
                self._closed = True
                self._task = None
                self.close()
            task.deleteLater()
        task.finished.connect(finish)
        task.start()


class SmokeBackend:
    """Read-only fixtures. Smoke tests never instantiate the real game manager."""
    def library(self):
        return {"games": [{"id": "fixture", "name": "Example DX12 game", "folder": "/fixture/game", "source": "Steam", "compatibility": "candidate", "managed": False, "enabled": False, "optiscaler": {"present": False, "runtime": "unknown"}, "framegen_summary": "No runtime evidence"}], "release": {"version": "fixture"}, "jobs": []}
    def details(self, gid):
        return self.library()["games"][0]
    def check_app_updates(self, force=True):
        return {"current": VERSION, "latest": VERSION, "auto_check": False, "update_available": False}
    def jobs(self):
        return []
    def close(self):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="HelixSR native desktop app")
    parser.add_argument("--home")
    parser.add_argument("--settings")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot")
    args = parser.parse_args(argv)
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.screenshot and not Path(args.screenshot).is_absolute():
        parser.error("--screenshot must be an absolute path")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    # The offscreen platform may have no font database even on a desktop host.
    if not QFontDatabase.families():
        windows_root = os.environ.get("WINDIR", "")
        fonts = ([Path(windows_root) / "Fonts/segoeui.ttf"] if windows_root else []) + [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
        ]
        for font_path in fonts:
            if font_path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    app.setFont(QFont(families[0], 10))
                    break
    if args.smoke_test:
        backend = SmokeBackend()
    else:
        from .backend import DesktopBackend
        backend = DesktopBackend(home=args.home, settings=args.settings)
    window = MainWindow(backend)
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous_handlers:
        signal.signal(sig, window.receive_shutdown_signal)
    window.show()
    if args.smoke_test:
        def complete():
            if window._task:
                QTimer.singleShot(50, complete)
                return
            if args.screenshot:
                path = Path(args.screenshot)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(path)):
                    raise RuntimeError("Unable to save screenshot")
            window.close()
        QTimer.singleShot(500, complete)
    try:
        return app.exec()
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
