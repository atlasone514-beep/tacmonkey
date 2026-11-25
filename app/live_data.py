"""Live data: box events (and later shared scripts) that every TACMonkey downloads, so a new box
event reaches everyone without a new release.

The data is one JSON file in the repository (data/live/box_events.json on main). fetch() reads it
from GitHub (a plain web request, like the update check) and keeps a copy in the TACMonkey folder,
so it still works offline. The Dev page publishes a new version through GitHub's API with the
developer's own token (dev.json, never shared); nobody else needs one.

    {"format": 1, "updated": "2026-11-23 20:15",
     "events": {"quest_ev_x": {"name": "...", "id": "quest_ev_x", "added": "2026-11-23",
                               "quests": [{"title": "...", "ap": 16, "max": 3, "tab": "Hard",
                                           "loot": [{"iname", "name", "type"}, ...]}],
                               "portraits": {"Glanz": "glan"}}},      # picked on the Dev page
     "scripts": {"rima_event_farm": {"name": "Rima event farm", "version": 2, "note": "...",
                                     "path": "data/live/scripts/rima_event_farm.tacscript",
                                     "sha256": "...", "size": 12345}},
     "texts": {"box.help": "..."}}          # wording changed on the Dev page (see texts.py)
Portraits are only pictures beside the names (app/portraits/<code>.png); nothing is found by them.
"""
import hashlib
import base64
import json
import re
import time
import urllib.error
import urllib.request

import farm

FORMAT = 1
REPOS = ("atlasone514-beep/tacmonkey", "MohammedEmad638/tacmonkey")   # as updater.REPOS
BRANCH = "main"
BOX_PATH = "data/live/box_events.json"
CACHE = farm.APP_DIR / "box_events.json"        # last copy downloaded (or published)
BUNDLED = farm.RES_DIR / "box_events.json"      # shipped with the release, for the first start
DEV_FILE = farm.APP_DIR / "dev.json"            # the developer's token - only on their PC
DRAFT_FILE = farm.APP_DIR / "box_draft.json"    # scanned but not published yet
MAX_BYTES = 2_000_000
UA = {"User-Agent": "TACMonkey"}
SHARD = re.compile(r"^(.+) Soul Shard$")
PORTRAITS = farm.RES_DIR / "portraits"
CODE = re.compile(r"[a-z0-9_]{1,40}")
SCRIPT_ID = re.compile(r"[a-z0-9_]{1,60}")
TEXT_KEY = re.compile(r"[a-z0-9_.]{1,80}")
SCRIPTS_DIR = "data/live/scripts"
MAX_SCRIPT = 8_000_000
MAX_TEXT = 4000


class LiveError(Exception):
    pass


def empty():
    return {"format": FORMAT, "updated": None, "events": {}, "scripts": {}, "texts": {}}


