"""
Serial protocol client for the Airbrakes V3 flight computer.

Mirrors the command set implemented in src/flash.cpp, including:
  LIST / CURRENT / GET <n> / DELETE <n> / INFO / GROUND_TEST ...
    and the 76-byte FlightRecord binary layout (<I16fII).

This module is GUI-framework-agnostic: it does blocking I/O and reports
progress via optional callbacks, so it's meant to be called from a
background thread (see app_threads.py) rather than directly from the
Tkinter mainloop.
"""

import struct
import time
import serial
import serial.tools.list_ports

RECORD_FORMAT = "<I16fII"
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)  # 76 bytes

FIELD_NAMES = [
    "time_ms", "altitude_m", "velocity_ms", "accel_bias_ms2",
    "raw_accel_ms2", "vertical_accel_ms2", "raw_baro_m", "motor_pos", "motor_vel",
    "motor_cmd_pos", "roll_rad", "pitch_rad", "yaw_rad",
    "Cd", "desired_Cd", "motor_current", "battery_voltage", "state", "axis_error",
]

STATE_NAMES = ["IDLE", "PAD", "BOOST", "CONTROL", "DESCENT", "LANDED",
               "GROUND_TEST_ARMED", "GROUND_TEST_RECORDING"]

USB_MANUFACTURER = "Srijan"
USB_PRODUCT = "AIrbrakes V3"


class FlightComputerError(Exception):
    pass


def find_board():
    """Return the most likely serial port for the flight computer, or None."""
    for port in serial.tools.list_ports.comports():
        if USB_MANUFACTURER in str(port.manufacturer):
            return port.device
        if USB_PRODUCT in str(port.product):
            return port.device
        desc = str(port.description)
        if "Pico" in desc or "RP2040" in desc or "RP2350" in desc:
            return port.device
    return None


def list_ports():
    """Return [(device, description), ...] for every serial port seen."""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


class FlightComputerLink:
    """One open serial connection to the board, with the flash.cpp protocol."""

    def __init__(self, port, baud=115200, timeout=1):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(2)  # RP2350 USB-serial needs a moment after DTR toggles

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def read_available_lines(self, limit=40):
        """Read already-buffered text without waiting.

        The ground-station monitor uses this between commands so it never
        blocks the UI. Protocol responses are still handled by the command
        methods; callers should pause the monitor while a command is active.
        """
        lines = []
        # Never let the GUI monitor wait on the normal command timeout.  A
        # boot/status message can be split across USB packets; temporarily
        # use a short read timeout and restore the command timeout afterwards.
        old_timeout = self.ser.timeout
        try:
            self.ser.timeout = 0.05
            for _ in range(limit):
                if not self.ser.in_waiting:
                    break
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    lines.append(line)
        finally:
            self.ser.timeout = old_timeout
        return lines

    def _send(self, cmd):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        time.sleep(0.1)

    def _read_lines_until(self, terminator, overall_timeout=3.0):
        lines = []
        deadline = time.time() + overall_timeout
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if line == terminator:
                    return lines
                lines.append(line)
        return lines  # timed out; return whatever we got

    def get_info(self):
        """Returns the raw 'FLASH:STORAGE: ...' payload string, or raises."""
        self._send("INFO")
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("FLASH:STORAGE:"):
                    return line.replace("FLASH:STORAGE:", "").strip()
        raise FlightComputerError("No response to INFO — check port/baud and that "
                                   "nothing else (e.g. pio device monitor) has the port open.")

    def list_flights(self):
        """Returns [{'file': 'flight_0.bin', 'num': 0, 'size': '12.30 KB', 'active': bool}, ...]"""
        self._send("LIST")
        results = []
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line == "FLASH:END":
                    break
                if line.startswith("FLASH:FLIGHT:"):
                    rest = line.replace("FLASH:FLIGHT:", "").strip()
                    active = "[ACTIVE]" in rest
                    rest = rest.replace("[ACTIVE]", "").strip()
                    # rest looks like: flight_3.bin (12.30 KB)
                    if "(" in rest:
                        fname, size = rest.split("(", 1)
                        fname = fname.strip()
                        size = size.rstrip(")").strip()
                    else:
                        fname, size = rest, "?"
                    num = None
                    try:
                        num = int(fname.replace("/flight_", "").replace("flight_", "")
                                   .replace(".bin", ""))
                    except ValueError:
                        pass
                    results.append({"file": fname, "num": num, "size": size, "active": active})
        return results

    def current_flight(self):
        self._send("CURRENT")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("FLASH:CURRENT:"):
                    try:
                        return int(line.replace("FLASH:CURRENT:", "").strip())
                    except ValueError:
                        return None
        return None

    def ground_test_start(self):
        """Arm the explicit shake-triggered ground test, or raise on refusal."""
        self._send("GROUND_TEST START")
        return self._ground_test_response()

    def ground_test_abort(self):
        """Immediately stop a ground test and command the brakes closed."""
        self._send("GROUND_TEST ABORT")
        return self._ground_test_response()

    def ground_test_status(self):
        self._send("GROUND_TEST STATUS")
        return self._ground_test_response()

    def _ground_test_response(self):
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("GROUND_TEST:ERROR"):
                    raise FlightComputerError(line)
                if line.startswith("GROUND_TEST:"):
                    return line
        raise FlightComputerError("No response to ground-test command.")

    def download_flight(self, flight_num, progress_cb=None):
        """
        Downloads /flight_<n>.bin and returns a list of dict records
        (already unpacked from the 76-byte binary format).
        progress_cb(bytes_received) is called periodically if given.
        """
        self._send(f"GET {flight_num}")

        deadline = time.time() + 5.0
        started = False
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line == "FLASH:DATA_START":
                    started = True
                    break
                if line.startswith("FLASH:ERROR"):
                    raise FlightComputerError(line)
        if not started:
            raise FlightComputerError("Device did not start sending data (no FLASH:DATA_START).")

        binary_data = bytearray()
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting)
                if b"FLASH:END" in chunk:
                    end_pos = chunk.find(b"FLASH:END")
                    binary_data.extend(chunk[:end_pos])
                    break
                binary_data.extend(chunk)
                deadline = time.time() + 5.0
                if progress_cb:
                    progress_cb(len(binary_data))

        if not binary_data:
            raise FlightComputerError("No data received for that flight.")

        remainder = len(binary_data) % RECORD_SIZE
        if remainder:
            # The protocol terminator is outside the binary payload. A
            # remainder therefore indicates truncation/noise, not a partial
            # record that should be silently accepted.
            raise FlightComputerError(
                f"Corrupt flight payload: {len(binary_data)} bytes is not a "
                f"multiple of {RECORD_SIZE} ({remainder} trailing bytes)."
            )
        num_records = len(binary_data) // RECORD_SIZE
        records = []
        for i in range(num_records):
            offset = i * RECORD_SIZE
            chunk = binary_data[offset:offset + RECORD_SIZE]
            if len(chunk) < RECORD_SIZE:
                break
            try:
                values = struct.unpack(RECORD_FORMAT, chunk)
            except struct.error:
                continue
            rec = dict(zip(FIELD_NAMES, values))
            rec["state_name"] = (STATE_NAMES[rec["state"]]
                                  if rec["state"] < len(STATE_NAMES)
                                  else f"UNKNOWN({rec['state']})")
            records.append(rec)
        return records

    def delete_flight(self, flight_num):
        self._send(f"DELETE {flight_num}")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line == "FLASH:DELETED":
                    return True
                if line.startswith("FLASH:ERROR"):
                    raise FlightComputerError(line)
        raise FlightComputerError("No response to DELETE (timed out).")
