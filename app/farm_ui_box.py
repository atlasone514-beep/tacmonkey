"""Box events tab, Dev page and the "new script" prompt for the TACMonkey window (farm_ui.pyw).

Mixed into farm_ui.App: they use its helpers (label, small_button, card, q, log ...) and the
Genesis farm's pick / count / start machinery, with "box" as a third mode next to "hard" and
"extra". The Dev page is only shown on the developer's PC (Ctrl+Shift+D turns it on).
"""
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

import box_farm
import farm
import live_data
import texts
from texts import t

# set by farm_ui.pyw (use_theme) so the colours match the window
BG = PANEL = FIELD = FG = MUTED = DARK = GREY = BLUE = GREEN = ORANGE = RED = YELLOW = ""
ACCENT_TEXT = NAV_SEL = TILE = ""
FONT = "Segoe UI"


def use_theme(**colors):
    globals().update(colors)


def scroll_area(parent, bg):
    """A frame that scrolls (wheel and bar) inside parent; the bar shows only when needed."""
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
    bar = tk.Scrollbar(parent, command=canvas.yview)
    inner = tk.Frame(canvas, bg=bg)
    item = canvas.create_window(0, 0, window=inner, anchor="nw")
    canvas.configure(yscrollcommand=bar.set)

    def fit(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        need = inner.winfo_reqheight() > canvas.winfo_height() + 2
        if need and not bar.winfo_manager():
            bar.pack(side="right", fill="y", before=canvas)
        elif not need and bar.winfo_manager():
            bar.pack_forget()
            canvas.yview_moveto(0)
    inner.bind("<Configure>", fit)
    canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(item, width=e.width), fit()))
    wheel = lambda e: canvas.yview_scroll(-e.delta // 120, "units") if bar.winfo_manager() else None
    canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
    canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
    canvas.pack(side="left", fill="both", expand=True)
    return inner


def fmt_wait(secs):
    h, m = secs // 3600, secs // 60 % 60
    return f"{h} h {m:02d} min" if h else f"{m} min"


class BoxTab:
    """The Box events tab: live events, a tile per unit with its portrait, search, daily counter."""

    # ---------- data ----------
    def box_load_data(self):
        """The box farm's picks from the live data: {unit: {"stages": quests}} like Genesis."""
        data = self.live
        self.box_units = live_data.units(data)
        self.box_pics = live_data.portraits(data)
        self.genesis_data["box"] = {u: {"stages": qs} for u, qs in self.box_units.items()}

    def box_image(self, code):
        if not code:
            return None
        if code not in self.box_imgs:
            try:
                self.box_imgs[code] = tk.PhotoImage(file=str(live_data.PORTRAITS / f"{code}.png"))
            except tk.TclError:
                self.box_imgs[code] = None
        return self.box_imgs[code]

    # ---------- layout ----------
    def build_box(self, page):
        self.box_imgs, self.box_tiles = {}, {}
        self.box_counter = box_farm.DayCounter()
        self.genesis_vars["box"], self.genesis_counts["box"], self.genesis_spins["box"] = {}, {}, {}
        page = scroll_area(page, BG)
        card = self.page_card(page, "Box events - units", key="box.title")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.box_search = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.box_search, bg=FIELD, fg=FG, relief="flat",
                         insertbackground=FG, font=(FONT, 10))
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        hint = self.label(entry, t("box.search", "Search units"), size=10, color=MUTED)
        self.text_widget(hint, "box.search", "Search units")
        self.box_hint = hint

        def show_hint(*_):
            if self.box_search.get() or entry.focus_get() is entry:
                hint.place_forget()
            else:
                hint.place(x=6, rely=0.5, anchor="w")
        entry.bind("<FocusIn>", show_hint)
        entry.bind("<FocusOut>", show_hint)
        hint.bind("<Button-1>", lambda _e: entry.focus_set())
        self.box_search.trace_add("write", lambda *_: (show_hint(), self.box_filter()))
        self.root.after_idle(show_hint)
        self.box_clock = tk.Label(row, text="", bg=NAV_SEL, fg=ACCENT_TEXT, font=(FONT, 9),
                                  padx=8, pady=3)
        self.box_clock.pack(side="left", padx=(8, 0))
        self.box_refresh_btn = self.small_button(row, "Refresh", self.box_refresh, key="box.refresh")
        self.box_refresh_btn.pack(side="left", padx=(8, 0))
        self.box_body = tk.Frame(card, bg=PANEL)
        self.box_body.pack(fill="x", pady=(6, 0))
        foot = tk.Frame(card, bg=GREY, height=1)
        foot.pack(fill="x", pady=(10, 6))
        self.box_today = self.label(card, "", size=9, color=MUTED, anchor="w", justify="left",
                                    wraplength=540)
        self.box_today.pack(anchor="w")
        self.genesis_info["box"] = self.label(card, "", size=9, color=MUTED, anchor="w")
        self.genesis_info["box"].pack(anchor="w", pady=(2, 0))
        self.live_hooks = getattr(self, "live_hooks", []) + [self.box_rebuild]
        self.box_rebuild()
        self.box_tick_clock()

    def box_rebuild(self):
        """Draw the events and unit tiles again (new live data)."""
        picked = set(self.genesis_selected("box")) if self.genesis_vars.get("box") else set()
        counts = self.genesis_count_map("box") if self.genesis_vars.get("box") else {}
        self.box_load_data()
        for w in self.box_body.winfo_children():
            w.destroy()
        self.box_tiles, self.box_groups = {}, []
        self.genesis_vars["box"], self.genesis_counts["box"], self.genesis_spins["box"] = {}, {}, {}
        data = self.live
        placed = set()
        for eid, ev in data.get("events", {}).items():
            units = []
            for q in ev["quests"]:
                for u in live_data.quest_units(q):
                    if u not in placed and u not in units:
                        units.append(u)
            placed |= set(units)
            if not units:
                continue
            head = tk.Frame(self.box_body, bg=PANEL)
            title = self.label(head, ev.get("name") or eid, size=10, bold=True)
            title.pack(side="left")
            left = self.label(head, "", size=9, color=MUTED)
            left.pack(side="right")
            grid = tk.Frame(self.box_body, bg=PANEL)
            for c in range(3):
                grid.columnconfigure(c, weight=1, uniform="box")
            self.box_groups.append({"eid": eid, "head": head, "grid": grid, "left": left,
                                    "units": units})
            for u in units:
                self.box_tile(grid, u, u in picked, counts.get(u))
        if not self.box_groups:
            self.label(self.box_body, t("box.empty", "No box events are live right now. When one "
                                        "is published it shows up here - on start, or press "
                                        "Refresh."),
                       size=9, color=MUTED, wraplength=540, justify="left").pack(anchor="w",
                                                                                pady=(8, 0))
        self.box_filter()
        self.box_counts_refresh()
        self.genesis_changed()

    def box_tile(self, grid, unit, on, count):
        n = len(self.box_units[unit])
        var = tk.BooleanVar(value=on)
        cnt = tk.IntVar(value=min(count or n, n))
        tile = tk.Frame(grid, bg=TILE, highlightthickness=1, highlightbackground=TILE,
                        padx=6, pady=4, cursor="hand2")
        cb = tk.Checkbutton(tile, variable=var, command=self.genesis_changed, bg=TILE,
                            activebackground=TILE, selectcolor=FIELD, highlightthickness=0, bd=0)
        cb.pack(side="left")
        img = self.box_image(self.box_pics.get(unit))
        pic = tk.Label(tile, bg=TILE, image=img, width=40, height=40) if img else \
            tk.Label(tile, bg=FIELD, fg=MUTED, text=unit[:2].upper(), width=4, height=2,
                     font=(FONT, 9, "bold"))
        pic.pack(side="left", padx=(2, 6))
        text = tk.Frame(tile, bg=TILE)
        text.pack(side="left", fill="x", expand=True)
        name = tk.Label(text, text=unit, bg=TILE, fg=FG, font=(FONT, 10), anchor="w")
        name.pack(fill="x")
        sub = tk.Label(text, text="", bg=TILE, fg=MUTED, font=(FONT, 8), anchor="w")
        sub.pack(fill="x")
        spin = tk.Spinbox(tile, from_=1, to=n, width=2, textvariable=cnt, wrap=False,
                          command=self.genesis_changed, bg=FIELD, fg=FG, buttonbackground=FIELD,
                          insertbackground=FG, relief="flat", font=(FONT, 9), justify="center",
                          highlightthickness=0)
        spin.bind("<KeyRelease>", lambda _e: self.genesis_changed())

        def toggle(_e=None):
            var.set(not var.get())
            self.genesis_changed()
        for w in (tile, pic, text, name, sub):
            w.bind("<Button-1>", toggle)
        self.genesis_vars["box"][unit] = var
        self.genesis_counts["box"][unit] = cnt
        self.genesis_spins["box"][unit] = spin
        self.box_tiles[unit] = {"tile": tile, "sub": sub, "name": name, "grid": grid}

    def box_filter(self):
        """Show the tiles whose unit name matches the search (and their events' headings)."""
        if not hasattr(self, "box_groups"):
            return
        want = self.box_search.get().strip().lower()
        for g in self.box_groups:
            shown = [u for u in g["units"] if want in u.lower()]
            for u in g["units"]:
                self.box_tiles[u]["tile"].grid_forget()
            for i, u in enumerate(shown):
                self.box_tiles[u]["tile"].grid(row=i // 3, column=i % 3, sticky="ew",
                                               padx=(0, 6), pady=3)
            if shown:
                g["head"].pack(fill="x", pady=(10, 2))
                g["grid"].pack(fill="x")
            else:
                g["head"].pack_forget()
                g["grid"].pack_forget()

    def box_counts_refresh(self):
        """Quests left today on every tile and event heading, plus the "today" line."""
        if not hasattr(self, "box_groups"):
            return
        c = self.box_counter
        c.roll()
        for unit, w in self.box_tiles.items():
            qs = self.box_units[unit]
            left = sum(1 for q in qs if not c.finished(box_farm.quest_key(q["event"], q),
                                                       q.get("max") or 1))
            done = left == 0
            w["sub"].config(text=t("box.done_today", "done for today") if done else
                            t("box.tile", "{quests} quest{s} · {left} left",
                              quests=len(qs), s="" if len(qs) == 1 else "s", left=left),
                            fg=GREEN if done else MUTED)
            w["name"].config(fg=MUTED if done else FG)
        for g in self.box_groups:
            left, total = box_farm.left_today(self.live, c, g["eid"])
            g["left"].config(text=t("box.event_left", "{left} of {total} quests left today",
                                    left=left, total=total))
        done = [q["title"] for eid, ev in self.live.get("events", {}).items() for q in ev["quests"]
                if c.done.get(box_farm.quest_key(eid, q))]
        self.box_today.config(text=t("box.today", "Today: {done}", done=", ".join(done))
                              if done else t("box.today_none", "Nothing done today yet."))

    def box_tick_clock(self):
        if self.box_counter.day != box_farm.game_day():
            self.box_counts_refresh()
        self.box_clock.config(text=t("box.reset", "Resets in {wait} (00:00 GMT)",
                                     wait=fmt_wait(box_farm.until_reset())))
        self.root.after(30_000, self.box_tick_clock)

    def box_refresh(self):
        self.enable(self.box_refresh_btn, False)

        def job():
            try:
                self.q.put(("live", live_data.fetch(), True))
            except Exception as e:
                self.q.put(("live_error", str(e), True))
            self.q.put(("grab_done", lambda: self.enable(self.box_refresh_btn, True)))
        threading.Thread(target=job, daemon=True).start()

    def box_farm_job(self, picks, counts):
        """The worker for Start on the Box events tab (called from genesis_go)."""
        return box_farm.BoxFarm(
            data=self.live, counter=box_farm.DayCounter(),
            log=lambda m: self.q.put(("log", m)), stop=self.genesis_stop,
            pause=self.genesis_pause, leaves=self.leaf_settings(),
            status=lambda s: self.q.put(("gstatus", s)),
            on_shards=lambda s: self.q.put(("gshards", s)))


