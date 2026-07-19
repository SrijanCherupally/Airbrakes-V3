#!/usr/bin/env python3
"""
Flight Data Manager for Airbrakes V3 Flight Computer

Downloads binary flight data logged over LittleFS on the Pico 2 (RP2350)
and converts it to CSV. Talks to the same serial command protocol
implemented in src/flash.cpp (LIST / GET <n> / DELETE <n> / INFO), and
unpacks the same 68-byte FlightRecord struct written there.

Based on the flight data manager from Nv7's rock7
(https://github.com/Nv7-GitHub/rock7), adapted for Airbrakes V3's USB
descriptor, board, and record layout.
"""

import serial
import serial.tools.list_ports
import os
import sys
import time
import struct
from datetime import datetime

# Binary record format (68 bytes): uint32_t time_ms, 14 floats
# (altitude, velocity, accel_bias, raw_accel, raw_baro, motor_pos, motor_vel,
# motor_cmd_pos, roll, pitch, yaw, Cd, desired_Cd, motor_current),
# uint32_t state, uint32_t axis_error.
# Must match the FlightRecord struct in src/flash.cpp exactly.
RECORD_FORMAT = '<I14fII'
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

# Matches platformio.ini's usb_manufacturer/usb_product for this board.
USB_MANUFACTURER = "Srijan"
USB_PRODUCT = "AIrbrakes V3"

# CSV header must match the field order in RECORD_FORMAT above.
CSV_HEADER = (
    "time_ms,altitude_m,velocity_ms,accel_bias_ms2,raw_accel_ms2,raw_baro_m,"
    "motor_pos,motor_vel,motor_cmd_pos,roll_rad,pitch_rad,yaw_rad,"
    "Cd,desired_Cd,motor_current_A,state,axis_error\n"
)

STATE_NAMES = ['IDLE', 'PAD', 'BOOST', 'CONTROL', 'DESCENT', 'LANDED']


