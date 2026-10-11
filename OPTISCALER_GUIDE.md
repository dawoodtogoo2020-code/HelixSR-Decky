# OptiScaler setup and troubleshooting

HelixSR has two installation routes. A **native FSR 3.1 replacement** uses the game's AMD FSR setting and does not require OptiScaler. The **OptiScaler proxy** route installs OptiScaler, fakenvapi, HelixSR and its locally prepared network automatically. DLSS, XeSS or FSR is the game's input; the selected OptiScaler backend determines the output. HelixSR does not add frame generation.

For a managed game, **Recorded route** identifies its existing installation. New native scans prefer DLLs in the game root or detected executable directory over nested SDK copies, then prefer the SR filename within that location tier. This does not migrate managed targets or establish that a Control crash is fixed.

## Install and select the backend

1. Finish the game's download or Steam update and close it. Select the game in either manager. Read its compatibility reasons and target executable. Use the game's **DirectX 12** renderer. Confirm DX12 only when you have actually selected it; an unrelated executable's imports do not prove the selected game runs DX12.
   If **Game executable** appears, choose the executable you actually launch. Games with separate DX11 and DX12 folders need the DX12 executable, for example `bin/x64_dx12/witcher3.exe`. The default is a detection guess, and **DX12 detected** describes that executable's imports, not verified game compatibility. The confirmation lists the selected executable and files before installation. Existing installations keep their recorded folder; remove through the manager before selecting another executable. This does not diagnose every Control crash or change the game's renderer for you.
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
- **Managed files changed:** the conflicting file no longer matches HelixSR's recorded installed bytes. Close the game and read the exact filename. Steam verification may replace DLLs, but it does not reconcile the installed-file hash record or guarantee that the block clears. Keep mutation and recovery guards in place; preserve records and original files until ownership is resolved. Do not delete records or backups or force an install. [Report the conflict](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml) with the filename, manager and HelixSR versions, **Recorded route**, Proton version and short fresh logs, with personal details removed. Interrupted-transaction recovery also stops when live files differ from its allowed hashes.
- **Overlay does not open:** confirm DX12, the target executable/folder, proxy override and configured shortcut. Read a fresh `OptiScaler.log`. An installed DLL does not establish that the game loaded it.
- **DLSS input is disabled:** inspect `EnableDlssInputs` in the installed OptiScaler configuration. Automatic fakenvapi handling is version-specific; the bundled configuration currently exposes `OverrideNvapiDll` and `NvapiPath`. Custom choices and an existing `nvapi64.dll` are reported and preserved. Do not force NVIDIA spoofing or global Proton NVAPI flags across all games.
- **Different backend/provider paths:** review **Update HelixSR** to restore its managed backend and paths. Other valid configuration settings, comments, overlay shortcut and frame-generation choices are retained. Duplicate or malformed settings require manual review.
- **Red border, shaking or fallback:** inspect the current `helixsr.log` and report a short sanitized excerpt. Historical logs and mapped-module evidence do not prove current neural output or stable gameplay.

## If game controls stop working

Close the OptiScaler overlay first and test controls again. Record whether the controller, keyboard/mouse or both stop, and whether controls return after disabling HelixSR through the manager and restarting the game.

For the **OptiScaler proxy route**, upstream documents a Steam Input conflict: `[Hotfix] DisableOverlays` also blocks Steam Input. Its `auto` setting normally means false, but becomes true with OptiFG. This is a possible cause, not a diagnosis for every controller problem. The native FSR replacement route does not install OptiScaler.

If you use Steam Input and this setting is involved, close the game, record its original value and try `DisableOverlays=false` in the installed `OptiScaler.ini`, as described in [OptiScaler's known issues](https://github.com/optiscaler/OptiScaler/wiki/Known-Issues). Restart and test. Overlay blocking exists for compatibility reasons; restore the original value if enabling overlays causes crashes or other regressions. Change one setting at a time. The manager preserves these custom settings during updates.

If the problem continues, [report it here](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml) with your device/OS, manager version, game, DX12 renderer, displayed route, frame-generation setup and a short fresh `OptiScaler.log` excerpt. Include the current `DisableOverlays`, `ManualInputPolling`, `OverlayMenu` and `ShortcutKey` values when present. Remove personal paths and information. File checks cannot establish which input hooks ran in your game.

## Using another mod manager or Decky-Framegen

[Decky-Framegen](https://github.com/xXJSONDeruloXx/Decky-Framegen) also manages OptiScaler and can apply configuration through its `fgmod` launch wrapper. Its launch environment settings can override the INI on each launch. HelixSR supplies an upscaling backend and does not replace frame generation.

Use one installer to own the same game's proxy files. Do not run both managers' patch/update/remove actions over each other's files. To switch managers, close the game, use the original manager's unpatch/removal instructions and review its Steam launch options, then refresh HelixSR's scan and preview. HelixSR refuses unknown injector conflicts instead of adopting another manager's files. Preserving an existing wrapper as text does not establish that the two setups can run together: a wrapper may copy files or change the backend at launch. No particular Decky-Framegen/HelixSR combination is guaranteed by these checks.

If the image still looks like another upscaler, first confirm the game's DX12 renderer, the displayed installation route, the selected FSR HelixSR backend and a fresh `helixsr.log`. Record the plugin version and exact input selection. Visual preference alone does not establish which backend ran, and neither an installed file nor an old log proves the current output.

Disable/Enable retains your owned configurations. Remove restores originals and keeps configuration copies in `<Game> Mod Files/HelixSR-Decky/records/config-*.json` as installation records. DLL/network changes still block unsafe operations. Removing game files does not undo launch options; use Decky's separate **Restore plugin launch-option change** or merge desktop launch guidance manually.

[Report a reproducible issue](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml). Include the manager version, game, renderer, exact review reason and relevant fresh logs. Remove personal details; never upload generated weights or kernels.

Official references: [HelixSR troubleshooting](https://github.com/lonewolf0622/HelixSR#troubleshooting), [OptiScaler manual installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation), [Control Ultimate Edition notes](https://github.com/optiscaler/OptiScaler/wiki/Control-Ultimate-Edition). Upstream Control testing on Windows does not establish behavior on every SteamOS device.

For an existing OptiScaler install, remove it using the installer that owns it before installing through HelixSR. The manager detects OptiScaler under its supported alternate proxy names as well as `dxgi.dll`, and stops rather than adding a second proxy. It leaves those external files untouched.
