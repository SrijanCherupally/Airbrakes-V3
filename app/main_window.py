"""
Airbrakes V3 Ground Station — a single GUI for pre-flight config/flash and
post-flight data download + plotting, so you never need VS Code or a
terminal for day-to-day use.

Launch via the top-level "Airbrakes App" launcher one directory up, or
directly with:  python main_window.py
(See app/README_APP.md for how to package this into a real double-click app.)
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from ttkbootstrap.constants import PRIMARY, SUCCESS, DANGER, INFO, SECONDARY, WARNING

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import config_editor
import coast_lookup
import coast_table_tool
import data_store
import firmware
import plotting
import serial_link

THEME = "minty"  # fresh, soft green-accented theme for a clean UI
# Font and color tokens used across the UI for a consistent look
FONT_HEADER = ("Segoe UI", 16, "bold")
FONT_NORMAL = ("Segoe UI", 10)
CONSOLE_BG = "#f6f9f8"
CONSOLE_FG = "#0b3d2e"
LIST_BG = "#eaf3ee"
LIST_FG = "#0b2b1f"
LIST_SELECT_BG = "#78c2a4"

APP_DIR = os.path.join(os.path.expanduser("~"), ".airbrakes_ground_station")
APP_CONFIG_PATH = os.path.join(APP_DIR, "app_config.json")


def load_app_config():
    if os.path.exists(APP_CONFIG_PATH):
        with open(APP_CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_app_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(APP_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def run_in_background(root, fn, on_done):
    """Runs fn() in a worker thread; on_done(result, error) is called back
    on the Tk main thread once it finishes."""
    q = queue.Queue()

    def worker():
        try:
            result = fn()
            q.put((result, None))
        except Exception as e:  # noqa: BLE001 - surface any error to the GUI
            q.put((None, e))

    def poll():
        try:
            result, err = q.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        on_done(result, err)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)


class App(ttk.Window):
    def __init__(self):
        super().__init__(themename=THEME)
        self.title("Airbrakes V3 Ground Station")
        self.geometry("1200x780")
        self.minsize(1000, 650)

        self.app_cfg = load_app_config()
        self.repo_path = self.app_cfg.get("repo_path")
        self.data_dir = self.app_cfg.get(
            "data_dir", os.path.join(APP_DIR, "flight_data"))
        self.store = data_store.DataStore(self.data_dir)

        self.link = None          # active serial_link.FlightComputerLink
        self.live_process = None  # active firmware.LiveProcess

        self._build_menu()
        self._build_header()
        self._build_layout()

        if not self.repo_path or not os.path.isdir(self.repo_path):
            self.after(200, self._first_run_prompt)

    def _build_header(self):
        # Prominent, well-spaced header with a compact connection indicator
        header = ttk.Frame(self, bootstyle="primary", padding=(20, 12))
        header.pack(fill="x")
        ttk.Label(header, text="🚀 Airbrakes V3", font=FONT_HEADER,
                  bootstyle="inverse-primary").pack(side="left")
        ttk.Label(header, text="Ground Station", font=("", 12),
                  bootstyle="inverse-primary", foreground="#0b3d2e").pack(side="left", padx=(8, 0))
        self.conn_dot = ttk.Label(header, text="●  Not connected",
                                   bootstyle="inverse-primary", foreground="#e05260")
        self.conn_dot.pack(side="right")

    # ---------- setup / chrome ----------

    def _build_menu(self):
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Set repo folder...", command=self._choose_repo)
        filemenu.add_command(label="Set data folder...", command=self._choose_data_dir)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        self.config(menu=menubar)

    def _first_run_prompt(self):
        messagebox.showinfo(
            "First-time setup",
            "Point this app at your local clone of the Airbrakes-V3 repo "
            "(the folder containing platformio.ini).")
        self._choose_repo()

    def _choose_repo(self):
        path = filedialog.askdirectory(title="Select your Airbrakes-V3 repo folder")
        if path:
            self.repo_path = path
            self.app_cfg["repo_path"] = path
            save_app_config(self.app_cfg)
            self._reload_config_tab()

    def _choose_data_dir(self):
        path = filedialog.askdirectory(title="Select where to store flight data")
        if path:
            self.data_dir = path
            self.app_cfg["data_dir"] = path
            save_app_config(self.app_cfg)
            self.store = data_store.DataStore(self.data_dir)
            self._refresh_history()

    def _build_layout(self):
        nb = ttk.Notebook(self, bootstyle=PRIMARY)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 10))

        self.tab_preflight = ttk.Frame(nb)
        self.tab_postflight = ttk.Frame(nb)
        self.tab_history = ttk.Frame(nb)
        nb.add(self.tab_preflight, text="Pre-Flight")
        nb.add(self.tab_postflight, text="Post-Flight / Download")
        nb.add(self.tab_history, text="History & Plots")

        self._build_preflight_tab()
        self._build_postflight_tab()
        self._build_history_tab()

    # ---------- Pre-Flight tab ----------

    def _build_preflight_tab(self):
        frame = self.tab_preflight
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=8, pady=4)
        ttk.Label(top, text="Repo:").pack(side="left")
        self.repo_label = ttk.Label(top, text=self.repo_path or "(not set)")
        self.repo_label.pack(side="left", padx=4)
        ttk.Button(top, text="Change...", command=self._choose_repo).pack(side="left")

        body = ttk.Panedwindow(frame, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # Left: config.h editor
        left = ttk.Frame(body)
        body.add(left, weight=1)
        ttk.Label(left, text="Config (include/config.h)",
                  font=("", 11, "bold")).pack(anchor="w")
        self.config_canvas = tk.Canvas(left, borderwidth=0)
        config_scroll = ttk.Scrollbar(left, orient="vertical",
                                       command=self.config_canvas.yview)
        self.config_form = ttk.Frame(self.config_canvas)
        self.config_form.bind(
            "<Configure>",
            lambda e: self.config_canvas.configure(
                scrollregion=self.config_canvas.bbox("all")))
        self.config_canvas.create_window((0, 0), window=self.config_form, anchor="nw")
        self.config_canvas.configure(yscrollcommand=config_scroll.set)
        self.config_canvas.pack(side="left", fill="both", expand=True)
        config_scroll.pack(side="right", fill="y")

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Reload", command=self._reload_config_tab,
                   bootstyle=SECONDARY).pack(side="left")
        ttk.Button(btns, text="Save changes", command=self._save_config,
                   bootstyle=PRIMARY).pack(side="left", padx=4)

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(left, text="Launch conditions -> coast table",
                  font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(left, text="Updates coast_table.py, coast_table.h, and "
                              "config.h's MASS/RHO automatically.",
                  foreground="gray", wraplength=320, justify="left").pack(anchor="w")

        cond_form = ttk.Frame(left)
        cond_form.pack(fill="x", pady=4)
        self.cond_vars = {
            "mass_kg": tk.StringVar(),
            "temp_f": tk.StringVar(),
            "humidity_pct": tk.StringVar(),
            "pressure_hpa": tk.StringVar(),
        }
        labels = {
            "mass_kg": "Rocket mass (kg)",
            "temp_f": "Temperature (°F)",
            "humidity_pct": "Humidity (%)",
            "pressure_hpa": "Pressure (hPa)",
        }
        for key in ("mass_kg", "temp_f", "humidity_pct", "pressure_hpa"):
            row = ttk.Frame(cond_form)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=labels[key], width=20, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=self.cond_vars[key], width=10).pack(side="left")

        ttk.Button(left, text="Regenerate coast table",
                   command=self._run_coast_table, bootstyle=INFO).pack(anchor="w", pady=4)

        # Right: build/flash console
        right = ttk.Frame(body)
        body.add(right, weight=1)
        ttk.Label(right, text="Build / Flash / Console",
                  font=("", 11, "bold")).pack(anchor="w")

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=4)
        ttk.Button(actions, text="Build", command=self._run_build,
                   bootstyle=SECONDARY).pack(side="left")
        ttk.Button(actions, text="Flash to board", command=self._run_upload,
                   bootstyle=WARNING).pack(side="left", padx=4)
        ttk.Button(actions, text="Pre-flight check (INFO)",
                   command=self._run_preflight_check, bootstyle=INFO).pack(side="left", padx=4)

        # Console area with a slim progress bar, status line, and a clearable log
        console_frame = ttk.Frame(right, bootstyle="secondary", padding=6)
        console_frame.pack(fill="both", expand=True, pady=4)

        self.progress = ttk.Progressbar(console_frame, mode="indeterminate", bootstyle="info")
        self.progress.pack(fill="x", pady=(0, 6))

        self.console_status = ttk.Label(console_frame, text="Idle", font=("", 10), foreground="#0b3d2e")
        self.console_status.pack(anchor="w", pady=(0, 6))

        self.console = tk.Text(console_frame, height=15, bg=CONSOLE_BG, fg=CONSOLE_FG,
                                insertbackground=CONSOLE_FG, relief="flat",
                                font=("Consolas", 10) if os.name == "nt" else ("Menlo", 11),
                                padx=8, pady=6, borderwidth=0, highlightthickness=1,
                                highlightbackground="#d1e7df")
        self.console.pack(fill="both", expand=True)

        btn_row = ttk.Frame(console_frame)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="Clear", command=lambda: self.console.delete("1.0", "end"), bootstyle=SECONDARY).pack(side="left")
        self.console_input = ttk.Entry(btn_row)
        self.console_input.pack(side="left", fill="x", expand=True, padx=6)
        self.console_input.bind("<Return>", self._send_console_input)
        ttk.Button(btn_row, text="Send", command=self._send_console_input, bootstyle=PRIMARY).pack(side="left")

        self._config_fields_widgets = {}
        self._reload_config_tab()

    def _log(self, text):
        self.console.insert("end", text + "\n")
        self.console.see("end")

    def _start_progress(self, message="Working..."):
        try:
            self.progress.start(10)
            self.console_status.config(text=message)
        except Exception:
            pass

    def _stop_progress(self, final_message="Idle"):
        try:
            self.progress.stop()
            self.console_status.config(text=final_message)
        except Exception:
            pass

    def _send_console_input(self, event=None):
        text = self.console_input.get()
        self.console_input.delete(0, "end")
        if self.live_process and self.live_process.is_running():
            self.live_process.send_input(text)
            self._log("> " + text)
        else:
            self._log("(no running process to send input to)")

    def _reload_config_tab(self):
        for child in self.config_form.winfo_children():
            child.destroy()
        self._config_fields_widgets = {}

        if not self.repo_path:
            ttk.Label(self.config_form, text="Set a repo folder first.").pack()
            return
        config_h = os.path.join(self.repo_path, "include", "config.h")
        if not os.path.exists(config_h):
            ttk.Label(self.config_form,
                      text=f"Couldn't find {config_h}").pack(anchor="w")
            return

        self.config_h_path = config_h
        self.current_config = config_editor.ConfigFile(config_h)
        for field in self.current_config.fields:
            row = ttk.Frame(self.config_form)
            row.pack(fill="x", pady=1)
            name_label = ttk.Label(row, text=field.name, width=24, anchor="w")
            if field.is_auto_generated:
                name_label.configure(foreground="gray")
            name_label.pack(side="left")
            var = tk.StringVar(value=field.value)
            entry = ttk.Entry(row, textvariable=var, width=14)
            entry.pack(side="left", padx=4)
            comment = field.comment
            if field.is_auto_generated:
                comment += "  (set via 'Regenerate coast table' below, not by hand)"
            if comment:
                ttk.Label(row, text=comment, foreground="gray").pack(side="left")
            self._config_fields_widgets[field.name] = var

        try:
            saved = self.app_cfg.get("last_launch_conditions")
            if saved:
                defaults = saved
            else:
                defaults = coast_table_tool.current_defaults(self.repo_path)
            self.cond_vars["mass_kg"].set(defaults["mass_kg"])
            self.cond_vars["temp_f"].set(defaults["temp_f"])
            self.cond_vars["humidity_pct"].set(defaults["humidity_pct"])
            self.cond_vars["pressure_hpa"].set(defaults["pressure_hpa"])
        except Exception as e:
            self._log(f"Couldn't read current launch conditions: {e}")

    def _save_config(self):
        if not getattr(self, "current_config", None):
            return
        for name, var in self._config_fields_widgets.items():
            self.current_config.set_value(name, var.get())
        self.current_config.save()
        self._log(f"Saved {self.config_h_path}")
        messagebox.showinfo("Saved", "config.h updated. Rebuild + flash to apply.")

    def _run_coast_table(self):
        if not self.repo_path:
            return
        try:
            mass_kg = float(self.cond_vars["mass_kg"].get())
            temp_f = float(self.cond_vars["temp_f"].get())
            humidity_pct = float(self.cond_vars["humidity_pct"].get())
            pressure_hpa = float(self.cond_vars["pressure_hpa"].get())
        except ValueError:
            messagebox.showerror("Invalid input", "Mass/temperature/humidity/pressure "
                                                    "must all be numbers.")
            return

        self._log(f"Regenerating coast table: mass={mass_kg} kg, temp={temp_f}F, "
                   f"humidity={humidity_pct}%, pressure={pressure_hpa} hPa ...")
        self._start_progress("Regenerating coast table...")

        def on_line_cb(line):
            # show detailed running status and keep the console log updated
            self.after(0, lambda: (self._log(line), self.console_status.config(text=line[:200])))

        def task():
            return coast_table_tool.regenerate(
                self.repo_path, mass_kg, temp_f, humidity_pct, pressure_hpa,
                on_line=on_line_cb)

        def done(result, err):
            if err:
                self._log(f"Coast table generation failed: {err}")
                self._stop_progress("Coast table failed")
            else:
                self.app_cfg["last_launch_conditions"] = {
                    "mass_kg": mass_kg, "temp_f": temp_f,
                    "humidity_pct": humidity_pct, "pressure_hpa": pressure_hpa,
                }
                save_app_config(self.app_cfg)
                self._coast_table_cache = None  # force reload on next plot
                self._reload_config_tab()  # MASS/RHO in config.h just changed
                self._stop_progress("Coast table regenerated")

        run_in_background(self, task, done)

    def _run_build(self):
        if not self.repo_path:
            return
        if not firmware.check_platformio_installed():
            self._log("PlatformIO CLI ('pio') not found. Install once with:\n"
                       "    pip install platformio\nthen retry.")
            return
        self._log("$ pio run")
        self._start_progress("Building firmware...")

        def on_line(l):
            # update the console and a short status line so the user sees what's happening
            self.after(0, lambda: (self._log(l), self.console_status.config(text=l[:200])))

        def on_exit(code):
            def finish():
                self._log(f"[build exited with code {code}]")
                self._stop_progress("Build finished" if code == 0 else f"Build failed (exit {code})")
            self.after(0, finish)

        self.live_process = firmware.build_firmware(
            self.repo_path, on_line=on_line, on_exit=on_exit)

    def _run_upload(self):
        if not self.repo_path:
            return
        if not firmware.check_platformio_installed():
            self._log("PlatformIO CLI ('pio') not found. Install once with:\n"
                       "    pip install platformio\nthen retry.")
            return
        if self.link:
            self._log("Closing ground-station serial connection so pio can flash...")
            self.link.close()
            self.link = None
        self._log("$ pio run -t upload")
        self._start_progress("Flashing firmware to device...")

        def on_line(l):
            self.after(0, lambda: (self._log(l), self.console_status.config(text=l[:200])))

        def on_exit(code):
            def finish():
                self._log(f"[upload exited with code {code}]")
                self._stop_progress("Upload finished" if code == 0 else f"Upload failed (exit {code})")
            self.after(0, finish)

        self.live_process = firmware.upload_firmware(
            self.repo_path, on_line=on_line, on_exit=on_exit)

    def _run_preflight_check(self):
        # If we're already connected (e.g. via the Post-Flight tab), reuse
        # that connection — opening a second one to the same port will
        # fail, since the OS won't let two handles hold it open at once.
        if self.link:
            self._log("Using existing connection for INFO check...")

            def task():
                return self.link.get_info()

            def done(result, err):
                if err:
                    self._log(f"Pre-flight check failed: {err}")
                else:
                    self._log(f"Storage OK: {result}")
                    self._log("Board responded — looks flight-ready from the software side.")

            run_in_background(self, task, done)
            return

        # Not connected yet: prefer whatever port is selected on the
        # Post-Flight tab, otherwise try auto-detection.
        port = self._selected_port() if hasattr(self, "port_var") else None
        if not port:
            port = serial_link.find_board()

        if not port:
            available = serial_link.list_ports()
            if available:
                listing = "\n".join(f"  - {dev}  ({desc})" for dev, desc in available)
                self._log("Couldn't auto-detect the board by USB descriptor. "
                           "Ports found:\n" + listing +
                           "\nGo to the Post-Flight tab, pick the right port from "
                           "the dropdown, click Connect, then retry this check.")
            else:
                self._log("No serial ports found at all — check the USB cable/port, "
                           "and that the board is powered on.")
            return

        self._log(f"Connecting to {port} for a pre-flight INFO check...")

        def task():
            link = serial_link.FlightComputerLink(port)
            info = link.get_info()
            link.close()
            return info

        def done(result, err):
            if err:
                self._log(f"Pre-flight check failed on {port}: {err}")
            else:
                self._log(f"Storage OK: {result}")
                self._log("Board responded — looks flight-ready from the software side.")

        run_in_background(self, task, done)

    # ---------- Post-Flight tab ----------

    def _build_postflight_tab(self):
        frame = self.tab_postflight
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=8, pady=4)

        ttk.Label(top, text="Port:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=30)
        self.port_combo.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh ports", command=self._refresh_ports,
                   bootstyle=SECONDARY).pack(side="left")
        ttk.Button(top, text="Connect", command=self._connect,
                   bootstyle=SUCCESS).pack(side="left", padx=4)
        ttk.Button(top, text="Disconnect", command=self._disconnect,
                   bootstyle="secondary-outline").pack(side="left")
        self.conn_status = ttk.Label(top, text="Not connected", foreground="#e05260")
        self.conn_status.pack(side="left", padx=10)

        mid = ttk.Frame(frame)
        mid.pack(fill="x", padx=8)
        ttk.Button(mid, text="List flights on device",
                   command=self._list_flights, bootstyle=INFO).pack(side="left")
        ttk.Button(mid, text="Download selected", bootstyle=PRIMARY,
                   command=lambda: self._download(auto_delete=False)).pack(side="left", padx=4)
        ttk.Button(mid, text="Download all (auto-delete after save)", bootstyle=PRIMARY,
                   command=self._download_all).pack(side="left", padx=4)
        ttk.Button(mid, text="Delete selected from device", bootstyle=DANGER,
                   command=self._delete_selected).pack(side="left", padx=4)

        self.flight_list = tk.Listbox(frame, height=10, bg=LIST_BG, fg=LIST_FG,
                                       selectbackground=LIST_SELECT_BG,
                                       selectforeground="white", relief="flat",
                                       borderwidth=0, highlightthickness=1,
                                       highlightbackground="#d1e7df",
                                       font=("", 11))
        self.flight_list.pack(fill="both", expand=True, padx=8, pady=4)

        self.postflight_status = ttk.Label(frame, text="")
        self.postflight_status.pack(fill="x", padx=8, pady=(0, 8))

        self._refresh_ports()

    def _refresh_ports(self):
        ports = serial_link.list_ports()
        values = [f"{dev}  ({desc})" for dev, desc in ports]
        self.port_combo["values"] = values
        auto = serial_link.find_board()
        if auto:
            for v in values:
                if v.startswith(auto):
                    self.port_var.set(v)
                    break

    def _selected_port(self):
        val = self.port_var.get()
        return val.split()[0] if val else None

    def _connect(self):
        port = self._selected_port()
        if not port:
            messagebox.showwarning("No port", "Pick a serial port first.")
            return

        def task():
            return serial_link.FlightComputerLink(port)

        def done(result, err):
            if err:
                self.conn_status.config(text=f"Connect failed: {err}", foreground="#e05260")
                self.conn_dot.config(text="●  Not connected", foreground="#e05260")
            else:
                self.link = result
                self.conn_status.config(text=f"Connected: {port}", foreground="#5fd77f")
                self.conn_dot.config(text=f"●  Connected", foreground="#5fd77f")

        run_in_background(self, task, done)

    def _disconnect(self):
        if self.link:
            self.link.close()
            self.link = None
        self.conn_status.config(text="Not connected", foreground="#e05260")
        self.conn_dot.config(text="●  Not connected", foreground="#e05260")

    def _require_link(self):
        if not self.link:
            messagebox.showwarning("Not connected", "Connect to the board first.")
            return False
        return True

    def _list_flights(self):
        if not self._require_link():
            return

        def task():
            return self.link.list_flights()

        def done(result, err):
            self.flight_list.delete(0, "end")
            if err:
                self.postflight_status.config(text=f"Error: {err}")
                return
            self._flights_on_device = result
            for f in result:
                tag = " [ACTIVE]" if f["active"] else ""
                self.flight_list.insert("end", f"{f['file']}  ({f['size']}){tag}")
            self.postflight_status.config(text=f"Found {len(result)} flight(s).")

        run_in_background(self, task, done)

    def _selected_flight_num(self):
        sel = self.flight_list.curselection()
        if not sel:
            return None
        return self._flights_on_device[sel[0]]["num"]

    def _download(self, auto_delete=False):
        if not self._require_link():
            return
        num = self._selected_flight_num()
        if num is None:
            messagebox.showwarning("No selection", "Select a flight in the list first.")
            return
        self.postflight_status.config(text=f"Downloading flight {num}...")
        self._start_progress(f"Downloading flight {num}...")

        def task():
            records = self.link.download_flight(num)
            config_h = os.path.join(self.repo_path, "include", "config.h") \
                if self.repo_path else None
            folder = self.store.save_flight(num, records, config_h_path=config_h)
            if auto_delete:
                active = any(f["num"] == num and f["active"]
                             for f in getattr(self, "_flights_on_device", []))
                if not active:
                    self.link.delete_flight(num)
            return folder

        def done(result, err):
            if err:
                self.postflight_status.config(text=f"Download failed: {err}")
                self._stop_progress("Download failed")
            else:
                self.postflight_status.config(text=f"Saved to {result}")
                self._refresh_history()
                self._stop_progress("Download complete")

        run_in_background(self, task, done)

    def _download_all(self):
        if not self._require_link():
            return
        if not getattr(self, "_flights_on_device", None):
            messagebox.showinfo("Nothing to do", "List flights first.")
            return

        nums = [f["num"] for f in self._flights_on_device if f["num"] is not None]

        self._start_progress(f"Downloading {len(nums)} flight(s)...")

        def task():
            saved = []
            for num in nums:
                records = self.link.download_flight(num)
                config_h = os.path.join(self.repo_path, "include", "config.h") \
                    if self.repo_path else None
                folder = self.store.save_flight(num, records, config_h_path=config_h)
                saved.append(folder)
                active = any(f["num"] == num and f["active"]
                             for f in self._flights_on_device)
                if not active:
                    self.link.delete_flight(num)
            return saved

        def done(result, err):
            if err:
                self.postflight_status.config(text=f"Download-all failed partway: {err}")
                self._stop_progress("Download failed")
            else:
                self.postflight_status.config(text=f"Downloaded {len(result)} flight(s).")
                self._refresh_history()
                self._list_flights()
                self._stop_progress("Download complete")

        run_in_background(self, task, done)

    def _delete_selected(self):
        if not self._require_link():
            return
        num = self._selected_flight_num()
        if num is None:
            return
        if not messagebox.askyesno("Confirm", f"Delete flight {num} from the DEVICE? "
                                                "(Make sure you've downloaded it first!)"):
            return

        def task():
            return self.link.delete_flight(num)

        def done(result, err):
            if err:
                self.postflight_status.config(text=f"Delete failed: {err}")
            else:
                self.postflight_status.config(text=f"Deleted flight {num} from device.")
                self._list_flights()

        run_in_background(self, task, done)

    # ---------- History & Plots tab ----------

    def _build_history_tab(self):
        frame = self.tab_history
        left = ttk.Frame(frame)
        left.pack(side="left", fill="y", padx=8, pady=8)

        ttk.Label(left, text="Saved flights", font=("", 11, "bold")).pack(anchor="w")
        self.history_list = tk.Listbox(left, width=44, height=30, bg=LIST_BG, fg=LIST_FG,
                                        selectbackground=LIST_SELECT_BG,
                                        selectforeground="white", relief="flat",
                                        borderwidth=0, highlightthickness=1,
                                        highlightbackground="#d1e7df",
                                        font=("", 10))
        self.history_list.pack(fill="y", expand=True)
        self.history_list.bind("<<ListboxSelect>>", lambda e: self._render_plot())

        ttk.Label(left, text="Plot:").pack(anchor="w", pady=(8, 0))
        self.plot_choice = tk.StringVar(value=plotting.ALL_PLOTS[0][0])
        plot_combo = ttk.Combobox(left, textvariable=self.plot_choice,
                                   values=[name for name, _ in plotting.ALL_PLOTS],
                                   state="readonly")
        plot_combo.pack(fill="x")
        plot_combo.bind("<<ComboboxSelected>>", lambda e: self._render_plot())

        self.plot_area = ttk.Frame(frame)
        self.plot_area.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        self._refresh_history()

    def _refresh_history(self):
        self.history_list.delete(0, "end")
        self._history_entries = self.store.list_flights()
        for e in self._history_entries:
            dur = e.get("duration_s", 0)
            alt = e.get("max_altitude_m")
            alt_str = f"{alt:.0f} m" if alt is not None else "?"
            self.history_list.insert(
                "end",
                f"Flight {e['flight_num']}  |  {e['downloaded_at']}  |  "
                f"{dur:.1f}s  |  max alt {alt_str}")

    def _get_coast_table(self):
        """Lazily loads + caches (vel_range, cd_range, table) from the repo's
        real sim/coast_table.py. Cache is invalidated whenever the coast
        table is regenerated (see _run_coast_table's done() callback)."""
        if getattr(self, "_coast_table_cache", None) is not None:
            return self._coast_table_cache
        if not self.repo_path:
            return None
        try:
            self._coast_table_cache = coast_lookup.load_coast_table(self.repo_path)
        except Exception as e:
            self._log(f"Couldn't load coast table for plotting: {e}")
            self._coast_table_cache = None
        return self._coast_table_cache

    def _render_plot(self):
        sel = self.history_list.curselection()
        if not sel:
            return
        entry = self._history_entries[sel[0]]
        df = pd.read_csv(entry["csv_path"])

        name = self.plot_choice.get()
        plot_fn = dict(plotting.ALL_PLOTS)[name]

        if plot_fn is plotting.plot_coast_predicted_vs_actual:
            cached = self._get_coast_table()
            if cached:
                vel_range, cd_range, table = cached
                fig = plot_fn(df, vel_range, cd_range, table)
            else:
                fig = plot_fn(df)
        else:
            fig = plot_fn(df)

        for child in self.plot_area.winfo_children():
            child.destroy()
        canvas = FigureCanvasTkAgg(fig, master=self.plot_area)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)


if __name__ == "__main__":
    App().mainloop()