"""Control window for farm.py: start / pause / stop, run limit, live status and log.

Start it by double-clicking this file, or:  python farm_ui.pyw
"""
import base64
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter import font as tkfont

try:
    import farm
except Exception as e:  # e.g. opencv missing - pythonw has no console to show it
    tk.Tk().withdraw()
    messagebox.showerror("TACMonkey",
                         f"Couldn't load farm.py:\n{e}\n\nSetup: pip install opencv-python numpy")
    raise SystemExit(1)
import updater

# Claude's dark theme: neutral near-black greys, blue accent, saturated green for Start
BG, PANEL, FIELD = "#1c1c1c", "#242424", "#2f2f2f"
FG, MUTED, DARK = "#ececec", "#9b9b9b", "#151515"
GREEN, YELLOW, ORANGE, RED, GREY, BLUE = ("#12a312", "#e8b33c", "#e8833f", "#e5534b",
                                          "#5c5c5c", "#5aa2f0")
ACCENT_TEXT = "#8cc2ff"   # blue text on the selected page's tint
ELEMENT_COLORS = {"Fire": "#e5534b", "Water": "#5aa2f0", "Thunder": "#e8b33c",
                  "Wind": "#3fb950", "Light": "#f0e6c0", "Dark": "#b48ce6"}
FONT = "Segoe UI"
SETTINGS = farm.APP_DIR / "ui_settings.json"  # remembers script and checkboxes
BAD_CHARS = set('\\/:*?"<>|')


