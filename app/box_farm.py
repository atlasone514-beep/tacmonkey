"""Box event farm: skip-ticket the box event quests that drop the units you pick.

The events and their quests come from the live data (live_data.py: published from the Dev page,
downloaded by every TACMonkey). Needs the TAC Auto Tap mod; everything is pressed and read
through it. For each quest that drops a picked unit, not done yet today:
    Quest > Event list -> the event -> (its tab, e.g. Hard) -> the quest row -> team screen
    -> skip (as many as attempts are left) -> rewards -> back to the event's quest list
The skip, AP refill, popups, grace period and pause work as in the Genesis farm.

Daily counter: quests done today are remembered (box_done.json) until the game's reset at 00:00
GMT, so after a stop the farm goes straight to the ones left. The quest row's own "used / max"
is read before anything is pressed, so quests played by hand count too and nothing is spent twice.
"""
import datetime
import json
import re
import time

import farm
import genesis_farm
import live_data
import event_scan
import map_scan
from event_scan import EventScanner, clean, parse_quest_text, QUEST_LIST, EVENT_SCREEN

DONE_FILE = farm.APP_DIR / "box_done.json"


# ---------- daily counter ----------
def game_day(now=None):
    """The game's day: it changes at 00:00 GMT, whatever the PC's time zone."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%d")


def until_reset(now=None):
    """Seconds until the next 00:00 GMT."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((nxt - now).total_seconds())


def quest_key(event, q):
    return f"{event}|{q.get('tab') or ''}|{q['title']}"


