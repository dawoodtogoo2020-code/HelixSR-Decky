import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// Execute the shipped component callbacks. The hook adapter deliberately ignores
// updates to an unmounted panel, matching the lifecycle that exposed this bug.
function harness(overrides = {}) {
  const game = { id: "pragmata", name: "PRAGMATA", folder: "/games/PRAGMATA", source: "Imported",
    compatibility: "candidate", managed: false, enabled: false, legacy: false,
    reasons: [], route: "direct", inputs: [], dx12_confirmation_needed: false,
    optiscaler: { present: false, involved: false, dlls: [], runtime: "unknown" },
    framegen: [], framegen_summary: "None", helix_runtime: "unknown", launch_options: "",
    setup_guidance: { headline: "Not installed", steps: ["Choose Install HelixSR"], notes: [], links: [] } };
  const release = { version: "1.8.1" };
  const library = () => ({ games: [game], warnings: [], release, license_accepted: false, jobs: [] });
  const calls = [], toasts = [], intervals = new Map(), modules = new Map();
  let panel, cursor, effects, modal, timer = 0;
  const handlers = { library, game_details: () => game, check_updates: () => release,
    preview_latest: () => ({ token: "reviewed-token", name: game.name, files: ["reviewed.dll"],
      warning: "Reviewed changes", model: "Model E", release_version: "1.8.1" }),
    set_license: () => true, install_latest: () => job(), job_status: () => [],
    plugin_update_status: () => ({ current_version: "0.1.21", auto_check: true }),
    overlay_status: () => ({ enabled: false }), ...overrides };
  function useState(initial) {
    const mount = panel, index = cursor++;
    if (!(index in mount.hooks)) mount.hooks[index] = typeof initial === "function" ? initial() : initial;
    return [mount.hooks[index], value => {
      if (mount.active) mount.hooks[index] = typeof value === "function" ? value(mount.hooks[index]) : value;
    }];
  }
  function useRef(initial) {
    const index = cursor++;
    if (!(index in panel.hooks)) panel.hooks[index] = { current: initial };
    return panel.hooks[index];
  }
  function useEffect(callback, deps) {
    const mount = panel, index = cursor++, old = mount.hooks[index];
    if (!old || deps.some((value, i) => value !== old.deps[i])) {
      mount.hooks[index] = { deps, cleanup: old?.cleanup };
      effects.push(() => { old?.cleanup?.(); mount.hooks[index].cleanup = callback(); });
    }
  }
  const jsx = (type, props) => ({ type, props: props || {} });
  const ui = Object.fromEntries(["ButtonItem", "DropdownItem", "PanelSection", "PanelSectionRow",
    "TextField", "ToggleField", "ConfirmModal"].map(name => [name, name]));
  ui.staticClasses = {};
  ui.showModal = (element, _window, options) => { modal = { element, options }; };
  const mocks = { "@decky/ui": ui, react: { useState, useRef, useEffect },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-icons/fa": { FaAdjust: "Icon" }, "@decky/api": {
      definePlugin: callback => callback,
      callable: route => async (...args) => {
        calls.push({ route, args });
        assert.ok(handlers[route], `Unexpected RPC ${route}`);
        return handlers[route](...args);
      }, toaster: { toast: value => toasts.push(value) }, openFilePicker: () => { throw Error("Unexpected picker"); }
    } };
  const context = vm.createContext({ console, Date, Set, Map, Promise,
    setTimeout: () => ++timer, clearTimeout: () => {},
    setInterval: (callback, ms) => { intervals.set(++timer, { callback, ms }); return timer; },
    clearInterval: id => intervals.delete(id) });
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename).exports;
    const module = { exports: {} }; modules.set(filename, module);
    const fixture = filename === path.join(source, "index.tsx") ? process.env.HELIXSR_TEST_INDEX_SOURCE : undefined;
    const compiled = ts.transpileModule(fs.readFileSync(fixture || filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
    }).outputText;
    const require = spec => {
      if (mocks[spec]) return mocks[spec];
      if (spec.startsWith(".")) return load(path.resolve(path.dirname(filename), spec + ".ts"));
      throw Error(`Unexpected dependency ${spec}`);
    };
    const fn = vm.runInContext(`(function(require,module,exports){${compiled}\n})`, context, { filename });
    fn(require, module, module.exports);
    return module.exports;
  }
  const plugin = load(path.join(source, "index.tsx")).default();
  function mount() { panel = { active: true, hooks: [] }; return render(); }
  function render() {
    cursor = 0; effects = [];
    const tree = plugin.content.type();
    effects.forEach(effect => effect());
    return tree;
  }
  function unmount() {
    panel.active = false;
    panel.hooks.forEach(value => value?.cleanup?.());
  }
  function walk(node, predicate) {
    if (Array.isArray(node)) return node.flatMap(child => walk(child, predicate));
    if (!node || typeof node !== "object") return [];
    return [...(predicate(node) ? [node] : []), ...walk(node.props?.children, predicate)];
  }
  function text(node) {
    if (Array.isArray(node)) return node.map(text).join(" ");
    if (node && typeof node === "object") return text(node.props?.children);
    return node == null || typeof node === "boolean" ? "" : String(node);
  }
  function installButton() {
    const buttons = walk(render(), node => node.type === "ButtonItem" && /Install HelixSR for this game/.test(text(node)));
    assert.equal(buttons.length, 1);
    return buttons[0];
  }
  async function openInstall() {
    const button = installButton(); assert.equal(button.props.disabled, false);
    button.props.onClick(); await flush(); assert.equal(modal.element.type, "ConfirmModal");
    return modal;
  }
  async function ready() { mount(); await flush(); render(); await flush(); render(); }
  return { game, library, calls, toasts, intervals, ready, render, mount, unmount, text, openInstall,
    count: route => calls.filter(call => call.route === route).length };
}
function job(state = "running") {
  return { id: "job-one", kind: "install_latest", gid: "pragmata", game: "PRAGMATA",
    state, message: state === "running" ? "Building local network" : "Files verified", log: "" };
}

