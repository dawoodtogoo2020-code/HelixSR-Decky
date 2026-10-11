"""One read-only sampler and an isolated, optional status HUD per frontend."""
import copy
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from runtime_status import RuntimeEvidence
from host_environment import host_environment


def private_directory(path):
    path = Path(path)
    # Refuse links in the existing path, never fix somebody else's permissions.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Status directory contains a symbolic link')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, 'getuid') and info.st_uid != os.getuid()) or info.st_mode & 0o077:
        raise ValueError('Status directory must be private and owned by your user')
    return path


def display_environment():
    env = dict(os.environ)
    if env.get('DISPLAY'):
        return env
    # Decky can run outside Steam's environment. Read only this user's actual
    # Steam process, never guess a display or change X access controls.
    if platform.system() == 'Linux':
        for path in list(Path('/proc').glob('[0-9]*'))[:4096]:
            try:
                if path.stat().st_uid != os.getuid() or (path / 'comm').read_text().strip() != 'steam':
                    continue
                values = dict(item.split(b'=', 1) for item in (path / 'environ').read_bytes()[:131072].split(b'\0') if b'=' in item)
                if b'DISPLAY' in values:
                    for key in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE'):
                        if key.encode() in values:
                            env[key] = values[key.encode()].decode()
                    return env
            except (OSError, ValueError, UnicodeError):
                continue
    return env


def child_command(directory, nonce, *, frozen_child=False, env=None):
    if frozen_child:
        return [sys.executable, '--status-overlay-child', str(directory), nonce]
    interpreter = sys.executable
    if getattr(sys, 'frozen', False):
        interpreter = shutil.which('python3', path=(env or {}).get('PATH'))
        if not interpreter:
            raise ValueError('System Python 3 is required for the Decky overlay helper')
    return [interpreter, str(Path(__file__).with_name('overlay_helper.py')), str(directory), nonce]


def record_stamp(path):
    try:
        value = path.stat()
        return (value.st_ino, value.st_size, value.st_mtime_ns)
    except FileNotFoundError:
        return None


