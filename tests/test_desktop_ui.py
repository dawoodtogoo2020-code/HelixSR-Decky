"""Widget-level safety tests; no game manager, filesystem writes, or network access."""
import importlib.util
import os
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
QT = importlib.util.find_spec('PySide6') is not None
if QT:
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
    from desktop.app import MainWindow, PreviewDialog, LIMIT, open_external_url


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.game = dict(id='a', name='Game A', folder='/fixture/a', source='Steam',
                         compatibility='candidate', managed=False, enabled=False,
                         route='optiscaler', dx12_confirmation_needed=False,
                         optiscaler=dict(present=True, helix_configured=False, runtime='unknown'),
                         framegen_summary='Configured, runtime unknown', helix_runtime='unknown')
        self.job_list = []
        self.closed = False

    def library(self):
        return dict(games=[self.game.copy(), dict(id='b', name='Blocked', compatibility='blocked', reasons=['Protected game'])],
                    release=dict(version='v1'), jobs=self.job_list)

    def details(self, gid):
        self.calls.append(('details', gid))
        return self.game.copy()

    def check_app_updates(self, force=True):
        self.calls.append(('app_check', force))
        return dict(current='0.1.0', latest='0.2.0', update_available=True, auto_check=True)

    def preview_latest(self, gid, dx12_confirmed=False):
        self.calls.append(('preview', gid, dx12_confirmed))
        return dict(token='token', action='latest', name='Game A', route='optiscaler', files=['dxgi.dll'], warning='Close the game')

    def accept_license(self, accepted):
        self.calls.append(('license', accepted))

    def preview_action(self, gid, action, dx12_confirmed=False):
        self.calls.append(('preview_action', action))
        return dict(token='cleanup-token', action=action, name='Game A', files=['dxgi.dll'])

    def apply_action(self, token):
        self.calls.append(('apply', token))
        return dict(message='Original files restored')

    def install_latest(self, token):
        self.calls.append(('install', token))
        job = dict(id='job', game='Game A', state='running', message='Preparing', log='')
        self.job_list = [job]
        return job

    def jobs(self):
        return self.job_list

    def cancel_job(self, jid):
        self.calls.append(('cancel', jid))
        return True

    def import_launcher(self, source):
        self.calls.append(('import', source))
        return self.library()

    def system_status(self):
        return {'platform': 'fixture', 'vulkan': {'available': None}}

    def close(self):
        self.closed = True
        self.calls.append(('close',))
        return True


