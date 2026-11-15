"""Story-farm button clicker for The Alchemist Code (native Windows client).

Loop it automates:
  map: newest quest -> team screen: Hire slot -> merc list: Wind tab, pick merc, Confirm -> Go!
  -> story: Skip -> Quest Missions screen: click -> results: End Quest -> repeat
When every quest on the map is cleared (finished counters, no new one), it taps
"To story selection" and then the newest act at the top of the act list. If the newest
act turns out to be finished too, it stops (next episode/chapter needs you).

Runs in the background: keep the game open and visible (e.g. on your 2nd screen) and use the
PC normally. It reads the game window directly, and taps buttons with an injected touch, so
your mouse stays where it is. Each tap gives the game focus for a split second, then hands it
back to the window you were using. The game must not be minimized, and the button being
tapped must not be covered by another window (it skips the tap and waits if it is).

Setup (once):
    pip install opencv-python numpy

Save the button images:
    python farm.py grab 01_quest_new  map screen, new quest: crop the "0/3" counter (with the dots)
    python farm.py grab 02_hire       team screen: the green "Hire" slot
    python farm.py grab 03_wind       merc list: the Wind (green swirl) tab while it is NOT selected
                                      (switch to another tab first, so it gets clicked only when needed)
    python farm.py grab 04_merc       merc list (Wind tab): the card of the merc you want
    python farm.py grab 05_confirm    "Hire ... for 1 Zeni?" popup: the blue "Confirm" button
    python farm.py grab 06_go         team screen: the red "Go!" button
    python farm.py grab 07_skip       story: the "Skip" button (top right)
    python farm.py grab 08_missions   "Quest Missions" screen: the title bar
    python farm.py grab 09_endquest   results screen: the "End Quest" button
    python farm.py grab 10_act        act list: the left end of an act panel (no "Act N" text)
    python farm.py grab x_quest_done  map screen, finished quest: its "3/3" counter with the star
    python farm.py grab x_back        map screen: the "To story selection" button
  Images starting with x_ are only used to detect the finished-act case, never tapped on their own.

Control window (start/pause/stop, run limit, live status and log):
    double-click farm_ui.pyw, or: python farm_ui.pyw

Check what it sees right now (no clicking):
    python farm.py test

Run:
    python farm.py run            (loops forever)
    python farm.py run 50         (stops after 50 End Quest clicks)
    python farm.py run nomerc     (skip the mercenary: straight from the team screen to Go!)
    F8 = pause/resume, F9 = quit (these work from any window)

Scripts (other setups, e.g. a Fire merc instead of the Wind one):
    Each folder in scripts/ is a script (Default is buttons/). Every captured image, in any of
    these folders, is in one shared pool, and each script picks the ones it uses: its
    script.json "use" list, e.g. "Default/02_hire", "Genesis/00_ok". Pick them in the
    window's Customize list. A script without a "use" list keeps the old rule: the Default
    images, with its own images replacing those with the same number.
    python farm.py scripts                           list them
    python farm.py grab 03_fire --script "Fire merc"  save an image into a script
    python farm.py test --script "Fire merc"
    python farm.py run --script "Fire merc"
  The window has a Script picker with Customize / New / Folder buttons for the same thing.

Buttons are checked in filename order and only ONE is clicked per scan, so the
number prefix is the priority. Files with the same number prefix (01_quest_new,
01_quest_done) are variants of one button and share its click cooldown. Keep the game
window the same size between `grab` and `run` (it rescales if it changed, but same size
matches best).
"""
import ctypes
import json
import re
import socket
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import cv2
import numpy as np

VERSION = "1.3.1"   # TACMonkey release (the setup and the window show it)
MOD_VERSION = "1.2.1"  # TAC Auto Tap version shipped with this release (release/build.py checks it)
WINDOW_TITLE = "The Alchemist Code"
# APP_DIR holds your buttons, scripts and settings; RES_DIR the files shipped with the program.
# Run from source both are this folder; as the installed TACMonkey.exe, APP_DIR is the exe's
# folder and RES_DIR the bundled files.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = RES_DIR = Path(__file__).parent
BUTTON_DIR = APP_DIR / "buttons"
REF_FILE = BUTTON_DIR / "_ref_width.json"   # frame width each template was grabbed at
SCRIPTS_DIR = APP_DIR / "scripts"  # one folder per extra script (see load_templates)
DEFAULT_SCRIPT = "Default"                       # the buttons/ folder on its own
SPOTS_FILE = "taps.json"                         # optional fixed tap spots (see load_spots)
EVERY_FILE = BUTTON_DIR / "_every_script.json"   # buttons pressed in every script (see every_script_ids)
FLOW_FILE = "flow.json"                          # which button followed which in runs (FlowRecorder)
SCRIPT_FILE = "script.json"                      # per-script settings: {"use": [...], "count": [...]}
THRESHOLD = 0.85        # match confidence 0-1. Lower it if a button is missed.
COLOR_TOL = 14          # max mean colour difference (0-255) between an image and the screen
SCAN_INTERVAL = 0.25    # seconds between scans
CLICK_COOLDOWN = 2.0    # seconds before the same button can be clicked again
STALL_WARNING = 30      # warn if nothing matched for this many seconds
TOPMOST_BUTTONS = {"01", "10"}  # click the highest match (newest quest / act is at the top)
QUEST_BUTTON = "01"
DONE_MARKER, BACK_MARKER = "x_quest_done", "x_back"
COUNT_BUTTON = "09"  # default run counter (number prefix); each script can pick its own


def is_hire(name):
    """The Hire slot image(s): the only thing left untapped when skipping the merc. Without a
    Hire tap the merc list and its 'Hire for 1 Zeni?' popup never open, so the Wind tab, merc
    and Confirm images stay usable for other screens (Confirm also closes 'Skip this cutscene?')."""
    return "hire" in name.lower()
# Screens that close on a tap anywhere: tap this empty spot (fraction of the window) first, and
# alternate with the matched image if it's still up. The spot is pressable through the mod; the
# matched image (e.g. the "Quest Missions" title) isn't, so tapping it needs a touch tap.
TAP_ANYWHERE = {"08": (0.5, 0.93)}  # Quest Missions: black area below the panel
STUCK_REPEAT = 4  # same button tapped this many times in a row -> log it and save a screenshot
# Buttons that normally take extra taps: the results screen plays its EXP/item motions first and
# ignores End Quest / Try Again! until they finish.
STUCK_REPEAT_FOR = {"09": 10}
STUCK_DIR = APP_DIR / "stuck"
VK_F8, VK_F9 = 0x77, 0x78

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.SetProcessDPIAware()
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.restype = wintypes.HWND


def find_window():
    """Return (hwnd, (left, top, width, height) of client area) or (None, None)."""
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd or user32.IsIconic(hwnd):
        return None, None  # not running, or minimized
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    if rect.right <= 0 or rect.bottom <= 0:
        return None, None
    return hwnd, (origin.x, origin.y, rect.right, rect.bottom)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def capture(hwnd, region):
    """Read the game window's own pixels (works while it's behind other windows).

    Returns None if the frame comes back black (e.g. the game isn't rendering).
    """
    w, h = region[2], region[3]
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 1 | 2)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    frame = cv2.cvtColor(np.frombuffer(buf, np.uint8).reshape(h, w, 4), cv2.COLOR_BGRA2BGR)
    return frame if frame.mean() > 1 else None


