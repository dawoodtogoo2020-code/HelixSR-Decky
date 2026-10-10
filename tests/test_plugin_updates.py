"""Offline regressions for plugin updates and optional awareness metadata."""
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import warnings
import zipfile


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "py_modules"))

import awareness
import plugin_updates


WORK = PLUGIN.parent.parent / "work"
WORK.mkdir(exist_ok=True)


class FakeResponse:
    def __init__(self, payload, url):
        self.payload = payload
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if self.offset >= len(self.payload):
            return b""
        end = len(self.payload) if size < 0 else min(len(self.payload), self.offset + size)
        chunk = self.payload[self.offset:end]
        self.offset = end
        return chunk


def release(version, payload_size=123, digest="a" * 64, **changes):
    tag = "v" + version
    filename = f"{plugin_updates.FOLDER}-{version}.zip"
    item = {
        "tag_name": tag,
        "draft": False,
        "prerelease": version.startswith("0."),
        "published_at": "2026-10-10T00:00:00Z",
        "html_url": f"{plugin_updates.PAGE}/tag/{tag}",
        "assets": [{
            "name": filename,
            "browser_download_url":
                f"https://github.com/{plugin_updates.REPO}/releases/download/{tag}/{filename}",
            "digest": "sha256:" + digest,
            "size": payload_size,
        }],
    }
    item.update(changes)
    return item


def archive_bytes(folder, version="0.1.1", extra=None, omit=()):
    path = folder / "fixture.zip"
    entries = {
        f"{plugin_updates.FOLDER}/main.py": b"pass\n",
        f"{plugin_updates.FOLDER}/plugin.json": json.dumps({
            "name": plugin_updates.PLUGIN_NAME,
            "flags": [],
            "api_version": 1,
        }).encode(),
        f"{plugin_updates.FOLDER}/package.json": json.dumps({
            "name": "helixsr-decky",
            "version": version,
        }).encode(),
        f"{plugin_updates.FOLDER}/dist/index.js": b"export {};\n",
        **{f"{plugin_updates.FOLDER}/py_modules/{name}.py": b"# fixture\n"
           for name in ('manager', 'library', 'awareness', 'plugin_updates')},
    }
    entries.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            if name not in omit:
                archive.writestr(name, content)
    return path.read_bytes()


class PluginUpdateFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="plugin-update-tests-", dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = self.root / "settings"
        self.settings.mkdir()
        self.package = self.root / "package.json"
        self.package.write_text(json.dumps({"version": "0.1.0"}))

    def updater(self):
        return plugin_updates.PluginUpdates(self.settings, self.package)

    def metadata_response(self, item):
        return FakeResponse(json.dumps([item]).encode(), plugin_updates.API)


