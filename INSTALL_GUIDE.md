# HelixSR Decky: beginner installation guide

## Finding controls in Decky

Choose **Game** and **Release to install** at the top. HelixSR version checks sit with the game installation controls. Plugin version and updates are grouped immediately below, followed by **Import games**. Expand **Advanced game settings** for model settings, the overlay, optional menu labels, diagnostics, **Disable HelixSR** and **Remove and restore originals**.

HelixSR 1.9.3 does not include its own frame generation. Alternative Scaler providers retain their settings and can be configured in Scaler's Frame Generation menu, subject to game, GPU and dependency requirements. Native FSR replacement installs use the game's available FG controls. A generic multiplier does not apply to every provider. To replace a modern Scaler installation with 1.8.1, remove HelixSR first to restore original files, then review a new installation.

## Installation error mentioning LICENSE-APACHE-2.0

Decky **0.1.30** and Desktop **0.1.19** support the reviewed official **HelixSR 1.9.3** release and its complete **Scaler 1.0.6** package. Select **Latest upstream**, then Install/Update and review the version and terms. The converter runs unchanged and builds Model E locally. Alternative frame-generation settings are preserved; HelixSR's own frame generation is unavailable. **Compatible HelixSR 1.8.1** remains an explicit option. Unknown releases or replaced 1.9.3 archives require another reviewed app update.