class ScriptOffers:
    """Scripts the developer pushed: ask once per version whether to add them."""

    def scripts_offer(self):
        data = self.live
        seen = self.scripts_seen
        self.scripts_asked = getattr(self, "scripts_asked", set())
        for sid, sc in data.get("scripts", {}).items():
            was = seen.get(sid)
            if was == "never" or (isinstance(was, int) and was >= sc["version"]):
                continue
            if (sid, sc["version"]) in self.scripts_asked:
                continue
            self.scripts_asked.add((sid, sc["version"]))
            self.root.after(300, lambda s=sid, e=dict(sc), u=isinstance(was, int):
                            self.script_offer_dialog(s, e, u))

    def script_offer_dialog(self, sid, sc, update):
        win = tk.Toplevel(self.root, bg=PANEL, padx=18, pady=14)
        win.title("TACMonkey")
        win.transient(self.root)
        win.resizable(False, False)
        head = (t("scripts.offer_update", "New version of {name}", name=sc["name"]) if update
                else t("scripts.offer_new", "New script: {name}", name=sc["name"]))
        self.label(win, head, size=11, bold=True, anchor="w").pack(anchor="w")
        if sc.get("note"):
            self.label(win, sc["note"], size=10, color=FG, anchor="w", justify="left",
                       wraplength=380).pack(anchor="w", pady=(6, 0))
        self.label(win, t("scripts.offer_safe", "It's added as a new script. Your own scripts "
                          "aren't changed."), size=9, color=MUTED, anchor="w", justify="left",
                   wraplength=380).pack(anchor="w", pady=(6, 0))
        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", pady=(14, 0))

        def answer(what):
            win.destroy()
            if what == "add":
                self.script_add(sid, sc)
            elif what == "never":
                self.scripts_seen[sid] = "never"
                self.save_settings()
        self.button(row, t("scripts.add", "Add it"), GREEN, lambda: answer("add")).pack(side="left")
        self.small_button(row, t("scripts.later", "Not now"), lambda: answer("later")).pack(
            side="left", padx=(8, 0))
        self.small_button(row, t("scripts.never", "Never for this one"),
                          lambda: answer("never")).pack(side="left", padx=(8, 0))
        win.protocol("WM_DELETE_WINDOW", lambda: answer("later"))

    def script_add(self, sid, sc):
        self.log(f"Downloading the script {sc['name']}...", "muted")

        def job():
            try:
                raw = live_data.fetch_script(sc)
                folder = Path(tempfile.mkdtemp(prefix="tacmonkey-script-"))
                path = folder / f"{sid}{farm.SHARE_EXT}"
                path.write_bytes(raw)
                name, images, notes = farm.import_script(str(path), name=sc["name"])
            except (live_data.LiveError, farm.ShareError, OSError) as e:
                self.q.put(("log", f"Couldn't add the script {sc['name']}: {e}", "bad"))
                return

            def done():
                self.scripts_seen[sid] = sc["version"]
                self.save_settings()
                self.refresh_scripts()
                self.log(f"Added the script '{name}' ({images} button images). Pick it on the "
                         "Scripts page and press Check screen to see whether its images match."
                         + (f" ({'; '.join(notes)})" if notes else ""), "good")
            self.q.put(("grab_done", done))
        threading.Thread(target=job, daemon=True).start()


