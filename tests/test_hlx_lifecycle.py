"""End-to-end file transactions for each reviewed HLX release.

Set HELIXSR_VERIFIED_ZIP (3.2.0) or HELIXSR_VERIFIED_ZIP_330 (3.3.0) to run against the actual archive.
"""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from test_backend import Fixtures, pe, write
import manager
import hlx_fsr_release as hlx
import model_variants
import test_helix20_install

ZIP_ENV = {'3.2.0': 'HELIXSR_VERIFIED_ZIP', '3.3.0': 'HELIXSR_VERIFIED_ZIP_330'}
TEMPLATE = b'[Upscalers]\nDx12Upscaler=auto\n[FSR]\nUpscalerIndex=auto\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n[FrameGen]\nEnabled=false\nFGInput=auto\nFGOutput=auto\nFGNvngxReplacement=auto\n'


class LifecycleTests(Fixtures):
    R = hlx.V320
    CHOICE = 'reviewed-3.2.0'

    def wire(self, release):
        """The actual archive when provided, otherwise a fixture with the release's exact member names."""
        path = os.environ.get(ZIP_ENV[release.MODERN_VERSION])
        if path:
            self.assertEqual(Path(path).stat().st_size, release.RELEASE_SIZE)
            return Path(path).read_bytes()
        payload = {name: name.encode() for name in release.PINS}
        payload[hlx.OUTPUT_DLL] = payload['helixsr-scaler/OptiScaler/amd_fidelityfx_upscaler_dx12.dll'] = pe(ffx=True, helix=True)
        payload[hlx.SCALER_INI] = TEMPLATE
        wire = io.BytesIO()
        with zipfile.ZipFile(wire, 'w') as archive:
            for name, data in payload.items():
                archive.writestr(f'HelixSR-{release.MODERN_VERSION}/' + name, data)
        wire = wire.getvalue()
        pins = {name: (len(b), hashlib.sha256(b).hexdigest()) for name, b in payload.items()}
        self.enterContext(patch.multiple(release, PINS=pins, RELEASE_SHA256=hashlib.sha256(wire).hexdigest(),
                          RELEASE_SIZE=len(wire), OUTPUT_SHA256=pins[hlx.OUTPUT_DLL][1]))
        return wire

    def archive_transport(self, *releases):
        wires = {release.RELEASE_URL: self.wire(release) for release in (releases or (self.R,))}
        return patch('manager.urllib.request.urlopen', side_effect=lambda req, **k: io.BytesIO(wires[req.full_url]))

    def install(self, release=None, choice=None, transport=True):
        release, choice = release or self.R, choice or self.CHOICE
        with (self.archive_transport(release) if transport else contextlib.nullcontext()):
            review = self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=choice)
            self.m.accept_license(True, review['token'])
            job = self.m.execute_latest(review['token'])
            self.m.worker.join(180)
            job = self.m.jobs[job['id']]
            self.assertEqual(job['state'], 'completed', job['message'])
        rec = self.m.record(self.game)
        self.assertEqual(rec['variant']['id'], hlx.VARIANT_ID)
        self.assertEqual((rec['version'], rec['release_sha256']), (release.MODERN_VERSION, release.RELEASE_SHA256))
        self.assertFalse(self.m.cfg['packages'])
        self.assertFalse((self.m.companion(self.game) / 'records/package.json').exists())
        return rec

    def act(self, action):
        review = self.m.preview(self.game['id'], action)
        self.m.execute(review['token'])

    def test_direct_repair_disable_enable_remove_round_trip(self):
        fg = self.root / 'amd_fidelityfx_framegeneration_dx12.dll'
        fg.write_bytes(b'Game frame generation')
        rec = self.install()
        self.assertEqual(len(self.m.cfg['variant_packages_v1']), 1)
        fallback = self.native.with_name('amd_fidelityfx_upscaler_dx12.amd.dll')
        self.assertEqual(fallback.read_bytes(), self.original)
        self.assertEqual(manager.sha(self.native), self.R.OUTPUT_SHA256)
        self.native.unlink()
        self.act('repair')
        self.assertEqual(manager.sha(self.native), self.R.OUTPUT_SHA256)
        self.act('disable')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(fallback.exists())
        self.act('enable')
        self.assertEqual(manager.sha(self.native), self.R.OUTPUT_SHA256)
        self.assertEqual(rec['package_selection'], self.m.record(self.game)['package_selection'])
        self.act('remove')
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertEqual(fg.read_bytes(), b'Game frame generation')
        self.assertFalse(fallback.exists())
        self.assertFalse(self.m.record(self.game))

    def test_direct_reset_after_game_update_preserves_new_dll(self):
        self.game['build'] = '100'
        self.install()
        self.game['build'] = '101'
        updated = pe(ffx=True) + b'new native game build'
        self.native.write_bytes(updated)
        review = self.m.preview(self.game['id'], 'reset')
        self.assertIn('amd_fidelityfx_upscaler_dx12.amd.dll', review['files'])
        self.m.execute(review['token'])
        self.assertEqual(self.native.read_bytes(), updated)
        self.assertFalse(self.m.record(self.game))
        self.assertFalse(self.native.with_name('amd_fidelityfx_upscaler_dx12.amd.dll').exists())
        review = self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=self.CHOICE)
        self.assertIn('cannot prove the DLL is stock', review['warning'])

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
        review = lambda: self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=self.CHOICE)
        with self.assertRaisesRegex(ValueError, 'needs the reviewed HelixSR 3.3.0'):
            self.m.preview_latest(self.game['id'], release_choice=self.CHOICE)
        fallback = self.native.with_name('amd_fidelityfx_upscaler_dx12.amd.dll')
        fallback.write_bytes(b'unmanaged')
        with self.assertRaisesRegex(ValueError, '(?i)unmanaged'):
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
        self.assertIn('Update HelixSR Decky', self.m.jobs[job['id']]['message'])
        self.assertEqual(self.native.read_bytes(), self.original)
        self.assertFalse(self.m.record(self.game))
        self.assertFalse(self.m.cfg.get('variant_packages_v1'))


