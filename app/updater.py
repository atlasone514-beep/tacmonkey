"""Update check for TACMonkey: asks GitHub for the latest release and fetches its setup.

latest() reads the public "latest release" page of the repository (no account, nothing about
you is sent beyond a normal web request). download() fetches the setup exe into its own temp
folder and checks it against the release's SHA256SUMS.txt; launch() starts it in update mode,
after which the app closes so the setup can replace it.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import farm

REPO = "MohammedEmad638/tacmonkey"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"  # assets must come from here
SETUP_NAME = re.compile(r"^TACMonkey-Setup-[0-9][0-9A-Za-z.\-]*\.exe$")
SUMS_NAME = "SHA256SUMS.txt"
MAX_SETUP = 300_000_000  # refuse anything absurdly large
HEADERS = {"User-Agent": "TACMonkey-Updater", "Accept": "application/vnd.github+json"}


class UpdateError(Exception):
    pass


def parse_version(text):
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); None if it isn't a plain version number."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def newer(candidate, current=farm.VERSION):
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _get(url, timeout):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000)
    except OSError as e:
        raise UpdateError(f"Couldn't reach GitHub ({e}).") from e


def latest(timeout=8):
    """The latest release if it's newer than this app, else None.

    Returns {"version", "page", "notes", "setup": {"name", "url", "size"}, "sums_url"}."""
    try:
        rel = json.loads(_get(API, timeout))
    except ValueError as e:
        raise UpdateError("GitHub sent something that isn't a release.") from e
    if rel.get("draft") or rel.get("prerelease"):
        return None
    version = (rel.get("tag_name") or "").lstrip("v")
    if not newer(version):
        return None
    setup = sums = None
    for a in rel.get("assets", []):
        name, url = a.get("name", ""), a.get("browser_download_url", "")
        if not url.startswith(DOWNLOADS):
            continue
        if SETUP_NAME.match(name):
            setup = {"name": name, "url": url, "size": int(a.get("size") or 0)}
        elif name == SUMS_NAME:
            sums = url
    if not setup or not sums:
        raise UpdateError(f"Release {version} has no setup or checksum file attached.")
    if not 0 < setup["size"] <= MAX_SETUP:
        raise UpdateError(f"Release {version}'s setup has an unexpected size.")
    page = rel.get("html_url") or PAGE
    if not page.startswith(f"https://github.com/{REPO}/"):
        page = PAGE
    return {"version": version, "page": page, "notes": (rel.get("body") or "").strip(),
            "setup": setup, "sums_url": sums}


def expected_hash(info, timeout=15):
    """The setup's SHA-256 as listed in the release's SHA256SUMS.txt."""
    text = _get(info["sums_url"], timeout).decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == info["setup"]["name"] and \
                re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError(f"{SUMS_NAME} doesn't list {info['setup']['name']}.")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(info, progress=lambda done: None, stop=None):
    """Fetch the setup into %TEMP%\\TACMonkey-Update and check it. Returns its path.

    progress(0..1) is called as it goes; stop (a threading.Event) cancels."""
    want = expected_hash(info)
    folder = Path(tempfile.gettempdir()) / "TACMonkey-Update"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / info["setup"]["name"]
    if target.is_file() and sha256(target) == want:
        progress(1.0)
        return target
    part = target.with_suffix(".part")
    size = info["setup"]["size"]
    got = 0
    req = urllib.request.Request(info["setup"]["url"], headers={"User-Agent": HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            while True:
                if stop is not None and stop.is_set():
                    raise UpdateError("Download cancelled.")
                block = r.read(1 << 16)
                if not block:
                    break
                got += len(block)
                if got > size:
                    raise UpdateError("The download is bigger than GitHub said it would be.")
                f.write(block)
                progress(got / size)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download failed ({e}).") from e
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    if got != size or sha256(part) != want:
        part.unlink(missing_ok=True)
        raise UpdateError("The downloaded setup doesn't match its checksum - not starting it. "
                          "Try again later, or download it from the Releases page.")
    part.replace(target)
    return target


def can_self_update():
    """Only the installed TACMonkey.exe updates itself; a copy run from source just gets a link."""
    return bool(getattr(sys, "frozen", False))


def launch(setup):
    """Start the setup in update mode. The caller then closes the app; the setup waits for it."""
    subprocess.Popen([str(setup), "--update", "--app-dir", str(farm.APP_DIR),
                      "--wait-pid", str(os.getpid())], close_fds=True)
