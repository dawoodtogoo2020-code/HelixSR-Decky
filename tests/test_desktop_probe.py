import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import probe


class ProbeTests(unittest.TestCase):
    def test_real_detail_fields_and_private_home_redaction(self):
        class Service:
            home = Path('/home/private-person')
            closed = False
            def __init__(self, *_): pass
            def library(self):
                return {'games': [{'id': 'one', 'name': 'Game', 'managed': True}]}
            def details(self, *_):
                return {'installed_version': '1.7.0', 'package_version': '1.7.0'}
            def system_status(self):
                return {'vulkan': {'evidence': 'raw GPU output', 'error': '/home/private-person/layer.so'}}
            def close(self): Service.closed = True
        with tempfile.TemporaryDirectory() as folder, patch.object(probe, 'DesktopBackend', Service):
            output = Path(folder) / 'report.json'
            self.assertEqual(probe.main(['--probe', '--output', str(output)]), 0)
            value = json.loads(output.read_text())
        self.assertEqual(value['games'][0]['installed_version'], '1.7.0')
        self.assertEqual(value['games'][0]['package_version'], '1.7.0')
        self.assertNotIn('evidence', value['system']['vulkan'])
        self.assertEqual(value['system']['vulkan']['error'], '<user-home>/layer.so')
        self.assertTrue(Service.closed)
