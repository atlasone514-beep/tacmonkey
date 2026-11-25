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
| `app/` | The farm (`farm.py`), its window (`farm_ui.pyw`, with `farm_ui_box.py`), the Genesis / Ex Genesis farm (`genesis_farm.py`), the box event farm (`box_farm.py`), the event scanner (`event_scan.py`), live data (`live_data.py`, `texts.py`) and unit portraits (`portraits/`) |
| `data/live/` | What the Dev page publishes: box events, pushed scripts and changed wording (every TACMonkey downloads it) |
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

**The game's own picture (mod 1.3):** with TAC Auto Tap 1.3, when Windows' picture comes back
black, or stops changing while the game shows something else, the farm reads the frame from inside
the game instead (the mod's `shot` command) and says so in the log; after a minute it tries
Windows' picture again. On PCs where Windows' picture works, nothing changes.

**Notifications:** when a script, the box farm, Genesis or Ex ends by itself (finished, a goal
or limit reached, an error), Windows shows a notification with the reason (and the shards got).
Pressing Stop or F9 doesn't notify. Turn it off in Settings: *Windows notification when a script
or farm finishes*. Focus Assist / Do not disturb hides it like any other notification.

**Finish and go home:** with a run limit set, tick *Then finish the last quest and go to the
home screen* (needs the mod). When the counter is on Go (or Try Again), the last quest is played to
the end and Go isn't pressed again; then the farm walks back to the home screen with the menu map.
A counter on a later step stops there and goes home.

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
themselves: the Peddler Shop (**View Later**), the Vision Clear Reward (**OK**) and the
monthly Login Bonus (**Close**; its free **Receive** is left for you). The list is
`KNOWN_POPUPS` in `farm.py`: each popup is found by its object's name in the mod's list and
answered with one safe button. Buttons that spend gems or open a shop are never added.

**Every script:** for other popups that can show up in any script (or the Peddler Shop without
the mod), capture the button once, click its card and tick **Press in every script**. Every
script then checks it before its own steps. It isn't part of any script's steps or priority.

**When seen, press:** an image's details panel has a **Press** list. *This image* is the usual
behaviour. Pick *another button* and, when this image is seen, the farm finds that button on
screen and taps it instead. If it isn't up yet, it waits (and says so after 5 s) without tapping
the first image. Pick *A fixed spot...* to drag a small box on a capture; its centre is tapped
instead. The other button doesn't have to be one of the script's steps. It's saved per script.

**Sharing:** **Export script** writes one `.tacscript` file with the images the script uses,
plus its steps, priority, run counter, tap spots, "When seen, press" choices (and the buttons
they press), learned arrows and item goal. Files exported by older versions still import. Your friend opens it with
**Import** (main window) or **Import script** (Customize). It becomes a new script with its own
copy of the images, so nothing they already have is overwritten. Then they press **Check
screen** to see whether the images match on their window.

## Box events

The **Box events** page has two tabs along the top: **Box events** (box event and Genesis units)
and **Genesis Ex** (the Extra stages, by chapter).

**Box events tab:** every box event that's live, with a tile per unit whose Soul Shards its
quests drop (portrait, name, quests, how many are left today). Tick units (the number beside a
ticked unit is how many of its quests to farm) and press **Start box farm**: it opens Quest >
Event, goes into each event, and skips the quests that drop those units, with the same skip, AP
refill (Leaves), popups, grace period and pause as the Genesis farm. Needs the mod. The search box
filters units by name. Portraits are only pictures; nothing is found by them.

**Main units:** an event can have main units (marked on the Dev page, optional, any number). They
show first with a *Main unit* badge, and the event's other units are folded under "N other units"
(click to open; a search or a ticked unit shows them anyway). Events without main units show
every unit.

The Genesis Hard units have their own section below, **Genesis (Hard)** (with *Solo stages
only*). One **Start** runs a queue: each box event with ticked units as its own job, one after
another, then Genesis, chapter by chapter (each chapter opened once). A job that stays stuck
after its grace periods is given up and the next one starts (the end says which). Stop and pause
cover the whole queue, and the Leaves limits count across it.

**Finding the way:** between jobs (and after a stop, or with the game left on any menu) the farm
uses a map of the game's menus (`data/screen_map.json` plus the Event and Genesis screens in
`app/navigator.py`): it recognises the screen, presses Back until it's on the way, then the menu
buttons. Only Back and menu buttons are pressed.

**Daily counter:** quests done today are remembered until the game's reset at 00:00 GMT (the tab
shows how long until then). After a stop, Start goes straight to the quests that are left. Before
pressing a quest the farm reads its row's "used / max", so quests played by hand count too and
nothing is spent twice. Genesis Hard stages are counted the same way.

