"""Durable ownership for Steam launch-option changes. Steam remains the live authority."""
import json
import os
from pathlib import Path
import re
import stat
import uuid
from operation_lock import operation_lock

LIMIT = 16384
NAME = 'launch-options.json'


def options(value):
    if not isinstance(value, str) or len(value) > LIMIT or '\0' in value:
        raise ValueError('Launch options must be a bounded string without NUL')
    return value


def validate(record):
    if not isinstance(record, dict) or set(record) - {'before', 'after', 'pending'}:
        raise ValueError('Invalid launch-option ownership receipt; manual review required')
    options(record.get('before'))
    options(record.get('after'))
    pending = record.get('pending')
    if pending is not None:
        if (not isinstance(pending, dict) or set(pending) != {'nonce', 'before', 'after', 'restore'}
                or not isinstance(pending['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', pending['nonce'])
                or type(pending['restore']) is not bool):
            raise ValueError('Invalid pending launch-option receipt; manual review required')
        options(pending['before'])
        options(pending['after'])
        if (pending['restore'] and (pending['before'] != record['after'] or pending['after'] != record['before'])):
            raise ValueError('Invalid restore ownership receipt')
        if not pending['restore'] and pending['after'] != record['after']:
            raise ValueError('Invalid save ownership receipt')
        if pending['before'] == pending['after']:
            raise ValueError('Invalid no-op pending ownership receipt')
    return record


class LaunchReceipts:
    def __init__(self, companion):
        self.companion = Path(companion)

    def _directory(self):
        directory = self.companion / 'records'
        for path in [directory, *directory.parents]:
            if path.is_symlink():
                raise ValueError('Launch receipt path cannot contain symlinks')
        if not directory.exists():
            directory.mkdir()
            self._sync(self.companion)
        if not directory.is_dir():
            raise ValueError('Invalid launch receipt directory')
        return directory

    @staticmethod
    def _sync(path):
        if os.name == 'posix':
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _read(self):
        if not (self.companion / 'records').exists() and not (self.companion / 'records').is_symlink():
            return None
        directory = self._directory()
        path = directory / NAME
        if path.is_symlink():
            raise ValueError('Launch ownership receipt cannot be a symlink')
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if os.name == 'posix' else None
        try:
            try:
                # A FIFO must not block the RPC before fstat can reject it.
                fd = os.open(NAME if directory_fd is not None else path,
                             os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory_fd)
            except FileNotFoundError:
                return None
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 524288:
                    raise ValueError('Invalid launch ownership receipt file')
                data = stream.read(524289)
            try:
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError('Duplicate launch receipt key')
                        result[key] = value
                    return result
                return validate(json.loads(data, object_pairs_hook=unique))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError('Malformed launch ownership receipt; manual review required') from exc
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def _write(self, record):
        directory = self._directory()
        # operation_lock may have just created the companion directory.
        self._sync(self.companion.parent)
        path = directory / NAME
        if path.is_symlink():
            raise ValueError('Launch ownership receipt cannot be a symlink')
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if os.name == 'posix' else None
        tmp = NAME + '.tmp-' + uuid.uuid4().hex
        try:
            if record is None:
                if path.exists():
                    os.unlink(NAME if directory_fd is not None else path, dir_fd=directory_fd)
            else:
                payload = (json.dumps(validate(record), ensure_ascii=False) + '\n').encode('utf-8')
                fd = os.open(tmp if directory_fd is not None else directory / tmp,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=directory_fd)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if directory_fd is not None:
                    os.replace(tmp, NAME, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                else:
                    os.replace(directory / tmp, path)
            if directory_fd is not None:
                os.fsync(directory_fd)
        finally:
            try:
                os.unlink(tmp if directory_fd is not None else directory / tmp, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            if directory_fd is not None:
                os.close(directory_fd)

    def _reconcile(self, record, actual):
        if record is None:
            return None
        pending = record.get('pending')
        if pending:
            if actual == pending['after']:
                record = None if pending['restore'] else {'before': record['before'], 'after': record['after']}
                self._write(record)
            elif actual != pending['before']:
                raise ValueError('Steam launch options changed outside this pending operation; preserve them and review manually')
        elif actual != record['after']:
            raise ValueError('Steam launch options differ from the owned receipt; preserve them and review manually')
        return record

    def owned(self, actual=None):
        with operation_lock(self.companion):
            record = self._read()
            return record if actual is None else self._reconcile(record, options(actual))

    def prepare(self, before, after, restore=False):
        options(before)
        options(after)
        if type(restore) is not bool or before == after:
            raise ValueError('Launch intent must describe an actual change')
        with operation_lock(self.companion):
            record = self._reconcile(self._read(), before)
            if record and record.get('pending'):
                pending = record['pending']
                if (pending['before'], pending['after'], pending['restore']) != (before, after, restore):
                    raise ValueError('Resolve the pending launch-option intent first')
                return dict(pending)
            if restore and (not record or before != record['after'] or after != record['before']):
                raise ValueError('Restore requires exact owned Steam launch options')
            original = record['before'] if record else before
            pending = {'nonce': uuid.uuid4().hex, 'before': before, 'after': after, 'restore': restore}
            self._write({'before': original, 'after': record['after'] if restore else after, 'pending': pending})
            return dict(pending)

    def finalize(self, nonce, actual):
        options(actual)
        if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{32}', nonce):
            raise ValueError('Invalid launch intent nonce')
        with operation_lock(self.companion):
            record = self._read()
            if not record or not record.get('pending') or record['pending']['nonce'] != nonce:
                raise ValueError('Launch intent expired; read live Steam options again')
            if actual != record['pending']['after']:
                raise ValueError('Steam did not retain the requested launch options; pending receipt preserved')
            return self._reconcile(record, actual)

    def remember(self, before, after):
        """Legacy post-save RPC: retain original ownership and never discard a pending intent."""
        options(before)
        options(after)
        with operation_lock(self.companion):
            record = self._read()
            if record and record.get('pending'):
                return bool(self._reconcile(record, after) is not None)
            if before == after:
                return True
            if record:
                if after == record['after']:
                    return True
                if before != record['after']:
                    raise ValueError('Launch ownership changed; manual review required')
                original = record['before']
            else:
                original = before
            updated = {'before': original, 'after': after}
            if record != updated:
                self._write(updated)
            return True