class ReleaseValidationTests(PluginUpdateFixtures):
    def test_semver_is_strict_and_release_identity_is_exact(self):
        self.assertEqual(plugin_updates.semver("v0.1.11"), (0, 1, 11))
        for invalid in ("1.2", "1.2.3-beta", "01.2.3", 123, None):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                plugin_updates.semver(invalid)

        expected = plugin_updates.release_info(release("0.1.1", 321, "A" * 64))
        self.assertEqual(expected["version"], "0.1.1")
        self.assertEqual(expected["sha256"], "a" * 64)
        self.assertEqual(expected["size"], 321)
        self.assertTrue(expected["prerelease"])

        mutations = [
            {"html_url": plugin_updates.PAGE + "/tag/v0.1.2"},
            {"assets": []},
            {"assets": [{**release("0.1.1")["assets"][0], "name": "other.zip"}]},
            {"assets": [{**release("0.1.1")["assets"][0], "digest": "sha256:" + "g" * 64}]},
            {"assets": [{**release("0.1.1")["assets"][0], "size": True}]},
            {"assets": [{**release("0.1.1")["assets"][0], "browser_download_url": "https://example.test/plugin.zip"}]},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                plugin_updates.release_info(release("0.1.1", **mutation))

    def test_complete_archive_is_accepted_and_unsafe_or_incomplete_archives_fail(self):
        valid = self.root / "valid.zip"
        valid.write_bytes(archive_bytes(self.root))
        plugin_updates.validate_zip(valid, "0.1.1")

        missing = self.root / "missing.zip"
        missing.write_bytes(archive_bytes(
            self.root, omit=(f"{plugin_updates.FOLDER}/dist/index.js",)))
        traversal = self.root / "traversal.zip"
        traversal.write_bytes(archive_bytes(
            self.root, extra={f"{plugin_updates.FOLDER}/../escape": b"no"}))
        symlink = self.root / "symlink.zip"
        with zipfile.ZipFile(symlink, "w") as output:
            for name, content in {
                f"{plugin_updates.FOLDER}/main.py": b"pass",
                f"{plugin_updates.FOLDER}/plugin.json": b"{}",
                f"{plugin_updates.FOLDER}/package.json": b"{}",
                f"{plugin_updates.FOLDER}/dist/index.js": b"",
            }.items():
                output.writestr(name, content)
            link = zipfile.ZipInfo(f"{plugin_updates.FOLDER}/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(link, "main.py")
        duplicate = self.root / "duplicate.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "w") as output:
                for name in (
                    f"{plugin_updates.FOLDER}/main.py",
                    f"{plugin_updates.FOLDER}/plugin.json",
                    f"{plugin_updates.FOLDER}/package.json",
                    f"{plugin_updates.FOLDER}/dist/index.js",
                    f"{plugin_updates.FOLDER}/main.py",
                ):
                    output.writestr(name, b"{}")

        for path in (missing, traversal, symlink, duplicate):
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                plugin_updates.validate_zip(path, "0.1.1")

        for alias in ('./plugin.json', '/plugin.json', './main.py'):
            payload = archive_bytes(self.root, extra={f'{plugin_updates.FOLDER}/{alias}': b'{}'})
            invalid = self.root / 'alias.zip'
            invalid.write_bytes(payload)
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, 'Unsafe'):
                plugin_updates.validate_zip(invalid, '0.1.1')

    def test_missing_backend_dependency_is_rejected(self):
        path = self.root / 'missing-backend.zip'
        path.write_bytes(archive_bytes(self.root, omit=(f'{plugin_updates.FOLDER}/py_modules/manager.py',)))
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            plugin_updates.validate_zip(path, '0.1.1')


class SchedulingAndNetworkTests(PluginUpdateFixtures):
    def test_auto_toggle_persists_and_due_uses_retry_and_success_intervals(self):
        updater = self.updater()
        with patch("plugin_updates.time.time", return_value=100_000):
            self.assertTrue(updater.due())
            updater.attempted_at = 99_999
            self.assertFalse(updater.due())
            updater.attempted_at = 0
            updater.checked_at = 99_999
            self.assertFalse(updater.due())
        self.assertFalse(updater.set_auto(False)["auto_check"])
        self.assertEqual(json.loads(updater.path.read_text()), {"auto_check": False})
        self.assertFalse(self.updater().enabled)
        with self.assertRaises(ValueError):
            updater.set_auto(1)

    def test_network_failure_preserves_last_successful_release_and_check_time(self):
        updater = self.updater()
        item = release("0.1.1")
        with patch("plugin_updates.time.time", side_effect=(100_000, 100_050)), patch(
                "plugin_updates.urllib.request.urlopen",
                side_effect=(self.metadata_response(item), OSError("offline"))):
            first = updater.check(force=True)
            second = updater.check(force=True)
        self.assertEqual(first["latest_version"], "0.1.1")
        self.assertEqual(second["latest_version"], "0.1.1")
        self.assertEqual(second["checked_at"], 100_000)
        self.assertEqual(second["attempted_at"], 100_050)
        self.assertIn("offline", second["error"])


class StagingTests(PluginUpdateFixtures):
    def test_corrupt_owned_cache_is_replaced_and_can_be_cancelled(self):
        payload = archive_bytes(self.root)
        digest = hashlib.sha256(payload).hexdigest()
        item = release('0.1.1', len(payload), digest)
        updater = self.updater()
        updater.stage.mkdir()
        corrupt = updater.stage / f'HelixSR-Decky-0.1.1-{digest}.zip'
        corrupt.write_bytes(b'corrupt')
        with patch('plugin_updates.shutil.disk_usage', return_value=SimpleNamespace(free=1 << 30)), patch(
                'plugin_updates.urllib.request.urlopen', side_effect=(self.metadata_response(item),
                    FakeResponse(payload, item['assets'][0]['browser_download_url']))):
            updater.prepare()
        self.assertEqual(corrupt.read_bytes(), payload)
        updater.cancel()
        self.assertFalse(corrupt.exists())

    def test_completed_owned_package_is_cleaned_but_other_files_are_preserved(self):
        payload = archive_bytes(self.root, version='0.1.0')
        digest = hashlib.sha256(payload).hexdigest()
        updater = self.updater()
        updater.stage.mkdir()
        owned = updater.stage / f'HelixSR-Decky-0.1.0-{digest}.zip'
        owned.write_bytes(payload)
        unrelated = updater.stage / 'personal.zip'
        unrelated.write_bytes(b'preserve')
        updater.cleanup_installed()
        self.assertFalse(owned.exists())
        self.assertEqual(unrelated.read_bytes(), b'preserve')

    def test_hash_or_size_failure_cleans_partial_file_then_retry_and_cancel_succeed(self):
        payload = archive_bytes(self.root)
        digest = hashlib.sha256(payload).hexdigest()
        item = release("0.1.1", len(payload), digest)
        download_url = item["assets"][0]["browser_download_url"]
        responses = (
            self.metadata_response(item),
            FakeResponse(payload + b"unexpected", download_url),
            self.metadata_response(item),
            FakeResponse(payload, download_url),
        )
        updater = self.updater()
        with patch("plugin_updates.shutil.disk_usage", return_value=SimpleNamespace(free=1 << 30)), patch(
                "plugin_updates.urllib.request.urlopen", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "declared size"):
                updater.prepare()
            self.assertEqual(list(updater.stage.iterdir()), [])
            prepared = updater.prepare()

        artifact = Path(prepared["artifact"].removeprefix("file://"))
        self.assertTrue(artifact.is_file())
        self.assertEqual(prepared["sha256"], digest)
        self.assertEqual(prepared["install_type"], 2)
        self.assertTrue(updater.status()["pending"])

        # A plugin reload loses in-memory pending state. Fresh metadata may
        # safely recover the exact cached artifact without another download.
        reloaded = self.updater()
        with patch("plugin_updates.shutil.disk_usage", return_value=SimpleNamespace(free=1 << 30)), patch(
                "plugin_updates.urllib.request.urlopen",
                return_value=self.metadata_response(item)) as request:
            cached = reloaded.prepare()
        self.assertEqual(cached, prepared)
        request.assert_called_once()

        reloaded.cancel()
        self.assertFalse(artifact.exists())
        self.assertFalse(reloaded.status()["pending"])

    def test_declared_size_match_with_wrong_hash_is_rejected(self):
        payload = archive_bytes(self.root)
        item = release("0.1.1", len(payload), "0" * 64)
        updater = self.updater()
        with patch("plugin_updates.shutil.disk_usage", return_value=SimpleNamespace(free=1 << 30)), patch(
                "plugin_updates.urllib.request.urlopen", side_effect=(
                    self.metadata_response(item),
                    FakeResponse(payload, item["assets"][0]["browser_download_url"]),
                )):
            with self.assertRaisesRegex(ValueError, "SHA-256 or size mismatch"):
                updater.prepare()
        self.assertEqual(list(updater.stage.glob("*")), [])


class AwarenessOptionalJsonTests(PluginUpdateFixtures):
    def inspect(self, metadata):
        home = self.root / "home"
        game = self.root / "game"
        home.mkdir(exist_ok=True)
        game.mkdir(exist_ok=True)
        executable = game / "Example.exe"
        executable.write_bytes(b"fixture")
        config = home / ".config/mako-render"
        config.mkdir(parents=True, exist_ok=True)
        (config / "conf.toml").write_text(
            '[[profile]]\nname = "selected"\nframe_generation_enabled = true\n')
        (config / "profile-metadata.json").write_text(json.dumps(metadata))
        record = {"appid": "42", "folder": str(game), "launch_options": ""}
        with patch("awareness.active_processes", return_value=[]):
            return awareness.awareness(record, [(game, [executable.name])], home, "direct")

    def test_null_or_list_profiles_and_null_profile_children_are_ignored(self):
        for metadata in ({"profiles": None}, {"profiles": []},
                         {"profiles": {"selected": None, "other": []}}):
            with self.subTest(metadata=metadata):
                result = self.inspect(metadata)
                self.assertEqual([x for x in result["framegen"] if x["source"] == "MAKO"], [])


if __name__ == "__main__":
    unittest.main()
