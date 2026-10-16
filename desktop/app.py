"""Native Qt Widgets controller. No browser, Steam RPC, or game writes on selection."""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThread, QTimer, Qt, Slot
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QGroupBox, QHBoxLayout, QLabel, QLayout, QListWidget, QMainWindow,
    QPushButton, QScrollArea, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from .version import VERSION
from .system import system_environment
from .folder_dialog import FolderDialog
from py_modules.game_guidance import setup_guidance

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
    "Setup scripts through 1.8.1 retain Apache 2.0 terms. Newer releases have different terms and require a supported adapter. Review the selected release license."
)


def game_status(game):
    report = game.get('installation_status') or {}
    if report:
        state = report.get('label') or report.get('state') or 'Status unavailable'
        recorded = f"Recorded as {'enabled' if game.get('enabled') else 'disabled'}" if (not report.get('can_modify', True) and game.get('managed') and report.get('state') not in ('enabled', 'disabled')) else ''
        color = '#f1ca7e' if report.get('issues') else '#82dfaf' if game.get('managed') or game.get('legacy') else '#a2a3af'
        return state, recorded, color
    review = bool(game) and (game.get('compatibility') != 'candidate' or bool(game.get('recovery_available')))
    state = ('Choose executable' if game.get('executable_selection_needed') else
             'Recovery needed' if game.get('recovery_available') else
             'Needs review' if review else 'Enabled' if game.get('enabled') else
             'Installed, disabled' if game.get('managed') else
             'Existing unmanaged installation' if game.get('legacy') else 'Not installed')
    recorded = f"Recorded as {'enabled' if game.get('enabled') else 'disabled'}" if review and game.get('managed') else ''
    color = '#f1ca7e' if review else '#82dfaf' if game.get('managed') or game.get('legacy') else '#a2a3af'
    return state, recorded, color


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
            f"Selected model: {preview.get('model', 'existing installation')}\n"
            f"HelixSR release: {preview.get('release_version', 'existing installation')}\n"
            f"Game executable: {preview.get('selected_executable') or 'recorded installation folder'}\n"
            f"Select in game: {preview.get('select_upscaler', 'see guide')}\n\n"
            f"{preview.get('warning', '')}\n\nChanged files:\n" +
            "\n".join(str(p) for p in preview.get('files', []))[:LIMIT] +
            "\n\nTerms and credits:\n" + TERMS
        )
        layout.addWidget(body)
        license_url = preview.get('license_url') or 'https://github.com/lonewolf0622/HelixSR'
        links = link_label('<a href="' + html.escape(license_url, quote=True) + '">Selected HelixSR release license</a>', parent._notify)
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
        self._task_done = None
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
        self._overlay_snapshot = {}
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
        self.overlay_timer = QTimer(self)
        self.overlay_timer.setInterval(1200)
        self.overlay_timer.timeout.connect(self.poll_overlay)
        self.overlay_timer.start()
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
        content.setSizeConstraint(QLayout.SetMinimumSize)
        self.library_summary = QLabel("Detecting installed games…")
        self.library_summary.setWordWrap(True)
        self.library_summary.setTextFormat(Qt.PlainText)
        content.addWidget(self.library_summary)
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
        self.next_step = QLabel()
        self.next_step.setWordWrap(True)
        self.next_step.setTextFormat(Qt.PlainText)
        content.addWidget(self.next_step)
        self.game_guide = link_label('', self._notify)
        self.game_guide.setWordWrap(True)
        content.addWidget(self.game_guide)
        self.executable_label = QLabel("Game executable")
        content.addWidget(self.executable_label)
        self.executables = QComboBox()
        self.executables.setObjectName("executables")
        self.executables.setMinimumHeight(40)
        self.executables.currentIndexChanged.connect(self.select_executable)
        content.addWidget(self.executables)
        self.executable_note = QLabel("Choose the DX12 executable you actually launch. HelixSR will be installed beside it. Remove an existing installation before choosing another executable.")
        self.executable_note.setWordWrap(True)
        content.addWidget(self.executable_note)
        content.addWidget(QLabel("Release to install"))
        self.release_choice = QComboBox()
        self.release_choice.setObjectName("release_choice")
        self.release_choice.addItem("Latest upstream", "latest")
        self.release_choice.addItem("Compatible HelixSR 1.8.1", "compatible-1.8.1")
        self.release_choice.setMinimumHeight(40)
        content.addWidget(self.release_choice)
        release_note = QLabel("HelixSR 1.9 uses a newer installer and Scaler engine that this app does not yet support. "
                             "Choose Compatible HelixSR 1.8.1 to install the reviewed version. Latest-version checks remain separate.")
        release_note.setWordWrap(True)
        content.addWidget(release_note)
        content.addWidget(QLabel("HelixSR model"))
        self.models = QComboBox()
        self.models.setObjectName("models")
        self.models.setMinimumHeight(40)
        content.addWidget(self.models)
        self.model_note = QLabel()
        self.model_note.setWordWrap(True)
        self.model_note.setTextFormat(Qt.PlainText)
        content.addWidget(self.model_note)
        self.dx12 = QCheckBox("I have set this game to DirectX 12")
        self.dx12.toggled.connect(self._controls)
        content.addWidget(self.dx12)
        row = QHBoxLayout()
        self.install = self._button("Install HelixSR", self.preview_latest, row)
        self.install.setObjectName("primary")
        self.refresh_button = self._button("Refresh games", self.refresh, row)
        content.addLayout(row)
        self.launch_setup = QPushButton('Copy Proton launch setup')
        self.launch_setup.clicked.connect(self.copy_launch)
        content.addWidget(self.launch_setup)
        row = QHBoxLayout()
        self.actions = {}
        for action in ("enable", "disable", "remove", "adopt", "recover"):
            self.actions[action] = self._button(action.title(), lambda checked=False, a=action: self.preview_action(a), row)
        self.forget = self._button("Forget import", self.forget_game, row)
        content.addLayout(row)
        self.blockers = QLabel()
        self.blockers.setWordWrap(True)
        self.blockers.setTextFormat(Qt.PlainText)
        content.addWidget(self.blockers)
        self.overlay_toggle = QCheckBox('Show experimental in-game status overlay')
        self.overlay_toggle.toggled.connect(self.set_overlay)
        content.addWidget(self.overlay_toggle)
        self.overlay_health = QLabel('Overlay: off · Visibility unverified')
        self.overlay_health.setWordWrap(True)
        self.overlay_health.setTextFormat(Qt.PlainText)
        content.addWidget(self.overlay_health)
        self.runtime_status = QLabel('Runtime: no current observation')
        self.runtime_status.setWordWrap(True)
        self.runtime_status.setTextFormat(Qt.PlainText)
        content.addWidget(self.runtime_status)
        self.evidence = QTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMinimumHeight(100)
        self.evidence.setMaximumHeight(180)
        content.addWidget(self.evidence, 1)
        self.launch = QPushButton("Copy manual launch guidance")
        self.launch.clicked.connect(self.copy_launch)
        content.addWidget(self.launch)
        self.unavailable = QListWidget()
        self.unavailable.setMaximumHeight(110)
        content.addWidget(QLabel("Unavailable games and detected reasons"))
        content.addWidget(self.unavailable)
        self.games_scroll = QScrollArea()
        self.games_scroll.setWidgetResizable(True)
        self.games_scroll.setWidget(page)
        self.tabs.addTab(self.games_scroll, "Games")
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
        self.helix_check = self._button("Check latest HelixSR version", lambda: self._run(lambda: self.backend.check_helix_updates(True), self._release_received), group_layout)
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
        self._task_done = done
        task.finished.connect(self._task_finished, Qt.QueuedConnection)
        self._controls()
        task.start()
        return True

    def _take_task_result(self):
        """Join before releasing the worker's callable, result and native object."""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Task completion must run on the GUI thread")
        task = self._task
        if task is None or self.sender() is not task:
            return None
        task.wait()
        result = (task.value, task.error, self._task_done)
        self._task = None
        self._task_done = None
        task.call = task.value = task.error = None
        task.deleteLater()
        return result

    @Slot()
    def _task_finished(self):
        # A QObject receiver provides an explicit GUI-thread context. Do not
        # connect finished to a closure retaining the worker and its payload.
        result = self._take_task_result()
        if result is None:
            return
        value, error, done = result
        if error:
            self._notify(error, True)
            if done == self._library_received:
                previous = f"Showing the previous scan ({len(self._games)} games). " if self._library_loaded else ""
                self.library_summary.setText("Library scan failed. " + previous + "Fix the error above, then refresh the library.")
        elif not self._closing:
            try:
                done(value)
            except Exception as exc:
                self._notify(str(exc), True)
        self._controls()
        if self._closing:
            self._finish_close()

    def _controls(self, *_):
        active = any(j.get("state") in ACTIVE for j in self._jobs)
        free = not (self._task or self._modal or self._closing or active)
        game = self.game or {}
        for control in (self.games, self.executables, self.models, self.release_choice, self.refresh_button, self.launchers, self.import_button, self.folder_button, self.helix_check, self.app_check, self.auto_check, self.diagnostic_button):
            control.setEnabled(free)
        choices = game.get("executable_choices", [])
        show_executable = not game.get("managed") and game.get("route") == "optiscaler" and bool(choices) and (len(choices) > 1 or not any(e['path'] == game.get('selected_executable') for e in choices))
        for control in (self.executable_label, self.executables, self.executable_note):
            control.setVisible(show_executable)
        self.dx12.setVisible(bool(game.get("dx12_confirmation_needed")))
        self.dx12.setEnabled(free)
        confirmed = not game.get("dx12_confirmation_needed") or self.dx12.isChecked()
        candidate = game.get("compatibility") == "candidate" and not game.get("recovery_available")
        report = game.get('installation_status') or {}
        if report:
            candidate = bool(report.get('can_modify')) and not game.get('recovery_available')
        candidate = candidate and not game.get('awareness_deferred')
        self.install.setText("Update this game's HelixSR" if game.get("managed") else "Install HelixSR for this game")
        self.install.setEnabled(free and candidate and confirmed and not game.get("legacy"))
        guidance = game.get('setup_guidance') or setup_guidance(game)
        message = 'Next step: ' + guidance['headline'] + '\n' + '\n\n'.join(guidance['steps'] + guidance['notes'])
        if game.get('dx12_confirmation_needed') and not confirmed:
            message += '\nConfirm DirectX 12 below before installing.'
        if active:
            current = next(j for j in self._jobs if j.get('state') in ACTIVE)
            message = f"{current.get('game', 'Game')}: {current.get('message') or 'Installing / preparing HelixSR…'}\nOpen Progress for details. Wait until it finishes before changing game files."
        self.next_step.setText(message if game or active else 'Select a game to see the installation steps.')
        self.game_guide.setText(' · '.join(f'<a href="{html.escape(link["url"], quote=True)}">{html.escape(link["label"])}</a>' for link in guidance['links']))
        self.game_guide.setVisible(bool(guidance['links']))
        self.launch_setup.setVisible(bool(game.get('managed') and game.get('enabled') and game.get('route') == 'optiscaler'))
        self.launch_setup.setEnabled(free and not game.get('awareness_deferred'))
        for action, button in self.actions.items():
            visible = (action == "recover" and game.get("recovery_available")) or (action == "adopt" and game.get("legacy")) or (game.get("managed") and (action == "remove" or action == ("disable" if game.get("enabled") else "enable")))
            button.setVisible(bool(visible))
            recovery_safe = not report.get('running') and not any(i.get('code') == 'steam_update' for i in report.get('issues', []))
            allowed = report.get('can_restore', candidate) if action in ('disable', 'remove') else candidate
            button.setEnabled(free and bool(visible) and (recovery_safe if action == "recover" else allowed))
        self.forget.setEnabled(free and game.get("source") == "Imported" and not game.get("managed"))
        self.launch.setEnabled(free and bool(game) and not game.get('awareness_deferred'))
        self.app_download.setEnabled(free and bool(self.app_update.get("update_available")) and not self.app_update.get("error"))
        self.cancel_button.setEnabled(active and not self._task and not self._modal and not self._closing)
        self.overlay_toggle.setEnabled(bool(game) and not self._task and not self._modal and not self._closing)
        reason = ('Confirm DirectX 12 before installing.' if not confirmed else self.blockers.text()) or 'Review this game before changing files.'
        for button in (self.install, *self.actions.values()):
            button.setToolTip('' if button.isEnabled() else reason)

    def refresh(self):
        if self._run(self.backend.library, self._library_received):
            self.library_summary.setText("Refreshing library…")

    def _library_received(self, value):
        previous = self.games.currentData()
        self._games = {g["id"]: g for g in value.get("games", [])}
        self.games.blockSignals(True)
        self.games.clear()
        self.unavailable.clear()
        for game in self._games.values():
            report = game.get('installation_status') or {}
            if report.get('selectable', game.get("compatibility") == "candidate" or game.get("managed") or game.get("recovery_available") or game.get("executable_selection_needed")):
                state, _, color = game_status(game)
                self.games.addItem(f"{game.get('name', game['id'])} · {state}", game["id"])
                self.games.setItemData(self.games.count() - 1, QColor(color), Qt.ForegroundRole)
            else:
                self.unavailable.addItem(f"{game.get('name', '')}: {'; '.join(game.get('reasons', [])) or game.get('compatibility', 'unknown')}")
                self.unavailable.item(self.unavailable.count() - 1).setToolTip('\n\n'.join(
                    i.get('reason', '') + '\nNext: ' + ' '.join(i.get('steps', [])) for i in report.get('issues', [])))
        count = len(self._games)
        candidates = sum(g.get('compatibility') == 'candidate' for g in self._games.values())
        summary = f"{count} games found · {candidates} installation candidates · {self.unavailable.count()} unavailable"
        if not count:
            summary += "\nNo installed game folders were found. Check Diagnostics for discovery notes. Open Steam, check that your library drive is mounted, then refresh. Use the Import tab for other launchers or individual game folders."
        elif not self.games.count():
            summary += "\nYour games were found, but none can be selected for installation yet. See Unavailable games below for the reasons."
        if value.get('warnings'):
            summary += "\nDiscovery notes are available in Diagnostics."
        self.library_summary.setText(summary)
        index = self.games.findData(previous)
        self.games.setCurrentIndex(index if index >= 0 else 0)
        self.games.blockSignals(False)
        self.release = value.get("release", {})
        models = value.get("model_catalog") or {}
        self.models.clear()
        for model in models.get("variants", []):
            self.models.addItem(f"{model['label']} · {model['source']}", model['id'])
        self.model_note.setText(models.get("note", ""))
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
        prior = (self._overlay_snapshot or {}).get('game_id')
        self.game = self._games.get(self.games.currentData())
        self.dx12.setChecked(False)
        self._render_game()
        if prior and prior != self.games.currentData() and (self._overlay_snapshot or {}).get('enabled'):
            gid = self.games.currentData()
            self._run(lambda: self.backend.set_status_overlay(None, False),
                      lambda value: self._overlay_switched(value, gid))
            return
        if self.game:
            gid = self.game["id"]
            self._run(lambda: self.backend.details(gid), lambda value: self._details_received(gid, value))

    def select_executable(self, *_):
        if not self.game or self.game.get("managed") or self.game.get("route") != "optiscaler":
            return
        gid, executable = self.game["id"], self.executables.currentData()
        if not executable or executable == self.game.get("selected_executable"):
            return
        self.dx12.setChecked(False)
        def change():
            if (self._overlay_snapshot or {}).get('enabled'):
                self.backend.set_status_overlay(None, False)
            return self.backend.details(gid, executable)
        self._run(change, lambda value: self._details_received(gid, value, reset_model=False))

    def _details_received(self, gid, value, reset_model=True):
        if self.games.currentData() == gid:
            self.game = value
            self._games[gid] = value
            state, _, color = game_status(value)
            self.games.setItemText(self.games.currentIndex(), f"{value.get('name', gid)} · {state}")
            self.games.setItemData(self.games.currentIndex(), QColor(color), Qt.ForegroundRole)
            self._render_game(reset_model=reset_model)
        if not self.app_update:
            QTimer.singleShot(0, lambda: self.check_app(False))

    def _render_game(self, reset_model=True):
        game = self.game or {}
        self.executables.blockSignals(True)
        self.executables.clear()
        for executable in game.get("executable_choices", []):
            renderer = "DX12 detected" if executable.get("dx12") else "Confirm DX12"
            self.executables.addItem(f"{executable['path']} · {renderer}", executable['path'])
        self.executables.setCurrentIndex(self.executables.findData(game.get("selected_executable")))
        self.executables.blockSignals(False)
        state, recorded, color = game_status(game)
        self.status.setText(f"HelixSR: {state} · Version: {game.get('installed_version') or 'none'}\n"
                            + (recorded + '\n' if recorded else '') +
                            f"Installed model: {game.get('installed_model') or 'not installed'}\n{game.get('folder', '')}")
        if reset_model:
            self.models.setCurrentIndex(max(0, self.models.findData(game.get('installed_variant'))))
        self.status.setStyleSheet(f"color: {color}")
        report = game.get('installation_status') or {}
        issues = report.get('issues') or []
        instructions = []
        for issue in issues:
            title = issue.get('title') or issue.get('code') or 'Review needed'
            reason = issue.get('reason') or ''
            steps = issue.get('steps') or []
            if isinstance(steps, str):
                steps = [steps]
            instructions.append(f"{title}: {reason}" + ("\nNext: " + '; '.join(map(str, steps)) if steps else ''))
        self.blockers.setText('\n\n'.join(instructions) if instructions else (report.get('summary') or ''))
        self.blockers.setVisible(bool(instructions or report.get('summary')))
        self.poll_overlay()
        opti = game.get("optiscaler") or {}
        route_label = 'Recorded route' if game.get('managed') else 'Detected route'
        text = (f"{route_label}: {game.get('route') or 'none detected'}\n"
                f"Target executable: {game.get('main_exe') or 'unknown'}\n"
                f"OptiScaler installed: {'not inspected' if opti.get('present') is None else 'yes' if opti.get('present') else 'no detected files'}\n"
                f"OptiScaler HelixSR route configured: {'not inspected' if opti.get('helix_configured') is None else 'yes' if opti.get('helix_configured') else 'no'}\n"
                f"OptiScaler runtime: {opti.get('runtime', 'unknown')}\n"
                f"HelixSR runtime: {game.get('helix_runtime', 'unknown')}\n\n"
                f"Frame generation: {game.get('framegen_summary', 'unknown')}\n"
                "HelixSR has no frame generation of its own. Configuration and runtime evidence are separate.\n")
        setup = opti.get('setup') or {}
        text += '\nSetup checks and next steps:\n' + '\n\n'.join(setup.get('checks', []))
        text += '\n\nDetected OptiScaler settings:\n' + '\n'.join(f'{k}={v}' for k, v in setup.get('settings', {}).items())
        for row in game.get("framegen", []):
            text += f"{row.get('source')}: {row.get('key')}={row.get('value')} · {row.get('meaning', '')}\n"
        text += "\nDetected reasons:\n" + "\n".join(game.get("reasons", []))
        text += "\nEvidence warnings:\n" + "\n".join(game.get("awareness_warnings", []))
        for log in game.get("logs", []):
            text += f"\n\n{log.get('path', '')}\n{str(log.get('excerpt', ''))[:5000]}"
        self.evidence.setPlainText(text[:LIMIT])
        self._release_received(self.release, notify=False)
        self._controls()

    def preview_latest(self):
        if self.game and self.install.isEnabled():
            gid, confirmed, model = self.game["id"], self.dx12.isChecked(), self.models.currentData()
            executable = self.game.get("selected_executable") if not self.game.get("managed") and self.game.get("route") == "optiscaler" else None
            choice = self.release_choice.currentData()
            call = (lambda: self.backend.preview_latest(gid, confirmed, model, executable)) if choice == "latest" else (
                lambda: self.backend.preview_latest(gid, confirmed, model, executable, choice))
            self._run(call, lambda p: self._preview_received(p, True))

    def preview_action(self, action):
        if self.game and self.actions[action].isEnabled():
            gid, confirmed = self.game["id"], self.dx12.isChecked()
            executable = self.game.get("selected_executable") if not self.game.get("managed") and self.game.get("route") == "optiscaler" else None
            self._run(lambda: self.backend.preview_action(gid, action, confirmed, executable), lambda p: self._preview_received(p, False))

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
                    self.backend.accept_license(True, preview["token"])
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

    def _overlay_switched(self, value, gid):
        self._overlay_received(value)
        if gid and self.games.currentData() == gid:
            self._run(lambda: self.backend.details(gid), lambda detail: self._details_received(gid, detail))

    def set_overlay(self, enabled):
        if self._closing or not self.game:
            return
        gid = self.game['id'] if enabled else None
        executable = self.game.get('selected_executable') if enabled and not self.game.get('managed') and self.game.get('route') == 'optiscaler' else None
        if not self._run(lambda: self.backend.set_status_overlay(gid, enabled, executable), self._overlay_received):
            self.poll_overlay()

    def _overlay_received(self, value):
        if isinstance(value, dict):
            self._overlay_snapshot = value
        self._show_overlay()

    def poll_overlay(self):
        if self._closing or self._task or not hasattr(self.backend, 'overlay_status'):
            return
        try:
            self._overlay_snapshot = self.backend.overlay_status()
        except Exception as exc:
            self._overlay_snapshot = dict(enabled=False, overlay=dict(state='error', label='Unavailable', detail=str(exc)),
                                          runtime=dict(label='Monitoring unavailable', detail=''))
        self._show_overlay()

    def _show_overlay(self):
        snapshot = self._overlay_snapshot or {}
        overlay = snapshot.get('overlay') or {}
        runtime = snapshot.get('runtime') or {}
        selected = (self.game or {}).get('id')
        checked = bool(snapshot.get('enabled') and snapshot.get('game_id') == selected)
        self.overlay_toggle.blockSignals(True)
        self.overlay_toggle.setChecked(checked)
        self.overlay_toggle.blockSignals(False)
        overlay_label = overlay.get('label') or overlay.get('state') or 'Off'
        overlay_detail = overlay.get('detail') or ''
        if snapshot.get('enabled') and snapshot.get('game_id') != selected:
            overlay_detail = f"Monitoring another game ({snapshot.get('game_id')}). " + overlay_detail
        health = ('Helper responding' if overlay.get('responding') else
                  'Helper response unavailable' if snapshot.get('enabled') else 'Off')
        self.overlay_health.setText(f"Overlay: {overlay_label} · {health} · Visibility unverified"
                                    + (f"\n{overlay_detail}" if overlay_detail else ''))
        runtime_label = runtime.get('label') or runtime.get('state') or 'No current observation'
        runtime_detail = runtime.get('detail') or ''
        self.runtime_status.setText(f"Runtime: {runtime_label}" + (f"\n{runtime_detail}" if runtime_detail else ''))

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
        dialog = FolderDialog(self)
        self._active_dialog = dialog
        accepted = dialog.exec() == QDialog.Accepted
        folders = dialog.selectedFiles() if accepted else []
        self._modal = False
        self._active_dialog = None
        dialog.deleteLater()
        self._controls()
        if folders:
            self._run(lambda: self.backend.import_folders(folders),
                      lambda value: self._folders_received(value, len(folders)))

    def _folders_received(self, value, count):
        self._library_received(value)
        warnings = len(value.get("warnings", []))
        message = f"Imported {count} game folder{'s' if count != 1 else ''}."
        if warnings:
            message += f" {warnings} library warnings. See Diagnostics."
        self._notify(message)

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
        if game.get('awareness_deferred'):
            self._notify('Refresh and inspect this game before copying its launch guidance.', True)
            return
        before = game.get("launch_options", "")
        if game.get("route") == "direct":
            guidance = ("Select AMD FSR in the game's upscaling settings. This native replacement does not require an additional proxy launch override. "
                        "Preserve your existing Steam or launcher launch options.\nExisting options:\n" + before)
        elif game.get("route") == "optiscaler":
            guidance = ("Preserve your existing Steam or launcher launch options. For the OptiScaler proxy, merge dxgi=n,b into WINEDLLOVERRIDES manually. "
                        "For empty Steam options use: WINEDLLOVERRIDES=\"dxgi=n,b\" %command%\n"
                        "Do not overwrite an existing dxgi rule without reviewing it.\nExisting options:\n" + before)
            setup = game.get('optiscaler', {}).get('setup') or {}
            guidance += '\n\nSetup checks:\n' + '\n\n'.join(setup.get('checks', []))
            guidance += '\n\nFull OptiScaler guide: ' + setup.get('guide', PROJECT + '/blob/main/OPTISCALER_GUIDE.md')
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
        self.overlay_timer.stop()
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
        task.finished.connect(self._close_finished, Qt.QueuedConnection)
        task.start()

    @Slot()
    def _close_finished(self):
        result = self._take_task_result()
        if result is None:
            return
        value, error, _ = result
        if error:
            self._closing = False
            self._notify(error, True)
            self.timer.start()
            self.overlay_timer.start()
            self._controls()
        elif value is False:
            self._notify("Installation is still stopping. Keeping the app open until its worker exits.")
            QTimer.singleShot(1500, self._finish_close)
        else:
            self._closed = True
            self.close()


