"""Phase 4 continuous search: 12L, S&C, one string per bay, 2 packs.

Aero variables are continuous. Chord 300–520 mm, start 310 mm; tail arm start 0.90 m.

Usage:  .venv/bin/python pi_tail_maxeon_gen5/scripts/run_boom290_washout.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import reference_design
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop

OUT = Path(__file__).resolve().parents[1] / "outputs"
MOTOR = config.MOTOR_DEFAULT
PROPS = ("MJ-21x14EL", "16x12E", "17x12E", "18x12E", "19x12E", "20x13E", "21x13E")

COLS = [
    "span_m", "chord_m", "tail_arm_m", "boom_spacing_m",
    "taper_ratio", "taper_start_frac", "washout_tip_deg", "washout_start_frac",
    "string_plan", "n_cells", "prop", "mass_kg", "p_night_w", "solar_wh",
    "roll_rate_deg_s", "roll_aileron_deg_s", "roll_elevon_deg_s",
    "cn_beta", "margin_wh", "closed",
]


def _drive():
    return drive_for(MOTOR)


def main():
    s = config.OPT_START
    d0 = reference_design(
        span_m=s["span_m"], chord_m=s["chord_m"], tail_arm_m=s["tail_arm_m"],
        boom_spacing_set_m=s["boom_spacing_m"],
        taper_ratio=s["taper_ratio"], taper_start_frac=s["taper_start_frac"],
        washout_tip_deg=s["washout_tip_deg"],
        washout_start_frac=s["washout_start_frac"],
        elevator_frac=s["elevator_frac"],
        prop_name="MJ-21x14EL", prop_diameter_in=21.0,
    )
    print(f"Site {config.LATITUDE_DEG:.6f} N  {config.LONGITUDE_DEG:.6f} E  "
          f"field {config.ALTITUDE_M:.0f} m MSL  "
          f"cruise {config.CRUISE_ALT_AGL_M / config.FT_TO_M:.0f} ft AGL")
    print(f"Boom {config.BOOM_MASS_PER_M:.3f} kg/m  "
          f"OD {config.BOOM_DIAMETER_M*1000:.1f} mm  "
          f"ref boom {d0.boom_length:.3f} m (c/4 → V-stab TE)  "
          f"ref total {d0.mass_kg:.3f} kg")
    print(f"Motor default {config.MOTOR_DEFAULT}")
    print(f"Vv floor {config.TAIL_VOLUME_V:.3f}")

    env = environment.design_day(config.SOLSTICE_DATE)
    print("=" * 70)
    print("PHASE 4 — continuous aero, 12L, S&C, Vv=0.030, 1.3 Vs")
    p_a, p_e = d0.roll_rate_parts_deg_s()
    print(f"  Start roll {d0.roll_rate_deg_s():.1f} deg/s  "
          f"(aileron {p_a:.1f} + elevon {p_e:.1f})")
    print(f"  Start packing: {d0.packing_geometry_reason() or 'ok'}  "
          f"cells={d0.n_cells}")
    df = optimize.search_continuous(
        env, verbose=True, one_string_per_bay=True,
        motor_name=MOTOR, prop_names=list(PROPS),
    )
    path = OUT / "phase4_sc_washout.csv"
    if df.empty:
        print("  No candidates survived.")
        return
    df.to_csv(path, index=False)
    print(f"  {len(df)} candidates → {path}")
    print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
    print("  Top 12:")
    print(df[COLS].head(12).to_string(index=False))

    w = optimize.winner(df)
    d = optimize.design_from_row(w)
    psys = PropulsionSystem(prop=load_prop(str(w["prop"])), motor=_drive())
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    d.prop_name = str(w["prop"])
    r = mission.simulate(d, env, psys)
    print("  Winner re-sim:")
    print(f"    {d.span_m:.2f}×{d.chord_m:.3f} λ={d.taper_ratio:.2f} "
          f"wo={d.washout_tip_deg:.1f}°@{d.washout_start_frac:.2f}  "
          f"tail {d.tail_arm_m:.2f} m  boom {d.boom_spacing:.2f} m")
    print(f"    cells={d.n_cells}  plan {d.string_plan_label()}  "
          f"mass={d.mass_kg:.3f} kg  booms={d.mass_breakdown()['booms']:.3f} kg")
    print(f"    Pnight={r.p_night_w:.1f} W  solar={r.solar_wh:.0f} Wh  "
          f"margin={r.margin_wh:.1f} Wh  SOC {r.soc_min:.3f}/{r.soc_end:.3f}  "
          f"closed={r.closed}")
    pa, pe = d.roll_rate_parts_deg_s()
    print(f"    roll {d.roll_rate_deg_s():.1f} deg/s "
          f"(aileron {pa:.1f} + elevon {pe:.1f})  "
          f"Cn_β={d.cn_beta():.3f}  Vloiter={r.v_night:.2f} m/s")
    print(f"    boom {d.boom_length:.3f} m  fuselage {d.fuselage_length_m:.3f} m  "
          f"Swet/pod {d.fuselage_wetted_each_m2*1e6:.1f} mm²")
    print(f"    packing {d.packing_geometry_reason() or 'ok'}")


if __name__ == "__main__":
    main()
