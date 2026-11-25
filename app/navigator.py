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
        els = els if els is not None else self.f.elements()
        btn = next((e for e in els if e.get("top") and e.get("on") and e["path"].endswith(step)),
                   None)
        if not btn:
            return False
        self.f.press(btn, step)
        return True

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
        for _ in range(tries):
            els = self.f.elements()
            d = self.dialog(els)
            if d:
                name, btn = d
                if btn:
                    self.f.press(btn, name)
                    self.f.sleep(1.2)
                    continue
            if self.f.dismiss_popup(els):
                continue
            here = self.where(els)
            if here == target:
                return here
            if here is None:
                unknown += 1
                if unknown > 3:
                    raise RuntimeError("the game is on a screen the farm doesn't know - "
                                       "go to the home screen and press Start again")
                self.back(None, els)
                self.f.sleep(2.0)
                continue
            unknown = 0
            have = self.route(here) or []
            if here == "home" or (have == want[:len(have)] and "<" not in "".join(have)):
                if self.forward(want[len(have):]):
                    continue
            if not self.back(here, els):
                raise RuntimeError(f"can't leave {here}")
            self.f.sleep(2.0)
        raise RuntimeError(f"couldn't get to {target}")

    def forward(self, steps):
        """Press the route's next buttons, each once it shows. True if any was pressed."""
        pressed = False
        for step in steps:
            if step.startswith("<"):
                return pressed   # a screen the farm opens itself (an event, a chapter)
            ok = self.f.wait_for(lambda: self.press_step(step), 8)
            if not ok:
                return pressed
            pressed = True
            self.f.sleep(2.0)
        return pressed
