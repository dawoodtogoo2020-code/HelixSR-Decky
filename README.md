# HelixSR Decky

Decky **0.1.31** and Desktop **0.1.20** add the reviewed official **HelixSR 2.0.0** release and **Scaler 1.1.0**. Select **Latest upstream**, scan, then review Install/Update. The unchanged official converter builds the upscaling network and both Light/Full frame-generation models locally. Per-game Scaler settings are editable in the plugin and desktop app. **Compatible HelixSR 1.8.1** remains available explicitly. Future releases are detected by scanning; an unfamiliar version or replaced archive requires a reviewed app update before installation. See [2.0 settings and compatibility](UPGRADE_2.0.md).

An independent Decky Loader plugin for managing HelixSR on SteamOS. It does not include HelixSR binaries or NVIDIA-derived weights. It downloads a complete official release and builds the network locally under the upstream licenses.

Created by Blackheart909. HelixSR is developed separately by [Lone Wolf](https://github.com/lonewolf0622/HelixSR); this plugin is an independent integration.

[Support Blackheart909 on Ko-fi](https://ko-fi.com/blackheart909). Optional support helps with my work on this independent plugin and my other projects. HelixSR is developed separately by Lone Wolf.

[Download Decky 0.1.30 install ZIP](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/download/v0.1.30/HelixSR-Decky-0.1.30.zip) · [All releases](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/latest) · [Step-by-step installation guide](INSTALL_GUIDE.md) · [Desktop AppImage and guide](DESKTOP_GUIDE.md) · [OptiScaler setup](OPTISCALER_GUIDE.md) · [Report a problem](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml)

Use the **install ZIP** in Decky. Developer source archives, including older `-source.zip` files and GitHub's **Source code** downloads, cannot run as a plugin. If Decky reports **Failed to fetch dynamically imported module**, follow the [repair steps](INSTALL_GUIDE.md#failed-to-fetch-dynamically-imported-module).

## Features

* Optional [native menu labels](docs/menu-labels.md) rename The Witcher 3's direct-route FSR option to **Helix SR**. Off by default, with reviewed changes and exact original restoration. This is cosmetic; visible in-game verification is pending. Other games need separate verified adapters.
* Clear installation reasons and next steps in both interfaces, plus an optional experimental status HUD. Running games remain inspectable while file changes are paused. Runtime output and overlay helper health are separate. See the [status and overlay guide](STATUS_GUIDE.md) for evidence levels and display limitations.

* The Decky plugin and desktop app share a **HelixSR model** selector and display the installed model separately from the release and input route. Currently the reviewed choice is **Model E, sourced from NVIDIA DLSS 310.7.0**. DLSS 4 or FSR-derived networks are not selectable yet. Unknown conversion recipes stop before building or changing a game; updating the app can add reviewed model support. See [model support and future variants](MODEL_VARIANTS.md).

* Checks this Decky plugin's own GitHub releases on startup and once a day, with a saved opt-out and manual check. Shows current/latest plugin versions separately from HelixSR. Downloads and verifies the update's SHA256, size, manifests, required modules and complete ZIP before opening Decky's confirmation. Plugin updates wait for game operations to finish; they do not update per-game HelixSR installations.
* Discovers installed Steam games across library drives, Steam shortcuts with executable paths, Heroic, Legendary and Lutris installation records. **Import Games From → Import Now** rescans a selected launcher and reports found games, new entries and installation candidates without duplicates. Native and Flatpak launcher locations are supported. Import other Windows game folders through the file picker. Native Linux games, emulators and unresolved launcher wrappers remain unsupported or require a folder import.
* Separates static compatibility candidates, managed file state and recent runtime evidence. HelixSR requires DirectX 12, x64 Windows game binaries through Proton and AMD RDNA 1 or newer. A DLL filename does not prove a game uses a supported renderer.
* Detects official HelixSR updates, verifies archive size and SHA256, and supports the reviewed 2.0.0 package. Unknown releases never silently replace working files.
* Prepares locally generated network files as a cancellable background job. Acceptance is tied to the selected release digest. Uses upstream portable dependencies and a separate compiler prefix; never changes SteamOS system packages or a game prefix.
* Supports install, update, disable, enable, remove, explicit adoption of a legacy native HelixSR installation and recovery of interrupted transactions. Keeps essential originals and installation records in a named companion folder beside the game on the same filesystem. Cleans completed staging and temporary transaction copies.
* Reports OptiScaler files, whether the selected Helix route involves OptiScaler, mapped-module evidence where available and bounded log excerpts. Reports native game frame-generation settings, OptiScaler configuration, matching MAKO/LSFG-VK profiles and running-process environment separately. A configured multiplier or installed plugin is not proof of active frame generation.
* Explains missing OptiScaler/DLSS input, proxy override conflicts, backend/provider mismatches and overlay shortcuts. Preserves owned configuration edits through updates and disable/enable; removal retains configuration installation records. Reviewed Steam launch changes have durable recovery intents and preserve existing supported environment assignments.
* Blocks detected anti-cheat, active games, incomplete Steam installs/download staging, wrong architecture, unmanaged injector conflicts and changed managed files. Conflicted installations show Needs review with their recorded state and route. Native discovery prefers DLLs beside the game or executable before nested SDK copies; existing managed targets stay recorded. Uses no root plugin flag.

## Install

1. Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
2. Open Decky Settings, Developer, and install the current `HelixSR-Decky` release ZIP from a file. The ZIP is built from this source tree and contains the plugin's code only. Users of v0.1.0 need this one manual upgrade to get the plugin updater. Users of v0.1.1 can use **Plugin updates**.
3. Open HelixSR Decky and choose a game from the **Game** dropdown. Choose **Install HelixSR for this game** or **Update this game's HelixSR** directly below it, review the change and accept local preparation terms. The plugin handles required downloads, local preparation and per-game installation in one background operation and notifies you when it completes.
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

Automatic checks run on startup and once a day and only notify you. They never silently replace the plugin. Network failures retain an explicit error; automatic retries wait an hour. If the installer bridge is unavailable, use the release ZIP through Decky Settings → Developer. Game payload updates use **Check latest HelixSR version** and **Update this game's HelixSR** beside the game and release selection. These checks follow current release metadata without fixed plugin-version URLs.

## Import launcher games

Scroll to **Import games**, choose **Import Games From**, select **Heroic Games Launcher**, **Lutris**, **Legendary**, **Steam non-Steam shortcuts** or **All supported launchers**, then choose **Import Now**. This reads local installed-game records and refreshes compatibility. Heroic's installed Epic, GOG and Amazon records are supported. Games you own but have not installed are not imported. Existing Steam entries keep their Steam identity when a launcher points to the same folder. Importing does not install HelixSR; select an installation candidate in **Game**, then use **Install HelixSR**.

Custom launcher locations, Heroic sideload apps and shortcut wrappers may need **Manage Games Folders → Add Games Folder**. The selected launcher and last import result survive closing the Quick Access panel; a plugin reload resets them. Detection warnings appear in **Discovery notes**.

## Bug reports

Use the [bug-report form](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Reports are assigned to the project owner. Include the game, plugin and HelixSR versions, Proton, renderer, OptiScaler/FG setup and steps to reproduce. A short sanitized log excerpt is optional. GitHub issues are public: omit account information and private paths, and never attach generated weights, kernels or prepared packages. No email address is required.

This is an initial beta. Per-game gameplay compatibility remains dependent on the renderer, Proton and HelixSR version. Installation candidates are not a guarantee of rendering quality or prolonged stability.

## Standalone desktop app

The native Linux AppImage is available separately from Decky. Follow the [desktop guide](DESKTOP_GUIDE.md) for download, installation, launcher imports and updates. It targets x86_64 SteamOS and Linux without administrator access. See the guide for hardware testing limits. Update Decky to 0.1.4 or newer before using both managers on the same game.
