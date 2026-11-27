"""Genesis-style event maps (Genesis chapters, box events): read the stages and their loot, and
find a stage's node on the map - by the game's own data, not fixed screen spots.

An event of this kind opens on a page with QUEST; QUEST shows a map with a Normal / Hard (/ Extra)
switch and one node per stage. The map's node list ("itemsof symbol/list") names every stage
(quest id, title "... - Hard 1", "Hard Stage 1", difficulty, state); a quick probe over the map
finds where each node is (probe hits ".../content(Clone)/top|bottom/icon", inspect names it).

Uses a farm object for the mod (genesis_farm.GenesisFarm or a subclass): send, probe, inspect,
tap, press, sleep, wait_for, elements, texts.
"""
import re
import time

MAP = "QuestEventMap"          # in the map screen's paths (GenesisQuestEventMap)
TOP = "QuestEventTop"          # the event's page with QUEST (GenesisQuestEventTop)
QUEST_BTN_END = "Button/right/quest"
DIFF_END = "difficulty/button1"
POPUP_OK = (0.5, 0.641)
INFO = (0.710, 0.398)          # the stage popup's magnifier
OUTSIDE = (0.12, 0.75)
BANNER = (0.5, 0.15)           # the map's banner with the event's name
NOTICE_OK = (0.5, 0.672)
ATTEMPTS = re.compile(r"(\d+)\s*/\s*(\d+)")
MODE_PIC = {"Normal": "btn_scenario_normal", "Hard": "btn_scenario_hard",
            "Extra": "btn_scenario_extra"}
DIFFICULTY = {"Normal": ("Normal",), "Hard": ("Elite", "Hard"), "Extra": ("Extra",)}
# a name may hold a tag from the game's text: "Ais Wallenstein Soul Shard <br>"
LOOT_RE = re.compile(r"[<,{]iname=([^,>]+),name=((?:[^,<>]|<[^>]*>)*),type=([^,>]+)")
ARCHIVE = "EventQuestLibrary"  # the Event Archives (navigator's "archive")
ARCHIVE_TAB_END = "window/tab/tab_event4"   # its Boss Battle Quest tab
UNLOCK_POPUP = "QuestArchiveOpenPopup"       # its Confirm Unlock dialog
UNLOCK_TITLE = (0.5, 0.245)    # the dialog's title (inspect: the popup's data names the event)
UNLOCK_TEXT = (0.5, 0.40)      # its message: "Unlock ... for 24 hour(s)? / Free once per day! ..."


class Unavailable(RuntimeError):
    """The event can't be opened now: not in its list (ended) or still locked in the archive.
    Waiting won't change that - the box farm skips its quests for this run."""


def norm_name(s):
    return " ".join(s.replace("\xa0", " ").split()).casefold()


def same_event(a, b):
    """Two ids of one event: the archive's unlock dialog says OR_DIE_FROHLICHE or
    OR_ADVANCE_DUNG_01 for the maps ADVANCE_DIE_FROHLICHE and ADVANCE_DUNG_01."""
    core = lambda s: re.sub(r"^(?:OR_)?(?:ADVANCE_)?", "", s or "")
    return bool(a and b) and core(a) == core(b)


def longer_name(full, wanted):
    """The archive may give an event a longer name than the one it was published under: "My
    Funeral, My Trial" for "My Funeral". True if full is a wanted name (2+ words) going on
    after a comma, colon or dash."""
    for w in wanted:
        if " " in w and full.startswith(w) and len(full) > len(w) and full[len(w)] in ",:-~":
            return True
        if " " in w and full.startswith(w + " -"):
            return True
    return False


def event_names(name=None, quests=()):
    """What an event may be called in a list: its name and its stages' titles up to " - "
    ("Qilin & Standing Alone - Hard 1" -> "Qilin & Standing Alone")."""
    out = [name] if name else []
    for q in quests:
        # "Qilin & Standing Alone - Hard 1", "Love Won't Tear Us Apart Again [Hard] (Hard Stage 1)"
        t = re.split(r" - |\s+\[", q.get("title") or "")[0].strip()
        if t and t not in out:
            out.append(t)
    return out