def state_color(state):
    for prefix, color in (("Running", GREEN), ("Paused", YELLOW), ("Waiting", ORANGE),
                          ("Stuck", RED)):
        if state.startswith(prefix):
            return color
    return GREY


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.skip_merc_event = threading.Event()  # kept across runs; flipped live by the checkbox
        self.state = "Idle"
        self.runs = 0
        self.run_time = 0.0
        self.tick_from = time.time()
        self.import_asked = False  # first-run "use your existing buttons?" was shown
        self.update_info = None    # the newer release found by the update check
        self.update_busy = False   # downloading it
        self.editor_view = "flow"  # Customize opens as "flow" (flowchart) or "list" (priority)
        self.tidy_asked = False    # the one-time "rename numbered buttons?" offer was shown

        root.title(f"TACMonkey {farm.VERSION}")
        root.configure(bg=BG)
        root.minsize(720, 660)
        root.geometry("820x800")
        self.build()
        self.load_settings()
        self.refresh_goal()
        self.set_state("Idle", "Open the game on its quest map, then press Start.")
        self.update_buttons()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        root.after(1000, self.tick)
        root.after(400, self.first_run)
        root.after(1200, self.offer_tidy)
        if self.check_updates.get():
            root.after(1500, lambda: self.check_for_updates(manual=False))
        threading.Thread(target=self.check_mod, daemon=True).start()

    def check_mod(self):
        """If the game is open with a different mod version than this app expects, say so."""
        problem = farm.mod_mismatch(farm.mod_status())
        if problem:
            self.q.put(("log", problem, "warn"))

    # ---------- updates ----------
    def build_update_bar(self):
        """The 'new version available' strip at the top; packed only when there is one."""
        bar = tk.Frame(self.root, bg=BLUE, padx=14, pady=8)
        self.update_text = tk.Label(bar, bg=BLUE, fg=DARK, font=(FONT, 10, "bold"), anchor="w",
                                    justify="left", wraplength=260)
        self.update_text.pack(side="left", fill="x", expand=True)
        self.update_buttons_ = []
        for text, command in (("Later", self.hide_update), ("What's new", self.update_notes),
                              ("Update", self.do_update)):
            b = tk.Button(bar, text=text, command=command, bg=DARK, fg=FG, activebackground=PANEL,
                          activeforeground=FG, disabledforeground=MUTED, relief="flat", bd=0,
                          font=(FONT, 9, "bold" if text == "Update" else "normal"), padx=8, pady=3,
                          cursor="hand2")
            b.color = DARK
            b.pack(side="right", padx=(6, 0))
            self.update_buttons_.append(b)
        self.update_btn = self.update_buttons_[-1]
        self.update_bar = bar

    def check_for_updates(self, manual=True):
        """Ask GitHub for a newer release on a worker thread; the answer comes back via poll."""
        if self.update_busy:
            return
        if manual:
            self.log("Checking for updates...", "muted")

        def job():
            try:
                self.q.put(("update", updater.latest(), manual))
            except updater.UpdateError as e:
                self.q.put(("update_error", str(e), manual))
            except Exception as e:
                self.q.put(("update_error", f"{e!r}", manual))

        threading.Thread(target=job, daemon=True).start()

    def show_update(self, info):
        self.update_info = info
        self.update_text.config(text=f"TACMonkey {info['version']} is available")
        self.enable(self.update_btn, True)
        if not self.update_bar.winfo_ismapped():
            self.update_bar.pack(fill="x", before=self.body)
        self.log(f"Update available: TACMonkey {info['version']}.", "info")

    def hide_update(self):
        if not self.update_busy:
            self.update_bar.pack_forget()

    def update_notes(self):
        webbrowser.open(self.update_info["page"] if self.update_info else updater.PAGE)

    def do_update(self):
        info = self.update_info
        if not info or self.update_busy:
            return
        if not updater.can_self_update():
            self.log("This copy runs from source - get the new version from the Releases page.",
                     "info")
            webbrowser.open(info["page"])
            return
        if self.running() or self.genesis_running():
            messagebox.showinfo("Update", "Stop the farm first, then press Update.",
                                parent=self.root)
            return
        self.update_busy = True
        self.enable(self.update_btn, False)
        size = info["setup"]["size"] / 1e6
        self.update_text.config(text=f"Downloading TACMonkey {info['version']} ({size:.0f} MB)...")
        self.log(f"Downloading {info['setup']['name']} from GitHub ({size:.0f} MB)...", "muted")
        shown = [-1]

        def progress(done):
            pct = int(done * 100)
            if pct != shown[0]:
                shown[0] = pct
                self.q.put(("update_progress", pct))

        def job():
            try:
                self.q.put(("update_ready", updater.download(info, progress)))
            except updater.UpdateError as e:
                self.q.put(("update_failed", str(e)))
            except Exception as e:
                self.q.put(("update_failed", f"{e!r}"))

        threading.Thread(target=job, daemon=True).start()

    def update_ready(self, setup):
        self.update_busy = False
        self.log("Download checked (SHA-256 matches the release).", "good")
        self.update_text.config(text=f"TACMonkey {self.update_info['version']} is ready to install.")
        self.enable(self.update_btn, True)
        if not messagebox.askyesno(
                "Update", f"TACMonkey will close and the setup will update it to "
                f"{self.update_info['version']}, then open it again.\n\nIf the game is open, close "
                "it too, so the mod can be updated.\n\nWindows may say it protected your PC - "
                "choose More info > Run anyway.\n\nUpdate now?", parent=self.root):
            return
        try:
            updater.launch(setup)
        except OSError as e:
            self.log(f"Couldn't start the setup: {e}", "bad")
            return
        self.close()

    def update_failed(self, text):
        self.update_busy = False
        self.log(f"Update failed: {text}", "bad")
        self.update_text.config(text="The update didn't download. Try again, or use What's new "
                                     "to get it from the Releases page.")
        self.enable(self.update_btn, True)

    def first_run(self):
        """No buttons captured yet (a fresh copy): offer to bring in existing ones, once."""
        if farm.library() or self.import_asked:
            return
        self.import_asked = True
        self.save_settings()
        if messagebox.askyesno(
                "No buttons yet", "This copy has no button images yet.\n\nDo you want to use "
                "buttons you already have? Pick the folder of your other copy (the one with a "
                "buttons and/or scripts folder in it).\n\nNo = start empty and capture your own "
                "in Customize. You can import later from Customize too.", parent=self.root):
            self.import_from(self.root)

    def offer_tidy(self):
        """Old numbered button names (06_go): offer once to rename them to plain names."""
        if not self.tidy_asked and farm.numbered_images():
            self.tidy_names(first=True)

    def tidy_names(self, first=False):
        ids = farm.numbered_images()
        if not ids:
            if not first:
                messagebox.showinfo("Tidy button names", "No numbered button names left.",
                                    parent=self.root)
            return
        if self.running() or self.genesis_running():
            messagebox.showinfo("Tidy button names", "Stop the farm first.", parent=self.root)
            return
        ok = messagebox.askyesno(
            "Tidy button names", f"{len(ids)} button images still have old number names (like "
            "06_go or 09_endquest).\n\nRename them to plain names (go, end quest, ...)?\n\n"
            "Every script keeps running exactly as before: its priority order and run counter "
            "are kept, and what the numbers 01, 08 and 10 did becomes ticks on the step's card "
            "in Customize.\n\nA backup zip of your buttons and scripts is saved first."
            + ("\n\nYou can also do this later from the Buttons page." if first else ""),
            parent=self.root)
        if first:
            self.tidy_asked = True
            self.save_settings()
        if not ok:
            return
        try:
            count, backup = farm.tidy_buttons()
        except Exception as e:
            self.log(f"Tidy button names failed: {e!r}", "bad")
            messagebox.showerror("Tidy button names", f"Something went wrong:\n{e}\n\nYour "
                                 "backup zip (if one was made) is in the TACMonkey folder.",
                                 parent=self.root)
            return
        self.log(f"Renamed {count} button images to plain names (backup: "
                 f"{backup.name if backup else '-'})", "good")
        self.refresh_scripts()
        if self.customizer and self.customizer.win.winfo_exists():
            self.customizer.refresh()
        self.refresh_buttons_page()

    def import_from(self, parent):
        """Ask for a folder and copy its buttons and scripts in. True if anything came in."""
        folder = filedialog.askdirectory(parent=parent, title="Folder with your buttons / scripts")
        if not folder:
            return False
        images, scripts, skipped = farm.import_buttons(folder)
        if not images and not scripts:
            messagebox.showinfo("Import buttons", (
                f"Everything there is already here ({skipped} files)." if skipped else
                "No button images found there. Pick the folder that holds the buttons and/or "
                "scripts folders."), parent=parent)
            return False
        self.log(f"Imported {images} button images ({', '.join(scripts)})"
                 + (f", kept {skipped} files that were already here" if skipped else ""), "good")
        self.refresh_scripts()
        return True

    # ---------- layout ----------
    def card(self, parent, **pack):
        frame = tk.Frame(parent, bg=PANEL, padx=16, pady=12)
        frame.pack(fill="x", padx=12, **pack)
        return frame

    def button(self, parent, text, color, command):
        b = tk.Button(parent, text=text, command=command, bg=color, fg=DARK,
                      activebackground=color, activeforeground=DARK, relief="flat", bd=0,
                      font=(FONT, 10, "bold"), padx=14, pady=7, cursor="hand2")
        b.color = color
        return b

    def small_button(self, parent, text, command):
        b = tk.Button(parent, text=text, command=command, bg=FIELD, fg=FG, activebackground=GREY,
                      activeforeground=FG, disabledforeground=MUTED, relief="flat", bd=0,
                      font=(FONT, 9), padx=8, pady=3, cursor="hand2")
        b.color = FIELD
        return b

    def label(self, parent, text="", size=10, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    def spinbox(self, parent, var, width=6, **kw):
        return tk.Spinbox(parent, textvariable=var, width=width, bg=FIELD, fg=FG, relief="flat",
                          buttonbackground=FIELD, insertbackground=FG, justify="center",
                          disabledbackground=PANEL, disabledforeground=MUTED,
                          font=(FONT, 10), **kw)

    def check(self, parent, text, var, command=None):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=PANEL, fg=FG,
                              selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                              disabledforeground=MUTED, font=(FONT, 10), anchor="w",
                              highlightthickness=0, bd=0)

    # ---------- layout: sidebar + pages ----------
    PAGES = (  # key, icon (Segoe Fluent Icons / MDL2 Assets glyph), label
        ("story", "", "Scripts"),
        ("genesis", "", "Genesis"),
        ("ex", "", "Ex"),
        ("leaves", "", "Leaves"),
        ("buttons", "", "Buttons"),
        ("settings", "", "Settings"),
    )
    PAGE_MODE = {"genesis": "hard", "ex": "extra"}   # pages that run the Genesis farm
    NAV_SEL, NAV_HOVER = "#1d3857", "#2c2c2c"

    def build(self):
        root = self.root
        self.build_update_bar()
        families = set(tkfont.families(root))
        self.icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets")
                               if f in families), None)
        self.page = "story"
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)
        self.body = body
        self.build_sidebar(body)

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.build_status(main)
        # bottom part first, so the page in the middle is what shrinks
        self.label(main, "F8 pause / resume  ·  F9 stop  —  these work from any window",
                   size=8, color=MUTED).pack(side="bottom", pady=(4, 8))
        self.build_log(main)
        self.build_controls(main)

        self.page_box = tk.Frame(main, bg=BG)
        self.page_box.pack(fill="both", expand=True)
        self.pages = {}
        for key, _, _ in self.PAGES:
            self.pages[key] = tk.Frame(self.page_box, bg=BG)
        self.build_story(self.pages["story"])
        self.build_genesis()
        self.build_leaves(self.pages["leaves"])
        self.build_buttons_page(self.pages["buttons"])
        self.build_settings(self.pages["settings"])
        self.show_page("story")

    def build_sidebar(self, parent):
        side = tk.Frame(parent, bg=PANEL, width=170)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        head = tk.Frame(side, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(16, 14))
        self.logo = None
        try:
            img = tk.PhotoImage(file=str(farm.RES_DIR / "icon.png"))
            self.logo = img.subsample(max(1, img.width() // 26))
            tk.Label(head, image=self.logo, bg=PANEL).pack(side="left", padx=(0, 8))
        except tk.TclError:
            pass
        self.label(head, "TACMonkey", size=11, bold=True).pack(side="left")
        self.nav = {}
        for key, glyph, text in self.PAGES:
            if key == "settings":
                tk.Frame(side, bg=PANEL).pack(fill="both", expand=True)
            self.nav_item(side, key, glyph, text)
        self.version_label = self.label(side, f"v{farm.VERSION}", size=8, color=MUTED, anchor="w")
        self.version_label.pack(fill="x", padx=18, pady=(4, 12))

    def nav_item(self, parent, key, glyph, text):
        row = tk.Frame(parent, bg=PANEL, cursor="hand2", padx=10, pady=7)
        row.pack(fill="x", padx=8, pady=1)
        icon = tk.Label(row, text=glyph if self.icon_font else "•", bg=PANEL, fg=MUTED,
                        font=(self.icon_font or FONT, 12), width=2, cursor="hand2")
        icon.pack(side="left")
        name = tk.Label(row, text=text, bg=PANEL, fg=FG, font=(FONT, 10), anchor="w",
                        cursor="hand2")
        name.pack(side="left", padx=(6, 0))
        badge = tk.Label(row, text="", bg=FIELD, fg=MUTED, font=(FONT, 8, "bold"), padx=6,
                         cursor="hand2")
        for w in (row, icon, name, badge):
            w.bind("<Button-1>", lambda _e, k=key: self.show_page(k))
            w.bind("<Enter>", lambda _e, k=key: self.nav_paint(k))
            w.bind("<Leave>", lambda _e, k=key: self.root.after(10, self.nav_paint, k))
        self.nav[key] = {"row": row, "icon": icon, "name": name, "badge": badge}

    def nav_paint(self, key):
        n = self.nav[key]
        under = self.root.winfo_containing(*self.root.winfo_pointerxy())
        hover = under is not None and (under is n["row"] or under.master is n["row"])
        on = key == self.page
        bg = self.NAV_SEL if on else self.NAV_HOVER if hover else PANEL
        for part in ("row", "icon", "name"):
            n[part].config(bg=bg)
        n["icon"].config(fg=ACCENT_TEXT if on else MUTED)
        n["name"].config(font=(FONT, 10, "bold" if on else "normal"),
                         fg=ACCENT_TEXT if on else FG)

    def set_badge(self, key, text):
        badge = self.nav[key]["badge"]
        text = str(text) if text not in (None, "", 0) else ""
        badge.config(text=text)
        if text and not badge.winfo_manager():
            badge.pack(side="right")
        elif not text and badge.winfo_manager():
            badge.pack_forget()

    def show_page(self, key):
        if key not in self.pages:
            key = "story"
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self.page = key
        if key in self.PAGE_MODE and not self.genesis_running():
            self.genesis_mode = self.PAGE_MODE[key]
        if key == "buttons":
            self.refresh_buttons_page()
        for k in self.nav:
            self.nav_paint(k)
        self.update_buttons()

    def build_status(self, parent):
        status = tk.Frame(parent, bg=PANEL, padx=16, pady=10)
        status.pack(fill="x", padx=12, pady=(12, 0))
        self.status_card = status
        left = tk.Frame(status, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)
        top = tk.Frame(left, bg=PANEL)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 13, 13, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.status_label = self.label(top, size=13, bold=True, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.detail_label = self.label(left, size=9, color=MUTED, anchor="w", justify="left",
                                       wraplength=300)
        self.detail_label.pack(fill="x", pady=(2, 0))
        self.stat_values = {}
        for name in ("Runs / hour", "Time", "Runs"):   # packed right to left
            box = tk.Frame(status, bg=PANEL)
            box.pack(side="right", padx=(16, 0))
            self.label(box, name.upper(), size=8, color=MUTED, anchor="w").pack(anchor="w")
            value = self.label(box, "0" if name == "Runs" else "-", size=15, bold=True)
            value.pack(anchor="w")
            self.stat_values[name] = value

    def build_controls(self, parent):
        controls = tk.Frame(parent, bg=BG)
        controls.pack(side="bottom", fill="x", padx=12, pady=(8, 0))
        self.start_btn = self.button(controls, "Start script", GREEN, self.start_any)
        self.pause_btn = self.button(controls, "Pause", FIELD, self.pause_any)
        self.stop_btn = self.button(controls, "Stop", FIELD, self.stop_any)
        for b in (self.pause_btn, self.stop_btn):   # quiet grey buttons, like Claude's
            b.config(fg=FG, activeforeground=FG, activebackground=GREY, disabledforeground=GREY)
        self.start_btn.grid(row=0, column=0, sticky="ew")
        self.pause_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.stop_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        controls.columnconfigure(0, weight=2, uniform="ctl")   # widths stay put when the
        controls.columnconfigure(1, weight=1, uniform="ctl")   # Start label changes
        controls.columnconfigure(2, weight=1, uniform="ctl")

    def build_log(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(side="bottom", fill="x")
        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x", padx=14, pady=(10, 4))
        self.label(head, "LOG", size=8, color=MUTED).pack(side="left")
        clear = self.label(head, "clear", size=8, color=MUTED, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda _: self.log_box.delete("1.0", "end"))
        box = tk.Frame(wrap, bg=DARK)
        box.pack(fill="x", padx=12)
        scroll = tk.Scrollbar(box)
        scroll.pack(side="right", fill="y")
        self.log_box = tk.Text(box, bg=DARK, fg=FG, relief="flat", bd=0, wrap="word",
                               font=("Consolas", 9), padx=10, pady=8, height=8,
                               yscrollcommand=scroll.set, insertbackground=FG)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log_box.yview)
        for tag, color in (("good", GREEN), ("muted", MUTED), ("warn", ORANGE), ("bad", RED),
                           ("info", BLUE)):
            self.log_box.tag_config(tag, foreground=color)

    def page_card(self, page, title, **pack):
        card = self.card(page, pady=(10, 0), **pack)
        self.label(card, title.upper(), size=8, color=MUTED).pack(anchor="w", pady=(0, 6))
        return card

    def section(self, parent, text):
        self.label(parent, text.upper(), size=8, color=MUTED).pack(anchor="w", pady=(10, 2))

    def wip_team_row(self, parent):
        """The team switch (to-do point 7) is a work in progress: shown, but not usable yet."""
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.label(row, "Team", color=MUTED).pack(side="left")
        tk.Entry(row, width=12, state="disabled", disabledbackground=FIELD, relief="flat",
                 font=(FONT, 10)).pack(side="left", padx=6)
        tk.Label(row, text="WIP", bg=YELLOW, fg=DARK, font=(FONT, 7, "bold"), padx=5).pack(
            side="left")
        self.label(row, "switch to a team by name - not built yet", size=8, color=MUTED).pack(
            side="left", padx=6)

    # ---------- pages ----------
    def build_story(self, page):
        opts = self.page_card(page, "Scripts")
        self.script = tk.StringVar(value=farm.DEFAULT_SCRIPT)
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "Script").pack(side="left")
        self.script_menu = tk.OptionMenu(row, self.script, farm.DEFAULT_SCRIPT)
        self.script_menu.config(bg=FIELD, fg=FG, activebackground=GREY, activeforeground=FG,
                                relief="flat", bd=0, highlightthickness=0, font=(FONT, 10),
                                width=16, anchor="w", disabledforeground=MUTED)
        self.script_menu["menu"].config(bg=FIELD, fg=FG, activebackground=BLUE,
                                        activeforeground=DARK, font=(FONT, 10), bd=0)
        self.script_menu.pack(side="left", padx=6)
        self.customizer = None
        self.grab_btn = self.small_button(row, "Customize", self.customize)
        self.new_btn = self.small_button(row, "New", self.new_script)
        self.import_btn = self.small_button(row, "Import", lambda: self.import_script(self.root))
        self.folder_btn = self.small_button(row, "Folder", self.open_folder)
        for b in (self.grab_btn, self.new_btn, self.import_btn, self.folder_btn):
            b.pack(side="left", padx=(0, 4))
        self.refresh_scripts()
        self.max_runs = tk.StringVar(value="0")
        self.threshold = tk.StringVar(value=f"{farm.THRESHOLD:.2f}")
        self.act_switch = tk.BooleanVar(value=True)
        self.on_top = tk.BooleanVar(value=False)
        self.skip_merc = tk.BooleanVar(value=False)
        self.section(opts, "Stop when")
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "Runs", width=5, anchor="w").pack(side="left")
        self.max_spin = self.spinbox(row, self.max_runs, from_=0, to=9999, increment=1)
        self.max_spin.pack(side="left", padx=6)
        self.label(row, "0 = never", color=MUTED).pack(side="left")
        # item goal: "Item  I have [2000] of [icon] Mechanical Wing Piece  Capture  From file  Clear"
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        self.label(row, "Item", width=5, anchor="w").pack(side="left")
        self.label(row, "I have").pack(side="left")
        self.goal_count = tk.StringVar(value="")
        self.goal_spin = self.spinbox(row, self.goal_count, from_=0, to=999999, increment=10,
                                      width=7)
        self.goal_spin.pack(side="left", padx=6)
        self.goal_count.set("")
        self.label(row, "of").pack(side="left")
        self.goal_thumb = tk.Label(row, bg=DARK, width=6, height=1, text="none", fg=MUTED,
                                   font=(FONT, 8))
        self.goal_thumb.pack(side="left", padx=6)
        self.goal_name = self.label(row, "", size=9, color=MUTED)
        self.goal_name.pack(side="left")
        self.goal_buttons = [self.small_button(row, "Clear", self.goal_clear),
                             self.small_button(row, "From file", self.goal_from_file),
                             self.small_button(row, "Capture", self.goal_capture)]
        for b in self.goal_buttons:
            b.pack(side="right", padx=(4, 0))
        self.goal_count.trace_add("write", lambda *_: self.goal_count_changed())
        self.goal_loading = False
        self.label(opts, "Item: on each results screen the farm finds the item's icon and reads "
                         "its \"(Owned: N)\", then stops there once you have that many. "
                         "Saved with the script. Blank or 0 = no item goal.", size=9,
                   color=MUTED, wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))
        self.section(opts, "While running")
        self.act_check = self.check(opts, "Go to the next act when one is finished",
                                    self.act_switch)
        self.act_check.pack(fill="x")
        self.check(opts, "Skip the mercenary (go without hiring) - works mid-run",
                   self.skip_merc, self.toggle_merc).pack(fill="x")
        self.wip_team_row(opts)
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x", pady=(12, 0))
        self.check_btn = self.button(row, "Check screen", BLUE, self.check_screen)
        self.check_btn.pack(side="left")
        self.label(row, "  scores each button image on the game now", size=9,
                   color=MUTED).pack(side="left")

    def build_leaves(self, page):
        card = self.page_card(page, "Leaves - Alchemy Drops for AP refills")
        self.label(card, "Used by the Genesis and Ex farms and the AP refill action. Leave a "
                         "limit blank for none. A limit stops the farm instead of refilling.",
                   size=9, color=MUTED, wraplength=520, justify="left").pack(anchor="w")
        self.leaf_per, self.leaf_most, self.leaf_floor = (tk.StringVar(value="7"),
                                                          tk.StringVar(), tk.StringVar())
        self.leaf_spins = []
        for var, lo, text, hint in ((self.leaf_per, 1, "Per refill", "Alchemy Drops"),
                                    (self.leaf_most, 0, "Max / session", "blank = no limit"),
                                    (self.leaf_floor, 0, "Stop below", "owned")):
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=(8, 0))
            self.label(row, text, width=13, anchor="w").pack(side="left")
            sp = self.spinbox(row, var, from_=lo, to=9999, increment=1, width=5)
            sp.pack(side="left", padx=(0, 8))
            self.label(row, hint, size=9, color=MUTED).pack(side="left")
            self.leaf_spins.append(sp)
        self.leaf_most.set("")   # a spinbox fills a blank variable with its lowest value
        self.leaf_floor.set("")
        self.leaf_per.trace_add("write", lambda *_: self.set_badge("leaves", self.leaf_per.get()))
        self.root.after_idle(lambda: self.set_badge("leaves", self.leaf_per.get()))
        self.section(card, "This session")
        self.leaf_session = self.label(card, "No refills yet.", size=10, anchor="w")
        self.leaf_session.pack(anchor="w")

    def build_buttons_page(self, page):
        card = self.page_card(page, "Buttons")
        self.buttons_summary = self.label(card, "", size=10, anchor="w")
        self.buttons_summary.pack(anchor="w")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        for text, command in (("Customize script", self.customize),
                              ("Import buttons", lambda: self.import_from(self.root)),
                              ("Import script", lambda: self.import_script(self.root)),
                              ("Open folder", self.open_folder)):
            self.small_button(row, text, command).pack(side="left", padx=(0, 4))
        self.tidy_row = tk.Frame(card, bg=PANEL)
        self.tidy_label = self.label(self.tidy_row, "", size=9, color=ORANGE)
        self.tidy_label.pack(side="left")
        self.small_button(self.tidy_row, "Tidy names", self.tidy_names).pack(side="left", padx=8)
        self.tidy_anchor = tk.Frame(card, bg=PANEL)   # the tidy row is packed before this
        self.tidy_anchor.pack(fill="x")
        self.section(card, "Pressed in every script")
        self.every_label = self.label(card, "", size=9, color=FG, anchor="w", justify="left",
                                      wraplength=520)
        self.every_label.pack(anchor="w")
        self.section(card, "Popups")
        self.label(card, "Peddler Shop -> View Later: automatic while the mod is running.",
                   size=9, anchor="w").pack(anchor="w")

    def refresh_buttons_page(self):
        try:
            lib = farm.library()
            every = sorted(i.split("/", 1)[-1] for i in farm.every_script_ids())
        except Exception:
            lib, every = [], []
        scripts = farm.list_scripts()
        self.buttons_summary.config(text=f"{len(lib)} button images · {len(scripts)} "
                                         f"script{'' if len(scripts) == 1 else 's'} "
                                         f"(this one: {self.script.get()})")
        self.every_label.config(text=", ".join(every) if every else
                                "None. Click a button's card in Customize and tick "
                                "'Press in every script'.")
        self.set_badge("buttons", len(lib))
        numbered = sum(1 for _, name, _, _, _ in lib if farm.NUMBERED.match(name))
        self.tidy_label.config(text=f"{numbered} images still have number names (like 06_go)")
        if numbered and not self.tidy_row.winfo_manager():
            self.tidy_row.pack(fill="x", pady=(8, 0), before=self.tidy_anchor)
        elif not numbered and self.tidy_row.winfo_manager():
            self.tidy_row.pack_forget()

    def build_settings(self, page):
        card = self.page_card(page, "Settings")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "Match threshold").pack(side="left")
        self.thr_spin = self.spinbox(row, self.threshold, from_=0.70, to=0.99, increment=0.01,
                                     format="%.2f")
        self.thr_spin.pack(side="left", padx=6)
        self.label(row, "lower it if a button is missed", color=MUTED).pack(side="left")
        self.check(card, "Keep this window on top", self.on_top,
                   lambda: self.root.attributes("-topmost", self.on_top.get())).pack(
            fill="x", pady=(8, 0))
        self.check_updates = tk.BooleanVar(value=True)
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.check(row, "Check for updates when TACMonkey starts", self.check_updates,
                   self.save_settings).pack(side="left")
        self.small_button(row, "Check now", self.check_for_updates).pack(side="right")
        self.section(card, "About")
        self.label(card, f"TACMonkey {farm.VERSION} · mod TAC Auto Tap {farm.MOD_VERSION}",
                   size=9, color=MUTED, anchor="w").pack(anchor="w")

    # ---------- shared Start / Pause / Stop ----------
    def start_any(self):
        if self.page in self.PAGE_MODE:
            self.genesis_go(self.PAGE_MODE[self.page])
        else:
            self.start()

    def pause_any(self):
        if self.running():
            self.toggle_pause()
        elif self.genesis_running():
            self.genesis_toggle_pause()

    def stop_any(self):
        if self.running():
            self.stop()
        elif self.genesis_running():
            self.genesis_halt()

    # ---------- Genesis unit farm / Ex Genesis farm ----------
    GENESIS_MODES = {  # mode -> (page, data file, what a pick is)
        "hard": ("genesis", "genesis_shards.json", "units"),
        "extra": ("ex", "genesis_extra.json", "chapters"),
    }

    def build_genesis(self):
        """Hard: pick units, skip-ticket the Genesis Hard stages that drop their shards; the
        number box next to a unit is how many of its stages to farm. Extra: pick chapters and
        skip-ticket all their Extra stages."""
        self.genesis_worker = None
        self.genesis_stop = threading.Event()
        self.genesis_pause = threading.Event()
        self.genesis_keys_prev = (False, False)   # F8, F9 last poll
        self.genesis_solo = tk.BooleanVar(value=False)
        self.genesis_mode = "hard"
        self.genesis_name = "Genesis farm"
        self.genesis_data, self.genesis_vars, self.genesis_counts = {}, {}, {}
        self.genesis_spins, self.genesis_info = {}, {}
        for mode, (_, file, _) in self.GENESIS_MODES.items():
            try:
                data = json.loads(farm.RES_DIR.joinpath(file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if mode == "extra":   # one pick per chapter, newest first ("ALL" is for the command line)
                data = dict(sorted(((k, v) for k, v in data.items() if k.startswith("ch")),
                                   key=lambda kv: -int(kv[0][2:])))
            self.genesis_data[mode] = data
            self.genesis_vars[mode], self.genesis_counts[mode] = {}, {}
            self.genesis_spins[mode] = {}
        self.genesis_grid(self.page_card(self.pages["genesis"], "Genesis farm - units (Hard)"))
        self.ex_list(self.page_card(self.pages["ex"], "Ex Genesis farm - chapters (Extra)"))

    @staticmethod
    def chapter_title(name):
        """'Chapter 8, Part 2: Pride Illuminates the World' from the game's chapter name."""
        head = re.match(r"\s*(Final Chapter|Chapter\s*\d+)", name)
        title = re.search(r'"([^"]+)"', name)
        part = re.search(r"\((?:Part\s*)?(One|Two|Three|\d)\)", name)
        num = {"One": "1", "Two": "2", "Three": "3"}.get(part.group(1), part.group(1)) if part else None
        h = head.group(1) if head else ""
        t = title.group(1) if title else re.sub(r"\(.*?\)", "", name[len(h):]).strip(' :"')
        return (f"{h}, Part {num}: {t}" if num else f"{h}: {t}") if h else name

    def chapter_units(self, chapter):
        """The units whose shards drop in a chapter's Hard stages."""
        return sorted({u for u, d in self.genesis_data["hard"].items()
                       for st in d["stages"] if st["chapter"] == chapter}, key=str.lower)

    def genesis_grid(self, frame):
        mode, data = "hard", self.genesis_data["hard"]
        import genesis_farm
        self.genesis_owners = genesis_farm.shared_owners(data)
        self.genesis_star = {}
        self.label(frame, "Tick units. The number beside one is how many of its stages to farm, "
                          "newest chapter first. Each stage is skipped with 3 skip tickets.",
                   size=9, color=MUTED, wraplength=520, justify="left").pack(anchor="w")
        self.check(frame, "Solo stages only (skip stages shared with another unit)",
                   self.genesis_solo, self.genesis_changed).pack(anchor="w", pady=(6, 0))
        grid = tk.Frame(frame, bg=PANEL)
        grid.pack(fill="x", pady=(6, 4))
        cols = 3
        keys = sorted(data, key=str.lower)
        for i, key in enumerate(keys):
            n = len(data[key]["stages"])
            var = tk.BooleanVar(value=False)
            count = tk.IntVar(value=n)
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // cols, column=i % cols, sticky="w", padx=(0, 6), pady=1)
            spin = tk.Spinbox(cell, from_=1, to=n, width=2, textvariable=count, wrap=False,
                              command=self.genesis_changed, bg=FIELD, fg=FG, buttonbackground=FIELD,
                              insertbackground=FG, relief="flat", font=(FONT, 9), justify="center",
                              highlightthickness=0)
            spin.bind("<KeyRelease>", lambda _e: self.genesis_changed())
            spin.bind("<FocusOut>", lambda _e: self.genesis_changed())
            cb = tk.Checkbutton(cell, text=key, variable=var, command=self.genesis_changed,
                                bg=PANEL, fg=FG, activebackground=PANEL, activeforeground=FG,
                                selectcolor=FIELD, highlightthickness=0, bd=0, font=(FONT, 10),
                                anchor="w")
            cb.pack(side="left")
            if self.genesis_shared_only(key):
                self.genesis_star[key] = cb   # gets a * while Solo stages only is ticked
            self.genesis_vars[mode][key] = var
            self.genesis_counts[mode][key] = count
            self.genesis_spins[mode][key] = spin   # shown only while ticked
        for c in range(cols):
            grid.columnconfigure(c, weight=1)
        if not keys:
            self.label(grid, "genesis_shards.json not found", color=RED).grid(row=0, column=0)
        self.genesis_star_note = self.label(frame, "* has only shared stages, so it keeps them",
                                            size=8, color=MUTED)
        self.genesis_star_anchor = tk.Frame(frame, bg=PANEL)   # the note is packed before this
        self.genesis_star_anchor.pack(fill="x")
        self.wip_team_row(frame)
        self.genesis_info["hard"] = self.label(frame, "", size=9, color=MUTED, anchor="w")
        self.genesis_info["hard"].pack(anchor="w", pady=(10, 0))

    def ex_list(self, frame):
        mode, data = "extra", self.genesis_data["extra"]
        self.label(frame, "Tick chapters to skip all their Extra stages. Each has 1 attempt a day "
                          "(1 skip ticket); clear a stage by hand once before it can be skipped. "
                          "On the right: the units farmed in that chapter's Hard stages.",
                   size=9, color=MUTED, wraplength=520, justify="left").pack(anchor="w")
        grid = tk.Frame(frame, bg=PANEL)
        grid.pack(fill="x", pady=(8, 4))
        for i, key in enumerate(data):
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(grid, text=self.chapter_title(data[key].get("name", key)),
                           variable=var, command=self.genesis_changed, bg=PANEL, fg=FG,
                           activebackground=PANEL, activeforeground=FG, selectcolor=FIELD,
                           highlightthickness=0, bd=0, font=(FONT, 10), anchor="w").grid(
                row=i, column=0, sticky="w", pady=1)
            units = self.chapter_units(int(key[2:]))
            self.label(grid, ", ".join(units), size=9, color=MUTED, anchor="w").grid(
                row=i, column=1, sticky="w", padx=(16, 0))
            self.genesis_vars[mode][key] = var
        grid.columnconfigure(1, weight=1)
        if not data:
            self.label(grid, "genesis_extra.json not found", color=RED).grid(row=0, column=0)
        row = tk.Frame(frame, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.small_button(row, "Tick all", lambda: self.genesis_tick_all("extra")).pack(side="left")
        self.genesis_info["extra"] = self.label(row, "", size=9, color=MUTED)
        self.genesis_info["extra"].pack(side="left", padx=10)
        # this run's elemental Soul Shards, counted up as each stage finishes
        tally = tk.Frame(frame, bg=PANEL)
        tally.pack(fill="x", pady=(10, 0))
        self.label(tally, "Elemental shards this run", size=9, color=MUTED).pack(side="left")
        self.element_labels = {}
        for el in ("Fire", "Water", "Thunder", "Wind", "Light", "Dark"):
            lab = self.label(tally, f"{el} 0", size=9, bold=True, color=ELEMENT_COLORS[el])
            lab.pack(side="left", padx=(12, 0))
            self.element_labels[el] = lab

    def show_elemental(self, shards):
        """Ex page tally: shards = {"Fire Soul Shard": 12, ...} (missing = 0)."""
        for el, lab in getattr(self, "element_labels", {}).items():
            lab.config(text=f"{el} {shards.get(f'{el} Soul Shard', 0)}")

    def genesis_tick_all(self, mode):
        """Tick every pick, or untick them all if they're all ticked already."""
        vars_ = self.genesis_vars[mode].values()
        on = not all(v.get() for v in vars_)
        for var in vars_:
            var.set(on)
        self.genesis_changed()

    def genesis_set_mode(self, mode):
        """Kept for old settings: show the page of that mode."""
        self.show_page(self.GENESIS_MODES[mode][0])

    def genesis_selected(self, mode=None):
        return [k for k, v in self.genesis_vars[mode or self.genesis_mode].items() if v.get()]

    def genesis_shared_only(self, unit):
        """A unit whose every Hard stage is shared (it keeps them with Solo stages only)."""
        return all(len(self.genesis_owners[st["stage"]]) > 1
                   for st in self.genesis_data["hard"][unit]["stages"])

    def genesis_solo_on(self, mode=None):
        return (mode or self.genesis_mode) == "hard" and self.genesis_solo.get()

    def genesis_stage_total(self, mode, key):
        """How many stages a pick has (with Solo stages only: without the shared ones)."""
        if not self.genesis_solo_on(mode):
            return len(self.genesis_data[mode][key]["stages"])
        import genesis_farm
        return len(genesis_farm.unit_stages(self.genesis_data[mode], key,
                                            self.genesis_selected(mode), True,
                                            self.genesis_owners))

    def genesis_count_map(self, mode=None):
        """{pick: stages to farm} for every pick (a blank or bad box counts as all of them).
        A box at its most counts as all of the pick's stages, so a count saved while Solo
        stages only is ticked still means "all" when it isn't. Ex chapters: always all."""
        mode = mode or self.genesis_mode
        out = {}
        for k, var in self.genesis_counts[mode].items():
            n = len(self.genesis_data[mode][k]["stages"])
            try:
                v = max(int(var.get()), 1)
                out[k] = n if v >= int(self.genesis_spins[mode][k].cget("to")) else min(v, n)
            except (tk.TclError, ValueError):
                out[k] = n
        return out

    def genesis_stages(self, picks, mode=None):
        import genesis_farm
        mode = mode or self.genesis_mode
        return [s["stage"] for s in genesis_farm.plan(self.genesis_data[mode], picks,
                                                       self.genesis_count_map(mode),
                                                       self.genesis_solo_on(mode))]

    def genesis_changed(self):
        if not getattr(self, "genesis_info", None) or len(self.genesis_info) < 2:
            return
        mode = "hard"
        for key, spin in self.genesis_spins[mode].items():   # number boxes only while ticked
            on = self.genesis_vars[mode][key].get()
            total = self.genesis_stage_total(mode, key) if on else None
            if on and int(spin.cget("to")) != total:   # Solo stages only changes the most
                var = self.genesis_counts[mode][key]
                try:
                    was = int(var.get())
                except (tk.TclError, ValueError):
                    was = total
                full = was >= int(spin.cget("to"))
                spin.config(to=total)
                var.set(total if full else min(was, total))
            if on and not spin.winfo_ismapped():
                spin.pack(side="left", padx=(2, 0))
            elif not on and spin.winfo_manager():
                spin.pack_forget()
        solo = self.genesis_solo.get()
        for key, cb in self.genesis_star.items():
            cb.config(text=key + (" *" if solo else ""))
        note = self.genesis_star_note
        if solo and not note.winfo_manager():
            note.pack(anchor="w", before=self.genesis_star_anchor)
        elif not solo and note.winfo_manager():
            note.pack_forget()
        for mode, per, page in (("hard", 3, "genesis"), ("extra", 1, "ex")):
            picks = self.genesis_selected(mode)
            stages = self.genesis_stages(picks, mode)
            self.genesis_info[mode].config(text=f"{len(stages)} stages · {len(stages) * per} "
                                                f"skips" if picks else "Nothing ticked yet")
            self.set_badge(page, len(picks))
        self.update_buttons()

    def genesis_running(self):
        worker = getattr(self, "genesis_worker", None)
        return worker is not None and worker.is_alive()

    def genesis_go(self, mode=None):
        mode = mode or self.genesis_mode
        picks = self.genesis_selected(mode)
        if not picks or self.running() or self.genesis_running():
            return
        self.genesis_mode = mode
        self.save_settings()
        stages = self.genesis_stages(picks, mode)
        counts = self.genesis_count_map(mode)
        name = "Genesis farm" if mode == "hard" else "Ex Genesis farm"
        self.genesis_stop, self.genesis_pause = threading.Event(), threading.Event()
        leaves, solo = self.leaf_settings(), self.genesis_solo_on(mode)
        self.genesis_name = name
        self.set_state(name, f"{', '.join(picks)} -> {len(stages)} stages")
        self.log(f"--- {name}: {', '.join(picks)} ---", "muted")
        if mode == "extra":
            self.show_elemental({})

        def job():
            try:
                import genesis_farm
                reason = genesis_farm.GenesisFarm(
                    log=lambda m: self.q.put(("log", m)), stop=self.genesis_stop, mode=mode,
                    pause=self.genesis_pause, leaves=leaves,
                    status=lambda t: self.q.put(("gstatus", t)),
                    on_shards=lambda s: self.q.put(("gshards", s))).run(picks, counts, solo)
            except Exception as e:
                saved = farm.log_error(name)
                reason = f"{name} error: {e!r}"
                self.q.put(("log", reason + (f" (details saved in {saved})" if saved else ""),
                            "bad"))
            self.q.put(("gdone", reason))

        self.genesis_worker = threading.Thread(target=job, daemon=True)
        self.genesis_worker.start()
        self.update_buttons()

    def genesis_halt(self):
        if self.genesis_running():
            self.genesis_pause.clear()
            self.genesis_stop.set()
            self.set_state("Stopping...")

    def genesis_toggle_pause(self):
        if not self.genesis_running():
            return
        if self.genesis_pause.is_set():
            self.genesis_pause.clear()
            self.log(f"{time.strftime('%H:%M:%S')} RESUME")
        else:
            self.genesis_pause.set()
            self.log(f"{time.strftime('%H:%M:%S')} PAUSE - the farm stops after the stage it's on",
                     "warn")
            self.set_state("Pausing...", "Finishing the stage it's on, then it waits")
        self.update_buttons()

    def leaf_settings(self):
        """The AP refill row as genesis_farm.leaf_settings (blank / 0 = no limit)."""
        import genesis_farm
        out = genesis_farm.leaf_settings(self.leaf_per.get(), self.leaf_most.get(),
                                         self.leaf_floor.get())
        self.leaf_per.set(str(out["per"]))
        self.leaf_most.set(str(out["most"] or ""))
        self.leaf_floor.set(str(out["floor"] or ""))
        return out

    # ---------- helpers ----------
    def log(self, text, tag=None):
        if tag is None:
            low = text.lower()
            tag = ("warn" if "covered" in low or "nothing recognised" in low or "paused" in low
                   or "stuck" in low
                   else "good" if "runs completed" in low or "reached" in low
                   else "info" if "act finished" in low else None)
        m = re.search(r"\((\d+) Alchemy Drops used this session(?:, (\d+) left)?\)", text)
        if m and hasattr(self, "leaf_session"):
            self.leaf_session.config(text=f"{m.group(1)} used" +
                                     (f" · {m.group(2)} left" if m.group(2) else ""))
        self.log_box.insert("end", text + "\n", tag or ())
        if int(self.log_box.index("end-1c").split(".")[0]) > 2000:
            self.log_box.delete("1.0", "500.0")
        self.log_box.see("end")

    def set_state(self, state, detail=None):
        self.state = state
        self.status_label.config(text=state)
        self.dot.itemconfig(self.dot_id, fill=state_color(state))
        if detail is not None:
            self.detail_label.config(text=detail)

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def enable(self, button, on):
        button.config(state="normal" if on else "disabled", bg=button.color if on else FIELD,
                      cursor="hand2" if on else "arrow")

    def update_buttons(self):
        if not hasattr(self, "pages"):
            return
        run, grun = self.running(), self.genesis_running()
        busy = run or grun
        mode = self.PAGE_MODE.get(self.page)
        if mode:
            text = "Start Genesis farm" if mode == "hard" else "Start Ex farm"
            can = not busy and bool(self.genesis_selected(mode))
        else:
            text, can = "Start script", not busy
        self.start_btn.config(text=text)
        self.enable(self.start_btn, can)
        self.enable(self.pause_btn, busy)
        self.enable(self.stop_btn, busy)
        paused = (run and self.state == "Paused") or (grun and self.genesis_pause.is_set())
        self.pause_btn.config(text="Resume" if paused else "Pause")
        for w in (self.max_spin, self.goal_spin, self.thr_spin, self.act_check, self.script_menu):
            w.config(state="disabled" if run else "normal")
        for b in self.goal_buttons:   # the goal is read at Start
            self.enable(b, not run)
        self.enable(self.new_btn, not run)
        self.enable(self.import_btn, not run)  # importing switches to the new script
        for sp in self.leaf_spins:   # leaf limits are read at Start
            sp.config(state="disabled" if busy else "normal")

    def show_stats(self):
        self.stat_values["Runs"].config(text=str(self.runs))
        self.set_badge("story", self.runs)
        secs = int(self.run_time)
        self.stat_values["Time"].config(text=f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}")
        per_hour = self.runs * 3600 / self.run_time if self.run_time >= 60 and self.runs else None
        self.stat_values["Runs / hour"].config(text=f"{per_hour:.1f}" if per_hour else "-")

    # ---------- actions ----------
    def start(self):
        if self.running():
            return
        try:
            max_runs = max(0, int(self.max_runs.get()))
        except ValueError:
            max_runs = 0
            self.max_runs.set("0")
        try:
            farm.THRESHOLD = min(0.99, max(0.5, float(self.threshold.get())))
        except ValueError:
            pass
        self.threshold.set(f"{farm.THRESHOLD:.2f}")
        self.stop_event, self.pause_event = threading.Event(), threading.Event()
        self.runs, self.run_time, self.tick_from = 0, 0.0, time.time()
        self.show_stats()
        limit = f"stops after {max_runs} runs" if max_runs else "runs until you stop it"
        self.set_state("Starting...", f"Farming - {limit}.")
        self.log(f"--- Start: script '{self.script.get()}', {limit}, "
                 f"threshold {farm.THRESHOLD:.2f} ---", "muted")
        self.worker = threading.Thread(target=self.work, daemon=True,
                                       args=(max_runs or None, self.act_switch.get(),
                                             self.script.get(), self.leaf_settings()))
        self.worker.start()
        self.update_buttons()

    def work(self, max_runs, act_switch, script, leaves=None):
        try:
            reason = farm.run(max_runs, log=lambda m: self.q.put(("log", m)),
                              stop=self.stop_event, pause=self.pause_event,
                              on_status=lambda s, r, l: self.q.put(("status", s, r, l)),
                              act_switch=act_switch, skip_merc=self.skip_merc_event,
                              script=script, leaves=leaves)
        except SystemExit as e:
            reason = str(e)
            self.q.put(("log", reason, "bad"))
        except Exception as e:
            saved = farm.log_error(f"script {script}")
            reason = f"Error: {e!r}"
            self.q.put(("log", reason + (f" (details saved in {saved})" if saved else ""),
                        "bad"))
        self.q.put(("done", reason))

    def toggle_merc(self):
        if self.skip_merc.get():
            self.skip_merc_event.set()
        else:
            self.skip_merc_event.clear()
        if self.running():
            self.log(f"{time.strftime('%H:%M:%S')} "
                     f"{'Skipping' if self.skip_merc.get() else 'Hiring'} the mercenary from now on",
                     "info")

    def toggle_pause(self):
        if not self.running():
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.log(f"{time.strftime('%H:%M:%S')} RESUMED")
            self.set_state("Running")
        else:
            self.pause_event.set()
            self.log(f"{time.strftime('%H:%M:%S')} PAUSED")
            self.set_state("Paused")
        self.update_buttons()

    def stop(self):
        if self.running():
            self.stop_event.set()
            self.set_state("Stopping...")

    # ---------- scripts ----------
    def refresh_scripts(self):
        menu = self.script_menu["menu"]
        menu.delete(0, "end")
        for name in farm.list_scripts():
            menu.add_command(label=name, command=lambda n=name: self.pick_script(n))
        if self.script.get() not in farm.list_scripts():
            self.script.set(farm.DEFAULT_SCRIPT)

    # ---------- item goal ----------
    def refresh_goal(self):
        """Show the picked script's item goal (picture, count, item name)."""
        goal = farm.load_goal(self.script.get())
        self.goal_loading = True
        self.goal_count.set(str(goal["count"]) if goal and goal["count"] else "")
        self.goal_loading = False
        img = goal["img"] if goal else None
        if img is None:
            self.goal_photo = None
            self.goal_thumb.config(image="", text="none", width=6, height=1)
        else:
            h, w = img.shape[:2]
            sc = min(56 / w, 30 / h, 1.0)
            small = farm.cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))),
                                    interpolation=farm.cv2.INTER_AREA)
            _, buf = farm.cv2.imencode(".png", small)
            self.goal_photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
            self.goal_thumb.config(image=self.goal_photo, text="", width=0, height=0)
        self.goal_name.config(text=(goal["name"] or "(name read on the first drop)")
                              if img is not None else "")

    def goal_count_changed(self):
        if self.goal_loading:
            return
        text = self.goal_count.get().strip()
        try:
            n = max(0, int(text)) if text else 0
        except ValueError:
            return
        farm.set_goal(self.script.get(), count=n or None)

    def goal_capture(self):
        self.log("Item goal: drag a box round the item's icon on a results screen "
                 "(just the picture, not the x12), then press Enter", "info")
        script = self.script.get()

        def job():
            try:
                farm.grab_goal(script)
                self.q.put(("log", f"Saved the item goal's picture for script '{script}'", "good"))
            except SystemExit as e:
                self.q.put(("log", f"Item goal: {e}", "bad"))
            except Exception as e:
                self.q.put(("log", f"Item goal capture failed: {e!r}", "bad"))
            self.q.put(("grab_done", self.refresh_goal))

        threading.Thread(target=job, daemon=True).start()

    def goal_from_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Picture of the item",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        img = farm.cv2.imread(path, farm.cv2.IMREAD_UNCHANGED)
        if img is None:
            messagebox.showerror("Item goal", "Couldn't read that image.", parent=self.root)
            return
        _, region = farm.find_window()
        width = region[2] if region else 2405  # assume it was cut from the game at its current size
        farm.set_goal_image(self.script.get(), img, width)
        self.log(f"Item goal picture from {Path(path).name} (window width {width})", "good")
        self.refresh_goal()

    def goal_clear(self):
        goal = farm.load_goal(self.script.get())
        if not goal:
            return
        if not messagebox.askyesno("Item goal", "Remove this script's item goal?\n\nIts picture "
                                   "goes to the script's _old folder.", parent=self.root):
            return
        farm.clear_goal(self.script.get())
        self.log(f"Item goal removed from script '{self.script.get()}'", "info")
        self.refresh_goal()

    def pick_script(self, name):
        self.script.set(name)
        self.refresh_goal()
        used = sorted(i.split("/", 1)[1] for i in farm.used_ids(name))
        self.log(f"Script: {name} - {len(used)} buttons: {', '.join(used) or 'none picked yet'}",
                 "info")
        self.save_settings()

    def ask_name(self, title, prompt):
        name = simpledialog.askstring(title, prompt, parent=self.root)
        name = (name or "").strip()
        if name and (BAD_CHARS & set(name) or name.startswith(".")):
            messagebox.showerror(title, 'A name can\'t contain \\ / : * ? " < > |', parent=self.root)
            return None
        return name or None

    def new_script(self):
        name = self.ask_name("New script", "Name for the new script (e.g. Fire merc):")
        if not name:
            return
        if name in farm.list_scripts():
            messagebox.showerror("New script", f"'{name}' already exists.", parent=self.root)
            return
        farm.script_dir(name).mkdir(parents=True)
        farm.new_script_settings(name)  # starts empty (no picks = not "all of Default")
        self.refresh_scripts()
        self.pick_script(name)
        self.log("Add its buttons in the window that opened: click them in the list at the "
                 "bottom, or capture new ones.", "muted")
        self.customize()

    def import_script(self, parent):
        """Make a new script from a .tacscript file someone sent."""
        path = filedialog.askopenfilename(
            parent=parent, title="Import script",
            filetypes=[("TACMonkey script", f"*{farm.SHARE_EXT}"), ("All files", "*.*")])
        if not path:
            return
        try:
            name, images, notes = farm.import_script(path)
        except (farm.ShareError, OSError) as e:
            messagebox.showerror("Import script", str(e), parent=parent)
            return
        self.refresh_scripts()
        self.pick_script(name)
        self.log(f"Imported script '{name}' from {Path(path).name}: {images} button images"
                 + (f" ({'; '.join(notes)})" if notes else ""), "good")
        messagebox.showinfo(
            "Import script", f"Added the script '{name}' with {images} button images.\n\n"
            "Its images were captured on another PC. Open the game on a screen the script "
            "uses and press Check screen: if a button scores low, re-capture it in Customize."
            + ("\n\nNote: " + "; ".join(notes) if notes else ""), parent=parent)
        self.customize()

    def open_folder(self):
        self.open_folder_of(self.script.get())()

    def open_folder_of(self, script):
        def go():
            folder = farm.script_dir(script)
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        return go

    def grab_image(self, script, name, on_done=None):
        """Capture the game, let the user drag a box, save it as <name>.png into the script."""
        def job():
            try:
                out = farm.grab(name, script)
                self.q.put(("log", f"Saved {out.name} into script '{script}'", "good"))
            except SystemExit as e:
                self.q.put(("log", f"Grab: {e}", "bad"))
            except Exception as e:
                self.q.put(("log", f"Grab failed: {e!r}", "bad"))
            self.q.put(("grab_done", on_done))

        threading.Thread(target=job, daemon=True).start()

    def customize(self):
        if self.customizer and self.customizer.win.winfo_exists():
            self.customizer.win.destroy()
        self.customizer = Customizer(self, self.script.get())

    # ---------- settings ----------
    def load_settings(self):
        try:
            s = json.loads(SETTINGS.read_text())
        except (OSError, ValueError):
            return
        if s.get("script") in farm.list_scripts():
            self.script.set(s["script"])
        self.act_switch.set(s.get("act_switch", True))
        self.skip_merc.set(s.get("skip_merc", False))
        self.import_asked = s.get("import_asked", False)
        self.tidy_asked = s.get("tidy_asked", False)
        self.check_updates.set(s.get("check_updates", True))
        self.editor_view = s.get("editor_view", "flow")
        self.toggle_merc()
        for mode, prefix in (("hard", "genesis"), ("extra", "ex")):
            for k in s.get(f"{prefix}_units", []):
                if k in self.genesis_vars[mode]:
                    self.genesis_vars[mode][k].set(True)
            for k, n in (s.get(f"{prefix}_counts") or {}).items():
                if k in self.genesis_counts[mode] and isinstance(n, int):
                    self.genesis_counts[mode][k].set(
                        min(max(n, 1), len(self.genesis_data[mode][k]["stages"])))
        self.genesis_solo.set(bool(s.get("genesis_solo", False)))
        self.leaf_per.set(str(s.get("leaf_per") or 7))
        self.leaf_most.set(str(s.get("leaf_most") or ""))
        self.leaf_floor.set(str(s.get("leaf_floor") or ""))
        page = s.get("page") or {"extra": "ex", "hard": "genesis"}.get(s.get("genesis_mode"))
        self.show_page(page if page in self.pages else "story")
        self.genesis_changed()

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps({"script": self.script.get(),
                                            "act_switch": self.act_switch.get(),
                                            "skip_merc": self.skip_merc.get(),
                                            "import_asked": self.import_asked,
                                            "tidy_asked": self.tidy_asked,
                                            "check_updates": self.check_updates.get(),
                                            "editor_view": self.editor_view,
                                            "genesis_units": self.genesis_selected("hard"),
                                            "genesis_counts": self.genesis_count_map("hard"),
                                            "ex_units": self.genesis_selected("extra"),
                                            "page": self.page,
                                            "genesis_mode": self.genesis_mode,
                                            "genesis_solo": self.genesis_solo.get(),
                                            **{f"leaf_{k}": v for k, v in
                                               self.leaf_settings().items()}}, indent=2))
        except OSError:
            pass

    def check_screen(self):
        script = self.script.get()
        self.enable(self.check_btn, False)

        def job():
            try:
                self.q.put(("check",) + farm.check(script))
            except SystemExit as e:
                self.q.put(("log", str(e), "bad"))
            except Exception as e:
                self.q.put(("log", f"Check failed: {e!r}", "bad"))
            self.q.put(("check_done",))

        threading.Thread(target=job, daemon=True).start()

    # ---------- loop ----------
    def poll(self):
        while True:
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            if kind == "log":
                self.log(*msg[1:])
            elif kind == "status":
                _, state, runs, last = msg
                self.runs = runs
                self.set_state(state, f"Last click: {last}" if last else "Watching the game...")
                self.show_stats()
                self.update_buttons()
                c = self.customizer
                if last and c and c.win.winfo_exists() and c.script == self.script.get():
                    c.highlight(last.rsplit(" (", 1)[0])
            elif kind == "done":
                self.worker = None
                self.refresh_goal()
                self.set_state("Stopped", msg[1])
                self.update_buttons()
            elif kind == "check":
                _, (w, h), scores, action = msg
                self.log(f"--- Check screen (window {w}x{h}, threshold {farm.THRESHOLD:.2f}) ---",
                         "muted")
                for name, score, diff in scores:
                    note = farm.check_note(score, diff)
                    self.log(f"  {name:<16} {score:.2f}{'  ' + note if note else ''}",
                             "good" if note == "<- seen" else "warn" if note else "muted")
                self.log(action, "info")
            elif kind == "check_done":
                self.enable(self.check_btn, True)
            elif kind == "grab_done":
                if msg[1]:
                    msg[1]()
            elif kind == "update":
                _, info, manual = msg
                if info:
                    self.show_update(info)
                elif manual:
                    self.log(f"TACMonkey {farm.VERSION} is the latest version.", "good")
            elif kind == "update_error":
                _, text, manual = msg
                self.log(f"Update check: {text}", "bad" if manual else "muted")
            elif kind == "update_progress":
                self.update_text.config(text=f"Downloading TACMonkey "
                                             f"{self.update_info['version']}... {msg[1]}%")
            elif kind == "update_ready":
                self.update_ready(msg[1])
            elif kind == "update_failed":
                self.update_failed(msg[1])
            elif kind == "gshards":
                if self.genesis_mode == "extra":
                    self.show_elemental(msg[1])
            elif kind == "gstatus":
                if not self.genesis_running():
                    pass
                elif msg[1] == "Paused":
                    self.set_state("Paused", "Genesis farm paused - press Resume or F8")
                elif msg[1] == "Running":
                    self.set_state(self.genesis_name, "Resumed")
                else:
                    self.detail_label.config(text=msg[1])
                self.update_buttons()
            elif kind == "gdone":
                self.genesis_worker = None
                self.genesis_pause.clear()
                self.set_state("Stopped", msg[1])
                self.update_buttons()
        if self.genesis_running():   # F8 pause / resume and F9 stop work for the Genesis farm too
            keys = (farm.key_down(farm.VK_F8), farm.key_down(farm.VK_F9))
            if keys[0] and not self.genesis_keys_prev[0]:
                self.genesis_toggle_pause()
            if keys[1] and not self.genesis_keys_prev[1]:
                self.genesis_halt()
            self.genesis_keys_prev = keys
        self.root.after(100, self.poll)

    def tick(self):
        now = time.time()
        if self.running() and self.state != "Paused":
            self.run_time += now - self.tick_from
            self.show_stats()
        self.tick_from = now
        self.root.after(1000, self.tick)

    def close(self):
        self.save_settings()
        if self.genesis_running():
            self.genesis_stop.set()
        if self.running():
            self.stop_event.set()
            self.worker.join(timeout=2)
        self.root.destroy()


