"""Run every Phase 1 / Phase 2 model and produce validation plots + a summary.

Usage:  .venv/bin/python scripts/validate_all.py
Plots land in outputs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment
from solar_uav.components import airfoils, propeller, solar_array
from solar_uav.components.battery import BatteryBank, cell_ocv
from solar_uav.components.motor import MotorDrive

OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)


def phase1_environment():
    print("=" * 70)
    print("PHASE 1 — Solar resource, solstice design day")
    prof = environment.design_day(config.SOLSTICE_DATE)
    k = environment.noct_coefficient()
    hours = prof.index.hour + prof.index.minute / 60.0

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(hours, prof["ghi"], label="GHI (clear sky)", lw=1.5)
    axes[0].plot(hours, prof["poa_eff"], label="POA effective (IAM + encaps.)",
                 lw=1.5)
    axes[0].set_ylabel("Irradiance [W/m²]")
    axes[0].legend()
    axes[0].set_title(
        f"{config.LATITUDE_DEG:.2f}°N {config.SOLSTICE_DATE} — clear-sky design day")

    axes[1].plot(hours, prof["sun_elevation_deg"], color="tab:orange")
    axes[1].axhline(0, color="k", lw=0.5)
    axes[1].set_ylabel("Sun elevation [deg]")

    axes[2].plot(hours, prof["t_amb_c"], label="Ambient", lw=1.5)
    axes[2].plot(hours, prof["t_cell_c"], label="Cell (static, NOCT-style)",
                 lw=1.5)
    axes[2].set_ylabel("Temperature [°C]")
    axes[2].set_xlabel("Local time [h]")
    axes[2].legend()
    fig.tight_layout()
    fig.savefig(OUT / "phase1_solstice_day.png", dpi=150)

    daily_kwh = prof["poa_eff"].sum() / 60.0 / 1000.0
    noon = prof["poa_eff"].max()
    zen_noon = 90.0 - prof["sun_elevation_deg"].max()
    print(f"  Peak sun elevation: {prof['sun_elevation_deg'].max():.1f} deg "
          f"(noon zenith offset {zen_noon:.1f} deg)")
    print(f"  Peak POA effective: {noon:.0f} W/m²  |  daily {daily_kwh:.2f} kWh/m²")
    print(f"  Peak cell temp: {prof['t_cell_c'].max():.1f} °C "
          f"(calibrated k={k*1000:.1f} °C per kW/m²)")

    scan = environment.window_scan()
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(scan.index, scan["poa_kwh_m2"], "o-", color="tab:blue")
    ax1.set_ylabel("POA energy [kWh/m²/day]", color="tab:blue")
    ax2 = ax1.twinx()
    ax2.plot(scan.index, scan["dark_hours"], "s-", color="tab:red")
    ax2.set_ylabel("Dark hours (<5° sun) [h]", color="tab:red")
    ax1.set_title("May–July mission window scan")
    fig.tight_layout()
    fig.savefig(OUT / "phase1_window_scan.png", dpi=150)

    worst = scan["poa_kwh_m2"].idxmin()
    print(f"  Worst energy day in window: {worst.date()} "
          f"({scan.loc[worst, 'poa_kwh_m2']:.2f} kWh/m², "
          f"{scan.loc[worst, 'dark_hours']:.1f} dark hours)")
    return prof


def phase2_array(prof: pd.DataFrame):
    print("=" * 70)
    print("PHASE 2 — Solar array")
    limit = solar_array.max_cells_per_string()
    print(f"  Max cells/string (boost MPPT, cold cells + low bus): {limit}")

    bays = solar_array.wing_layout(
        span_m=6.0, chord_m=0.45, boom_spacing_m=1.4,
        hstab_span_m=1.4, hstab_chord_m=0.30)
    for name, b in bays.items():
        print(f"  Bay {name:16s}: {b.rows} rows x {b.cols} cols = "
              f"{b.capacity} cells")
    plan = solar_array.feasible_string_plan(bays, cells_per_string=28)
    print(f"  Example plan @28 cells/string: {plan}")

    arr = solar_array.SolarArray(n_strings=4, cells_per_string=28)
    p_bus = arr.power_to_bus_w(prof["poa_eff"].to_numpy(),
                               prof["t_cell_c"].to_numpy())
    hours = prof.index.hour + prof.index.minute / 60.0
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(hours, p_bus, lw=1.5)
    ax.set_xlabel("Local time [h]")
    ax.set_ylabel("Array power to bus [W]")
    ax.set_title(f"{arr.n_cells} cells (4 strings × 28), bin "
                 f"{config.CELL_BIN_DEFAULT}, solstice")
    fig.tight_layout()
    fig.savefig(OUT / "phase2_array_power.png", dpi=150)

    e_day = float(np.trapezoid(p_bus, hours))
    print(f"  Example 112-cell array: peak {p_bus.max():.0f} W to bus, "
          f"{e_day:.0f} Wh/day  |  mass {arr.mass_kg:.3f} kg (incl. MPPTs)")
    return arr, p_bus


def phase2_battery():
    print("=" * 70)
    print("PHASE 2 — Battery bank")
    soc = np.linspace(0, 1, 200)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(soc * 100, 6 * cell_ocv(soc), lw=1.5)
    axes[0].axvline(config.SOC_MIN * 100, color="r", ls="--",
                    label="20% SOC floor")
    axes[0].set_xlabel("SOC [%]")
    axes[0].set_ylabel("Pack OCV [V]")
    axes[0].legend()
    axes[0].set_title("6S OCV curve (FLAGGED: generic, needs bench data)")

    # Charge acceptance vs SOC for 3 packs
    bank = BatteryBank(n_packs=3)
    accept = []
    for s in soc:
        bank.soc = s
        accept.append(bank.max_charge_power_w())
    axes[1].plot(soc * 100, accept, lw=1.5)
    axes[1].set_xlabel("SOC [%]")
    axes[1].set_ylabel("Max charge power [W]")
    axes[1].set_title("Charge acceptance, 3 packs (6 A/pack CC + CV taper)")
    fig.tight_layout()
    fig.savefig(OUT / "phase2_battery.png", dpi=150)

    # Night sim: 3 packs, 140 W constant, from full
    bank.reset(1.0)
    t, socs = [0.0], [1.0]
    dt = 60.0
    while bank.soc > config.SOC_MIN and t[-1] < 20 * 3600:
        r = bank.step(-140.0, dt)
        if r["deficit_w"] > 0:
            break
        t.append(t[-1] + dt)
        socs.append(bank.soc)
    endurance_h = t[-1] / 3600.0
    print(f"  3 packs: {BatteryBank(3).energy_usable_wh:.0f} Wh usable, "
          f"{endurance_h:.1f} h at 140 W to the 20% floor")
    bank4 = BatteryBank(4)
    print(f"  4 packs: {bank4.energy_usable_wh:.0f} Wh usable "
          f"({bank4.mass_kg:.2f} kg)")


def phase2_props():
    print("=" * 70)
    print("PHASE 2 — APC + Mejzlik propeller databases")
    propeller.download_database()
    idx = propeller.build_index()
    print(f"  APC index: {len(idx)} propellers")

    from solar_uav.components import mejzlik
    mejzlik.download_database()
    mj = mejzlik.build_index()
    print(f"  Mejzlik 2B electric: {len(mj)} props with maps")
    if not mj.empty:
        print("   " + ", ".join(mj["name"].tolist()))

    sample_name = None
    for cand in ["20x13E", "19x12E", "18x12E", "16x10E"]:
        if (idx["name"].str.lower() == cand.lower()).any():
            sample_name = cand
            break
    if sample_name is None:
        sample_name = idx.iloc[0]["name"]
    prop = propeller.Propeller.load(sample_name)
    print(f"  Sample APC: {prop.name} (D={prop.diameter_in} in), "
          f"est. mass {prop.mass_kg*1000:.0f} g "
          f"[{len(prop.data)} rows, {len(prop.rpm_grid)} RPM blocks]")

    v = np.linspace(0, 20, 60)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for rpm in prop.rpm_grid[1:10:2]:
        thrust = [prop.thrust_n(vi, rpm) for vi in v]
        power = [prop.shaft_power_w(vi, rpm) for vi in v]
        axes[0].plot(v, thrust, label=f"{rpm:.0f} rpm")
        axes[1].plot(v, power, label=f"{rpm:.0f} rpm")
    axes[0].set_xlabel("Airspeed [m/s]")
    axes[0].set_ylabel("Thrust [N] (derated)")
    axes[1].set_xlabel("Airspeed [m/s]")
    axes[1].set_ylabel("Shaft power [W] (inflated)")
    axes[0].legend(fontsize=7)
    fig.suptitle(f"APC {prop.name} with uncertainty factors")
    fig.tight_layout()
    fig.savefig(OUT / "phase2_prop_maps.png", dpi=150)

    if not mj.empty and (mj["name"] == "MJ-21x13EL").any():
        mprop = propeller.Propeller.load("MJ-21x13EL")
        print(f"  Sample Mejzlik: {mprop.name} / {mprop.vendor_name} "
              f"(D={mprop.diameter_in} in), mass {mprop.mass_kg*1000:.0f} g "
              f"[{len(mprop.data)} rows, {len(mprop.rpm_grid)} RPM blocks]")

    op = prop.operating_point(thrust_req_n=6.0, v_ms=10.0)
    print(f"  Op point 6 N @ 10 m/s: {op}")
    return prop, op


def phase2_motor(prop, op):
    print("=" * 70)
    print("PHASE 2 — Motor drive")
    drive = MotorDrive()
    print(f"  {drive.spec.name}: Kv_eff {drive.kv_effective:.0f} rpm/V, "
          f"mass {drive.mass_kg*1000:.0f} g")

    if op is not None:
        res = drive.electrical_power_w(op["torque_nm"], op["rpm"])
        print(f"  At sample cruise op point ({op['rpm']:.0f} rpm prop, "
              f"{op['shaft_power_w']:.0f} W shaft): "
              f"{float(res['p_bus_w']):.0f} W from bus, "
              f"eta {float(res['efficiency'])*100:.0f}%, "
              f"V={float(res['voltage_v']):.1f} (feasible on 6S: "
              f"{bool(res['feasible'])})")

    q = np.linspace(0.05, 2.5, 80)
    n = np.linspace(500, 6000, 80)
    qq, nn, eta = drive.efficiency_map(q, n)
    fig, ax = plt.subplots(figsize=(7, 5))
    c = ax.contourf(nn, qq, eta, levels=np.arange(0, 1.0, 0.05),
                    cmap="viridis")
    fig.colorbar(c, label="Bus→shaft efficiency")
    ax.set_xlabel("Prop RPM")
    ax.set_ylabel("Prop torque [N·m]")
    ax.set_title(f"{drive.spec.name} + ESC efficiency map (6S)")
    fig.tight_layout()
    fig.savefig(OUT / "phase2_motor_map.png", dpi=150)


def phase2_airfoils():
    print("=" * 70)
    print("PHASE 2 — Airfoil polars (NeuralFoil)")
    df = airfoils.generate_all()
    figs = airfoils.cruise_figures(df)
    at_re = figs[figs["re"] == 150e3].round(2)
    print("  Cruise figures @ Re 150k:")
    print(at_re.to_string(index=False))

    sel = df[df["re"] == 150e3]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    for name, g in sel.groupby("airfoil"):
        axes[0].plot(g["alpha_deg"], g["cl"], label=name)
        axes[1].plot(g["cd"], g["cl"], label=name)
        axes[2].plot(g["alpha_deg"],
                     np.where(g["cl"] > 0, g["cl"] ** 1.5 / g["cd"], np.nan),
                     label=name)
    axes[0].set_xlabel("alpha [deg]"); axes[0].set_ylabel("CL")
    axes[1].set_xlabel("CD"); axes[1].set_ylabel("CL")
    axes[1].set_xlim(0, 0.05)
    axes[2].set_xlabel("alpha [deg]"); axes[2].set_ylabel("CL^1.5/CD")
    for a in axes:
        a.legend(fontsize=8)
    fig.suptitle("NeuralFoil polars @ Re 150k (xlarge model)")
    fig.tight_layout()
    fig.savefig(OUT / "phase2_airfoil_polars.png", dpi=150)
    return figs


def main():
    prof = phase1_environment()
    arr, p_bus = phase2_array(prof)
    phase2_battery()
    prop, op = phase2_props()
    phase2_motor(prop, op)
    phase2_airfoils()
    print("=" * 70)
    print(f"All plots written to {OUT}")


if __name__ == "__main__":
    main()
