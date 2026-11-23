"""Event scanner: read every event's quests and their loot through the TAC Auto Tap mod (1.2+).

Start with the game on the Event Quest list (Quest > Event). For each event in the list: open it,
read every quest row (title, AP, attempts), and - unless survey only - open each quest's
magnifier (Quest Details) and read its Loot from the game data, then close back out. It finds
everything by the game's object names, not by screen positions, so it works for any event.
Never presses a quest itself, so no AP, tickets or attempts are used.

    python event_scan.py              every event: quests + loot
    python event_scan.py --survey     every event: quest rows only (quick)
    python event_scan.py glanz inazuma    only events whose id contains one of these

Results go to event_scan.json in the TACMonkey folder (one entry per event, saved after every
quest, so a re-run skips what's done; --fresh starts over).
"""
import json
import re
import sys
import threading
import time

import farm

SCAN_FILE = farm.APP_DIR / "event_scan.json"

# the mod shortens deep paths to their last parts, so match on short, telling pieces
EVENT_LIST, QUEST_LIST = "ChapterList", "QuestList"
EVENT_SCREEN = "EventQuestSelector/CanvasBoundsPanel/"   # on the event screen's Back buttons
LIST_ENTRY = re.compile(r"ChapterList/contents/viewport/list/([^/]+)\(Clone\)")
OUTSIDE = (0.12, 0.75)              # an empty spot: closes Quest Details
LOOT_RE = re.compile(r"[<,{]iname=([^,>]+),name=([^,>]+),type=([^,>]+)")


class Stop(Exception):
    pass


def clean(t):
    return t.replace("\xa0", " ").strip()


def parse_quest_text(text):
    """A quest row reads "Unit Lv20 Job Lv2 Recommended | Episode 1: ... | 10 | 0 | / | 3"
    -> {"title", "ap", "used", "max", "note"} (missing parts left out)."""
    parts = [clean(p) for p in text.split("|")]
    out = {}
    if "/" in parts:
        i = parts.index("/")
        if i > 0 and parts[i - 1].isdigit() and i + 1 < len(parts) and parts[i + 1].isdigit():
            out["used"], out["max"] = int(parts[i - 1]), int(parts[i + 1])
            parts = parts[:i - 1] + parts[i + 2:]
    nums = [p for p in parts if p.isdigit()]
    if nums:
        out["ap"] = int(nums[-1])
    words = [p for p in parts if p and not p.isdigit()]
    notes = [w for w in words if "Recommended" in w]
    titles = [w for w in words if w not in notes]
    if titles:
        out["title"] = titles[0]
    if notes:
        out["note"] = notes[0]
    return out


def parse_loot(reply):
    out = []
    for m in LOOT_RE.finditer(reply or ""):
        item = {"iname": m.group(1), "name": clean(m.group(2)), "type": m.group(3)}
        if item not in out:
            out.append(item)
    return out


