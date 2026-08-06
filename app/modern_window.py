"""
Airbrakes V3 Ground Station — modernised UI.

DROP-IN REPLACEMENT for app/modern_window.py in the Airbrakes-V3 repo.
All backend modules (serial_link, data_store, plotting, firmware,
coast_table_tool, coast_lookup, config_editor) are completely untouched.

Key improvements over the original
-----------------------------------
* Persistent page frames — pages are shown/hidden, never destroyed/rebuilt.
* Auto-connect — daemon thread polls serial_link.find_board() every 2 s and
  connects automatically when a board is found and no link is open.
* Toast notification system — every single button fires a non-blocking
  coloured status strip (ok / warn / error / info) that auto-dismisses.
* Board page — animated progress, per-flight row delete, download-and-delete,
  per-row selection highlight.
* History page — two-panel layout:
    Left  : scrollable flight list with per-row local delete, category badges.
    Right : Stats | Plots | Data table tabs.
      Plots     : all 7 plotting.ALL_PLOTS with NavigationToolbar2Tk
                  (zoom / pan / save) embedded in-app.
      Data table: full CSV viewer in-app (no Excel), scrollable, up to 2000
                  rows shown, export button.
* Larger fonts (28 px page titles / 13 px nav / 11 px body).
* Bug-fix: removes the duplicate _activity() definition from the original.
* Bug-fix: Ground test page no longer calls _postflight().
* Bug-fix: port combo is cleared before every refresh.
"""

import csv as _csv
import json
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import matplotlib

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import pandas as pd

import coast_lookup
import coast_table_tool
import data_store
import firmware
import plotting
import serial_link

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------
APP_DIR = os.path.join(os.path.expanduser("~"), ".airbrakes_ground_station")
APP_CONFIG_PATH = os.path.join(APP_DIR, "app_config.json")

# ---------------------------------------------------------------------------
# Design tokens — every colour lives here, nowhere else
# ---------------------------------------------------------------------------
BG        = "#080e14"
SIDEBAR   = "#0d1520"
SURFACE   = "#111d2a"
SURFACE2  = "#172233"
CARD      = "#1a2739"
FIELD     = "#1f2f40"
HOVER     = "#28405a"
BORDER    = "#1e3045"
CONSOLE   = "#060d14"

TEXT      = "#e8f4f0"
MUTED     = "#7b9aab"
SUBTLE    = "#4d6878"

TEAL      = "#3de0b5"
TEAL_DIM  = "#0e4038"
TEAL_MID  = "#1a5e52"
AMBER     = "#f5c542"
AMBER_DIM = "#3d2d08"
RED       = "#f0697a"
RED_DIM   = "#3d1520"
BLUE      = "#5ea8f5"

