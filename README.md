# HelixSR Decky

An independent Decky Loader plugin for managing HelixSR on SteamOS. It does not include HelixSR binaries or NVIDIA-derived weights. It downloads a complete official release and builds the network locally under the upstream licenses.

Created by Blackheart909. HelixSR is developed separately by [Lone Wolf](https://github.com/lonewolf0622/HelixSR); this plugin is an independent integration.

[Download the plugin ZIP](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/latest) · [Step-by-step installation guide](INSTALL_GUIDE.md) · [Report a problem](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml)

## Features

* Discovers installed Steam games across library drives, Steam shortcuts with executable paths, Heroic, Legendary and Lutris installation records. Import other Windows game folders through the file picker. Native Linux games, emulators and unresolved launcher wrappers remain unsupported or require a folder import.
* Separates static compatibility candidates, managed file state and recent runtime evidence. HelixSR requires DirectX 12, x64 Windows game binaries through Proton and AMD RDNA 1 or newer. A DLL filename does not prove a game uses a supported renderer.
* Checks upstream stable releases with a six-hour metadata cache, ETag support, bounded downloads and SHA256 verification. Version 1.7.0 additionally has an independently pinned archive digest. Updates are applied per game only after review.
* Prepares locally generated network files as a cancellable background job. Acceptance is tied to the selected release digest. Uses upstream portable dependencies and a separate compiler prefix; never changes SteamOS system packages or a game prefix.
* Supports install, update, disable, enable, remove, explicit adoption of a legacy native HelixSR installation and recovery of interrupted transactions. Keeps essential originals and installation records in a named companion folder beside the game on the same filesystem. Cleans completed staging and temporary transaction copies.
* Reports OptiScaler files, whether the selected Helix route involves OptiScaler, mapped-module evidence where available and bounded log excerpts. Reports native game frame-generation settings, OptiScaler configuration, matching MAKO/LSFG-VK profiles and running-process environment separately. A configured multiplier or installed plugin is not proof of active frame generation.
* Blocks detected anti-cheat, active games, incomplete Steam installs/download staging, wrong architecture, unmanaged injector conflicts and changed managed files. Uses no root plugin flag.

## Install

1. Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
2. Open Decky Settings, Developer, and install `HelixSR-Decky-0.1.0.zip` from a file. The ZIP is built from this source tree and contains the plugin's code only.
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
python3 scripts/package.py
```

## Verification boundaries

Tests cover synthetic file/API fixtures, transactions, conflict detection, safe extraction, library imports and source-aware diagnostics. Real rendering depends on game, Proton, driver and upstream HelixSR version. Recent logs are evidence of the current process only when their timestamp is after its start; visual quality, controller navigation, frame pacing and prolonged stability require device testing. The plugin never labels static candidates as proven compatible. Anti-cheat detection is conservative but cannot enumerate every proprietary protection system.

This plugin is independent of the HelixSR, OptiScaler and Decky projects. It cannot make unsupported renderers compatible, cannot inject into arbitrary native Vulkan/Linux titles, and cannot guarantee zero defects across all games.

## Bug reports

Use the [bug-report form](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Reports are assigned to the project owner. Include the game, plugin and HelixSR versions, Proton, renderer, OptiScaler/FG setup and steps to reproduce. A short sanitized log excerpt is optional. GitHub issues are public: omit account information and private paths, and never attach generated weights, kernels or prepared packages. No email address is required.

This is an initial beta. Per-game gameplay compatibility remains dependent on the renderer, Proton and HelixSR version. Installation candidates are not a guarantee of rendering quality or prolonged stability.