class POINTER_INFO(ctypes.Structure):
    _fields_ = [("pointerType", ctypes.c_uint32), ("pointerId", ctypes.c_uint32),
                ("frameId", ctypes.c_uint32), ("pointerFlags", ctypes.c_uint32),
                ("sourceDevice", wintypes.HANDLE), ("hwndTarget", wintypes.HWND),
                ("ptPixelLocation", wintypes.POINT), ("ptHimetricLocation", wintypes.POINT),
                ("ptPixelLocationRaw", wintypes.POINT), ("ptHimetricLocationRaw", wintypes.POINT),
                ("dwTime", wintypes.DWORD), ("historyCount", ctypes.c_uint32),
                ("InputData", ctypes.c_int32), ("dwKeyStates", wintypes.DWORD),
                ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int)]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32),
                ("touchMask", ctypes.c_uint32), ("rcContact", wintypes.RECT),
                ("rcContactRaw", wintypes.RECT), ("orientation", ctypes.c_uint32),
                ("pressure", ctypes.c_uint32)]


TOUCH_DOWN = 0x00010000 | 0x2 | 0x4   # POINTER_FLAG_DOWN | INRANGE | INCONTACT
TOUCH_UPDATE = 0x00020000 | 0x2 | 0x4  # POINTER_FLAG_UPDATE | INRANGE | INCONTACT
TOUCH_UP = 0x00040000                 # POINTER_FLAG_UP
# How long the finger stays down. The game draws only ~7 frames/s while it isn't the focused
# window, so a shorter tap can start and end between two frames and get missed.
TAP_HOLD = 0.2
_touch_ready = False


def _touch(x, y, flags):
    t = POINTER_TOUCH_INFO()
    t.pointerInfo.pointerType = 2  # PT_TOUCH
    t.pointerInfo.pointerFlags = flags
    t.pointerInfo.ptPixelLocation = wintypes.POINT(x, y)
    t.touchMask = 0x7  # contact area, orientation, pressure
    t.rcContact = wintypes.RECT(x - 2, y - 2, x + 2, y + 2)
    t.orientation = 90
    t.pressure = 32000
    return user32.InjectTouchInput(1, ctypes.byref(t))


# TAC Auto Tap: BepInEx plugin inside the game (D:\Games\...\TAC Auto Mod\src\TACAutoTap) that
# presses UI buttons from inside the game - no mouse, no focus change, works while covered.
MOD_PORT = 47613
USE_MOD = True
last_tap = ""  # how the last successful tap was done: "mod" or "touch" (for the log)
MOD_RETRY = 30.0      # after failing to reach the mod, wait this long before trying again
_mod_down_until = 0.0


def mod_send(command, timeout=3.0, force=False):
    """Send one line to the TAC Auto Tap mod and return its reply, or None if it isn't running.
    (Windows takes a moment to refuse a local connection, so a failure is remembered for
    MOD_RETRY seconds instead of slowing every tap down.)"""
    global _mod_down_until
    if not force and time.time() < _mod_down_until:
        return None
    try:
        with socket.create_connection(("127.0.0.1", MOD_PORT), timeout=0.5) as s:
            s.settimeout(timeout)
            s.sendall((command + "\n").encode("ascii"))
            reply = s.makefile("r", encoding="utf-8").readline().strip() or None
        _mod_down_until = 0.0  # reachable again (e.g. a forced ping after the game started)
        return reply
    except OSError:
        _mod_down_until = time.time() + MOD_RETRY
        return None


def mod_status():
    """'pong <version> <w>x<h>' from the mod, or None if it isn't running."""
    reply = mod_send("ping", timeout=2.0, force=True)
    return reply if reply and reply.startswith("pong") else None


def mod_mismatch(status):
    """A warning if the running mod isn't the version this app came with, else None."""
    parts = (status or "").split()
    if len(parts) < 2 or parts[1] == MOD_VERSION:
        return None
    return (f"The game has TAC Auto Tap {parts[1]}, but this TACMonkey is made for {MOD_VERSION}. "
            "Close the game and run the TACMonkey setup (or the update) to bring them in step - "
            "some buttons may not work until then.")


def mod_tap(hwnd, x, y):
    """Ask the mod to press what's at screen point (x, y). Returns its 'ok ...' reply, or None if
    the mod isn't running or found nothing pressable there (the caller then touch-taps)."""
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    if rect.right <= 0 or rect.bottom <= 0:
        return None
    fx, fy = (x - origin.x) / rect.right, (y - origin.y) / rect.bottom
    reply = mod_send(f"tap {fx:.5f} {fy:.5f}")
    return reply if reply and reply.startswith("ok") else None


def tap(hwnd, x, y):
    """Tap screen point (x, y) on the game. Through the TAC Auto Tap mod when it's running and
    there is a UI button there (mouse and focus untouched); otherwise a touch tap that gives
    focus and the cursor back afterwards.

    Returns False (and taps nothing) if the touch tap is needed but another window covers the point.
    """
    global _touch_ready, last_tap
    x, y = int(x), int(y)
    if USE_MOD and mod_tap(hwnd, x, y):
        last_tap = "mod"
        return True
    if user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2) != hwnd:
        return False
    last_tap = "touch"
    if not _touch_ready:
        _touch_ready = bool(user32.InitializeTouchInjection(1, 3))  # 1 contact, no feedback
    prev = user32.GetForegroundWindow()
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    _touch(x, y, TOUCH_DOWN)
    end = time.time() + TAP_HOLD
    while time.time() < end:
        time.sleep(0.03)
        _touch(x, y, TOUCH_UPDATE)  # keep the contact alive while held
    _touch(x, y, TOUCH_UP)
    time.sleep(0.1)
    if prev and prev != hwnd and user32.GetForegroundWindow() != prev:
        user32.SetForegroundWindow(prev)
    user32.SetCursorPos(cursor.x, cursor.y)
    return True


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def list_scripts():
    """Default plus every folder in scripts/."""
    extra = sorted(d.name for d in SCRIPTS_DIR.iterdir() if d.is_dir()) if SCRIPTS_DIR.is_dir() else []
    return [DEFAULT_SCRIPT] + extra


def script_dir(script=None):
    return SCRIPTS_DIR / script if script and script != DEFAULT_SCRIPT else BUTTON_DIR


NUMBERED = re.compile(r"^(\d+)_")


def group_key(name, steps=None):
    """The step an image belongs to (images of one step are variants of one button): the step
    the script assigns it (script.json "steps"), else an old-style number prefix (07_skip and
    07_talk are step 07), else the image is a step of its own. x_ markers are their own name."""
    if steps and name in steps:
        return steps[name]
    if name.startswith("x_"):
        return name
    m = NUMBERED.match(name)
    return m.group(1) if m else name


def step_map(script=None):
    """{image name: step} the script assigns by hand (variants grouped in Customize)."""
    steps = script_settings(script).get("steps", {})
    return {k: v for k, v in steps.items() if isinstance(k, str) and isinstance(v, str)} \
        if isinstance(steps, dict) else {}


