"""Simple-geometry STEP (AP214) of the twin-boom airframe.

Boxes / tapered hexes for lifting surfaces, n-gon prisms for booms, pods,
and prop disks. Aircraft axes: +x aft, +y span, +z up; origin at wing LE.
Coordinates are millimetres so SolidWorks / Fusion import at the right size.

This is an envelope OML, not the AeroSandbox loft.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .aircraft import BOOM_DIAMETER_M, FUSELAGE_RADIUS_M, Design

IN_TO_M = 0.0254
MM = 1000.0
N_GON = 16


def _fmt(x: float) -> str:
    return f"{float(x):.8f}"


def _t_over_c(name: str, default: float = 0.10) -> float:
    try:
        import aerosandbox as asb
        coords = np.asarray(asb.Airfoil(name).coordinates, dtype=float)
        return float(max(coords[:, 1].max() - coords[:, 1].min(), default))
    except Exception:
        return default


def _rot_y(pts: np.ndarray, deg: float,
           x0: float = 0.0, z0: float = 0.0) -> np.ndarray:
    th = np.radians(deg)
    c, s = np.cos(th), np.sin(th)
    out = np.array(pts, dtype=float, copy=True)
    x = out[..., 0] - x0
    z = out[..., 2] - z0
    out[..., 0] = x0 + x * c + z * s
    out[..., 2] = z0 - x * s + z * c
    return out


def _box_faces(x0, x1, y0, y1, z0, z1) -> list[np.ndarray]:
    p = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=float)
    idx = (
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 4, 7, 3), (1, 2, 6, 5),
        (0, 1, 5, 4), (3, 7, 6, 2),
    )
    return [p[list(i)] for i in idx]


def _hex_faces(verts8: np.ndarray) -> list[np.ndarray]:
    p = np.asarray(verts8, dtype=float)
    idx = (
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 4, 7, 3), (1, 2, 6, 5),
        (0, 1, 5, 4), (3, 7, 6, 2),
    )
    return [p[list(i)] for i in idx]


def _outward(faces: list[np.ndarray]) -> list[np.ndarray]:
    pts = np.vstack(faces)
    c = pts.mean(axis=0)
    out = []
    for f in faces:
        n = np.cross(f[1] - f[0], f[2] - f[0])
        if np.dot(n, f.mean(axis=0) - c) < 0:
            f = f[::-1]
        out.append(np.asarray(f, dtype=float))
    return out


def _prism_x(x0: float, x1: float, y: float, z: float, r: float,
             n: int = N_GON) -> list[np.ndarray]:
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    ring0 = np.column_stack([np.full(n, x0), y + r * np.cos(th), z + r * np.sin(th)])
    ring1 = np.column_stack([np.full(n, x1), y + r * np.cos(th), z + r * np.sin(th)])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append(np.array([ring0[i], ring1[i], ring1[j], ring0[j]]))
    faces.append(ring0[::-1].copy())
    faces.append(ring1.copy())
    return _outward(faces)


def _solids(design: Design) -> list[tuple[str, list[np.ndarray]]]:
    d = design
    tc_w = _t_over_c(d.wing_airfoil)
    tc_t = _t_over_c("naca0010")
    y_tip = 0.5 * d.span_m
    y_tap = min(float(d.y_taper_m), y_tip)
    c_r = float(d.chord_m)
    c_t = float(d.tip_chord_m)
    t_r = tc_w * c_r
    i_w = d.wing_incidence_deg()
    i_t = d.hstab_incidence_deg()
    solids: list[tuple[str, list[np.ndarray]]] = []

    def wing_panel(y0, y1, c0, c1, name):
        t0, t1 = tc_w * c0, tc_w * c1
        verts = np.array([
            [0.0, y0, -0.5 * t0], [c0, y0, -0.5 * t0],
            [c1, y1, -0.5 * t1], [0.0, y1, -0.5 * t1],
            [0.0, y0, 0.5 * t0], [c0, y0, 0.5 * t0],
            [c1, y1, 0.5 * t1], [0.0, y1, 0.5 * t1],
        ])
        solids.append((name, _outward(_hex_faces(_rot_y(verts, i_w)))))

    if abs(y_tap - y_tip) < 0.02:
        faces = _outward(_box_faces(0.0, c_r, -y_tip, y_tip, -0.5 * t_r, 0.5 * t_r))
        solids.append(("wing", [_rot_y(f, i_w) for f in faces]))
    else:
        faces = _outward(_box_faces(0.0, c_r, -y_tap, y_tap, -0.5 * t_r, 0.5 * t_r))
        solids.append(("wing_inboard", [_rot_y(f, i_w) for f in faces]))
        wing_panel(y_tap, y_tip, c_r, c_t, "wing_R")
        wing_panel(-y_tap, -y_tip, c_r, c_t, "wing_L")

    x_h = float(d.hstab_le_x())
    z_h = float(d.hstab_z)
    c_h = float(d.hstab_chord)
    y_h = 0.5 * float(d.hstab_span)
    t_h = tc_t * c_h
    h_faces = _box_faces(x_h, x_h + c_h, -y_h, y_h, z_h - 0.5 * t_h, z_h + 0.5 * t_h)
    solids.append(("hstab", [_rot_y(f, i_t, x_h, z_h) for f in _outward(h_faces)]))

    c_v = float(d.vstab_chord)
    t_v = tc_t * c_v
    yb = 0.5 * float(d.boom_spacing)
    for name, y in (("vstab_L", -yb), ("vstab_R", yb)):
        solids.append((name, _outward(_box_faces(
            x_h, x_h + c_v, y - 0.5 * t_v, y + 0.5 * t_v,
            0.0, float(d.vstab_height)))))

    x_c4 = float(d.boom_x_front)
    x_vte = float(d.vstab_te_x)
    r_boom = 0.5 * BOOM_DIAMETER_M
    for name, y in (("boom_L", -yb), ("boom_R", yb)):
        solids.append((name, _prism_x(x_c4, x_vte, y, 0.0, r_boom)))

    x_prop = float(d.prop_x)
    x_te = float(d.chord_m)
    r_fuse = float(FUSELAGE_RADIUS_M)
    for name, y in (("pod_L", -yb), ("pod_R", yb)):
        solids.append((name, _prism_x(x_prop, x_te, y, 0.0, r_fuse)))

    dia = float(d.prop_diameter_in or 18.0)
    if d.prop_name:
        try:
            from .components.propulsion import load_prop
            dia = float(load_prop(d.prop_name).diameter_in or dia)
        except Exception:
            pass
    r_prop = 0.5 * dia * IN_TO_M
    for name, y in (("prop_L", -yb), ("prop_R", yb)):
        solids.append((name, _prism_x(x_prop, x_prop + 0.004, y, 0.0, r_prop)))
    return solids


class _Step:
    def __init__(self):
        self._n = 0
        self.lines: list[str] = []

    def emit(self, body: str) -> int:
        self._n += 1
        self.lines.append(f"#{self._n} = {body};")
        return self._n

    def point(self, x, y, z) -> int:
        return self.emit(
            f"CARTESIAN_POINT('',({_fmt(x)},{_fmt(y)},{_fmt(z)}))")

    def direction(self, x, y, z) -> int:
        n = np.array([x, y, z], dtype=float)
        ln = np.linalg.norm(n)
        n = n / ln if ln > 1e-18 else np.array([0.0, 0.0, 1.0])
        return self.emit(
            f"DIRECTION('',({_fmt(n[0])},{_fmt(n[1])},{_fmt(n[2])}))")

    def solid(self, faces: list[np.ndarray]) -> int:
        xyz_of: dict[int, np.ndarray] = {}
        point_of: dict[int, int] = {}
        vmap: dict[tuple[int, int, int], int] = {}
        emap: dict[tuple[int, int], int] = {}

        def vertex(pt) -> int:
            key = tuple(int(round(float(c) * 1e6)) for c in pt)
            if key not in vmap:
                xyz = np.asarray(pt, dtype=float)
                p = self.point(*xyz)
                v = self.emit(f"VERTEX_POINT('',#{p})")
                vmap[key] = v
                xyz_of[v] = xyz
                point_of[v] = p
            return vmap[key]

        def edge_curve(a: int, b: int) -> tuple[int, bool]:
            lo, hi, sense = (a, b, True) if a < b else (b, a, False)
            key = (lo, hi)
            if key not in emap:
                dxyz = xyz_of[hi] - xyz_of[lo]
                dr = self.direction(*dxyz)
                vec = self.emit(f"VECTOR('',#{dr},1.0)")
                line = self.emit(f"LINE('',#{point_of[lo]},#{vec})")
                emap[key] = self.emit(
                    f"EDGE_CURVE('',#{lo},#{hi},#{line},.T.)")
            return emap[key], sense

        adv = []
        for face in faces:
            ids = [vertex(p) for p in face]
            if len(set(ids)) < 3:
                continue
            oedges = []
            for i, a in enumerate(ids):
                b = ids[(i + 1) % len(ids)]
                if a == b:
                    continue
                eid, sense = edge_curve(a, b)
                flag = ".T." if sense else ".F."
                oedges.append(self.emit(
                    f"ORIENTED_EDGE('',*,*,#{eid},{flag})"))
            if len(oedges) < 3:
                continue
            loop = self.emit(
                "EDGE_LOOP('',(" + ",".join(f"#{e}" for e in oedges) + "))")
            bound = self.emit(f"FACE_OUTER_BOUND('',#{loop},.T.)")
            p0 = np.asarray(face[0], dtype=float)
            e1 = np.asarray(face[1], dtype=float) - p0
            e2 = np.asarray(face[2], dtype=float) - p0
            origin = self.point(*p0)
            ax = self.direction(*np.cross(e1, e2))
            ref = self.direction(*e1)
            plc = self.emit(f"AXIS2_PLACEMENT_3D('',#{origin},#{ax},#{ref})")
            plane = self.emit(f"PLANE('',#{plc})")
            adv.append(self.emit(
                f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)"))
        if not adv:
            raise ValueError("solid has no faces")
        shell = self.emit(
            "CLOSED_SHELL('',(" + ",".join(f"#{a}" for a in adv) + "))")
        return self.emit(f"MANIFOLD_SOLID_BREP('',#{shell})")


def write_step(design: Design, path: Path | str) -> Path:
    """Write a multi-body AP214 STEP of the simple airframe envelope."""
    solids = _solids(design)
    doc = _Step()
    app = doc.emit("APPLICATION_CONTEXT('automotive design')")
    doc.emit(
        "APPLICATION_PROTOCOL_DEFINITION('international standard',"
        f"'automotive_design',2010,#{app})")
    pctx = doc.emit(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    pdctx = doc.emit(
        f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    prod = doc.emit(
        "PRODUCT('aircraft','solar UAV simple OML','twin-boom envelope',"
        f"(#{pctx}))")
    form = doc.emit(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdef = doc.emit(f"PRODUCT_DEFINITION('design','',#{form},#{pdctx})")
    pshape = doc.emit(f"PRODUCT_DEFINITION_SHAPE('','',#{pdef})")

    si = doc.emit("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    plane_a = doc.emit("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    solid_a = doc.emit("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = doc.emit(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-3),#{si},"
        f"'distance_accuracy_value','')")
    ctx = doc.emit(
        "( GEOMETRIC_REPRESENTATION_CONTEXT(3) "
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{si},#{plane_a},#{solid_a})) "
        "REPRESENTATION_CONTEXT('Context #1','3D') )")

    breps = []
    for _name, faces in solids:
        mm_faces = [np.asarray(f, dtype=float) * MM for f in faces]
        breps.append(doc.solid(mm_faces))
    shape = doc.emit(
        "ADVANCED_BREP_SHAPE_REPRESENTATION('',("
        + ",".join(f"#{b}" for b in breps)
        + f"),#{ctx})")
    doc.emit(f"SHAPE_DEFINITION_REPRESENTATION(#{pshape},#{shape})")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('solar UAV simple OML'),'2;1');\n"
        f"FILE_NAME('{path.name}','{stamp}',('solar_uav'),('solar_uav'),"
        f"'solar_uav.step_export','','');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    path.write_text(
        header + "\n".join(doc.lines) + "\nENDSEC;\nEND-ISO-10303-21;\n",
        encoding="ascii")
    return path
