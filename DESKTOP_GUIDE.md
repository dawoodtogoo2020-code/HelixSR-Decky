# HelixSR Desktop installation guide

HelixSR Desktop is a standalone Linux app. Decky Loader is optional. It manages HelixSR for compatible 64-bit Windows DirectX 12 games running through Proton or Wine.

## Download and open

1. Switch your SteamOS device to Desktop Mode.
2. Download **HelixSR-Desktop-0.1.12-x86_64.AppImage** from the [desktop release](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/releases/tag/desktop-v0.1.12). Save it in a folder such as `Applications` under your own home folder.
3. In your file manager, right-click the AppImage, open **Properties → Permissions**, and enable **Is executable** (wording varies).
4. Double-click the AppImage. Do not run it with sudo or as administrator.

If your system cannot mount AppImages, open a terminal in its folder and run:

```sh
chmod +x HelixSR-Desktop-0.1.12-x86_64.AppImage
./HelixSR-Desktop-0.1.12-x86_64.AppImage --appimage-extract-and-run
```

This fallback extracts the app temporarily and does not require FUSE or administrator access. [AppImage documentation](https://docs.appimage.org/user-guide/troubleshooting/fuse.html) explains the options.

## Find and install a game

1. Steam libraries and installed games from known launcher locations are detected automatically. Click **Refresh games** if a download just finished.
2. Choose a game from the dropdown. Unavailable entries show a reason and cannot be installed.
3. For another launcher, choose **Import games from → Heroic, Lutris, Legendary, or Steam shortcuts**, then **Import now**. The app reads installed records; it does not start the launcher or alter its database.
4. For an unlisted game, use **Import game folders → Add folder**. Add each game's install folder to the list, then choose **Import listed folders**. You can remove a mistaken entry before importing. Select each game's install folder, not an entire drive or Wine prefix.
5. Close the game. Click **Install HelixSR** or **Update HelixSR**, review the files and terms, and confirm. Only confirm DirectX 12 when your game's selected renderer uses it.
   For a new OptiScaler installation with more than one executable, use **Game executable** to choose the DX12 executable you actually launch before installing. Games labelled **Choose executable** need an eligible x64 selection first. The file review binds that selection. Existing installations keep their recorded folder; remove them through the manager before changing it. See the [OptiScaler guide](OPTISCALER_GUIDE.md).
6. Wait for **HelixSR enabled**. Downloads, dependencies and local network preparation happen automatically. Keep at least 3 GiB free on the game's drive while preparing.
7. Follow the displayed launch-option guidance. For native FSR replacement, select AMD FSR in the game's settings. For an OptiScaler route, follow the displayed input and Proton override instructions. The desktop app displays these instructions and does not change Steam launch options for you.

For setup checks, missing DLSS input, shortcuts and configuration retention, follow the [OptiScaler guide](OPTISCALER_GUIDE.md).

The app distinguishes detected OptiScaler files, configuration and available runtime evidence. Frame generation is reported separately and is preserved. Presence of files does not prove a feature is active in gameplay.

For a managed game, **Recorded route** describes its existing installation. New native scans prefer DLLs in the game root or detected executable directory over nested SDK copies, then prefer the SR filename within that location tier. Existing managed targets are not migrated. This does not establish that a Control crash is fixed.

## Updates and removal

The **HelixSR model** dropdown on the Games tab shows supported networks. Currently **HelixSR Model E**, sourced from NVIDIA DLSS 310.7.0, is the only reviewed choice. The confirmation binds the model and release shown; an upstream change requires another review. DLSS 4 and FSR-derived models will appear only after upstream release and app support. See [model support and future variants](MODEL_VARIANTS.md).

**Enable** uses the recorded package instead of silently choosing a newer cache. For older disabled records whose exact package cannot be proven, use **Update HelixSR** and review the change. Model metadata problems do not prevent restoring owned originals through Disable or Remove. For model support, update both managers to Decky **0.1.9** and desktop **0.1.5** or newer before using them on the same game.

**HelixSR updates** checks the current official upstream release. It downloads fresh release metadata, validates the official archive size and SHA-256, and prepares network files on your device. A changed upstream format or failed integrity check stops installation with an explanation.

**App updates** checks desktop releases separately from Decky releases. Automatic checks can be switched on or off. Downloading a newer AppImage verifies its official release metadata and saves a separate executable in your desktop configuration folder's `app-updates` directory. Close the old app, open the new downloaded AppImage, and replace your shortcut when ready. Downloads do not automatically execute code or overwrite the running app.

Use **Disable**, **Enable**, or **Remove** from the selected game when its ownership checks pass. Removal restores the original files. These local actions reuse verified prepared packages from either app and do not need a new upstream download. If an interrupted transaction is reported, close the game and use the reviewed recovery action. Do not delete its recovery journal manually.

A **Managed files changed** message means the conflicting file no longer matches HelixSR's recorded installed bytes. The status is **Needs review**, even if the record says HelixSR was enabled. Steam verification may replace DLLs or remove mods, but it does not reconcile HelixSR's installed-file hash record and cannot by itself guarantee that the block clears. Keep mutation and recovery guards in place; interrupted-transaction recovery stops when live files differ from its allowed hashes.

Close the game and read the exact conflicting filename. Preserve installation records and original files until ownership is resolved. Do not delete records or backups or force an install. [Report the conflict](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml) with the filename, desktop and HelixSR versions, **Recorded route**, Proton version and short relevant logs, with personal details removed.

Both apps share installation records beside each game in `<Game> Mod Files/HelixSR-Decky`. Desktop preferences are separate under `$XDG_CONFIG_HOME/helixsr-desktop`, or `~/.config/helixsr-desktop` by default. Locally generated NVIDIA-derived network files must remain on the device where they were generated.

If you also use Decky, update the plugin to **0.1.4 or newer** before using both managers. Those versions coordinate through a per-game lock. Older Decky versions do not participate in that protection. Avoid running both managers on the same game with an older plugin.

## Device and game support

The AppImage targets **Linux x86_64 with glibc 2.35 or newer**, including Steam Deck, other SteamOS handhelds, and Steam Machine. It uses the signed-in Linux user's home and launcher locations rather than assuming the account is called `deck`. It has no ARM64 build.

Hardware portability and game compatibility are separate. HelixSR has its own [upstream requirements and limitations](https://github.com/lonewolf0622/HelixSR). A game's name, SteamOS support, or an AMD vendor ID alone does not establish HelixSR compatibility. Native Linux, DirectX 11 and Vulkan game rendering are not supported installation routes. Anti-cheat and unsupported installations are blocked.

Steam Deck is the device used for release runtime checks. Other SteamOS devices and Steam Machine are supported targets; physical validation on those models is still needed. UI startup and file verification do not establish gameplay stability or performance in every game.

If an older app reports **Network output missing or incomplete** with HelixSR 1.8.0, use **App updates** to download desktop **0.1.3 or newer**, open the new AppImage, then retry Install/Update HelixSR. This concerns generated model files, not your internet connection. If it persists, include a short sanitized build-log excerpt in your report.

For **Network build failed**, update to desktop **0.1.4 or newer**. Preparation checks installed Proton in external Steam libraries, custom tools and known Flatpak Steam locations, and uses a discovered runtime only if it starts on the host. Flatpak sandbox dependencies can still prevent shader compilation; the original upstream search remains the fallback. Install Proton through Steam if none is available, and resolve any drive permission or free-space error before retrying. The **Jobs** tab shows preparation output; selected-game diagnostics also include retained build logs. Include only the final error lines with private paths removed in a bug report. A local build failure does not establish that the game itself is incompatible.

## Report a problem

The Games tab now shows exact blockers and next steps beside the controls. Its optional status-overlay toggle checks HUD helper health and monitors new runtime events. See the [status and overlay guide](STATUS_GUIDE.md) for **Game running**, changed-file ownership, runtime evidence and experimental display support.

Open [a bug report](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Include the app or plugin version, device model, SteamOS/Linux version, launcher, game, selected renderer, and the exact error. Copy the relevant diagnostics or build log after removing personal paths or other private information. Do not upload generated weights, kernels, entire game folders or credentials.

You can also comment on the [HelixSR video](https://www.youtube.com/watch?v=atLknP_heZY). GitHub issues keep reproducible reports and fix tracking in one place.

## Run from source

Use Python 3.11 or newer and a user-owned virtual environment. Install `PySide6-Essentials==6.11.2` and `shiboken6==6.11.2`, then run `python -m desktop.app` from the repository. The [source](https://github.com/dawoodtogoo2020-code/HelixSR-Decky) includes the desktop backend, native UI, regression tests and build scripts.
