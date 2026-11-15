"""Talk to the TAC Auto Tap mod by hand.
    python modtest.py ping
    python modtest.py probe 0.5 0.5      (what's at the middle of the window - presses nothing)
    python modtest.py tap 0.5 0.5        (press it)
    python modtest.py list               (every pressable element on screen, as a table)
    python modtest.py list all           (also covered / disabled ones)
    python modtest.py click Hard Stage 5 (press the element whose text contains that)
"""
import json
import socket
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # labels can be Japanese

args = sys.argv[1:] or ["ping"]
show_all = args[:2] == ["list", "all"]
cmd = "list" if show_all else " ".join(args)
try:
    with socket.create_connection(("127.0.0.1", 47613), timeout=1) as s:
        s.settimeout(10)
        s.sendall((cmd + "\n").encode())
        reply = s.makefile("r", encoding="utf-8").readline().strip()
except OSError as e:
    sys.exit(f"mod not reachable ({e}) - is the game running with BepInEx + TACAutoTap.dll?")

if cmd == "list" and reply.startswith("["):
    items = json.loads(reply)
    shown = [i for i in items if show_all or (i["top"] and i["on"])]
    print(f"{len(items)} pressable elements, {len(shown)} shown"
          f"{'' if show_all else ' (on top + enabled; use: list all)'}")
    for i in shown:
        flags = ("" if i["top"] else " COVERED") + ("" if i["on"] else " DISABLED")
        print(f"  ({i['x']:.3f},{i['y']:.3f})  {i['text'][:60]!r:<62} {i['path'][-55:]}{flags}")
else:
    print(reply)
