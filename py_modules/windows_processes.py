"""Read-only Windows process guard for the native verification harness."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path

from library import scan_tree


def active_processes(root):
    # Restrict access requests to executable names actually present in this game.
    names = {name.casefold() for _, files in scan_tree(root) for name in files
             if name.lower().endswith('.exe')}
    if not names:
        return []
    class Entry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('exe', w.WCHAR * 260)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    def bind(name, result, *args):
        fn = getattr(k, name)
        fn.restype, fn.argtypes = result, args
        return fn
    snapshot = bind('CreateToolhelp32Snapshot', w.HANDLE, w.DWORD, w.DWORD)(2, 0)
    close = bind('CloseHandle', w.BOOL, w.HANDLE)
    if snapshot == w.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        first = bind('Process32FirstW', w.BOOL, w.HANDLE, ctypes.POINTER(Entry))
        next_entry = bind('Process32NextW', w.BOOL, w.HANDLE, ctypes.POINTER(Entry))
        open_process = bind('OpenProcess', w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
        image_name = bind('QueryFullProcessImageNameW', w.BOOL, w.HANDLE, w.DWORD,
                          w.LPWSTR, ctypes.POINTER(w.DWORD))
        entry, found = Entry(), []
        entry.size = ctypes.sizeof(entry)
        ok = first(snapshot, ctypes.byref(entry))
        while ok:
            if entry.exe.casefold() in names:
                handle = open_process(0x1000, False, entry.pid)
                if not handle:
                    if ctypes.get_last_error() != 87:  # PID exited
                        raise ValueError('Cannot inspect process ' + entry.exe + '; close it before file changes')
                else:
                    try:
                        out, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
                        if not image_name(handle, 0, out, ctypes.byref(length)):
                            raise ctypes.WinError(ctypes.get_last_error())
                        if root in Path(out.value).resolve().parents:
                            found.append(dict(pid=entry.pid, env={}, started_at=0))
                    finally:
                        close(handle)
            ok = next_entry(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return found
    finally:
        close(snapshot)
