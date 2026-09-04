"""Phase 4 — energy-closure time march (settled 24 h loop).

Walks a design through a design-day irradiance profile at night-loiter /
day-cruise speeds, charging the battery only up to the 6 A/pack limit.

Launch day starts full (ground charge) at the last afternoon surplus.
Day 2 starts wherever day 1 ended — no reset. Closed means the repeating
day stays above the 20% SOC floor and does not get poorer (start ≤ end).
Margin is watt-hours above 20% at the worst point of day 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .aircraft import Design, RHO_DAY, RHO_NIGHT
from .components.battery import BatteryBank
from .components.propulsion import PropulsionSystem
from .components.solar_array import SolarArray

# Numerical slack on day-2 end ≥ start. Not a 98% refill gate.
CYCLE_SLACK_WH = 0.5


@dataclass
class MissionScales:
    """Multipliers / offsets applied to a single mission march (Phase 5).

    1.0 / 0.0 leaves the Phase 4 model unchanged. Propulsion scales are
    *absolute* APC factors (mean = the FLAGGED derate/inflate), not extra
    stacked conservatism.
    """
    irradiance: float = 1.0
    array_eff: float = 1.0
    t_cell_k_scale: float = 1.0
    t_cell_offset_c: float = 0.0
    mass: float = 1.0
    drag: float = 1.0
    avionics_w: float | None = None
    pack_energy: float = 1.0
    prop_thrust: float | None = None
    prop_power: float | None = None


@dataclass
class MissionResult:
    closed: bool
    soc_min: float
    soc_end: float
    margin_wh: float          # energy above the 20% floor at the worst point
    unmet_wh: float           # energy the battery could not supply
    spilled_wh: float         # solar that could not be accepted
    solar_wh: float
    propulsion_wh: float
    avionics_wh: float
    v_night: float
    v_day: float
    p_night_w: float
    p_day_w: float
    climb_ms: float
    battery_night_h: float    # hours with array < propulsion+avionics
    start_hour: float
    soc_trace: np.ndarray
    hours: np.ndarray
    p_solar: np.ndarray
    p_load: np.ndarray
    reason: str
    mass_kg: float = 0.0
    prop_notes: tuple[str, ...] = ()
    soc_start: float = float("nan")   # day-2 start (repeating-loop phase)
    cycle_wh: float = float("nan")    # (soc_end - soc_start) * E on day 2


@dataclass
class DisplayTrace:
    """Viewer-only march. Does not change scored closure."""
    hours: np.ndarray          # hours from start_hod
    soc_trace: np.ndarray
    p_solar: np.ndarray
    p_load: np.ndarray
    start_hod: float
    duration_h: float


def _wrap_hours(hours: np.ndarray, start_idx: int) -> np.ndarray:
    """Hour-of-day axis starting at start_idx, increasing through 24 h."""
    h0 = hours[start_idx]
    n = hours.size
    out = np.empty(n)
    for i in range(n):
        out[i] = (hours[(start_idx + i) % n] - h0) % 24.0
        if i and out[i] < out[i - 1]:
            out[i] += 24.0
    return out


def _bus_powers(design: Design, env: pd.DataFrame, prop_sys: PropulsionSystem,
                dt_min: int, sc: MissionScales) -> dict | None:
    """Repeating-day solar / load / net at `dt_min`. None if props can't thrust."""
    step = max(1, dt_min)
    prof = env.iloc[::step]
    hours = (prof.index.hour + prof.index.minute / 60.0).to_numpy()
    poa0 = prof["poa_eff"].to_numpy(dtype=float)
    t_cell0 = prof["t_cell_c"].to_numpy(dtype=float)
    if "t_amb_c" in prof.columns:
        t_amb = prof["t_amb_c"].to_numpy(dtype=float)
    else:
        t_amb = np.full_like(t_cell0, 0.5 * (config.T_AMB_MIN_C + config.T_AMB_MAX_C))
    poa = poa0 * sc.irradiance
    t_cell = (t_amb + sc.t_cell_offset_c
              + sc.t_cell_k_scale * (t_cell0 - t_amb) * sc.irradiance)
    n = len(prof)
    dt_s = step * 60.0
    dt_h = dt_s / 3600.0

    array = SolarArray(string_lengths=design.string_lengths())
    p_solar = array.power_to_bus_w(poa, t_cell) * sc.array_eff

    mass = design.mass_kg * sc.mass
    av_w = config.AVIONICS_POWER_W if sc.avionics_w is None else float(sc.avionics_w)
    drive = prop_sys.with_scales(sc.prop_thrust, sc.prop_power)

    v_night = design.min_power_speed(rho=RHO_NIGHT, mass_kg=mass)
    v_day = design.min_power_speed(rho=RHO_DAY, mass_kg=mass)
    d_night = float(np.asarray(
        design.drag_n(v_night, mass_kg=mass, rho=RHO_NIGHT)).reshape(-1)[0]) * sc.drag
    d_day = float(np.asarray(
        design.drag_n(v_day, mass_kg=mass, rho=RHO_DAY)).reshape(-1)[0]) * sc.drag

    fl_n = drive.level_flight(v_night, d_night, rho=RHO_NIGHT)
    fl_d = drive.level_flight(v_day, d_day, rho=RHO_DAY)
    if fl_n is None or fl_d is None:
        return None

    p_night = fl_n["p_bus_w"] + av_w
    p_day = fl_d["p_bus_w"] + av_w
    t_max = drive.max_thrust_n(v_day, rho=RHO_DAY)
    climb = design.climb_rate_ideal_ms(v_day, t_max, mass_kg=mass, rho=RHO_DAY)
    is_night = p_solar < p_night
    p_load = np.where(is_night, p_night, p_day)
    p_net = p_solar - p_load
    return {
        "hours": hours, "n": n, "dt_s": dt_s, "dt_h": dt_h, "av_w": av_w,
        "mass": mass, "v_night": v_night, "v_day": v_day,
        "p_solar": p_solar, "p_load": p_load, "p_net": p_net,
        "p_night": p_night, "p_day": p_day, "climb": climb,
        "is_night": is_night, "fl_n": fl_n, "fl_d": fl_d,
    }


