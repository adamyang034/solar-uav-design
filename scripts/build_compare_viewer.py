"""Build the three-config AircraftView (dropdown + compare table).

Usage:
  .venv/bin/python scripts/build_compare_viewer.py

Writes outputs/compare/aircraft_viewer.html (serve that folder).
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("compare_view.html")
OUT_DIR = ROOT / "outputs" / "compare"

FORKS = [
    {
        "id": "pi_tail",
        "label": "Single empennage (π-tail)",
        "root": ROOT,
        "csv": ROOT / "outputs" / "phase4_candidates.csv",
    },
    {
        "id": "split",
        "label": "Split empennage",
        "root": ROOT / "split_empennage",
        "csv": ROOT / "split_empennage" / "outputs" / "phase4_candidates.csv",
    },
    {
        "id": "conventional",
        "label": "Conventional",
        "root": ROOT / "conventional",
        "csv": ROOT / "conventional" / "outputs" / "phase4_candidates.csv",
    },
]


def _purge_solar_uav():
    for k in list(sys.modules):
        if k == "solar_uav" or k.startswith("solar_uav."):
            del sys.modules[k]


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


def _stl_b64(write_stl, mesh, name: str) -> str:
    pts, faces = mesh
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    write_stl(tmp_path, pts, faces, name=name)
    b64 = base64.b64encode(tmp_path.read_bytes()).decode("ascii")
    tmp_path.unlink(missing_ok=True)
    return b64


def _design_from_csv(optimize, load_prop, csv: Path, reference_design, config):
    if csv.exists():
        import pandas as pd
        w = optimize.winner(pd.read_csv(csv))
        if w is not None and bool(w.get("closed", False)):
            d = optimize.design_from_row(w)
            pname = str(w["prop"])
            prop = load_prop(pname)
            d.prop_diameter_in = prop.diameter_in or d.prop_diameter_in
            d.prop_name = pname
            return d
    d = reference_design()
    prop = load_prop(config.REF_PROP)
    d.prop_diameter_in = prop.diameter_in or d.prop_diameter_in
    d.prop_name = config.REF_PROP
    return d


def bundle_fork(spec: dict) -> dict:
    _purge_solar_uav()
    root = spec["root"]
    sys.path.insert(0, str(root))
    try:
        from solar_uav import config, optimize
        from solar_uav.aircraft import reference_design
        from solar_uav.cad import (
            drag_snapshot, mesh_cells, mesh_props, mesh_structure,
            mission_snapshot, write_stl,
        )
        from solar_uav.components.propulsion import load_prop
        from solar_uav.viewer_data import payload as viewer_payload

        d = _design_from_csv(
            optimize, load_prop, spec["csv"], reference_design, config)
        energy = mission_snapshot(d)
        v_night = energy.get("v_night_ms")
        drag = drag_snapshot(d, v_ms=v_night)
        print(f"  {spec['id']}: {d.span_m:.2f}×{d.chord_m:.2f} m  "
              f"{d.string_plan_label()}  {d.n_cells} cells  "
              f"{d.prop_name}  {d.mass_kg:.2f} kg  packs={d.n_packs}  "
              f"closed={bool((energy or {}).get('closed'))}  "
              f"margin={(energy or {}).get('margin_wh')}",
              flush=True)
        data = viewer_payload(d, energy, drag)
        data["metrics"] = {
            "n_motors": int(config.N_MOTORS),
            "n_packs": int(d.n_packs),
            "n_cells": int(d.n_cells),
            "string_plan": d.string_plan_label(),
            "prop": d.prop_name,
            "motor": d.motor_name,
            "pack_wh": float(d.n_packs * config.PACK_ENERGY_WH),
            "boom_od_mm": float(config.BOOM_DIAMETER_M * 1000.0),
        }
        data["dims"]["mass_kg"] = float(d.mass_kg)
        return {
            "label": spec["label"],
            "payload": data,
            "struct": _stl_b64(write_stl, mesh_structure(d), "structure"),
            "cells": _stl_b64(write_stl, mesh_cells(d), "cells"),
            "props": _stl_b64(write_stl, mesh_props(d), "props"),
        }
    finally:
        if sys.path and sys.path[0] == str(root):
            sys.path.pop(0)
        _purge_solar_uav()


def main():
    print("Building compare viewer…", flush=True)
    configs = {}
    for spec in FORKS:
        configs[spec["id"]] = bundle_fork(spec)
    template = TEMPLATE.read_text(encoding="utf-8")
    html = (template
            .replace("__TITLE__", "AircraftView — three configurations")
            .replace("__CONFIGS_JSON__", json.dumps(
                configs, separators=(",", ":"), default=_json_default)))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "aircraft_viewer.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({out.stat().st_size / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
