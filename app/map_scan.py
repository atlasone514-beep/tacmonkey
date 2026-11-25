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

MAP = "QuestEventMap"          # in the map screen's paths (GenesisQuestEventMap)
TOP = "QuestEventTop"          # the event's page with QUEST (GenesisQuestEventTop)
QUEST_BTN_END = "Button/right/quest"
DIFF_END = "difficulty/button1"
POPUP_OK = (0.5, 0.641)
INFO = (0.710, 0.398)          # the stage popup's magnifier
OUTSIDE = (0.12, 0.75)
NOTICE_OK = (0.5, 0.672)
ATTEMPTS = re.compile(r"(\d+)\s*/\s*(\d+)")
MODE_PIC = {"Normal": "btn_scenario_normal", "Hard": "btn_scenario_hard",
            "Extra": "btn_scenario_extra"}
DIFFICULTY = {"Normal": ("Normal",), "Hard": ("Elite", "Hard"), "Extra": ("Extra",)}
LOOT_RE = re.compile(r"[<,{]iname=([^,>]+),name=([^,>]+),type=([^,>]+)")


def parse_loot(reply):
    out = []
    for m in LOOT_RE.finditer(reply or ""):
        item = {"iname": m.group(1), "name": m.group(2).replace("\xa0", " ").strip(),
                "type": m.group(3)}
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
        """From the event's page, press QUEST and wait for the map."""
        for _ in range(6):
            if self.on_map():
                return True
            btn = next((e for e in self.f.elements() if e["top"] and e["on"]
                        and e["path"].endswith(QUEST_BTN_END)), None)
            if btn:
                self.f.press(btn, "QUEST")
            if self.f.wait_for(self.on_map, 6):
                return True
            self.f.sleep(1.0)
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
            self.f.sleep(1.5)
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
            self.f.sleep(0.6)
        return None

    def _attempts(self):
        for p in ((0.70, 0.474), (0.693, 0.474), (0.72, 0.474)):
            m = ATTEMPTS.search(" ".join(self.f.texts(self.f.inspect(p))))
            if m:
                return int(m.group(1)), int(m.group(2))
        used = re.findall(r"\d+", " ".join(self.f.texts(self.f.inspect((0.693, 0.474)))))
        most = re.findall(r"\d+", " ".join(self.f.texts(self.f.inspect((0.72, 0.474)))))
        return (int(used[0]), int(most[0])) if used and most else None

    def open_stage(self, node, spot):
        """Tap a node; True once the stage popup naming it is up."""
        self.f.tap(spot)
        want = node["name"].split()[-1] if node.get("name") else ""
        return bool(self.f.wait_for(
            lambda: (node["title"] and node["title"] in self.popup_title()) or
            (want and re.search(rf"\b{want}\s*$", self.popup_title())), 8))

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
            self.f.sleep(1.2)
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

    # ---------- a whole map ----------
    def scan(self, tab="Hard", progress=None):
        """Every stage of the open map's tab: title, attempts, loot. Presses only the nodes, the
        magnifier and empty spots (never OK), so nothing is spent."""
        if not self.on_map() and not (self.on_top() and self.open_map()):
            raise RuntimeError("open a box event's map (its QUEST) in the game first")
        if tab and not self.set_tab(tab):
            raise RuntimeError(f"this map has no {tab} switch")
        self.f.sleep(1.0)
        event = self.chapter_id()
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
            if not spot:
                q["error"] = "node not found on the map (scrolled off?)"
                out.append(q)
                continue
            q["spot"] = list(spot)
            if not self.open_stage(n, spot):
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
    def learn_origin(self, event, nav):
        """From the event's map or page, go Back to the list it was opened from and find its
        entry there. Returns {"list": screen name (navigator), "name": the event's name}."""
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
        entry = self.f.wait_for(lambda: self.find_entry(event), 10) if event else None
        name = None
        if entry:
            m = re.search(r"mName=([^,>]+)", self.f.inspect((entry["x"], entry["y"])))
            name = m.group(1).strip() if m else None
        return {"list": here, "found": bool(entry), "name": name}

    def open_event(self, event, list_screen, nav):
        """Get to the event's map from anywhere: the menu map to its list, its entry, QUEST."""
        if self.on_map() and self.chapter_id() == event:
            return True
        nav.go(list_screen)
        entry = self.f.wait_for(lambda: self.find_entry(event), 10)
        if not entry:
            raise RuntimeError(f"{event} isn't in the {list_screen} (has the event ended?)")
        self.f.press(entry, event)
        if not self.f.wait_for(lambda: self.on_top() or self.on_map(), 15):
            raise RuntimeError(f"{event}: its page didn't open")
        # the page animates in and may ignore an early press: open_map retries
        if not self.open_map():
            raise RuntimeError(f"{event}: its map didn't open")
        return True
    def find_entry(self, event):
        """On a list screen: the entry whose game data names the event, scrolled into view."""
        lists = [e for e in self.f.elements() if e["top"] and e["on"]
                 and "/viewport/list/" in e["path"]]
        if not lists:
            return None
        anchor = lists[0]
        for step in range(11):
            self.f.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {1 - step / 10}")
            self.f.sleep(0.6)
            for e in self.f.elements():
                if e["top"] and e["on"] and "/viewport/list/" in e["path"] and \
                        0.2 < e["y"] < 0.9 and event in self.f.inspect((e["x"], e["y"])):
                    return e
        return None
