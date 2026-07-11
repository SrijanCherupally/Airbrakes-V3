from __future__ import annotations

import re
from pathlib import Path

import numpy as np

# ----------------------------------
# Editable Configuration
# ----------------------------------

MASS = 0.608 # kg
TEMP = 70 # °F
HUMIDITY = 0.55 # %
PRESSURE = 1015 # hPa

N_VEL = 20                   # Make a 20×20 table
N_CD = 20
VEL_MIN = 0.0
VEL_MAX = 80.0               # Velocity from 0 to 80 m/s
CD_MIN = 0.492
CD_MAX = 5.492

def computeAirDensity(temp_f: float, humidity_pct: float, pressure_hpa: float = 1015.0) -> float:
    """Compute moist-air density from Fahrenheit temperature and RH%."""
    temp_c = (temp_f - 32.0) * (5.0 / 9.0)
    temp_k = temp_c + 273.15
    rh = max(0.0, min(100.0, humidity_pct)) / 100.0
    pressure_pa = pressure_hpa * 100.0

    # Magnus formula for saturation vapor pressure over water (Pa)
    sat_vapor_pa = 610.94 * np.exp((17.625 * temp_c) / (temp_c + 243.04))
    vapor_pa = rh * sat_vapor_pa
    dry_air_pa = pressure_pa - vapor_pa

    # Gas constants for dry air and water vapor.
    r_dry = 287.05
    r_vapor = 461.495
    rho = (dry_air_pa / (r_dry * temp_k)) + (vapor_pa / (r_vapor * temp_k))
    return float(rho)

def simulateCoast(initial_velocity: float, cd: float, mass_kg: float,rho_air: float) -> float:
    """Simulate coast and return altitude gained until apogee."""
    vel = initial_velocity
    alt_gained = 0.0
    t = 0.0

    while vel > 0.0 and t < 20.0:
        drag = -0.5 * rho_air * AREA * cd * vel * abs(vel)
        weight = -mass_kg * G
        accel = (drag + weight) / mass_kg

        vel += accel * DT
        alt_gained += vel * DT
        t += DT

    return max(0.0, alt_gained)
