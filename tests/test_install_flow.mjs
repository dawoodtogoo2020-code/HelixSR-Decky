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
  return { game, library, calls, toasts, intervals, timeouts, context, ready, render, mount, unmount, text, openInstall,
    chooseExecutable, menuToggle, openMenuChange, openAdvanced, walk, installButton,
    currentModal: () => modal,
    count: route => calls.filter(call => call.route === route).length };
}
function job(state = "running") {
  return { id: "job-one", kind: "install_latest", gid: "pragmata", game: "PRAGMATA",
    state, message: state === "running" ? "Building local network" : "Files verified", log: "" };
}

for (const route of ["direct", "optiscaler"]) {
  for (const enabled of [true, false]) {
    for (const action of [enabled ? "disable" : "enable", "remove"]) {
    test(`${route} ${enabled ? "enabled" : "disabled"} setup exposes ${action} before optional settings and requires review`, async () => {
      const h = harness({preview_action: (_id, action) => ({token: "restore-token", action,
        name: "PRAGMATA", route, files: ["saved-original.dll"], warning: "Close the game.", select_upscaler: "AMD FSR"})});
      Object.assign(h.game, {managed: true, enabled, route});
      await h.ready();
      const buttons = () => h.walk(h.render(), n => n.type === "ButtonItem");
      const named = label => buttons().filter(n => h.text(n) === label);
      const toggle = enabled ? "Disable HelixSR" : "Enable HelixSR";
      for (const label of [toggle, "Remove and restore originals"]) {
        assert.equal(named(label).length, 1);
        assert.equal(named(label)[0].props.disabled, false);
        const labels = buttons().map(n => h.text(n));
        assert.ok(labels.indexOf(label) < labels.indexOf("Refresh library and status"),
          "restoration is beside the primary action, before settings and library controls");
      }
      assert.equal(named(enabled ? "Enable HelixSR" : "Disable HelixSR").length, 0);
      h.openAdvanced();
      assert.equal(named(toggle).length, 1, "opening optional settings does not duplicate controls");
      assert.equal(named("Remove and restore originals").length, 1);
      {
        const label = action === "remove" ? "Remove and restore originals" : toggle;
        const before = h.count("apply_action");
        named(label)[0].props.onClick(); await flush();
        assert.equal(h.calls.filter(c => c.route === "preview_action").at(-1).args[1], action);
        assert.equal(h.count("apply_action"), before, "opening the review does not change game files");
        const modal = h.currentModal();
        assert.equal(modal.element.props.strOKButtonText, label);
        if (action !== "enable") {
          assert.match(h.text(modal.element.props.strDescription), /files saved before HelixSR was installed/);
          assert.doesNotMatch(h.text(modal.element.props.strDescription), /In game: select/);
          if (route === "optiscaler") assert.match(h.text(modal.element.props.strDescription), /Restore plugin launch-option change/);
        }
        modal.element.props.onOK(); await flush();
        assert.equal(h.count("apply_action"), before + 1);
        assert.equal(h.calls.filter(c => c.route === "apply_action").at(-1).args[0], "restore-token");
        modal.options.fnOnClose(); await flush();
      }
    });
    }
  }
}

test("visible restoration controls retain file review, running job and plugin update guards", async () => {
  for (const state of ["file-review", "running-game", "install-job", "plugin-update"]) {
    const h = harness(state === "install-job" ? {library: () => ({...h.library(), jobs: [job()]})}
      : state === "plugin-update" ? {plugin_update_status: () => ({current_version: "0.1.41", pending: {version: "0.1.42"}})} : {});
    Object.assign(h.game, {managed: true, enabled: true});
    if (["file-review", "running-game"].includes(state)) h.game.installation_status = {
      state: state === "running-game" ? "running" : "review", label: "Needs review", summary: "Close game or resolve file conflict",
      running: state === "running-game", can_modify: false, can_restore: false, issues: []};
    await h.ready();
    for (const label of ["Disable HelixSR", "Remove and restore originals"]) {
      const button = h.walk(h.render(), n => n.type === "ButtonItem" && h.text(n) === label)[0];
      assert.ok(button, `${state}: action remains discoverable`);
      assert.equal(button.props.disabled, true, `${state}: action stays blocked`);
    }
    assert.equal(h.count("apply_action"), 0);
  }
});

