# Optional native game menu labels

The **Use HelixSR menu labels** switch is an optional text change for The Witcher 3's Steam version using HelixSR's direct replacement route. It is off by default. Installing, enabling or updating HelixSR does not opt you in.

The checked Witcher 3 resource contains a literal **AMD FSR Upscaling** option. This feature changes that option's displayed name to **Helix SR**. It preserves the option's existing behavior, quality choices and frame-generation labels. It edits the game's menu resource rather than drawing an overlay.

## Turn the label on or off

1. Close the game and let any Steam installation or update finish.
2. In HelixSR Decky, select The Witcher 3 with a managed, enabled direct-route HelixSR installation.
3. Find **Use HelixSR menu labels** in the game's section. Switch it on, review the affected file and confirm **Apply reviewed change**.
4. To restore the original label, close the game, switch the same control off and confirm the reviewed restore.

Turning the switch off restores the exact original resource bytes when the safety checks pass. **Disable HelixSR** and **Remove and restore originals** also restore the original menu resource and clear the optional label state. Re-enabling HelixSR leaves this optional label off until you choose it again.

A disabled switch has a reason below it. Resolve that reason and refresh the game details. The feature requires a readable Linux process view; an unavailable process check cannot establish that the game is closed.

## Files and safety checks

The only menu resource used by this profile is:

```text
bin/config/r4game/user_config_matrix/pc/graphics.xml
```

The plugin verifies the XML layout, the FSR option and its existing mapping before preparing the change. It changes only the validated display-name value and preserves the rest of the file's bytes. Unknown, already altered or ambiguous layouts are refused.

Original bytes and ownership records live beside the game on the same drive:

```text
<Game folder name> Mod Files/HelixSR-Decky/originals/
<Game folder name> Mod Files/HelixSR-Decky/records/install.json
```

Keep these while the modification is managed. They are needed for verified restoration. Completed temporary transaction files are cleaned after a successful operation.

Running games, incomplete Steam installs, build changes, unexpected file edits, unsafe resource paths and damaged ownership or original records can block a change or restore. The plugin does not overwrite an unexpected resource to force restoration. Keep the records, close the game and review the reported issue before trying again. If an operation was interrupted, use **Recover interrupted file transaction** when offered.

Removing the Decky plugin itself does not restore game files. Use the per-game restore or removal action first.

## What has been verified

The installed Witcher 3 XML resource was inspected and its FSR option matched the narrow profile. Source and transaction checks can verify the changed file and exact restoration. The physical in-game menu has not been verified for this feature.

The label is cosmetic. Seeing **Helix SR**, having the switch enabled or passing a file-hash check does not prove that HelixSR is running, producing neural output or improving image quality. Runtime evidence and visible menu verification are separate checks. This feature does not enable an upscaler or frame generation.

## Other requested games

These games have no available native menu-label profile in this implementation:

| Game | Current limitation |
| --- | --- |
| Control / Control Ultimate Edition | The original game was not installed in the inspected local inventory, so its menu resource was not verified. |
| CONTROL Resonant | Uses packed RMD localization; no verified resource adapter is available. |
| PRAGMATA | The inspected KPKA 4.2 archive uses encryption/chunking. The exact menu resource and loading route still need verification. |
| Crimson Desert | The inspected local folder was incomplete and had no verified Steam manifest. |
| Ace Combat 8 | Easy Anti-Cheat files were present; modification remains blocked. |

These observations do not establish compatibility for another build or installation. Other Steam games also remain unavailable unless a specific resource profile is implemented and its safety checks pass. No additional loader or archive modification is installed to make an unsupported label work.
