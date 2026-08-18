"""Simple CAD of the split-empennage twin-fuselage airframe.

Builds an AeroSandbox solid (wing, two T-tails, pods, booms), plus
wing solar-cell patches and tractor prop disks. Exports:

  * binary STL (structure mesh)
  * OpenSCAD source (lofted airfoils + cylinders)
  * self-contained Three.js HTML viewer (dimensions + mass bars)
  * annotated matplotlib three-view and mass bar chart
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from . import config
from .aircraft import BOOM_DIAMETER_M, Design, reference_design
from .components import solar_array

IN_TO_M = 0.0254


def _rotate_y(pts: np.ndarray, deg: float,
              x0: float = 0.0, z0: float = 0.0) -> np.ndarray:
    """Rotate points about +y through (x0, z0). Positive deg = TE down (LE-up incidence)."""
    th = np.radians(deg)
    c, s = np.cos(th), np.sin(th)
    out = np.array(pts, dtype=float, copy=True)
    x = out[..., 0] - x0
    z = out[..., 2] - z0
    out[..., 0] = x0 + x * c + z * s
    out[..., 2] = z0 - x * s + z * c
    return out


def build_airplane(design: Design | None = None):
    d = design or reference_design()
    d.aileron_y_inner()
    return d, d.to_asb()


def _triangulate(faces: np.ndarray) -> np.ndarray:
    faces = np.asarray(faces, dtype=np.int32)
    if faces.ndim != 2:
        raise ValueError("faces must be (M, 3) or (M, 4)")
    if faces.shape[1] == 3:
        return faces
    if faces.shape[1] == 4:
        return np.vstack([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])
    raise ValueError(f"unsupported face width {faces.shape[1]}")


def mesh_structure(design: Design | None = None):
    """(points, tri_faces) of the AeroSandbox solid."""
    d, ac = build_airplane(design)
    points, faces = ac.mesh_body(method="tri", thin_wings=False)
    return np.asarray(points, dtype=float), _triangulate(np.asarray(faces))


def _upper_surface_z(af, chord: float, x_from_le: float,
                     offset: float = 0.003) -> float:
    """Aircraft-z of the upper skin at x, in the section frame (camber at z=0)."""
    upper = np.asarray(af.upper_coordinates(), dtype=float)[::-1]
    c = max(float(chord), 1e-6)
    xi = float(np.clip(x_from_le / c, 0.0, 1.0))
    y_c = float(np.interp(xi, upper[:, 0], upper[:, 1]))
    return c * y_c + offset


def _cell_quads(design: Design) -> list[np.ndarray]:
    """Top-surface 125 mm cells as 4-vertex quads (x,y,z).

    Columns are packed boom→tip so the taper sheds rows as local chord
    falls below each pitch. Budget matches the electrical n_cells.
    Cells sit on the airfoil upper surface, not the chord plane.
    """
    import aerosandbox as asb
    pitch = config.CELL_PITCH_M
    side = config.CELL_SIDE_M
    af_w = asb.Airfoil(design.wing_airfoil)
    quads = []
    used = 0
    budget = design.n_cells
    i_w = design.wing_incidence_deg()

    def add_cell(x_c, y_c, usable_x, inc, rx, rz, chord, af, x_le, z_camber):
        nonlocal used
        if used >= budget:
            return False
        if x_c > usable_x:
            return True
        # Drape along the upper surface so a 125 mm panel does not chord
        # through the camber and show on the lower skin.
        n_c = 5
        xs = np.linspace(x_c - 0.5 * side, x_c + 0.5 * side, n_c)
        y0, y1 = y_c - 0.5 * side, y_c + 0.5 * side
        zs = [z_camber + _upper_surface_z(af, chord, x - x_le, offset=0.012)
              for x in xs]
        for i in range(n_c - 1):
            quad = np.array([
                [xs[i], y0, zs[i]],
                [xs[i + 1], y0, zs[i + 1]],
                [xs[i + 1], y1, zs[i + 1]],
                [xs[i], y1, zs[i]],
            ])
            quads.append(_rotate_y(quad, inc, rx, rz))
        used += 1
        return True

    y_b = 0.5 * design.boom_spacing
    y_tip = 0.5 * design.span_m
    # Inboard, then each outboard boom→tip. No H-stab cells.
    n_in = int(np.floor(design.boom_spacing / pitch))
    y0_in = -y_b
    c_in = design.chord_m
    rows_in = int(np.floor(c_in / pitch))
    x0 = 0.0
    for col in range(n_in):
        y = y0_in + (col + 0.5) * pitch
        if abs(y) + 0.5 * side > y_b:
            continue
        for row in range(rows_in):
            if not add_cell(x0 + (row + 0.5) * pitch, y, c_in, i_w,
                            0.0, 0.0, c_in, af_w, 0.0, 0.0):
                return quads
    for sign in (-1.0, 1.0):
        n_out = int(np.floor(max(y_tip - y_b, 0.0) / pitch))
        for col in range(n_out):
            y = sign * (y_b + (col + 0.5) * pitch)
            y_edge = sign * (y_b + (col + 1) * pitch)
            c_loc = design.chord_at_y(y_edge)
            frac = 1.0
            if (not design.cells_on_aileron()
                    and abs(y_edge) >= design.aileron_y_inner() - 1e-9):
                frac = max(0.0, 1.0 - config.AILERON_CHORD_FRAC)
            rows = int(np.floor(c_loc * frac / pitch))
            if rows < 1:
                continue
            usable_x = c_loc * frac
            for row in range(rows):
                if not add_cell(x0 + (row + 0.5) * pitch, y, usable_x, i_w,
                                0.0, 0.0, c_loc, af_w, 0.0, 0.0):
                    return quads
    return quads


def _disk_tris(center, normal, radius, n=28) -> tuple[np.ndarray, np.ndarray]:
    c = np.asarray(center, dtype=float)
    nrm = np.asarray(normal, dtype=float)
    nrm = nrm / np.linalg.norm(nrm)
    tmp = np.array([0.0, 1.0, 0.0]) if abs(nrm[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(nrm, tmp)
    u /= np.linalg.norm(u)
    v = np.cross(nrm, u)
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = c + radius * (np.cos(th)[:, None] * u + np.sin(th)[:, None] * v)
    pts = np.vstack([c, ring])
    faces = np.array([[0, i, i + 1] for i in range(1, n)] + [[0, n, 1]], dtype=int)
    return pts, faces


def mesh_props(design: Design) -> tuple[np.ndarray, np.ndarray]:
    r = 0.5 * design.prop_diameter_in * IN_TO_M
    yb = 0.5 * design.boom_spacing
    meshes = []
    for y in (-yb, yb):
        meshes.append(_disk_tris([design.prop_x, y, 0.0], [1.0, 0.0, 0.0], r))
    return _stack(meshes)


def mesh_cells(design: Design) -> tuple[np.ndarray, np.ndarray]:
    meshes = []
    for q in _cell_quads(design):
        meshes.append((q, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)))
    return _stack(meshes) if meshes else (np.zeros((0, 3)), np.zeros((0, 3), dtype=int))


def _stack(meshes: list[tuple[np.ndarray, np.ndarray]]):
    pts, faces = meshes[0]
    for p, f in meshes[1:]:
        faces = np.vstack([faces, f + len(pts)])
        pts = np.vstack([pts, p])
    return pts, faces


def write_stl(path: Path, points: np.ndarray, faces: np.ndarray,
              name: str = "solar-uav") -> Path:
    faces = _triangulate(faces)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(len(faces))
    header = name.encode("ascii", "replace")[:80].ljust(80, b"\0")
    with path.open("wb") as f:
        f.write(header)
        f.write(struct.pack("<I", n))
        for i0, i1, i2 in faces:
            v0, v1, v2 = points[i0], points[i1], points[i2]
            nrm = np.cross(v1 - v0, v2 - v0)
            ln = np.linalg.norm(nrm)
            nrm = nrm / ln if ln > 1e-12 else np.array([0.0, 0.0, 1.0])
            f.write(struct.pack("<3f", *nrm))
            f.write(struct.pack("<3f", *v0))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<H", 0))
    return path


def _airfoil_pts(name: str, n: int = 48) -> np.ndarray:
    import aerosandbox as asb
    coords = np.asarray(asb.Airfoil(name).coordinates, dtype=float)
    # downsample while keeping LE/TE
    if len(coords) <= n:
        return coords
    idx = np.linspace(0, len(coords) - 1, n).astype(int)
    return coords[idx]


def write_scad(design: Design, path: Path) -> Path:
    """OpenSCAD: extruded airfoils, boom tubes, pods, prop disks."""
    af_w = _airfoil_pts(design.wing_airfoil)
    af_t = _airfoil_pts("naca0010")

    def poly(coords) -> str:
        pts = ", ".join(f"[{x:.5f}, {y:.5f}]" for x, y in coords)
        return f"[{pts}]"

    yb = 0.5 * design.boom_spacing
    y_tap = design.y_taper_m
    y_tip = 0.5 * design.span_m
    c_r = design.chord_m
    c_t = design.tip_chord_m
    x_h = design.hstab_le_x()
    z_h = design.hstab_z
    r_boom = 0.5 * BOOM_DIAMETER_M
    r_prop = 0.5 * design.prop_diameter_in * IN_TO_M
    r_fuse = design.fuselage_wetted_each_m2 / max(
        2.0 * np.pi * design.fuselage_length_m, 1e-6)
    x_prop = design.prop_x
    x_boom0 = design.boom_x_front
    x_vte = design.vstab_te_x
    x_wing_te = design.chord_m
    L_fuse = design.fuselage_length_m
    i_w = design.wing_incidence_deg()
    i_t = design.hstab_incidence_deg()
    boom_h = x_vte - x_boom0
    scad = f"""// Split-empennage solar UAV — generated from solar_uav.cad