class StatusMonitor:
    def __init__(self, manager, *, frozen_child=False):
        self.manager = manager
        self.frozen_child = frozen_child
        self.lock = threading.RLock()
        self.control = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.child = None
        self.directory = None
        self.closed = False
        self.value = self._disabled()

    @staticmethod
    def _disabled():
        return dict(enabled=False, game_id=None, overlay=dict(state='disabled', label='Status overlay off',
                    detail='Enable for the selected game to check the HUD and monitor runtime evidence.',
                    responding=False, visible_verified=False), runtime=dict(state='unverified', label='Monitor off', detail=''))

    def status(self):
        with self.lock:
            value = copy.deepcopy(self.value)
        if value['enabled'] and time.monotonic() - value.get('_sampled', time.monotonic()) > 6:
            value['runtime'] = dict(state='unavailable', label='Runtime sampler stale', detail='Toggle the monitor off and on to retry.')
            value['overlay'] = dict(state='stale', label='Overlay status stale', detail='No current health confirmation.', responding=False, visible_verified=False)
        value.pop('_sampled', None)
        return value

    def configure(self, gid, enabled, executable=None):
        if type(enabled) is not bool:
            raise ValueError('Overlay setting requires a boolean')
        with self.control:
            if self.closed:
                raise ValueError('The status monitor is closed')
            self._stop()
            if not enabled:
                return self.status()
            if not isinstance(gid, str) or not gid:
                raise ValueError('Select a game before enabling its status overlay')
            game = self.manager.assess_safe(self.manager.get_game(gid), executable=executable)
            evidence = RuntimeEvidence(game)
            record = self.manager.record_path(game)
            stamp = record_stamp(record)
            self.stop = threading.Event()
            with self.lock:
                self.value = dict(enabled=True, game_id=gid, _sampled=time.monotonic(),
                    overlay=dict(state='starting', label='Checking overlay helper', detail='Display and input transparency checks are pending.', responding=False, visible_verified=False),
                    runtime=dict(state='unverified', label='Checking runtime evidence', detail='Existing log text will not be treated as live proof.'))
            if platform.system() == 'Linux':
                try:
                    parent = private_directory(Path(self.manager.home) / '.cache/helixsr-status')
                    self.directory = Path(tempfile.mkdtemp(prefix='session-', dir=parent))
                    self.nonce = uuid.uuid4().hex
                    env = display_environment()
                    if getattr(sys, 'frozen', False) and not self.frozen_child:
                        env = host_environment(env)
                    self.child = subprocess.Popen(child_command(self.directory, self.nonce, frozen_child=self.frozen_child, env=env), env=env,
                                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.started_at = time.monotonic()
                except (OSError, ValueError) as exc:
                    self._overlay_error(str(exc))
            else:
                self._overlay_error('The continuous overlay currently requires Linux X11 or a verified Gamescope session.')
            self.thread = threading.Thread(target=self._loop, args=(evidence, record, stamp), daemon=True, name='HelixSR-status')
            self.thread.start()
            return self.status()

    def _overlay_error(self, detail, state='unavailable'):
        with self.lock:
            self.value['overlay'] = dict(state=state, label='Overlay unavailable', detail=detail[:240], responding=False, visible_verified=False)

    def _frame(self, runtime, sequence):
        from overlay_helper import write_private
        write_private(self.directory / 'frame.json', dict(schema=1, nonce=self.nonce, sequence=sequence,
                      expires_at=time.monotonic() + 8, **{k: runtime.get(k, '') for k in ('state', 'label', 'game_name', 'version', 'model')}))

    def _health(self, sequence):
        if not self.child:
            return
        from overlay_helper import read_private
        try:
            ack = read_private(self.directory / 'ack.json')
            if ack.get('nonce') != self.nonce:
                raise ValueError('Overlay acknowledgement belongs to a different session')
            if self.child.poll() is not None and ack.get('state') not in ('unavailable', 'conflict'):
                raise ValueError('Overlay helper exited')
            if ack.get('state') not in ('unavailable', 'conflict'):
                observed = ack.get('observed_at', 0)
                if not isinstance(observed, (int, float)) or not 0 <= time.monotonic() - observed < 3:
                    raise ValueError('Overlay helper heartbeat expired')
                if not isinstance(ack.get('sequence'), int) or not 0 <= sequence - ack['sequence'] <= 2:
                    raise ValueError('Overlay helper has not consumed current status')
            with self.lock:
                self.value['overlay'] = {k: ack.get(k) for k in ('state', 'label', 'detail', 'responding', 'provider')}
                self.value['overlay']['visible_verified'] = False
        except FileNotFoundError:
            if self.child.poll() is not None:
                self._overlay_error('Overlay helper exited before confirming startup.')
            elif time.monotonic() - getattr(self, 'started_at', time.monotonic()) > 4:
                self.child.terminate()
                self._overlay_error('Overlay startup timed out. Toggle off and on to retry.')
        except (OSError, ValueError, TypeError) as exc:
            self._overlay_error(str(exc), 'stale')

    def _loop(self, evidence, record, stamp):
        sequence = 0
        while not self.stop.is_set():
            try:
                if record_stamp(record) != stamp:
                    runtime = dict(state='unverified', label='Installation changed; recheck required',
                                   detail='Turn the monitor off, refresh the game, and enable it again.')
                else:
                    runtime = evidence.sample()
            except Exception as exc:
                runtime = dict(state='unavailable', label='Runtime sampler unavailable', detail=str(exc)[:200])
            with self.lock:
                self.value['runtime'] = runtime
                self.value['_sampled'] = time.monotonic()
            sequence += 1
            if self.child:
                try:
                    self._frame(runtime, sequence)
                    self._health(sequence)
                except (OSError, ValueError) as exc:
                    self._overlay_error(str(exc))
            self.stop.wait(1.5)

    def _stop(self):
        self.stop.set()
        still_stopping = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(5)
            still_stopping = self.thread.is_alive()
        if self.child:
            # Signal only the subprocess handle this controller created.
            if self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=2)
            self.child = None
        if still_stopping:
            # Destroy the owned HUD even if a read is slow. Retain its directory
            # until the writer finishes; no replacement sampler is started.
            self._overlay_error('Status sampler is still stopping; retry shortly.')
            raise ValueError('Status sampler is still stopping; retry shortly')
        self.thread = None
        if self.directory:
            for name in ('frame.json', 'ack.json', 'frame.tmp', 'ack.tmp'):
                (self.directory / name).unlink(missing_ok=True)
            self.directory.rmdir()
            self.directory = None
        with self.lock:
            self.value = self._disabled()

    def close(self):
        with self.control:
            self._stop()
            self.closed = True
