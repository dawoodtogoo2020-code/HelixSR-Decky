# OptiScaler setup and troubleshooting

HelixSR has two installation routes. A **native FSR 3.1 replacement** uses the game's AMD FSR setting and does not require OptiScaler. The **OptiScaler proxy** route installs OptiScaler, fakenvapi, HelixSR and its locally prepared network automatically. DLSS, XeSS or FSR is the game's input; the selected OptiScaler backend determines the output. HelixSR does not add frame generation.

## Install and select the backend

1. Finish the game's download or Steam update and close it. Select the game in either manager. Read its compatibility reasons and target executable. Use the game's **DirectX 12** renderer. Confirm DX12 only when you have actually selected it; an unrelated executable's imports do not prove the selected game runs DX12.
2. Choose **Install HelixSR** or **Update HelixSR**. Review the changed files and local preparation terms, then wait for **HelixSR enabled**. This route adds the required OptiScaler files itself. If an existing unmanaged injector conflicts, remove it through its own installation method first. The manager does not overwrite unknown DLLs or automatically adopt an existing OptiScaler installation.
3. In Decky, choose **Review Proton proxy launch option** and confirm the before/after preview. It preserves supported existing environment assignments and arguments. The desktop app's **Copy manual launch guidance** gives instructions for Steam or another launcher; the desktop app does not save launch options for you.
4. For empty Steam launch options, use:

   ```text
   WINEDLLOVERRIDES="dxgi=n,b" %command%
   ```

   Preserve existing launch options. Do not paste this over an existing wrapper or a conflicting DXGI rule. Ambiguous shell syntax requires manual review. Decky saves a recovery intent before changing Steam, verifies the saved value, and lets you resume an interrupted change or restore its exact owned change. It refuses to overwrite options changed elsewhere.
5. Launch the game in DX12. Open OptiScaler with **Insert**, unless you changed `ShortcutKey`. Map Insert to a Steam Input back button if needed. Select **Upscaling → Upscalers → FFX → FSR HelixSR (3.1.5)**. The upstream menu name includes the FSR integration version; it is not the DLSS source model's version.
6. Enable an input that this game supports. If DLSS is unavailable, use supported FSR or XeSS input if offered. Seeing “DLSS” in the game's menu alone does not confirm HelixSR output. Check the selected FFX backend and a fresh `helixsr.log`, then inspect gameplay for artifacts and stability.

## If DLSS is missing or the game needs review

Open the selected game's **OptiScaler and frame generation** details in Decky, or its setup checks in the desktop **Games** page. The manager shows missing files, the DXGI override status, exact backend/provider paths, DLSS input settings, NVAPI handling and your overlay shortcut. These are file/configuration checks, separate from runtime evidence.

- **Needs review:** read the exact reason first. An unfinished Steam install, running game, changed game build, unmanaged proxy or damaged DLL needs a different remedy. Refresh after downloads finish. Do not reinstall a game just because the status says review.
- **Overlay does not open:** confirm DX12, the target executable/folder, proxy override and configured shortcut. Read a fresh `OptiScaler.log`. An installed DLL does not establish that the game loaded it.
- **DLSS input is disabled:** inspect `EnableDlssInputs` in the installed OptiScaler configuration. Automatic fakenvapi handling is version-specific; the bundled configuration currently exposes `OverrideNvapiDll` and `NvapiPath`. Custom choices and an existing `nvapi64.dll` are reported and preserved. Do not force NVIDIA spoofing or global Proton NVAPI flags across all games.
- **Different backend/provider paths:** review **Update HelixSR** to restore its managed backend and paths. Other valid configuration settings, comments, overlay shortcut and frame-generation choices are retained. Duplicate or malformed settings require manual review.
- **Red border, shaking or fallback:** inspect the current `helixsr.log` and report a short sanitized excerpt. Historical logs and mapped-module evidence do not prove current neural output or stable gameplay.

Disable/Enable retains your owned configurations. Remove restores originals and keeps configuration copies in `<Game> Mod Files/HelixSR-Decky/records/config-*.json` as installation records. DLL/network changes still block unsafe operations. Removing game files does not undo launch options; use Decky's separate **Restore plugin launch-option change** or merge desktop launch guidance manually.

[Report a reproducible issue](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Include the manager version, game, renderer, exact review reason and relevant fresh logs. Remove personal details; never upload generated weights or kernels.

Official references: [HelixSR troubleshooting](https://github.com/lonewolf0622/HelixSR#troubleshooting), [OptiScaler manual installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation), [Control Ultimate Edition notes](https://github.com/optiscaler/OptiScaler/wiki/Control-Ultimate-Edition). Upstream Control testing on Windows does not establish behavior on every SteamOS device.
