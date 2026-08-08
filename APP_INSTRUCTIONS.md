# Airbrakes V3 Ground Station

The ground station is one Electron desktop application. It combines board
connection, pre-flight checks, DPS368 diagnostics, ground tests, configuration,
firmware operations, flight downloads, serial monitoring, and the interactive
analytics dashboard.

## Launch

From the repository root:

```bash
npm install
npm start
```

On Windows, double-click `app.bat`. On macOS, make `app.command` executable
once and double-click it. PlatformIO's `pio` command must be installed for
build and flash operations.

## Storage and firmware safety

Downloaded flights are saved under
`C:\Users\srija\.airbrakes_ground_station\flight_data` on Windows. The app
does not edit anything under `src/`; it only sends the existing serial commands
and can update `include/config.h` when explicitly saved.
