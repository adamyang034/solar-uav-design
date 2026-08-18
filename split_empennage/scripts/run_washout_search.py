"""Washout search: tapered (case A) vs rectangular extra-cells (case B).

Both unlock geometric washout on the outboard panel. Case A keeps the
one-string-per-bay Voc rule and the taper grid. Case B locks rectangular
outboards and packs leftover cells as extra Voc-legal strings.

Neighborhood is the 12L nearest-miss family (6.0 m, 0.36–0.40 m chord,
0.80–1.00 m tail, 1.30/1.56 m booms). Motor locked to A40-12L kv410.

Usage:  .venv/bin/python scripts/run_washout_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import alpha_deg_at_cl, reference_design
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "outputs"
MOTOR = "A40-12L-V4-kv410-direct"
# Props that actually won on the 12L grid, plus two larger fans for the
# heavier rectangular wing. Full 51-prop catalog is a runtime sink here.
PROPS = ("MJ-21x14EL", "16x12E", "17x12E", "18x12E", "19x12E", "20x13E", "21x13E")

SPAN = (6.0,)
CHORD = (0.36, 0.40)
TAIL = (0.80, 0.90, 1.00)
BOOM = (1.30, 1.56)
ELEV = (0.34,)


def _sanity():
    """Zero washout must not move the published baseline polar."""
    d0 = reference_design()
    d1 = reference_design(washout_tip_deg=0.0, washout_start_frac=0.0)
    v = d0.min_airspeed()
    drag0 = float(d0.drag_n(v))
    drag1 = float(d1.drag_n(v))
    if abs(drag0 - drag1) > 1e-6:
        raise RuntimeError(f"zero-washout polar moved: {drag0:.4f} vs {drag1:.4f} N")
    dw = reference_design(washout_tip_deg=5.0, washout_start_frac=0.0)
    a_l0 = np.radians(float(alpha_deg_at_cl(dw.wing_airfoil, 0.0, 2e5)))
    a0 = dw._section_a0(2e5)
    _at, cl_t = dw._ll_match(dw.cruise_cl(), 0.0, a_l0, a0, True)
    _a0, cl_u = dw._ll_match(dw.cruise_cl(), 0.0, a_l0, a0, False)
    if float(cl_t[0]) >= float(cl_u[0]) - 1e-4:
        raise RuntimeError(
            f"washout did not unload the tip: twisted {cl_t[0]:.3f} vs "
            f"untwisted {cl_u[0]:.3f}")
    print(f"  sanity: baseline drag {drag0:.3f} N unchanged; "
          f"5° washout tip CL {cl_u[0]:.3f} → {cl_t[0]:.3f}  "
          f"root CL {cl_u[-1]:.3f} → {cl_t[-1]:.3f}")


def _show(df, label: str, path: Path):
    df.to_csv(path, index=False)
    print(f"  {len(df)} candidates → {path}")
    print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
    cols = ["span_m", "chord_m", "tail_arm_m", "boom_spacing_m",
            "taper_ratio", "taper_start_frac", "washout_tip_deg",
            "washout_start_frac", "string_plan", "n_cells", "prop",
            "mass_kg", "p_night_w", "solar_wh", "margin_wh", "closed"]
    print(f"  {label} top 8:")
    print(df[cols].head(8).to_string(index=False))
    w = optimize.winner(df)
    return w


def _drive():
    return drive_for(MOTOR)


def _resim(row, env):
    d = optimize.design_from_row(row)
    psys = PropulsionSystem(prop=load_prop(str(row["prop"])), motor=_drive())
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    d.prop_name = str(row["prop"])
    r = mission.simulate(d, env, psys)
    print(f"  re-sim {d.span_m:.1f}×{d.chord_m:.2f} λ={d.taper_ratio:.2f} "
          f"wo={d.washout_tip_deg:.1f}°@{d.washout_start_frac:.2f}  "
          f"cells={d.n_cells}  mass={d.mass_kg:.2f} kg  "
          f"Pnight={r.p_night_w:.1f} W  solar={r.solar_wh:.0f} Wh  "
          f"margin={r.margin_wh:.1f} Wh  closed={r.closed}")
    return d, r


def main():
    print("WASHOUT SANITY")
    _sanity()

    env = environment.design_day(config.SOLSTICE_DATE)
    wo = optimize.washout_grid()
    common = dict(
        env=env, verbose=True, motor_name=MOTOR,
        span_grid=SPAN, chord_grid=CHORD, tail_grid=TAIL,
        elevator_grid=ELEV, boom_grid=BOOM, washout_pairs=wo,
        prop_names=list(PROPS),
    )

    print("=" * 70)
    print("CASE A — washout unlocked, taper still allowed, one string/bay")
    df_a = optimize.search(
        mixed_strings=True, one_string_per_bay=True, **common)
    w_a = _show(df_a, "A", OUT / "phase4_washout_taper.csv")

    print("=" * 70)
    print("CASE B — washout unlocked, rectangular, extra cells packed")
    df_b = optimize.search(
        mixed_strings=True, one_string_per_bay=False,
        taper_pairs=[(1.0, 1.0)], **common)
    w_b = _show(df_b, "B", OUT / "phase4_washout_rect.csv")

    print("=" * 70)
    print("BASELINE (current 12L nearest-miss, washout 0)")
    d0 = reference_design()
    psys0 = PropulsionSystem(prop=load_prop(config.REF_PROP), motor=_drive())
    d0.prop_diameter_in = psys0.prop.diameter_in or 18.0
    r0 = mission.simulate(d0, env, psys0)
    print(f"  {d0.span_m:.1f}×{d0.chord_m:.2f} λ={d0.taper_ratio:.2f}  "
          f"cells={d0.n_cells}  mass={d0.mass_kg:.2f} kg  "
          f"Pnight={r0.p_night_w:.1f} W  solar={r0.solar_wh:.0f} Wh  "
          f"margin={r0.margin_wh:.1f} Wh  closed={r0.closed}")

    print("=" * 70)
    print("WINNERS")
    if w_a is not None:
        print("  Case A:")
        _resim(w_a, env)
    if w_b is not None:
        print("  Case B:")
        _resim(w_b, env)
    print(f"  Baseline margin {r0.margin_wh:.1f} Wh")


if __name__ == "__main__":
    main()
