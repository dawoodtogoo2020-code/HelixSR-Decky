import assert from "node:assert/strict";
import test from "node:test";

import { proxyOptions } from "../src/launchOptions.ts";
import { PluginInstaller } from "../src/pluginInstaller.ts";
import { gameStatus } from "../src/gameStatus.ts";

test("changed managed files cannot appear as a healthy enabled install", () => {
  const enabled = {compatibility: "candidate", managed: true, enabled: true, legacy: false, installed_version: "1.8.1"};
  assert.equal(gameStatus(enabled).label, "Enabled");
  assert.equal(gameStatus(enabled).installed, true);
  const conflict = gameStatus({...enabled, compatibility: "blocked"});
  assert.equal(conflict.label, "Needs review");
  assert.equal(conflict.installed, false);
  assert.match(conflict.summary, /Needs review.*Recorded as enabled/);
  assert.notEqual(conflict.color, gameStatus(enabled).color);
  const recovery = gameStatus({...enabled, recovery_available: true});
  assert.equal(recovery.label, "Recovery needed");
  assert.equal(recovery.installed, false);
  assert.match(gameStatus({...enabled, enabled: false}).summary, /disabled/);
  assert.equal(gameStatus({...enabled, compatibility: "blocked", executable_selection_needed: true}).label, "Choose executable");
});

const artifact = {artifact: "file:///private/update-attempt.zip", name: "HelixSR Decky", version: "0.1.3", sha256: "a".repeat(64), install_type: 2};

test("download requests confirmation, reopening cancels the previous exact request", async t => {
  const calls = [];
  const installer = new PluginInstaller(async (...args) => { calls.push(args); if (args[0] === "utilities/install_plugin") installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256); }, () => {});
  t.after(() => installer.dispose());
  await installer.open(artifact);
  assert.equal(installer.phase, "awaiting");
  assert.match(installer.message, /Press Update/);
  installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256);
  await installer.open(artifact);
  assert.deepEqual(calls[1], ["utilities/cancel_plugin_install", "request-A"]);
  assert.equal(calls[2][0], "utilities/install_plugin");
  assert.equal(calls.filter(c => c[0] === "utilities/confirm_plugin_install").length, 0);
});

test("cancel invalidates Decky's request before deleting the artifact or releasing the guard", async t => {
  const calls = [];
  const installer = new PluginInstaller(async route => { calls.push(route); if (route === "utilities/install_plugin") installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256); }, () => {});
  t.after(() => installer.dispose());
  await installer.open(artifact);
  installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256);
  await installer.cancel(async () => { calls.push("delete-private-zip"); });
  assert.deepEqual(calls.slice(1), ["utilities/cancel_plugin_install", "delete-private-zip"]);
  assert.equal(installer.phase, "idle");
});

test("failed native cancellation preserves artifact and mutation guard", async t => {
  let removed = false;
  const installer = new PluginInstaller(async route => { if (route.includes("cancel")) throw new Error("disconnected"); installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256); }, () => {});
  t.after(() => installer.dispose());
  await installer.open(artifact);
  installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256);
  await assert.rejects(installer.cancel(async () => { removed = true; }), /disconnected/);
  assert.equal(removed, false);
  assert.equal(installer.requestId, "request-A");
});

test("native Cancel's precise missing request is recoverable; unrelated errors are not", async t => {
  const installer = new PluginInstaller(async route => { if (route === "utilities/install_plugin") installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256); if (route.includes("cancel")) { const err = new Error(""); err.name = "Python KeyError"; throw err; } }, () => {});
  t.after(() => installer.dispose());
  await installer.open(artifact);
  installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256);
  await installer.open(artifact);
  assert.equal(installer.phase, "awaiting");
});

test("installer request failure stays retryable and retains an explanation across panel remounts", async t => {
  const installer = new PluginInstaller(async () => { throw new Error("installer unavailable"); }, () => {});
  t.after(() => installer.dispose());
  await assert.rejects(installer.open(artifact), /unavailable/);
  assert.equal(installer.phase, "awaiting");
  assert.match(installer.message, /downloaded update is retained/);
  assert.equal(installer.target.version, "0.1.3");
});

test("missing finish and failed finish never claim installed or release pending game protection", async t => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  const installer = new PluginInstaller(async () => { installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256); }, () => {});
  t.after(() => installer.dispose());
  await installer.open(artifact);
  installer.started(artifact.name);
  installer.prompt(artifact.name, artifact.version, "late-request", artifact.sha256);
  assert.equal(installer.phase, "installing");
  t.mock.timers.tick(120000);
  assert.equal(installer.phase, "unknown");
  assert.equal(installer.locked, true);
  await assert.rejects(installer.cancel(async () => assert.fail("deleted active ZIP")), /Do not cancel/);
  installer.finished(artifact.name);
  assert.equal(installer.phase, "unknown");
  assert.match(installer.message, /verify Current plugin/);
});

test("an in-flight handoff cannot create duplicate prompts or be cancelled before acknowledgement", async t => {
  let finish;
  let installs = 0;
  const installer = new PluginInstaller(async () => { installs++; await new Promise(resolve => { finish = resolve; }); }, () => {});
  t.after(() => installer.dispose());
  const first = installer.open(artifact);
  await Promise.resolve();
  await assert.rejects(installer.open(artifact), /current installer request/);
  await assert.rejects(installer.cancel(async () => assert.fail("deleted in-flight ZIP")), /current installer request/);
  installer.prompt(artifact.name, artifact.version, "request-A", artifact.sha256);
  finish();
  await first;
  assert.equal(installs, 1);
});

