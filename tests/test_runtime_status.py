"""Runtime evidence must be attributable to a new, identified game session."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import runtime_status


READY = 'model-e: network running (nchw8, 19 launches per frame)\n'
DISPATCH = 'dispatch 1: render 640x400 -> 1280x800\n'
SUCCESS = READY + DISPATCH


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / 'helixsr.log'
        self.module = self.root / 'amd_fidelityfx_dx12.dll'
        self.game = dict(folder=str(self.root), target=str(self.root), targets=[str(self.module)],
                         main_exe=str(self.root / 'game.exe'), route='direct', managed=True,
                         enabled=True, name='Test game', appid='42')
        self.proc = dict(pid=123, started_at=100)
        self.session = (123, '1000')
        self.processes = [self.proc]
        self.mapped = True
        self.patches = [
            patch.object(runtime_status, 'active_processes', side_effect=lambda *_: self.processes),
            patch.object(runtime_status, 'executable_session', side_effect=lambda *_: self.session),
            patch.object(runtime_status, 'mapped_paths', side_effect=lambda *_: self.mapped),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.evidence = runtime_status.RuntimeEvidence(self.game)

    def append(self, content):
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(content)

    def test_initial_log_and_mtime_touch_do_not_claim_output(self):
        self.log.write_text(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        os.utime(self.log, None)
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.append('unrelated activity\n')
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.append(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'output')

    def test_ready_event_is_not_output_and_ordered_failure_can_recover(self):
        self.log.touch()
        self.evidence.sample()
        self.append('network running (model e)\n')
        self.assertEqual(self.evidence.sample()['state'], 'loaded')
        self.append(SUCCESS + 'network failed\n')
        self.assertEqual(self.evidence.sample()['state'], 'failure')
        self.append(DISPATCH)
        self.assertEqual(self.evidence.sample()['state'], 'failure')
        self.append(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'output')

    def test_partial_line_and_overflow_never_promote_old_fragment(self):
        self.log.touch()
        self.evidence.sample()
        self.append(READY)
        self.evidence.sample()
        self.append(DISPATCH.rstrip('\n'))
        self.assertEqual(self.evidence.sample()['state'], 'loaded')
        self.append('\n')
        self.assertEqual(self.evidence.sample()['state'], 'output')
        self.append('x' * (runtime_status.LIMIT + 1))
        self.assertEqual(self.evidence.sample()['state'], 'unavailable')
        self.assertNotEqual(self.evidence.sample()['state'], 'output')

    def test_truncation_rotation_restart_exit_and_disabled_clear_output(self):
        self.log.touch()
        self.evidence.sample()
        self.append(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'output')
        self.log.write_text('')
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.append(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'output')
        self.log.rename(self.root / 'helixsr.previous.log')
        self.log.write_text(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.session = (123, '2000')
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.processes = []
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        self.evidence.game['enabled'] = False
        self.assertEqual(self.evidence.sample()['state'], 'disabled')

    def test_symlink_or_unidentified_session_never_promotes_output(self):
        self.log.touch()
        self.evidence.sample()
        with patch.object(runtime_status, 'regular_beneath', side_effect=ValueError('symbolic link')):
            self.assertEqual(self.evidence.sample()['state'], 'unavailable')
        self.session = None
        self.assertEqual(self.evidence.sample()['state'], 'unverified')

    def test_unmapped_module_and_unknown_executable_cannot_claim_output(self):
        self.log.touch()
        self.evidence.sample()
        self.append(SUCCESS)
        self.mapped = False
        self.assertEqual(self.evidence.sample()['state'], 'unverified')

    def test_dispatch_alone_and_placeholder_error_never_claim_neural_output(self):
        self.log.touch()
        self.evidence.sample()
        self.append(DISPATCH)
        self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.append(READY + 'model-e: HelixSR ERROR: 10 network shaders unavailable; using the placeholder upscale with a RED FRAME\n' + DISPATCH)
        self.assertEqual(self.evidence.sample()['state'], 'failure')

    def test_truncate_and_regrow_between_samples_resets_continuity(self):
        self.log.write_text('prior baseline\n')
        self.evidence.sample()
        self.append(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'output')
        self.log.write_text('replacement bytes\n' * 20 + SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_prelaunch_new_log_requires_exact_game_writer(self):
        self.processes = []
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        self.log.write_text(SUCCESS)
        with patch.object(runtime_status, 'writing_log', return_value=False):
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.log.unlink()
        self.processes = []
        self.evidence.sample()
        self.processes = [self.proc]
        self.log.write_text(SUCCESS)
        with patch.object(runtime_status, 'writing_log', return_value=True):
            self.assertEqual(self.evidence.sample()['state'], 'output')
        self.mapped = True
        self.session = None
        self.assertEqual(self.evidence.sample()['state'], 'unverified')

    def test_armed_existing_log_rewrite_captures_fresh_startup_once(self):
        for previous in ('historical line\n' * 20 + SUCCESS, 'old\n'):
            with self.subTest(previous_size=len(previous)):
                evidence = runtime_status.RuntimeEvidence(self.game)
                self.processes = []
                self.log.write_text(previous)
                self.assertEqual(evidence.sample()['state'], 'not_running')
                self.processes = [self.proc]
                self.mapped = False
                self.assertEqual(evidence.sample()['state'], 'unverified')
                self.log.write_text(SUCCESS)
                self.mapped = True
                with patch.object(runtime_status, 'writing_log', return_value=True):
                    self.assertEqual(evidence.sample()['state'], 'output')
                    self.assertEqual(evidence.sample()['state'], 'output')

    def test_armed_existing_log_needs_changed_bytes_and_exact_writer(self):
        self.processes = []
        self.log.write_text(SUCCESS)
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        os.utime(self.log, None)
        with patch.object(runtime_status, 'writing_log', return_value=True):
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
        self.processes = []
        self.evidence.sample()
        self.processes = [self.proc]
        self.log.write_text('old baseline\n')
        with patch.object(runtime_status, 'writing_log', return_value=False):
            self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_later_rotation_cannot_replay_log_after_first_inspection(self):
        self.processes = []
        self.log.write_text('historical line\n')
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        with patch.object(runtime_status, 'writing_log', return_value=True):
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            self.log.rename(self.root / 'helixsr.previous.log')
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_oversized_startup_rewrite_is_unavailable(self):
        self.processes = []
        self.log.write_text('historical line\n')
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        self.log.write_text('x' * runtime_status.LIMIT + SUCCESS)
        with patch.object(runtime_status, 'writing_log', return_value=True):
            self.assertEqual(self.evidence.sample()['state'], 'unavailable')
            self.assertNotEqual(self.evidence.sample()['state'], 'output')

    def test_helper_only_process_does_not_disarm_prelaunch_baseline(self):
        self.processes = []
        self.log.write_text('historical line\n')
        with patch.object(runtime_status, 'executable_session',
                          side_effect=lambda proc, *_: None if proc['pid'] == 900 else self.session), \
                patch.object(runtime_status, 'writing_log', return_value=True):
            self.assertEqual(self.evidence.sample()['state'], 'not_running')
            self.processes = [dict(pid=900, started_at=90)]
            self.assertEqual(self.evidence.sample()['state'], 'unverified')
            self.processes = [dict(pid=900, started_at=90), self.proc]
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'output')

    def test_delayed_game_writer_can_rewrite_unchanged_armed_log(self):
        clock = [100.0]
        self.processes = []
        self.log.write_text('historical line\n')
        with patch.object(runtime_status.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(runtime_status, 'writing_log', side_effect=lambda *_: clock[0] >= 103):
            self.assertEqual(self.evidence.sample()['state'], 'not_running')
            self.processes = [self.proc]
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 103.1
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'output')

    def test_startup_session_recheck_failure_cannot_parse_append(self):
        self.processes = []
        self.log.write_text('historical line\n')
        self.assertEqual(self.evidence.sample()['state'], 'not_running')
        self.processes = [self.proc]
        with patch.object(runtime_status, 'writing_log', return_value=False):
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            self.append(SUCCESS)
            with patch.object(runtime_status, 'executable_session',
                              side_effect=[self.session, (123, '1001')]):
                self.assertEqual(self.evidence.sample()['state'], 'unavailable')
            self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_startup_grace_expires_without_replaying_late_rewrite(self):
        clock = [100.0]
        self.processes = []
        self.log.write_text('historical line\n')
        with patch.object(runtime_status.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(runtime_status, 'writing_log', side_effect=lambda *_: clock[0] >= 116):
            self.assertEqual(self.evidence.sample()['state'], 'not_running')
            self.processes = [self.proc]
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 114.9
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 116.0
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_module_remap_does_not_extend_first_mapping_deadline(self):
        clock = [100.0]
        self.processes = []
        self.log.write_text('historical line\n')
        with patch.object(runtime_status.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(runtime_status, 'writing_log', side_effect=lambda *_: clock[0] >= 116):
            self.assertEqual(self.evidence.sample()['state'], 'not_running')
            self.processes = [self.proc]
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            self.mapped = False
            clock[0] = 110.0
            self.assertEqual(self.evidence.sample()['state'], 'unverified')
            self.mapped = True
            clock[0] = 114.0
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 116.0
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'mapped')

    def test_changed_bytes_without_game_writer_consumes_startup_token(self):
        clock = [100.0]
        self.processes = []
        self.log.write_text('historical line\n')
        with patch.object(runtime_status.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(runtime_status, 'writing_log', side_effect=lambda *_: clock[0] >= 103):
            self.assertEqual(self.evidence.sample()['state'], 'not_running')
            self.processes = [self.proc]
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 102.0
            self.log.write_text(SUCCESS)
            self.assertEqual(self.evidence.sample()['state'], 'mapped')
            clock[0] = 103.0
            self.assertEqual(self.evidence.sample()['state'], 'mapped')


class ExecutableSessionTests(unittest.TestCase):
    """Proton wrapper arguments must not impersonate the running game."""

    def session(self, argv, expected=r'S:\games\PRAGMATA.exe', *, started_at=100,
                stat_present=True, changed_start=False):
        cmdline = b'\0'.join(arg.encode() for arg in argv) + b'\0'
        stat = '123 (process name with spaces) ' + ' '.join(['0'] * 19 + ['9001'])
        changed_stat = '123 (process name with spaces) ' + ' '.join(['0'] * 19 + ['9002'])
        stat_reads = 0

        def read_bytes(path):
            self.assertEqual(path.name, 'cmdline')
            return cmdline

        def read_text(path):
            nonlocal stat_reads
            self.assertEqual(path.name, 'stat')
            if not stat_present:
                raise FileNotFoundError(path)
            stat_reads += 1
            return changed_stat if changed_start and stat_reads > 1 else stat

        with patch.object(Path, 'read_bytes', autospec=True, side_effect=read_bytes), \
                patch.object(Path, 'read_text', autospec=True, side_effect=read_text), \
                patch.object(Path, 'stat', autospec=True,
                             return_value=SimpleNamespace(st_uid=getattr(os, 'getuid', lambda: 0)())):
            return runtime_status.executable_session(
                dict(pid=123, started_at=started_at), expected)

    def test_windows_game_argv_zero_is_attributed_to_its_session(self):
        for expected, command in (
            (r'S:\games\PRAGMATA.exe', r'S:\games\PRAGMATA.exe'),
            (r'Z:\steamapps\common\PRAGMATA.exe', r'Z:\steamapps\common\PRAGMATA.exe'),
            (r'Z:\steamapps\common\PRAGMATA.exe', r'S:\games\PRAGMATA.exe'),
            ('/games/Pragmata.EXE', '/games/PRAGMATA.exe'),
        ):
            with self.subTest(expected=expected, command=command):
                self.assertEqual(self.session([command, '-dx12'], expected), (123, '9001'))

    def test_wrapper_or_steam_argv_zero_cannot_borrow_later_game_argument(self):
        for wrapper in ('reaper', 'srt-bwrap', 'pv-adverb', 'python3', 'steam.exe'):
            with self.subTest(wrapper=wrapper):
                self.assertIsNone(self.session([wrapper, r'S:\games\PRAGMATA.exe']))

    def test_other_executable_and_missing_process_identity_are_unverified(self):
        self.assertIsNone(self.session([r'S:\games\OTHER.exe',
                                        r'S:\games\PRAGMATA.exe']))
        self.assertIsNone(self.session([r'S:\games\PRAGMATA.exe'], started_at=0))
        self.assertIsNone(self.session([r'S:\games\PRAGMATA.exe'], stat_present=False))
        self.assertIsNone(self.session([r'S:\games\PRAGMATA.exe'], changed_start=True))
        self.assertIsNone(self.session([], expected=r'S:\games\PRAGMATA.exe'))

    def test_other_user_proc_cannot_be_attributed(self):
        with patch.object(runtime_status.os, 'getuid', create=True, return_value=1000), \
                patch.object(Path, 'stat', autospec=True,
                             return_value=SimpleNamespace(st_uid=1001)), \
                patch.object(Path, 'read_bytes', autospec=True,
                             side_effect=AssertionError('foreign cmdline must not be read')):
            self.assertIsNone(runtime_status.executable_session(
                dict(pid=123, started_at=100), r'S:\games\PRAGMATA.exe'))


from test_backend import Fixtures


class ManagedRuntimeAssessmentTests(Fixtures):
    def test_real_managed_optiscaler_assessment_supplies_actual_provider_paths(self):
        import test_backend
        test_backend.RecoveryAndOptiScalerRegressionTests.optiscaler_fixture(self)
        self.action('install')
        game = self.m.assess_safe(self.game)
        self.assertTrue(game['managed'])
        self.assertEqual(game['route'], 'optiscaler')
        evidence = runtime_status.RuntimeEvidence(game)
        providers = [p for p in evidence.modules if p.parent.name == 'HelixSR']
        self.assertEqual({p.name for p in providers}, {'helixsr.dll', 'helixsr_upscaler.dll'})
        self.assertTrue(all(p.is_file() for p in providers))
        self.assertTrue(game['main_exe'])


if __name__ == '__main__':
    unittest.main()
