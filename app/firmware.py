"""
Wraps everything that would normally require an open terminal / VS Code:

  - `pio run`            (build)
  - `pio run -t upload`  (flash)
  - `python sim/generate_coast_table.py` (regenerate coast_table.h + config.h
    mass/air-density constants)

Each is run as a subprocess with stdout/stderr streamed line-by-line to a
callback, so the GUI can show a live scrolling console. If a script prompts
for input on stdin (generate_coast_table.py may, since we haven't seen its
exact interface), `send_input()` lets the GUI forward whatever the user
types in an input box straight to the subprocess — so it behaves like an
embedded terminal without the user ever opening one themselves.
"""

import importlib.util
import os
import subprocess
import sys
import threading


class LiveProcess:
    """A subprocess whose output is streamed to a callback, with a way to
    send input back to it (for interactive scripts)."""

    def __init__(self, cmd, cwd, on_line, on_exit=None):
        self.on_line = on_line
        self.on_exit = on_exit
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_env_with_utf8(),
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        for line in iter(self.proc.stdout.readline, ""):
            self.on_line(line.rstrip("\n"))
        self.proc.stdout.close()
        code = self.proc.wait()
        if self.on_exit:
            self.on_exit(code)

    def send_input(self, text):
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()

    def terminate(self):
        self.proc.terminate()

    def is_running(self):
        return self.proc.poll() is None


def _env_with_utf8():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _platformio_importable():
    """True if the SAME Python running this app can import platformio —
    this is independent of PATH, so it's true right after
    `pip install platformio` even before any shell restart."""
    try:
        return importlib.util.find_spec("platformio") is not None
    except (ImportError, ValueError):
        return False


def _pio_command():
    """
    Returns the argv prefix to invoke PlatformIO with. Prefers
    `<this python> -m platformio`, since that only depends on the package
    being pip-installed into this interpreter — not on the `pio` console
    script being on PATH (which is the #1 source of "pio not found" after
    a successful `pip install platformio`, especially when launched via a
    double-click launcher that may not inherit a full shell PATH).
    Falls back to the bare `pio` command if the module isn't importable
    but something named `pio` is on PATH anyway (e.g. installed via a
    different mechanism, like a system package or PlatformIO Core installer).
    """
    if _platformio_importable():
        return [sys.executable, "-m", "platformio"]
    from shutil import which
    if which("pio"):
        return ["pio"]
    return None


def check_platformio_installed():
    return _pio_command() is not None


def build_firmware(repo_path, on_line, on_exit=None):
    cmd = _pio_command()
    return LiveProcess(cmd + ["run"], cwd=repo_path, on_line=on_line, on_exit=on_exit)


def upload_firmware(repo_path, on_line, on_exit=None):
    cmd = _pio_command()
    return LiveProcess(cmd + ["run", "-t", "upload"], cwd=repo_path,
                        on_line=on_line, on_exit=on_exit)


def generate_coast_table(repo_path, on_line, on_exit=None):
    script = os.path.join(repo_path, "sim", "generate_coast_table.py")
    return LiveProcess([sys.executable, script], cwd=repo_path,
                        on_line=on_line, on_exit=on_exit)