# ---------- checking ----------
def validate(data):
    """The data if it's well-formed (unknown keys are kept), else LiveError. Anything a farm
    reads later is checked here, so a bad file can't break the app."""
    if not isinstance(data, dict) or not isinstance(data.get("events"), dict):
        raise LiveError("not a box event file")
    if not isinstance(data.get("format"), int) or data["format"] > FORMAT:
        raise LiveError("made by a newer TACMonkey - update to use it")
    for eid, ev in data["events"].items():
        if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,80}", eid):
            raise LiveError(f"bad event id {eid!r}")
        if not isinstance(ev, dict) or not isinstance(ev.get("quests"), list):
            raise LiveError(f"{eid}: no quest list")
        if not isinstance(ev.get("name", ""), str):
            raise LiveError(f"{eid}: bad name")
        pics = ev.get("portraits", {})
        if not isinstance(pics, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                 and CODE.fullmatch(v) for k, v in pics.items()):
            raise LiveError(f"{eid}: bad portraits")
        for q in ev["quests"]:
            if not isinstance(q, dict) or not isinstance(q.get("title"), str) or \
                    not isinstance(q.get("loot", []), list):
                raise LiveError(f"{eid}: bad quest entry")
            for it in q.get("loot", []):
                if not isinstance(it, dict) or not all(isinstance(it.get(k), str)
                                                       for k in ("iname", "name", "type")):
                    raise LiveError(f"{eid}: bad loot entry")
    scripts = data.setdefault("scripts", {})
    if not isinstance(scripts, dict):
        raise LiveError("bad script list")
    for sid, sc in scripts.items():
        if not isinstance(sid, str) or not SCRIPT_ID.fullmatch(sid) or not isinstance(sc, dict) \
                or not isinstance(sc.get("name"), str) or not isinstance(sc.get("version"), int) \
                or sc.get("path") != f"{SCRIPTS_DIR}/{sid}.tacscript" \
                or not isinstance(sc.get("sha256"), str) or not isinstance(sc.get("note", ""), str):
            raise LiveError(f"bad script entry {sid!r}")
    texts = data.setdefault("texts", {})
    if not isinstance(texts, dict) or not all(
            isinstance(k, str) and TEXT_KEY.fullmatch(k) and isinstance(v, str)
            and len(v) <= MAX_TEXT for k, v in texts.items()):
        raise LiveError("bad text list")
    return data


def units(data):
    """{unit name: [{"event", "event_name", "title", "ap", "max", "tab"}]} - every quest whose
    loot has the unit's Soul Shard, in the file's order."""
    out = {}
    for eid, ev in data.get("events", {}).items():
        for q in ev.get("quests", []):
            for it in q.get("loot", []):
                m = SHARD.match(it["name"]) if it["type"] == "UnitPiece" else None
                if m:
                    out.setdefault(m.group(1), []).append(
                        {"event": eid, "event_name": ev.get("name") or eid, "title": q["title"],
                         "ap": q.get("ap"), "max": q.get("max"), "tab": q.get("tab"),
                         "iname": it["iname"]})
    return out


# ---------- portraits (display only) ----------
def portrait_codes():
    try:
        return sorted(f.stem for f in PORTRAITS.glob("*.png") if CODE.fullmatch(f.stem))
    except OSError:
        return []


def _in_order(short, long):
    """Every letter of short appears in long, in the same order."""
    it = iter(long)
    return all(ch in it for ch in short)


def guess_portrait(iname, codes=None):
    """The portrait code for a shard's item id (IT_PI_MATHIAS -> "math"), or None. A portrait's
    code is the start of the unit's id, sometimes shortened (JUURIA -> "jria")."""
    codes = portrait_codes() if codes is None else codes
    key = iname.lower()
    for pre in ("it_pi_", "it_un_", "un_v2_", "un_"):
        if key.startswith(pre):
            key = key[len(pre):]
            break
    if key in codes:
        return key
    dark = key.endswith("_dark")
    base = key[:-5] if dark else key
    best = None
    for c in codes:
        if c.endswith("_dark") != dark:
            continue
        cb = c[:-5] if dark else c
        if len(cb) < 3:
            continue
        flat_c, flat_b = cb.replace("_", ""), base.replace("_", "")
        score = (3 if base.startswith(cb) else
                 2 if base.split("_")[-1].startswith(cb) else
                 1 if flat_c[0] == flat_b[0] and _in_order(flat_c, flat_b) else 0)
        if score and (best is None or (score, len(cb)) > best[0]):
            best = ((score, len(cb)), c)
    return best[1] if best else None


def portraits(data, codes=None):
    """{unit: portrait code or None}: the Dev page's pick, else a guess."""
    codes = portrait_codes() if codes is None else codes
    out = {}
    for unit, quests in units(data).items():
        picked = next((ev.get("portraits", {}).get(unit) for ev in data["events"].values()
                       if ev.get("portraits", {}).get(unit)), None)
        out[unit] = picked if picked in codes else guess_portrait(quests[0]["iname"], codes)
    return out


