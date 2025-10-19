# -*- coding: utf-8 -*-
# ToweringBot — Towering Ruin (fullscreen, robust confirm + spam)
#
# Flow (TL;DR):
# 1) WAIT_F -> detect [F] -> press F
# 2) WAIT_HARD -> click Hard (once)
# 3) WAIT_MATCH -> click Match (once)
# 4) BECOME_CAPTAIN -> if Decline not within 3s: ESC -> I -> party-leave (icon first, then confirm)
# 5) CHECK_MATCHING_UNTIL_CONFIRM -> latch "Matching..." once; every 3s re-check "Matching..."; if missing: click Match again (then BECOME_CAPTAIN); always hunt CONFIRM
# 6) CONFIRM_MONITOR -> after first CONFIRM: 15s window; if confirm vanishes -> LINKCLICK_SPAM
# 7) LINKCLICK_SPAM -> pywinauto left-click spam; cheap confirm recheck; HUD-armed 16min failsafe: press P + Confirm
# 8) WAIT_VICTORY_LEAVE -> click Leave
# 9) POST_LEAVE_CHECK -> short window after leave: first try CONFIRM, else look for F Towering
# 10) Reset / Loop
#
# Hotkeys: F8 start • F9 pause • F10 exit

from __future__ import annotations
import time
import random
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, Dict

import os  # <-- env override support (optional, used by BlueBot GUI)
import numpy as np
import cv2 as cv
import mss
import pyautogui
from pynput import keyboard
# only used for left-click spam (works well with some games)
from pywinauto import mouse

try:
    import win32gui  # optional (window rect)
except Exception:
    win32gui = None

# ---------------------------- CONFIG ---------------------------- #
GAME_WINDOW_TITLE = None   # None => capture full monitor (no window binding)
MONITOR_INDEX = 2          # 1=primary, 2=secondary
DEBUG = True

# Optional: allow BlueBot GUI to override these via environment vars
GAME_WINDOW_TITLE = os.getenv("GAME_WINDOW_TITLE", GAME_WINDOW_TITLE)
try:
    MONITOR_INDEX = int(os.getenv("MONITOR_INDEX", str(MONITOR_INDEX)))
except ValueError:
    pass

# Left-click spam (pywinauto)
CPS_MIN = 12               # min clicks/sec
CPS_MAX = 20               # max clicks/sec

# "Matching..." can live in two UI areas — old/new
MATCHING_REGIONS = [
    (0.50, 0.62, 0.40, 0.08),  # legacy: between Single/Dual and Match
    (0.56, 0.86, 0.36, 0.10),  # newer: lower-right cluster
]

# Timing knobs
CAPTAIN_DECLINE_GRACE = 3.0
CONFIRM_MONITOR_DURATION = 15.0
CONFIRM_GONE_MARGIN = 1.0
POST_LEAVE_WINDOW = 8.0

# HUD-armed dungeon failsafe (P + Confirm -> post-leave)
SPAM_FAILSAFE_SECS = 16 * 60
FAILSAFE_RETRY_SECS = 2.0

# Retry "Match" if Matching disappears
MATCH_RETRY_COOLDOWN = 3.0  # seconds

# Template thresholds (tuned)
THRESH = {
    # World/Lobby
    "F_TOWERING":         0.55,
    "BTN_TOWERING_HARD":  0.85,
    "BTN_MATCH":          0.88,
    "BTN_DECLINE_CPT":    0.80,
    "LBL_MATCHING":       0.37,
    "BTN_CONFIRM_MATCH":  0.88,

    # Dungeon / flow
    "LBL_VICTORY":        0.90,
    "BTN_LEAVE_DUNGEON":  0.85,
    "HUD_DUNGEON":        0.80,

    # Party-Leave
    "BTN_LEAVE_ICON":     0.90,
    "BTN_CONFIRM_PARTY":  0.90,
}

# File map for templates
TEMPLATES = {
    # World/Lobby — Towering Ruin
    "F_TOWERING":         "assets/f_towering.png",
    "BTN_TOWERING_HARD":  "assets/btn_towering_hard.png",
    "BTN_MATCH":          "assets/btn_match.png",
    "BTN_DECLINE_CPT":    "assets/btn_decline_cpt.png",
    "LBL_MATCHING":       "assets/lbl_matching.png",
    "BTN_CONFIRM_MATCH":  "assets/btn_confirm_match.png",

    # Dungeon / victory
    "LBL_VICTORY":        "assets/lbl_victory.png",
    "BTN_LEAVE_DUNGEON":  "assets/btn_leave_dungeon.png",
    "HUD_DUNGEON":        "assets/hud_dungeon.png",

    # Party-Leave
    "BTN_LEAVE_ICON":     "assets/btn_leave_icon.png",
    "BTN_CONFIRM_PARTY":  "assets/btn_confirm_party.png",
}

