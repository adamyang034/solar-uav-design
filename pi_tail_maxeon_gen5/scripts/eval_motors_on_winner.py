"""Catalog Hacker motors + free-Kv rewind on the current best airframe.

Airframe is the Phase 4 10L nearest-miss (6.0 m × 0.36 m, one string/bay).
Each motor re-picks the climb-legal prop. Duty is reported, not a cutoff.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from solar_uav import config, environment, mission, optimize, optimize_kv
from solar_uav.aircraft import RHO_NIGHT
from solar_uav.components.motor import drive_for, motor_from_kv
from solar_uav.components.propulsion import load_prop
from solar_uav.optimize import _best_prop, _prop_candidates

OUT = Path(__file__).resolve().parents[1] / "outputs"
AIR = OUT / "phase4_full_search.csv"


def _load_winner():
    df = pd.read_csv(AIR)
    return optimize.design_from_row(df.iloc[0])


def _eval_drive(design, drive, env, prop_names, cache, label):
    design.motor_name = label if label in config.MOTOR_CATALOG else design.motor_name
    picked = _best_prop(design, prop_names, cache, motor=drive)
    if picked is None:
        print(f"  {label}: no climb-legal prop")
        return None
    pname, psys, pnight = picked
    design.prop_diameter_in = psys.prop.diameter_in or 18.0
    design.prop_name = pname
    mres = mission.simulate(design, env, psys)
    drag = float(np.asarray(design.drag_n(mres.v_night)).reshape(-1)[0])
    fl = psys.level_flight(mres.v_night, drag, rho=RHO_NIGHT)
    duty = float(fl["voltage_v"]) / config.BUS_V_NOM if fl else float("nan")
    idle = 2.0 * float(fl["voltage_v"]) * drive.spec.i0_a if fl else float("nan")
    rec = {
        "motor": label,
        "prop": pname,
        "mass_kg": design.mass_kg,
        "p_night_w": mres.p_night_w,
        "p_day_w": mres.p_day_w,
        "idle_w": idle,
        "duty": duty,
        "voltage_v": float(fl["voltage_v"]) if fl else float("nan"),
        "prop_rpm": float(fl["rpm"]) if fl else float("nan"),
        "climb_ms": mres.climb_ms,
        "margin_wh": mres.margin_wh,
        "soc_min": mres.soc_min,
        "soc_end": mres.soc_end,
        "closed": mres.closed,
        "reason": mres.reason,
    }
    print(f"  {drive.spec.name}")
    print(f"    prop={pname}  mass={design.mass_kg:.2f} kg  "
          f"Pnight={mres.p_night_w:.1f} W  idle={idle:.1f} W  "
          f"duty={duty:.0%}  RPM={rec['prop_rpm']:.0f}  "
          f"climb={mres.climb_ms:.2f}  margin={mres.margin_wh:.0f} Wh  "
          f"closed={mres.closed}")
    return rec


def main():
    env = environment.design_day(config.SOLSTICE_DATE)
    base = _load_winner()
    prop_names = _prop_candidates()
    cache = {n: load_prop(n) for n in prop_names}

    print("=" * 70)
    print("CATALOG HACKER MOTORS  (airframe = 10L nearest miss, prop re-picked)")
    print(f"  {base.span_m} m × {base.chord_m} m  tail={base.tail_arm_m}  "
          f"elev={base.elevator_frac}  boom={base.boom_spacing_set_m}  "
          f"taper={base.taper_ratio}/{base.taper_start_frac}  "
          f"cells={base.n_cells}  {base.string_plan_label()}")

    rows = []
    for key in config.MOTOR_CATALOG:
        d = optimize.design_from_row(pd.read_csv(AIR).iloc[0])
        d.motor_name = key
        rec = _eval_drive(d, drive_for(key), env, prop_names, cache, key)
        if rec:
            rows.append(rec)
    pd.DataFrame(rows).to_csv(OUT / "motor_swap_on_winner.csv", index=False)

    print("=" * 70)
    print("FREE Kv  (A40-12L stator rewind, climb-legal, duty NOT a cutoff)")
    d = optimize.design_from_row(pd.read_csv(AIR).iloc[0])
    d.motor_name = config.MOTOR_SCALE_REF
    kv_df = optimize_kv.search(d, verbose=True)
    kv_path = OUT / "kv_prop_on_winner.csv"
    kv_df.to_csv(kv_path, index=False)
    print(f"  {len(kv_df)} combos -> {kv_path}")

    w = optimize_kv.winner(kv_df)
    print("  Ideal Kv (min night bus, climb ok):")
    cols = ["prop", "kv", "p_bus_w", "idle_w", "efficiency", "prop_rpm",
            "voltage_v", "duty", "climb_ms", "i0_a", "r_ohm"]
    print(w[cols].to_string())

    ok = kv_df[kv_df["climb_ok"]].sort_values("p_bus_w")
    print("  Top 10 climb-legal (any duty):")
    print(ok[cols].head(10).round(3).to_string(index=False))
    print("  Envelope: best prop at each Kv (climb-legal):")
    env_kv = ok.loc[ok.groupby("kv")["p_bus_w"].idxmin()].sort_values("kv")
    show = env_kv[(env_kv.kv % 40 == 0) | (env_kv.kv == w["kv"])]
    print(show[["kv", "prop", "p_bus_w", "idle_w", "duty", "climb_ms"]]
          .round(2).to_string(index=False))

    # Full 24 h march with the ideal rewind on this airframe.
    key = f"A40-class-kv{int(w['kv'])}"
    drive = motor_from_kv(float(w["kv"]))
    config.MOTOR_CATALOG[key] = drive.spec
    d = optimize.design_from_row(pd.read_csv(AIR).iloc[0])
    d.motor_name = key
    print("=" * 70)
    print(f"MISSION with ideal rewind kv{int(w['kv'])} + {w['prop']}")
    rec = _eval_drive(d, drive, env, prop_names, cache, key)
    if rec:
        pd.DataFrame(rows + [rec]).to_csv(OUT / "motor_swap_on_winner.csv",
                                          index=False)


if __name__ == "__main__":
    main()
