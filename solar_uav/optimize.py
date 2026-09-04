"""Phase 4 — design-space search.

Aero variables (span, chord, H-stab arm, V-stab arm, boom spacing, taper,
washout, elevator fraction) are continuous. Integer / catalog quantities stay
discrete: cell count (from packing), pack count, motor, ESC. Propellers
are a discrete inner pick (lowest night bus that still climbs).

`search_continuous()` is the production path (differential evolution).
`search()` is the legacy exhaustive grid, kept for neighborhood dumps.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config, environment
from .aircraft import RHO_DAY, RHO_NIGHT, Design
from .components.propulsion import PropulsionSystem, load_prop, shortlist_props
from .components.motor import drive_for
from .mission import simulate


def _prop_candidates(max_n: int | None = None) -> list[str]:
    """Every shortlisted electric prop. No diameter-cap subsample."""
    idx = shortlist_props()
    if idx.empty:
        raise RuntimeError("No electric APC/Mejzlik props in the catalog window")
    names = idx["name"].tolist()
    if max_n is not None and len(names) > max_n:
        names = names[:max_n]
    return names


def _hard_constraints(d: Design) -> str | None:
    if d.span_m > config.WINGSPAN_MAX_M + 1e-9:
        return "span"
    if d.mass_kg > config.MTOW_MAX_KG:
        return "mass"
    if not d.solar_feasible():
        return "solar_layout"
    if d.stall_speed() * config.STALL_MARGIN_FACTOR > 25.0:
        return "stall"
    if not d.stability_ok():
        return d.stability_fail_reason() or "stability"
    if d.boom_length <= 0.4:
        return "boom"
    if d.vstab_le_x() + 1e-9 < d.hstab_te_x():
        return "vstab_overlap"
    return None


def _best_prop(design: Design, prop_names: list[str],
               cache: dict, motor=None,
               systems: dict | None = None) -> tuple[str, PropulsionSystem, float] | None:
    """Pick the prop with the lowest night bus power that still meets climb.

    Same optimum as testing climb on every fan: rank by cruise power, then
    accept the first that meets the climb rule.
    """
    drive = motor or drive_for(design.motor_name)
    v_night = design.min_power_speed()
    d_night = float(np.asarray(design.drag_n(v_night)).reshape(-1)[0])
    v_day = design.min_power_speed(rho=RHO_DAY)

    ranked: list[tuple[float, str, PropulsionSystem]] = []
    for name in prop_names:
        if systems is not None and name in systems:
            sys = systems[name]
        else:
            sys = PropulsionSystem(prop=cache[name], motor=drive)
        design.prop_diameter_in = sys.prop.diameter_in or 18.0
        design.prop_name = name
        if design.mass_kg > config.MTOW_MAX_KG:
            continue
        fl = sys.level_flight(v_night, d_night, rho=RHO_NIGHT)
        if fl is None:
            continue
        ranked.append((fl["p_bus_w"], name, sys))
    ranked.sort(key=lambda t: t[0])
    for p_bus, name, sys in ranked:
        design.prop_diameter_in = sys.prop.diameter_in or 18.0
        design.prop_name = name
        if design.mass_kg > config.MTOW_MAX_KG:
            continue
        t_max = sys.max_thrust_n(v_day, rho=RHO_DAY)
        roc = design.climb_rate_ideal_ms(v_day, t_max, rho=RHO_DAY)
        if roc >= config.CLIMB_RATE_REQ_MS:
            return name, sys, p_bus
    return None


def _string_options(mixed_strings: bool):
    """Yield (cells_per_string, label) for the outer packing loop."""
    if mixed_strings:
        yield None, "mixed"
        return
    for cps in config.CELLS_PER_STRING_GRID:
        yield int(cps), str(cps)


def _taper_options(pairs=None):
    """Unique (taper_ratio, taper_start_frac) pairs; rectangular once."""
    if pairs is not None:
        for p in pairs:
            yield float(p[0]), float(p[1])
        return
    yield 1.0, 1.0
    for lam in config.TAPER_RATIO_GRID:
        if lam >= 1.0 - 1e-9:
            continue
        for f in config.TAPER_START_FRAC_GRID:
            if f >= 1.0 - 1e-9:
                continue
            yield float(lam), float(f)


def _washout_options(pairs=None):
    """Unique (start_frac, tip_deg). Default is untwisted (legacy searches)."""
    if pairs is None:
        yield 0.0, 0.0
        return
    for p in pairs:
        yield float(p[0]), float(p[1])


def washout_grid() -> list[tuple[float, float]]:
    """Full discrete washout set: zero plus start × tip-angle."""
    out = [(0.0, 0.0)]
    for deg in config.WASHOUT_TIP_DEG_GRID:
        if deg <= 0.05:
            continue
        for f in config.WASHOUT_START_FRAC_GRID:
            out.append((float(f), float(deg)))
    return out


def _boom_options(grid=None):
    vals = config.BOOM_SPACING_GRID_M if grid is None else grid
    for x in vals:
        yield None if float(x) <= 0.0 else float(x)


def design_from_row(row) -> Design:
    """Rebuild a Design from a search-result row (mixed or uniform)."""
    cps = row["cells_per_string"] if "cells_per_string" in row.index else None
    if cps is None or (isinstance(cps, float) and np.isnan(cps)):
        cps = None
    elif str(cps).strip().lower() in ("", "mixed", "none", "nan", "one_per_bay"):
        cps = None
    else:
        cps = int(cps)

    def _get(name, default):
        if name not in getattr(row, "index", row):
            return default
        val = row[name]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)

    boom_set = _get("boom_spacing_set_m", 0.0)
    one_per = False
    if "one_string_per_bay" in getattr(row, "index", row):
        one_per = bool(row["one_string_per_bay"])
    n_str_raw = row["n_strings"]
    if one_per or n_str_raw is None or (isinstance(n_str_raw, float) and np.isnan(n_str_raw)):
        n_str = None
    else:
        n_str = int(n_str_raw)
    return Design(
        span_m=float(row["span_m"]),
        chord_m=float(row["chord_m"]),
        tail_arm_m=float(row["tail_arm_m"]),
        n_packs=int(row["n_packs"]),
        cells_per_string=cps,
        n_strings=n_str,
        elevator_frac=float(row["elevator_frac"]),
        taper_ratio=_get("taper_ratio", 1.0),
        taper_start_frac=_get("taper_start_frac", 1.0),
        boom_spacing_set_m=(None if boom_set <= 0 else boom_set),
        vstab_arm_set_m=(_get("vstab_arm_m", 0.0) or None),
        one_string_per_bay=one_per,
        washout_tip_deg=_get("washout_tip_deg", 0.0),
        washout_start_frac=_get("washout_start_frac", 0.0),
        motor_name=(str(row["motor"]) if "motor" in getattr(row, "index", row)
                    and pd.notna(row["motor"]) else
                    str(row["motor_name"]) if "motor_name" in getattr(row, "index", row)
                    and pd.notna(row["motor_name"]) else config.MOTOR_DEFAULT),
        prop_name=(str(row["prop"]) if "prop" in getattr(row, "index", row)
                   and pd.notna(row["prop"]) else None),
    )


def search(env: pd.DataFrame | None = None,
           verbose: bool = True,
           mixed_strings: bool = True,
           one_string_per_bay: bool = False,
           boom_grid: tuple = (0.0,),
           elevator_grid: tuple | None = None,
           motor_name: str | None = None,
           span_grid: tuple | None = None,
           chord_grid: tuple | None = None,
           tail_grid: tuple | None = None,
           taper_pairs: list | None = None,
           washout_pairs: list | None = None,
           prop_names: list[str] | None = None) -> pd.DataFrame:
    """Exhaustive discrete search. Returns one row per evaluated, feasible-
    enough candidate (including those that miss energy closure).

    one_string_per_bay: inboard + each outboard + H-stab are each one
    MPPT-legal series string. boom_grid of 0 means auto boom from Vh.
    motor_name: catalog key; each airframe re-picks the best climb-legal prop.
    """
    if env is None:
        env = environment.design_day(config.SOLSTICE_DATE)
    elevs = elevator_grid if elevator_grid is not None else config.ELEVATOR_FRAC_GRID
    spans = span_grid if span_grid is not None else config.SPAN_GRID_M
    chords = chord_grid if chord_grid is not None else config.CHORD_GRID_M
    tails = tail_grid if tail_grid is not None else config.TAIL_ARM_GRID_M
    motor_key = motor_name or config.MOTOR_DEFAULT
    drive = drive_for(motor_key)

    prop_names = (list(prop_names) if prop_names is not None
                  else _prop_candidates())
    prop_cache = {n: load_prop(n) for n in prop_names}
    sys_cache = {n: PropulsionSystem(prop=prop_cache[n], motor=drive)
                 for n in prop_names}
    washouts = list(_washout_options(washout_pairs))
    tapers = list(_taper_options(taper_pairs))
    if verbose:
        if one_string_per_bay:
            mode = "one series string per bay (GVB-8 Voc/power cap)"
        elif mixed_strings:
            mode = "mixed-length per bay"
        else:
            mode = "uniform cells/string"
            print(f"  String packing: {mode}", flush=True)
            print(f"  Outboard taper options ({len(tapers)}): {tapers}", flush=True)
            print(f"  Washout options ({len(washouts)}): {washouts}", flush=True)
            booms = list(_boom_options(boom_grid))
            print(f"  Boom / inboard span options: {booms}", flush=True)
            print(f"  Motor: {drive.spec.name}  ({motor_key})", flush=True)
            print(f"  Prop shortlist ({len(prop_names)}): {prop_names}", flush=True)

    rows = []
    n_eval = 0
    n_skip = 0
    best_holder: list = [None]
    for span in spans:
        for chord in chords:
            for lt in tails:
                for elev in elevs:
                    for n_pack in config.PACK_GRID:
                        for taper_r, taper_f in tapers:
                            for boom in _boom_options(boom_grid):
                                cps_iter = ([(None, "one_per_bay")]
                                            if one_string_per_bay
                                            else list(_string_options(mixed_strings)))
                                for cps, cps_label in cps_iter:
                                    proto = Design(
                                        span_m=span, chord_m=chord, tail_arm_m=lt,
                                        n_packs=n_pack,
                                        cells_per_string=None if one_string_per_bay else cps,
                                        n_strings=None, elevator_frac=elev,
                                        taper_ratio=taper_r,
                                        taper_start_frac=taper_f,
                                        boom_spacing_set_m=boom,
                                        one_string_per_bay=one_string_per_bay,
                                        motor_name=motor_key)
                                    max_s = proto.max_strings()
                                    if max_s < 1:
                                        n_skip += 1
                                        continue
                                    why_geom = _hard_constraints(proto)
                                    if why_geom in ("solar_layout", "mass", "span", "boom"):
                                        n_skip += len(washouts)
                                        continue
                                    n_str_choices = (
                                        {None} if one_string_per_bay
                                        else {max_s, max(1, max_s - 1)})
                                    for n_str in n_str_choices:
                                      for wo_f, wo_d in washouts:
                                        d = Design(
                                            span_m=span, chord_m=chord,
                                            tail_arm_m=lt,
                                            n_packs=n_pack,
                                            cells_per_string=(
                                                None if one_string_per_bay else cps),
                                            n_strings=n_str, elevator_frac=elev,
                                            taper_ratio=taper_r,
                                            taper_start_frac=taper_f,
                                            boom_spacing_set_m=boom,
                                            one_string_per_bay=one_string_per_bay,
                                            motor_name=motor_key,
                                            washout_start_frac=wo_f,
                                            washout_tip_deg=wo_d)
                                        why = _hard_constraints(d)
                                        if why:
                                            n_skip += 1
                                            continue
                                        picked = _best_prop(
                                            d, prop_names, prop_cache,
                                            motor=drive, systems=sys_cache)
                                        if picked is None:
                                            n_skip += 1
                                            continue
                                        pname, psys, _pnight = picked
                                        d.prop_diameter_in = (
                                            psys.prop.diameter_in or 18.0)
                                        d.prop_name = pname
                                        if d.mass_kg > config.MTOW_MAX_KG:
                                            n_skip += 1
                                            continue
                                        v_n = d.min_power_speed()
                                        t_one = psys.max_thrust_n(
                                            v_n, rho=RHO_NIGHT) / config.N_MOTORS
                                        if not d.differential_thrust_yaw_ok(t_one, v_n):
                                            n_skip += 1
                                            continue
                                        n_eval += 1
                                        mres = simulate(d, env, psys)
                                        bays = d.solar_bays()
                                        p_a, p_e = d.roll_rate_parts_deg_s()
                                        rows.append({
                                            "span_m": span,
                                            "chord_m": chord,
                                            "tail_arm_m": lt,
                                            "elevator_frac": elev,
                                            "taper_ratio": taper_r,
                                            "taper_start_frac": taper_f,
                                            "washout_tip_deg": wo_d,
                                            "washout_start_frac": wo_f,
                                            "y_washout_m": d.y_washout_m,
                                            "tip_chord_m": d.tip_chord_m,
                                            "y_taper_m": d.y_taper_m,
                                            "boom_spacing_m": d.boom_spacing,
                                            "boom_spacing_set_m": (
                                                0.0 if boom is None else boom),
                                            "hstab_chord_m": d.hstab_chord,
                                            "tail_volume_h": d.tail_volume_h(),
                                            "tail_volume_v": d.tail_volume_v_actual(),
                                            "aileron_y_inner_m": d.aileron_y_inner(),
                                            "aileron_span_each_m": d.aileron_span_each_m(),
                                            "roll_rate_deg_s": p_a + p_e,
                                            "roll_aileron_deg_s": p_a,
                                            "roll_elevon_deg_s": p_e,
                                            "cn_beta": d.cn_beta(),
                                            "cn_r": d.cn_r(),
                                            "cn_r_control": d.cn_r_control(),
                                            "yaw_rate_deg_s": d.yaw_rate_deg_s(
                                                t_one, v_n, level_flight=True),
                                            "yaw_rate_max_deg_s": d.yaw_rate_deg_s(
                                                t_one, v_n),
                                            "yaw_rate_level_deg_s": d.yaw_rate_deg_s(
                                                t_one, v_n, level_flight=True,
                                                against_weathercock=True),
                                            "yaw_correct_s": d.yaw_correct_time_s(
                                                t_one, v_n, level_flight=True),
                                            "izz_kgm2": d.yaw_inertia_kgm2(),
                                            "incidence_wing_deg": d.wing_incidence_deg(),
                                            "incidence_hstab_deg": d.hstab_incidence_deg(),
                                            "n_packs": n_pack,
                                            "cells_per_string": (
                                                "one_per_bay" if one_string_per_bay
                                                else cps_label),
                                            "one_string_per_bay": one_string_per_bay,
                                            "string_plan": d.string_plan_label(),
                                            "n_strings": d.n_mppts,
                                            "n_cells": d.n_cells,
                                            "inboard_cells": bays["wing_inboard"].capacity,
                                            "outboard_cells": bays["wing_outboard_L"].capacity,
                                            "hstab_cells": bays["hstab"].capacity,
                                            "motor": motor_key,
                                            "prop": pname,
                                            "mass_kg": d.mass_kg,
                                            "wing_area_m2": d.wing_area,
                                            "aspect_ratio": d.aspect_ratio,
                                            "static_margin": d.static_margin(),
                                            "v_stall": d.stall_speed(),
                                            "v_night": mres.v_night,
                                            "v_day": mres.v_day,
                                            "p_night_w": mres.p_night_w,
                                            "p_day_w": mres.p_day_w,
                                            "climb_ms": mres.climb_ms,
                                            "soc_min": mres.soc_min,
                                            "soc_end": mres.soc_end,
                                            "soc_start": mres.soc_start,
                                            "cycle_wh": mres.cycle_wh,
                                            "margin_wh": mres.margin_wh,
                                            "unmet_wh": mres.unmet_wh,
                                            "spilled_wh": mres.spilled_wh,
                                            "solar_wh": mres.solar_wh,
                                            "propulsion_wh": mres.propulsion_wh,
                                            "battery_night_h": mres.battery_night_h,
                                            "closed": mres.closed,
                                            "reason": mres.reason,
                                        })
                                        _maybe_write_winner_step(
                                            d, rows[-1], best_holder, verbose)
                                        if verbose and n_eval % 25 == 0:
                                            print(f"  evaluated {n_eval} "
                                                  f"(skipped {n_skip}) ...",
                                                  flush=True)

    if verbose:
        print(f"  Done: {n_eval} evaluated, {n_skip} skipped by constraints",
              flush=True)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["closed", "margin_wh"], ascending=[False, False])
    df = df.reset_index(drop=True)
    w = winner(df)
    if w is not None:
        write_winner_step(design_from_row(w))
    return df


def winner(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    closed = df[df["closed"]]
    pool = closed if len(closed) else df
    return pool.iloc[0]


def _is_better_winner(row, prev) -> bool:
    if prev is None:
        return True
    c_new, c_old = bool(row["closed"]), bool(prev["closed"])
    if c_new != c_old:
        return c_new
    return float(row["margin_wh"]) > float(prev["margin_wh"]) + 1e-9


def write_winner_step(design: Design, path: Path | None = None) -> Path | None:
    """Overwrite outputs/aircraft.step with this airplane's simple OML."""
    from .step_export import write_step
    out = path or (Path(__file__).resolve().parents[1] / "outputs" / "aircraft.step")
    try:
        return write_step(design, out)
    except Exception as exc:
        print(f"  STEP write failed: {exc}", flush=True)
        return None


