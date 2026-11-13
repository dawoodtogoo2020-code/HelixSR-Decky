# Game status and optional overlay

The Decky plugin and desktop app show the exact reason and next step beside the installation controls. An installation candidate has detected prerequisites; it is not a promise of tested game compatibility.

## Why changes are blocked

| Message | What to do |
| --- | --- |
| Game running | The game can keep running. Install, update, disable and remove stay paused to protect its files. Close the game normally, then refresh. This message does not mean HelixSR stopped working. |
| Steam update in progress | Let Steam finish downloading or updating, then refresh. Do not delete its download staging folder. |
| Steam build changed | Steam updated the game since HelixSR was installed. Close it and finish Steam updates. In Decky 0.1.40, native installations can offer **Reset HelixSR setup** after the native DLL has been restored. If Reset is unavailable, follow its specific reason. Reset never restores old-build files. See the recovery steps below. |
| HelixSR files are missing | In Decky 0.1.36, choose **Repair HelixSR files** when offered, review the listed files and confirm. The plugin restores only absent files that it can reproduce exactly from the recorded package or verified originals. Existing changed files, a changed Steam build, a running game or an incomplete update still block repair. If repair is unavailable, follow the specific reason in the file-status card. Steam verification checks Steam's game files; it does not reinstall files added by HelixSR or reconcile HelixSR's installation record. |
| Managed files changed | A file no longer matches the old setup. Use **Reset HelixSR setup** when offered for a native installation. If another tool changed a file added by HelixSR, restore it through that tool first. Reset preserves current game files and does not grant ownership of another mod's files. |
| Existing injector or configuration | Review the named files with the tool that installed them before adding another injector. |
| Recovery needed | Close the game and finish Steam updates, then review the existing recovery action. Recovery stops if it cannot verify the current files. |
| Choose executable / DX12 needs confirmation | Choose the x64 Windows DX12 executable you actually launch. Confirm DX12 only after selecting it in the game. |
| Anti-cheat restriction / Supported route unavailable | Injection stays blocked. Administrator access cannot make this route compatible. |

Several reasons can apply at once. Resolving one does not bypass the others. Unavailable games retain their reasons and next steps; recorded installations retain their enabled/disabled state separately from permission to modify them.

### Resetting a native installation after a game update

1. Close the game and let Steam finish its update. Verify game files in Steam, then use **Refresh library and status**.
2. Choose **Reset HelixSR setup** when offered. Review the files to remove and the files to keep. This removes only unchanged files that HelixSR added, preserves preexisting game files byte-for-byte, and archives the old receipt and saved originals in the game's companion folder under `HelixSR-Decky/records/reset-*`.
3. Verify game files in Steam again if needed, restore any other mods through their own manager, refresh, and explicitly install the chosen HelixSR model. The install confirmation explains that it replaces the current native DLL and saves its current bytes for later removal. Compatibility checks cannot prove that this DLL is stock.

### Resetting a Scaler installation after a game update

From 0.1.47, a Scaler-route install that shows **Steam build changed** offers **Reset HelixSR setup** too.

1. Close the game, let Steam finish its update, then use **Refresh library and status**. No file verification is needed: Scaler only added files.
2. Choose **Reset HelixSR setup** and review the file list. It removes only HelixSR's files (the Scaler proxy, its folders and its settings) and leaves the game's own files unchanged. A Scaler settings file you changed after installation, such as `OptiScaler.ini` saved from Scaler's overlay, is copied into the reset archive under `configs/` first. The old receipt is archived in the game's companion folder.
3. Refresh, confirm DX12 again if the panel asks (a game update changes the executable), and install HelixSR again.

A Scaler file changed by another tool stops the reset and nothing is deleted. Without a game update, a Scaler install keeps using **Repair HelixSR files** or **Remove and restore originals**.

