"""Export / refresh the split-empennage CAD visualizer.

Usage:  .venv/bin/python split_empennage/scripts/visualize.py
Opens split_empennage/outputs/aircraft_viewer.html when possible.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav.aircraft import reference_design
from solar_uav.cad import export_all
from solar_uav.components.propulsion import load_prop
from solar_uav import config, optimize


def _design():
    csv = Path(__file__).resolve().parents[1] / "outputs" / "phase4_candidates.csv"
    if csv.exists():
        import pandas as pd
        w = optimize.winner(pd.read_csv(csv))
        d = optimize.design_from_row(w)
        prop = load_prop(str(w["prop"]))
        d.prop_diameter_in = prop.diameter_in or d.prop_diameter_in
        d.prop_name = str(w["prop"])
        return d, str(w["prop"])
    d = reference_design()
    prop = load_prop(config.REF_PROP)
    d.prop_diameter_in = prop.diameter_in or 22.0
    return d, config.REF_PROP


def main():
    d, pname = _design()
    print(f"CAD: {d.span_m:.2f}×{d.chord_m:.2f} m  {d.string_plan_label()}  "
          f"{d.n_cells} cells  {pname}  {d.mass_kg:.2f} kg")
    paths = export_all(d)
    html = Path(paths["html"])
    print("Wrote:")
    for k, p in paths.items():
        print(f"  {k:16s} {p}")
    webbrowser.open(html.resolve().as_uri())


if __name__ == "__main__":
    main()