def _maybe_write_winner_step(design: Design, row, best_holder: list,
                             verbose: bool = True) -> None:
    if not _is_better_winner(row, best_holder[0]):
        return
    best_holder[0] = row
    path = write_winner_step(design)
    if verbose and path is not None:
        print(f"  new best STEP  {path}  "
              f"{float(row['margin_wh']):.1f} Wh  "
              f"{float(row['span_m']):.2f}×{float(row['chord_m']):.2f} m",
              flush=True)


# ---------------------------------------------------------------------------
# Continuous aero search
# ---------------------------------------------------------------------------
CONTINUOUS_KEYS = config.OPT_KEYS


def _continuous_bounds() -> list[tuple[float, float]]:
    return [config.CONTINUOUS[k][:2] for k in CONTINUOUS_KEYS]


def x_from_start(start: dict | None = None) -> np.ndarray:
    s = dict(config.OPT_START)
    if start:
        s.update(start)
    return np.array([s[k] for k in CONTINUOUS_KEYS], dtype=float)


def design_from_x(x, *, n_packs: int = 2, motor_name: str | None = None,
                  one_string_per_bay: bool = True) -> Design:
    """Map the continuous vector to a Design. Cells/packs/motor stay discrete."""
    vals = {k: float(v) for k, v in zip(CONTINUOUS_KEYS, np.asarray(x, dtype=float))}
    lam = vals["taper_ratio"]
    f = vals["taper_start_frac"]
    if lam >= 0.995:
        lam, f = 1.0, 1.0
    span = vals["span_m"]
    boom = float(np.clip(vals["boom_spacing_m"], 0.4, 0.92 * span))
    return Design(
        span_m=span, chord_m=vals["chord_m"], tail_arm_m=vals["tail_arm_m"],
        vstab_arm_set_m=vals["vstab_arm_m"],
        n_packs=int(n_packs),
        cells_per_string=None, n_strings=None,
        elevator_frac=vals["elevator_frac"],
        taper_ratio=lam, taper_start_frac=f,
        boom_spacing_set_m=boom,
        one_string_per_bay=one_string_per_bay,
        motor_name=motor_name or config.MOTOR_DEFAULT,
        washout_tip_deg=max(0.0, vals["washout_tip_deg"]),
        washout_start_frac=float(np.clip(vals["washout_start_frac"], 0.0, 1.0)),
    )


