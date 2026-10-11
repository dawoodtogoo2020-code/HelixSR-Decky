"""Bounded, read-only runtime observations. Existing log text is never live proof."""
import os
from pathlib import Path
import re
import stat
import time

from awareness import active_processes

LIMIT = 32768
SUCCESS = re.compile(r'\bdispatch\b[^\r\n]*\brender\s+\d+x\d+\s*->\s*\d+x\d+', re.I)
READY = re.compile(r'\bnetwork running\s*\(', re.I)
FAILURE = re.compile(r'\b(?:HelixSR ERROR|network (?:failed|not loaded)|network shaders unavailable|falling back|using fallback|fallback activated|placeholder upscale|RED FRAME|red border)\b', re.I)


def regular_beneath(path, root):
    """Reject symlink components and non-regular logs, including after opening."""
    path, root = Path(path), Path(root)
    path.relative_to(root)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('A runtime log path is a symbolic link')
        if part == root:
            break
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    if os.open in os.supports_dir_fd:
        # Hold each directory by FD, so a parent swapped to a symlink between
        # validation and open cannot redirect the log read outside this root.
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.relative_to(root).parts[:-1]:
                next_parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = next_parent
            fd = os.open(path.name, flags, dir_fd=parent)
        finally:
            os.close(parent)
    else:
        fd = os.open(path, flags)
    stream = os.fdopen(fd, 'rb')
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        stream.close()
        raise ValueError('A runtime log is not a private regular file')
    return stream, info


def mapped_paths(pid, paths):
    """An exact mapped path establishes module presence, never rendered output."""
    try:
        with (Path('/proc') / str(pid) / 'maps').open() as stream:
            source = stream.read(4 << 20)
        mapped = {line.split(None, 5)[5].removesuffix(' (deleted)')
                  for line in source.splitlines() if len(line.split(None, 5)) == 6}
        return any(str(path) in mapped for path in paths)
    except OSError:
        return False


