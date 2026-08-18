"""Export / refresh the aircraft CAD visualizer.

Usage:  .venv/bin/python scripts/visualize.py

Serves the Three.js viewer at http://127.0.0.1:8099/  (ES modules will not
load from a file:// page). Reuses the server if it is already running.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav.aircraft import reference_design
from solar_uav.cad import export_all
from solar_uav.cad_server import ensure_running
from solar_uav.components.propulsion import load_prop
from solar_uav import config


def main():
    d = reference_design()
    prop = load_prop(config.REF_PROP)
    d.prop_diameter_in = prop.diameter_in or 22.0
    print(f"CAD: {d.span_m:.3f}×{d.chord_m:.3f} m  λ={d.taper_ratio:.3f}  "
          f"wo={d.washout_tip_deg:.2f}°  H-arm {d.tail_arm_m:.2f} m  "
          f"V-arm {d.vstab_arm_m:.2f} m  {d.string_plan_label()}  "
          f"{d.n_cells} cells  {config.REF_PROP}  {d.mass_kg:.2f} kg")
    paths = export_all(d)
    print("Wrote:")
    for k, p in paths.items():
        print(f"  {k:16s} {p}")
    href = ensure_running()
    print(f"Viewer  {href}")
    webbrowser.open(href)


if __name__ == "__main__":
    main()
