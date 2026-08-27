# `sim/`

Simulation utilities and generated artifacts for apogee prediction and coast-phase modeling.

## What is here

- `generate_coast_table.py` — generates the coast-phase lookup table and updates mass and air-density constants.
- `coast_table.py` — generated Python lookup table (do not edit by hand).
- `include/coast_table.h` — generated C++ lookup table (do not edit by hand).

## Generating the coast lookup table

Run the generator from the repository root:

```bash
python sim/generate_coast_table.py
```

The script uses a simple drag model and a configured rocket mass to precompute altitude gain versus velocity and drag coefficient. It writes:

- `sim/coast_table.py` for Python consumers.
- `include/coast_table.h` for firmware lookup.
- Updates `include/config.h` with `MASS` and `RHO` values that match the current environment.

## Inputs and configuration

Default values are defined at the top of `generate_coast_table.py`. They can be overridden with environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `AIRBRAKES_MASS_KG` | `0.608` | Rocket mass in kilograms. |
| `AIRBRAKES_TEMP_F` | `68.0` | Ambient temperature in Fahrenheit. |
| `AIRBRAKES_HUMIDITY_PCT` | `55.0` | Relative humidity in percent. |
| `AIRBRAKES_PRESSURE_HPA` | `1015.0` | Ambient pressure in hectopascals. |

Example with custom inputs:

```bash
AIRBRAKES_MASS_KG=0.620 AIRBRAKES_TEMP_F=72.0 python sim/generate_coast_table.py
```

## Generated files

- **Do not hand-edit** `coast_table.py` or `include/coast_table.h`. Treat them as build outputs.
- Regenerate them whenever mass, atmospheric conditions, or the simulation model change.
- Commit the regenerated files together with the inputs that produced them so the repository state is reproducible.

## Reproducibility

When logging a simulation run for later reference, record:

- The mass, temperature, humidity, and pressure values used.
- The commit hash of the `generate_coast_table.py` script.
- Any changes made to the physical model constants in the script (for example, reference area or time step).

## Dependencies

- Python 3.
- NumPy. Install it with:

```bash
python -m pip install numpy
```

## Links

- [`../include/coast_table.h`](../include/coast_table.h) — generated C++ lookup table.
- [`../include/config.h`](../include/config.h) — where mass and air density are defined.
- [`../README.md`](../README.md) — project onboarding and quick-start commands.
