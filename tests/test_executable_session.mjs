import { test } from "node:test";
import assert from "node:assert/strict";

import { ExecutableSession, executableSession } from "../src/executableSession.ts";

const EXE_A = "C:/Games/Alpha/alpha.exe";
const EXE_B = "C:/Games/Alpha/bin/alpha-dx12.exe";

test("same game refresh and remount keep the chosen executable via the singleton", () => {
  executableSession.selectGame("alpha");
  executableSession.choose("alpha", EXE_B);

  // Simulated remount: a new component re-selects the same game and reads back.
  executableSession.selectGame("alpha");
  assert.equal(executableSession.get("alpha"), EXE_B);

  // Simulated refresh with a scan that still offers the path.
  executableSession.reconcile({
    id: "alpha",
    route: "optiscaler",
    managed: false,
    executable_choices: [{ path: EXE_A }, { path: EXE_B }],
    selected_executable: EXE_A,
  });
  assert.equal(executableSession.get("alpha"), EXE_B);

  executableSession.clear("alpha");
  assert.equal(executableSession.get("alpha"), undefined);
});

test("selecting a different game clears the prior path", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.selectGame("beta");
  assert.equal(session.get("beta"), undefined);
  assert.equal(session.get("alpha"), undefined);
  session.selectGame("alpha");
  assert.equal(session.get("alpha"), undefined);
});

test("get only answers for the current game", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  assert.equal(session.get("beta"), undefined);
  assert.equal(session.get("alpha"), EXE_A);
});

test("managed game invalidates the selection", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.reconcile({ id: "alpha", managed: true, route: "optiscaler", executable_choices: [{ path: EXE_A }] });
  assert.equal(session.get("alpha"), undefined);
});

test("non-optiscaler route invalidates the selection", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.reconcile({ id: "alpha", route: "direct", executable_choices: [{ path: EXE_A }] });
  assert.equal(session.get("alpha"), undefined);
});

test("omitted route and omitted choices preserve the selection", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.reconcile({ id: "alpha" });
  assert.equal(session.get("alpha"), EXE_A);
  session.reconcile({ id: "alpha", route: "optiscaler", managed: false });
  assert.equal(session.get("alpha"), EXE_A);
});

test("provided empty choices are authoritative and clear the selection", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.reconcile({ id: "alpha", route: "optiscaler", executable_choices: [] });
  assert.equal(session.get("alpha"), undefined);
});

test("provided choices missing the selected path clear it", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  session.reconcile({ id: "alpha", route: "optiscaler", executable_choices: [{ path: EXE_B }] });
  assert.equal(session.get("alpha"), undefined);
});

test("heuristic selected_executable is never adopted as a choice", () => {
  const session = new ExecutableSession();
  session.selectGame("alpha");
  session.reconcile({
    id: "alpha",
    route: "optiscaler",
    executable_choices: [{ path: EXE_A }],
    selected_executable: EXE_A,
  });
  assert.equal(session.get("alpha"), undefined);
});

test("empty choose is rejected and leaves state unchanged", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);
  assert.throws(() => session.choose("alpha", ""), TypeError);
  assert.throws(() => session.choose("alpha", "   "), TypeError);
  assert.throws(() => session.choose("beta", ""), TypeError);
  assert.equal(session.get("alpha"), EXE_A);
  assert.equal(session.get("beta"), undefined);
});

test("stale reconcile and clear for an unrelated game do not affect the current one", () => {
  const session = new ExecutableSession();
  session.choose("alpha", EXE_A);

  session.reconcile({ id: "beta", managed: true });
  session.reconcile({ id: "beta", route: "direct" });
  session.reconcile({ id: "beta", route: "optiscaler", executable_choices: [] });
  session.clear("beta");

  assert.equal(session.get("alpha"), EXE_A);
  assert.equal(session.get("beta"), undefined);
});

test("module exports a shared ExecutableSession singleton", () => {
  assert.ok(executableSession instanceof ExecutableSession);
});
