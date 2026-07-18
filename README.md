# ODrive CAN constant-velocity test

This branch contains only the firmware needed to test an ODrive over CAN. It
runs one calibrated ODrive axis at a constant velocity and reports all useful
CAN/ODrive state over USB serial.

## Hardware configuration

The firmware targets the RP2350 Pico 2 and an MCP2515 CAN controller:

| Signal | GPIO |
| --- | ---: |
| MCP2515 MISO | 16 |
| MCP2515 CS | 17 |
| MCP2515 SCK | 18 |
| MCP2515 MOSI | 19 |
| MCP2515 INT | 20 |

The MCP2515 oscillator is configured as 16 MHz and CAN is configured as
250 kbit/s. CANH connects to CANH, CANL connects to CANL, and the nodes need a
common ground plus 120-ohm termination at both physical ends of the bus.

## ODrive setup

Use the ODrive GUI/USB first to complete motor and encoder calibration. Enable
CANSimple, set the axis CAN node ID to `0`, set the CAN baud rate to `250000`,
and enable heartbeat messages. Enable cyclic encoder estimates and Iq messages
as well if position, measured velocity, and current should be printed. The
firmware sends `Set_Controller_Mode` for velocity/passthrough input mode,
requests closed-loop control, and then sends `Set_Input_Vel` every 100 ms.

Set `kODriveNodeId`, `kCanBaudRate`, and
`kStartupVelocityTurnsPerSecond` at the top of
[`src/main.cpp`](src/main.cpp). Velocity units are turns per second. The default
is a deliberately low `1.0 rev/s`.

## Running and debugging

Upload with PlatformIO and open the serial monitor at 115200 baud. The test
waits for a heartbeat before it commands the motor, retries closed-loop entry
when no fault is present, and sends no velocity command if the heartbeat goes
stale. Status is printed once per second; it includes heartbeat freshness, axis
state, ODrive error bits, encoder feedback, queue drops, and CAN TX failures.

Serial commands:

| Key | Action |
| --- | --- |
| `+` / `-` | Increase/decrease target velocity by 0.25 rev/s |
| `0` | Send zero velocity and stop command output |
| `s` | Toggle periodic motor command output |
| `c` | Clear errors and request velocity closed-loop control |
| `t` | Toggle received CAN-frame hex trace |
| `x` | Toggle transmitted CAN-frame hex trace |
| `r` | Dump MCP2515 registers |
| `h` or `?` | Show command help |

If the monitor remains at `heartbeat=missing`, verify the node ID, baud rate,
CANH/CANL wiring, shared ground, bus termination, and MCP2515 crystal value.
If it reports an ODrive error or never reaches state `8`, correct the ODrive
configuration/calibration fault in the GUI before using `c` to retry.