def _candidate_record(d: Design, mres, motor_key: str, pname: str,
                      one_string_per_bay: bool,
                      t_one: float | None = None,
                      v_n: float | None = None) -> dict:
    bays = d.solar_bays()
    p_a, p_e = d.roll_rate_parts_deg_s()
    if t_one is not None and v_n is not None:
        yaw_rate = d.yaw_rate_deg_s(t_one, v_n, level_flight=True)
        yaw_max = d.yaw_rate_deg_s(t_one, v_n)
        yaw_level = d.yaw_rate_deg_s(
            t_one, v_n, level_flight=True, against_weathercock=True)
        yaw_t = d.yaw_correct_time_s(t_one, v_n, level_flight=True)
    else:
        yaw_rate = yaw_max = yaw_level = yaw_t = float("nan")
    return {
        "span_m": d.span_m,
        "chord_m": d.chord_m,
        "tail_arm_m": d.tail_arm_m,
        "vstab_arm_m": d.vstab_root_arm_m,
        "elevator_frac": d.elevator_frac,
        "taper_ratio": d.taper_ratio,
        "taper_start_frac": d.taper_start_frac,
        "washout_tip_deg": d.washout_tip_deg,
        "washout_start_frac": d.washout_start_frac,
        "y_washout_m": d.y_washout_m,
        "tip_chord_m": d.tip_chord_m,
        "y_taper_m": d.y_taper_m,
        "boom_spacing_m": d.boom_spacing,
        "boom_spacing_set_m": d.boom_spacing_set_m or 0.0,
        "hstab_chord_m": d.hstab_chord,
        "tail_volume_h": d.tail_volume_h(),
        "tail_volume_v": d.tail_volume_v_actual(),
        "aileron_y_inner_m": d.aileron_y_inner(),
        "aileron_span_each_m": d.aileron_span_each_m(),
        "roll_rate_deg_s": p_a + p_e,
        "roll_aileron_deg_s": p_a,
        "roll_elevon_deg_s": p_e,
        "cn_beta": d.cn_beta(),
        "cn_r": d.cn_r(),
        "cn_r_control": d.cn_r_control(),
        "izz_kgm2": d.yaw_inertia_kgm2(),
        "yaw_rate_deg_s": yaw_rate,
        "yaw_rate_max_deg_s": yaw_max,
        "yaw_rate_level_deg_s": yaw_level,
        "yaw_correct_s": yaw_t,
        "incidence_wing_deg": d.wing_incidence_deg(),
        "incidence_hstab_deg": d.hstab_incidence_deg(),
        "n_packs": d.n_packs,
        "cells_per_string": "one_per_bay" if one_string_per_bay else d.cells_per_string,
        "one_string_per_bay": one_string_per_bay,
        "string_plan": d.string_plan_label(),
        "n_strings": d.n_mppts,
        "n_cells": d.n_cells,
        "inboard_cells": bays["wing_inboard"].capacity,
        "outboard_cells": bays["wing_outboard_L"].capacity,
        "hstab_cells": bays["hstab"].capacity,
        "motor": motor_key,
        "prop": pname,
        "mass_kg": d.mass_kg,
        "wing_area_m2": d.wing_area,
        "aspect_ratio": d.aspect_ratio,
        "static_margin": d.static_margin(),
        "v_stall": d.stall_speed(),
        "v_night": mres.v_night,
        "v_day": mres.v_day,
        "p_night_w": mres.p_night_w,
        "p_day_w": mres.p_day_w,
        "climb_ms": mres.climb_ms,
        "soc_min": mres.soc_min,
        "soc_end": mres.soc_end,
        "soc_start": mres.soc_start,
        "cycle_wh": mres.cycle_wh,
        "margin_wh": mres.margin_wh,
        "unmet_wh": mres.unmet_wh,
        "spilled_wh": mres.spilled_wh,
        "solar_wh": mres.solar_wh,
        "propulsion_wh": mres.propulsion_wh,
        "battery_night_h": mres.battery_night_h,
        "closed": mres.closed,
        "reason": mres.reason,
        "boom_length_m": d.boom_length,
        "aft_boom_length_m": d.aft_boom_length,
        "fuselage_length_m": d.fuselage_length_m,
        "packing_ok": d.packing_geometry_ok(),
    }