def _march_day(bank: BatteryBank, order: np.ndarray,
               p_solar: np.ndarray, p_load: np.ndarray, p_net: np.ndarray,
               dt_s: float, dt_h: float, av_w: float
               ) -> tuple[np.ndarray, float, float, float, float]:
    """One 24 h wrap. Returns SOC trace, spilled Wh, unmet Wh, solar Wh, prop Wh."""
    n = int(order.size)
    soc = np.empty(n)
    spilled = 0.0
    unmet = 0.0
    solar_wh = 0.0
    prop_wh = 0.0
    for k, i in enumerate(order):
        solar_wh += float(p_solar[i]) * dt_h
        prop_wh += float(p_load[i] - av_w) * dt_h
        r = bank.step(float(p_net[i]), dt_s)
        spilled += r["p_spilled_w"] * dt_h
        unmet += r["deficit_w"] * dt_h
        soc[k] = bank.soc
    return soc, spilled, unmet, solar_wh, prop_wh


def simulate(design: Design,
             env: pd.DataFrame,
             prop_sys: PropulsionSystem,
             dt_min: int = 5,
             scales: MissionScales | None = None) -> MissionResult:
    """Launch-full day 1, then a repeating day 2. `env` is a 1-minute
    (or coarser) profile from `environment.design_day`."""
    sc = scales or MissionScales()
    bp = _bus_powers(design, env, prop_sys, dt_min, sc)
    if bp is None:
        mass = design.mass_kg * sc.mass
        v_night = design.min_power_speed(rho=RHO_NIGHT, mass_kg=mass)
        v_day = design.min_power_speed(rho=RHO_DAY, mass_kg=mass)
        return MissionResult(
            False, np.nan, np.nan, -1e9, np.nan, 0.0, 0.0, 0.0, 0.0,
            v_night, v_day, np.nan, np.nan, np.nan, np.nan, np.nan,
            np.array([]), np.array([]), np.array([]), np.array([]),
            "propulsion cannot make required thrust on 6S", mass)
    hours = bp["hours"]
    n = bp["n"]
    dt_s = bp["dt_s"]
    dt_h = bp["dt_h"]
    av_w = bp["av_w"]
    mass = bp["mass"]
    v_night = bp["v_night"]
    v_day = bp["v_day"]
    p_solar = bp["p_solar"]
    p_load = bp["p_load"]
    p_net = bp["p_net"]
    p_night = bp["p_night"]
    p_day = bp["p_day"]
    climb = bp["climb"]
    is_night = bp["is_night"]
    fl_n = bp["fl_n"]
    fl_d = bp["fl_d"]

    # Last afternoon surplus so the night is fully counted. Day 1 starts
    # full (ground charge). Day 2 starts wherever day 1 ended.
    surplus = p_net > 1.0
    start_idx = 0
    if surplus.any():
        idxs = np.where(surplus)[0]
        afternoon = idxs[hours[idxs] >= 12.0]
        start_idx = int(afternoon[-1] if len(afternoon) else idxs[-1])

    bank = BatteryBank(n_packs=design.n_packs, soc=1.0,
                       energy_scale=sc.pack_energy)
    order = np.arange(start_idx, start_idx + n) % n
    _march_day(bank, order, p_solar, p_load, p_net, dt_s, dt_h, av_w)

    soc_start = float(bank.soc)
    soc, spilled, unmet, solar_wh, prop_wh = _march_day(
        bank, order, p_solar, p_load, p_net, dt_s, dt_h, av_w)

    soc_min = float(soc.min())
    soc_end = float(soc[-1])
    e_tot = bank.energy_total_wh
    reserve_wh = (soc_min - config.SOC_MIN) * e_tot
    cycle_wh = (soc_end - soc_start) * e_tot
    margin_wh = float(reserve_wh)
    if unmet > 0.5:
        margin_wh = min(margin_wh, -unmet)
    periodic_ok = cycle_wh >= -CYCLE_SLACK_WH
    closed = (soc_min >= config.SOC_MIN - 1e-6
              and unmet < 0.5
              and climb >= config.CLIMB_RATE_REQ_MS
              and periodic_ok)

    reasons = []
    if soc_min < config.SOC_MIN or unmet >= 0.5:
        reasons.append(f"SOC floor violated (min {soc_min:.3f}, unmet {unmet:.0f} Wh)")
    if climb < config.CLIMB_RATE_REQ_MS:
        reasons.append(f"climb {climb:.2f} m/s < {config.CLIMB_RATE_REQ_MS}")
    if not periodic_ok:
        reasons.append(
            f"ratchet (day-2 {soc_start:.3f} -> {soc_end:.3f}, {cycle_wh:.0f} Wh)")
    reason = "ok" if closed else "; ".join(reasons) or "infeasible"
    notes = tuple(n for n in (fl_n.get("notes"), fl_d.get("notes")) if n)
    if notes:
        reason = (reason + "; " if reason != "ok" else "") + "; ".join(notes)

    hours_wrapped = _wrap_hours(hours, start_idx)
    night_h = float(is_night.mean() * 24.0)
    av_wh = av_w * 24.0

    return MissionResult(
        closed=closed,
        soc_min=soc_min,
        soc_end=soc_end,
        margin_wh=margin_wh,
        unmet_wh=unmet,
        spilled_wh=spilled,
        solar_wh=solar_wh,
        propulsion_wh=prop_wh,
        avionics_wh=av_wh,
        v_night=v_night,
        v_day=v_day,
        p_night_w=p_night,
        p_day_w=p_day,
        climb_ms=climb,
        battery_night_h=night_h,
        start_hour=float(hours[start_idx]),
        soc_trace=soc,
        hours=hours_wrapped,
        p_solar=p_solar[order],
        p_load=p_load[order],
        reason=reason,
        mass_kg=mass,
        prop_notes=notes,
        soc_start=soc_start,
        cycle_wh=float(cycle_wh),
    )


