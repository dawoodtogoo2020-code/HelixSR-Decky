import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from operation_lock import operation_lock
from manager import Manager


def hold(path, pipe):
    with operation_lock(path):
        pipe.send('locked')
        pipe.recv()


class OperationLocks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_second_process_rejected_and_release_reusable(self):
        ctx = multiprocessing.get_context('spawn')
        parent, child = ctx.Pipe()
        process = ctx.Process(target=hold, args=(str(self.root), child))
        process.start()
        try:
            self.assertTrue(parent.poll(15), 'lock holder did not start')
            self.assertEqual(parent.recv(), 'locked')
            with self.assertRaisesRegex(ValueError, 'Another HelixSR manager'):
                with operation_lock(self.root):
                    self.fail('overlapping writer acquired lock')
            parent.send('release')
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            with operation_lock(self.root):
                self.assertTrue((self.root / '.operation.lock').is_file())
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)
            parent.close()
            child.close()

    def test_nested_lock_keeps_other_thread_out_and_exception_releases(self):
        failures = []
        def contender():
            try:
                with operation_lock(self.root):
                    failures.append('acquired')
            except ValueError:
                failures.append('blocked')
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with operation_lock(self.root):
                with operation_lock(self.root):
                    pass
                thread = threading.Thread(target=contender)
                thread.start(); thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, ['blocked'])
                raise RuntimeError('fixture')
        with operation_lock(self.root):
            pass

    @unittest.skipUnless(os.name == 'posix', 'Linux symlink safety')
    def test_symlink_lock_and_companion_rejected(self):
        target = self.root / 'target'
        target.write_text('do not alter')
        (self.root / '.operation.lock').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            with operation_lock(self.root):
                pass
        self.assertEqual(target.read_text(), 'do not alter')
        link = self.root / 'redirect'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            with operation_lock(link):
                pass

    def test_cancel_process_exit_race_does_not_break_shutdown(self):
        manager = Manager(self.root, self.root / 'settings')
        manager.jobs['job'] = {'state': 'running'}
        manager.process = Mock(pid=42)
        manager.process.poll.return_value = None
        with patch('os.killpg', side_effect=ProcessLookupError, create=True):
            self.assertTrue(manager.cancel_job('job'))
        self.assertTrue(manager.cancel.is_set())
