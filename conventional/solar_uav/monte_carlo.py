"""Phase 5 — uncertainty quantification.

Latin-hypercube / Sobol sampling over the FLAGGED model knobs, then a 24 h
energy march per draw. Reports P(closure), margin percentiles, and a
one-at-a-time tornado so the next test (Phase 6) is aimed at the drivers.

The sample *means* are the current model (including the APC thrust derate
and power inflate). This replaces stacked extra fudge factors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import qmc

from . import config, environment, mission
from .aircraft import Design, reference_design
from .components.propulsion import PropulsionSystem, load_prop
from .mission import MissionScales


# (name, config tuple (mean, sigma, lo, hi), MissionScales field)
PARAMS: tuple[tuple[str, tuple, str], ...] = (
    ("irradiance", config.MC_IRRADIANCE, "irradiance"),
    ("t_cell_k", config.MC_T_CELL_K, "t_cell_k_scale"),
    ("t_cell_offset_c", config.MC_T_CELL_OFFSET_C, "t_cell_offset_c"),
    ("array_eff", config.MC_ARRAY_EFF, "array_eff"),
    ("mass", config.MC_MASS, "mass"),
    ("drag", config.MC_DRAG, "drag"),
    ("prop_thrust", config.MC_PROP_THRUST, "prop_thrust"),
    ("prop_power", config.MC_PROP_POWER, "prop_power"),
    ("avionics_w", config.MC_AVIONICS_W, "avionics_w"),
    ("pack_energy", config.MC_PACK_ENERGY, "pack_energy"),
)


def _truncnorm(mean: float, sigma: float, lo: float, hi: float):
    a, b = (lo - mean) / sigma, (hi - mean) / sigma
    return stats.truncnorm(a, b, loc=mean, scale=sigma)


def _scales_from_row(row: dict) -> MissionScales:
    return MissionScales(
        irradiance=row["irradiance"],
        array_eff=row["array_eff"],
        t_cell_k_scale=row["t_cell_k"],
        t_cell_offset_c=row["t_cell_offset_c"],
        mass=row["mass"],
        drag=row["drag"],
        avionics_w=row["avionics_w"],
        pack_energy=row["pack_energy"],
        prop_thrust=row["prop_thrust"],
        prop_power=row["prop_power"],
    )


def sample_table(n: int = config.MC_N_SAMPLES,
                 seed: int = config.MC_SEED) -> pd.DataFrame:
    """Sobol samples mapped through each parameter's truncated normal."""
    dim = len(PARAMS)
    m = int(np.ceil(np.log2(max(n, 2))))
    engine = qmc.Sobol(d=dim, scramble=True, seed=seed)
    u = engine.random_base2(m)[:n]
    data = {}
    for j, (name, spec, _field) in enumerate(PARAMS):
        mean, sigma, lo, hi = spec
        data[name] = _truncnorm(mean, sigma, lo, hi).ppf(np.clip(u[:, j], 1e-9, 1 - 1e-9))
    return pd.DataFrame(data)


def run_sample(design: Design, env: pd.DataFrame, prop_sys: PropulsionSystem,
               row: dict, dt_min: int = 10) -> dict:
    sc = _scales_from_row(row)
    res = mission.simulate(design, env, prop_sys, dt_min=dt_min, scales=sc)
    overweight = res.mass_kg > config.MTOW_MAX_KG + 1e-9
    closed_legal = bool(res.closed) and not overweight
    out = dict(row)
    out.update({
        "closed": bool(res.closed),
        "closed_legal": closed_legal,
        "overweight": overweight,
        "margin_wh": res.margin_wh,
        "soc_min": res.soc_min,
        "soc_end": res.soc_end,
        "unmet_wh": res.unmet_wh,
        "p_night_w": res.p_night_w,
        "p_day_w": res.p_day_w,
        "climb_ms": res.climb_ms,
        "mass_kg": res.mass_kg,
        "reason": res.reason,
    })
    return out


