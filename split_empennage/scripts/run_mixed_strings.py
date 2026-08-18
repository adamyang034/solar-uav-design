"""Phase 4 re-run with mixed string lengths (no uniform cells/string grid).

Writes outputs/phase4_mixed_strings.csv and does not touch the uniform-grid
baseline in outputs/phase4_candidates.csv.

Usage:  .venv/bin/python scripts/run_mixed_strings.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, mission, optimize
from solar_uav.aircraft import reference_design
from solar_uav.components.propulsion import PropulsionSystem, load_prop

OUT = Path(__file__).resolve().parents[1] / "outputs"


def main():
    d0 = reference_design()
    packed = d0.pack_layout()
    print("Reference mixed pack (6.00 × 0.36 m, 2 packs):")
    print(f"  by bay: {packed['by_bay']}")
    print(f"  strings {d0.string_plan_label()}  cells {d0.n_cells}  "
          f"MPPTs {d0.n_mppts}  mass {d0.mass_kg:.3f} kg")

    env = environment.design_day(config.SOLSTICE_DATE)
    print("=" * 70)
    print("PHASE 4 — mixed-length string search")
    df = optimize.search(env, verbose=True, mixed_strings=True)
    if df.empty:
        print("  No candidates survived the hard constraints.")
        return
    path = OUT / "phase4_mixed_strings.csv"
    df.to_csv(path, index=False)
    n_closed = int(df["closed"].sum())
    print(f"  {len(df)} candidates written to {path}")
    print(f"  closed: {n_closed} / {len(df)}")
    print("  Failure modes:")
    print(df["reason"].value_counts().head(8).to_string())
    print("  Top 8 by margin:")
    cols = ["span_m", "chord_m", "n_packs", "string_plan", "n_cells",
            "n_strings", "prop", "mass_kg", "margin_wh", "p_night_w",
            "climb_ms", "closed", "reason"]
    print(df[cols].head(8).to_string(index=False))

    w = optimize.winner(df)
    print("  Winner:")
    print(w[cols].to_string())

    d = optimize.design_from_row(w)
    psys = PropulsionSystem(prop=load_prop(str(w["prop"])))
    d.prop_diameter_in = psys.prop.diameter_in or 18.0
    res = mission.simulate(d, env, psys)
    print(f"  Re-sim: closed={res.closed}  margin={res.margin_wh:.1f} Wh  "
          f"SOC min={res.soc_min:.3f}  Pnight={res.p_night_w:.1f} W  "
          f"solar={res.solar_wh:.0f} Wh  climb={res.climb_ms:.2f} m/s")
    print(f"  vs uniform 7×12=84 cells (~−770 Wh on this planform)")
    print(f"  Δcells={d.n_cells - 84:+d}  Δmargin vs −770 Wh: "
          f"{res.margin_wh - (-770):+.0f} Wh")


if __name__ == "__main__":
    main()
