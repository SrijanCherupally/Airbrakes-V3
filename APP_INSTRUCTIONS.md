# Ground-station application

The Airbrakes V3 ground station is a Python desktop app for pre-flight setup,
firmware operations, flight downloads, and plotting. The launcher is kept at
the repository root so it remains stable while the implementation in `app/`
changes.

## Install and launch

From the repository root:

```bash
pip install -r app/requirements.txt
python app.py
```

On Windows, double-click `app.bat`. On macOS, make `app.command` executable
once, then double-click it in Finder:

```bash
chmod +x app.command
```

The app needs `pio` for build and flash operations; it is installed by the
requirements file or can be provided by an existing PlatformIO installation.

## Main workflows

### Pre-flight

- Edit the live tunables in `include/config.h`.
- Enter mass, temperature, humidity, and pressure to regenerate
  `include/coast_table.h` and the related constants.
- Run a build, flash the board, and check serial `INFO` before flight.

### Post-flight

- Connect the board over USB and list the flights stored on LittleFS.
- Download one or more flights, then delete device copies only after checking
  the local files.
- Browse downloaded flights and compare altitude, velocity, acceleration,
  brake position, Cd tracking, state transitions, and coast predictions.

For the record format, serial commands, storage safeguards, and the equivalent
CLI commands, see [`DATA.md`](DATA.md).

## Application modules

| Module | Responsibility |
| --- | --- |
| `app/modern_window.py` | Application window and startup |
| `app/main_window.py` | GUI layout and workflow coordination |
| `app/serial_link.py` | Board connection and serial protocol |
| `app/config_editor.py` | Reads and updates `include/config.h` |
| `app/coast_table_tool.py` | Runs the repository coast-table generator |
| `app/coast_lookup.py` | Loads the Python coast-table model |
| `app/firmware.py` | Runs PlatformIO commands |
| `app/data_store.py` | Stores downloaded flights and metadata |
| `app/plotting.py` | History and flight plots |

Downloaded GUI data defaults to:
`~/.airbrakes_ground_station/flight_data/`.

## Hardware boundary

The GUI can prepare files and invoke PlatformIO, but hardware-dependent steps
still require a real board: serial connection, flashing, ODrive operation, and
the final pre-flight checks. Keep only one program connected to the board's
serial port at a time.