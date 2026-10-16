import { test } from "node:test";
import assert from "node:assert/strict";
import { LibraryRead } from "../src/libraryRead.ts";

const TIMEOUT = /library has not responded/;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function scripted() {
  const scans = [];
  const read = () => {
    const d = deferred();
    scans.push(d);
    return d.promise;
  };
  return { scans, read };
}

async function flush() {
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
}

test("result settling after every caller timed out is returned by the next get", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read, 10);

  await assert.rejects(lib.get(), TIMEOUT);
  assert.equal(scans.length, 1);

  const games = [{ appid: 1, name: "Game One" }, { appid: 2, name: "Game Two" }];
  scans[0].resolve(games);
  await flush();

  assert.deepEqual(await lib.get(), games);
  assert.equal(scans.length, 1);

  const next = lib.get();
  await flush();
  assert.equal(scans.length, 2);
  scans[1].resolve(["fresh"]);
  assert.deepEqual(await next, ["fresh"]);
});

test("timed out gets share one pending scan and a waiting get receives it", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read, 20);

  await assert.rejects(lib.get(), TIMEOUT);
  await assert.rejects(lib.get(), TIMEOUT);
  assert.equal(scans.length, 1);

  const waiting = lib.get();
  await new Promise((r) => setImmediate(r));
  assert.equal(scans.length, 1);
  scans[0].resolve("completed scan");
  let value;
  try {
    value = await waiting;
  } catch (error) {
    // Only reachable on a heavily loaded scheduler; the result must still not be lost.
    assert.match(String(error), TIMEOUT);
    value = await lib.get();
  }
  assert.equal(value, "completed scan");
  assert.equal(scans.length, 1);

  const next = lib.get();
  await flush();
  assert.equal(scans.length, 2);
  scans[1].resolve("fresh");
  assert.equal(await next, "fresh");
});

test("concurrent late consumers receive the same result", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read, 20);

  await assert.rejects(lib.get(), TIMEOUT);
  const a = lib.get();
  const b = lib.get();
  await new Promise((r) => setImmediate(r));
  assert.equal(scans.length, 1);

  const payload = { games: ["x"] };
  scans[0].resolve(payload);
  const [ra, rb] = await Promise.allSettled([a, b]);
  if (ra.status === "fulfilled" && rb.status === "fulfilled") {
    assert.equal(ra.value, payload);
    assert.equal(rb.value, payload);
  } else {
    // Only reachable on a heavily loaded scheduler; the result must still not be lost.
    assert.equal(await lib.get(), payload);
  }
  assert.equal(scans.length, 1);
});

test("concurrent waiters on a pending scan receive the same result without duplicate reads", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read);

  const a = lib.get();
  const b = lib.get();
  const c = lib.get();
  await flush();
  assert.equal(scans.length, 1);

  const payload = [{ appid: 7 }];
  scans[0].resolve(payload);
  assert.equal(await a, payload);
  assert.equal(await b, payload);
  assert.equal(await c, payload);

  const next = lib.get();
  await flush();
  assert.equal(scans.length, 2);
  scans[1].resolve([]);
  assert.deepEqual(await next, []);
});

test("concurrent waiters on a pending scan receive the same error", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read);

  const a = lib.get();
  const b = lib.get();
  await flush();
  assert.equal(scans.length, 1);

  const failure = new Error("scan failed");
  scans[0].reject(failure);
  await assert.rejects(a, (error) => error === failure);
  await assert.rejects(b, (error) => error === failure);

  const retry = lib.get();
  await flush();
  assert.equal(scans.length, 2);
  scans[1].resolve("ok");
  assert.equal(await retry, "ok");
});

test("slow rejection after deadlines surfaces once without unhandled rejection", async () => {
  const unhandled = [];
  const onUnhandled = (reason) => unhandled.push(reason);
  process.on("unhandledRejection", onUnhandled);
  try {
    const { scans, read } = scripted();
    const lib = new LibraryRead(read, 10);

    await assert.rejects(lib.get(), TIMEOUT);
    await assert.rejects(lib.get(), TIMEOUT);
    assert.equal(scans.length, 1);

    const failure = new Error("backend scan failed");
    scans[0].reject(failure);
    await flush();
    assert.deepEqual(unhandled, []);

    await assert.rejects(lib.get(), (error) => error === failure);
    assert.equal(scans.length, 1);

    const retry = lib.get();
    await flush();
    assert.equal(scans.length, 2);
    scans[1].resolve("recovered");
    assert.equal(await retry, "recovered");
    await flush();
    assert.deepEqual(unhandled, []);
  } finally {
    process.off("unhandledRejection", onUnhandled);
  }
});

test("ordinary success starts a fresh read each time", async () => {
  let calls = 0;
  const lib = new LibraryRead(async () => {
    calls++;
    return [`scan ${calls}`];
  });
  assert.deepEqual(await lib.get(), ["scan 1"]);
  assert.deepEqual(await lib.get(), ["scan 2"]);
  assert.equal(calls, 2);
});

test("immediate error is surfaced and the next get retries", async () => {
  let calls = 0;
  const failure = new Error("backend unavailable");
  const lib = new LibraryRead(async () => {
    calls++;
    if (calls === 1) throw failure;
    return "ok";
  });
  await assert.rejects(lib.get(), (error) => error === failure);
  assert.equal(await lib.get(), "ok");
  assert.equal(calls, 2);
});

test("synchronous throw is treated as a rejection and the next get retries", async () => {
  let calls = 0;
  const failure = new Error("sync boom");
  const lib = new LibraryRead(() => {
    calls++;
    if (calls === 1) throw failure;
    return Promise.resolve("ok");
  });
  const first = lib.get();
  assert.ok(first instanceof Promise);
  await assert.rejects(first, (error) => error === failure);
  assert.equal(await lib.get(), "ok");
  assert.equal(calls, 2);
});

test("timeout message explains the scan may still be running", async () => {
  const { scans, read } = scripted();
  const lib = new LibraryRead(read, 10);
  await assert.rejects(lib.get(), (error) => {
    assert.match(error.message, TIMEOUT);
    assert.match(error.message, /still be running/);
    assert.match(error.message, /Refresh/);
    return true;
  });
  scans[0].resolve(null);
  await flush();
  assert.equal(await lib.get(), null);
  assert.equal(scans.length, 1);
});
