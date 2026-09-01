# Airbrakes V3 Ground Station

The ground station is an Electron desktop application for connecting to the project hardware, viewing diagnostics, managing configuration, downloading recorded data, and exploring flight logs.

## Launch

From the repository root:

```bash
npm install
npm start
```

PlatformIO should be installed separately if you need the application's firmware build/flash integration.

On Windows, `app.bat` is the convenience launcher. On macOS, make `app.command` executable once before using it.

## Application views

The application is organized into four primary views:

| View | Purpose |
| --- | --- |
| **Operations** | Connection status, diagnostics, serial output, and supported development operations |
| **Configuration** | Edit supported project configuration values |
| **Analytics** | Browse downloaded data and inspect telemetry charts |
| **3D Replay** | Replay a recorded CSV and inspect its telemetry interactively |

A light/dark theme setting is available in the application header and is remembered between launches.

## Operations

Use the connection controls to select and connect to the appropriate serial port. The application can display board responses and project diagnostics through the serial monitor.

The Operations view also exposes the project's supported storage and diagnostic commands. These controls communicate with the existing firmware interface; they do not replace the project's hardware or testing procedures.

For hardware-related testing, follow the team's current safety and supervision requirements and the procedures maintained with the hardware documentation.

## Configuration

The Configuration view exposes supported values from `include/config.h`.

After changing configuration:

1. Review the resulting values carefully.
2. Save only when the intended change is understood.
3. Build the firmware and review compiler output before using the result elsewhere.

Simulation-generated artifacts should be regenerated through their documented tools rather than manually edited.

## Analytics

The Analytics view can list recorded data, download supported records from the connected device, and inspect locally saved logs.

Downloaded data is organized under the application's local data directory. A typical layout is:

```text
flight_data/
  flights/flight_0001/data.csv
  ground_tests/ground_test_0001/data.csv
```

The folder is the repository-root `flight_data/` directory. Downloaded flights and ground tests are kept there so they can be versioned with the project.

Use the Analytics view to inspect available telemetry and compare recorded runs. Keep original data copies until you have verified that the downloaded files are complete.

## 3D Replay

The 3D Replay view accepts a saved CSV/log and provides playback controls, a scrubber, playback speed, camera controls, and a telemetry display.

The visualization is a reconstruction from recorded telemetry. It should not be interpreted as a direct measurement of quantities that the hardware does not record.

## Development architecture

The main desktop components are:

- `desktop/main.js` — Electron main process and local-system integration.
- `desktop/preload.js` — renderer/main-process API bridge.
- `desktop/renderer.html` — primary application shell.
- `desktop/renderer.js` — renderer-side application behavior.
- `desktop/analytics.js` — data analytics and charting.
- `desktop/flight3d.js` — replay visualization.

When changing a user-facing workflow, update this document if the workflow is no longer accurately described.

## Troubleshooting

### Application will not start

Run `npm install` again from the repository root and check the terminal output from `npm start` for the first reported error.

### Serial port is unavailable

Close other applications that may have the port open, reconnect the board, and refresh the available ports. If the problem persists, check the operating system's device list and the project's hardware documentation.

### Data download does not complete

Make sure another serial-monitor application is not using the same port. Retry the transfer and verify the resulting file before removing any original copy.

### Configuration change is not reflected

Confirm that the file was saved, rebuild the relevant software, and verify that the application is using the intended project checkout.

## Related documentation

- [`README.md`](README.md) — repository overview and development orientation.
- [`DATA.md`](DATA.md) — data formats, storage, serial interfaces, and analysis.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution and pull-request guidelines.