def smoke_model_catalog():
    """Read-only display fixture; this does not prepare or install any model."""
    return dict(default="helixsr-model-e", variants=[dict(id="helixsr-model-e",
        label="HelixSR Model E", source="NVIDIA DLSS 310.7.0")],
        note="Only reviewed models are selectable. Future variants require upstream and app support.")


class SmokeBackend:
    """Read-only fixtures. Smoke tests never instantiate the real game manager."""
    def library(self):
        return {"games": [{"id": "fixture", "name": "Example DX12 game", "folder": "/fixture/game", "source": "Steam", "compatibility": "candidate", "managed": False, "enabled": False, "route": "optiscaler", "selected_executable": "DX12/Game.exe", "executable_choices": [{"path": "DX11/Game.exe", "dx12": False}, {"path": "DX12/Game.exe", "dx12": True}], "optiscaler": {"present": False, "runtime": "unknown"}, "framegen_summary": "No runtime evidence"}], "release": {"version": "fixture"}, "jobs": [], "model_catalog": smoke_model_catalog()}
    def details(self, gid, executable=None):
        return self.library()["games"][0]
    def check_app_updates(self, force=True):
        return {"current": VERSION, "latest": VERSION, "auto_check": False, "update_available": False}
    def jobs(self):
        return []
    def close(self):
        pass


