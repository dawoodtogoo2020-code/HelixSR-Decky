import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, TextField,
  ToggleField, ConfirmModal, showModal, staticClasses } from "@decky/ui";
import { callable, definePlugin, openFilePicker, toaster } from "@decky/api";
import { ReactNode, useEffect, useRef, useState } from "react";
import { FaAdjust } from "react-icons/fa";
import { proxyOptions } from "./launchOptions";
import { PluginInstaller, PluginArtifact } from "./pluginInstaller";

declare const DeckyBackend: { callable: <A extends unknown[], R>(route: string) => (...args: A) => Promise<R>;
  addEventListener?: (event: string, listener: (...args: any[]) => void) => unknown;
  removeEventListener?: (event: string, listener: (...args: any[]) => void) => void } | undefined;
type PluginUpdate = { current_version: string; latest_version: string | null; update_available: boolean;
  auto_check: boolean; checked_at: number; attempted_at: number; error: string; page: string; pending: boolean };
const pluginUpdateStatus = callable<[], PluginUpdate>("plugin_update_status");
const checkPluginUpdates = callable<[boolean], PluginUpdate>("check_plugin_updates");
const setPluginAutoCheck = callable<[boolean], PluginUpdate>("set_plugin_auto_check");
const preparePluginUpdate = callable<[], PluginArtifact>("prepare_plugin_update");
const resumePluginUpdate = callable<[], PluginArtifact>("resume_plugin_update");
const cancelPluginUpdate = callable<[], PluginUpdate>("cancel_plugin_update");
let latestPluginStatus: PluginUpdate | undefined;
let pluginUpdateTimer: ReturnType<typeof setInterval> | undefined;
let pluginUpdatePolling = false;
let notifiedPluginVersion = "";
const pluginUpdateListeners = new Set<(status: PluginUpdate) => void>();
function publishPluginStatus(status: PluginUpdate) {
  if (pluginDisposed) return;
  latestPluginStatus = status;
  pluginUpdateListeners.forEach(listener => listener(status));
  if (status.update_available && !status.error && status.latest_version !== notifiedPluginVersion) {
    notifiedPluginVersion = status.latest_version || "";
    toaster.toast({ title: "HelixSR Decky update available", body: `Plugin ${status.latest_version} is ready. Open Plugin updates to review it.`, duration: 6000 });
  }
}
function pollPluginStatus() {
  if (pluginUpdatePolling || pluginDisposed) return;
  pluginUpdatePolling = true;
  void pluginUpdateStatus().then(publishPluginStatus).catch(() => {}).finally(() => { pluginUpdatePolling = false; });
}

type FG = { source: string; key: string; value: string; enabled: boolean | null; meaning: string; path: string };
type Game = { id: string; name: string; folder: string; source: string; compatibility: string;
  appid?: string;
  reasons: string[]; route: string | null; inputs: string[]; managed: boolean; enabled: boolean;
  legacy: boolean; recovery_available?: boolean; installed_version?: string; package_version?: string; dx12_confirmation_needed: boolean;
  main_exe?: string; target?: string; installed_model?: string; installed_variant?: string;
  executable_choices?: { path: string; dx12: boolean }[]; selected_executable?: string; executable_selection_needed?: boolean;
  optiscaler: { present: boolean; involved: boolean; helix_configured?: boolean; runtime: string; dlls: string[];
    setup?: { checks: string[]; backend: string; override: string; overlay_shortcut: string; settings: Record<string, string>; guide: string } };
  framegen: FG[]; framegen_summary: string; helix_runtime: string;
  launch_options: string; logs?: { path: string; modified: number; excerpt: string }[] };
type Release = { version?: string; error?: string; checked_at?: number; page?: string };
type ModelCatalog = { variants: { id: string; label: string; source: string }[]; default: string; note: string };
type Job = { id: string; kind: string; game: string; state: string; message: string; log: string };
type LauncherImport = { launcher: string; found: number; added: number; candidates: number;
  unavailable: number; game_ids: string[]; warnings: string[] };
type Library = { games: Game[]; warnings: string[]; release: Release; license_accepted: boolean; jobs: Job[];
  launcher_import?: LauncherImport; model_catalog?: ModelCatalog };
type Preview = { token: string; name: string; action: string; route: string; files: string[];
  warning: string; select_upscaler: string; model?: string; variant_id?: string; release_version?: string; selected_executable?: string };
const library = callable<[], Library>("library");
const details = callable<[string, string?], Game>("game_details");
const checkUpdates = callable<[boolean], Release>("check_updates");
const forgetGame = callable<[string], Library>("forget_game");
const importFolders = callable<[string[]], Library>("import_folders");
const importLauncher = callable<[string], Library>("import_launcher");
const setLicense = callable<[boolean, string?], boolean>("set_license");
const jobStatus = callable<[], Job[]>("job_status");
const cancelJob = callable<[string], boolean>("cancel_job");
const previewAction = callable<[string, string, boolean, string?], Preview>("preview_action");
const applyAction = callable<[string], { message: string }>("apply_action");
const previewLatest = callable<[string, boolean, string?, string?], Preview>("preview_latest");
const installLatest = callable<[string], Job>("install_latest");
type LaunchIntent = { nonce: string; before: string; after: string; restore: boolean };
const prepareLaunch = callable<[string, string, string, boolean], LaunchIntent>("prepare_launch_options");
const finalizeLaunch = callable<[string, string, string], unknown>("finalize_launch_options");
const ownedLaunch = callable<[string, string], { before: string; after: string; pending?: LaunchIntent } | null>("owned_launch_options");

