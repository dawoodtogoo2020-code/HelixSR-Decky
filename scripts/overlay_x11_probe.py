"""Exercise the isolated HUD on an X11 test display, for example xvfb-run.

This checks X11 mapping, pixels, input shape and conflict handling. It cannot
establish that Gamescope selected the window or that a player saw its pixels.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
from overlay_helper import Attributes, X11, read_private, write_private  # noqa: E402


class DisplayProbe(X11):
    def __init__(self):
        super().__init__()
        ptr, ulong, integer = C.c_void_p, C.c_ulong, C.c_int
        self.x.XFetchName.restype = integer
        self.x.XFetchName.argtypes = [ptr, ulong, C.POINTER(C.c_char_p)]
        self.x.XGetInputFocus.restype = integer
        self.x.XGetInputFocus.argtypes = [ptr, C.POINTER(ulong), C.POINTER(integer)]
        self.x.XGetImage.restype = ptr
        self.x.XGetImage.argtypes = [ptr, ulong, integer, integer, C.c_uint, C.c_uint, ulong, integer]
        self.x.XGetPixel.restype = ulong
        self.x.XGetPixel.argtypes = [ptr, integer, integer]
        self.x.XDestroyImage.restype = integer
        self.x.XDestroyImage.argtypes = [ptr]
        self.ext.XShapeGetRectangles.restype = ptr
        self.ext.XShapeGetRectangles.argtypes = [ptr, ulong, integer, C.POINTER(integer), C.POINTER(integer)]

    def children(self):
        root, parent, children = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)()
        count = C.c_uint()
        if not self.x.XQueryTree(self.display, self.root, C.byref(root), C.byref(parent),
                                 C.byref(children), C.byref(count)):
            raise AssertionError('XQueryTree failed')
        try:
            return [children[i] for i in range(count.value)]
        finally:
            if children:
                self.x.XFree(children)

    def name(self, window):
        value = C.c_char_p()
        if not self.x.XFetchName(self.display, window, C.byref(value)) or not value.value:
            return ''
        try:
            return value.value.decode('utf-8', 'replace')
        finally:
            self.x.XFree(C.cast(value, C.c_void_p))

    def hud(self):
        self.x.XSync(self.display, 0)
        matches = [window for window in self.children() if self.name(window) == 'HelixSR status (experimental)']
        if len(matches) > 1:
            raise AssertionError('More than one helper window exists')
        return matches[0] if matches else None

    def attributes(self, window):
        attrs = Attributes()
        if not self.x.XGetWindowAttributes(self.display, window, C.byref(attrs)):
            raise AssertionError('XGetWindowAttributes failed')
        return attrs

    def focus(self):
        window, revert = C.c_ulong(), C.c_int()
        self.x.XGetInputFocus(self.display, C.byref(window), C.byref(revert))
        return window.value, revert.value

    def input_rectangles(self, window):
        count, ordering = C.c_int(), C.c_int()
        rectangles = self.ext.XShapeGetRectangles(self.display, window, 2,
                                                  C.byref(count), C.byref(ordering))
        if rectangles:
            self.x.XFree(rectangles)
        return count.value

    def drawn_colors(self, window):
        attrs = self.attributes(window)
        image = self.x.XGetImage(self.display, window, 0, 0, attrs.width, attrs.height,
                                 C.c_ulong(-1).value, 2)
        if not image:
            raise AssertionError('XGetImage failed for the mapped helper window')
        try:
            colors = set()
            for y in range(10, min(attrs.height, 100), 2):
                for x in range(10, min(attrs.width, 430), 2):
                    colors.add(self.x.XGetPixel(image, x, y))
                    if len(colors) >= 2:
                        return len(colors)
            return len(colors)
        finally:
            self.x.XDestroyImage(image)


def until(predicate, seconds=5, label='condition'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f'Timed out waiting for {label}')


class HelperSession:
    def __init__(self, parent, child_executable=None):
        self.temp = tempfile.TemporaryDirectory(prefix='session-', dir=parent)
        self.directory = Path(self.temp.name)
        self.nonce = uuid.uuid4().hex
        self.sequence = 0
        self.process = None
        self.child_executable = child_executable

    def frame(self, *, expires_in=8, stop=False):
        self.sequence += 1
        write_private(self.directory / 'frame.json', dict(schema=1, nonce=self.nonce,
            sequence=self.sequence, expires_at=time.monotonic() + expires_in,
            game_name='X11 probe game', state='unverified', label='Probe runtime evidence',
            version='probe', model='probe', stop=stop))
        return self.sequence

    def start(self):
        self.frame()
        command = ([self.child_executable, '--appimage-extract-and-run', '--status-overlay-child',
                    str(self.directory), self.nonce] if self.child_executable else
                   [sys.executable, str(ROOT / 'py_modules' / 'overlay_helper.py'),
                    str(self.directory), self.nonce])
        env = dict(os.environ, XDG_SESSION_TYPE='x11')
        self.process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def ack(self, state=None, sequence=None):
        def current():
            try:
                value = read_private(self.directory / 'ack.json')
            except FileNotFoundError:
                return None
            if value.get('nonce') != self.nonce:
                raise AssertionError('Acknowledgement nonce mismatch')
            if (state is None or value.get('state') == state) and (sequence is None or value.get('sequence') == sequence):
                return value
            if self.process.poll() is not None:
                raise AssertionError(f'Helper exited before {state or "acknowledgement"}: {value}')
            return None
        return until(current, label=f'{state or "helper"} acknowledgement')

    def exited(self):
        until(lambda: self.process.poll() is not None, label='helper exit')
        return self.process.returncode

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process.communicate(timeout=2)
        self.temp.cleanup()


def run(child_executable=None):
    if sys.platform != 'linux' or not os.environ.get('DISPLAY'):
        raise RuntimeError('Run this probe on Linux with an authorized X11 DISPLAY, such as xvfb-run')
    with tempfile.TemporaryDirectory(prefix='helixsr-overlay-probe-') as parent:
        x = DisplayProbe()
        foreign = None
        try:
            # A successful heartbeat must correspond to the current nonce and sequence.
            session = HelperSession(parent, child_executable)
            try:
                baseline_focus = x.focus()
                session.start()
                ack = session.ack('responding', session.sequence)
                assert ack.get('responding') is True and ack.get('visible_verified') is False, ack
                window = until(lambda: x.hud(), label='helper window')
                assert x.attributes(window).map_state == 2, 'Helper did not map its window'
                assert x.attributes(window).override_redirect, 'Desktop helper can receive a WM frame'
                assert x.input_rectangles(window) == 0, 'Helper window accepts input'
                assert x.focus() == baseline_focus, 'Helper changed input focus'
                assert x.drawn_colors(window) >= 2, 'No drawn text pixels found'
                next_sequence = session.frame()
                session.ack('responding', next_sequence)
                session.frame(stop=True)
                assert session.exited() == 0, 'Stop frame did not close cleanly'
                until(lambda: x.hud() is None, label='window destruction after disable')
            finally:
                session.close()

            # Expiring the feed must remove the window even if no controller sends stop.
            session = HelperSession(parent, child_executable)
            try:
                session.start()
                session.ack('responding', session.sequence)
                session.frame(expires_in=0.6)
                assert session.exited() != 0, 'Expired feed left helper running'
                until(lambda: x.hud() is None, label='window destruction after expiry')
            finally:
                session.close()

            # A dead child must also lose its X window without requiring a frame.
            session = HelperSession(parent, child_executable)
            try:
                session.start()
                session.ack('responding', session.sequence)
                session.process.terminate()
                session.exited()
                until(lambda: x.hud() is None, label='window destruction after process outage')
            finally:
                session.close()

            # A foreign mapped external overlay owns the surface. Keep it intact.
            foreign = x.x.XCreateSimpleWindow(x.display, x.root, 4, 4, 100, 40, 0, 0, 0x445566)
            x.set_cardinal(foreign, 'GAMESCOPE_EXTERNAL_OVERLAY', 1)
            x.x.XMapRaised(x.display, foreign)
            x.x.XSync(x.display, 0)
            foreign_focus = x.focus()
            session = HelperSession(parent, child_executable)
            try:
                session.start()
                ack = session.ack('conflict', session.sequence)
                assert ack.get('responding') is False, ack
                window = until(lambda: x.hud(), label='unmapped helper window')
                assert x.attributes(window).map_state != 2, 'Helper mapped over foreign overlay'
                assert x.attributes(foreign).map_state == 2, 'Foreign overlay was unmapped'
                assert x.property(foreign, 'GAMESCOPE_EXTERNAL_OVERLAY') == 1, 'Foreign overlay property changed'
                assert x.focus() == foreign_focus, 'Conflict handling changed focus'
                x.x.XUnmapWindow(x.display, foreign)
                x.x.XSync(x.display, 0)
                session.ack('responding', session.sequence)
                assert x.attributes(window).map_state == 2, 'Helper did not map after conflict cleared'
                x.x.XMapRaised(x.display, foreign)
                x.x.XSync(x.display, 0)
                session.ack('conflict', session.sequence)
                assert x.attributes(window).map_state != 2, 'Helper did not yield to new foreign overlay'
                assert x.attributes(foreign).map_state == 2, 'Foreign overlay changed while yielding'
            finally:
                session.close()
            return dict(result='passed', provider='x11-test-display',
                        checks=['mapped and drew pixels', 'nonce and sequence acknowledged',
                                'empty XShape input region', 'focus unchanged', 'stop', 'expiry',
                                'process outage', 'foreign overlay conflict and yield'],
                        visibility_verified=False)
        finally:
            if foreign:
                x.x.XDestroyWindow(x.display, foreign)
            x.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-executable', type=Path,
                        help='Frozen AppImage executable to run with --appimage-extract-and-run --status-overlay-child')
    args = parser.parse_args()
    try:
        print(json.dumps(run(str(args.child_executable) if args.child_executable else None)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(result='failed', error=str(exc), visibility_verified=False)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
