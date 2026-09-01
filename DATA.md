# Flight Data

This document describes the repository's recorded-data interfaces: onboard storage, the firmware serial protocol, desktop downloads, local file organization, and analysis workflows.

General project setup belongs in [`README.md`](README.md). Ground-station usage belongs in [`APP_INSTRUCTIONS.md`](APP_INSTRUCTIONS.md).

## Data flow

At a high level, recorded data moves through four stages:

1. The firmware records structured telemetry to onboard storage.
2. The desktop application retrieves supported records through the firmware's serial interface.
3. Downloaded records are stored locally as CSV data.
4. Analytics and replay tools read the local data for inspection.

Treat each stage as an interface. Changes to record layout or protocol should be reflected in both implementation and documentation.

## Onboard storage

The RP2350 firmware stores flight records in the onboard LittleFS partition. The current firmware uses files named `/flight_<N>.bin`; flight numbers are not reused.

Each record is a fixed-size binary structure. The current Python-compatible layout is:

```text
<I16fII
```

The record definition is implemented by the firmware and consumed by the desktop download path. Keep the field order synchronized whenever the format changes.

The logged state values currently include:

- `IDLE`
- `PAD`
- `BOOST`
- `CONTROL`
- `DESCENT`
- `LANDED`
- `GROUND_TEST_ARMED`
- `GROUND_TEST_RECORDING`

## Serial interface

The board communicates with the desktop application over a newline-terminated serial interface. The current connection uses **115200 baud**.

The primary storage commands are:

| Command | Purpose |
| --- | --- |
| `INFO` | Report storage information. |
| `LIST` | List stored flight files and identify the active file. |
| `CURRENT` | Report the current flight number. |
| `GET <n>` | Transfer a selected flight record. |
| `DELETE <n>` | Remove a stored flight when permitted by the firmware. |

Binary transfer responses are framed by the firmware's `FLASH:` protocol. The desktop application is the preferred client for normal data retrieval.

## Downloaded data

The unified desktop application provides the current download workflow. From **Analytics**, connect to the board, list the available records, and download the required data.

Local data is organized into category/run folders similar to:

```text
flight_data/
  flights/flight_0001/data.csv
  ground_tests/ground_test_0001/data.csv
```

The `flight_data/` directory is stored at the repository root and is intentionally versioned with the project. The desktop application writes there on every launch/download.

## Data integrity

Keep the original onboard copy until the downloaded data has been verified.

A basic verification pass should check that:

- the downloaded file exists and is non-empty;
- the expected columns are present;
- timestamps cover the expected recording interval;
- there are no unexpected gaps or malformed rows;
- the record count is plausible for the recording duration.

If a transfer is interrupted, retry the download rather than treating a partial file as a complete dataset.

## Analytics and replay

The desktop application's **Analytics** view can chart available telemetry and compare recorded runs.

The **3D Replay** view loads a saved CSV and provides playback, scrubbing, speed control, camera controls, and a telemetry HUD. The visualization is derived from the recorded data; it should not be treated as a direct measurement of quantities that are not present in the log.

## Changing the data format

Data formats should be treated as compatibility-sensitive interfaces.

When adding, removing, or reordering fields:

1. Update the firmware record definition.
2. Update the desktop parser/serializer.
3. Update any simulation or analysis code that consumes the affected fields.
4. Update tests where available.
5. Update this document.
6. Consider whether existing recorded files still need to be readable.

Avoid silent format changes. If a migration is necessary, document the old and new formats explicitly.

## Troubleshooting

### Board is not detected

Close other serial applications, reconnect the board, and refresh the available ports. Check the operating system device list if the port still does not appear.

### Download is interrupted

Ensure that only one application is using the serial port. Retry the download and verify the resulting file before deleting any source copy.

### A record appears incomplete

Check the transfer again and compare the resulting row count with the expected recording interval. Preserve the original source data while investigating.

### No flight appears in the list

Check that the firmware has created a recorded file and that the desktop application is connected to the intended board. Consult the firmware's current logging implementation before changing any data-handling code.

## Source of truth

For implementation details, inspect:

- firmware logging implementation under `src/`;
- logging interfaces under `include/`;
- desktop serial/download handling under `desktop/`;
- analysis and replay code under `desktop/` and `sim/`.

Documentation should describe the current implementation rather than preserve obsolete behavior for compatibility with older revisions.
