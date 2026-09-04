"""Phase 3 + 4 checks, then the discrete optimizer.

Usage:  .venv/bin/python scripts/run_phase34.py
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

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import Design, RHO_NIGHT, clmax_2d, profile_cd
from solar_uav.cad import export_all
from solar_uav.components.battery import BatteryBank
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop, shortlist_props
from solar_uav.components.solar_array import SolarArray, max_cells_per_string

OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def sample_design(**kwargs) -> Design:
    defaults = dict(span_m=5.5, chord_m=0.40, tail_arm_m=1.5,
                    n_packs=3, cells_per_string=16, n_strings=4,
                    elevator_frac=0.28)
    defaults.update(kwargs)
    d = Design(**defaults)
    # Fill as many strings as the bays allow without going overweight later.
    d.n_strings = max(1, d.max_strings())
    return d


def test_profile_cd():
    print("-- profile_cd interpolates the NeuralFoil table --")
    df = pd.read_csv(Path(__file__).resolve().parents[1] / "data/polars/s4310.csv")
    g = df[(df["re"] == 150000.0) & (df["alpha_deg"] >= 0)]
    row = g.iloc[20]
    cd = profile_cd("s4310", float(row["cl"]), 150000.0)
    rel = abs(cd - row["cd"]) / row["cd"]
    check("cd matches polar at known CL", rel < 0.05,
          f"got {cd:.5f} vs table {row['cd']:.5f}")
    check("clmax_2d in a sane range", 1.1 < clmax_2d("s4310") < 1.8,
          f"{clmax_2d('s4310'):.3f}")


def test_mass_and_geometry():
    print("-- mass / geometry coupling --")
    d = sample_design()
    m = d.mass_breakdown()
    check("mass breakdown sums", abs(sum(m.values()) - d.mass_kg) < 1e-9,
          f"{sum(m.values())} vs {d.mass_kg}")
    d2 = sample_design(span_m=6.0)
    check("longer span is heavier", d2.mass_kg > d.mass_kg,
          f"{d2.mass_kg:.2f} vs {d.mass_kg:.2f}")
    check("cell count is an integer", d.n_cells == int(d.n_cells)
          and d.n_cells % d.cells_per_string == 0, str(d.n_cells))
    check("pack count is an integer", isinstance(d.n_packs, int), str(d.n_packs))
    check("strings fit in bays", d.solar_feasible(),
          f"strings {d.n_strings} max {d.max_strings()}")
    check("string length <= GVB-8 MPPT limit",
          d.cells_per_string <= max_cells_per_string(),
          str(max_cells_per_string()))
    bays = d.solar_bays()
    used = d.n_cells
    cap = sum(b.capacity for b in bays.values())
    check("cells do not hang off the planform", used <= cap,
          f"{used} cells vs {cap} slots")
    check("boom length positive", d.boom_length > 0.5, f"{d.boom_length:.2f} m")
    check("H-stab span is from V_H × AR (not the center panel)",
          abs(d.hstab_span - float(np.sqrt(d.hstab_ar * d.hstab_area))) < 1e-6
          or d.hstab_span <= config.HSTAB_SPAN_FRAC_MAX * d.span_m + 1e-9,
          f"H={d.hstab_span:.3f} AR-span={np.sqrt(d.hstab_ar*d.hstab_area):.3f} "
          f"panel={d.boom_spacing:.3f}")
    check("no H-stab solar bay", "hstab" not in bays, str(list(bays)))
    print(f"     sample mass {d.mass_kg:.2f} kg, {d.n_cells} cells, "
          f"AR {d.aspect_ratio:.1f}, SM {d.static_margin():.3f}")


def test_aero():
    print("-- drag polar / stall / control --")
    d = sample_design()
    v = np.linspace(d.min_airspeed(), 18.0, 12)
    drag = np.asarray(d.drag_n(v), dtype=float)
    p = d.power_aero_w(v)
    check("drag finite and positive", np.all(np.isfinite(drag)) and np.all(drag > 0))
    check("high-speed drag exceeds mid-speed drag", drag[-1] > drag[2],
          f"{drag[-1]:.1f} vs {drag[2]:.1f} N")
    check("min-power speed >= stall-margin floor",
          d.min_power_speed() >= d.min_airspeed() - 1e-6,
          f"{d.min_power_speed():.2f} vs {d.min_airspeed():.2f}")
    vmp = d.min_power_speed()
    vmin = d.min_airspeed()
    v_lo_b, v_hi_b = config.V_CRUISE_BOUNDS_MS
    v_hi = max(vmin + 1.0, float(v_hi_b))
    grid = np.linspace(max(vmin, float(v_lo_b)), v_hi, 17)
    p_grid = np.asarray(d.power_aero_w(grid), dtype=float)
    p_star = float(np.asarray(d.power_aero_w(vmp)).reshape(-1)[0])
    check("min-power speed is continuous (≤ 17-point grid)",
          p_star <= float(p_grid.min()) + 1e-3,
          f"Vmp={vmp:.4f} P={p_star:.3f} vs grid {p_grid.min():.3f}")
    if vmp > vmin + 0.5 * config.V_CRUISE_TOL_MS:
        step = config.V_CRUISE_TOL_MS
        check("flown speed is on 0.01 m/s steps",
              abs(vmp / step - round(vmp / step)) < 1e-9,
              f"{vmp:.4f} m/s")
    check("min-power search starts at 12 m/s",
          abs(config.V_CRUISE_START_MS - 12.0) < 1e-12)
    vs = d.stall_speed()
    check("stall speed in 6-14 m/s", 6.0 < vs < 14.0, f"{vs:.2f} m/s")
    check("static margin above minimum",
          d.static_margin() >= config.STATIC_MARGIN_MIN,
          f"{d.static_margin():.3f}")
    check("elevator trim feasible", d.elevator_authority_ok())
    check("pitch acceleration sufficient", d.pitch_ok(),
          f"{d.pitch_accel_rad_s2(d.min_airspeed()):.2f} rad/s²")
    from solar_uav.aircraft import reference_design
    ref = reference_design()
    check("yaw weathercock/damping floors are off",
          config.REQUIRE_YAW_STABILITY is False)
    check("reference roll rate >= 35 deg/s",
          ref.roll_ok(), f"{ref.roll_rate_deg_s():.1f} deg/s")
    check("rudder yaw-rate floor is 5 deg/s",
          abs(config.YAW_RATE_MIN_DEG_S - 5.0) < 1e-12)
    check("reference rudder yaw is feasible",
          ref.rudder_yaw_ok(), f"{ref.yaw_rate_deg_s():.1f} deg/s")
    check("loiter speed is 1.3 Vs",
          ref.min_airspeed() >= config.LOITER_STALL_FACTOR * ref.stall_speed() - 1e-6,
          f"{ref.min_airspeed():.2f} vs 1.3×{ref.stall_speed():.2f}")
    airplane = d.to_asb()
    check("AeroSandbox airplane builds", airplane is not None
          and len(airplane.wings) >= 3, str(airplane))


def test_battery_and_mission_physics():
    print("-- battery + energy-march physics --")
    bank = BatteryBank(n_packs=3, soc=1.0)
    e0 = bank.soc * bank.energy_total_wh
    for _ in range(60):  # 1 hour at 100 W
        bank.step(-100.0, 60.0)
    e1 = bank.soc * bank.energy_total_wh
    check("discharge lowers SOC", bank.soc < 0.99, f"SOC={bank.soc:.3f}")
    check("discharged energy ~ 100 Wh", abs((e0 - e1) - 100) < 25,
          f"ΔE={e0-e1:.1f} Wh")

    bank2 = BatteryBank(n_packs=3, soc=0.5)
    bank2.step(500.0, 60.0)
    i_limit = config.PACK_CHARGE_MAX_A * 3
    # 500 W into ~22 V is ~23 A, above 18 A limit, so it must clip.
    check("charge current clips at 6 A/pack",
          bank2.soc < 0.5 + (500 * 1 / 60) / bank2.energy_total_wh - 1e-4,
          f"SOC={bank2.soc:.4f}")

    env = environment.design_day(config.SOLSTICE_DATE)
    # Night-only: zero the array by using a 1-cell? Can't. Use a design and
    # check that SOC falls while poa is ~0.
    d = sample_design(n_packs=4)
    d.n_strings = max(1, d.max_strings())
    props = shortlist_props()
    name = "18x12E" if (props["name"] == "18x12E").any() else props.iloc[0]["name"]
    psys = PropulsionSystem(prop=load_prop(name))
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    res = mission.simulate(d, env, psys)
    print(f"     sample mission: closed={res.closed}  minSOC={res.soc_min:.3f}  "
          f"margin={res.margin_wh:.0f} Wh  Pnight={res.p_night_w:.0f} W  "
          f"climb={res.climb_ms:.2f} m/s  reason={res.reason}")
    check("mission returns a 24 h trace",
          res.soc_trace.size > 100 and res.hours[-1] >= 23.0,
          f"n={res.soc_trace.size} span={res.hours[-1]:.1f}h")
    check("night load includes 5 W avionics",
          res.p_night_w > config.AVIONICS_POWER_W,
          f"{res.p_night_w:.1f} W")
    if np.max(res.p_solar) > 1.3 * res.p_night_w:
        check("battery-true night is 8-16 h (array covers cruise with margin)",
              8.0 <= res.battery_night_h <= 16.0,
              f"{res.battery_night_h:.1f} h")
    else:
        print(f"     (sample array only barely exceeds cruise — "
              f"peak solar {res.p_solar.max():.0f} W vs night {res.p_night_w:.0f} W, "
              f"battery-night {res.battery_night_h:.1f} h)")
    # SOC should drop after the start (which is afternoon-full).
    check("SOC falls through the night",
          float(np.min(res.soc_trace[: int(0.4 * len(res.soc_trace))]))
          < 0.99,
          f"min early SOC {res.soc_trace[:50].min():.3f}")
    return d, res, env, psys


def test_integers_in_search_row():
    print("-- optimizer reports discrete cells/packs --")
    d = sample_design(n_packs=3, cells_per_string=16)
    d.n_strings = d.max_strings()
    check("n_cells == n_strings * cells_per_string",
          d.n_cells == d.n_strings * d.cells_per_string)


def test_site_motor_boom_fuse_pack():
    print("-- site / 12L / boom / fuselage / packing --")
    check("site is El Mirage latitude",
          abs(config.LATITUDE_DEG - 34.646849) < 1e-8, str(config.LATITUDE_DEG))
    check("site is El Mirage longitude",
          abs(config.LONGITUDE_DEG - (-117.605977)) < 1e-8,
          str(config.LONGITUDE_DEG))
    check("cruise is 400 ft AGL",
          abs(config.CRUISE_ALT_AGL_M / config.FT_TO_M - 400.0) < 0.1,
          f"{config.CRUISE_ALT_AGL_M:.2f} m")
    check("default motor is A40-12L direct",
          config.MOTOR_DEFAULT == "A40-12L-V4-kv410-direct",
          config.MOTOR_DEFAULT)
    check("Vv floor is 0.030 (one fin)",
          abs(config.TAIL_VOLUME_V - 0.030) < 1e-9,
          str(config.TAIL_VOLUME_V))
    check("one motor, one boom, one fuselage",
          config.N_MOTORS == 1 and config.N_BOOMS == 1
          and config.N_FUSELAGES == 1, 
          f"motors={config.N_MOTORS} booms={config.N_BOOMS}")
    check("no H-stab solar", config.SOLAR_ON_HSTAB is False)
    check("paired-rotation props are not required",
          config.REQUIRE_PAIRED_ROTATION_PROPS is False)
    check("pack count is 2 or 3, cap 3",
          tuple(config.PACK_GRID) == (2, 3), str(config.PACK_GRID))
    check("chord floor is 300 mm, start 310 mm",
          abs(config.CHORD_BOUNDS_M[0] - 0.300) < 1e-9
          and abs(config.CHORD_BOUNDS_M[1] - 0.520) < 1e-9
          and abs(config.OPT_START["chord_m"] - 0.310) < 1e-9)
    check("tail arm start is 0.90 m",
          abs(config.OPT_START["tail_arm_m"] - 0.90) < 1e-9)
    check("span high / start is 6 m",
          abs(config.SPAN_BOUNDS_M[1] - 6.0) < 1e-9
          and abs(config.OPT_START["span_m"] - 6.0) < 1e-9)
    check("cruise speed start is 12 m/s",
          abs(config.CONTINUOUS["v_cruise_ms"][2] - 12.0) < 1e-12)
    for k, (lo, hi, x0) in config.CONTINUOUS.items():
        check(f"{k} start in [{lo}, {hi}]",
              lo <= x0 <= hi, f"start={x0}")
        check(f"{k} range is ordered", hi > lo, f"[{lo}, {hi}]")
    for k in config.OPT_KEYS:
        check(f"DE key {k} is in CONTINUOUS", k in config.CONTINUOUS)

    from solar_uav.aircraft import (reference_design, fuselage_wetted_each_m2,
                                    FUSELAGE_RADIUS_M)
    d = reference_design()
    check("wing areal is 0.8 × 0.84 kg/m² (main wing only)",
          abs(config.WING_AREAL_MASS - 0.84 * 0.8) < 1e-12,
          str(config.WING_AREAL_MASS))
    check("boom is 0.290 kg/m, 1.5 in OD (single load path)",
          abs(config.BOOM_MASS_PER_M - 0.290) < 1e-12
          and abs(config.BOOM_DIAMETER_M - 1.5 * 0.0254) < 1e-12,
          f"{config.BOOM_MASS_PER_M} kg/m  Ø{config.BOOM_DIAMETER_M*1000:.1f} mm")
    check("H-stab is in the wing plane",
          abs(d.hstab_z) < 1e-9, f"{d.hstab_z:.3f} m")
    check("V-stab LE is behind H-stab TE",
          d.vstab_le_x() + 1e-9 >= d.hstab_te_x(),
          f"V LE {d.vstab_le_x():.3f} vs H TE {d.hstab_te_x():.3f}")
    check("V-stab arm is in the DE vector",
          "vstab_arm_m" in config.OPT_KEYS)
    check("V-stab arm start is 1.20 m",
          abs(config.OPT_START["vstab_arm_m"] - 1.20) < 1e-9)
    x_c4 = d.boom_x_front
    x_vte = d.vstab_te_x
    check("one boom on the centerline",
          abs(d.boom_length - (x_vte - x_c4)) < 1e-9,
          f"{d.boom_length:.3f} vs {x_vte-x_c4:.3f}")
    check("no aft boom", abs(d.aft_boom_length) < 1e-12, str(d.aft_boom_length))
    check("V-stab areal is the same as H-stab",
          abs(config.TAIL_AREAL_MASS - 0.44) < 1e-12,
          str(config.TAIL_AREAL_MASS))
    check("boom starts at wing c/4, not the prop",
          abs(d.boom_x_front - 0.25 * d.chord_m) < 1e-9
          and d.boom_x_front > d.prop_x + 0.05,
          f"c/4 {d.boom_x_front:.3f}  prop {d.prop_x:.3f}")
    check("fuselage is prop disk to wing TE",
          abs(d.fuselage_length_m - (config.PROP_LE_OFFSET_M + d.chord_m)) < 1e-9,
          f"{d.fuselage_length_m:.3f} m")
    swet_cad = fuselage_wetted_each_m2(config.FUSELAGE_LENGTH_REF_M)
    check("CAD fuselage Swet at 980 mm",
          abs(swet_cad - config.FUSELAGE_WETTED_REF_M2) < 1e-12,
          f"{swet_cad*1e6:.3f} mm²")
    check("fuselage radius is finite", FUSELAGE_RADIUS_M > 0.01, str(FUSELAGE_RADIUS_M))
    why = d.packing_geometry_reason()
    check("reference packing is on-planform, no overlap", why is None, why or "")
    from solar_uav.components.solar_array import CellRect, packing_geometry_reason
    bad = [
        CellRect("wing_inboard", 0.0, 0.12, 0.0, 0.12),
        CellRect("wing_inboard", 0.05, 0.17, 0.05, 0.17),
    ]
    why_ov = packing_geometry_reason(
        bad, n_cells=2, span_m=d.span_m, chord_at_y=d.chord_at_y,
        boom_spacing_m=d.boom_spacing, hstab_span_m=d.hstab_span,
        hstab_chord_m=d.hstab_chord, elevator_chord_frac=d.elevator_frac,
        aileron_y_inner_m=d.aileron_y_inner(),
        aileron_chord_frac=config.AILERON_CHORD_FRAC,
        cells_on_aileron=d.cells_on_aileron())
    check("overlapping cells are rejected",
          why_ov is not None and "overlap" in why_ov, str(why_ov))
    off = [CellRect("wing_inboard", 0.0, d.chord_m + 0.05, -0.1, 0.0)]
    why_off = packing_geometry_reason(
        off, n_cells=1, span_m=d.span_m, chord_at_y=d.chord_at_y,
        boom_spacing_m=d.boom_spacing, hstab_span_m=d.hstab_span,
        hstab_chord_m=d.hstab_chord, elevator_chord_frac=d.elevator_frac,
        aileron_y_inner_m=d.aileron_y_inner(),
        aileron_chord_frac=config.AILERON_CHORD_FRAC,
        cells_on_aileron=d.cells_on_aileron())
    check("cell past the trailing edge is rejected",
          why_off is not None, str(why_off))


def test_asb_envelope():
    print("-- AeroSandbox conservative envelope --")
    from solar_uav.aircraft import reference_design, RHO_NIGHT, MU_AIR
    from solar_uav.asb_physics import audit_design, cruise_atmosphere
    check("night density is finite", 0.8 < RHO_NIGHT < 1.3, f"{RHO_NIGHT:.4f}")
    check("Sutherland mu is finite", 1e-5 < MU_AIR < 3e-5, f"{MU_AIR:.3e}")
    atm = cruise_atmosphere(config.T_AMB_MIN_C + 2.0)
    check("ASB atmosphere is ISA + temperature offset",
          abs(float(atm.temperature()) - (config.T_AMB_MIN_C + 2.0 + 273.15)) < 0.05,
          f"T={float(atm.temperature())-273.15:.2f} C")
    d = reference_design()
    d.aileron_y_inner()
    a = audit_design(d)
    check("VLM ran", bool(a["vlm"] and a["vlm"].get("ok")),
          str((a["vlm"] or {}).get("error")))
    check("downwash k used is >= 1 (no T-tail credit)",
          a["used"]["downwash_k"] >= 1.0 - 1e-9,
          f"{a['used']['downwash_k']:.3f}")
    check("used e is not better than handbook",
          a["used"]["oswald_e"] <= a["handbook"]["e"] + 1e-9,
          f"{a['used']['oswald_e']:.3f} vs {a['handbook']['e']:.3f}")
    check("AeroBuildup ran", bool(a["aerobuildup"] and a["aerobuildup"].get("ok")),
          str((a["aerobuildup"] or {}).get("error")))
    check("used |Cl_p| is at least handbook",
          abs(a["used"]["clp"]) >= abs(a["handbook"]["clp"]) - 1e-6,
          f"{a['used']['clp']:.3f} vs {a['handbook']['clp']:.3f}")
    check("used Cn_β is at most handbook",
          a["used"]["cnb"] <= a["handbook"]["cnb"] + 1e-6,
          f"{a['used']['cnb']:.3f} vs {a['handbook']['cnb']:.3f}")
    check("mesh inertia ran", bool(a["inertia"] and a["inertia"].get("ok")),
          str((a["inertia"] or {}).get("error")))
    check("used Iyy is at least lumped",
          a["used"]["iyy"] >= a["handbook"]["iyy"] - 1e-9,
          f"{a['used']['iyy']:.3f} vs {a['handbook']['iyy']:.3f}")
    check("XFoil cd scale is >= 1",
          a["used"]["cd_scale"] >= 1.0 - 1e-12, str(a["used"]["cd_scale"]))
    check("production Cl_p matches envelope",
          abs(d.cl_p() - a["used"]["clp"]) < 1e-6,
          f"{d.cl_p():.4f} vs {a['used']['clp']:.4f}")


def run_optimizer(env):
    print("=" * 70)
    print("PHASE 4 — continuous search (max energy margin)")
    df = optimize.search_continuous(
        env, verbose=True, dump_path=OUT / "phase4_candidates.csv")
    if df.empty:
        print("  No candidates survived the hard constraints.")
        return None, df
    path = OUT / "phase4_candidates.csv"
    df.to_csv(path, index=False)
    print(f"  {len(df)} candidates written to {path}")
    print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
    print("  Failure modes:")
    print(df["reason"].value_counts().head(8).to_string())
    print("  Top 5 by margin:")
    cols = ["span_m", "chord_m", "tail_arm_m", "vstab_arm_m", "n_packs",
            "n_cells", "prop", "mass_kg",
            "margin_wh", "soc_min", "soc_end", "p_night_w", "closed"]
    print(df[cols].head(5).to_string(index=False))
    w = optimize.winner(df)
    print("  Winner:")
    cols = ["span_m", "chord_m", "n_packs", "n_strings", "cells_per_string",
            "n_cells", "prop", "mass_kg", "margin_wh", "soc_min", "p_night_w",
            "climb_ms", "closed", "reason"]
    if "string_plan" in w.index:
        cols = ["span_m", "chord_m", "tail_arm_m", "vstab_arm_m", "n_packs",
                "string_plan", "n_cells",
                "prop", "mass_kg", "margin_wh", "soc_min", "soc_end", "cycle_wh",
                "p_night_w",
                "climb_ms", "closed", "reason"]
    print(w[cols].to_string())
    check("winner mass <= 12 kg", w["mass_kg"] <= config.MTOW_MAX_KG + 1e-6,
          f"{w['mass_kg']:.3f}")
    check("winner span <= 6 m", w["span_m"] <= config.WINGSPAN_MAX_M + 1e-6,
          f"{w['span_m']}")
    check("winner cell count integer",
          float(w["n_cells"]) == int(w["n_cells"]))
    check("winner pack count integer",
          float(w["n_packs"]) == int(w["n_packs"]))
    check("winner packing ok", bool(w.get("packing_ok", True)))

    d_win = optimize.design_from_row(w)
    paths = export_all(d_win)
    print(f"  CAD viewer: {paths['html']}")

    print("-- catalog motors on this airframe (prop re-picked) --")
    prop_names = optimize._prop_candidates()
    cache = {n: load_prop(n) for n in prop_names}
    motor_rows = []
    for key in config.MOTOR_CATALOG:
        d_m = optimize.design_from_row(w)
        d_m.motor_name = key
        drive = drive_for(key)
        systems = {n: PropulsionSystem(prop=cache[n], motor=drive)
                   for n in prop_names}
        rec = optimize.evaluate_design(
            d_m, env, prop_names, cache, drive, systems)
        if rec is None:
            print(f"  {key}: no climb-legal prop")
            continue
        motor_rows.append(rec)
        print(f"  {key}  {rec['prop']}  mass={rec['mass_kg']:.2f} kg  "
              f"Pnight={rec['p_night_w']:.1f} W  margin={rec['margin_wh']:.1f} Wh  "
              f"closed={rec['closed']}")
    if motor_rows:
        pd.DataFrame(motor_rows).to_csv(OUT / "phase4_motors_on_winner.csv",
                                        index=False)
    return w, df


def plots(env, winner_row, df, sample_res):
    # Drag polar of a representative design
    d = sample_design()
    v = np.linspace(max(6.0, 0.9 * d.stall_speed()), 20.0, 40)
    drag = np.asarray(d.drag_n(v), dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(v, drag, lw=1.5)
    axes[0].axvline(d.stall_speed(), color="r", ls="--", label="stall")
    axes[0].axvline(d.min_airspeed(), color="k", ls=":", label="v_min")
    axes[0].set_xlabel("Airspeed [m/s]")
    axes[0].set_ylabel("Drag [N]")
    axes[0].legend()
    axes[0].set_title("Phase 3 drag polar (sample 5.5 m design)")
    axes[1].plot(v, d.power_aero_w(v), lw=1.5)
    axes[1].axvline(d.min_power_speed(), color="g", ls="--", label="min power")
    axes[1].set_xlabel("Airspeed [m/s]")
    axes[1].set_ylabel("Shaft-equivalent power D·V [W]")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT / "phase3_drag_polar.png", dpi=150)
    plt.close(fig)

    # Sample mission traces
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(sample_res.hours, sample_res.p_solar, label="array to bus")
    axes[0].plot(sample_res.hours, sample_res.p_load, label="propulsion+avionics")
    axes[0].set_ylabel("Power [W]")
    axes[0].legend()
    axes[0].set_title("24 h energy march (sample design, start = last surplus)")
    axes[1].plot(sample_res.hours, sample_res.soc_trace * 100, lw=1.5)
    axes[1].axhline(config.SOC_MIN * 100, color="r", ls="--", label="20% floor")
    axes[1].set_ylabel("SOC [%]")
    axes[1].legend()
    axes[2].set_xlabel("Hours from afternoon-full")
    axes[2].axis("off")
    fig.tight_layout()
    fig.savefig(OUT / "phase4_sample_mission.png", dpi=150)
    plt.close(fig)

    if df is None or df.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    closed = df["closed"]
    axes[0].scatter(df.loc[~closed, "mass_kg"], df.loc[~closed, "margin_wh"],
                    s=18, alpha=0.5, label="open")
    if closed.any():
        axes[0].scatter(df.loc[closed, "mass_kg"], df.loc[closed, "margin_wh"],
                        s=28, c="tab:green", label="closed")
    axes[0].axvline(config.MTOW_MAX_KG, color="k", ls="--")
    axes[0].axhline(0, color="r", ls=":")
    axes[0].set_xlabel("Mass [kg]")
    axes[0].set_ylabel("Energy margin [Wh]")
    axes[0].legend()
    axes[0].set_title("Phase 4 trade space")
    axes[1].scatter(df["n_cells"], df["n_packs"], c=df["margin_wh"],
                    cmap="coolwarm", s=24)
    cb = fig.colorbar(axes[1].collections[0], ax=axes[1])
    cb.set_label("margin Wh")
    axes[1].set_xlabel("Cell count")
    axes[1].set_ylabel("Pack count")
    fig.tight_layout()
    fig.savefig(OUT / "phase4_tradespace.png", dpi=150)
    plt.close(fig)

    # Re-simulate winner for a clean trace
    if winner_row is None:
        return
    d = optimize.design_from_row(winner_row)
    psys = PropulsionSystem(prop=load_prop(str(winner_row["prop"])))
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    res = mission.simulate(d, env, psys)
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(res.hours, res.p_solar, label="array to bus")
    axes[0].plot(res.hours, res.p_load, label="propulsion+avionics")
    axes[0].set_ylabel("Power [W]")
    axes[0].legend()
    axes[0].set_title(
        f"Winner: {d.span_m} m × {d.chord_m} m, {d.n_cells} cells, "
        f"{d.n_packs} packs, {winner_row['prop']}, {d.mass_kg:.2f} kg")
    axes[1].plot(res.hours, res.soc_trace * 100, lw=1.5)
    axes[1].axhline(config.SOC_MIN * 100, color="r", ls="--")
    axes[1].set_ylabel("SOC [%]")
    axes[1].set_xlabel("Hours from afternoon-full")
    fig.tight_layout()
    fig.savefig(OUT / "phase4_winner_mission.png", dpi=150)
    plt.close(fig)

    # Mass pie
    fig, ax = plt.subplots(figsize=(7, 5))
    mb = d.mass_breakdown()
    ax.pie(mb.values(), labels=mb.keys(), autopct="%1.0f%%",
           textprops={"fontsize": 8})
    ax.set_title(f"Mass breakdown — {d.mass_kg:.2f} kg")
    fig.tight_layout()
    fig.savefig(OUT / "phase4_winner_mass.png", dpi=150)
    plt.close(fig)


def main():
    print("=" * 70)
    print("PHASE 3/4 CHECKS")
    test_profile_cd()
    test_mass_and_geometry()
    test_aero()
    d, sample_res, env, _ = test_battery_and_mission_physics()
    test_integers_in_search_row()
    test_site_motor_boom_fuse_pack()
    test_asb_envelope()

    if FAILURES:
        print("=" * 70)
        print(f"{len(FAILURES)} CHECK(S) FAILED:")
        for f in FAILURES:
            print("  -", f)

    do_search = "--search" in sys.argv
    if do_search:
        w, df = run_optimizer(env)
        plots(env, w, df, sample_res)
    else:
        print("=" * 70)
        print("Skipping the long search (pass --search to run it).")
        w, df = None, None

    print("=" * 70)
    if FAILURES:
        print(f"Finished with {len(FAILURES)} failed check(s). See above.")
        sys.exit(1)
    print(f"All checks passed. Plots in {OUT}" if do_search else
          "All checks passed.")


if __name__ == "__main__":
    main()
