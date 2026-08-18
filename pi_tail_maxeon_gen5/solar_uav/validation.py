"""Phase 6 — validation protocols and measured-data ingest.

Physical tests the models are waiting on:

  1. Encapsulated Maxeon Gen 5 panel vs Phase 1–2 prediction (flash or outdoor).
  2. GOLD V1 pack capacity + 6 A charge-acceptance bench.
  3. Thrust-stand of the chosen motor + prop vs APC + motor model.
  4. Glide-polar flight test vs the Phase 3 drag polar.

Drop CSVs into ``data/validation/measured/`` matching the templates in
``data/validation/templates/``. This module compares them to the model,
recommends updates to the FLAGGED factors, and writes
``outputs/phase6_factor_recommendations.json``.

Until real files exist, ``run_self_test()`` generates synthetic lab traces
from the model plus noise and checks that the fitter recovers the planted
scale — that is the unit test for the Phase 6 pipeline, not a substitute
for the bench.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .aircraft import TRIM_DRAG_FACTOR, Design, RHO_NIGHT, reference_design
from .components.battery import BatteryBank
from .components.propulsion import load_prop
from .components.solar_array import SolarArray

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "data" / "validation" / "templates"
MEASURED_DIR = ROOT / "data" / "validation" / "measured"
OUT_DEFAULT = ROOT / "outputs" / "phase6_factor_recommendations.json"


@dataclass
class Comparison:
    protocol: str
    n_points: int
    model_mean: float
    meas_mean: float
    scale_meas_over_model: float
    residual_rms: float
    recommended_factor: str
    recommended_value: float
    current_value: float
    notes: str
    awaiting_data: bool = False


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, comment="#")
    df.columns = [c.strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# 1. Encapsulated panel
# ---------------------------------------------------------------------------
def compare_panel(path: Path | None = None,
                  n_cells: int = 12) -> Comparison:
    """Measured DC watts vs SolarArray.power_dc_w at the recorded G and T."""
    path = path or (MEASURED_DIR / "panel_iv.csv")
    df = _read_csv(path)
    factor = "ENCAPSULATION_TRANSMISSION * WIRING_MISMATCH_SOILING_EFF"
    current = config.ENCAPSULATION_TRANSMISSION * config.WIRING_MISMATCH_SOILING_EFF
    if df is None or df.empty:
        return Comparison(
            "panel", 0, np.nan, np.nan, np.nan, np.nan, factor, current, current,
            f"No file at {path}. Template: {TEMPLATE_DIR / 'panel_iv.csv'}",
            True)
    arr = SolarArray(n_strings=1, cells_per_string=n_cells)
    # power_dc_w already includes wiring/mismatch; poa_eff should already
    # include encapsulation if the pyranometer is plane-of-array raw GHI.
    # Treat measured G as raw POA and apply encapsulation in the model via
    # the environment convention: pass G * ENCAPSULATION as poa_eff.
    poa_eff = df["g_poa_w_m2"].to_numpy() * config.ENCAPSULATION_TRANSMISSION
    t = df["t_cell_c"].to_numpy()
    model = arr.power_dc_w(poa_eff, t)
    meas = df["p_dc_w"].to_numpy()
    ratio = meas / np.clip(model, 1e-6, None)
    scale = float(np.median(ratio))
    rms = float(np.sqrt(np.mean((meas - model * scale) ** 2)))
    # Fold the residual into encapsulation (keep wiring at 0.965).
    new_encap = float(np.clip(
        config.ENCAPSULATION_TRANSMISSION * scale, 0.85, 1.0))
    return Comparison(
        "panel", len(df), float(np.mean(model)), float(np.mean(meas)),
        scale, rms, "ENCAPSULATION_TRANSMISSION", new_encap,
        config.ENCAPSULATION_TRANSMISSION,
        "Median meas/model folded into encapsulation transmission.",
        False)


# ---------------------------------------------------------------------------
# 2. Battery capacity / charge acceptance
# ---------------------------------------------------------------------------
def compare_battery(path: Path | None = None) -> Comparison:
    path = path or (MEASURED_DIR / "battery_capacity.csv")
    df = _read_csv(path)
    if df is None or df.empty:
        return Comparison(
            "battery", 0, config.PACK_ENERGY_WH, np.nan, np.nan, np.nan,
            "PACK_ENERGY_WH", config.PACK_ENERGY_WH, config.PACK_ENERGY_WH,
            f"No file at {path}. Template: {TEMPLATE_DIR / 'battery_capacity.csv'}",
            True)
    # Constant-current discharge Wh to the 20% floor (or the listed cutoff).
    meas_wh = float(df["energy_wh"].iloc[-1]) if "energy_wh" in df.columns else (
        float(np.trapezoid(df["voltage_v"] * df["current_a"], df["t_s"] / 3600.0)))
    # Model: usable window of one pack, minus a crude I^2R estimate.
    bank = BatteryBank(n_packs=1, soc=1.0)
    i = float(np.mean(np.abs(df["current_a"]))) if "current_a" in df.columns else 6.0
    # Integrate model SOC from full to 0.20 at that current.
    dt = 30.0
    e_out = 0.0
    while bank.soc > config.SOC_MIN:
        p = bank.voltage_oc * i
        r = bank.step(-p, dt)
        e_out += r["p_discharge_w"] * dt / 3600.0
        if r["deficit_w"] > 0:
            break
    scale = meas_wh / max(e_out, 1e-6)
    new_e = config.PACK_ENERGY_WH * scale
    return Comparison(
        "battery", len(df), e_out, meas_wh, scale, abs(meas_wh - e_out),
        "PACK_ENERGY_WH", new_e, config.PACK_ENERGY_WH,
        "Measured discharge Wh to the SOC floor vs energy-based bank model.",
        False)


def compare_charge_limit(path: Path | None = None) -> Comparison:
    path = path or (MEASURED_DIR / "battery_charge.csv")
    df = _read_csv(path)
    if df is None or df.empty:
        return Comparison(
            "battery_charge", 0, config.PACK_CHARGE_MAX_A, np.nan, np.nan, np.nan,
            "PACK_CHARGE_MAX_A", config.PACK_CHARGE_MAX_A, config.PACK_CHARGE_MAX_A,
            f"No file at {path}. Template: {TEMPLATE_DIR / 'battery_charge.csv'}",
            True)
    i_cc = float(np.percentile(df["current_a"], 95))
    return Comparison(
        "battery_charge", len(df), config.PACK_CHARGE_MAX_A, i_cc,
        i_cc / config.PACK_CHARGE_MAX_A, abs(i_cc - config.PACK_CHARGE_MAX_A),
        "PACK_CHARGE_MAX_A", i_cc, config.PACK_CHARGE_MAX_A,
        "95th-percentile observed charge current vs datasheet 6 A/pack.",
        False)


# ---------------------------------------------------------------------------
# 3. Thrust stand
# ---------------------------------------------------------------------------
def compare_thrust_stand(path: Path | None = None,
                         prop_name: str | None = None) -> Comparison:
    path = path or (MEASURED_DIR / "thrust_stand.csv")
    prop_name = prop_name or config.REF_PROP
    df = _read_csv(path)
    if df is None or df.empty:
        return Comparison(
            "thrust_stand", 0, np.nan, np.nan, np.nan, np.nan,
            "PROP_THRUST_DERATE", config.PROP_THRUST_DERATE, config.PROP_THRUST_DERATE,
            f"No file at {path}. Template: {TEMPLATE_DIR / 'thrust_stand.csv'}",
            True)
    prop = load_prop(prop_name)
    t_model, t_meas = [], []
    p_model, p_meas = [], []
    for _, r in df.iterrows():
        tn = prop.thrust_n(float(r["v_ms"]), float(r["rpm"]), nominal=True)
        pn = prop.shaft_power_w(float(r["v_ms"]), float(r["rpm"]), nominal=True)
        if np.isfinite(tn):
            t_model.append(tn)
            t_meas.append(float(r["thrust_n"]))
        if np.isfinite(pn) and "shaft_power_w" in df.columns and np.isfinite(r["shaft_power_w"]):
            p_model.append(pn)
            p_meas.append(float(r["shaft_power_w"]))
    t_scale = float(np.median(np.array(t_meas) / np.clip(t_model, 1e-6, None)))
    rms = float(np.sqrt(np.mean((np.array(t_meas) - np.array(t_model) * t_scale) ** 2)))
    notes = f"Thrust scale {t_scale:.3f} vs APC nominal."
    if p_model:
        p_scale = float(np.median(np.array(p_meas) / np.clip(p_model, 1e-6, None)))
        notes += f" Power inflate {p_scale:.3f}."
    else:
        p_scale = config.PROP_POWER_INFLATE
    return Comparison(
        "thrust_stand", len(t_meas), float(np.mean(t_model)), float(np.mean(t_meas)),
        t_scale, rms, "PROP_THRUST_DERATE", t_scale, config.PROP_THRUST_DERATE,
        notes, False)


# ---------------------------------------------------------------------------
# 4. Glide polar
# ---------------------------------------------------------------------------
def compare_glide_polar(design: Design, path: Path | None = None) -> Comparison:
    path = path or (MEASURED_DIR / "glide_polar.csv")
    df = _read_csv(path)
    if df is None or df.empty:
        return Comparison(
            "glide_polar", 0, np.nan, np.nan, np.nan, np.nan,
            "TRIM_DRAG_FACTOR", TRIM_DRAG_FACTOR, TRIM_DRAG_FACTOR,
            f"No file at {path}. Template: {TEMPLATE_DIR / 'glide_polar.csv'}",
            True)
    v = df["v_ms"].to_numpy()
    d_meas = df["drag_n"].to_numpy() if "drag_n" in df.columns else (
        design.mass_kg * 9.80665 * (df["sink_ms"] / v))
    d_model = np.asarray(design.drag_n(v, rho=RHO_NIGHT), dtype=float)
    # drag_n already includes TRIM_DRAG_FACTOR; back it out then refit.
    d_raw = d_model / TRIM_DRAG_FACTOR
    scale = float(np.median(d_meas / np.clip(d_raw, 1e-6, None)))
    rms = float(np.sqrt(np.mean((d_meas - d_raw * scale) ** 2)))
    return Comparison(
        "glide_polar", len(df), float(np.mean(d_model)), float(np.mean(d_meas)),
        scale, rms, "TRIM_DRAG_FACTOR", scale, TRIM_DRAG_FACTOR,
        "Median meas/model drag; recommend replacing TRIM_DRAG_FACTOR.",
        False)


def evaluate_all(design: Design | None = None,
                 prop_name: str | None = None) -> list[Comparison]:
    design = design or reference_design()
    prop_name = prop_name or config.REF_PROP
    return [
        compare_panel(),
        compare_battery(),
        compare_charge_limit(),
        compare_thrust_stand(prop_name=prop_name),
        compare_glide_polar(design),
    ]


def write_recommendations(comps: list[Comparison],
                          path: Path = OUT_DEFAULT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "awaiting_any": any(c.awaiting_data for c in comps),
        "comparisons": [asdict(c) for c in comps],
        "note": ("Do not auto-edit config.py. Review these recommended factor "
                 "updates after the corresponding bench/flight test."),
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


# ---------------------------------------------------------------------------
# Synthetic self-test of the fitter (runs without lab data)
# ---------------------------------------------------------------------------
def run_self_test(seed: int = 11) -> dict:
    """Plant known scales, write temp CSVs, recover them, then delete."""
    rng = np.random.default_rng(seed)
    tmp = MEASURED_DIR / "_selftest"
    tmp.mkdir(parents=True, exist_ok=True)
    design = reference_design()
    results = {}

    # Panel: 12-cell string, plant 0.94 extra loss on DC power.
    arr = SolarArray(n_strings=1, cells_per_string=12)
    g = np.linspace(200, 1000, 16)
    t = 25.0 + 0.04 * g
    poa_eff = g * config.ENCAPSULATION_TRANSMISSION
    p_model = arr.power_dc_w(poa_eff, t)
    plant_panel = 0.94
    p_meas = p_model * plant_panel * (1.0 + 0.01 * rng.normal(size=g.size))
    panel_path = tmp / "panel_iv.csv"
    pd.DataFrame({"g_poa_w_m2": g, "t_cell_c": t, "p_dc_w": p_meas}).to_csv(
        panel_path, index=False)
    c_panel = compare_panel(panel_path, n_cells=12)
    results["panel_recovered"] = c_panel.scale_meas_over_model
    results["panel_planted"] = plant_panel
    results["panel_ok"] = abs(c_panel.scale_meas_over_model - plant_panel) < 0.03

    # Thrust: plant 0.90 on APC nominal.
    try:
        prop = load_prop(config.REF_PROP)
        rows = []
        plant_t = 0.90
        for rpm in list(prop.rpm_grid[2:8]):
            for v in (0.0, 8.0, 10.5):
                tn = prop.thrust_n(v, rpm, nominal=True)
                pn = prop.shaft_power_w(v, rpm, nominal=True)
                if not np.isfinite(tn) or tn <= 0:
                    continue
                rows.append({
                    "v_ms": v, "rpm": rpm,
                    "thrust_n": tn * plant_t * (1 + 0.01 * rng.normal()),
                    "shaft_power_w": (pn if np.isfinite(pn) else np.nan),
                })
        tpath = tmp / "thrust_stand.csv"
        pd.DataFrame(rows).to_csv(tpath, index=False)
        c_t = compare_thrust_stand(tpath, prop_name=config.REF_PROP)
        results["thrust_recovered"] = c_t.scale_meas_over_model
        results["thrust_planted"] = plant_t
        results["thrust_ok"] = abs(c_t.scale_meas_over_model - plant_t) < 0.04
    except Exception as exc:  # pragma: no cover - missing APC files
        results["thrust_ok"] = False
        results["thrust_error"] = str(exc)

    # Glide: plant TRIM_DRAG_FACTOR = 1.12 on the raw polar.
    from . import aircraft as ac
    v = np.linspace(design.min_airspeed(), 16.0, 10)
    d_raw = np.asarray(design.drag_n(v), dtype=float) / ac.TRIM_DRAG_FACTOR
    plant_d = 1.12
    d_meas = d_raw * plant_d * (1 + 0.015 * rng.normal(size=v.size))
    gpath = tmp / "glide_polar.csv"
    pd.DataFrame({"v_ms": v, "drag_n": d_meas}).to_csv(gpath, index=False)
    c_g = compare_glide_polar(design, gpath)
    results["glide_recovered"] = c_g.recommended_value
    results["glide_planted"] = plant_d
    results["glide_ok"] = abs(c_g.recommended_value - plant_d) < 0.05

    results["passed"] = all(results.get(k, False)
                            for k in ("panel_ok", "thrust_ok", "glide_ok"))
    return results
