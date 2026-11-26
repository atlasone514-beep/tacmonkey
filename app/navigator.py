"""Find the way around the game's menus: which screen is showing, and how to get to another.

The map is screen_map.json (data/screen_map.json in the repository): each screen has a marker (a
piece of an on-screen object's path that shows only there), "open" (the buttons to press from
home, in order) and "back" (the button that leaves it). The Event and Genesis screens the farms
use are added below (ROUTES), with the same fields.

go(target) works from any screen it knows: it presses Back (closing known popups on the way)
until it's on the target's route - home at the latest - then presses the route's buttons. A farm
can be stopped anywhere, or the game left on any menu, and the next job still finds its way.
Nothing is bought, claimed or started: only Back and menu buttons are pressed.
"""
import json
import re
import time

import farm

MAP_FILES = (farm.RES_DIR / "screen_map.json",
             farm.RES_DIR.parent / "data" / "screen_map.json")   # run from source

# the screens the farms need, on top of what the menu walk recorded; "parent" is the screen
# its Back goes to. Steps are path ends to press ("@x,y" = a spot, for screens without names).
QUEST = "HomeBG/HomeBGUI/CanvasBoundsPanel/quest/event"
ARCHIVE_BOSS_TAB = "EventQuestLibrary(Clone)/CanvasBoundsPanel/window/tab/tab_event4"
ROUTES = {
    "title": {"marker": "SRPG_TITLE", "open": None, "back": None,
              "forward": "SRPG_TITLE/2D/CanvasBoundsPanel/UI/Play", "parent": "home"},
    "event list": {"marker": "EventQuestSelector/CanvasBoundsPanel/ChapterList/Bottom/back",
                   "open": [QUEST, "QuestList/default/button2/image",
                            "QuestList/event/button2/image"],
                   "back": "EventQuestSelector/CanvasBoundsPanel/ChapterList/Bottom/back",
                   "parent": "quests: event"},
    "event quests": {"marker": "EventQuestSelector/CanvasBoundsPanel/QuestList/Bottom/back",
                     "open": None,   # an event is opened by the farm (by its id)
                     "back": "QuestList/Bottom/back/back", "parent": "event list"},
    # Boss Battle Quest (Quest > Event > first banner): the box events. Its list's Back goes
    # straight home; each event's page has QUEST (a Normal / Hard map), the boss battles and
    # Event Summon (the box). Events in the list are named by their banner (quest_ev_Advance_x).
    "boss battle list": {"marker": "AdvanceQuestSelector",
                         "open": [QUEST, "QuestList/default/button2/image",
                                  "QuestList/event/button1/image"],
                         "back": "AdvanceQuestSelector(Clone)/Button/back", "parent": "home"},
    "boss battle event": {"marker": "AdvanceQuestEventTop", "open": None,
                          "back": "AdvanceQuestEventTop(Clone)/Button/left/back",
                          "parent": "boss battle list"},
    "boss battle map": {"marker": "AdvanceQuestEventMap", "open": None,
                        "back": "AdvanceQuestEventMap(Clone)/Button/left/back",
                        "parent": "boss battle event"},
    # Event Archives (Quest > Event > 4th button): past events, unlocked for a while (a free
    # unlock or gems - the farm never unlocks). It always opens on Encounter Event, so the route
    # ends on the Boss Battle Quest tab; its events open the same page / map as the list above.
    "archive": {"marker": "EventQuestLibrary",
                "open": [QUEST, "QuestList/default/button2/image",
                         "QuestList/event/button4/image", ARCHIVE_BOSS_TAB],
                "back": "EventQuestLibrary(Clone)/CanvasBoundsPanel/window/button/back",
                "parent": "home"},
    "genesis list": {"marker": "GenesisQuestSelector",
                     "open": [QUEST, "QuestList/default/button1/image",
                              "QuestList/story/list/viewport/content/button3/image"],
                     "back": "GenesisQuestSelector(Clone)/Button/back", "parent": "quests: story"},
    "genesis chapter": {"marker": "GenesisQuestEventTop", "open": None,
                        "back": "GenesisQuestEventTop(Clone)/Button/left/back",
                        "parent": "genesis list"},
    "genesis map": {"marker": "GenesisQuestEventMap", "open": None,
                    "back": "GenesisQuestEventMap(Clone)/Button/left/back",
                    "parent": "genesis chapter"},
    "team": {"marker": "PartyEditor2", "open": None, "back": "@0.062,0.941", "parent": None},
}