class Lifecycle330Tests(LifecycleTests):
    """The same transactions with HelixSR 3.3.0, plus its Scaler-only HLX FSR 4 Full."""
    R = hlx.V330
    CHOICE = 'reviewed-3.3.0'
    FULL = 'OptiScaler/custom/HLX FSR 4 Full/ffx/amd_fidelityfx_upscaler_dx12.dll'

    def test_scaler_full_upscaler_is_installed_selectable_and_survives_disable(self):
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        self.install()
        full = self.root / self.FULL
        self.assertEqual(manager.sha(full), self.R.PINS[hlx.FULL_DIR + 'amd_fidelityfx_upscaler_dx12.dll'][1])
        self.assertTrue((full.parent / 'hlx_fsr4.ini').is_file())
        state = self.m.game_settings(self.game)
        self.assertEqual((state['upscaler'], state['full_available'], state['release']), ('hlx-fsr', True, '3.3.0'))
        self.m.set_game_settings(self.game['id'], {'upscaler': 'hlx-fsr-full'}, state['revision'])
        self.assertIn('Dx12Upscaler=HLX FSR 4 Full', (self.root / 'OptiScaler.ini').read_text())
        self.assertEqual(self.m.game_settings(self.game)['upscaler'], 'hlx-fsr-full')
        self.act('disable')
        self.assertFalse(full.exists())
        self.act('enable')
        self.assertTrue(full.exists())
        self.assertEqual(self.m.game_settings(self.game)['upscaler'], 'hlx-fsr-full')
        self.act('remove')
        self.assertEqual([f for f in (self.root / 'OptiScaler').rglob('*') if not f.is_dir()], [],
                         'Remove deletes every added file (existing behavior keeps empty folders)')
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_rdr2_scaler_installs_the_reviewed_optiscaler_as_winmm(self):
        """Deck Wizard's Red Dead Redemption 2 setup: OptiScaler as winmm.dll, no file copied in by hand."""
        self.game.update(source='Steam', appid='1174180', name='Red Dead Redemption 2')
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        self.install()
        winmm = self.root / 'winmm.dll'
        self.assertEqual(manager.sha(winmm), self.R.PINS[hlx.SCALER_DIR + 'OptiScaler.dll'][1])
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertEqual(self.m.record(self.game)['proxy'], 'winmm.dll')
        data = self.m.assess(self.game)
        setup = data['optiscaler']['setup']
        self.assertEqual(setup['missing'], [])
        self.assertTrue(any(check.startswith('winmm launch override: missing') for check in setup['checks']), setup['checks'])
        self.game['launch_options'] = 'WINEDLLOVERRIDES="winmm=n,b" SteamDeck=0 %command%'
        self.assertEqual(self.m.assess(self.game)['optiscaler']['setup']['override'], 'correct')
        winmm.unlink()
        self.assertEqual(self.m.assess(self.game)['repair_files'], ['winmm.dll'])
        self.act('repair')
        self.assertEqual(manager.sha(winmm), self.R.PINS[hlx.SCALER_DIR + 'OptiScaler.dll'][1])
        self.act('disable')
        self.assertFalse(winmm.exists())
        self.act('enable')
        self.assertTrue(winmm.exists())
        self.act('remove')
        self.assertFalse(winmm.exists())
        self.assertFalse((self.root / 'dxgi.dll').exists())
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_direct_install_uses_the_330_runtime_without_full(self):
        self.install()
        self.assertEqual(manager.sha(self.native), self.R.OUTPUT_SHA256)
        self.assertFalse((self.root / 'OptiScaler').exists(), 'Full is a Scaler upscaler only')

    def test_scaler_upgrade_from_320_keeps_settings_and_adds_full(self):
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        with self.archive_transport(hlx.V320, hlx.V330):
            self.install(hlx.V320, 'reviewed-3.2.0', transport=False)
            before = self.m.game_settings(self.game)
            self.assertFalse(before['full_available'])
            self.m.set_game_settings(self.game['id'], {'upscaler': 'fsr', 'overlay': 'upscaler'}, before['revision'])
            self.install(hlx.V330, 'reviewed-3.3.0', transport=False)
        after = self.m.game_settings(self.game)
        self.assertEqual((after['upscaler'], after['overlay'], after['full_available']), ('fsr', 'upscaler', True))
        self.assertTrue((self.root / self.FULL).is_file())
        self.assertEqual(manager.sha(self.root / 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'), hlx.V330.OUTPUT_SHA256)
        self.act('remove')
        self.assertEqual([f for f in (self.root / 'OptiScaler').rglob('*') if not f.is_dir()], [],
                         'Remove deletes every added file (existing behavior keeps empty folders)')
        self.assertEqual(self.native.read_bytes(), self.original)

    def run_hlx_job(self):
        """Press Install or Update with HLX FSR 4 and HelixSR 3.3.0 selected; return the finished job."""
        with self.archive_transport():
            review = self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=self.CHOICE)
            self.m.accept_license(True, review['token'])
            job = self.m.execute_latest(review['token'])
            self.m.worker.join(180)
        return self.m.jobs[job['id']]

    def test_model_e_scaler_game_switches_to_hlx_then_removes_and_reinstalls(self):
        """DeckWiz's FINAL FANTASY VII REBIRTH report: Model E on Scaler, Update with HLX FSR 4, Remove, Install."""
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        test_helix20_install.Helix20InstallTests.modern20_package(self)
        self.enterContext(patch.object(test_helix20_install.helix20_release, 'verify_outputs', return_value=None))
        self.act('install')
        self.assertEqual(self.m.assess(self.game)['installed_variant'], 'helixsr-model-e')
        model_e_only = test_helix20_install.helix20_release.OUTPUT_DLL
        self.assertTrue((self.root / model_e_only).is_file())
        state = self.m.game_settings(self.game)
        # HelixSR 3.3.0 has no HelixSR FG: the review names the setting to change instead of failing later.
        with self.assertRaisesRegex(ValueError, 'Select Off, FSR or XeSS FG'):
            self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=self.CHOICE)
        self.m.set_game_settings(self.game['id'], {'provider': 'off'}, state['revision'])

        job = self.run_hlx_job()
        self.assertEqual(job['state'], 'completed', job['message'])
        data = self.m.assess(self.game)
        self.assertEqual((data['installed_variant'], data['installed_version']), (hlx.VARIANT_ID, '3.3.0'))
        self.assertEqual(data['installed_model'], 'HLX FSR 4 (FSR 4.1.2 Lite)')
        self.assertFalse((self.root / model_e_only).exists(), 'Model E files are retired by the update')
        expected = {dest for _, dest in self.R.scaler_pairs()} | {'OptiScaler.ini', 'HelixSR/helixsr-install.json',
                                                                  'nvngx_dlss.dll', 'Example.exe'}
        self.assertEqual({p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()}, expected)
        self.assertEqual(self.m.game_settings(self.game)['upscaler'], 'hlx-fsr')

        self.act('remove')
        self.assertEqual({p.name for p in self.root.rglob('*') if p.is_file()}, {'nvngx_dlss.dll', 'Example.exe'})
        self.assertFalse(self.m.record(self.game))
        job = self.run_hlx_job()
        self.assertEqual(job['state'], 'completed', job['message'])
        data = self.m.assess(self.game)
        self.assertEqual((data['installed_variant'], data['installed_version']), (hlx.VARIANT_ID, '3.3.0'))
        self.assertEqual(manager.sha(self.root / 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll'), self.R.OUTPUT_SHA256)

    def test_install_from_replaced_20261111_build_stays_recognized_and_updates(self):
        """0.1.44 installed 3.3.0's 2026-11-11 build; upstream replaced it in place on 2026-11-12."""
        rec = self.install()
        old_recipe = next(iter(hlx.V330.REPLACED_RECIPES))
        rec['variant'] = dict(rec['variant'], recipe_sha256=old_recipe)
        rec['release_sha256'] = '4d87481061db0f499112041b38da5aebfc86e7f9ca3c7b1894258f20452d9045'
        manager.atomic_json(self.m.record_path(self.game), rec)
        self.m.cfg['variant_packages_v1'].clear()
        self.assertTrue(model_variants.valid_variant(rec['variant']))
        data = self.m.assess(self.game)
        self.assertEqual((data['installed_variant'], data['installed_model']), (hlx.VARIANT_ID, 'HLX FSR 4 (FSR 4.1.2 Lite)'))
        job = self.run_hlx_job()
        self.assertEqual(job['state'], 'completed', job['message'])
        updated = self.m.record(self.game)
        self.assertEqual((updated['variant']['recipe_sha256'], updated['release_sha256']),
                         (self.R.RECIPE_SHA256, self.R.RELEASE_SHA256))

    def test_combined_fsr_dll_game_is_sent_to_scaler_with_a_plain_reason(self):
        """DeckWiz's God of War Ragnarök report: only AMD's combined FSR 3.1 DLL, plus DLSS."""
        self.native.unlink()
        combined = write(self.root / manager.DLL, pe(ffx=True))
        write(self.root / 'nvngx_dlss.dll', pe())
        data = self.m.assess(self.game)
        self.assertEqual((data['route'], data['hlx_direct_supported']), ('direct', False))
        self.assertIn('Switch this game to the Scaler route', data['hlx_scaler_reason'])
        self.assertIn(manager.DLL, data['hlx_scaler_reason'])
        with self.assertRaisesRegex(ValueError, 'cannot replace this game.s FSR file directly'):
            self.m.preview_latest(self.game['id'], variant_id=hlx.VARIANT_ID, release_choice=self.CHOICE)
        self.m.set_installation_route(self.game['id'], 'optiscaler')
        data = self.m.assess(self.game)
        self.assertEqual((data['route'], data['hlx_direct_supported'], data['hlx_scaler_reason']), ('optiscaler', None, None))
        job = self.run_hlx_job()
        self.assertEqual(job['state'], 'completed', job['message'])
        self.assertEqual(combined.read_bytes(), pe(ffx=True), 'Scaler leaves the game\'s FSR DLL untouched')

    def test_split_dll_game_keeps_the_direct_route(self):
        data = self.m.assess(self.game)
        self.assertEqual((data['route'], data['hlx_direct_supported'], data['hlx_scaler_reason']), ('direct', True, None))
