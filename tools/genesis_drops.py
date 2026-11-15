"""Read the loot of every Genesis Hard stage through the TAC Auto Tap mod (v1.2+).

Start with the game on the Genesis chapter list. For each chapter (ch19 = top of the list ...
ch1 = bottom): open it -> QUEST -> Hard -> for each of the 5 stages: tap it, check the popup
names that stage, open the magnifier (Quest Details), read every Loot entry from the game data
("items"), save a stitched screenshot of the whole Loot row, then close back out.
Never presses OK, so no AP / tickets / attempts are used.

    python genesis_drops.py              all chapters
    python genesis_drops.py 19 18        only those chapters (your numbering)
Results are saved after every stage (results.json), so a re-run skips what's done.
"""
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
import farm  # noqa: E402

OUT = REPO / "data" / "genesis"   # results.json + one loot screenshot per stage
RESULTS = OUT / "results.json"

LIST_X, SLOTS = 0.777, (0.365, 0.599, 0.834)        # chapter list entries (window fractions)
DOWN = (0.779, 0.974)                                 # chapter list: next page
QUEST_BTN = (0.836, 0.512)                            # chapter page: QUEST
DIFF = (0.127, 0.168)                                 # map: Normal/Hard switch
NODES = ((0.1936, 0.4195), (0.3258, 0.5738), (0.4627, 0.4195), (0.5977, 0.5738), (0.7318, 0.4195))
POPUP_TITLE = (0.40, 0.40)                            # "<chapter> - Hard N"
INFO = (0.710, 0.398)                                 # popup: magnifying glass
OUTSIDE = (0.12, 0.75)                                # empty spot: closes details / popup
LOOT = (0.40, 0.853)                                  # Loot row once Quest Details is scrolled down
MAP_BACK, TOP_BACK = (0.075, 0.933), (0.074, 0.935)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def send(cmd, timeout=6.0):
    for _ in range(3):
        r = farm.mod_send(cmd, timeout=timeout, force=True)
        if r is not None:
            return r
        time.sleep(1)
    raise RuntimeError(f"mod not reachable for '{cmd}' - is the game running?")


def tap(p):
    return send(f"tap {p[0]:.4f} {p[1]:.4f}")


def probe(p):
    return send(f"probe {p[0]:.4f} {p[1]:.4f}")


def inspect(p):
    return send(f"inspect {p[0]:.4f} {p[1]:.4f}", timeout=10)


def texts(reply):
    return [t.replace("\xa0", " ").strip() for t in re.findall(r"text:([^,\]]*)", reply)]


def wait_for(fn, timeout=12.0, every=0.4):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
        except RuntimeError:
            raise
        except Exception:
            v = None
        if v:
            return v
        time.sleep(every)
    return None


def on_chapter_list():
    return "ChapterList" in probe((LIST_X, SLOTS[1]))


def chapter_list():
    reply = send(f"items {LIST_X} {SLOTS[1]}", timeout=10)
    out = []
    for chunk in reply.split(" ||| ")[1:]:
        iname = re.search(r"mIname=([^,>]+)", chunk)
        name = re.search(r"mName=([^,>]+)", chunk)
        if iname:
            out.append((iname.group(1), name.group(1) if name else "?"))
    return out


def chapter_in_slot(y):
    m = re.search(r"mIname=([^,>]+)", inspect((LIST_X, y)))
    return m.group(1) if m else None


def open_chapter(iname):
    if not wait_for(on_chapter_list, 15):
        raise RuntimeError("not on the Genesis chapter list")
    send(f"scroll {LIST_X} {SLOTS[1]} 1")
    time.sleep(1.0)
    for _ in range(9):
        for y in SLOTS:
            if chapter_in_slot(y) == iname:
                tap((LIST_X, y))
                if not wait_for(lambda: "GenesisQuestEventTop" in probe(QUEST_BTN), 15):
                    raise RuntimeError(f"{iname}: chapter page didn't open")
                # the page animates in first and ignores presses until it's settled: retry
                for _ in range(6):
                    time.sleep(1.5)
                    if "difficulty" in probe(DIFF):
                        return True
                    if "GenesisQuestEventTop" in probe(QUEST_BTN):
                        tap(QUEST_BTN)
                    if wait_for(lambda: "difficulty" in probe(DIFF), 5):
                        return True
                raise RuntimeError(f"{iname}: quest map didn't open")
        tap(DOWN)
        time.sleep(1.2)
    raise RuntimeError(f"{iname}: not found in the chapter list")


def set_hard():
    for _ in range(4):
        pics = inspect(DIFF)
        if "btn_scenario_hard" in pics:
            return True
        if "btn_scenario_normal" in pics:
            tap(DIFF)
        time.sleep(1.5)
    return False


def popup_title():
    for t in texts(inspect(POPUP_TITLE)):
        if re.search(r"\bHard\s*\d+\s*$", t):   # "<chapter> - Hard 2" (ch12 writes it without the dash)
            return t
    return None


def popup_open():
    return "GenesisQuestConfirm" in probe(OUTSIDE) or "QuestDetail" in probe(OUTSIDE)


