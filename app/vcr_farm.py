"""VCR farm: replay the quest you're on until every equipped memento reaches 100%.

Each finished run adds a little (0.1%) to every equipped memento's progress (the result screen's
錬金境界値 row); at 100% the memento's VCR is earned. The loop, from the quest's team screen:
Go -> the battle plays on auto -> Quest Missions (tap empty space) -> EXP count-up (tap) ->
result screen (read the mementos' %) -> Try Again! -> team screen -> Go ...
Out of AP: the Replenish AP window - refilled with Alchemy Drops when leaves are on (Leaves page
limits), otherwise the farm stops. Works on any stage: nothing here is tied to one quest.
"""
import re
import time

import genesis_farm
from genesis_farm import GenesisFarm, LeafLimit, Stop

GO_END = "/w/go"                      # team screen: PartyEditor2(Clone)/.../main/w/go
RETRY_END = "/buttons/btn_retry"      # result screen: Try Again!
MISSIONS_END = "/CloseMissionDetail"  # Quest Missions panel after the battle
EXPSKIP_END = "/expskip"              # the EXP count-up
SHOP = "UnlockGuerrillaShopPopup"     # "Peddler Shop: Bazaar Found!" - View Later
SHOP_LATER_END = "/btn_cancel"
EMPTY = (0.5, 0.95)                   # empty space under the missions panel / between buttons
# the mementos' "0.1%" labels on the result screen, one per unit (seen at 2405x1353)
MEMENTO_Y = (0.525, 0.51, 0.54)
MEMENTO_X = (0.220, 0.332, 0.444, 0.557, 0.669, 0.781)
PERCENT = re.compile(r"^(\d{1,4}(?:\.\d+)?)\s*%?$")
STUCK = 180          # s on one screen (not the battle) before the farm gives up
BATTLE_MAX = 30 * 60  # s a single battle may take


class VcrFarm(GenesisFarm):
    def __init__(self, use_leaves=True, **kw):
        super().__init__(mode="hard", **kw)
        self.counter = None
        self.use_leaves = use_leaves
        self.runs = 0

    # ---------- what's on screen ----------
    def state(self):
        """(name, top elements): apwindow, shop, missions, expskip, result, team, battle, other."""
        els = [e for e in self.elements() if e["top"]]
        on = [e for e in els if e["on"]]
        paths = " ".join(e["path"] for e in els)
        ends = lambda end: next((e for e in on if e["path"].endswith(end)), None)
        if "HealAPItemList" in paths or "UseApHealItem" in paths or "HealApResult" in paths:
            return "apwindow", els
        if SHOP in paths:
            return "shop", els
        if ends(MISSIONS_END):
            return "missions", els
        if ends(EXPSKIP_END):
            return "expskip", els
        if ends(RETRY_END):
            return "result", els
        if "PartyEditor2" in paths and ends(GO_END):
            return "team", els
        if any("BattleUI" in e["path"] for e in self.elements()):
            return "battle", els
        return "other", els

    def mementos(self):
        """The equipped mementos' progress in % (left to right) from the result screen, or []
        when it can't be read (yet)."""
        out = []
        for x in MEMENTO_X:
            for y in MEMENTO_Y:
                nums = [float(m.group(1)) for t in self.texts(self.inspect((x, y)))
                        if (m := PERCENT.match(t.replace(",", "")))]
                if nums:
                    out.append(nums[0])
                    break
        return out

    def read_mementos(self):
        """Two reads that agree (the labels count up for a moment), or the last read."""
        last = None
        for _ in range(4):
            now = self.mementos()
            if now and now == last:
                return now
            last = now
            self.sleep(0.8)
        return last or []

    # ---------- the loop ----------
    def press_end(self, els, end, what):
        btn = next((e for e in els if e["on"] and e["path"].endswith(end)), None)
        self.press(btn, what)

    def refill(self):
        if not self.use_leaves:
            self.close_ap_window()
            raise LeafLimit("Out of AP - stopping (Use leaves is off)")
        self.log("  Out of AP - refilling")
        self.replenish_ap()
        self.log(f"  AP refilled ({self.leaf_summary()})")

    def run(self):
        try:
            state, _ = self.state()
            if state not in ("team", "result", "battle", "missions", "expskip", "shop",
                             "apwindow"):
                raise RuntimeError("open the quest's team screen (Go) in the game first")
            self.log(f"VCR farm: until every equipped memento is at 100%"
                     + ("" if self.use_leaves else " (no leaves: stops when AP runs out)"))
            return self.loop()
        except Stop:
            self.log(f"VCR farm stopped after {self.runs} run{'s' * (self.runs != 1)}.")
            return "Stopped."
        except LeafLimit as e:
            self.log(f"{e}.")
            return str(e)

    def loop(self):
        last, since, nudged, read_at = None, time.time(), False, None
        while True:
            state, els = self.state()
            if state != last:
                last, since, nudged = state, time.time(), False
            stuck_for = time.time() - since
            if state == "battle":
                if stuck_for > BATTLE_MAX:
                    raise RuntimeError("the battle has been going for 30 minutes - is auto on?")
                self.sleep(2.0)
                continue
            if stuck_for > STUCK:
                raise RuntimeError(f"stuck on the same screen ({state}) for {STUCK // 60} minutes")
            if state == "team":
                if self.wait_if_paused():
                    continue
                self.status(f"Run {self.runs + 1}")
                self.press_end(els, GO_END, "Go")
                self.wait_for(lambda: self.state()[0] != "team", 10)
            elif state == "apwindow":
                self.refill()
                self.sleep(1.0)
            elif state in ("missions", "expskip"):
                self.tap(EMPTY)
                self.sleep(1.0)
            elif state == "shop":
                self.press_end(els, SHOP_LATER_END, "View Later")
                self.sleep(1.0)
            elif state == "result":
                if read_at != since:   # a new result screen: one run done
                    read_at = since
                    self.runs += 1
                    done = self.check_mementos()
                    if done:
                        return done
                if self.wait_if_paused():
                    continue
                self.press_end(els, RETRY_END, "Try Again!")
                self.wait_for(lambda: self.state()[0] != "result", 10)
            else:   # a screen in between: give it a moment, then tap empty space once
                if stuck_for > 20 and not nudged:
                    nudged = True
                    self.tap(EMPTY)
                self.sleep(1.0)

    def check_mementos(self):
        """After a run: log the mementos' progress; the reason to stop once all are at 100%."""
        got = self.read_mementos()
        if not got:
            self.log(f"  Run {self.runs} done (couldn't read the mementos' progress)")
            return None
        txt = " · ".join(f"{p:g}%" for p in got)
        self.log(f"  Run {self.runs} done - mementos {txt}")
        self.status(f"Run {self.runs} done - lowest memento {min(got):g}%")
        if all(p >= 100 for p in got):
            self.log(f"All {len(got)} mementos are at 100% or more - VCR farm finished "
                     f"after {self.runs} run{'s' * (self.runs != 1)}.")
            return f"All {len(got)} mementos at 100%."
        return None


__all__ = ["VcrFarm", "LeafLimit", "Stop", "genesis_farm"]
