"""One series string per panel, GVB-8 Voc/power cap, wider inboard/H-stab.

Usage:  .venv/bin/python scripts/run_one_string_bays.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import Design
from solar_uav.components.propulsion import PropulsionSystem, load_prop
from solar_uav.components.solar_array import max_cells_per_string

OUT = Path(__file__).resolve().parents[1] / "outputs"


def _show(d: Design, label: str):
    bays = d.solar_bays()
    print(f"{label}")
    print(f"  boom={d.boom_spacing:.3f} m  H-stab {d.hstab_span:.3f}×{d.hstab_chord:.3f} m  "
          f"Vh={d.tail_volume_h():.3f}  AR_h={d._planform()['hstab_ar_actual']:.1f}")
    print(f"  S={d.wing_area:.3f}  cells {d.n_cells}  plan {d.string_plan_label()}  "
          f"mass {d.mass_kg:.3f} kg  feasible={d.solar_feasible()}")
    for name, bay in bays.items():
        print(f"    {name:18s} {bay.capacity:3d} cells")


def main():
    limit = max_cells_per_string()
    print(f"GVB-8 cap → max {limit} cells/string")
    d0 = Design(span_m=6.0, chord_m=0.30, tail_arm_m=1.30, n_packs=2,
                elevator_frac=0.28, one_string_per_bay=True,
                taper_ratio=0.4, taper_start_frac=0.5,
                boom_spacing_set_m=1.69)
    _show(d0, "Example: 6.0×0.30, boom 1.69 m, λ=0.4 halfway")

    env = environment.design_day(config.SOLSTICE_DATE)
    print("=" * 70)
    print("PHASE 4 — one string per bay, wide inboard")
    df = optimize.search(
        env, verbose=True, mixed_strings=True, one_string_per_bay=True,
        boom_grid=config.BOOM_SPACING_GRID_M,
        elevator_grid=(0.28, 0.34))
    if df.empty:
        print("  No candidates survived (likely solar layout / mass).")
        return
    path = OUT / "phase4_one_string_bays.csv"
    df.to_csv(path, index=False)
    print(f"  {len(df)} candidates written to {path}")
    print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
    cols = ["span_m", "chord_m", "elevator_frac", "boom_spacing_m", "taper_ratio",
            "taper_start_frac", "string_plan", "n_cells", "inboard_cells",
            "outboard_cells", "hstab_cells", "prop", "mass_kg", "p_night_w",
            "margin_wh", "closed"]
    print("  Top 10:")
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
          f"cells={d.n_cells}  MPPTs={d.n_mppts}  mass={d.mass_kg:.3f} kg")
    print(f"  vs 2-pack mixed best −184 Wh: {res.margin_wh - (-184):+.0f} Wh")


if __name__ == "__main__":
    main()
