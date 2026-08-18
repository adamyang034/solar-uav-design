"""Phase 4 re-run with outboard taper unfrozen.

Writes outputs/phase4_taper.csv. Mixed string packing stays on.

Usage:  .venv/bin/python pi_tail_maxeon_gen5/scripts/run_taper_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import Design, reference_design
from solar_uav.components.propulsion import PropulsionSystem, load_prop

OUT = Path(__file__).resolve().parents[1] / "outputs"


def _show(d: Design, label: str):
    bays = d.solar_bays()
    print(f"{label}:")
    print(f"  S={d.wing_area:.3f} m²  AR={d.aspect_ratio:.1f}  MAC={d.mac_m:.3f} m  "
          f"tip={d.tip_chord_m:.3f} m  taper starts y={d.y_taper_m:.2f} m")
    print(f"  mass {d.mass_kg:.3f} kg  cells {d.n_cells}  "
          f"plan {d.string_plan_label()}  e={d.oswald_e:.3f}")
    for name, bay in bays.items():
        print(f"    {name:18s} cap={bay.capacity:3d}  "
              f"{bay.rows}×{bay.cols}" +
              (f" (fixed {bay.n_cells_fixed})" if bay.n_cells_fixed is not None else ""))


def main():
    rect = reference_design()
    _show(rect, "Rectangular reference (6.00 × 0.36 m)")
    tap = reference_design(taper_ratio=0.40, taper_start_frac=0.50)
    _show(tap, "Same planform, λ=0.40 starting halfway along outboards")

    env = environment.design_day(config.SOLSTICE_DATE)
    print("=" * 70)
    print("PHASE 4 — mixed strings + outboard taper")
    df = optimize.search(env, verbose=True, mixed_strings=True)
    if df.empty:
        print("  No candidates survived the hard constraints.")
        return
    path = OUT / "phase4_chord300.csv"
    df.to_csv(path, index=False)
    n_closed = int(df["closed"].sum())
    print(f"  {len(df)} candidates written to {path}")
    print(f"  closed: {n_closed} / {len(df)}")
    print("  Failure modes:")
    print(df["reason"].value_counts().head(8).to_string())
    cols = ["span_m", "chord_m", "taper_ratio", "taper_start_frac",
            "n_packs", "string_plan", "n_cells", "prop", "mass_kg",
            "wing_area_m2", "margin_wh", "p_night_w", "climb_ms", "closed"]
    print("  Top 10 by margin:")
    print(df[cols].head(10).to_string(index=False))
    w = optimize.winner(df)
    print("  Winner:")
    print(w[cols].to_string())
    d = optimize.design_from_row(w)
    psys = PropulsionSystem(prop=load_prop(str(w["prop"])))
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    res = mission.simulate(d, env, psys)
    print(f"  Re-sim: closed={res.closed}  margin={res.margin_wh:.1f} Wh  "
          f"SOC min={res.soc_min:.3f}  Pnight={res.p_night_w:.1f} W  "
          f"solar={res.solar_wh:.0f} Wh  climb={res.climb_ms:.2f} m/s  "
          f"mass={d.mass_kg:.3f} kg  S={d.wing_area:.3f} m²  cells={d.n_cells}")
    print(f"  vs prior taper best −218 Wh: {res.margin_wh - (-218):+.0f} Wh")
    print(f"  vs mixed-rect best −356 Wh: {res.margin_wh - (-356):+.0f} Wh")


if __name__ == "__main__":
    main()