def set_step(script, name, key):
    """Put image `name` into step `key` for this script (None = its own default step)."""
    before = rank_steps(script_steps(script), priority_order(script))
    settings = script_settings(script)
    steps = step_map(script)
    if key is None or key == group_key(name):
        steps.pop(name, None)
    else:
        steps[name] = key
    if steps:
        settings["steps"] = dict(sorted(steps.items()))
    else:
        settings.pop("steps", None)
    _write_settings(script, settings)
    added = [k for k in script_steps(script) if k not in before]
    if added and before:  # a step split off goes to the bottom of the priority
        set_priority_order(script, [k for k in before if k in script_steps(script)] + added)


def script_steps(script=None):
    """The steps this script's picked images make up (markers and built-ins left out), in plain
    sort order - the starting point that priority_order reorders."""
    steps = step_map(script)
    names = [i.split("/", 1)[1] for i in used_ids(script) if i not in ACTIONS]
    return sorted({group_key(n, steps) for n in names if not n.startswith("x_")})


def load_refs(folder=BUTTON_DIR):
    ref_file = folder / REF_FILE.name
    return json.loads(ref_file.read_text()) if ref_file.exists() else {}


def grab(name, script=None):
    """Drag a box on a fresh capture of the game and save it as <name>.png in the script's folder."""
    hwnd, region = find_window()
    if not region:
        sys.exit(f"Window '{WINDOW_TITLE}' not found or minimized.")
    frame = capture(hwnd, region)
    if frame is None:
        sys.exit("Captured a black frame - make sure the game is open and not minimized.")
    x, y, w, h = cv2.selectROI("Drag a box around the button, ENTER to save, C to cancel",
                               frame, showCrosshair=False)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        sys.exit("Cancelled.")
    out = save_image(script, name, frame[y:y + h, x:x + w], frame.shape[1])
    print(f"Saved {out} (grabbed at window width {frame.shape[1]})")
    return out


def save_image(script, name, img, ref_width):
    """Save a button image into a script folder, with the window width it was cut at."""
    folder = script_dir(script)
    folder.mkdir(parents=True, exist_ok=True)
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    out = folder / f"{name}.png"
    cv2.imwrite(str(out), img)
    refs = load_refs(folder)
    refs[name] = int(ref_width)
    (folder / REF_FILE.name).write_text(json.dumps(refs, indent=2))
    return out


def remove_image(script, name):
    """Take an image out of a script (moved to its _old folder, not deleted)."""
    folder = script_dir(script)
    old = folder / "_old"
    old.mkdir(exist_ok=True)
    (folder / f"{name}.png").replace(old / f"{name}.png")
    refs = load_refs(folder)
    refs.pop(name, None)
    (folder / REF_FILE.name).write_text(json.dumps(refs, indent=2))


def script_settings(script=None):
    f = script_dir(script) / SCRIPT_FILE
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def new_script_settings(script):
    """A new script starts with nothing picked (a folder without script.json would use every
    Default image, the old behaviour kept for scripts made before the pool existed)."""
    _write_settings(script, {"use": []})


def _write_settings(script, settings):
    folder = script_dir(script)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SCRIPT_FILE).write_text(json.dumps(settings, indent=2))


IMPORT_SKIP = {"_old", "_original", "__pycache__"}


def import_buttons(src):
    """Copy button images and scripts from another copy of this program (a folder holding
    buttons/ and/or scripts/, or a buttons folder itself). Files already here are kept.
    Returns (images copied, scripts touched, files skipped because they already exist)."""
    import shutil
    src = Path(src)
    if src.name.lower() == "buttons" and not (src / "buttons").is_dir():
        pairs = [(src, BUTTON_DIR)]
    else:
        pairs = [(src / "buttons", BUTTON_DIR)]
        if (src / "scripts").is_dir():
            pairs += [(d, SCRIPTS_DIR / d.name) for d in sorted((src / "scripts").iterdir())
                      if d.is_dir() and d.name not in IMPORT_SKIP]
    images = skipped = 0
    scripts = set()
    for frm, to in pairs:
        if not frm.is_dir() or frm.resolve() == to.resolve():
            continue
        for f in sorted(frm.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".png", ".json"):
                continue
            out = to / f.name
            if out.exists():
                skipped += 1
                continue
            to.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            if f.suffix.lower() == ".png":
                images += 1
            scripts.add(DEFAULT_SCRIPT if to == BUTTON_DIR else to.name)
    return images, sorted(scripts), skipped


# ---------- sharing a script as one file ----------
SHARE_EXT = ".tacscript"   # a zip: manifest.json + images/<name>.png
SHARE_FORMAT = 1
SHARE_MAX_IMAGES = 400
SHARE_MAX_IMAGE_BYTES = 5_000_000
SHARE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,80}$")


class ShareError(Exception):
    pass


def export_script(script, path):
    """Write one script to a .tacscript file: the images it uses (wherever they live), their
    capture widths, its run counter, tap spots and built-in actions.

    Returns (images written, names renamed {old: new}, ids missing on disk)."""
    import zipfile
    want = used_ids(script)
    actions = [i for i in want if i in ACTIONS]
    pool = {bid: (name, home) for bid, name, home, _, _ in library()}
    counters = counter_names(script)
    src_steps = step_map(script)
    images, renamed, missing, out_steps = {}, {}, [], {}
    files = {}
    for bid in sorted(i for i in want if i not in ACTIONS):
        if bid not in pool:
            missing.append(bid)
            continue
        name, home = pool[bid]
        src = script_dir(home) / f"{name}.png"
        data = src.read_bytes()
        out = name
        if out in files and files[out] != data:  # same name from two folders: keep both
            n = 2
            while f"{name}_{n}" in files:
                n += 1
            out = f"{name}_{n}"
            renamed[f"{home}/{name}"] = out
        if out in files:
            continue  # the very same image twice
        files[out] = data
        images[out] = {"ref": load_refs(script_dir(home)).get(name),
                       "count": name in counters}
        step = group_key(name, src_steps)
        if step != group_key(out):
            out_steps[out] = step
    if not files and not actions:
        raise ShareError("This script has no buttons picked - nothing to export.")
    pairs, _ = load_flow(script)  # the learned arrows travel along (renamed images left out)
    flow = {f"{a}>{b}": n for (a, b), n in pairs.items() if a in images and b in images and
            a not in renamed.values() and b not in renamed.values()}
    manifest = {"format": SHARE_FORMAT, "app_version": VERSION, "name": script,
                "images": images, "actions": actions, "flow": flow,
                "order": priority_order(script), "steps": out_steps,
                "spots": {k: list(v) for k, v in load_spots(script).items()}}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name, data in files.items():
            z.writestr(f"images/{name}.png", data)
    return len(files), renamed, missing


def free_script_name(name):
    """name, or 'name (2)', 'name (3)' ... whichever isn't taken yet."""
    taken = {s.lower() for s in list_scripts()}
    out, n = name, 2
    while out.lower() in taken:
        out, n = f"{name} ({n})", n + 1
    return out


