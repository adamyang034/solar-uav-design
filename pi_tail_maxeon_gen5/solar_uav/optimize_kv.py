"""Kv × APC-prop matcher.

Propellers stay discrete (buyable APC electrics). Motor Kv is free on a
fixed A40-12L stator (rewind model). Objective: minimum 6S bus power at
the airframe's night min-power speed, subject to the 1.5 m/s climb rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .aircraft import RHO_DAY, RHO_NIGHT, Design
from .components.motor import MotorDrive, motor_from_kv
from .components.propulsion import PropulsionSystem, load_prop, shortlist_props


def cruise_condition(design: Design) -> tuple[float, float]:
    v = design.min_power_speed()
    drag = float(np.asarray(design.drag_n(v)).reshape(-1)[0])
    return v, drag


def evaluate_combo(prop_name: str, kv: float, design: Design,
                   v: float, drag: float) -> dict | None:
    prop = load_prop(prop_name)
    drive = motor_from_kv(kv)
    sys = PropulsionSystem(prop=prop, motor=drive)
    fl = sys.level_flight(v, drag, rho=RHO_NIGHT)
    if fl is None:
        return None
    t_max = sys.max_thrust_n(v, rho=RHO_DAY)
    roc = design.climb_rate_ideal_ms(v, t_max, rho=RHO_DAY)
    idle_w = 2.0 * fl["voltage_v"] * drive.spec.i0_a
    return {
        "prop": prop_name,
        "diameter_in": prop.diameter_in,
        "pitch_in": prop.pitch_in,
        "kv": kv,
        "r_ohm": drive.spec.r_ohm,
        "i0_a": drive.spec.i0_a,
        "prop_rpm": fl["rpm"],
        "motor_rpm": fl["rpm"],
        "voltage_v": fl["voltage_v"],
        "p_bus_w": fl["p_bus_w"],
        "p_shaft_w": fl["p_shaft_w"],
        "idle_w": idle_w,
        "efficiency": fl["efficiency"],
        "climb_ms": roc,
        "climb_ok": roc >= config.CLIMB_RATE_REQ_MS,
        "duty": fl["voltage_v"] / config.BUS_V_NOM,
    }


def search(design: Design,
           kv_grid: tuple[int, ...] = config.KV_GRID,
           verbose: bool = True) -> pd.DataFrame:
    """Exhaustive APC-electric × Kv grid at this airframe's cruise point."""
    v, drag = cruise_condition(design)
    props = shortlist_props()["name"].tolist()
    if verbose:
        print(f"  Cruise: {v:.2f} m/s, {drag:.2f} N, aero {drag*v:.1f} W")
        print(f"  {len(props)} APC props × {len(kv_grid)} Kv values")

    rows = []
    for name in props:
        prop = load_prop(name)
        # Prop operating point is motor-independent; skip props that
        # cannot make the thrust at all.
        if prop.operating_point(drag / config.N_MOTORS, v, rho=RHO_NIGHT) is None:
            continue
        for kv in kv_grid:
            rec = evaluate_combo(name, float(kv), design, v, drag)
            if rec is None:
                continue
            rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values("p_bus_w").reset_index(drop=True)


def winner(df: pd.DataFrame) -> pd.Series | None:
    """Climb-legal, minimum night bus. Duty is reported, not a cutoff."""
    if df.empty:
        return None
    ok = df[df["climb_ok"]]
    if ok.empty:
        ok = df
    return ok.sort_values("p_bus_w").iloc[0]


def catalog_references(design: Design) -> pd.DataFrame:
    """The two real Hacker units, for plotting against the free-Kv surface."""
    v, drag = cruise_condition(design)
    rows = []
    for key, spec in config.MOTOR_CATALOG.items():
        drive = MotorDrive(spec=spec)
        for pname in shortlist_props()["name"].tolist():
            sys = PropulsionSystem(prop=load_prop(pname), motor=drive)
            fl = sys.level_flight(v, drag, rho=RHO_NIGHT)
            if fl is None:
                continue
            roc = design.climb_rate_ideal_ms(v, sys.max_thrust_n(v, rho=RHO_DAY), rho=RHO_DAY)
            rows.append({
                "catalog": spec.name,
                "prop": pname,
                "kv_effective": drive.kv_effective,
                "p_bus_w": fl["p_bus_w"],
                "climb_ms": roc,
                "climb_ok": roc >= config.CLIMB_RATE_REQ_MS,
                "voltage_v": fl["voltage_v"],
            })
    return pd.DataFrame(rows)