test("unmanaged games do not offer managed restoration controls", async () => {
  const h = harness(); await h.ready();
  assert.equal(h.walk(h.render(), n => n.type === "ButtonItem" &&
    ["Disable HelixSR", "Enable HelixSR", "Remove and restore originals"].includes(h.text(n))).length, 0);
});

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
  assert.doesNotMatch(h.text(tree), /Managed HelixSR files are missing/);
  assert.match(h.text(tree), /Choose Repair HelixSR files/);
  const details = h.walk(tree, node => node.type === "ButtonItem" && h.text(node) === "Setup details")[0];
  assert.ok(details);
  details.props.onClick();
  assert.match(h.text(h.render()), /Managed HelixSR files are missing/);
  const button = h.walk(tree, node => node.type === "ButtonItem" && /Repair HelixSR files/.test(h.text(node)))[0];
  assert.ok(button, h.text(tree));
  assert.equal(button.props.disabled, false);
  button.props.onClick(); await flush();
  assert.equal(h.calls.filter(call => call.route === "preview_action").at(-1).args[1], "repair");
  assert.equal(h.count("apply_action"), 0);
});

function resetGame(h, eligible = true, canReset = true) {
  Object.assign(h.game, {managed: true, enabled: true, compatibility: "blocked", reset_eligible: eligible,
    repair_eligible: true, reset_reason: eligible ? undefined : "Close Steam before resetting.",
    installation_status: {state: "review", label: "Needs review", selectable: true, running: false,
      can_modify: false, can_repair: true, can_reset: canReset, summary: "Game build changed",
      issues: [{code: "steam_build_changed", title: "Game build changed", reason: "Old build recorded",
        steps: ["Use Reset HelixSR setup."], blocking: true}]}});
}

test("reset is the primary action ahead of repair and requires reviewed confirmation", async () => {
  const warning = "Reset keeps the current DLL. Verify files in Steam before reinstalling.";
  const h = harness({preview_action: (_id, action) => ({token: "reset-token", action, name: "PRAGMATA",
    route: "direct", warning, files: ["added.dll"], preserved_files: ["native.dll"], select_upscaler: "AMD FSR"})});
  resetGame(h); await h.ready();
  const button = () => h.walk(h.render(), n => n.type === "ButtonItem" && h.text(n) === "Reset HelixSR setup")[0];
  assert.ok(button()); assert.equal(button().props.disabled, false);
  button().props.onClick(); await flush();
  const modal = h.currentModal();
  assert.equal(h.calls.filter(c => c.route === "preview_action").at(-1).args[1], "reset");
  assert.equal(modal.element.props.strTitle, "Reset HelixSR setup");
  assert.equal(modal.element.props.strOKButtonText, "Reset setup");
  const description = h.text(modal.element.props.strDescription);
  assert.ok(description.includes(warning));
  assert.match(description, /added\.dll/); assert.match(description, /native\.dll/);
  assert.doesNotMatch(description, /In game: select|AMD FSR/);
  modal.options.fnOnClose(); await flush();
  assert.equal(h.count("apply_action"), 0);
  button().props.onClick(); await flush();
  const confirmation = h.currentModal();
  confirmation.element.props.onOK(); confirmation.element.props.onOK();
  confirmation.options.fnOnClose(); await flush();
  assert.equal(h.count("apply_action"), 1);
  assert.equal(h.calls.filter(c => c.route === "apply_action")[0].args[0], "reset-token");
});

