"""Review choices remain available when upstream advances or is offline."""
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import compatibility_release as releases
from test_backend import Fixtures


class ReleaseChoiceTests(Fixtures):
    def test_recommended_release_is_first_and_older_choices_are_explicit(self):
        choices = releases.release_choices()
        self.assertEqual(choices[0]['id'], releases.RECOMMENDED_CHOICE)
        self.assertEqual(choices[0]['version'], '2.0.0')
        self.assertTrue(choices[0]['recommended'])
        self.assertEqual(sum(bool(choice['recommended']) for choice in choices), 1)
        self.assertTrue(all('older release' in choice['label'] for choice in choices[1:3]))
        self.assertEqual(choices[-1]['id'], 'latest')

    def test_reviewed_choices_do_not_need_network(self):
        with patch.object(self.m, 'check_update', side_effect=AssertionError('Network used')):
            for choice in releases.REVIEWED_CHOICES:
                release = self.m.release_for_choice(choice)
                self.assertTrue(releases.release_status(release)['supported'])
                self.assertEqual(release['version'], choice.split('-', 1)[1])

    def test_future_release_does_not_hide_reviewed_releases(self):
        result = releases.release_status({'version': '2.1.0'})
        self.assertFalse(result['supported'])
        self.assertIn('plugin update', result['support_reason'])
        self.assertIn('reviewed-2.0.0', [c['id'] for c in releases.release_choices()])
        self.assertIn('reviewed-1.9.3', [c['id'] for c in releases.release_choices()])

    def test_same_version_replaced_archive_stays_blocked(self):
        release = releases.reviewed_release('reviewed-2.0.0')
        release['sha256'] = '0' * 64
        self.assertFalse(releases.release_status(release)['supported'])

    def test_pinned_modern_downgrade_is_rejected_before_preview(self):
        data = dict(managed=True, legacy=False, installed_version='2.0.0')
        with patch.object(self.m, 'assess', return_value=data):
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                self.m.preview_latest(self.game['id'], release_choice='reviewed-1.9.3')
        self.assertEqual(self.m.previews, {})

    def test_status_keeps_errors_and_does_not_mutate_cache(self):
        release = releases.reviewed_release('reviewed-2.0.0')
        release['error'] = 'Network unavailable'
        result = releases.release_status(release)
        self.assertFalse(result['supported'])
        self.assertEqual(result['error'], 'Network unavailable')
        self.assertNotIn('supported', release)


if __name__ == '__main__':
    unittest.main()
