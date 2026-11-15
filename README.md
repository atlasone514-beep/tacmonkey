# tacmonkey

Automation for The Alchemist Code (TagaReconstruction private server): story/event farming by
button images, a Genesis unit-shard farm, and an in-game mod that presses buttons without using
your mouse.

## Layout

| Folder | What's in it |
|---|---|
| `app/` | The farm (`farm.py`), its window (`farm_ui.pyw`) and the Genesis unit farm (`genesis_farm.py`) |
| `mod/TACAutoTap/` | BepInEx 6 IL2CPP plugin: presses UI buttons from inside the game over 127.0.0.1:47613 |
| `tools/` | `modtest.py` (talk to the mod by hand), Genesis loot reader/report, and the BepInEx loader patcher |
| `data/genesis/` | Unit shard drops of all 95 Genesis Hard stages (table, list, full loot CSV, raw results) |
| `docs/NOTES.md` | How the mod setup works and what was checked |

## Run the farm

1. Install Python 3.11+ and run `pip install -r app/requirements.txt`.
2. Double-click `app/farm_ui.pyw`.
3. A fresh copy has no button images. On first start it offers to import them from another copy
   (any folder with a `buttons` and/or `scripts` folder). You can also do it later with
   **Customize > Import buttons**, or capture your own there.

Without the mod, the farm uses touch taps (the game window must stay uncovered).

## Build the mod

Needs the .NET 8 SDK and the game folder with BepInEx 6 (IL2CPP) installed and started once.

```
set TAC_GAME=<game folder with TagaReconstruction.exe>
dotnet build mod/TACAutoTap -c Release
```

Copy `mod/TACAutoTap/bin/TACAutoTap.dll` to `<game>\BepInEx\plugins\` with the game closed.
This game needs a patched `Il2CppInterop.Generator.dll` for BepInEx to load. See
`docs/NOTES.md` and `tools/patcher`.
