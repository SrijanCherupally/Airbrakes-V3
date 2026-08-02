"""
Drives the REAL sim/generate_coast_table.py from the user's repo — loaded
fresh via importlib each time so it always reflects whatever's on disk —
but with mass/temperature/humidity/pressure supplied from the GUI instead
of requiring the user to hand-edit that script's module-level constants
(MASS_KG / TEMP_F / HUMIDITY_PCT / PRESSURE_HPA at the top of the file).

This calls the same functions main() calls (compute_air_density,
generate_coast_table, save_coast_table_to_file, save_coast_table_to_cpp,
update_config_header), so the output is byte-for-byte what running the
script directly would produce for those inputs — just without needing to
open the file in an editor first.
"""

import contextlib
import importlib.util
import io
import os
from pathlib import Path


def _load_module(repo_path):
    path = os.path.join(repo_path, "sim", "generate_coast_table.py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No generate_coast_table.py at {path}")
    spec = importlib.util.spec_from_file_location("_generate_coast_table_live", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _LineCallbackWriter(io.TextIOBase):
    """Redirect target for stdout: forwards completed lines to a callback
    as the underlying functions print(), instead of buffering silently."""

    def __init__(self, on_line):
        self.on_line = on_line
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.on_line(line)
        return len(s)

    def flush(self):
        if self._buf:
            self.on_line(self._buf)
            self._buf = ""


def current_defaults(repo_path):
    """Reads the script's current module-level constants, to pre-fill the
    GUI form with whatever was last used (rather than blank fields)."""
    mod = _load_module(repo_path)
    return {
        "mass_kg": mod.MASS_KG,
        "temp_f": mod.TEMP_F,
        "humidity_pct": mod.HUMIDITY_PCT,
        "pressure_hpa": mod.PRESSURE_HPA,
    }


def regenerate(repo_path, mass_kg, temp_f, humidity_pct, pressure_hpa, on_line=print):
    """
    Runs the full pipeline (air density -> lookup table -> coast_table.py
    + coast_table.h + config.h MASS/RHO update) with the given launch
    conditions, streaming progress to on_line(str) as it goes.
    Returns the (vel_range, cd_range, altitude_table) that were generated.
    """
    mod = _load_module(repo_path)
    here = Path(os.path.join(repo_path, "sim")).resolve()
    out_py = (here / mod.OUTPUT_PY).resolve()
    out_cpp = (here / mod.OUTPUT_CPP).resolve()
    config_h = (here / mod.CONFIG_H).resolve()

    writer = _LineCallbackWriter(on_line)
    with contextlib.redirect_stdout(writer):
        rho_air = mod.compute_air_density(temp_f, humidity_pct, pressure_hpa)
        print(f"Computed rho = {rho_air:.6f} kg/m^3 at {temp_f:.1f}F, "
              f"{humidity_pct:.1f}% RH, {pressure_hpa:.2f} hPa")

        vel_range, cd_range, altitude_table = mod.generate_coast_table(
            mass_kg=mass_kg,
            rho_air=rho_air,
            n_vel=mod.N_VEL,
            n_cd=mod.N_CD,
            vel_min=mod.VEL_MIN,
            vel_max=mod.VEL_MAX,
            cd_min=mod.CD_MIN,
            cd_max=mod.CD_MAX,
        )

        mod.save_coast_table_to_file(vel_range, cd_range, altitude_table, out_py)
        mod.save_coast_table_to_cpp(vel_range, cd_range, altitude_table, out_cpp)
        mod.update_config_header(config_h, mass_kg, rho_air, temp_f, humidity_pct)

        print("Done. coast_table.py, coast_table.h, and config.h "
              "(MASS/RHO) are all updated — rebuild + flash to apply.")

    writer.flush()
    return vel_range, cd_range, altitude_table