class DevPage:
    """Only on the developer's PC: scan box events, push them, scripts and wording to everyone."""

    def dev_on(self):
        return bool(live_data.dev_settings().get("enabled"))

    def dev_toggle(self, _e=None):
        d = live_data.dev_settings()
        d["enabled"] = not d.get("enabled")
        try:
            live_data.save_dev_settings(d)
        except OSError as e:
            self.log(f"Couldn't save the Dev setting: {e}", "bad")
            return
        self.dev_show_nav()
        self.log("Dev page on (Ctrl+Shift+D turns it off)" if d["enabled"] else "Dev page off",
                 "info")
        if d["enabled"]:
            self.show_page("dev")
        elif self.page == "dev":
            self.show_page("story")

    def dev_show_nav(self):
        row = self.nav["dev"]["row"]
        if self.dev_on() and not row.winfo_manager():
            row.pack(fill="x", padx=8, pady=1, before=self.nav_spacer)
        elif not self.dev_on() and row.winfo_manager():
            row.pack_forget()

    # ---------- layout ----------
    def build_dev(self, page):
        self.dev_draft = live_data.load_draft()
        self.dev_busy = False
        self.dev_stop = threading.Event()
        page = scroll_area(page, BG)
        # scan
        card = self.page_card(page, "Box event: scan")
        grid = tk.Frame(card, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.dev_event = tk.StringVar()
        self.dev_choices = {}   # label -> event id
        self.label(grid, "Event", color=MUTED).grid(row=0, column=0, sticky="w")
        self.dev_event_menu = tk.OptionMenu(grid, self.dev_event, "")
        self.style_menu(self.dev_event_menu)
        self.dev_event_menu.grid(row=0, column=1, sticky="ew", padx=6)
        self.dev_btns = [self.small_button(grid, "Read event list", self.dev_read_events)]
        self.dev_btns[-1].grid(row=0, column=2)
        self.dev_name, self.dev_place = tk.StringVar(), tk.StringVar()
        for r, (text, var, hint) in enumerate((("Name for players", self.dev_name, ""),
                                               ("Place (optional)", self.dev_place,
                                                "e.g. Hard, if it has several lists")), 1):
            self.label(grid, text, color=MUTED).grid(row=r, column=0, sticky="w", pady=(6, 0))
            tk.Entry(grid, textvariable=var, bg=FIELD, fg=FG, relief="flat", insertbackground=FG,
                     font=(FONT, 10)).grid(row=r, column=1, sticky="ew", padx=6, pady=(6, 0))
            if hint:
                self.label(grid, hint, size=8, color=MUTED).grid(row=r, column=2, sticky="w",
                                                                pady=(6, 0))
        self.dev_name.trace_add("write", lambda *_: self.dev_name_changed())
        self.dev_event.trace_add("write", lambda *_: self.dev_event_changed())
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        for text, cmd in (("Scan whole event", self.dev_scan_event),
                          ("Scan the open list", self.dev_scan_open),
                          ("Add the open Quest Details", self.dev_scan_detail)):
            b = self.small_button(row, text, cmd)
            b.pack(side="left", padx=(0, 6))
            self.dev_btns.append(b)
        self.dev_stop_btn = self.small_button(row, "Stop scan", self.dev_stop.set)
        self.dev_units = tk.Frame(card, bg=PANEL)
        self.dev_units.pack(fill="x", pady=(8, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        self.dev_summary = self.label(row, "", size=9, color=MUTED)
        self.dev_summary.pack(side="left")
        self.small_button(row, "Clear this event's draft", self.dev_clear).pack(side="right")
        self.small_button(row, "Show quests", self.dev_show_quests).pack(side="right", padx=6)
        # scripts
        card = self.page_card(page, "Scripts: push to everyone")
        grid = tk.Frame(card, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.dev_script, self.dev_note = tk.StringVar(), tk.StringVar()
        self.label(grid, "Script", color=MUTED).grid(row=0, column=0, sticky="w")
        self.dev_script_menu = tk.OptionMenu(grid, self.dev_script, *(farm.list_scripts() or [""]))
        self.style_menu(self.dev_script_menu)
        self.dev_script_menu.grid(row=0, column=1, sticky="ew", padx=6)
        self.label(grid, "What's new", color=MUTED).grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Entry(grid, textvariable=self.dev_note, bg=FIELD, fg=FG, relief="flat",
                 insertbackground=FG, font=(FONT, 10)).grid(row=1, column=1, sticky="ew", padx=6,
                                                            pady=(6, 0))
        self.dev_btns.append(self.small_button(grid, "Push script", self.dev_push_script))
        self.dev_btns[-1].grid(row=1, column=2, pady=(6, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.dev_scripts_label = self.label(row, "", size=9, color=MUTED, anchor="w")
        self.dev_scripts_label.pack(side="left")
        self.dev_btns.append(self.small_button(row, "Remove...", self.dev_remove_script))
        self.dev_btns[-1].pack(side="right")
        # texts
        card = self.page_card(page, "Texts")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.dev_texts_label = self.label(row, "", size=9, color=MUTED)
        self.dev_texts_label.pack(side="left")
        self.small_button(row, "Edit texts...", self.dev_edit_texts).pack(side="right")
        # publish
        card = self.page_card(page, "Publish to everyone")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.dev_live_label = self.label(row, "", size=9)
        self.dev_live_label.pack(side="left")
        self.small_button(row, "Refresh", self.box_refresh).pack(side="right")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        self.dev_publish_btn = self.button(row, "Publish this event", GREEN, self.dev_publish)
        self.dev_publish_btn.pack(side="left")
        self.dev_btns.append(self.dev_publish_btn)
        self.dev_btns.append(self.small_button(row, "Remove an event from live...",
                                               self.dev_remove_event))
        self.dev_btns[-1].pack(side="left", padx=8)
        grid = tk.Frame(card, bg=PANEL)
        grid.pack(fill="x", pady=(10, 0))
        grid.columnconfigure(1, weight=1)
        self.dev_token = tk.StringVar(value=live_data.dev_settings().get("token", ""))
        self.label(grid, "GitHub token", color=MUTED).grid(row=0, column=0, sticky="w")
        tk.Entry(grid, textvariable=self.dev_token, show="•", bg=FIELD, fg=FG, relief="flat",
                 insertbackground=FG, font=(FONT, 10)).grid(row=0, column=1, sticky="ew", padx=6)
        self.small_button(grid, "Save", self.dev_save_token).grid(row=0, column=2)
        link = self.label(card, "Fine-grained token with Contents: read and write on "
                                f"{live_data.REPOS[0]} only. Saved on this PC only (dev.json). "
                                "Make one on GitHub (click here).",
                          size=8, color=MUTED, anchor="w", justify="left", wraplength=540,
                          cursor="hand2")
        link.pack(anchor="w", pady=(4, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(
            "https://github.com/settings/personal-access-tokens/new"))
        self.live_hooks = getattr(self, "live_hooks", []) + [self.dev_refresh]
        self.dev_refresh_choices()
        self.dev_refresh()

    def style_menu(self, menu):
        menu.config(bg=FIELD, fg=FG, activebackground=GREY, activeforeground=FG, relief="flat",
                    bd=0, highlightthickness=0, font=(FONT, 9), anchor="w",
                    disabledforeground=MUTED)
        menu["menu"].config(bg=FIELD, fg=FG, activebackground=BLUE, activeforeground=DARK,
                            font=(FONT, 9), bd=0)

    def set_menu(self, menu, var, options):
        m = menu["menu"]
        m.delete(0, "end")
        for o in options:
            m.add_command(label=o, command=lambda v=o: var.set(v))

    # ---------- state ----------
    def dev_eid(self):
        return self.dev_choices.get(self.dev_event.get())

    def dev_draft_event(self, create=False):
        eid = self.dev_eid()
        if not eid:
            return None, None
        ev = self.dev_draft["events"].get(eid)
        if ev is None and create:
            ev = self.dev_draft["events"][eid] = {"name": self.dev_name.get().strip(),
                                                  "quests": []}
        return eid, ev

    def dev_refresh_choices(self):
        """The event menu: events read from the game, plus drafts and live ones."""
        known = dict(live_data.dev_settings().get("events_seen") or {})
        for eid in list(self.dev_draft["events"]) + list(self.live.get("events", {})):
            known.setdefault(eid, "")
        self.dev_choices = {(f"{eid}  -  {first}" if first else eid): eid
                            for eid, first in known.items()}
        self.set_menu(self.dev_event_menu, self.dev_event, list(self.dev_choices))
        if self.dev_event.get() not in self.dev_choices and self.dev_choices:
            self.dev_event.set(next(iter(self.dev_choices)))

    def dev_event_changed(self):
        eid, ev = self.dev_draft_event()
        live = self.live.get("events", {}).get(eid or "", {})
        self._dev_naming = True
        self.dev_name.set((ev or {}).get("name") or live.get("name") or "")
        self._dev_naming = False
        self.dev_refresh()

    def dev_name_changed(self):
        if getattr(self, "_dev_naming", False):
            return
        eid, ev = self.dev_draft_event()
        if ev is not None:
            ev["name"] = self.dev_name.get().strip()
            live_data.save_draft(self.dev_draft)

    def dev_refresh(self):
        if not hasattr(self, "dev_units"):
            return
        eid, ev = self.dev_draft_event()
        for w in self.dev_units.winfo_children():
            w.destroy()
        quests = (ev or {}).get("quests", [])
        one = {"format": 1, "events": {eid: ev}} if ev else {"format": 1, "events": {}}
        units = live_data.units(one) if ev else {}
        pics = live_data.portraits(one) if ev else {}
        for i, (u, qs) in enumerate(units.items()):
            tile = tk.Frame(self.dev_units, bg=TILE, padx=6, pady=4)
            tile.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, 6), pady=3)
            img = self.box_image(pics.get(u))
            (tk.Label(tile, image=img, bg=TILE) if img else
             tk.Label(tile, text="?", bg=FIELD, fg=MUTED, width=4, height=2)).pack(side="left")
            box = tk.Frame(tile, bg=TILE)
            box.pack(side="left", padx=6)
            tk.Label(box, text=u, bg=TILE, fg=FG, font=(FONT, 10), anchor="w").pack(fill="x")
            pick = tk.Label(box, text=(", ".join(q["title"] for q in qs)[:40] + " · change picture"
                                       if img else "no picture - pick one"),
                            bg=TILE, fg=MUTED if img else ORANGE, font=(FONT, 8), anchor="w",
                            cursor="hand2")
            pick.pack(fill="x")
            pick.bind("<Button-1>", lambda _e, unit=u: self.dev_pick_portrait(unit))
        for c in range(3):
            self.dev_units.columnconfigure(c, weight=1, uniform="dev")
        errors = sum(1 for q in quests if q.get("error"))
        self.dev_summary.config(text=(f"{len(quests)} quests scanned, {len(units)} units"
                                      + (f", {errors} without loot" if errors else ""))
                                if ev else "Nothing scanned for this event yet.")
        live = self.live
        n_ev, n_sc = len(live.get("events", {})), len(live.get("scripts", {}))
        self.dev_live_label.config(text=f"Live: {n_ev} box event{'s' if n_ev != 1 else ''}, "
                                        f"{n_sc} script{'s' if n_sc != 1 else ''}"
                                        + (f" · updated {live['updated']}" if live.get("updated")
                                           else ""))
        self.dev_scripts_label.config(text="Pushed: " + (", ".join(
            f"{s['name']} (v{s['version']})" for s in live.get("scripts", {}).values()) or "none"))
        self.set_menu(self.dev_script_menu, self.dev_script, farm.list_scripts())
        if not self.dev_script.get() and farm.list_scripts():
            self.dev_script.set(farm.list_scripts()[0])
        self.dev_texts_label.config(text=f"{len(live.get('texts', {}))} of {len(texts.DEFAULTS)} "
                                         "texts changed from the built-in wording")
        name = (ev or {}).get("name") or eid or "this event"
        self.dev_publish_btn.config(text=f"Publish {name}"[:40])

    # ---------- scanning ----------
    def dev_work(self, what, job, done=None):
        """Run a scan / publish on a worker thread; the Dev buttons are off meanwhile."""
        if self.dev_busy or self.running() or self.genesis_running():
            self.log("Wait for the farm or the scan that's running to finish first.", "warn")
            return
        self.dev_busy = True
        self.dev_stop.clear()
        for b in self.dev_btns:
            self.enable(b, False)
        self.dev_stop_btn.pack(side="left")
        self.set_state(what)

        def run():
            result, err = None, None
            try:
                result = job()
            except (live_data.LiveError, farm.ShareError, RuntimeError, OSError) as e:
                err = e   # expected: says what to do
            except Exception as e:
                err = e
                farm.log_error(what)   # here, while the traceback is at hand

            def finish():
                self.dev_busy = False
                for b in self.dev_btns:
                    self.enable(b, True)
                self.dev_stop_btn.pack_forget()
                self.set_state("Idle", "")
                if err is not None:
                    self.log(f"{what}: {err}", "bad")
                elif done:
                    done(result)
                self.dev_refresh()
            self.q.put(("grab_done", finish))
        threading.Thread(target=run, daemon=True).start()

    def scanner(self):
        import event_scan
        return event_scan.EventScanner(log=lambda m: self.q.put(("log", m)), stop=self.dev_stop,
                                       status=lambda s: self.q.put(("gstatus", s)))

    def dev_read_events(self):
        sc = self.scanner()

        def done(choices):
            d = live_data.dev_settings()
            d["events_seen"] = {eid: first for eid, first in choices}
            live_data.save_dev_settings(d)
            self.dev_refresh_choices()
            self.log(f"Event list: {len(choices)} events", "good")
        self.dev_work("Reading the event list",
                      lambda: sc.event_choices(lambda s: self.q.put(("log", f"  {s}"))), done)

    def dev_add_quests(self, quests):
        eid, ev = self.dev_draft_event(create=True)
        ev["quests"] = live_data.merge_quests(ev["quests"], quests)
        if not ev.get("name"):
            ev["name"] = self.dev_name.get().strip()
        live_data.save_draft(self.dev_draft)
        found = sorted({u for q in quests for u in live_data.quest_units(q)})
        self.log(f"Scanned {len(quests)} quests" + (f": {', '.join(found)}" if found else
                                                    " (no unit shards in their loot)"), "good")

    def dev_need_event(self):
        if not self.dev_eid():
            messagebox.showinfo("Dev", "Pick the event first (Read event list, with the game "
                                "on Quest > Event).", parent=self.root)
            return False
        return True

    def dev_scan_event(self):
        if not self.dev_need_event():
            return
        sc, eid, place = self.scanner(), self.dev_eid(), self.dev_place.get().strip() or None
        log = lambda s: self.q.put(("log", f"  {s}"))
        self.dev_work(f"Scanning {eid}", lambda: sc.scan_event(eid, place, log)[0],
                      self.dev_add_quests)

    def dev_scan_open(self):
        if not self.dev_need_event():
            return
        sc, place = self.scanner(), self.dev_place.get().strip() or None
        log = lambda s: self.q.put(("log", f"  {s}"))
        self.dev_work("Scanning the open list", lambda: sc.scan_open_list(place, log)[0],
                      self.dev_add_quests)

    def dev_scan_detail(self):
        if not self.dev_need_event():
            return
        from tkinter import simpledialog
        title = simpledialog.askstring("Add the open Quest Details",
                                       "The quest's name (as players should see it):",
                                       parent=self.root)
        if not title or not title.strip():
            return
        sc, place = self.scanner(), self.dev_place.get().strip() or None
        quest = {"title": title.strip(), **({"tab": place} if place else {})}
        self.dev_work("Reading the open Quest Details",
                      lambda: [{**quest, "loot": sc.scan_open_detail()}], self.dev_add_quests)

    def dev_clear(self):
        eid, ev = self.dev_draft_event()
        if ev and messagebox.askyesno("Dev", f"Forget what was scanned for {eid}?",
                                      parent=self.root):
            self.dev_draft["events"].pop(eid, None)
            live_data.save_draft(self.dev_draft)
            self.dev_refresh()

    def dev_show_quests(self):
        eid, ev = self.dev_draft_event()
        if not ev:
            return
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title(f"{ev.get('name') or eid} - quests")
        box = tk.Text(win, bg=DARK, fg=FG, font=("Consolas", 9), width=90, height=24,
                      relief="flat", padx=10, pady=8)
        box.pack(fill="both", expand=True)
        for q in ev["quests"]:
            units = ", ".join(live_data.quest_units(q)) or "-"
            box.insert("end", f"{q['title']}  [{q.get('tab') or '-'}]  {q.get('ap', '?')} AP, "
                              f"{q.get('max', '?')} tries  units: {units}"
                              + (f"  ! {q['error']}" if q.get("error") else "") + "\n")
            box.insert("end", "    " + ", ".join(i["name"] for i in q.get("loot", [])) + "\n")
        box.config(state="disabled")

    def dev_pick_portrait(self, unit):
        """A searchable grid of every portrait; the pick goes into the draft event."""
        eid, ev = self.dev_draft_event()
        if not ev:
            return
        win = tk.Toplevel(self.root, bg=PANEL, padx=10, pady=10)
        win.title(f"Picture for {unit}")
        win.geometry("560x520")
        q = tk.StringVar(value=unit.split()[0].lower()[:3])
        tk.Entry(win, textvariable=q, bg=FIELD, fg=FG, relief="flat", insertbackground=FG,
                 font=(FONT, 10)).pack(fill="x", ipady=3)
        holder = tk.Frame(win, bg=PANEL)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        inner = scroll_area(holder, PANEL)
        codes = live_data.portrait_codes()

        def pick(code):
            ev.setdefault("portraits", {})[unit] = code
            live_data.save_draft(self.dev_draft)
            win.destroy()
            self.dev_refresh()

        def show(*_):
            for w in inner.winfo_children():
                w.destroy()
            want = q.get().strip().lower()
            for i, code in enumerate([c for c in codes if want in c][:120]):
                cell = tk.Frame(inner, bg=TILE, padx=4, pady=4, cursor="hand2")
                cell.grid(row=i // 6, column=i % 6, padx=3, pady=3)
                img = self.box_image(code)
                a = tk.Label(cell, image=img, bg=TILE) if img else tk.Label(cell, text="?")
                a.pack()
                b = tk.Label(cell, text=code, bg=TILE, fg=MUTED, font=(FONT, 8))
                b.pack()
                for w in (cell, a, b):
                    w.bind("<Button-1>", lambda _e, c=code: pick(c))
        q.trace_add("write", show)
        show()

    # ---------- publishing ----------
    def dev_save_token(self):
        d = live_data.dev_settings()
        d["token"] = self.dev_token.get().strip()
        try:
            live_data.save_dev_settings(d)
            self.log("GitHub token saved on this PC (dev.json).", "good")
        except OSError as e:
            self.log(f"Couldn't save the token: {e}", "bad")

    def dev_need_token(self):
        token = self.dev_token.get().strip() or live_data.dev_settings().get("token", "")
        if not token:
            messagebox.showinfo("Dev", "Paste your GitHub token and press Save first.",
                                parent=self.root)
        return token

    def dev_published(self, result):
        url, data = result
        self.live_changed(data)
        self.scripts_seen.update({sid: sc["version"] for sid, sc in data.get("scripts", {}).items()
                                  if self.scripts_seen.get(sid) != "never"})
        self.save_settings()
        self.log(f"Published. Everyone gets it on their next start or Check now. {url}", "good")

    def dev_publish(self):
        eid, ev = self.dev_draft_event()
        token = self.dev_need_token()
        if not token or not self.dev_need_event():
            return
        if not ev or not ev.get("quests"):
            messagebox.showinfo("Dev", "Scan the event first.", parent=self.root)
            return
        name = self.dev_name.get().strip() or ev.get("name") or eid
        units = live_data.units({"format": 1, "events": {eid: ev}})
        no_loot = [q["title"] for q in ev["quests"] if not q.get("loot")]
        if not messagebox.askyesno(
                "Publish", f"Publish '{name}' to everyone?\n\n{len(ev['quests'])} quests, "
                f"{len(units)} units: {', '.join(units) or 'none'}"
                + (f"\n\nNo loot was read for: {', '.join(no_loot)}" if no_loot else "")
                + "\n\nIt replaces what's live for this event.", parent=self.root):
            return
        event = {**ev, "name": name}
        event["quests"] = [{k: v for k, v in q.items() if k not in ("error", "row", "note")}
                           for q in ev["quests"]]
        self.dev_work("Publishing", lambda: live_data.publish_events(token, {eid: event}),
                      self.dev_published)

    def dev_remove_event(self):
        token = self.dev_need_token()
        events = self.live.get("events", {})
        if not token:
            return
        if not events:
            messagebox.showinfo("Dev", "No box events are live.", parent=self.root)
            return
        eid = self.dev_ask_choice("Remove from live", "Which event should go?",
                                  {f"{ev.get('name') or k} ({k})": k for k, ev in events.items()})
        if eid and messagebox.askyesno("Remove", f"Take {eid} off for everyone?",
                                       parent=self.root):
            self.dev_work("Publishing", lambda: live_data.publish_events(token, remove=[eid]),
                          self.dev_published)

    def dev_ask_choice(self, title, text, options):
        """A small window with a list to pick from; returns the picked value or None."""
        win = tk.Toplevel(self.root, bg=PANEL, padx=14, pady=12)
        win.title(title)
        win.transient(self.root)
        self.label(win, text).pack(anchor="w")
        lb = tk.Listbox(win, bg=FIELD, fg=FG, relief="flat", font=(FONT, 10), width=50,
                        height=min(10, len(options)), selectbackground=BLUE)
        lb.pack(fill="x", pady=8)
        for o in options:
            lb.insert("end", o)
        out = {}

        def ok():
            sel = lb.curselection()
            if sel:
                out["v"] = options[lb.get(sel[0])]
            win.destroy()
        self.small_button(win, "OK", ok).pack(side="left")
        self.small_button(win, "Cancel", win.destroy).pack(side="left", padx=6)
        win.grab_set()
        self.root.wait_window(win)
        return out.get("v")

    def dev_push_script(self):
        token = self.dev_need_token()
        script = self.dev_script.get()
        if not token or not script:
            return
        note = self.dev_note.get().strip()
        if not messagebox.askyesno("Push script", f"Push the script '{script}' to everyone?\n\n"
                                   "Each player is asked whether to add it.", parent=self.root):
            return

        def job():
            folder = Path(tempfile.mkdtemp(prefix="tacmonkey-push-"))
            path = folder / f"{live_data.script_id(script)}{farm.SHARE_EXT}"
            count, _renamed, missing = farm.export_script(script, str(path))
            if missing:
                self.q.put(("log", f"  (left out, not on disk: {', '.join(missing)})", "warn"))
            return live_data.publish_script(token, script, note, path.read_bytes())
        self.dev_work("Pushing the script", job, self.dev_published)

    def dev_remove_script(self):
        token = self.dev_need_token()
        scripts = self.live.get("scripts", {})
        if not token or not scripts:
            return
        sid = self.dev_ask_choice("Remove a script", "Stop offering which script? (players who "
                                  "added it keep their copy)",
                                  {f"{sc['name']} (v{sc['version']})": k
                                   for k, sc in scripts.items()})
        if sid:
            self.dev_work("Publishing", lambda: live_data.remove_script(token, sid),
                          self.dev_published)

    # ---------- texts ----------
    def dev_edit_texts(self):
        """Every editable text with its built-in wording; changes go out with Publish texts."""
        win = tk.Toplevel(self.root, bg=PANEL, padx=12, pady=10)
        win.title("Edit texts")
        win.geometry("760x560")
        changed = dict(self.live.get("texts", {}))
        top = tk.Frame(win, bg=PANEL)
        top.pack(fill="x")
        search = tk.StringVar()
        tk.Entry(top, textvariable=search, bg=FIELD, fg=FG, relief="flat", insertbackground=FG,
                 font=(FONT, 10)).pack(side="left", fill="x", expand=True, ipady=3)
        only = tk.BooleanVar(value=False)
        self.check(top, "Changed only", only, lambda: show()).pack(side="left", padx=8)
        body = tk.PanedWindow(win, bg=PANEL, sashwidth=6, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(8, 0))
        lb = tk.Listbox(body, bg=FIELD, fg=FG, relief="flat", font=(FONT, 9),
                        selectbackground=BLUE, exportselection=False, width=34)
        body.add(lb)
        right = tk.Frame(body, bg=PANEL, padx=8)
        body.add(right)
        self.label(right, "Built-in", size=8, color=MUTED).pack(anchor="w")
        builtin = self.label(right, "", size=9, color=MUTED, justify="left", anchor="w",
                             wraplength=380)
        builtin.pack(anchor="w", fill="x")
        self.label(right, "Shown to players", size=8, color=MUTED).pack(anchor="w", pady=(10, 0))
        edit = tk.Text(right, bg=FIELD, fg=FG, relief="flat", insertbackground=FG,
                       font=(FONT, 10), height=8, wrap="word", padx=6, pady=4)
        edit.pack(fill="both", expand=True)
        problem = self.label(right, "", size=9, color=ORANGE, anchor="w", justify="left",
                             wraplength=380)
        problem.pack(anchor="w", fill="x")
        row = tk.Frame(right, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        state = {"key": None, "keys": []}

        def keep():
            key = state["key"]
            if not key:
                return
            text = edit.get("1.0", "end-1c")
            bad = texts.usable(key, text)
            problem.config(text=bad or "")
            if bad:
                return
            if text == texts.DEFAULTS.get(key):
                changed.pop(key, None)
            else:
                changed[key] = text

        def select(_e=None):
            keep()
            sel = lb.curselection()
            if not sel:
                return
            key = state["keys"][sel[0]]
            state["key"] = key
            builtin.config(text=texts.DEFAULTS[key] + f"   ({key})")
            edit.delete("1.0", "end")
            edit.insert("1.0", changed.get(key, texts.DEFAULTS[key]))
            problem.config(text="")

        def show(*_):
            want = search.get().strip().lower()
            lb.delete(0, "end")
            state["keys"] = [k for k in sorted(texts.DEFAULTS)
                             if (want in k.lower() or want in texts.DEFAULTS[k].lower()
                                 or want in changed.get(k, "").lower())
                             and (not only.get() or k in changed)]
            for k in state["keys"]:   # the wording itself; its name shows when picked
                text = " ".join(changed.get(k, texts.DEFAULTS[k]).split())
                lb.insert("end", ("* " if k in changed else "  ") + (text[:60] or k))

        def reset():
            if state["key"]:
                edit.delete("1.0", "end")
                edit.insert("1.0", texts.DEFAULTS[state["key"]])
                keep()
                show()

        def publish():
            keep()
            if problem.cget("text"):
                return
            token = self.dev_need_token()
            if not token:
                return
            if not messagebox.askyesno("Publish texts", f"Publish the wording to everyone? "
                                       f"{len(changed)} texts differ from the built-in ones.",
                                       parent=win):
                return
            self.dev_work("Publishing texts", lambda: live_data.publish_texts(token, changed),
                          self.dev_published)
            win.destroy()

        self.small_button(row, "Back to built-in", reset).pack(side="left")
        self.button(row, "Publish texts", GREEN, publish).pack(side="right")
        lb.bind("<<ListboxSelect>>", select)
        edit.bind("<KeyRelease>", lambda _e: (keep(), None))
        search.trace_add("write", show)
        show()
