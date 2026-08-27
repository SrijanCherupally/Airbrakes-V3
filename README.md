# Airbrakes V3

Airbrakes V3 is an experimental active-airbrakes platform. This repository contains the embedded firmware, Electron ground station, simulation helpers, CAN support, and recorded-data tools used to develop and test it.

> **Safety first:** This is research and development software for hardware that can move and deploy actuators. Follow your team's test plans, launch rules, adult-supervision requirements, and electrical/mechanical safety procedures. This README is not a substitute for those procedures.

## Choose your starting point

| If you want to… | Start here | First command |
| --- | --- | --- |
| Build firmware | [Firmware](#firmware) | `pio run -e AirbrakesV3` |
| Open the ground station | [Ground station](#ground-station) | `npm install` then `npm start` |
| Run PlatformIO tests | [`test/README`](test/README) | `pio test -e AirbrakesV3` |
| Regenerate the coast lookup table | [`sim/README.md`](sim/README.md) | `python sim/generate_coast_table.py` |
| Understand recorded logs | [`DATA.md`](DATA.md) | — |
| Contribute a change | [`CONTRIBUTING.md`](CONTRIBUTING.md) | — |

## Prerequisites

Install only the tools needed for the work you plan to do:

- **Firmware:** [PlatformIO](https://platformio.org/) through VS Code or the [PlatformIO CLI](https://docs.platformio.org/en/latest/core/installation/index.html).
- **Ground station:** Node.js and npm. The app currently uses Electron 35, SerialPort, Papa Parse, and Plotly; `npm install` installs the project dependencies.
- **Simulation:** Python 3 and NumPy. Install NumPy with `python -m pip install numpy` if it is not already available.
- **Hardware work:** the appropriate board, sensors, motor-control hardware, cables, and your team's approved test setup. Hardware procedures are maintained separately from this software guide.

## Quick start

Clone the repository, then open a terminal in the repository root. The commands below are independent; run the ones for your task.

### Firmware

Build the RP2350/Pico 2 target:

```bash
pio run -e AirbrakesV3
```

The board, framework, upload settings, serial speed, and dependencies are defined in [`platformio.ini`](platformio.ini). Connect hardware and upload firmware only after reviewing the applicable test procedure.

### Ground station

Install JavaScript dependencies and start the Electron app:

```bash
npm install
npm start
```

Convenience launchers are also provided:

- Windows: double-click [`app.bat`](app.bat).
- macOS/Linux: run `bash app.command` from a terminal. On macOS, make it executable once with `chmod +x app.command`.

For connection, configuration, analytics, and 3D replay instructions, see [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md).

### Tests

Run the PlatformIO test command for this environment:

```bash
pio test -e AirbrakesV3
```

Read [`test/README`](test/README) before adding tests, especially if a test needs physical hardware.

### Simulation and analysis

The coast-table generator uses NumPy and writes generated lookup data for both Python and C++ consumers:

```bash
python sim/generate_coast_table.py
```

The script also updates mass and air-density constants in `include/config.h`. Review its output before building firmware. See [`sim/README.md`](sim/README.md) for inputs, generated files, and reproducibility notes.

Recorded data can be explored in the ground station or inspected with the workflows described in [`DATA.md`](DATA.md).

## Repository layout

| Directory or file | What it contains |
| --- | --- |
| `src/` | Firmware implementations, including sensors, estimation, control, state, CAN, and logging. |
| `include/` | Shared firmware headers, configuration, and generated C++ lookup data. See [`include/README`](include/README). |
| `platformio.ini` | The PlatformIO environment and firmware dependencies. |
| `desktop/` | Electron main process, preload bridge, renderer, analytics, and 3D replay code. |
| `sim/` | Simulation scripts and generated coast-table data. See [`sim/README.md`](sim/README.md). |
| `tools/` | Standalone development aids that are not automatically built as firmware. See [`tools/README.md`](tools/README.md). |
| `lib/` | Project-local libraries, including the patched CAN library. See [`lib/README`](lib/README). |
| `test/` | PlatformIO test sources and test notes. See [`test/README`](test/README). |
| `flight_data/` | Recorded flight and ground-test data when present. See [`DATA.md`](DATA.md). |
| `APP_INSTRUCTIONS.md` | Ground-station installation and user workflows. |
| `DATA.md` | Storage format, serial commands, downloads, and data validation. |
| `CONTRIBUTING.md` | Branch, code, documentation, and pull-request guidance. |

### Source, generated files, and recorded data

- Treat files in `src/`, `include/`, `desktop/`, `sim/`, and `tools/` as source unless a file says it is generated.
- Do not hand-edit `sim/coast_table.py` or `include/coast_table.h`; regenerate them with `sim/generate_coast_table.py`.
- The generator updates selected values in `include/config.h`; review that change as part of the same update.
- `flight_data/` contains recorded datasets, not firmware source. Keep original copies while checking downloads and avoid committing personal or unnecessary data.
- `lib/` contains a project-local CAN implementation because the project needs MCP2515 20 MHz crystal support. Do not replace it with a registry dependency without checking the compatibility implications.

## Firmware overview

Firmware responsibilities are divided into focused layers:

- **Hardware:** board pins, sensors, storage, and motor-control interfaces.
- **Estimation:** inertial/barometric processing, orientation, and state estimation.
- **Flight state:** high-level state definitions and transitions.
- **Control:** model-based calculations and actuator commands.
- **Logging:** structured records written to onboard storage.
- **Configuration:** tunable constants and hardware-specific settings.

Useful entry points include:

| Concern | Start with |
| --- | --- |
| Program entry point | `src/main.cpp` |
| Configuration | `include/config.h` |
| Hardware interfaces | `include/hardware.h`, `src/hardware.cpp` |
| Flight states | `include/state.h`, `src/state.cpp` |
| Estimation | `include/estimator.h`, `src/estimator.cpp`, `src/kalman.cpp` |
| Control | `include/control.h`, `src/control.cpp` |
| Logging | `include/flash.h`, `src/flash.cpp` |

## Ground-station overview

The desktop app is split into focused components:

- `desktop/main.js` — Electron main process and local-system integration.
- `desktop/preload.js` — controlled main-process/renderer API bridge.
- `desktop/renderer.html` — application shell.
- `desktop/renderer.js` — renderer-side behavior.
- `desktop/analytics.js` — data browsing and charts.
- `desktop/flight3d.js` — recorded-telemetry replay.

The app can connect to the board, show diagnostics, change supported configuration values, download records, chart logs, and replay CSV data. See [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) before using a hardware-connected workflow.

## Troubleshooting first steps

### `pio` is not recognized

Install PlatformIO, restart the terminal or VS Code, and confirm the PlatformIO executable is on your `PATH`. The ground station can still be developed without PlatformIO, but firmware build and upload integration require it.

### The Electron app will not start

Run `npm install` from the repository root, then run `npm start` again. Read the first error in the terminal output; later errors may only be follow-on failures.

### No serial port appears

Reconnect the board, close other serial-monitor applications, and refresh the available ports. Do not use a hardware-connected operation until the selected port is confirmed to be the intended board.

### A generated file looks out of date

Regenerate it from the source script instead of editing the generated file directly:

```bash
python sim/generate_coast_table.py
```

Review the resulting diff, including any changes to `include/config.h`.

## Documentation map

- [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md) — install and use the ground station.
- [`DATA.md`](DATA.md) — recorded-data formats, storage, serial transfers, and validation.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to make and validate changes.
- [`include/README`](include/README) — shared firmware header conventions.
- [`lib/README`](lib/README) — project-local library conventions.
- [`sim/README.md`](sim/README.md) — simulation and coast-table generation.
- [`test/README`](test/README) — PlatformIO test guidance.
- [`tools/README.md`](tools/README.md) — standalone development utilities.

## License

See [`LICENSE`](LICENSE) for the project's license terms.