Reset is separate from **Repair HelixSR files**, which reproduces missing files for the same recorded build. Reset does not run a download, install HelixSR, change launch options, or prove the game is ready to play. Missing or identified HelixSR native DLLs, unknown changes to added files, active games, Steam updates, incomplete records and interrupted transactions still require the displayed next step. Enabled menu-label patches must be restored before reset. Scaler installations keep their existing recovery rules.

Decky 0.1.40 shows a short next step on each warning card. Open **Setup details** for the exact diagnostic, Steam build IDs, file states and additional instructions.

**Review** has two separate meanings. The install confirmation lets you inspect proposed changes before applying them. A **reviewed release** is a package whose archive identity, layout and preparation steps are supported by the plugin, not a promise of tested gameplay in every title. Neither is a queue waiting for a maintainer to approve your game.

The game list is reused when Decky reopens the panel or a dropdown. Selecting a game still checks that game's current status. Use **Refresh library and status** after installing, moving or removing games outside the plugin. Imports and completed plugin operations refresh the list automatically; install and repair actions always recheck their safety conditions before writing.

“Network output missing or incomplete” refers to locally generated model files, not your internet connection. Update both the app/plugin and HelixSR before retrying preparation; if it persists, report the final build-log lines with private paths removed. A new upstream format may need another reviewed adapter update.

## Check whether HelixSR is running

1. Select the installed game. Enable **Show HelixSR status overlay (experimental)** in Decky, or the status-overlay toggle in Desktop. This starts a read-only monitor and checks its separate HUD helper. It does not install files, change launch options, or enable frame generation.
2. Enable it before launching the game so it can observe initialization. Select AMD FSR for the native replacement, or the configured input for the OptiScaler route.
3. Read the runtime status:
   * **No running game observed**: no matching game process was observed. Process access restrictions can limit detection.
   * **Game running; HelixSR unverified**: the game is observed, but the selected executable and managed HelixSR module have not both been verified.
   * **HelixSR module mapped; output unverified**: the module is loaded. Its presence alone does not prove neural rendering.
   * **HelixSR network loaded; output unverified**: a new network-ready event was read; a later neural dispatch has not yet been verified.
   * **Neural output reported this session**: a new network-ready event followed by a dispatch was read for the identified game session. This is log evidence, not proof of continuous rendering, image quality, stability, FPS or active frame generation.
   * **Session log reports a fallback/error**: review the log and setup. A generic dispatch cannot clear this warning; successful network reinitialization is required.
   * With **HLX FSR 4 Full** selected (HelixSR 3.3.0, Scaler), the monitor's HLX evidence lines have not been reviewed for Full yet, so the status can stay unverified even when Full runs. Use Full's lines in `OptiScaler.log` or a GPU capture.
   * HLX FSR 4 (3.2.0 and 3.3.0) has no per-frame log message. **HLX FSR 4 runtime active; frame processing unverified** means HLX created its own-runtime context this session. **AMD FSR (native) provider selected; frame processing unverified** means AMD's provider took the context while AMD FSR (native) is the configured Scaler output. **Session log reports AMD fallback or an HLX error** means AMD's original took over from HLX, or neither provider produced the context or frame. Use a GPU capture to confirm rendered frames. The monitor reads HLX's own log ([locations](docs/hlx-fsr.md)). If you set `LogToFile=true` in a Scaler game's `OptiScaler.ini`, also set `LogLevel=2`: the default Trace level grows too fast and shows **Runtime evidence unavailable**.
4. If you enabled monitoring after initialization, existing log text is treated as historical. Close the game normally, keep monitoring enabled, and relaunch to capture fresh evidence. Decky **0.1.14** and Desktop **0.1.10** fix Proton launch helpers being mistaken for the game and capture an authenticated startup log rewrite when monitoring was armed while the game was closed. If the game does not expose attributable new events, the monitor stays unverified. Do not treat that alone as proof HelixSR is off. A separate manual installation outside the manager's recorded DLL path is also left unverified; do not delete or move its files to bypass that check.
5. Turn the toggle off to close the HUD. Changing games, changing executable, reloading the plugin or closing Desktop stops that frontend's monitor. Only one HelixSR HUD controls the display at a time.

