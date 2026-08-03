# Airbrakes V3

Flight-computer firmware and ground-station tools for a TARC active-airbrakes
system. The firmware runs on an RP2350 (Pico 2) and combines an ICM42688 IMU,
DPS368 barometer, ODrive motor control over CAN, onboard LittleFS logging, and
a closed-loop coefficient-of-drag controller.

## Start here

| Task | Read / run |
| --- | --- |
| Understand the firmware | [Firmware overview](#firmware-overview) |
| Build and flash | [Quick start](#quick-start) |
| Configure the ground station | [Ground station](#ground-station) and [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) |
| Retrieve or analyze flight logs | [`DATA.md`](DATA.md) |
| Regenerate the coast table | `python sim/generate_coast_table.py` |
| Check the repository layout | [Project layout](#project-layout) |

## Quick start

### Firmware

Install PlatformIO (the VS Code extension or the standalone `pio` CLI), then:

```bash
pio run
pio run -t upload
pio device monitor                 # 115200 baud
```

Before flashing, calibrate and configure the ODrive as described in
[Hardware setup](#hardware-setup). Update `include/config.h` for the current
rocket and regenerate the coast table when mass or launch-day weather changes:

```bash
python sim/generate_coast_table.py
```

### Ground station

The desktop GUI provides configuration, build/flash, serial downloads, and
plotting:

```bash
pip install -r app/requirements.txt
python app.py
```

On Windows, `app.bat` is the double-click launcher. For the lower-level serial
workflow, use `python flight_data_manager.py`; see [`DATA.md`](DATA.md).

## Firmware overview

The RP2350 uses both cores:

- **Core 0** handles flash commands, ODrive CAN servicing, and the flight state
  machine.
- **Core 1** runs the 500 Hz estimator: IMU sampling, attitude propagation,
  and the altitude/velocity/bias Kalman filter.

The flight states are:

`IDLE → PAD → BOOST → CONTROL → DESCENT → LANDED`

The controller estimates drag during coast, predicts apogee using the generated
velocity/Cd coast table, solves for a target Cd, and commands the ODrive brake
position. Logging runs at 100 Hz and is buffered before being written to
LittleFS. The complete storage format and serial protocol are documented in
[`DATA.md`](DATA.md).

Useful implementation areas:

| Area | Files |
| --- | --- |
| Flight state machine | `include/state.h`, `src/state.cpp` |
| Estimation | `src/estimator.cpp`, `src/kalman.cpp`, `src/orientation.cpp` |
| Drag controller | `src/control.cpp`, `include/coast_table.h` |
| Hardware and CAN | `src/hardware.cpp`, `include/hardware.h` |
| Logging | `src/flash.cpp`, `include/flash.h` |
| Tuning | `include/config.h` |

## Hardware setup

### ODrive

Use the ODrive GUI/USB before flashing:

1. Complete motor and encoder calibration.
2. Enable CANSimple; set the axis node ID to `0` and baud rate to `250000`.
3. Enable heartbeat, cyclic encoder-estimate, and Iq messages.
4. Configure the axis for position control.

The firmware assumes this configuration and does not send
`Set_Controller_Mode` at runtime. Brake travel is limited by `MOTOR_MIN` and
`MOTOR_MAX` in `include/config.h`.

### Pinout

| Signal | GPIO |
| --- | ---: |
| MCP2515 MISO / CS / SCK / MOSI / INT | 16 / 17 / 18 / 19 / 20 |
| DPS368 SCL / SDA | 5 / 4 |
| ICM42688 CS / SCK / MISO / MOSI | 9 / 10 / 8 / 11 |
| RGB LED R / G / B | 24 / 23 / 22 |

### Vendored CAN library

`lib/CAN` is a patched local copy of `sandeepmistry/CAN@0.3.1` with the
20 MHz MCP2515 crystal timing table required by this board. Do **not** add the
registry CAN package to `platformio.ini`; PlatformIO should use the local copy.

## Ground station

- `app.py` launches the desktop GUI; `app.bat` launches it on Windows.
- `app/` contains the GUI, serial link, configuration editor, coast-table
  tools, plotting, and firmware helpers.
- `flight_data_manager.py` is the command-line downloader and CSV converter.

The GUI and CLI use the same firmware protocol: `INFO`, `LIST`, `CURRENT`,
`GET <n>`, and `DELETE <n>`. For setup, safety checks, record layout, and
troubleshooting, use [`DATA.md`](DATA.md) rather than duplicating that
information here.

## Project layout

```text
include/              Firmware headers and shared configuration
src/                  Firmware implementation
lib/CAN/              Patched local CAN library
app/                  Ground-station application modules
sim/                  Coast-table generation and lookup tools
tools/                Standalone ODrive CAN test source
flight_data/          Downloaded CSV files
test/                 PlatformIO tests
```

The standalone ODrive bring-up firmware is stored as
`tools/odrive_can_standalone_test.cpp.txt` so it is not included in the normal
PlatformIO build. Copy it to `src/main.cpp` only when testing the CAN link in
isolation, and restore the original firmware afterward.

## Documentation map

- [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) — GUI setup and usage.
- [`DATA.md`](DATA.md) — LittleFS records, serial protocol, download workflow,
  and troubleshooting.
- [`include/README`](include/README) — header-directory conventions.
- [`lib/README`](lib/README) — local-library notes.
- [`test/README`](test/README) — test-directory conventions.