async function liveLaunchOptions(appid: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { subscription?.unregister(); reject(new Error("Steam did not provide live launch options")); }, 5000);
    let subscription: { unregister(): void } | undefined;
    subscription = SteamClient.Apps.RegisterForAppDetails(appid, detail => {
      clearTimeout(timer); subscription?.unregister(); resolve(detail.strLaunchOptions);
    });
  });
}

let lastSelected = "";
const selectionListeners = new Set<(id: string) => void>();
function chooseGame(id: string) {
  lastSelected = id;
  selectionListeners.forEach(listener => listener(id));
}
// Steam can unmount the quick-access panel when a dialog opens. Keep the lock across mounts.
let interactionBusy = false;
let reviewApplying = false;
let dialogShowing = false;
let interactionAfter = 0;
const interactionListeners = new Set<() => void>();
const pluginInstaller = new PluginInstaller(async (route, ...args) => {
  if (typeof DeckyBackend === "undefined" || typeof DeckyBackend.callable !== "function")
    throw new Error("Decky's installer is unavailable. Install the release ZIP through Decky Settings → Developer.");
  return DeckyBackend.callable<unknown[], unknown>(route)(...args);
}, () => interactionListeners.forEach(listener => listener()));
function nativeUpdatePrompt(name: string, version: string, requestId: string, hash: string) {
  pluginInstaller.prompt(name, version, requestId, hash);
}
function nativeUpdateStarted(name: string) {
  pluginInstaller.started(name);
}
function nativeUpdateFinished(name: string) {
  pluginInstaller.finished(name);
}
function finishInteraction() {
  if (reviewApplying) { dialogShowing = false; return; }
  interactionBusy = false; dialogShowing = false;
  interactionAfter = Date.now() + 700;
  interactionListeners.forEach(fn => fn());
}
async function interact(fn: () => Promise<void>) {
  if (interactionBusy || reviewApplying || Date.now() < interactionAfter) return;
  interactionBusy = true;
  interactionListeners.forEach(listener => listener());
  try { await fn(); }
  finally { if (!dialogShowing) finishInteraction(); }
}
function beginReview() {
  if (reviewApplying) return false;
  reviewApplying = true; interactionBusy = true;
  interactionListeners.forEach(listener => listener());
  return true;
}
function openDialog(modal: ReactNode) {
  dialogShowing = true;
  try { showModal(modal, undefined, { bNeverPopOut: true, fnOnClose: finishInteraction }); }
  catch (e) { finishInteraction(); throw e; }
}
const notifiedJobs = new Set<string>();
const jobListeners = new Set<(next: Job[], finished: boolean) => void>();
const folderListeners = new Set<(next: string[]) => void>();
let pendingFolders: string[] = [];
const launcherOptions = [
  { data: "heroic", label: "Heroic Games Launcher" },
  { data: "lutris", label: "Lutris" },
  { data: "legendary", label: "Legendary" },
  { data: "steam-shortcuts", label: "Steam non-Steam shortcuts" },
  { data: "all-launchers", label: "All supported launchers" },
];
let selectedLauncher = "heroic";
let launcherImportMessage = "";
const launcherListeners = new Set<() => void>();
function chooseLauncher(id: string) {
  if (!launcherOptions.some(option => option.data === id)) return;
  selectedLauncher = id; launcherImportMessage = "";
  launcherListeners.forEach(listener => listener());
}
function reportLauncherImport(message: string) {
  launcherImportMessage = message;
  launcherListeners.forEach(listener => listener());
}
function queueFolders(next: string[]) {
  pendingFolders = next;
  folderListeners.forEach(listener => listener(next));
}
let watchedJobs: Job[] = [];
let jobTimer: ReturnType<typeof setInterval> | undefined;
let jobPolling = false;
let pluginDisposed = false;
function watchJobs(next: Job[]) {
  if (pluginDisposed) return;
  const finished = watchedJobs.some(old => old.state === "running" && next.some(j => j.id === old.id && j.state !== "running"));
  next.forEach(j => {
    if (j.state === "running" || notifiedJobs.has(j.id)) return;
    notifiedJobs.add(j.id);
    if (!watchedJobs.some(old => old.id === j.id && old.state === "running")) return;
    toaster.toast({ title: j.state === "completed" ? j.kind === "install_latest" ? "HelixSR enabled" : "HelixSR preparation complete" : j.state === "cancelled" ? "HelixSR operation cancelled" : "HelixSR operation failed",
      body: `${j.game}: ${j.message}`, duration: 6000 });
  });
  watchedJobs = next;
  jobListeners.forEach(listener => listener(next, finished));
  if (next.some(j => j.state === "running") && !jobTimer) {
    // Notifications continue when the quick-access panel is closed.
    jobTimer = setInterval(() => {
      if (jobPolling) return;
      jobPolling = true;
      void jobStatus().then(watchJobs).catch(() => {}).finally(() => { jobPolling = false; });
    }, 2000);
  } else if (!next.some(j => j.state === "running") && jobTimer) {
    clearInterval(jobTimer); jobTimer = undefined;
  }
}
function Content() {
  const [data, setData] = useState<Library>();
  const [selected, select] = useState(lastSelected);
  const [game, setGame] = useState<Game>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [folder, setFolder] = useState("");
  const [folders, setFolders] = useState<string[]>(pendingFolders);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [dx12, setDx12] = useState(false);
  const [variant, setVariant] = useState<string>();
  const [diagnostics, setDiagnostics] = useState(false);
  const [discoveryNotes, setDiscoveryNotes] = useState(false);
  const [setupOptions, setSetupOptions] = useState(false);
  const [unavailableGames, setUnavailableGames] = useState(false);
  const [importOpen, setImportOpen] = useState(!!pendingFolders.length);
  const [launcher, setLauncher] = useState(selectedLauncher);
  const [importMessage, setImportMessage] = useState(launcherImportMessage);
  const [modalOpen, setModalOpen] = useState(interactionBusy || reviewApplying || pluginInstaller.locked);
  const [pluginUpdate, setPluginUpdate] = useState(latestPluginStatus);
  const [pluginInstallMessage, setPluginInstallMessage] = useState(pluginInstaller.message);
  const selectedRef = useRef(selected);
  const executableRef = useRef<string | undefined>(undefined);
  selectedRef.current = selected;

  useEffect(() => {
    pluginUpdateListeners.add(setPluginUpdate);
    setPluginUpdate(latestPluginStatus);
    pollPluginStatus();
    return () => { pluginUpdateListeners.delete(setPluginUpdate); };
  }, []);

  useEffect(() => {
    const changed = () => { setModalOpen(interactionBusy || reviewApplying || pluginInstaller.locked); setPluginInstallMessage(pluginInstaller.message); };
    interactionListeners.add(changed); changed();
    return () => { interactionListeners.delete(changed); };
  }, []);
  useEffect(() => {
    const changed = (id: string) => { if (selectedRef.current !== id) executableRef.current = undefined; selectedRef.current = id; select(id); };
    selectionListeners.add(changed); changed(lastSelected);
    return () => { selectionListeners.delete(changed); };
  }, []);
  useEffect(() => {
    folderListeners.add(setFolders); setFolders(pendingFolders);
    return () => { folderListeners.delete(setFolders); };
  }, []);
  useEffect(() => {
    const changed = () => { setLauncher(selectedLauncher); setImportMessage(launcherImportMessage); };
    launcherListeners.add(changed); changed();
    return () => { launcherListeners.delete(changed); };
  }, []);

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true); setError("");
    try { return await fn(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return undefined; }
    finally { setBusy(false); }
  }
  async function refresh() {
    const result = await run(library);
    if (result) {
      setData(result); watchJobs(result.jobs);
      if (!selectedRef.current || !result.games.some(g => g.id === selectedRef.current)) {
        const first = result.games.find(g => g.recovery_available) || result.games.find(g => g.compatibility === "candidate" && g.managed) || result.games.find(g => g.compatibility === "candidate" || g.executable_selection_needed);
        if (first) chooseGame(first.id);
      }
    }
    const id = selectedRef.current;
    if (id) {
      const current = result?.games.find(g => g.id === id);
      if (current?.managed || current?.route !== "optiscaler") executableRef.current = undefined;
      const g = await run(() => details(id, executableRef.current));
      if (g && selectedRef.current === id) setGame(g);
    }
  }
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    let active = true;
    setGame(undefined); setDx12(false); setDiagnostics(false);
    if (selected) void run(() => details(selected)).then(g => { if (g && active) setGame(g); });
    return () => { active = false; };
  }, [selected]);
  useEffect(() => {
    setVariant(game?.installed_variant || data?.model_catalog?.default);
  }, [game?.id, game?.installed_variant, data?.model_catalog?.default]);
  useEffect(() => {
    const changed = (next: Job[], finished: boolean) => { setJobs(next); if (finished) void refresh(); };
    jobListeners.add(changed); setJobs(watchedJobs);
    return () => { jobListeners.delete(changed); };
  }, []);

  async function chooseExecutable(path: string) {
    if (!game || game.managed || game.route !== "optiscaler") return;
    const id = game.id;
    executableRef.current = path;
    setDx12(false);
    const updated = await run(() => details(id, path));
    if (selectedRef.current !== id || executableRef.current !== path) return;
    if (updated) setGame(updated);
    else { executableRef.current = undefined; setGame(undefined); }
  }

  async function importFromLauncher() {
    const source = selectedLauncher;
    const label = launcherOptions.find(option => option.data === source)!.label;
    reportLauncherImport(`Detecting installed games from ${label}…`);
    const result = await run(() => importLauncher(source));
    if (!result?.launcher_import) {
      reportLauncherImport("Import failed. Review the error message and try again.");
      return;
    }
    setData(result); watchJobs(result.jobs);
    const report = result.launcher_import;
    const summary = report.found
      ? `${report.found} game${report.found === 1 ? "" : "s"} found · ${report.added} new · ${report.candidates} installation candidate${report.candidates === 1 ? "" : "s"}${report.unavailable ? ` · ${report.unavailable} unavailable` : ""}`
      : `No importable installed games found in ${label}. Check that the game is installed and its drive is mounted, or use Games Folders below for a custom location.`;
    const message = report.warnings.length
      ? `${summary} ${report.warnings.length} detection warning${report.warnings.length === 1 ? "" : "s"}; open Discovery notes below.`
      : summary;
    reportLauncherImport(message);
    // Keep the existing selection. Auto-select a candidate only when none exists.
    const current = result.games.find(g => g.id === selectedRef.current);
    if (!current || !(current.compatibility === "candidate" || current.managed || current.recovery_available)) {
      const first = result.games.find(g => report.game_ids.includes(g.id) && g.compatibility === "candidate");
      chooseGame(first?.id || "");
      setGame(undefined);
    } else {
      const id = selectedRef.current;
      if (current.managed || current.route !== "optiscaler") executableRef.current = undefined;
      const updated = await run(() => details(id, executableRef.current));
      if (selectedRef.current === id) setGame(updated);
    }
    toaster.toast({ title: report.warnings.length ? "Game import finished with warnings" : "Game import complete", body: `${label}: ${message}`, duration: 6000 });
  }

  async function installOrUpdate() {
    if (!game) return;
    const currentRelease = await run(() => checkUpdates(true));
    if (!currentRelease?.version || currentRelease.error) { setError(currentRelease?.error || "Could not check the latest HelixSR release. Retry Check for updates."); return; }
    setData(d => d ? { ...d, release: currentRelease } : d);
    const executable = !game.managed && game.route === "optiscaler" ? game.selected_executable : undefined;
    const p = await run(() => previewLatest(game.id, dx12, variant, executable));
    if (!p) return;
    openDialog(<ConfirmModal bDisableBackgroundDismiss strTitle={`${game.managed || game.legacy ? "Update" : "Install"} HelixSR ${currentRelease.version}`}
      strDescription={<div style={{ overflowWrap: "anywhere" }}>
        <p>{p.name}: {p.warning}</p>
        <p>Selected model: {p.model}. HelixSR release: {p.release_version}.</p>
        {p.selected_executable && <p>Game executable: {p.selected_executable}</p>}
        <p>Required downloads and local preparation are automatic. Uses HelixSR freeware and NVIDIA DLSS under their linked licenses. Locally generated network files must stay on this device.</p>
        <p>Files: {p.files.join(", ")}</p>
      </div>}
      strOKButtonText={data?.license_accepted ? "Install / update HelixSR" : "Accept terms and install"}
      onOK={() => { if (!beginReview()) return; void run(async () => {
        await setLicense(true, p.token);
        const job = await installLatest(p.token);
        watchJobs([job]);
        setData(d => d ? { ...d, license_accepted: true } : d);
      }).finally(() => { reviewApplying = false; finishInteraction(); }); }} />);
  }

  async function action(name: string) {
    if (!game) return;
    const executable = !game.managed && game.route === "optiscaler" ? game.selected_executable : undefined;
    const p = await run(() => previewAction(game.id, name, dx12, executable));
    if (!p) return;
    openDialog(<ConfirmModal bDisableBackgroundDismiss strTitle={`${name.toUpperCase()}: ${p.name}`}
      strDescription={<div style={{ overflowWrap: "anywhere" }}>
        <p>{p.warning}</p><p>Route: {p.route}. In game: select {p.select_upscaler}.</p>
        {p.selected_executable && <p>Game executable: {p.selected_executable}</p>}
        <p>Files: {p.files.join(", ")}</p>
      </div>} strOKButtonText="Apply reviewed change" strCancelButtonText="Cancel"
      onOK={() => { if (!beginReview()) return; void run(() => applyAction(p.token)).then(async result => {
        if (result) toaster.toast({ title: "HelixSR Decky", body: result.message });
        await refresh();
      }).finally(() => { reviewApplying = false; finishInteraction(); }); }} />);
  }
  async function launchChange(restore = false) {
    if (!game?.appid) return;
    const appid = Number(game.appid);
    const before = await run(() => liveLaunchOptions(appid));
    if (before === undefined) return;
    const receipt = await run(() => ownedLaunch(game.id, before));
    if (receipt === undefined) return;
    let after: string;
    try {
      if (receipt?.pending) {
        if (receipt.pending.restore !== restore) throw new Error("Finish the pending launch-option change using the same action first.");
        after = receipt.pending.after;
      } else if (restore) {
        if (!receipt || receipt.after !== before) throw new Error("Launch options changed outside the plugin. Review them in Steam.");
        after = receipt.before;
      } else {
        after = proxyOptions(before);
        if (after === before) { toaster.toast({ title: "HelixSR Decky", body: "OptiScaler proxy launch option is already configured" }); return; }
      }
    } catch (e) { setError(String(e)); return; }
    openDialog(<ConfirmModal bDisableBackgroundDismiss strTitle={restore ? "Restore previous launch options" : "Enable Proton OptiScaler proxy"}
      strDescription={<div style={{ overflowWrap: "anywhere" }}><p>Before: {before || "empty"}</p><p>After: {after || "empty"}</p></div>}
      onOK={() => { if (!beginReview()) return; void run(async () => {
        const current = await liveLaunchOptions(appid);
        if (current !== before) throw new Error("Live launch options changed since preview");
        const intent = await prepareLaunch(game.id, before, after, restore);
        SteamClient.Apps.SetAppLaunchOptions(appid, after);
        const saved = await liveLaunchOptions(appid);
        if (saved !== after) throw new Error("Steam did not confirm saved launch options");
        await finalizeLaunch(game.id, intent.nonce, saved);
        toaster.toast({ title: "HelixSR Decky", body: "Steam launch options saved and verified" });
        await refresh();
      }).finally(() => { reviewApplying = false; finishInteraction(); }); }} />);
  }
  async function updatePlugin(resume = false) {
    if (typeof DeckyBackend === "undefined" || typeof DeckyBackend.callable !== "function" || !DeckyBackend.addEventListener || !DeckyBackend.removeEventListener) {
      setError("This Decky version cannot open the plugin installer. Use Decky Settings → Developer → Install plugin from URL with the release ZIP.");
      return;
    }
    await run(async () => {
      const prepared = await (resume ? resumePluginUpdate() : preparePluginUpdate());
      // Informational status failures must never prevent the native handoff.
      pollPluginStatus();
      await pluginInstaller.open(prepared);
      toaster.toast({ title: "Plugin downloaded, confirmation required", body: "Press Update in Decky's confirmation. Downloading alone does not install the plugin.", duration: 10000 });
    });
  }
  async function cancelDownloadedPlugin() {
    await run(async () => {
      await pluginInstaller.cancel(async () => publishPluginStatus(await cancelPluginUpdate()));
    });
  }
  const running = jobs.some(x => x.state === "running");
  const disabled = busy || running || modalOpen || !!pluginUpdate?.pending;
  const games = (data?.games || []).filter(g => g.compatibility === "candidate" || g.recovery_available || g.managed || g.executable_selection_needed);
  const unavailable = (data?.games || []).filter(g => !games.includes(g));
  const infoStyle = { fontSize: "13px", lineHeight: "1.45", overflowWrap: "anywhere" as const, whiteSpace: "pre-wrap" as const };

  return <div className="helixsr-decky">
    <style>{`.helixsr-decky{width:100%;box-sizing:border-box;margin:0 auto;padding:8px 4px;color:#e8f1fa;background:linear-gradient(180deg,rgba(50,135,160,.1),transparent 280px)}
      .helixsr-decky button{box-sizing:border-box;max-width:100%;text-align:center;justify-content:center;border-radius:7px;background-color:#30313d!important;color:#e8f1fa!important}
      .helixsr-decky .helix-installed button{background-color:#1c6048!important;color:#c6ffe1!important;border:1px solid #55cd92}
      .helixsr-decky .helix-selected button{outline:2px solid #ad8aff!important}
      .helixsr-decky .helix-primary button{background-color:#634394!important;color:#fff!important;border:1px solid #b58ae9}
      .helixsr-decky button:focus{outline:2px solid #7de1e7!important;background-color:#4d465e!important}
      .helixsr-decky button:disabled{opacity:.5}
      .helixsr-decky .helix-card{width:100%;box-sizing:border-box;padding:12px;border-left:3px solid #53c5d0;border-radius:7px;background:rgba(34,83,104,.25)}
      .helixsr-decky .helix-muted{color:#c5d1df;font-size:12px}
      .helixsr-decky .helix-status{color:#8ee8bc}`}</style>
    <PanelSection title="Games">
      <PanelSectionRow><div className="helix-card helix-muted">{busy && !data ? "Detecting installed games…" : `${data?.games.length || 0} detected · ${games.filter(g => g.compatibility === "candidate").length} installation candidates`}</div></PanelSectionRow>
      <div className={`${game?.enabled || game?.legacy ? "helix-installed" : ""} helix-selected`}><PanelSectionRow>
        <DropdownItem layout="below" label="Game" menuLabel="Detected games" selectedOption={selected}
          strDefaultLabel={games.length ? "Select a game" : "No compatible games detected"} disabled={busy || modalOpen || !games.length}
          rgOptions={games.map(g => ({ data: g.id, label: <span style={{ borderLeft: `3px solid ${g.enabled || g.legacy ? "#55cd92" : "#8b8297"}`, paddingLeft: 8 }}>{g.name} · {g.executable_selection_needed ? "Choose executable" : g.recovery_available ? "Recovery needed" : g.compatibility !== "candidate" ? "Needs review" : g.managed ? g.enabled ? "Enabled" : "Disabled" : g.legacy ? "Existing HelixSR" : "Not installed"}</span> }))}
          onChange={option => chooseGame(String(option.data))} />
      </PanelSectionRow></div>
      {game && <>
        <PanelSectionRow><div className="helix-muted" style={{ color: game.enabled ? "#8ee8bc" : "#c5d1df" }}>{game.enabled ? `HelixSR enabled · ${game.installed_version}` : game.legacy ? "Existing HelixSR installation" : "HelixSR is not enabled"}</div></PanelSectionRow>
        {!game.managed && game.route === "optiscaler" && !!game.executable_choices?.length && (game.executable_choices.length > 1 || !game.executable_choices.some(choice => choice.path === game.selected_executable)) && <>
          <PanelSectionRow><DropdownItem layout="below" label="Game executable" menuLabel="Choose the executable you launch"
            selectedOption={game.selected_executable} strDefaultLabel="Choose a game executable" disabled={disabled}
            rgOptions={game.executable_choices!.map(choice => ({ data: choice.path, label: `${choice.path} · ${choice.dx12 ? "DX12 detected" : "Confirm DX12"}` }))}
            onChange={option => void chooseExecutable(String(option.data))} /></PanelSectionRow>
          <PanelSectionRow><div className="helix-muted">Choose the DX12 executable you actually launch. HelixSR will be installed beside it. Existing installs keep their recorded folder; remove them before choosing another executable.</div></PanelSectionRow>
        </>}
        {game.dx12_confirmation_needed && <PanelSectionRow><ToggleField label="Game is set to DirectX 12"
          description="Confirm the renderer selected in the game." checked={dx12} onChange={setDx12} disabled={disabled} /></PanelSectionRow>}
        <div className="helix-primary"><PanelSectionRow><ButtonItem layout="below" disabled={disabled || game.compatibility !== "candidate"}
          onClick={() => void interact(installOrUpdate)}>{game.managed || game.legacy ? "Update HelixSR" : "Install HelixSR"}</ButtonItem></PanelSectionRow></div>
      </>}
      <PanelSectionRow><ButtonItem layout="below" onClick={() => void refresh()} disabled={busy || modalOpen}>Refresh library and status</ButtonItem></PanelSectionRow>
      {!!unavailable.length && <PanelSectionRow><ButtonItem layout="below" onClick={() => setUnavailableGames(!unavailableGames)}>{unavailableGames ? "Hide unavailable games" : `Unavailable games (${unavailable.length})`}</ButtonItem></PanelSectionRow>}
      {unavailableGames && unavailable.map(g => <PanelSectionRow key={g.id}><div className="helix-card helix-muted">{g.name}{"\n"}{g.reasons.join("\n") || "No supported upscaler detected"}</div></PanelSectionRow>)}
      {error && <PanelSectionRow><div role="alert" style={{ ...infoStyle, color: "#ffb4a7" }}>{error}</div></PanelSectionRow>}
    </PanelSection>
    {game && <PanelSection title={game.name}>
      <PanelSectionRow><div className="helix-card" style={infoStyle}>
        {game.source} · {game.compatibility}{"\n"}
        Route: {game.route === "direct" ? "Native FSR 3.1 replacement" : game.route === "optiscaler" ? "OptiScaler proxy" : "None detected"}{"\n"}
        HelixSR: {game.managed ? `${game.enabled ? "enabled" : "disabled"}, ${game.installed_version}` : game.legacy ? "existing unmanaged install" : "unmanaged"}{"\n"}
        Prepared: {game.package_version || "none on this drive"}{"\n"}
        Installed model: {game.installed_model || "not installed"}{"\n"}
        {game.reasons.join("\n")}
      </div></PanelSectionRow>
      {!!data?.model_catalog?.variants.length && <>
        <PanelSectionRow><DropdownItem label="HelixSR model" rgOptions={data.model_catalog.variants.map(v => ({ label: `${v.label} · ${v.source}`, data: v.id }))}
          selectedOption={variant || data.model_catalog.default} disabled={disabled}
          onChange={option => setVariant(String(option.data))} /></PanelSectionRow>
        <PanelSectionRow><div className="helix-muted">{data.model_catalog.note}</div></PanelSectionRow>
      </>}
      <PanelSectionRow><div className="helix-muted">Downloads, required dependencies and the local network build are handled automatically. Administrator access is not needed for your own game folders.</div></PanelSectionRow>
      {game.managed && <>
        <PanelSectionRow><ButtonItem layout="below" disabled={disabled || game.compatibility !== "candidate"}
          onClick={() => void interact(() => action(game.enabled ? "disable" : "enable"))}>{game.enabled ? "Disable HelixSR" : "Enable HelixSR"}</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={disabled || game.compatibility !== "candidate"} onClick={() => void interact(() => action("remove"))}>Remove and restore originals</ButtonItem></PanelSectionRow>
      </>}
      {game.recovery_available && <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => void interact(() => action("recover"))}>Recover interrupted file transaction</ButtonItem></PanelSectionRow>}
      {game.source === "Imported" && <PanelSectionRow><ButtonItem layout="below" disabled={disabled || game.managed}
        onClick={() => void run(() => forgetGame(game.id)).then(result => { if (result) { setData(result); chooseGame(""); } })}>Forget imported folder</ButtonItem></PanelSectionRow>}
    </PanelSection>}
    {game && <PanelSection title="OptiScaler and frame generation">
      <PanelSectionRow><div style={infoStyle}>
        OptiScaler installed: {game.optiscaler.present ? "yes" : "no detected files"}{"\n"}
        OptiScaler HelixSR route configured: {game.optiscaler.helix_configured ? "yes" : "no"}{"\n"}
        OptiScaler runtime: {game.optiscaler.runtime}{"\n"}
        HelixSR runtime: {game.helix_runtime}{"\n"}
        Frame generation: {game.framegen_summary}{"\n"}
        {game.framegen.map(f => `${f.source} · ${f.key}: ${f.value} (${f.meaning})`).join("\n")}{"\n"}
        HelixSR has no frame generation of its own. Settings and runtime evidence are separate.
      </div></PanelSectionRow>
      {game.route === "optiscaler" && <PanelSectionRow><div style={infoStyle}>
        Target: {game.main_exe || game.target || "unknown"}{"\n"}
        {(game.optiscaler.setup?.checks || []).join("\n\n")}
      </div></PanelSectionRow>}
      {game.route === "optiscaler" && game.appid && <>
        <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => void interact(() => launchChange())}>Review Proton proxy launch option</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => void interact(() => launchChange(true))}>Restore plugin launch-option change</ButtonItem></PanelSectionRow>
      </>}
      <PanelSectionRow><ButtonItem layout="below" onClick={() => setDiagnostics(!diagnostics)}>{diagnostics ? "Hide diagnostics" : "Show diagnostics and logs"}</ButtonItem></PanelSectionRow>
      {diagnostics && <PanelSectionRow><div style={infoStyle}>
        Folder: {game.folder}{"\n"}Launch options: {game.launch_options || "none detected"}{"\n"}
        {Object.entries(game.optiscaler.setup?.settings || {}).map(([key, value]) => `${key}=${value}`).join("\n")}{"\n"}
        {(game.logs || []).map(l => `${l.path}\n${new Date(l.modified * 1000).toLocaleString()}\n${l.excerpt}`).join("\n\n") || "No supported logs found"}
      </div></PanelSectionRow>}
    </PanelSection>}
    <PanelSection title="Plugin updates">
      <PanelSectionRow><div className="helix-card" style={{ ...infoStyle, borderLeftColor: pluginUpdate?.update_available ? "#ad8aff" : "#55cd92" }}>
        Current plugin: {pluginUpdate?.current_version || "loading…"}{"\n"}
        Latest plugin: {pluginUpdate?.latest_version || "checking required"}{"\n"}
        {pluginUpdate?.error ? "Could not check for updates" : pluginUpdate?.pending ? "Downloaded. Confirm Update in Decky to install." : pluginUpdate?.update_available ? "Plugin update available" : pluginUpdate?.checked_at ? "Plugin is up to date" : pluginUpdate?.auto_check === false ? "Automatic checks are off" : "Automatic check will run shortly"}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || modalOpen || !!pluginUpdate?.pending}
        onClick={() => void run(() => checkPluginUpdates(true)).then(r => { if (r) publishPluginStatus(r); })}>Check plugin updates</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ToggleField label="Check plugin updates automatically" description="Checks on startup and once a day. Updates are installed only after you confirm."
        checked={pluginUpdate?.auto_check ?? true} disabled={busy || modalOpen || !!pluginUpdate?.pending}
        onChange={enabled => void run(() => setPluginAutoCheck(enabled)).then(r => { if (r) publishPluginStatus(r); })} /></PanelSectionRow>
      {pluginUpdate?.update_available && !pluginUpdate.pending && <div className="helix-primary"><PanelSectionRow><ButtonItem layout="below"
        disabled={disabled} onClick={() => void interact(() => updatePlugin())}>Download plugin update</ButtonItem></PanelSectionRow></div>}
      {pluginUpdate?.pending && <div className="helix-primary"><PanelSectionRow><ButtonItem layout="below" disabled={busy || modalOpen}
        onClick={() => void interact(() => updatePlugin(true))}>Open update confirmation</ButtonItem></PanelSectionRow></div>}
      {pluginUpdate?.pending && <PanelSectionRow><ButtonItem layout="below" disabled={busy || modalOpen}
        onClick={() => void interact(cancelDownloadedPlugin)}>Cancel downloaded update</ButtonItem></PanelSectionRow>}
      {pluginUpdate?.pending && <PanelSectionRow><div className="helix-muted">{pluginInstallMessage || "Press Update in Decky's confirmation to finish. Close that screen before reopening it here. Restart Decky if installation status is unresolved."}</div></PanelSectionRow>}
      {pluginUpdate?.error && <PanelSectionRow><div className="helix-muted">{pluginUpdate.error}</div></PanelSectionRow>}
    </PanelSection>
    <PanelSection title="HelixSR updates">
      <PanelSectionRow><div className="helix-card" style={infoStyle}>Current HelixSR: {game?.installed_version || "not installed"}{"\n"}
        Latest HelixSR: {data?.release?.version || "checking required"}</div></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || modalOpen} onClick={() => void run(() => checkUpdates(true)).then(r => { if (r) setData(d => d ? { ...d, release: r } : d); })}>Check for updates</ButtonItem></PanelSectionRow>
      {data?.release?.error && <PanelSectionRow><div className="helix-muted">{data.release.error}</div></PanelSectionRow>}
      <PanelSectionRow><ButtonItem layout="below" onClick={() => setSetupOptions(!setupOptions)}>{setupOptions ? "Hide preparation settings" : "Preparation settings"}</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={modalOpen} onClick={() => void interact(async () => openDialog(<ConfirmModal bDisableBackgroundDismiss strTitle="Installation guide" strOKButtonText="Done"
        strDescription={<div><p>1. Choose a detected game from the Game dropdown. Green means HelixSR is present; purple highlights the install/update action.</p>
          <p>2. Choose Install HelixSR or Update HelixSR and review the change. Required downloads and the local network build happen automatically.</p>
          <p>3. Wait for completion, then launch the game with DirectX 12. Choose AMD FSR for a native replacement, or the appropriate DLSS/XeSS/FSR input for OptiScaler.</p>
          <p>For an OptiScaler Steam game, use Review Proton proxy launch option to save its required override while preserving your other options.</p>
          <p>For launcher games, scroll to Import games, choose Import Games From, select Heroic or Lutris, then Import Now. Supported installed games appear in the Game dropdown. For other locations, open Manage Games Folders, add each game folder, then Import selected folders.</p>
          <p>Administrator access is unnecessary for writable folders owned by you.</p>
          <p>Disable and Remove restore the original game files. Unsupported renderers and protected games cannot be made compatible by administrator access.</p></div>} />))}>
        Installation guide</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={modalOpen} onClick={() => SteamClient.System.OpenInSystemBrowser("https://github.com/dawoodtogoo2020-code/HelixSR-Decky/blob/main/INSTALL_GUIDE.md")}>Open full guide</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={modalOpen} onClick={() => SteamClient.System.OpenInSystemBrowser("https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml")}>Report a problem</ButtonItem></PanelSectionRow>
      {setupOptions && <>
      <PanelSectionRow><ToggleField label="Accept local preparation terms" checked={!!data?.license_accepted}
        description="Uses the official HelixSR freeware release, NVIDIA DLSS under NVIDIA's license, portable Python, numpy and DXC. Network stays on this device. Review upstream licenses before accepting."
        onChange={accepted => void run(() => setLicense(accepted)).then(ok => setData(d => d ? { ...d, license_accepted: !!ok } : d))} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" onClick={() => SteamClient.System.OpenInSystemBrowser("https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE")}>Read HelixSR license</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" onClick={() => SteamClient.System.OpenInSystemBrowser("https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt")}>Read NVIDIA DLSS license</ButtonItem></PanelSectionRow>
      </>}
      {jobs.map(job => <PanelSectionRow key={job.id}><div style={infoStyle}>
        {job.game}: {job.state}{"\n"}{job.message}
        {job.state === "running" && <ButtonItem layout="below" disabled={busy || modalOpen} onClick={() => void interact(async () => openDialog(<ConfirmModal bDisableBackgroundDismiss strTitle="Cancel preparation?"
          strDescription="No game files are changed during preparation. Temporary build files will be removed."
          onOK={() => void run(() => cancelJob(job.id))} />))}>Cancel preparation</ButtonItem>}
        {diagnostics && <pre style={{ ...infoStyle, fontSize: "11px" }}>{job.log}</pre>}
      </div></PanelSectionRow>)}
    </PanelSection>
    <PanelSection title="Import games">
      <PanelSectionRow><DropdownItem layout="below" label="Import Games From" menuLabel="Import Games From"
        selectedOption={launcher} disabled={disabled} rgOptions={launcherOptions}
        onChange={option => chooseLauncher(String(option.data))} /></PanelSectionRow>
      <div className="helix-primary"><PanelSectionRow><ButtonItem layout="below" disabled={disabled}
        onClick={() => void interact(importFromLauncher)}>Import Now</ButtonItem></PanelSectionRow></div>
      <PanelSectionRow><div className="helix-muted">Detects installed games from the selected launcher. Compatibility is checked before HelixSR installation.</div></PanelSectionRow>
      {!!importMessage && <PanelSectionRow><div className="helix-card helix-muted" style={infoStyle}>{importMessage}</div></PanelSectionRow>}
      <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => { if (!interactionBusy && Date.now() >= interactionAfter) setImportOpen(!importOpen); }}>{importOpen ? "Hide Games Folders" : "Manage Games Folders"}</ButtonItem></PanelSectionRow>
      {importOpen && <>
      <PanelSectionRow><div className="helix-muted">Steam, Heroic, Legendary and Lutris are detected automatically. Add other game folders below.</div></PanelSectionRow>
      <PanelSectionRow><TextField label="Games Folder" value={folder} disabled={disabled} onChange={e => setFolder(e.target.value)} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => void interact(async () => { await run(async () => {
        const pick = await openFilePicker(1, folder || "/home/deck", false, true);
        queueFolders([...new Set([...pendingFolders, pick.realpath])]);
      }); })}>Add Games Folder</ButtonItem></PanelSectionRow>
      {!!folder && <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => { if (interactionBusy || Date.now() < interactionAfter) return; queueFolders([...new Set([...pendingFolders, folder])]); setFolder(""); }}>Add typed folder</ButtonItem></PanelSectionRow>}
      {!!folders.length && <PanelSectionRow><div className="helix-card helix-muted">{folders.join("\n")}</div></PanelSectionRow>}
      {folders.map(path => <PanelSectionRow key={path}><ButtonItem layout="below" disabled={disabled}
        onClick={() => queueFolders(pendingFolders.filter(p => p !== path))}>Remove folder: {path.split("/").filter(Boolean).pop()}</ButtonItem></PanelSectionRow>)}
      {!!folders.length && <PanelSectionRow><ButtonItem layout="below" disabled={disabled}
        onClick={() => queueFolders([])}>Clear selected folders</ButtonItem></PanelSectionRow>}
      <PanelSectionRow><ButtonItem layout="below" disabled={disabled || !folders.length} onClick={() => void run(() => importFolders(folders)).then(result => {
        if (result) { setData(result); queueFolders([]); }
      })}>Import selected folders ({folders.length})</ButtonItem></PanelSectionRow>
      </>}
      {(data?.warnings || []).length > 0 && <PanelSectionRow><ButtonItem layout="below" onClick={() => setDiscoveryNotes(!discoveryNotes)}>
        {discoveryNotes ? "Hide discovery notes" : `Show discovery notes (${data!.warnings.length})`}</ButtonItem></PanelSectionRow>}
      {discoveryNotes && <PanelSectionRow><div style={infoStyle}>{data?.warnings.join("\n")}</div></PanelSectionRow>}
    </PanelSection>
  </div>;
}

