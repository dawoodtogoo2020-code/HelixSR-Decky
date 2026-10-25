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
  const calls = [], toasts = [], intervals = new Map(), timeouts = new Map(), modules = new Map();
  let panel, cursor, effects, modal, timer = 0;
  const handlers = { library, game_details: () => game, check_updates: () => release,
    preview_latest: () => ({ token: "reviewed-token", name: game.name, files: ["reviewed.dll"],
      warning: "Reviewed changes", model: "Model E", release_version: "1.8.1" }),
    set_license: () => true, install_latest: () => job(), job_status: () => [],
    preview_action: (_id, action) => ({ token: "menu-token", action, name: game.name,
      files: ["graphics.xml"], warning: "Cosmetic label only", select_upscaler: "Helix SR", route: "direct" }),
    apply_action: () => ({message: "Reviewed change complete"}),
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
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
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
    setTimeout: (callback, ms) => { timeouts.set(++timer, {callback, ms}); return timer; },
    clearTimeout: id => timeouts.delete(id),
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
      if (spec.startsWith(".")) {
        const base = path.resolve(path.dirname(filename), spec);
        return load(fs.existsSync(base + '.ts') ? base + '.ts' : base + '.tsx');
      }
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
  function openAdvanced() {
    const button = walk(render(), node => node.type === "ButtonItem" && text(node) === "Show game settings")[0];
    if (button) button.props.onClick();
    render();
  }
  function menuToggle() {
    const toggle = walk(render(), node => node.type === "ToggleField" && node.props.label === "Use HelixSR menu labels")[0];
    assert.ok(toggle, "optional menu label toggle is visible"); return toggle;
  }
  async function openMenuChange(enabled) {
    const toggle = menuToggle(); assert.equal(toggle.props.disabled, false);
    toggle.props.onChange(enabled); await flush(); assert.equal(modal.element.type, "ConfirmModal");
    return modal;
  }
  async function chooseExecutable(path) {
    const dropdown = walk(render(), node => node.type === "DropdownItem" && node.props.label === "Game executable")[0];
    assert.ok(dropdown, "Game executable selector is visible");
    dropdown.props.onChange({ data: path }); await flush(); render();
  }
  return { game, library, calls, toasts, intervals, timeouts, ready, render, mount, unmount, text, openInstall,
    chooseExecutable, menuToggle, openMenuChange, openAdvanced, walk, installButton,
    count: route => calls.filter(call => call.route === route).length };
}
function job(state = "running") {
  return { id: "job-one", kind: "install_latest", gid: "pragmata", game: "PRAGMATA",
    state, message: state === "running" ? "Building local network" : "Files verified", log: "" };
}

test("protected games remain in the dropdown with diagnostics and installation blocked", async () => {
  const h = harness();
  Object.assign(h.game, {name: "skate", appid: "123456", compatibility: "blocked", route: "optiscaler",
    reasons: ["Anti-cheat files detected; injection is blocked"],
    installation_status: {state: "review", label: "Needs review", selectable: false,
      can_modify: false, can_restore: false, running: false,
      summary: "Anti-cheat files detected; injection is blocked", issues: []}});
  await h.ready();
  const dropdown = h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === "Game")[0];
  assert.equal(dropdown.props.rgOptions.length, 1);
  assert.equal(dropdown.props.rgOptions[0].data, h.game.id);
  assert.match(h.text(dropdown.props.rgOptions[0].label), /skate.*Needs review/);
  assert.match(h.text(h.render()), /Anti-cheat files detected/);
  assert.equal(h.installButton().props.disabled, true);
  h.openAdvanced();
  const proxy = h.walk(h.render(), n => n.type === "ButtonItem" && /Review Proton proxy launch option/.test(h.text(n)))[0];
  assert.ok(proxy);
  assert.equal(proxy.props.disabled, true);
  proxy.props.onClick(); await flush();
  assert.equal(h.count("owned_launch_options"), 0);
  assert.equal(h.count("preview_latest"), 0);
  assert.equal(h.count("install_latest"), 0);
});