def run(design: Design | None = None,
        prop_name: str | None = None,
        n: int = config.MC_N_SAMPLES,
        seed: int = config.MC_SEED,
        dt_min: int = 10,
        env: pd.DataFrame | None = None,
        verbose: bool = True) -> pd.DataFrame:
    design = design or reference_design()
    prop_name = prop_name or config.REF_PROP
    if env is None:
        env = environment.design_day(config.SOLSTICE_DATE)
    prop_sys = PropulsionSystem(prop=load_prop(prop_name))
    design.prop_diameter_in = prop_sys.prop.diameter_in or design.prop_diameter_in
    table = sample_table(n, seed)
    rows = []
    for i, rec in enumerate(table.to_dict(orient="records")):
        rows.append(run_sample(design, env, prop_sys, rec, dt_min=dt_min))
        if verbose and (i + 1) % 32 == 0:
            print(f"  Phase 5: {i + 1}/{n} samples")
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    m = df["margin_wh"].replace([-1e9], np.nan)
    finite = m.dropna()
    p = np.nanpercentile(finite, [10, 50, 90]) if len(finite) else [np.nan] * 3
    return {
        "n": int(len(df)),
        "p_closed": float(df["closed"].mean()),
        "p_closed_legal": float(df["closed_legal"].mean()),
        "p_overweight": float(df["overweight"].mean()),
        "p_soc_floor": float((df["soc_min"] >= config.SOC_MIN).mean()),
        "margin_p10_wh": float(p[0]),
        "margin_p50_wh": float(p[1]),
        "margin_p90_wh": float(p[2]),
        "soc_min_p10": float(np.nanpercentile(df["soc_min"], 10)),
        "soc_min_p50": float(np.nanpercentile(df["soc_min"], 50)),
        "mean_p_night_w": float(np.nanmean(df["p_night_w"])),
        "mean_mass_kg": float(np.nanmean(df["mass_kg"])),
    }


def tornado(design: Design, env: pd.DataFrame, prop_sys: PropulsionSystem,
            dt_min: int = 10) -> tuple[pd.DataFrame, mission.MissionResult]:
    """One-at-a-time ±1σ on each knob; delta margin vs the nominal mean point."""
    nominal = {name: spec[0] for name, spec, _ in PARAMS}
    base = mission.simulate(design, env, prop_sys, dt_min=dt_min,
                            scales=_scales_from_row(nominal))
    rows = []
    for name, spec, _field in PARAMS:
        mean, sigma, lo, hi = spec
        for side, val in (("lo", max(lo, mean - sigma)),
                          ("hi", min(hi, mean + sigma))):
            row = dict(nominal)
            row[name] = val
            res = mission.simulate(design, env, prop_sys, dt_min=dt_min,
                                   scales=_scales_from_row(row))
            rows.append({
                "param": name,
                "side": side,
                "value": val,
                "margin_wh": res.margin_wh,
                "delta_wh": res.margin_wh - base.margin_wh,
                "soc_min": res.soc_min,
                "closed": res.closed,
            })
    return pd.DataFrame(rows), base


def spearman_drivers(df: pd.DataFrame) -> pd.DataFrame:
    """Rank correlation of each input with energy margin."""
    y = df["margin_wh"].to_numpy()
    rows = []
    for name, _spec, _field in PARAMS:
        x = df[name].to_numpy()
        mask = np.isfinite(x) & np.isfinite(y) & (y > -1e8)
        if mask.sum() < 8:
            rho, p = np.nan, np.nan
        else:
            rho, p = stats.spearmanr(x[mask], y[mask])
        rows.append({"param": name, "spearman_rho": float(rho), "p_value": float(p)})
    out = pd.DataFrame(rows)
    out["abs_rho"] = out["spearman_rho"].abs()
    return out.sort_values("abs_rho", ascending=False).drop(columns=["abs_rho"])
