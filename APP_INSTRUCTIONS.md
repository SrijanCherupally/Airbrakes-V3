# Airbrakes V3 Ground Station

The ground station is one Electron desktop application. It combines board
connection, pre-flight checks, DPS368 diagnostics, ground tests, configuration,
firmware operations, flight downloads, serial monitoring, and the interactive
analytics dashboard.

The window has four views: **Operations**, **Configuration**, **Analytics**, and
**3D Replay**. A light/dark theme toggle is available in the header and the
selection is remembered between launches.

## Launch

From the repository root:

```bash
npm install
npm start
```

On Windows, double-click `app.bat`. On macOS, make `app.command` executable
once and double-click it. PlatformIO's `pio` command must be installed for
build and flash operations.

## Operations

Use **Refresh ports**, **Auto-connect**, or **Connect selected**. A successful
connection is verified with `INFO`. The view also provides storage and DPS368
checks, ground-test status, live serial output, activity logs, firmware build
and flash, and the shake-triggered ground-test arm/abort controls. Ground-test
buttons affect real hardware; follow the power and pre-flight procedure in
[`README.md`](README.md).

## Configuration

The `config.h` page exposes supported values from `include/config.h`. Save the
file, then build and flash when ready. The Coast table page regenerates the
generated coast-table artifacts from rocket mass, temperature, humidity, and
pressure; it does not change flight-control source code.

## Analytics and replay

In **Analytics**, connect to the board and choose **List device flights**.
Download individual flights or all non-active flights, open the saved folder,
and manage local `flights` and `ground_tests` logs. The embedded dashboard
loads a selected `flight_data` folder and charts available telemetry.

In **3D Replay**, open a CSV or choose a saved log. Use playback, the scrubber,
speed and camera selectors, and the telemetry HUD. Left-drag orbits, right-drag
pans, and the wheel zooms. Horizontal track is estimated from the airframe
axis because the flight computer has no GPS; altitude, velocity, attitude, and
the other logged values are the source data.

## Storage and firmware safety

Downloaded flights are saved under
`C:\Users\srija\.airbrakes_ground_station\flight_data` on Windows. The app
uses category/run folders such as `flights/flight_0001/data.csv` and
`ground_tests/ground_test_0001/data.csv`. It does not edit anything under
`src/`; it sends the existing serial commands and can update
`include/config.h` when explicitly saved.
