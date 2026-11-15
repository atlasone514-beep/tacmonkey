"""Control window for farm.py: start / pause / stop, run limit, live status and log.

Start it by double-clicking this file, or:  python farm_ui.pyw
"""
import base64
import json
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

try:
    import farm
except Exception as e:  # e.g. opencv missing - pythonw has no console to show it
    tk.Tk().withdraw()
    messagebox.showerror("TAC Auto Story",
                         f"Couldn't load farm.py:\n{e}\n\nSetup: pip install opencv-python numpy")
    raise SystemExit(1)

BG, PANEL, FIELD = "#17181c", "#22242b", "#2d3039"
FG, MUTED, DARK = "#e8e8ea", "#8b8d98", "#121316"
GREEN, YELLOW, ORANGE, RED, GREY, BLUE = ("#3ecf8e", "#f2c14e", "#f08c4a", "#ef5f5f",
                                          "#6b6e7a", "#5b9cf5")
FONT = "Segoe UI"
SETTINGS = Path(__file__).with_name("ui_settings.json")  # remembers script and checkboxes
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

        root.title("TAC Auto Story")
        root.configure(bg=BG)
        root.minsize(480, 760)
        root.geometry("500x940")
        self.build()
        self.load_settings()
        self.set_state("Idle", "Open the game on its quest map, then press Start.")
        self.update_buttons()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        root.after(1000, self.tick)
        root.after(400, self.first_run)

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

    def spinbox(self, parent, var, **kw):
        return tk.Spinbox(parent, textvariable=var, width=6, bg=FIELD, fg=FG, relief="flat",
                          buttonbackground=FIELD, insertbackground=FG, justify="center",
                          disabledbackground=PANEL, disabledforeground=MUTED,
                          font=(FONT, 10), **kw)

    def check(self, parent, text, var, command=None):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=PANEL, fg=FG,
                              selectcolor=FIELD, activebackground=PANEL, activeforeground=FG,
                              disabledforeground=MUTED, font=(FONT, 10), anchor="w",
                              highlightthickness=0, bd=0)

    def build(self):
        root = self.root
        tk.Frame(root, bg=BG, height=12).pack()

        # status
        status = self.card(root)
        top = tk.Frame(status, bg=PANEL)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 13, 13, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.status_label = self.label(top, size=13, bold=True, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.detail_label = self.label(status, size=9, color=MUTED, anchor="w", justify="left",
                                       wraplength=420)
        self.detail_label.pack(fill="x", pady=(4, 10))
        stats = tk.Frame(status, bg=PANEL)
        stats.pack(fill="x")
        self.stat_values = {}
        for i, name in enumerate(("Runs", "Time", "Runs / hour")):
            box = tk.Frame(stats, bg=PANEL)
            box.grid(row=0, column=i, sticky="w")
            stats.columnconfigure(i, weight=1)
            self.label(box, name.upper(), size=8, color=MUTED, anchor="w").pack(anchor="w")
            value = self.label(box, "0" if name == "Runs" else "-", size=18, bold=True)
            value.pack(anchor="w")
            self.stat_values[name] = value

        # controls
        controls = tk.Frame(root, bg=BG)
        controls.pack(fill="x", padx=12, pady=10)
        self.start_btn = self.button(controls, "Start", GREEN, self.start)
        self.pause_btn = self.button(controls, "Pause", YELLOW, self.toggle_pause)
        self.stop_btn = self.button(controls, "Stop", RED, self.stop)
        for i, b in enumerate((self.start_btn, self.pause_btn, self.stop_btn)):
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            controls.columnconfigure(i, weight=1)

        # options
        opts = self.card(root)
        self.script = tk.StringVar(value=farm.DEFAULT_SCRIPT)
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x", pady=(0, 10))
        self.label(row, "Script").pack(side="left")
        self.script_menu = tk.OptionMenu(row, self.script, farm.DEFAULT_SCRIPT)
        self.script_menu.config(bg=FIELD, fg=FG, activebackground=GREY, activeforeground=FG,
                                relief="flat", bd=0, highlightthickness=0, font=(FONT, 10),
                                width=13, anchor="w", disabledforeground=MUTED)
        self.script_menu["menu"].config(bg=FIELD, fg=FG, activebackground=BLUE,
                                        activeforeground=DARK, font=(FONT, 10), bd=0)
        self.script_menu.pack(side="left", padx=6)
        self.customizer = None
        self.new_btn = self.small_button(row, "New", self.new_script)
        self.folder_btn = self.small_button(row, "Folder", self.open_folder)
        self.grab_btn = self.small_button(row, "Customize", self.customize)
        for b in (self.grab_btn, self.new_btn, self.folder_btn):
            b.pack(side="left", padx=(0, 4))
        self.refresh_scripts()
        self.max_runs = tk.StringVar(value="0")
        self.threshold = tk.StringVar(value=f"{farm.THRESHOLD:.2f}")
        self.act_switch = tk.BooleanVar(value=True)
        self.on_top = tk.BooleanVar(value=False)
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x")
        self.label(row, "Stop after").pack(side="left")
        self.max_spin = self.spinbox(row, self.max_runs, from_=0, to=9999, increment=1)
        self.max_spin.pack(side="left", padx=6)
        self.label(row, "runs  (0 = never)", color=MUTED).pack(side="left")
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.label(row, "Match threshold").pack(side="left")
        self.thr_spin = self.spinbox(row, self.threshold, from_=0.70, to=0.99, increment=0.01,
                                     format="%.2f")
        self.thr_spin.pack(side="left", padx=6)
        self.label(row, "lower it if a button is missed", color=MUTED).pack(side="left")
        self.act_check = self.check(opts, "Go to the next act when one is finished",
                                    self.act_switch)
        self.act_check.pack(fill="x", pady=(8, 0))
        self.skip_merc = tk.BooleanVar(value=False)
        self.check(opts, "Skip the mercenary (go without hiring) - works mid-run",
                   self.skip_merc, self.toggle_merc).pack(fill="x")
        self.check(opts, "Keep this window on top", self.on_top,
                   lambda: self.root.attributes("-topmost", self.on_top.get())).pack(fill="x")
        row = tk.Frame(opts, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        self.check_btn = self.button(row, "Check screen", BLUE, self.check_screen)
        self.check_btn.pack(side="left")
        self.label(row, "  scores each button image on the game now", size=9,
                   color=MUTED).pack(side="left")

        self.build_genesis(root)

        # log
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        self.label(head, "LOG", size=8, color=MUTED).pack(side="left")
        clear = self.label(head, "clear", size=8, color=MUTED, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda _: self.log_box.delete("1.0", "end"))
        box = tk.Frame(root, bg=DARK)
        box.pack(fill="both", expand=True, padx=12)
        scroll = tk.Scrollbar(box)
        scroll.pack(side="right", fill="y")
        self.log_box = tk.Text(box, bg=DARK, fg=FG, relief="flat", bd=0, wrap="word",
                               font=("Consolas", 9), padx=10, pady=8, height=10,
                               yscrollcommand=scroll.set, insertbackground=FG)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log_box.yview)
        for tag, color in (("good", GREEN), ("muted", MUTED), ("warn", ORANGE), ("bad", RED),
                           ("info", BLUE)):
            self.log_box.tag_config(tag, foreground=color)
        self.label(root, "F8 pause / resume  ·  F9 stop  —  these work from any window",
                   size=8, color=MUTED).pack(pady=8)

    # ---------- Genesis unit farm ----------
    def build_genesis(self, root):
        """Pick units; skip-ticket the Genesis Hard stages that drop their shards."""
        self.genesis_worker = None
        self.genesis_stop = threading.Event()
        self.genesis_data = {}
        try:
            self.genesis_data = json.loads(Path(__file__).with_name("genesis_shards.json")
                                           .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        card = self.card(root, pady=(10, 0))
        head = tk.Frame(card, bg=PANEL)
        head.pack(fill="x")
        self.label(head, "GENESIS UNIT FARM", size=8, color=MUTED).pack(side="left")
        self.label(head, "skip tickets x3 per stage · AP refill: 7 Alchemy Drops", size=8,
                   color=MUTED).pack(side="right")
        grid = tk.Frame(card, bg=PANEL)
        grid.pack(fill="x", pady=(6, 4))
        self.genesis_vars = {}
        units = sorted(self.genesis_data, key=str.lower)
        cols = 3
        for i, unit in enumerate(units):
            var = tk.BooleanVar(value=False)
            n = len(self.genesis_data[unit]["stages"])
            cb = tk.Checkbutton(grid, text=f"{unit} ({n})", variable=var, command=self.genesis_changed,
                                bg=PANEL, fg=FG, activebackground=PANEL, activeforeground=FG,
                                selectcolor=FIELD, highlightthickness=0, bd=0, font=(FONT, 9),
                                anchor="w")
            cb.grid(row=i // cols, column=i % cols, sticky="w", padx=(0, 6))
            self.genesis_vars[unit] = var
        for c in range(cols):
            grid.columnconfigure(c, weight=1)
        if not units:
            self.label(grid, "genesis_shards.json not found", color=RED).grid(row=0, column=0)
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        self.genesis_start = self.button(row, "Start Genesis farm", GREEN, self.genesis_go)
        self.genesis_start.pack(side="left")
        self.genesis_stop_btn = self.button(row, "Stop", RED, self.genesis_halt)
        self.genesis_stop_btn.pack(side="left", padx=6)
        self.genesis_info = self.label(row, "", size=9, color=MUTED)
        self.genesis_info.pack(side="left", padx=4)

    def genesis_selected(self):
        return [u for u, v in self.genesis_vars.items() if v.get()]

    def genesis_stages(self, units):
        return sorted({s["stage"] for u in units for s in self.genesis_data[u]["stages"]},
                      key=lambda k: (-int(k.split("-")[0]), int(k.split("-")[1])))

    def genesis_changed(self):
        units = self.genesis_selected()
        stages = self.genesis_stages(units)
        self.genesis_info.config(text=f"{len(units)} units -> {len(stages)} stages · "
                                      f"{len(stages) * 3} skips" if units else "tick the units to farm")
        self.update_buttons()

    def genesis_running(self):
        return self.genesis_worker is not None and self.genesis_worker.is_alive()

    def genesis_go(self):
        units = self.genesis_selected()
        if not units or self.running() or self.genesis_running():
            return
        self.save_settings()
        stages = self.genesis_stages(units)
        self.genesis_stop = threading.Event()
        self.set_state("Genesis farm", f"{', '.join(units)} -> {len(stages)} stages")
        self.log(f"--- Genesis farm: {', '.join(units)} ---", "muted")

        def job():
            try:
                import genesis_farm
                reason = genesis_farm.GenesisFarm(log=lambda m: self.q.put(("log", m)),
                                                  stop=self.genesis_stop).run(units)
            except Exception as e:
                reason = f"Genesis farm error: {e}"
                self.q.put(("log", reason, "bad"))
            self.q.put(("gdone", reason))

        self.genesis_worker = threading.Thread(target=job, daemon=True)
        self.genesis_worker.start()
        self.update_buttons()

    def genesis_halt(self):
        if self.genesis_running():
            self.genesis_stop.set()
            self.set_state("Stopping...")

    # ---------- helpers ----------
    def log(self, text, tag=None):
        if tag is None:
            low = text.lower()
            tag = ("warn" if "covered" in low or "nothing recognised" in low or "paused" in low
                   or "stuck" in low
                   else "good" if "runs completed" in low or "reached" in low
                   else "info" if "act finished" in low else None)
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
        run = self.running()
        grun = hasattr(self, "genesis_vars") and self.genesis_running()
        self.enable(self.start_btn, not run and not grun)
        self.enable(self.pause_btn, run)
        self.enable(self.stop_btn, run)
        for w in (self.max_spin, self.thr_spin, self.act_check, self.script_menu):
            w.config(state="disabled" if run else "normal")
        self.enable(self.new_btn, not run)
        self.pause_btn.config(text="Resume" if self.state == "Paused" else "Pause")
        if hasattr(self, "genesis_vars"):
            self.enable(self.genesis_start, not run and not grun and bool(self.genesis_selected()))
            self.enable(self.genesis_stop_btn, grun)

    def show_stats(self):
        self.stat_values["Runs"].config(text=str(self.runs))
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
                                             self.script.get()))
        self.worker.start()
        self.update_buttons()

    def work(self, max_runs, act_switch, script):
        try:
            reason = farm.run(max_runs, log=lambda m: self.q.put(("log", m)),
                              stop=self.stop_event, pause=self.pause_event,
                              on_status=lambda s, r, l: self.q.put(("status", s, r, l)),
                              act_switch=act_switch, skip_merc=self.skip_merc_event,
                              script=script)
        except SystemExit as e:
            reason = str(e)
            self.q.put(("log", reason, "bad"))
        except Exception as e:
            reason = f"Error: {e!r}"
            self.q.put(("log", reason, "bad"))
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

    def pick_script(self, name):
        self.script.set(name)
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
        self.refresh_scripts()
        self.pick_script(name)
        self.log("Open Customize to pick its buttons from the list, or capture new ones there.",
                 "muted")

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
        self.toggle_merc()
        for u in s.get("genesis_units", []):
            if u in self.genesis_vars:
                self.genesis_vars[u].set(True)
        self.genesis_changed()

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps({"script": self.script.get(),
                                            "act_switch": self.act_switch.get(),
                                            "skip_merc": self.skip_merc.get(),
                                            "import_asked": self.import_asked,
                                            "genesis_units": self.genesis_selected()}, indent=2))
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
            elif kind == "done":
                self.worker = None
                self.set_state("Stopped", msg[1])
                self.update_buttons()
            elif kind == "check":
                _, (w, h), scores, action = msg
                self.log(f"--- Check screen (window {w}x{h}, threshold {farm.THRESHOLD:.2f}) ---",
                         "muted")
                for name, score in scores:
                    ok = score >= farm.THRESHOLD
                    self.log(f"  {name:<16} {score:.2f}{'  <- seen' if ok else ''}",
                             "good" if ok else "muted")
                self.log(action, "info")
            elif kind == "check_done":
                self.enable(self.check_btn, True)
            elif kind == "grab_done":
                if msg[1]:
                    msg[1]()
            elif kind == "gdone":
                self.genesis_worker = None
                self.set_state("Stopped", msg[1])
                self.update_buttons()
        self.root.after(100, self.poll)

    def tick(self):
        now = time.time()
        if self.running() and self.state != "Paused":
            self.run_time += now - self.tick_from
            self.show_stats()
        self.tick_from = now
        if self.genesis_running() and farm.key_down(farm.VK_F9):   # F9 stops the Genesis farm too
            self.genesis_halt()
        self.root.after(1000, self.tick)

    def close(self):
        self.save_settings()
        if self.genesis_running():
            self.genesis_stop.set()
        if self.running():
            self.stop_event.set()
            self.worker.join(timeout=2)
        self.root.destroy()