def display_trace(design: Design,
                  env: pd.DataFrame,
                  prop_sys: PropulsionSystem,
                  *,
                  start_hod: float = 8.0,
                  duration_h: float = 60.0,
                  dt_min: int = 5,
                  scales: MissionScales | None = None) -> DisplayTrace | None:
    """SOC=1 at `start_hod`, then `duration_h` of the repeating design day.

    Viewer plots only. Scoring still uses `simulate` (afternoon-full day 1,
    then the day-2 loop).
    """
    sc = scales or MissionScales()
    bp = _bus_powers(design, env, prop_sys, dt_min, sc)
    if bp is None:
        return None
    hours = bp["hours"]
    n = int(bp["n"])
    dt_s = float(bp["dt_s"])
    dt_h = float(bp["dt_h"])
    p_solar = bp["p_solar"]
    p_load = bp["p_load"]
    p_net = bp["p_net"]
    wrap = (hours - float(start_hod) + 12.0) % 24.0 - 12.0
    start_idx = int(np.argmin(np.abs(wrap)))
    n_steps = max(1, int(round(float(duration_h) / dt_h)))
    bank = BatteryBank(n_packs=design.n_packs, soc=1.0,
                       energy_scale=sc.pack_energy)
    t = np.linspace(0.0, n_steps * dt_h, n_steps + 1)
    soc = np.empty(n_steps + 1)
    ps = np.empty(n_steps + 1)
    pl = np.empty(n_steps + 1)
    soc[0] = 1.0
    i0 = start_idx % n
    ps[0] = float(p_solar[i0])
    pl[0] = float(p_load[i0])
    for k in range(n_steps):
        i = (start_idx + k) % n
        bank.step(float(p_net[i]), dt_s)
        soc[k + 1] = bank.soc
        j = (start_idx + k + 1) % n
        ps[k + 1] = float(p_solar[j])
        pl[k + 1] = float(p_load[j])
    return DisplayTrace(
        hours=t, soc_trace=soc, p_solar=ps, p_load=pl,
        start_hod=float(hours[i0]), duration_h=float(t[-1]),
    )