def find_pico():
    """Find the Airbrakes V3 Pico 2 serial port by USB descriptor."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if USB_MANUFACTURER in str(port.manufacturer):
            return port.device
        if USB_PRODUCT in str(port.product):
            return port.device
        # Fallback: any RP2040/RP2350-family Pico descriptor.
        if "Pico" in str(port.description) or "RP2040" in str(port.description) \
                or "RP2350" in str(port.description):
            return port.device
    return None


def send_command(ser, command):
    """Send a command and wait briefly for the device to process it."""
    ser.write((command + '\n').encode())
    time.sleep(0.1)


def list_flights(ser):
    """Request the list of flight files from the device."""
    print("\nRequesting flight list from Airbrakes V3...")
    ser.reset_input_buffer()
    send_command(ser, "LIST")

    flights = []
    timeout = time.time() + 2
    while time.time() < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith("FLASH:FLIGHT:"):
                flights.append(line.replace("FLASH:FLIGHT:", "").strip())
            elif line == "FLASH:END":
                break

    return flights


def get_current_flight(ser):
    """Get the currently-active flight number, if any is being logged."""
    flights = list_flights(ser)
    for flight in flights:
        if "[ACTIVE]" in flight:
            parts = flight.split("_")
            if len(parts) >= 2:
                try:
                    return int(parts[1].split(".")[0])
                except ValueError:
                    pass
    return None


def download_flight(ser, flight_num, output_dir="flight_data", auto_delete=False):
    """Download a specific flight file and convert it to CSV."""
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"flight_{flight_num}_{timestamp}.csv")

    print(f"\nDownloading flight {flight_num}...")
    ser.reset_input_buffer()
    send_command(ser, f"GET {flight_num}")

    timeout = time.time() + 5
    data_started = False
    while time.time() < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line == "FLASH:DATA_START":
                data_started = True
                break
            elif line.startswith("FLASH:ERROR"):
                print(f"✗ {line}")
                return None

    if not data_started:
        print("✗ No response from device")
        return None

    binary_data = bytearray()
    timeout = time.time() + 10

    while time.time() < timeout:
        if ser.in_waiting:
            chunk = ser.read(ser.in_waiting)
            if b'FLASH:END' in chunk:
                end_pos = chunk.find(b'FLASH:END')
                binary_data.extend(chunk[:end_pos])
                break
            binary_data.extend(chunk)
            timeout = time.time() + 5

    if not binary_data:
        print("✗ No data received")
        return None

    num_records = len(binary_data) // RECORD_SIZE
    remainder = len(binary_data) % RECORD_SIZE

    print(f"Converting {num_records} records ({len(binary_data)} bytes)...")
    if remainder != 0:
        print(f"Warning: Ignoring {remainder} trailing byte(s) that do not form a full record")

    with open(output_file, 'w') as f:
        f.write(CSV_HEADER)

        for i in range(num_records):
            offset = i * RECORD_SIZE
            record_bytes = binary_data[offset:offset + RECORD_SIZE]

            if len(record_bytes) < RECORD_SIZE:
                break

            try:
                (time_ms, alt, vel, bias, raw_accel, raw_baro, motor_pos,
                 motor_vel, motor_cmd_pos, roll, pitch, yaw, Cd, desired_Cd,
                 motor_current, state_val, axis_error) = struct.unpack(
                    RECORD_FORMAT, record_bytes)

                state_name = (STATE_NAMES[state_val]
                              if state_val < len(STATE_NAMES)
                              else f'UNKNOWN({state_val})')
                f.write(
                    f"{time_ms},{alt:.4f},{vel:.4f},{bias:.4f},"
                    f"{raw_accel:.4f},{raw_baro:.4f},{motor_pos:.4f},"
                    f"{motor_vel:.4f},{motor_cmd_pos:.4f},{roll:.4f},"
                    f"{pitch:.4f},{yaw:.4f},{Cd:.4f},{desired_Cd:.4f},"
                    f"{motor_current:.4f},{state_name},{axis_error}\n"
                )
            except struct.error:
                print(f"Warning: Corrupt record at offset {offset}")
                continue

    print(f"✓ Saved {num_records} records to {output_file}")

    if auto_delete:
        current_flight = get_current_flight(ser)
        if current_flight is not None and int(flight_num) == current_flight:
            print(f"⚠ Skipping delete - flight {flight_num} is currently active")
        else:
            print(f"Deleting flight {flight_num} from device...")
            if delete_flight(ser, flight_num, quiet=True):
                print(f"✓ Deleted flight {flight_num} from device")

    return output_file


def delete_flight(ser, flight_num, quiet=False):
    """Delete a flight file from the device."""
    if not quiet:
        print(f"\nDeleting flight {flight_num}...")
    ser.reset_input_buffer()
    send_command(ser, f"DELETE {flight_num}")

    timeout = time.time() + 2
    while time.time() < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line == "FLASH:DELETED":
                if not quiet:
                    print("✓ Flight deleted")
                return True
            elif line.startswith("FLASH:ERROR"):
                if not quiet:
                    print(f"✗ {line}")
                return False
    return False


def get_storage_info(ser):
    """Get flash storage usage information."""
    ser.reset_input_buffer()
    send_command(ser, "INFO")

    timeout = time.time() + 2
    while time.time() < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith("FLASH:STORAGE:"):
                return line.replace("FLASH:STORAGE:", "").strip()
    return "Unknown"


def interactive_mode(port):
    """Interactive mode for managing flight data."""
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        time.sleep(2)

        print(f"Connected to Airbrakes V3 on {port}")

        while True:
            print("\n" + "=" * 50)
            print("Flight Data Manager")
            print("=" * 50)
            print("1. List flights")
            print("2. Download flight")
            print("3. Download all flights")
            print("4. Delete flight")
            print("5. Check storage")
            print("6. Exit")

            choice = input("\nChoice: ").strip()

            if choice == "1":
                flights = list_flights(ser)
                if flights:
                    print(f"\nFound {len(flights)} flight(s):")
                    for flight in flights:
                        if "[ACTIVE]" in flight:
                            print(f"  - {flight} ← Currently logging")
                        else:
                            print(f"  - {flight}")
                else:
                    print("\nNo flights found")

            elif choice == "2":
                flight_num = input("Enter flight number: ").strip()
                download_flight(ser, flight_num)

            elif choice == "3":
                print("\nDownloading all flights (will auto-delete after download)...")
                flights = list_flights(ser)
                if flights:
                    for flight_info in flights:
                        parts = flight_info.split("_")
                        if len(parts) >= 2:
                            flight_num = parts[1].split(".")[0]
                            download_flight(ser, flight_num, auto_delete=True)
                else:
                    print("\nNo flights to download")

            elif choice == "4":
                current_flight = get_current_flight(ser)
                flight_num = input("Enter flight number to delete: ").strip()

                if current_flight is not None and int(flight_num) == current_flight:
                    print(f"⚠ Cannot delete flight {flight_num} - it is currently active")
                else:
                    confirm = input(f"Delete flight {flight_num}? (yes/no): ")
                    if confirm.lower() == "yes":
                        delete_flight(ser, flight_num)

            elif choice == "5":
                info = get_storage_info(ser)
                print(f"\nStorage: {info}")

            elif choice == "6":
                break

            else:
                print("Invalid choice")

        ser.close()

    except KeyboardInterrupt:
        print("\n\nExiting...")
    except Exception as e:
        print(f"Error: {e}")


def main():
    print("Airbrakes V3 Flight Data Manager")
    print("-" * 40)

    port = find_pico()

    if not port:
        print("\nCouldn't auto-detect the flight computer. Available ports:")
        ports = serial.tools.list_ports.comports()
        for i, p in enumerate(ports):
            print(f"  {i}: {p.device} - {p.description}")

        if not ports:
            print("No serial ports found!")
            return

        choice = input("\nEnter port number or full path: ").strip()
        if choice.isdigit() and int(choice) < len(ports):
            port = ports[int(choice)].device
        else:
            port = choice

    print(f"Using port: {port}")

    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            flights = list_flights(ser)
            for flight in flights:
                print(flight)
            ser.close()
        elif sys.argv[1] == "get" and len(sys.argv) > 2:
            ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            download_flight(ser, sys.argv[2])
            ser.close()
        elif sys.argv[1] == "download-all":
            ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(2)
            flights = list_flights(ser)
            for flight_info in flights:
                parts = flight_info.split("_")
                if len(parts) >= 2:
                    flight_num = parts[1].split(".")[0]
                    download_flight(ser, flight_num, auto_delete=True)
            ser.close()
        else:
            print("Usage:")
            print("  python flight_data_manager.py              # Interactive mode")
            print("  python flight_data_manager.py list         # List flights")
            print("  python flight_data_manager.py get <num>    # Download flight")
            print("  python flight_data_manager.py download-all # Download all")
    else:
        interactive_mode(port)


if __name__ == "__main__":
    main()