@unittest.skipUnless(QT, 'PySide6 Essentials unavailable; native widget tests require Qt')
class DesktopWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.backend = FakeBackend()
        self.window = MainWindow(self.backend, auto_load=False)
        self.window.show()
        self.window._library_received(self.backend.library())
        self.settle()

    def settle(self, timeout=3):
        deadline = time.monotonic() + timeout
        quiet = 0
        while time.monotonic() < deadline:
            self.app.processEvents()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            if not self.window._task:
                quiet += 1
                if quiet > 20:
                    return
            else:
                quiet = 0
            time.sleep(.002)
        self.fail('Native UI worker did not settle')

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog):
                widget.reject()
        self.window.close()
        self.settle()
        self.window.deleteLater()
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_selection_is_read_only_and_button_immediately_available(self):
        self.assertEqual(self.window.games.count(), 1)
        self.assertIn('Not installed', self.window.games.currentText())
        self.assertTrue(self.window.install.isEnabled())
        self.assertEqual(self.window.unavailable.count(), 1)
        self.assertIn('Protected game', self.window.unavailable.item(0).text())
        self.assertFalse(any(c[0] in ('install', 'preview', 'license') for c in self.backend.calls))
        self.assertIn('OptiScaler installed: yes', self.window.evidence.toPlainText())
        self.assertIn('OptiScaler runtime: unknown', self.window.evidence.toPlainText())
        self.assertIn('Frame generation:', self.window.evidence.toPlainText())

    def test_launch_guidance_matches_detected_route_and_preserves_options(self):
        self.window.game['launch_options'] = 'CUSTOM=1 %command%'
        for route in ('direct', 'optiscaler', None):
            self.window.game['route'] = route
            self.window.copy_launch()
            copied = self.app.clipboard().text()
            self.assertIn('CUSTOM=1 %command%', copied)
            if route == 'direct':
                self.assertIn('Select AMD FSR', copied)
                self.assertNotIn('dxgi=n,b', copied)
            elif route == 'optiscaler':
                self.assertIn('dxgi=n,b', copied)
            else:
                self.assertIn('No supported installation route', copied)
                self.assertNotIn('dxgi=n,b', copied)

    def test_desktop_help_uses_desktop_guide(self):
        from desktop.app import GUIDE
        self.assertTrue(GUIDE.endswith('/DESKTOP_GUIDE.md'))

    def test_many_library_warnings_keep_notice_short_and_diagnostics_intact(self):
        self.window._library_loaded = False
        warnings = [f'Steam shortcut {i}: launcher/wrapper unresolved; import game folder /fixture/game-{i}' for i in range(83)]
        value = self.backend.library()
        value['warnings'] = warnings
        self.window._library_received(value)
        self.settle()
        self.assertEqual(self.window.notice.text(), '83 library warnings. See Diagnostics.')
        self.assertLess(len(self.window.notice.text()), 100)
        self.assertNotIn('\n', self.window.notice.text())
        self.assertEqual(self.window.library_warning_view.toPlainText(), '\n\n'.join(warnings))
        self.assertTrue(self.window.library_warning_view.isReadOnly())
        self.assertLessEqual(self.window.library_warning_view.maximumHeight(), 180)
        self.window.diagnostic_button.click()
        self.settle()
        self.assertIn('fixture', self.window.diagnostics.toPlainText())
        self.assertEqual(self.window.library_warning_view.toPlainText(), '\n\n'.join(warnings))

    def test_library_refresh_preserves_operation_result_notification(self):
        self.window._notify('HelixSR enabled')
        value = self.backend.library()
        value['warnings'] = ['Unresolved unrelated shortcut']
        self.window._library_received(value)
        self.settle()
        self.assertEqual(self.window.notice.text(), 'HelixSR enabled')
        self.assertIn('Unresolved unrelated shortcut', self.window.library_warning_view.toPlainText())

    def test_cached_network_errors_do_not_hide_successful_local_actions(self):
        self.window._notify('Disable completed and file hashes verified')
        value = self.backend.library()
        value['release']['error'] = 'Cached Helix metadata network error'
        self.backend.check_app_updates = lambda force=True: dict(current='0.1.1', latest=None,
            auto_check=True, error='Cached desktop network error')
        self.window._library_received(value)
        self.settle()
        self.window.check_app(False)
        self.settle()
        self.assertEqual(self.window.notice.text(), 'Disable completed and file hashes verified')
        self.assertIn('Cached Helix', self.window.helix_status.text())
        self.assertIn('Cached desktop', self.window.app_status.text())
        self.window.check_app(True)
        self.settle()
        self.assertIn('Cached desktop network error', self.window.notice.text())

    def test_dx12_confirmation_required_only_when_needed(self):
        self.backend.game['dx12_confirmation_needed'] = True
        self.window._details_received('a', self.backend.game)
        self.assertFalse(self.window.dx12.isHidden())
        self.assertFalse(self.window.install.isEnabled())
        self.window.dx12.setChecked(True)
        self.assertTrue(self.window.install.isEnabled())
        self.backend.game['dx12_confirmation_needed'] = False
        self.window._details_received('a', self.backend.game)
        self.assertTrue(self.window.dx12.isHidden())

    def test_preview_cancel_never_mutates_game(self):
        def reject():
            dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, PreviewDialog))
            self.assertFalse(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
            self.assertTrue(self.window._modal)
            self.assertFalse(self.window.install.isEnabled())
            self.assertFalse(self.window._run(lambda: None, lambda _: None))
            dialog.reject()
        QTimer.singleShot(80, reject)
        self.window.install.click()
        self.settle()
        self.assertTrue(any(c[0] == 'preview' for c in self.backend.calls))
        self.assertFalse(any(c[0] in ('license', 'install') for c in self.backend.calls))

    def test_confirmation_acknowledges_license_before_job(self):
        def accept():
            dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, PreviewDialog))
            dialog.ack.setChecked(True)
            dialog.buttons.button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(80, accept)
        self.window.install.click()
        self.settle()
        calls = [c[0] for c in self.backend.calls]
        self.assertLess(calls.index('license'), calls.index('install'))
        self.assertFalse(self.window.install.isEnabled())
        self.assertTrue(self.window.cancel_button.isEnabled())
        self.window.cancel_button.click()
        self.settle()
        self.assertIn(('cancel', 'job'), self.backend.calls)

    def test_async_guard_responsive_and_exceptions_visible(self):
        completed = []
        self.assertTrue(self.window._run(lambda: time.sleep(.08), lambda _: completed.append(True)))
        self.assertFalse(self.window._run(lambda: None, lambda _: None))
        self.assertFalse(self.window.games.isEnabled())
        heartbeat = []
        QTimer.singleShot(10, lambda: heartbeat.append(True))
        self.settle()
        self.assertTrue(heartbeat)
        self.assertTrue(completed)
        def fail():
            raise ValueError('Fixture failure')
        self.window._run(fail, lambda _: None)
        self.settle()
        self.assertIn('Fixture failure', self.window.notice.text())

    def test_cleanup_does_not_require_license_or_network(self):
        def unavailable_license(accepted):
            raise RuntimeError('Offline license lookup must not occur for cleanup')
        self.backend.accept_license = unavailable_license
        self.window.game['managed'] = True
        self.window._controls()
        def accept():
            dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, PreviewDialog))
            dialog.ack.setChecked(True)
            dialog.buttons.button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(80, accept)
        self.window.actions['remove'].click()
        self.settle()
        self.assertIn(('apply', 'cleanup-token'), self.backend.calls)
        self.assertFalse(any(c[0] == 'license' for c in self.backend.calls))

    def test_updates_separate_and_launcher_sources(self):
        from py_modules.library import LAUNCHER_SOURCES
        self.assertIn('v1', self.window.helix_status.text())
        self.assertIn('0.2.0', self.window.app_status.text())
        self.assertTrue(self.window.app_download.isEnabled())
        self.assertEqual({self.window.launchers.itemData(i) for i in range(self.window.launchers.count())},
                         set(LAUNCHER_SOURCES))
        self.window.launchers.setCurrentIndex(self.window.launchers.findData('heroic'))
        self.window.import_button.click()
        self.settle()
        self.assertIn(('import', 'heroic'), self.backend.calls)

    def test_logs_bounded_and_polling_does_not_open_dialog(self):
        self.backend.job_list = [dict(id='job', state='running', game='A', log='x' * 100000)]
        self.window._jobs_received(self.backend.job_list)
        self.window.poll_jobs()
        self.settle()
        self.assertLessEqual(len(self.window.job_view.toPlainText()), LIMIT)
        self.assertFalse(self.window._modal)
        self.assertFalse(any(isinstance(w, PreviewDialog) for w in QApplication.topLevelWidgets()))

    def test_newest_job_and_completion_are_visible_before_previous_logs(self):
        jobs = [dict(id='old', state='cancelled', game='Old', message='Cancelled', log='x' * 100000),
                dict(id='new', state='done', game='New', message='HelixSR enabled', log='Latest verified files')]
        self.window._jobs_received(jobs)
        self.assertTrue(self.window.job_view.toPlainText().startswith('New: done\nHelixSR enabled'))
        self.assertIn('Latest verified files', self.window.job_view.toPlainText())
        self.assertLessEqual(len(self.window.job_view.toPlainText()), LIMIT)
        self.assertIn('New: done', self.window.notice.text())

    def test_launch_guidance_preserves_existing_options(self):
        self.window.game['launch_options'] = 'MANGOHUD=1 %command% -flag'
        self.window.copy_launch()
        self.assertIn('MANGOHUD=1 %command% -flag', QApplication.clipboard().text())
        self.assertIn('Preserve', QApplication.clipboard().text())
        self.assertFalse(any(c[0] == 'install' for c in self.backend.calls))

    def test_close_waits_for_worker_then_backend(self):
        self.window._run(lambda: time.sleep(.05), lambda _: None)
        self.window.close()
        self.assertFalse(self.backend.closed)
        self.assertFalse(self.window._closed)
        self.settle()
        self.assertTrue(self.backend.closed)
        self.assertTrue(self.window._closed)

    def test_forget_only_unmanaged_manual_imports(self):
        for source, managed, enabled in [('Steam', False, False), ('Heroic', False, False),
                                         ('Imported', True, False), ('Imported', False, True)]:
            self.window.game.update(source=source, managed=managed)
            self.window._controls()
            self.assertEqual(self.window.forget.isEnabled(), enabled)

    def test_repeated_close_does_not_overlap_retry_worker(self):
        counts = {'calls': 0, 'active': 0, 'max_active': 0}
        def bounded_close():
            counts['calls'] += 1
            counts['active'] += 1
            counts['max_active'] = max(counts['max_active'], counts['active'])
            time.sleep(.04)
            counts['active'] -= 1
            return counts['calls'] >= 2
        self.backend.close = bounded_close
        self.window.close()
        self.settle()
        self.assertFalse(self.window._closed)
        for _ in range(5):
            self.window.close()
        self.app.processEvents()
        self.assertEqual(counts['calls'], 1)
        deadline = time.monotonic() + 3
        while not self.window._closed and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(self.window._closed)
        self.assertEqual(counts['calls'], 2)
        self.assertEqual(counts['max_active'], 1)

    def test_external_links_use_sanitized_host_tools(self):
        clean = {'PATH': '/usr/bin'}
        with mock.patch('desktop.app.sys.platform', 'linux'), mock.patch('desktop.app.system_environment', return_value=clean), \
             mock.patch('desktop.app.shutil.which', return_value='/usr/bin/xdg-open'), mock.patch('desktop.app.subprocess.Popen') as launch:
            open_external_url('https://github.com/example/issues')
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/xdg-open', 'https://github.com/example/issues'])
            self.assertIs(launch.call_args.kwargs['env'], clean)
        with mock.patch('desktop.app.sys.platform', 'win32'), \
             mock.patch('desktop.app.system_environment', return_value={'WINDIR': 'D:/Windows'}), \
             mock.patch('desktop.app.subprocess.CREATE_NO_WINDOW', 0, create=True), \
             mock.patch('desktop.app.subprocess.Popen') as launch:
            open_external_url('https://github.com/example/issues')
            self.assertTrue(launch.call_args.args[0][0].endswith('explorer.exe'))
        for bad in ('file:///tmp/a', 'javascript:alert(1)', 'https://user:pass@example.com', 'https://example.com/\ncmd'):
            with self.assertRaises(ValueError):
                open_external_url(bad)
        with mock.patch('desktop.app.sys.platform', 'linux'), mock.patch('desktop.app.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'xdg-open is unavailable'):
                open_external_url('https://github.com/example/issues')

    def test_signal_cancels_preview_and_closes_without_installing(self):
        QTimer.singleShot(80, self.window.receive_shutdown_signal)
        self.window.install.click()
        deadline = time.monotonic() + 2
        while not self.window._closed and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(self.window._closed)
        self.assertFalse(any(c[0] in ('license', 'install') for c in self.backend.calls))

    def test_signal_during_preview_worker_discards_stale_result(self):
        original = self.backend.preview_latest
        def delayed_preview(*args):
            time.sleep(.2)
            return original(*args)
        self.backend.preview_latest = delayed_preview
        self.window.install.click()
        QTimer.singleShot(20, self.window.receive_shutdown_signal)
        deadline = time.monotonic() + 2
        while not self.window._closed and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(self.window._closed)
        self.assertFalse(self.window._modal)
        self.assertFalse(any(c[0] in ('license', 'install') for c in self.backend.calls))


if __name__ == '__main__':
    unittest.main()