test("first confirmation starts once and survives panel remount during both RPCs", async () => {
  const terms = deferred(), install = deferred();
  const h = harness({ set_license: () => terms.promise, install_latest: () => install.promise });
  await h.ready(); const modal = await h.openInstall(); h.unmount();
  modal.element.props.onOK(); modal.options.fnOnClose();
  h.mount(); await flush();
  assert.match(h.text(h.render()), /Starting installation/);
  assert.doesNotMatch(h.text(h.render()), /Next step: Not installed/);
  assert.equal(h.count("library"), 1, "remount must not queue discovery during submission");
  assert.equal(h.count("game_details"), 1, "remount must not queue an assessment during submission");
  modal.element.props.onOK();
  assert.equal(h.count("set_license"), 1); assert.equal(h.count("install_latest"), 0);
  terms.resolve(true); await flush(); assert.equal(h.count("install_latest"), 1);
  h.unmount(); h.mount(); await flush(); assert.match(h.text(h.render()), /Starting installation/);
  assert.equal(h.count("library"), 1);
  assert.equal(h.count("game_details"), 1);
  install.resolve(job()); await flush();
  assert.match(h.text(h.render()), /Building local network/);
  await flush();
  assert.match(h.text(h.render()), /installation is in progress/);
  assert.equal(h.count("set_license"), 1); assert.equal(h.count("install_latest"), 1);
  assert.equal(h.toasts.filter(toast => /Starting HelixSR/.test(toast.title)).length, 1);
});

test("late empty library response cannot erase the submitted job or stop polling", async () => {
  const late = deferred(), install = deferred(); let reads = 0;
  const h = harness({ library: () => ++reads === 1 ? h.library() : late.promise,
    install_latest: () => install.promise });
  await h.ready(); const modal = await h.openInstall(); h.unmount(); h.mount(); await flush();
  // This scan was started before confirmation. It cannot erase a newer job.
  assert.equal(h.count("library"), 2);
  modal.element.props.onOK(); modal.options.fnOnClose(); await flush();
  install.resolve(job()); await flush(); late.resolve(h.library()); await flush();
  assert.match(h.text(h.render()), /Building local network/);
  assert.ok([...h.intervals.values()].some(interval => interval.ms === 2000));
  assert.equal(h.count("install_latest"), 1);
});

test("submission failure stays visible after remount and never launches an unaccepted job", async () => {
  const terms = deferred(); const h = harness({ set_license: () => terms.promise });
  await h.ready(); const modal = await h.openInstall(); h.unmount();
  modal.element.props.onOK(); modal.options.fnOnClose();
  terms.reject(Error("Installation review expired; review the change again")); await flush();
  h.mount(); await flush();
  assert.match(h.text(h.render()), /Installation review expired/);
  assert.equal(h.count("install_latest"), 0);
  assert.equal(h.toasts.filter(toast => /could not start/.test(toast.title)).length, 1);
  h.unmount(); h.mount(); await flush(); assert.match(h.text(h.render()), /Installation review expired/);
});

for (const state of ["completed", "failed"]) {
  test(`an immediately ${state} job is reported and refreshes without a second click`, async () => {
    const h = harness({ install_latest: () => job(state) });
    await h.ready(); const modal = await h.openInstall(); h.unmount();
    modal.element.props.onOK(); modal.options.fnOnClose(); h.mount(); await flush();
    assert.equal(h.count("install_latest"), 1);
    assert.ok(h.toasts.some(toast => state === "completed" ? /files installed/.test(toast.title) : /operation failed/.test(toast.title)));
    assert.ok(h.count("library") >= 2);
  });
}