NAME_HELP = ("Name for the new button image.\n\n"
             "Start it with a number - lower numbers are checked first\n"
             "(00_ok is checked before 02_hire). Images with the same number are\n"
             "variants of one button. x_ at the start = marker only, never tapped.")


class Customizer:
    """Pick, from every captured button, the ones a script uses."""
    THUMB_W, THUMB_H = 150, 70

    def __init__(self, app, script):
        self.app, self.script = app, script
        self.photos = []  # keep thumbnails alive
        self.only_used = tk.BooleanVar(value=False)
        self.win = win = tk.Toplevel(app.root)
        win.title(f"Customize script - {script}")
        win.configure(bg=BG)
        win.geometry("760x760")
        win.minsize(620, 420)
        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        self.title = app.label(head, "", size=13, bold=True)
        self.title.pack(anchor="w")
        app.label(head, (
            "Every button you have captured is listed here, whichever script it was captured "
            "in. Tick the ones this script should use. They are checked top to bottom and the "
            "first one seen is tapped, so the number at the start is the priority. Tick "
            "'Counts as a run' on the button(s) whose tap means one run is done. "
            "Changes apply on the next Start."),
            size=9, color=MUTED, wraplength=720, justify="left").pack(anchor="w", pady=(2, 8))
        bar = tk.Frame(head, bg=BG)
        bar.pack(fill="x")
        for text, cmd in (("Capture new button", self.add_grab),
                          ("New button from file", self.add_file),
                          ("Import buttons", self.import_buttons)):
            app.small_button(bar, text, cmd).pack(side="left", padx=(0, 6))
        tk.Checkbutton(bar, text="Only show buttons this script uses", variable=self.only_used,
                       command=self.refresh, bg=BG, fg=FG, activebackground=BG,
                       activeforeground=FG, selectcolor=FIELD, highlightthickness=0, bd=0,
                       font=(FONT, 9)).pack(side="right")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(body, command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner_id = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.inner_id,
                                                                           width=e.width))
        win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))
        self.refresh()

    def thumb(self, img):
        h, w = img.shape[:2]
        s = min(self.THUMB_W / w, self.THUMB_H / h, 1.0)
        small = farm.cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                                interpolation=farm.cv2.INTER_AREA)
        _, buf = farm.cv2.imencode(".png", small)
        photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        self.photos.append(photo)
        return photo

    def describe(self, b):
        if b["action"]:
            return f"built-in action (no image)\n{b['about']}"
        parts = ["marker: only used to spot a finished act, never tapped" if b["marker"]
                 else f"priority {b['name'].split('_')[0]}",
                 f"captured in: {b['home']}"]
        if b["spot"] and b["used"]:
            parts.append(f"taps a fixed spot ({b['spot'][0]:.0%} across, "
                         f"{b['spot'][1]:.0%} down) instead of the image")
        return "\n".join(parts)

    def refresh(self):
        y = self.canvas.yview()[0]
        for child in self.inner.winfo_children():
            child.destroy()
        self.photos.clear()
        buttons = farm.describe_library(self.script)
        used = sum(b["used"] for b in buttons)
        self.title.config(text=f"Script: {self.script}   -   {used} of {len(buttons)} "
                               "captured buttons used")
        app = self.app
        for b in buttons:
            if self.only_used.get() and not b["used"]:
                continue
            row = tk.Frame(self.inner, bg=PANEL if b["used"] else BG, padx=10, pady=8,
                           highlightthickness=1,
                           highlightbackground=GREEN if b["used"] else FIELD)
            row.pack(fill="x", pady=(0, 6))
            bg = row["bg"]
            pic = tk.Frame(row, bg=DARK, width=self.THUMB_W + 8, height=self.THUMB_H + 8)
            pic.pack(side="left", padx=(0, 12))
            pic.pack_propagate(False)
            tk.Label(pic, image=self.thumb(b["img"]), bg=DARK).pack(expand=True)
            actions = tk.Frame(row, bg=bg)
            actions.pack(side="right")
            for text, cmd in (("Re-capture", lambda b=b: self.grab(b["home"], b["name"])),
                              ("From file", lambda b=b: self.load_file(b["home"], b["name"])),
                              ("Delete", lambda b=b: self.delete(b))):
                if not b["action"]:
                    app.small_button(actions, text, cmd).pack(fill="x", pady=1)
            text = tk.Frame(row, bg=bg)
            text.pack(side="left", fill="x", expand=True)
            app.label(text, b["name"], size=11, bold=True,
                      color=FG if b["used"] else MUTED).pack(anchor="w")
            app.label(text, self.describe(b), size=9, color=MUTED, wraplength=320,
                      justify="left").pack(anchor="w")
            ticks = tk.Frame(text, bg=bg)
            ticks.pack(anchor="w", pady=(4, 0))
            for w in (text, ticks):
                w.configure(bg=bg)
            self.check_row(ticks, b)
        self.win.update_idletasks()
        self.canvas.yview_moveto(y)

    def check_row(self, parent, b):
        bg = parent["bg"]
        for text, value, cmd, color in (
                ("Use in this script", b["used"], lambda on, b=b: self.use(b, on),
                 GREEN if b["used"] else FG),
                ("Counts as a run", b["counter"], lambda on, b=b: self.count(b, on),
                 GREEN if b["counter"] else FG)):
            if (b["marker"] or b["action"]) and text == "Counts as a run":
                continue
            var = tk.BooleanVar(value=value)
            tk.Checkbutton(parent, text=text, variable=var, bg=bg, fg=color,
                           activebackground=bg, activeforeground=FG, selectcolor=FIELD,
                           highlightthickness=0, bd=0, font=(FONT, 9),
                           command=lambda c=cmd, v=var: c(v.get())).pack(side="left",
                                                                         padx=(0, 14))

    # ---------- actions ----------
    def use(self, b, on):
        farm.set_used(self.script, b["id"], on)
        self.app.log(f"{self.script}: {'using' if on else 'not using'} {b['name']} "
                     f"(captured in {b['home']})", "info")
        self.refresh()

    def count(self, b, on):
        farm.set_counter(self.script, b["name"], on)
        now = sorted(farm.counter_names(self.script))
        self.app.log(f"{self.script}: run counter is now {', '.join(now) or 'nothing'}", "info")
        self.refresh()

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

    def grab(self, home, name, pick=False):
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
                farm.set_used(self.script, f"{home}/{name}", True)
            self.refresh_if_open()

        self.app.grab_image(home, name, done)

    def refresh_if_open(self):
        if self.win.winfo_exists():
            self.refresh()

    def add_grab(self):
        name = self.ask("Capture new button", NAME_HELP)
        if name:
            self.grab(self.script, name, pick=True)

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
        if not messagebox.askyesno(
                "Delete button", f"Delete {b['name']} (captured in {b['home']}) from the list?\n\n"
                f"Used by: {', '.join(users) or 'no script'}\n\nThe file is moved to the "
                f"{b['home']} folder's _old folder, not erased.", parent=self.win):
            return
        for s in users:  # keep their current picks fixed, minus this one
            farm.set_used(s, b["id"], False)
        farm.remove_image(b["home"], b["name"])
        self.app.log(f"Deleted {b['name']} (moved to {b['home']}/_old)", "info")
        self.refresh()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
