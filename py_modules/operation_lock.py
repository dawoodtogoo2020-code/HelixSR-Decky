"""Nonblocking shared game locks for Decky and the desktop manager.

Lock files remain in place: unlinking a live lock would allow another writer
to lock a different inode. The OS releases the advisory lock after a crash.
"""
import contextlib
from functools import wraps
import os
from pathlib import Path
import stat
import threading

_held = threading.local()


@contextlib.contextmanager
def operation_lock(companion):
    directory = Path(companion)
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError('Companion directory cannot be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.operation.lock'
    key = os.path.normcase(str(path.absolute()))
    held = getattr(_held, 'paths', {})
    _held.paths = held
    if key in held:
        yield
        return
    if path.is_symlink():
        raise ValueError('Operation lock cannot be a symlink')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    if os.name == 'posix':
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(path.name, flags, 0o600, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    else:
        fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Operation lock must be a regular private file')
        if os.name == 'posix':
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another HelixSR manager is working on this game. Wait and try again.') from None
        else:
            import msvcrt
            if not info.st_size:
                os.write(fd, b'0')
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError('Another HelixSR manager is working on this game. Wait and try again.') from None
        acquired = True
        held[key] = fd
        yield
    finally:
        if acquired:
            held.pop(key, None)
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)


def game_locked(method):
    @wraps(method)
    def wrapped(self, game, *args, **kwargs):
        with operation_lock(self.companion(game)):
            return method(self, game, *args, **kwargs)
    return wrapped
