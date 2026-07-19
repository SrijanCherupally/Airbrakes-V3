# Airbrakes V3

Flight computer firmware for a TARC active airbrakes system, built on an
RP2350 (Pico 2) with an ODrive-driven brake motor, ICM42688 IMU, DPS368
barometer, and a closed-loop coefficient-of-drag controller targeting a set
apogee altitude.

This branch merges two lines of work:

- The full flight-computer state machine, sensor fusion, and Cd controller
  (as of commit `2c1a594`, before the ODrive/CAN wiring was pulled out for
  isolated testing).
- The proven-working ODrive CAN link from the `CAN` branch, including a
  vendored, patched copy of the `CAN` library with 20 MHz MCP2515 crystal
  support.

## Architecture

The RP2350 runs two cores (see `src/main.cpp`):

- **Core 0** (`loop()`): flash-log command handling, ODrive CAN servicing,
  and the flight state machine (`stateUpdate()`).
- **Core 1** (`loop1()`): the 500 Hz sensor fusion loop (`estimatorUpdate()`)
  — IMU read, quaternion attitude propagation, and the scalar Kalman
  altitude/velocity filter.

### Flight state machine (`state.h` / `state.cpp`)

`STATE_IDLE -> STATE_PAD -> STATE_BOOST -> STATE_CONTROL -> STATE_DESCENT -> STATE_LANDED`

- **IDLE**: waiting for 10 s of stillness before arming (`STATE_PAD`) and
  starting flash logging.
- **PAD**: calibrates accelerometer bias while stationary, arms a short
  launch-detection window on a sudden accel spike, and recovers the missed
  pre-roll velocity once launch is confirmed.
- **BOOST**: logs flight data; watches for burnout (velocity below
  `VEL_CONTROL_START` while still ascending and decelerating).
- **CONTROL**: runs `controlUpdate()` — solves for and closed-loop-tracks the
  Cd needed to hit `TARGET_ALTITUDE`, commanding the ODrive to a brake
  position. Transitions to `DESCENT` once vertical velocity goes negative
  past `VEL_DESCENT` (apogee).
- **DESCENT**: closes the airbrakes and waits to cross `ALT_LANDED`.
- **LANDED**: flushes the flight log buffer to flash and idles.

### Estimation (`estimator.cpp`, `kalman.cpp`, `orientation.cpp`, `vector.cpp`)

A quaternion attitude filter integrates gyro rates to rotate body-frame
accelerometer readings into the world frame; a 3-state (altitude, velocity,
accelerometer bias) Kalman filter fuses that world-frame vertical
acceleration with barometric altitude. Coefficient of drag is estimated
in-flight from the deceleration during coast and low-pass filtered.

### Control (`control.cpp`, `coast_table.h`)

`coast_table.h` is an auto-generated bilinear lookup table (velocity x Cd ->
altitude gained through coast) produced by `sim/generate_coast_table.py`. At
each control-loop tick, `getCoastAltitude()` predicts apogee for the current
state at both minimum and maximum Cd; if `TARGET_ALTITUDE` falls between
those predictions, a bisection search finds the Cd that hits it, and a
PI controller drives the ODrive position setpoint to track that Cd.

### Hardware layer (`hardware.h` / `hardware.cpp`)

Owns the global driver instances (`baro`, `imu`, `led`, `odrv`) and the
ODrive CAN link: MCP2515 over SPI0, ODrive telemetry via CAN callbacks
(heartbeat, encoder estimates, Iq), and helpers to request/maintain
closed-loop control and command a brake position.

### Logging (`flash.h` / `flash.cpp`)

Buffers flight records in RAM and writes them to LittleFS in ~52 KB chunks
to avoid blocking the control loop. Serial commands (`LIST`, `CURRENT`,
`GET <n>`, `DELETE <n>`, `INFO`) let a ground-station script pull flight logs
off the device after landing.

## Hardware pinout

