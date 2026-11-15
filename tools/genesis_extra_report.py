"""Build the Ex Genesis farm's data from genesis_drops.py --extra (data/genesis/results_extra.json).

Writes app/genesis_extra.json (the Ex farm's picks: each chapter -> its Extra stages, plus
"ALL" = every Extra stage) and data/genesis/genesis_extra_drops.txt (what they drop).

Extra stages you haven't cleared are locked: their popup doesn't open, so their loot can't be
read. Within a chapter every readable Extra stage has had the same loot so far, so a locked
stage is listed with its chapter's pieces (marked "guessed" in the text file). The farm skips
locked stages anyway, and a re-scan after clearing them replaces the guess.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "genesis"
r = json.loads((OUT / "results_extra.json").read_text(encoding="utf-8"))

stages = {}   # "15-1" -> {stage, chapter, hard, chapter_iname, chapter_name, pieces, locked}
for key, v in r.items():
    m = re.fullmatch(r"(\d+)-(\d+)", key)
    if not m or "chapter" not in v:
        continue
    stages[key] = {"stage": key, "chapter": v["chapter"], "hard": int(m.group(2)),
                   "chapter_iname": v["chapter_iname"], "chapter_name": v["chapter_name"],
                   "pieces": [x["name"] for x in v.get("loot", []) if x["type"] == "ItemPiecePiece"],
                   "locked": bool(v.get("locked")), "guessed": False}

for ch in {s["chapter"] for s in stages.values()}:
    mine = [s for s in stages.values() if s["chapter"] == ch]
    seen = {tuple(s["pieces"]) for s in mine if s["pieces"]}
    if len(seen) == 1:
        for s in mine:
            if not s["pieces"]:
                s["pieces"], s["guessed"] = list(next(iter(seen))), True

order = sorted(stages.values(), key=lambda s: (-s["chapter"], s["hard"]))


def entry(s):
    return {k: s[k] for k in ("stage", "chapter", "hard", "chapter_iname", "chapter_name")}


# the farm's picks: one per chapter ("ch15" -> its Extra stages), plus ALL
picks = {"ALL": {"stages": [entry(s) for s in order]}}
for s in order:
    picks.setdefault(f"ch{s['chapter']}", {"name": s["chapter_name"], "stages": []})["stages"].append(entry(s))
(REPO / "app" / "genesis_extra.json").write_text(json.dumps(picks, indent=1, ensure_ascii=False),
                                                 encoding="utf-8")

lines = ["Genesis Extra stages - gear Diagram Pieces (read from the game's loot lists)",
         "Every Extra stage also drops a [3-Title] Boss Challenge Ticket, the six elemental Soul",
         "Shards and Branch. 'guessed' = locked when scanned, listed with its chapter's pieces.", ""]
for ch in sorted({s["chapter"] for s in order}, reverse=True):
    mine = [s for s in order if s["chapter"] == ch]
    lines.append(f"ch{ch}  {mine[0]['chapter_name']}")
    for s in mine:
        note = "  (guessed - locked)" if s["guessed"] else "  (locked, no loot read)" if s["locked"] and not s["pieces"] else ""
        lines.append(f"  EX {s['stage']}: {', '.join(s['pieces']) or '-'}{note}")
    lines.append("")
by_piece = {}
for s in order:
    for piece in s["pieces"]:
        by_piece.setdefault(piece, []).append(s["stage"])
lines += ["By Diagram Piece", ""]
for piece in sorted(by_piece):
    lines.append(f"  {piece}: {', '.join(by_piece[piece])}")
(OUT / "genesis_extra_drops.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