def import_script(path, name=None):
    """Make a new script from a .tacscript file. Nothing that's already here is touched: the
    images go into the new script's own folder. Returns (script name, images, notes)."""
    import zipfile
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ShareError(f"Not a TACMonkey script file ({e}).") from e
    with z:
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError) as e:
            raise ShareError("Not a TACMonkey script file (no readable manifest).") from e
        if not isinstance(manifest, dict) or manifest.get("format") != SHARE_FORMAT:
            raise ShareError("This script file is from a different TACMonkey version - "
                             "update TACMonkey and try again.")
        images = manifest.get("images") or {}
        if not isinstance(images, dict) or len(images) > SHARE_MAX_IMAGES:
            raise ShareError("The script file's image list is broken.")
        notes = []
        decoded = {}
        for img_name, meta in images.items():
            if not isinstance(img_name, str) or not SHARE_NAME.match(img_name) or \
                    not isinstance(meta, dict):
                raise ShareError(f"Unsafe image name in the script file: {img_name!r}")
            try:
                info = z.getinfo(f"images/{img_name}.png")
            except KeyError:
                notes.append(f"{img_name} is listed but missing from the file - skipped")
                continue
            if info.file_size > SHARE_MAX_IMAGE_BYTES:
                raise ShareError(f"{img_name}.png is too large to be a button image.")
            img = cv2.imdecode(np.frombuffer(z.read(info), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ShareError(f"{img_name}.png isn't a readable image.")
            decoded[img_name] = (img, meta)
        actions = [a for a in manifest.get("actions") or [] if a in ACTIONS]
        if not decoded and not actions:
            raise ShareError("The script file has no buttons in it.")
        spots = {}
        for key, val in (manifest.get("spots") or {}).items():
            try:
                x, y = float(val[0]), float(val[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if isinstance(key, str) and SHARE_NAME.match(key) and 0 <= x <= 1 and 0 <= y <= 1:
                spots[key] = [x, y]
        flow = {}
        raw_flow = manifest.get("flow") or {}
        for key, n in (raw_flow.items() if isinstance(raw_flow, dict) else []):
            a, _, b = str(key).partition(">")
            if a in decoded and b in decoded and isinstance(n, int) and 0 < n < 10**7:
                flow[f"{a}>{b}"] = n

    wanted = str(name or manifest.get("name") or Path(path).stem)
    wanted = "".join(c for c in wanted if c not in '\\/:*?"<>|').strip(" .") or "Imported"
    if wanted == DEFAULT_SCRIPT:
        wanted = "Imported"
    script = free_script_name(wanted[:60])
    folder = script_dir(script)
    folder.mkdir(parents=True)
    refs = {}
    for img_name, (img, meta) in decoded.items():
        cv2.imwrite(str(folder / f"{img_name}.png"), img)  # re-encoded: only pixels come in
        ref = meta.get("ref")
        if isinstance(ref, int) and 100 <= ref <= 10000:
            refs[img_name] = ref
    (folder / REF_FILE.name).write_text(json.dumps(refs, indent=2))
    if spots:
        (folder / SPOTS_FILE).write_text(json.dumps(spots, indent=2))
    if flow:
        (folder / FLOW_FILE).write_text(json.dumps({"pairs": flow, "pressed": {}}, indent=2))
    settings = {
        "use": sorted([f"{script}/{n}" for n in decoded] + actions),
        "count": sorted(n for n, (_, meta) in decoded.items() if meta.get("count") is True)}
    raw_steps = manifest.get("steps")
    step_of = {n: k for n, k in (raw_steps.items() if isinstance(raw_steps, dict) else [])
               if n in decoded and isinstance(k, str) and SHARE_NAME.match(k)}
    if step_of:
        settings["steps"] = dict(sorted(step_of.items()))
    steps = {group_key(n, step_of) for n in decoded}
    raw_order = manifest.get("order")
    order = [k for k in raw_order if isinstance(k, str) and k in steps] \
        if isinstance(raw_order, list) else []
    if order:
        settings["order"] = order
    _write_settings(script, settings)
    if manifest.get("app_version") and manifest["app_version"] != VERSION:
        notes.append(f"made with TACMonkey {manifest['app_version']} (you have {VERSION})")
    return script, len(decoded), notes


def library():
    """Every captured button image, whichever script it was captured in:
    [(id, name, home, image, ref width)] with id "<home>/<name>" and home = Default (buttons/)
    or the script folder it lives in."""
    out = []
    for home in list_scripts():
        folder = script_dir(home)
        if folder.is_dir():
            out += [(f"{home}/{name}", name, home, tpl, ref) for name, tpl, ref in _load_folder(folder)]
    return out


def used_ids(script=None):
    """Pool ids this script uses: its pick list (script.json "use"). A script not edited since
    the pool was added keeps what it used before: the Default images, with the script's own
    images replacing those with the same number, minus any it had turned off."""
    settings = script_settings(script)
    if "use" in settings:
        return list(settings["use"])
    ids = [f"{DEFAULT_SCRIPT}/{f.stem}" for f in sorted(BUTTON_DIR.glob("*.png"))]
    if script and script != DEFAULT_SCRIPT:
        own = [f.stem for f in sorted(script_dir(script).glob("*.png"))]
        replaced = {group_key(name) for name in own}
        ids = [i for i in ids if group_key(i.split("/", 1)[1]) not in replaced]
        ids += [f"{script}/{name}" for name in own]
    off = set(settings.get("off", []))
    return [i for i in ids if i.split("/", 1)[1] not in off]


def freeze_use(script=None):
    """Write the script's current picks to its script.json, so later additions don't change them."""
    settings = script_settings(script)
    if "use" not in settings:
        settings["use"] = sorted(used_ids(script))
        settings.pop("off", None)
        _write_settings(script, settings)


def set_used(script, button_id, on):
    """Pick (or un-pick) one pool image for this script. A new step goes to the bottom of the
    priority (not wherever its name would sort)."""
    freeze_use(script)
    before = rank_steps(script_steps(script), priority_order(script))
    settings = script_settings(script)
    ids = set(settings["use"])
    ids = ids | {button_id} if on else ids - {button_id}
    settings["use"] = sorted(ids)
    _write_settings(script, settings)
    added = [k for k in script_steps(script) if k not in before]
    if on and added and before:
        set_priority_order(script, before + added)


def counter_names(script=None, templates=None):
    """Images whose tap counts as one finished run: the script's own pick (script.json "count"),
    or by default every used image numbered COUNT_BUTTON (09_endquest, 09_tryagain)."""
    settings = script_settings(script)
    if "count" in settings:
        return set(settings["count"])
    if templates is not None:
        names = [name for name, _, _ in templates]
    else:  # from the picks, not load_templates(): that stops on a script with nothing picked
        names = [i.split("/", 1)[1] for i in used_ids(script) if i not in ACTIONS]
    steps = step_map(script)
    return {name for name in names if group_key(name, steps) == COUNT_BUTTON}


def set_counter(script, name, on):
    """Make one image count as a run (or stop counting) for this script only."""
    names = counter_names(script)
    names = names | {name} if on else names - {name}
    settings = script_settings(script)
    settings["count"] = sorted(names)
    _write_settings(script, settings)


# Buttons pressed in every script, e.g. "View Later" on the Peddler Shop popup that can show
# up after any quest. They're checked before the script's own steps, and aren't part of any
# script's steps, priority or flow.
EVERY_PREFIX = "*"   # their step keys in the farm loop, so they never clash with a script's steps


def every_script_ids():
    """Pool ids ("<home>/<name>") pressed in every script."""
    try:
        ids = json.loads(EVERY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in ids if isinstance(i, str) and "/" in i] if isinstance(ids, list) else []


def set_every_script(button_id, on):
    ids = set(every_script_ids())
    ids = ids | {button_id} if on else ids - {button_id}
    BUTTON_DIR.mkdir(parents=True, exist_ok=True)
    EVERY_FILE.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def every_script_templates(script=None):
    """[(name, image, ref)] of the every-script buttons this script doesn't pick itself."""
    own = set(used_ids(script))
    want = {i for i in every_script_ids() if i not in own}
    return sorted(((name, tpl, ref) for button_id, name, _, tpl, ref in library()
                   if button_id in want), key=lambda t: t[0])


def every_script_groups(templates):
    """{"*view later": [(name, image, ref)]}: one step each, checked before the script's."""
    return {EVERY_PREFIX + name: [(name, tpl, ref)] for name, tpl, ref in templates}


# Built-in actions: pool entries with no image, done through the TAC Auto Tap mod. A script
# picks them in Customize like any button. They're checked before the images on every scan.
ACTION_HOME = "Built-in"
AP_REFILL = f"{ACTION_HOME}/ap_refill"
ACTIONS = {AP_REFILL: ("AP refill - 7 Alchemy Drops",
                       "When the Replenish AP window is open: picks Alchemy Drops, sets 7 pcs "
                       "(fewer if the game caps it), OK, OK. Needs the mod.")}
ACTION_CHECK = 1.0  # seconds between checks for an action's screen


def action_badge(text):
    """A small picture for an action in the customizer (it has no captured image)."""
    img = np.full((60, 180, 3), (60, 40, 25), np.uint8)
    for i, line in enumerate(text.split("\n")):
        cv2.putText(img, line, (8, 24 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 230, 170), 1, cv2.LINE_AA)
    return img


def used_actions(script=None):
    return [i for i in used_ids(script) if i in ACTIONS]


PEDDLER = "UnlockGuerrillaShopPopup"   # the Peddler Shop popup that can follow any quest


def press_view_later():
    """If the Peddler Shop popup is showing, press its View Later (through the mod). True if so."""
    reply = mod_send("list", timeout=5.0)
    if not reply or PEDDLER not in reply:
        return False
    try:
        els = json.loads(reply)
    except ValueError:
        return False
    btn = next((e for e in els if PEDDLER in e.get("path", "") and e["path"].endswith("btn_cancel")
                and e.get("on")), None)
    return bool(btn) and mod_send(f"tap {btn['x']:.4f} {btn['y']:.4f}", timeout=5.0) is not None


def ap_window_open():
    """True if the game shows the Replenish AP window (asked through the mod)."""
    reply = mod_send("list", timeout=5.0)
    return bool(reply) and "HealAPItemList" in reply


def describe_library(script=None):
    """Every pool entry for the customizer, in priority order: dicts with id, name, home, img,
    ref, used (this script uses it), counter, spot, marker, action (built-in, no image)."""
    used = set(used_ids(script))
    every = set(every_script_ids())
    counters = counter_names(script)
    spots = load_spots(script)
    steps = step_map(script)
    out = [{"id": aid, "name": name, "home": ACTION_HOME, "img": action_badge("AP refill\n7 Alch. Drops"),
            "ref": None, "used": aid in used, "counter": False, "marker": False, "spot": None,
            "action": True, "every": False, "about": about} for aid, (name, about) in ACTIONS.items()]
    for button_id, name, home, tpl, ref in sorted(library(), key=lambda b: (b[1], b[2])):
        marker = name.startswith("x_")
        out.append({"id": button_id, "name": name, "home": home, "img": tpl, "ref": ref,
                    "used": button_id in used, "counter": name in counters, "marker": marker,
                    "spot": None if marker else spots.get(group_key(name, steps)),
                    "step": group_key(name, steps), "action": False,
                    "every": button_id in every})
    return out


# ---------- the flow: which button follows which (drawn by the customizer) ----------
def load_flow(script=None):
    """({(a, b): times b was pressed right after a}, {name: times pressed}) from runs."""
    try:
        data = json.loads((script_dir(script) / FLOW_FILE).read_text())
        pairs = {tuple(k.split(">", 1)): int(v) for k, v in data.get("pairs", {}).items()
                 if ">" in k}
        return pairs, {k: int(v) for k, v in data.get("pressed", {}).items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}, {}


def reset_flow(script=None):
    (script_dir(script) / FLOW_FILE).unlink(missing_ok=True)


class FlowRecorder:
    """Counts, during a run, which button was pressed after which. Repeat taps of the same
    button are one step. Saved every few presses and at the end."""

    def __init__(self, script):
        self.script = script
        self.pairs, self.pressed = load_flow(script)
        self.prev, self.unsaved = None, 0

    def press(self, name):
        self.pressed[name] = self.pressed.get(name, 0) + 1
        if self.prev and self.prev != name:
            self.pairs[(self.prev, name)] = self.pairs.get((self.prev, name), 0) + 1
        self.prev = name
        self.unsaved += 1
        if self.unsaved >= 5:
            self.save()

    def save(self):
        if not self.unsaved:
            return
        try:
            folder = script_dir(self.script)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / FLOW_FILE).write_text(json.dumps(
                {"pairs": {f"{a}>{b}": n for (a, b), n in sorted(self.pairs.items())},
                 "pressed": dict(sorted(self.pressed.items()))}, indent=2))
            self.unsaved = 0
        except OSError:
            pass


def flow_model(script=None):
    """What the customizer draws: this script's buttons grouped like the farm groups them
    (same number = variants of one step), in the order runs went through them.

    {"groups": {key: [entries]}, "order": [keys], "pairs": {(ka, kb): n}, "pressed": {key: n},
     "learned": bool, "actions": [entries], "markers": [entries], "every": [entries]} - entries
    as describe_library ("every": buttons pressed in every script that this one doesn't pick)."""
    library_entries = describe_library(script)
    entries = [b for b in library_entries if b["used"]]
    every = [b for b in library_entries if b["every"] and not b["used"]]
    actions = [b for b in entries if b["action"]]
    markers = [b for b in entries if not b["action"] and b["marker"]]
    groups = {}
    for b in sorted((b for b in entries if not b["action"] and not b["marker"]),
                    key=lambda b: (b["step"], b["name"], b["home"])):
        groups.setdefault(b["step"], []).append(b)
    key_of = {b["name"]: k for k, bs in groups.items() for b in bs}
    pairs, pressed = load_flow(script)
    gpairs, gpressed = {}, {}
    for (a, b), n in pairs.items():
        if a in key_of and b in key_of and key_of[a] != key_of[b]:
            gpairs[(key_of[a], key_of[b])] = gpairs.get((key_of[a], key_of[b]), 0) + n
    for name, n in pressed.items():
        if name in key_of:
            gpressed[key_of[name]] = gpressed.get(key_of[name], 0) + n
    own = priority_order(script)
    priority = rank_steps(list(groups), own)
    return {"groups": groups, "order": flow_order(priority, gpairs, gpressed),
            "priority": priority, "custom_priority": bool(own),
            "pairs": gpairs, "pressed": gpressed, "learned": bool(gpairs),
            "actions": actions, "markers": markers, "every": every}


def flow_order(keys, pairs, pressed):
    """Steps in the order runs go through them: from the first pressed step (in priority
    order), always on to its most frequent next step not placed yet; never-pressed steps go
    last. Without any runs it's simply the priority order (keys as given)."""
    if not pairs:
        return list(keys)
    nxt = {}
    for (a, b), n in pairs.items():
        nxt.setdefault(a, []).append((n, b))
    seen_pressed = [k for k in keys if pressed.get(k) or any(k in p for p in pairs)]
    order, placed = [], set()
    current = seen_pressed[0] if seen_pressed else None
    while current is not None:
        order.append(current)
        placed.add(current)
        options = sorted((o for o in nxt.get(current, []) if o[1] not in placed),
                         key=lambda o: (-o[0], keys.index(o[1])))
        current = options[0][1] if options else next(
            (k for k in seen_pressed if k not in placed), None)
    return order + [k for k in keys if k not in placed]


def load_spots(script=None):
    """Fixed tap spots: {"04": (0.12, 0.35)} = when button 04's image is seen, tap that spot
    (fractions of the window width/height) instead of the image. Read from taps.json in
    buttons/ and then the script folder (the script wins)."""
    spots = {}
    for folder in (BUTTON_DIR, script_dir(script)):
        f = folder / SPOTS_FILE
        if f.exists():
            spots.update({k: tuple(v) for k, v in json.loads(f.read_text()).items()})
    return spots


def tap_point(button, hit, size, spots):
    """Where to tap for a hit: its fixed spot if the button has one, else the image centre."""
    if button in spots:
        return int(size[0] * spots[button][0]), int(size[1] * spots[button][1]), " (fixed spot)"
    return hit[2], hit[3], ""


def _load_folder(folder):
    refs = load_refs(folder)
    return [(f.stem, cv2.imread(str(f)), refs.get(f.stem)) for f in sorted(folder.glob("*.png"))]


def load_templates(script=None):
    """The images a script uses (see used_ids), from the shared pool, in priority order."""
    if script and script != DEFAULT_SCRIPT and not script_dir(script).is_dir():
        sys.exit(f"Script folder not found: {script_dir(script)}")
    want = set(used_ids(script))
    templates = sorted(((name, tpl, ref) for button_id, name, _, tpl, ref in library()
                        if button_id in want), key=lambda t: t[0])
    if not templates:
        sys.exit("This script has no buttons picked - tick some in Customize "
                 "(or capture images with: python farm.py grab <name>)")
    return templates


def match_map(frame, tpl, ref_width):
    """Full-size score map: (map, template scaled to the frame), or None if it doesn't fit.
    (The farm loop uses the faster _search; this is kept for checking images by hand.)"""
    # rescale on any size change: even a 1% difference drops text-heavy images below THRESHOLD
    if ref_width and frame.shape[1] != ref_width:
        s = frame.shape[1] / ref_width
        tpl = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    if tpl.shape[0] > frame.shape[0] or tpl.shape[1] > frame.shape[1]:
        return None
    return cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED), tpl


def color_ok(frame, tpl, x, y):
    """True if the screen at top-left (x, y) has the image's colours, not just its shape.

    The match score mostly ignores colour, so e.g. the Fire tab icon scores 0.82-0.87 on a
    selected (bright) tab or behind a dimmed popup. Real matches differ by ~11/255 at most.
    """
    h, w = tpl.shape[:2]
    patch = frame[y:y + h, x:x + w].astype(np.int16)
    return float(np.abs(patch - tpl.astype(np.int16)).mean()) <= COLOR_TOL


# Fast search: look on a half-size copy of the screen first (about 4x less work), then
# re-check only the promising spots at full size, so scores and positions stay exact.
COARSE = 0.5       # size of the quick first look
COARSE_THR = 0.6   # quick-look score a spot needs before it's checked at full size
COARSE_PAD = 8     # pixels around a quick-look spot searched at full size
_scaled_cache = {}            # id(template) -> (template, frame width, full-size copy, half-size copy)
_small_frame = [None, None]   # [frame, its half-size copy] for the frame being scanned


def _small(frame):
    if _small_frame[0] is not frame:
        _small_frame[:] = [frame, cv2.resize(frame, None, fx=COARSE, fy=COARSE,
                                             interpolation=cv2.INTER_AREA)]
    return _small_frame[1]


def _scaled(tpl, ref_width, frame_width):
    """The template resized to this window width, plus its half-size copy (cached)."""
    hit = _scaled_cache.get(id(tpl))
    if hit and hit[0] is tpl and hit[1] == frame_width:
        return hit[2], hit[3]
    t = tpl
    if ref_width and frame_width != ref_width:
        s = frame_width / ref_width
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    small = cv2.resize(t, None, fx=COARSE, fy=COARSE, interpolation=cv2.INTER_AREA)
    if len(_scaled_cache) > 500:
        _scaled_cache.clear()
    _scaled_cache[id(tpl)] = (tpl, frame_width, t, small)  # holding tpl keeps its id unique
    return t, small


def _full_res(frame, t, x0, y0, x1, y1):
    """Full-size score map for top-left positions in [x0, x1] x [y0, y1]: (map, x offset, y offset)."""
    h, w = t.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame.shape[1] - w, x1), min(frame.shape[0] - h, y1)
    if x1 < x0 or y1 < y0:
        return None
    crop = frame[y0:y1 + h, x0:x1 + w]
    return cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED), x0, y0