test("reset is unavailable unless both backend eligibility and status allow it", async () => {
  for (const [eligible, canReset] of [[false, true], [true, false]]) {
    const h = harness(); resetGame(h, eligible, canReset); h.game.repair_eligible = false;
    h.game.installation_status.can_repair = false;
    await h.ready();
    const tree = h.render();
    assert.equal(h.walk(tree, n => n.type === "ButtonItem" && h.text(n) === "Reset HelixSR setup").length, 0);
    const update = h.walk(tree, n => n.type === "ButtonItem" && h.text(n) === "Update this game's HelixSR")[0];
    assert.ok(update); assert.equal(update.props.disabled, true);
    assert.equal(h.count("preview_action"), 0); assert.equal(h.count("apply_action"), 0);
  }
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

test("choosing HLX selects its reviewed release and displays its source terms before install", async () => {
  const models = [
    { id: "helixsr-model-e", label: "Model E", source: "NVIDIA", release_choices: ["reviewed-2.0.0"] },
    { id: "hlx-fsr4-1-2", label: "HLX FSR 4", source: "AMD", release_choices: ["reviewed-3.2.0"],
      routes: ["direct"], source_terms: "AMD model terms", source_license_url: "https://example.com/terms" }
  ];
  const h = harness({
    library: () => ({ ...h.library(), model_catalog: { default: models[0].id, variants: models },
      release_choices: [{id: "reviewed-2.0.0", version: "2.0.0"}, {id: "reviewed-3.2.0", version: "3.2.0"}] }),
    preview_latest: (_gid, _confirmed, id, _exe, choice) => {
      assert.equal(id, models[1].id);
      assert.equal(choice, "reviewed-3.2.0");
      return {token: "preview", name: "Game", files: [], variant_id: id, model: "HLX FSR 4", route: "direct",
        select_upscaler: "AMD FSR", release_version: "3.2.0"};
    }
  });
  await h.ready();
  const control = label => h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === label)[0];
  control("HelixSR model").props.onChange({data: models[1].id});
  assert.equal(control("Release to install").props.selectedOption, "reviewed-3.2.0");
  const review = await h.openInstall();
  assert.match(h.text(review.element.props.strDescription), /AMD model terms/);
  assert.equal(h.count("install_latest"), 0);
  control("Release to install").props.onChange({data: "reviewed-2.0.0"});
  assert.equal(control("HelixSR model").props.selectedOption, models[0].id);
});

test("viewing an installed HLX game does not opt the next game into the prerelease", async () => {
  const models = [
    {id: "helixsr-model-e", label: "Model E", release_choices: ["reviewed-2.0.0"]},
    {id: "hlx-fsr4-1-2", label: "HLX FSR 4", release_choices: ["reviewed-3.2.0"]}
  ];
  const h = harness({library: () => ({...h.library(),
    model_catalog: {default: models[0].id, variants: models},
    release_choices: models.map(m => ({id: m.release_choices[0], label: m.label}))})});
  h.game.installed_variant = models[1].id;
  await h.ready();
  const control = label => h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === label)[0];
  assert.equal(control("Release to install").props.selectedOption, "reviewed-3.2.0");
  delete h.game.installed_variant;
  h.render(); h.render();
  assert.equal(control("Release to install").props.selectedOption, "reviewed-2.0.0");
  assert.equal(control("HelixSR model").props.selectedOption, models[0].id);
});

test("an explicit HLX choice for one game is kept on refresh but never preselected for another game", async () => {
  const models = [
    {id: "helixsr-model-e", label: "Model E", release_choices: ["reviewed-2.0.0"]},
    {id: "hlx-fsr4-1-2", label: "HLX FSR 4", release_choices: ["reviewed-3.2.0"]}
  ];
  let games;
  const h = harness({
    library: () => ({...h.library(), games,
      model_catalog: {default: models[0].id, variants: models},
      release_choices: models.map(m => ({id: m.release_choices[0], label: m.label}))}),
    game_details: id => games.find(g => g.id === id),
  });
  games = [h.game, {...h.game, id: "other", name: "Other game", folder: "/games/Other"}];
  await h.ready();
  const control = label => h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === label)[0];
  control("HelixSR model").props.onChange({data: models[1].id});
  assert.equal(control("Release to install").props.selectedOption, "reviewed-3.2.0");
  const refresh = h.walk(h.render(), n => n.type === "ButtonItem" && /Refresh library and status/.test(h.text(n)))[0];
  refresh.props.onClick(); await flush(); h.render(); await flush(); h.render();
  assert.equal(control("HelixSR model").props.selectedOption, models[1].id, "same game keeps its explicit opt-in");
  control("Game").props.onChange({data: "other"}); await flush(); h.render(); await flush(); h.render();
  assert.equal(control("Release to install").props.selectedOption, "reviewed-2.0.0");
  assert.equal(control("HelixSR model").props.selectedOption, models[0].id);
});

