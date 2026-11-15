"""TACMonkey setup: installs the TACMonkey app and the TAC Auto Tap mod (with BepInEx) in one go.

Built into TACMonkey-Setup-<version>.exe by release/build.py. Everything it installs comes from the
bundled payload folder, except BepInEx, which it downloads from the official build server (or
takes from a zip you already have) and checks against a known SHA-256.

What goes where:
    app folder (default %LOCALAPPDATA%\\Programs\\TACMonkey): TACMonkey.exe + _internal\\
        (your buttons, scripts and settings are created next to it and never overwritten)
    game folder: BepInEx 6 be.793 (winhttp.dll, doorstop_config.ini, BepInEx\\, dotnet\\ ...),
        BepInEx\\core\\Il2CppInterop.Generator.dll -> patched copy (original kept as .original),
        BepInEx\\plugins\\TACAutoTap.dll, TACMonkey-install.json (what this setup added)
"""
import ctypes
import hashlib
import json
import os
import queue
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

if getattr(sys, "frozen", False):
    PAYLOAD = Path(sys._MEIPASS) / "payload"
else:  # running from source: use the payload that release/build.py prepared
    PAYLOAD = Path(__file__).resolve().parents[1] / "build" / "payload"

GAME_EXE = "TagaReconstruction.exe"
APP_EXE = "TACMonkey.exe"
RECORD = "TACMonkey-install.json"   # in the game folder: what this setup added
GENERATOR = Path("BepInEx", "core", "Il2CppInterop.Generator.dll")
PLUGIN = Path("BepInEx", "plugins", "TACAutoTap.dll")
BEPINEX_TOP = ["winhttp.dll", "doorstop_config.ini", ".doorstop_version", "changelog.txt"]
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW for helper processes