def _search(frame, tpl, ref_width, all_above=None):
    """Find a template. Returns (scaled template, spots) where spots is [(score, x, y)] (top-left):
    the single best spot, or with all_above=thr every full-size position scoring >= thr."""
    t, ts = _scaled(tpl, ref_width, frame.shape[1])
    if t.shape[0] > frame.shape[0] or t.shape[1] > frame.shape[1]:
        return t, []
    if min(ts.shape[:2]) < 12:  # too small to look at half size: search at full size
        found = _full_res(frame, t, 0, 0, frame.shape[1], frame.shape[0])
    else:
        quick = cv2.matchTemplate(_small(frame), ts, cv2.TM_CCOEFF_NORMED)
        if all_above is None:
            _, s, _, loc = cv2.minMaxLoc(quick)
            if s < COARSE_THR:  # nothing promising: report the quick score
                return t, [(s, int(loc[0] / COARSE), int(loc[1] / COARSE))]
            xs, ys = np.array([loc[0]]), np.array([loc[1]])
        else:
            ys, xs = np.where(quick >= COARSE_THR)
            if not len(ys):
                return t, []
        found = _full_res(frame, t, int(xs.min() / COARSE) - COARSE_PAD,
                          int(ys.min() / COARSE) - COARSE_PAD,
                          int(xs.max() / COARSE) + COARSE_PAD, int(ys.max() / COARSE) + COARSE_PAD)
    if found is None:
        return t, []
    res, ox, oy = found
    if all_above is None:
        _, s, _, loc = cv2.minMaxLoc(res)
        return t, [(s, ox + loc[0], oy + loc[1])]
    ys, xs = np.where(res >= all_above)
    return t, [(float(res[y, x]), ox + x, oy + y) for y, x in zip(ys, xs)]