MONO = "Cascadia Mono" if os.name == "nt" else "Menlo"
SANS = "Segoe UI"      if os.name == "nt" else "SF Pro Display"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config():
    try:
        with open(APP_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(v):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(v, f, indent=2)


def _run_bg(root, task, done):
    """Run task() in a daemon thread; call done(result, error) on main thread."""
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            q.put((task(), None))
        except Exception as exc:          # noqa: BLE001
            q.put((None, exc))

    def poll():
        try:
            r, e = q.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        done(r, e)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    # ------------------------------------------------------------------ init
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Airbrakes V3  ·  Ground Station")
        self.geometry("1380x900")
        self.minsize(1050, 700)
        self.configure(fg_color=BG)
        self._dark_titlebar()

        # App state
        self.cfg          = load_config()
        self.repo_path    = self.cfg.get("repo_path")
        self.data_dir     = self.cfg.get("data_dir", os.path.join(APP_DIR, "flight_data"))
        self.store        = data_store.DataStore(self.data_dir)
        self.link         = None            # FlightComputerLink or None
        self._last_port   = None
        self._monitor_job = None
        self._monitor_paused = False
        self._autoscroll  = True
        self._op_running  = False
        self._flights_on_board = []
        self._selected_flight_idx = None
        self._coast_table_cache = None
        self._history_entries = []
        self._selected_history_entry = None
        self._auto_connect_enabled = True
        self._auto_connect_job = None
        self._pages = {}                    # name -> CTkFrame

        # Build chrome (sidebar + content shell) then all pages
        self._build_chrome()
        self._show_page("Board")

        # Kick off auto-scan after the window is visible
        self.after(800, self._auto_connect_tick)

        if not self.repo_path or not os.path.isdir(self.repo_path):
            self.after(600, self._choose_repo_prompt)

    # ------------------------------------------------------------------ OS
    def _dark_titlebar(self):
        if os.name == "nt":
            try:
                import ctypes
                v = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    self.winfo_id(), 20, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass

    # ================================================================== Chrome
    def _build_chrome(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        # Content area
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # Toast overlay — built once, shown/hidden via place()
        self._toast_frame = ctk.CTkFrame(
            self.content, fg_color=TEAL_DIM, corner_radius=12,
            border_color=TEAL_MID, border_width=1)
        self._toast_label = ctk.CTkLabel(
            self._toast_frame, text="", text_color=TEAL,
            font=ctk.CTkFont(family=SANS, size=12, weight="bold"),
            wraplength=520, anchor="w")
        self._toast_label.pack(padx=16, pady=10)
        self._toast_visible = False
        self._toast_job = None

        # Build all pages upfront so they exist for the lifetime of the app
        self._build_board_page()
        self._build_preflight_page()
        self._build_ground_test_page()
        self._build_history_page()

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=256, fg_color=SIDEBAR, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        # Logo block
        logo_box = ctk.CTkFrame(sb, fg_color="transparent")
        logo_box.pack(fill="x", padx=24, pady=(28, 32))
        mark = ctk.CTkFrame(logo_box, width=42, height=42, fg_color=TEAL_DIM, corner_radius=14)
        mark.pack(side="left", padx=(0, 14))
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="A", text_color=TEAL,
                     font=ctk.CTkFont(family=SANS, size=22, weight="bold")).place(
            relx=.5, rely=.48, anchor="center")
        ctk.CTkLabel(logo_box, text="AIRBRAKES", text_color=TEAL,
                     font=ctk.CTkFont(family=SANS, size=17, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(logo_box, text="V3  /  GROUND STATION", text_color=SUBTLE,
                     font=ctk.CTkFont(family=SANS, size=9, weight="bold")).pack(anchor="w")

        # Nav buttons
        self._nav_btns = {}
        nav_items = [
            ("Board",       "⌁"),
            ("Pre-flight",  "◈"),
            ("Ground test", "⚙"),
            ("History",     "◷"),
        ]
        for name, glyph in nav_items:
            btn = ctk.CTkButton(
                sb, text=f"  {glyph}   {name}", anchor="w",
                height=48, corner_radius=14,
                fg_color="transparent", bg_color=SIDEBAR,
                hover_color=FIELD, text_color=MUTED,
                font=ctk.CTkFont(family=SANS, size=13, weight="bold"),
                command=lambda n=name: self._show_page(n))
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_btns[name] = btn

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).pack(fill="x", padx=22, pady=28)

        # Connection status
        ctk.CTkLabel(sb, text="BOARD LINK", text_color=SUBTLE,
                     font=ctk.CTkFont(family=SANS, size=9, weight="bold")).pack(
            anchor="w", padx=26)
        conn_card = ctk.CTkFrame(sb, fg_color=SURFACE, corner_radius=13)
        conn_card.pack(fill="x", padx=18, pady=(8, 6))
        self._conn_dot = ctk.CTkLabel(
            conn_card, text="●  OFFLINE", text_color=RED,
            font=ctk.CTkFont(family=SANS, size=11, weight="bold"))
        self._conn_dot.pack(anchor="w", padx=14, pady=(10, 2))
        self._conn_hint = ctk.CTkLabel(
            conn_card, text="Auto-scanning for board…", text_color=MUTED,
            font=ctk.CTkFont(family=SANS, size=10),
            wraplength=190, justify="left")
        self._conn_hint.pack(anchor="w", padx=14, pady=(0, 10))

        # Auto-connect toggle
        self._autoconn_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sb, text="Auto-connect", variable=self._autoconn_var,
            text_color=MUTED, font=ctk.CTkFont(family=SANS, size=11),
            fg_color=TEAL_MID, hover_color=TEAL_DIM, border_color=BORDER,
            checkmark_color=TEAL,
            command=self._toggle_autoconnect).pack(anchor="w", padx=22, pady=(4, 0))

    # ---------------------------------------------------------------- nav
    def _show_page(self, name: str):
        for pname, pbtn in self._nav_btns.items():
            active = pname == name
            pbtn.configure(
                fg_color=TEAL_DIM if active else "transparent",
                text_color=TEXT if active else MUTED)
        for pname, pframe in self._pages.items():
            if pname == name:
                pframe.grid(row=0, column=0, sticky="nsew")
            else:
                pframe.grid_remove()

    # ================================================================= Toast
    def toast(self, msg: str, kind: str = "ok", duration: int = 4000):
        """Non-blocking toast.  kind = 'ok' | 'warn' | 'error' | 'info'."""
        palettes = {
            "ok":    (TEAL,  TEAL_DIM,  TEAL_MID),
            "warn":  (AMBER, AMBER_DIM, "#6b4e0a"),
            "error": (RED,   RED_DIM,   "#6b1522"),
            "info":  (BLUE,  "#0e2040",  "#1e3a6b"),
        }
        tc, bg, brd = palettes.get(kind, palettes["ok"])
        self._toast_frame.configure(fg_color=bg, border_color=brd)
        self._toast_label.configure(text=msg, text_color=tc)
        if not self._toast_visible:
            self._toast_frame.place(relx=0.01, rely=0.01, relwidth=0.98)
            self._toast_visible = True
        if self._toast_job:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
        if duration > 0:
            self._toast_job = self.after(duration, self._dismiss_toast)

    def _dismiss_toast(self):
        self._toast_frame.place_forget()
        self._toast_visible = False
        self._toast_job = None

    # ================================================================= Auto-connect
    def _toggle_autoconnect(self):
        self._auto_connect_enabled = self._autoconn_var.get()
        if self._auto_connect_enabled:
            self.toast("Auto-connect enabled", "info")
            self._auto_connect_tick()
        else:
            self.toast("Auto-connect disabled", "warn")
            if self._auto_connect_job:
                try:
                    self.after_cancel(self._auto_connect_job)
                except tk.TclError:
                    pass
                self._auto_connect_job = None

    def _auto_connect_tick(self):
        self._auto_connect_job = None
        if not self._auto_connect_enabled:
            return
        if not self.link and not self._op_running:
            def scan():
                return serial_link.find_board()

            def on_scan(port, err):
                if port and not self.link:
                    self._log_activity(f"Board detected on {port} — auto-connecting…")
                    self._conn_hint.configure(text=f"Found on {port} — connecting…")
                    self._do_connect(port, auto=True)

            _run_bg(self, scan, on_scan)
        self._auto_connect_job = self.after(2000, self._auto_connect_tick)

    # ================================================================= Widget helpers
    def _lbl(self, parent, text, color=TEXT, size=12, weight="normal", **kw):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=ctk.CTkFont(family=SANS, size=size, weight=weight), **kw)

    def _btn(self, parent, text, cmd, kind="secondary", width=140, height=38, **kw):
        palettes = {
            "primary":   (TEAL,       "#29c49e", "#041410"),
            "secondary": (FIELD,      HOVER,     TEXT),
            "quiet":     ("transparent", FIELD,  MUTED),
            "danger":    ("#4a2028",  "#662030", RED),
            "warn":      (AMBER_DIM,  "#5c4208", AMBER),
        }
        fg, ho, tc = palettes.get(kind, palettes["secondary"])
        return ctk.CTkButton(
            parent, text=text, command=cmd,
            width=width, height=height, corner_radius=12,
            fg_color=fg, hover_color=ho, text_color=tc,
            font=ctk.CTkFont(family=SANS, size=12, weight="bold"), **kw)

    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER,
                            border_width=1, corner_radius=18, **kw)

    def _section_title(self, parent, eyebrow, title, subtitle=""):
        ctk.CTkLabel(parent, text=eyebrow.upper(), text_color=TEAL,
                     font=ctk.CTkFont(family=SANS, size=9, weight="bold")).pack(
            anchor="w", padx=28, pady=(26, 2))
        ctk.CTkLabel(parent, text=title, text_color=TEXT,
                     font=ctk.CTkFont(family=SANS, size=28, weight="bold")).pack(
            anchor="w", padx=28, pady=(4, 2))
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, text_color=MUTED,
                         font=ctk.CTkFont(family=SANS, size=12),
                         wraplength=860, justify="left").pack(
                anchor="w", padx=28, pady=(2, 18))

    # ================================================================= Activity log (shared)
    def _build_activity_widget(self, parent):
        card = self._card(parent)
        card.pack(fill="x", padx=20, pady=(0, 20))

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=18, pady=(16, 0))
        self._lbl(hdr, "LIVE ACTIVITY", TEAL, 9, "bold").pack(side="left")
        self._activity_title = self._lbl(hdr, "Standing by", TEXT, 12, "bold")
        self._activity_title.pack(side="right")

        self._activity_detail = self._lbl(card, "Your next operation will appear here.",
                                          MUTED, 10)
        self._activity_detail.pack(anchor="w", padx=18, pady=(4, 0))

        self._activity_bar = ctk.CTkProgressBar(card, height=8, corner_radius=4,
                                                 fg_color=FIELD, progress_color=TEAL)
        self._activity_bar.pack(fill="x", padx=18, pady=(10, 4))
        self._activity_bar.set(0)

        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.pack(fill="x", padx=18, pady=(0, 4))
        self._activity_pct = self._lbl(foot, "0%", SUBTLE, 10, "bold")
        self._activity_pct.pack(side="left")
        self._log_toggle_btn = self._btn(foot, "▸  Details", self._toggle_log, "quiet", 100, 27)
        self._log_toggle_btn.pack(side="right", padx=(0, 8))
        self._btn(foot, "Clear", self._clear_log, "quiet", 65, 27).pack(side="right")

        self._log_box = ctk.CTkTextbox(
            card, height=130, corner_radius=12,
            fg_color=CONSOLE, border_color=BORDER, border_width=1,
            text_color="#b3e8d5",
            font=ctk.CTkFont(family=MONO, size=10), wrap="none")
        self._log_box.pack(fill="x", padx=18, pady=(2, 14))
        self._log_box.pack_forget()
        self._log_box.configure(state="disabled")
        self._log_visible = False
        return card

    def _set_activity(self, text: str, running=False):
        self._op_running = running
        if not hasattr(self, "_activity_title"):
            return
        self._activity_title.configure(text=text)
        if running:
            self._activity_bar.configure(mode="indeterminate")
            self._activity_bar.start()
            self._activity_pct.configure(text="Working…")
            self._activity_detail.configure(
                text="Processing in the background — open Details for technical output")
        else:
            self._activity_bar.stop()
            self._activity_bar.configure(mode="determinate")
            ok = "fail" not in text.lower() and "error" not in text.lower()
            self._activity_bar.set(1.0 if ok else 0.0)
            self._activity_pct.configure(text="Done" if ok else "Needs attention")
            self._activity_detail.configure(
                text="Operation finished" if ok else "Open Details for more information")

    def _log_activity(self, s: str):
        try:
            if hasattr(self, "_log_box") and self._log_box.winfo_exists():
                self._log_box.configure(state="normal")
                self._log_box.insert("end", s + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
        except tk.TclError:
            pass

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self._log_box.pack(fill="x", padx=18, pady=(2, 14))
            self._log_toggle_btn.configure(text="▾  Details")
        else:
            self._log_box.pack_forget()
            self._log_toggle_btn.configure(text="▸  Details")

    def _clear_log(self):
        if hasattr(self, "_log_box"):
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            self._log_box.configure(state="disabled")

    # ================================================================= Serial monitor (shared)
    def _build_monitor_widget(self, parent):
        card = self._card(parent)
        card.pack(fill="x", padx=20, pady=(0, 20))

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=18, pady=(16, 6))
        self._lbl(hdr, "LIVE SERIAL MONITOR", TEAL, 9, "bold").pack(side="left")
        self._monitor_status_lbl = self._lbl(hdr, "●  Waiting for board", MUTED, 10, "bold")
        self._monitor_status_lbl.pack(side="right")

        ctrl = ctk.CTkFrame(card, fg_color="transparent")
        ctrl.pack(fill="x", padx=18, pady=(0, 6))
        self._monitor_lines_lbl = self._lbl(ctrl, "0 lines", SUBTLE, 10)
        self._monitor_lines_lbl.pack(side="left")
        self._btn(ctrl, "Clear", self._clear_monitor, "quiet", 65, 27).pack(side="right")
        self._autoscroll_btn = self._btn(
            ctrl, "Autoscroll  ON", self._toggle_autoscroll, "quiet", 118, 27)
        self._autoscroll_btn.pack(side="right", padx=(0, 8))

        self._monitor_box = ctk.CTkTextbox(
            card, height=170, corner_radius=12,
            fg_color=CONSOLE, border_color=BORDER, border_width=1,
            text_color="#c5ede0",
            font=ctk.CTkFont(family=MONO, size=10), wrap="none")
        self._monitor_box.pack(fill="x", padx=18, pady=(0, 14))

        tb = self._monitor_box._textbox
        tb.tag_config("normal", foreground="#c5ede0")
        tb.tag_config("warn",   foreground=AMBER)
        tb.tag_config("error",  foreground=RED)
        tb.tag_config("state",  foreground=BLUE)
        return card

    def _toggle_autoscroll(self):
        self._autoscroll = not self._autoscroll
        self._autoscroll_btn.configure(
            text="Autoscroll  " + ("ON" if self._autoscroll else "OFF"))
        self.toast(f"Autoscroll {'enabled' if self._autoscroll else 'disabled'}", "info", 2000)

    def _clear_monitor(self):
        self._monitor_box.configure(state="normal")
        self._monitor_box.delete("1.0", "end")
        self._monitor_box.configure(state="disabled")
        self._monitor_lines_lbl.configure(text="0 lines")
        self.toast("Monitor cleared", "info", 1500)

    def _append_monitor(self, text: str, tag="normal"):
        try:
            if not hasattr(self, "_monitor_box") or not self._monitor_box.winfo_exists():
                return
            tb = self._monitor_box._textbox
            tb.configure(state="normal")
            tb.insert("end", str(text) + "\n", tag)
            if self._autoscroll:
                tb.see("end")
            tb.configure(state="disabled")
        except tk.TclError:
            pass

    def _start_monitor_poll(self):
        if self._monitor_job is None:
            self._monitor_job = self.after(250, self._poll_monitor)

    def _poll_monitor(self):
        self._monitor_job = None
        if self.link and not self._monitor_paused:
            try:
                lines = self.link.read_available_lines()
                for line in lines:
                    lo = line.lower()
                    tag = ("error" if "error" in lo or "fail" in lo
                           else "warn"  if "warn" in lo
                           else "state" if "state" in lo
                           else "normal")
                    self._append_monitor(line, tag)
                if lines:
                    tb = self._monitor_box._textbox
                    count = int(tb.index("end-1c").split(".")[0]) - 1
                    if count > 600:
                        tb.configure(state="normal")
                        tb.delete("1.0", "100.0")
                        tb.configure(state="disabled")
                        count = max(0, count - 100)
                    self._monitor_lines_lbl.configure(text=f"{count:,} lines")
                    self._monitor_status_lbl.configure(
                        text=f"●  Live · {len(lines)} new line(s)", text_color=TEAL)
            except Exception as err:
                self._monitor_status_lbl.configure(
                    text=f"●  Monitor paused: {err}", text_color=RED)
        if self.link:
            self._monitor_job = self.after(250, self._poll_monitor)

    # ================================================================= Connection helpers
    def _do_connect(self, port: str, auto=False):
        self._set_activity(f"Connecting to {port}…", True)
        self._log_activity(f"Opening {port}…")
        if hasattr(self, "_board_prog") and self._board_prog.winfo_exists():
            self._board_prog.configure(mode="indeterminate")
            self._board_prog.start()
            self._board_prog.grid()
        if hasattr(self, "_board_event_lbl") and self._board_event_lbl.winfo_exists():
            self._board_event_lbl.configure(
                text=f"Connecting to {port}… board may need a moment", text_color=AMBER)

        def task():
            return serial_link.FlightComputerLink(port)

        def done(result, err):
            try:
                if hasattr(self, "_board_prog") and self._board_prog.winfo_exists():
                    self._board_prog.stop()
                    self._board_prog.grid_remove()
            except tk.TclError:
                pass
            if err:
                self.link = None
                self._conn_dot.configure(text="●  OFFLINE", text_color=RED)
                self._conn_hint.configure(text="Connection failed.")
                if hasattr(self, "_board_event_lbl"):
                    try:
                        self._board_event_lbl.configure(
                            text=f"Connection failed: {err}", text_color=RED)
                    except tk.TclError:
                        pass
                self._set_activity("Connection failed", False)
                self._log_activity(f"Error: {err}")
                if not auto:
                    self.toast(f"Connection failed: {err}", "error", 0)
                return
            self.link = result
            self._last_port = port
            self._conn_dot.configure(text="●  CONNECTED", text_color=TEAL)
            self._conn_hint.configure(text=f"Connected on {port}")
            if hasattr(self, "_board_event_lbl"):
                try:
                    self._board_event_lbl.configure(
                        text=f"Connected to {port} — board link active", text_color=TEAL)
                except tk.TclError:
                    pass
            if hasattr(self, "_monitor_status_lbl"):
                try:
                    self._monitor_status_lbl.configure(
                        text="●  Connected · waiting for output", text_color=AMBER)
                except tk.TclError:
                    pass
            self._set_activity("Connected", False)
            self._log_activity(f"Connected to {port}")
            self.toast(f"Board connected on {port}", "ok")
            self._start_monitor_poll()
            if hasattr(self, "_port_var"):
                self._port_var.set(port)

        _run_bg(self, task, done)

    def _disconnect(self):
        if self.link:
            try:
                self.link.close()
            except Exception:
                pass
            self.link = None
        if self._monitor_job:
            try:
                self.after_cancel(self._monitor_job)
            except tk.TclError:
                pass
            self._monitor_job = None
        self._conn_dot.configure(text="●  OFFLINE", text_color=RED)
        self._conn_hint.configure(text="Disconnected — scan or connect manually")
        if hasattr(self, "_board_event_lbl"):
            try:
                self._board_event_lbl.configure(
                    text="Disconnected — choose a port to reconnect", text_color=MUTED)
            except tk.TclError:
                pass
        if hasattr(self, "_monitor_status_lbl"):
            try:
                self._monitor_status_lbl.configure(text="●  Disconnected", text_color=MUTED)
            except tk.TclError:
                pass
        self._set_activity("Disconnected", False)
        self.toast("Board disconnected", "warn")

    def _reconnect_after_upload(self, port, attempt=0):
        if attempt >= 8:
            self._conn_dot.configure(text="●  OFFLINE", text_color=RED)
            self._conn_hint.configure(text="Reconnect manually after upload.")
            self.toast("Board did not reappear — reconnect manually", "warn")
            return
        self._log_activity(f"Waiting for {port} to reappear ({attempt+1}/8)…")

        def task():
            time.sleep(1.0)
            return serial_link.FlightComputerLink(port)

        def done(result, err):
            if err:
                self.after(500, lambda: self._reconnect_after_upload(port, attempt + 1))
            else:
                self.link = result
                self._last_port = port
                self._conn_dot.configure(text="●  CONNECTED", text_color=TEAL)
                self._conn_hint.configure(text=f"Reconnected after upload on {port}")
                self._log_activity("Board rebooted — serial monitor restored")
                self.toast(f"Board reconnected on {port} after upload", "ok")
                self._start_monitor_poll()

        _run_bg(self, task, done)

    # ================================================================= Repo / data dir
    def _choose_repo_prompt(self):
        messagebox.showinfo(
            "First-time setup",
            "Point this app at your local Airbrakes-V3 repo folder "
            "(the one containing platformio.ini).")
        self._choose_repo()

    def _choose_repo(self):
        path = filedialog.askdirectory(title="Select Airbrakes-V3 repo folder")
        if path:
            self.repo_path = path
            self.cfg["repo_path"] = path
            save_config(self.cfg)
            if hasattr(self, "_repo_path_lbl"):
                self._repo_path_lbl.configure(text=path)
            self._reload_config_fields()
            self.toast(f"Repo set: {path}", "ok")

    def _choose_data_dir(self):
        path = filedialog.askdirectory(title="Select flight data folder")
        if path:
            self.data_dir = path
            self.cfg["data_dir"] = path
            save_config(self.cfg)
            self.store = data_store.DataStore(self.data_dir)
            self._refresh_history_list()
            self.toast(f"Data folder set: {path}", "ok")

    # ================================================================= BOARD PAGE
    def _build_board_page(self):
        page = ctk.CTkScrollableFrame(
            self.content, fg_color=BG,
            scrollbar_fg_color=BG, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        self._pages["Board"] = page

        self._section_title(page, "TELEMETRY", "Board",
                            "Connect, download flights, and manage on-board storage.")

        # Connection card
        conn_card = self._card(page)
        conn_card.pack(fill="x", padx=20, pady=(0, 16))
        conn_card.grid_columnconfigure(1, weight=1)

        self._lbl(conn_card, "Board connection", TEXT, 17, "bold").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 8))
        self._lbl(conn_card, "Port", MUTED, 11).grid(
            row=1, column=0, sticky="w", padx=20)

        self._port_var = tk.StringVar()
        self._port_combo = ctk.CTkComboBox(
            conn_card, variable=self._port_var,
            height=38, corner_radius=10,
            fg_color=FIELD, border_width=1, border_color=BORDER,
            button_color=FIELD, button_hover_color=HOVER,
            dropdown_fg_color=SURFACE2, dropdown_hover_color=HOVER,
            text_color=TEXT, values=[],
            font=ctk.CTkFont(family=MONO, size=11))
        self._port_combo.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=6)
        self._btn(conn_card, "Refresh", self._refresh_ports, "secondary", 90).grid(
            row=1, column=2, padx=(0, 20), pady=6)

        br = ctk.CTkFrame(conn_card, fg_color="transparent")
        br.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 4))
        self._connect_btn = self._btn(br, "Connect", self._manual_connect, "primary", 120)
        self._connect_btn.pack(side="left", padx=(0, 10))
        self._btn(br, "Disconnect", self._disconnect, "secondary", 120).pack(
            side="left", padx=(0, 10))
        self._btn(br, "Verify (INFO)", self._verify_connection, "secondary", 130).pack(
            side="left")

        self._board_prog = ctk.CTkProgressBar(
            conn_card, height=7, corner_radius=4, fg_color=FIELD, progress_color=TEAL)
        self._board_prog.grid(row=3, column=0, columnspan=3, sticky="ew",
                              padx=20, pady=(4, 0))
        self._board_prog.set(0)
        self._board_prog.grid_remove()

        self._board_event_lbl = self._lbl(
            conn_card, "Ready — choose a port or wait for auto-connect", MUTED, 10)
        self._board_event_lbl.grid(row=4, column=0, columnspan=3, sticky="w",
                                   padx=20, pady=(4, 16))

        # Stored flights card
        flights_card = self._card(page)
        flights_card.pack(fill="x", padx=20, pady=(0, 16))
        flights_card.grid_columnconfigure(0, weight=1)

        fhdr = ctk.CTkFrame(flights_card, fg_color="transparent")
        fhdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 4))
        self._lbl(fhdr, "Flights on board", TEXT, 17, "bold").pack(side="left")
        self._btn(fhdr, "List flights", self._list_flights, "secondary", 120, 32).pack(
            side="right")

        self._flights_status_lbl = self._lbl(
            flights_card, "Connect and click 'List flights' to see on-board flights", MUTED, 11)
        self._flights_status_lbl.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 8))

        self._flights_list_frame = ctk.CTkFrame(flights_card, fg_color="transparent")
        self._flights_list_frame.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))

        bar = ctk.CTkFrame(flights_card, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="w", padx=20, pady=(4, 18))
        self._btn(bar, "Download selected",          self._download_selected, "primary",  170).pack(side="left", padx=(0, 10))
        self._btn(bar, "Download all",               self._download_all,      "primary",  140).pack(side="left", padx=(0, 10))
        self._btn(bar, "Delete selected from device", self._delete_from_device, "danger", 210).pack(side="left")

        self._build_monitor_widget(page)
        self._build_activity_widget(page)
        self._refresh_ports()

    # ---- Board actions ----
    def _refresh_ports(self):
        ports = serial_link.list_ports()
        vals = [f"{dev}  ·  {desc}" for dev, desc in ports]
        if hasattr(self, "_port_combo"):
            self._port_combo.configure(values=vals)
        auto = serial_link.find_board()
        if auto and hasattr(self, "_port_var"):
            matched = next((v for v in vals if v.startswith(auto)), auto)
            self._port_var.set(matched)
        n = len(vals)
        if hasattr(self, "_board_event_lbl"):
            try:
                self._board_event_lbl.configure(
                    text=f"{n} serial port(s) found — select one, or wait for auto-connect")
            except tk.TclError:
                pass
        self.toast(f"Port scan: {n} port(s) found", "info", 2000)

    def _selected_port(self):
        val = getattr(self, "_port_var", tk.StringVar()).get()
        return val.split()[0] if val else None

    def _manual_connect(self):
        port = self._selected_port()
        if not port:
            self.toast("Select a serial port first", "warn")
            messagebox.showwarning("No port", "Choose a serial port first.")
            return
        # Disable auto-connect so this manual selection is respected
        self._auto_connect_enabled = False
        self._autoconn_var.set(False)
        self._do_connect(port, auto=False)

    def _verify_connection(self):
        if not self.link:
            self.toast("Not connected — connect first", "warn")
            messagebox.showwarning("Not connected", "Connect to the board first.")
            return
        self.toast("Sending INFO to board…", "info", 2000)
        self._set_activity("Verifying board connection…", True)
        self._monitor_paused = True

        def task():
            return self.link.get_info()

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("Verification failed", False)
                self._board_event_lbl.configure(text=f"INFO failed: {err}", text_color=RED)
                self.toast(f"Verification failed: {err}", "error", 0)
            else:
                self._set_activity("Board verified", False)
                self._board_event_lbl.configure(
                    text=f"Board verified — {result}", text_color=TEAL)
                self.toast(f"Board verified: {result}", "ok")

        _run_bg(self, task, done)

    def _list_flights(self):
        if not self.link:
            self.toast("Not connected — connect first", "warn")
            messagebox.showwarning("Not connected", "Connect first.")
            return
        self.toast("Listing flights on board…", "info", 2000)
        self._set_activity("Reading flights from board…", True)
        self._monitor_paused = True
        self._flights_status_lbl.configure(text="Reading flight list…", text_color=AMBER)

        def task():
            return self.link.list_flights()

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("List failed", False)
                self._flights_status_lbl.configure(text=str(err), text_color=RED)
                self.toast(f"List failed: {err}", "error", 0)
                return
            self._flights_on_board = result
            self._selected_flight_idx = None
            self._render_flight_rows()
            self._flights_status_lbl.configure(
                text=f"{len(result)} flight(s) on board", text_color=MUTED)
            self._set_activity(f"{len(result)} flights found", False)
            self.toast(f"Found {len(result)} flight(s) on board", "ok")

        _run_bg(self, task, done)

    def _render_flight_rows(self):
        for w in self._flights_list_frame.winfo_children():
            w.destroy()
        if not self._flights_on_board:
            self._lbl(self._flights_list_frame, "No flights found on the board.",
                      MUTED, 11).pack(pady=18)
            return
        for i, f in enumerate(self._flights_on_board):
            self._build_flight_row(i, f)

    def _build_flight_row(self, idx: int, f: dict):
        is_sel = self._selected_flight_idx == idx
        row = ctk.CTkFrame(
            self._flights_list_frame,
            fg_color=HOVER if is_sel else FIELD,
            border_color=TEAL_MID if is_sel else BORDER,
            border_width=1 if is_sel else 0,
            corner_radius=12)
        row.pack(fill="x", padx=6, pady=3)
        row.bind("<Button-1>", lambda e, i=idx: self._select_flight_row(i))

        self._lbl(row, f"{idx+1:02d}", TEAL, 12, "bold",
                  width=34).pack(side="left", padx=(12, 4), pady=10)
        self._lbl(row, f["file"], TEXT, 11, "bold").pack(side="left", padx=4)
        self._lbl(row, f["size"], MUTED, 10).pack(side="left", padx=6)
        if f["active"]:
            ctk.CTkLabel(row, text="ACTIVE", text_color=AMBER, fg_color=AMBER_DIM,
                         corner_radius=8, padx=8, pady=3,
                         font=ctk.CTkFont(family=SANS, size=9, weight="bold")).pack(
                side="right", padx=4)
        self._btn(row, "Delete", lambda ff=f: self._delete_flight_row(ff),
                  "danger", 76, 30).pack(side="right", padx=(0, 10))
        row.bind("<Enter>",
                 lambda e, r=row: r.configure(fg_color=HOVER))
        row.bind("<Leave>",
                 lambda e, r=row, i=idx:
                 r.configure(fg_color=HOVER if self._selected_flight_idx == i else FIELD))

    def _select_flight_row(self, idx: int):
        self._selected_flight_idx = idx
        self._render_flight_rows()
        f = self._flights_on_board[idx]
        self._flights_status_lbl.configure(
            text=f"Selected: {f['file']}  ({f['size']})", text_color=TEAL)
        self.toast(f"Selected {f['file']}", "info", 1500)

    def _delete_flight_row(self, f: dict):
        if not self.link:
            self.toast("Not connected", "warn"); return
        if not messagebox.askyesno("Delete from device",
                                   f"Delete {f['file']} from the BOARD?\n\n"
                                   "Make sure you have already downloaded it!"):
            return
        self.toast(f"Deleting {f['file']} from device…", "warn", 0)
        self._set_activity(f"Deleting {f['file']}…", True)
        self._monitor_paused = True

        def task():
            return self.link.delete_flight(f["num"])

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("Delete failed", False)
                self.toast(f"Delete failed: {err}", "error", 0)
            else:
                self._set_activity("Flight deleted from device", False)
                self.toast(f"{f['file']} deleted from board", "ok")
                self._list_flights()

        _run_bg(self, task, done)

    def _download_selected(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        if self._selected_flight_idx is None:
            self.toast("Click a flight row first to select it", "warn")
            messagebox.showinfo("No selection", "Click a flight row to select it."); return
        f = self._flights_on_board[self._selected_flight_idx]
        self._do_download([f["num"]], delete_after=False)

    def _download_all(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        if not self._flights_on_board:
            self.toast("List flights first", "warn")
            messagebox.showinfo("Nothing to download", "List flights first."); return
        nums = [f["num"] for f in self._flights_on_board if f["num"] is not None]
        self._do_download(nums, delete_after=True)

    def _do_download(self, nums: list, delete_after=False):
        self.toast(f"Downloading {len(nums)} flight(s)…", "info", 0)
        self._set_activity(f"Downloading {len(nums)} flight(s)…", True)
        self._monitor_paused = True

        def task():
            saved = []
            for num in nums:
                records = self.link.download_flight(num)
                config_h = (os.path.join(self.repo_path, "include", "config.h")
                            if self.repo_path else None)
                category = ("ground_test"
                            if any(r.get("state_name", "").startswith("GROUND_TEST")
                                   for r in records)
                            else "flight")
                folder = self.store.save_flight(num, records,
                                                config_h_path=config_h,
                                                category=category)
                saved.append(folder)
                if delete_after and not any(
                        f["num"] == num and f["active"] for f in self._flights_on_board):
                    self.link.delete_flight(num)
            return saved

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("Download failed", False)
                self.toast(f"Download failed: {err}", "error", 0)
            else:
                self._set_activity(f"Downloaded {len(result)} flight(s)", False)
                self.toast(f"Downloaded {len(result)} flight(s) — view in History", "ok")
                self._log_activity(f"Saved: {result}")
                self._refresh_history_list()
                if delete_after:
                    self._list_flights()

        _run_bg(self, task, done)

    def _delete_from_device(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        if self._selected_flight_idx is None:
            self.toast("Click a flight row first", "warn"); return
        f = self._flights_on_board[self._selected_flight_idx]
        self._delete_flight_row(f)

    # ================================================================= PRE-FLIGHT PAGE
    def _build_preflight_page(self):
        page = ctk.CTkScrollableFrame(
            self.content, fg_color=BG,
            scrollbar_fg_color=BG, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        self._pages["Pre-flight"] = page

        self._section_title(page, "OPERATIONS", "Pre-flight",
                            "Prepare the vehicle, generate its flight model, build and flash.")

        # Repo card
        repo_card = self._card(page)
        repo_card.pack(fill="x", padx=20, pady=(0, 16))
        repo_card.grid_columnconfigure(1, weight=1)
        self._lbl(repo_card, "Repository", TEXT, 17, "bold").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 4))
        self._repo_path_lbl = self._lbl(
            repo_card, self.repo_path or "No repo selected", MUTED, 11, anchor="w")
        self._repo_path_lbl.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20,
                                 pady=(0, 14))
        self._btn(repo_card, "Choose folder…", self._choose_repo, "secondary", 150).grid(
            row=1, column=2, padx=20, pady=(0, 14))

        # Launch conditions card
        lc_card = self._card(page)
        lc_card.pack(fill="x", padx=20, pady=(0, 16))
        lc_card.grid_columnconfigure(1, weight=1)
        self._lbl(lc_card, "Launch conditions", TEXT, 17, "bold").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 4))
        self._lbl(lc_card,
                  "Updates coast_table.py, coast_table.h and config.h (MASS/RHO) automatically.",
                  MUTED, 11).grid(row=1, column=0, columnspan=3, sticky="w",
                                  padx=20, pady=(0, 14))

        self._cond_entries: dict = {}
        fields = [
            ("mass_kg",      "Rocket mass",  "kg"),
            ("temp_f",       "Temperature",  "°F"),
            ("humidity_pct", "Humidity",     "%"),
            ("pressure_hpa", "Pressure",     "hPa"),
        ]
        for r_idx, (key, label, unit) in enumerate(fields, 2):
            self._lbl(lc_card, label, MUTED, 11).grid(
                row=r_idx, column=0, sticky="w", padx=20, pady=5)
            ent = ctk.CTkEntry(lc_card, height=36, corner_radius=10,
                               fg_color=FIELD, border_width=1, border_color=BORDER,
                               text_color=TEXT, font=ctk.CTkFont(family=MONO, size=11))
            ent.grid(row=r_idx, column=1, sticky="ew", padx=(8, 8), pady=5)
            self._lbl(lc_card, unit, SUBTLE, 10).grid(
                row=r_idx, column=2, sticky="w", padx=(0, 20))
            self._cond_entries[key] = ent

        self._btn(lc_card, "Generate coast table",
                  self._run_coast_table, "primary", 200).grid(
            row=6, column=0, columnspan=3, sticky="ew", padx=20, pady=(12, 20))

        self._load_conditions()

        # Config editor (scrollable)
        cfg_card = self._card(page)
        cfg_card.pack(fill="x", padx=20, pady=(0, 16))
        self._lbl(cfg_card, "config.h editor", TEXT, 17, "bold").pack(
            anchor="w", padx=20, pady=(18, 4))
        self._lbl(cfg_card, "Edit firmware parameters directly from here.",
                  MUTED, 11).pack(anchor="w", padx=20)

        cfg_scroll = ctk.CTkScrollableFrame(
            cfg_card, height=260, fg_color=SURFACE,
            scrollbar_fg_color=SURFACE, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=12)
        cfg_scroll.pack(fill="x", padx=16, pady=(10, 6))
        cfg_scroll.grid_columnconfigure(1, weight=1)
        self._config_scroll = cfg_scroll
        self._config_fields: dict = {}

        cfg_btns = ctk.CTkFrame(cfg_card, fg_color="transparent")
        cfg_btns.pack(anchor="w", padx=20, pady=(4, 16))
        self._btn(cfg_btns, "Reload", self._reload_config_fields, "secondary", 120).pack(
            side="left", padx=(0, 10))
        self._btn(cfg_btns, "Save changes", self._save_config_fields, "primary", 140).pack(
            side="left")

        self._reload_config_fields()

        # Firmware card
        fw_card = self._card(page)
        fw_card.pack(fill="x", padx=20, pady=(0, 16))
        self._lbl(fw_card, "Firmware", TEXT, 17, "bold").pack(
            anchor="w", padx=20, pady=(18, 4))
        self._lbl(fw_card,
                  "Build and flash run in the background — open Details below for live output.",
                  MUTED, 11).pack(anchor="w", padx=20)
        fw_btns = ctk.CTkFrame(fw_card, fg_color="transparent")
        fw_btns.pack(anchor="w", padx=20, pady=(12, 20))
        self._btn(fw_btns, "Build firmware",   self._run_build,           "secondary", 160).pack(side="left", padx=(0, 10))
        self._btn(fw_btns, "Flash to board",   self._run_upload,          "primary",   160).pack(side="left", padx=(0, 10))
        self._btn(fw_btns, "Pre-flight check", self._run_preflight_check, "secondary", 160).pack(side="left")

        self._build_activity_widget(page)

    # ---- Config editor helpers ----
    def _reload_config_fields(self):
        for w in self._config_scroll.winfo_children():
            w.destroy()
        self._config_fields = {}
        if not self.repo_path:
            self._lbl(self._config_scroll, "Set a repo folder first.", MUTED, 11).pack(pady=12)
            return
        cfg_h = os.path.join(self.repo_path, "include", "config.h")
        if not os.path.exists(cfg_h):
            self._lbl(self._config_scroll, f"config.h not found at {cfg_h}", RED, 11).pack(pady=12)
            return
        try:
            import config_editor
            self._config_h_path = cfg_h
            self._current_config = config_editor.ConfigFile(cfg_h)
            for r_idx, field in enumerate(self._current_config.fields):
                color = SUBTLE if field.is_auto_generated else MUTED
                self._lbl(self._config_scroll, field.name, color, 10).grid(
                    row=r_idx, column=0, sticky="w", padx=(12, 8), pady=3)
                var = tk.StringVar(value=field.value)
                ent = ctk.CTkEntry(
                    self._config_scroll, textvariable=var, height=30,
                    corner_radius=8, fg_color=FIELD, border_width=1,
                    border_color=BORDER, text_color=TEXT,
                    font=ctk.CTkFont(family=MONO, size=10), width=120)
                ent.grid(row=r_idx, column=1, sticky="ew", padx=(0, 8), pady=3)
                if field.comment:
                    self._lbl(self._config_scroll, field.comment, SUBTLE, 9).grid(
                        row=r_idx, column=2, sticky="w", padx=(0, 12))
                self._config_fields[field.name] = var
            self.toast("config.h loaded", "info", 1500)
        except Exception as err:
            self._lbl(self._config_scroll, f"Error loading config.h: {err}", RED, 10).pack(pady=12)
            self.toast(f"Could not load config.h: {err}", "error", 0)

    def _save_config_fields(self):
        if not getattr(self, "_current_config", None):
            self.toast("Load config.h first", "warn"); return
        for name, var in self._config_fields.items():
            self._current_config.set_value(name, var.get())
        self._current_config.save()
        self._log_activity(f"Saved {self._config_h_path}")
        self.toast("config.h saved — rebuild + flash to apply", "ok")

    # ---- Pre-flight actions ----
    def _load_conditions(self):
        d = self.cfg.get("last_launch_conditions", {})
        for key, ent in self._cond_entries.items():
            val = d.get(key, "")
            if val:
                ent.delete(0, "end")
                ent.insert(0, str(val))

    def _run_coast_table(self):
        if not self.repo_path:
            self.toast("Set a repo folder first", "warn")
            messagebox.showwarning("No repo", "Choose the repo folder first."); return
        try:
            vals = [float(self._cond_entries[k].get())
                    for k in ("mass_kg", "temp_f", "humidity_pct", "pressure_hpa")]
        except ValueError:
            self.toast("All condition fields must be numbers", "error")
            messagebox.showerror("Invalid", "All launch-condition fields must be numbers."); return
        self.toast("Generating coast table…", "info", 0)
        self._set_activity("Generating coast table…", True)

        def on_line(line):
            self.after(0, lambda l=line: self._log_activity(l))

        def task():
            return coast_table_tool.regenerate(self.repo_path, *vals, on_line=on_line)

        def done(result, err):
            if err:
                self._set_activity("Coast table failed", False)
                self.toast(f"Coast table failed: {err}", "error", 0)
                self._log_activity(f"Error: {err}")
            else:
                self.cfg["last_launch_conditions"] = dict(
                    zip(("mass_kg", "temp_f", "humidity_pct", "pressure_hpa"), vals))
                save_config(self.cfg)
                self._coast_table_cache = None
                self._set_activity("Coast table generated", False)
                self.toast("Coast table generated — rebuild + flash to apply", "ok")

        _run_bg(self, task, done)

    def _run_build(self):
        if not self.repo_path:
            self.toast("Set a repo folder first", "warn"); return
        if not firmware.check_platformio_installed():
            self.toast("PlatformIO not found — install it first", "error")
            messagebox.showerror("PlatformIO", "Install PlatformIO then retry."); return
        self.toast("Building firmware…", "info", 0)
        self._set_activity("Building firmware…", True)
        self._log_activity("$ pio run")

        def on_line(l):
            self.after(0, lambda line=l: self._log_activity(line))

        def on_exit(code):
            def finish():
                if code == 0:
                    self._set_activity("Build succeeded", False)
                    self.toast("Firmware build succeeded", "ok")
                else:
                    self._set_activity(f"Build failed (exit {code})", False)
                    self.toast(f"Build failed — exit code {code}", "error", 0)
                self._log_activity(f"[exited with code {code}]")
            self.after(0, finish)

        firmware.build_firmware(self.repo_path, on_line=on_line, on_exit=on_exit)

    def _run_upload(self):
        if not self.repo_path:
            self.toast("Set a repo folder first", "warn"); return
        if not firmware.check_platformio_installed():
            self.toast("PlatformIO not found — install it first", "error")
            messagebox.showerror("PlatformIO", "Install PlatformIO then retry."); return
        reconnect_port = self._last_port
        if self.link:
            self._log_activity("Closing serial link so PlatformIO can claim the USB port…")
            try:
                self.link.close()
            except Exception:
                pass
            self.link = None
            self._conn_dot.configure(text="●  FLASHING", text_color=AMBER)
            self._conn_hint.configure(text="Port released for upload")
        self.toast("Flashing firmware…", "warn", 0)
        self._set_activity("Flashing firmware…", True)
        self._log_activity("$ pio run -t upload")

        def on_line(l):
            self.after(0, lambda line=l: self._log_activity(line))

        def on_exit(code):
            def finish():
                if code == 0:
                    self._set_activity("Flash succeeded", False)
                    self.toast("Firmware flashed successfully", "ok")
                    if reconnect_port:
                        self._log_activity("Waiting for board to reboot…")
                        self._reconnect_after_upload(reconnect_port)
                else:
                    self._set_activity(f"Flash failed (exit {code})", False)
                    self.toast(f"Flash failed — exit code {code}", "error", 0)
                self._log_activity(f"[exited with code {code}]")
            self.after(0, finish)

        firmware.upload_firmware(self.repo_path, on_line=on_line, on_exit=on_exit)

    def _run_preflight_check(self):
        port = self._last_port or serial_link.find_board()
        if not self.link and not port:
            self.toast("No board found — connect first", "warn")
            messagebox.showinfo("Not connected",
                                "Connect from the Board page first, then retry."); return
        self.toast("Sending INFO to board…", "info", 2000)
        self._set_activity("Pre-flight check…", True)
        self._monitor_paused = True

        if self.link:
            def task():
                return self.link.get_info()
        else:
            def task():
                tmp = serial_link.FlightComputerLink(port)
                try:
                    return tmp, tmp.get_info()
                except Exception:
                    tmp.close()
                    raise

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("Pre-flight check failed", False)
                self.toast(f"Pre-flight check failed: {err}", "error", 0)
                self._log_activity(f"Error: {err}")
            else:
                if isinstance(result, tuple):
                    self.link, info = result
                    self._last_port = port
                else:
                    info = result
                self._set_activity("Pre-flight check passed", False)
                self.toast(f"Board OK — {info}", "ok")
                self._log_activity(f"Storage: {info}")
                self._conn_dot.configure(text="●  CONNECTED", text_color=TEAL)
                self._conn_hint.configure(text=f"Connected on {self._last_port or port}")

        _run_bg(self, task, done)

    # ================================================================= GROUND TEST PAGE
    def _build_ground_test_page(self):
        page = ctk.CTkScrollableFrame(
            self.content, fg_color=BG,
            scrollbar_fg_color=BG, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        self._pages["Ground test"] = page

        self._section_title(page, "HARDWARE", "Ground test",
                            "Arm a shake-triggered sensor recording and airbrake sweep.")

        gt_card = self._card(page)
        gt_card.pack(fill="x", padx=20, pady=(0, 16))
        self._lbl(gt_card, "Airbrake ground test", TEXT, 17, "bold").pack(
            anchor="w", padx=20, pady=(18, 4))
        self._lbl(gt_card,
                  "Arms a shake-triggered 15 s sensor log and slow close → open → close sweep.\n"
                  "Keep clear of the mechanism during the test.",
                  MUTED, 11, wraplength=860, justify="left").pack(anchor="w", padx=20)
        gt_btns = ctk.CTkFrame(gt_card, fg_color="transparent")
        gt_btns.pack(anchor="w", padx=20, pady=(12, 8))
        self._btn(gt_btns, "Arm ground test",  self._gt_start,  "primary",   160).pack(side="left", padx=(0, 10))
        self._btn(gt_btns, "Abort / close",    self._gt_abort,  "danger",    160).pack(side="left", padx=(0, 10))
        self._btn(gt_btns, "Check status",     self._gt_status, "secondary", 140).pack(side="left", padx=(0, 10))
        self._btn(gt_btns, "Check DPS368",     self._gt_baro,   "quiet",     130).pack(side="left")

        self._gt_status_lbl = self._lbl(gt_card, "Connect to arm a test.", MUTED, 11)
        self._gt_status_lbl.pack(anchor="w", padx=20, pady=(4, 18))

        self._build_monitor_widget(page)
        self._build_activity_widget(page)

    # ---- Ground test actions ----
    def _gt_start(self):
        if not self.link:
            self.toast("Not connected", "warn")
            messagebox.showwarning("Not connected", "Connect first."); return
        if not messagebox.askyesno("Arm ground test",
                                   "Keep clear of the airbrakes.\n"
                                   "Shake to trigger. Continues for 15 s then sweeps brakes.\n\n"
                                   "Continue?"):
            return
        self.toast("Arming ground test…", "warn", 0)
        self._gt_command(self.link.ground_test_start, "Arming ground test")

    def _gt_abort(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        self.toast("Aborting ground test…", "warn", 0)
        self._gt_command(self.link.ground_test_abort, "Aborting ground test")

    def _gt_status(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        self.toast("Checking ground test status…", "info", 2000)
        self._gt_command(self.link.ground_test_status, "Checking status")

    def _gt_baro(self):
        if not self.link:
            self.toast("Not connected", "warn"); return
        self.toast("Checking DPS368…", "info", 2000)
        self._set_activity("Checking DPS368…", True)
        self._monitor_paused = True

        def task():
            return self.link.baro_status()

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._set_activity("DPS368 check failed", False)
                self._gt_status_lbl.configure(text=str(err), text_color=RED)
                self.toast(f"DPS368 failed: {err}", "error", 0)
            else:
                self._set_activity("DPS368 OK", False)
                self._gt_status_lbl.configure(text=str(result), text_color=TEAL)
                self._append_monitor(result, "state")
                self.toast(f"DPS368: {result}", "ok")

        _run_bg(self, task, done)

    def _gt_command(self, cmd, label):
        self._monitor_paused = True
        self._gt_status_lbl.configure(text=f"{label}…", text_color=AMBER)
        self._set_activity(label, True)

        def task():
            return cmd()

        def done(result, err):
            self._monitor_paused = False
            if err:
                self._gt_status_lbl.configure(text=str(err), text_color=RED)
                self._set_activity(f"{label} failed", False)
                self.toast(f"{label} failed: {err}", "error", 0)
            else:
                self._gt_status_lbl.configure(text=str(result), text_color=TEAL)
                self._set_activity(f"{label} done", False)
                self.toast(f"{label} complete", "ok")
                self._log_activity(str(result))

        _run_bg(self, task, done)

    # ================================================================= HISTORY PAGE
    def _build_history_page(self):
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=0)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(0, weight=1)
        self._pages["History"] = page

        # Left panel
        left = ctk.CTkScrollableFrame(
            page, width=320, fg_color=SIDEBAR,
            scrollbar_fg_color=SIDEBAR, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)

        lhdr = ctk.CTkFrame(left, fg_color="transparent")
        lhdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(20, 8))
        self._lbl(lhdr, "SAVED FLIGHTS", TEAL, 9, "bold").pack(side="left")
        self._btn(lhdr, "Refresh", self._refresh_history_list, "quiet", 76, 28).pack(
            side="right")

        self._hist_list_inner = ctk.CTkFrame(left, fg_color="transparent")
        self._hist_list_inner.grid(row=1, column=0, sticky="ew")

        del_row = ctk.CTkFrame(left, fg_color="transparent")
        del_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(12, 6))
        self._btn(del_row, "Delete all local", self._delete_all_local, "danger", 140, 32).pack(
            anchor="w")

        ddir_row = ctk.CTkFrame(left, fg_color="transparent")
        ddir_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 20))
        self._btn(ddir_row, "Change data folder", self._choose_data_dir, "quiet", 160, 30).pack(
            anchor="w")

        # Right panel
        right = ctk.CTkFrame(page, fg_color=BG, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        rh = ctk.CTkFrame(right, fg_color=BG)
        rh.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))
        rh.grid_columnconfigure(0, weight=1)
        self._hist_title = self._lbl(rh, "Select a flight to inspect it", TEXT, 20, "bold")
        self._hist_title.grid(row=0, column=0, sticky="w")

        # Tab bar
        tab_bar = ctk.CTkFrame(rh, fg_color=SURFACE2, corner_radius=10)
        tab_bar.grid(row=0, column=1, sticky="e")
        self._hist_tab_btns = {}
        for tname in ("Stats", "Plots", "Data table"):
            tb = ctk.CTkButton(
                tab_bar, text=tname, width=100, height=30, corner_radius=8,
                fg_color=TEAL_DIM if tname == "Plots" else "transparent",
                hover_color=FIELD,
                text_color=TEXT if tname == "Plots" else MUTED,
                font=ctk.CTkFont(family=SANS, size=11, weight="bold"),
                command=lambda n=tname: self._switch_hist_tab(n))
            tb.pack(side="left", padx=3, pady=3)
            self._hist_tab_btns[tname] = tb

        self._hist_content = ctk.CTkFrame(right, fg_color=BG, corner_radius=0)
        self._hist_content.grid(row=1, column=0, sticky="nsew")
        self._hist_content.grid_columnconfigure(0, weight=1)
        self._hist_content.grid_rowconfigure(0, weight=1)

        self._build_hist_stats_panel()
        self._build_hist_plots_panel()
        self._build_hist_table_panel()
        self._switch_hist_tab("Plots")
        self._refresh_history_list()

    # ---- History sub-panels ----
    def _build_hist_stats_panel(self):
        self._hist_stats_panel = ctk.CTkScrollableFrame(
            self._hist_content, fg_color=BG,
            scrollbar_fg_color=BG, scrollbar_button_color=FIELD,
            scrollbar_button_hover_color=HOVER, corner_radius=0)
        self._hist_stats_panel.grid_columnconfigure(0, weight=1)
        self._hist_stats_card = self._card(self._hist_stats_panel)
        self._hist_stats_card.pack(fill="x", padx=20, pady=20)
        self._lbl(self._hist_stats_card, "Select a flight to view stats",
                  MUTED, 13).pack(padx=24, pady=40)

    def _build_hist_plots_panel(self):
        self._hist_plots_panel = ctk.CTkFrame(
            self._hist_content, fg_color=BG, corner_radius=0)
        self._hist_plots_panel.grid_columnconfigure(0, weight=1)
        self._hist_plots_panel.grid_rowconfigure(1, weight=1)

        # Plot selector chip bar
        sel_row = ctk.CTkFrame(self._hist_plots_panel, fg_color=SURFACE2, corner_radius=10)
        sel_row.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        self._lbl(sel_row, "Plot:", MUTED, 11).pack(side="left", padx=(14, 8), pady=8)
        self._plot_choice = tk.StringVar(value=plotting.ALL_PLOTS[0][0])
        self._plot_btns = {}
        for pname, _ in plotting.ALL_PLOTS:
            pb = ctk.CTkButton(
                sel_row, text=pname, height=28, width=0, corner_radius=8,
                fg_color=TEAL_DIM if pname == plotting.ALL_PLOTS[0][0] else "transparent",
                hover_color=HOVER,
                text_color=TEXT if pname == plotting.ALL_PLOTS[0][0] else MUTED,
                font=ctk.CTkFont(family=SANS, size=10, weight="bold"),
                command=lambda n=pname: self._select_plot(n))
            pb.pack(side="left", padx=3, pady=6)
            self._plot_btns[pname] = pb

        # Canvas host
        self._plot_host = ctk.CTkFrame(
            self._hist_plots_panel, fg_color=SURFACE, corner_radius=16)
        self._plot_host.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        self._plot_host.grid_columnconfigure(0, weight=1)
        self._plot_host.grid_rowconfigure(0, weight=1)
        self._lbl(self._plot_host, "Select a flight from the left to plot it",
                  MUTED, 13).grid(row=0, column=0)
        self._plot_canvas_widget  = None
        self._plot_toolbar_widget = None

    def _build_hist_table_panel(self):
        self._hist_table_panel = ctk.CTkFrame(
            self._hist_content, fg_color=BG, corner_radius=0)
        self._hist_table_panel.grid_columnconfigure(0, weight=1)
        self._hist_table_panel.grid_rowconfigure(1, weight=1)

        ctrl = ctk.CTkFrame(self._hist_table_panel, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        self._table_info_lbl = self._lbl(ctrl, "Select a flight to view its data", MUTED, 11)
        self._table_info_lbl.pack(side="left")
        self._btn(ctrl, "Export CSV", self._export_csv, "secondary", 110, 30).pack(
            side="right")

        table_host = ctk.CTkFrame(
            self._hist_table_panel, fg_color=SURFACE, corner_radius=16)
        table_host.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        table_host.grid_columnconfigure(0, weight=1)
        table_host.grid_rowconfigure(0, weight=1)

        self._table_canvas = tk.Canvas(table_host, bg=SURFACE, highlightthickness=0)
        vsb = ctk.CTkScrollbar(table_host, orientation="vertical",
                                command=self._table_canvas.yview,
                                fg_color=SURFACE, button_color=FIELD,
                                button_hover_color=HOVER)
        hsb = ctk.CTkScrollbar(table_host, orientation="horizontal",
                                command=self._table_canvas.xview,
                                fg_color=SURFACE, button_color=FIELD,
                                button_hover_color=HOVER)
        self._table_canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._table_canvas.grid(row=0, column=0, sticky="nsew")

        self._table_inner = tk.Frame(self._table_canvas, bg=SURFACE)
        self._table_canvas.create_window((0, 0), window=self._table_inner, anchor="nw")
        self._table_inner.bind(
            "<Configure>",
            lambda e: self._table_canvas.configure(
                scrollregion=self._table_canvas.bbox("all")))

    def _switch_hist_tab(self, name: str):
        panels = {
            "Stats":      self._hist_stats_panel,
            "Plots":      self._hist_plots_panel,
            "Data table": self._hist_table_panel,
        }
        for pname, pframe in panels.items():
            if pname == name:
                pframe.grid(row=0, column=0, sticky="nsew")
            else:
                pframe.grid_remove()
        for tname, tbtn in self._hist_tab_btns.items():
            active = tname == name
            tbtn.configure(
                fg_color=TEAL_DIM if active else "transparent",
                text_color=TEXT if active else MUTED)

    # ---- History list ----
    def _refresh_history_list(self):
        self._history_entries = self.store.list_flights()
        for w in self._hist_list_inner.winfo_children():
            w.destroy()
        if not self._history_entries:
            self._lbl(self._hist_list_inner, "No saved flights yet", MUTED, 12).pack(
                anchor="center", pady=8)
            self._lbl(self._hist_list_inner,
                      "Download a flight from the\nBoard page first.",
                      SUBTLE, 10, justify="center").pack(anchor="center")
            return

        flights = [e for e in self._history_entries if e.get("category") == "flight"]
        tests   = [e for e in self._history_entries if e.get("category") == "ground_test"]
        others  = [e for e in self._history_entries
                   if e not in flights and e not in tests]

        for section_label, entries, color in (
            ("Flights",      flights, TEAL),
            ("Ground tests", tests,   AMBER),
            ("Other",        others,  BLUE),
        ):
            if not entries:
                continue
            self._lbl(self._hist_list_inner, section_label.upper(),
                      SUBTLE, 9, "bold").pack(anchor="w", padx=14, pady=(14, 4))
            for entry in entries:
                self._build_history_row(entry, color)

    def _build_history_row(self, entry: dict, color=TEAL):
        folder = entry.get("folder", "")
        is_sel = (self._selected_history_entry is not None and
                  self._selected_history_entry.get("folder") == folder)

        row = ctk.CTkFrame(
            self._hist_list_inner,
            fg_color=HOVER if is_sel else FIELD,
            border_color=TEAL_MID if is_sel else BORDER,
            border_width=1 if is_sel else 0,
            corner_radius=12)
        row.pack(fill="x", padx=10, pady=3)

        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))

        num = entry.get("flight_num", "?")
        badge = f"FLIGHT {num:04d}" if isinstance(num, int) else f"FLIGHT {num}"
        ctk.CTkLabel(top, text=badge, text_color=color,
                     fg_color=TEAL_DIM if color == TEAL else AMBER_DIM,
                     corner_radius=8, padx=8, pady=3,
                     font=ctk.CTkFont(family=SANS, size=9, weight="bold")).pack(side="left")

        dur = entry.get("duration_s", 0)
        alt = entry.get("max_altitude_m")
        alt_str = f"{alt:.0f} m" if alt is not None else "?"
        self._lbl(top, f"{dur:.1f}s  ·  {alt_str}", MUTED, 9).pack(side="right", padx=(0, 4))

        ts = entry.get("downloaded_at", "")
        display_ts = ts[:19].replace("_", " ") if ts else "Unknown"
        self._lbl(row, display_ts, SUBTLE, 9).pack(anchor="w", padx=10, pady=(0, 6))

        # Per-row delete
        del_btn = self._btn(row, "Delete", lambda e=entry: self._delete_local(e),
                            "danger", 70, 26)
        del_btn.place(relx=1.0, x=-8, rely=0.0, y=6, anchor="ne")

        # Click anywhere on the row to select it
        for widget in [row, top, del_btn]:
            try:
                widget.bind("<Button-1>", lambda ev, e=entry: self._select_history_entry(e))
            except Exception:
                pass
        row.bind("<Enter>", lambda ev, r=row: r.configure(fg_color=HOVER))
        row.bind("<Leave>", lambda ev, r=row, e=entry:
                 r.configure(fg_color=HOVER if (
                     self._selected_history_entry is not None and
                     self._selected_history_entry.get("folder") == e.get("folder")
                 ) else FIELD))

    def _select_history_entry(self, entry: dict):
        self._selected_history_entry = entry
        self._refresh_history_list()
        num = entry.get("flight_num", "?")
        cat = entry.get("category", "flight").replace("_", " ").title()
        self._hist_title.configure(text=f"{cat}  {num}")
        self.toast(f"Viewing {cat} {num}", "info", 1500)
        self._render_stats(entry)
        self._render_active_plot()
        self._render_table(entry)

    def _delete_local(self, entry: dict):
        folder = entry.get("folder", "")
        if messagebox.askyesno("Delete local",
                               f"Delete {folder} from this computer?\n"
                               "(This does not affect the board.)"):
            self.store.delete_local(folder)
            if (self._selected_history_entry is not None and
                    self._selected_history_entry.get("folder") == folder):
                self._selected_history_entry = None
            self._refresh_history_list()
            self.toast(f"{folder} deleted locally", "ok")

    def _delete_all_local(self):
        if messagebox.askyesno("Delete all local data",
                               "Delete every saved flight and ground test from this computer?\n"
                               "This does NOT affect the board."):
            self.store.delete_all_local()
            self._selected_history_entry = None
            self._refresh_history_list()
            self.toast("All local flight data deleted", "ok")

    # ---- Stats ----
    def _render_stats(self, entry: dict):
        for w in self._hist_stats_card.winfo_children():
            w.destroy()
        self._lbl(self._hist_stats_card, "Flight summary", TEXT, 16, "bold").pack(
            anchor="w", padx=22, pady=(18, 10))

        stats = [
            ("Flight number", str(entry.get("flight_num", "?"))),
            ("Downloaded",    entry.get("downloaded_at", "?")[:19].replace("_", " ")),
            ("Duration",      f"{entry.get('duration_s', 0):.2f} s"),
            ("Records",       str(entry.get("num_records", "?"))),
            ("Max altitude",  (f"{entry['max_altitude_m']:.1f} m"
                               if entry.get("max_altitude_m") is not None else "N/A")),
            ("Category",      entry.get("category", "flight").replace("_", " ").title()),
            ("Folder",        entry.get("folder", "?")),
        ]
        try:
            df = pd.read_csv(entry["csv_path"])
            stats.insert(5, ("Max velocity", f"{df['velocity_ms'].max():.1f} m/s"))
        except Exception:
            pass

        for label, val in stats:
            r = ctk.CTkFrame(self._hist_stats_card, fg_color=FIELD, corner_radius=10)
            r.pack(fill="x", padx=16, pady=3)
            self._lbl(r, label, MUTED, 11).pack(side="left", padx=14, pady=8)
            self._lbl(r, val,   TEXT,  11, "bold").pack(side="right", padx=14, pady=8)

        ctk.CTkFrame(self._hist_stats_card, height=1, fg_color=BORDER).pack(
            fill="x", padx=16, pady=8)
        self._lbl(self._hist_stats_card,
                  f"CSV path: {entry.get('csv_path', '?')}",
                  SUBTLE, 9).pack(anchor="w", padx=22, pady=(0, 16))

    # ---- Plots ----
    def _select_plot(self, name: str):
        self._plot_choice.set(name)
        for pname, pbtn in self._plot_btns.items():
            active = pname == name
            pbtn.configure(
                fg_color=TEAL_DIM if active else "transparent",
                text_color=TEXT if active else MUTED)
        self._render_active_plot()

    def _render_active_plot(self):
        if self._selected_history_entry is None:
            return
        entry = self._selected_history_entry
        try:
            df = pd.read_csv(entry["csv_path"])
        except Exception as err:
            self.toast(f"Could not load CSV: {err}", "error", 0); return

        name = self._plot_choice.get()
        plot_fn = dict(plotting.ALL_PLOTS).get(name)
        if plot_fn is None:
            return

        if plot_fn is plotting.plot_coast_predicted_vs_actual:
            cached = self._get_coast_table()
            fig = (plot_fn(df, *cached) if cached else plot_fn(df))
        else:
            fig = plot_fn(df)

        # Theme the figure to match the dark UI
        plot_bg = "#0e1820"
        ax_bg   = "#111d2a"
        fig.patch.set_facecolor(plot_bg)
        for ax in fig.get_axes():
            ax.set_facecolor(ax_bg)
            ax.tick_params(colors=MUTED, labelsize=9)
            ax.xaxis.label.set_color(MUTED)
            ax.yaxis.label.set_color(MUTED)
            ax.title.set_color(TEXT)
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            ax.grid(True, color=BORDER, alpha=0.5)
        fig.tight_layout(pad=2.0)

        # Clear previous canvas + toolbar
        if self._plot_canvas_widget:
            try:
                self._plot_canvas_widget.get_tk_widget().destroy()
            except Exception:
                pass
        if self._plot_toolbar_widget:
            try:
                self._plot_toolbar_widget.destroy()
            except Exception:
                pass
        for w in self._plot_host.winfo_children():
            w.destroy()

        # Embed canvas
        canvas = FigureCanvasTkAgg(fig, master=self._plot_host)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=(4, 0))

        # Embed NavigationToolbar2Tk (zoom / pan / save built-in)
        tb_host = tk.Frame(self._plot_host, bg=ax_bg)
        tb_host.pack(fill="x", padx=4, pady=(0, 4))
        toolbar = NavigationToolbar2Tk(canvas, tb_host)
        toolbar.configure(background=ax_bg)
        for child in toolbar.winfo_children():
            try:
                child.configure(background=ax_bg, foreground=TEXT)
            except Exception:
                pass
        toolbar.update()

        self._plot_canvas_widget  = canvas
        self._plot_toolbar_widget = toolbar
        plt.close(fig)

    # ---- Data table ----
    def _render_table(self, entry: dict):
        for w in self._table_inner.winfo_children():
            w.destroy()
        try:
            with open(entry["csv_path"], newline="", encoding="utf-8") as f:
                rows = list(_csv.reader(f))
        except Exception as err:
            self.toast(f"Could not load CSV: {err}", "error", 0); return
        if not rows:
            return

        n_data = len(rows) - 1
        n_cols = len(rows[0]) if rows else 0
        self._table_info_lbl.configure(
            text=f"{n_data} records  ·  {n_cols} columns")

        HDR_BG = SURFACE2
        HDR_FG = TEAL
        ROW_BG = SURFACE
        ALT_BG = CARD
        COL_W  = 11          # chars

        for c, col in enumerate(rows[0]):
            tk.Label(self._table_inner, text=col, anchor="w",
                     width=COL_W, bg=HDR_BG, fg=HDR_FG,
                     font=(MONO, 9, "bold"),
                     borderwidth=0, padx=4, pady=4).grid(
                row=0, column=c, sticky="ew", padx=1, pady=1)

        MAX_ROWS = 2000
        for r, data_row in enumerate(rows[1:MAX_ROWS + 1], 1):
            bg = ALT_BG if r % 2 == 0 else ROW_BG
            for c, val in enumerate(data_row):
                tk.Label(self._table_inner, text=val, anchor="e",
                         width=COL_W, bg=bg, fg=TEXT,
                         font=(MONO, 9),
                         borderwidth=0, padx=4, pady=2).grid(
                    row=r, column=c, sticky="ew", padx=1, pady=0)

        if n_data > MAX_ROWS:
            tk.Label(self._table_inner,
                     text=f"Showing first {MAX_ROWS} of {n_data} rows",
                     bg=SURFACE, fg=MUTED,
                     font=(SANS, 9)).grid(
                row=MAX_ROWS + 1, column=0, columnspan=n_cols, pady=8, sticky="w")

        self._table_canvas.update_idletasks()
        self._table_canvas.configure(
            scrollregion=self._table_canvas.bbox("all"))

    def _export_csv(self):
        if self._selected_history_entry is None:
            self.toast("Select a flight first", "warn"); return
        src = self._selected_history_entry.get("csv_path", "")
        if not os.path.isfile(src):
            self.toast("CSV file not found", "error"); return
        dest = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=os.path.basename(src))
        if dest:
            shutil.copy2(src, dest)
            self.toast(f"Exported to {dest}", "ok")

    # ---- Coast table cache ----
    def _get_coast_table(self):
        if self._coast_table_cache is not None:
            return self._coast_table_cache
        if not self.repo_path:
            return None
        try:
            self._coast_table_cache = coast_lookup.load_coast_table(self.repo_path)
        except Exception as err:
            self._log_activity(f"Could not load coast table for plotting: {err}")
            self._coast_table_cache = None
        return self._coast_table_cache


if __name__ == "__main__":
    App().mainloop()