def executable_session(proc, expected):
    """Do not attribute a Steam AppID launcher's log to the game executable."""
    if not expected or not proc.get('started_at', 0):
        return None
    try:
        base = Path('/proc') / str(proc['pid'])
        args = (base / 'cmdline').read_bytes()[:32768].split(b'\0')
        name = Path(expected).name.lower()
        candidates = [arg.decode(errors='replace').replace('\\', '/').split('/')[-1].lower()
                      for arg in args if arg.lower().endswith(b'.exe')]
        if name not in candidates:
            return None
        start_ticks = (base / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        return (proc['pid'], start_ticks)
    except (OSError, ValueError, IndexError):
        return None


def writing_log(pid, info):
    """Only a writable FD on this exact inode ties a new log to the game."""
    try:
        base = Path('/proc') / str(pid)
        for fd in list((base / 'fd').iterdir())[:4096]:
            try:
                opened = fd.stat()
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    continue
                source = (base / 'fdinfo' / fd.name).read_text()[:4096]
                flags = re.search(r'(?m)^flags:\s*([0-7]+)', source)
                if flags and int(flags[1], 8) & os.O_ACCMODE in (os.O_WRONLY, os.O_RDWR):
                    return True
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return False


class RuntimeEvidence:
    def __init__(self, game):
        self.game = dict(game)
        self.root = Path(game['folder'])
        self.expected = game.get('main_exe')
        target = Path(game['target']) if game.get('target') else None
        # Direct installations may place the API DLL separately from the EXE.
        directories = {Path(p).parent for p in game.get('targets', [])}
        if target:
            directories.add(target)
        self.paths = sorted({d / suffix for d in directories
                             for suffix in ('helixsr.log', 'HelixSR/helixsr.log')}, key=str)
        self.modules = [Path(p) for p in game.get('targets', [])]
        if game.get('route') == 'optiscaler' and target:
            self.modules += [target / 'HelixSR/helixsr.dll', target / 'HelixSR/helixsr_upscaler.dll']
        self.session = None
        self.cursors = {}
        self.event = None
        self.ready = set()
        self.failed = False
        self.prelaunch = False
        self.absent = set()

    @staticmethod
    def _cursor(stream, info):
        stream.seek(0)
        prefix = stream.read(min(info.st_size, 4096))
        stream.seek(max(0, info.st_size - 128))
        return dict(identity=(info.st_dev, info.st_ino), offset=info.st_size,
                    pending=b'', prefix=prefix, anchor=stream.read(128))

    def _prime(self):
        for path in self.paths:
            try:
                stream, info = regular_beneath(path, self.root)
                with stream:
                    self.cursors[str(path)] = self._cursor(stream, info)
                self.absent.discard(str(path))
            except FileNotFoundError:
                self.cursors.pop(str(path), None)
                self.absent.add(str(path))
            except (OSError, ValueError):
                self.cursors.pop(str(path), None)
                self.absent.discard(str(path))

    def _read(self, path, proc):
        with_regular, info = regular_beneath(path, self.root)
        with with_regular as stream:
            identity = (info.st_dev, info.st_ino)
            cursor = self.cursors.get(str(path))
            if (not cursor and str(path) in self.absent and writing_log(proc['pid'], info)
                    and executable_session(proc, self.expected) == self.session):
                # Monitor was armed before launch and this game owns the new
                # log's writable FD. Capture one-time initialization safely.
                cursor = dict(identity=identity, offset=0, pending=b'', prefix=b'', anchor=b'')
                self.cursors[str(path)] = cursor
            self.absent.discard(str(path))
            continuous = True
            if cursor:
                stream.seek(0)
                continuous = stream.read(len(cursor['prefix'])) == cursor['prefix']
                stream.seek(max(0, cursor['offset'] - len(cursor['anchor'])))
                continuous = continuous and stream.read(len(cursor['anchor'])) == cursor['anchor']
            # First attach, replacement and truncation establish a baseline.
            # Skip existing text even if somebody touches its timestamp.
            if not cursor or cursor['identity'] != identity or info.st_size < cursor['offset'] or not continuous:
                self.event = None
                self.ready.discard(str(path))
                self.cursors[str(path)] = self._cursor(stream, info)
                return []
            offset = cursor['offset']
            if info.st_size - offset > LIMIT:
                # Discard an overflow rather than promote a truncated historic fragment.
                self.cursors[str(path)] = self._cursor(stream, info)
                raise ValueError('Runtime log grew too quickly; evidence reset')
            stream.seek(offset)
            data = cursor['pending'] + stream.read(LIMIT)
            cursor['offset'] = stream.tell()
            stream.seek(0)
            cursor['prefix'] = stream.read(min(cursor['offset'], 4096))
            stream.seek(max(0, cursor['offset'] - 128))
            cursor['anchor'] = stream.read(min(128, cursor['offset']))
            lines = data.split(b'\n')
            cursor['pending'] = lines.pop()[-4096:]
            return [line.decode(errors='replace') for line in lines]

    def sample(self):
        base = dict(game_name=self.game.get('name', 'Game'), version=self.game.get('installed_version') or 'unknown',
                    model=self.game.get('installed_model') or 'unknown', route=self.game.get('route') or 'unknown',
                    observed_at=time.time())
        processes = active_processes(self.root, self.game.get('appid', ''))
        sessions = [(executable_session(p, self.expected), p) for p in processes]
        sessions = [(s, p) for s, p in sessions if s]
        if len(sessions) != 1:
            self.session = None
            self.cursors.clear()
            self.event = None
            self.ready.clear()
            self.failed = False
            if processes:
                self.prelaunch = False
                self.absent.clear()
                return dict(base, state='unverified', label='Game running; HelixSR unverified',
                            detail='The running executable could not be identified uniquely. No current output claim.')
            self._prime()
            self.prelaunch = True
            return dict(base, state='not_running', label='No running game observed',
                        detail='Launch this game, select its required upscaler, and keep this monitor enabled.')
        session, proc = sessions[0]
        if session != self.session:
            self.session = session
            if not self.prelaunch:
                self.cursors.clear()
                self.absent.clear()
            self.prelaunch = False
            self.event = None
            self.ready.clear()
            self.failed = False
        if self.game.get('managed') and not self.game.get('enabled'):
            return dict(base, state='disabled', label='Recorded installation disabled',
                        detail='Close the game and enable HelixSR before testing again.')
        if not self.game.get('managed') or not mapped_paths(proc['pid'], self.modules):
            # Keep armed prelaunch positions while the module is still loading.
            self.event = None
            self.ready.clear()
            self.failed = False
            return dict(base, state='unverified', label='Game running; HelixSR unverified',
                        detail='No managed HelixSR module mapping verified. File installation alone is not output evidence.')
        errors = []
        for path in self.paths:
            try:
                for line in self._read(path, proc):
                    if FAILURE.search(line):
                        self.event = ('failure', time.time())
                        self.failed = True
                        self.ready.clear()
                    elif SUCCESS.search(line) and str(path) in self.ready and not self.failed:
                        self.event = ('output', time.time())
                    elif READY.search(line):
                        self.event = ('loaded', time.time())
                        self.ready.add(str(path))
                        self.failed = False
            except FileNotFoundError:
                if str(path) in self.cursors:
                    self.cursors.pop(str(path), None)
                    self.event = None
                    self.ready.discard(str(path))
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            self.event = None
            self.ready.clear()
            return dict(base, state='unavailable', label='Runtime evidence unavailable', detail=errors[0][:200])
        state, when = self.event or ('mapped', 0)
        age = max(0, time.time() - when) if when else None
        labels = dict(failure='Session log reports a fallback/error', output='Neural output reported this session',
                      loaded='HelixSR network loaded; output unverified', mapped='HelixSR module mapped; output unverified')
        detail = ('A new dispatch was read after monitoring started. This does not verify image quality or continuous rendering.'
                  if state == 'output' else 'New session evidence only. Existing log text is not treated as live output.')
        if age is not None:
            detail += f' Last event {int(age)}s ago.'
        return dict(base, state=state, label=labels[state], detail=detail, last_event_at=when,
                    evidence_age=age, pid=proc['pid'])