def match(frame, tpl, ref_width):
    """Return (score, center_x, center_y) of the best match in frame coordinates (shape only)."""
    t, spots = _search(frame, tpl, ref_width)
    if not spots:
        return 0.0, 0, 0
    score, x, y = spots[0]
    return score, x + t.shape[1] // 2, y + t.shape[0] // 2


def find_button(frame, variants, topmost):
    """Return (name, score, x, y) to click for one button, or None.

    Normal buttons: the first variant that matches. Topmost buttons: the highest match on
    screen across all variants (the story map lists the newest quest at the top).
    A match also has to pass the colour check.
    """
    hits = []
    for name, tpl, ref in variants:
        if not topmost:
            t, spots = _search(frame, tpl, ref)
            if spots:
                score, x, y = spots[0]
                if score >= THRESHOLD and color_ok(frame, t, x, y):
                    return name, score, x + t.shape[1] // 2, y + t.shape[0] // 2
            continue
        t, spots = _search(frame, tpl, ref, all_above=THRESHOLD)
        hits += [(name, score, x, y, t) for score, x, y in spots]
    while hits:
        # best-scoring point of the topmost match (its top edge only just clears the threshold)
        top = min(hit[3] for hit in hits)
        cluster = [hit for hit in hits if hit[3] - top < 20]
        name, score, x, y, tpl = max(cluster, key=lambda hit: hit[1])
        if color_ok(frame, tpl, x, y):
            return name, score, x + tpl.shape[1] // 2, y + tpl.shape[0] // 2
        hits = [hit for hit in hits if hit[3] - top >= 20]  # wrong colours: try the next one down
    return None


