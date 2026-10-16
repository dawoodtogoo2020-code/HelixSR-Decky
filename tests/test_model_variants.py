"""Regression coverage for reviewed model variants using synthetic payloads only."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zipfile


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / 'py_modules'))

import manager
import model_variants
from test_backend import Fixtures, pe, write


REVIEWED_RECIPE = next(iter(model_variants.REVIEWED_RECIPES))


def reviewed_variant(recipe=REVIEWED_RECIPE):
    return dict(id=model_variants.DEFAULT_VARIANT, adapter=model_variants.ADAPTER,
                recipe_sha256=recipe)


def release(version='1.8.0', digest='a' * 64, size=1):
    tag = 'v' + version
    return dict(version=version, sha256=digest, size=size,
                url=f'https://github.com/{manager.REPO}/releases/download/{tag}/HelixSR-{version}.zip',
                page=f'https://github.com/{manager.REPO}/releases/tag/{tag}')


class Response:
    def __init__(self, payload, url):
        self.payload = io.BytesIO(payload)
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.payload.read(size)

    def geturl(self):
        return self.url


class RegistryTests(unittest.TestCase):
    def test_model_e_is_the_default_reviewed_variant(self):
        catalog = model_variants.catalog()
        self.assertEqual(model_variants.DEFAULT_VARIANT, 'helixsr-model-e')
        self.assertEqual(catalog['default'], model_variants.DEFAULT_VARIANT)
        self.assertEqual([item['id'] for item in catalog['variants']],
                         [model_variants.DEFAULT_VARIANT])
        selected = model_variants.select_variant()
        self.assertEqual(selected['label'], 'HelixSR Model E')
        self.assertEqual(selected['source'], 'NVIDIA DLSS 310.7.0')
        self.assertEqual(selected['adapter'], model_variants.ADAPTER)

    def test_recipe_registry_has_the_complete_known_file_set_and_hashes(self):
        self.assertEqual(len(model_variants.RECIPE_FILES), 40)
        self.assertEqual(len(set(model_variants.RECIPE_FILES)), 40)
        self.assertIn('helixsr-setup.sh', model_variants.RECIPE_FILES)
        self.assertIn('setup/helixsr_setup.py', model_variants.RECIPE_FILES)
        self.assertIn('setup/lib/model/model_gen.inc', model_variants.RECIPE_FILES)
        self.assertEqual(set(model_variants.REVIEWED_RECIPES.values()),
                         {model_variants.DEFAULT_VARIANT})
        self.assertGreaterEqual(len(model_variants.REVIEWED_RECIPES), 2)
        for digest in model_variants.REVIEWED_RECIPES:
            self.assertRegex(digest, r'^[a-f0-9]{64}$')

    def test_unknown_models_and_malformed_variant_metadata_are_rejected(self):
        for value in ('future-model', 4, {}, [], True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'not supported'):
                model_variants.select_variant(value)
        valid = reviewed_variant()
        self.assertTrue(model_variants.valid_variant(valid))
        for malformed in (None, 'model', {}, {'id': model_variants.DEFAULT_VARIANT},
                          dict(valid, id=3), dict(valid, adapter=3),
                          dict(valid, recipe_sha256=3),
                          dict(valid, recipe_sha256='f' * 64)):
            with self.subTest(malformed=malformed):
                self.assertFalse(model_variants.valid_variant(malformed))


class RecipeGateTests(Fixtures):
    def archive(self, missing=None, extra=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            prefix = 'HelixSR-1.8.0/'
            files = set(model_variants.RECIPE_FILES)
            if missing:
                files.remove(missing)
            if extra:
                files.add(extra)
            for name in files:
                archive.writestr(prefix + name, ('synthetic recipe: ' + name).encode())
            archive.writestr(prefix + 'setup/helixsr_install.py', b'raise SystemExit(1)\n')
            archive.writestr(prefix + manager.DLL, pe(ffx=True, helix=True))
            for name in ('LICENSE', 'LICENSE-APACHE-2.0', 'THIRD_PARTY_NOTICES.md',
                         'optiscaler/OptiScaler.dll', 'optiscaler/OptiScaler.ini'):
                archive.writestr(prefix + name, b'synthetic fixture')
        payload = buffer.getvalue()
        metadata = release(size=len(payload), digest=hashlib.sha256(payload).hexdigest())
        return payload, metadata

    def prepare_archive(self, missing=None, extra=None):
        payload, metadata = self.archive(missing, extra)
        self.m.cfg['license'] = manager.license_key(metadata)
        job = {'id': 'recipe-gate', 'variant_id': model_variants.DEFAULT_VARIANT,
               'reviewed_release': dict(metadata)}
        with patch.object(self.m, 'check_update', return_value=metadata), \
                patch('manager.https_context', return_value=None), \
                patch('manager.urllib.request.urlopen',
                      return_value=Response(payload, metadata['url'])), \
                patch('manager.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError, 'recipe|conversion files changed'):
                self.m.prepare(self.game, job)
            process.assert_not_called()

    def test_unreviewed_recipe_hash_is_rejected_before_build(self):
        self.prepare_archive()

    def test_missing_and_extra_recipe_files_are_rejected_before_build(self):
        for missing, extra in (('setup/lib/samplers.py', None),
                               (None, 'setup/lib/unreviewed_adapter.py')):
            with self.subTest(missing=missing, extra=extra):
                self.prepare_archive(missing, extra)


class OutputVerificationTests(Fixtures):
    def output_package(self, shader_payloads=(b'first shader', b'second shader')):
        package = self.base / 'synthetic-output'
        weights = b'synthetic Model E weights'
        weight_hash = hashlib.sha256(weights).hexdigest()
        write(package / 'helixsr_weights.bin', weights)
        manifest = dict(source_sha256='1' * 64, ptx_target='sm_89',
                        shaders=len(shader_payloads), wave64=False,
                        weights_sha256=weight_hash)
        write(package / 'helixsr_setup.json', json.dumps(manifest))
        offset = 16 + 40 * len(shader_payloads)
        rows = []
        for index, payload in enumerate(shader_payloads):
            name = f'synthetic_{index}'.encode().ljust(32, b'\0')
            rows.append(struct.pack('<32sII', name, offset, len(payload)))
            offset += len(payload)
        pak = b'HXSRKPAK' + struct.pack('<II', 2, len(shader_payloads))
        pak += b''.join(rows) + b''.join(shader_payloads)
        write(package / 'helixsr_kernels.pak', pak)
        return package, weights, manifest

    def verify_synthetic(self, package, weights, manifest):
        with patch.object(model_variants, 'SOURCE_SHA256', manifest['source_sha256']), \
                patch.object(model_variants, 'KERNEL_NAMES', tuple(f'synthetic_{i}'.encode() for i in range(manifest['shaders']))), \
                patch.object(model_variants, 'WEIGHTS_SIZE', len(weights)), \
                patch.object(model_variants, 'WEIGHTS_SHA256', manifest['weights_sha256']):
            return model_variants.verify_outputs(package)

    def test_canonical_weights_manifest_and_pak_are_verified_together(self):
        package, weights, manifest = self.output_package()
        self.assertIsNone(self.verify_synthetic(package, weights, manifest))

    def test_weight_and_manifest_drift_are_rejected(self):
        package, weights, manifest = self.output_package()
        write(package / 'helixsr_weights.bin', weights + b'tamper')
        with self.assertRaisesRegex(ValueError, 'selected Model E recipe'):
            self.verify_synthetic(package, weights, manifest)
        write(package / 'helixsr_weights.bin', weights)
        changed = dict(manifest, unexpected=True)
        write(package / 'helixsr_setup.json', json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'selected Model E recipe'):
            self.verify_synthetic(package, weights, manifest)

    def test_pak_header_table_count_and_trailing_bytes_are_rejected(self):
        package, weights, manifest = self.output_package()
        pak = package / 'helixsr_kernels.pak'
        original = pak.read_bytes()
        corruptions = (b'BADPAK!!' + original[8:],
                       original[:12] + struct.pack('<I', 3) + original[16:],
                       original + b'trailing')
        for payload in corruptions:
            with self.subTest(length=len(payload)):
                write(pak, payload)
                with self.assertRaisesRegex(ValueError, 'kernels|kernel'):
                    self.verify_synthetic(package, weights, manifest)
        self.assertNotIn(b'NVIDIA', weights)


class ManagerVariantTests(Fixtures):
    def verified_package(self, version='1.9.0', prepared_at=100, marker=b'old'):
        folder = self.base / 'prepared' / (version + '-' + marker.decode())
        write(folder / manager.DLL, pe(ffx=True, helix=True) + marker)
        for name in manager.NETWORK:
            write(folder / name, b'synthetic network ' * 128)
        write(folder / 'optiscaler/OptiScaler.dll', b'synthetic proxy')
        write(folder / 'optiscaler/fakenvapi.dll', b'synthetic fakenvapi')
        write(folder / 'optiscaler/fakenvapi.ini', '[synthetic]\n')
        write(folder / 'optiscaler/OptiScaler.ini', '[Upscalers]\nDx12Upscaler=auto\n'
              'FfxDx12Path=auto\nFfxDx12SRPath=auto\nFfxDx12FGPath=auto\n')
        write(folder / 'amd-fsr/amd_fidelityfx_upscaler_dx12.dll', pe(ffx=True))
        record = dict(path=str(folder), version=version, release_sha256='a' * 64,
                      prepared_at=prepared_at, variant=reviewed_variant(),
                      files={name: manager.sha(folder / name) for name in manager.PACKAGE_FILES})
        self.m.cfg['packages'][str(folder)] = record
        self.reviewed_package(folder)
        return folder, record

    def test_package_filters_by_variant_and_exact_selection(self):
        older, older_record = self.verified_package('1.9.0', 100, b'old')
        newer, _ = self.verified_package('1.10.0', 200, b'new')
        selected = model_variants.package_selection(older_record)
        self.assertEqual(self.m.package(self.game, variant_id=model_variants.DEFAULT_VARIANT,
                                        selection=selected)[1], older)
        self.assertEqual(self.m.package(self.game, variant_id=model_variants.DEFAULT_VARIANT)[1], newer)
        self.assertIsNone(self.m.package(self.game, selection='0' * 64))
        with self.assertRaisesRegex(ValueError, 'not supported'):
            self.m.package(self.game, variant_id='future-model')

    def test_enable_reuses_installed_package_identity_when_newer_cache_exists(self):
        older, older_record = self.verified_package('1.9.0', 100, b'old')
        self.action('install')
        installed_identity = model_variants.package_selection(older_record)
        self.assertEqual(self.m.record(self.game)['package_selection'], installed_identity)
        self.action('disable')
        newer, _ = self.verified_package('1.10.0', 200, b'new')
        self.action('enable')
        self.assertEqual(manager.sha(self.native), manager.sha(older / manager.DLL))
        self.assertNotEqual(manager.sha(self.native), manager.sha(newer / manager.DLL))
        rec = self.m.record(self.game)
        self.assertEqual(rec['package_selection'], installed_identity)
        actions = sorted((self.m.companion(self.game) / 'records').glob('action-*.json'),
                         key=lambda path: path.stat().st_mtime_ns)
        self.assertEqual(manager.load_json(actions[-1])['package_selection'], installed_identity)

    def test_reviewed_action_rejects_package_metadata_drift(self):
        _folder, record = self.verified_package()
        token = self.m.preview(self.game['id'], 'install')['token']
        record['release_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            self.m.execute(token)
        self.assertEqual(self.native.read_bytes(), self.original)

    def test_preview_latest_rejects_unknown_variant_without_network(self):
        with patch.object(self.m, 'check_update') as check:
            with self.assertRaisesRegex(ValueError, 'not supported'):
                self.m.preview_latest(self.game['id'], variant_id='future-model')
            check.assert_not_called()

    def test_release_change_between_preview_and_accept_is_rejected(self):
        before = release('1.8.0', 'a' * 64)
        after = release('1.8.1', 'b' * 64)
        with patch.object(self.m, 'check_update', return_value=before):
            token = self.m.preview_latest(self.game['id'],
                                          variant_id=model_variants.DEFAULT_VARIANT)['token']
        with patch.object(self.m, 'check_update', return_value=after):
            with self.assertRaisesRegex(ValueError, 'changed since review'):
                self.m.accept_license(True, token)
        self.assertFalse(self.m.cfg.get('license'))

    def test_release_change_between_accept_and_prepare_is_rejected(self):
        before = release('1.8.0', 'a' * 64)
        after = release('1.8.1', 'b' * 64)
        with patch.object(self.m, 'check_update', return_value=before):
            token = self.m.preview_latest(self.game['id'])['token']
            self.m.accept_license(True, token)
        job = {'id': 'release-drift', 'variant_id': model_variants.DEFAULT_VARIANT,
               'reviewed_release': before}
        with patch.object(self.m, 'check_update', return_value=after), \
                patch('manager.urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'release changed'):
                self.m.prepare(self.game, job)
            network.assert_not_called()

    def test_shared_package_index_exposes_multiple_exact_caches(self):
        first, first_record = self.verified_package('1.9.0', 100, b'first')
        second, second_record = self.verified_package('1.10.0', 200, b'second')
        companion = self.m.companion(self.game)
        shared_first = companion / 'packages' / first.name
        shared_second = companion / 'packages' / second.name
        shared_first.parent.mkdir(parents=True, exist_ok=True)
        first.rename(shared_first)
        second.rename(shared_second)
        first_record = dict(first_record, path=str(shared_first))
        second_record = dict(second_record, path=str(shared_second))
        self.m.cfg['packages'].clear()
        manager.atomic_json(companion / 'records/package.json', second_record)
        manager.atomic_json(companion / 'records/packages-v1.json',
                            {'schema': 1, 'packages': [first_record, second_record]})
        self.assertEqual(self.m.package(
            self.game, selection=model_variants.package_selection(first_record))[1], shared_first)
        self.assertEqual(self.m.package(
            self.game, selection=model_variants.package_selection(second_record))[1], shared_second)
        pointer = companion / 'records/package.json'
        for broken in (None, '{broken', 'x' * ((1 << 20) + 1)):
            if broken is None:
                pointer.unlink()
            else:
                pointer.write_text(broken, encoding='utf-8')
            self.assertEqual(self.m.package(self.game,
                selection=model_variants.package_selection(first_record))[1], shared_first)
        manager.atomic_json(pointer, first_record)
        (companion / 'records/packages-v1.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(self.m.package(self.game,
            selection=model_variants.package_selection(first_record))[1], shared_first)

    def test_legacy_opti_identity_includes_all_immutable_providers_and_fg(self):
        self.native.unlink()
        write(self.root / 'nvngx_dlss.dll', pe())
        folder, record = self.verified_package('1.7.0')
        write(folder / 'amd-fsr' / manager.AMD_FG, pe(ffx=True))
        self.sync_package_record(folder)
        self.action('install')
        installed = self.m.record(self.game)
        self.assertTrue(self.m.matches_installed_payload(self.game, installed, record))
        for name in ('optiscaler/OptiScaler.dll', 'optiscaler/fakenvapi.dll',
                     'amd-fsr/amd_fidelityfx_upscaler_dx12.dll', 'amd-fsr/' + manager.AMD_FG):
            changed = json.loads(json.dumps(record))
            changed['files'][name] = '0' * 64
            self.assertFalse(self.m.matches_installed_payload(self.game, installed, changed), name)
        absent = json.loads(json.dumps(record))
        absent['files'].pop('amd-fsr/' + manager.AMD_FG)
        self.assertFalse(self.m.matches_installed_payload(self.game, installed, absent))

    def test_relabelled_cache_with_updated_hashes_still_rejects_wrong_model(self):
        folder, record = self.verified_package()
        self.assertIsNotNone(self.m.package(self.game))
        write(folder / 'helixsr_weights.bin', b'other model' * 300)
        record['files']['helixsr_weights.bin'] = manager.sha(folder / 'helixsr_weights.bin')
        self.assertIsNone(self.m.package(self.game))

    def test_broken_model_metadata_does_not_block_original_restoration(self):
        for metadata in (None, 'unknown', ['unknown'], {'id': 'future-model'}):
            with self.subTest(metadata=metadata):
                self.package()
                self.action('install')
                rec = self.m.record(self.game)
                rec['variant'] = metadata
                manager.atomic_json(self.m.record_path(self.game), rec)
                self.action('disable')
                self.assertEqual(self.native.read_bytes(), self.original)
                self.action('remove')
                self.assertFalse(self.m.record(self.game))

    def test_legacy_enable_uses_recorded_version_and_refuses_ambiguous_revision(self):
        older, _ = self.verified_package('1.7.0', 100, b'old')
        self.action('install')
        rec = self.m.record(self.game)
        rec.pop('package_selection')
        rec.pop('variant')
        manager.atomic_json(self.m.record_path(self.game), rec)
        self.action('disable')
        self.verified_package('1.8.1', 200, b'new')
        self.action('enable')
        self.assertEqual(manager.sha(self.native), manager.sha(older / manager.DLL))
        rec = self.m.record(self.game)
        rec.pop('package_selection')
        manager.atomic_json(self.m.record_path(self.game), rec)
        revision, revision_record = self.verified_package('1.7.0', 300, b'revision')
        write(revision / manager.DLL, (older / manager.DLL).read_bytes())
        self.sync_package_record(revision)
        revision_record['release_sha256'] = 'b' * 64
        self.action('disable')
        with self.assertRaisesRegex(ValueError, 'use Update HelixSR'):
            self.m.preview(self.game['id'], 'enable')

    def test_future_legacy_cache_is_excluded_and_old_unknown_model_is_displayed(self):
        folder, record = self.verified_package('1.9.0', 100, b'future')
        record.pop('variant')
        self.assertIsNone(self.m.package(self.game))
        self.m.cfg['packages'].clear()
        legacy = self.package()
        self.action('install')
        assessed = self.m.assess(self.game)
        self.assertEqual(assessed['installed_model'], 'Model unverified')
        self.assertIsNone(assessed['installed_variant'])
        self.assertEqual(manager.sha(self.native), manager.sha(legacy / manager.DLL))


if __name__ == '__main__':
    unittest.main(verbosity=2)