// Units: metres. Open in OpenSCAD (F6 to render).
// Two identical T-tails (no π-bridge, no H-stab solar). Props {config.PROP_LE_OFFSET_M*1000:.0f} mm ahead of wing LE.
// Incidence from NeuralFoil: wing {i_w:.2f} deg, H-stab {i_t:.2f} deg (booms at α≈0).
$fn = 32;

module airfoil_sec(y, chord, pts) {{
    translate([0, y, 0])
        rotate([90, 0, 90])
            linear_extrude(height=0.002, center=true)
                scale([chord, chord]) polygon(points=pts);
}}

module wing_planform(pts) {{
    // Rectangular carry-through (LE unswept), then optional outboard taper.
    if (abs({y_tap:.4f} - {y_tip:.4f}) < 0.02) {{
        rotate([90, 0, 90])
            linear_extrude(height={design.span_m:.4f}, center=true)
                scale([{c_r:.4f}, {c_r:.4f}]) polygon(points=pts);
    }} else {{
        rotate([90, 0, 90])
            linear_extrude(height={2.0 * y_tap:.4f}, center=true)
                scale([{c_r:.4f}, {c_r:.4f}]) polygon(points=pts);
        for (s = [-1, 1]) {{
            hull() {{
                airfoil_sec(s*{y_tap:.4f}, {c_r:.4f}, pts);
                airfoil_sec(s*{y_tip:.4f}, {c_t:.4f}, pts);
            }}
        }}
    }}
}}

