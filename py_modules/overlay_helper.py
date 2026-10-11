"""Isolated X11 HUD. Never grabs input or modifies another overlay.

The gamescope external surface has one selected slot. A foreign HUD makes this
helper unmap itself. Drawing/IPC acknowledgements do not prove presentation.
"""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import stat
import sys
import time


def read_private(path, limit=16384):
    if path.is_symlink():
        raise ValueError('Overlay data is a symbolic link')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('Invalid overlay data file')
        return json.loads(stream.read(limit))


def write_private(path, data):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Attributes(C.Structure):
    _fields_ = [(n, t) for n, t in (
        ('x', C.c_int), ('y', C.c_int), ('width', C.c_int), ('height', C.c_int),
        ('border_width', C.c_int), ('depth', C.c_int), ('visual', C.c_void_p), ('root', C.c_ulong),
        ('class_', C.c_int), ('bit_gravity', C.c_int), ('win_gravity', C.c_int),
        ('backing_store', C.c_int), ('backing_planes', C.c_ulong), ('backing_pixel', C.c_ulong),
        ('save_under', C.c_int), ('colormap', C.c_ulong), ('map_installed', C.c_int),
        ('map_state', C.c_int), ('all_event_masks', C.c_long), ('your_event_mask', C.c_long),
        ('do_not_propagate_mask', C.c_long), ('override_redirect', C.c_int), ('screen', C.c_void_p))]


class Hints(C.Structure):
    _fields_ = [('flags', C.c_long), ('input', C.c_int), ('initial_state', C.c_int),
               ('icon_pixmap', C.c_ulong), ('icon_window', C.c_ulong), ('icon_x', C.c_int),
               ('icon_y', C.c_int), ('icon_mask', C.c_ulong), ('window_group', C.c_ulong)]


class SetAttributes(C.Structure):
    _fields_ = [('background_pixmap', C.c_ulong), ('background_pixel', C.c_ulong),
                ('border_pixmap', C.c_ulong), ('border_pixel', C.c_ulong),
                ('bit_gravity', C.c_int), ('win_gravity', C.c_int), ('backing_store', C.c_int),
                ('backing_planes', C.c_ulong), ('backing_pixel', C.c_ulong), ('save_under', C.c_int),
                ('event_mask', C.c_long), ('do_not_propagate_mask', C.c_long), ('override_redirect', C.c_int),
                ('colormap', C.c_ulong), ('cursor', C.c_ulong)]


