"""End-to-end file transactions. Set HELIXSR_VERIFIED_ZIP for the actual SDK runtime."""
import hashlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from test_backend import Fixtures, pe
import manager
import hlx_fsr_release as hlx


class LifecycleTests(Fixtures):
    def archive_transport(self):
        path = os.environ.get('HELIXSR_VERIFIED_ZIP')
        if path:
            path = Path(path)
            self.assertEqual(path.stat().st_size, hlx.RELEASE_SIZE)
            return patch('manager.urllib.request.urlopen', side_effect=lambda req, **k: path.open('rb'))
        payload = {name: name.encode() for name in hlx.PINS}
        payload[hlx.OUTPUT_DLL] = payload['helixsr-scaler/OptiScaler/amd_fidelityfx_upscaler_dx12.dll'] = pe(ffx=True, helix=True)
        payload[hlx.SCALER_INI] = b'[Upscalers]\nDx12Upscaler=auto\n[FSR]\nUpscalerIndex=auto\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n[FrameGen]\nEnabled=false\nFGInput=auto\nFGOutput=auto\nFGNvngxReplacement=auto\n'
        wire = io.BytesIO()
        with zipfile.ZipFile(wire, 'w') as archive:
            for name, data in payload.items():
                archive.writestr('HelixSR-3.2.0/' + name, data)
        wire = wire.getvalue()
        pins = {name: (len(b), hashlib.sha256(b).hexdigest()) for name, b in payload.items()}
        self.enterContext(patch.multiple(hlx, PINS=pins, RELEASE_SHA256=hashlib.sha256(wire).hexdigest(),
                         RELEASE_SIZE=len(wire), OUTPUT_SHA256=pins[hlx.OUTPUT_DLL][1]))
        return patch('manager.urllib.request.urlopen', side_effect=lambda req, **k: io.BytesIO(wire))

    def install(self):
        with self.archive_transport():
            review = self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice='reviewed-3.2.0')
            self.assertFalse(review['license_accepted'])
            self.m.accept_license(True, review['token'])
            job = self.m.execute_latest(review['token'])
            self.m.worker.join(180)
            job = self.m.jobs[job['id']]
            self.assertEqual(job['state'], 'completed', job['message'])
        rec = self.m.record(self.game)
        self.assertEqual(rec['variant']['id'], hlx.VARIANT_ID)
        self.assertEqual(rec['release_sha256'], hlx.RELEASE_SHA256)
        self.assertFalse(self.m.cfg['packages'])
        self.assertFalse((self.m.companion(self.game) / 'records/package.json').exists())
        self.assertEqual(len(self.m.cfg['variant_packages_v1']), 1)
        return rec

    def act(self, action):
        review = self.m.preview(self.game['id'], action)
        self.m.execute(review['token'])

    def test_direct_repair_disable_enable_remove_round_trip(self):
        fg = self.root / 'amd_fidelityfx_framegeneration_dx12.dll'
        fg.write_bytes(b'Game frame generation')
        rec = self.install()
        fallback = self.native.with_name('amd_fidelityfx_upscaler_dx12.amd.dll')
        self.assertEqual(fallback.read_bytes(), self.original)
        self.assertEqual(manager.sha(self.native), hlx.OUTPUT_SHA256)
        self.native.unlink()
        self.act('repair')
        self.assertEqual(manager.sha(self.native), hlx.OUTPUT_SHA256)
        self.act('disable')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(fallback.exists())
        self.act('enable')
        self.assertEqual(manager.sha(self.native), hlx.OUTPUT_SHA256)
        self.assertEqual(rec['package_selection'], self.m.record(self.game)['package_selection'])
        self.act('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(fg.read_bytes(), b'Game frame generation')
        self.assertFalse(fallback.exists())
        self.assertFalse(self.m.record(self.game))

    def test_scaler_native_selection_survives_disable_and_is_distinct_from_fg(self):
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        self.install()
        original = self.m.game_settings(self.game)
        self.assertEqual(original['upscaler'], 'hlx-fsr')
        self.m.set_game_settings(self.game['id'], {'upscaler': 'fsr'}, original['revision'])
        switched = self.m.game_settings(self.game)
        self.assertEqual((switched['upscaler'], switched['provider']), ('fsr', original['provider']))
        self.act('disable')
        self.act('enable')
        self.assertEqual(self.m.game_settings(self.game)['upscaler'], 'fsr')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.act('remove')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertFalse((self.root / 'OptiScaler.ini').exists())

    def test_reject_conflicts_incompatible_models_and_changed_archive_before_game_writes(self):
        review = lambda: self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice='reviewed-3.2.0')
        with self.assertRaisesRegex(ValueError, 'requires'):
            self.m.preview_latest(self.game['id'], release_choice='reviewed-3.2.0')
        fallback = self.native.with_name('amd_fidelityfx_upscaler_dx12.amd.dll')
        fallback.write_bytes(b'unmanaged')
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            review()
        self.assertEqual(fallback.read_bytes(), b'unmanaged')
        fallback.unlink()
        token = review()['token']
        self.m.accept_license(True, token)
        with patch('manager.urllib.request.urlopen', return_value=io.BytesIO(b'replaced zip')):
            job = self.m.execute_latest(token)
            self.m.worker.join(10)
        self.assertEqual(self.m.jobs[job['id']]['state'], 'failed')
        self.assertIn('size mismatch', self.m.jobs[job['id']]['message'])
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))
        self.assertFalse(self.m.cfg.get('variant_packages_v1'))
