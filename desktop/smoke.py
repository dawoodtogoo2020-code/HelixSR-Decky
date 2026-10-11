"""Bounded real-widget stress test with fixtures only, also usable when frozen."""
import gc
import json
import os
from pathlib import Path
import tempfile
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QFileDialog


class StressBackend:
    """No Manager, network, real game paths, or persistent application settings."""
    def __init__(self):
        self.calls = 0
        self.closed = 0
        self.imports = 0
        self.launchers = []
        self.jobs_created = 0
        self.removed = 0
        self.job_list = []
        self.managed = False

    def _called(self):
        if QThread.isMainThread():
            raise AssertionError("Backend fixture called on the GUI thread")
        self.calls += 1

    def _game(self):
        return dict(id="fixture", name="Fixture DX12 game", folder="/fixture/game",
                    source="Imported", compatibility="candidate", managed=self.managed,
                    enabled=self.managed, route="direct", optiscaler={},
                    framegen_summary="No runtime evidence")

    def _library(self):
        from .app import smoke_model_catalog
        return dict(games=[self._game()], jobs=[dict(j) for j in self.job_list],
                    release={"version": "fixture"}, warnings=[], model_catalog=smoke_model_catalog())

    def library(self):
        self._called()
        return self._library()

    def details(self, gid):
        self._called()
        return self._game()

    def check_app_updates(self, force=False):
        self._called()
        return dict(auto_check=False, update_available=False)

    def preview_latest(self, gid, confirmed=False, variant_id=None):
        self._called()
        assert variant_id == "helixsr-model-e", variant_id
        return dict(token="fixture", action="install", name="Fixture DX12 game",
                    route="direct", files=["fixture.dll"], model="HelixSR Model E", release_version="fixture")

    def preview_action(self, gid, action, confirmed=False):
        self._called()
        return dict(token="fixture", action=action, name="Fixture DX12 game",
                    route="direct", files=["fixture.dll"])

    def accept_license(self, accepted, token=None):
        self._called()
        assert accepted
        assert token == "fixture", token

    def install_latest(self, token):
        self._called()
        self.jobs_created += 1
        job = dict(id=str(self.jobs_created), game="Fixture DX12 game", state="running",
                   message="Fixture operation", log="No game files are changed")
        self.job_list = [job]
        return dict(job)

    def jobs(self):
        self._called()
        self.managed = True
        self.job_list = [dict(j, state="done", message="Fixture complete") for j in self.job_list]
        return [dict(j) for j in self.job_list]

    def apply_action(self, token):
        self._called()
        self.removed += 1
        self.managed = False
        return dict(message="Fixture removed")

    def import_folders(self, folders):
        self._called()
        assert len(folders) == 2 and all(Path(p).is_dir() for p in folders)
        self.imports += 1
        return self._library()

    def import_launcher(self, source):
        self._called()
        self.launchers.append(source)
        return self._library()

    def close(self):
        self._called()
        self.closed += 1
        return True


class StressDriver(QObject):
    def __init__(self, window, cycles):
        super().__init__(window)
        self.window = window
        self.cycles = cycles
        self.cycle = 0
        self.stage = 0
        self.preview_accept = False
        self.errors = []
        self.gui_checks = 0
        self.none_refcounts = []
        self.temp = tempfile.TemporaryDirectory(prefix="helixsr-ui-smoke-",
                                               dir=os.environ.get("HELIXSR_TEST_TMP"))
        self.folders = [Path(self.temp.name) / name for name in ("Game One", "Game Two")]
        for folder in self.folders:
            folder.mkdir()
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.advance)
        self.timer.start()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(60000)
        self.deadline.timeout.connect(self.timed_out)
        self.deadline.start()

    def _gui(self):
        assert QThread.currentThread() == self.window.thread(), "UI callback outside GUI thread"
        self.gui_checks += 1

    @Slot()
    def timed_out(self):
        self.errors.append("Fixture workflow exceeded 60 seconds")
        self.timer.stop()
        self.window.receive_shutdown_signal()

    @Slot()
    def advance(self):
        try:
            self._gui()
            window = self.window
            if window._closing:
                return
            dialog = window._active_dialog
            if window._modal:
                if dialog is not None and hasattr(dialog, "ack"):
                    if self.preview_accept:
                        dialog.ack.setChecked(True)
                        dialog.accept()
                    else:
                        dialog.reject()
                return
            if window._task:
                return
            if any(j.get("state") == "running" for j in window._jobs):
                window.poll_jobs()
                return
            stage = self.stage
            self.stage += 1
            if stage == 0:
                if not self.none_refcounts:
                    gc.collect()
                    self.none_refcounts.append(sys.getrefcount(None))
                QTimer.singleShot(10, self.pick_folders)
                window.import_folders()
            elif stage in (1, 2):
                source = ("heroic", "lutris")[stage - 1]
                window.launchers.setCurrentIndex(window.launchers.findData(source))
                window.import_button.click()
            elif stage in (3, 4, 5):
                assert window.models.currentData() == "helixsr-model-e"
                self.preview_accept = stage != 3
                window.preview_latest()
            elif stage == 6:
                self.preview_accept = True
                window.preview_action("remove")
            elif stage < 27:
                # Repeated discovery exercises worker/result teardown, details,
                # automatic-check callbacks, and both None and dictionary values.
                if stage % 2:
                    window.refresh()
                else:
                    window._run(lambda: None, self.none_received)
            else:
                gc.collect()
                self.none_refcounts.append(sys.getrefcount(None))
                self.cycle += 1
                if self.cycle == self.cycles:
                    self.timer.stop()
                    self.deadline.stop()
                    window.close()
                else:
                    self.stage = 0
        except Exception as exc:
            self.errors.append(str(exc))
            self.timer.stop()
            self.window.receive_shutdown_signal()

    def none_received(self, value):
        self._gui()
        assert value is None

    @Slot()
    def pick_folders(self):
        try:
            self._gui()
            dialog = self.window._active_dialog
            for folder in self.folders:
                def choose(path=folder):
                    self._gui()
                    picker = dialog._picker
                    assert isinstance(picker, QFileDialog)
                    picker.setDirectory(str(path))
                    QTimer.singleShot(10, picker.accept)
                QTimer.singleShot(10, choose)
                dialog.add_button.click()
            assert dialog.selectedFiles() == [str(p.resolve()) for p in self.folders]
            dialog.import_button.click()
        except Exception as exc:
            self.errors.append(str(exc))
            self.window.receive_shutdown_signal()

    def validate(self):
        backend = self.window.backend
        assert not self.errors, self.errors
        assert self.cycle == self.cycles, (self.cycle, self.cycles)
        assert backend.closed == 1, backend.closed
        assert backend.imports == self.cycles, backend.imports
        assert backend.launchers == ["heroic", "lutris"] * self.cycles, backend.launchers
        assert backend.jobs_created == self.cycles * 2, backend.jobs_created
        assert backend.removed == self.cycles, backend.removed
        assert backend.calls >= self.cycles * 40, backend.calls
        assert self.gui_checks >= self.cycles * 10, self.gui_checks
        print("PRODUCTION_STRESS_OK " + json.dumps(dict(
            cycles=self.cycle, backend_calls=backend.calls, gui_checks=self.gui_checks,
            imports=backend.imports, jobs=backend.jobs_created, removals=backend.removed,
            python=sys.version.split()[0], none_refcounts=self.none_refcounts)), flush=True)

    def cleanup(self):
        self.temp.cleanup()