def dispose_window(app, window):
    """Destroy native widgets while Python callbacks and Qt are still available."""
    if not window._closed:
        # An external application.quit() must still use the normal guarded close.
        loop = QEventLoop()
        waiter = QTimer()
        waiter.setInterval(20)
        waiter.timeout.connect(lambda: loop.quit() if window._closed else None)
        waiter.start()
        window.receive_shutdown_signal()
        window._process_shutdown()
        if not window._closed:
            loop.exec()
        waiter.stop()
        waiter.deleteLater()
    for timer in window.findChildren(QTimer):
        timer.stop()
    # finished() can precede thread-local destructors; wait before native deletion.
    for thread in window.findChildren(QThread):
        thread.wait()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def main(argv=None):
    parser = argparse.ArgumentParser(description="HelixSR native desktop app")
    parser.add_argument("--home")
    parser.add_argument("--settings")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-cycles", type=int, default=0,
                        help="Exercise 1-20 read-only fixture UI cycles before smoke-test exit")
    parser.add_argument("--screenshot")
    args = parser.parse_args(argv)
    if args.smoke_cycles and (not args.smoke_test or not 1 <= args.smoke_cycles <= 20):
        parser.error("--smoke-cycles requires --smoke-test and a value from 1 to 20")
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.screenshot and not Path(args.screenshot).is_absolute():
        parser.error("--screenshot must be an absolute path")
    existing_app = QApplication.instance()
    app = existing_app or QApplication(sys.argv[:1])
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
    smoke_driver = None
    if args.smoke_cycles:
        from .smoke import StressBackend, StressDriver
        backend = StressBackend()
    elif args.smoke_test:
        backend = SmokeBackend()
    else:
        from .backend import DesktopBackend
        backend = DesktopBackend(home=args.home, settings=args.settings)
    window = MainWindow(backend)
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous_handlers:
        signal.signal(sig, window.receive_shutdown_signal)
    window.show()
    if args.smoke_cycles:
        smoke_driver = StressDriver(window, args.smoke_cycles)
    elif args.smoke_test:
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
        status = app.exec()
        if smoke_driver is not None:
            smoke_driver.validate()
        return status
    finally:
        try:
            dispose_window(app, window)
            if smoke_driver is not None:
                from shiboken6 import isValid
                if isValid(window):
                    raise RuntimeError("Smoke test left the native window alive")
            if existing_app is None:
                app.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                if smoke_driver is not None and QApplication.instance() is not None:
                    raise RuntimeError("Smoke test left a QApplication alive")
        finally:
            try:
                if smoke_driver is not None:
                    smoke_driver.cleanup()
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
