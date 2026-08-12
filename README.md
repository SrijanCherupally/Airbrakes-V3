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

## Airbrakes setup and pre-flight procedure

Follow this order every time. Your board has been confirmed to support USB-C
and the flight battery connected simultaneously, so that combination is
allowed. Do not treat unplugging and reflashing as a normal flight requirement;
it can clear a transient USB, I2C, or power-state problem, but it does not prove
that the barometer or wiring is reliable.

### Exact USB-C and battery sequence

The table below is the recommended sequence. “OFF” means physically
disconnected, not merely switched off in software. USB-C + battery is allowed
on this board, but disconnect USB before launch so the rocket has only the
intended flight-power connection.

| Step | USB-C | Flight battery | Action |
| --- | --- | --- | --- |
| 1. Inspect wiring | **Disconnected** | **Disconnected** | Check wiring and polarity with all power removed. |
| 2. Connect for programming | **Connect** | **Disconnected or connected** | Connect USB-C to the board and computer. Battery may remain connected because simultaneous power is supported, but disconnect it if the motor could move unexpectedly. |
| 3. Flash firmware | **Connected** | **Disconnected or connected** | Build/upload with PlatformIO. Keep the airbrake mechanism safe; flashing resets the board and temporarily interrupts logging. |
| 4. Open diagnostics | **Connected** | **Disconnected** | Open the 115200-baud serial monitor and press reset once. |
| 5. Verify sensors | **Connected** | **Disconnected or connected** | Confirm `DPS368 OK` and inspect `PREFLIGHT`. Click **Check DPS368** in the app for an on-demand result. Do not launch unless the complete powered system later reports all required devices OK. |
| 6. Ground test: sensors/logging | **Connected** | **Disconnected or connected** | USB-only is sufficient for a stationary sensor/logging test. Battery + USB is also allowed. Use the app’s monitor and **Check DPS368**; download the log afterward. |
| 7. Optional airbrake sweep | **Connected** | **Connected if required by ODrive/motor** | This is optional when the actuator has already repeatedly passed testing. Run it only when you need to verify the mechanism, with the mechanism restrained and the battery/motor supply connected. |
| 8. End USB test | **Disconnect** | **Connected or disconnected** | Stop the monitor and abort/finish the test. Disconnect USB-C before launch; do not power-cycle merely as a routine logging step. |
| 9. Battery-only boot | **Disconnected** | **Connect** | Connect the flight battery with correct polarity and allow the board to boot once. Do not reflash at this stage. |
| 10. Flight installation | **Disconnected** | **Connected** | Keep USB-C disconnected while installing and launching. Arm only after the battery-only boot and hardware inspection pass. |
| 11. After recovery | **Disconnected** | **Disconnect** | After landing, disconnect the battery before reconnecting USB-C or handling the board. |

1. **Inspect hardware with all power disconnected.** Confirm DPS368 SDA is
   GPIO4, SCL is GPIO5, 3.3 V and GND are connected, and the sensor board has
   no loose or shorted jumper. The firmware probes DPS368 addresses `0x76` and
   `0x77`.
2. **Connect USB only** and flash the firmware. Close PlatformIO/serial monitor
   programs that keep the port open after uploading.
3. Open a monitor at **115200 baud**, reset the board once, and wait for:
   `DPS368 OK, baseline pressure Pa: ...` and
   `PREFLIGHT: ... DPS368=OK`. A valid baseline should be near local atmospheric
   pressure (roughly 80,000–110,000 Pa), not zero.
4. If DPS368 is `FAIL`, stop. Read the `DPS368_DIAG` line. `no DPS368 at
   0x76 or 0x77` means wiring, power, pins, pull-ups, or the sensor board is
   wrong; an invalid baseline points to a bad I2C read or sensor/calibration
   problem. Do not launch with this warning.
