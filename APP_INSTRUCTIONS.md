# Airbrakes V3 Ground Station

A desktop app that replaces VS Code + the terminal + the old
`flight_data_manager.py` CLI for day-to-day use — pre-flight config and
flashing, post-flight data download, and full flight plotting, all in one
place with a proper UI.

## Folder layout

```
Airbrakes App.py         <- the file you actually run (see "Running it" below)
Airbrakes App.command    <- double-click launcher, macOS/Linux
Airbrakes App.bat        <- double-click launcher, Windows
build_mac_linux.sh       <- ONE-TIME: packages everything into a real .app/binary
build_windows.bat        <- ONE-TIME: packages everything into a real .exe
app/                     <- all the actual application code lives here
  main_window.py          - the GUI (ttkbootstrap), ties everything together
  serial_link.py           - talks flash.cpp's exact serial protocol
  config_editor.py         - generic #define parser/editor for config.h
  coast_table_tool.py       - drives your REAL sim/generate_coast_table.py
  coast_lookup.py           - loads your REAL sim/coast_table.py for plotting
  firmware.py               - runs `pio run` / `pio run -t upload`
  data_store.py             - local flight database (CSV + metadata per flight)
  plotting.py               - matplotlib figures for the History tab
  requirements.txt
```

Why the launcher is a separate file outside `app/`: it's the one stable
entry point you (or a double-click icon) point at. Everything else can be
reorganized inside `app/` later without breaking how you launch it.

## Running it

**First time, from a terminal (one-time setup):**
```bash
pip install -r app/requirements.txt
python "Airbrakes App.py"
```
It'll ask you to point it at your local clone of `Airbrakes-V3` (the folder
with `platformio.ini` in it) the first time it runs.

**After that, three ways to launch it without typing commands:**

1. Double-click `Airbrakes App.command` (macOS/Linux) or `Airbrakes App.bat`
   (Windows). These just run the Python app for you — quickest option, but
   a terminal window may flash briefly since that's how double-clickable
   scripts work on these platforms.
2. **Recommended for "never see a terminal again":** run the one-time
   packaging step —
   ```bash
   bash build_mac_linux.sh     # macOS/Linux
   build_windows.bat           # Windows
   ```
   This uses PyInstaller to bundle Python + the app + all its libraries
   into a real double-clickable app under `dist/`. Drag that to your
   Desktop/Applications/Start Menu. From then on, it's just an icon.
3. From VS Code or a terminal, same as before: `python "Airbrakes App.py"`.

`pio` (PlatformIO's CLI) is installed by the same `pip install -r
app/requirements.txt` — you don't need the VS Code extension for building
or flashing.

## What it does

**Pre-Flight tab**
- Edits every tunable in `include/config.h` through a form (built by
  parsing your actual file's `#define` lines — nothing hardcoded). Saving
  rewrites only the changed values; every comment, blank line, and the
  commented-out `BARO_COMP_*` block are left exactly as they are.
- `MASS` is greyed out with a note that it's set by the coast-table tool,
  not hand-edited, since that's what its own comment in `config.h` says.
- A launch-conditions form (mass, temperature, humidity, pressure) that
  calls your real `sim/generate_coast_table.py` functions directly —
  regenerating `coast_table.py`, `coast_table.h`, and updating `config.h`'s
  `MASS`/`RHO`, exactly like running that script yourself would, just
  without opening it in an editor to change its constants first.
- Build / Flash / pre-flight serial check (`INFO`), all streamed to a live
  console in the app.

**Post-Flight / Download tab**
- Connects to the board over serial (auto-detects it by USB descriptor,
  same as `flight_data_manager.py` did, with a manual port picker as a
  fallback).
- Lists flights on the device, downloads one or all of them, deletes from
  device storage — using the exact `LIST`/`GET <n>`/`DELETE <n>`/`INFO`
  protocol implemented in `src/flash.cpp`.

**History & Plots tab**
- Every downloaded flight is saved locally (see "Where your data lives"
  below) and browsable.
- Plots: altitude & velocity, acceleration, motor/airbrake position, motor
  position vs Cd, Cd tracking (actual vs desired), flight state timeline,
  and **coast predicted-vs-actual** — this last one uses your real
  `sim/coast_table.py` lookup table (bilinear-interpolated) to show what
  the onboard model predicted at each instant of coast vs. what actually
  happened, which is the most direct check of whether the flight matched
  the model.

## Where your data lives

Downloaded flights save under `~/.airbrakes_ground_station/flight_data/`
by default (changeable from the File menu), one folder per flight:
```
flight_0000_2026-08-01_171338/
  data.csv              <- full 100 Hz record, one row per sample
  meta.json              <- duration, max altitude, download time
  config_snapshot.h       <- exact config.h this flight flew with
```

## What's actually been verified vs. what needs your hardware

I have your real repo now, so almost everything below was tested against
your actual files rather than assumptions:

- **Verified against your real files:**
  - `config_editor.py` parses all 17 live tunables in your `config.h`
    correctly, correctly skips the commented-out `BARO_COMP_*` block
    (this was a real bug I caught and fixed after you sent the files),
    and round-trips saves without touching anything but the intended
    value.
  - `coast_table_tool.py` ran your actual `generate_coast_table.py`
    end-to-end on a scratch copy of your repo — `coast_table.py`,
    `coast_table.h`, and `config.h`'s `MASS`/`RHO` all updated correctly
    for new launch conditions.
  - `coast_lookup.py`'s bilinear interpolation is exact at your table's
    grid points and matches expected values in between.
  - The full data pipeline (download → CSV → all 7 plots) was tested on
    synthetic flight data and rendered correctly (also caught and fixed a
    real bug here: the CSV writer was dropping the numeric `state`
    column).
  - The GUI itself: I actually ran it on a virtual display and
    screenshotted it — the ttkbootstrap dark theme renders correctly
    (confirmed via pixel analysis, not just "should work").

- **Still needs a pass on your actual bench/hardware:**
  - Serial connect/list/download/delete against a real board (the
    protocol is exact, but I don't have your Pico 2 here to test with).
  - `pio run` / `pio run -t upload` against your real board and toolchain.
  - The PyInstaller packaging scripts (`build_mac_linux.sh` /
    `build_windows.bat`) — these follow standard PyInstaller usage but
    haven't been run for real, since that also needs to happen on your
    machine.

If anything misbehaves on real hardware, tell me exactly what happened
(error text, which button, what you expected) and I'll fix it fast.