test("an unresponsive backend ends loading, exposes an error, and shares its pending scan across remounts", async () => {
  const pending = deferred();
  const h = harness({library: () => pending.promise});
  await h.ready();
  assert.match(h.text(h.render()), /Detecting installed games/);
  const deadline = [...h.timeouts.values()].find(t => t.ms === 30000);
  assert.ok(deadline);
  deadline.callback(); await flush();
  assert.match(h.text(h.render()), /Library scan failed/);
  assert.match(h.text(h.render()), /backend could not start/);
  const refresh = h.walk(h.render(), n => n.type === "ButtonItem" && /Refresh library and status/.test(h.text(n)))[0];
  assert.equal(refresh.props.disabled, false);
  refresh.props.onClick(); await flush();
  h.unmount(); h.mount(); await flush();
  assert.equal(h.count("library"), 2);
  pending.resolve(h.library()); await flush(); h.render(); await flush();
  assert.match(h.text(h.render()), /1 games found/);
  assert.doesNotMatch(h.text(h.render()), /Library scan failed/);
});

test("a blocked enabled installation cannot enable the Proton proxy", async () => {
  const h = harness();
  Object.assign(h.game, {appid: "123456", compatibility: "blocked", route: "optiscaler",
    managed: true, enabled: true,
    installation_status: {state: "review", label: "Needs review", selectable: true,
      can_modify: false, can_restore: false, running: false, summary: "Anti-cheat detected", issues: []}});
  await h.ready();
  h.openAdvanced();
  const proxy = h.walk(h.render(), n => n.type === "ButtonItem" && /Review Proton proxy launch option/.test(h.text(n)))[0];
  assert.ok(proxy);
  assert.equal(proxy.props.disabled, true);
  proxy.props.onClick(); await flush();
  assert.equal(h.count("owned_launch_options"), 0);
  assert.equal(h.count("prepare_launch_options"), 0);
});

test("menu labels stay off until review applies and the backend refresh confirms them", async () => {
  const h = harness({apply_action: () => {
    h.game.menu_labels.enabled = true;
    return {message: "Menu label verified"};
  }});
  Object.assign(h.game, {managed: true, enabled: true, menu_labels: {available: true,
    supported: true, enabled: false, label: "Helix SR", reason: "Original menu retained", experimental: true}});
  await h.ready();
  h.openAdvanced();
  assert.equal(h.menuToggle().props.checked, false);
  const modal = await h.openMenuChange(true);
  assert.equal(h.calls.filter(c => c.route === "preview_action").at(-1).args[1], "labels_enable");
  assert.equal(h.count("apply_action"), 0);
  assert.equal(h.menuToggle().props.checked, false);
  assert.match(modal.element.props.strTitle, /Enable Helix SR menu labels/);
  modal.element.props.onOK(); modal.options.fnOnClose(); await flush(); h.render(); await flush(); h.render();
  assert.equal(h.count("apply_action"), 1);
  assert.equal(h.menuToggle().props.checked, true);
});

test("eligible missing managed files use the existing reviewed repair action", async () => {
  const reason = "Managed HelixSR files are missing: nvngx.dll";
  const h = harness();
  Object.assign(h.game, {managed: true, enabled: false, repair_eligible: true, repair_files: ["nvngx.dll"],
    installation_status: {state: "review", label: "Repair available", selectable: true,
      can_modify: false, can_restore: true, can_repair: true, running: false, summary: reason,
      issues: [{code: "managed_files_missing", title: "HelixSR files missing", reason,
        steps: ["Choose Repair HelixSR files."], blocking: true}]}});
  await h.ready();
  const tree = h.render();
  assert.equal((h.text(tree).match(/Managed HelixSR files are missing/g) || []).length, 1);
  const button = h.walk(tree, node => node.type === "ButtonItem" && /Repair HelixSR files/.test(h.text(node)))[0];
  assert.ok(button, h.text(tree));
  assert.equal(button.props.disabled, false);
  button.props.onClick(); await flush();
  assert.equal(h.calls.filter(call => call.route === "preview_action").at(-1).args[1], "repair");
  assert.equal(h.count("apply_action"), 0);
});

