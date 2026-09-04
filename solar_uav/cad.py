"""Simple CAD of the twin-boom reference airframe.

Builds an AeroSandbox solid (wing, H-stab in the wing plane, V-stabs further
aft, pods, booms), plus solar-cell patches and tractor prop disks. Exports:

  * binary STL (structure mesh)
  * simple-geometry STEP (boxes / tubes, millimetres)
  * OpenSCAD source (lofted airfoils + cylinders)
  * self-contained AircraftView HTML (3D + specs + energy + planform)
  * annotated matplotlib three-view
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
from .aircraft import (BOOM_DIAMETER_M, Design, G,
                       reference_design)
from .components import solar_array
from .step_export import write_step

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
    af_t = asb.Airfoil("naca0010")
    quads = []
    used = 0
    budget = design.n_cells
    i_w = design.wing_incidence_deg()
    i_t = design.hstab_incidence_deg()

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
    # Inboard, then each outboard boom→tip, then H-stab.
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
    bay = design.solar_bays()["hstab"]
    x_h = design.hstab_le_x()
    usable = bay.chord_m * bay.usable_chord_frac
    y0 = -0.5 * design.hstab_span
    z_h = design.hstab_z
    c_h = design.hstab_chord
    for col in range(bay.cols):
        y = y0 + (col + 0.5) * pitch
        if y + 0.5 * side > -y0:
            continue
        x = x_h + 0.03 * c_h + 0.5 * side
        if not add_cell(x, y, x_h + usable, i_t, x_h, z_h, c_h, af_t, x_h, z_h):
            break
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
    x_v = design.vstab_le_x()
    z_v_lo = design.vstab_z_lo
    z_v_hi = design.vstab_z_hi
    z_h = design.hstab_z
    r_boom = 0.5 * BOOM_DIAMETER_M
    r_prop = 0.5 * design.prop_diameter_in * IN_TO_M
    r_fuse = design.fuselage_wetted_each_m2 / max(
        2.0 * np.pi * design.fuselage_length_m, 1e-6)
    x_prop = design.prop_x
    x_c4 = design.boom_x_front
    x_vte = design.vstab_te_x
    x_wing_te = design.chord_m
    L_fuse = design.fuselage_length_m
    i_w = design.wing_incidence_deg()
    i_t = design.hstab_incidence_deg()
    boom_h = x_vte - x_c4
    scad = f"""// Twin-boom solar UAV — generated from solar_uav.cad
// Units: metres. Open in OpenSCAD (F6 to render).
// Independent tails: H-stab in the wing plane, V-stabs straddle the boom.
// Boom: wing c/4 → V-stab root TE. Props {config.PROP_LE_OFFSET_M*1000:.0f} mm ahead of wing LE.
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

module vfin_sec(x, z, chord, pts) {{
    // Thin airfoil slice in the X–Y plane at height z (chord along x).
    translate([x, 0, z])
        linear_extrude(height=0.002, center=true)
            scale([chord, chord]) polygon(points=pts);
}}

