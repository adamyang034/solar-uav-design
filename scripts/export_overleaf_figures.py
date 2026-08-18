"""Build PNG figures for the Overleaf documentation pack.

Writes to docs/overleaf/figures/. Numbers come from reference_design()
and outputs/phase4_candidates.csv — the same nearest-miss as the guide.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solar_uav import config, environment, mission
from solar_uav.aircraft import RHO_NIGHT, reference_design
from solar_uav.cad import mesh_cells, mesh_structure, three_view, write_mass_png
from solar_uav.components import airfoils
from solar_uav.components.battery import cell_ocv
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop
from solar_uav.components.solar_array import SolarArray

OUT = ROOT / "docs" / "overleaf" / "figures"
CSV = ROOT / "outputs" / "phase4_candidates.csv"

C_SOLAR = "#d4a017"
C_LOAD = "#3d6d99"
C_SOC = "#2e7d32"
C_FLOOR = "#c62828"
C_WING = "#8ab4f8"
C_STRUCT = "#9aa0a6"


def _style() -> None:
    plt.rcParams.update({
        "font.size": 9.5,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "figure.dpi": 120,
        "savefig.dpi": 180,
        "savefig.bbox": "tight",
        "axes.grid": True,
        "grid.alpha": 0.35,
        "grid.linewidth": 0.4,
    })


def _save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path)
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")
    return path


def fig_three_view(d) -> None:
    three_view(d, mesh_structure(d), mesh_cells(d), OUT / "three_view.png")
    print(f"  wrote {(OUT / 'three_view.png').relative_to(ROOT)}")


def fig_mass(d) -> None:
    write_mass_png(d, OUT / "mass_breakdown.png")
    print(f"  wrote {(OUT / 'mass_breakdown.png').relative_to(ROOT)}")


def fig_geometry(d) -> None:
    # Side: independent tails, boom c/4 → V TE, H-stab in the wing plane.
    fig, ax = plt.subplots(figsize=(9.2, 3.4))
    c = d.chord_m
    h_le, h_te = d.hstab_le_x(), d.hstab_te_x()
    v_le, v_te = d.vstab_le_x(), d.vstab_te_x
    vh = d.vstab_height
    ax.fill([0, c, c, 0], [-0.02, -0.02, 0.02, 0.02],
            color="#5f6b7a", label="Wing (side, thickness schematic)")
    ax.plot([d.boom_x_front, v_te], [0, 0], color="#3c4043", lw=3.2,
            solid_capstyle="butt", label="Boom (c/4 → V-stab TE)")
    ax.fill([h_le, h_te, h_te, h_le], [-0.015, -0.015, 0.015, 0.015],
            color="#1a73e8", label="H-stab (wing plane)")
    ax.fill([v_le, v_te, v_te, v_le], [0, 0, vh, vh],
            color="#188038", alpha=0.85, label="V-stab")
    ax.axvline(h_te, color="#1a73e8", ls=":", lw=0.9)
    ax.axvline(v_le, color="#188038", ls=":", lw=0.9)
    ax.annotate("", xy=(v_le, vh + 0.04), xytext=(h_te, vh + 0.04),
                arrowprops=dict(arrowstyle="<->", color="#5f6368", lw=1.0))
    ax.text(0.5 * (h_te + v_le), vh + 0.07,
            f"V LE {v_le - h_te:.2f} m behind H TE",
            ha="center", va="bottom", fontsize=8, color="#5f6368")
    ax.set_aspect("equal")
    ax.set_xlabel("x [m] aft of wing LE")
    ax.set_ylabel("z [m]")
    ax.set_ylim(-0.18, vh + 0.22)
    ax.set_title("Independent tails — H-stab in the wing plane, V-stab further aft")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.92)
    _save(fig, "geometry_side.png")

    # Top: planform + boom + H-stab + V-stab footprints.
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    yb = 0.5 * d.boom_spacing
    cr, ct = d.chord_m, d.tip_chord_m
    b2 = 0.5 * d.span_m

    def chord_at(y):
        ay = abs(y)
        if ay <= yb:
            return cr
        # outboard
        l_out = b2 - yb
        y_loc = ay - yb
        f = d.taper_start_frac
        l_rect = f * l_out
        if y_loc <= l_rect:
            return cr
        t = (y_loc - l_rect) / max(l_out - l_rect, 1e-9)
        return cr + t * (ct - cr)

    ys = np.linspace(-b2, b2, 240)
    cs = np.array([chord_at(y) for y in ys])
    ax.fill(np.concatenate([np.zeros_like(ys), cs[::-1]]),
            np.concatenate([ys, ys[::-1]]),
            color="#c8ccd0", edgecolor="#5f6368", lw=0.8, label="Wing")
    ax.fill([h_le, h_te, h_te, h_le], [-yb, -yb, yb, yb],
            color="#1a73e8", alpha=0.55, label="H-stab")
    for s in (-1, 1):
        ax.fill([v_le, v_te, v_te, v_le],
                [s * yb - 0.012, s * yb - 0.012, s * yb + 0.012, s * yb + 0.012],
                color="#188038", label="V-stab" if s > 0 else None)
        ax.plot([d.boom_x_front, v_te], [s * yb, s * yb],
                color="#3c4043", lw=2.0)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m] aft")
    ax.set_ylabel("y [m] span")
    ax.set_title(
        f"Planform  {d.span_m:.2f}×{d.chord_m:.3f} m  λ={d.taper_ratio:.2f}  "
        f"H-arm {d.tail_arm_m:.2f} m  V-arm {d.vstab_arm_m:.2f} m")
    ax.legend(loc="upper right", fontsize=8)
    _save(fig, "geometry_top.png")


def fig_drag(d) -> None:
    bd = d.drag_breakdown()
    parts = bd["drag_n"]
    labels = {
        "wing_profile": "Wing profile",
        "wing_induced": "Wing induced",
        "hstab_profile": "H-stab profile",
        "hstab_induced": "H-stab induced",
        "vstab_profile": "V-stab profile",
        "pods": "Pods",
        "booms": "Booms",
        "control_gaps": "Control gaps",
    }
    items = [(labels[k], v) for k, v in parts.items()]
    total = bd["drag_total_n"]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    y = np.arange(len(items))
    ax.barh(y, [v for _, v in items], color=C_WING, height=0.72)
    ax.set_yticks(y, [k for k, _ in items])
    ax.invert_yaxis()
    ax.set_xlabel("Drag [N]")
    ax.set_title(
        f"Night drag at {bd['v_ms']:.2f} m/s  "
        f"(1.3 $V_s$ binds)  $D$={total:.2f} N  $DV$={bd['power_aero_w']:.1f} W")
    for yi, (_, v) in zip(y, items):
        ax.text(v + 0.02, yi, f"{v:.2f}  {100 * v / total:.0f}%",
                va="center", fontsize=8)
    ax.set_xlim(0, max(v for _, v in items) * 1.32)
    _save(fig, "drag_budget.png")


def fig_power_speed(d) -> None:
    vs = np.linspace(7.4, 16.0, 90)
    dv = np.array([float(d.power_aero_w(v)) for v in vs])
    drag = np.array([float(d.drag_n(v)) for v in vs])
    v_s = d.stall_speed()
    v_min = d.min_airspeed()
    i_free = int(np.argmin(dv))
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0))
    axes[0].plot(vs, drag, color=C_LOAD, lw=1.8)
    axes[0].axvline(v_s, color=C_FLOOR, ls="--", lw=1.0, label=f"$V_s$ {v_s:.2f}")
    axes[0].axvline(v_min, color="#3c4043", ls=":", lw=1.2,
                    label=f"$1.3 V_s$ {v_min:.2f}")
    axes[0].set_xlabel("Airspeed [m/s]")
    axes[0].set_ylabel("Drag [N]")
    axes[0].legend(fontsize=8)
    axes[0].set_title("Night polar")
    axes[1].plot(vs, dv, color=C_LOAD, lw=1.8)
    axes[1].axvline(vs[i_free], color="#188038", ls="--", lw=1.0,
                    label=f"aero min-power {vs[i_free]:.2f} m/s")
    axes[1].axvline(v_min, color="#3c4043", ls=":", lw=1.2,
                    label="flown (floor binds)")
    axes[1].scatter([vs[i_free], v_min],
                    [dv[i_free], float(d.power_aero_w(v_min))],
                    c=["#188038", C_FLOOR], zorder=3)
    axes[1].set_xlabel("Airspeed [m/s]")
    axes[1].set_ylabel("Aero power $DV$ [W]")
    axes[1].legend(fontsize=8)
    axes[1].set_title("Why the speed floor costs watts")
    fig.suptitle(f"Nearest-miss  {d.mass_kg:.2f} kg  ρ$_N$={RHO_NIGHT:.3f} kg/m³",
                 fontsize=11)
    fig.tight_layout()
    _save(fig, "power_vs_speed.png")


def fig_airfoils() -> None:
    df = airfoils.generate_all(save=False)
    sel = df[np.isclose(df["re"], 150e3)]
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.8))
    for name, g in sel.groupby("airfoil"):
        axes[0].plot(g["alpha_deg"], g["cl"], label=name, lw=1.5)
        axes[1].plot(g["cd"], g["cl"], label=name, lw=1.5)
        cl = g["cl"].to_numpy()
        cd = g["cd"].to_numpy()
        axes[2].plot(g["alpha_deg"],
                     np.where(cl > 0, cl ** 1.5 / np.maximum(cd, 1e-6), np.nan),
                     label=name, lw=1.5)
    axes[0].set_xlabel(r"$\alpha$ [deg]")
    axes[0].set_ylabel(r"$c_\ell$")
    axes[1].set_xlabel(r"$c_d$")
    axes[1].set_ylabel(r"$c_\ell$")
    axes[1].set_xlim(0, 0.04)
    axes[2].set_xlabel(r"$\alpha$ [deg]")
    axes[2].set_ylabel(r"$c_\ell^{1.5}/c_d$")
    for a in axes:
        a.legend(fontsize=8)
    fig.suptitle("NeuralFoil polars @ Re 150k (xlarge) — S4310 wing, NACA 0010 tails")
    fig.tight_layout()
    _save(fig, "airfoil_polars.png")


def fig_solstice(d, env: pd.DataFrame) -> None:
    hours = env.index.hour + env.index.minute / 60.0
    fig, axes = plt.subplots(3, 1, figsize=(8.8, 7.2), sharex=True)
    axes[0].plot(hours, env["ghi"], label="GHI", color="#9aa0a6", lw=1.1)
    axes[0].plot(hours, env["poa_raw"], label="POA geometric", color="#e8710a", lw=1.1)
    axes[0].plot(hours, env["poa_eff"], label="POA after IAM + encaps",
                 color=C_SOLAR, lw=1.8)
    axes[0].set_ylabel("Irradiance [W/m²]")
    axes[0].legend(fontsize=8)
    axes[0].set_title(
        f"El Mirage  {config.LATITUDE_DEG:.2f}°N  {config.SOLSTICE_DATE}  "
        f"clear-sky Ineichen")
    axes[1].plot(hours, env["sun_elevation_deg"], color="#e8710a", lw=1.5)
    axes[1].axhline(0, color="#3c4043", lw=0.6)
    axes[1].set_ylabel("Sun elevation [deg]")
    axes[2].plot(hours, env["t_amb_c"], label="Ambient", color="#5f6368", lw=1.4)
    axes[2].plot(hours, env["t_cell_c"], label="Cell (static NOCT, no flight cooling)",
                 color=C_FLOOR, lw=1.4)
    axes[2].set_ylabel("Temperature [°C]")
    axes[2].set_xlabel("Local time [h]")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    _save(fig, "solstice_day.png")


def fig_mission(d, env: pd.DataFrame) -> None:
    psys = PropulsionSystem(
        prop=load_prop(d.prop_name),
        motor=drive_for(d.motor_name))
    res = mission.simulate(d, env, psys)
    hours = env.index.hour + env.index.minute / 60.0
    arr = SolarArray(string_lengths=d.string_lengths())
    p_solar = arr.power_to_bus_w(
        env["poa_eff"].to_numpy(dtype=float),
        env["t_cell_c"].to_numpy(dtype=float))
    p_load = np.where(p_solar < res.p_night_w, res.p_night_w, res.p_day_w)

    fig, ax = plt.subplots(figsize=(8.8, 3.8))
    ax.fill_between(hours, 0, p_solar, color=C_SOLAR, alpha=0.35, label="Array to bus")
    ax.plot(hours, p_solar, color=C_SOLAR, lw=1.6)
    ax.plot(hours, p_load, color=C_LOAD, lw=1.7, label="Propulsion + 5 W avionics")
    ax.axhline(res.p_night_w, color=C_LOAD, ls=":", lw=0.9)
    ax.set_xlim(0, 24)
    ax.set_xlabel("Local time [h]")
    ax.set_ylabel("Power [W]")
    ax.set_title(
        f"Design-day power  night bus {res.p_night_w:.1f} W  "
        f"battery-true night {res.battery_night_h:.1f} h  "
        f"{d.n_cells} cells")
    ax.legend(fontsize=8)
    _save(fig, "mission_power.png")

    fig, ax = plt.subplots(figsize=(8.8, 3.6))
    ax.plot(res.hours, res.soc_trace * 100, color=C_SOC, lw=1.8)
    ax.axhline(config.SOC_MIN * 100, color=C_FLOOR, ls="--", lw=1.2,
               label="20% floor")
    ax.axhline(98, color="#5f6368", ls=":", lw=1.0, label="98% refill")
    ax.set_xlabel("Hours from last afternoon surplus (pack starts full)")
    ax.set_ylabel("SOC [%]")
    ax.set_ylim(0, 105)
    ax.set_title(
        f"Energy march  SOC$_\\mathrm{{min}}$={res.soc_min:.3f}  "
        f"SOC$_\\mathrm{{end}}$={res.soc_end:.3f}  "
        f"margin {res.margin_wh:.0f} Wh  closed={res.closed}")
    ax.legend(fontsize=8, loc="lower left")
    _save(fig, "mission_soc.png")
    return res


def fig_battery() -> None:
    soc = np.linspace(0, 1, 200)
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(soc * 100, 6 * cell_ocv(soc), color=C_LOAD, lw=1.8)
    ax.axvline(config.SOC_MIN * 100, color=C_FLOOR, ls="--",
               label="20% usable-window floor")
    ax.set_xlabel("SOC [%]")
    ax.set_ylabel("6S pack OCV [V]")
    ax.set_title("Generic Si-anode Li-ion OCV (FLAGGED) × 6 cells")
    ax.legend(fontsize=8)
    _save(fig, "battery_ocv.png")


def fig_tradespace() -> None:
    if not CSV.is_file():
        print("  skip tradespace (no CSV)")
        return
    df = pd.read_csv(CSV)
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.2))
    axes[0].scatter(df["mass_kg"], df["margin_wh"], s=14, alpha=0.45,
                    c=df["p_night_w"], cmap="viridis")
    best = df.loc[df["margin_wh"].idxmax()]
    axes[0].scatter([best["mass_kg"]], [best["margin_wh"]],
                    s=70, c=C_FLOOR, zorder=3, label="nearest-miss")
    axes[0].axhline(0, color=C_FLOOR, ls=":", lw=1.0)
    axes[0].axvline(config.MTOW_MAX_KG, color="#3c4043", ls="--", lw=0.9)
    axes[0].set_xlabel("Mass [kg]")
    axes[0].set_ylabel("Energy margin [Wh]")
    axes[0].set_title(f"DE search  {len(df)} scored, 0 closed")
    axes[0].legend(fontsize=8)
    sc = axes[1].scatter(df["v_night"], df["p_night_w"], s=14, alpha=0.45,
                         c=df["margin_wh"], cmap="coolwarm")
    axes[1].scatter([best["v_night"]], [best["p_night_w"]],
                    s=70, c=C_FLOOR, zorder=3)
    axes[1].set_xlabel(r"$V_\mathrm{night}$ [m/s]")
    axes[1].set_ylabel("Night bus [W]")
    axes[1].set_title("Speed floor and night watts")
    fig.colorbar(sc, ax=axes[1], label="margin [Wh]")
    fig.tight_layout()
    _save(fig, "tradespace.png")


def main() -> None:
    _style()
    OUT.mkdir(parents=True, exist_ok=True)
    print("Overleaf figures →", OUT)
    d = reference_design()
    print(f"  airplane {d.span_m:.3f}×{d.chord_m:.3f} m  {d.mass_kg:.3f} kg  "
          f"{d.prop_name}  {d.n_cells} cells")
    fig_three_view(d)
    fig_geometry(d)
    fig_mass(d)
    fig_drag(d)
    fig_power_speed(d)
    fig_airfoils()
    env = environment.design_day(config.SOLSTICE_DATE)
    fig_solstice(d, env)
    fig_mission(d, env)
    fig_battery()
    fig_tradespace()
    print("done")


if __name__ == "__main__":
    main()
