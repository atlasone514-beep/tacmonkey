"""Box events tab, Dev page and the "new script" prompt for the TACMonkey window (farm_ui.pyw).

Mixed into farm_ui.App: they use its helpers (label, small_button, card, q, log ...) and the
Genesis farm's pick / count / start machinery, with "box" as a third mode next to "hard" and
"extra". The Dev page is only shown on the developer's PC (Ctrl+Shift+D turns it on).
"""
import itertools
import json
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
ARCHIVE_BG, ARCHIVE_FG = "#352f4f", "#c4b5fd"   # the Archive tags


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
        self.box_owners = box_farm.quest_owners(data)
        self.box_pics = live_data.portraits(data)
        self.genesis_data["box"] = {u: {"stages": qs} for u, qs in self.box_units.items()}

    def box_quests(self, unit):
        """A box unit's quests (with Solo stages only: without the ones shared with units that
        aren't ticked)."""
        return box_farm.unit_quests(self.live, unit, self.genesis_selected("box"),
                                    self.box_solo.get(), self.box_units, self.box_owners)

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
        self.box_refresh_btn.pack(side="right", padx=(8, 0))
        srow = tk.Frame(card, bg=PANEL)
        srow.pack(fill="x", pady=(6, 0))
        self.label(srow, "Clear in this order", size=9, color=MUTED, key="box.order").pack(
            side="left")
        self.box_order_var = tk.StringVar()
        self.box_order_btn = tk.OptionMenu(srow, self.box_order_var, "")
        self.style_menu(self.box_order_btn)
        self.box_order_btn.pack(side="left", padx=(6, 0))
        self.check(srow, "Solo stages only", self.box_solo, self.box_solo_changed,
                   key="box.solo").pack(side="right")
        self.box_star_note = self.label(srow, "* only shared stages, kept", size=8, color=MUTED,
                                        key="box.star_note")
        self.box_body = tk.Frame(card, bg=PANEL)
        self.box_body.pack(fill="x", pady=(6, 0))
        foot = tk.Frame(card, bg=GREY, height=1)
        foot.pack(fill="x", pady=(10, 6))
        self.box_today = self.label(card, "", size=9, color=MUTED, anchor="w", justify="left",
                                    wraplength=540)
        self.box_today.pack(anchor="w")
        self.genesis_info["box"] = self.label(card, "", size=9, color=MUTED, anchor="w")
        self.genesis_info["box"].pack(anchor="w", pady=(2, 0))
        gcard = self.page_card(page, "Genesis (Hard) - units", key="genesis.title")
        self.genesis_body = tk.Frame(gcard, bg=PANEL)
        self.genesis_body.pack(fill="x")
        self.genesis_info["hard"] = self.label(gcard, "", size=9, color=MUTED, anchor="w")
        self.genesis_info["hard"].pack(anchor="w", pady=(8, 0))
        self.live_hooks = getattr(self, "live_hooks", []) + [self.box_rebuild]
        self.box_rebuild()
        self.box_tick_clock()

    # ---------- clearing order ----------
    KIND_NAMES = {"event": "Events", "archive": "Archive", "genesis": "Genesis"}

    def order_text(self, order):
        return " › ".join(t(f"box.kind_{k}", self.KIND_NAMES[k]) for k in order)

    def box_order_now(self):
        return live_data.clear_order(self.live, getattr(self, "box_order", None))

    def box_events_in_order(self):
        """[(event id, event)] grouped by kind in the clearing order (the file's order inside a
        group)."""
        order = self.box_order_now()
        evs = list(self.live.get("events", {}).items())
        return sorted(evs, key=lambda kv: order.index(live_data.event_kind(kv[1])))

    def box_order_menu(self):
        """The Box page's clearing order menu: the developer's order, then every order."""
        if not hasattr(self, "box_order_btn"):
            return
        dev = t("box.order_dev", "Developer's order: {order}",
                order=self.order_text(live_data.clear_order(self.live)))
        m = self.box_order_btn["menu"]
        m.delete(0, "end")
        m.add_command(label=dev, command=lambda: self.box_order_pick([]))
        for o in itertools.permutations(live_data.KINDS):
            m.add_command(label=self.order_text(o),
                          command=lambda o=list(o): self.box_order_pick(o))
        self.box_order_var.set(self.order_text(self.box_order) if self.box_order else dev)

    def box_order_pick(self, order):
        if self.running() or self.genesis_running():
            self.box_order_menu()   # a run already has its order: change it once it's done
            return
        self.box_order = order
        self.save_settings()
        self.box_rebuild()   # the events listed in the new order

    def box_rebuild(self):
        """Draw the groups and unit tiles again: one per live box event (in the clearing
        order), then Genesis."""
        keep = {m: (set(self.genesis_selected(m)), self.genesis_count_map(m))
                for m in ("box", "hard") if self.genesis_vars.get(m)}
        self.box_load_data()
        for w in self.box_body.winfo_children() + self.genesis_body.winfo_children():
            w.destroy()
        self.box_tiles, self.box_groups = {}, []
        for m in ("box", "hard"):
            self.genesis_vars[m], self.genesis_counts[m], self.genesis_spins[m] = {}, {}, {}
        self.genesis_star = {}
        self.box_star = {}   # box units with only shared quests: a * with Solo stages only
        if not self.live.get("events"):
            self.label(self.box_body, t("box.empty", "No box events are live right now. When one "
                                        "is published it shows up here - on start, or press "
                                        "Refresh."),
                       size=9, color=MUTED, wraplength=540, justify="left",
                       key=False).pack(anchor="w", pady=(8, 0))
        picked, counts = keep.get("box", (set(), {}))
        placed = set()
        # a unit shows once: under the event it's a main unit of, else the first it drops in
        home = {}
        for eid, ev in self.live.get("events", {}).items():
            for u in live_data.main_units(ev):
                home.setdefault(u, eid)
        for eid, ev in self.box_events_in_order():
            units = []
            for q in ev["quests"]:
                for u in live_data.quest_units(q):
                    if u not in placed and u not in units and home.get(u, eid) == eid:
                        units.append(u)
            placed |= set(units)
            if not units:
                continue
            mains = [u for u in live_data.main_units(ev) if u in units]
            # main units first; the others fold away under them
            units = mains + [u for u in units if u not in mains]
            g = self.box_group(ev.get("name") or eid, eid)
            g["mains"] = set(mains)
            if ev.get("list") == "archive":
                tk.Label(g["head"], text=t("box.archive_tag", "Archive"), bg=ARCHIVE_BG,
                         fg=ARCHIVE_FG, font=(FONT, 8), padx=6).pack(side="left", padx=(0, 8),
                                                                     before=g["left"])
            for u in units:
                self.box_tile(g, "box", u, u in picked, counts.get(u))
        # Genesis Hard: the same tiles, farmed after the box quests by the same Start
        gdata = self.genesis_data.get("hard", {})
        if gdata:
            picked, counts = keep.get("hard", (set(), {}))
            g = self.box_group("", "genesis", self.genesis_body)
            self.check(g["head"], "Solo stages only", self.genesis_solo,
                       self.genesis_changed).pack(side="right")
            self.genesis_star_note = self.label(g["head"], "* only shared stages, kept",
                                                size=8, color=MUTED)
            for u in sorted(gdata, key=str.lower):
                self.box_tile(g, "hard", u, u in picked, counts.get(u))
        self.box_filter()
        self.box_counts_refresh()
        self.genesis_changed()
        self.box_order_menu()

    def box_group(self, title, gid, parent=None):
        parent = parent or self.box_body
        head = tk.Frame(parent, bg=PANEL)
        if title:
            self.label(head, title, size=10, bold=True, key=False).pack(side="left",
                                                                       padx=(0, 10))
        left = self.label(head, "", size=9, color=MUTED, key=False)
        left.pack(side="left")
        grid = tk.Frame(parent, bg=PANEL)
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="box")
        fold = tk.Label(parent, text="", bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w",
                        cursor="hand2")
        fold.bind("<Button-1>", lambda _e: self.box_toggle_others(gid))
        g = {"id": gid, "head": head, "grid": grid, "left": left, "keys": [], "mains": set(),
             "fold": fold}
        self.box_groups.append(g)
        return g

    def unit_quests(self, mode, unit):
        """The quests (box) or stages (Genesis) a tile stands for, with their daily-counter keys."""
        if mode == "box":
            return [(box_farm.quest_key(q["event"], q), q.get("max") or 1)
                    for q in self.box_quests(unit)]
        import genesis_farm
        stages = genesis_farm.unit_stages(self.genesis_data["hard"], unit,
                                          self.genesis_selected("hard"), self.genesis_solo.get(),
                                          self.genesis_owners)
        return [(f"genesis|{s['stage']}", genesis_farm.SKIPS) for s in stages]

    def box_tile(self, g, mode, unit, on, count):
        key = unit if mode == "box" else (mode, unit)
        n = len(self.genesis_data[mode][unit]["stages"])
        var = tk.BooleanVar(value=on)
        cnt = tk.IntVar(value=min(count or n, n))
        tile = tk.Frame(g["grid"], bg=TILE, highlightthickness=1, highlightbackground=TILE,
                        padx=6, pady=4, cursor="hand2")
        cb = tk.Checkbutton(tile, variable=var, command=lambda: self.box_ticked(mode, unit, var),
                            bg=TILE, fg="#ffffff", activeforeground="#ffffff",   # the check: white
                            activebackground=TILE, selectcolor=FIELD, highlightthickness=0, bd=0)
        cb.pack(side="left")
        code = (self.box_pics.get(unit) if mode == "box" else
                live_data.guess_portrait(self.genesis_data["hard"][unit].get("item", ""),
                                         self.portrait_list()))
        img = self.box_image(code)
        pic = tk.Label(tile, bg=TILE, image=img, width=40, height=40) if img else \
            tk.Label(tile, bg=FIELD, fg=MUTED, text=unit[:2].upper(), width=4, height=2,
                     font=(FONT, 9, "bold"))
        pic.pack(side="left", padx=(2, 6))
        text = tk.Frame(tile, bg=TILE)
        text.pack(side="left", fill="x", expand=True)
        line = tk.Frame(text, bg=TILE)
        line.pack(fill="x")
        name = tk.Label(line, text=unit, bg=TILE, fg=FG, font=(FONT, 10), anchor="w")
        name.pack(side="left")
        if mode == "box" and unit in g["mains"]:
            badge = tk.Label(line, text=t("box.main_unit", "Main unit"), bg="#4a3b17", fg=YELLOW,
                             font=(FONT, 8), padx=5)
            badge.pack(side="left", padx=(6, 0))
            badge.bind("<Button-1>", lambda _e: toggle())
        line.bind("<Button-1>", lambda _e: toggle())
        sub = tk.Label(text, text="", bg=TILE, fg=MUTED, font=(FONT, 8), anchor="w")
        sub.pack(fill="x")
        spin = tk.Spinbox(tile, from_=1, to=n, width=2, textvariable=cnt, wrap=False,
                          command=self.genesis_changed, bg=FIELD, fg=FG, buttonbackground=FIELD,
                          insertbackground=FG, relief="flat", font=(FONT, 9), justify="center",
                          highlightthickness=0)
        spin.bind("<KeyRelease>", lambda _e: self.genesis_changed())

        def toggle(_e=None):
            var.set(not var.get())
            self.box_ticked(mode, unit, var)
        for w in (tile, pic, text, name, sub):
            w.bind("<Button-1>", toggle)
        self.genesis_vars[mode][unit] = var
        self.genesis_counts[mode][unit] = cnt
        self.genesis_spins[mode][unit] = spin
        if mode == "hard" and self.genesis_shared_only(unit):
            self.genesis_star[unit] = name   # gets a * while Solo stages only is ticked
        if mode == "box" and box_farm.shared_only(self.box_units, unit, self.box_owners):
            self.box_star[unit] = name
        self.box_tiles[key] = {"tile": tile, "sub": sub, "name": name, "mode": mode,
                               "unit": unit}
        g["keys"].append(key)

    def box_ticked(self, mode, unit, var):
        """A tile was ticked or unticked."""
        self.genesis_changed()
        if mode == "box" and self.box_solo.get():
            self.box_counts_refresh()   # a shared quest counts once all its units are ticked

    def box_solo_changed(self):
        """Solo stages only (box events): the counts, the stars and the note follow."""
        self.save_settings()
        self.genesis_changed()
        self.box_counts_refresh()

    def portrait_list(self):
        if not hasattr(self, "_portrait_codes"):
            self._portrait_codes = live_data.portrait_codes()
        return self._portrait_codes

    def box_filter(self):
        """Show the tiles whose unit name matches the search (and their groups' headings). An
        event with main units shows those (plus ticked ones) until its other units are opened;
        a search shows every match."""
        if not hasattr(self, "box_groups"):
            return
        want = self.box_search.get().strip().lower()
        opened = getattr(self, "box_others_open", set())
        for g in self.box_groups:
            shown = [k for k in g["keys"] if want in self.box_tiles[k]["unit"].lower()]
            others = [k for k in g["keys"] if k not in g["mains"]] if g["mains"] else []
            fold = bool(others) and not want
            if fold and g["id"] not in opened:
                ticked = lambda k: self.genesis_vars["box"][k].get()
                shown = [k for k in shown if k in g["mains"] or ticked(k)]
            hidden = [k for k in others if k not in shown]
            g["fold"].config(text=(t("box.others_hide", "▾  Hide the other units")
                                   if fold and not hidden else
                                   t("box.others", "▸  {n} other units ({names})", n=len(hidden),
                                     names=", ".join(self.box_tiles[k]["unit"] for k in hidden[:5])
                                     + ("..." if len(hidden) > 5 else ""))))
            for k in g["keys"]:
                self.box_tiles[k]["tile"].grid_forget()
            for i, k in enumerate(shown):
                self.box_tiles[k]["tile"].grid(row=i // 3, column=i % 3, sticky="ew",
                                               padx=(0, 6), pady=3)
            if shown:
                g["head"].pack(fill="x", pady=(10 if g["id"] != "genesis" else 0, 2))
                g["grid"].pack(fill="x")
                if fold:
                    g["fold"].pack(fill="x", pady=(2, 0), after=g["grid"])
                else:
                    g["fold"].pack_forget()
            else:
                g["head"].pack_forget()
                g["grid"].pack_forget()
                g["fold"].pack_forget()

    def box_toggle_others(self, gid):
        """Open or fold an event's units other than its main unit."""
        opened = self.box_others_open = getattr(self, "box_others_open", set())
        opened.symmetric_difference_update({gid})
        self.box_filter()

    def box_counts_refresh(self):
        """What's left today on every tile and group heading, plus the "today" line."""
        if not hasattr(self, "box_groups"):
            return
        c = self.box_counter
        c.roll()
        for key, w in self.box_tiles.items():
            qs = self.unit_quests(w["mode"], w["unit"])
            left = sum(1 for k, most in qs if not c.finished(k, most))
            done = bool(qs) and left == 0
            word = "quest" if w["mode"] == "box" else "stage"
            w["sub"].config(text=t("box.done_today", "done for today") if done else
                            t("box.tile", "{quests} {word}{s} · {left} left", quests=len(qs),
                              word=word, s="" if len(qs) == 1 else "s", left=left),
                            fg=GREEN if done else MUTED)
            w["name"].config(fg=MUTED if done else FG)
        for g in self.box_groups:
            if g["id"] == "genesis":
                keys = [f"genesis|{s}" for s in self.genesis_owners]
                left = sum(1 for k in keys if not c.finished(k, 3))
                g["left"].config(text=t("box.genesis_left", "{left} of {total} stages left today",
                                        left=left, total=len(keys)))
            else:
                left, total = box_farm.left_today(self.live, c, g["id"])
                ticked = sum(1 for k in g["keys"] if self.genesis_vars["box"][k].get())
                g["left"].config(text=t("box.event_left", "{left} of {total} quests left today",
                                        left=left, total=total)
                                 + (t("box.event_ticked", " · {n} ticked", n=ticked)
                                    if ticked else ""))
        done = [q["title"] for eid, ev in self.live.get("events", {}).items() for q in ev["quests"]
                if c.done.get(box_farm.quest_key(eid, q))]
        gdone = sorted((k.split("|", 1)[1] for k in c.done if k.startswith("genesis|")),
                       key=lambda s: [int(x) for x in s.split("-")] if s.replace("-", "").isdigit()
                       else [0])
        if gdone:
            done.append(t("box.today_genesis", "Genesis {stages}", stages=", ".join(gdone)))
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

    def box_go(self):
        """Start on the Box events tab: the ticked box quests, then the ticked Genesis stages,
        with one stop / pause and the Leaves limits counted across both."""
        picks, gpicks = self.genesis_selected("box"), self.genesis_selected("hard")
        if not (picks or gpicks) or self.running() or self.genesis_running():
            return
        import genesis_farm
        self.genesis_mode = "box"
        self.save_settings()
        counts, gcounts = self.genesis_count_map("box"), self.genesis_count_map("hard")
        solo, bsolo = self.genesis_solo.get(), self.box_solo.get()
        name = ("Box + Genesis farm" if picks and gpicks else "Box farm" if picks
                else "Genesis farm")
        self.genesis_stop, self.genesis_pause = threading.Event(), threading.Event()
        leaves = self.leaf_settings()
        self.genesis_name = name
        self.last_shards = {}
        what = ", ".join(picks + gpicks)
        self.set_state(name, what)
        self.log(f"--- {name}: {what} ---", "muted")
        self.log(f"Clearing order: {self.order_text(self.box_order_now())}", "muted")
        put = self.q.put
        common = dict(log=lambda m: put(("log", m)), stop=self.genesis_stop,
                      pause=self.genesis_pause, leaves=leaves,
                      status=lambda s: put(("gstatus", s)))

        jobs = self.box_jobs(picks, gpicks)

        def job():
            put(("gdone", self.run_queue(jobs, counts, gcounts, solo, common, name, bsolo)))

        self.genesis_worker = threading.Thread(target=job, daemon=True)
        self.genesis_worker.start()
        self.update_buttons()

    def box_jobs(self, picks, gpicks):
        """[(kind, event id, units)]: each box event with ticked units on its own, then Genesis
        (its stages go chapter by chapter, each chapter opened once), grouped in the clearing
        order: e.g. every Boss Battle Quest event, then every Event Archives one, then Genesis."""
        jobs = []
        for eid, ev in self.box_events_in_order():
            here = [u for u in picks if any(q["event"] == eid for q in self.box_quests(u))]
            if here:
                jobs.append(("box", eid, here))
        if gpicks:
            jobs.append(("genesis", None, list(gpicks)))
        order = self.box_order_now()
        rank = lambda j: order.index("genesis" if j[0] == "genesis"
                                     else live_data.event_kind(self.live["events"][j[1]]))
        return sorted(jobs, key=rank)

    def run_queue(self, jobs, counts, gcounts, solo, common, name, bsolo=False):
        """Run the jobs one after another (worker thread). A job that stays stuck after its
        grace periods is given up and the next one starts; Stop, a Leaves limit or an
        unexpected error end the whole run. Returns the reason shown at the end."""
        import genesis_farm
        put = self.q.put
        used, got, done, failed = 0, {}, [], []
        merged = lambda s: {**got, **{u: got.get(u, 0) + n for u, n in s.items()}}
        for kind, eid, units in jobs:
            title = (self.live["events"][eid].get("name") or eid) if kind == "box" else "Genesis"
            put(("log", f"=== {title}: {', '.join(units)} ===", "info"))
            put(("gstatus", f"{title} ({len(done) + len(failed) + 1} of {len(jobs)})"))
            f = None
            try:
                if kind == "box":
                    data = {"format": 1, "events": {eid: self.live["events"][eid]}}
                    f = box_farm.BoxFarm(data=data, counter=box_farm.DayCounter(),
                                         on_shards=lambda s: put(("gshards", merged(s))),
                                         **common)
                    f.leaves_used = used   # "at most N per session" covers the whole run
                    f.mapper.free_unlock = self.archive_unlock.get()
                    reason = f.run(units, counts, bsolo)
                else:
                    f = genesis_farm.GenesisFarm(mode="hard", counter=box_farm.DayCounter(),
                                                 on_shards=lambda s: put(("gshards", merged(s))),
                                                 **common)
                    f.leaves_used = used
                    reason = f.run(units, gcounts, solo)
            except RuntimeError as e:   # stuck even after the grace periods: next job
                failed.append(title)
                put(("log", f"{title}: given up ({e}) - going on with the next one", "warn"))
                farm.log_error(f"{name}, {title}")
                used = f.leaves_used if f is not None else used
                continue
            except Exception as e:
                saved = farm.log_error(name)
                put(("log", f"{name} error: {e!r}" + (f" (details saved in {saved})" if saved
                                                      else ""), "bad"))
                return f"{name} error: {e!r}"
            used = f.leaves_used
            for u, n in f.shards.items():
                got[u] = got.get(u, 0) + n
            if reason != "Finished.":
                return reason   # Stopped, or a Leaves limit
            done.append(title)
        if failed:
            return f"Finished, but gave up on {', '.join(failed)} (see the log)."
        return "Finished."