5. Start a sensor/logging ground test only after the preflight output reports
   `DPS368=OK`. With USB-only power, `ODRIVE=FAIL` can be expected because the
   motor controller may be unpowered. For an airbrake sweep, provide the
   separate ODrive/motor supply and verify ODrive readiness before starting.
   Keep the board stationary for several seconds and verify the logged raw
   barometer altitude is finite and changes smoothly when pressure is gently
   applied/released near the sensor (do not blow moisture into it).
6. **The serial preflight check requires USB.** Perform it while USB is
   connected; the battery may also be connected because simultaneous power is
   supported. The serial monitor is how you read `DPS368=OK` and
   `DPS368_DIAG`. After it passes, stop the serial monitor and disconnect USB
   before installation. A battery-only boot repeats the diagnostic internally,
   but its serial output cannot be read without a telemetry link.
   If the board has no documented LED fault code or other telemetry, you cannot
   independently verify the barometer after disconnecting USB; do not assume
   that it passed.
7. Do not repeatedly reflash immediately before launch as a substitute for
   finding a persistent `DPS368=FAIL` condition. If you need to power-cycle,
   power down completely, wait a few seconds, then power the board once and
   inspect the result over USB before proceeding.

If a power cycle makes the barometer work, record that as evidence of a reset or
power-sequencing issue and inspect the 3.3 V rail, I2C pull-ups, USB grounding,
and sensor wiring before flight. A power cycle is not a guarantee of recovery.

### What the app can and cannot do

The app can select the serial port, flash firmware, reconnect after upload,
show boot/preflight output, send `GROUND_TEST START/STATUS/ABORT`, and download
the resulting log. It cannot provide power to the board or ODrive. USB power is
normally enough for the Pico, IMU, DPS368, and a sensor/logging test. USB-C and
battery may remain connected together on this board. An airbrake motion test
requires whatever separate ODrive/motor supply the hardware wiring requires,
even though the command is sent through USB. The app’s **Pre-flight
check (INFO)** only checks the serial link and onboard storage; it does not
perform the hardware sensor preflight. The actual sensor result is the
firmware’s `PREFLIGHT`/`DPS368_DIAG` text in the live monitor. Do not interpret a
successful `INFO` response as proof that the barometer works.


To check the barometer later without resetting or reflashing, connect to the
board in the app and press **Check DPS368** in the Ground test card. This sends
`BARO STATUS` and prints a fresh `DPS368_DIAG` line. A healthy result has
`initialized=YES`, a pressure near local atmospheric pressure (normally about
80,000–110,000 Pa), and `valid` greater than zero. `initialized=NO` or an error
such as `no DPS368 at 0x76 or 0x77` means the sensor is not usable.
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
npm install
npm start
```

On Windows, `app.bat` is the double-click launcher. On macOS, run
`chmod +x app.command` once, then double-click `app.command` in Finder. For the
The app saves flights to the same local folder as before; see
[`DATA.md`](DATA.md) for the wire protocol.

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
| RGB LED R / G / B | 24 / 22 / 23 |

### Vendored CAN library

`lib/CAN` is a patched local copy of `sandeepmistry/CAN@0.3.1` with the
20 MHz MCP2515 crystal timing table required by this board. Do **not** add the
registry CAN package to `platformio.ini`; PlatformIO should use the local copy.

## Ground station

- `desktop/renderer.html` is the unified Electron UI; `app.bat` and
  `app.command` are the Windows and macOS double-click launchers.
- `desktop/main.js` provides the local serial, PlatformIO, configuration, and
  flight-download bridge. Analytics and replay are built into the Node/Electron renderer; replay supports left-drag orbiting, right-drag panning, and wheel zoom.

The GUI and CLI use the same firmware protocol: `INFO`, `LIST`, `CURRENT`,
`GET <n>`, and `DELETE <n>`. For setup, safety checks, record layout, and
troubleshooting, use [`DATA.md`](DATA.md) rather than duplicating that
information here.

## Project layout

```text
include/              Firmware headers and shared configuration
src/                  Firmware implementation
lib/CAN/              Patched local CAN library
desktop/              Unified Electron ground-station application
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
