# Flight data

This document covers the flight-log lifecycle: firmware storage, the serial
protocol, desktop downloads, local log layout, analytics, and troubleshooting.
General project setup belongs in [`README.md`](README.md); GUI-specific
instructions belong in
[`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md).

## Storage on the board

The RP2350 stores logs in the onboard LittleFS partition. Each flight is a
file named `/flight_<N>.bin`; flight numbers are not reused. A file contains
76-byte `FlightRecord` values:

| Field | Type |
| --- | --- |
| `time_ms` | `uint32_t` |
| `altitude_m` through `battery_voltage` | 16 `float` values, including raw and corrected vertical acceleration |
| `state`, `axis_error` | 2 × `uint32_t` |

The Python struct format is `<I16fII`. The fields are defined in
`src/flash.cpp` and must stay in the same order as `desktop/main.js`.
The state values are `IDLE`, `PAD`, `BOOST`, `CONTROL`, `DESCENT`, `LANDED`,
`GROUND_TEST_ARMED`, and `GROUND_TEST_RECORDING`.

Logging is rate-limited to 100 Hz. Records are buffered in RAM in a 2048-record
queue and flushed periodically from the main loop, keeping filesystem writes
off the 500 Hz estimator path. The firmware warns when LittleFS has less than
4 MB free. Check this with `INFO` before flight.

## Serial protocol

The board uses **115200 baud** and newline-terminated commands. Responses use
the `FLASH:` prefix.

| Command | Purpose |
| --- | --- |
| `INFO` | Report used and total storage. |
| `LIST` | List flight files and mark the active file. |
| `CURRENT` | Report the flight number currently being logged. |
| `GET <n>` | Stream flight `<n>` as `FLASH:DATA_START:<byte_count>`, exactly that many binary bytes, then `FLASH:END`. |
| `DELETE <n>` | Delete flight `<n>` unless it is active. |

The firmware flushes and temporarily closes an active file before serving
`GET`, then reopens it for logging. Never delete a flight until its download
has been checked.

## Downloading flights

### Desktop GUI

Run `npm start`, open **Analytics**, connect to the board, and choose **List
device flights**. Download one flight or choose **Download all safe copies**;
the latter skips the active flight. Verify the saved CSV and charts before
deleting the board copy. **Open saved flight folder** opens local storage.

Logs are stored under `~/.airbrakes_ground_station/flight_data/` (equivalent to
`C:\\Users\\<user>\\.airbrakes_ground_station\\flight_data` on Windows):

```text
flight_data/
  flights/flight_0001/data.csv
  ground_tests/ground_test_0001/data.csv
```

The dashboard can select this folder and browse both categories. It charts
available altitude, velocity, acceleration, attitude, drag coefficient,
airbrake position, battery, and state-timeline columns. The **3D Replay** view
opens a downloaded CSV or saved log and supports playback, scrubbing, 0.1×–4×
speed, multiple camera modes, reframe, and orbit/pan/zoom controls. Horizontal
ground track is reconstructed from the airframe axis because the board has no
GPS; it is not measured position.

The current repository does not ship a separate command-line downloader;
listing, downloading, and deleting are provided by the unified desktop app.
The app preserves the firmware's serial protocol and local data location.

## Recommended after-flight sequence

1. Connect the board over USB and close any serial monitor.
2. Run `LIST` or the downloader's list command.
3. Download the flight.
4. Check that the CSV is non-empty and spans the expected flight duration.
5. Delete the board copy only after the local copy is safe.
6. Use `sim/coast_table.py`, the Analytics charts, or 3D Replay for model
   comparisons.

## Troubleshooting

- **Board not found:** close other serial programs, reconnect USB, or choose
  the port manually. The expected USB identifiers are `Srijan` and
  `Airbrakes V3`.
- **Download hangs:** make sure `pio device monitor` or another application is
  not using the same port.
- **Low or failed storage:** download existing flights and delete them. A
  reformat is a last resort because it erases unretrieved data.
- **No flight listed:** logging starts only after the state machine leaves
  `IDLE` and begins recording.
- **Corrupt record warning:** the downloader skips an incomplete trailing
  record; verify the remaining row count and transfer again if needed.