class X11:
    def __init__(self):
        library = ctypes.util.find_library('X11')
        extension = ctypes.util.find_library('Xext')
        if not library or not extension:
            raise ValueError('X11 and XShape libraries are required for this overlay')
        self.x, self.ext = C.CDLL(library), C.CDLL(extension)
        ptr, ulong, integer = C.c_void_p, C.c_ulong, C.c_int
        methods = {
            'XOpenDisplay': (ptr, [C.c_char_p]), 'XCloseDisplay': (integer, [ptr]),
            'XDefaultRootWindow': (ulong, [ptr]), 'XDefaultScreen': (integer, [ptr]),
            'XDefaultDepth': (integer, [ptr, integer]),
            'XDisplayWidth': (integer, [ptr, integer]), 'XDisplayHeight': (integer, [ptr, integer]),
            'XInternAtom': (ulong, [ptr, C.c_char_p, integer]),
            'XCreateSimpleWindow': (ulong, [ptr, ulong, integer, integer, C.c_uint, C.c_uint, C.c_uint, ulong, ulong]),
            'XChangeProperty': (integer, [ptr, ulong, ulong, ulong, integer, integer, ptr, integer]),
            'XGetWindowProperty': (integer, [ptr, ulong, ulong, C.c_long, C.c_long, integer, ulong,
                                           C.POINTER(ulong), C.POINTER(integer), C.POINTER(ulong), C.POINTER(ulong), C.POINTER(ptr)]),
            'XQueryTree': (integer, [ptr, ulong, C.POINTER(ulong), C.POINTER(ulong), C.POINTER(C.POINTER(ulong)), C.POINTER(C.c_uint)]),
            'XGetWindowAttributes': (integer, [ptr, ulong, C.POINTER(Attributes)]),
            'XSetWMHints': (integer, [ptr, ulong, C.POINTER(Hints)]),
            'XChangeWindowAttributes': (integer, [ptr, ulong, ulong, C.POINTER(SetAttributes)]),
            'XStoreName': (integer, [ptr, ulong, C.c_char_p]),
            'XMapRaised': (integer, [ptr, ulong]), 'XUnmapWindow': (integer, [ptr, ulong]),
            'XDestroyWindow': (integer, [ptr, ulong]), 'XSync': (integer, [ptr, integer]),
            'XCreateGC': (ptr, [ptr, ulong, ulong, ptr]), 'XFreeGC': (integer, [ptr, ptr]),
            'XSetForeground': (integer, [ptr, ptr, ulong]),
            'XClearWindow': (integer, [ptr, ulong]),
            'XDrawString': (integer, [ptr, ulong, ptr, integer, integer, C.c_char_p, integer]),
            'XMoveResizeWindow': (integer, [ptr, ulong, integer, integer, C.c_uint, C.c_uint]),
            'XFree': (integer, [ptr]),
        }
        for name, (result, args) in methods.items():
            function = getattr(self.x, name)
            function.restype, function.argtypes = result, args
        callback = C.CFUNCTYPE(integer, ptr, ptr)
        self.errors = 0
        def error(_display, _event):
            self.errors += 1
            return 0
        self.error_handler = callback(error)
        self.x.XSetErrorHandler.restype = ptr
        self.x.XSetErrorHandler.argtypes = [callback]
        self.x.XSetErrorHandler(self.error_handler)
        self.ext.XShapeQueryExtension.restype = integer
        self.ext.XShapeQueryExtension.argtypes = [ptr, C.POINTER(integer), C.POINTER(integer)]
        self.ext.XShapeQueryVersion.restype = integer
        self.ext.XShapeQueryVersion.argtypes = [ptr, C.POINTER(integer), C.POINTER(integer)]
        self.ext.XShapeGetRectangles.restype = ptr
        self.ext.XShapeGetRectangles.argtypes = [ptr, ulong, integer, C.POINTER(integer), C.POINTER(integer)]
        self.ext.XShapeCombineRectangles.restype = None
        self.ext.XShapeCombineRectangles.argtypes = [ptr, ulong, integer, integer, integer, ptr, integer, integer, integer]
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise ValueError('No authorized X11 display connection. Use a supported X11 session.')
        self.root = self.x.XDefaultRootWindow(self.display)
        self.screen = self.x.XDefaultScreen(self.display)
        event, error_code = integer(), integer()
        if not self.ext.XShapeQueryExtension(self.display, C.byref(event), C.byref(error_code)):
            self.close()
            raise ValueError('XShape input transparency is unavailable; overlay refused')
        major, minor = integer(), integer()
        if not self.ext.XShapeQueryVersion(self.display, C.byref(major), C.byref(minor)) or (major.value, minor.value) < (1, 1):
            self.close()
            raise ValueError('XShape 1.1 input transparency is required')

    def atom(self, name):
        return self.x.XInternAtom(self.display, name.encode(), 0)

    def property(self, window, name):
        actual, fmt, count, remaining, data = C.c_ulong(), C.c_int(), C.c_ulong(), C.c_ulong(), C.c_void_p()
        self.x.XGetWindowProperty(self.display, window, self.atom(name), 0, 32, 0, 0,
                                  C.byref(actual), C.byref(fmt), C.byref(count), C.byref(remaining), C.byref(data))
        try:
            if fmt.value == 32 and count.value and data.value:
                return C.cast(data, C.POINTER(C.c_ulong))[0]
            return None
        finally:
            if data.value:
                self.x.XFree(data)

    def set_cardinal(self, window, name, value):
        data = C.c_ulong(value)
        self.x.XChangeProperty(self.display, window, self.atom(name), self.atom('CARDINAL'), 32, 0, C.byref(data), 1)

    def foreign_overlay(self, own=0):
        root, parent, children, count = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)(), C.c_uint()
        if not self.x.XQueryTree(self.display, self.root, C.byref(root), C.byref(parent), C.byref(children), C.byref(count)):
            raise ValueError('Cannot inspect the overlay surface')
        try:
            if count.value > 4096:
                raise ValueError('Too many display windows to verify overlay ownership')
            for i in range(count.value):
                window = children[i]
                if window == own:
                    continue
                if self.property(window, 'GAMESCOPE_EXTERNAL_OVERLAY'):
                    attrs = Attributes()
                    if self.x.XGetWindowAttributes(self.display, window, C.byref(attrs)) and attrs.map_state != 0:
                        return True
            return False
        finally:
            if children:
                self.x.XFree(children)

    def close(self):
        if self.display:
            self.x.XCloseDisplay(self.display)
            self.display = None


def plain(value, length=68):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))[:length]


