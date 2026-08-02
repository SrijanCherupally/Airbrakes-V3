"""
Local flight-data database.

Every downloaded flight gets its own folder under the app's data directory:

    flight_data/
      flight_0000_2026-07-30_142310/
        data.csv
        meta.json
        config_snapshot.h      (copy of config.h at download time, if available)
      flight_0001_2026-08-01_091044/
        ...
      index.json

index.json is a flat list so the History tab can populate instantly without
re-reading every CSV.
"""

import csv
import json
import os
import shutil
from datetime import datetime

from serial_link import FIELD_NAMES


class DataStore:
    def __init__(self, root_dir):
        self.root = root_dir
        os.makedirs(self.root, exist_ok=True)
        self.index_path = os.path.join(self.root, "index.json")
        if not os.path.exists(self.index_path):
            self._write_index([])

    def _read_index(self):
        with open(self.index_path) as f:
            return json.load(f)

    def _write_index(self, data):
        with open(self.index_path, "w") as f:
            json.dump(data, f, indent=2)

    def save_flight(self, flight_num, records, config_h_path=None, notes=""):
        """Writes a new flight folder from a list of record dicts (see serial_link)."""
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        folder_name = f"flight_{flight_num:04d}_{ts}"
        folder = os.path.join(self.root, folder_name)
        os.makedirs(folder, exist_ok=True)

        csv_path = os.path.join(folder, "data.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            header = FIELD_NAMES + ["state_name"]  # keeps numeric `state` AND readable name
            writer.writerow(header)
            for r in records:
                row = [r.get(k) for k in FIELD_NAMES]
                row.append(r.get("state_name"))
                writer.writerow(row)

        config_snapshot = None
        if config_h_path and os.path.exists(config_h_path):
            config_snapshot = os.path.join(folder, "config_snapshot.h")
            shutil.copyfile(config_h_path, config_snapshot)

        meta = {
            "flight_num": flight_num,
            "downloaded_at": ts,
            "num_records": len(records),
            "duration_s": (records[-1]["time_ms"] / 1000.0) if records else 0,
            "max_altitude_m": max((r["altitude_m"] for r in records), default=None),
            "notes": notes,
        }
        with open(os.path.join(folder, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)

        index = self._read_index()
        index.append({
            "folder": folder_name,
            "csv_path": csv_path,
            **meta,
        })
        self._write_index(index)
        return folder

    def list_flights(self):
        """Newest first."""
        return list(reversed(self._read_index()))

    def delete_local(self, folder_name):
        index = self._read_index()
        index = [e for e in index if e["folder"] != folder_name]
        self._write_index(index)
        folder = os.path.join(self.root, folder_name)
        if os.path.exists(folder):
            shutil.rmtree(folder)
