"""Genesis unit farm: skip-ticket the Genesis Hard stages that drop the units you pick.
Ex Genesis farm: the same for the Extra stages (third setting of the map's Normal/Hard switch,
ch7 and later): pick chapters and how many of their 5 Extra stages to do. Extra stages give
1 attempt a day and must be cleared once by hand before they can be skipped.

Needs the TAC Auto Tap mod (v1.2+) running in the game - everything is pressed and read through
it, so the mouse is never used. For every stage that drops a chosen unit:
    stage -> OK (team screen) -> "N times" skip button -> Use Skip Tickets (3x) -> OK
    -> rewards -> OK -> Back to the map
When AP runs out: Replenish AP -> Alchemy Drops -> set N pcs (7 unless set) -> OK -> OK, then
carry on - unless a leaf limit says stop (at most N per session / stop below N owned).
Stages with no attempts left today are skipped. The unit -> stage map comes from
genesis_shards.json (built from the loot of all 95 Genesis Hard stages); the Extra stages'
from genesis_extra.json (tools/genesis_drops.py --extra, then tools/genesis_extra_report.py).

    python genesis_farm.py Matia "Dark Julia"      (command line; the farm window has a picker)
    python genesis_farm.py --extra ALL             every Extra stage you have cleared
"""
import json
import re
import sys
import threading
import time
from pathlib import Path

import farm

SHARDS_FILE = farm.RES_DIR / "genesis_shards.json"
EXTRA_FILE = farm.RES_DIR / "genesis_extra.json"
ALL_EXTRA = "ALL"            # the Ex farm's "every Extra stage" pick (a key in genesis_extra.json)
AP_ITEM = "Alchemy Drops"   # exact row name; not "Alchemy Droplets" / event drops
AP_PCS = 7                  # Alchemy Drops per refill unless the leaf settings say otherwise
SKIPS = 3                   # skips per stage (the daily Hard attempts)
# Grace period (built in): a slow game stretches every wait (up to LAG_MAX times), and a stage
# that still gets stuck is given GRACE_WAIT s, then tried again - at most GRACE_TRIES per run.
LAG_MAX = 3.0
SLOW_REPLY = 1.5            # s: a mod reply slower than this is a sign the game is lagging
GRACE_WAIT = 10             # s
GRACE_TRIES = 3
# Waits poll the game instead of sleeping a fixed time: a mod reply takes ~20 ms, so every wait
# ends as soon as the screen has changed. SETTLE is a short pause after a screen change, for the
# game's slide-in animation (a press during it can be ignored - the farms check and press again).
POLL = 0.12
SETTLE = 0.25

# window fractions (same at any window size)
LIST_X, SLOTS = 0.777, (0.365, 0.599, 0.834)    # Genesis chapter list entries
DOWN = (0.779, 0.974)
QUEST_BTN = (0.836, 0.512)
DIFF = (0.127, 0.168)
NODES = ((0.1936, 0.4195), (0.3258, 0.5738), (0.4627, 0.4195), (0.5977, 0.5738), (0.7318, 0.4195))
POPUP_TITLE, POPUP_OK = (0.40, 0.40), (0.5, 0.641)
PEDDLER = "UnlockGuerrillaShopPopup"   # the Peddler Shop popup; its View Later is btn_cancel
NOTICE, NOTICE_OK = (0.5, 0.35), (0.5, 0.672)   # e.g. "Clear ... EX 1 to unlock." + its OK
MODES = {  # map switch sprite, how the stage popup ends its title, log label
    "hard": ("btn_scenario_hard", r"Hard", "Hard"),
    "extra": ("btn_scenario_extra", r"(?:Extra|EX)", "EX"),
}
ATTEMPTS_USED, ATTEMPTS_MAX = (0.693, 0.474), (0.72, 0.474)   # popup "Attempts 0/3"
OUTSIDE = (0.12, 0.75)
MAP_BACK, TOP_BACK, TEAM_BACK = (0.075, 0.933), (0.074, 0.935), (0.062, 0.941)
HOME_QUEST, STORY, GENESIS = (0.882, 0.895), (0.226, 0.520), (0.493, 0.540)


def result_button(els, end):
    """A button of the skip's rewards screen (RaidResultWindow) whose path ends with end."""
    return next((e for e in els if "RaidResultWindow" in e["path"] and e["path"].endswith(end)),
                None)


class Stop(Exception):
    pass


class LeafLimit(Exception):
    """A leaf (Alchemy Drops) limit was reached: stop instead of refilling."""


def leaf_settings(per=None, most=None, floor=None):
    """{"per": drops per refill, "most": at most this many per session (None = no limit),
    "floor": stop when fewer than this many are owned (None = off)}. Bad values are dropped."""
    def num(v, low):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        return v if v >= low else None
    return {"per": num(per, 1) or AP_PCS, "most": num(most, 1), "floor": num(floor, 1)}