export default definePlugin(() => {
  pluginDisposed = false;
  if (pluginUpdateTimer) clearInterval(pluginUpdateTimer);
  pollPluginStatus();
  pluginUpdateTimer = setInterval(pollPluginStatus, 60000);
  if (typeof DeckyBackend !== "undefined" && DeckyBackend.addEventListener && DeckyBackend.removeEventListener) {
    DeckyBackend.addEventListener("loader/add_plugin_install_prompt", nativeUpdatePrompt);
    DeckyBackend.addEventListener("loader/plugin_download_start", nativeUpdateStarted);
    DeckyBackend.addEventListener("loader/plugin_download_finish", nativeUpdateFinished);
  }
  return ({
  name: "HelixSR Decky", titleView: <div className={staticClasses.Title}>HelixSR Decky</div>,
  content: <Content />, icon: <FaAdjust />, onDismount() {
    pluginDisposed = true;
    pluginInstaller.dispose();
    if (pluginUpdateTimer) clearInterval(pluginUpdateTimer);
    pluginUpdateTimer = undefined;
    if (typeof DeckyBackend !== "undefined" && DeckyBackend.removeEventListener) {
      DeckyBackend.removeEventListener("loader/add_plugin_install_prompt", nativeUpdatePrompt);
      DeckyBackend.removeEventListener("loader/plugin_download_start", nativeUpdateStarted);
      DeckyBackend.removeEventListener("loader/plugin_download_finish", nativeUpdateFinished);
    }
    if (jobTimer) clearInterval(jobTimer);
    jobTimer = undefined;
  },
  });
});