## Show the active upscaler in game

For games installed with the Scaler route (HelixSR 2.0 Model E or HLX FSR 4), turn on **Show upscaler overlay in game** under **Upscaling and frame generation**, or the matching option in Desktop's settings dialog. Close the game first; the setting applies at the next launch. It sets `ShowFps=true` and `FpsOverlayType=1` in that game's `OptiScaler.ini` `[Menu]` section, and turning it off restores `ShowFps=false` with the default overlay type. No other settings change.

Scaler's FPS overlay then shows the frame rate followed by the input and the upscaler path it drives, for example `DLSS -> FSR 3.1.5`. HelixSR Model E runs behind the FSR 3.1 interface, so the overlay may name FSR rather than HelixSR; HLX FSR 4 runs behind the FSR 4 interface. The overlay reports the configured path. It does not prove that HelixSR's network produced the frame. Use the status overlay above, or the game's HelixSR log, for that evidence. Page Up hides or shows the overlay in game and Page Down changes its detail level; on a Steam Deck, bind those keys in Steam Input if you need them. The native FSR replacement route has no Scaler, so the switch is shown greyed out there with that explanation. Some games name the active provider in their own graphics menu instead; Resident Evil Requiem shows **AMD FSR HLX FSR 4 (4.1.2)** with HLX installed natively. HelixSR itself has no watermark setting.

## Overlay health and limits

**Overlay helper responding** means the helper consumed current status, mapped its window and acknowledged drawing. **Visibility unverified** is deliberate: those checks cannot prove that Steam's compositor is presenting the pixels to you. Look for the small status card at the upper-left of the display. **Recorded** version/model identifies the installation record; it is separate from runtime evidence.

The continuous HUD currently uses Linux X11, or a verified Gamescope root display. Decky 0.1.14 and Desktop 0.1.10 were tested on a Steam Deck OLED: the Desktop X11 card appeared during PRAGMATA and passed the click-through and focus checks. Gaming Mode confirmed fresh neural-output events inside Decky, but its existing MangoApp overlay occupied the HUD surface. **Another overlay is using its surface** means the continuous card cannot appear alongside that overlay; HelixSR leaves it alone and still reports runtime status inside Decky. These checks do not establish visible HUD support in every compositor or gameplay stability in every game. Desktop Wayland and inaccessible displays report the continuous HUD as unavailable. No root access, global MangoHud configuration changes or extra game launch options are required.

## GitHub update checks

If GitHub's API reaches its primary request limit, Decky 0.1.14 and Desktop 0.1.10 can verify the latest HelixSR through its official release page instead. Both the official SHA256 digest and exact current download size are required; the downloaded archive must still pass verification. Repeated clicks respect a short cooldown and the API reset time. Other access failures or secondary request limits remain visible and must be retried later. Reconnecting does not necessarily clear a GitHub limit. This fallback applies to HelixSR releases; plugin and desktop app updates use their separate release feeds.

Gamescope's external-overlay surface can conflict with a performance HUD. If a foreign external overlay is present, this HUD stays hidden and shows **another overlay is using its surface**. It also yields if a conflicting overlay appears later. It never disables or changes the other overlay. You can choose your existing performance HUD or this experimental HUD; neither is silently replaced. The provider behavior is based on [Gamescope's source](https://github.com/ValveSoftware/gamescope/blob/master/src/steamcompmgr.cpp).

If the helper crashes, cannot establish input transparency, loses its status feed, or fails its startup deadline, the UI reports unavailable/stale status. Toggle off and on to retry. The HUD does not grab keyboard, controller, mouse or touch input.

Decky also submits brief status-change notifications while monitoring is enabled, including when the continuous HUD is unavailable. Open the plugin to see the current reason and runtime evidence. Notification delivery is controlled by Steam/Decky and is not used as proof of HUD visibility.

[Report a problem](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml): include the plugin/app version, game, Proton version, installation route, exact status and short sanitized log excerpt. Do not upload generated networks or personal files.
