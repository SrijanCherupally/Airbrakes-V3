#!/bin/bash

# Double-click this file in Finder to launch the Airbrakes ground station.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

npm start
status=$?

if [ "$status" -ne 0 ]; then
    printf '\nThe Airbrakes ground station exited with status %s.\n' "$status"
    read -r -p 'Press Return to close...' _
fi

exit "$status"