test("missing prompt acknowledgement preserves the guard and requires restart", async t => {
  const installer = new PluginInstaller(async () => {}, () => {});
  t.after(() => installer.dispose());
  await assert.rejects(installer.open(artifact), /did not acknowledge/);
  assert.equal(installer.phase, "unknown");
  installer.prompt(artifact.name, artifact.version, "late-request", artifact.sha256);
  assert.equal(installer.phase, "unknown");
});


test("arguments-only launch options receive Steam's command placeholder", () => {
  assert.equal(
    proxyOptions("-dx12 -novid"),
    'WINEDLLOVERRIDES="dxgi=n,b" %command% -dx12 -novid',
  );
});

test("existing environment assignments and command arguments are preserved", () => {
  const original = "MANGOHUD=1 %command% -dx12";
  assert.equal(proxyOptions(original), `WINEDLLOVERRIDES="dxgi=n,b" ${original}`);
});

test("a non-conflicting override is extended without dropping surrounding options", () => {
  assert.equal(
    proxyOptions('MANGOHUD=1 WINEDLLOVERRIDES="d3d11=n" %command% -novid'),
    'MANGOHUD=1 WINEDLLOVERRIDES="d3d11=n;dxgi=n,b" %command% -novid',
  );
});

test("grouped and case-insensitive DXGI overrides are refused", () => {
  for (const options of [
    'WINEDLLOVERRIDES="d3d11,DXGI=n,b" %command%',
    "WINEDLLOVERRIDES='dxgi,d3d12=b' %command%",
    "WINEDLLOVERRIDES=DxGi=n %command%",
    'WINEDLLOVERRIDES="dxgi.dll=b" %command%',
  ]) {
    assert.throws(() => proxyOptions(options), /existing dxgi override needs review/i);
  }
});

test("wildcards, shell expansion and repeated override assignments need review", () => {
  for (const options of [
    "WINEDLLOVERRIDES='*=b' %command%",
    "WINEDLLOVERRIDES='$RULE' %command%",
    'WINEDLLOVERRIDES="d3d11=n" WINEDLLOVERRIDES="d3d12=n" %command%',
  ]) assert.throws(() => proxyOptions(options), /review/i);
});

test("environment-only and multiple literal assignments stay before Steam's command", () => {
  assert.equal(proxyOptions('MANGOHUD=1'), 'WINEDLLOVERRIDES="dxgi=n,b" MANGOHUD=1 %command%');
  assert.equal(proxyOptions('MANGOHUD=1 FOO="two words" -dx12 -novid'), 'WINEDLLOVERRIDES="dxgi=n,b" MANGOHUD=1 FOO="two words" %command% -dx12 -novid');
  assert.equal(proxyOptions('FOO=1 WINEDLLOVERRIDES="d3d11=n" BAR=2 -novid'), 'FOO=1 WINEDLLOVERRIDES="d3d11=n;dxgi=n,b" BAR=2 %command% -novid');
});

test("already correct dxgi is a byte-preserving no-op with a placeholder", () => {
  for (const original of ['WINEDLLOVERRIDES=dxgi=n,b %command%', 'FOO=1  WINEDLLOVERRIDES="d3d11=n;dxgi=n,b" gamescope -f -- %command% -dx12'])
    assert.equal(proxyOptions(original), original);
  assert.equal(proxyOptions('WINEDLLOVERRIDES=dxgi=n,b'), 'WINEDLLOVERRIDES=dxgi=n,b %command%');
});

test("literal wrappers, whitespace and trailing arguments survive", () => {
  const original = '  FOO="two words" gamescope -f -- %command% -novid "two words"  ';
  assert.equal(proxyOptions(original), `WINEDLLOVERRIDES="dxgi=n,b" ${original}`);
  assert.equal(proxyOptions('env WINEDLLOVERRIDES="d3d11=n" %command% -dx12'), 'env WINEDLLOVERRIDES="d3d11=n;dxgi=n,b" %command% -dx12');
});

test("malformed and ambiguous shell options are refused", () => {
  for (const input of [
    'FOO="unterminated', 'FOO=1; echo hi', '%command% | cat', '%command% && true',
    '"FOO=1" %command%', "'WINEDLLOVERRIDES=dxgi=n,b' %command%",
    'FOO=$HOME %command%', 'FOO=`id` %command%', 'FOO=one\\ two %command%',
    '%command% %command%', 'prefix%command%', '"%command%"',
    'gamescope -f', '-dx12 WINEDLLOVERRIDES=dxgi=n,b',
    '%command% WINEDLLOVERRIDES=dxgi=n,b', 'gamescope WINEDLLOVERRIDES=dxgi=n,b %command%',
    'WINEDLLOVERRIDES="d3d11=n;;dxgi=n,b" %command%',
    'WINEDLLOVERRIDES="dxgi=n,b;dxgi=n,b" %command%',
  ]) assert.throws(() => proxyOptions(input), /review/i, input);
});