module naca_tail(span, chord, pts) {{
    rotate([90, 0, 90])
        linear_extrude(height=span, center=true)
            scale([chord, chord]) polygon(points=pts);
}}

module nacelle(y) {{
    translate([{x_prop:.4f}, y, 0])
        rotate([0, 90, 0])
            hull() {{
                sphere(r=0.010);
                translate([0, 0, {0.12 * (x_wing_te - x_prop):.4f}])
                    sphere(r={r_fuse:.4f});
                translate([0, 0, {L_fuse:.4f}])
                    sphere(r={0.55 * r_fuse:.4f});
            }}
}}

color([0.82, 0.84, 0.86])
    rotate([0, {i_w:.4f}, 0])
        wing_planform({poly(af_w)});

for (s = [-1, 1]) {{
    translate([{x_h:.4f}, s*{yb:.4f}, {z_h:.4f}])
        rotate([0, {i_t:.4f}, 0])
            color([0.75, 0.78, 0.80])
                naca_tail({design.hstab_span:.4f}, {design.hstab_chord:.4f}, {poly(af_t)});
    translate([{x_h:.4f}, s*{yb:.4f}, 0])
        rotate([90, 0, 90])
            linear_extrude(height={design.vstab_height:.4f})
                scale([{design.vstab_chord:.4f}, {design.vstab_chord:.4f}])
                    polygon(points={poly(af_t)});
    color([0.15, 0.15, 0.16])
        translate([{x_boom0:.4f}, s*{yb:.4f}, 0])
            rotate([0, 90, 0])
                cylinder(h={boom_h:.4f}, r={r_boom:.4f});
    color([0.22, 0.24, 0.26]) nacelle(s*{yb:.4f});
    color([0.25, 0.25, 0.28, 0.35])
        translate([{x_prop:.4f}, s*{yb:.4f}, 0])
            rotate([0, 90, 0])
                cylinder(h=0.004, r={r_prop:.4f});
}}
"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scad)
    return path


