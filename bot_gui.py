# bot_gui.py
# BlueBot Studio — a polished GUI for launching and controlling BlueBot bots.
#
# Highlights:
# - Modern dark theme with gradient header and accent color
# - Notebook tabs: Control • Logs • Settings • About
# - Icon-like buttons with hover effects and keyboard shortcuts
# - Color-coded log tags ([Bot], [Probe], [Error], [Kanamia], [Tina], [Towering])
# - Live status pill with soft pulse animation
# - Split view with resizable panes
# - Persists your preferences to .bluebot_gui.json
#
# No external dependencies. Pure tkinter + ttk.

import os
import sys
import json
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont

import pyautogui  # for global hotkeys to the bots
pyautogui.FAILSAFE = False

APP_TITLE = "BlueBot Studio"
PREFS_FILE = ".bluebot_gui.json"

# --- Bot script paths (adjust if your file names differ) ---
BOT_SCRIPTS = {
    "Kanamia":  "kanamia_bot.py",
    "Tina":     "tina_bot.py",
    "Towering": "towering_bot.py",
}

# --- Default preferences (loaded/saved to .bluebot_gui.json) ---
DEFAULT_PREFS = {
    "bot": "Kanamia",
    "python": sys.executable,
    "monitor_index": "2",
    "window_title": "",
    "wrap_logs": False,
    "accent_color": "#7C5CFF",  # soft violet
}

# -------------- Utilities --------------


def load_prefs() -> dict:
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_PREFS, **data}
        except Exception:
            pass
    return DEFAULT_PREFS.copy()


def save_prefs(prefs: dict):
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass


def best_font(*candidates, fallback="Segoe UI"):
    root = tk._get_default_root()
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return fallback

# -------------- Main GUI --------------


