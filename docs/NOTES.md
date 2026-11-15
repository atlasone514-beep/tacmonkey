# TAC Auto Mod - notes

Goal: let farm.py tap the game **without using the Windows mouse/focus**. A small mod inside the
game receives "tap at x,y" from farm.py over a local connection and presses whatever Unity UI
element is under that point (EventSystem raycast + pointer down/up/click). farm.py keeps all its
screen reading, scripts and Customize; only `tap()` changes (falls back to the touch tap when the
mod isn't running).

## What the game is (checked 2026-11-07, read-only)
- Unity **6000.3.24f1** (Unity 6.3), IL2CPP build (`GameAssembly.dll` + `global-metadata.dat`).
- `global-metadata.dat`: normal header `AF 1B B1 FA` -> **not encrypted**; **metadata version 39**.
- Names inside are readable (not obfuscated), e.g. `ADVANCE_QUEST_OPEN_SKIP`.
- UI uses `UnityEngine.UI` (uGUI) -> EventSystem clicks should work.
- Other assemblies of note: Photon (networking), `Backtrace.Unity` (crash reporter - a crash
  caused by a mod may get reported to whoever runs the game's crash reporting),
  `GSCC.DeviceKit`. No well-known anti-cheat found.

## What the game reports to the rebuild server (read-only check, 2026-11-11)
- Server: `alchemist.jb3.in`. The rebuild's own code ("Mod*" classes: ModLogin, ModUpdate,
  ModPurchase, ModTelemetry, ModAntiCheat, ModPrank...) is compiled into the game.
- **ModTelemetry** redirects crash reporting + logs to the rebuild server:
  `/telemetry/backtrace`, `/telemetry/unitycrash/{0}`, `/telemetry/slack/files.upload`.
  Backtrace: managed errors only ("no 64-bit BacktraceCrashpadWindows.dll ... native crash
  capture disabled"); config allows adding the Unity log to reports.
- **LogKit analytics** (queued in LocalLow\Taga Reconstruction\The Alchemist Code\AppData\_logs):
  device id, CPU, RAM, Windows version, and every scene change (e.g. Start -> town004),
  tagged `environment: production`. So the server can see a play timeline (farming pattern).
- **ModAntiCheat** starts Code Stage ACTk `ObscuredCheatingDetector` (memory editing) and
  `SpeedHackDetector` every launch. Its fields (Flag, StampPendingFlag, HeaderName) suggest a
  detection is stamped into a header on the next server request. A button-pressing mod or
  the screen-reading script changes neither memory values nor game speed.
- **No checks for mod loaders**: no strings for BepInEx/MelonLoader/doorstop/winhttp/Harmony,
  no module/process listing APIs (CreateToolhelp32Snapshot, EnumProcessModules). ACTk's
  InjectionDetector is compiled in but only works on Mono builds, not IL2CPP.
- After the BepInEx launch: Player.log, LogKit queue and backtrace folder contain **no**
  mention of BepInEx; no crash report was written.
- `ModPrank`: plays a downloaded video (rick.mp4) and suppresses a reward popup - trigger
  unknown (joke/event feature; not obviously tied to the anti-cheat).

## Mod loader status for Unity 6000.3 / metadata v39
- **BepInEx 6 bleeding-edge (IL2CPP)**: v39 metadata support since build #755; use the newest
  build. Known open problem on some 6000.3 games: Il2CppInterop hook signature scan fails and the
  game crashes (Il2CppInterop issue #283). So: works for some 6000.3 games, not all.
- **MelonLoader**: several open bugs on Unity 6000.x (e.g. "No Support Module Loaded!").
- Plan: try BepInEx 6 BE first; if it crashes, MelonLoader nightly; if both fail, use the VM
  route instead.

## Steps
1. [x] Check build type, metadata, Unity version.
2. [x] Download BepInEx 6 BE (IL2CPP, win-x64), newest build, from builds.bepinex.dev.
       Got build #793 (2026-11-05): `downloads\bepinex-be793\BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.793+dbc82f0.zip`
       34,339,235 bytes, sha256 5b63d7d0e92a2448ccd13b738ff95ff1cc1026c6d718555d4df8e6c824953ac4
       Zip tested OK: 233 files - winhttp.dll, doorstop_config.ini, .doorstop_version,
       changelog.txt, BepInEx\ (41), dotnet\ (188).
3. [x] Close the game, unzip BepInEx into the GAME folder (next to TagaReconstruction.exe).
       Installed 2026-11-11: 228 files, nothing overwritten (all names were free first).
       Added: `winhttp.dll`, `doorstop_config.ini`, `.doorstop_version`, `changelog.txt`,
       `BepInEx\`, `dotnet\`. Every added file is listed in `installed_files.txt` (this folder).
       Uninstall = close the game, delete those 4 files + 2 folders (BepInEx\ will by then also
       hold generated files, delete it all). Quick off-switch without uninstalling:
       `doorstop_config.ini` -> `enabled = false`.
4. [~] Start the game once: BepInEx generates the interop assemblies (first start is slow).
       Check `BepInEx\LogOutput.log` - success or the known crash.
       Result 2026-11-11: BepInEx loads, downloads unity-libs 6000.3.24, Cpp2IL reads metadata
       v39 fine (9 s). Then Il2CppInterop generation FAILS:
       `Pass11ComputeTypeSpecifics -> CustomAttributeEx.Extract -> SingleOrDefault:
       Sequence contains more than one matching element`. No interop assemblies -> no plugins.
       The game itself starts and runs normally.
       Cause (confirmed): the rebuild was compiled from dumped/decompiled code and still carries
       the dumper tags (`AddressAttribute`, `TokenAttribute`, `FieldOffsetAttribute`,
       `MetadataOffsetAttribute`, `Cpp2ILInjected` are in its own global-metadata.dat). Cpp2IL
       adds the same tags again -> each method has 2 -> SingleOrDefault throws.
       Fix idea: patched `Il2CppInterop.Generator.dll` (BepInEx\core) whose Extract ignores the
       game's leftover copy (or takes the last one). Needs a .NET SDK to build (none installed;
       only runtimes 8/9/10). MelonLoader uses the same Cpp2IL + Il2CppInterop pipeline, so it
       would most likely hit the same error.
4b. [x] Patch for the duplicate tags (2026-11-11):
       - .NET 8 SDK 8.0.428 (portable zip, sha512 checked) in `tools\dotnet-sdk-8.0.428`.
       - `tools\diag`: runs Cpp2IL like BepInEx. 238,969 members have 2 copies of
         Address/Token/FieldOffset tags: leftover = namespace `Cpp2IlInjected` (lower-case l,
         old Cpp2IL used to make the rebuild), fresh = `Cpp2ILInjected`. The fresh copy is ALWAYS
         the last one (238,969/238,969) and holds this build's real token (62,808/62,820
         checked; the 12 misses are overloads my name-based check can't tell apart).
       - `tools\patcher`: in `Il2CppInterop.Generator.dll` (1.5.3, dbda1cb),
         `CustomAttributeEx.Extract`: `SingleOrDefault<CustomAttribute>` -> `LastOrDefault`.
       - `tools\gentest`: full offline generation with the patched dll -> OK, 102 interop
         assemblies (Assembly-CSharp 38.8 MB) in ~27 s.
       - Installed: `BepInEx\core\Il2CppInterop.Generator.dll` = `patched\...`.
         Original kept in `backup\Il2CppInterop.Generator.original.dll` (copy it back to undo).
       - Note: updating BepInEx would overwrite the patched dll - re-run the patcher after.
4c. [x] Launch with the patched generator (2026-11-11 21:19): interop generation "Done!",
       105 assemblies in BepInEx\interop, "Chainloader startup complete", 0 plugins.
       Warning: "Class::Init signatures have been exhausted, using a substitute!" (the
       Il2CppInterop #283 symptom) - but registering BepInEx's own injected type worked, and the
       game ran ~2 min and shut down cleanly: no exceptions in Player.log, no crash events.
       Nothing mentions BepInEx in the game's logs / LogKit queue / backtrace folder.
5. [ ] If it loads: add UnityExplorer (BepInEx IL2CPP build) to look at the UI objects live.
6. [x] Write the mod: `src\TACAutoTap` (build: `tools\dotnet-sdk-8.0.428\dotnet.exe build -c Release`
       in that folder; built against BepInEx's own .NET 6 runtime). Installed as
       `BepInEx\plugins\TACAutoTap.dll`. Listens on 127.0.0.1:47613 only. Commands:
       `ping`, `probe FX FY` (report only), `tap FX FY` (FX/FY = fraction of the window from the
       top-left). Press = EventSystem.RaycastAll -> pointer down / up / click on the main thread.
       Replies `ok <object path>` or `nohandler <why>`. Hand test: `python tools\modtest.py ping`.
       Remove the mod = delete `BepInEx\plugins\TACAutoTap.dll`.
7. [x] farm.py `tap()`: tries the mod first (no mouse, no focus, works while covered); falls back
       to the touch tap on `nohandler` or if the mod isn't running (re-checked every 30 s). The log
       marks each click `[mod]` or `[touch]`; a run's first lines say whether the mod is running.
9. [x] Mod v1.2 (2026-11-11): adds `list` (pressable elements + their text, JSON),
       `click TEXT [#N]`, `items FX FY` (every entry of the list under the point, with the game's
       data fields - e.g. loot item iname/name/type, chapter mIname/mName), `inspect FX FY`,
       `scroll FX FY V`. v1.0 kept in backup\TACAutoTap-1.0.0.dll.
       `tools\genesis_drops.py`: reads the loot of every Genesis Hard stage (never presses OK);
       `tools\genesis_report.py`: builds D:\programs\TAC Auto Story\genesis_drops\
       genesis_unit_shards.txt + genesis_loot_all.csv. All 95 stages read and checked.
10. [x] Genesis unit farm (2026-11-11): `D:\programs\TAC Auto Story\genesis_farm.py` + a
       "GENESIS UNIT FARM" section in farm_ui.pyw (tick units -> their stages from
       genesis_shards.json). Per stage: popup (skips if "Attempts 3/3") -> OK -> team screen
       `ticket/btn` "3 times" -> RaidSettings dialog (reads the count) -> OK -> RaidResultWindow
       -> btn_ok -> team Back -> close popup. AP: HealAPItemList -> row "Alchemy Drops" ->
       UseApHealItem: + until 7 pcs (game caps so AP <= max) -> OK -> OK. Tested: 3 real 3x skips
       (8-3/4/5), AP 760 -> 400. AP refill path not yet seen live (needs AP < 120).
8. [~] Test in the game (2026-11-11): plugin loads ("Loading [TAC Auto Tap 1.0.0]", TapRunner
       registered despite the Class::Init substitute warning). `ping` -> `pong 1.0.0 1765x993`.
       Probes on the home screen found the real buttons (ShortcutMenu/open, quest/event,
       mapbutton/limitedshop, mapbutton/guild, menu/new_arrivals, menu/friend); empty sky ->
       nohandler. Real taps: Notices (opens a web link - disabled on this server, as expected),
       Friends (opened the Friends screen), Home button `PlayerStatus/option_back/back` (back to
       home). Each 9-80 ms, focus never changed. Still to do: a farm run with [mod] taps.
