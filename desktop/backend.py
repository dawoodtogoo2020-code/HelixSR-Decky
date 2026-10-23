"""Synchronous desktop adapter; all game transactions stay in Manager."""
import copy
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from manager import Manager, atomic_json
from status_monitor import StatusMonitor
from .app_updates import AppUpdates
from .system import system_status


def valid_package_record(record):
    """Persisted preparation metadata is untrusted input to the shared engine."""
    if not isinstance(record, dict):
        return False
    path, version = record.get('path'), record.get('version')
    if (not isinstance(path, str) or not path or '\x00' in path or not Path(path).is_absolute()
            or not isinstance(version, str)
            or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version)):
        return False
    prepared = record.get('prepared_at', 0)
    if type(prepared) not in (int, float) or (type(prepared) is float and not math.isfinite(prepared)) or prepared < 0:
        return False
    digest = record.get('release_sha256')
    if 'release_sha256' in record and (not isinstance(digest, str)
            or not re.fullmatch(r'[a-fA-F0-9]{64}', digest)):
        return False
    files = record.get('files')
    if not isinstance(files, dict) or not files:
        return False
    for name, digest in files.items():
        if not isinstance(name, str) or not name or '\x00' in name or '\\' in name or ':' in name:
            return False
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '.' in relative.parts
                or relative.as_posix() != name or name == '.'
                or not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest)):
            return False
    return True


class DesktopBackend:
    def __init__(self, home=None, settings=None):
        self.home = Path(home if home is not None else Path.home()).expanduser().resolve()
        config = os.environ.get('XDG_CONFIG_HOME')
        base = Path(config) if config and Path(config).is_absolute() else self.home / '.config'
        self.settings = Path(settings) if settings is not None else base / 'helixsr-desktop'
        self.settings = self.settings.expanduser().resolve()
        self.settings.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        self.warnings = []
        path = self.settings / 'settings.json'
        if path.exists():
            try:
                if path.stat().st_size > 4 << 20:
                    raise ValueError('Desktop settings are too large')
                cfg = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(cfg, dict) or not isinstance(cfg.get('imports', []), list)
                        or not isinstance(cfg.get('packages', {}), dict)):
                    raise ValueError('Invalid desktop settings structure')
                if any(not isinstance(x, dict) or not isinstance(x.get('folder'), str)
                       for x in cfg.get('imports', [])):
                    raise ValueError('Invalid imported game settings')
                packages = cfg.get('packages', {})
                valid = {key: value for key, value in packages.items() if valid_package_record(value)}
                if len(valid) != len(packages):
                    backup = path.with_name('settings.json.corrupt-' + uuid.uuid4().hex)
                    os.replace(path, backup)
                    self.warnings.append(f'Invalid prepared package entries ignored; original settings preserved at {backup}. Per-game records are unchanged.')
                    cfg['packages'] = valid
                cfg.setdefault('imports', [])
                cfg.setdefault('packages', {})
                cfg.setdefault('license', None)
                atomic_json(path, cfg)
            except (ValueError, UnicodeError):
                backup = path.with_name('settings.json.corrupt-' + uuid.uuid4().hex)
                os.replace(path, backup)
                self.warnings.append(f'Unreadable desktop settings preserved at {backup}; per-game records remain available.')
        self.manager = Manager(self.home, self.settings)
        self.status_monitor = StatusMonitor(self.manager, frozen_child=bool(getattr(sys, 'frozen', False)))
        self.app_updates = AppUpdates(self.settings)

    def overlay_status(self):
        """Return the monitor's cached snapshot without waiting for Manager work."""
        self._open()
        return self.status_monitor.status()

    def set_status_overlay(self, gid, enabled, executable=None):
        self._open()
        return self.status_monitor.configure(gid, enabled, executable)

    def _open(self):
        if self.closed:
            raise ValueError('The desktop service is closed')

    def _write(self):
        self._open()
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            raise ValueError('Run HelixSR Desktop as your normal user; game changes as root are refused')

    def library(self):
        with self.lock:
            self._open()
            result = self.manager.refresh()
            result['warnings'] = self.warnings + result.get('warnings', [])
            return result

    def details(self, gid, executable=None):
        with self.lock:
            self._open()
            return self.manager.assess_safe(self.manager.get_game(gid), executable=executable)

    def check_helix_updates(self, force=True):
        with self.lock:
            self._open()
            return self.manager.check_update(bool(force))

    def set_game_settings(self, gid, changes, revision):
        with self.lock:
            self._write()
            return self.manager.set_game_settings(gid, changes, revision)

    def set_installation_route(self, gid, route):
        with self.lock:
            self._write()
            return self.manager.set_installation_route(gid, route)

    def accept_license(self, accepted, token=None):
        if type(accepted) is not bool:
            raise ValueError('License acceptance requires a boolean')
        with self.lock:
            self._write()
            return self.manager.accept_license(accepted, token)

    def preview_latest(self, gid, dx12_confirmed=False, variant_id=None, executable=None, release_choice=None):
        with self.lock:
            self._open()
            return self.manager.preview_latest(gid, dx12_confirmed, variant_id, executable, release_choice)

    def install_latest(self, token):
        with self.lock:
            self._write()
            return self.manager.execute_latest(token)

    def preview_action(self, gid, action, dx12_confirmed=False, executable=None):
        with self.lock:
            self._open()
            return self.manager.preview(gid, action, dx12_confirmed, executable)

    def apply_action(self, token):
        with self.lock:
            self._write()
            return self.manager.execute(token)

    def jobs(self):
        # Do not acquire the service or Manager lock: preparation and transactions
        # can hold them while the UI still needs progress and cancellation.
        return [copy.deepcopy(job) for job in list(self.manager.jobs.values())]

    def cancel_job(self, jid):
        return self.manager.cancel_job(jid)

    def import_launcher(self, source):
        with self.lock:
            self._write()
            return self.manager.import_launcher(source)

    def import_folders(self, folders):
        with self.lock:
            self._write()
            return self.manager.import_folders(folders)

    def forget_game(self, gid):
        with self.lock:
            self._write()
            return self.manager.forget(gid)

    def system_status(self):
        return system_status()

    def check_app_updates(self, force=True):
        return self.app_updates.check(bool(force))

    def set_app_auto_check(self, enabled):
        self._open()
        return self.app_updates.set_auto(enabled)

    def download_app_update(self):
        self._write()
        return self.app_updates.download()

    def close(self):
        self.closed = True
        monitor_stopped = True
        try:
            self.status_monitor.close()
        except Exception:
            monitor_stopped = False
        for job in self.jobs():
            if job['state'] == 'running':
                self.manager.cancel_job(job['id'])
        worker = self.manager.worker
        if worker and worker is not threading.current_thread():
            worker.join(15)
        return monitor_stopped and not (worker and worker.is_alive())