def load_map():
    for f in MAP_FILES:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            continue
    else:
        d = {"screens": {}, "dialogs": {}}
    screens = {k: dict(v) for k, v in d.get("screens", {}).items()}
    for k, v in ROUTES.items():
        screens[k] = {**screens.get(k, {}), **v}
    return screens, d.get("dialogs", {})


class Navigator:
    """Uses a farm object for the mod (GenesisFarm / BoxFarm: elements, press, tap, sleep,
    wait_for, dismiss_popup)."""

    def __init__(self, f, log=None):
        self.f = f
        self.log = log or (lambda m: None)
        self.screens, self.dialogs = load_map()
        self.spots = {}   # route step -> where its button ended up the last time it was pressed
        self.off_since = {}   # route step -> since when it's been held still somewhere else

    # ---------- where am I ----------
    def where(self, els=None):
        """The screen showing (the most specific one whose marker is on screen), or None."""
        els = els if els is not None else self.f.elements()
        paths = " ".join(e["path"] for e in els if e.get("top"))
        if not paths:
            paths = " ".join(e["path"] for e in els)
        hits = [k for k, s in self.screens.items() if s.get("marker") and s["marker"] in paths]
        if not hits:
            return None
        # deeper screens first: the longest route, then the longest marker
        depth = lambda k: (len(self.route(k) or []) if self.route(k) is not None else 9,
                           len(self.screens[k]["marker"]))
        return max(hits, key=depth)

    def route(self, screen):
        s = self.screens.get(screen) or {}
        if s.get("open") is not None:
            return list(s["open"])
        parent = s.get("parent")
        if parent and parent != screen:
            up = self.route(parent)
            return None if up is None else up + [f"<{screen}>"]
        return [] if screen == "home" else None

    def dialog(self, els):
        """(name, safe button) of a known dialog on top, or None."""
        for name, d in self.dialogs.items():
            if any(d["marker"] in e["path"] for e in els if e.get("top")):
                btn = next((e for e in els if e.get("top") and e.get("on")
                            and e["path"].endswith(d["safe"])), None)
                return name, btn
        return None

    # ---------- moving ----------
    def press_step(self, step, els=None):
        """Press a route step: a path end, or "@x,y" (a spot). True if pressed."""
        if step.startswith("@"):
            x, y = (float(v) for v in step[1:].split(","))
            self.f.tap((x, y))
            return True
        if els is None:
            # a screen sliding in moves (and grows) its buttons, and some wait a moment before
            # they move: press once it has held still - where it was the last time, if it was
            # pressed before (for a while somewhere else: the layout changed, take that)
            if not self.find_step(step):
                return False
            btn = self.find_step(step, self.f.settled(3.0))
            if not btn:
                return False
            known = self.spots.get(step)
            if known and (abs(btn["x"] - known[0]) > 0.01 or abs(btn["y"] - known[1]) > 0.01):
                since = self.off_since.setdefault(step, time.time())
                if time.time() - since < 2.0:
                    return False
            self.off_since.pop(step, None)
        else:
            btn = self.find_step(step, els)
        if not btn:
            return False
        self.f.press(btn, step)
        self.pressed = (step, btn["x"], btn["y"])
        return True

    def took(self):
        """The last route press worked: remember where its button was."""
        step, x, y = getattr(self, "pressed", (None, 0, 0))
        if step:
            self.spots[step] = (x, y)

    def find_step(self, step, els=None):
        els = els if els is not None else self.f.elements()
        return next((e for e in els if e.get("top") and e.get("on") and e["path"].endswith(step)),
                    None)

    def moved_on(self, here, timeout=4.0):
        """After a press on screen `here`: wait until another screen (or a dialog) shows, then
        a moment for its animation."""
        # (mid-way no screen is known: wait for the next one, not just "another")
        self.f.wait_for(lambda: self.where() not in (here, None), timeout)
        self.f.sleep(0.25)

    def back(self, screen, els):
        """Leave a screen (its Back, or a generic one). True if something was pressed."""
        s = self.screens.get(screen) or {}
        if screen == "title":
            return self.press_step(s["forward"], els)
        if s.get("back") and self.press_step(s["back"], els):
            return True
        for end in ("/back", "/Back", "Btn_Close", "/close", "/btn_close"):
            btn = next((e for e in els if e.get("top") and e.get("on")
                        and e["path"].endswith(end)), None)
            if btn:
                self.f.press(btn, "Back")
                return True
        return False

    def go(self, target, tries=16):
        """Get to the target screen from wherever the game is. RuntimeError if it can't."""
        want = self.route(target)
        if want is None:
            raise RuntimeError(f"no route to {target}")
        unknown = 0
        for turn in range(tries):
            els = self.f.elements()
            d = self.dialog(els)
            if d:
                name, btn = d
                if btn:
                    self.f.press(btn, name)
                    self.f.wait_for(lambda: not self.dialog(self.f.elements()), 3)
                    self.f.sleep(0.25)
                    continue
            if self.f.dismiss_popup(els):
                continue
            here = self.where(els)
            if here == target:
                return here
            if here is None and self.f.wait_for(lambda: self.where() is not None, 1.5):
                continue   # it was between two screens
            if here is None:
                unknown += 1
                if unknown > 3:
                    raise RuntimeError("the game is on a screen the farm doesn't know - "
                                       "go to the home screen and press Start again")
                self.back(None, els)
                self.moved_on(None, 2.5)
                continue
            unknown = 0
            have = self.route(here) or []
            if here == "home" or (have == want[:len(have)] and "<" not in "".join(have)):
                if self.forward(want[len(have):], target):
                    continue
            # a Back pressed while the screen is still coming in is ignored: let it settle
            # (not the screen the game was already on)
            if turn:
                els = self.f.settled(3.0)
                if self.where(els) != here:
                    continue
            if not self.back(here, els):
                raise RuntimeError(f"can't leave {here}")
            self.moved_on(here)
        raise RuntimeError(f"couldn't get to {target}")

    def forward(self, steps, target=None):
        """Press the route's next buttons, each once it shows (and has stopped moving). True if
        any was pressed."""
        pressed = False
        for i, step in enumerate(steps):
            if step.startswith("<"):
                return pressed   # a screen the farm opens itself (an event, a chapter)
            ok = self.f.wait_for(lambda: self.press_step(step), 8)
            if not ok:
                return pressed
            pressed = True
            nxt = steps[i + 1] if i + 1 < len(steps) and not steps[i + 1].startswith("<") else None
            if nxt:   # until the press took: its button gone or the next one up
                for _ in range(3):
                    if self.f.wait_for(lambda: self.find_step(nxt) or not self.find_step(step), 1.0):
                        self.took()
                        break
                    # ignored (its screen was still animating in): press it again
                    if not self.press_step(step):
                        break
            else:     # the last one: until the target shows (its screen can take a while)
                if target:
                    if self.f.wait_for(lambda: self.where() == target, 5):
                        self.took()
                else:
                    self.f.wait_for(lambda: not self.find_step(step), 3)
                self.f.sleep(0.5 if self.find_step(step) else 0.25)   # a tab: its list redraws
        return pressed
