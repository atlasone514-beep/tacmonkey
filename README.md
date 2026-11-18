# tacmonkey

Automation for The Alchemist Code (TagaReconstruction private server): story/event farming by
button images, Genesis unit-shard and Ex (Extra stage) farms, and an in-game mod that presses buttons without using
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
| `app/` | The farm (`farm.py`), its window (`farm_ui.pyw`) and the Genesis / Ex Genesis farm (`genesis_farm.py`) |
| `mod/TACAutoTap/` | BepInEx 6 IL2CPP plugin: presses UI buttons from inside the game over 127.0.0.1:47613 |
| `tools/` | `modtest.py` (talk to the mod by hand), Genesis loot reader (`--extra` for Extra stages) and reports, and the BepInEx loader patcher |
| `data/genesis/` | Unit shard drops of all 95 Genesis Hard stages (table, list, full loot CSV, raw results), and what the Extra stages drop |
| `installer/`, `release/` | The setup program and the script that builds a release |
| `docs/NOTES.md` | How the mod setup works and what was checked |

## Run the farm

1. Install Python 3.11+ and run `pip install -r app/requirements.txt`.
2. Double-click `app/farm_ui.pyw`.
3. A fresh copy has no button images. On first start it offers to import them from another copy
   (any folder with a `buttons` and/or `scripts` folder). You can also do it later with
   **Customize > Import buttons**, or capture your own there.

Without the mod, the farm uses touch taps (the game window must stay uncovered).

**Item goal:** under *Stop when*, "Item: I have [N] of [picture]" stops the script once you own
N of an item. Capture the item's icon on a results screen (just the picture, not the `x12`),
or load it from a file. On each results screen the farm finds the icon and, through the mod,
reads how many dropped and the item's "(Owned: N)", then stops there before tapping on. The
farm matches the top of the picture, since the drop count is drawn over the icon's bottom.
Where a screen also names its drops (the Genesis rewards), the item is picked by name, so
look-alike icons (the gear Diagram scrolls) aren't mixed up; a normal quest's results don't
name them, so pick an icon that doesn't look like another drop. Without the mod it counts the
runs the item dropped in instead. It only sees the drops showing on screen. The goal is saved with the script and travels in a
shared `.tacscript`.

**Check screen** shows each image's score. "Shape matches, but colours are off" means the
picture is found but its colours differ, so it isn't tapped (another screen state, or a dimmed
screen). Images grabbed at another window size are fine: the farm resizes them and compares
colours after a light blur.

**Game in the background:** a script needs the game's picture. Covered by other windows is
fine (with the mod, taps work there too); **minimized is not**, since Windows doesn't draw a
minimized window. While there's no picture the log says why: minimized, not found, or a black
picture (some PCs stop drawing a covered window: keep part of it visible, or turn off
"Optimizations for windowed games" in Windows Settings > Display > Graphics). If the picture
stops changing for 20 s the log says so too, and **Check screen** reports whether the picture is
live. The Genesis farm doesn't use the picture, only the mod.

**Errors:** an unexpected error is logged in the window and its full details are added to
`errors.log` in the TACMonkey folder. If the AP refill misses a button, the farm tries the
refill again (it stops after 3 failures in a row).

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
variant grouping are saved in the script, not in file names. A new button goes to the bottom of
the priority list; without a list of its own, a script's steps follow the usual run order
(quest, skip, hire, go, auto, end quest, act). Names starting with `x_` are markers, which are
only looked at and never tapped (`x_quest_done` and `x_back` drive act switching).

**Step options:** a step's card in Customize has three ticks: *Tap the highest one* (the newest
quest or act is at the top), *Tap an empty spot first* (screens that close on a tap anywhere)
and *It's the new-quest button* (tells when an act is finished). Which image counts a run is
ticked on the image itself.

**Old numbered names** (`06_go`, `09_endquest`) still work: `01` gets topmost + new quest, `08`
the empty spot, `10` topmost, and `09` is the default run counter. TACMonkey offers once to
**tidy** them into plain names (`go`, `end quest`); the Buttons page has the same button. Every
script keeps running as before, and a backup zip of `buttons/` and `scripts/` is saved first.

**Known popups:** when the mod is running, the farm and the Genesis farm answer these by
themselves: the Peddler Shop (**View Later**) and the Vision Clear Reward (**OK**). The list is
`KNOWN_POPUPS` in `farm.py`: each popup is found by its object's name in the mod's list and
answered with one safe button. Buttons that spend gems or open a shop are never added.

**Every script:** for other popups that can show up in any script (or the Peddler Shop without
the mod), capture the button once, click its card and tick **Press in every script**. Every
script then checks it before its own steps. It isn't part of any script's steps or priority.

**Sharing:** **Export script** writes one `.tacscript` file with the images the script uses,
plus its steps, priority, run counter, tap spots, learned arrows and item goal. Your friend opens it with
**Import** (main window) or **Import script** (Customize). It becomes a new script with its own
copy of the images, so nothing they already have is overwritten. Then they press **Check
screen** to see whether the images match on their window.

## Genesis farm

Needs the mod. Start from the home screen or anywhere in Genesis.

- **Units (Hard):** tick the units whose shards you want. The number that appears beside a
  ticked unit is how many of its stages to farm, newest chapter first. Each stage is skipped
  with 3 skip tickets.
- **Ex chapters (Extra):** the third setting of the map's Normal/Hard switch, from Eulalia's
  chapter (ch7) on. Tick chapters; the number is how many of their 5 Extra stages to farm. Each
  has 1 attempt a day (1 skip ticket). Extra stages you haven't cleared by hand are locked and
  skipped.
- **Solo stages only:** leaves out a unit's stages that it shares with another unit, unless
  every unit on that stage is ticked. Units with only shared stages (marked `*`) keep them.
- **Pause** waits for the stage it's on to finish. You can play meanwhile: on **Resume** (or
  F8) the farm finds its way back to the chapter. F9 stops it.
- On Stop, the log shows the shards got so far; while it runs, the status line keeps a total.
  The Ex farm's summary lists only the six elemental Soul Shards, and the Ex page counts them
  up during the run (each stage's own line still lists its Diagram Pieces).

**Leaves (AP refill):** when AP runs out, the Genesis and Ex farms and the AP refill action
refill it with Alchemy Drops. The **Leaves** row in the main window sets how many per refill
(7 by default), the most to use per session, and a number of owned drops to stop below. Leave
the last two blank for no limit. When a limit is reached, the farm stops instead of refilling.

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
