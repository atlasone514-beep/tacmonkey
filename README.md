# tacmonkey

Automation for The Alchemist Code (TagaReconstruction private server): story/event farming by
button images, a Genesis unit-shard farm, and an in-game mod that presses buttons without using
your mouse.

## Install (no Python needed)

1. Download `TACMonkey-Setup-<version>.exe` from the
   [Releases](https://github.com/atlasone514-beep/tacmonkey/releases) page.
2. Close the game and run the setup. It finds the game folder by itself (or pick it), and can
   download BepInEx for you from the official build server.
3. Start the game once: the first start with BepInEx takes a minute or two.
4. Open **TACMonkey** from the Start menu. On first start it offers to import buttons you
   already have.

Windows may warn that the setup is from an unknown publisher (it isn't code-signed): click
**More info > Run anyway**. To remove it, run the setup again and use its **Uninstall...** button.

### Updates

On start, TACMonkey asks GitHub whether a newer release exists (turn this off with **Check for
updates when TACMonkey starts**, or press **Check now**). If there is one, a bar offers
**Update**. The new setup is downloaded and checked against the release's `SHA256SUMS.txt`.
TACMonkey then closes, the setup updates the app and the mod (BepInEx is left as it is), and
the app opens again. Buttons, scripts and settings stay. Close the game first so the mod can be
updated too. Running the new setup by hand works the same way.

If the game has a different mod version than the app expects, the log says so.

## Layout

| Folder | What's in it |
|---|---|
| `app/` | The farm (`farm.py`), its window (`farm_ui.pyw`) and the Genesis unit farm (`genesis_farm.py`) |
| `mod/TACAutoTap/` | BepInEx 6 IL2CPP plugin: presses UI buttons from inside the game over 127.0.0.1:47613 |
| `tools/` | `modtest.py` (talk to the mod by hand), Genesis loot reader/report, and the BepInEx loader patcher |
| `data/genesis/` | Unit shard drops of all 95 Genesis Hard stages (table, list, full loot CSV, raw results) |
| `installer/`, `release/` | The setup program and the script that builds a release |
| `docs/NOTES.md` | How the mod setup works and what was checked |

## Run the farm

1. Install Python 3.11+ and run `pip install -r app/requirements.txt`.
2. Double-click `app/farm_ui.pyw`.
3. A fresh copy has no button images. On first start it offers to import them from another copy
   (any folder with a `buttons` and/or `scripts` folder). You can also do it later with
   **Customize > Import buttons**, or capture your own there.

Without the mod, the farm uses touch taps (the game window must stay uncovered).

## Scripts

**Customize** opens a script in one of two views (switch with the tabs):

- **Flowchart:** one card per step, in the order your runs actually go through them.
  - A step is one button; its images are variants (different looks of it).
  - The farm records which button followed which, so the arrows show counts like `27x (90%)`.
  - Before the first run, the cards follow the priority list.
  - During a run, the step it just pressed is outlined in yellow.
- **Priority list:** the order the farm checks steps on every scan. When two are on screen at
  once, the higher one is tapped. Move steps with the arrows.

To change a step, click its card. From there you can:
- re-capture or replace an image, or remove or delete it;
- mark it as the run counter;
- **Add a variant**, or move an image into another step with **Step**.

Below the flow is every other captured button: click one to add it.

**Button names are free.** `go.png`, `try again.png` and so on all work. The priority and the
variant grouping are saved in the script, not in file names. Old names like `06_go` still work:
their number is used as the default step and order until you change it. A new button goes to
the bottom of the priority list. Names starting with `x_` are markers, which are only looked
at and never tapped.

Some old story-farm behaviour still depends on fixed numbers: `01` topmost quest, `08` tap
anywhere, `09` default run counter, `10` act, and the `x_quest_done` / `x_back` markers.

**Sharing:** **Export script** writes one `.tacscript` file with the images the script uses,
plus its steps, priority, run counter, tap spots and learned arrows. Your friend opens it with
**Import** (main window) or **Import script** (Customize). It becomes a new script with its own
copy of the images, so nothing they already have is overwritten. Then they press **Check
screen** to see whether the images match on their window.

## Build the mod

Needs the .NET 8 SDK and the game folder with BepInEx 6 (IL2CPP) installed and started once.

```
set TAC_GAME=<game folder with TagaReconstruction.exe>
dotnet build mod/TACAutoTap -c Release
```

Copy `mod/TACAutoTap/bin/TACAutoTap.dll` to `<game>\BepInEx\plugins\` with the game closed.
This game needs a patched `Il2CppInterop.Generator.dll` for BepInEx to load. See
`docs/NOTES.md` and `tools/patcher`.

## Build a release

```
set TAC_GAME=<game folder with BepInEx be.793 and the patched loader>
pip install pyinstaller
python release/build.py
```

Output: `build/dist/TACMonkey-Setup-<version>.exe`, `SHA256SUMS.txt` and `NOTICE.txt`.
Bump `VERSION` in `app/farm.py` first. If the mod changed, bump its `Version` in `Plugin.cs` and
set `MOD_VERSION` in `app/farm.py` to match (the build stops if they differ).

Publish with a `v<version>` tag and attach all three files. The app's update check needs the
setup exe and `SHA256SUMS.txt` on the release:

```
gh release create v<version> build/dist/TACMonkey-Setup-<version>.exe build/dist/SHA256SUMS.txt build/dist/NOTICE.txt
```