**Event Archives:** older box events live in Quest > Event > **Event Archives** (Boss Battle
Quest tab) and must be unlocked there for 24 hours. The farm finds an event there by its name when
it isn't in the live list. Those units carry an **Archive** tag, and the pill at the top counts
the archive events picked (3 a day): ticking a unit of a 4th event is refused with a warning. A
locked archive event is unlocked with the day's free unlocks: OK is pressed
only if the dialog is for that event and says "Free once per day", read in full. Once it says
"Owned" (it would cost items) the farm presses Cancel and stops that job. Items and gems are never
spent. Needs TAC Auto Tap 1.3.1. Both are on by default; the Dev page has a switch for each
(the warning, the free unlock).

**Where the events come from:** a file on GitHub (`data/live/box_events.json`) that TACMonkey
downloads on start with the update check (or **Refresh** / **Check now**). Publishing a new box
event doesn't make a new release, so nobody gets an update prompt.

## VCR farm

Every finished run adds 0.1% to each equipped memento's progress (錬金境界値 on the result
screen); at 100% the memento's VCR is earned. The **VCR** page replays the quest you're on until
every equipped memento is at 100%:

- Open any quest's team screen and press **Start VCR farm**.
- Each run: **Go** → the battle plays on auto → Quest Missions (closed by tapping empty space) →
  EXP count-up (skipped) → result screen → **Try Again!** → **Go** again. A "Peddler Shop:
  Bazaar Found!" popup gets **View Later**.
- After each run the log shows every memento's %. Once they're all at 100% or more, the farm
  stops on the result screen.
- **Use leaves when AP runs out**: refills with Alchemy Drops using the Leaves page's settings
  and limits. Off: the farm stops when AP runs out.

The farm reads the screen through the mod, so it doesn't need button images.

## Dev page (developer only)

**Ctrl+Shift+D** turns on a **Dev** page (saved in `dev.json`, only on that PC). It needs a
fine-grained GitHub token with *Contents: read and write* on this repository only (also kept in
`dev.json`, never shared).

- **Box event: Scan the open map.** Box events are laid out like Genesis (a page with QUEST, a
  map with a Normal / Hard switch, one node per stage). Open the event's map in the game, pick
  Hard / Extra / Normal beside the button and press **Scan the open map**: it switches the map,
  reads every stage from the map's own data (title, attempts, loot through the magnifier; never
  OK), then goes Back to learn which list the event is opened from (Boss Battle Quest or the Event
  Archives). The farm later finds its way there with the menu map, opens the event, and taps each
  stage's node (found on the map by its quest id). Hard only shows once the event's Normal stages
  are cleared.
- **Scanned events:** every draft and live event, one row each, with where it's opened from and
  its state (*Draft, not live* / *Live* / *Live, draft changed*). Each row has its own **Publish**,
  **Take off live** and **Remove draft**. Click a row for the name players see, the unit pictures
  and the main units (☆ main on a unit; optional, any number).
- **Box event: list-style events** (folded under *Older list-style scans*). With the game on Quest > Event: **Read event list**, pick the event, give
  it a name for players, then **Scan whole event** (goes in, reads every quest and its Loot, comes
  back), **Scan the open list** (the quest list you have open; put e.g. `Hard` in *Place* if the
  event has more than one list) or **Add the open Quest Details** (a quest's magnifier you opened
  yourself). Scans of a few places add up in a draft (`box_draft.json`). Nothing is pressed that
  spends AP or attempts. Each unit's portrait is guessed from its shard's id; click one to pick
  another. The event then has its row under *Scanned events*, published from there.
- **Scripts: push to everyone.** Pick a script, write what's new, **Push script**. Every TACMonkey
  then asks once: **Add it** (added as a new script, nothing of theirs is changed), **Not now**
  (asks on the next start) or **Never for this one**. A new push of the same script asks again.
  The file is checked against its SHA-256 before it's added.
- **Texts.** **Edit texts...** lists every piece of wording on the pages (search, built-in text,
  what players see). Changes go out with **Publish texts**. Text with `{fields}` keeps them; an
  edit that doesn't fit falls back to the built-in wording.

`app/event_scan.py` also runs on its own: `python event_scan.py` scans every event's quests and
loot into `event_scan.json` (`--survey` for quest rows only).

## Genesis farm

Needs the mod. Start from the home screen or anywhere in Genesis. Hard units are picked on the
**Box events** tab (under Genesis (Hard)); Extra chapters on the **Genesis Ex** tab.

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
- **Grace period (built in):** when the game answers slowly, every wait stretches (up to 3x)
  before anything counts as stuck. If a stage still gets stuck ("stuck after skipping", "team
  screen didn't open" ...), the farm gives the game 10 s, closes popups, goes back into the
  chapter and tries that stage again. It reads the stage's attempts first, so a skip that went
  through isn't spent twice. After 3 grace periods in one run it stops as before; each one is
  written to `errors.log`. Running out of Alchemy Drops stops at once.
- On Stop, the log shows the shards got so far; while it runs, the status line keeps a total.
  The Ex farm's summary lists only the six elemental Soul Shards, and the Ex page counts them
  up during the run (each stage's own line still lists its Diagram Pieces).

**Leaves (AP refill):** when AP runs out, the Genesis and Ex farms and the AP refill action
refill it with Alchemy Drops (the box event farm too). The **Leaves** row in the main window sets how many per refill
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