test("unsupported menu profiles are disabled with an explanation", async () => {
  const h = harness();
  Object.assign(h.game, {managed: true, enabled: true, menu_labels: {available: false,
    supported: false, enabled: false, label: "Helix SR", reason: "Verified profile unavailable", experimental: true}});
  await h.ready();
  h.openAdvanced();
  assert.equal(h.menuToggle().props.disabled, true);
  assert.match(h.text(h.render()), /Verified profile unavailable/);
  assert.match(h.text(h.render()), /does not verify the active upscaler/);
  assert.equal(h.count("apply_action"), 0);
});

test("disabling menu labels uses a reviewed restore request and cancel changes nothing", async () => {
  const h = harness();
  Object.assign(h.game, {managed: true, enabled: true, menu_labels: {available: true,
    supported: true, enabled: true, label: "Helix SR", reason: "Enabled", experimental: true}});
  await h.ready();
  h.openAdvanced();
  const modal = await h.openMenuChange(false);
  assert.match(modal.element.props.strTitle, /Restore original menu labels/);
  assert.equal(h.calls.filter(c => c.route === "preview_action").at(-1).args[1], "labels_disable");
  modal.options.fnOnClose(); await flush();
  assert.equal(h.menuToggle().props.checked, true);
  assert.equal(h.count("apply_action"), 0);
});

test("explicit executable survives a real panel remount and is used for install review", async () => {
  const h = harness({ game_details: (_id, executable) => ({ ...h.game,
    selected_executable: executable || "DX11/Game.exe" }) });
  Object.assign(h.game, { route: "optiscaler", selected_executable: "DX11/Game.exe",
    executable_choices: [{ path: "DX11/Game.exe", dx12: false }, { path: "DX12/Game.exe", dx12: true }] });
  await h.ready(); await h.chooseExecutable("DX12/Game.exe");
  h.unmount(); h.mount(); await flush(); h.render(); await flush(); h.render();
  assert.equal(h.calls.filter(call => call.route === "game_details").at(-1).args[1], "DX12/Game.exe");
  await h.openInstall();
  assert.equal(h.calls.filter(call => call.route === "preview_latest").at(-1).args[3], "DX12/Game.exe");
});

test("a failed selection request from an old panel cannot clear the new panel's choice", async () => {
  const old = deferred(); let selectedReads = 0;
  const h = harness({ game_details: (_id, executable) => {
    if (executable && ++selectedReads === 1) return old.promise;
    return { ...h.game, selected_executable: executable || "DX11/Game.exe" };
  } });
  Object.assign(h.game, { route: "optiscaler", selected_executable: "DX11/Game.exe",
    executable_choices: [{ path: "DX11/Game.exe", dx12: false }, { path: "DX12/Game.exe", dx12: true }] });
  await h.ready(); await h.chooseExecutable("DX12/Game.exe");
  h.unmount(); h.mount(); await flush(); h.render(); await flush(); h.render();
  old.reject(Error("Old panel request failed")); await flush();
  h.unmount(); h.mount(); await flush(); h.render(); await flush(); h.render();
  assert.equal(h.calls.filter(call => call.route === "game_details").at(-1).args[1], "DX12/Game.exe");
});

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

test("panel remount reuses the library snapshot and cannot erase the submitted job", async () => {
  const install = deferred();
  const h = harness({ install_latest: () => install.promise });
  await h.ready(); const modal = await h.openInstall(); h.unmount(); h.mount(); await flush();
  assert.equal(h.count("library"), 1);
  modal.element.props.onOK(); modal.options.fnOnClose(); await flush();
  install.resolve(job()); await flush();
  assert.match(h.text(h.render()), /Building local network/);
  assert.ok([...h.intervals.values()].some(interval => interval.ms === 2000));
  assert.equal(h.count("install_latest"), 1);
});