class VcrPage:
    """VCR page: replay the quest that's open until every equipped memento is at 100%."""

    def build_vcr(self, page):
        card = self.page_card(page, "VCR farm", key="vcr.title")
        self.label(card, "Replays the quest you're on until every equipped memento is at 100% "
                         "(each finished run adds 0.1%). Start it on the quest's team screen "
                         "(Go). Any stage works.", size=9, color=MUTED, wraplength=520,
                   justify="left", anchor="w", key="vcr.help").pack(anchor="w")
        self.label(card, "Each run: Go → the battle plays on auto → Quest Missions → Try Again! "
                         "→ Go again. It stops by itself once all the mementos are at 100%.",
                   size=9, color=MUTED, wraplength=520, justify="left", anchor="w",
                   key="vcr.loop").pack(anchor="w", pady=(6, 0))
        self.vcr_leaves = tk.BooleanVar(value=True)
        self.check(card, "Use leaves when AP runs out", self.vcr_leaves, self.save_settings,
                   key="vcr.leaves").pack(fill="x", pady=(10, 0))
        self.label(card, "Alchemy Drops per refill and the limits come from the Leaves page. "
                         "Off: it stops when AP runs out.", size=9, color=MUTED, wraplength=500,
                   justify="left", anchor="w", key="vcr.leaves_help").pack(anchor="w",
                                                                         padx=(24, 0))

    def vcr_go(self):
        if self.running() or self.genesis_running():
            return
        import vcr_farm
        self.genesis_mode = "vcr"
        self.save_settings()
        name = t("vcr.name", "VCR farm")
        self.genesis_stop, self.genesis_pause = threading.Event(), threading.Event()
        leaves = self.leaf_settings()
        self.genesis_name = name
        self.last_shards = {}
        use = self.vcr_leaves.get()
        self.set_state(name, t("vcr.state", "until every memento is at 100%"))
        self.log(f"--- {name} ---", "muted")
        put = self.q.put

        def job():
            try:
                reason = vcr_farm.VcrFarm(
                    use_leaves=use, log=lambda m: put(("log", m)), stop=self.genesis_stop,
                    pause=self.genesis_pause, leaves=leaves,
                    status=lambda s: put(("gstatus", s))).run()
            except Exception as e:
                saved = farm.log_error(name)
                reason = f"{name}: {e}"
                put(("log", reason + (f" (details saved in {saved})" if saved else ""), "bad"))
            put(("gdone", reason))

        self.genesis_worker = threading.Thread(target=job, daemon=True)
        self.genesis_worker.start()
        self.update_buttons()


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
        # scan: one main button (the event's open map) and the events scanned or live below
        card = self.page_card(page, "Box event: scan")
        self.dev_sel = None          # the event open in the list (its name and units shown)
        self.dev_row_btns = []       # the list's buttons (rebuilt with it)
        self.dev_btns = []
        self.dev_tab = tk.StringVar(value="Hard")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.dev_btns.append(self.button(row, "Scan the open map", BLUE, self.dev_scan_map))
        self.dev_btns[-1].pack(side="left")
        seg = tk.Frame(row, bg=PANEL)
        seg.pack(side="left", padx=(10, 0))
        self.dev_tab_btns = {}
        for tab in ("Hard", "Extra", "Normal"):
            b = self.small_button(seg, tab, lambda v=tab: self.dev_set_tab(v))
            b.pack(side="left", padx=(0, 1))
            self.dev_tab_btns[tab] = b
        self.dev_stop_btn = self.small_button(row, "Stop scan", self.dev_stop.set)
        self.dev_hint = self.label(card, "Open the event's map in the game first. Hard shows once "
                                         "its Normal stages are cleared.", size=8, color=MUTED,
                                   anchor="w")
        self.dev_hint.pack(fill="x", pady=(6, 0))
        # the last scan's result (packed under the hint once there is one)
        self.dev_last = self.label(card, "", size=9, color=GREEN, anchor="w", key=False,
                                   justify="left", wraplength=560)
        card.bind("<Configure>", lambda e: self.dev_last.config(wraplength=max(300, e.width - 40)),
                  add="+")
        self.label(card, "Scanned events", size=9, color=MUTED, anchor="w").pack(
            fill="x", pady=(12, 4))
        self.dev_list = tk.Frame(card, bg=FIELD, padx=1, pady=1)   # FIELD: a hairline around
        self.dev_list.pack(fill="x")
        self.dev_name = tk.StringVar()
        self.dev_name.trace_add("write", lambda *_: self.dev_name_changed())
        self.dev_set_tab("Hard")
        # the older list-style scans (Event Quest lists), folded away
        fold = self.label(card, "▸  Older list-style scans (Read event list, Scan whole event, "
                                "Scan the open list, Quest Details)", size=9, color=MUTED,
                          anchor="w", cursor="hand2")
        fold.pack(fill="x", pady=(12, 0))
        old = tk.Frame(card, bg=PANEL)
        fold.bind("<Button-1>", lambda _e: self.dev_toggle_old(fold, old))
        grid = tk.Frame(old, bg=PANEL)
        grid.pack(fill="x", pady=(8, 0))
        grid.columnconfigure(1, weight=1)
        self.dev_event = tk.StringVar()
        self.dev_choices = {}   # label -> event id
        self.label(grid, "Event", color=MUTED).grid(row=0, column=0, sticky="w")
        self.dev_event_menu = tk.OptionMenu(grid, self.dev_event, "")
        self.style_menu(self.dev_event_menu)
        self.dev_event_menu.grid(row=0, column=1, sticky="ew", padx=6)
        self.dev_btns.append(self.small_button(grid, "Read event list", self.dev_read_events))
        self.dev_btns[-1].grid(row=0, column=2)
        self.dev_place = tk.StringVar()
        self.label(grid, "Place (optional)", color=MUTED).grid(row=1, column=0, sticky="w",
                                                               pady=(6, 0))
        tk.Entry(grid, textvariable=self.dev_place, bg=FIELD, fg=FG, relief="flat",
                 insertbackground=FG, font=(FONT, 10)).grid(row=1, column=1, sticky="ew", padx=6,
                                                            pady=(6, 0))
        self.label(grid, "e.g. Hard, if it has several lists", size=8, color=MUTED).grid(
            row=1, column=2, sticky="w", pady=(6, 0))
        self.dev_event.trace_add("write", lambda *_: self.dev_event_changed())
        row = tk.Frame(old, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        for text, cmd in (("Scan whole event", self.dev_scan_event),
                          ("Scan the open list", self.dev_scan_open),
                          ("Add the open Quest Details", self.dev_scan_detail)):
            b = self.small_button(row, text, cmd)
            b.pack(side="left", padx=(0, 6))
            self.dev_btns.append(b)
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
        self.label(card, "Each event is published or taken off from its row under Box event: "
                         "scan.", size=8, color=MUTED, anchor="w").pack(fill="x", pady=(4, 0))
        self.label(card, "Everyone's clearing order (players can pick their own on the Box "
                         "events tab)", size=9, color=MUTED, anchor="w").pack(fill="x",
                                                                            pady=(10, 4))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self.dev_order = live_data.clear_order(self.live)
        self.dev_order_sel = None
        self.dev_order_chips = tk.Frame(row, bg=PANEL)
        self.dev_order_chips.pack(side="left")
        self.small_button(row, "◂", lambda: self.dev_order_move(-1)).pack(side="left",
                                                                                padx=(8, 1))
        self.small_button(row, "▸", lambda: self.dev_order_move(1)).pack(side="left")
        self.dev_btns.append(self.small_button(row, "Publish order", self.dev_publish_order))
        self.dev_btns[-1].pack(side="right")
        self.dev_order_live = self.label(card, "", size=8, color=MUTED, anchor="w", key=False)
        self.dev_order_live.pack(fill="x", pady=(4, 0))
        self.dev_order_draw()
        self.check(card, "Unlock locked Event Archives events with the day's free unlocks "
                         "(never items: stops at \"Owned\")", self.archive_unlock,
                   self.save_settings).pack(fill="x", pady=(10, 0))
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
        self.live_hooks = getattr(self, "live_hooks", []) + [self.dev_refresh, self.dev_order_draw]
        self.dev_refresh_choices()
        self.dev_refresh()

    def dev_order_draw(self):
        """Everyone's clearing order as chips: click one, then move it with the arrows."""
        for w in self.dev_order_chips.winfo_children():
            w.destroy()
        for i, k in enumerate(self.dev_order):
            sel = k == self.dev_order_sel
            bg, fg = ((BLUE, DARK) if sel else (ARCHIVE_BG, ARCHIVE_FG) if k == "archive"
                      else (FIELD, FG))
            chip = tk.Label(self.dev_order_chips, text=f"{i + 1}  {self.KIND_NAMES[k]}", bg=bg,
                            fg=fg, font=(FONT, 9), padx=10, pady=3, cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda _e, k=k: self.dev_order_select(k))
        live = live_data.clear_order(self.live)
        same = live == self.dev_order
        self.dev_order_live.config(
            text=f"Live: {self.order_text(live)}"
            + ("" if self.live.get("order") else " (the built-in order - none published yet)")
            + ("" if same else "  ·  yours isn't published yet"),
            fg=MUTED if same else YELLOW)

    def dev_order_select(self, kind):
        self.dev_order_sel = None if self.dev_order_sel == kind else kind
        self.dev_order_draw()

    def dev_order_move(self, step):
        k = self.dev_order_sel
        if k is None:
            return
        i = self.dev_order.index(k)
        j = min(max(i + step, 0), len(self.dev_order) - 1)
        self.dev_order[i], self.dev_order[j] = self.dev_order[j], self.dev_order[i]
        self.dev_order_draw()

    def dev_publish_order(self):
        token = self.dev_need_token()
        if not token:
            return
        order = list(self.dev_order)
        if self.live.get("order") == order:
            messagebox.showinfo("Dev", "That order is already live.", parent=self.root)
            return
        if messagebox.askyesno("Publish", f"Make {self.order_text(order)} everyone's clearing "
                                          "order?\n\nPlayers who picked their own keep theirs.",
                               parent=self.root):
            self.dev_work("Publishing", lambda: live_data.publish_order(token, order),
                          self.dev_published)

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
    LIST_NAMES = {"boss battle list": "Boss Battle Quest", "archive": "Event Archives",
                  "genesis list": "Genesis", "event list": "Event Quest"}

    def dev_eid(self):
        """The event picked in the older list-style scans' menu."""
        return self.dev_choices.get(self.dev_event.get())

    def dev_draft_event(self, create=False, eid=None):
        """(id, draft) of the event open in the list (or eid). create: start a draft - a copy
        of what's live, if it's live."""
        eid = eid or self.dev_sel
        if not eid:
            return None, None
        ev = self.dev_draft["events"].get(eid)
        if ev is None and create:
            live = self.live.get("events", {}).get(eid)
            ev = self.dev_draft["events"][eid] = (json.loads(json.dumps(live)) if live else
                                                  {"name": "", "quests": []})
        return eid, ev

    def dev_set_tab(self, tab):
        self.dev_tab.set(tab)
        for name, b in self.dev_tab_btns.items():
            b.color = BLUE if name == tab else FIELD
            b.config(bg=b.color, fg=DARK if name == tab else FG, activebackground=b.color)

    def dev_toggle_old(self, fold, frame):
        if frame.winfo_manager():
            frame.pack_forget()
            fold.config(text=fold["text"].replace("▾", "▸", 1))
        else:
            frame.pack(fill="x", after=fold)
            fold.config(text=fold["text"].replace("▸", "▾", 1))

    def dev_refresh_choices(self):
        """The older scans' event menu: events read from the game, plus drafts and live ones."""
        known = dict(live_data.dev_settings().get("events_seen") or {})
        for eid in list(self.dev_draft["events"]) + list(self.live.get("events", {})):
            known.setdefault(eid, "")
        self.dev_choices = {(f"{eid}  -  {first}" if first else eid): eid
                            for eid, first in known.items()}
        self.set_menu(self.dev_event_menu, self.dev_event, list(self.dev_choices))
        if self.dev_event.get() not in self.dev_choices and self.dev_choices:
            self.dev_event.set(next(iter(self.dev_choices)))

    def dev_event_changed(self):
        pass   # the menu only says which event the older scans add to

    def dev_select(self, eid):
        """Open (or close) an event's row: its name and units."""
        self.dev_sel = None if self.dev_sel == eid else eid
        self.dev_refresh()

    def dev_name_changed(self):
        if getattr(self, "_dev_naming", False) or not self.dev_sel:
            return
        pill = getattr(self, "dev_pills", {}).get(self.dev_sel)
        was_same = pill is not None and pill.cget("text") == "Live"
        eid, ev = self.dev_draft_event(create=True)
        ev["name"] = self.dev_name.get().strip()
        live_data.save_draft(self.dev_draft)
        if was_same != (self.dev_state(eid)[0] == "Live"):
            # Publish comes (or goes): rebuild the row, keep typing where it was
            self.dev_refresh_list()
            self.dev_name_entry.focus_set()
            self.dev_name_entry.icursor("end")
        else:
            self.dev_refresh_states()

    @staticmethod
    def dev_public(ev):
        """An event as it's published (without the scan's notes)."""
        return {**ev, "quests": [{k: v for k, v in q.items() if k not in ("error", "row", "note")}
                                 for q in ev.get("quests", [])]}

    def dev_state(self, eid):
        """(text, bg, fg) of an event's state pill: draft only, live, or live with a newer draft."""
        draft = self.dev_draft["events"].get(eid)
        live = self.live.get("events", {}).get(eid)
        if not live:
            return "Draft, not live", "#4a3b17", YELLOW
        same = lambda ev: {k: v for k, v in self.dev_public(ev).items() if k not in ("id", "added")}
        if draft and same(draft) != same(live):   # publishing adds id and date
            return "Live, draft changed", "#4a3b17", YELLOW
        return "Live", "#1d3d1d", "#7ee07e"

    def dev_events(self):
        """Every event scanned or live: drafts first, then by name."""
        live = self.live.get("events", {})
        ids = list(dict.fromkeys(list(self.dev_draft["events"]) + list(live)))
        name = lambda e: ((self.dev_draft["events"].get(e) or live.get(e) or {}).get("name")
                          or e).casefold()
        return sorted(ids, key=lambda e: (e not in self.dev_draft["events"], name(e)))

    def dev_refresh_states(self):
        """Just the state pills (while a name is typed, the list isn't rebuilt)."""
        for eid, pill in getattr(self, "dev_pills", {}).items():
            text, bg, fg = self.dev_state(eid)
            pill.config(text=text, bg=bg, fg=fg)

    def dev_refresh(self):
        if not hasattr(self, "dev_list"):
            return
        self.dev_refresh_list()
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

    def dev_refresh_list(self):
        """The scanned / live events, one row each; the open one shows its name and units."""
        for w in self.dev_list.winfo_children():
            w.destroy()
        self.dev_row_btns, self.dev_pills = [], {}
        live = self.live.get("events", {})
        events = self.dev_events()
        if self.dev_sel not in events:
            self.dev_sel = None
        if not events:
            tk.Label(self.dev_list, text=t("dev.no_events", "Nothing scanned yet: open a box "
                                                          "event's map in the game and press "
                                                          "Scan the open map."),
                     bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w", padx=10, pady=10).pack(
                fill="x")
        for i, eid in enumerate(events):
            draft = self.dev_draft["events"].get(eid)
            ev = draft or live.get(eid) or {}
            open_ = eid == self.dev_sel
            bg = TILE if open_ else PANEL
            row = tk.Frame(self.dev_list, bg=bg, padx=10, pady=8, cursor="hand2")
            row.pack(fill="x", pady=(0 if i == 0 else 1, 0))
            head = tk.Frame(row, bg=bg)
            head.pack(fill="x")
            left = tk.Frame(head, bg=bg)
            left.pack(side="left", fill="x", expand=True)
            top = tk.Frame(left, bg=bg)
            top.pack(fill="x")
            parts = [tk.Label(top, text=ev.get("name") or eid, bg=bg, fg=FG,
                              font=(FONT, 10, "bold" if open_ else "normal"))]
            parts[-1].pack(side="left")
            where = ev.get("list")
            if where:
                archive = where == "archive"
                parts.append(tk.Label(top, text=self.LIST_NAMES.get(where, where),
                                      bg=ARCHIVE_BG if archive else FIELD,
                                      fg=ARCHIVE_FG if archive else MUTED, font=(FONT, 8), padx=6))
                parts[-1].pack(side="left", padx=(8, 0))
            text, pbg, pfg = self.dev_state(eid)
            changed = draft and text != "Live"   # a draft the same as live has nothing to do
            pill = tk.Label(top, text=text, bg=pbg, fg=pfg, font=(FONT, 8), padx=6)
            pill.pack(side="left", padx=(6, 0))
            self.dev_pills[eid] = pill
            quests = ev.get("quests", [])
            units = live_data.units({"format": 1, "events": {eid: ev}})
            tabs = sorted({q.get("tab") or "" for q in quests} - {""})
            errors = sum(1 for q in quests if q.get("error"))
            info = (f"{eid}  ·  {len(quests)} {'/'.join(tabs) + ' ' if tabs else ''}"
                    f"stage{'s' if len(quests) != 1 else ''}  ·  {len(units)} "
                    f"unit{'s' if len(units) != 1 else ''}"
                    + (f"  ·  {errors} without loot" if errors else ""))
            parts.append(tk.Label(left, text=info, bg=bg, fg=MUTED, font=(FONT, 8), anchor="w"))
            parts[-1].pack(fill="x")
            for w in [row, head, left, top] + parts:
                w.bind("<Button-1>", lambda _e, e=eid: self.dev_select(e))
            btns = tk.Frame(head, bg=bg)
            btns.pack(side="right")
            if changed:
                b = self.button(btns, "Publish", GREEN, lambda e=eid: self.dev_publish(e))
                b.config(font=(FONT, 9, "bold"), padx=10, pady=3)
                b.pack(side="left")
                self.dev_row_btns.append(b)
            if eid in live:
                b = self.small_button(btns, "Take off live", lambda e=eid: self.dev_remove_event(e))
                b.pack(side="left", padx=(6, 0))
                self.dev_row_btns.append(b)
            if changed:
                b = self.small_button(btns, "Remove draft", lambda e=eid: self.dev_clear(e))
                b.pack(side="left", padx=(6, 0))
                self.dev_row_btns.append(b)
            if open_:
                self.dev_row_open(row, eid, ev)
        for b in self.dev_row_btns:
            self.enable(b, not self.dev_busy)

    def dev_set_main(self, eid, unit):
        """Mark / unmark one of the event's main units (optional, any number): players see them
        first with the other units folded away; none: every unit shows."""
        eid, ev = self.dev_draft_event(create=True, eid=eid)
        mains = live_data.main_units(ev)
        mains = [u for u in mains if u != unit] if unit in mains else mains + [unit]
        if mains:
            ev["main"] = mains
        else:
            ev.pop("main", None)
        live_data.save_draft(self.dev_draft)
        self.dev_refresh_list()

    def dev_row_open(self, row, eid, ev):
        """The open row: the name players see, a tile per unit (click: pick its picture)."""
        line = tk.Frame(row, bg=TILE)
        line.pack(fill="x", pady=(8, 0))
        tk.Label(line, text=t("dev.name_players", "Name for players"), bg=TILE, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        self._dev_naming = True
        self.dev_name.set(ev.get("name") or "")
        self._dev_naming = False
        self.dev_name_entry = tk.Entry(line, textvariable=self.dev_name, bg=FIELD, fg=FG,
                                       relief="flat", insertbackground=FG, font=(FONT, 10))
        self.dev_name_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=2)
        self.small_button(line, "Show quests", lambda: self.dev_show_quests(eid)).pack(
            side="right")
        grid = tk.Frame(row, bg=TILE)
        grid.pack(fill="x", pady=(8, 0))
        one = {"format": 1, "events": {eid: ev}}
        units, pics = live_data.units(one), live_data.portraits(one)
        mains = live_data.main_units(ev)
        units = dict(sorted(units.items(), key=lambda kv: kv[0] not in mains))   # mains first
        for i, (u, qs) in enumerate(units.items()):
            tile = tk.Frame(grid, bg=PANEL, padx=6, pady=4)
            tile.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0, 6), pady=3)
            img = self.box_image(pics.get(u))
            (tk.Label(tile, image=img, bg=PANEL) if img else
             tk.Label(tile, text="?", bg=FIELD, fg=MUTED, width=4, height=2)).pack(side="left")
            box = tk.Frame(tile, bg=PANEL)
            box.pack(side="left", padx=6)
            tk.Label(box, text=u, bg=PANEL, fg=FG, font=(FONT, 10), anchor="w").pack(fill="x")
            acts = tk.Frame(box, bg=PANEL)
            acts.pack(fill="x")
            main = u in live_data.main_units(ev)
            star = tk.Label(acts, text="★ main" if main else "☆ main", bg=PANEL,
                            fg=YELLOW if main else MUTED, font=(FONT, 8), cursor="hand2")
            star.pack(side="left")
            star.bind("<Button-1>", lambda _e, unit=u: self.dev_set_main(eid, unit))
            tk.Label(acts, text="·", bg=PANEL, fg=MUTED, font=(FONT, 8)).pack(side="left",
                                                                                  padx=3)
            pick = tk.Label(acts, text=("picture" if img else "no picture - pick one"),
                            bg=PANEL, fg=MUTED if img else ORANGE, font=(FONT, 8), anchor="w",
                            cursor="hand2")
            pick.pack(side="left")
            pick.bind("<Button-1>", lambda _e, unit=u: self.dev_pick_portrait(unit, eid))
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="dev")
        mains = live_data.main_units(ev)
        tk.Label(row, text=(f"Main units: {', '.join(mains)} - players see them first, the other "
                            "units are folded away on the Box events tab." if mains else
                            "Main units (optional): mark the units most players come for and the "
                            "others are folded away on the Box events tab. None: every unit shows."),
                 bg=TILE, fg=MUTED, font=(FONT, 8), anchor="w", justify="left",
                 wraplength=560).pack(fill="x", pady=(6, 0))

    # ---------- scanning ----------
    def dev_work(self, what, job, done=None, failed=None):
        """Run a scan / publish on a worker thread; the Dev buttons are off meanwhile."""
        if self.dev_busy or self.running() or self.genesis_running():
            self.log("Wait for the farm or the scan that's running to finish first.", "warn")
            return
        self.dev_busy = True
        self.dev_stop.clear()
        for b in self.dev_btns + self.dev_row_btns:
            self.enable(b, False)
        self.dev_stop_btn.pack(side="left", padx=(10, 0))
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
                    if failed:
                        failed(err)
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
        """The older scans: add to the event picked in their menu (now open in the list)."""
        eid, ev = self.dev_draft_event(create=True)
        ev["quests"] = live_data.merge_quests(ev["quests"], quests)
        live_data.save_draft(self.dev_draft)
        found = sorted({u for q in quests for u in live_data.quest_units(q)})
        self.log(f"Scanned {len(quests)} quests" + (f": {', '.join(found)}" if found else
                                                    " (no unit shards in their loot)"), "good")

    def dev_need_event(self):
        if not self.dev_eid():
            messagebox.showinfo("Dev", "Pick the event first (Read event list, with the game "
                                "on Quest > Event).", parent=self.root)
            return False
        self.dev_sel = self.dev_eid()   # what's scanned lands in that event's row
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

    def dev_show_last(self, text, color):
        self.dev_last.config(text=text, fg=color)
        if not self.dev_last.winfo_manager():
            self.dev_last.pack(fill="x", pady=(4, 0), after=self.dev_hint)

    def dev_scan_map(self):
        """A Genesis-style event (box events): with its map (or page) open in the game, read
        every stage of the tab picked beside the button, then go Back to learn which list it's
        opened from. The event is named by its own id - no need to pick it first."""
        import genesis_farm
        import map_scan
        tab = self.dev_tab.get() or "Hard"
        log = lambda s: self.q.put(("log", f"  {s}"))

        def job():
            f = genesis_farm.GenesisFarm(log=log, stop=self.dev_stop)
            ms = map_scan.MapScanner(f, log=log)
            event, quests = ms.scan(tab, log)
            if not event:
                raise RuntimeError("couldn't read the event's id from its map")
            origin = ms.learn_origin(event, f.navigator, map_scan.event_names(ms.map_name, quests))
            origin["banner"] = ms.map_name
            return event, quests, origin

        def done(result):
            event, quests, origin = result
            ev = self.dev_draft["events"].get(event)
            if ev is None:   # a live event scanned again starts from what's live
                _eid, ev = self.dev_draft_event(create=True, eid=event)
            ev.update({"kind": "map", "chapter": event, "list": origin["list"]})
            ev["name"] = ev.get("name") or origin.get("banner") or origin.get("name") or event
            known = {map_scan.norm_name(n) for n in map_scan.event_names(ev["name"], quests)}
            if origin.get("list") == "archive" and origin.get("name") and \
                    map_scan.norm_name(origin["name"]) not in known:
                ev["archive_name"] = origin["name"]   # the archive's name for it: the farm looks for it
            ev["quests"] = live_data.merge_quests(ev["quests"], quests)
            live_data.save_draft(self.dev_draft)
            self.dev_sel = event
            self.dev_refresh_choices()
            found = sorted({u for q in quests for u in live_data.quest_units(q)})
            self.log(f"Scanned {len(quests)} {tab} stages of {ev['name']}"
                     + (f": {', '.join(found)}" if found else " (no unit shards in their loot)"),
                     "good")
            where = self.LIST_NAMES.get(origin.get("list"), origin.get("list"))
            if not origin.get("list") or not origin.get("found"):
                self.log("Couldn't tell which list this event is opened from - the farm won't "
                         "find its way there. Open it from Quest > Event > Boss Battle Quest, the "
                         "Event Archives' Boss Battle Quest tab or the Genesis list, and scan "
                         "again.", "warn")
                self.dev_show_last(f"{ev['name']}: {len(quests)} {tab} stages, {len(found)} "
                                   "units - but not where it's opened from (scan it again from "
                                   "its list)", YELLOW)
            else:
                self.log(f"  It's opened from {where}: the farm goes there by itself.", "muted")
                self.dev_show_last(f"✔  {ev['name']}: {len(quests)} {tab} stages, "
                                   f"{len(found)} units, opened from {where}", GREEN)

        def failed(err):
            self.dev_show_last(f"✖  {err}", RED)
        self.dev_work(f"Scanning the open map ({tab})", job, done, failed)

    def dev_clear(self, eid):
        ev = self.dev_draft["events"].get(eid)
        live = eid in self.live.get("events", {})
        if ev and messagebox.askyesno(
                "Dev", f"Forget what was scanned for {ev.get('name') or eid}?"
                + ("\n\nWhat's live stays." if live else ""), parent=self.root):
            self.dev_draft["events"].pop(eid, None)
            live_data.save_draft(self.dev_draft)
            self.dev_refresh()

    def dev_show_quests(self, eid=None):
        eid, ev = self.dev_draft_event(eid=eid)
        ev = ev or self.live.get("events", {}).get(eid or "")
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

    def dev_pick_portrait(self, unit, eid=None):
        """A searchable grid of every portrait; the pick goes into the event's draft."""
        eid, ev = self.dev_draft_event(create=True, eid=eid)
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

    def dev_publish(self, eid):
        eid, ev = self.dev_draft_event(eid=eid)
        token = self.dev_need_token()
        if not token:
            return
        if not ev or not ev.get("quests"):
            messagebox.showinfo("Dev", "Scan the event first.", parent=self.root)
            return
        name = ev.get("name") or eid
        units = live_data.units({"format": 1, "events": {eid: ev}})
        no_loot = [q["title"] for q in ev["quests"] if not q.get("loot")]
        where = self.LIST_NAMES.get(ev.get("list"), ev.get("list") or "?")
        if not messagebox.askyesno(
                "Publish", f"Publish '{name}' to everyone?\n\n{len(ev['quests'])} quests, "
                f"{len(units)} units: {', '.join(units) or 'none'}\nOpened from: {where}"
                + (f"\n\nNo loot was read for: {', '.join(no_loot)}" if no_loot else "")
                + "\n\nIt replaces what's live for this event.", parent=self.root):
            return
        event = self.dev_public({**ev, "name": name})

        def done(result):
            self.dev_draft["events"].pop(eid, None)   # it's live now: the row shows that
            live_data.save_draft(self.dev_draft)
            self.dev_published(result)
        self.dev_work("Publishing", lambda: live_data.publish_events(token, {eid: event}), done)

    def dev_remove_event(self, eid):
        token = self.dev_need_token()
        ev = self.live.get("events", {}).get(eid)
        if not token or not ev:
            return
        if messagebox.askyesno("Take off live", f"Take {ev.get('name') or eid} ({eid}) off for "
                                                "everyone?" + ("\n\nYour draft of it stays."
                                                              if eid in self.dev_draft["events"]
                                                              else ""), parent=self.root):
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