def load_manifest():
    try:
        return json.loads((PAYLOAD / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


M = load_manifest()


# ---------- helpers ----------
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_running(exe):
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"], capture_output=True,
                             text=True, creationflags=NO_WINDOW, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return exe.lower() in out.lower()


def fixed_drives():
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        root = f"{letter}:\\"
        if mask >> i & 1 and ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
            out.append(root)
    return out


def find_game():
    """The game folder if it's in one of the usual places, else None."""
    tails = [Path("Games", "TagatameLauncher", "TagatameRebuild"),
             Path("TagatameLauncher", "TagatameRebuild"),
             Path("Games", "TagatameRebuild"), Path("TagatameRebuild")]
    roots = fixed_drives() + [os.environ.get(k, "") for k in
                              ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramFiles",
                               "ProgramFiles(x86)")]
    for root in filter(None, roots):
        for tail in tails:
            p = Path(root) / tail
            if (p / GAME_EXE).is_file():
                return p
    return None


def has_bepinex(game):
    return (game / "BepInEx" / "core" / "BepInEx.Core.dll").is_file() and \
        (game / "winhttp.dll").is_file()


def read_record(game):
    try:
        return json.loads((game / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_record(game, record):
    (game / RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")


def inside(base, target):
    base, target = base.resolve(), target.resolve()
    return target == base or base in target.parents


# ---------- install steps (run on the worker thread; say(text) logs, progress(0..1)) ----------
class Installer:
    def __init__(self, say, progress):
        self.say, self.progress = say, progress

    def download_bepinex(self):
        b = M["bepinex"]
        tmp = Path(tempfile.gettempdir()) / "TACMonkey-Setup" / b["file"]
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if tmp.is_file() and sha256(tmp) == b["sha256"]:
            self.say("Using the BepInEx zip downloaded earlier.")
            return tmp
        self.say(f"Downloading BepInEx ({b['size'] / 1e6:.0f} MB) from builds.bepinex.dev ...")
        req = urllib.request.Request(b["url"], headers={"User-Agent": "TACMonkey-Setup"})
        got = 0
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                f.write(block)
                got += len(block)
                self.progress(min(1.0, got / b["size"]))
        if got != b["size"] or sha256(tmp) != b["sha256"]:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("The BepInEx download doesn't match the expected file (checksum). "
                               "Try again, or download it yourself and use 'a zip I already have'.")
        self.say("Download checked (SHA-256 matches).")
        return tmp

    def check_zip(self, path):
        if sha256(path) != M["bepinex"]["sha256"]:
            raise RuntimeError(f"{Path(path).name} isn't BepInEx 6 be.793 IL2CPP win-x64 (checksum "
                               "differs). This setup's loader fix is made for exactly that build.")
        return Path(path)

    def install_bepinex(self, zip_path, game, record):
        self.say("Installing BepInEx into the game folder ...")
        added = []
        with zipfile.ZipFile(zip_path) as z:
            items = z.infolist()
            for n, info in enumerate(items):
                target = game / info.filename
                if not inside(game, target):
                    raise RuntimeError(f"Unsafe path in the zip: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not target.exists():
                    added.append(info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                self.progress((n + 1) / len(items))
        if "BepInEx/core/BepInEx.Core.dll" in added:
            record["bepinex_by_setup"] = True
        record.setdefault("added", [])
        record["added"] = sorted(set(record["added"]) | set(added))
        self.say(f"BepInEx installed ({len(items)} files).")

    def patch_generator(self, game, record):
        gen = game / GENERATOR
        g = M["generator"]
        if not gen.is_file():
            raise RuntimeError("BepInEx\\core\\Il2CppInterop.Generator.dll is missing - reinstall "
                               "BepInEx with this setup.")
        h = sha256(gen)
        if h == g["patched_sha256"]:
            self.say("Loader fix already in place.")
            return
        if h != g["original_sha256"]:
            raise RuntimeError("The installed BepInEx isn't build be.793, so the loader fix doesn't "
                               "fit it. Choose 'Download BepInEx' to put be.793 in.")
        backup = gen.with_name(gen.name + ".original")
        if not backup.exists():
            shutil.copy2(gen, backup)
        shutil.copy2(PAYLOAD / "Il2CppInterop.Generator.dll", gen)
        record["generator_backup"] = str(backup.relative_to(game))
        # a run with the unfixed loader may have left half-made files; let BepInEx rebuild them
        interop = game / "BepInEx" / "interop"
        if interop.is_dir() and inside(game, interop):
            shutil.rmtree(interop, ignore_errors=True)
        self.say("Loader fix installed (original kept as Il2CppInterop.Generator.dll.original).")

    def install_mod(self, game, record):
        target = game / PLUGIN
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PAYLOAD / "TACAutoTap.dll", target)
        record["mod"] = str(PLUGIN)
        record["mod_version"] = M["mod_version"]
        self.say(f"TAC Auto Tap mod {M['mod_version']} installed.")

    def install_app(self, folder, desktop):
        if is_running(APP_EXE):
            raise RuntimeError("TACMonkey is running - close it first.")
        folder.mkdir(parents=True, exist_ok=True)
        old = folder / "_internal"
        if old.is_dir():  # program files only; buttons, scripts and settings stay
            shutil.rmtree(old)
        self.say(f"Installing the app into {folder} ...")
        with zipfile.ZipFile(PAYLOAD / "app.zip") as z:
            items = z.infolist()
            for n, info in enumerate(items):
                target = folder / info.filename
                if not inside(folder, target):
                    raise RuntimeError(f"Unsafe path in app.zip: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                self.progress((n + 1) / len(items))
        shortcuts(folder / APP_EXE, desktop)
        self.say("App installed" + (", with Start menu and desktop shortcuts." if desktop
                                    else ", with a Start menu shortcut."))


def shortcuts(target, desktop, remove=False):
    """Create (or remove) the Start menu and desktop shortcuts. Paths go in as environment
    variables, so nothing in them is read as PowerShell code."""
    script = (
        "$names = @([Environment]::GetFolderPath('Programs'))\n"
        "if ($env:TM_DESKTOP -eq '1') { $names += [Environment]::GetFolderPath('Desktop') }\n"
        "foreach ($d in $names) {\n"
        "  $lnk = Join-Path $d 'TACMonkey.lnk'\n"
        "  if ($env:TM_REMOVE -eq '1') { Remove-Item -LiteralPath $lnk -ErrorAction SilentlyContinue; continue }\n"
        "  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)\n"
        "  $s.TargetPath = $env:TM_TARGET; $s.WorkingDirectory = $env:TM_DIR; $s.Save()\n"
        "}\n")
    env = dict(os.environ, TM_TARGET=str(target), TM_DIR=str(Path(target).parent),
               TM_DESKTOP="1" if desktop else "0", TM_REMOVE="1" if remove else "0")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-Command", script], env=env, creationflags=NO_WINDOW, check=not remove,
                   capture_output=True, timeout=60)


# ---------- window ----------
class Setup:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        root.title(f"TACMonkey Setup {M['version']}")
        root.geometry("640x660")
        root.minsize(560, 600)
        pad = {"padx": 14}

        ttk.Label(root, text=f"TACMonkey {M['version']}", font=("Segoe UI", 15, "bold")).pack(
            anchor="w", pady=(12, 0), **pad)
        ttk.Label(root, text="Installs the farm app and the in-game mod that presses buttons "
                             "without your mouse. Close the game before installing.",
                  wraplength=600).pack(anchor="w", pady=(2, 10), **pad)

        self.game = tk.StringVar(value=str(find_game() or ""))
        self.app_dir = tk.StringVar(value=str(Path(os.environ.get("LOCALAPPDATA", Path.home()))
                                              / "Programs" / "TACMonkey"))
        self.folder_row("Game folder (has TagaReconstruction.exe)", self.game, self.pick_game)
        self.game_note = ttk.Label(root, text="", foreground="#a33")
        self.game_note.pack(anchor="w", **pad)
        self.folder_row("App folder", self.app_dir, self.pick_app)

        box = ttk.LabelFrame(root, text="Install")
        box.pack(fill="x", pady=(10, 0), **pad)
        self.do_app = tk.BooleanVar(value=True)
        self.do_desktop = tk.BooleanVar(value=True)
        self.do_mod = tk.BooleanVar(value=True)
        self.bep = tk.StringVar(value="download")
        self.zip_path = tk.StringVar()
        ttk.Checkbutton(box, text="TACMonkey app", variable=self.do_app,
                        command=self.refresh).pack(anchor="w", padx=8, pady=(6, 0))
        self.desktop_cb = ttk.Checkbutton(box, text="Desktop shortcut", variable=self.do_desktop)
        self.desktop_cb.pack(anchor="w", padx=30)
        ttk.Checkbutton(box, text=f"TAC Auto Tap mod {M['mod_version']} (+ the loader fix this game "
                                  "needs)", variable=self.do_mod,
                        command=self.refresh).pack(anchor="w", padx=8, pady=(8, 0))
        b = M["bepinex"]
        self.bep_buttons = [
            ttk.Radiobutton(box, text=f"Download BepInEx 6 be.793 from builds.bepinex.dev "
                                      f"({b['size'] / 1e6:.0f} MB)", value="download",
                            variable=self.bep, command=self.refresh),
            ttk.Radiobutton(box, text="Use a BepInEx zip I already have", value="zip",
                            variable=self.bep, command=self.refresh),
            ttk.Radiobutton(box, text="BepInEx is already installed in the game", value="have",
                            variable=self.bep, command=self.refresh)]
        for rb in self.bep_buttons:
            rb.pack(anchor="w", padx=30)
        zrow = ttk.Frame(box)
        zrow.pack(fill="x", padx=50, pady=(0, 8))
        self.zip_entry = ttk.Entry(zrow, textvariable=self.zip_path)
        self.zip_entry.pack(side="left", fill="x", expand=True)
        self.zip_btn = ttk.Button(zrow, text="Browse...", command=self.pick_zip)
        self.zip_btn.pack(side="left", padx=(6, 0))

        self.bar = ttk.Progressbar(root, maximum=1.0)
        self.bar.pack(fill="x", pady=(12, 4), **pad)
        self.text = tk.Text(root, height=9, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.text.pack(fill="both", expand=True, **pad)
        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=12, **pad)
        self.install_btn = ttk.Button(buttons, text="Install", command=self.install)
        self.install_btn.pack(side="right")
        self.remove_btn = ttk.Button(buttons, text="Uninstall...", command=self.uninstall)
        self.remove_btn.pack(side="left")
        self.game.trace_add("write", lambda *_: self.refresh())
        if self.game.get() and has_bepinex(Path(self.game.get())):
            self.bep.set("have")
        self.refresh()
        root.after(100, self.poll)

    def folder_row(self, label, var, pick):
        ttk.Label(self.root, text=label).pack(anchor="w", padx=14, pady=(6, 0))
        row = ttk.Frame(self.root)
        row.pack(fill="x", padx=14)
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=pick).pack(side="left", padx=(6, 0))

    def pick_game(self):
        d = filedialog.askdirectory(parent=self.root, title="Folder with TagaReconstruction.exe")
        if d:
            self.game.set(str(Path(d)))
            if has_bepinex(Path(d)):
                self.bep.set("have")

    def pick_app(self):
        d = filedialog.askdirectory(parent=self.root, title="Where to put the TACMonkey app")
        if d:
            self.app_dir.set(str(Path(d)))

    def pick_zip(self):
        f = filedialog.askopenfilename(parent=self.root, title="BepInEx be.793 zip",
                                       filetypes=[("Zip", "*.zip")])
        if f:
            self.zip_path.set(f)
            self.bep.set("zip")

    def refresh(self):
        game = Path(self.game.get()) if self.game.get() else None
        ok = bool(game and (game / GAME_EXE).is_file())
        note = "" if ok else ("Pick the game folder (the one with TagaReconstruction.exe)."
                              if self.do_mod.get() else "")
        if ok and self.do_mod.get() and self.bep.get() == "have" and not has_bepinex(game):
            note = "BepInEx isn't in this game folder yet - choose Download."
        self.game_note.config(text=note)
        mod = self.do_mod.get() and not self.busy
        for rb in self.bep_buttons:
            rb.state(["!disabled"] if mod else ["disabled"])
        zip_on = mod and self.bep.get() == "zip"
        self.zip_entry.state(["!disabled"] if zip_on else ["disabled"])
        self.zip_btn.state(["!disabled"] if zip_on else ["disabled"])
        self.desktop_cb.state(["!disabled"] if self.do_app.get() and not self.busy else ["disabled"])
        can = not self.busy and (self.do_app.get() or (self.do_mod.get() and ok))
        self.install_btn.state(["!disabled"] if can else ["disabled"])
        self.remove_btn.state(["disabled"] if self.busy else ["!disabled"])

    def say(self, text):
        self.q.put(("log", text))

    def progress(self, value):
        self.q.put(("bar", value))

    def poll(self):
        while True:
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "log":
                self.text.config(state="normal")
                self.text.insert("end", msg[1] + "\n")
                self.text.see("end")
                self.text.config(state="disabled")
            elif msg[0] == "bar":
                self.bar["value"] = msg[1]
            elif msg[0] == "done":
                self.busy = False
                self.refresh()
                ok, text = msg[1], msg[2]
                (messagebox.showinfo if ok else messagebox.showerror)(
                    "TACMonkey Setup", text, parent=self.root)
        self.root.after(100, self.poll)

    # ---------- install / uninstall ----------
    def install(self):
        game = Path(self.game.get()) if self.game.get() else None
        do_mod, bep = self.do_mod.get(), self.bep.get()
        if do_mod:
            if not (game and (game / GAME_EXE).is_file()):
                messagebox.showerror("TACMonkey Setup", "Pick the game folder first.", parent=self.root)
                return
            if is_running(GAME_EXE):
                messagebox.showerror("TACMonkey Setup", "The game is running - close it first.",
                                     parent=self.root)
                return
            if bep == "zip" and not Path(self.zip_path.get()).is_file():
                messagebox.showerror("TACMonkey Setup", "Pick your BepInEx zip.", parent=self.root)
                return
            if bep == "have" and not has_bepinex(game):
                messagebox.showerror("TACMonkey Setup", "BepInEx isn't installed in that game folder "
                                     "- choose Download.", parent=self.root)
                return
        app, desktop = (Path(self.app_dir.get()) if self.do_app.get() else None), self.do_desktop.get()
        self.busy = True
        self.refresh()
        threading.Thread(target=self.install_job, args=(game, do_mod, bep, app, desktop),
                         daemon=True).start()

    def install_job(self, game, do_mod, bep, app, desktop):
        steps = Installer(self.say, self.progress)
        try:
            if do_mod:
                record = read_record(game)
                if bep == "download":
                    steps.install_bepinex(steps.download_bepinex(), game, record)
                elif bep == "zip":
                    steps.install_bepinex(steps.check_zip(self.zip_path.get()), game, record)
                steps.patch_generator(game, record)
                steps.install_mod(game, record)
                record["setup_version"] = M["version"]
                write_record(game, record)
            if app:
                steps.install_app(app, desktop)
            self.progress(1.0)
            text = "Done.\n\n"
            if do_mod:
                text += ("Start the game once. The first start with BepInEx takes a minute or two "
                         "while it prepares (a console window may show progress).\n\n")
            if app:
                text += "Open TACMonkey from the Start menu" + (" or your desktop." if desktop else ".")
            self.say("All done.")
            self.q.put(("done", True, text))
        except PermissionError as e:
            self.q.put(("done", False, f"No permission to write {e.filename}.\n\nRun the setup as "
                        "administrator (right-click > Run as administrator), or pick folders you "
                        "can write to."))
        except Exception as e:  # report anything else plainly
            self.say(f"Failed: {e}")
            self.q.put(("done", False, f"Setup failed:\n{e}"))

    def uninstall(self):
        game = Path(self.game.get()) if self.game.get() else None
        app = Path(self.app_dir.get()) if self.app_dir.get() else None
        record = read_record(game) if game else {}
        mod_there = bool(game and (game / PLUGIN).is_file())
        app_there = bool(app and (app / APP_EXE).is_file())
        if not mod_there and not app_there and not record:
            messagebox.showinfo("Uninstall", "Nothing from TACMonkey found in those folders.",
                                parent=self.root)
            return
        remove_mod = mod_there or bool(record)
        if remove_mod:
            if is_running(GAME_EXE):
                messagebox.showerror("Uninstall", "The game is running - close it first.",
                                     parent=self.root)
                return
            remove_mod = messagebox.askyesno("Uninstall", "Remove the TAC Auto Tap mod from the game?",
                                             parent=self.root)
        remove_bep = remove_mod and record.get("bepinex_by_setup") and messagebox.askyesno(
            "Uninstall", "Also remove BepInEx? (It was installed by this setup.)", parent=self.root)
        remove_app = app_there and messagebox.askyesno(
            "Uninstall", f"Remove the TACMonkey app from {app}?\n\nYour buttons, scripts and "
            "settings in that folder are kept.", parent=self.root)
        if not (remove_mod or remove_app):
            return
        try:
            done = []
            if remove_mod:
                (game / PLUGIN).unlink(missing_ok=True)
                backup = game / GENERATOR.with_name(GENERATOR.name + ".original")
                if backup.is_file():
                    shutil.copy2(backup, game / GENERATOR)
                    backup.unlink()
                done.append("mod removed, original loader file put back")
                if remove_bep:
                    for name in BEPINEX_TOP:
                        if name in record.get("added", []):
                            (game / name).unlink(missing_ok=True)
                    for name in ("BepInEx", "dotnet"):
                        if inside(game, game / name):
                            shutil.rmtree(game / name, ignore_errors=True)
                    done.append("BepInEx removed")
                (game / RECORD).unlink(missing_ok=True)
            if remove_app:
                if is_running(APP_EXE):
                    raise RuntimeError("TACMonkey is running - close it first.")
                (app / APP_EXE).unlink(missing_ok=True)
                shutil.rmtree(app / "_internal", ignore_errors=True)
                shortcuts(app / APP_EXE, True, remove=True)
                done.append("app removed (your buttons and scripts are still in its folder)")
            self.say("Uninstall: " + "; ".join(done) + ".")
            messagebox.showinfo("Uninstall", "Done:\n- " + "\n- ".join(done), parent=self.root)
        except Exception as e:
            messagebox.showerror("Uninstall", f"Uninstall failed:\n{e}", parent=self.root)


def main():
    root = tk.Tk()
    if M is None:
        root.withdraw()
        messagebox.showerror("TACMonkey Setup", f"Setup files missing ({PAYLOAD}). Build the setup "
                             "with release/build.py.")
        return
    Setup(root)
    root.mainloop()


if __name__ == "__main__":
    main()