The compatibility download is tied to the reviewed official archive SHA-256 and the [1.8.1 license](https://github.com/lonewolf0622/HelixSR/blob/v1.8.1/LICENSE). A replaced archive is rejected. Newer or unverified existing installations are blocked from being downgraded; remove them using their owning manager first. Keep locally generated networks and game installation records.

HelixSR Decky manages HelixSR files for supported Windows DirectX 12 games on SteamOS. You install the Decky plugin once, then install HelixSR separately for each game. A game listed as a candidate still needs a successful gameplay test. Control Ultimate Edition and PRAGMATA are currently being tested; this guide does not claim verified gameplay for either.

## 1. Download the plugin in Desktop Mode

1. Finish any Steam game download or update. Close the game you want to modify.
2. Open the Steam power menu and choose **Switch to Desktop**.
3. Download the [Decky 0.1.30 install ZIP](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/download/v0.1.30/HelixSR-Decky-0.1.30.zip). When browsing [release Assets](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/latest), choose **HelixSR-Decky-VERSION.zip**, where VERSION matches the release. Do not select an older **-source.zip**, **-source.tar.gz**, GitHub's **Source code (zip)** or **Code → Download ZIP**. Those are developer files without the compiled plugin frontend. The plugin is distributed through GitHub and is currently not listed in the Decky Store.
4. Keep the plugin ZIP in **Downloads** and leave it zipped. The next steps select that ZIP directly inside Decky.

## 2. Install Decky Loader if needed

1. Skip this section if Decky already appears in your Quick Access menu.
2. Download the [official Decky installer](https://github.com/SteamDeckHomebrew/decky-installer/releases/latest/download/decky_installer.desktop). Follow the [official installation instructions](https://github.com/SteamDeckHomebrew/decky-loader#installation). If Firefox adds `.download` to the filename, rename it to `decky_installer.desktop`.
3. Move the installer to the desktop, open it, and choose the stable **Latest Release**. Follow its own prompts. Decky's installer permissions are separate from HelixSR's per-game operation.
4. Open **Return to Gaming Mode** on the desktop.

## 3. Install the plugin ZIP in Gaming Mode

1. Press the **Quick Access button**, the button with three dots on the right of the Deck. Open the **Decky** plug icon.
2. Open Decky's **gear icon** for Settings. Select **Developer**.
3. If Developer is missing, open **General**, enable **Developer mode**, then return to Developer. You do not need Valve's internal developer menu or remote debugging.
4. Under **Install Plugin from ZIP File**, choose **Browse**. Open your **Downloads** folder and select the packaged HelixSR-Decky ZIP.
5. Confirm the installation prompt. Wait for Decky to finish, then return to its plugin list and open **HelixSR Decky**. The ZIP picker selects a local file; you do not need to paste a URL or extract it.

If Decky disappears after a SteamOS update, follow Decky's own recovery instructions before troubleshooting this plugin.

### Failed to fetch dynamically imported module

This is a failure to load the Decky plugin's interface, before game detection or HelixSR installation. A developer source ZIP can cause it: Decky accepts the manifest, but that archive has no compiled `dist/index.js` interface. An incomplete plugin installation or a Decky loading problem can also produce this message.

1. Download the **install ZIP** linked in section 1. Check that the filename has no `-source` suffix and leave it zipped.
2. If you installed a **source ZIP**, first remove **HelixSR Decky only** through **Decky Settings → Plugins → Uninstall**. This removes the broken plugin code; its uninstall hook leaves per-game modifications alone. A source archive uses a different plugin folder, so installing over it can leave the broken copy selected. Keep the plugin's settings/data folders and all game installation records.
3. Use **Decky Settings → Developer → Install Plugin from ZIP File** to install the correct ZIP, and confirm the installation or **Update** prompt. Wait for completion, then reopen HelixSR Decky. Restart Steam if Decky still shows the old loading error.
4. Keep your per-game HelixSR files, settings and installation records. You do not need to remove or reinstall game modifications to repair the plugin interface.
5. If it still fails, [report the full error](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml), exact downloaded filename, Decky version, and SteamOS version/channel. Include the module URL and HTTP status if available. Remove private paths. The missing-interface reproduction does not establish the cause of every dynamic-import error.

From 0.1.25, the custom developer source download uses `.tar.gz` so it cannot be mistaken for an install ZIP. The release build checks that the install ZIP contains the compiled frontend and that its download links and checksums match the release.

From 0.1.27, detected games remain in the Game dropdown even when installation is blocked. Select a game to see the reason. EA anti-cheat helpers are not eligible game executables, and choosing another executable does not remove an anti-cheat block. A DX12 renderer alone does not establish compatibility. No anti-cheat files should be deleted to force installation.

If the library does not answer within 30 seconds, the panel reports the stalled read instead of loading indefinitely. Refresh checks the same outstanding scan without queuing duplicates. From 0.1.29, a result that completes after the timeout remains available to the next Refresh. Missing optional SQLite support no longer prevents Steam discovery; Lutris can use its game configuration files instead. If it still does not respond, restart Decky and include the HelixSR backend log in a bug report. Version 0.1.27 also isolates optional menu-label XML dependencies so missing parsers cannot prevent the backend from starting.

### Errors after a Steam update

Read the exact plugin name on Steam's error screen. An error naming **ProtonDB Badges** needs that plugin's troubleshooting; reinstalling HelixSR will not repair a different plugin. Restart Steam, then use Decky's settings to check updates or temporarily disable the named plugin to isolate the failure. Preserve your HelixSR game files and installation records.

If HelixSR itself will not install, distinguish **installing the plugin ZIP** from **installing HelixSR for a game**. Check **Current plugin**, then note the game, exact button or failing step, full error, SteamOS version/channel and Steam client/Decky versions. [Report those details](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml) with private paths removed. A Steam update occurring first does not establish the cause.

## 4. Install HelixSR for one game

**Not installed** means the plugin found the game but has not installed HelixSR into it. Selecting a game does not install anything. Follow **Next step** beside the game. If Install is disabled, its explanation tells you whether to confirm DX12, close the game, resolve a review reason, or finish another operation.

1. Open the **Game** dropdown at the top. Select your installed game. Choose **Refresh library and status** if you recently installed it. Steam, supported Steam shortcuts, Heroic, Legendary and Lutris records are detected automatically.
2. Read its status and route. **Needs review** or an unavailable game has a reason shown in the panel. Do not bypass a block. If asked, enable **Game is set to DirectX 12** only after confirming that renderer in the game's launch selection or settings.
   This checkbox appears only when DX12 needs confirmation. A detected DX12 executable or native FSR replacement can proceed without it. Its absence does not prove gameplay compatibility. For native FSR replacement, select **AMD FSR** in the game; this route does not add a DLSS menu option.
3. Select the purple **Install HelixSR for this game** button directly beneath the game selector. An existing managed or supported legacy installation shows **Update this game's HelixSR** instead.
4. Review the selected game, changed files, download details and linked terms. Choose **Accept terms and install** when you agree. Preparation uses the [HelixSR license](https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE), [NVIDIA DLSS license](https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt) and required dependencies. Acceptance is tied to the release version and archive digest.
5. Confirm once. **Starting installation** appears immediately while the backend accepts the request, followed by download and preparation progress. You do not need to press Install again. If the request fails, its error remains at the top of the panel even after reopening it. Required portable dependencies are handled automatically. A verified package already prepared on that drive can be reused. Keep the game closed. You can close the Quick Access panel while the background job continues.
6. Wait for the completion notification and check that the selected game says HelixSR is enabled. A failure notice needs attention before launch. Installed files and a completed job do not prove correct rendering or stability.

Keep locally generated network files on your device. Do not upload prepared packages, weights or kernels with a bug report.

**Offline use:** game detection, local diagnostics, Disable, Remove, and Enable with the exact verified prepared package work without GitHub access. HelixSR itself does not need an internet connection during gameplay. Installing a new release, updating game installations and checking available releases require internet access. **Check latest HelixSR version** checks the release metadata; **Update this game's HelixSR** applies it to the selected game.

### If no games appear

Check the summary at the top before importing anything:

- **Library scan failed** means the scan did not finish. Read the error there and refresh after resolving it. A previous successful scan stays visible.
- **0 games found** means no installed game directories were discovered. Open **Discovery notes** beside the game selector. Confirm Steam can see the installed games, and that the SD card or external library is mounted. Open Steam once after moving a library, then refresh. Use **Import Games From** for supported launchers, or import the individual game folder from a custom location.
- **Games found, but none selectable** means discovery worked. **Unavailable games** opens automatically when every entry is blocked; read each game's reason. Adding a folder or confirming DX12 cannot make an unsupported renderer compatible.

Version 0.1.18 isolates malformed Steam manifests, optional profile metadata and individual game assessment failures so one bad entry cannot discard healthy entries. Missing libraries and unreadable metadata have discovery notes. Detailed log, launch-option and frame-generation inspection runs when selecting a game. Directory scans remain bounded, and installation safety checks still run before any file changes.

The scan covers installed local games, not every title owned by your Steam account. If a large library still hangs or crashes, report the plugin version, device, installed game count, drive type and the summary/Discovery notes. Remove usernames and private paths first. A 6,000-manifest regression fixture is not a physical-device crash test.

## 5. Select the renderer and upscaler

The **HelixSR model** dropdown in the selected game's details shows supported networks. Currently it offers **HelixSR Model E**, sourced from NVIDIA DLSS 310.7.0. This is separate from selecting AMD FSR or DLSS in the game's settings. The confirmation shows the model and HelixSR release being installed. Future DLSS 4 or FSR-derived models require upstream files and reviewed app support before appearing here. See [model support](MODEL_VARIANTS.md).

**Enable** restores the recorded prepared package rather than upgrading to a newer cache. If an older disabled installation has no provable package identity, choose **Update HelixSR** and review the supported model instead. **Disable** and **Remove** still restore owned originals when model metadata needs review. Update both the Decky plugin and desktop app before using new model support on the same game.

1. Launch the game's **DirectX 12** version. Native Linux, Vulkan-only, DirectX 11 and 32-bit games are unsupported by this workflow. **God of War (2018) is DirectX 11 only**, so HelixSR cannot run in it. Having DLSS files does not change its renderer, and neither OptiScaler nor a DX12 launch option adds DirectX 12 support. Use the game's built-in upscaling instead. If an earlier plugin installed HelixSR, Disable or Remove can restore recorded originals after the normal file, Steam build and running-game checks pass. [Official game requirements](https://store.steampowered.com/app/1593500/).
2. For **Native FSR 3.1 replacement**, choose **AMD FSR** in the game. That selection reaches the replaced native upscaler.
3. For **OptiScaler proxy**, select the supported input shown for that game, commonly **DLSS**, or a supported XeSS/FSR input. OptiScaler forwards that input into HelixSR. The DLSS option is the game input; HelixSR executes DLSS Model E through its own shaders rather than NVIDIA's native runtime.
4. For a Steam OptiScaler game, use **Review Proton proxy launch option** if required. Review the proposed `WINEDLLOVERRIDES="dxgi=n,b"` change and confirm it once. The plugin preserves your other launch options and verifies the saved change. For Heroic or Lutris, apply the shown override in that launcher's settings instead.
5. Check the image, useful game audio, controller operation and stability during play. **Show diagnostics and logs** distinguishes configuration from recent runtime evidence. HelixSR supplies no frame generation of its own; native FG, LSFG-VK and MAKO remain separate settings.

## 6. Control Ultimate Edition

1. Wait until Steam's download and update are fully complete, then close Control and refresh the plugin library.
2. Select Control only if it is an installation candidate. Prefer its **DirectX 12** launch choice.
3. Follow the displayed route. Control may require the OptiScaler proxy and the reviewed Proton override. With that route, choose **DLSS as the input** feeding HelixSR.
4. The [upstream Control OptiScaler page](https://github.com/OptiScaler/OptiScaler/wiki/Control-Ultimate-Edition) lists OptiScaler 0.9.4, Windows 11 24H2 and DLSS input. This Windows result is not proof of SteamOS compatibility. Record your actual outcome and versions if testing fails.

## 7. Import games from other launchers

1. Scroll down to **Import games**. Open **Import Games From** and select **Heroic Games Launcher** or **Lutris**. **Legendary**, **Steam non-Steam shortcuts** and **All supported launchers** are also available.
2. Select **Import Now**. Wait for the result and notification showing how many installed games were found, how many are new and how many are installation candidates. Both native and Flatpak launcher records are checked. Heroic's installed Epic, GOG and Amazon games are supported. You do not need to open or sign in to the launcher.
3. Return to the **Game** dropdown and select a candidate. Select **Install HelixSR** and follow section 4. Importing finds games; it does not install HelixSR by itself. Unavailable games retain their compatibility reasons.
4. Import again after installing or moving a launcher game. Repeated imports do not duplicate games. A game already registered through Steam keeps its existing Steam entry. Launcher selection and the result survive closing the Quick Access panel, but reset when the plugin reloads.
5. If no games appear, confirm they are installed and their drive is mounted. Open **Discovery notes** if detection warnings are reported. For a custom launcher location, Heroic sideload app or unresolved shortcut, use the folder steps below.

### Add several game folders manually

1. Open **Manage Games Folders**, then **Add Games Folder**. Select one game's installation directory containing its Windows executable.
2. Repeat for each additional game. Choose individual game folders, not your entire home folder, drive or a parent holding many unrelated games.
3. Select **Import selected folders** to save the batch. The queue survives closing the Quick Access panel, but a plugin reload clears it. Every folder is checked before the batch is saved. Use **Remove folder** for an invalid entry, or **Clear selected folders** to start again, then retry.
4. Use writable folders owned by the Deck user. HelixSR runs without root and does not change SteamOS system packages. A read-only mount or another user's folder needs its location permissions resolved first. Administrator access cannot fix an unsupported renderer or protected game.

## 8. Updates, removal and troubleshooting

For the **Decky plugin itself**:

1. Users with v0.1.0 must install the current release ZIP through Decky Settings once. Users with v0.1.1 or newer can use the built-in updater.
2. Open **Plugin updates**. It shows **Current plugin** and **Latest plugin**. Leave **Check plugin updates automatically** on for a check when the plugin starts and once a day, or turn it off and choose **Check plugin updates** yourself.
3. When a newer plugin is available, finish any HelixSR preparation or game-file operation, then choose **Download plugin update**. Older plugin versions call this button **Update Decky plugin**. The ZIP is verified before Decky's installer opens. A completed download is not an installed update.
4. Review Decky's confirmation, choose **Update**, and wait for the plugin to reload. Check **Current plugin** afterward. The confirmation opening alone does not mean the update finished.
5. If the confirmation closes before you choose Update, choose **Open update confirmation** in the plugin. It reopens the exact verified download without downloading it again. If you want to cancel, close the native prompt first, then choose **Cancel downloaded update**. Older plugin versions use **Continue without updating**. Do not cancel staging after confirming installation. If Decky has not confirmed completion, restart Decky from its settings or restart the Deck, then check Current plugin. No administrator prompt is added by this plugin; Decky manages its own installation permissions.
6. If an update check fails, reconnect and try again. Automatic retries wait an hour. If your Decky version cannot open the installer from the plugin, download the new release ZIP and repeat section 3.

For **HelixSR inside a game**, and troubleshooting:

1. Select a game and release, choose **Check latest HelixSR version**, then **Update this game's HelixSR** and review the change. Updates apply per game. Close it and wait for completion again. Updating the Decky plugin does not replace a game's HelixSR files.
   The plugin follows the latest official stable HelixSR ZIP even if its size changes or upstream replaces the ZIP without changing the version number. New preparation checks the latest asset metadata, and changed bytes require fresh terms acceptance. A download must match GitHub's advertised size and SHA256. If the archive changes during downloading, check again and retry. If a future release changes its setup layout, preparation stops with a clear error rather than altering game files.
2. **Disable HelixSR** restores original files while retaining what is needed to enable it again. **Remove and restore originals** removes the managed installation. If used, separately choose **Restore plugin launch-option change**. Removing the Decky plugin itself does not remove game modifications.
3. For **game running** or incomplete Steam downloads, close it or wait, then refresh. For network failures, reconnect and retry after reviewing the message. For other injector conflicts, resolve the existing mod through its own installer before retrying; do not overwrite unknown DLLs.
4. A **Managed files changed** message means a file no longer matches the installed bytes recorded by HelixSR. The game shows **Needs review**; **Recorded route** describes the existing installation, not a fresh compatibility result. Steam verification may replace DLLs or remove mods, but it does not reconcile HelixSR's installed-file hash record and cannot by itself guarantee that the block clears. File-change and recovery guards must remain in place.
5. Close the game and read the exact conflicting filename. **Recover interrupted file transaction** restores only files that match its transaction; it stops if another process changed them. Preserve installation records and original files until ownership is resolved. Do not delete records or backups or force an installation. [Report the conflict](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml) with the filename, plugin and HelixSR versions, **Recorded route**, Proton version and short relevant logs, with personal details removed.

New native scans prefer DLLs in the game root or detected executable directory over nested SDK copies, then prefer the SR filename within that location tier. This does not move an existing managed installation or change its recorded targets. It does not establish that a Control crash is fixed.

If an older app reports **Network output missing or incomplete** while preparing HelixSR 1.8.0, update the **Decky plugin to 0.1.7 or newer**, then retry Install/Update HelixSR. This concerns generated model files, not your internet connection. The fix requests the separate output files supported by upstream. If preparation still fails, copy a short sanitized build-log excerpt; keep generated weights and kernels private.

For **Network build failed**, use plugin **0.1.8 or newer**. Preparation now checks installed Proton in external Steam libraries, custom tools and known Flatpak Steam locations, and probes whether each runtime starts on the host before selecting it. A Flatpak runtime may still need dependencies from its sandbox; detection alone does not guarantee shader compilation. The original upstream search remains the fallback. If no Proton is available, install a Proton version through Steam and retry. Permission or space errors require fixing the game drive first. Open **Show diagnostics and logs** for the selected game and copy only the final error lines from the build log, with private paths removed. These are local preparation errors, not proof of a game compatibility problem.

## 9. Report a problem

For exact blocked-game reasons, next steps, and the optional runtime overlay, read the [status and overlay guide](STATUS_GUIDE.md). **Game running** pauses file changes; it does not mean HelixSR is incompatible or has stopped. The overlay toggle checks helper health and reads new session log evidence, with visibility and image quality kept unverified.

Use [GitHub Issues](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new/choose). Include the game, plugin/HelixSR versions, SteamOS, Proton, route, OptiScaler and FG setup, steps, expected result and actual result. Paste only a short sanitized diagnostic excerpt. Reports are public: remove usernames, account details and private paths; never attach credentials, full home-folder data or generated network files. No email address is required.

Reports are assigned to the project owner. The owner can choose **Watch → All Activity**. GitHub inbox and email delivery follow the owner's [notification preferences](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications).

For exact OptiScaler setup, missing DLSS input, overlay shortcuts and settings retention, see the [OptiScaler guide](OPTISCALER_GUIDE.md).

## Dragon's Dogma 2

Read the **Detected route** first. For an **OptiScaler proxy** route, [OptiScaler's DD2 guide](https://github.com/optiscaler/OptiScaler/wiki/Dragons-Dogma-2) requires the matching DD2 build of REFramework (`dinput8.dll`) and links separate Linux loader troubleshooting. HelixSR Decky installs its own OptiScaler payload, but does not install or verify REFramework. An existing DLL with that name does not prove correct setup. Do not overwrite another mod or copy an old launch command blindly. Follow the game guide and preserve your existing launcher settings. A verified native FSR replacement is a different route and does not need these OptiScaler instructions.

This is setup guidance, not a verified Dragon's Dogma 2 Steam Deck compatibility claim. If installation stops, report your plugin version, displayed route, exact error or disabled-button explanation, and whether the unmodified game launches.
