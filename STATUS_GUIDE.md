# Game status and optional overlay

The Decky plugin and desktop app show the exact reason and next step beside the installation controls. An installation candidate has detected prerequisites; it is not a promise of tested game compatibility.

## Why changes are blocked

| Message | What to do |
| --- | --- |
| Game running | The game can keep running. Install, update, disable and remove stay paused to protect its files. Close the game normally, then refresh. This message does not mean HelixSR stopped working. |
| Steam update in progress | Let Steam finish downloading or updating, then refresh. Do not delete its download staging folder. |
| Steam build changed | Steam reports a different build from the one recorded when HelixSR was installed. **Remove** restores saved originals, which may now belong to an older build, so file changes remain blocked. Close the game, finish Steam's update and refresh. The game details show recorded/current build IDs and relative file states in Decky 0.1.15 and Desktop 0.1.11. Include this check in your bug report. Steam verification may restore current game files but does not reconcile the HelixSR receipt; matching an old saved original does not prove that it belongs to the current build. Do not edit the build ID or erase records to unlock controls. |
| Managed files changed | The named file differs from the bytes recorded when HelixSR installed it. This is not a Linux file-owner or administrator check. If another mod changed it, restore it through that mod's own manager and refresh. Otherwise report the affected filename for review. Do not delete DLLs or the installation record to bypass the guard. |
| Existing injector or configuration | Review the named files with the tool that installed them before adding another injector. |
| Recovery needed | Close the game and finish Steam updates, then review the existing recovery action. Recovery stops if it cannot verify the current files. |
| Choose executable / DX12 needs confirmation | Choose the x64 Windows DX12 executable you actually launch. Confirm DX12 only after selecting it in the game. |
| Anti-cheat restriction / Supported route unavailable | Injection stays blocked. Administrator access cannot make this route compatible. |

Several reasons can apply at once. Resolving one does not bypass the others. Unavailable games retain their reasons and next steps; recorded installations retain their enabled/disabled state separately from permission to modify them.

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
4. If you enabled monitoring after initialization, existing log text is treated as historical. Close the game normally, keep monitoring enabled, and relaunch to capture fresh evidence. Decky **0.1.14** and Desktop **0.1.10** fix Proton launch helpers being mistaken for the game and capture an authenticated startup log rewrite when monitoring was armed while the game was closed. If the game does not expose attributable new events, the monitor stays unverified. Do not treat that alone as proof HelixSR is off. A separate manual installation outside the manager's recorded DLL path is also left unverified; do not delete or move its files to bypass that check.
5. Turn the toggle off to close the HUD. Changing games, changing executable, reloading the plugin or closing Desktop stops that frontend's monitor. Only one HelixSR HUD controls the display at a time.

## Overlay health and limits

**Overlay helper responding** means the helper consumed current status, mapped its window and acknowledged drawing. **Visibility unverified** is deliberate: those checks cannot prove that Steam's compositor is presenting the pixels to you. Look for the small status card at the upper-left of the display. **Recorded** version/model identifies the installation record; it is separate from runtime evidence.

The continuous HUD currently uses Linux X11, or a verified Gamescope root display. Decky 0.1.14 and Desktop 0.1.10 were tested on a Steam Deck OLED: the Desktop X11 card appeared during PRAGMATA and passed the click-through and focus checks. Gaming Mode confirmed fresh neural-output events inside Decky, but its existing MangoApp overlay occupied the HUD surface. **Another overlay is using its surface** means the continuous card cannot appear alongside that overlay; HelixSR leaves it alone and still reports runtime status inside Decky. These checks do not establish visible HUD support in every compositor or gameplay stability in every game. Desktop Wayland and inaccessible displays report the continuous HUD as unavailable. No root access, global MangoHud configuration changes or extra game launch options are required.

## GitHub update checks

If GitHub's API reaches its primary request limit, Decky 0.1.14 and Desktop 0.1.10 can verify the latest HelixSR through its official release page instead. Both the official SHA256 digest and exact current download size are required; the downloaded archive must still pass verification. Repeated clicks respect a short cooldown and the API reset time. Other access failures or secondary request limits remain visible and must be retried later. Reconnecting does not necessarily clear a GitHub limit. This fallback applies to HelixSR releases; plugin and desktop app updates use their separate release feeds.

Gamescope's external-overlay surface can conflict with a performance HUD. If a foreign external overlay is present, this HUD stays hidden and shows **another overlay is using its surface**. It also yields if a conflicting overlay appears later. It never disables or changes the other overlay. You can choose your existing performance HUD or this experimental HUD; neither is silently replaced. The provider behavior is based on [Gamescope's source](https://github.com/ValveSoftware/gamescope/blob/master/src/steamcompmgr.cpp).

If the helper crashes, cannot establish input transparency, loses its status feed, or fails its startup deadline, the UI reports unavailable/stale status. Toggle off and on to retry. The HUD does not grab keyboard, controller, mouse or touch input.

Decky also submits brief status-change notifications while monitoring is enabled, including when the continuous HUD is unavailable. Open the plugin to see the current reason and runtime evidence. Notification delivery is controlled by Steam/Decky and is not used as proof of HUD visibility.

[Report a problem](https://github.com/dawoodtogoo2020-code/HelixSR-Decky/issues/new?template=bug_report.yml): include the plugin/app version, game, Proton version, installation route, exact status and short sanitized log excerpt. Do not upload generated networks or personal files.
