"""Build the Genesis Hard-stage unit shard list from genesis_drops/results.json.
Writes genesis_unit_shards.txt (19-5: units), a by-unit index, and genesis_loot_all.csv."""
import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "genesis"
r = json.loads((OUT / "results.json").read_text(encoding="utf-8"))


# shorter display names (only in these report files; the farm uses its own data)
SHORT = {"Yishai Ignacio": "Yishai", "Ouroboros Legacy": "Ouroboros"}


def short(name):
    return SHORT.get(name, name)


def shards(key):
    return [short(x["name"].replace(" Soul Shard", "")) for x in r[key]["loot"] if x["type"] == "UnitPiece"]


lines = ["Genesis Hard stages - unit shards (read from the game's loot lists)",
         "ch19 = top of the Genesis chapter list ... ch1 = bottom", ""]
by_unit = {}
table = []  # rows for genesis_unit_shards.csv
for c in range(19, 0, -1):
    name = r[f"{c}-1"]["chapter_name"]
    lines.append(f"ch{c}  {name}")
    per = {f"{c}-{s}": shards(f"{c}-{s}") for s in range(1, 6)}
    for key, units in per.items():
        for u in units:
            by_unit.setdefault(u, []).append(key)
    if len({tuple(sorted(u)) for u in per.values()}) == 1:
        units = per[f"{c}-1"]
        lines.append(f"  {c}-1 to {c}-5: {', '.join(units) if units else '(no unit shards)'} (same for all)")
        table.append([c, ", ".join(units)] + ["same"] * 4)
    else:
        table.append([c] + [", ".join(u) for u in per.values()])
        for key, units in per.items():
            lines.append(f"  {key}: {', '.join(units) if units else '(no unit shards)'}")
    lines.append("")

lines += ["", "By unit (where each shard drops)", ""]
for u in sorted(by_unit, key=str.lower):
    lines.append(f"  {u}: {', '.join(by_unit[u])}")

(OUT / "genesis_unit_shards.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

with open(OUT / "genesis_unit_shards.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Chapter", "Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5"])
    w.writerows(table)

with open(OUT / "genesis_loot_all.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["stage", "chapter", "item", "type", "item_id"])
    for c in range(19, 0, -1):
        for s in range(1, 6):
            key = f"{c}-{s}"
            for x in r[key]["loot"]:
                name = x["name"]
                for long, sh in SHORT.items():
                    name = name.replace(long, sh)
                w.writerow([key, r[key]["chapter_name"], name, x["type"], x["iname"]])
print("\n".join(lines))
