#!/usr/bin/env python3
"""
Airbrakes App — the one file you actually run.

Everything else lives in app/ (kept separate so the launcher itself stays
tiny and stable). This just points Python at that folder and starts the
GUI — no command-line flags, no terminal usage required beyond the very
first `python "Airbrakes App.py"` while you're setting things up.

To get an actual double-click icon (no terminal at all, ever again), run
the one-time packaging script for your OS — see app/README_APP.md.
"""

import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(THIS_DIR, "app")
sys.path.insert(0, APP_DIR)

from main_window import App  # noqa: E402  (import after sys.path setup)

if __name__ == "__main__":
    App().mainloop()