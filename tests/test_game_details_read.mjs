import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { GameDetailsRead } from '../src/gameDetailsRead.ts';

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('details deadline releases the actual panel action busy state and reports recovery', async () => {
  const source = fs.readFileSync(new URL('../src/index.tsx', import.meta.url), 'utf8');
  const start = source.indexOf('  async function run<T>');
  const end = source.indexOf('  async function refresh(', start);
  assert(start >= 0 && end > start);
  const action = source.slice(start, end).replace(
    'async function run<T>(fn: () => Promise<T>): Promise<T | undefined>', 'async function run(fn)');
  let busy = false, error = '';
  const run = Function('setBusy', 'setError', 'toaster', `${action}; return run;`)(
    value => { busy = value; }, value => { error = value; }, { toast() {} });
  const pending = deferred();
  const reads = new GameDetailsRead(() => pending.promise, 10);
  const result = run(() => reads.get('a'));
  assert.equal(busy, true);
  assert.equal(await result, undefined);
  assert.equal(busy, false);
  assert.match(error, /Game details have not responded/);
  assert.match(error, /Select another game or press Refresh/);
  pending.resolve('late');
  await tick();
  assert.equal(busy, false);
  assert.match(source, /gameDetailsRead\.get\(selected, requestedExecutable\)/);
  assert.match(source, /gameDetailsRead\.get\(id, path\)/);
  assert.match(source, /g && active && selectedRef\.current === selected && executableRef\.current === requestedExecutable/);
});

test('late response after timeout cannot overwrite a newer successful selection', async () => {
  const old = deferred();
  const reads = new GameDetailsRead(id => id === 'old' ? old.promise : Promise.resolve('new details'), 10);
  let displayed;
  const oldConsumer = reads.get('old').then(value => { displayed = value; });
  await assert.rejects(oldConsumer, /Game details have not responded/);
  displayed = await reads.get('new');
  old.resolve('obsolete details');
  await tick();
  assert.equal(displayed, 'new details');
});

test('retry shares a timed-out read, then fresh refresh starts another after completion', async () => {
  const first = deferred();
  let calls = 0;
  const reads = new GameDetailsRead(() => ++calls === 1 ? first.promise : Promise.resolve('fresh'), 10);
  await assert.rejects(reads.get('a', 'game.exe'), /Game details have not responded/);
  const retry = reads.get('a', 'game.exe');
  first.resolve('completed');
  assert.equal(await retry, 'completed');
  assert.equal(calls, 1);
  assert.equal(await reads.get('a', 'game.exe'), 'fresh');
  assert.equal(calls, 2);
});

test('executable choices have independent reads and rejection permits retry', async () => {
  const first = deferred();
  const calls = [];
  const reads = new GameDetailsRead((id, exe) => {
    calls.push([id, exe]);
    return exe === 'old.exe' ? first.promise : Promise.resolve('new executable');
  }, 10);
  await assert.rejects(reads.get('a', 'old.exe'), /Game details have not responded/);
  assert.equal(await reads.get('a', 'new.exe'), 'new executable');
  first.reject(new Error('late transport failure'));
  await tick();
  await assert.rejects(reads.get('a', 'old.exe'), /late transport failure/);
  assert.equal(calls.length, 3);
});
