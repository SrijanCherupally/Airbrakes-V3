#!/bin/bash

# Double-click this file in Finder to launch the Airbrakes ground station.
# It keeps the terminal open so startup errors remain visible.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    printf 'Python 3 is required to run the Airbrakes ground station.\n'
    printf 'Install Python 3 from https://www.python.org/downloads/macos/\n'
    read -r -p 'Press Return to close...' _
    exit 1
fi

"$PYTHON" "$SCRIPT_DIR/app.py"
status=$?

if [ "$status" -ne 0 ]; then
    printf '\nThe Airbrakes ground station exited with status %s.\n' "$status"
    read -r -p 'Press Return to close...' _
fi

exit "$status"