class EventScanner:
    def __init__(self, log=print, stop=None, status=None):
        self.log = log
        self.stop = stop or threading.Event()
        self.status = status or (lambda text: None)

    # ---------- mod ----------
    def send(self, cmd, timeout=8.0):
        for _ in range(6):
            if self.stop.is_set():
                raise Stop()
            r = farm.mod_send(cmd, timeout=timeout, force=True)
            if r is not None and not r.startswith("err timeout"):
                return r
            if r is not None and cmd.startswith(("tap", "scroll")):
                self.sleep(1.5)
                return "ok (late)"
            self.sleep(1.0)
        raise RuntimeError("TAC Auto Tap mod not answering - is the game running with the mod?")

    def sleep(self, s):
        if self.stop.wait(s):
            raise Stop()

    def tap(self, x, y):
        return self.send(f"tap {x:.4f} {y:.4f}")

    def elements(self, usable=True):
        for _ in range(3):
            try:
                els = json.loads(self.send("list", timeout=10))
            except ValueError:
                self.sleep(1.0)
                continue
            return [e for e in els if isinstance(e, dict) and "path" in e
                    and (not usable or (e.get("top") and e.get("on")))]
        raise RuntimeError("the mod's list came back unreadable")

    def wait_for(self, fn, timeout=12.0, every=0.4):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            self.sleep(every)
        return None

    def find(self, part, els=None, text=None):
        for e in (els if els is not None else self.elements()):
            if part in e["path"] and (text is None or clean(e.get("text", "")).startswith(text)):
                return e
        return None

    # ---------- where are we ----------
    def on_event_list(self):
        return bool(self.find(EVENT_SCREEN + EVENT_LIST + "/Bottom/back"))

    def on_quest_list(self):
        return bool(self.find(EVENT_SCREEN + QUEST_LIST + "/Bottom/back"))

    def detail_open(self):
        """Quest Details is up: its own dark background sits under the empty spot (only that
        is ever tapped to close it, so nothing behind the window gets pressed)."""
        return "QuestDetail" in self.send(f"probe {OUTSIDE[0]} {OUTSIDE[1]}")

    def close_detail(self):
        for _ in range(4):
            if not self.detail_open():
                return
            self.tap(*OUTSIDE)
            self.sleep(1.2)
        raise RuntimeError("Quest Details didn't close")

    def back_to_event_list(self):
        for _ in range(6):
            if self.on_event_list():
                return
            if self.detail_open():
                self.close_detail()
            else:
                b = self.find(EVENT_SCREEN + QUEST_LIST + "/Bottom/back")
                if not b:
                    raise RuntimeError("not on an event screen - open Quest > Event first")
                self.tap(b["x"], b["y"])
            self.sleep(2.0)
        raise RuntimeError("couldn't get back to the event list")

    # ---------- event list ----------
    def scroll_list(self, which, v):
        anchor = self.find(which + "/contents/viewport/list/")
        if anchor:
            self.send(f"scroll {anchor['x']:.4f} {anchor['y']:.4f} {v}")
            self.sleep(0.6)

    def visible_events(self):
        out = {}
        for e in self.elements():
            m = LIST_ENTRY.search(e["path"])
            if m and 0.2 < e["y"] < 0.92:
                out.setdefault(m.group(1), e)
        return out

    def list_events(self):
        """Every event id in the list, top to bottom (the list is scrolled through)."""
        seen = []
        for step in range(11):
            self.scroll_list(EVENT_LIST, 1 - step / 10)
            for name, e in sorted(self.visible_events().items(), key=lambda kv: kv[1]["y"]):
                if name not in seen:
                    seen.append(name)
        self.scroll_list(EVENT_LIST, 1)
        return seen

    def open_event(self, name):
        self.back_to_event_list()
        for step in range(11):
            self.scroll_list(EVENT_LIST, 1 - step / 10)
            e = self.visible_events().get(name)
            if e:
                self.tap(e["x"], e["y"])
                if self.wait_for(self.on_quest_list, 10):
                    self.sleep(1.0)
                    return
                raise RuntimeError(f"{name}: the event's quest list didn't open")
        raise RuntimeError(f"{name}: not in the event list")

    # ---------- quest list ----------
    def visible_quests(self):
        """[(row, info button)] for the quest rows on screen."""
        els = self.elements()
        rows = [e for e in els if QUEST_LIST + "/contents/viewport/list/" in e["path"]
                and e["path"].endswith("(Clone)") and e.get("text")]
        infos = [e for e in els if QUEST_LIST in e["path"] and e["path"].endswith("btn_info")]
        out = []
        for r in rows:
            near = min(infos, key=lambda i: abs(i["y"] - r["y"]), default=None)
            if near is not None and abs(near["y"] - r["y"]) > 0.08:
                near = None
            out.append((r, near))
        return out

    def list_quests(self):
        """Every quest row of the open event, top to bottom: parsed text + kind of row."""
        seen, order = {}, []
        for step in range(21):
            self.scroll_list(QUEST_LIST, 1 - step / 20)
            for r, _ in sorted(self.visible_quests(), key=lambda q: q[0]["y"]):
                text = clean(r["text"])
                if text not in seen:
                    kind = re.search(r"/([^/]+)\(Clone\)$", r["path"]).group(1)
                    seen[text] = {**parse_quest_text(r["text"]), "row": kind, "text": text}
                    order.append(text)
            if step and not self.find(QUEST_LIST + "/contents/Down"):
                break
        self.scroll_list(QUEST_LIST, 1)
        return [seen[t] for t in order]

    def read_loot(self, text):
        """Open the quest row's magnifier, read its Loot, close it again."""
        for step in range(21):
            self.scroll_list(QUEST_LIST, 1 - step / 20)
            hit = next(((r, i) for r, i in self.visible_quests() if clean(r["text"]) == text), None)
            if hit and 0.2 < hit[0]["y"] < 0.88:
                break
        else:
            raise RuntimeError(f"quest row not found again: {text[:50]}")
        row, info = hit
        if not info:
            return None, "no magnifier on this row"
        opened = False
        for _ in range(3):
            self.tap(info["x"], info["y"])
            if self.wait_for(self.detail_open, 5):
                opened = True
                break
        if not opened:
            return None, "Quest Details didn't open"
        self.sleep(0.8)
        self.send("scroll 0.5 0.5 0")
        self.sleep(1.0)
        loot, reply = [], ""
        for _ in range(3):
            reply = self.send("itemsof droplist", timeout=12)
            loot = parse_loot(reply)
            if loot:
                break
            self.sleep(1.0)
        self.close_detail()
        return loot, (None if loot else f"no loot read ({reply[:80]})")

    # ---------- scan here (the Dev page) ----------
    STANDARD = ("/contents/", "/Bottom/", "ChapterDetail", "Ranking", "OtherQuest", "BtnEventShop")

    def screen(self):
        """"detail" (Quest Details open), "quest_list" (an event's quests), "event_list" or None."""
        if self.detail_open():
            return "detail"
        if self.on_quest_list():
            return "quest_list"
        if self.on_event_list():
            return "event_list"
        return None

    def extras(self):
        """Buttons on the event screen that aren't the usual ones (e.g. a Normal / Hard switch):
        kept with a scan so a farm can find its way back to that place."""
        out = []
        for e in self.elements():
            if EVENT_SCREEN in e["path"] and not any(k in e["path"] for k in self.STANDARD):
                out.append({"path": e["path"], "text": clean(e.get("text", "")),
                            "x": round(e["x"], 3), "y": round(e["y"], 3)})
        return out

    def scan_open_list(self, tab=None, progress=None):
        """Every quest of the quest list that is open now, with its loot. tab: a label for this
        place (e.g. "Hard") when the event has more than one list."""
        if self.screen() != "quest_list":
            raise RuntimeError("open an event's quest list in the game first")
        extras = self.extras()
        quests = self.list_quests()
        out = []
        for i, q in enumerate(quests, 1):
            if progress:
                progress(f"{i}/{len(quests)} {q.get('title', '')}")
            loot, err = self.read_loot(q["text"])
            q = {k: v for k, v in q.items() if k != "text"}
            q["loot"] = loot or []
            if tab:
                q["tab"] = tab
            if err:
                q["error"] = err
            out.append(q)
        return out, extras

    def scan_open_detail(self):
        """The loot of the Quest Details that is open now (for screens the list scan doesn't know)."""
        if not self.detail_open():
            raise RuntimeError("open a quest's details (the magnifier) in the game first")
        self.send("scroll 0.5 0.5 0")
        self.sleep(1.0)
        for _ in range(3):
            loot = parse_loot(self.send("itemsof droplist", timeout=12))
            if loot:
                return loot
            self.sleep(1.0)
        raise RuntimeError("couldn't read the Loot of the open Quest Details")

    def event_choices(self, progress=None):
        """[(event id, its first quest's title)] for the event list, so events can be told
        apart (their banners are pictures). Ends back on the event list."""
        self.back_to_event_list()
        out = []
        for name in self.list_events():
            if progress:
                progress(name)
            self.open_event(name)
            rows = sorted(self.visible_quests(), key=lambda q: q[0]["y"])
            first = parse_quest_text(rows[0][0]["text"]).get("title", "") if rows else ""
            out.append((name, first))
            self.back_to_event_list()
        return out

    def scan_event(self, name, tab=None, progress=None):
        """Open an event from the list, scan its quest list, come back."""
        self.open_event(name)
        try:
            return self.scan_open_list(tab, progress)
        finally:
            self.back_to_event_list()

    # ---------- run ----------
    def run(self, only=(), survey=False, fresh=False):
        results = {} if fresh or not SCAN_FILE.exists() else \
            json.loads(SCAN_FILE.read_text(encoding="utf-8"))
        save = lambda: SCAN_FILE.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
        try:
            self.back_to_event_list()
            events = self.list_events()
            self.log(f"{len(events)} events in the list: {', '.join(events)}")
            for name in events:
                if only and not any(o.lower() in name.lower() for o in only):
                    continue
                ev = results.setdefault(name, {"id": name})
                self.log(f"{name}")
                self.status(f"Scanning {name}")
                self.open_event(name)
                quests = self.list_quests()
                old = {q["text"]: q for q in ev.get("quests", [])}
                ev["quests"] = [{**q, **{k: old[q["text"]][k] for k in ("loot",)
                                         if k in old.get(q["text"], {})}} for q in quests]
                ev["scanned"] = time.strftime("%Y-%m-%d %H:%M")
                save()
                for q in ev["quests"]:
                    tag = f"  {q.get('title', q['text'][:40])}  ({q.get('ap', '?')} AP" + \
                          (f", {q['used']}/{q['max']}" if "max" in q else "") + ")"
                    if survey or q.get("loot"):
                        self.log(tag + (f"  - {len(q['loot'])} loot" if q.get("loot") else ""))
                        continue
                    loot, err = self.read_loot(q["text"])
                    if loot:
                        q["loot"] = loot
                        q.pop("error", None)
                    else:
                        q["error"] = err
                    coins = [x["name"] for x in loot or [] if x["type"].startswith("Event")]
                    self.log(tag + (f"  - {len(loot)} loot" + (f", event: {coins}" if coins else "")
                                    if loot else f"  [{err}]"))
                    save()
                self.back_to_event_list()
            self.log("Event scan finished.")
            return "Finished."
        except Stop:
            self.log("Event scan stopped.")
            return "Stopped."


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    print(EventScanner().run(only=[a for a in args if not a.startswith("--")],
                             survey="--survey" in args, fresh="--fresh" in args))
