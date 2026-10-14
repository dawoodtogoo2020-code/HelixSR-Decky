import assert from "node:assert/strict";
import test from "node:test";

import { readLaunchOptions } from "../src/launchDetails.ts";

const validDetail = (strLaunchOptions) => ({ strLaunchOptions });

test("resolves launch options supplied synchronously and unregisters once", async () => {
  let unregisterCalls = 0;

  const result = await readLaunchOptions((listener) => {
    listener(validDetail("-dx12"));
    return { unregister: () => { unregisterCalls += 1; } };
  });

  assert.equal(result, "-dx12");
  assert.equal(unregisterCalls, 1);
});

test("resolves asynchronous options, including an empty Steam launch string", async () => {
  let unregisterCalls = 0;

  const result = await readLaunchOptions((listener) => {
    queueMicrotask(() => listener(validDetail("")));
    return { unregister: () => { unregisterCalls += 1; } };
  });

  assert.equal(result, "");
  assert.equal(unregisterCalls, 1);
});

for (const detail of [null, undefined, {}, validDetail(42), validDetail(false)]) {
  test(`rejects malformed callback detail: ${String(detail)}`, async () => {
    let unregisterCalls = 0;
    let callbackThrew = false;

    const promise = readLaunchOptions((listener) => {
      try {
        listener(detail);
      } catch {
        callbackThrew = true;
      }
      return { unregister: () => { unregisterCalls += 1; } };
    });

    await assert.rejects(
      promise,
      new Error("Steam returned invalid launch options. Reopen the game and try again."),
    );
    assert.equal(callbackThrew, false);
    assert.equal(unregisterCalls, 1);
  });
}

test("keeps the first callback result when Steam invokes the listener more than once", async () => {
  let unregisterCalls = 0;

  const result = await readLaunchOptions((listener) => {
    listener(validDetail("-first"));
    listener(validDetail("-second"));
    return { unregister: () => { unregisterCalls += 1; } };
  });

  assert.equal(result, "-first");
  assert.equal(unregisterCalls, 1);
});

test("keeps an accepted callback result when registration throws afterwards", async () => {
  const registrationFailure = new Error("register failed after callback");

  const result = await readLaunchOptions((listener) => {
    listener(validDetail("-safe"));
    throw registrationFailure;
  });

  assert.equal(result, "-safe");
});

test("rejects with the original registration failure", async () => {
  const registrationFailure = new Error("register failed");

  await assert.rejects(
    readLaunchOptions(() => { throw registrationFailure; }),
    (error) => error === registrationFailure,
  );
});

test("unregister failures do not change an already accepted result", async () => {
  const result = await readLaunchOptions((listener) => {
    queueMicrotask(() => listener(validDetail("-vulkan")));
    return { unregister: () => { throw new Error("unregister failed"); } };
  });

  assert.equal(result, "-vulkan");
});

test("times out, unregisters once, and ignores a late callback", async () => {
  let listener;
  let unregisterCalls = 0;

  const promise = readLaunchOptions((registeredListener) => {
    listener = registeredListener;
    return { unregister: () => { unregisterCalls += 1; } };
  }, 20);

  await assert.rejects(promise, new Error("Steam did not provide live launch options"));
  assert.equal(unregisterCalls, 1);

  assert.doesNotThrow(() => listener(validDetail("-late")));
  assert.equal(unregisterCalls, 1);
});

test("does not clean up twice after an early callback passes the timeout window", async () => {
  let unregisterCalls = 0;

  const result = await readLaunchOptions((listener) => {
    setTimeout(() => listener(validDetail("-immediate")), 1);
    return { unregister: () => { unregisterCalls += 1; } };
  }, 25);

  assert.equal(result, "-immediate");
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(unregisterCalls, 1);
});