test("a terminal job observed while unmounted invalidates the snapshot for the next mount", async () => {
  const h = harness({ job_status: () => [job("completed")] });
  await h.ready();
  const modal = await h.openInstall();
  modal.element.props.onOK(); modal.options.fnOnClose(); await flush();
  assert.ok([...h.intervals.values()].some(interval => interval.ms === 2000));
  h.unmount();
  const scansBefore = h.count("library");
  [...h.intervals.values()].filter(interval => interval.ms === 2000).forEach(interval => interval.callback());
  await flush();
  h.mount(); await flush(); h.render(); await flush();
  assert.equal(h.count("library"), scansBefore + 1);
});

test("checked release metadata survives a panel remount without a library scan", async () => {
  const checked = {version: "2.1.0", supported: false, support_reason: "Not reviewed"};
  const h = harness({check_updates: () => checked});
  await h.ready();
  const updates = h.walk(h.render(), node => node.type === "ButtonItem" && /Game release and plugin updates/.test(h.text(node)))[0];
  updates.props.onClick();
  const check = h.walk(h.render(), node => node.type === "ButtonItem" && /Check latest HelixSR version/.test(h.text(node)))[0];
  check.props.onClick(); await flush(); h.render();
  assert.match(h.text(h.render()), /Latest found:\s+2\.1\.0/);
  const scansBefore = h.count("library");
  h.unmount(); h.mount(); await flush(); h.render();
  assert.equal(h.count("library"), scansBefore);
  const reopened = h.walk(h.render(), node => node.type === "ButtonItem" && /Game release and plugin updates/.test(h.text(node)))[0];
  reopened.props.onClick();
  assert.match(h.text(h.render()), /Latest found:\s+2\.1\.0/);
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

test("explicit compatible release survives remount and confirms its exact version without a latest lookup", async () => {
  const h = harness({ check_updates: () => { throw Error("Latest lookup must stay separate"); },
    preview_latest: (_gid, _dx12, _model, _exe, choice) => {
      assert.equal(choice, "compatible-1.8.1");
      return { token: "compat-token", name: "PRAGMATA", files: ["reviewed.dll"], warning: "Compatibility release, not the latest Scaler engine",
        model: "Model E", release_version: "1.8.1", license_accepted: false,
        license_url: "https://github.com/lonewolf0622/HelixSR/blob/v1.8.1/LICENSE" };
    } });
  await h.ready();
  const dropdown = h.walk(h.render(), node => node.type === "DropdownItem" && node.props.label === "Release to install")[0];
  assert.ok(dropdown);
  dropdown.props.onChange({ data: "compatible-1.8.1" });
  h.unmount(); h.mount(); await flush(); h.render(); await flush(); h.render();
  const modal = await h.openInstall();
  assert.match(modal.element.props.strTitle, /1\.8\.1/);
  assert.equal(modal.element.props.strOKButtonText, "Accept terms and install");
  assert.ok(h.walk(modal.element.props.strDescription, node => node.type === "a"
    && node.props.href === "https://github.com/lonewolf0622/HelixSR/blob/v1.8.1/LICENSE").length);
  assert.equal(h.count("check_updates"), 0);
  modal.element.props.onOK(); await flush();
  assert.equal(h.count("set_license"), 1);
  assert.equal(h.count("install_latest"), 1);
  assert.equal(h.calls.find(call => call.route === "set_license").args[1], "compat-token");
});


test("primary controls precede collapsed game settings, updates, and import", async () => {
  const h = harness(); await h.ready();
  const tree = h.render();
  const dropdowns = h.walk(tree, n => n.type === "DropdownItem");
  assert.deepEqual(dropdowns.slice(0, 2).map(n => n.props.label), ["Game", "Release to install"]);
  const sections = h.walk(tree, n => n.type === "PanelSection").map(n => n.props.title);
  assert.ok(sections.indexOf("Game settings") < sections.indexOf("Plugin updates"));
  assert.ok(sections.indexOf("Plugin updates") < sections.indexOf("Import games"));
  assert.equal(h.walk(tree, n => n.type === "ToggleField" && /status overlay/.test(n.props.label)).length, 0);
  h.openAdvanced();
  const expanded = h.render();
  assert.equal(h.walk(expanded, n => n.type === "ToggleField" && /status overlay/.test(n.props.label)).length, 1);
  const expandedSections = h.walk(expanded, n => n.type === "PanelSection").map(n => n.props.title);
  assert.ok(expandedSections.indexOf("Upscaling and frame generation") < expandedSections.indexOf("Status overlay"));
  assert.ok(expandedSections.indexOf("Status overlay") < expandedSections.indexOf("Game actions"));
});

test("setup details stay compact while blocking issues remain visible", async () => {
  const h = harness();
  h.game.dx12_confirmation_needed = true;
  h.game.setup_guidance = { headline: "Set up DX12", steps: ["Choose DX12 in the game", "Install REFramework after launch"],
    notes: ["Extra setup note"], links: [{label: "Setup guide", url: "https://example.com/setup"}] };
  h.game.installation_status = {state: "review", label: "Needs review", summary: "Check compatibility",
    running: false, selectable: true, can_modify: false, issues: [
      {code: "protected", title: "Blocking issue", reason: "Review game files", steps: ["Resolve files"], blocking: true},
      {code: "dx12_unconfirmed", title: "DX12 issue", reason: "Confirm DX12", steps: ["Choose DX12"], blocking: false}
    ]};
  await h.ready();
  let tree = h.render();
  assert.match(h.text(tree), /Choose DX12 in the game/);
  assert.match(h.text(tree), /Blocking issue/);
  assert.doesNotMatch(h.text(tree), /DX12 issue|Install REFramework after launch|Extra setup note|Setup guide/);
  const details = h.walk(tree, n => n.type === "ButtonItem" && h.text(n) === "Setup details")[0];
  assert.ok(details);
  details.props.onClick();
  tree = h.render();
  assert.match(h.text(tree), /Install REFramework after launch|Extra setup note|Setup guide/);
});

test("selected game dropdown refreshes its label after external enable", async () => {
  let enabled = false;
  const h = harness({
    library: () => ({...h.library(), games: [{...h.game, managed: true, enabled: false, installed_version: "2.0.0"}]}),
    game_details: () => ({...h.game, managed: true, enabled, installed_version: "2.0.0"})
  });
  await h.ready();
  const dropdown = () => h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === "Game")[0];
  const before = dropdown();
  assert.match(h.text(before.props.rgOptions[0].label), /Disabled/);
  enabled = true;
  const refresh = h.walk(h.render(), n => n.type === "ButtonItem" && /Refresh library and status/.test(h.text(n)))[0];
  refresh.props.onClick(); await flush(); h.render(); await flush();
  const after = dropdown();
  assert.match(h.text(after.props.rgOptions[0].label), /Enabled/);
  assert.notEqual(after.key, before.key, "Decky dropdown remounts when the selected status changes");
});

function renderedHelixSettings(h) {
  const node = h.walk(h.render(), n => typeof n.type === "function" && n.type.name === "HelixSettings")[0];
  assert.ok(node, "Helix settings component is present in Game settings");
  // HelixSettings is a pure nested function component. Render it directly so
  // these tests exercise its actual dropdown callbacks through the panel save path.
  return node.type(node.props);
}
function settingsDropdown(h, label) {
  const node = h.walk(renderedHelixSettings(h), n => n.type === "DropdownItem" && n.props.label === label)[0];
  assert.ok(node, `settings dropdown ${label} is visible`);
  return node;
}
function enableSettings(h, extra = {}) {
  Object.assign(h.game, { managed: true, enabled: true, route: "optiscaler", helix_settings: {
    available: true, revision: "settings-rev-7", provider: "helixsr", model: "full", quick_flow: "fast",
    multiplier: 2, upscaler: "helixsr", int8: "auto", wave_size: "auto", ...extra
  }});
}

test("FG controls stay visible while optional game settings and tuning retain disclosure choices", async () => {
  const h = harness(); enableSettings(h); await h.ready();
  assert.equal(h.walk(h.render(), n => typeof n.type === "function" && n.type.name === "HelixSettings").length, 1,
    "frame generation is discoverable without opening optional settings");
  h.openAdvanced();
  let settings = h.walk(h.render(), n => typeof n.type === "function" && n.type.name === "HelixSettings")[0];
  assert.equal(settings.props.advanced, false, "tuning starts collapsed");
  assert.ok(settingsDropdown(h, "QuickFlow"), "Full model controls are visible before remount");
  settings.props.toggleAdvanced(); h.render();
  assert.ok(settingsDropdown(h, "INT8 math"), "advanced tuning is visible before remount");

  h.unmount(); h.mount(); await flush(); h.render(); await flush();
  settings = h.walk(h.render(), n => typeof n.type === "function" && n.type.name === "HelixSettings")[0];
  assert.ok(settings, "game settings remain open after remount");
  assert.equal(settings.props.advanced, true, "advanced tuning remains open after remount");
  assert.ok(settingsDropdown(h, "QuickFlow"), "Full model controls remain reachable after remount");
  assert.ok(settingsDropdown(h, "INT8 math"));

  settings.props.toggleAdvanced(); h.render();
  const close = h.walk(h.render(), n => n.type === "ButtonItem" && h.text(n) === "Hide game settings")[0];
  close.props.onClick(); h.render();
  h.unmount(); h.mount(); await flush(); h.render(); await flush();
  assert.equal(h.walk(h.render(), n => typeof n.type === "function" && n.type.name === "HelixSettings").length, 1,
    "closing optional settings does not hide frame generation");
  assert.equal(h.walk(renderedHelixSettings(h), n => n.type === "DropdownItem" && n.props.label === "INT8 math").length, 0,
    "advanced tuning remains collapsed after remount");
});

test("Helix settings provider, model, and multiplier callbacks preserve the current revision", async () => {
  async function change(label, data, settings = {}) {
    const h = harness({ set_game_settings: () => h.game });
    enableSettings(h, settings); await h.ready(); h.openAdvanced();
    const control = settingsDropdown(h, label);
    control.props.onChange({ data }); await flush();
    return { h, control };
  }
  const model = await change("Frame generation model", "light");
  assert.deepEqual(JSON.parse(JSON.stringify(model.h.calls.at(-1))), { route: "set_game_settings", args: ["pragmata", { model: "light", quick_flow: "off" }, "settings-rev-7"] });
  const provider = await change("Frame generation", "xess");
  assert.deepEqual(JSON.parse(JSON.stringify(provider.h.calls.at(-1))), { route: "set_game_settings", args: ["pragmata", { provider: "xess", multiplier: 2 }, "settings-rev-7"] });
  const multiplier = await change("Frame multiplier", 3, { provider: "xess" });
  assert.deepEqual(JSON.parse(JSON.stringify(multiplier.control.props.rgOptions.map(option => option.data))), [2, 3]);
  assert.deepEqual(JSON.parse(JSON.stringify(multiplier.h.calls.at(-1))), { route: "set_game_settings", args: ["pragmata", { multiplier: 3 }, "settings-rev-7"] });
});

test("Helix settings exposes save failures and disables edits during a running job", async () => {
  const h = harness({ library: () => ({ ...h.library(), jobs: [job()] }),
    set_game_settings: () => { throw Error("Settings changed; refresh before saving"); } });
  enableSettings(h); await h.ready(); h.openAdvanced();
  assert.equal(settingsDropdown(h, "Upscaler").props.disabled, true, "running install locks settings");
  // The backend may reject a save after a stale revision even if the UI was enabled.
  const editable = harness({ set_game_settings: () => { throw Error("Settings changed; refresh before saving"); } });
  enableSettings(editable); await editable.ready(); editable.openAdvanced();
  settingsDropdown(editable, "Upscaler").props.onChange({ data: "fsr" }); await flush();
  assert.match(editable.text(editable.render()), /Settings changed; refresh before saving/);
  assert.ok(editable.toasts.some(toast => /action could not complete/.test(toast.title)));
});
