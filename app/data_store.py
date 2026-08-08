"""Persistent local storage for downloaded flights and ground tests."""
import csv, hashlib, json, os, shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from serial_link import FIELD_NAMES

class DataStore:
    def __init__(self, root_dir):
        self.root = root_dir
        os.makedirs(self.root, exist_ok=True)
        self.index_path = os.path.join(self.root, "index.json")
        if not os.path.exists(self.index_path): self._write_index([])
        self._migrate_legacy_names()
        # Clean up copies created by older versions before the history view
        # reads them. The newest copy of each identical CSV is retained.
        self.remove_duplicates()

    def _read_index(self):
        try:
            with open(self.index_path, encoding="utf-8") as f: value = json.load(f)
            return value if isinstance(value, list) else []
        except (OSError, ValueError): return []

    def _write_index(self, data):
        with open(self.index_path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

    def _migrate_legacy_names(self):
        """Rename old timestamp-suffixed folders to stable numbered names."""
        index = self._read_index()
        changed = False
        next_num = {}
        for entry in index:
            old_name = entry.get("folder", "")
            category = entry.get("category", "flight")
            if not old_name or category not in ("flight", "ground_test"):
                continue
            # Only migrate names such as ground_test_0001_2026-08-07_...
            prefix = f"{category}_"
            if not old_name.startswith(prefix) or len(old_name.split("_")) < 3:
                continue
            try:
                old_num = int(old_name[len(prefix):].split("_", 1)[0])
            except ValueError:
                continue
            candidate = f"{category}_{old_num:04d}"
            old_path = os.path.join(self.root, old_name)
            new_path = os.path.join(self.root, candidate)
            if os.path.isdir(old_path) and old_name != candidate and not os.path.exists(new_path):
                os.rename(old_path, new_path)
                entry["folder"] = candidate
                entry["csv_path"] = os.path.join(new_path, f"{candidate}.csv")
                legacy_csv = os.path.join(new_path, "data.csv")
                clean_csv = entry["csv_path"]
                if os.path.isfile(legacy_csv) and not os.path.exists(clean_csv):
                    os.rename(legacy_csv, clean_csv)
                changed = True
            next_num[category] = max(next_num.get(category, 0), old_num)
        if changed:
            self._write_index(index)

    @staticmethod
    def _records_fingerprint(records):
        payload = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def save_flight(self, flight_num, records, config_h_path=None, notes="", category=None):
        fingerprint = self._records_fingerprint(records)
        category = category or ("ground_test" if any(r.get("state_name", "").startswith("GROUND_TEST") for r in records) else "flight")
        # A repeated ground test can legitimately contain identical samples;
        # every download must receive its own local sequence number.
        if category != "ground_test":
            for entry in self._read_index():
                if entry.get("fingerprint") == fingerprint:
                    folder = os.path.join(self.root, entry.get("folder", ""))
                    if os.path.isdir(folder): return folder
        # The board number is a device slot (often 0000/0001), not a unique
        # local flight ID.  Use a monotonic local sequence for readable names.
        used = []
        for item in self._read_index():
            if item.get("category", "flight") == category:
                try:
                    used.append(int(str(item.get("folder", "")).split("_")[1]))
                except (IndexError, ValueError):
                    pass
        local_num = max(used, default=0) + 1
        folder_name = f"{category}_{local_num:04d}"
        # Be robust if an old folder/index entry already occupies the name.
        while os.path.exists(os.path.join(self.root, folder_name)):
            local_num += 1
            folder_name = f"{category}_{local_num:04d}"
        folder = os.path.join(self.root, folder_name); os.makedirs(folder, exist_ok=False)
        csv_path = os.path.join(folder, f"{folder_name}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f); writer.writerow(FIELD_NAMES + ["state_name"])
            for r in records: writer.writerow([r.get(k) for k in FIELD_NAMES] + [r.get("state_name")])
        if config_h_path and os.path.exists(config_h_path): shutil.copyfile(config_h_path, os.path.join(folder, "config_snapshot.h"))
        downloaded = datetime.now(ZoneInfo("America/Los_Angeles"))
        meta = {"flight_num": flight_num, "downloaded_at": downloaded.strftime("%Y-%m-%d %I:%M:%S %p %Z"), "num_records": len(records), "duration_s": records[-1].get("time_ms", 0) / 1000.0 if records else 0, "max_altitude_m": max((r.get("altitude_m") for r in records), default=None), "notes": notes, "category": category, "fingerprint": fingerprint}
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f: json.dump(meta, f, indent=2)
        index = self._read_index(); index.append({"folder": folder_name, "csv_path": csv_path, **meta}); self._write_index(index)
        return folder

    def list_flights(self):
        entries = []
        for entry in self._read_index():
            folder = os.path.join(self.root, entry.get("folder", ""))
            csv_path = os.path.join(folder, f"{entry.get('folder', '')}.csv")
            if not os.path.isfile(csv_path):
                csv_path = os.path.join(folder, "data.csv")
            if os.path.isfile(csv_path): entry["csv_path"] = csv_path; entries.append(entry)
        return sorted(entries, key=lambda e: e.get("downloaded_at", ""), reverse=True)

    def list_by_category(self, category=None):
        entries = self.list_flights()
        return entries if category is None else [e for e in entries if e.get("category", "flight") == category]

    def delete_local(self, folder_name):
        self._write_index([e for e in self._read_index() if e.get("folder") != folder_name])
        folder = os.path.join(self.root, folder_name)
        if os.path.isdir(folder): shutil.rmtree(folder)

    def delete_all_local(self):
        for entry in self._read_index():
            folder = os.path.join(self.root, entry.get("folder", ""))
            if os.path.isdir(folder): shutil.rmtree(folder)
        self._write_index([])

    def remove_duplicates(self):
        index = self._read_index(); seen = set(); kept = []
        for entry in sorted(index, key=lambda e: e.get("downloaded_at", ""), reverse=True):
            folder = os.path.join(self.root, entry.get("folder", ""))
            path = os.path.join(folder, f"{entry.get('folder', '')}.csv")
            if not os.path.isfile(path): path = os.path.join(folder, "data.csv")
            if not os.path.isfile(path): continue
            if entry.get("category") == "ground_test":
                kept.append(entry)
                continue
            with open(path, "rb") as f: digest = hashlib.sha256(f.read()).hexdigest()
            if digest in seen:
                folder = os.path.dirname(path)
                if os.path.isdir(folder): shutil.rmtree(folder)
                continue
            seen.add(digest); entry.setdefault("fingerprint", digest); kept.append(entry)
        if len(kept) != len(index): self._write_index(kept)
        return len(index) - len(kept)