def write_html(design: Design, path: Path,
               structure: tuple[np.ndarray, np.ndarray],
               cells: tuple[np.ndarray, np.ndarray],
               props: tuple[np.ndarray, np.ndarray]) -> Path:
    """Self-contained Three.js orbit viewer with the mesh embedded as STL-b64."""
    import tempfile
    chunks = {}
    for key, mesh in (("structure", structure), ("cells", cells), ("props", props)):
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        write_stl(tmp_path, mesh[0], mesh[1], name=key)
        chunks[key] = base64.b64encode(tmp_path.read_bytes()).decode("ascii")
        tmp_path.unlink(missing_ok=True)
    dims = design.dimension_report()
    mb = {k: float(v) for k, v in dims.get("mass_breakdown_kg", {}).items()}
    dims["mass_breakdown_kg"] = mb
    dims["fixed_breakdown_kg"] = {k: float(v) for k, v in config.FIXED_MASSES_KG.items()}
    html = _HTML_TEMPLATE.replace("__STRUCT_B64__", chunks["structure"])
    html = html.replace("__CELLS_B64__", chunks["cells"])
    html = html.replace("__PROPS_B64__", chunks["props"])
    html = html.replace("__DIMS_JSON__", json.dumps(dims, indent=2))
    html = html.replace("__TITLE__", (
        f"Split-empennage solar UAV  {design.span_m:.2f} m × {design.chord_m:.2f} m  "
        f"({design.n_cells} cells)"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path


def write_mass_png(design: Design, path: Path) -> Path:
    """Horizontal bar mass breakdown for the airplane being visualized."""
    mb = {k: float(v) for k, v in design.mass_breakdown().items()}
    items = sorted(mb.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(mb.values()) or 1.0
    labels = [k.replace("_", " ") for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    y = np.arange(len(items))
    ax.barh(y, vals, color="#8ab4f8", height=0.72)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("kg")
    ax.set_xlim(0, (max(vals) * 1.28) if vals else 1)
    ax.set_title(f"Mass breakdown — {total:.2f} kg")
    for yi, v in zip(y, vals):
        ax.text(v + 0.03, yi, f"{v:.2f}  {100 * v / total:.0f}%",
                va="center", fontsize=8, color="#3c4043")
    ax.grid(True, axis="x", lw=0.4, alpha=0.4)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def three_view(design: Design, structure, cells, path: Path) -> Path:
    pts, faces = structure
    tris = pts[faces]
    fig = plt.figure(figsize=(11.5, 9.5))
    views = [
        (221, "Top", 0, 1, "x [m] aft", "y [m] span"),
        (222, "Front", 1, 2, "y [m] span", "z [m] up"),
        (223, "Side", 0, 2, "x [m] aft", "z [m] up"),
    ]
    for slot, title, i, j, xl, yl in views:
        ax = fig.add_subplot(slot)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.fill(tris[:, :, i].T, tris[:, :, j].T,
                facecolor="#c8ccd0", edgecolor="#6b7076", linewidth=0.15, alpha=0.9)
        if cells[0].size:
            ct = cells[0][cells[1]]
            ax.fill(ct[:, :, i].T, ct[:, :, j].T,
                    facecolor="#3d6d99", edgecolor="#2a4d6e", linewidth=0.2, alpha=0.85)
        ax.grid(True, lw=0.3, alpha=0.4)
    ax3 = fig.add_subplot(224, projection="3d")
    coll = Poly3DCollection(tris, facecolor="#c8ccd0", edgecolor="#6b7076",
                            linewidth=0.08, alpha=0.92)
    ax3.add_collection3d(coll)
    if cells[0].size:
        ax3.add_collection3d(Poly3DCollection(
            cells[0][cells[1]], facecolor="#3d6d99", edgecolor="#2a4d6e",
            linewidth=0.1, alpha=0.9))
    span = max(pts.max(axis=0) - pts.min(axis=0))
    mid = 0.5 * (pts.max(axis=0) + pts.min(axis=0))
    ax3.set_xlim(mid[0] - 0.55 * span, mid[0] + 0.55 * span)
    ax3.set_ylim(mid[1] - 0.55 * span, mid[1] + 0.55 * span)
    ax3.set_zlim(mid[2] - 0.55 * span, mid[2] + 0.55 * span)
    ax3.set_xlabel("x [m]")
    ax3.set_ylabel("y [m]")
    ax3.set_zlabel("z [m]")
    ax3.view_init(elev=22, azim=-60)
    ax3.set_title("Isometric")
    fig.suptitle(
        f"Split empennage  {design.span_m:.2f}×{design.chord_m:.2f} m  "
        f"λ={design.taper_ratio:.2f}  {design.string_plan_label()}  "
        f"AR {design.aspect_ratio:.1f}  {design.mass_kg:.2f} kg",
        fontsize=11)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def export_all(design: Design | None = None,
               out_dir: Path | None = None) -> dict:
    d = design or reference_design()
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parents[1] / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    structure = mesh_structure(d)
    cells = mesh_cells(d)
    props = mesh_props(d)
    all_pts, all_faces = _stack([structure, cells, props])
    paths = {
        "stl": write_stl(out / "aircraft.stl", all_pts, all_faces),
        "stl_structure": write_stl(out / "aircraft_structure.stl", *structure),
        "scad": write_scad(d, out / "aircraft.scad"),
        "html": write_html(d, out / "aircraft_viewer.html", structure, cells, props),
        "three_view": three_view(d, structure, cells, out / "aircraft_three_view.png"),
        "mass": write_mass_png(d, out / "aircraft_mass.png"),
        "dims": out / "aircraft_dimensions.json",
    }
    report = d.dimension_report()
    report["mass_breakdown_kg"] = {k: float(v) for k, v in report["mass_breakdown_kg"].items()}
    paths["dims"].write_text(json.dumps(report, indent=2))
    return {k: str(v) for k, v in paths.items()}


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>__TITLE__</title>
<style>
  html, body { margin: 0; height: 100%; background: #1b1d21; color: #e8eaed;
               font-family: ui-sans-serif, system-ui, sans-serif; }
  #c { display: block; width: 100%; height: 100%; }
  #hud { position: absolute; top: 16px; left: 16px; max-width: 340px;
         background: #25282e; border: 1px solid #3a3f46; padding: 12px 14px;
         font-size: 12px; line-height: 1.45; }
  #hud h1 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
  #hud table { border-collapse: collapse; width: 100%; }
  #hud td { padding: 1px 6px 1px 0; color: #c4c7cc; }
  #hud td.v { text-align: right; color: #f1f3f4; font-variant-numeric: tabular-nums; }
  #mass { position: absolute; top: 16px; right: 16px; width: 280px;
         background: #25282e; border: 1px solid #3a3f46; padding: 12px 14px;
         font-size: 12px; line-height: 1.4; max-height: calc(100% - 48px);
         overflow: auto; }
  #mass h1 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
  #mass .row { display: grid; grid-template-columns: 92px 1fr 70px;
               gap: 6px; align-items: center; margin: 3px 0; }
  #mass .row.sub { grid-template-columns: 92px 1fr 70px; padding-left: 8px;
                   color: #9aa0a6; font-size: 11px; }
  #mass .lab { color: #c4c7cc; overflow: hidden; text-overflow: ellipsis; }
  #mass .bar { height: 8px; background: #1b1d21; border: 1px solid #3a3f46; }
  #mass .bar > i { display: block; height: 100%; background: #8ab4f8; }
  #mass .row.sub .bar > i { background: #5f7a9b; }
  #mass .kg { text-align: right; color: #f1f3f4; font-variant-numeric: tabular-nums; }
  #hint { position: absolute; bottom: 12px; right: 16px; color: #9aa0a6; font-size: 11px; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud">
  <h1>__TITLE__</h1>
  <table id="dims"></table>
</div>
<div id="mass">
  <h1 id="mass-title">Mass</h1>
  <div id="mass-rows"></div>
</div>
<div id="hint">drag to orbit · scroll to zoom · right-drag to pan</div>
<script type="importmap">
{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js",
            "three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const DIMS = __DIMS_JSON__;
const rows = [
  ["Span", DIMS.span_m.toFixed(2) + " m"],
  ["Chord root / tip", DIMS.chord_m.toFixed(2) + " / " + (DIMS.tip_chord_m || DIMS.chord_m).toFixed(2) + " m"],
  ["Taper start", (DIMS.y_taper_m || 0).toFixed(2) + " m from CL"],
  ["Wing area / AR", DIMS.wing_area_m2.toFixed(2) + " m² / " + DIMS.aspect_ratio.toFixed(1)],
  ["Tail arm", DIMS.tail_arm_m.toFixed(2) + " m"],
  ["Motor", DIMS.motor_name || ""],
  ["Prop", (DIMS.prop_name || "") + "  " + (DIMS.prop_diameter_in || 0).toFixed(1) + " in"],
  ["H-stab (each)", DIMS.hstab_span_m.toFixed(2) + " × " + DIMS.hstab_chord_m.toFixed(2) + " m  (2 T-tails)"],
  ["V_H / SM", (DIMS.tail_volume_h || 0).toFixed(3) + " / " + (DIMS.static_margin || 0).toFixed(3)],
  ["V_V / Cn_β (not constrained)", (DIMS.tail_volume_v || 0).toFixed(3) + " / " + (DIMS.cn_beta || 0).toFixed(3)],
  ["Boom spacing", DIMS.boom_spacing_m.toFixed(2) + " m"],
  ["Boom (wing TE→V-stab TE)", DIMS.boom_length_m.toFixed(2) + " m"],
  ["Fuselage (prop→wing TE)", (DIMS.fuselage_length_m || 0).toFixed(2) + " m"],
  ["Prop ahead of LE", DIMS.prop_le_offset_m.toFixed(2) + " m"],
  ["V-stab", DIMS.vstab_height_m.toFixed(2) + " × " + DIMS.vstab_chord_m.toFixed(2) + " m"],
  ["Aileron y_in / span", (DIMS.aileron_y_inner_m || 0).toFixed(2) + " / " + (DIMS.aileron_span_each_m || 0).toFixed(2) + " m"],
  ["Roll rate", (DIMS.roll_rate_deg_s || 0).toFixed(1) + " deg/s"],
  ["H-stab height", DIMS.hstab_z_m.toFixed(2) + " m (on fin tips, no π-bridge)"],
  ["Wing incidence", (DIMS.incidence_wing_deg || 0).toFixed(2) + " deg"],
  ["H-stab incidence", (DIMS.incidence_hstab_deg || 0).toFixed(2) + " deg"],
  ["Cells", (DIMS.string_plan || (DIMS.n_strings + " × " + DIMS.cells_per_string)) + " = " + DIMS.n_cells],
  ["Packs", String(DIMS.n_packs)],
  ["Mass", DIMS.mass_kg.toFixed(2) + " kg"],
  ["Vstall / Vmin", DIMS.v_stall_ms.toFixed(1) + " / " + DIMS.v_min_ms.toFixed(1) + " m/s"],
];
document.getElementById("dims").innerHTML = rows.map(
  ([k,v]) => `<tr><td>${k}</td><td class="v">${v}</td></tr>`).join("");

(function renderMass() {
  const mb = DIMS.mass_breakdown_kg || {};
  const fixed = DIMS.fixed_breakdown_kg || {};
  const items = Object.entries(mb).sort((a, b) => b[1] - a[1]);
  const total = items.reduce((s, [, v]) => s + v, 0) || 1;
  const max = items.length ? items[0][1] : 1;
  document.getElementById("mass-title").textContent =
    "Mass  " + total.toFixed(2) + " kg";
  const label = (k) => k.replace(/_/g, " ");
  const row = (k, v, sub) => {
    const pct = 100 * v / total;
    const w = 100 * v / max;
    return `<div class="row${sub ? " sub" : ""}">
      <div class="lab">${label(k)}</div>
      <div class="bar"><i style="width:${w.toFixed(1)}%"></i></div>
      <div class="kg">${v.toFixed(2)} ${pct.toFixed(0)}%</div>
    </div>`;
  };
  let html = items.map(([k, v]) => row(k, v, false)).join("");
  const fixedItems = Object.entries(fixed).sort((a, b) => b[1] - a[1]);
  if (fixedItems.length) {
    html += `<div style="margin:8px 0 4px;color:#9aa0a6;font-size:11px">fixed (includes fuselages)</div>`;
    html += fixedItems.map(([k, v]) => row(k, v, true)).join("");
  }
  document.getElementById("mass-rows").innerHTML = html;
})();

function parseSTL(b64) {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const n = new DataView(bin.buffer).getUint32(80, true);
  const pos = new Float32Array(n * 9);
  let o = 84, p = 0;
  for (let i = 0; i < n; i++) {
    o += 12; // skip normal
    for (let k = 0; k < 9; k++, p++, o += 4) pos[p] = new DataView(bin.buffer).getFloat32(o, true);
    o += 2;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return g;
}

const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1d21);
const camera = new THREE.PerspectiveCamera(40, 2, 0.05, 40);
camera.up.set(0, 1, 0);
camera.position.set(1.2, 5.5, 4.2);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0.25, 0.12, 0);
controls.update();

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 0.85);
key.position.set(2, 6, 4);
scene.add(key);
const fill = new THREE.DirectionalLight(0x88aacc, 0.35);
fill.position.set(-4, 1, -2);
scene.add(fill);