def main_units(ev):
    """The event's main units, marked on the Dev page (optional, any number): the Box events
    tab shows them first and folds the other units away. [] = every unit shows."""
    m = ev.get("main") or []
    return [m] if isinstance(m, str) else list(m)


def quest_units(q):
    return [SHARD.match(it["name"]).group(1) for it in q.get("loot", [])
            if it["type"] == "UnitPiece" and SHARD.match(it["name"])]


# ---------- reading ----------
def _read_json(path):
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, LiveError):
        return None


def load():
    """The newest copy on this PC: the last download, else the one shipped with the release."""
    return _read_json(CACHE) or _read_json(BUNDLED) or empty()


def _get(url, timeout, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_BYTES + 1)


def fetch(timeout=8):
    """Download the live file from GitHub, keep a copy, return it (LiveError if it can't)."""
    last = None
    for repo in REPOS:
        url = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/{BOX_PATH}?t={int(time.time())}"
        try:
            raw = _get(url, timeout)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                continue
            break
        except OSError as e:
            last = e
            break
        if len(raw) > MAX_BYTES:
            raise LiveError("the box event file is too large")
        try:
            data = validate(json.loads(raw.decode("utf-8")))
        except ValueError as e:
            raise LiveError(f"the box event file isn't readable ({e})") from e
        save_cache(data)
        return data
    if isinstance(last, urllib.error.HTTPError) and last.code == 404:
        return load()   # not published yet: nothing new
    raise LiveError(f"couldn't reach GitHub ({last})")


def fetch_script(entry, timeout=15):
    """The .tacscript bytes of a pushed script, checked against its sha256."""
    last = None
    for repo in REPOS:
        url = (f"https://raw.githubusercontent.com/{repo}/{BRANCH}/{entry['path']}"
               f"?v={entry['version']}")
        try:
            raw = _get(url, timeout)
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 404:
                raise LiveError(f"couldn't download the script ({e})") from e
        except OSError as e:
            raise LiveError(f"couldn't download the script ({e})") from e
    else:
        raise LiveError(f"the script file isn't on GitHub ({last})")
    if len(raw) > MAX_SCRIPT:
        raise LiveError("the script file is too large")
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise LiveError("the script file doesn't match what was published - try again in a "
                        "few minutes")
    return raw


def save_cache(data):
    try:
        CACHE.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------- developer side ----------
