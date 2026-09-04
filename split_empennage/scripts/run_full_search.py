"""Full split-empennage Phase 4 search (wing + inner prop).

Usage:
  .venv/bin/python split_empennage/scripts/run_full_search.py
  .venv/bin/python split_empennage/scripts/run_full_search.py --smoke
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, optimize
from solar_uav.cad import export_all
from solar_uav.components.motor import drive_for
from solar_uav.components.propulsion import PropulsionSystem, load_prop


OUT = Path(__file__).resolve().parents[1] / "outputs"


def motors_on_winner(env, w):
    print("-- catalog motors on this airframe (prop re-picked) --")
    prop_names = optimize._prop_candidates()
    cache = {n: load_prop(n) for n in prop_names}
    rows = []
    for key in config.MOTOR_CATALOG:
        d = optimize.design_from_row(w)
        d.motor_name = key
        drive = drive_for(key)
        systems = {n: PropulsionSystem(prop=cache[n], motor=drive)
                   for n in prop_names}
        rec = optimize.evaluate_design(
            d, env, prop_names, cache, drive, systems)
        if rec is None:
            print(f"  {key}: no climb-legal prop")
            continue
        rows.append(rec)
        print(f"  {key}  {rec['prop']}  mass={rec['mass_kg']:.2f} kg  "
              f"Pnight={rec['p_night_w']:.1f} W  margin={rec['margin_wh']:.1f} Wh  "
              f"closed={rec['closed']}")
    if rows:
        import pandas as pd
        pd.DataFrame(rows).to_csv(OUT / "phase4_motors_on_winner.csv",
                                  index=False)


def main():
    smoke = "--smoke" in sys.argv
    env = environment.design_day(config.SOLSTICE_DATE)
    kwargs = dict(env=env, verbose=True,
                  dump_path=OUT / "phase4_candidates.csv")
    if smoke:
        kwargs.update(maxiter=1, popsize=1, workers=4)
        kwargs["dump_path"] = OUT / "phase4_smoke.csv"
        print("SMOKE: maxiter=1 popsize=1 workers=4")
    print("=" * 70)
    print("PHASE 4 — continuous search (max energy margin)")
    df = optimize.search_continuous(**kwargs)
    if df.empty:
        print("  No candidates survived the hard constraints.")
        return
    path = kwargs["dump_path"]
    df.to_csv(path, index=False)
    print(f"  {len(df)} candidates written to {path}")
    print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
    print("  Failure modes:")
    print(df["reason"].value_counts().head(8).to_string())
    cols = ["span_m", "chord_m", "tail_arm_m", "boom_spacing_m",
            "n_packs", "n_cells", "prop", "mass_kg", "margin_wh", "soc_min",
            "p_night_w", "closed"]
    print("  Top 5 by margin:")
    print(df[cols].head(5).to_string(index=False))
    w = optimize.winner(df)
    print("  Winner:")
    show = ["span_m", "chord_m", "tail_arm_m", "boom_spacing_m",
            "taper_ratio", "string_plan", "n_packs", "n_cells", "prop", "motor",
            "mass_kg", "margin_wh", "soc_min", "soc_end", "cycle_wh",
            "p_night_w", "climb_ms", "closed", "reason"]
    show = [c for c in show if c in w.index]
    print(w[show].to_string())
    if smoke:
        return
    d = optimize.design_from_row(w)
    paths = export_all(d)
    print(f"  CAD viewer: {paths['html']}")
    motors_on_winner(env, w)


if __name__ == "__main__":
    main()