def shared_owners(data):
    """{stage: set of units that drop from it} for the Hard data."""
    owners = {}
    for unit, d in data.items():
        for st in d["stages"]:
            owners.setdefault(st["stage"], set()).add(unit)
    return owners


def unit_stages(data, unit, picks=(), solo=False, owners=None):
    """A unit's stages in order. solo: leave out stages it shares with another unit, unless
    every unit on that stage is picked; a unit with only shared stages keeps them all."""
    lst = data[unit]["stages"]
    if not solo:
        return lst
    owners = owners if owners is not None else shared_owners(data)
    if shared_only(data, unit, owners):
        return lst
    picked = set(picks) | {unit}
    return [st for st in lst if owners.get(st["stage"], {unit}) <= picked]


def shared_only(data, unit, owners=None):
    owners = owners if owners is not None else shared_owners(data)
    return all(len(owners[st["stage"]]) > 1 for st in data[unit]["stages"])


def plan(data, units, counts=None, solo=False):
    """The stages to farm, newest chapter first: each unit's stages in the data's order, only
    its first counts[unit] of them when a count is set. Stages shared by units are done once.
    solo: leave out shared stages (see unit_stages)."""
    stages = {}
    owners = shared_owners(data) if solo else None
    for u in units:
        lst = unit_stages(data, u, units, solo, owners)
        n = (counts or {}).get(u)
        if isinstance(n, int) and 0 < n < len(lst):
            lst = lst[:n]
        for st in lst:
            stages[st["stage"]] = st
    return sorted(stages.values(), key=lambda s: (-s["chapter"], s["hard"]))


ELEMENTS = ("Fire", "Water", "Thunder", "Wind", "Light", "Dark")   # Ex drops "Fire Soul Shard" ...