def close_all():
    for _ in range(4):
        if not popup_open():
            return True
        tap(OUTSIDE)
        time.sleep(1.3)
    return not popup_open()


def parse_items(reply):
    """Every item in the reply, in order (works whether the mod listed the Loot row's entries or
    one wrapper object holding them all)."""
    out = []
    for m in re.finditer(r"[<,{]iname=([^,>]+),name=([^,>]+),type=([^,>]+)", reply):
        item = {"iname": m.group(1), "name": m.group(2), "type": m.group(3)}
        if item not in out:
            out.append(item)
    return out


LOOT_ICONS = (0.301, 0.383, 0.466, 0.548, 0.630)   # icon centres on the Loot row


def read_loot():
    for x in LOOT_ICONS:
        reply = send(f"items {x} {LOOT[1]}", timeout=12)
        if reply.startswith("ok") and "droplist" in reply.split(" ")[1]:
            return parse_items(reply), reply
    return parse_items(reply) if reply.startswith("ok") else [], reply


def loot_strip():
    """Screenshot the Loot row at its left, middle and right, stacked into one picture."""
    hwnd, region = farm.find_window()
    parts = []
    for v in (0, 0.5, 1):
        send(f"scroll {LOOT[0]} {LOOT[1]} {v}")
        time.sleep(0.7)
        f = farm.capture(hwnd, region)
        if f is None:
            continue
        h, w = f.shape[:2]
        parts.append(f[int(h * 0.775):int(h * 0.935), int(w * 0.255):int(w * 0.79)])
    return np.vstack(parts) if parts else None


def read_stage(ch, st):
    tap(NODES[st - 1])
    title = wait_for(popup_title, 8)
    if not title:
        close_all()
        return {"error": "stage popup didn't open"}
    m = re.search(r"\bHard\s*(\d+)\s*$", title)
    got = int(m.group(1)) if m else st
    opened = False
    for _ in range(4):                 # the popup animates in and may ignore an early press
        time.sleep(0.8)
        if "QuestDetail" in probe(OUTSIDE):
            opened = True
            break
        tap(INFO)
        if wait_for(lambda: "QuestDetail" in probe(OUTSIDE), 4):
            opened = True
            break
    if not opened:
        close_all()
        return {"title": title, "error": "Quest Details didn't open"}
    time.sleep(0.8)
    send("scroll 0.5 0.5 0")
    time.sleep(1.2)
    loot, reply = read_loot()
    strip = loot_strip()
    if strip is not None:
        label = f"{ch}-{got}  {title}"
        bar = np.full((44, strip.shape[1], 3), 30, np.uint8)
        cv2.putText(bar, label.encode("ascii", "replace").decode(), (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(str(OUT / f"{ch}-{got}.png"), np.vstack([bar, strip]))
    close_all()
    res = {"title": title, "stage": got, "loot": loot}
    if got != st:
        res["note"] = f"tapped node {st} but the popup was Hard {got}"
    if not loot:
        res["error"] = f"no loot read ({reply[:120]})"
    return res


def back_to_list():
    """From the quest map or the chapter page, back to the chapter list (retrying presses)."""
    for _ in range(8):
        if on_chapter_list():
            return True
        close_all()
        if "difficulty" in probe(DIFF):
            close_all()
            tap(MAP_BACK)
        elif "GenesisQuestEventTop" in probe(QUEST_BTN):
            tap(TOP_BACK)
        time.sleep(2.5)
    return on_chapter_list()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not on_chapter_list():
        back_to_list()
    results = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    chapters = chapter_list()
    if len(chapters) < 10:
        raise SystemExit("couldn't read the chapter list - start on the Genesis chapter list")
    total = len(chapters)
    wanted = {int(a) for a in sys.argv[1:]} or set(range(1, total + 1))
    log(f"{total} chapters in the list; doing {sorted(wanted, reverse=True)}")
    for idx, (iname, name) in enumerate(chapters):
        ch = total - idx                      # top of the list = highest number
        if ch not in wanted:
            continue
        todo = [st for st in range(1, 6) if "loot" not in results.get(f"{ch}-{st}", {})
                or not results[f"{ch}-{st}"]["loot"]]
        if not todo:
            log(f"ch{ch} already done")
            continue
        log(f"ch{ch} {iname} {name}")
        open_chapter(iname)
        if not set_hard():
            log(f"  ch{ch}: couldn't switch to Hard - skipped")
            results[f"ch{ch}"] = {"error": "no Hard mode", "iname": iname, "name": name}
        else:
            for st in todo:
                r = read_stage(ch, st)
                r.update({"chapter": ch, "chapter_iname": iname, "chapter_name": name})
                key = f"{ch}-{r.get('stage', st)}"
                results[key] = r
                RESULTS.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
                shards = [x["name"] for x in r.get("loot", []) if x["type"] == "UnitPiece"]
                log(f"  {key}: {len(r.get('loot', []))} items, shards: {shards}"
                    + (f"  [{r['error']}]" if r.get("error") else "") + (f"  [{r['note']}]" if r.get("note") else ""))
        if not back_to_list():
            raise RuntimeError("couldn't get back to the chapter list")
    log("finished")


if __name__ == "__main__":
    main()
