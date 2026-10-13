import test from "node:test";
import assert from "node:assert/strict";

import { InstallSession, JobTracker } from "../src/installSession.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function job(id, state = "running") {
  return {
    id,
    kind: "install",
    game: "PRAGMATA",
    state,
    message: state,
    log: "",
  };
}

test("first confirmation publishes pending synchronously and invokes the backend once", async () => {
  const session = new InstallSession();
  const backend = deferred();
  const seen = [];
  let calls = 0;
  session.subscribe((state) => seen.push(state));

  const submitted = session.start("42", "PRAGMATA", () => {
    calls += 1;
    return backend.promise;
  });

  assert.equal(calls, 1);
  assert.deepEqual(session.snapshot, {
    pending: true,
    gid: "42",
    name: "PRAGMATA",
    message: "Starting HelixSR installation. Waiting for the backend; you do not need to press Install again.",
    error: "",
  });
  assert.equal(seen.at(-1).pending, true);

  backend.resolve();
  assert.equal(await submitted, true);
  assert.deepEqual(session.snapshot, {
    pending: false,
    gid: "42",
    name: "PRAGMATA",
    message: "",
    error: "",
  });
});

test("remounted panels replay state before, during, and after a rejected submission", async () => {
  const session = new InstallSession();
  const before = [];
  const unsubscribeBefore = session.subscribe((state) => before.push(state));
  assert.equal(before.at(-1).pending, false);
  unsubscribeBefore();

  const backend = deferred();
  const submitted = session.start("77", "PRAGMATA", () => backend.promise);
  const during = [];
  session.subscribe((state) => during.push(state));
  assert.equal(during.at(-1).pending, true);
  assert.equal(during.at(-1).gid, "77");

  backend.reject(new Error("backend refused terms"));
  assert.equal(await submitted, false);
  const after = [];
  session.subscribe((state) => after.push(state));
  assert.deepEqual(after.at(-1), {
    pending: false,
    gid: "77",
    name: "PRAGMATA",
    message: "",
    error: "backend refused terms",
  });
});

test("duplicate confirmation is blocked while the first request is pending", async () => {
  const session = new InstallSession();
  const backend = deferred();
  let firstCalls = 0;
  let duplicateCalls = 0;
  const first = session.start("1", "First", () => {
    firstCalls += 1;
    return backend.promise;
  });

  assert.equal(await session.start("2", "Duplicate", async () => {
    duplicateCalls += 1;
  }), false);
  assert.equal(firstCalls, 1);
  assert.equal(duplicateCalls, 0);
  assert.equal(session.snapshot.gid, "1");
  assert.equal(session.snapshot.name, "First");

  backend.resolve();
  assert.equal(await first, true);
});

test("synchronous throws and rejected tasks preserve their error until an intentional retry or clear", async () => {
  const session = new InstallSession();
  assert.equal(await session.start("1", "PRAGMATA", () => {
    throw new Error("sync backend failure");
  }), false);
  assert.equal(session.snapshot.error, "sync backend failure");

  session.clearError();
  assert.equal(session.snapshot.error, "");

  assert.equal(await session.start("1", "PRAGMATA", () => Promise.reject("plain failure")), false);
  assert.equal(session.snapshot.error, "plain failure");
  assert.equal(await session.start("1", "PRAGMATA", async () => {}), true);
  assert.equal(session.snapshot.error, "");
});

test("unsubscribe stops notifications, listener errors cannot break submission, and snapshots are defensive", async () => {
  const session = new InstallSession();
  const seen = [];
  const unsubscribe = session.subscribe((state) => seen.push(state));
  session.subscribe(() => {
    throw new Error("panel render failed");
  });
  unsubscribe();

  assert.equal(await session.start("8", "PRAGMATA", async () => {}), true);
  assert.equal(seen.length, 1);

  const snapshot = session.snapshot;
  snapshot.gid = "tampered";
  snapshot.pending = true;
  assert.equal(session.snapshot.gid, "8");
  assert.equal(session.snapshot.pending, false);
});

test("a library snapshot captured before an install cannot erase the newly running job", () => {
  const oldFlow = new JobTracker();
  const oldLibraryRevision = oldFlow.revision;
  oldFlow.update([job("new-job")]);
  assert.equal(oldFlow.update([]), true);
  assert.deepEqual(oldFlow.jobs, []);

  const tracker = new JobTracker();
  const libraryRevision = tracker.revision;
  assert.equal(tracker.update([job("new-job")]), true);
  assert.equal(tracker.update([], libraryRevision), false);
  assert.deepEqual(tracker.jobs.map((item) => item.id), ["new-job"]);
});

test("an old running snapshot cannot erase a terminal result, while fresh snapshots are accepted", () => {
  const tracker = new JobTracker();
  tracker.update([job("same", "running")]);
  const oldPollRevision = tracker.revision;
  tracker.update([job("same", "completed")]);

  assert.equal(tracker.update([job("same", "running")], oldPollRevision), false);
  assert.equal(tracker.jobs[0].state, "completed");

  const freshRevision = tracker.revision;
  assert.equal(tracker.update([job("other", "running")], freshRevision), true);
  assert.deepEqual(tracker.jobs.map((item) => item.id), ["other"]);
});

test("terminal jobs never regress even in an accepted response and distinct jobs remain independent", () => {
  const tracker = new JobTracker();
  tracker.update([job("done", "completed"), job("other", "running")]);
  const revision = tracker.revision;

  assert.equal(tracker.update([job("done", "running"), job("other", "failed")], revision), true);
  assert.deepEqual(tracker.jobs.map((item) => [item.id, item.state]), [
    ["done", "completed"],
    ["other", "failed"],
  ]);
});

test("job lists are defensively copied and stale polling responses are ignored", () => {
  const tracker = new JobTracker();
  const initial = [job("poll", "running")];
  tracker.update(initial);
  initial[0].state = "tampered";
  const pollingRevision = tracker.revision;

  tracker.update([job("new", "running")]);
  assert.equal(tracker.update([job("poll", "completed")], pollingRevision), false);
  const copy = tracker.jobs;
  copy[0].id = "tampered";
  copy.push(job("extra"));
  assert.deepEqual(tracker.jobs.map((item) => item.id), ["new"]);
});