| Signal | GPIO |
| --- | ---: |
| MCP2515 (CAN) MISO | 16 |
| MCP2515 (CAN) CS | 17 |
| MCP2515 (CAN) SCK | 18 |
| MCP2515 (CAN) MOSI | 19 |
| MCP2515 (CAN) INT | 20 |
| DPS368 baro SCL | 5 |
| DPS368 baro SDA | 4 |
| ICM42688 IMU CS (SPI1) | 9 |
| ICM42688 IMU SCK (SPI1) | 10 |
| ICM42688 IMU MISO (SPI1) | 8 |
| ICM42688 IMU MOSI (SPI1) | 11 |
| RGB LED R / G / B | 24 / 23 / 22 |

All of the above are `#define`d in `include/hardware.h`, `include/baro.h`,
and `include/imu.h`.

## The CAN library: why it's vendored, not a registry dependency

`lib/CAN` is a local copy of `sandeepmistry/CAN@0.3.1`, patched to add a
20 MHz MCP2515 CNF (bit-timing) table — the upstream release only ships CNF
tables for common crystals (8/16 MHz), not the 20 MHz oscillator this board
uses. **Do not** add `sandeepmistry/CAN` to `lib_deps` in `platformio.ini`;
PlatformIO will already prefer this local copy, and pulling in the upstream
package risks confusing which `CAN.h` gets picked up. The clock is set in
`hardware.cpp` via `CAN.setClockFrequency(MCP2515_CLK_HZ)` with
`MCP2515_CLK_HZ` defined as `20000000` in `include/hardware.h` — this is the
value that was confirmed working on the `CAN` branch.

The ODrive-side CAN glue (`ODriveCAN.h/.cpp`, `ODriveMCPCAN.hpp`,
`ODriveEnums.h`, `can_helpers.hpp`, `can_simple_messages.hpp`) is ODrive's
official Arduino CAN-Simple library, unmodified. It talks to the vendored
`lib/CAN` through the same `MCP2515Class` interface upstream would provide,
so no changes were needed there.

## ODrive setup

Before flashing this firmware, use the ODrive GUI/USB to:

1. Complete motor and encoder calibration.
2. Enable CANSimple, set the axis's CAN node ID to `0`, and set the CAN baud
   rate to `250000`.
3. Enable heartbeat messages, cyclic encoder estimates, and Iq messages.
4. Configure the axis controller for **position control** (this firmware
   never sends `Set_Controller_Mode` at runtime — it assumes the ODrive is
   already configured and calibrated, and just requests closed-loop control
   and streams position setpoints).

`odrvPosition()` in `hardware.cpp` sends `Set_Input_Pos`; brake travel is
clamped to `MOTOR_MIN`/`MOTOR_MAX` in `include/config.h`.

## Tuning constants (`include/config.h`)

Mass, base Cd, launch/landing thresholds, target apogee altitude, brake
travel limits, and the Cd-tracking PI gains all live here. `MASS` and the
air-density constant are meant to be regenerated together with
`coast_table.h` by `sim/generate_coast_table.py` whenever the rocket's mass
or expected launch-day weather changes — see that script's header for the
editable fields.

## Standalone ODrive CAN test

`tools/odrive_can_standalone_test.cpp.txt` is the single-purpose ODrive
velocity-mode test firmware this project used to bring up and debug the CAN
link in isolation (formerly `src/main.cpp` on the `CAN` branch). It's kept
here, out of the PlatformIO build (`.txt` extension, outside `lib/`), in case
the ODrive/CAN wiring ever needs to be re-tested independent of the rest of
the flight computer — copy it back to `src/main.cpp` temporarily to use it.

## Building

```
pio run                 # build
pio run -t upload        # flash
pio device monitor       # serial monitor @ 115200 baud
```

## Simulation tools (`sim/`)

- `generate_coast_table.py`: regenerates `include/coast_table.h` and the
  `MASS`/air-density constants in `include/config.h` from rocket mass,
  temperature, humidity, and pressure.
- `coast_table.py`: a Python-side copy of the same lookup table, useful for
  offline analysis/plotting against logged flight data.
