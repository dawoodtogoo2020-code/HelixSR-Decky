# HelixSR Decky: beginner installation guide

HelixSR Decky manages HelixSR files for supported Windows DirectX 12 games on SteamOS. You install the Decky plugin once, then install HelixSR separately for each game. A game listed as a candidate still needs a successful gameplay test. Control Ultimate Edition and PRAGMATA are currently being tested; this guide does not claim verified gameplay for either.

## 1. Download the plugin in Desktop Mode

1. Finish any Steam game download or update. Close the game you want to modify.
2. Open the Steam power menu and choose **Switch to Desktop**.
3. Open the [HelixSR Decky release](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/latest) and download **HelixSR-Decky-0.1.17.zip** under **Assets**. Do not select **Source code (zip)** or **Code → Download ZIP**: those contain source files rather than the ready-to-install plugin. It is distributed through GitHub and is currently not listed in the Decky Store.
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

## 4. Install HelixSR for one game

1. Open the **Game** dropdown at the top. Select your installed game. Choose **Refresh library and status** if you recently installed it. Steam, supported Steam shortcuts, Heroic, Legendary and Lutris records are detected automatically.
2. Read its status and route. **Needs review** or an unavailable game has a reason shown in the panel. Do not bypass a block. If asked, enable **Game is set to DirectX 12** only after confirming that renderer in the game's launch selection or settings.
3. Select the purple **Install HelixSR for this game** button directly beneath the game selector. An existing managed or supported legacy installation shows **Update this game's HelixSR** instead.
4. Review the selected game, changed files, download details and linked terms. Choose **Accept terms and install** when you agree. Preparation uses the [HelixSR license](https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE), [NVIDIA DLSS license](https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt) and required dependencies. Acceptance is tied to the release version and archive digest.
5. Allow downloads and local network preparation to finish. Required portable dependencies are handled automatically. A verified package already prepared on that drive can be reused. Keep the game closed. You can close the Quick Access panel while the background job continues.
6. Wait for the completion notification and check that the selected game says HelixSR is enabled. A failure notice needs attention before launch. Installed files and a completed job do not prove correct rendering or stability.

Keep locally generated network files on your device. Do not upload prepared packages, weights or kernels with a bug report.

**Offline use:** game detection, local diagnostics, Disable, Remove, and Enable with the exact verified prepared package work without GitHub access. HelixSR itself does not need an internet connection during gameplay. Installing a new release, updating game installations and checking available releases require internet access. **Check latest HelixSR version** checks the release metadata; **Update this game's HelixSR** applies it to the selected game.

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

1. In **HelixSR updates**, choose **Check for updates**, select a game, then **Update HelixSR** and review the change. Updates apply per game. Close it and wait for completion again. Updating the Decky plugin does not replace a game's HelixSR files.
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
