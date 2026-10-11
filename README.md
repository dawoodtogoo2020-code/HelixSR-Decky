# HelixSR Decky

An independent Decky Loader plugin for managing HelixSR on SteamOS. It does not include HelixSR binaries or NVIDIA-derived weights. It downloads a complete official release and builds the network locally under the upstream licenses.

Created by Blackheart909. HelixSR is developed separately by [Lone Wolf](https://github.com/lonewolf0622/HelixSR); this plugin is an independent integration.

[Download the plugin ZIP](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases) · [Step-by-step installation guide](INSTALL_GUIDE.md) · [Report a problem](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml)

## Features

* Checks this Decky plugin's own GitHub releases on startup and once a day, with a saved opt-out and manual check. Shows current/latest plugin versions separately from HelixSR. Downloads and verifies the update's SHA256, size, manifests, required modules and complete ZIP before opening Decky's confirmation. Plugin updates wait for game operations to finish; they do not update per-game HelixSR installations.
* Discovers installed Steam games across library drives, Steam shortcuts with executable paths, Heroic, Legendary and Lutris installation records. **Import Games From → Import Now** rescans a selected launcher and reports found games, new entries and installation candidates without duplicates. Native and Flatpak launcher locations are supported. Import other Windows game folders through the file picker. Native Linux games, emulators and unresolved launcher wrappers remain unsupported or require a folder import.
* Separates static compatibility candidates, managed file state and recent runtime evidence. HelixSR requires DirectX 12, x64 Windows game binaries through Proton and AMD RDNA 1 or newer. A DLL filename does not prove a game uses a supported renderer.
* Follows the latest official stable HelixSR release, including replaced archives with the same version and changed download sizes. Refreshes GitHub asset metadata before preparation and verifies its current size and SHA256. Uses a six-hour metadata cache for other checks. Updates are applied per game only after review; changed archives require renewed consent. Network errors stay visible and never substitute an obsolete archive.
* Prepares locally generated network files as a cancellable background job. Acceptance is tied to the selected release digest. Uses upstream portable dependencies and a separate compiler prefix; never changes SteamOS system packages or a game prefix.
* Supports install, update, disable, enable, remove, explicit adoption of a legacy native HelixSR installation and recovery of interrupted transactions. Keeps essential originals and installation records in a named companion folder beside the game on the same filesystem. Cleans completed staging and temporary transaction copies.
* Reports OptiScaler files, whether the selected Helix route involves OptiScaler, mapped-module evidence where available and bounded log excerpts. Reports native game frame-generation settings, OptiScaler configuration, matching MAKO/LSFG-VK profiles and running-process environment separately. A configured multiplier or installed plugin is not proof of active frame generation.
* Blocks detected anti-cheat, active games, incomplete Steam installs/download staging, wrong architecture, unmanaged injector conflicts and changed managed files. Uses no root plugin flag.

## Install

1. Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
2. Open Decky Settings, Developer, and install `HelixSR-Decky-0.1.3.zip` from a file. The ZIP is built from this source tree and contains the plugin's code only. Users of v0.1.0 need this one manual upgrade to get the plugin updater. Users of v0.1.1 can use **Plugin updates**.
3. Open HelixSR Decky and choose a game from the **Game** dropdown. Choose **Install HelixSR** or **Update HelixSR** directly below it, review the change and accept local preparation terms. The plugin handles required downloads, local preparation and per-game installation in one background operation and notifies you when it completes.
4. Select AMD FSR for a direct native replacement; for the OptiScaler route select the appropriate DLSS/XeSS/FSR input. See the included [installation guide](INSTALL_GUIDE.md) for multiple folder imports, permissions and removal.
5. An OptiScaler proxy may need `WINEDLLOVERRIDES="dxgi=n,b"` before the existing Steam launch command. Preserve other options. The plugin reports the route and logs, but does not rewrite Steam's live VDF files. See [OptiScaler installation](https://github.com/OptiScaler/OptiScaler/wiki/Installation).

Disable restores the original game files while keeping the plugin's prepared package and essential originals needed for enabling again. Remove restores originals and removes the managed record/original store. Removing the Decky plugin itself does not remove game modifications: remove them per game first. Prepared packages and portable dependencies are retained for re-use; they contain local-only network files and must not be uploaded. They can be deleted when no managed game needs that version.

## Build and test

Requires Node, pnpm and Python 3.11 or newer. The backend uses only Python's standard library. Older Python versions have a restricted TOML profile parser fallback; current Decky uses a sufficiently recent Python runtime.

```
pnpm install
pnpm typecheck
pnpm build
python3 tests/test_backend.py
pnpm test:frontend
python3 -m unittest discover -s tests -p 'test_*.py'
pnpm audit --audit-level=low
python3 scripts/package.py
```

## Verification boundaries

Tests cover synthetic file/API fixtures, transactions, conflict detection, safe extraction, library imports and source-aware diagnostics. Real rendering depends on game, Proton, driver and upstream HelixSR version. Recent logs are evidence of the current process only when their timestamp is after its start; visual quality, controller navigation, frame pacing and prolonged stability require device testing. The plugin never labels static candidates as proven compatible. Anti-cheat detection is conservative but cannot enumerate every proprietary protection system.

This plugin is independent of the HelixSR, OptiScaler and Decky projects. It cannot make unsupported renderers compatible, cannot inject into arbitrary native Vulkan/Linux titles, and cannot guarantee zero defects across all games.

## Plugin updates

Open **Plugin updates**, check for updates and choose **Download plugin update**. Downloading alone does not install it: press **Update** in Decky's confirmation and wait for the plugin to reload. Verify **Current plugin** afterward. If the screen closes, choose **Open update confirmation**; it reuses the verified ZIP and cancels the previous native request. To abandon a downloaded update, close the native screen and choose **Cancel downloaded update**. If installation status is unresolved, restart Decky before retrying. Restart invalidates orphaned download prompts. Older plugin versions label the download button **Update Decky plugin** and require the same native confirmation.

Automatic checks run on startup and once a day and only notify you. They never silently replace the plugin. Network failures retain an explicit error; automatic retries wait an hour. If the installer bridge is unavailable, use the release ZIP through Decky Settings → Developer. **HelixSR updates** is the separate section for game payloads. These checks follow current release metadata without fixed plugin-version URLs.

## Import launcher games

Scroll to **Import games**, choose **Import Games From**, select **Heroic Games Launcher**, **Lutris**, **Legendary**, **Steam non-Steam shortcuts** or **All supported launchers**, then choose **Import Now**. This reads local installed-game records and refreshes compatibility. Heroic's installed Epic, GOG and Amazon records are supported. Games you own but have not installed are not imported. Existing Steam entries keep their Steam identity when a launcher points to the same folder. Importing does not install HelixSR; select an installation candidate in **Game**, then use **Install HelixSR**.

Custom launcher locations, Heroic sideload apps and shortcut wrappers may need **Manage Games Folders → Add Games Folder**. The selected launcher and last import result survive closing the Quick Access panel; a plugin reload resets them. Detection warnings appear in **Discovery notes**.

## Bug reports

Use the [bug-report form](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Reports are assigned to the project owner. Include the game, plugin and HelixSR versions, Proton, renderer, OptiScaler/FG setup and steps to reproduce. A short sanitized log excerpt is optional. GitHub issues are public: omit account information and private paths, and never attach generated weights, kernels or prepared packages. No email address is required.

This is an initial beta. Per-game gameplay compatibility remains dependent on the renderer, Proton and HelixSR version. Installation candidates are not a guarantee of rendering quality or prolonged stability.
