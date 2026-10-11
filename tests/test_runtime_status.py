"""Runtime evidence must be attributable to a new, identified game session."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
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
