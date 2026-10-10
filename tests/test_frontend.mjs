import assert from "node:assert/strict";
import test from "node:test";

import { proxyOptions } from "../src/launchOptions.ts";


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
