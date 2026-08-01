# Flight Data Logging Guide (LittleFS)

This document explains how flight data logging works on the Airbrakes V3
flight computer, and walks through the process of setting up the board,
flying, and pulling flight logs off it afterward.

It's meant to sit alongside the main `README.md` (which covers the flight
software architecture in general) and is focused specifically on
**LittleFS** and the **data-retrieval workflow** implemented in
`src/flash.cpp` / `include/flash.h` on the device side, and
`flight_data_manager.py` on the ground-station side.

---

## 1. What LittleFS is, and why this project uses it

The RP2350 (Pico 2) has no SD card — flight data is stored directly on the
chip's onboard flash. Writing to raw flash directly is risky for a flight
computer, because:

- **Power can cut out mid-write** (a hard landing, a battery disconnect, a
  brownout) and a naive write scheme can leave you with a half-written,
  corrupted file.
- **Flash wears out** after a bounded number of erase/write cycles per
  block, so hammering the same block on every write is a bad idea.
- **RAM is limited**, so a filesystem that needs a big heap to operate
  isn't practical here.

[LittleFS](https://github.com/littlefs-project/littlefs) is a small
filesystem built for exactly this environment: it's power-loss resilient
(copy-on-write, so a lost-power write doesn't corrupt the whole
filesystem), wear-levels across blocks, and only needs small static
buffers. In this project it's simply the on-chip "drive" that holds flight
logs between landing and the point where you pull them off over serial.

## 2. How the firmware actually uses it (`src/flash.cpp`)

### Storage format

Each flight is written as its own file, `/flight_<N>.bin`, where `<N>`
starts at 0 and increments — `initFlash()` scans on boot for the first
`N` that doesn't already exist on the filesystem, so flights are never
overwritten, only added.

Each file is a flat binary stream of fixed-size, packed `FlightRecord`
structs, **68 bytes each**:

| Field | Type | Notes |
| --- | --- | --- |
| `time_ms` | `uint32_t` | ms since logging started for this flight |
| `altitude_m` | `float` | |
| `velocity_ms` | `float` | |
| `accel_bias_ms2` | `float` | |
| `raw_accel_ms2` | `float` | |
| `raw_baro_m` | `float` | |
| `motor_pos` | `float` | |
| `motor_vel` | `float` | |
| `motor_cmd_pos` | `float` | |
| `roll_rad` / `pitch_rad` / `yaw_rad` | `float` | |
| `Cd` / `desired_Cd` | `float` | |
| `motor_current` | `float` | |
| `state` | `uint32_t` | flight state enum, see below |
| `axis_error` | `uint32_t` | ODrive axis error code |

The record layout is `<I14fII` if you're parsing it yourself in Python
(`struct.calcsize` gives 68 bytes) — one `uint32_t`, fourteen `float`s,
then two more `uint32_t`s.

### Buffering and write cadence

- `logFlightData()` is rate-limited to **100 Hz** (a record is only
  appended if ≥10 ms have passed since the last one), even though it may be
  called more often from the control loop.
- Records go into a RAM ring buffer (`writeBuffer`) of **768 records =
  ~52 KB**, which at 100 Hz holds about **7.7 seconds** of flight data
  before it needs to be flushed.
- `flushLogBuffer()` drains that ring buffer to the open `LittleFS` file
  and calls `.flush()` so the file's size on disk stays accurate and the
  data is durable. This is called from the main loop rather than on every
  sample, which is what keeps LittleFS writes off the hot path of the
  500 Hz sensor-fusion loop.
- If the RAM buffer ever fills up completely (the flush loop falling
  behind), `logFlightData()` forces an immediate flush rather than
  silently dropping data.
- The actual `/flight_<N>.bin` file isn't created until the **first**
  `logFlightData()` call — i.e., logging (and the file) only starts once
  the state machine begins actively recording, not the moment the board
  powers on.

### Low storage warning

On `initFlash()`, if free space on the LittleFS partition drops below
**4 MB**, the firmware prints a low-storage warning and flags it for
10 seconds (`checkStorageWarning()`) — worth checking before a flight.

### Serial command protocol

`handleFlashCommands()` reads newline-terminated commands from `Serial`
and responds with `FLASH:`-prefixed lines:

| Command | Behavior |
| --- | --- |
| `INFO` | Prints `FLASH:STORAGE: <used> / <total> used` (auto-scaled to bytes/KB/MB). |
| `LIST` | Prints one `FLASH:FLIGHT:<filename> (<size>)` line per flight file found, tagging the currently-open flight with `[ACTIVE]`, then `FLASH:END`. |
| `CURRENT` | Prints `FLASH:CURRENT:<N>` — the flight number currently in use for logging. |
| `GET <n>` | If flight `<n>` is the one currently being logged, flushes and closes it first (then reopens it in append mode afterward so logging can continue), then streams the raw file bytes between `FLASH:DATA_START` and `FLASH:END` markers, in 256-byte chunks. |
| `DELETE <n>` | Deletes `/flight_<n>.bin`, unless it's the currently-active flight (refuses with `FLASH:ERROR: Cannot delete active flight`). Responds `FLASH:DELETED` on success. |

Baud rate is **115200** (matches `pio device monitor` default in the main
README).

## 3. `flight_data_manager.py` (ground station script)

This is the Python counterpart, in the repo root. It:

- **Auto-detects the board** by USB descriptor (manufacturer `"Srijan"` /
  product `"AIrbrakes V3"` from `platformio.ini`), falling back to any
  port that looks like a Pico/RP2040/RP2350, and otherwise lets you pick a
  port manually from a numbered list.
- Talks the exact protocol above (`LIST`, `GET <n>`, `DELETE <n>`, `INFO`)
  over serial at 115200 baud.
- Unpacks each 68-byte binary record with `struct` (format `<I14fII`) and
  writes it out as a CSV with a human-readable `state` column (mapped from
  the numeric state via `STATE_NAMES = ['IDLE','PAD','BOOST','CONTROL','DESCENT','LANDED']`).
- Saves CSVs to a local `flight_data/` folder (created automatically) as
  `flight_<N>_<YYYYMMDD_HHMMSS>.csv`.

### Usage

```bash
python flight_data_manager.py                # interactive menu
python flight_data_manager.py list           # list flights, then exit
python flight_data_manager.py get <n>        # download flight <n> to CSV, then exit
python flight_data_manager.py download-all   # download every flight, auto-deleting each from the device after a successful save
```

Interactive mode (no arguments) gives you a menu: list flights, download
one flight, download+auto-delete all flights, delete a specific flight,
check storage, or exit. It will refuse to delete (or auto-delete after
download) whichever flight is currently active on the device.

Requires `pyserial`:
```bash
pip install pyserial
```

---

## 4. Step-by-step: setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/SrijanCherupally/Airbrakes-V3.git
   cd Airbrakes-V3
   ```

2. **Install PlatformIO** (VS Code extension or the standalone `pio` CLI).

3. **Install the Python dependency for the ground-station script:**
   ```bash
   pip install pyserial
   ```

4. **Do the ODrive setup before flashing this firmware**, using the
   ODrive GUI/USB (not this firmware):
   - Complete motor and encoder calibration.
   - Enable CANSimple, set the axis's CAN node ID to `0`, CAN baud rate to
     `250000`.
   - Enable heartbeat, cyclic encoder estimate, and Iq CAN messages.
   - Set the axis controller to **position control** mode.

   This firmware never sends `Set_Controller_Mode` at runtime — it assumes
   the ODrive is already calibrated and configured, and just requests
   closed-loop control and streams position setpoints.

5. **Check/update tuning constants** in `include/config.h` (mass, target
   apogee altitude, brake travel limits, PI gains). Regenerate `MASS` and
   `include/coast_table.h` together whenever rocket mass or launch-day
   weather changes:
   ```bash
   python sim/generate_coast_table.py
   ```

6. **Wire the hardware** per the pinout table in the main README.

7. **Build and flash:**
   ```bash
   pio run                 # build
   pio run -t upload       # flash to the RP2350
   pio device monitor       # serial monitor @ 115200 baud
   ```

8. **Confirm the filesystem is healthy before you fly.** With the serial
   monitor open, send:
   ```
   INFO
   ```
   and check the reported free space is comfortably above the 4 MB
   low-storage threshold. If old flights are eating space, clear them with
   `flight_data_manager.py` (see step 10 below) before heading to the pad.

---

## 5. Step-by-step: at the pad / during flight

1. **Power on and let the board sit still** — `STATE_IDLE` waits for 10 s
   of stillness before arming.
2. `STATE_PAD` calibrates accelerometer bias while stationary and arms
   launch detection. Keep the rocket still through this.
3. On launch detection, the state machine moves through `STATE_BOOST` →
   `STATE_CONTROL` → `STATE_DESCENT` → `STATE_LANDED`. Logging starts with
   the first `logFlightData()` call after arming and continues
   automatically — no user action needed. Data is buffered at 100 Hz and
   flushed to LittleFS in ~52 KB chunks in the background.
4. On reaching `STATE_LANDED`, any remaining buffered data is flushed and
   the file is left ready to be closed/read out.

---

## 6. Step-by-step: after landing (retrieving data)

1. **Recover the rocket and connect it to your laptop** over USB.

2. **Run the ground-station script:**
   ```bash
   python flight_data_manager.py
   ```
   It should auto-detect the board's serial port; if not, it'll list
   available ports for you to choose from.

3. **List flights** (option `1`, or `python flight_data_manager.py list`)
   to confirm which flight number corresponds to the flight you just flew
   — it will be tagged `[ACTIVE]`/"Currently logging" if it's still the
   open file.

4. **Download it** (option `2`, or `python flight_data_manager.py get <n>`).
   This writes `flight_data/flight_<n>_<timestamp>.csv` on your laptop. If
   you're downloading the currently-active flight, the firmware flushes
   and briefly closes/reopens the file on-device automatically — you don't
   need to do anything special for that.

5. **Verify the CSV** looks complete (row count roughly matches flight
   duration × 100 Hz, no obvious truncation) before deleting anything from
   the device.

6. **Free up space on the device** once you're confident the data is
   safe — either delete individually (option `4`, or `DELETE <n>` over
   serial), or use `download-all` next time, which downloads every flight
   and auto-deletes each one from the device right after a successful
   save (skipping the active flight if one is still logging).

7. **Analyze the data.** `sim/coast_table.py` is a Python-side copy of the
   same coast-table lookup logic used on-device, useful for comparing the
   logged flight (actual apogee/Cd tracking) against the sim's
   predictions.

---

## 7. Quick troubleshooting

- **Script can't find the board:** it matches on USB manufacturer/product
  strings (`"Srijan"` / `"AIrbrakes V3"`, from `platformio.ini`) or a
  generic Pico/RP2040/RP2350 description. If none of those match your
  OS's port listing, just pick the port manually from the numbered list
  the script prints.
- **`INFO` reports the filesystem is low on space or failed to mount:**
  pull logs off and delete them (or reformat as a last resort — that
  wipes any un-retrieved flight data, so always download promptly after a
  flight).
- **`GET`/download seems to hang:** make sure nothing else has the serial
  port open at the same time (e.g. `pio device monitor` and
  `flight_data_manager.py` both fighting over the port).
- **CSV has a "Corrupt record" warning:** the script detected a chunk that
  didn't cleanly unpack as a 68-byte record (e.g. a partial trailing
  record from an interrupted transfer) and skipped it rather than
  crashing — the rest of the file should still be valid.
- **Log list is empty after a flight:** logging only starts on the first
  `logFlightData()` call, so double-check the board actually left
  `STATE_IDLE` and armed before launch.