def group_templates(templates, order=None, steps=None):
    """Group clickable templates into steps (see group_key): {"01": [variants], "go": [...]}.
    The dict order is the priority (checked first to last): plain sort order of the steps, or
    the script's own priority list (see priority_order) when it has one.

    x_ marker images are left out (see split_markers).
    """
    groups = {}
    for name, tpl, ref in templates:
        if not name.startswith("x_"):
            groups.setdefault(group_key(name, steps), []).append((name, tpl, ref))
    return {k: groups[k] for k in rank_steps(sorted(groups), order)}


def rank_steps(keys, order=None):
    """keys (in number order) in priority order: the ones in the script's priority list in that
    order, then any others (e.g. added since) in number order after them."""
    if not order:
        return list(keys)
    listed = [k for k in order if k in keys]
    return listed + [k for k in keys if k not in listed]


def priority_order(script=None):
    """The script's own priority list of steps ([] = plain number order)."""
    order = script_settings(script).get("order", [])
    return [k for k in order if isinstance(k, str)] if isinstance(order, list) else []


def set_priority_order(script, keys):
    """Save the step priority for this script; the plain number order is stored as no list."""
    settings = script_settings(script)
    if list(keys) == sorted(keys) or not keys:
        settings.pop("order", None)
    else:
        settings["order"] = list(keys)
    _write_settings(script, settings)


def split_markers(templates):
    return {name: (tpl, ref) for name, tpl, ref in templates if name.startswith("x_")}


def act_finished(frame, groups, markers):
    """Return the back-button hit if this is a quest map with no new quest left, else None."""
    if DONE_MARKER not in markers or BACK_MARKER not in markers:
        return None
    if QUEST_BUTTON in groups and find_button(frame, groups[QUEST_BUTTON], True):
        return None
    if match(frame, *markers[DONE_MARKER])[0] < THRESHOLD:
        return None
    score, x, y = match(frame, *markers[BACK_MARKER])
    return (BACK_MARKER, score, x, y) if score >= THRESHOLD else None


def check(script=None):
    """Score every button image of a script on the current screen.

    Returns ((width, height), [(name, score), ...], what-it-would-click text).
    """
    templates = load_templates(script)
    hwnd, region = find_window()
    if not region:
        sys.exit(f"Window '{WINDOW_TITLE}' not found or minimized.")
    frame = capture(hwnd, region)
    if frame is None:
        sys.exit("Captured a black frame - make sure the game is open and not minimized.")
    every = every_script_templates(script)
    scores = [(name, match(frame, tpl, ref)[0]) for name, tpl, ref in templates + every]
    groups = {**every_script_groups(every),
              **group_templates(templates, priority_order(script), step_map(script))}
    back = act_finished(frame, groups, split_markers(templates))
    if AP_REFILL in used_actions(script) and ap_window_open():
        action = "Replenish AP is open -> would refill AP with 7 Alchemy Drops"
    elif back:
        action = f"Act finished -> would click: {back[0]} at ({back[2]},{back[3]}) in the window"
    else:
        spots = load_spots(script)
        for button, variants in groups.items():
            hit = find_button(frame, variants, button in TOPMOST_BUTTONS)
            if hit:
                x, y, note = tap_point(button, hit, (region[2], region[3]), spots)
                action = f"Would click: {hit[0]} at ({x},{y}) in the window{note}"
                break
        else:
            action = "Would click: nothing"
    return (region[2], region[3]), scores, action


def test(script=None):
    (w, h), scores, action = check(script)
    print(f"Window {w}x{h}. Threshold {THRESHOLD}. Scores on the current screen:")
    for name, score in scores:
        print(f"  {name:<16} {score:.2f}")
    print(action)


