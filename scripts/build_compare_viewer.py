"""Build AircraftView for every layout × battery combo.

Usage:
  .venv/bin/python scripts/build_compare_viewer.py

Writes outputs/compare/aircraft_viewer.html (serve that folder).
"""

from __future__ import annotations

import base64
import argparse
import json
import sys
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from study_variants import RECTANGULAR_LAYOUT, apply_layout, validate_layout
from engineering_snapshot import snapshot
from mass_allocation import allocation

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("engineering_view.html")
OUT_DIR = ROOT / "outputs" / "compare"

# GOLD V1 mean voltage is kept for the 36 Ah study (conservative vs 22.2 V).
_GOLD_WH = 483.0
_GOLD_AH = 23.68
_GOLD_KG = 1.278

BATTERIES = [
    {
        "id": "gold_v1",
        "label": "GOLD V1",
        "detail": "6S 23.7 Ah · 1.28 kg",
        "pack": {
            "PACK_ENERGY_WH": _GOLD_WH,
            "PACK_CAPACITY_AH": _GOLD_AH,
            "PACK_MASS_KG": _GOLD_KG,
            "PACK_CHARGE_MAX_A": 6.0,
        },
    },
    {
        "id": "6s_36ah",
        "label": "6S 36 Ah",
        "detail": "6S 36 Ah · 2.0 kg",
        "pack": {
            "PACK_ENERGY_WH": 36.0 * _GOLD_WH / _GOLD_AH,
            "PACK_CAPACITY_AH": 36.0,
            "PACK_MASS_KG": 2.0,
            "PACK_CHARGE_MAX_A": 6.0,
        },
    },
]

LAYOUTS = [
    {
        "id": "pi_tail",
        "label": "Single empennage (π-tail)",
        "short": "π-tail",
        "root": ROOT,
        "csv": {
            "gold_v1": ROOT / "outputs" / "phase4_candidates.csv",
            "6s_36ah": ROOT / "outputs" / "battery_36ah" / "pi_tail_phase4.csv",
        },
    },
    {
        "id": "split",
        "label": "Split empennage",
        "short": "Split",
        "root": ROOT / "split_empennage",
        "csv": {
            "gold_v1": ROOT / "split_empennage" / "outputs" / "phase4_candidates.csv",
            "6s_36ah": ROOT / "outputs" / "battery_36ah" / "split_phase4.csv",
        },
    },
    {
        "id": "conventional",
        "label": "Conventional",
        "short": "Conv.",
        "root": ROOT / "conventional",
        "csv": {
            "gold_v1": ROOT / "conventional" / "outputs" / "phase4_candidates.csv",
            "6s_36ah": ROOT / "outputs" / "battery_36ah" / "conventional_phase4.csv",
        },
    },
]

LAYOUTS.append({
    "id": RECTANGULAR_LAYOUT,
    "label": "Conventional rectangular (no twist)",
    "short": "Rect.",
    "root": ROOT / "conventional",
    "csv": {b["id"]: ROOT / "outputs/rectangular_2026-09-15" /
            f"{RECTANGULAR_LAYOUT}__{b['id']}.csv" for b in BATTERIES},
})

for _layout in LAYOUTS:
    if _layout["id"] != RECTANGULAR_LAYOUT:
        _layout["csv"] = {
            b["id"]: ROOT / "outputs/surrogate_final_2026-09-15" /
            f"{_layout['id']}__{b['id']}.csv" for b in BATTERIES
        }


def combo_id(layout_id: str, battery_id: str) -> str:
    return f"{layout_id}__{battery_id}"


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


def _apply_pack(config, pack: dict):
    for key, value in pack.items():
        setattr(config, key, float(value) if key != "PACK_CAPACITY_AH" else float(value))


def _design_from_csv(optimize, load_prop, csv: Path, reference_design, config):
    if csv.exists():
        import pandas as pd
        w = optimize.winner(pd.read_csv(csv))
        if w is not None:
            d = optimize.design_from_row(w)
            pname = str(w["prop"])
            prop = load_prop(pname)
            d.prop_diameter_in = prop.diameter_in or d.prop_diameter_in
            d.prop_name = pname
            return d, True, w
    raise ValueError(f"No evaluated candidate available for the engineering snapshot: {csv}")