NAME_HELP = ("Name for the new button image (e.g. go, confirm, try again).\n\n"
             "It goes to the bottom of the Priority list - move it up there if it\n"
             "should win over other buttons. To add another look of a button that\n"
             "is already in the script, use 'Add a variant' on its card instead.\n\n"
             "Start the name with x_ for a marker: only looked at, never tapped.")


class Customizer:
    """A script as a flowchart (or as its priority list): one card per step (its images are
    variants of one button), arrows in the order real runs went through them, a detail panel
    for the picked card, and every other captured button below to add with a click."""
    CARD_W, THUMB_W, THUMB_H = 184, 164, 54
    GAP_X, GAP_Y = 56, 70
    TILE_W, TILE_H = 132, 56

    def __init__(self, app, script):
        self.app, self.script = app, script
        self.photos = {}          # (id, w, h) -> PhotoImage, kept alive while shown
        self.selected = None      # ("step", key) / ("entry", id)
        self.live = None          # step key of the last button the farm pressed
        self.model = None
        self.win = win = tk.Toplevel(app.root)
        win.title(f"Customize script - {script}")
        win.configure(bg=BG)
        win.geometry("1100x880")
        win.minsize(820, 600)

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        self.title = app.label(head, "", size=13, bold=True)
        self.title.pack(anchor="w")
        self.subtitle = app.label(head, "", size=9, color=MUTED, wraplength=1040, justify="left")
        self.subtitle.pack(anchor="w", pady=(2, 8))
        bar = tk.Frame(head, bg=BG)
        bar.pack(fill="x")
        for text, cmd in (("Capture new button", self.add_grab),
                          ("New button from file", self.add_file),
                          ("Import buttons", self.import_buttons)):
            app.small_button(bar, text, cmd).pack(side="left", padx=(0, 6))
        for text, cmd in (("Import script", self.import_script),
                          ("Export script", self.export_script),
                          ("Reset arrows", self.reset_arrows)):
            app.small_button(bar, text, cmd).pack(side="right", padx=(6, 0))
        # view switch: the flow of a run, or the order buttons are checked in
        tabs = tk.Frame(head, bg=BG)
        tabs.pack(fill="x", pady=(10, 0))
        self.mode = app.editor_view if app.editor_view in ("flow", "list") else "flow"
        self.tabs = {}
        for mode, text in (("flow", "Flowchart"), ("list", "Priority list")):
            b = tk.Button(tabs, text=text, relief="flat", bd=0, padx=14, pady=4,
                          font=(FONT, 10, "bold"), cursor="hand2",
                          command=lambda m=mode: self.set_mode(m))
            b.pack(side="left", padx=(0, 4))
            self.tabs[mode] = b
        self.style_tabs()

        panes = tk.PanedWindow(win, orient="vertical", bg=BG, sashwidth=6, bd=0,
                               sashrelief="flat")
        panes.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        # top: the flow (left) and the picked card (right)
        top = tk.Frame(panes, bg=BG)
        self.detail = tk.Frame(top, bg=PANEL, width=300, padx=12, pady=10)
        self.detail.pack(side="right", fill="y", padx=(8, 0))
        self.detail.pack_propagate(False)
        self.flow = self.scroll_canvas(top)
        self.flow.bind("<Configure>", lambda _: self.draw_flow())
        panes.add(top, minsize=260, height=520)

        # bottom: everything else that's captured, to add with a click
        bottom = tk.Frame(panes, bg=BG)
        row = tk.Frame(bottom, bg=BG)
        row.pack(fill="x", pady=(6, 4))
        app.label(row, "ADD BUTTONS", size=8, color=MUTED).pack(side="left")
        app.label(row, "  click one to add it to this script", size=8,
                  color=MUTED).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.draw_pool())
        tk.Entry(row, textvariable=self.search, bg=FIELD, fg=FG, insertbackground=FG,
                 relief="flat", font=(FONT, 10), width=24).pack(side="right")
        app.label(row, "Search ", size=9, color=MUTED).pack(side="right")
        self.pool = self.scroll_canvas(bottom)
        self.pool.bind("<Configure>", lambda _: self.draw_pool())
        panes.add(bottom, minsize=140)

        win.bind("<MouseWheel>", self.wheel)
        self.refresh()

    def style_tabs(self):
        for mode, b in self.tabs.items():
            on = mode == self.mode
            b.configure(bg=BLUE if on else FIELD, fg=DARK if on else FG,
                        activebackground=BLUE if on else GREY, activeforeground=DARK if on else FG)

    def set_mode(self, mode):
        self.mode = self.app.editor_view = mode
        self.app.save_settings()
        self.style_tabs()
        self.flow.yview_moveto(0)
        self.refresh()

    # ---------- drawing helpers ----------
    def scroll_canvas(self, parent):
        box = tk.Frame(parent, bg=BG)
        box.pack(side="left", fill="both", expand=True)
        canvas = tk.Canvas(box, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(box, command=canvas.yview)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=bar.set)
        return canvas

    def wheel(self, e):
        widget = self.win.winfo_containing(e.x_root, e.y_root)
        detail = getattr(self, "detail_canvas", None)
        for canvas in (self.flow, self.pool, detail):
            if canvas is None or not canvas.winfo_exists() or widget is None:
                continue
            if str(widget).startswith(str(canvas)):  # the canvas or something on it
                canvas.yview_scroll(-e.delta // 120, "units")
                return

    def photo(self, b, max_w, max_h):
        """A thumbnail of an entry's image (cached while the window shows it)."""
        key = (b["id"], max_w, max_h)
        if key not in self.photos:
            img = b["img"]
            h, w = img.shape[:2]
            s = min(max_w / w, max_h / h, 1.0)
            small = farm.cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                                    interpolation=farm.cv2.INTER_AREA)
            _, buf = farm.cv2.imencode(".png", small)
            self.photos[key] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        return self.photos[key]

    @staticmethod
    def pretty(name):
        """'quest new' from 01_quest_new: an old-style number prefix isn't part of the name."""
        return farm.NUMBERED.sub("", name).replace("_", " ").strip() or name

    @classmethod
    def step_title(cls, key, entries):
        """A step's title: its first image's name (priority is shown separately, as #n)."""
        return cls.pretty(entries[0]["name"])

    def card_height(self, n):
        return 34 + n * (self.THUMB_H + 6) + 22

    # ---------- refresh ----------
    def refresh(self):
        self.photos.clear()
        self.model = m = farm.flow_model(self.script)
        steps = sum(len(v) for v in m["groups"].values())
        self.title.config(text=f"Script: {self.script}   -   {len(m['groups'])} steps, "
                               f"{steps} button images"
                               + (f", {len(m['actions'])} built-in" if m["actions"] else ""))
        if self.mode == "list":
            text = ("The order the farm checks the steps on every scan: when two are on screen at "
                    "once, the higher one in this list is tapped. Move steps with the arrows. "
                    + ("This script has its own order." if m["custom_priority"] else
                       "Right now it's the default order: old numbered names first, then the rest A-Z.")
                    + " Click a step for its options. Changes apply on the next Start.")
        else:
            text = ("Each card is one step: its images are variants (looks) of one button - "
                    "group them with Add a variant or an image's Step. " + (
                        "The arrows show the order your runs went through the steps."
                        if m["learned"] else
                        "Until the farm has run with this script the cards follow the priority "
                        "list (dashed arrows); after a run the arrows show the real order.")
                    + " When two are on screen at once, the Priority list decides. Click a card "
                      "for its options. Changes apply on the next Start.")
        self.subtitle.config(text=text)
        if self.selected and not self.find_selected():
            self.selected = None
        self.draw_flow()
        self.draw_pool()
        self.draw_detail()

    def find_selected(self):
        m, sel = self.model, self.selected
        if not sel:
            return None
        if sel[0] == "step":
            return m["groups"].get(sel[1])
        hits = [b for b in m["actions"] + m["markers"] + m["every"] if b["id"] == sel[1]]
        return hits or None

    def highlight(self, name):
        """Light up the step of the button the farm just pressed."""
        key = next((k for k, bs in self.model["groups"].items()
                    if any(b["name"] == name for b in bs)), None) if self.model else None
        if key != self.live:
            self.live = key
            self.draw_flow()

    # ---------- the flow ----------
    def tag(self, *parts):
        """A canvas tag for a card. Not the step name itself: Tk splits a tag at spaces, so a
        card named "try again" would get the tags "step:try" and "again" and no click would
        reach it."""
        tags = self.__dict__.setdefault("_tags", {})
        return tags.setdefault(parts, f"card{len(tags)}")

    def draw_flow(self):
        c, m = self.flow, self.model
        if m is None:
            return
        if self.mode == "list":
            self.draw_list()
            return
        c.delete("all")
        width = max(c.winfo_width(), self.CARD_W + 40)
        cols = max(1, (width - 20 + self.GAP_X) // (self.CARD_W + self.GAP_X))
        x0, y = 16, 14
        if not m["groups"] and not m["actions"] and not m["markers"]:
            c.create_text(width // 2, 80, fill=MUTED, font=(FONT, 11), justify="center",
                          text="This script has no buttons yet.\n\nAdd some from the list below, "
                               "or capture new ones with the buttons at the top.")
            c.configure(scrollregion=(0, 0, width, 200))
            return

        order = m["order"]
        boxes = {}
        rows = [order[i:i + cols] for i in range(0, len(order), cols)]
        for row in rows:
            h = max(self.card_height(len(m["groups"][k])) for k in row)
            for i, key in enumerate(row):
                x = x0 + i * (self.CARD_W + self.GAP_X)
                boxes[key] = (x, y, x + self.CARD_W, y + self.card_height(len(m["groups"][key])))
            y += h + self.GAP_Y
        for i, key in enumerate(order):  # arrows first, cards on top
            if i + 1 < len(order):
                self.arrow(key, order[i + 1], boxes)
        if order and m["learned"]:
            last = boxes[order[-1]]
            back = m["pairs"].get((order[-1], order[0]))
            c.create_text(last[2] + 8, (last[1] + last[3]) // 2, anchor="w", fill=MUTED,
                          font=(FONT, 8), text="back to\n" + order[0] + (f" ({back})" if back
                                                                        else ""))
        for key in order:
            self.card(key, boxes[key])

        # built-in actions and markers: outside the loop
        extras = ([("ANY TIME", b) for b in m["actions"]] + [("MARKER", b) for b in m["markers"]]
                  + [("EVERY SCRIPT", b) for b in m["every"]])
        if extras:
            c.create_text(x0, y - self.GAP_Y + 24, anchor="nw", fill=MUTED, font=(FONT, 8),
                          text="OUTSIDE THE LOOP  -  built-in actions run whenever their window "
                               "shows; markers are only looked at, never tapped; every-script "
                               "buttons are pressed in all scripts, before their own steps")
            ey = y - self.GAP_Y + 44
            for i, (tag, b) in enumerate(extras):
                x = x0 + (i % cols) * (self.CARD_W + self.GAP_X)
                yy = ey + (i // cols) * (self.card_height(1) + 16)
                self.extra_card(tag, b, (x, yy, x + self.CARD_W, yy + self.card_height(1)))
            y = ey + ((len(extras) - 1) // cols + 1) * (self.card_height(1) + 16)
        c.configure(scrollregion=(0, 0, width, y + 10))

    # ---------- the priority list ----------
    LIST_THUMB_W, LIST_THUMB_H, ROW_H = 120, 44, 64

    def draw_list(self):
        c, m = self.flow, self.model
        c.delete("all")
        width = max(c.winfo_width(), 520)
        steps = m["priority"]
        if not steps:
            c.create_text(width // 2, 80, fill=MUTED, font=(FONT, 11), justify="center",
                          text="This script has no buttons yet.\n\nAdd some from the list below.")
            c.configure(scrollregion=(0, 0, width, 200))
            return
        y = 10
        if m["custom_priority"]:
            t = c.create_text(16, y, anchor="nw", fill=BLUE, font=(FONT, 9, "underline"),
                              text="Back to default order", tags="reset")
            c.tag_bind("reset", "<Button-1>", lambda _e: self.reset_priority())
            c.tag_bind("reset", "<Enter>", lambda _e: c.configure(cursor="hand2"))
            c.tag_bind("reset", "<Leave>", lambda _e: c.configure(cursor=""))
            y = c.bbox(t)[3] + 8
        for i, key in enumerate(steps):
            self.list_row(i, key, (8, y, width - 8, y + self.ROW_H))
            y += self.ROW_H + 6
        extras = m["actions"] + m["markers"]
        if m["every"]:
            c.create_text(16, y + 8, anchor="nw", fill=MUTED, font=(FONT, 8), width=width - 32,
                          text="CHECKED BEFORE #1 (every script): "
                               + ", ".join(self.pretty(b["name"]) for b in m["every"]))
            y += 28
        if extras:
            c.create_text(16, y + 8, anchor="nw", fill=MUTED, font=(FONT, 8), width=width - 32,
                          text="NOT RANKED: " + ", ".join(b["name"] for b in extras) +
                               "  -  built-in actions run whenever their window shows; markers "
                               "are only looked at. Switch to Flowchart to open them.")
            y += 40
        c.configure(scrollregion=(0, 0, width, y + 10))

    def list_row(self, i, key, box):
        c, m = self.flow, self.model
        entries = m["groups"][key]
        x1, y1, x2, y2 = box
        tag = self.tag("row", key)
        sel = self.selected == ("step", key)
        live = self.live == key
        c.create_rectangle(x1, y1, x2, y2, fill=PANEL, tags=tag, width=3 if (sel or live) else 1,
                           outline=YELLOW if live else BLUE if sel else FIELD)
        c.create_text(x1 + 30, (y1 + y2) // 2, text=f"#{i + 1}", fill=FG,
                      font=(FONT, 13, "bold"), tags=tag)
        c.create_text(x1 + 62, y1 + 10, anchor="nw", text=self.step_title(key, entries), fill=FG,
                      font=(FONT, 10, "bold"), width=170, tags=tag)
        pressed = m["pressed"].get(key, 0)
        sub = [f"{len(entries)} variant{'s' if len(entries) > 1 else ''}"]
        if pressed:
            sub.append(f"pressed {pressed}x")
        if any(b["counter"] for b in entries):
            sub.append("counts runs")
        c.create_text(x1 + 62, y2 - 10, anchor="sw", text="  ·  ".join(sub), fill=MUTED,
                      font=(FONT, 8), tags=tag)
        tx = x1 + 250
        room = max(1, (x2 - 110 - tx) // (self.LIST_THUMB_W + 8))
        for b in entries[:room]:
            c.create_rectangle(tx, y1 + 9, tx + self.LIST_THUMB_W, y2 - 9, fill=DARK, outline="",
                               tags=tag)
            c.create_image(tx + self.LIST_THUMB_W // 2, (y1 + y2) // 2, tags=tag,
                           image=self.photo(b, self.LIST_THUMB_W - 6, self.LIST_THUMB_H))
            tx += self.LIST_THUMB_W + 8
        if len(entries) > room:
            c.create_text(tx, (y1 + y2) // 2, anchor="w", fill=MUTED, font=(FONT, 9),
                          text=f"+{len(entries) - room}", tags=tag)
        c.tag_bind(tag, "<Button-1>", lambda _e, k=key: self.select(("step", k)))
        last = len(m["priority"]) - 1
        for label, delta, x, ok in (("▲", -1, x2 - 64, i > 0), ("▼", 1, x2 - 28, i < last)):
            bt = self.tag("move", key, delta)
            c.create_rectangle(x - 15, y1 + 16, x + 15, y2 - 16, fill=FIELD if ok else PANEL,
                               outline="", tags=bt)
            c.create_text(x, (y1 + y2) // 2, text=label, fill=FG if ok else GREY,
                          font=(FONT, 11), tags=bt)
            if ok:
                c.tag_bind(bt, "<Button-1>", lambda _e, k=key, d=delta: self.move(k, d))
                c.tag_bind(bt, "<Enter>", lambda _e: c.configure(cursor="hand2"))
                c.tag_bind(bt, "<Leave>", lambda _e: c.configure(cursor=""))

    def move(self, key, delta):
        order = list(self.model["priority"])
        i = order.index(key)
        j = i + delta
        if not 0 <= j < len(order):
            return
        order[i], order[j] = order[j], order[i]
        farm.set_priority_order(self.script, order)
        self.app.log(f"{self.script}: priority is now " + " > ".join(order), "info")
        self.selected = ("step", key)
        self.refresh()

    def reset_priority(self):
        farm.set_priority_order(self.script, [])
        self.app.log(f"{self.script}: priority back to the default order", "info")
        self.refresh()

    def arrow(self, a, b, boxes):
        c, m = self.flow, self.model
        ax1, ay1, ax2, ay2 = boxes[a]
        bx1, by1, bx2, by2 = boxes[b]
        n = m["pairs"].get((a, b))
        out = sum(v for (p, _), v in m["pairs"].items() if p == a)
        learned = m["learned"]
        color = BLUE if n else GREY
        dash = () if n else (4, 3)
        if abs(ay1 - by1) < 2:  # same row: straight across
            pts = (ax2, ay1 + 30, bx1, by1 + 30)
            lx, ly = (ax2 + bx1) // 2, ay1 + 18
        else:  # next row: down, back to the left, down into the card
            mid = max(ay2, by1 - self.GAP_Y) + self.GAP_Y // 2
            pts = ((ax1 + ax2) // 2, ay2, (ax1 + ax2) // 2, mid, (bx1 + bx2) // 2, mid,
                   (bx1 + bx2) // 2, by1)
            lx, ly = (ax1 + ax2) // 2 + 6, ay2 + 12
        c.create_line(*pts, fill=color, width=2, arrow="last", arrowshape=(9, 11, 4), dash=dash)
        if learned and n:
            c.create_text(lx, ly, fill=BLUE, font=(FONT, 8), anchor="center" if abs(ay1 - by1)
                          < 2 else "w", text=f"{n}x" + (f" ({n * 100 // out}%)" if out else ""))

    def card(self, key, box):
        c, m = self.flow, self.model
        entries = m["groups"][key]
        x1, y1, x2, y2 = box
        pressed = m["pressed"].get(key, 0)
        sel = self.selected == ("step", key)
        live = self.live == key
        dim = m["learned"] and not pressed
        outline = YELLOW if live else BLUE if sel else (FIELD if dim else GREY)
        tag = self.tag("step", key)
        c.create_rectangle(x1, y1, x2, y2, fill=PANEL, outline=outline,
                           width=3 if (sel or live) else 1, tags=tag)
        c.create_text(x1 + 10, y1 + 9, anchor="nw", text=self.step_title(key, entries),
                      fill=MUTED if dim else FG, font=(FONT, 10, "bold"), tags=tag,
                      width=self.CARD_W - 20)
        if any(b["counter"] for b in entries):
            c.create_rectangle(x2 - 46, y1 + 8, x2 - 8, y1 + 24, fill=GREEN, outline="", tags=tag)
            c.create_text(x2 - 27, y1 + 16, text="RUN", fill=DARK, font=(FONT, 7, "bold"), tags=tag)
        ty = y1 + 34
        for b in entries:
            c.create_rectangle(x1 + 10, ty, x2 - 10, ty + self.THUMB_H, fill=DARK, outline="",
                               tags=tag)
            c.create_image((x1 + x2) // 2, ty + self.THUMB_H // 2, tags=tag,
                           image=self.photo(b, self.THUMB_W, self.THUMB_H - 4))
            ty += self.THUMB_H + 6
        foot = (f"pressed {pressed}x" if pressed else
                "not pressed in runs yet" if m["learned"] else
                f"{len(entries)} variant{'s' if len(entries) > 1 else ''}")
        if any(b["spot"] for b in entries):
            foot += "  ·  fixed spot"
        c.create_text(x1 + 10, y2 - 16, anchor="w", text=foot, fill=MUTED, font=(FONT, 8),
                      tags=tag)
        c.create_text(x2 - 10, y2 - 16, anchor="e", text=f"#{m['priority'].index(key) + 1}",
                      fill=MUTED, font=(FONT, 8, "bold"), tags=tag)
        c.tag_bind(tag, "<Button-1>", lambda _e, k=key: self.select(("step", k)))
        c.tag_bind(tag, "<Enter>", lambda _e: c.configure(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda _e: c.configure(cursor=""))

    def extra_card(self, label, b, box):
        c = self.flow
        x1, y1, x2, y2 = box
        sel = self.selected == ("entry", b["id"])
        tag = self.tag("entry", b["id"])
        c.create_rectangle(x1, y1, x2, y2, fill=PANEL, outline=BLUE if sel else ORANGE,
                           width=3 if sel else 1, dash=() if sel else (3, 2), tags=tag)
        c.create_text(x1 + 10, y1 + 9, anchor="nw", text=b["name"], fill=FG, width=self.CARD_W - 20,
                      font=(FONT, 9, "bold"), tags=tag)
        c.create_rectangle(x1 + 10, y1 + 34, x2 - 10, y1 + 34 + self.THUMB_H, fill=DARK, outline="",
                           tags=tag)
        c.create_image((x1 + x2) // 2, y1 + 34 + self.THUMB_H // 2, tags=tag,
                       image=self.photo(b, self.THUMB_W, self.THUMB_H - 4))
        c.create_text(x1 + 10, y2 - 16, anchor="w", text=label.lower(), fill=ORANGE,
                      font=(FONT, 8), tags=tag)
        c.tag_bind(tag, "<Button-1>", lambda _e: self.select(("entry", b["id"])))

    def select(self, what):
        self.selected = None if self.selected == what else what
        self.draw_flow()
        self.draw_detail()

    # ---------- the picked card ----------
    def draw_detail(self):
        d, app, m = self.detail, self.app, self.model
        for child in d.winfo_children():
            child.destroy()
        entries = self.find_selected()
        if not entries:
            app.label(d, "Click a card", size=11, bold=True).pack(anchor="w")
            app.label(d, "Its images, what they do, and buttons to re-capture, remove or count "
                         "it as a run show up here.", size=9, color=MUTED, wraplength=270,
                      justify="left").pack(anchor="w", pady=(4, 0))
            if m and m["learned"]:
                app.label(d, "\nArrows: how often the next step came right after this one in "
                             "your runs. Grey cards weren't pressed in any run - an old "
                             "capture, or a screen that just hasn't come up.", size=9,
                          color=MUTED, wraplength=270, justify="left").pack(anchor="w")
            return
        sel = self.selected
        if sel[0] == "step":
            key = sel[1]
            app.label(d, self.step_title(key, entries), size=12, bold=True).pack(anchor="w")
            nxt = sorted(((n, b) for (a, b), n in m["pairs"].items() if a == key), reverse=True)
            rank = m["priority"].index(key) + 1
            info = [f"priority #{rank} of {len(m['priority'])}"
                    + (" (own order)" if m["custom_priority"] else " (default order)")]
            if nxt:
                total = sum(n for n, _ in nxt)
                info.append("next in runs: " + ", ".join(
                    f"{self.step_title(b, m['groups'][b]) if b in m['groups'] else b} "
                    f"{n * 100 // total}%" for n, b in nxt[:4]))
            app.label(d, "\n".join(info), size=9, color=MUTED, wraplength=270,
                      justify="left").pack(anchor="w", pady=(2, 6))
            opts = farm.step_options(self.script).get(key, set())
            box = tk.Frame(d, bg=PANEL)
            box.pack(fill="x", pady=(0, 8))
            for opt, text in farm.STEP_OPTIONS.items():
                var = tk.BooleanVar(value=opt in opts)
                tk.Checkbutton(box, text=text, variable=var, bg=PANEL,
                               fg=BLUE if opt in opts else FG, activebackground=PANEL,
                               activeforeground=FG, selectcolor=FIELD, highlightthickness=0,
                               bd=0, font=(FONT, 9), wraplength=250, justify="left",
                               command=lambda o=opt, v=var: self.set_option(key, o, v.get())).pack(
                    anchor="w")
        if sel[0] == "step":
            app.small_button(d, "Add a variant (capture)", lambda: self.add_variant(sel[1])).pack(
                side="bottom", fill="x", pady=(6, 0))
        # the variants, scrolling if there are more than fit
        holder = tk.Frame(d, bg=PANEL)
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, width=270)
        bar = tk.Scrollbar(holder, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=PANEL)
        canvas.create_window(0, 0, window=body, anchor="nw", width=262)
        for b in entries:
            self.detail_entry(body, b)
        body.update_idletasks()
        canvas.configure(scrollregion=(0, 0, 262, body.winfo_reqheight()))
        if body.winfo_reqheight() > canvas.winfo_height() > 1 or len(entries) > 2:
            bar.pack(side="right", fill="y")
        self.detail_canvas = canvas

    def detail_entry(self, parent, b):
        app = self.app
        box = tk.Frame(parent, bg=FIELD, padx=8, pady=6)
        box.pack(fill="x", pady=(0, 6))
        tk.Label(box, image=self.photo(b, 260, 60), bg=DARK).pack(fill="x")
        app.label(box, b["name"], size=10, bold=True).pack(anchor="w", pady=(4, 0))
        global_only = b.get("every") and not b["used"]   # pressed everywhere, not a step here
        about = (b["about"] if b["action"] else
                 "marker: only looked at, never tapped" if b["marker"] else
                 f"captured in: {b['home']}")
        if global_only:
            about += "\npressed in every script, before its own steps"
        if b.get("spot"):
            about += f"\ntaps a fixed spot ({b['spot'][0]:.0%} across, {b['spot'][1]:.0%} down)"
        app.label(box, about, size=8, color=MUTED, wraplength=250, justify="left").pack(anchor="w")
        if not (b["marker"] or b["action"] or global_only):
            var = tk.BooleanVar(value=b["counter"])
            tk.Checkbutton(box, text="Counts as a run", variable=var, bg=FIELD,
                           fg=GREEN if b["counter"] else FG, activebackground=FIELD,
                           activeforeground=FG, selectcolor=PANEL, highlightthickness=0, bd=0,
                           font=(FONT, 9), command=lambda: self.count(b, var.get())).pack(
                anchor="w", pady=(4, 0))
        if not (b["marker"] or b["action"]):
            evar = tk.BooleanVar(value=bool(b.get("every")))
            tk.Checkbutton(box, text="Press in every script (popups like the Peddler Shop's "
                                     "View Later)", variable=evar, bg=FIELD, wraplength=215,
                           justify="left", fg=ORANGE if b.get("every") else FG,
                           activebackground=FIELD, activeforeground=FG, selectcolor=PANEL,
                           highlightthickness=0, bd=0, font=(FONT, 9),
                           command=lambda: self.every(b, evar.get())).pack(anchor="w", pady=(4, 0))
        if not (b["marker"] or b["action"] or global_only):
            self.step_chooser(box, b)
        grid = tk.Frame(box, bg=FIELD)
        grid.pack(fill="x", pady=(4, 0))
        grid.columnconfigure((0, 1), weight=1)
        buttons = [] if global_only else [("Remove from script", lambda: self.use(b, False))]
        if not b["action"]:
            buttons += [("Delete", lambda: self.delete(b)),
                        ("Re-capture", lambda: self.grab(b["home"], b["name"])),
                        ("From file", lambda: self.load_file(b["home"], b["name"]))]
        for i, (text, cmd) in enumerate(buttons):
            btn = app.small_button(grid, text, cmd)
            btn.configure(bg=PANEL)
            btn.color = PANEL
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 4) if i % 2 == 0 else 0,
                     pady=(0, 3))

    def step_chooser(self, parent, b):
        """'Step: [#2 hire v]' - move this image into another step (as a variant of that
        button) or make it a step of its own."""
        m = self.model
        own = "Its own step"
        labels = {f"#{i + 1}  {self.step_title(k, m['groups'][k])}": k
                  for i, k in enumerate(m["priority"])}
        current = next((lab for lab, k in labels.items() if k == b["step"]), own)
        alone = len(m["groups"].get(b["step"], [])) <= 1
        options = list(labels) + ([] if alone else [own])
        row = tk.Frame(parent, bg=FIELD)
        row.pack(fill="x", pady=(4, 0))
        self.app.label(row, "Step", size=9, color=MUTED).pack(side="left")
        var = tk.StringVar(value=current)
        menu = tk.OptionMenu(row, var, *options,
                             command=lambda lab: self.move_to_step(b, labels.get(lab)))
        menu.config(bg=PANEL, fg=FG, activebackground=GREY, activeforeground=FG, relief="flat",
                    bd=0, highlightthickness=0, font=(FONT, 9), anchor="w")
        menu["menu"].config(bg=FIELD, fg=FG, activebackground=BLUE, activeforeground=DARK,
                            font=(FONT, 9), bd=0)
        menu.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def move_to_step(self, b, key):
        """key = another step (join it as a variant), or None = a step of its own."""
        target = key or b["name"]
        if target == b["step"]:
            return
        farm.set_step(self.script, b["name"], target)
        self.app.log(f"{self.script}: {b['name']} is now "
                     + (f"a variant in step {self.step_title(key, self.model['groups'][key])}"
                        if key else "a step of its own (at the bottom of the priority)"), "info")
        self.selected = ("step", farm.group_key(b["name"], farm.step_map(self.script)))
        self.refresh()

    # ---------- the pool ----------
    def draw_pool(self):
        c = self.pool
        if self.model is None:
            return
        c.delete("all")
        width = max(c.winfo_width(), self.TILE_W + 20)
        word = self.search.get().strip().lower()
        items = [b for b in farm.describe_library(self.script) if not b["used"] and not b["every"]
                 and (not word or word in b["name"].lower() or word in b["home"].lower())]
        if not items:
            c.create_text(width // 2, 40, fill=MUTED, font=(FONT, 10), text=(
                "Nothing matches." if word else
                "Every captured button is in this script. Capture or import more at the top."))
            c.configure(scrollregion=(0, 0, width, 80))
            return
        cols = max(1, (width - 8) // (self.TILE_W + 10))
        th = self.TILE_H + 52
        for i, b in enumerate(items):
            x = 4 + (i % cols) * (self.TILE_W + 10)
            y = 4 + (i // cols) * (th + 10)
            tag = f"pool:{b['id']}"
            c.create_rectangle(x, y, x + self.TILE_W, y + th, fill=PANEL, outline=FIELD, tags=tag)
            c.create_image(x + self.TILE_W // 2, y + 6 + self.TILE_H // 2, tags=tag,
                           image=self.photo(b, self.TILE_W - 12, self.TILE_H))
            name = c.create_text(x + 6, y + self.TILE_H + 12, anchor="nw", fill=FG,
                                 font=(FONT, 8, "bold"), text=b["name"], width=self.TILE_W - 12,
                                 tags=tag)
            c.create_text(x + 6, c.bbox(name)[3] + 1, anchor="nw", fill=MUTED, font=(FONT, 7),
                          text="built-in" if b["action"] else b["home"], width=self.TILE_W - 12,
                          tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda _e, b=b: self.use(b, True))
            c.tag_bind(tag, "<Enter>", lambda _e: c.configure(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda _e: c.configure(cursor=""))
        rows = (len(items) - 1) // cols + 1
        c.configure(scrollregion=(0, 0, width, 8 + rows * (th + 10)))

    # ---------- actions ----------
    def use(self, b, on):
        farm.set_used(self.script, b["id"], on)
        self.app.log(f"{self.script}: {'added' if on else 'removed'} {b['name']} "
                     f"(captured in {b['home']})", "info")
        if on and not b["action"] and not b["marker"]:
            self.selected = ("step", farm.group_key(b["name"], farm.step_map(self.script)))
        self.refresh()

    def every(self, b, on):
        """Press this button in every script (it then leaves this script's own steps)."""
        farm.set_every_script(b["id"], on)
        if on and b["used"]:
            farm.set_used(self.script, b["id"], False)
        self.app.log(f"{b['name']} is {'now pressed in every script' if on else 'no longer pressed in every script'}"
                     + ("" if on else f" (add it to a script from the list to use it there)"), "info")
        self.selected = ("entry", b["id"]) if on else None
        self.refresh()

    def set_option(self, key, option, on):
        farm.set_step_option(self.script, key, option, on)
        what = farm.STEP_OPTIONS[option].split(" (")[0].lower()
        self.app.log(f"{self.script}: step {self.step_title(key, self.model['groups'][key])} - "
                     f"{what}: {'on' if on else 'off'}", "info")
        self.refresh()

    def count(self, b, on):
        farm.set_counter(self.script, b["name"], on)
        now = sorted(farm.counter_names(self.script))
        self.app.log(f"{self.script}: run counter is now {', '.join(now) or 'nothing'}", "info")
        self.refresh()

    def reset_arrows(self):
        if not self.model or not self.model["learned"]:
            messagebox.showinfo("Reset arrows", "No arrows learned yet - they come from runs.",
                                parent=self.win)
            return
        if messagebox.askyesno("Reset arrows", "Forget the order learned from runs? The cards go "
                               "back to priority order until the next run.", parent=self.win):
            farm.reset_flow(self.script)
            self.refresh()

    def export_script(self):
        path = filedialog.asksaveasfilename(
            parent=self.win, title="Export script", defaultextension=farm.SHARE_EXT,
            initialfile=f"{self.script}{farm.SHARE_EXT}",
            filetypes=[("TACMonkey script", f"*{farm.SHARE_EXT}")])
        if not path:
            return
        try:
            count, renamed, missing = farm.export_script(self.script, path)
        except (farm.ShareError, OSError) as e:
            messagebox.showerror("Export script", str(e), parent=self.win)
            return
        notes = [f"{count} button images"]
        if renamed:
            notes.append("renamed (same name in two folders): " +
                         ", ".join(f"{a} -> {b}" for a, b in renamed.items()))
        if missing:
            notes.append("missing on disk, left out: " + ", ".join(missing))
        self.app.log(f"Exported '{self.script}' to {Path(path).name}: " + "; ".join(notes), "good")
        messagebox.showinfo("Export script", f"Saved {Path(path).name}.\n\n" + "\n".join(notes) +
                            "\n\nSend that one file. Your friend opens it with Import script.",
                            parent=self.win)

    def import_script(self):
        self.app.import_script(self.win)

    def ask(self, title, prompt):
        name = simpledialog.askstring(title, prompt, parent=self.win)
        name = (name or "").strip()
        if name and (BAD_CHARS & set(name) or name.startswith(".")):
            messagebox.showerror(title, 'A name can\'t contain \\ / : * ? " < > |',
                                 parent=self.win)
            return None
        return name or None

    def confirm_replace(self, home, name):
        if not (farm.script_dir(home) / f"{name}.png").exists():
            return True
        users = [s for s in farm.list_scripts() if f"{home}/{name}" in farm.used_ids(s)]
        return messagebox.askyesno(
            "Replace image", f"Replace the picture of {name}?\n\nUsed by: "
            f"{', '.join(users) or 'no script'}", parent=self.win)

    def grab(self, home, name, pick=False, step=None):
        """Capture an image; pick=True adds it to this script (into `step`, if given)."""
        if not self.confirm_replace(home, name):
            return
        if not messagebox.askokcancel(
                "Capture from game", "Open the screen with this button in the game first.\n\n"
                "After OK, a capture opens: drag a box around the button, then press Enter "
                "(C cancels).", parent=self.win):
            return
        if pick:
            farm.freeze_use(self.script)

        def done():
            if pick and (farm.script_dir(home) / f"{name}.png").exists():
                if step:
                    farm.set_step(self.script, name, step)
                farm.set_used(self.script, f"{home}/{name}", True)
                self.selected = ("step", farm.group_key(name, farm.step_map(self.script)))
            self.refresh_if_open()

        self.app.grab_image(home, name, done)

    def refresh_if_open(self):
        if self.win.winfo_exists():
            self.refresh()

    def add_grab(self):
        name = self.ask("Capture new button", NAME_HELP)
        if name:
            self.grab(self.script, name, pick=True)

    def add_variant(self, key):
        """Capture another look of the same step (named <first image>_2, _3 ...)."""
        names = {b["name"] for b in farm.describe_library(self.script)}
        base = self.model["groups"][key][0]["name"]
        n = 2
        while f"{base}_{n}" in names:
            n += 1
        self.grab(self.script, f"{base}_{n}", pick=True, step=key)

    def load_file(self, home, name, pick=False):
        path = filedialog.askopenfilename(
            parent=self.win, title=f"Image for {name}",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path or not self.confirm_replace(home, name):
            return
        img = farm.cv2.imread(path, farm.cv2.IMREAD_UNCHANGED)
        if img is None:
            messagebox.showerror("From file", "Couldn't read that image.", parent=self.win)
            return
        if pick:
            farm.freeze_use(self.script)
        _, region = farm.find_window()
        width = region[2] if region else 2405  # assume it was cut from the game at its current size
        farm.save_image(home, name, img, width)
        if pick:
            farm.set_used(self.script, f"{home}/{name}", True)
            self.selected = ("step", farm.group_key(name, farm.step_map(self.script)))
        self.app.log(f"Saved {name}.png (from {Path(path).name}, window width {width})", "good")
        self.refresh()

    def add_file(self):
        name = self.ask("New button from file", NAME_HELP)
        if name:
            self.load_file(self.script, name, pick=True)

    def import_buttons(self):
        if self.app.import_from(self.win):
            self.refresh()

    def delete(self, b):
        users = [s for s in farm.list_scripts() if b["id"] in farm.used_ids(s)]
        if b.get("every"):
            users.append("every script")
        if not messagebox.askyesno(
                "Delete button", f"Delete {b['name']} (captured in {b['home']}) from the list?\n\n"
                f"Used by: {', '.join(users) or 'no script'}\n\nThe file is moved to the "
                f"{b['home']} folder's _old folder, not erased.", parent=self.win):
            return
        for s in users:  # keep their current picks fixed, minus this one
            if s == "every script":
                continue
            farm.set_used(s, b["id"], False)
        if b.get("every"):
            farm.set_every_script(b["id"], False)
        farm.remove_image(b["home"], b["name"])
        self.app.log(f"Deleted {b['name']} (moved to {b['home']}/_old)", "info")
        self.refresh()


if __name__ == "__main__":
    root = tk.Tk()
    try:   # the TACMonkey icon, for this window and every window it opens
        root.iconphoto(True, tk.PhotoImage(file=str(farm.RES_DIR / "icon.png")))
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
