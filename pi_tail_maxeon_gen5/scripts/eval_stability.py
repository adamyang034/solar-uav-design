"""Reference-design dump for lateral/directional sizing (rev6 items 1, 2, 4, 7).

No full search. Prints pass/fail and the night-watt hit vs the old 1.2 Vs floor.

Usage:  .venv/bin/python pi_tail_maxeon_gen5/scripts/eval_stability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config
from solar_uav.aircraft import RHO_NIGHT, reference_design
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def test_aileron_layout():
    print("-- aileron layout --")
    tap = reference_design()
    check("tapered: cells off aileron", not tap.cells_on_aileron())
    y_drop = tap.y_second_row_drop_m()
    y_ail = tap.aileron_y_inner()
    check("tapered aileron starts at or inboard of second-row drop",
          y_ail <= y_drop + 0.02,
          f"y_ail={y_ail:.3f} y_drop={y_drop:.3f}")
    check("aileron does not cross inboard of the boom",
          y_ail >= 0.5 * tap.boom_spacing - 1e-6,
          f"{y_ail:.3f} vs boom {0.5*tap.boom_spacing:.3f}")

    rect = reference_design(taper_ratio=1.0, taper_start_frac=1.0)
    check("rectangular: cells may cover ailerons", rect.cells_on_aileron())
    p_tiny = tap.roll_rate_deg_s(y_inner=tap.aileron_y_tip_m() - 0.10)
    check("a 10 cm tip strip cannot make 35 deg/s",
          p_tiny < config.ROLL_RATE_MIN_DEG_S,
          f"{p_tiny:.1f} deg/s")


def test_fins_and_loiter():
    print("-- fins / boom floor / loiter speed --")
    short = reference_design(tail_arm_m=0.90)
    mid = reference_design(tail_arm_m=1.30)
    long = reference_design(tail_arm_m=2.00)
    check("long boom does not shrink fins below the 1.30 m-arm area",
          abs(long.vstab_area_total - mid.vstab_area_total) < 1e-8,
          f"long {long.vstab_area_total:.4f} vs mid {mid.vstab_area_total:.4f}")
    check("short boom still grows fins (fixed Vv)",
          short.vstab_area_total > mid.vstab_area_total + 1e-6,
          f"short {short.vstab_area_total:.4f} vs mid {mid.vstab_area_total:.4f}")
    check("|Cn_r| grows with boom at the area floor",
          abs(long.cn_r()) > abs(mid.cn_r()),
          f"long {long.cn_r():.4f} vs mid {mid.cn_r():.4f}")

    d = reference_design()
    vs = d.stall_speed()
    vmin = d.min_airspeed()
    check("loiter floor is 1.3 Vs (or 15 kt)",
          abs(vmin - max(1.3 * vs, config.MIN_AIRSPEED_WIND_MS)) < 1e-6,
          f"Vmin={vmin:.2f}  1.3 Vs={1.3*vs:.2f}")
    check("1.3 Vs is above the 1.2 never-below",
          vmin >= config.STALL_MARGIN_FACTOR * vs - 1e-9)


def test_reference_closes_s_and_c():
    print("-- reference airplane S&C --")
    d = reference_design()
    why = d.stability_fail_reason()
    check("stability_ok", why is None, why or "")
    print(f"     mass {d.mass_kg:.2f} kg  cells {d.n_cells}  "
          f"Sv {d.vstab_area_total:.3f} m²  Vv {d.tail_volume_v_actual():.3f}")
    print(f"     aileron y={d.aileron_y_inner():.2f}–{d.aileron_y_tip_m():.2f} m  "
          f"({d.aileron_span_each_m():.2f} m each)")
    print(f"     p={d.roll_rate_deg_s():.1f} deg/s  "
          f"Cn_β={d.cn_beta():.3f}  Cn_r={d.cn_r():.3f}")
    print(f"     Vs={d.stall_speed():.2f}  Vloiter={d.min_airspeed():.2f}  "
          f"Vmp={d.min_power_speed():.2f} m/s")

    ac = d.to_asb()
    names = [cs.name for w in ac.wings for xs in w.xsecs for cs in xs.control_surfaces]
    check("ASB has aileron", "aileron" in names, str(names))
    check("ASB has elevator", "elevator" in names, str(names))
    check("ASB has elevon", "elevon" in names, str(names))
    check("ASB has no rudder", "rudder" not in names, str(names))
    check("packing geometry ok",
          d.packing_geometry_ok(),
          d.packing_geometry_reason() or "")

    sys_p = PropulsionSystem(
        prop=load_prop(config.REF_PROP),
        motor=drive_for(config.REF_MOTOR))
    v = d.min_power_speed()
    t_one = sys_p.max_thrust_n(v, rho=RHO_NIGHT) / config.N_MOTORS
    check("differential-thrust yaw vs 5 deg sideslip and yaw rate",
          d.differential_thrust_yaw_ok(t_one, v),
          f"T_one_max={t_one:.1f} N  r_loiter={d.yaw_rate_deg_s(t_one, v, level_flight=True):.1f} deg/s")
    check("zero thrust cannot yaw",
          not d.differential_thrust_yaw_ok(0.0, v),
          "T_one=0")
    check("half a newton of max thrust cannot make 5 deg/s",
          d.yaw_rate_deg_s(0.5, v, level_flight=True) < config.YAW_RATE_MIN_DEG_S,
          f"{d.yaw_rate_deg_s(0.5, v, level_flight=True):.2f} deg/s")
    r_loiter = d.yaw_rate_deg_s(t_one, v, level_flight=True)
    r_max = d.yaw_rate_deg_s(t_one, v)
    r_lvl = d.yaw_rate_deg_s(t_one, v, level_flight=True,
                             against_weathercock=True)
    print(f"     DT yaw loiter {r_loiter:.1f} deg/s  "
          f"max-effort {r_max:.1f} deg/s  "
          f"vs 5° β leftover {r_lvl:.2f} deg/s")
    print(f"     ṙ_loiter={d.yaw_accel_rad_s2(t_one, v, level_flight=True):.2f} rad/s²  "
          f"t_5°={d.yaw_correct_time_s(t_one, v, level_flight=True):.2f} s  "
          f"Izz={d.yaw_inertia_kgm2():.2f} kg m²")
    print(f"     N_dt_max={d.differential_thrust_moment_n(t_one, v_ms=v):.1f} N·m  "
          f"N_dt_loiter={d.differential_thrust_moment_n(t_one, v_ms=v, level_flight=True):.1f} N·m  "
          f"N_β={d.weathercock_moment_n(v):.1f} N·m  "
          f"N_r={d.yaw_damping_n_per_rads(v):.1f} N·m/(rad/s)")

    drag = float(d.drag_n(v))
    fl = sys_p.level_flight(v, drag, rho=RHO_NIGHT)
    p_bus = fl["p_bus_w"] + config.AVIONICS_POWER_W if fl else float("nan")
    print(f"     night V={v:.2f} m/s  D={drag:.2f} N  bus {p_bus:.1f} W "
          f"(incl. {config.AVIONICS_POWER_W:.0f} W avionics)")
    bd = d.drag_breakdown(v)
    gaps = bd["drag_n"].get("control_gaps", 0.0)
    print(f"     control-surface gap drag {gaps:.3f} N  "
          f"({100*gaps/bd['drag_total_n']:.1f}% of total)")
    from solar_uav.asb_physics import audit_design
    a = audit_design(d)
    print(f"     ASB envelope: k_ε={a['used']['downwash_k']:.3f}  "
          f"e={a['used']['oswald_e']:.3f}  "
          f"Cl_p={a['used']['clp']:.3f}  Cn_β={a['used']['cnb']:.3f}  "
          f"Iyy={a['used']['iyy']:.3f} kg m²")
    for f in a["flags"]:
        print(f"     FLAG  {f}")


def main() -> int:
    print("=" * 70)
    print("Lateral / directional sizing on the reference airframe")
    test_aileron_layout()
    test_fins_and_loiter()
    test_reference_closes_s_and_c()
    print("=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} failed check(s):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All S&C checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