def bundle_combo(layout: dict, battery: dict) -> dict:
    _purge_solar_uav()
    root = layout["root"]
    csv = layout["csv"][battery["id"]]
    sys.path.insert(0, str(root))
    try:
        from solar_uav import config
        apply_layout(config, layout["id"])
        from solar_uav import optimize
        from solar_uav.aircraft import RHO_NIGHT, reference_design
        from solar_uav.cad import (
            drag_snapshot, mesh_cells, mesh_props, mesh_structure,
            mission_snapshot, write_stl,
        )
        from solar_uav.components.motor import drive_for
        from solar_uav.components.propulsion import PropulsionSystem, load_prop
        from solar_uav.viewer_data import payload as viewer_payload

        _apply_pack(config, battery["pack"])
        d, from_csv, search_row = _design_from_csv(
            optimize, load_prop, csv, reference_design, config)
        validate_layout(d, layout["id"])
        energy = mission_snapshot(d)
        if not energy:
            raise RuntimeError(f"Mission recomputation failed for {csv}")
        hard_failure = optimize._hard_constraints(d)
        v_control = d.min_power_speed()
        if layout["id"] in ("conventional", RECTANGULAR_LAYOUT):
            yaw_pass = d.rudder_yaw_ok(v_control)
        else:
            psys = PropulsionSystem(prop=load_prop(d.prop_name),
                                    motor=drive_for(d.motor_name))
            t_one = psys.max_thrust_n(v_control, rho=RHO_NIGHT) / config.N_MOTORS
            yaw_pass = d.differential_thrust_yaw_ok(t_one, v_control)
        if search_row is not None and not np.isclose(
                d.mass_kg, float(search_row["mass_kg"]), atol=1e-6, rtol=0):
            raise ValueError(f"Reconstructed mass differs from search for {csv}")
        v_night = energy.get("v_night_ms")
        drag = drag_snapshot(d, v_ms=v_night)
        cid = combo_id(layout["id"], battery["id"])
        print(f"  {cid}: {d.span_m:.2f}×{d.chord_m:.2f} m  "
              f"{d.string_plan_label()}  {d.n_cells} cells  "
              f"{d.prop_name}  {d.mass_kg:.2f} kg  packs={d.n_packs}  "
              f"csv={from_csv}  closed={bool((energy or {}).get('closed'))}  "
              f"margin={(energy or {}).get('margin_wh')}",
              flush=True)
        data = viewer_payload(d, energy, drag)
        search_soc = (search_row.get("objective_soc")
                      if search_row is not None else None)
        data["study"] = {
            "source_csv": str(csv.resolve()),
            "search_morning_soc": search_soc,
            "verified_morning_soc": energy["objective_soc"],
            "morning_soc_difference_pp": (
                100 * (energy["objective_soc"] - search_soc)
                if search_soc is not None else None),
            "search_closed": bool(search_row["closed"]) if search_row is not None else None,
            "hard_failure": hard_failure,
            "yaw_pass": bool(yaw_pass),
            "passed": bool(energy["closed"] and not hard_failure and yaw_pass),
        }
        pack_wh = float(config.PACK_ENERGY_WH)
        data["combo"] = {
            "layout_id": layout["id"],
            "layout_label": layout["label"],
            "layout_short": layout["short"],
            "battery_id": battery["id"],
            "battery_label": battery["label"],
            "battery_detail": battery["detail"],
            "from_csv": from_csv,
            "pack_wh": pack_wh,
            "pack_ah": float(config.PACK_CAPACITY_AH),
            "pack_mass_kg": float(config.PACK_MASS_KG),
        }
        data["metrics"] = {
            "n_motors": int(config.N_MOTORS),
            "n_packs": int(d.n_packs),
            "n_cells": int(d.n_cells),
            "string_plan": d.string_plan_label(),
            "prop": d.prop_name,
            "motor": d.motor_name,
            "pack_wh": float(d.n_packs * pack_wh),
            "pack_wh_each": pack_wh,
            "pack_mass_kg": float(config.PACK_MASS_KG),
            "boom_od_mm": float(config.BOOM_DIAMETER_M * 1000.0),
        }
        data["dims"]["mass_kg"] = float(d.mass_kg)
        data["review"] = snapshot(data, d, config, csv, root)
        data["mass"]["allocation"] = allocation(d, config)
        return {
            "id": cid,
            "label": f"{layout['short']} · {battery['label']}",
            "layout_id": layout["id"],
            "battery_id": battery["id"],
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--rectangular-results-dir", type=Path,
                        help="Optional separate results directory for the rectangular variant")
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    for layout in LAYOUTS:
        source_dir = (args.rectangular_results_dir
                      if layout["id"] == RECTANGULAR_LAYOUT and args.rectangular_results_dir
                      else args.results_dir)
        if source_dir:
            for battery in BATTERIES:
                csv = source_dir / f"{combo_id(layout['id'], battery['id'])}.csv"
                if not csv.exists():
                    raise FileNotFoundError(csv)
                layout["csv"][battery["id"]] = csv
    print("Building compare viewer (layout × battery)…", flush=True)
    configs = {}
    combo_order = []
    for batt in BATTERIES:
        for layout in LAYOUTS:
            cid = combo_id(layout["id"], batt["id"])
            combo_order.append(cid)
            configs[cid] = bundle_combo(layout, batt)
    meta = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "schema_version": 2,
        "layouts": [{"id": L["id"], "label": L["label"], "short": L["short"]}
                    for L in LAYOUTS],
        "batteries": [{"id": B["id"], "label": B["label"], "detail": B["detail"]}
                      for B in BATTERIES],
        "comboOrder": combo_order,
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    html = (template
            .replace("__TITLE__", "AircraftView — layout × battery")
            .replace("__META_JSON__", json.dumps(meta, separators=(",", ":")))
            .replace("__CONFIGS_JSON__", json.dumps(
                configs, separators=(",", ":"), default=_json_default)))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = args.output_dir / "lib" / "review"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for asset in Path(__file__).with_name("aircraft_view").iterdir():
        if asset.is_file():
            shutil.copy2(asset, asset_dir / asset.name)
            (args.output_dir / asset.name).unlink(missing_ok=True)
    out = args.output_dir / "aircraft_viewer.html"
    out.write_text(html, encoding="utf-8")
    summary = {cid: {"study": c["payload"]["study"],
                     "mass_kg": c["payload"]["dims"]["mass_kg"],
                     "metrics": c["payload"]["metrics"],
                     "energy": {k: v for k, v in c["payload"]["energy"].items()
                                if not isinstance(v, (list, dict))}}
               for cid, c in configs.items()}
    (args.output_dir / "study_results.json").write_text(
        json.dumps(summary, indent=2, default=_json_default))
    print(f"Wrote {out}  ({out.stat().st_size / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