def dev_settings():
    try:
        d = json.loads(DEV_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_dev_settings(d):
    DEV_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def load_draft():
    try:
        d = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
        return validate(d)
    except (OSError, ValueError, LiveError):
        return empty()


def save_draft(d):
    DRAFT_FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def merge_quests(old, new):
    """Quests of a draft event plus newly scanned ones: same title and tab = the same quest
    (the newer scan wins, but keeps loot it had if the new one read none)."""
    out = list(old)
    key = lambda q: (q.get("title"), q.get("tab"))
    where = {key(q): i for i, q in enumerate(out)}
    for q in new:
        if key(q) in where:
            i = where[key(q)]
            out[i] = {**out[i], **q, "loot": q.get("loot") or out[i].get("loot", [])}
        else:
            where[key(q)] = len(out)
            out.append(q)
    return out


API = "https://api.github.com"


def _api(method, path, token, body=None, timeout=15):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={**UA, "Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
                 **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(MAX_BYTES * 2) or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        detail = ""
        try:
            detail = json.loads(e.read(20000)).get("message", "")
        except (ValueError, OSError):
            pass
        hint = {401: "the token isn't valid (expired or mistyped?)",
                403: "the token can't write to the repository (it needs Contents: read and write)",
                404: "the repository wasn't found with this token",
                409: "someone changed the file at the same moment - try again",
                422: "GitHub refused the change"}.get(e.code, "")
        raise LiveError(f"GitHub said {e.code} {detail}" + (f": {hint}" if hint else "")) from e
    except OSError as e:
        raise LiveError(f"couldn't reach GitHub ({e})") from e


def remote(token, repo=REPOS[0]):
    """(data, sha) of the published file, read through the API (no web cache); (empty, None)
    if it doesn't exist yet."""
    r = _api("GET", f"/repos/{repo}/contents/{BOX_PATH}?ref={BRANCH}", token)
    if not r:
        return empty(), None
    raw = base64.b64decode(r.get("content", ""))
    return validate(json.loads(raw.decode("utf-8"))), r.get("sha")


def publish(data, token, message, sha=None, repo=REPOS[0]):
    """Write the file to the repository (one commit on main). Returns the commit's web address."""
    data = validate({**data, "format": FORMAT, "updated": time.strftime("%Y-%m-%d %H:%M")})
    body = {"message": message, "branch": BRANCH,
            "content": base64.b64encode(json.dumps(data, indent=1, ensure_ascii=False)
                                        .encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    r = _api("PUT", f"/repos/{repo}/contents/{BOX_PATH}", token, body)
    save_cache(data)
    return (r.get("commit") or {}).get("html_url", "")


def script_id(name):
    sid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    return sid or "script"


def publish_script(token, name, note, raw, repo=REPOS[0]):
    """Upload a .tacscript (farm.export_script) and list it one version up. Returns
    (commit address, new data)."""
    if len(raw) > MAX_SCRIPT:
        raise LiveError("the script file is too large to push")
    sid = script_id(name)
    path = f"{SCRIPTS_DIR}/{sid}.tacscript"
    old = _api("GET", f"/repos/{repo}/contents/{path}?ref={BRANCH}", token)
    body = {"message": f"Script file: {name}", "branch": BRANCH,
            "content": base64.b64encode(raw).decode()}
    if old and old.get("sha"):
        body["sha"] = old["sha"]
    _api("PUT", f"/repos/{repo}/contents/{path}", token, body)
    data, sha = remote(token, repo)
    prev = data["scripts"].get(sid, {})
    entry = {"name": name, "version": int(prev.get("version", 0)) + 1, "note": note,
             "path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
             "added": time.strftime("%Y-%m-%d")}
    data = {**data, "scripts": {**data["scripts"], sid: entry}}
    url = publish(data, token, f"Scripts: push {name} v{entry['version']}", sha, repo)
    return url, load()


def remove_script(token, sid, repo=REPOS[0]):
    """Take a script off the list (players who added it keep their copy)."""
    data, sha = remote(token, repo)
    scripts = dict(data["scripts"])
    gone = scripts.pop(sid, None)
    url = publish({**data, "scripts": scripts}, token,
                  f"Scripts: remove {gone['name'] if gone else sid}", sha, repo)
    return url, load()


def publish_texts(token, texts, repo=REPOS[0]):
    """Replace the changed wording ({key: text}; keys left out go back to the built-in text)."""
    data, sha = remote(token, repo)
    url = publish({**data, "texts": dict(texts)}, token,
                  f"Texts: {len(texts)} changed from the built-in wording", sha, repo)
    return url, load()


def publish_events(token, add=None, remove=(), repo=REPOS[0]):
    """Read the published file, put in `add` ({id: event}) and take out `remove`, publish.
    Returns (commit address, new data)."""
    data, sha = remote(token, repo)
    events = dict(data["events"])
    for eid in remove:
        events.pop(eid, None)
    for eid, ev in (add or {}).items():
        events[eid] = {**ev, "id": eid, "added": ev.get("added") or time.strftime("%Y-%m-%d")}
    what = ([f"add {', '.join((add[e].get('name') or e) for e in add)}"] if add else []) + \
        ([f"remove {', '.join(remove)}"] if remove else [])
    data = {**data, "events": events}
    url = publish(data, token, f"Box events: {'; '.join(what) or 'update'}", sha, repo)
    return url, load()