const grid = new THREE.GridHelper(8, 16, 0x3a3f46, 0x2a2e34);
grid.position.y = -0.45;
scene.add(grid);

// AeroSandbox / aircraft axes: x aft, y span, z up. Three.js y is up, so remap.
function acToThree(geom) {
  const m = new THREE.Matrix4().set(
    1,0,0,0,
    0,0,1,0,
    0,1,0,0,
    0,0,0,1
  );
  geom.applyMatrix4(m);
  return geom;
}

const struct = new THREE.Mesh(
  acToThree(parseSTL("__STRUCT_B64__")),
  new THREE.MeshStandardMaterial({ color: 0xc8ccd0, metalness: 0.05, roughness: 0.55 })
);
scene.add(struct);
const cells = new THREE.Mesh(
  acToThree(parseSTL("__CELLS_B64__")),
  new THREE.MeshStandardMaterial({
    color: 0x2f5f8a, metalness: 0.2, roughness: 0.4,
    side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2
  })
);
scene.add(cells);
const props = new THREE.Mesh(
  acToThree(parseSTL("__PROPS_B64__")),
  new THREE.MeshStandardMaterial({ color: 0x4a4e54, metalness: 0.1, roughness: 0.7, transparent: true, opacity: 0.45, side: THREE.DoubleSide })
);
scene.add(props);

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function tick() {
  resize();
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
tick();
</script>
</body>
</html>
"""