class GenesisFarm:
    def __init__(self, log=print, stop=None, mode="hard", pause=None, status=None, leaves=None,
                 on_shards=None, counter=None):
        self.log = log
        self.stop = stop or threading.Event()
        self.pause = pause or threading.Event()   # set = pause before the next stage
        self.status = status or (lambda text: None)
        self.mode = mode
        self.pic, self.title_re, self.label = MODES[mode]
        self.shards = {}   # unit -> shards got this session
        self.on_shards = on_shards or (lambda shards: None)   # called with self.shards
        self.leaves = leaves or leaf_settings()
        self.leaves_used = 0
        self.leaves_left = None   # Alchemy Drops owned, as last read
        self.lag = 1.0            # patience: waits are stretched this much (grows when slow)
        self.recoveries = 0       # stuck stages given a grace period this run
        self.skips = SKIPS        # skips per stage (the box farm sets it per quest)
        # daily counter (box_farm.DayCounter): Hard stages done today, until 00:00 GMT
        self.counter = counter if mode == "hard" else None

    # ---------- talking to the mod ----------
    def send(self, cmd, timeout=8.0):
        """One mod command. "err timeout" means the game was busy (e.g. loading): a read is asked
        again; a tap, click or scroll is already queued in the game, so it isn't sent twice."""
        busy = False
        for _ in range(8):
            if self.stop.is_set():
                raise Stop()
            start = time.time()
            r = farm.mod_send(cmd, timeout=timeout, force=True)
            if r is None:
                busy = farm.mod_error() == "slow"
                if busy:
                    self.note_speed(slow=True)
                time.sleep(1)
                continue
            self.note_speed(slow=r.startswith("err timeout") or time.time() - start > SLOW_REPLY)
            if r.startswith("err timeout"):
                if cmd.startswith(("tap", "click", "scroll")):
                    self.sleep(1.5)   # it runs when the game catches up
                    return "ok (late - the game was busy)"
                busy = True
                self.sleep(1.5)
                continue
            return r
        raise RuntimeError("the game isn't answering (busy, paused or frozen?)" if busy else
                           "TAC Auto Tap mod not reachable - is the game running with the mod?")

    def note_speed(self, slow):
        """Grace period: each slow reply raises the patience a step; fast ones lower it slowly."""
        before = self.lag
        self.lag = min(LAG_MAX, self.lag + 0.5) if slow else max(1.0, self.lag - 0.02)
        if before < 2.0 <= self.lag:
            self.log("  The game is slow right now - waiting longer before calling anything stuck")

    def tap(self, p):
        return self.send(f"tap {p[0]:.4f} {p[1]:.4f}")

    def probe(self, p):
        return self.send(f"probe {p[0]:.4f} {p[1]:.4f}")

    def inspect(self, p):
        return self.send(f"inspect {p[0]:.4f} {p[1]:.4f}", timeout=10)

    def elements(self):
        """The mod's list of pressable things on screen (entries checked: path, x, y; text, top
        and on default to empty / False)."""
        r = ""
        for _ in range(3):
            r = self.send("list", timeout=10)
            try:
                els = json.loads(r)
            except ValueError:
                els = None
            if isinstance(els, list):
                out = []
                for e in els:
                    if isinstance(e, dict) and isinstance(e.get("path"), str) and \
                            isinstance(e.get("x"), (int, float)) and isinstance(e.get("y"), (int, float)):
                        out.append({**e, "text": str(e.get("text") or ""),
                                    "top": bool(e.get("top")), "on": bool(e.get("on"))})
                return out
            self.sleep(1.0)
        raise RuntimeError(f"the mod's list came back unreadable: {r[:60]!r}")

    @staticmethod
    def texts(reply):
        return [t.replace("\xa0", " ").strip() for t in re.findall(r"text:([^,\]]*)", reply)]

    def sleep(self, s):
        if self.stop.wait(s):
            raise Stop()

    def wait_for(self, fn, timeout=12.0, every=POLL):
        """fn() until it's truthy, for up to timeout s - stretched while the game is slow.
        Asked often (a mod reply takes ~20 ms): the farm moves on as soon as the game has."""
        end = time.time() + timeout * self.lag
        while time.time() < end:
            v = fn()
            if v:
                return v
            self.sleep(every)
        return None

    def steady(self, match, timeout=4.0, hold=4):
        """The on-screen element `match(e)` picks, once it has held still (same place and size)
        for `hold` looks in a row, ~0.08 s apart - the game slides and scales buttons in, and a
        press on a moving one can hit its neighbour - or None."""
        seen = []

        def still():
            e = next((e for e in self.elements() if e["top"] and e["on"] and match(e)), None)
            if not e:
                seen.clear()
                return None
            box = (round(e["x"], 3), round(e["y"], 3), round(e.get("w") or 0, 3),
                   round(e.get("h") or 0, 3))
            if seen and seen[-1] != box:
                seen.clear()
            seen.append(box)
            return e if len(seen) >= hold else None
        return self.wait_for(still, timeout, every=0.08)

    def settled(self, timeout=4.0, hold=0.3):
        """Wait until nothing on screen has moved, appeared or changed state for `hold` s (a
        screen loads its buttons in waves, and ignores presses until it's done). The elements
        then, or the last ones looked at if it never settled within timeout."""
        # what's on top only: behind-the-scenes decoration (the quest menu's light streaks)
        # never stops moving
        sig = lambda els: tuple((e["path"], e["on"], round(e["x"], 3), round(e["y"], 3),
                                 round(e.get("w") or 0, 3)) for e in els if e["top"])
        end = time.time() + timeout * self.lag
        els = self.elements()
        last, since = sig(els), time.time()
        while time.time() < end:
            self.sleep(0.08)
            els = self.elements()
            s = sig(els)
            if s != last:
                last, since = s, time.time()
            elif time.time() - since >= hold:
                break
        return els

    def gone(self, el, timeout=3.0):
        """Wait until a pressed element has left the screen (the press took).
        True if it did."""
        def away():
            return not any(e["path"] == el["path"] and abs(e["x"] - el["x"]) < 0.01
                           and abs(e["y"] - el["y"]) < 0.01 for e in self.elements())
        return bool(self.wait_for(away, timeout))

    def state_left(self, state, timeout=3.0):
        """Wait until screen_state() isn't `state` any more. The new state, or None."""
        def moved():
            s = self.screen_state()[0]
            return s if s != state else None
        return self.wait_for(moved, timeout)

    def find(self, path_end=None, text=None, usable=True):
        """First on-screen element whose path ends with path_end / whose text starts with text."""
        for e in self.elements():
            if usable and not (e["top"] and e["on"]):
                continue
            if path_end and not e["path"].endswith(path_end):
                continue
            if text and not e["text"].replace("\xa0", " ").startswith(text):
                continue
            return e
        return None

    def press(self, e, what="button"):
        if not e:
            raise RuntimeError(f"{what} wasn't on screen to tap")
        return self.tap((e["x"], e["y"]))

    def find_ok(self, wait=0.0):
        """The OK button of the open dialog (either width of "OK"), waiting up to `wait` s."""
        look = lambda: self.find(text="OK") or self.find(text="\uff2f\uff2b")
        return self.wait_for(look, wait) if wait else look()

    # ---------- where are we ----------
    def on_chapter_list(self):
        return "ChapterList" in self.probe((LIST_X, SLOTS[1]))

    def on_map(self):
        return "difficulty" in self.probe(DIFF)

    def on_team(self):
        return any("PartyEditor2" in e["path"] for e in self.elements() if e["top"])

    @property
    def navigator(self):
        if getattr(self, "_nav", None) is None:
            import navigator
            self._nav = navigator.Navigator(self, log=self.log)
        return self._nav

    def go_genesis(self):
        """Get to the Genesis chapter list from any screen the menu map knows (navigator.py);
        if that fails, the old way (home screen or anywhere inside Genesis)."""
        if self.on_chapter_list():
            return
        try:
            self.navigator.go("genesis list")
            if self.wait_for(self.on_chapter_list, 6):
                return
        except RuntimeError as e:
            self.log(f"  (menu map: {e} - trying the usual way)")
        for _ in range(10):
            if self.on_chapter_list():
                return
            if self.on_team():
                self.tap(TEAM_BACK)
            elif self.on_map():
                self.close_popups()
                self.tap(MAP_BACK)
            elif "GenesisQuestEventTop" in self.probe(QUEST_BTN):
                self.tap(TOP_BACK)
            elif "quest/event" in self.probe(HOME_QUEST):
                for p, w in ((HOME_QUEST, 4), (STORY, 4), (GENESIS, 5)):
                    self.tap(p)
                    self.sleep(w)
            else:
                self.close_popups()
            self.sleep(2.5)
        raise RuntimeError("couldn't reach the Genesis chapter list - start from the home screen")

    def dismiss_popup(self, els=None):
        """Press the safe button of a known popup (farm.KNOWN_POPUPS: the Peddler Shop's View
        Later, the Vision Clear Reward's OK ...) if one is showing. True if it was."""
        hit = farm.known_popup(els if els is not None else self.elements())
        if not hit:
            return False
        name, answer, btn = hit
        self.press(btn)
        self.log(f"  {name} popped up - {answer}")
        self.gone(btn, 3)
        self.sleep(SETTLE)
        return True

    dismiss_peddler = dismiss_popup   # its old name

    def close_popups(self):
        for _ in range(4):
            here = self.probe(OUTSIDE)
            if any(obj in here for _, obj, _, _ in farm.KNOWN_POPUPS):
                if not self.dismiss_popup():
                    return
                continue
            elif "Win_Btn_Decide" in here:          # a game notice: its OK closes it
                self.tap(NOTICE_OK)
            elif "GenesisQuestConfirm" in here or "QuestDetail" in here:
                self.tap(OUTSIDE)
            else:
                return
            self.wait_for(lambda: self.probe(OUTSIDE) != here, 2.5)
            self.sleep(SETTLE)

    def notice(self):
        """The text of a game notice (e.g. "Clear ... EX 1 to unlock."), or None."""
        if "Win_Btn_Decide" not in self.probe(NOTICE):
            return None
        return " ".join(self.texts(self.inspect(NOTICE))) or "?"

    # ---------- chapter / stage ----------
    def chapter_in_slot(self, y):
        m = re.search(r"mIname=([^,>]+)", self.inspect((LIST_X, y)))
        return m.group(1) if m else None

    def open_chapter(self, iname):
        self.go_genesis()
        self.send(f"scroll {LIST_X} {SLOTS[1]} 1")
        self.sleep(0.4)
        for _ in range(9):
            for y in SLOTS:
                if self.chapter_in_slot(y) == iname:
                    self.tap((LIST_X, y))
                    if not self.wait_for(lambda: "GenesisQuestEventTop" in self.probe(QUEST_BTN), 15):
                        raise RuntimeError(f"{iname}: chapter page didn't open")
                    # its QUEST grows in and ignores an early press (map_scan.open_map waits)
                    import map_scan
                    if not map_scan.MapScanner(self).open_map():
                        raise RuntimeError(f"{iname}: quest map didn't open")
                    return self.set_mode()
            self.tap(DOWN)
            self.sleep(0.6)
        raise RuntimeError(f"{iname}: not in the Genesis chapter list")

    def set_mode(self):
        """Press the map's Normal/Hard/Extra switch until it shows this farm's mode."""
        for _ in range(4):
            pics = self.inspect(DIFF)
            if self.pic in pics:
                return True
            if "btn_scenario_" in pics:
                self.tap(DIFF)
                self.wait_for(lambda: self.inspect(DIFF) != pics, 2.5)
                self.sleep(SETTLE)   # the nodes redraw
            else:
                self.sleep(0.5)
        raise RuntimeError(f"couldn't switch the map to {self.label}")

    def popup_title(self):
        for t in self.texts(self.inspect(POPUP_TITLE)):
            if re.search(rf"\b{self.title_re}\s*\d+\s*$", t):
                return t
        return None

    def popup_attempts(self):
        """(used, max) from the popup's "Attempts 0/3", or None if it can't be read."""
        def num(p):
            for t in self.texts(self.inspect(p)):
                m = re.search(r"(\d+)", t)
                if m:
                    return int(m.group(1))
            return None
        used, most = num(ATTEMPTS_USED), num(ATTEMPTS_MAX)
        return (used, most) if used is not None and most else None

    # ---------- skip + AP ----------
    def slider_value(self):
        """The number shown above the slider of the open dialog (skip count / pcs)."""
        s = self.find(path_end="slider", usable=False)
        if not s:
            return None
        for dy in (0.085, 0.057, 0.07, 0.1, 0.05, 0.065, 0.075, 0.09, 0.11, 0.04):
            t = self.texts(self.inspect((s["x"], s["y"] - dy)))
            # the panel lists its labels in order, e.g. '803', '1', 'pcs' -> the number before 'pcs'
            for i, w in enumerate(t):
                if w.lower() in ("pcs", "x", "times") and i > 0 and t[i - 1].isdigit():
                    return int(t[i - 1])
            if len(t) == 1 and t[0].isdigit():   # hit the number itself
                return int(t[0])
        return None

    def set_slider(self, want):
        """Press - / + until the dialog's number is `want` (or as close as allowed)."""
        for _ in range(25):
            v = self.slider_value()
            if v is None or v == want:
                return v
            btn = self.find(path_end="minus" if v > want else "plus") or \
                self.find(path_end="btn_minus" if v > want else "btn_plus")
            if not btn:
                return v
            self.press(btn)
            self.sleep(0.4)
            if self.slider_value() == v:   # didn't move: limit reached
                return v
        return self.slider_value()

    SUCCESS_OK = "HealApResult/layout/ok"   # seen live: UICanvas(Clone)/HealAP(Clone)/
    #                                         CanvasBoundsPanel/Panel/HealApResult/layout/ok

    def success_ok(self):
        """The OK of the "AP successfully replenished" popup, if it's up - only that exact
        button, so the Alchemy Drops amount step's OK is never pressed a second time."""
        return next((e for e in self.elements() if e["top"] and e["on"]
                     and e["path"].endswith(self.SUCCESS_OK)), None)

    def close_success(self, wait):
        """Press the success popup's OK - waiting up to `wait` s for it - until it's gone.
        True if it was pressed."""
        presses = 0
        end = time.time() + wait
        while presses < 5:   # (looks at least once, even with wait=0)
            ok = self.success_ok()
            if ok:
                self.press(ok)
                presses += 1
                self.gone(ok, 2.0)
            elif presses or time.time() >= end:
                break
            else:
                self.sleep(0.25)
        return presses > 0

    def leaf_summary(self):
        left = f", {self.leaves_left} left" if self.leaves_left is not None else ""
        return f"{self.leaves_used} {AP_ITEM} used this session{left}"

    def close_ap_window(self):
        """Leave the Replenish AP window without refilling (cancel / close, whatever shows)."""
        for _ in range(3):
            els = [e for e in self.elements() if e["top"] and e["on"]]
            btn = next((e for e in els if ("UseApHealItem" in e["path"] or "HealAP" in e["path"])
                        and e["path"].rsplit("/", 1)[-1] in ("cancel", "btn_cancel", "btn_close",
                                                             "close")), None)
            if not btn:
                return
            self.press(btn)
            self.sleep(1.0)

    def leaf_stop(self, why):
        self.close_ap_window()
        raise LeafLimit(f"{why} - stopping instead of refilling AP ({self.leaf_summary()})")

    def replenish_ap(self):
        """Replenish AP window is open: Alchemy Drops x N -> OK -> OK (N = leaves per refill),
        unless a leaf limit is reached: then LeafLimit."""
        per, most, floor = self.leaves["per"], self.leaves["most"], self.leaves["floor"]
        want = per
        if most is not None:
            if self.leaves_used >= most:
                self.leaf_stop(f"Leaf limit: {most} per session reached")
            want = min(per, most - self.leaves_used)
        if self.close_success(0):   # a refill's success popup was left up: just close it
            self.log("  Closed the \"AP successfully replenished\" popup")
            return
        els = self.elements()
        # the amount step may already be open (e.g. pressed by hand): carry on if it's for
        # Alchemy Drops (and no "stop below" check needs the list), else cancel it and pick
        # Alchemy Drops from the list
        amount_open = False
        ticket = next((e for e in els if e["path"].endswith("UseApHealItem/layout/inline/ticket")), None)
        if ticket and ticket["top"]:
            if floor is None and AP_ITEM in self.texts(self.inspect((ticket["x"] - 0.09, ticket["y"]))):
                amount_open = True
            else:
                cancel = self.find(path_end="UseApHealItem/layout/cancel")
                if cancel:
                    self.press(cancel)
                    self.sleep(1.0)
                els = self.elements()
        if not amount_open:
            # rows read like "@ | 803 | Alchemy Drops | 120 | AP Replenished" - match the name exactly
            row = next((e for e in els if e["top"] and e["on"] and "HealAPItemList" in e["path"]
                        and AP_ITEM in [p.strip() for p in e["text"].replace("\xa0", " ").split("|")]),
                       None)
            if not row:   # out of them: a retry wouldn't help
                self.leaf_stop(f"Replenish AP is open but '{AP_ITEM}' isn't there (out of them?)")
            parts = [p.strip() for p in row["text"].replace("\xa0", " ").split("|")]
            i = parts.index(AP_ITEM)
            if i > 0 and parts[i - 1].isdigit():   # owned count sits right before the name
                self.leaves_left = int(parts[i - 1])
            if floor is not None and self.leaves_left is not None and self.leaves_left < floor:
                self.leaf_stop(f"Leaf limit: fewer than {floor} {AP_ITEM} left")
            self.press(row, AP_ITEM)
            if not self.find_ok(6):
                raise RuntimeError("Alchemy Drops confirm didn't open")
        self.sleep(0.6)
        got = self.set_slider(want)
        if got is None:
            raise RuntimeError("couldn't read the Alchemy Drops amount")
        if got > want:   # the slider wouldn't go lower: don't use more than allowed
            self.leaf_stop(f"Couldn't set {AP_ITEM} to {want}")
        if got != want:   # the game caps it so AP can't pass its maximum
            self.log(f"  (the game allows only {got} {AP_ITEM} right now - using {got})")
        # the OK can take a moment to show (or be briefly covered): wait for it, don't look once
        self.press(self.find_ok(5), "The Alchemy Drops amount step's OK")
        # then "AP successfully replenished" opens on top with its own OK. The amount step's OK
        # can still be on screen for a moment, and the popup can take a while: looking once
        # (too early) pressed nothing and left the farm stuck on that popup. Wait for an OK
        # that isn't the amount step's, press it, and check it has gone.
        if not self.close_success(12):
            self.log("  (the \"AP successfully replenished\" popup didn't show up - carrying on)")
        self.leaves_used += got
        if self.leaves_left is not None:
            self.leaves_left -= got
        self.log(f"  AP refilled with {got} {AP_ITEM} ({self.leaf_summary()})")
        self.sleep(1.5)

    def screen_state(self):
        els = [e for e in self.elements() if e["top"]]
        paths = " ".join(e["path"] for e in els)
        alltext = " ".join(e["text"] for e in els).replace("\xa0", " ")
        if any(obj in paths for _, obj, _, _ in farm.KNOWN_POPUPS):
            return "popup", els
        if "RaidResultWindow" in paths:
            return "result", els
        if "RaidSettings" in paths:
            return "skipdialog", els
        if "HealAPItemList" in paths:
            return "apwindow", els
        if "PartyEditor2" in paths:
            return "team", els
        return "other", els

    def skip_stage(self, key):
        """On the team screen: skip as many times as attempts allow (up to SKIPS). Returns
        (shards got, whether it skipped)."""
        got = {}
        did_skip = False
        refill_fails = 0
        counted = False   # this skip's rewards screen has been read
        start = time.time()
        for _ in range(400):   # ~50 s, stretched while the game is slow
            if time.time() - start > 50 * self.lag:
                break
            state, els = self.screen_state()
            if state == "team":
                btn = next((e for e in els if e["path"].endswith("ticket/btn")), None)
                if not btn or not btn["on"]:
                    return got, did_skip     # no attempts left today
                if did_skip:
                    return got, did_skip     # one 3x skip per stage
                self.press(btn)
                self.state_left("team", 2.5)   # ignored (still sliding in)? pressed again
                self.sleep(SETTLE)
            elif state == "skipdialog":
                n = self.slider_value()
                if n is not None and n < self.skips:
                    self.set_slider(self.skips)
                    n = self.slider_value()
                ok = next((e for e in els if e["path"].endswith("bg/ok")), None)
                if not ok:
                    raise RuntimeError("skip dialog has no OK button")
                self.press(ok)
                if not did_skip:
                    self.log(f"  {key}: skipping {n}x")
                did_skip = True
                self.state_left("skipdialog", 3)
            elif state == "popup":
                if not self.dismiss_popup(els):
                    self.sleep(0.5)
            elif state == "apwindow":
                try:
                    self.replenish_ap()
                    refill_fails = 0
                except RuntimeError as e:   # a missed button mid-refill: look again
                    refill_fails += 1
                    if refill_fails >= 3:
                        raise
                    self.log(f"  AP refill didn't finish ({e}) - trying again")
                    self.sleep(1.0)
            elif state == "result":
                # the result window's own OK only: the team screen's hidden sort menu has a
                # "btn_ok" too (UnitSortMenu/window/btn_ok), and taking it for this one counted
                # the rewards twice
                okb = result_button(els, "btn_ok")
                if okb and not counted:
                    # seen the moment it opens now: let its rewards fill in before reading them
                    els = self.settled(2.0)
                    okb = result_button(els, "btn_ok")
                if okb:
                    # one 3x skip = one rewards screen: counted once, however many presses
                    # its OK takes (one the game ignores while it animates leaves it up)
                    if not counted:
                        shards = self.reward_shards(els)
                        if shards is not None:
                            for unit, n in shards:
                                got[unit] = got.get(unit, 0) + n
                            counted = True
                    self.press(okb)
                    self.gone(okb, 2.5)
                else:
                    skip = result_button(els, "itemskip")
                    if skip:
                        self.press(skip)
                        self.gone(skip, 2.0)
                    else:
                        self.sleep(0.3)
            elif self.close_success(0):   # a refill's success popup was left up
                self.log("  Closed the \"AP successfully replenished\" popup")
            else:
                self.sleep(0.25)
        raise RuntimeError(f"{key}: stuck after skipping")

    def reward_shards(self, els):
        """(name, count) for the unit shards (and, on Extra stages, Diagram Pieces) on the
        rewards screen; None while its drop list isn't there to read."""
        node = next((e for e in els if "itemlist" in e["path"] and e["path"].endswith("dropitem")), None)
        if not node:
            return None
        reply = self.send(f"items {node['x']:.3f} {node['y']:.3f}", timeout=10)
        out = []
        for chunk in reply.split(" ||| ")[1:]:
            m = re.search(r"name=([^,<>]+?)(?:'s|’s)? Soul Shard\s*(?:<[^>]*>\s*)*,type=UnitPiece", chunk)
            if not m and self.mode == "extra":
                m = re.search(r"name=([^,<>]+ Diagram Piece)\s*(?:<[^>]*>\s*)*,type=ItemPiecePiece", chunk)
            if m:
                # labels read e.g. "*", "3", "(Owned: 49)" - the count sits right before "(Owned"
                t = self.texts(chunk)
                n = next((int(t[i - 1]) for i in range(1, len(t))
                          if t[i].startswith("(Owned") and t[i - 1].isdigit()), None)
                name = m.group(1)
                if self.mode == "extra" and not name.endswith("Diagram Piece"):
                    name += " Soul Shard"   # elemental shards: "Thunder Soul Shard", not "Thunder"
                out.append((name, n if n is not None else 1))
        return out

    def farm_stage(self, st):
        key = st["stage"] if self.mode == "hard" else f"EX {st['stage']}"
        self.set_mode()
        self.tap(NODES[st["hard"] - 1])
        title = self.wait_for(lambda: self.popup_title() or (self.notice() and "notice"), 8)
        if title == "notice":
            text = self.notice()
            self.close_popups()
            why = "locked - clear it by hand once" if "unlock" in text.lower() else text
            self.log(f"  {key}: {why} - skipped")
            return
        if not title or not re.search(rf"\b{self.title_re}\s*{st['hard']}\s*$", title):
            self.close_popups()
            self.log(f"  {key}: stage popup didn't open as expected ({title}) - skipped")
            return
        att = self.popup_attempts()
        if att and att[0] >= att[1]:
            self.log(f"  {key}: attempts {att[0]}/{att[1]} used today - skipped")
            self.note_done(st, att[1])
            self.close_popups()
            return
        self.tap(POPUP_OK)
        if not self.wait_for(self.on_team, 12):
            self.close_popups()
            self.log(f"  {key}: team screen didn't open - skipped")
            return
        self.sleep(SETTLE)
        got, skipped = self.skip_stage(key)
        self.note_done(st, att[1] if att else SKIPS)   # skipped, or no attempts left
        if not skipped:
            self.log(f"  {key}: no attempts left today - skipped" if self.mode == "hard" else
                     f"  {key}: can't skip - no attempt left today, or not cleared by hand yet")
        else:
            txt = ", ".join(f"{u} x{n}" for u, n in got.items()) or "no shards this time"
            self.log(f"  {key}: done - {txt}")
            for u, n in got.items():
                self.shards[u] = self.shards.get(u, 0) + n
            self.on_shards(dict(self.shards))
            self.status(f"{key} done - {self.shard_summary()}")
        self.back_to_map(key, self.on_map, self.close_popups)

    def back_to_map(self, key, on_map, close_popups):
        """From the team screen after a skip: its Back (to the stage popup), the popup closed,
        until the map shows. Back is pressed again only if the team screen stays a while: an
        extra press once it's gone would hit the map's own Back."""
        self.tap(TEAM_BACK)
        last = time.time()
        end = last + 15 * self.lag
        while time.time() < end:
            if self.on_team():
                if time.time() - last > 3 * self.lag:
                    self.tap(TEAM_BACK)
                    last = time.time()
                self.sleep(POLL)
                continue
            close_popups()
            if on_map():
                self.sleep(SETTLE)
                return
            self.sleep(0.2)
        raise RuntimeError(f"{key}: didn't get back to the map")

    def day_key(self, st):
        # Extra stages share their numbers with the Hard ones ("19-1"): kept apart
        return f"genesis|{'' if self.mode == 'hard' else 'EX '}{st['stage']}"

    def note_done(self, st, most):
        if self.counter is not None:
            self.counter.note(self.day_key(st), most, most)

    def grace(self, st, err):
        """A stage got stuck: give the game GRACE_WAIT s, tidy up, and say whether to try it
        again (False once GRACE_TRIES are used). Call it inside the except block. A retry can't
        spend twice: the stage's attempts are read again, and a used-up stage is skipped."""
        key = st["stage"] if self.mode == "hard" else f"EX {st['stage']}"
        self.recoveries += 1
        err = str(err)
        err = err[len(key) + 2:] if err.startswith(f"{key}: ") else err
        farm.log_error(f"{self.label} Genesis farm, {key} (grace period {self.recoveries})")
        if self.recoveries > GRACE_TRIES:
            self.log(f"  {key}: {err} - still stuck after {GRACE_TRIES} grace periods this run")
            return False
        wait = round(GRACE_WAIT * self.lag)
        self.log(f"  {key}: {err} - giving the game {wait} s, then trying {key} again "
                 f"({self.recoveries} of {GRACE_TRIES})")
        self.status(f"{key}: giving the game {wait} s")
        self.sleep(wait)
        self.lag = min(LAG_MAX, self.lag + 0.5)   # and be more patient from here on
        try:
            self.close_success(0)
            self.close_ap_window()
            self.close_popups()
        except RuntimeError:
            pass
        return True

    def elemental(self):
        """{element: shards} got this session (Ex drops the six elemental Soul Shards)."""
        return {el: self.shards[f"{el} Soul Shard"] for el in ELEMENTS
                if self.shards.get(f"{el} Soul Shard")}

    def shard_summary(self):
        if self.mode == "extra":   # just the elemental shards: the Diagram Pieces made it long
            got = ", ".join(f"{el} x{n}" for el, n in self.elemental().items()) or "none"
            return f"Elemental shards this run: {got}"
        got = ", ".join(f"{u} x{n}" for u, n in self.shards.items()) or "none"
        return f"Shards this run: {got}"

    def wait_if_paused(self):
        """Pause point (between stages). True if it paused - the caller then finds its way back,
        since the game may have been used meanwhile."""
        if not self.pause.is_set():
            return False
        self.log("  Paused - press Resume (or F8) to carry on")
        self.status("Paused")
        while self.pause.is_set():
            self.sleep(0.3)
        self.log("  Resumed")
        self.status("Running")
        return True

    def run(self, units, counts=None, solo=False):
        """units: unit names (Hard) or chapters like "ch15" / ALL_EXTRA (Extra).
        counts: {unit: how many of its stages to farm} (missing = all of them).
        solo: Hard only - leave out stages shared with units that aren't picked."""
        data = load_data(self.mode)
        unknown = [u for u in units if u not in data]
        if unknown:
            raise RuntimeError(f"unknown picks: {unknown}")
        order = plan(data, units, counts, solo and self.mode == "hard")
        name = "Genesis farm" if self.mode == "hard" else "Ex Genesis farm"
        if self.counter is not None:   # straight to the stages left today
            done = [s for s in order if self.counter.finished(self.day_key(s), SKIPS)]
            if done:
                self.log(f"{name}: {len(done)} stage{'s' if len(done) != 1 else ''} already "
                         f"done today - "
                         f"{', '.join(s['stage'] for s in done)}")
                order = [s for s in order if s not in done]
        self.log(f"{name}: {', '.join(units)} -> {len(order)} {self.label} stages"
                 f"{' (solo stages only)' if solo and self.mode == 'hard' else ''}: "
                 f"{', '.join(s['stage'] for s in order)}")
        try:
            chapter = None
            for st in order:
                if self.wait_if_paused():
                    chapter = None   # reopen the chapter: the game may have moved meanwhile
                while True:
                    try:
                        if st["chapter"] != chapter:
                            chapter = None
                            self.log(f"ch{st['chapter']} {st['chapter_name']}")
                            self.open_chapter(st["chapter_iname"])
                            chapter = st["chapter"]
                        self.farm_stage(st)
                        break
                    except RuntimeError as e:
                        chapter = None   # find the way back in from wherever it is
                        if not self.grace(st, e):
                            raise
            self.go_genesis()
            self.log(f"{name} finished. {self.shard_summary()}")
            return "Finished."
        except Stop:
            self.log(f"{name} stopped. {self.shard_summary()}")
            return "Stopped."
        except LeafLimit as e:
            self.log(f"{e}. {self.shard_summary()}")
            return str(e)
        except Exception:
            self.log(f"{name} ended early. {self.shard_summary()}")
            raise


def load_data(mode="hard"):
    """{pick: {"stages": [...]}}: units (Hard) or chapters ("ch15") + ALL_EXTRA (Extra)."""
    return json.loads((SHARDS_FILE if mode == "hard" else EXTRA_FILE).read_text(encoding="utf-8"))


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "extra" if "--extra" in args else "hard"
    print(GenesisFarm(mode=mode).run([a for a in args if a != "--extra"]))
