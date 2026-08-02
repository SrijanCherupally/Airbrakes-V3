"""
Builds matplotlib Figures from a flight's CSV (as a pandas DataFrame with
the columns written by data_store.save_flight / flight_data_manager.py).

Each function returns a Figure so the GUI can embed it via
FigureCanvasTkAgg. Nothing here talks to Tkinter directly.
"""

import matplotlib
matplotlib.use("Agg")  # overridden by the GUI (TkAgg) when embedded live
import matplotlib.pyplot as plt

# Matches the app's ttkbootstrap "superhero" theme so embedded plots don't
# look like a jarring white rectangle inside a dark UI.
BG = "#2b3e50"
FG = "#e5e9f0"
GRID = "#44566b"
ACCENT = "#4f9bde"
ACCENT2 = "#e07b39"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "axes.edgecolor": GRID,
    "axes.labelcolor": FG,
    "text.color": FG,
    "xtick.color": FG,
    "ytick.color": FG,
    "grid.color": GRID,
    "legend.facecolor": BG,
    "legend.edgecolor": GRID,
    "legend.labelcolor": FG,
})


def _fig(title, xlabel, ylabel):
    fig, ax = plt.subplots(figsize=(7, 4))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_title(title, color=FG)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.4, color=GRID)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    fig.tight_layout()
    return fig, ax


def plot_altitude_velocity(df):
    fig, ax1 = _fig("Altitude & Velocity vs Time", "Time (s)", "Altitude (m)")
    t = df["time_ms"] / 1000.0
    ax1.plot(t, df["altitude_m"], color="tab:blue", label="Altitude")
    ax2 = ax1.twinx()
    ax2.plot(t, df["velocity_ms"], color="tab:orange", label="Velocity", alpha=0.8)
    ax2.set_ylabel("Velocity (m/s)")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="best")
    return fig


def plot_acceleration(df):
    fig, ax = _fig("Acceleration vs Time", "Time (s)", "Acceleration (m/s²)")
    t = df["time_ms"] / 1000.0
    ax.plot(t, df["raw_accel_ms2"], label="Raw accel", alpha=0.7)
    ax.plot(t, df["accel_bias_ms2"], label="Accel bias", alpha=0.7)
    ax.legend(loc="best")
    return fig


def plot_motor_position(df):
    fig, ax = _fig("Motor / Airbrake Position vs Time", "Time (s)", "Position")
    t = df["time_ms"] / 1000.0
    ax.plot(t, df["motor_pos"], label="Actual position")
    ax.plot(t, df["motor_cmd_pos"], label="Commanded position", linestyle="--")
    ax.legend(loc="best")
    return fig


def plot_motor_vs_cd(df):
    fig, ax = _fig("Motor Position vs Cd", "Motor position", "Cd")
    ax.scatter(df["motor_pos"], df["Cd"], s=6, alpha=0.5)
    return fig


def plot_cd_tracking(df):
    fig, ax = _fig("Cd Tracking vs Time", "Time (s)", "Cd")
    t = df["time_ms"] / 1000.0
    ax.plot(t, df["Cd"], label="Estimated Cd")
    ax.plot(t, df["desired_Cd"], label="Desired Cd", linestyle="--")
    ax.legend(loc="best")
    return fig


def plot_state_timeline(df):
    fig, ax = _fig("Flight State vs Time", "Time (s)", "State")
    t = df["time_ms"] / 1000.0
    ax.step(t, df["state"], where="post")
    if "state_name" in df.columns:
        # Label the y ticks with state names where we can.
        uniq = sorted(df["state"].unique())
        names = []
        for v in uniq:
            match = df.loc[df["state"] == v, "state_name"]
            names.append(match.iloc[0] if len(match) else str(v))
        ax.set_yticks(uniq)
        ax.set_yticklabels(names)
    return fig


def plot_coast_predicted_vs_actual(df, vel_range=None, cd_range=None, table=None):
    """
    Plots, over the CONTROL (coast) phase of the flight:
      - actual remaining altitude to apogee (max altitude reached - current altitude)
      - predicted remaining altitude, from the SAME bilinear lookup table
        control.cpp's onboard bisection search uses, evaluated at the
        flight's actual (velocity, Cd) at each instant.
    This is the most direct check of "did the model match reality" — if the
    controller's model of the rocket was accurate, these two curves should
    sit on top of each other throughout the coast.

    vel_range/cd_range/table come from coast_lookup.load_coast_table(repo_path).
    If not provided, only the actual curve is plotted.
    """
    has_state = "state_name" in df.columns
    coast_df = df[df["state_name"] == "CONTROL"] if has_state else df

    fig, ax = _fig("Coast: Predicted vs Actual Remaining Altitude",
                    "Time into coast (s)", "Remaining altitude to apogee (m)")

    if not len(coast_df):
        ax.text(0.5, 0.5, "No CONTROL-phase data in this flight",
                 transform=ax.transAxes, ha="center", va="center", color="gray")
        return fig

    t = (coast_df["time_ms"] - coast_df["time_ms"].iloc[0]) / 1000.0
    max_alt = df["altitude_m"].max()
    actual_remaining = max_alt - coast_df["altitude_m"]
    ax.plot(t, actual_remaining, label="Actual remaining", color="tab:blue")

    if vel_range is not None and table is not None:
        from coast_lookup import predicted_remaining_altitude
        predicted = predicted_remaining_altitude(coast_df, vel_range, cd_range, table,
                                                  cd_column="Cd")
        ax.plot(t, predicted, label="Predicted remaining (onboard model)",
                 color="tab:red", linestyle="--")
    else:
        ax.text(0.02, 0.95, "Predicted curve unavailable — couldn't load "
                 "sim/coast_table.py", transform=ax.transAxes, va="top",
                 fontsize=8, color="gray")

    ax.legend(loc="best")
    return fig


ALL_PLOTS = [
    ("Altitude & Velocity", plot_altitude_velocity),
    ("Acceleration", plot_acceleration),
    ("Motor / Airbrake Position", plot_motor_position),
    ("Motor Position vs Cd", plot_motor_vs_cd),
    ("Cd Tracking", plot_cd_tracking),
    ("Flight State Timeline", plot_state_timeline),
    ("Coast: Predicted vs Actual", plot_coast_predicted_vs_actual),
]