def parse_loot(reply):
    out = []
    for m in LOOT_RE.finditer(reply or ""):
        name = re.sub(r"<[^>]*>", "", m.group(2)).replace("\xa0", " ").strip()   # "<br>" etc.
        item = {"iname": m.group(1), "name": name, "type": m.group(3)}
        if item not in out:
            out.append(item)
    return out


def unique_titles(nodes):
    """A title per node that no other node of the map shares: quests are told apart (and counted
    per day) by title. Boss Battle events call every Hard stage "<event> - Hard", so a repeated
    title gets the stage's own name ("... - Hard (Hard Stage 2)"), or its place if that repeats too."""
    base = [n["title"] or n["name"] or n["iname"] for n in nodes]
    out = []
    for i, n in enumerate(nodes):
        t = base[i]
        if base.count(t) > 1:
            names = [nodes[j]["name"] for j in range(len(nodes)) if base[j] == t]
            t = f"{t} ({n['name']})" if n["name"] and names.count(n["name"]) == 1 else f"{t} #{i + 1}"
        out.append(t)
    return out


class MapScanner:
    def __init__(self, f, log=None):
        self.f = f
        self.log = log or (lambda m: None)
        self.locked = None   # find_entry: a wanted Event Archives entry that's still locked
        self.map_name = None   # scan: the event's name from the map's banner
        # unlock a locked archive event with the day's free unlock (never items): the box farm
        # turns it on from the setting
        self.free_unlock = False
        self.unlock_tried = set()   # names whose Confirm Unlock was already opened this time
        self.unlock_note = ""       # why the last one wasn't unlocked
        self.event = None           # find_entry: the event looked for (its id), for the dialog
        self.by_id = False          # archive_by_id: open locked entries' dialogs to read their id
        self.found_name = None      # open_event: what the Event Archives called the event
        self.others = set()         # entry names whose dialog named another event

    # ---------- where ----------
    def on_map(self):
        return any(MAP in e["path"] for e in self.f.elements() if e["top"])

    def on_top(self):
        return any(TOP in e["path"] for e in self.f.elements() if e["top"])

    def chapter_id(self):
        """The event's id as the map holds it (e.g. GENESIS_09_2), or None."""
        for e in self.f.elements():
            if MAP in e["path"]:
                r = self.f.inspect((e["x"], e["y"]))
                m = re.search(r"QuestEventMap\{[^{}]*?mIname=([A-Za-z0-9_]+)", r) or \
                    re.search(r"mIname=([A-Z][A-Z0-9_]+)", r)
                if m:
                    return m.group(1)
        return None

    def open_map(self):
        """From the event's page, press QUEST and wait for the map. The page's buttons wait a
        moment at a small size, then grow in, and a press before they've grown is ignored: QUEST
        is pressed once it has grown (or has shown for a while), and again if the map hasn't
        come up a moment later - a press that's taken brings the map within ~0.8 s."""
        first = size = None
        pressed = 0.0
        end = time.time() + 20 * self.f.lag
        while time.time() < end:
            els = self.f.elements()
            if any(MAP in e["path"] for e in els if e["top"]):
                self.f.sleep(0.2)
                return True
            btn = next((e for e in els if e["top"] and e["on"]
                        and e["path"].endswith(QUEST_BTN_END)), None)
            now = time.time()
            if btn:
                w = round(btn.get("w") or 0, 3)
                if first is None:
                    first, size = (now, w), None
                grown = w != first[1] and w == size   # changed from its first size, then held
                size = w
                if (grown or now - first[0] > 1.2) and now - pressed > 1.2:
                    self.f.press(btn, "QUEST")
                    pressed = now
            self.f.sleep(0.08)
        return False

    def set_tab(self, tab):
        """Press the map's Normal / Hard / Extra switch until it shows tab. False if it can't."""
        pic = MODE_PIC.get(tab)
        for _ in range(4):
            btn = next((e for e in self.f.elements() if e["path"].endswith(DIFF_END)), None)
            if not btn:
                return False
            pics = self.f.inspect((btn["x"], btn["y"]))
            if pic and pic in pics:
                return True
            if "btn_scenario_" not in pics:
                return False
            self.f.press(btn, "the Normal / Hard switch")
            self.f.wait_for(lambda: self.f.inspect((btn["x"], btn["y"])) != pics, 2.5)
            self.f.sleep(0.3)   # the nodes redraw
        return False

    # ---------- the stages ----------
    def nodes(self, tab=None):
        """[{iname, title, name, difficulty, state}] of the map's stages, in order (only the
        tab's when given)."""
        r = self.f.send("itemsof symbol/list", timeout=15)
        out = []
        for chunk in r.split(" ||| ")[1:]:
            q = re.search(r"mQuestParam<([^>]*)", chunk)
            if not q:
                continue
            fields = dict(re.findall(r"(\w+)=([^,]*)", q.group(1)))
            if not fields.get("iname"):
                continue
            node = {k: fields.get(k, "").replace("\xa0", " ").strip()
                    for k in ("iname", "title", "name", "difficulty")}
            st = re.search(r"mCurrentState=(\w+)", chunk)
            node["state"] = st.group(1) if st else ""
            out.append(node)
        if tab:
            want = DIFFICULTY.get(tab, (tab,))
            out = [n for n in out if n["difficulty"] in want or n["name"].startswith(tab)]
        return out

    def node_spots(self, step=0.03):
        """{quest iname: (x, y)} for the nodes on screen: probe a grid over the map, group the
        node hits, inspect each group's middle to name it."""
        hits = []
        for yi in range(int(0.26 / step), int(0.78 / step) + 1):
            for xi in range(int(0.06 / step), int(0.95 / step) + 1):
                x, y = round(xi * step, 3), round(yi * step, 3)
                r = self.f.probe((x, y))
                if re.search(r"content\(Clone\)/(top|bottom)/(icon|root)", r):
                    hits.append((x, y))
        groups = []
        for p in hits:
            for g in groups:
                if abs(g[0][0] - p[0]) < 0.07 and abs(g[0][1] - p[1]) < 0.09:
                    g.append(p)
                    break
            else:
                groups.append([p])
        spots = {}
        for g in groups:
            x = sum(p[0] for p in g) / len(g)
            y = sum(p[1] for p in g) / len(g)
            for px, py in [(x, y)] + g[:3]:
                m = re.search(r"iname=(QE_[A-Za-z0-9_]+|[A-Z][A-Z0-9_]*QE[A-Z0-9_]*)",
                              self.f.inspect((px, py)))
                if m:
                    spots.setdefault(m.group(1), (round(px, 4), round(py, 4)))
                    break
        return spots

    def popup_title(self):
        return " ".join(self.f.texts(self.f.inspect((0.40, 0.40))))

    def popup_attempts(self):
        """(used, max) from the stage popup's "Attempts 0/3", or None (asked a few times: the
        popup fills its labels a moment after it shows)."""
        for _ in range(4):
            got = self._attempts()
            if got:
                return got
            self.f.sleep(0.25)
        return None

    def _attempts(self):
        for p in ((0.70, 0.474), (0.693, 0.474), (0.72, 0.474)):
            m = ATTEMPTS.search(" ".join(self.f.texts(self.f.inspect(p))))
            if m:
                return int(m.group(1)), int(m.group(2))
        used = re.findall(r"\d+", " ".join(self.f.texts(self.f.inspect((0.693, 0.474)))))
        most = re.findall(r"\d+", " ".join(self.f.texts(self.f.inspect((0.72, 0.474)))))
        return (int(used[0]), int(most[0])) if used and most else None

    def open_stage(self, node, spot, wait=8):
        """Tap a node; True once the stage popup naming it is up (within `wait` s). Brackets
        don't count: the popup's text comes back without its closing "]" ("... [Hard" for
        "... [Hard]")."""
        self.f.tap(spot)
        want = node["name"].split()[-1] if node.get("name") else ""
        flat = lambda s: " ".join(re.sub(r"[\[\]]", " ", s or "").split())
        # a repeated title got the stage's name added by the scan ("... - Hard (Hard Stage 2)"):
        # the popup shows the game's own title
        base = re.sub(r"\s+(\([^()]*\)|#\d+)$", "", node.get("title") or "")

        def up():
            title = self.popup_title()
            return ((base and flat(base) in flat(title)) or
                    (want and re.search(rf"\b{re.escape(want)}\s*$", title)))
        return bool(self.f.wait_for(up, wait))

    def popup_up(self):
        here = self.f.probe(OUTSIDE)
        return any(k in here for k in ("QuestConfirm", "QuestDetail", "Win_Btn_Decide"))

    def close_popups(self):
        for _ in range(5):
            if not self.popup_up():
                return True
            if "Win_Btn_Decide" in self.f.probe(NOTICE_OK):
                self.f.tap(NOTICE_OK)
            else:
                self.f.tap(OUTSIDE)
            # until it's gone (a second popup under it is closed next round)
            before = self.f.probe(OUTSIDE)
            self.f.wait_for(lambda: self.f.probe(OUTSIDE) != before or not self.popup_up(), 2.0)
            self.f.sleep(0.2)
        return not self.popup_up()

    def read_loot(self):
        """With the stage popup up: the magnifier (Quest Details), its Loot, then close."""
        opened = False
        for _ in range(4):
            self.f.sleep(0.8)
            if "QuestDetail" in self.f.probe(OUTSIDE):
                opened = True
                break
            self.f.tap(INFO)
            if self.f.wait_for(lambda: "QuestDetail" in self.f.probe(OUTSIDE), 4):
                opened = True
                break
        if not opened:
            return []
        self.f.sleep(0.8)
        self.f.send("scroll 0.5 0.5 0")
        self.f.sleep(1.0)
        loot = []
        for _ in range(3):
            loot = parse_loot(self.f.send("itemsof droplist", timeout=12))
            if loot:
                break
            self.f.sleep(1.0)
        return loot

    def banner_name(self):
        """The event's name from the map's banner ("Scavengers of Time and Space" over "HARD"),
        or None. Stage titles name the event in different ways ("X - Hard 1", "X [Hard]",
        "X Hard Stage 1"); the banner is the name the lists show."""
        for t in self.f.texts(self.f.inspect(BANNER)):
            if t.strip() and t.strip().upper() not in ("NORMAL", "HARD", "EXTRA", "EX"):
                return t.strip()
        return None

    # ---------- a whole map ----------
    def scan(self, tab="Hard", progress=None):
        """Every stage of the open map's tab: title, attempts, loot. Presses only the nodes, the
        magnifier and empty spots (never OK), so nothing is spent."""
        if not self.on_map() and not (self.on_top() and self.open_map()):
            raise RuntimeError("open a box event's map (its QUEST) in the game first")
        if tab and not self.set_tab(tab):
            if not any(e["path"].endswith(DIFF_END) for e in self.f.elements()):
                # no Normal / Hard switch at all: the game shows it once Normal is cleared
                raise RuntimeError(f"{tab} isn't open on this map yet - clear its Normal stages in "
                                   "the game first (or pick Normal to scan those)")
            raise RuntimeError(f"this map has no {tab} switch")
        self.f.sleep(1.0)
        event = self.chapter_id()
        self.map_name = self.banner_name()
        nodes = self.nodes(tab)
        if not nodes:
            raise RuntimeError("couldn't read the map's stages")
        spots = self.node_spots()
        titles = unique_titles(nodes)
        out = []
        for i, n in enumerate(nodes, 1):
            if progress:
                progress(f"{i}/{len(nodes)} {titles[i - 1]}")
            q = {"title": titles[i - 1], "name": n["name"], "iname": n["iname"],
                 "tab": tab, "kind": "map", "loot": []}
            spot = spots.get(n["iname"])
            opened = bool(spot) and self.open_stage(n, spot)
            if not opened:   # the map may have moved under the popups: look again, once
                self.close_popups()
                spots = self.node_spots()
                spot = spots.get(n["iname"])
                opened = bool(spot) and self.open_stage(n, spot)
            if not spot:
                q["error"] = "node not found on the map (scrolled off?)"
                out.append(q)
                continue
            q["spot"] = list(spot)
            if not opened:
                q["error"] = "stage popup didn't open"
                self.close_popups()
                out.append(q)
                continue
            att = self.popup_attempts()
            if att:
                q["max"] = att[1]
            q["loot"] = self.read_loot()
            if not q["loot"]:
                q["error"] = "no loot read"
            self.close_popups()
            out.append(q)
        return event, out

    # ---------- where it lives ----------
    def learn_origin(self, event, nav, names=()):
        """From the event's map or page, go Back to the list it was opened from and find its
        entry there (names: see open_event - the Event Archives know events only by name).
        Returns {"list": screen name (navigator), "name": the event's name}."""
        self.close_popups()
        for _ in range(4):
            if not (self.on_map() or self.on_top()):
                break
            here = nav.where()
            if not nav.back(here, self.f.elements()):
                break
            self.f.sleep(2.0)
        # the list animates in (and loads its banners) after Back: wait for it, as open_event does
        here = self.f.wait_for(lambda: nav.where(), 10)
        entry = self.f.wait_for(lambda: self.find_entry(event, names), 10) if event else None
        name = None
        if entry:
            m = re.search(r"mName=([^,>]+)", self.f.inspect((entry["x"], entry["y"])))
            name = m.group(1).strip() if m else entry.get("archive_name")
        elif event and here == "archive":
            # the archive may call it something else than its map ("DanMachi Advance" for "The
            # Code of the Heroic Tale"): open the unlocked entries until one is this event
            name = self.archive_name_by_id(event, nav)
            entry = bool(name)
        return {"list": here, "found": bool(entry), "name": name}

    def archive_rows(self, els=None):
        """[(name, node, open button or None, unlock button or None)] of the Event Archives
        rows in view. By name, not by Node_n: the list hands its slots to other entries as it
        scrolls, and a slot just handed over can still show the last entry's button a moment."""
        els = els if els is not None else \
            [e for e in self.f.elements() if e["top"] and "/viewport/list/" in e["path"]]
        out = []
        for info in els:
            node = re.search(r"/(Node_\d+)/btn_information$", info["path"])
            if not node or not 0.15 < info["y"] < 0.93:   # the last row sits low
                continue
            texts = re.findall(r"text:(.*?)(?=, text:|\])", self.f.inspect((0.45, info["y"])))
            if not texts:
                continue
            mine = [e for e in els if e["on"] and f"/{node.group(1)}/" in e["path"]]
            opened = next((e for e in mine if e["path"].endswith("/btn_opened")), None)
            lock = next((e for e in mine if e["path"].endswith("/btn_open")), None)
            if opened or lock:
                out.append((texts[0].strip(), node.group(1), opened, lock))
        return out

    def archive_entries(self):
        """[(name, locked)] of every Event Archives entry (scrolls the list, presses nothing).
        Each row is seen on several scroll steps: the state seen most wins (see archive_rows)."""
        votes = {}
        lists = [e for e in self.f.elements() if e["top"] and e["on"] and "/viewport/list/" in e["path"]]
        if not lists:
            return []
        anchor = lists[0]
        for step in range(16):
            self.f.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {1 - step / 15}")
            self.f.sleep(0.6)
            for name, _, opened, _ in self.archive_rows():
                votes.setdefault(name, []).append(not opened)
        return [(n, v.count(True) > v.count(False)) for n, v in votes.items()]

    def archive_name_by_id(self, event, nav):
        """With the Event Archives open: the name of the unlocked entry whose map is this event
        (opens each one's map and comes back - nothing is spent), or None."""
        for name, locked in self.archive_entries():
            if locked:
                continue
            self.log(f"  is it {name}?")
            entry = self.f.wait_for(lambda: self.find_entry(event, [name]), 10)
            if not entry:
                continue
            self.f.press(entry, name)
            cid = None
            if self.f.wait_for(lambda: self.on_top() or self.on_map(), 15) and self.open_map():
                self.f.sleep(1.0)
                cid = self.chapter_id()
            for _ in range(4):   # back to the archive
                if not (self.on_map() or self.on_top()):
                    break
                if not nav.back(nav.where(), self.f.elements()):
                    break
                self.f.sleep(2.0)
            self.f.wait_for(lambda: nav.where() == "archive", 10)
            if cid == event:
                return name
        return None

    def archive_by_id(self, event, nav):
        """With the Event Archives open, for an event its names didn't find (the archive calls
        DanMachi's "The Code of the Heroic Tale" "DanMachi Advance"): a locked entry's Confirm
        Unlock dialog names the event's id, so each locked entry's dialog is opened and
        cancelled unless it's this event (then it's unlocked if that's free, as by name); the
        unlocked entries are told apart by their map's id. Returns the entry's open button (with
        "archive_name"), or None (self.locked = its name if it's there but stays locked)."""
        self.log(f"  {event}: not under its name in the Event Archives - looking for it by id")
        self.event, self.by_id = event, True
        lists = [e for e in self.f.elements() if e["top"] and e["on"] and "/viewport/list/" in e["path"]]
        if not lists:
            return None
        anchor, opened = lists[0], set()
        try:
            # one pass down the list: each locked entry's dialog, read and cancelled
            for step in range(16):
                self.f.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {1 - step / 15}")
                self.f.sleep(0.6)
                again = True
                while again:   # after a dialog the rows are read afresh
                    again = False
                    for name, node, btn, lock in self.archive_rows():
                        if btn:
                            opened.add(name)
                        if not lock or btn or lock["y"] >= 0.97 or name in self.unlock_tried \
                                or name in self.others:
                            continue
                        got = self.unlock_free(lock, name, node)
                        if got == "unlocked":
                            btn = self.f.wait_for(lambda: self.opened_button(node), 10)
                            return {**btn, "archive_name": name} if btn else None
                        if got == "locked":   # this event, still locked
                            self.locked = name
                            return None
                        self.others.add(name)
                        again = True
                        # closing a dialog can move the list: put it back before reading again
                        self.f.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {1 - step / 15}")
                        self.f.sleep(0.6)
                        break
        finally:
            self.by_id = False
        # the unlocked entries: their map says which event they are
        if opened:
            name = self.archive_name_by_id(event, nav)
            if name:
                return self.f.wait_for(lambda: self.find_entry(event, [name], tab=False), 10)
        return None

    def open_event(self, event, list_screen, nav, names=()):
        """Get to the event's map from anywhere: the menu map to its list, its entry, QUEST.
        A Boss Battle event that has left its list is looked for in the Event Archives too
        (by name: names = the event's name and its stages' "<event> - Hard 1" titles)."""
        if self.on_map() and self.chapter_id() == event:
            return True
        self.unlock_tried, self.unlock_note, self.found_name = set(), "", None
        self.others = set()
        lists = [list_screen]
        if names and list_screen == "boss battle list":
            lists.append("archive")
        entry = None
        for screen in lists:
            nav.go(screen)
            # the list's entries first, then a look through it (twice: it may still be filling)
            self.f.wait_for(lambda: any(e["top"] and "/viewport/list/" in e["path"]
                                        for e in self.f.elements()), 8)
            for tries in range(2):
                # the route ends on the archive's Boss Battle Quest tab: it's pressed again
                # only for the second look (the game was left on another tab)
                entry = self.find_entry(event, names, tab=tries > 0)
                if entry or self.locked:
                    break
            if entry:
                break
        if not entry and lists[-1] == "archive" and not self.locked:
            entry = self.archive_by_id(event, nav)
        if not entry:
            if self.locked:
                raise Unavailable(f"{self.locked} is locked in the Event Archives - unlock it in "
                                  "the game first"
                                  + (f" ({self.unlock_note})" if self.unlock_note else ""))
            raise Unavailable(f"{event} isn't in the {' or '.join(lists)} (has the event ended?)")
        self.found_name = entry.get("archive_name")
        self.f.press(entry, event)
        if not self.f.wait_for(lambda: self.on_top() or self.on_map(), 15):
            raise RuntimeError(f"{event}: its page didn't open")
        # the page animates in and may ignore an early press: open_map retries
        if not self.open_map():
            raise RuntimeError(f"{event}: its map didn't open")
        return True
    def find_entry(self, event, names=(), tab=True):
        """On a list screen: the entry whose game data names the event, scrolled into view.
        The Event Archives' entries don't carry the event's id, only its name: there the entry
        is found by name (names) and its open button returned, with "archive_name" added. A
        locked one (still to unlock) is never pressed: it's noted in self.locked instead."""
        self.locked = None
        self.event = event if event and event != "?" else None
        els = self.f.elements()
        archive = any(ARCHIVE in e["path"] for e in els if e["top"])
        if archive and tab:
            tab = next((e for e in els if e["top"] and e["path"].endswith(ARCHIVE_TAB_END)), None)
            if tab:
                self.f.press(tab, "Boss Battle Quest")   # it may be on another tab
                self.f.sleep(0.5)
        wanted = {norm_name(n) for n in names if n}
        lists = [e for e in self.f.elements() if e["top"] and e["on"]
                 and "/viewport/list/" in e["path"]]
        if not lists or (archive and not wanted):
            return None
        anchor = lists[0]
        steps = 16 if archive else 11
        for step in range(steps):
            self.f.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {1 - step / (steps - 1)}")
            self.f.sleep(0.25)
            els = [e for e in self.f.elements() if e["top"] and "/viewport/list/" in e["path"]]
            if archive:
                hit = self.archive_entry(els, wanted)
                if hit:
                    return hit
                if self.locked:
                    return None
                continue
            for e in els:
                if e["on"] and 0.2 < e["y"] < 0.9 and event in self.f.inspect((e["x"], e["y"])):
                    return e
        return None

    def opened_button(self, node):
        return next((e for e in self.f.elements() if e["top"] and e["on"]
                     and e["path"].endswith(f"/{node}/btn_opened")), None)

    def unlock_free(self, lock, name, node):
        """Press a locked archive entry's unlock button and read its Confirm Unlock: the event
        it's for (mChapter<iname=OR_<event id>,name=...>) and its cost. OK only if it's the event
        looked for (self.event: its id, else the name), free unlocks are on and the dialog says
        it's free ("Free once per day!") with nothing "Owned" (the item cost once the day's free
        unlocks are used). Else Cancel. Returns "unlocked", "other" (another event's entry) or
        "locked". (The dialog's second line needs TAC Auto Tap 1.3.1+: with an older mod the
        free line can't be read, so nothing is unlocked.)"""
        def popup_btn(end):
            return next((e for e in self.f.elements() if e["top"] and e["on"]
                         and UNLOCK_POPUP in e["path"] and e["path"].endswith(end)), None)
        self.unlock_tried.add(name)
        self.f.press(lock, f"unlock {name}?" if self.free_unlock else f"is {name} it?")
        if not self.f.wait_for(lambda: popup_btn("/btn_ok"), 6):
            return "locked"
        self.f.sleep(0.6)
        about = self.f.inspect(UNLOCK_TITLE)
        m = re.search(r"mChapter<[^<>]*?,name=(.*?),expr=", about)
        iname = re.search(r"mChapter<(?:[^<>]*?,)?iname=([^,<>]+)", about)
        iname = iname.group(1) if iname else ""
        text = re.search(r"mCurrentText=(.*?)\}", self.f.inspect(UNLOCK_TEXT))
        text = (text.group(1) if text else "").lower()
        whole = " / " in text and not text.endswith("...")   # older mods cut it short
        if self.event and iname:
            ours = same_event(iname, self.event)
        else:
            ours = bool(m) and norm_name(m.group(1)) == norm_name(name)
        free = ours and self.free_unlock and whole and \
            "free once per day" in text and "owned" not in text
        btn = popup_btn("/btn_ok" if free else "/btn_cancel")
        if not btn:
            return "locked"
        self.f.press(btn, "OK - free unlock" if free else "Cancel")
        if not free:
            self.f.wait_for(lambda: not popup_btn("/btn_cancel"), 5)
            if not ours:
                return "other"
            self.unlock_note = ("free unlocks are off on the Dev page" if not self.free_unlock else
                                "the mod can't read the unlock's cost - update TACMonkey (TAC "
                                "Auto Tap 1.3.1)" if not whole else
                                "today's free unlocks are used up; the farm never spends items")
            self.log(f"{name}: {self.unlock_note} - not unlocked")
            return "locked"
        self.log(f"Unlocked {name} with today's free unlock (24 hours)")
        # the game says it's open: its OK (a game notice) closes it
        for _ in range(10):
            self.f.sleep(1.0)
            els = self.f.elements()
            if any(e["top"] and e["path"].endswith(f"/{node}/btn_opened") for e in els):
                return "unlocked"
            ok = next((e for e in els if e["top"] and e["on"] and
                       ("Win_Btn_Decide" in e["path"] or e["path"].endswith("/btn_ok"))), None)
            if ok:
                self.f.press(ok, "OK")
        return "unlocked"

    def archive_entry(self, els, wanted):
        """An Event Archives entry in view whose name is wanted: its open button (Node_n/btn_opened),
        or None (and self.locked = its name if it's there but locked: Node_n/btn_open)."""
        for info in els:
            # the last entry's row sits low even with the list at its end
            if not info["path"].endswith("/btn_information") or not 0.15 < info["y"] < 0.93:
                continue
            node = re.search(r"/(Node_\d+)/", info["path"])
            # the name sits on the magnifier's row, left of it
            texts = re.findall(r"text:(.*?)(?=, text:|\])", self.f.inspect((0.45, info["y"])))
            name = next((t.strip() for t in texts if norm_name(t) in wanted), None) or                 next((t.strip() for t in texts if longer_name(norm_name(t), wanted)), None)
            if not node or not name or name in self.others:
                continue
            mine = [e for e in els if f"/{node.group(1)}/" in e["path"]]
            btn = next((e for e in mine if e["on"] and e["path"].endswith("/btn_opened")), None)
            if btn and btn["y"] < 0.97:
                return {**btn, "archive_name": name}
            lock = next((e for e in mine if e["on"] and e["path"].endswith("/btn_open")), None)
            if lock:
                got = "locked"
                if (self.free_unlock or self.by_id) and lock["y"] < 0.97 \
                        and name not in self.unlock_tried:
                    got = self.unlock_free(lock, name, node.group(1))
                if got == "unlocked":
                    btn = self.f.wait_for(lambda: self.opened_button(node.group(1)), 10)
                    if btn:
                        return {**btn, "archive_name": name}
                if got == "other":   # same name, another event: keep looking
                    self.others.add(name)
                    continue
                self.locked = name
                return None
            # its button is below the view: the next scroll step brings it up
        return None