def run(directory, nonce):
    import fcntl
    directory = Path(directory)
    parent = directory.parent
    for path in (directory, parent):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Overlay IPC directory must be owned by this user and private')
    fd = os.open(parent / 'overlay.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            write_private(directory / 'ack.json', dict(nonce=nonce, state='conflict', label='Another HelixSR monitor owns this display', responding=False))
            return 2
        return render(directory, nonce)


def render(directory, nonce):
    x = X11()
    window, gc = 0, None
    try:
        pid = x.property(x.root, 'GAMESCOPE_PID')
        gamescope = False
        if pid:
            try:
                gamescope = 'gamescope' in (Path('/proc') / str(pid) / 'comm').read_text().lower()
            except OSError:
                pass
            if not gamescope or x.property(x.root, 'GAMESCOPE_FOCUSED_APP') is None:
                raise ValueError('Gamescope root display could not be verified')
        elif os.environ.get('XDG_SESSION_TYPE') != 'x11':
            raise ValueError('Continuous HUD unavailable on this session. Runtime status is still available in the app.')
        if x.x.XDefaultDepth(x.display, x.screen) < 24:
            raise ValueError('Overlay requires a 24-bit X11 display')
        window = x.x.XCreateSimpleWindow(x.display, x.root, 16, 16, 440, 110, 0, 0, 0x172331)
        if not gamescope:
            # Bypass desktop decorations/reparenting, which would otherwise add
            # an input-catching WM frame around the input-transparent client.
            attrs = SetAttributes(override_redirect=1)
            x.x.XChangeWindowAttributes(x.display, window, 1 << 9, C.byref(attrs))
        x.x.XStoreName(x.display, window, b'HelixSR status (experimental)')
        hints = Hints(flags=1, input=0)
        x.x.XSetWMHints(x.display, window, C.byref(hints))
        # Empty input shape before mapping: mouse/touch clicks pass through.
        x.ext.XShapeCombineRectangles(x.display, window, 2, 0, 0, None, 0, 0, 0)
        count, ordering = C.c_int(), C.c_int()
        rectangles = x.ext.XShapeGetRectangles(x.display, window, 2, C.byref(count), C.byref(ordering))
        if rectangles:
            x.x.XFree(rectangles)
        x.x.XSync(x.display, 0)
        if x.errors or count.value:
            raise ValueError('Input transparency could not be confirmed; HUD refused')
        states = (C.c_ulong * 3)(*[x.atom(n) for n in ('_NET_WM_STATE_ABOVE', '_NET_WM_STATE_SKIP_TASKBAR', '_NET_WM_STATE_SKIP_PAGER')])
        x.x.XChangeProperty(x.display, window, x.atom('_NET_WM_STATE'), x.atom('ATOM'), 32, 0, states, 3)
        if gamescope:
            x.set_cardinal(window, 'GAMESCOPE_EXTERNAL_OVERLAY', 1)
        gc = x.x.XCreateGC(x.display, window, 0, None)
        mapped = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                data = read_private(directory / 'frame.json')
            except FileNotFoundError:
                time.sleep(0.1)
                continue
            if data.get('schema') != 1 or data.get('nonce') != nonce:
                raise ValueError('Overlay status session mismatch')
            if data.get('stop'):
                return 0
            expires = data.get('expires_at', 0)
            if not isinstance(expires, (int, float)) or expires < time.monotonic():
                raise ValueError('Status feed expired; overlay stopped')
            deadline = min(expires + 2, time.monotonic() + 10)
            conflict = x.foreign_overlay(window)
            if conflict and mapped:
                x.x.XUnmapWindow(x.display, window)
                mapped = False
            elif not conflict and not mapped:
                x.x.XMapRaised(x.display, window)
                mapped = True
            width = min(440, x.x.XDisplayWidth(x.display, x.screen) - 32)
            if width < 240 or x.x.XDisplayHeight(x.display, x.screen) < 160:
                raise ValueError('Display is too small for the status overlay')
            x.x.XMoveResizeWindow(x.display, window, 16, 16, width, 110)
            x.x.XClearWindow(x.display, window)
            x.x.XSetForeground(x.display, gc, 0x8ee8bc if data.get('state') == 'output' else 0xf1ca7e)
            lines = ['HelixSR | ' + plain(data.get('game_name'), 40), plain(data.get('label'), 62),
                     'Version ' + plain(data.get('version'), 15) + ' | ' + plain(data.get('model'), 30),
                     'Session log evidence | image quality unverified']
            for i, line in enumerate(lines):
                encoded = plain(line, max(20, (width - 24) // 6)).encode('ascii')
                x.x.XDrawString(x.display, window, gc, 12, 22 + i * 22, encoded, len(encoded))
            x.x.XSync(x.display, 0)
            if x.errors:
                raise ValueError('X11 rejected an overlay operation; HUD closed')
            attrs = Attributes()
            mapped = bool(mapped and x.x.XGetWindowAttributes(x.display, window, C.byref(attrs)) and attrs.map_state == 2)
            write_private(directory / 'ack.json', dict(nonce=nonce, sequence=data.get('sequence'), observed_at=time.monotonic(),
                state='conflict' if conflict else 'responding', responding=mapped and not conflict,
                label='HUD unavailable: another overlay is using its surface' if conflict else 'Overlay helper responding',
                detail='Other overlays were left unchanged.' if conflict else 'Window mapped and draw acknowledged; visibility unverified.',
                visible_verified=False, provider='gamescope-experimental' if gamescope else 'x11-desktop'))
            time.sleep(0.4)
        raise ValueError('Status feed stopped; overlay closed')
    finally:
        if gc:
            x.x.XFreeGC(x.display, gc)
        if window:
            x.x.XDestroyWindow(x.display, window)
        x.close()


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if len(args) != 2:
        return 2
    directory, nonce = Path(args[0]), args[1]
    try:
        return run(directory, nonce)
    except Exception as exc:
        try:
            write_private(directory / 'ack.json', dict(nonce=nonce, state='unavailable', responding=False,
                label='Overlay unavailable', detail=str(exc)[:200], observed_at=time.monotonic(), visible_verified=False))
        except Exception:
            pass
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