CLICK_DELAY = 0.06
RANDOM_MOVE_JITTER_PX = 3

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

# ------------------------- UTILITIES ---------------------------- #


@dataclass
class Match:
    name: str
    top_left: Tuple[int, int]
    bottom_right: Tuple[int, int]
    score: float

    @property
    def center(self) -> Tuple[int, int]:
        x1, y1 = self.top_left
        x2, y2 = self.bottom_right
        return (x1 + (x2 - x1)//2, y1 + (y2 - y1)//2)


def _win_rect_for_title(sub: str) -> Optional[Tuple[int, int, int, int]]:
    # best-effort window binding by title substring (case-insensitive)
    if not win32gui:
        return None
    sub = sub.lower()
    out = None

    def enum(hwnd, _):
        nonlocal out
        if out is not None:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        t = win32gui.GetWindowText(hwnd)
        if sub in t.lower():
            out = win32gui.GetWindowRect(hwnd)

    win32gui.EnumWindows(enum, None)
    return out


def _monitor_bbox(sct: mss.mss, rect: Optional[Tuple[int, int, int, int]]):
    # turn monitor index or window rect into an mss bbox
    if rect is None:
        m = sct.monitors[MONITOR_INDEX]
        return dict(left=m["left"], top=m["top"], width=m["width"], height=m["height"])
    L, T, R, B = rect
    return dict(left=L, top=T, width=R-L, height=B-T)

# --------------------------- VISION ------------------------------ #


class Vision:
    def __init__(self, templates: Dict[str, str]):
        # load templates in grayscale, keep dims for quick guards
        self.tmps = {}
        for k, p in templates.items():
            img = cv.imread(p, cv.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(f"Template not found: {p}")
            self.tmps[k] = (img, img.shape[::-1])

    def find_best(self, frame_bgr, key, thr: float):
        # single best match via TM_CCOEFF_NORMED, guard too-small regions
        gray = cv.cvtColor(frame_bgr, cv.COLOR_BGR2GRAY)
        tmpl, (w, h) = self.tmps[key]
        H, W = gray.shape[:2]
        if H < tmpl.shape[0] or W < tmpl.shape[1]:
            if DEBUG:
                print(
                    f"[Skip] {key}: {W}xH {W}x{H} < tmpl {tmpl.shape[1]}x{tmpl.shape[0]}")
            return None
        res = cv.matchTemplate(gray, tmpl, cv.TM_CCOEFF_NORMED)
        _, maxV, _, maxL = cv.minMaxLoc(res)
        if DEBUG:
            print(f"[Score] {key}: {maxV:.3f}")
        if maxV >= thr:
            x, y = maxL
            return Match(key, (x, y), (x+w, y+h), maxV)
        return None

# ----------------------------- BOT ------------------------------- #


class Bot:
    def __init__(self):
        self.running = False
        self.exit_flag = False
        self.vision = Vision(TEMPLATES)
        self.window_rect = _win_rect_for_title(
            GAME_WINDOW_TITLE) if GAME_WINDOW_TITLE else None

        self.state = "WAIT_F"
        self.hard_clicked = False
        self.match_clicked = False

        self.matching_seen = False
        self.confirm_monitor_start = 0.0
        self.last_confirm_seen = 0.0

        self.captain_wait_start = 0.0
        self.match_check_start = 0.0

        # post-leave bookkeeping
        self.post_leave_start = 0.0
        self.after_leave_cycle = False

        # HUD-armed failsafe bookkeeping
        self.dungeon_timer_start = 0.0
        self.hud_timer_armed = False
        self.failsafe_last_try_ts = 0.0

        # leave-party timing
        self.leave_enter_ts = 0.0  # when we entered LEAVE_PARTY, after esc+i

        # retry "Match" bookkeeping
        self.last_match_retry_ts = 0.0

        # one-time probe after 5s without F_TOWERING in LEAVE_PARTY
        self.leave_probe_start_ts = 0.0
        self.leave_probe_done = False

    # ---- input helpers ----
    def _press_f(self):
        pyautogui.keyDown('f')
        time.sleep(CLICK_DELAY)
        pyautogui.keyUp('f')

    def _press_h_once(self):
        pyautogui.keyDown('h')
        time.sleep(2)
        pyautogui.keyUp('h')

    def _click_at(self, pt):
        x = pt[0] + random.randint(-RANDOM_MOVE_JITTER_PX,
                                   RANDOM_MOVE_JITTER_PX)
        y = pt[1] + random.randint(-RANDOM_MOVE_JITTER_PX,
                                   RANDOM_MOVE_JITTER_PX)
        pyautogui.moveTo(x, y, duration=random.uniform(0.02, 0.06))
        pyautogui.click()

    # ---- capture & detect ----
    def _grab(self, sct: mss.mss, box=None):
        if box is None:
            box = _monitor_bbox(sct, self.window_rect)
        return np.array(sct.grab(box))[:, :, :3].copy()

    def _scan_full(self, sct: mss.mss, key: str, thr: float):
        box = _monitor_bbox(sct, self.window_rect)
        frame = self._grab(sct, box)
        m = self.vision.find_best(frame, key, thr)
        if m is None:
            return None
        return Match(
            m.name,
            (m.top_left[0] + box['left'],  m.top_left[1] + box['top']),
            (m.bottom_right[0] + box['left'], m.bottom_right[1] + box['top']),
            m.score
        )

    def _scan_region(self, sct: mss.mss, key: str, region_percent, thr: float):
        full = _monitor_bbox(sct, self.window_rect)
        L, T, W, H = full["left"], full["top"], full["width"], full["height"]
        rx, ry, rw, rh = region_percent
        box = dict(left=int(L + rx*W), top=int(T + ry*H),
                   width=int(rw*W), height=int(rh*H))
        frame = self._grab(sct, box)
        m = self.vision.find_best(frame, key, thr)
        if m is None:
            return None
        return Match(
            m.name,
            (m.top_left[0] + box['left'],  m.top_left[1] + box['top']),
            (m.bottom_right[0] + box['left'], m.bottom_right[1] + box['top']),
            m.score
        )

    def _maybe_arm_hud_timer(self, sct):
        if not self.hud_timer_armed:
            hud = self._scan_full(sct, "HUD_DUNGEON", THRESH["HUD_DUNGEON"])
            if hud:
                self.dungeon_timer_start = time.time()
                self.hud_timer_armed = True
                print("[Bot] HUD detected -> arm 16min timer + press H once")
                self._press_h_once()

    def _full_reset(self):
        self.hard_clicked = False
        self.match_clicked = False
        self.matching_seen = False
        self.confirm_monitor_start = 0.0
        self.last_confirm_seen = 0.0
        self.captain_wait_start = 0.0
        self.match_check_start = 0.0
        self.after_leave_cycle = False
        self.dungeon_timer_start = 0.0
        self.hud_timer_armed = False
        self.failsafe_last_try_ts = 0.0
        self.leave_enter_ts = 0.0
        self.last_match_retry_ts = 0.0
        # reset one-time probe
        self.leave_probe_start_ts = 0.0
        self.leave_probe_done = False
        self.state = "WAIT_F"

    # --- One-time asset probe (debug) ---
    def _probe_any_asset(self, sct) -> bool:
        # Order: scan quick/global items first
        probe_order = [
            "F_TOWERING", "BTN_TOWERING_HARD", "BTN_MATCH",
            "LBL_MATCHING", "BTN_CONFIRM_MATCH",
            "HUD_DUNGEON", "BTN_LEAVE_DUNGEON",
            "BTN_LEAVE_ICON", "BTN_CONFIRM_PARTY",
        ]
        for k in probe_order:
            m = self._scan_full(sct, k, THRESH.get(k, 0.8))
            if m:
                print(f"[Probe] Found asset: {k} (score={m.score:.3f})")
                return True
        print("[Probe] No asset detected.")
        return False

    # --------------------- main loop ---------------------- #
    def loop(self):
        with mss.mss() as sct:
            full = _monitor_bbox(sct, self.window_rect)
            print(
                f"[Bot] Started. State=WAIT_F | monitor={MONITOR_INDEX} box={full}")
            while not self.exit_flag:
                if not self.running:
                    time.sleep(0.05)
                    continue

                # >>> F-GUARD (collision-free)
                # Active ONLY when not in LEAVE_PARTY and HUD isn't visible.
                in_dungeon = self._scan_full(
                    sct, "HUD_DUNGEON", THRESH["HUD_DUNGEON"])
                if (self.state != "LEAVE_PARTY") and (not in_dungeon):
                    fg = self._scan_full(
                        sct, "F_TOWERING", THRESH["F_TOWERING"])
                    if fg and self.state != "WAIT_F":
                        print(
                            "[Bot] F-Guard: F_TOWERING visible -> reset to WAIT_F")
                        self._full_reset()
                        time.sleep(0.15)
                        continue

                # 1) Wait for [F] prompt
                if self.state == "WAIT_F":
                    f = self._scan_full(sct, "F_TOWERING",
                                        THRESH["F_TOWERING"])
                    if f:
                        print("[Bot] F_TOWERING prompt -> press F")
                        self._press_f()
                        time.sleep(1)
                        self.state = "WAIT_HARD"
                        continue

                # 2) Hard (one shot)
                elif self.state == "WAIT_HARD":
                    if not self.hard_clicked:
                        h = self._scan_full(
                            sct, "BTN_TOWERING_HARD", THRESH["BTN_TOWERING_HARD"])
                        if h:
                            print("[Bot] HARD (Towering) -> click once")
                            self._click_at(h.center)
                            self.hard_clicked = True
                            time.sleep(1)
                    self.state = "WAIT_MATCH"
                    continue

                # 3) Match (one shot)
                elif self.state == "WAIT_MATCH":
                    if not self.match_clicked:
                        m = self._scan_full(
                            sct, "BTN_MATCH", THRESH["BTN_MATCH"])
                        if m:
                            print("[Bot] MATCH -> click once")
                            self._click_at(m.center)
                            self.match_clicked = True
                            time.sleep(1)
                            self.captain_wait_start = time.time()
                            self.state = "BECOME_CAPTAIN"
                            continue
                    time.sleep(0.05)
                    continue

                # 4) Captain dialog
                elif self.state == "BECOME_CAPTAIN":
                    d = self._scan_full(
                        sct, "BTN_DECLINE_CPT", THRESH["BTN_DECLINE_CPT"])
                    if d:
                        print("[Bot] Captain prompt: Decline -> click")
                        self._click_at(d.center)
                        time.sleep(0.6)
                        self.match_check_start = time.time()
                        self.state = "CHECK_MATCHING_UNTIL_CONFIRM"
                        continue

                    if (time.time() - self.captain_wait_start) >= CAPTAIN_DECLINE_GRACE:
                        print(
                            "[Bot] Decline not found -> ESC, then I -> LEAVE_PARTY")
                        pyautogui.press('esc')
                        time.sleep(0.2)
                        pyautogui.press('i')
                        self.leave_enter_ts = time.time()
                        self.state = "LEAVE_PARTY"
                        continue

                    time.sleep(0.1)
                    continue

                # 5) Matching/Confirm loop
                elif self.state == "CHECK_MATCHING_UNTIL_CONFIRM":
                    now = time.time()

                    if not self.matching_seen:
                        found = False
                        for rp in MATCHING_REGIONS:
                            mlabel = self._scan_region(
                                sct, "LBL_MATCHING", rp, THRESH["LBL_MATCHING"])
                            if mlabel:
                                found = True
                                break
                        if found:
                            print("[Bot] Matching... seen (latched)")
                            self.matching_seen = True

                    if (now - self.last_match_retry_ts) >= MATCH_RETRY_COOLDOWN:
                        still_matching = False
                        for rp in MATCHING_REGIONS:
                            mlabel = self._scan_region(
                                sct, "LBL_MATCHING", rp, THRESH["LBL_MATCHING"])
                            if mlabel:
                                still_matching = True
                                break
                        if not still_matching:
                            print(
                                "[Bot] Matching not visible -> click MATCH again")
                            mbtn = self._scan_full(
                                sct, "BTN_MATCH", THRESH["BTN_MATCH"])
                            if mbtn:
                                self._click_at(mbtn.center)
                                time.sleep(0.6)
                                self.captain_wait_start = time.time()
                                self.last_match_retry_ts = now
                                self.state = "BECOME_CAPTAIN"
                                continue
                            else:
                                self.last_match_retry_ts = now

                    cfm = self._scan_full(
                        sct, "BTN_CONFIRM_MATCH", THRESH["BTN_CONFIRM_MATCH"])
                    if cfm:
                        print("[Bot] Match popup -> initial CONFIRM")
                        self._click_at(cfm.center)
                        time.sleep(0.8)
                        self.confirm_monitor_start = time.time()
                        self.last_confirm_seen = time.time()
                        self.state = "CONFIRM_MONITOR"
                        continue

                    if (not self.matching_seen) and ((now - self.match_check_start) > 5.0):
                        print(
                            "[Bot] No Matching/Confirm -> ESC, then I -> LEAVE_PARTY")
                        pyautogui.press('esc')
                        time.sleep(0.2)
                        pyautogui.press('i')
                        self.leave_enter_ts = time.time()
                        self.state = "LEAVE_PARTY"
                        continue

                    time.sleep(0.1)
                    continue

                # 6) Confirm monitor
                elif self.state == "CONFIRM_MONITOR":
                    self._maybe_arm_hud_timer(sct)

                    now = time.time()
                    cfm = self._scan_full(
                        sct, "BTN_CONFIRM_MATCH", THRESH["BTN_CONFIRM_MATCH"])
                    if cfm:
                        self.last_confirm_seen = now
                        print("[Bot] CONFIRM_MONITOR: CONFIRM seen -> click")
                        self._click_at(cfm.center)
                        time.sleep(0.3)

                    vic = self._scan_full(
                        sct, "LBL_VICTORY", THRESH["LBL_VICTORY"])
                    if vic:
                        print(
                            "[Bot] Victory during confirm-monitor -> WAIT_VICTORY_LEAVE")
                        self.state = "WAIT_VICTORY_LEAVE"
                        continue

                    if (now - self.confirm_monitor_start) >= CONFIRM_MONITOR_DURATION:
                        if (now - self.last_confirm_seen) > CONFIRM_GONE_MARGIN:
                            print(
                                "[Bot] Confirm disappeared -> start LINKCLICK_SPAM")
                            self.state = "LINKCLICK_SPAM"
                            continue
                        else:
                            self.confirm_monitor_start = now
                    time.sleep(0.12)
                    continue

                # 7) Spam
                elif self.state == "LINKCLICK_SPAM":
                    now = time.time()
                    self._maybe_arm_hud_timer(sct)

                    if self.hud_timer_armed and self.dungeon_timer_start > 0:
                        if (now - self.dungeon_timer_start) >= SPAM_FAILSAFE_SECS:
                            if (now - self.failsafe_last_try_ts) >= FAILSAFE_RETRY_SECS:
                                print(
                                    "[Bot] HUD failsafe reached -> press P and try Confirm")
                                pyautogui.press('p')
                                time.sleep(0.3)
                                cf = self._scan_full(
                                    sct, "BTN_CONFIRM_PARTY", THRESH["BTN_CONFIRM_PARTY"])
                                if cf:
                                    print(
                                        "[Bot] Failsafe confirm -> click, go POST_LEAVE_CHECK")
                                    self._click_at(cf.center)
                                    time.sleep(0.6)
                                    self.post_leave_start = time.time()
                                    self.after_leave_cycle = True
                                    self._full_reset()
                                    self.post_leave_start = time.time()
                                    self.state = "POST_LEAVE_CHECK"
                                    continue
                                self.failsafe_last_try_ts = now

                    cfm = self._scan_full(
                        sct, "BTN_CONFIRM_MATCH", THRESH["BTN_CONFIRM_MATCH"])
                    if cfm:
                        print(
                            "[Bot] LINKCLICK_SPAM: Confirm reappeared -> click & back to CONFIRM_MONITOR")
                        self._click_at(cfm.center)
                        time.sleep(0.3)
                        self.confirm_monitor_start = time.time()
                        self.last_confirm_seen = time.time()
                        self.matching_seen = True
                        self.state = "CONFIRM_MONITOR"
                        continue

                    vic = self._scan_full(
                        sct, "LBL_VICTORY", THRESH["LBL_VICTORY"])
                    if vic:
                        print("[Bot] Victory detected during spam")
                        self.state = "WAIT_VICTORY_LEAVE"
                        continue

                    cps = random.uniform(CPS_MIN, CPS_MAX)
                    mouse.click(button='left')
                    time.sleep(1.0 / cps)
                    continue

                # 8) Victory -> Leave
                elif self.state == "WAIT_VICTORY_LEAVE":
                    lv = self._scan_full(
                        sct, "BTN_LEAVE_DUNGEON", THRESH["BTN_LEAVE_DUNGEON"])
                    if lv:
                        print("[Bot] Leave Dungeon -> click")
                        self._click_at(lv.center)
                        time.sleep(1.0)
                        self.post_leave_start = time.time()
                        self.after_leave_cycle = True
                        self.state = "POST_LEAVE_CHECK"
                        continue
                    time.sleep(0.2)
                    continue

                # 9) Post-leave sanity
                elif self.state == "POST_LEAVE_CHECK":
                    now = time.time()
                    cfm = self._scan_full(
                        sct, "BTN_CONFIRM_MATCH", THRESH["BTN_CONFIRM_MATCH"])
                    if cfm:
                        print(
                            "[Bot] Post-Leave: CONFIRM found -> click & CONFIRM_MONITOR")
                        self._click_at(cfm.center)
                        time.sleep(0.6)
                        self.confirm_monitor_start = time.time()
                        self.last_confirm_seen = time.time()
                        self.matching_seen = True
                        self.state = "CONFIRM_MONITOR"
                        continue

                    f = self._scan_full(sct, "F_TOWERING",
                                        THRESH["F_TOWERING"])
                    if f:
                        print(
                            "[Bot] Post-Leave: F_TOWERING detected -> back to WAIT_F")
                        self._full_reset()
                        continue

                    if (now - self.post_leave_start) > POST_LEAVE_WINDOW:
                        print("[Bot] Post-Leave window elapsed -> reset to WAIT_F")
                        self._full_reset()
                        continue

                    time.sleep(0.12)
                    continue

                # 10) Leave-Party flow
                elif self.state == "LEAVE_PARTY":
                    # small render grace after ESC+I
                    if self.leave_enter_ts and (time.time() - self.leave_enter_ts) < 0.6:
                        time.sleep(0.1)
                        continue

                    now = time.time()

                    # 1) Primary goal: find leave icon and confirm
                    lp = self._scan_full(
                        sct, "BTN_LEAVE_ICON", THRESH["BTN_LEAVE_ICON"])
                    if lp:
                        print("[Bot] Leave-Icon -> click")
                        self._click_at(lp.center)
                        time.sleep(0.6)

                        cf = self._scan_full(
                            sct, "BTN_CONFIRM_PARTY", THRESH["BTN_CONFIRM_PARTY"])
                        if cf:
                            print("[Bot] Confirm (party) -> click")
                            self._click_at(cf.center)
                            time.sleep(0.8)

                        # close panel and reset loop
                        pyautogui.press('esc')
                        time.sleep(0.4)
                        self._full_reset()
                        continue

                    # 2) After 5s without leave icon: ESC -> check F_TOWERING
                    if (now - self.leave_enter_ts) >= 5.0:
                        print(
                            "[Bot] Leave-Icon not found for 5s -> press ESC and check F_TOWERING")
                        pyautogui.press('esc')
                        time.sleep(0.2)

                        f = self._scan_full(
                            sct, "F_TOWERING", THRESH["F_TOWERING"])
                        if f:
                            print(
                                "[Bot] F_TOWERING detected after ESC -> reset to WAIT_F")
                            self._full_reset()
                            continue

                        # one-time asset probe after 5s without F
                        if self.leave_probe_start_ts == 0.0:
                            self.leave_probe_start_ts = time.time()
                        elif (not self.leave_probe_done) and (time.time() - self.leave_probe_start_ts >= 0.0):
                            print(
                                "[Bot] 5s without Leave-Icon/F -> run one-time asset probe")
                            _ = self._probe_any_asset(sct)
                            self.leave_probe_done = True

                    # 3) still within the 5s window: wait & rescan
                    time.sleep(0.15)
                    continue

                # idle throttle
                time.sleep(0.05)

# ============================== DRIVER ============================== #


def _run():
    bot = Bot()
    t = threading.Thread(target=bot.loop, daemon=True)
    t.start()
    print("Hotkeys: F8 start • F9 pause • F10 exit")

    def on_press(key):
        try:
            if key == keyboard.Key.f8:
                bot.running = True
                print("[Bot] RUNNING")
            elif key == keyboard.Key.f9:
                bot.running = False
                print("[Bot] PAUSED")
            elif key == keyboard.Key.f10:
                bot.exit_flag = True
                print("[Bot] EXIT")
                return False
        except Exception as e:
            print("[HotkeyError]", e)

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    pyautogui.FAILSAFE = False
    _run()