def evaluate_design(d: Design, env: pd.DataFrame, prop_names: list[str],
                    prop_cache: dict, drive, systems: dict | None = None
                    ) -> dict | None:
    """Hard constraints → best prop → two-day energy march. None if discarded."""
    why = _hard_constraints(d)
    if why:
        return None
    picked = _best_prop(d, prop_names, prop_cache, motor=drive, systems=systems)
    if picked is None:
        return None
    pname, psys, _pnight = picked
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    d.prop_name = pname
    if d.mass_kg > config.MTOW_MAX_KG:
        return None
    v_n = d.min_power_speed()
    t_one = psys.max_thrust_n(v_n, rho=RHO_NIGHT) / config.N_MOTORS
    if not d.differential_thrust_yaw_ok(t_one, v_n):
        return None
    mres = simulate(d, env, psys)
    return _candidate_record(d, mres, d.motor_name, pname, d.one_string_per_bay,
                             t_one=t_one, v_n=v_n)


def search_continuous(env: pd.DataFrame | None = None,
                      verbose: bool = True,
                      one_string_per_bay: bool = True,
                      motor_name: str | None = None,
                      prop_names: list[str] | None = None,
                      maxiter: int = 18,
                      popsize: int = 6,
                      seed: int = 7,
                      start: dict | None = None) -> pd.DataFrame:
    """Differential evolution over continuous aero variables.

    Discrete: 2 or 3 packs (cap 3), default 12L motor, MPPT-legal
    one-string-per-bay cells, inner-loop propeller. Returns every
    *feasible-enough* evaluation (including energy misses), ranked like
    `search()`. One DE per pack count; pack count is not a DE coordinate.
    """
    from scipy.optimize import differential_evolution

    if env is None:
        env = environment.design_day(config.SOLSTICE_DATE)
    motor_key = motor_name or config.MOTOR_DEFAULT
    drive = drive_for(motor_key)
    prop_names = (list(prop_names) if prop_names is not None
                  else _prop_candidates())
    prop_cache = {n: load_prop(n) for n in prop_names}
    systems = {n: PropulsionSystem(prop=prop_cache[n], motor=drive)
               for n in prop_names}
    pack_counts = tuple(int(n) for n in config.PACK_GRID)
    if any(n < 1 or n > 3 for n in pack_counts):
        raise ValueError(f"PACK_GRID {pack_counts} exceeds the 3-pack cap")
    bounds = _continuous_bounds()
    x0 = x_from_start(start)
    rows: list[dict] = []
    n_eval = 0
    n_skip = 0
    best_holder: list = [None]

    if verbose:
        print("  Continuous aero search (differential evolution)", flush=True)
        print(f"  Motor: {drive.spec.name}  ({motor_key})", flush=True)
        print(f"  Packs: {pack_counts} (cap 3)   strings: one MPPT-legal per bay",
              flush=True)
        s0 = dict(zip(CONTINUOUS_KEYS, x0))
        print(f"  Start: span {s0['span_m']:.2f} m  "
              f"chord {s0['chord_m']*1000:.0f} mm  "
              f"H-arm {s0['tail_arm_m']:.2f} m  "
              f"V-arm {s0['vstab_arm_m']:.2f} m  "
              f"boom {s0['boom_spacing_m']:.2f} m", flush=True)
        print(f"  Prop shortlist ({len(prop_names)}): {prop_names}", flush=True)
        print(f"  DE maxiter={maxiter}  popsize={popsize}  seed={seed}",
              flush=True)

    rng = np.random.default_rng(seed)
    n_dim = len(bounds)
    n_pop = max(popsize * n_dim, n_dim + 1)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])

    for n_packs in pack_counts:
        seen: set[tuple] = set()
        if verbose:
            print(f"  --- {n_packs} pack(s) ---", flush=True)

        def objective(x, n_packs=n_packs, seen=seen):
            nonlocal n_eval, n_skip
            x = np.asarray(x, dtype=float)
            k = (n_packs, *np.round(x, 5))
            d = design_from_x(x, n_packs=n_packs, motor_name=motor_key,
                              one_string_per_bay=one_string_per_bay)
            row = evaluate_design(d, env, prop_names, prop_cache, drive, systems)
            if row is None:
                n_skip += 1
                return 1.0e6
            if k not in seen:
                seen.add(k)
                rows.append(row)
                n_eval += 1
                _maybe_write_winner_step(d, row, best_holder, verbose)
                if verbose and n_eval % 10 == 0:
                    best = max(r["margin_wh"] for r in rows)
                    print(f"  evaluated {n_eval} (skipped {n_skip})  "
                          f"best {best:.1f} Wh ...", flush=True)
            return float(-row["margin_wh"])

        init = rng.random((n_pop, n_dim)) * (hi - lo) + lo
        init[0] = np.clip(x0, lo, hi)
        differential_evolution(
            objective, bounds=bounds, init=init, maxiter=maxiter,
            popsize=popsize, seed=seed + n_packs, polish=False, atol=0.5,
            tol=0.01, updating="immediate", workers=1, disp=False)

    if verbose:
        print(f"  Done: {n_eval} evaluated, {n_skip} skipped by constraints",
              flush=True)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["closed", "margin_wh"], ascending=[False, False])
    df = df.reset_index(drop=True)
    w = winner(df)
    if w is not None:
        write_winner_step(design_from_row(w))
    return df

