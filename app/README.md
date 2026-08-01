# Airbrakes V3 Ground Station

Double-click `AirbrakesApp.pyw` on Windows. The app can detect the flight
computer, edit launch settings, regenerate the coast table, build and flash
the firmware, download and store flight logs, and plot the saved data.

One-time prerequisites are Python 3, PlatformIO Core, and the packages in
`app/requirements.txt`. The app does not require VS Code or a terminal during
normal flight preparation and recovery. A packaged Windows executable can be
produced later with PyInstaller once the hardware workflow is validated.

The app keeps downloaded CSV files in `flight_data/`. It intentionally skips
deleting active flights and only deletes flights from the board after an
explicit download-all operation.