class BlueBotGUI(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master: tk.Tk = master
        self.pack(fill="both", expand=True)

        # State
        self.proc: subprocess.Popen | None = None
        self.stop_reader = threading.Event()
        self.output_q: "queue.Queue[str]" = queue.Queue()
        self.status_state = "idle"  # idle, running, paused
        self.pulse_phase = 0

        # Preferences
        self.prefs = load_prefs()
        self.accent = self.prefs.get(
            "accent_color", DEFAULT_PREFS["accent_color"])

        # Theming & layout
        self._init_theme()
        self._build_header()
        self._build_body()
        self._bind_shortcuts()
        self._animate_status_pill()
        self._drain_queue()

        self.master.protocol("WM_DELETE_WINDOW", self.on_close)
        self.master.title(APP_TITLE)
        self.master.minsize(900, 560)

    # ---------- Theme ----------
    def _init_theme(self):
        self.master.configure(bg="#0f1116")
        style = ttk.Style(self.master)

        # Force "clam" theme for better dark styling
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Palette
        self.bg = "#0f1116"
        self.surface = "#141821"
        self.sunken = "#0b0e14"
        self.col_text = "#e7eaf0"
        self.col_subtext = "#9aa4b2"
        self.col_muted = "#6b7686"
        self.border = "#1a2030"
        self.success = "#2ec27e"
        self.warn = "#ffb454"
        self.err = "#e05f65"
        self.accent_hover = self._blend(self.accent, "#FFFFFF", 0.12)

        # Global styles
        style.configure(".", background=self.bg,
                        foreground=self.col_text, bordercolor=self.border)
        style.configure("TFrame", background=self.bg)
        style.configure("Card.TFrame", background=self.surface,
                        relief="flat", borderwidth=1)
        style.configure(
            "Dim.TLabel", foreground=self.col_subtext, background=self.bg)
        style.configure("Header.TLabel", foreground=self.col_text, background=self.bg,
                        font=(best_font("SF Pro Text", "Inter", "Segoe UI", "Helvetica"), 18, "bold"))

        # Buttons
        style.configure("Accent.TButton",
                        font=(best_font("Inter", "Segoe UI"), 10, "bold"),
                        background=self.accent,
                        foreground="#ffffff",
                        padding=(14, 8),
                        borderwidth=0,
                        focusthickness=3, focuscolor=self.accent)

        style.map("Accent.TButton",
                  background=[("active", self.accent_hover), ("disabled", "#3a3f4b")])

        style.configure("Tool.TButton",
                        font=(best_font("Inter", "Segoe UI"), 10, "bold"),
                        background="#1a2030", foreground=self.col_text,
                        padding=(12, 6), borderwidth=0)
        style.map("Tool.TButton",
                  background=[("active", "#222a3a"), ("disabled", "#1a2030")])

        style.configure("Pill.TLabel",
                        background="#1b2231", foreground=self.col_text,
                        padding=(12, 6))

        # Notebook
        style.configure("TNotebook", background=self.bg, borderwidth=0)
        style.configure("TNotebook.Tab", font=(best_font("Inter", "Segoe UI"), 10, "bold"),
                        padding=(18, 8), background=self.surface)
        style.map("TNotebook.Tab",
                  background=[("selected", self.bg), ("active", self.surface)],
                  foreground=[("selected", self.col_text), ("!selected", self.col_muted)])

        # Entries / Combos
        for w in ("TEntry", "TCombobox"):
            style.configure(w, fieldbackground="#111622",
                            background="#111622", foreground=self.col_text)
            style.map(w, fieldbackground=[("readonly", "#111622")])

    # ---------- Header ----------
    def _build_header(self):
        header = tk.Canvas(
            self, height=88, highlightthickness=0, bd=0, bg=self.bg)
        header.pack(side="top", fill="x")

        # Gradient background
        self._paint_header_gradient(header)

        # Title & subtitle
        title = tk.Label(header, text=APP_TITLE,
                         font=(best_font("SF Pro Display",
                               "Inter", "Segoe UI"), 22, "bold"),
                         fg="#ffffff", bg="#000000", bd=0, highlightthickness=0)
        subtitle = tk.Label(header, text="Launch and control your BlueBot automations with style ✨",
                            font=(best_font("Inter", "Segoe UI"), 11),
                            fg="#d7dbec", bg="#000000")
        title.place(x=24, y=16)
        subtitle.place(x=26, y=52)

        # Status pill
        self.status_pill = ttk.Label(
            header, text="• IDLE", style="Pill.TLabel")
        self.status_pill.place(relx=1.0, x=-24, y=26, anchor="ne")

        self.header_canvas = header
        self.header_canvas.bind(
            "<Configure>", lambda e: self._paint_header_gradient(header))

    def _paint_header_gradient(self, canvas: tk.Canvas):
        canvas.delete("grad")
        w = canvas.winfo_width() or canvas.winfo_reqwidth()
        h = canvas.winfo_height() or 88

        # Smooth diagonal gradient
        start = self._hex_to_rgb(self.accent)
        end = self._hex_to_rgb("#0f1116")
        steps = max(16, w // 16)
        for i in range(steps):
            t = i / (steps - 1)
            r = int(start[0]*(1-t) + end[0]*t)
            g = int(start[1]*(1-t) + end[1]*t)
            b = int(start[2]*(1-t) + end[2]*t)
            x0 = int(i * (w / steps))
            x1 = int((i+1) * (w / steps))
            canvas.create_rectangle(
                x0, 0, x1, h, fill=f"#{r:02x}{g:02x}{b:02x}", width=0, tags="grad")
        # Overlay soft vignette
        canvas.create_rectangle(
            0, 0, w, h, fill="#000000", stipple="gray25", width=0, tags="grad")

    # ---------- Body ----------
    def _build_body(self):
        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(side="top", fill="both", expand=True, padx=10, pady=10)

        self.tab_control = ttk.Frame(self.nb, style="TFrame")
        self.tab_logs = ttk.Frame(self.nb, style="TFrame")
        self.tab_settings = ttk.Frame(self.nb, style="TFrame")
        self.tab_about = ttk.Frame(self.nb, style="TFrame")

        self.nb.add(self.tab_control, text="Control")
        self.nb.add(self.tab_logs, text="Logs")
        self.nb.add(self.tab_settings, text="Settings")
        self.nb.add(self.tab_about, text="About")

        self._build_control_tab()
        self._build_logs_tab()
        self._build_settings_tab()
        self._build_about_tab()

    # ---------- Control Tab ----------
    def _build_control_tab(self):
        outer = ttk.Frame(self.tab_control, padding=10)
        outer.pack(fill="both", expand=True)

        # Top controls card
        card = ttk.Frame(outer, style="Card.TFrame")
        card.pack(fill="x")
        inner = ttk.Frame(card, padding=14, style="Card.TFrame")
        inner.pack(fill="x")

        # Bot selector
        ttk.Label(inner, text="Bot", style="Dim.TLabel").grid(
            row=0, column=0, sticky="w")
        self.bot_var = tk.StringVar(value=self.prefs["bot"])
        self.bot_combo = ttk.Combobox(inner, textvariable=self.bot_var,
                                      values=list(BOT_SCRIPTS.keys()),
                                      state="readonly", width=16)
        self.bot_combo.grid(row=1, column=0, sticky="we", padx=(0, 12))

        # Python path
        ttk.Label(inner, text="Python", style="Dim.TLabel").grid(
            row=0, column=1, sticky="w")
        self.py_var = tk.StringVar(value=self.prefs["python"])
        self.py_entry = ttk.Entry(inner, textvariable=self.py_var)
        self.py_entry.grid(row=1, column=1, sticky="we")
        ttk.Button(inner, text="Browse", style="Tool.TButton",
                   command=self._pick_python).grid(row=1, column=2, padx=(8, 0))

        # Monitor index
        ttk.Label(inner, text="Monitor Index", style="Dim.TLabel").grid(
            row=0, column=3, sticky="w", padx=(18, 0))
        self.mon_var = tk.StringVar(value=self.prefs["monitor_index"])
        ttk.Entry(inner, textvariable=self.mon_var, width=6).grid(
            row=1, column=3, sticky="w", padx=(18, 0))

        # Window title
        ttk.Label(inner, text="Window Title (optional)", style="Dim.TLabel").grid(
            row=0, column=4, sticky="w", padx=(18, 0))
        self.win_var = tk.StringVar(value=self.prefs["window_title"])
        ttk.Entry(inner, textvariable=self.win_var, width=32).grid(
            row=1, column=4, sticky="we", padx=(0, 8))

        inner.columnconfigure(1, weight=1)
        inner.columnconfigure(4, weight=2)

        # Action bar
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(12, 8))

        self.start_btn = ttk.Button(
            bar, text="▶  Start", style="Accent.TButton", command=self.start_bot)
        self.start_btn.pack(side="left")

        self.kill_btn = ttk.Button(
            bar, text="␡  Kill", style="Tool.TButton", command=self.kill_bot, state=tk.DISABLED)
        self.kill_btn.pack(side="left", padx=(8, 0))

        bar_sp = ttk.Frame(bar)
        bar_sp.pack(side="left", padx=8)

        self.run_btn = ttk.Button(bar, text="⏵  Run  (F8)", style="Tool.TButton",
                                  command=lambda: self._send_key('f8'), state=tk.DISABLED)
        self.run_btn.pack(side="left", padx=4)

        self.pause_btn = ttk.Button(bar, text="⏸  Pause (F9)", style="Tool.TButton",
                                    command=lambda: self._send_key('f9'), state=tk.DISABLED)
        self.pause_btn.pack(side="left", padx=4)

        self.exit_btn = ttk.Button(bar, text="⏻  Exit  (F10)", style="Tool.TButton",
                                   command=lambda: self._send_key('f10'), state=tk.DISABLED)
        self.exit_btn.pack(side="left", padx=4)

        # Split: Log preview on the right, helpful tips on the left
        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=10, style="Card.TFrame")
        right = ttk.Frame(paned, padding=0, style="Card.TFrame")
        paned.add(left, weight=1)
        paned.add(right, weight=2)

        # Helpful tips
        ttk.Label(left, text="Quick Tips", font=(
            best_font("Inter", "Segoe UI"), 12, "bold")).pack(anchor="w", pady=(0, 6))
        tips = (
            "• Use F8/F9/F10 hotkeys to control the bot.\n"
            "• The status pill reflects bot state (IDLE/RUNNING/PAUSED).\n"
            "• 'Python' points to your interpreter; switch to venv if needed.\n"
            "• You can pass 'Monitor Index' and 'Window Title' to bots.\n"
            "• Logs are also in the Logs tab with color tags."
        )
        tk.Label(left, text=tips, justify="left", fg=self.col_subtext, bg=self.surface,
                 font=(best_font("Inter", "Segoe UI"), 10)).pack(anchor="w")

        # Live tail log (read-only)
        self.preview = tk.Text(right, wrap="none", height=16, bg=self.sunken, fg=self.col_text,
                               insertbackground=self.col_text, relief="flat", padx=10, pady=8)
        self.preview.pack(fill="both", expand=True)
        self._style_log_widget(self.preview)

    # ---------- Logs Tab ----------
    def _build_logs_tab(self):
        outer = ttk.Frame(self.tab_logs, padding=10)
        outer.pack(fill="both", expand=True)

        # Toolbar
        tb = ttk.Frame(outer)
        tb.pack(fill="x")
        self.wrap_var = tk.BooleanVar(value=self.prefs.get("wrap_logs", False))
        ttk.Checkbutton(tb, text="Wrap lines", variable=self.wrap_var,
                        command=self._toggle_wrap).pack(side="left")

        ttk.Button(tb, text="Clear", style="Tool.TButton",
                   command=self._clear_logs).pack(side="right")

        # Log text
        self.log_text = tk.Text(outer, wrap="none" if not self.wrap_var.get() else "word",
                                height=24, bg=self.sunken, fg=self.col_text,
                                insertbackground=self.col_text, relief="flat", padx=10, pady=10)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self._style_log_widget(self.log_text)

    def _style_log_widget(self, widget: tk.Text):
        # Tag colors for nicer logs
        widget.tag_configure("bot", foreground=self.col_text)
        widget.tag_configure("probe", foreground=self.warn)
        widget.tag_configure("err", foreground=self.err)
        widget.tag_configure("kanamia", foreground="#6bdcff")
        widget.tag_configure("tina", foreground="#ff7ac6")
        widget.tag_configure("towering", foreground="#ffd479")
        widget.tag_configure("gray", foreground=self.col_muted)

    # ---------- Settings Tab ----------
    def _build_settings_tab(self):
        outer = ttk.Frame(self.tab_settings, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Theme & Behavior", font=(
            best_font("Inter", "Segoe UI"), 12, "bold")).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Accent Color (hex):",
                  style="Dim.TLabel").pack(side="left")
        self.accent_var = tk.StringVar(value=self.accent)
        ent = ttk.Entry(row, textvariable=self.accent_var, width=14)
        ent.pack(side="left", padx=8)
        ttk.Button(row, text="Apply", style="Tool.TButton",
                   command=self._apply_accent).pack(side="left")

        ttk.Label(outer, text="Settings are saved automatically.",
                  style="Dim.TLabel").pack(anchor="w", pady=(12, 0))

    # ---------- About Tab ----------
    def _build_about_tab(self):
        outer = ttk.Frame(self.tab_about, padding=16)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="BlueBot Studio", style="Header.TLabel")
        title.pack(anchor="w", pady=(0, 6))
        msg = (
            "A lightweight, elegant launcher for your BlueBot family (Kanamia, Tina, Towering).\n"
            "• Pure tkinter + ttk (no extra dependencies)\n"
            "• Dark theme, gradient header, and color-coded logs\n"
            "• Keyboard shortcuts: Ctrl+R (Start), Ctrl+P (Pause), Ctrl+E (Exit), Ctrl+K (Kill)"
        )
        ttk.Label(outer, text=msg, style="Dim.TLabel",
                  justify="left").pack(anchor="w")

    # ---------- Actions ----------
    def _pick_python(self):
        path = filedialog.askopenfilename(
            title="Select Python interpreter",
            filetypes=[("Executable", "*.exe;*"), ("All files", "*.*")]
        )
        if path:
            self.py_var.set(path)
            self._persist()

    def start_bot(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("BlueBot Studio", "A bot is already running.")
            return

        bot_key = self.bot_var.get()
        script = BOT_SCRIPTS.get(bot_key)
        if not script or not os.path.exists(script):
            messagebox.showerror("Error", f"Script not found: {script}")
            return

        # Pass monitor index and window title via environment variables
        env = os.environ.copy()
        if self.mon_var.get().strip().isdigit():
            env["MONITOR_INDEX"] = self.mon_var.get().strip()
        if self.win_var.get().strip():
            env["GAME_WINDOW_TITLE"] = self.win_var.get().strip()

        cmd = [self.py_var.get().strip() or sys.executable, script]
        self._write_log(f"[BlueBot] Launching {script} …\n", tags=("bot",))
        self._set_status("running")

        # Start subprocess with stdout piping (TEXT MODE for line buffering)
        self.stop_reader.clear()
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # line-buffered (works only with text=True)
                bufsize=1,
                text=True,                 # <— critical fix
                encoding="utf-8",
                errors="replace",
                cwd=os.path.dirname(os.path.abspath(script)) or None,
                env=env,
            )
        except Exception as e:
            self._write_log(f"[Error] Failed to launch: {e}\n", tags=("err",))
            self._set_status("idle")
            return

        t = threading.Thread(target=self._reader,
                             args=(self.proc,), daemon=True)
        t.start()

        self.kill_btn.config(state=tk.NORMAL)
        self.run_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.NORMAL)
        self.exit_btn.config(state=tk.NORMAL)

        self._persist()

    def kill_bot(self):
        if self.proc and self.proc.poll() is None:
            self._write_log("[BlueBot] Terminating process …\n", tags=("bot",))
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._write_log("[BlueBot] Force-killing …\n", tags=("bot",))
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self._cleanup_proc()
        self._set_status("idle")

    def _cleanup_proc(self):
        self.stop_reader.set()
        if self.proc and self.proc.stdout:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
        self.proc = None
        self.kill_btn.config(state=tk.DISABLED)
        self.run_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)
        self.exit_btn.config(state=tk.DISABLED)

    def _send_key(self, key_name: str):
        try:
            pyautogui.keyDown(key_name)
            pyautogui.keyUp(key_name)
            self._write_log(
                f"[BlueBot] Hotkey sent: {key_name.upper()}\n", tags=("bot",))
            if key_name.lower() == "f8":
                self._set_status("running")
            elif key_name.lower() == "f9":
                self._set_status("paused")
            elif key_name.lower() == "f10":
                self._set_status("idle")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send hotkey: {e}")

    # ---------- Reader / Logs ----------
    def _reader(self, proc: subprocess.Popen):
        try:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                if self.stop_reader.is_set():
                    break
                self.output_q.put(line)
        except Exception as e:
            self.output_q.put(f"[Error] Reader error: {e}\n")

    def _drain_queue(self):
        drained = False
        try:
            while True:
                msg = self.output_q.get_nowait()
                drained = True
                # Tag heuristics
                tags = self._guess_tags(msg)
                self._write_log(msg, tags=tags)
        except queue.Empty:
            pass

        # Keep preview and logs in sync
        if drained and self.preview.winfo_exists():
            self.preview.see("end")
        self.master.after(50, self._drain_queue)

    def _guess_tags(self, msg: str):
        m = msg.lower()
        tags = []
        if "[error]" in m or "error:" in m:
            tags.append("err")
        if "kanamia" in m:
            tags.append("kanamia")
        if "tina" in m:
            tags.append("tina")
        if "towering" in m:
            tags.append("towering")
        if "[probe]" in m:
            tags.append("probe")
        if "[bot]" in m:
            tags.append("bot")
        return tuple(tags) if tags else ("gray",)

    def _write_log(self, msg: str, tags=("gray",)):
        # Main log pane
        if self.log_text.winfo_exists():
            self.log_text.insert("end", msg, tags)
            self.log_text.see("end")
        # Preview pane
        if self.preview.winfo_exists():
            self.preview.insert("end", msg, tags)
            self.preview.see("end")

    def _toggle_wrap(self):
        self.log_text.config(wrap="word" if self.wrap_var.get() else "none")
        self._persist()

    def _clear_logs(self):
        self.log_text.delete("1.0", "end")
        self.preview.delete("1.0", "end")

    # ---------- Shortcuts & Status ----------
    def _bind_shortcuts(self):
        self.master.bind("<Control-r>", lambda e: self.start_bot())
        self.master.bind("<Control-p>", lambda e: self._send_key('f9'))
        self.master.bind("<Control-e>", lambda e: self._send_key('f10'))
        self.master.bind("<Control-k>", lambda e: self.kill_bot())

    def _set_status(self, state: str):
        self.status_state = state
        if state == "running":
            txt = "• RUNNING"
            fg = self.success
        elif state == "paused":
            txt = "• PAUSED"
            fg = self.warn
        else:
            txt = "• IDLE"
            fg = self.col_text
        try:
            self.status_pill.configure(text=txt, foreground=fg)
        except Exception:
            pass

    def _animate_status_pill(self):
        # soft pulse while running
        try:
            if self.status_state == "running":
                self.pulse_phase = (self.pulse_phase + 1) % 60
                t = (self.pulse_phase / 60.0)
                mix = 0.10 + 0.10 * (1 + (2*t - 1))  # simple wave
                self.status_pill.configure(background=self._blend(
                    "#1b2231", self.accent, abs(mix)))
            else:
                self.status_pill.configure(background="#1b2231")
        except Exception:
            pass
        self.master.after(120, self._animate_status_pill)

    def _apply_accent(self):
        color = self.accent_var.get().strip() or self.accent
        if not color.startswith("#") or len(color) not in (4, 7):
            messagebox.showerror(
                "Invalid color", "Please enter a hex color like #7C5CFF")
            return
        self.accent = color
        self.prefs["accent_color"] = color
        save_prefs(self.prefs)
        self._init_theme()
        self._paint_header_gradient(self.header_canvas)

    def _persist(self):
        self.prefs["bot"] = self.bot_var.get()
        self.prefs["python"] = self.py_var.get().strip()
        self.prefs["monitor_index"] = self.mon_var.get().strip()
        self.prefs["window_title"] = self.win_var.get().strip()
        self.prefs["wrap_logs"] = bool(self.wrap_var.get())
        save_prefs(self.prefs)

    # ---------- Color helpers ----------
    def _hex_to_rgb(self, h: str):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join([c*2 for c in h])
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, rgb):
        r, g, b = rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    def _blend(self, c1: str, c2: str, t: float):
        r1, g1, b1 = self._hex_to_rgb(c1)
        r2, g2, b2 = self._hex_to_rgb(c2)
        r = int(r1*(1-t) + r2*t)
        g = int(g1*(1-t) + g2*t)
        b = int(b1*(1-t) + b2*t)
        return self._rgb_to_hex((r, g, b))

    # ---------- Close ----------
    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Close", "A BlueBot is still running. Close anyway?"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=1.5)
            except Exception:
                pass
        self._cleanup_proc()
        save_prefs(self.prefs)
        try:
            self.master.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    # Window background and initial geometry
    root.configure(bg="#0f1116")
    root.geometry("980x640")
    app = BlueBotGUI(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # Graceful Ctrl+C in console
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