def run(max_runs=None, log=print, stop=None, pause=None, on_status=None, act_switch=True,
        skip_merc=None, script=None):
    """Farm until stopped and return why it stopped.

    The window (farm_ui.pyw) passes threading.Events for stop/pause/skip_merc, its own log
    function and on_status(state, runs, last_click). F8 (pause/resume) and F9 (stop) work either
    way. While skip_merc is set, the Hire slot is never tapped (straight to Go!).
    """
    stop = stop or threading.Event()
    pause = pause or threading.Event()
    skip_merc = skip_merc or threading.Event()

    def say(msg):
        log(f"{time.strftime('%H:%M:%S')} {msg}")

    templates = load_templates(script)
    groups = group_templates(templates, priority_order(script), step_map(script))
    log(f"Loaded {len(templates)} buttons: {', '.join(n for n, _, _ in templates)}")
    log("Priority: " + " > ".join(groups) + (" (own list)" if priority_order(script) else ""))
    every = every_script_templates(script)
    if every:
        log("Pressed in every script (checked first): " + ", ".join(n for n, _, _ in every))
        groups = {**every_script_groups(every), **groups}
    markers = split_markers(templates)
    spots = load_spots(script)
    counters = counter_names(script, templates)
    log(f"Run counter: {', '.join(sorted(counters)) or 'none - runs are not counted'}")
    if spots:
        log("Fixed tap spots: " + ", ".join(f"{b} at {x:.0%} across, {y:.0%} down"
                                            for b, (x, y) in sorted(spots.items())))
    if not act_switch:
        markers = {}  # act_finished() never fires without the markers
        log("Act switching is off.")
    elif DONE_MARKER not in markers or BACK_MARKER not in markers or "10" not in groups:
        log("Note: act switching is off (needs x_quest_done, x_back and 10_act images).")
    if skip_merc.is_set():
        log("Skipping the mercenary (the Hire slot is never tapped).")
    status = mod_status() if USE_MOD else None
    if status:
        log(f"TAC Auto Tap mod is running ({status.split()[1]}): buttons are pressed inside the "
            "game - your mouse is left alone (touch taps only where there's no UI button).")
        if mod_mismatch(status):
            log("WARNING: " + mod_mismatch(status))
    else:
        log("TAC Auto Tap mod not running - using touch taps.")
    refill = None  # the AP refill action, if this script uses it
    if AP_REFILL in used_actions(script):
        import genesis_farm  # its refill routine (imported here: it imports this file)
        refill = genesis_farm.GenesisFarm(log=log, stop=stop)
        log(f"AP refill is on: when Replenish AP opens, it uses {genesis_farm.AP_PCS} "
            f"{genesis_farm.AP_ITEM}." + ("" if status else " (Needs the mod - it isn't running.)"))
    last_ap_check = last_peddler_check = 0.0
    log("F8 = pause/resume, F9 = stop (from any window). Keep the game open and uncovered.")
    flow = FlowRecorder(script)  # learns the arrows the customizer draws
    last_click, runs, f8_prev = {}, 0, False
    went_back = False  # tapped "back" for a finished act, no new quest found since
    last_action = time.time()
    warned = covered_warned = False
    last, shown, reason = "", None, None
    repeat_button, repeats = None, 0  # same button tapped how many times in a row

    def show(state):
        nonlocal shown
        if on_status and (state, runs, last) != shown:
            shown = (state, runs, last)
            on_status(state, runs, last)

    while not stop.is_set():
        if key_down(VK_F9):
            reason = "Stopped (F9)."
            break
        f8 = key_down(VK_F8)
        if f8 and not f8_prev:
            if pause.is_set():
                pause.clear()
                say("RESUMED")
            else:
                pause.set()
                say("PAUSED")
        f8_prev = f8
        if pause.is_set():
            show("Paused")
            time.sleep(SCAN_INTERVAL)
            continue

        hwnd, region = find_window()
        frame = capture(hwnd, region) if region else None
        if frame is None:
            show("Waiting for the game (loading, minimized or closed)")
            time.sleep(SCAN_INTERVAL)
            continue

        if status and time.time() - last_peddler_check >= ACTION_CHECK:
            last_peddler_check = time.time()
            if press_view_later():
                say("Peddler Shop popped up - View Later [mod]")
                last = "View Later (Peddler Shop)"
                last_action = time.time()
                repeat_button, warned = None, False
                time.sleep(1.0)
                continue

        if refill and time.time() - last_ap_check >= ACTION_CHECK:
            last_ap_check = time.time()
            if ap_window_open():
                say("Replenish AP is open - refilling [mod]")
                show("Refilling AP")
                try:
                    refill.replenish_ap()
                except genesis_farm.Stop:
                    break
                except RuntimeError as e:
                    reason = f"AP refill failed: {e}"
                    break
                last = ACTIONS[AP_REFILL][0]
                last_action = last_ap_check = time.time()
                repeat_button, warned = None, False
                show("Running")
                continue

        back = act_finished(frame, groups, markers)
        if back and time.time() - last_click.get(BACK_MARKER, 0) >= CLICK_COOLDOWN:
            if went_back:
                reason = ("The newest act is finished too - pick the next episode/chapter "
                          "yourself, then start again.")
                break
            if tap(hwnd, region[0] + back[2], region[1] + back[3]):
                say(f"act finished - click {BACK_MARKER} [{last_tap}]")
                last = BACK_MARKER
                last_click[BACK_MARKER] = last_action = time.time()
                went_back, warned = True, False
                show("Running")
            else:
                show(f"Waiting: {BACK_MARKER} is covered by another window")
            time.sleep(SCAN_INTERVAL)
            continue

        for button, variants in groups.items():
            if time.time() - last_click.get(button, 0) < CLICK_COOLDOWN:
                continue
            if skip_merc.is_set():
                variants = [v for v in variants if not is_hire(v[0])]
                if not variants:
                    continue
            hit = find_button(frame, variants, button in TOPMOST_BUTTONS)
            if hit:
                name, score, cx, cy = hit
                streak = repeats + 1 if button == repeat_button else 1
                cx, cy, where = tap_point(button, hit, (region[2], region[3]), spots)
                if button in TAP_ANYWHERE and streak % 2 == 1:  # 1st, 3rd... tap: empty area
                    fx, fy = TAP_ANYWHERE[button]
                    cx, cy = int(region[2] * fx), int(region[3] * fy)
                    where = " - tapping the empty area instead"
                if not tap(hwnd, region[0] + cx, region[1] + cy):
                    if not covered_warned:
                        say(f"{name} is covered by another window - waiting until it's visible")
                        covered_warned = True
                    show(f"Waiting: {name} is covered by another window")
                    break
                covered_warned = False
                repeat_button, repeats = button, streak
                say(f"click {name} ({score:.2f}){f' x{streak}' if streak > 1 else ''}{where}"
                    f" [{last_tap}]")
                if streak == STUCK_REPEAT_FOR.get(button, STUCK_REPEAT):
                    STUCK_DIR.mkdir(exist_ok=True)
                    shot = STUCK_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}.png"
                    cv2.imwrite(str(shot), frame)
                    say(f"{name} tapped {streak} times in a row and the screen hasn't moved on "
                        f"- saved {shot.name} in the stuck folder")
                last = f"{name} ({score:.2f})"
                if streak == 1 and not button.startswith(EVERY_PREFIX):
                    flow.press(name)
                last_click[button] = last_action = time.time()
                warned = False
                if button == QUEST_BUTTON:
                    went_back = False
                if name in counters and streak == 1 and not button.startswith(EVERY_PREFIX):
                    # (repeat taps are still the same screen)
                    runs += 1
                    log(f"  runs completed: {runs}")
                    if max_runs and runs >= max_runs:
                        reason = f"Reached {max_runs} runs."
                show("Running")
                break
        else:
            if time.time() - last_action > STALL_WARNING:
                if not warned:
                    say(f"nothing recognised for {STALL_WARNING}s - unknown screen/popup? "
                        "(Check screen / `python farm.py test` shows the scores)")
                    warned = True
                show(f"Stuck: nothing recognised for {STALL_WARNING}s+")
            else:
                show("Running")
        if reason:
            break
        time.sleep(SCAN_INTERVAL)
    flow.save()
    reason = reason or "Stopped."
    say(reason)
    show("Stopped")
    return reason


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    chosen = None
    if "--script" in args:  # --script "Fire merc"
        i = args.index("--script")
        chosen = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if cmd == "grab" and args:
        grab(args[0], chosen)
    elif cmd == "test":
        test(chosen)
    elif cmd == "scripts":
        print("\n".join(list_scripts()))
    elif cmd == "run":
        no_merc = threading.Event()
        if "nomerc" in args:
            args.remove("nomerc")
            no_merc.set()
        run(int(args[0]) if args else None, skip_merc=no_merc, script=chosen)
    else:
        print(__doc__)
