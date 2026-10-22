# HelixSR 2.0 controls

Select the reviewed HelixSR 2.0.0 release, or scan with Latest upstream, then review Install/Update. Open Plugin updates for the selected release notes. Preparation uses the unchanged official 2.0 setup and verifies the embedded Model E network plus both frame-generation models. NVIDIA-derived files stay on the device and are never included in this plugin's download.

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

PRAGMATA has not passed HelixSR upscaling or generated-frame gameplay validation on this Deck. Prior tests produced black/frozen rendering with HelixSR SR. AMD FSR plus HelixSR FG reached an animated title screen, which does not prove active frame generation. Use the game settings controls only with this distinction in mind.