module vstab_fin(pts) {{
    hull() {{
        vfin_sec(0, {z_v_lo:.4f}, {design.vstab_chord:.4f}, pts);
        vfin_sec(0, {z_v_hi:.4f}, {design.vstab_chord:.4f}, pts);
    }}
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

translate([{x_h:.4f}, 0, {z_h:.4f}])
    rotate([0, {i_t:.4f}, 0])
        color([0.75, 0.78, 0.80])
            naca_tail({design.hstab_span:.4f}, {design.hstab_chord:.4f}, {poly(af_t)});

for (s = [-1, 1]) {{
    translate([{x_v:.4f}, s*{yb:.4f}, 0])
        color([0.75, 0.78, 0.80])
            vstab_fin({poly(af_t)});
    color([0.15, 0.15, 0.16])
        translate([{x_c4:.4f}, s*{yb:.4f}, 0])
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


def _clock_hod(hod: float) -> str:
    """Local clock `HH:MM` from a fractional hour-of-day."""
    h = float(hod) % 24.0
    hh = int(np.floor(h + 1e-9))
    mm = int(round((h - hh) * 60.0))
    if mm >= 60:
        hh, mm = (hh + 1) % 24, 0
    return f"{hh:02d}:{mm:02d}"


def _soc_setpoints(r, e_tot: float) -> list[dict]:
    """Launch / dawn / 20% floor / next-dusk charge states for the HUD card."""
    soc = np.asarray(r.soc_trace, dtype=float)
    hours = np.asarray(r.hours, dtype=float)
    if soc.size == 0:
        return []
    i_min = int(np.argmin(soc))
    hod_min = (float(r.start_hour) + float(hours[i_min])) % 24.0
    floor = float(config.SOC_MIN)
    start_h = float(r.start_hour)
    return [
        {"id": "launch", "label": "Launch (full)",
         "clock": _clock_hod(start_h), "soc": 1.0, "wh": e_tot,
         "note": "ground charge"},
        {"id": "dawn", "label": "Dawn (min)",
         "clock": _clock_hod(hod_min), "soc": float(r.soc_min),
         "wh": float(r.soc_min) * e_tot, "note": "worst point"},
        {"id": "floor", "label": "20% floor",
         "clock": "", "soc": floor, "wh": floor * e_tot,
         "note": "must stay above"},
        {"id": "dusk", "label": "Next dusk",
         "clock": _clock_hod(start_h), "soc": float(r.soc_end),
         "wh": float(r.soc_end) * e_tot, "note": "loop end"},
    ]


def mission_snapshot(design: Design) -> dict:
    """24 h energy march on this airplane, for the CAD HUD. Empty if no prop."""
    if not design.prop_name:
        return {}
    from . import environment
    from .components.motor import drive_for
    from .components.propulsion import PropulsionSystem, load_prop
    from .mission import display_trace, simulate
    try:
        psys = PropulsionSystem(
            prop=load_prop(design.prop_name),
            motor=drive_for(design.motor_name))
        env = environment.design_day(config.SOLSTICE_DATE)
        r = simulate(design, env, psys)
        tr = display_trace(design, env, psys, start_hod=8.0, duration_h=60.0)
    except Exception:
        return {}
    e_tot = float(design.n_packs * config.PACK_ENERGY_WH)
    from .viewer_data import attach_traces
    snap = {
        "margin_wh": float(r.margin_wh),
        "reserve_wh": float((r.soc_min - config.SOC_MIN) * e_tot),
        "cycle_wh": float(r.cycle_wh),
        "soc_min": float(r.soc_min),
        "soc_start": float(r.soc_start),
        "soc_end": float(r.soc_end),
        "unmet_wh": float(r.unmet_wh),
        "spilled_wh": float(r.spilled_wh),
        "solar_wh": float(r.solar_wh),
        "propulsion_wh": float(r.propulsion_wh),
        "avionics_wh": float(r.avionics_wh),
        "p_night_w": float(r.p_night_w),
        "p_day_w": float(r.p_day_w),
        "closed": bool(r.closed),
        "pack_wh": e_tot,
        "usable_wh": e_tot * (1.0 - config.SOC_MIN),
        "reason": str(r.reason),
        "climb_ms": float(r.climb_ms),
        "battery_night_h": float(r.battery_night_h),
        "v_night_ms": float(r.v_night),
        "soc_floor": float(config.SOC_MIN),
        "start_clock": _clock_hod(r.start_hour),
        "setpoints": _soc_setpoints(r, e_tot),
    }
    return attach_traces(snap, tr if tr is not None else r)


def drag_snapshot(design: Design, v_ms: float | None = None) -> dict:
    """Night-cruise drag budget for the CAD HUD. Same V as the energy march."""
    v = float(design.min_power_speed() if v_ms is None else v_ms)
    b = design.drag_breakdown(v_ms=v)
    d_tot = float(b["drag_total_n"])
    m = float(b["mass_kg"])
    return {
        "v_ms": float(b["v_ms"]),
        "rho": float(b["rho"]),
        "q_pa": float(b["q_pa"]),
        "mass_kg": m,
        "cl_net": float(b["cl_net"]),
        "cl_wing": float(b["cl_wing"]),
        "cl_hstab": float(b["cl_hstab"]),
        "cd_wingref": float(b["cd_wingref"]),
        "ld": float(m * G / max(d_tot, 1e-12)),
        "drag_total_n": d_tot,
        "power_aero_w": float(b["power_aero_w"]),
        "re_wing": float(b["re_wing"]),
        "parts_n": {k: float(val) for k, val in b["drag_n"].items()},
    }


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


def write_html(design: Design, path: Path,
               structure: tuple[np.ndarray, np.ndarray],
               cells: tuple[np.ndarray, np.ndarray],
               props: tuple[np.ndarray, np.ndarray],
               energy: dict | None = None,
               drag: dict | None = None) -> Path:
    """Self-contained AircraftView HTML (Three.js + tabs). Meshes as STL-b64."""
    import tempfile
    from .viewer_data import payload as viewer_payload
    chunks = {}
    for key, mesh in (("structure", structure), ("cells", cells), ("props", props)):
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        write_stl(tmp_path, mesh[0], mesh[1], name=key)
        chunks[key] = base64.b64encode(tmp_path.read_bytes()).decode("ascii")
        tmp_path.unlink(missing_ok=True)
    energy = energy if energy is not None else mission_snapshot(design)
    drag = drag if drag is not None else drag_snapshot(design)
    data = viewer_payload(design, energy, drag)
    title = data["title"]
    template = Path(__file__).with_name("aircraft_view.html").read_text(encoding="utf-8")
    html = (template
            .replace("__TITLE__", title)
            .replace("__PAYLOAD_JSON__", json.dumps(
                data, separators=(",", ":"), default=_json_default))
            .replace("__STRUCT_B64__", chunks["structure"])
            .replace("__CELLS_B64__", chunks["cells"])
            .replace("__PROPS_B64__", chunks["props"]))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
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
        f"{design.span_m:.2f}×{design.chord_m:.2f} m  "
        f"λ={design.taper_ratio:.2f}  H {design.tail_arm_m:.2f}/V {design.vstab_root_arm_m:.2f} m  "
        f"{design.string_plan_label()}  "
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
    energy = mission_snapshot(d)
    v_night = energy.get("v_night_ms")
    drag = drag_snapshot(d, v_ms=v_night)
    paths = {
        "stl": write_stl(out / "aircraft.stl", all_pts, all_faces),
        "stl_structure": write_stl(out / "aircraft_structure.stl", *structure),
        "step": write_step(d, out / "aircraft.step"),
        "scad": write_scad(d, out / "aircraft.scad"),
        "html": write_html(d, out / "aircraft_viewer.html", structure, cells, props,
                           energy=energy, drag=drag),
        "three_view": three_view(d, structure, cells, out / "aircraft_three_view.png"),
        "mass": write_mass_png(d, out / "aircraft_mass.png"),
        "dims": out / "aircraft_dimensions.json",
    }
    report = d.dimension_report()
    report["mass_breakdown_kg"] = {k: float(v) for k, v in report["mass_breakdown_kg"].items()}
    report["fixed_breakdown_kg"] = {k: float(v) for k, v in config.FIXED_MASSES_KG.items()}
    report["energy"] = energy
    report["drag"] = drag
    paths["dims"].write_text(json.dumps(report, indent=2))
    return {k: str(v) for k, v in paths.items()}