class DayCounter:
    """{quest key: {"used": n, "max": m}} for today; empty again after the reset."""

    def __init__(self, path=DONE_FILE):
        self.path = path
        self.day, self.done = game_day(), {}
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("day") == self.day and isinstance(d.get("done"), dict):
                self.done = {k: v for k, v in d["done"].items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass

    def roll(self):
        if game_day() != self.day:
            self.day, self.done = game_day(), {}

    def save(self):
        try:
            self.path.write_text(json.dumps({"day": self.day, "done": self.done}, indent=1,
                                            ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def note(self, key, used, most):
        self.roll()
        self.done[key] = {"used": int(used), "max": int(most)}
        self.save()

    def left(self, key, most):
        """Attempts left today as far as we know (most if never seen today)."""
        self.roll()
        d = self.done.get(key)
        if not d:
            return most
        return max(0, int(d.get("max", most)) - int(d.get("used", 0)))

    def finished(self, key, most):
        return self.left(key, most) <= 0


# ---------- what to farm ----------
def plan(data, units, counts=None):
    """[(event id, quest)] for the picked units, each unit's first counts[unit] quests (all if
    no count), a quest shared by units once, in the live file's order (event by event)."""
    by_unit = live_data.units(data)
    wanted = set()
    for u in units:
        qs = by_unit.get(u, [])
        n = (counts or {}).get(u)
        if isinstance(n, int) and 0 < n < len(qs):
            qs = qs[:n]
        wanted |= {(q["event"], q.get("tab"), q["title"]) for q in qs}
    out = []
    for eid, ev in data["events"].items():
        for q in ev["quests"]:
            if (eid, q.get("tab"), q["title"]) in wanted:
                out.append((eid, q))
    return out


def left_today(data, counter, eid, quests=None):
    """(quests left today, quests in all) for an event (or just the given quests)."""
    qs = quests if quests is not None else data["events"][eid]["quests"]
    left = sum(1 for q in qs if not counter.finished(quest_key(eid, q), q.get("max") or 1))
    return left, len(qs)


class BoxFarm(genesis_farm.GenesisFarm):
    def __init__(self, data=None, counter=None, **kw):
        super().__init__(mode="hard", **kw)
        self.label = "Box"
        self.data = data or live_data.load()
        self.counter = counter or DayCounter()
        self.nav = EventScanner(log=self.log, stop=self.stop)
        self.mapper = map_scan.MapScanner(self, log=self.log)   # Genesis-style event maps
        self.here = None   # (event id, tab) whose quest list / map is open
        self.spots = {}    # quest id -> node spot on the open map

    # ---------- finding the quest ----------
    def open_quest_list(self, eid, tab):
        if self.here == (eid, tab) and self.nav.on_quest_list():
            return
        self.here = None
        self.go_event_list()
        self.nav.open_event(eid)
        if tab:
            self.switch_tab(tab)
        self.here = (eid, tab)

    def go_event_list(self):
        """To Quest > Event from any screen the menu map knows (navigator.py); if that fails,
        the old way (team screen, a popup, the quest list or home)."""
        if self.nav.on_event_list():
            return
        try:
            self.navigator.go("event list")
            if self.wait_for(self.nav.on_event_list, 6):
                return
        except RuntimeError as e:
            self.log(f"  (menu map: {e} - trying the usual way)")
        for _ in range(10):
            if self.nav.on_event_list():
                return
            if self.on_team():
                self.tap(genesis_farm.TEAM_BACK)
            elif self.nav.on_quest_list() or self.nav.detail_open():
                self.nav.back_to_event_list()
                continue
            elif "quest/event" in self.probe(genesis_farm.HOME_QUEST):
                self.tap(genesis_farm.HOME_QUEST)
                self.sleep(4)
                ev = self.find(path_end="OtherQuest/EventQuest")
                if ev:
                    self.press(ev)
            else:
                self.close_popups()
                ev = self.find(path_end="OtherQuest/EventQuest")
                if ev:
                    self.press(ev)
            self.sleep(2.5)
        raise RuntimeError("couldn't reach the Event quest list - start from the home screen "
                           "or Quest > Event")

    def switch_tab(self, tab):
        """Press the event screen's button labelled like the tab (e.g. "Hard")."""
        for _ in range(3):
            btn = next((e for e in self.elements() if e["top"] and e["on"]
                        and EVENT_SCREEN in e["path"] and QUEST_LIST + "/contents" not in e["path"]
                        and clean(e["text"]).lower() == tab.lower()), None)
            if not btn:
                return   # no such button: the list is probably already the right one
            self.press(btn, f"the {tab} tab")
            self.sleep(1.5)
            return

    def find_row(self, title):
        """(row element, parsed text) of the quest row with that title, scrolled into view."""
        for step in range(21):
            self.nav.scroll_list(QUEST_LIST, 1 - step / 20)
            for r, _ in self.nav.visible_quests():
                info = parse_quest_text(r["text"])
                if info.get("title") == title and 0.2 < r["y"] < 0.88:
                    return r, info
        return None, None

    # ---------- one quest ----------
    def farm_quest(self, eid, q):
        if q.get("kind") == "map":
            return self.farm_map_quest(eid, q)
        key = quest_key(eid, q)
        name = q["title"] + (f" ({q['tab']})" if q.get("tab") else "")
        self.open_quest_list(eid, q.get("tab"))
        row, info = self.find_row(q["title"])
        if not row:
            raise RuntimeError(f"{name}: not in the event's quest list")
        most = info.get("max") or q.get("max") or 1
        used = info.get("used", 0)
        if used >= most:
            self.counter.note(key, used, most)
            self.log(f"  {name}: {used}/{most} done today - skipped")
            return
        self.skips = most - used
        self.press(row, name)
        # the team screen, maybe after a confirm popup with OK
        for _ in range(int(12 * self.lag)):
            self.sleep(1.0)
            if self.on_team():
                break
            ok = self.find_ok()
            if ok:
                self.press(ok)
                continue
            self.dismiss_popup()
        else:
            raise RuntimeError(f"{name}: team screen didn't open")
        self.sleep(1.0)
        got, skipped = self.skip_stage(name)
        if skipped:
            self.counter.note(key, most, most)
            txt = ", ".join(f"{u} x{n}" for u, n in got.items()) or "no shards this time"
            self.log(f"  {name}: done - {txt}")
            for u, n in got.items():
                self.shards[u] = self.shards.get(u, 0) + n
            self.on_shards(dict(self.shards))
            self.status(f"{name} done - {self.shard_summary()}")
        else:
            self.log(f"  {name}: can't skip - no attempt left, or not cleared by hand yet")
            self.counter.note(key, most, most)
        self.tap(genesis_farm.TEAM_BACK)
        if not self.wait_for(lambda: self.nav.on_quest_list() or self.on_team(), 15):
            self.close_popups()
        if self.on_team():
            self.tap(genesis_farm.TEAM_BACK)
            self.wait_for(self.nav.on_quest_list, 10)

    def farm_map_quest(self, eid, q):
        """A stage of a Genesis-style event: its map (opened through the list it was scanned
        in), its node, the popup's attempts, OK, skip, back to the map."""
        ev = self.data["events"][eid]
        key, name, ms = quest_key(eid, q), q["title"], self.mapper
        if self.here != (eid, q.get("tab")) or not ms.on_map():
            self.here = None
            ms.open_event(ev.get("chapter") or eid, ev.get("list") or "event list",
                          self.navigator)
            if q.get("tab") and not ms.set_tab(q["tab"]):
                raise RuntimeError(f"{name}: couldn't switch the map to {q['tab']}")
            self.sleep(1.0)
            self.spots = ms.node_spots()
            self.here = (eid, q.get("tab"))
        node = {"iname": q.get("iname", ""), "title": q["title"], "name": q.get("name", "")}
        spot = self.spots.get(node["iname"]) or (tuple(q["spot"]) if q.get("spot") else None)
        if not spot or not ms.open_stage(node, spot):
            ms.close_popups()
            self.spots = ms.node_spots()   # the map may have moved: look again
            spot = self.spots.get(node["iname"])
            if not spot or not ms.open_stage(node, spot):
                ms.close_popups()
                raise RuntimeError(f"{name}: stage popup didn't open")
        att = ms.popup_attempts()
        most = (att[1] if att else q.get("max")) or 1
        if att and att[0] >= att[1]:
            self.counter.note(key, att[0], att[1])
            self.log(f"  {name}: {att[0]}/{att[1]} done today - skipped")
            ms.close_popups()
            return
        self.skips = most - (att[0] if att else 0)
        self.tap(map_scan.POPUP_OK)
        if not self.wait_for(self.on_team, 12):
            ms.close_popups()
            raise RuntimeError(f"{name}: team screen didn't open")
        self.sleep(1.0)
        got, skipped = self.skip_stage(name)
        self.counter.note(key, most, most)
        self.done_quest(name, got, skipped)
        self.tap(genesis_farm.TEAM_BACK)
        start = time.time()
        while time.time() - start < 15 * self.lag:
            self.sleep(1.2)
            ms.close_popups()
            if ms.on_map():
                return
            if self.on_team():
                self.tap(genesis_farm.TEAM_BACK)
        raise RuntimeError(f"{name}: didn't get back to the map")

    def done_quest(self, name, got, skipped):
        if skipped:
            txt = ", ".join(f"{u} x{n}" for u, n in got.items()) or "no shards this time"
            self.log(f"  {name}: done - {txt}")
            for u, n in got.items():
                self.shards[u] = self.shards.get(u, 0) + n
            self.on_shards(dict(self.shards))
            self.status(f"{name} done - {self.shard_summary()}")
        else:
            self.log(f"  {name}: can't skip - no attempt left, or not cleared by hand yet")

    # ---------- run ----------
    def run(self, units, counts=None, solo=False):
        order = plan(self.data, units, counts)
        todo = [(e, q) for e, q in order
                if not self.counter.finished(quest_key(e, q), q.get("max") or 1)]
        names = lambda lst: ", ".join(q["title"] for _, q in lst)
        self.log(f"Box farm: {', '.join(units)} -> {len(order)} quests"
                 + (f", {len(order) - len(todo)} already done today" if len(todo) < len(order) else "")
                 + (f": {names(todo)}" if todo else ""))
        try:
            for eid, q in todo:
                if self.wait_if_paused():
                    self.here = None
                st = {"stage": q["title"]}
                while True:
                    try:
                        self.farm_quest(eid, q)
                        break
                    except RuntimeError as e:
                        self.here = None
                        if not self.grace(st, e):
                            raise
            self.log(f"Box farm finished. {self.shard_summary()}")
            return "Finished."
        except (genesis_farm.Stop, event_scan.Stop):
            self.log(f"Box farm stopped. {self.shard_summary()}")
            return "Stopped."
        except genesis_farm.LeafLimit as e:
            self.log(f"{e}. {self.shard_summary()}")
            return str(e)
        except Exception:
            self.log(f"Box farm ended early. {self.shard_summary()}")
            raise