const MODEL_E = "helixsr-model-e", HLX = "hlx-fsr4-1-2";
function modelChoiceHarness(games, {catalog = () => true, ...overrides} = {}) {
  const models = [
    {id: MODEL_E, label: "Model E", release_choices: ["reviewed-2.0.0", "reviewed-1.9.3", "compatible-1.8.1", "latest"]},
    {id: HLX, label: "HLX FSR 4", release_choices: ["reviewed-3.2.0"]}
  ];
  let list;
  const h = harness({
    library: () => ({...h.library(), games: list.map(g => ({...g})),
      ...(catalog() ? {model_catalog: {default: MODEL_E, variants: models}} : {}),
      release_choices: [{id: "reviewed-2.0.0", version: "2.0.0"}, {id: "reviewed-3.2.0", version: "3.2.0"}]}),
    game_details: id => ({...list.find(g => g.id === id)}),
    preview_latest: (gid, _dx12, id, _exe, choice) => ({token: "preview", name: gid, files: [], variant_id: id,
      model: id, route: "direct", select_upscaler: "Helix SR", release_version: choice}),
    ...overrides });
  list = games(h.game);
  const control = label => h.walk(h.render(), n => n.type === "DropdownItem" && n.props.label === label)[0];
  const shown = () => [control("HelixSR model").props.selectedOption, control("Release to install").props.selectedOption];
  // Steam closes the quick-access panel while a dropdown menu is open: the option
  // reaches the unmounted panel's callback and a fresh panel mounts afterwards.
  async function pickInMenu(label, data) {
    const dropdown = control(label); h.unmount();
    dropdown.props.onChange({data});
    h.mount(); const remounted = shown();
    await flush(); h.render(); await flush(); h.render();
    return remounted;
  }
  async function refresh() {
    h.walk(h.render(), n => n.type === "ButtonItem" && /Refresh library and status/.test(h.text(n)))[0].props.onClick();
    await flush(); h.render(); await flush(); h.render();
  }
  async function update() {
    const button = h.walk(h.render(), n => n.type === "ButtonItem" && /Update this game's HelixSR/.test(h.text(n)))[0];
    assert.ok(button); assert.equal(button.props.disabled, false);
    button.props.onClick(); await flush(); h.render();
    return h.calls.filter(call => call.route === "preview_latest").at(-1).args;
  }
  return {...h, control, shown, pickInMenu, refresh, update};
}

test("an explicit HLX choice on a managed Model E game survives the dropdown remount and Refresh", async () => {
  const h = modelChoiceHarness(game => [Object.assign(game, {managed: true, enabled: true,
    installed_version: "2.0.0", installed_model: "HelixSR Model E", installed_variant: MODEL_E})]);
  await h.ready();
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"], "without a choice the installed model is shown");
  assert.deepEqual(await h.pickInMenu("HelixSR model", HLX), [HLX, "reviewed-3.2.0"], "remounted panel starts with the choice");
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"], "installed Model E does not override the choice");
  await h.refresh();
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"]);
  h.unmount(); h.mount(); await flush(); h.render(); await flush(); h.render();
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"]);
  const args = await h.update();
  assert.deepEqual([args[2], args[4]], [HLX, "reviewed-3.2.0"], "Update reviews the Model E to HLX upgrade");
  // The review dialog also remounts the panel; choose before it has the game's details.
  h.unmount(); h.mount(); await flush();
  assert.deepEqual(await h.pickInMenu("HelixSR model", MODEL_E), [MODEL_E, "reviewed-2.0.0"]);
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"], "choosing the installed model again leaves no stale HLX state");
});

test("an explicit Model E choice on an HLX game survives the remount so Update reaches the downgrade guard", async () => {
  const downgrade = "HelixSR 3.2.0 is installed for this game; installing 2.0.0 would downgrade it. Close the game and use Remove to restore the original files, then install the selected model. No files were changed.";
  const h = modelChoiceHarness(game => [Object.assign(game, {managed: true, enabled: true,
    installed_version: "3.2.0", installed_model: "HLX FSR 4 (FSR 4.1.2 Lite)", installed_variant: HLX})], {
    preview_latest: (_gid, _dx12, id, _exe, choice) => {
      assert.deepEqual([id, choice], [MODEL_E, "reviewed-2.0.0"]);
      throw Error(downgrade);
    } });
  await h.ready();
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"], "without a choice the installed model is shown");
  assert.deepEqual(await h.pickInMenu("HelixSR model", MODEL_E), [MODEL_E, "reviewed-2.0.0"]);
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"], "installed HLX does not override the choice");
  await h.refresh();
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"]);
  const args = await h.update();
  assert.deepEqual([args[2], args[4]], [MODEL_E, "reviewed-2.0.0"]);
  assert.match(h.text(h.render()), /installing 2\.0\.0 would downgrade it/);
  assert.equal(h.count("install_latest"), 0);
});

// Decky 3.3 rejects a failed backend call with a PyError: an Error of the panel's
// own realm whose message is empty; the exception text is only in pythonTraceback.
function pyError(h, message, type = "Exception") {
  const PyError = vm.runInContext(`(class PyError extends Error {
    constructor(traceback) { super(""); this.name = "Python Exception"; this.pythonTraceback = traceback; } })`, h.context);
  return new PyError('Traceback (most recent call last):\n  File "decky_loader/plugin/messages.py", line 44, in wait_for_result\n'
    + `${type}: ${message}\n`);
}

test("a release chosen before the model catalog loads is kept for a managed game once the catalog arrives", async () => {
  let catalog = false;
  const h = modelChoiceHarness(game => [Object.assign(game, {managed: true, enabled: true,
    installed_version: "2.0.0", installed_model: "HelixSR Model E", installed_variant: MODEL_E})], {catalog: () => catalog});
  await h.ready();
  assert.equal(h.control("HelixSR model"), undefined, "no model dropdown before the catalog loads");
  // The release menu remounts the panel; its choice cannot resolve a model yet.
  const release = h.control("Release to install"); h.unmount();
  release.props.onChange({data: "reviewed-3.2.0"});
  h.mount(); await flush(); h.render(); await flush(); h.render();
  catalog = true;
  await h.refresh();
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"], "the installed model does not replace the earlier release choice");
});

test("Decky's empty-message PyError still shows the downgrade guard text after Update", async () => {
  const downgrade = "HelixSR 3.2.0 is installed for this game; installing 2.0.0 would downgrade it. Close the game and use Remove to restore the original files, then install the selected model. No files were changed.";
  const h = modelChoiceHarness(game => [Object.assign(game, {managed: true, enabled: true,
    installed_version: "3.2.0", installed_model: "HLX FSR 4 (FSR 4.1.2 Lite)", installed_variant: HLX})], {
    preview_latest: () => { throw pyError(h, downgrade); } });
  await h.ready();
  await h.pickInMenu("HelixSR model", MODEL_E);
  const args = await h.update();
  assert.deepEqual([args[2], args[4]], [MODEL_E, "reviewed-2.0.0"]);
  const alerts = h.walk(h.render(), n => n.props?.role === "alert").map(n => h.text(n));
  assert.ok(alerts.includes(downgrade), `alert shows the backend text: ${JSON.stringify(alerts)}`);
  assert.equal(h.count("install_latest"), 0);
});

test("an explicit HLX choice for uninstalled game A survives remounts and Refresh but never preselects game B", async () => {
  const h = modelChoiceHarness(game => [game, {...game, id: "other", name: "Other game", folder: "/games/Other"}]);
  await h.ready();
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"]);
  assert.deepEqual(await h.pickInMenu("HelixSR model", HLX), [HLX, "reviewed-3.2.0"]);
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"]);
  await h.refresh();
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"], "same game keeps its explicit opt-in across Refresh");
  assert.deepEqual(await h.pickInMenu("Game", "other"), [MODEL_E, "reviewed-2.0.0"], "B's remounted panel never starts on A's prerelease");
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"], "B shows the default");
  await h.refresh();
  assert.deepEqual(h.shown(), [MODEL_E, "reviewed-2.0.0"]);
  assert.deepEqual(await h.pickInMenu("Game", "pragmata"), [HLX, "reviewed-3.2.0"]);
  assert.deepEqual(h.shown(), [HLX, "reviewed-3.2.0"], "A keeps its own choice after B was viewed");
});

test("HLX Scaler exposes native AMD as a separate output and only available FG providers", async () => {
  const h = harness();
  enableSettings(h, {family: "hlx-fsr", upscaler: "hlx-fsr", provider: "off"});
  await h.ready();
  const options = label => Array.from(settingsDropdown(h, label).props.rgOptions, v => v.data);
  assert.deepEqual(options("Upscaler"), ["hlx-fsr", "fsr"]);
  assert.deepEqual(options("Frame generation"), ["off", "fsr", "xess"]);
  assert.doesNotMatch(h.text(renderedHelixSettings(h)), /Advanced tuning/);
});

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

test("a failed panel action shows and toasts the PyError's traceback message", async () => {
  const message = "Settings changed; refresh before saving";
  const h = harness({ set_game_settings: () => { throw pyError(h, message, "ValueError"); } });
  enableSettings(h); await h.ready(); h.openAdvanced();
  settingsDropdown(h, "Upscaler").props.onChange({ data: "fsr" }); await flush();
  const toast = h.toasts.find(item => /action could not complete/.test(item.title));
  assert.equal(toast?.body, message);
  assert.match(h.text(h.render()), new RegExp(message));
});
