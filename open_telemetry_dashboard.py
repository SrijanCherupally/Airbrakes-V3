"""Serve the interactive telemetry dashboard and open it in the browser."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse, functools, webbrowser
import shutil
import json

DEFAULT = Path(r"C:\Users\srija\.airbrakes_ground_station\flight_data\ground_test_0001_2026-08-07_090400_277727\data.csv")
ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", type=Path, default=DEFAULT)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.csv.exists():
        raise SystemExit(f"CSV or folder not found: {args.csv}")
    staged = []
    if args.csv.is_dir():
        files = sorted(args.csv.glob("*.csv"))
        if not files:
            raise SystemExit(f"No CSV files found in: {args.csv}")
        for index, source in enumerate(files):
            target = ROOT / ("data.csv" if index == 0 else f"data_{index}.csv")
            shutil.copyfile(source, target)
            staged.append(target)
    else:
        target = ROOT / "data.csv"
        shutil.copyfile(args.csv, target)
        staged.append(target)
    manifest = ROOT / "data_manifest.json"
    manifest.write_text(json.dumps([target.name for target in staged]), encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
    url = f"http://127.0.0.1:{args.port}/telemetry_dashboard.html"
    print(f"Opening {url}. Press Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for target in staged:
            target.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
