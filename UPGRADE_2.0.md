# HelixSR 2.0 controls

HelixSR 2.0.0 is selected by default in Decky. Review Install/Update to see what will change for the selected game. Preparation uses the unchanged official 2.0 setup and verifies the embedded Model E network plus both frame-generation models. NVIDIA-derived files stay on the device and are never included in this plugin's download.

## Release choices and review

**HelixSR 2.0.0 (recommended)** is the current supported package. **1.9.3** and **1.8.1** remain available as older releases for existing setups and specific compatibility needs. You do not need to install all three. Selecting an older release does not bypass the downgrade checks on an existing installation.

**Latest upstream (check for newer)** follows the official upstream release feed. A newly published package may need a plugin update before it can be installed. Keeping 2.0.0 selected avoids making an ordinary installation depend on that discovery request.

Package review means the plugin has an adapter for the official archive, its file layout, local preparation and installation steps, with a pinned size and SHA256. It is not a human approval queue and does not certify every game's rendering or performance. The installation confirmation is your opportunity to inspect the proposed changes. A game's **Needs review** warning is a separate file-state or setup issue; its details explain the next action.

For Scaler installations, open **Game settings**, then **Upscaling and frame generation** in Decky, or **Upscaling and frame generation settings** in Desktop. Close the game before saving and restart it afterwards.

| Control | Supported choices |
| --- | --- |
| Upscaler | HelixSR Model E or AMD FSR; selects the first AMD backend supported by the GPU; additional choices remain in Scaler's own menu |
| Frame generation provider | Off, HelixSR DLSS FG, AMD FSR FG, Intel XeSS FG |
| HelixSR FG model | Light or Full |
| QuickFlow | Off, Fast or Fastest with Full only |
| Frame multiplier | 2×; 3× with XeSS FG only |
| GPU settings | Automatic/on/off INT8; automatic/32/64 wave size |

HelixSR's DLSS FG route requires a DirectX 12 game with DLSS frame generation enabled in-game. Light and Full refer to frame generation, not alternative upscaling networks. Model E remains the reviewed SR model. Provider availability and performance depend on the game, GPU and Proton. Configured settings are distinct from verified runtime activity.

Native FSR replacement installs the embedded upscaler only. To change to Scaler, remove the managed installation to restore originals, choose **Use Scaler for frame generation and settings**, then install. Do not mix native replacement and proxy installation files manually. Existing launch options are preserved through the plugin's reviewed launch-option flow.

Settings use the existing journal, ownership checks, atomic writes and restoration records. Stale edits, active games, Steam downloads, changed game builds, missing payloads and unmanaged collisions stop changes. Updates preserve supported settings. Bootstrap and dependency files remain included in frozen Decky and Desktop packages.

Scanning detects future official releases automatically. It does not establish that a changed converter, network or file layout is compatible. Unreviewed releases report that an application update is needed and leave the installed game unchanged. A substituted archive at the same version is rejected by its pinned identity.

This update adds regression coverage for installation migrations and settings. It does not guarantee every game is bug-free. Report the game, route, installed versions and current logs if gameplay fails.

## Steam Deck validation limits

The plugin currently validates DX12 installation routes. Upstream 2.0 Scaler also supports DX11 and Vulkan upscaling, but those hooks have not been validated by this integration. The DX12 confirmation records your confirmation of the game mode; it does not select a renderer in the game.

PRAGMATA has not passed performance acceptance with frame generation on this Deck. HelixSR Light 2x initialized and evaluated but produced intense flickering, not a permanently black image. FSR upscaler-input FG 2x reached moving Shelter gameplay without full-scene black frames in a short capture, but substantially worsened captured frame pacing compared with FG Off. Full mode removed the alternating black frames in a 15-second moving Shelter capture (486 frames), but its captured rate remained below FG Off. Changing Light mode to Present-based frame timing did not resolve flickering: 364 of 721 captured frames were nearly black. Keep FG Off for this tested setup. A subsequent XeSS 2x trial with native FG Off and no GPU spoof failed at startup with DXGI_ERROR_INVALID_CALL (0x887a0001), before gameplay. Separate HelixSR neural SR and FSR 3.1.5 comparisons with FG Off each captured about 19 seconds of Shelter character movement, with zero nearly-black frames and similar capture cadence (38.97 and 39.79 packets/second). These short captures do not establish a visual-quality winner, hardware display FPS, endurance or physical responsiveness. These controls are not a compatibility fix for the upstream renderer, and successful logs or a higher FPS counter are not proof of usable generated frames.

## Interactive settings menu and L4

The In-game menu card shows Scaler's configured keyboard shortcut and opens the selected game's controller settings. Enable Back Grip Buttons and map L4 to that key. The default is Insert. Pressing it shows or hides the interactive settings menu, separate from the performance HUD. Decky does not inspect or automatically change Steam Input bindings and cannot verify physical button presses.

If REFramework also uses Insert, change its Configuration → Menu Key to Home. This keeps Scaler and an existing L4 = Insert binding unchanged. In the tested Pragmata setup, physical L4 was confirmed by the user; separate Insert/Home menu behavior and persistence were checked after restarting the game. Other controller layouts still need their own check.
