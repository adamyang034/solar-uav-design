"""JSON payload for the AircraftView HTML export.

Built from the live Design so the viewer always matches REF / CAD, not a
stale optimizer CSV.
"""

from __future__ import annotations

import math

import numpy as np

from . import config
from .aircraft import Design, RHO_NIGHT


def _ds(arr, n: int = 160) -> list[float]:
    a = np.asarray(arr, dtype=float).ravel()
    if a.size == 0:
        return []
    if a.size <= n:
        return [float(x) for x in a]
    idx = np.linspace(0, a.size - 1, n).astype(int)
    return [float(a[i]) for i in idx]


def _fmt(v, spec: str = ".3f", suffix: str = "") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    try:
        return f"{float(v):{spec}}{suffix}"
    except (TypeError, ValueError):
        return f"{v}{suffix}"


def _box_mp(mass: float, lx: float, ly: float, lz: float,
            x: float, y: float, z: float) -> dict:
    m = float(mass)
    return {
        "mass": m,
        "x_cg": float(x), "y_cg": float(y), "z_cg": float(z),
        "Ixx": m / 12.0 * (ly * ly + lz * lz),
        "Iyy": m / 12.0 * (lx * lx + lz * lz),
        "Izz": m / 12.0 * (lx * lx + ly * ly),
        "Ixy": 0.0, "Iyz": 0.0, "Ixz": 0.0,
    }


def _sph_mp(mass: float, r: float, x: float, y: float, z: float) -> dict:
    m = float(mass)
    i = 0.4 * m * r * r
    return {
        "mass": m,
        "x_cg": float(x), "y_cg": float(y), "z_cg": float(z),
        "Ixx": i, "Iyy": i, "Izz": i,
        "Ixy": 0.0, "Iyz": 0.0, "Ixz": 0.0,
    }


def combine_total(components: dict) -> dict:
    m = mx = my = mz = 0.0
    for c in components.values():
        m += c["mass"]
        mx += c["mass"] * c["x_cg"]
        my += c["mass"] * c["y_cg"]
        mz += c["mass"] * c["z_cg"]
    x = mx / m if m else 0.0
    y = my / m if m else 0.0
    z = mz / m if m else 0.0
    Ixx = Iyy = Izz = Ixy = Iyz = Ixz = 0.0
    for c in components.values():
        Rx, Ry, Rz = x - c["x_cg"], y - c["y_cg"], z - c["z_cg"]
        rr = Rx * Rx + Ry * Ry + Rz * Rz
        Ixx += c["Ixx"] + c["mass"] * (rr - Rx * Rx)
        Iyy += c["Iyy"] + c["mass"] * (rr - Ry * Ry)
        Izz += c["Izz"] + c["mass"] * (rr - Rz * Rz)
        Ixy += c["Ixy"] - c["mass"] * Rx * Ry
        Iyz += c["Iyz"] - c["mass"] * Ry * Rz
        Ixz += c["Ixz"] - c["mass"] * Rz * Rx
    return {
        "mass": m, "x_cg": x, "y_cg": y, "z_cg": z,
        "Ixx": Ixx, "Iyy": Iyy, "Izz": Izz,
        "Ixy": Ixy, "Iyz": Iyz, "Ixz": Ixz,
    }


def mass_model(design: Design) -> dict:
    """Named CAD lumps. Same stations as asb_physics.component_inertia.

    Packs / motors / avionics are draggable in the viewer; structure is not.
    Batteries and fixed mass are split (the scoring inertia lumps them).
    """
    mb = design.mass_breakdown()
    c = float(design.chord_m)
    mac = float(design.mac_m)
    b = float(design.span_m)
    x_c4 = 0.25 * mac
    x_h = float(design.hstab_le_x() + 0.25 * design.hstab_chord)
    x_v = float(0.25 * mac + design.vstab_arm_m)
    z_h = float(design.hstab_z)
    y_b = 0.5 * float(design.boom_spacing)
    x_prop = float(design.prop_x)
    x_vte = float(design.vstab_te_x)
    x_main_c = 0.5 * (float(design.boom_x_front) + x_vte)
    L_main = float(design.boom_length)
    t_w = 0.10 * c
    t_t = 0.10 * float(design.hstab_chord)
    fuse_r = (design.fuselage_wetted_each_m2
              / (2.0 * math.pi * max(design.fuselage_length_m, 1e-6)))

    components: dict[str, dict] = {}
    positions: dict[str, dict] = {}

    def add(name, cat, mp, kind, size, draggable):
        components[name] = mp
        positions[name] = {
            "xyz": [mp["x_cg"], mp["y_cg"], mp["z_cg"]],
            "kind": kind,
            "size": size,
            "draggable": draggable,
            "category": cat,
        }

    add("Wing", "structure",
        _box_mp(mb["wing"], c, b, t_w, 0.40 * c, 0.0, 0.0),
        "box", [c, b, t_w], False)
    add("Solar cells", "solar",
        _box_mp(mb["solar_cells"], c * 0.9, b * 0.7, 0.004, 0.40 * c, 0.0, 0.02),
        "box", [c * 0.5, b * 0.4, 0.004], False)
    n_m = max(1, int(design.n_mppts))
    m_each = mb["mppts"] / n_m
    y_mp = (np.linspace(-0.35 * b, 0.35 * b, n_m)
            if n_m > 1 else np.array([0.0]))
    for i, y in enumerate(y_mp):
        label = "MPPT" if n_m == 1 else f"MPPT {i + 1}"
        add(label, "avionics",
            _box_mp(m_each, 0.06, 0.08, 0.025, 0.18 * c, float(y), -0.03),
            "box", [0.06, 0.08, 0.025], True)
    add("H-stab", "structure",
        _box_mp(mb["hstab"], design.hstab_chord, design.hstab_span, t_t, x_h, 0.0, z_h),
        "box", [design.hstab_chord, design.hstab_span, t_t], False)
    add("V-stab L", "structure",
        _box_mp(0.5 * mb["vstabs"], design.vstab_chord, t_t, design.vstab_height,
                x_v, -y_b, 0.0),
        "box", [design.vstab_chord, t_t, design.vstab_height], False)
    add("V-stab R", "structure",
        _box_mp(0.5 * mb["vstabs"], design.vstab_chord, t_t, design.vstab_height,
                x_v, y_b, 0.0),
        "box", [design.vstab_chord, t_t, design.vstab_height], False)
    add("Boom L", "structure",
        _box_mp(0.5 * mb["booms"], L_main, config.BOOM_DIAMETER_M, config.BOOM_DIAMETER_M,
                x_main_c, -y_b, 0.0),
        "cylinder", [L_main, config.BOOM_DIAMETER_M], False)
    add("Boom R", "structure",
        _box_mp(0.5 * mb["booms"], L_main, config.BOOM_DIAMETER_M, config.BOOM_DIAMETER_M,
                x_main_c, y_b, 0.0),
        "cylinder", [L_main, config.BOOM_DIAMETER_M], False)
    add("Motor L", "propulsion",
        _sph_mp(0.5 * mb["motors"], 0.04, x_prop, -y_b, 0.0),
        "sphere", [0.04], True)
    add("Motor R", "propulsion",
        _sph_mp(0.5 * mb["motors"], 0.04, x_prop, y_b, 0.0),
        "sphere", [0.04], True)
    add("Prop L", "propulsion",
        _sph_mp(0.5 * mb["props"], 0.15, x_prop, -y_b, 0.0),
        "disk", [0.5 * design.prop_diameter_in * 0.0254], False)
    add("Prop R", "propulsion",
        _sph_mp(0.5 * mb["props"], 0.15, x_prop, y_b, 0.0),
        "disk", [0.5 * design.prop_diameter_in * 0.0254], False)
    n_p = max(1, int(design.n_packs))
    p_each = mb["batteries"] / n_p
    if n_p == 1:
        pack_ys, pack_names = [0.0], ["Pack"]
    elif n_p == 2:
        pack_ys, pack_names = [-y_b, y_b], ["Pack L", "Pack R"]
    elif n_p == 3:
        pack_ys, pack_names = [-y_b, 0.0, y_b], ["Pack L", "Pack C", "Pack R"]
    else:
        pack_ys = list(np.linspace(-y_b, y_b, n_p))
        pack_names = [f"Pack {i + 1}" for i in range(n_p)]
    for name, y in zip(pack_names, pack_ys):
        add(name, "battery",
            _box_mp(p_each, 0.20 * c, 0.08, 0.08, x_c4, float(y), 0.0),
            "box", [0.20 * c, 0.08, 0.08], True)
    add("Avionics L", "avionics",
        _box_mp(0.5 * mb["fixed"], 0.16, 2 * fuse_r, 2 * fuse_r,
                design.boom_x_front - 0.25 * design.fuselage_length_m, -y_b, 0.0),
        "box", [0.16, 2 * fuse_r, 2 * fuse_r], True)
    add("Avionics R", "avionics",
        _box_mp(0.5 * mb["fixed"], 0.16, 2 * fuse_r, 2 * fuse_r,
                design.boom_x_front - 0.25 * design.fuselage_length_m, y_b, 0.0),
        "box", [0.16, 2 * fuse_r, 2 * fuse_r], True)

    total = combine_total(components)
    return {
        "components": components,
        "positions": positions,
        "total": total,
        "x_c4": x_c4,
        "breakdown": {k: float(v) for k, v in mb.items()},
        "fixed_breakdown": {k: float(v) for k, v in config.FIXED_MASSES_KG.items()},
    }


def _section(title: str, rows: list) -> dict:
    return {"title": title, "rows": [[a, b] for a, b in rows if b not in (None, "")]}


def specs(design: Design, energy: dict, drag: dict, mass: dict) -> list[dict]:
    d = design
    e = energy or {}
    dr = drag or {}
    tot = mass["total"]
    mot = config.MOTOR_CATALOG.get(d.motor_name)
    cell = config.C60_BINS[config.CELL_BIN_DEFAULT]
    env_rho = RHO_NIGHT
    return [
        {"id": "overview", "label": "Overview", "sections": [
            _section("Mission", [
                ["Site", "El Mirage Race Course"],
                ["Latitude", _fmt(config.LATITUDE_DEG, ".6f", "°")],
                ["Longitude", _fmt(config.LONGITUDE_DEG, ".6f", "°")],
                ["Field elevation", _fmt(config.SITE_ALTITUDE_M, ".0f", " m MSL")],
                ["Cruise altitude", _fmt(config.CRUISE_ALT_AGL_M, ".0f", " m AGL")],
                ["Design day", str(config.SOLSTICE_DATE) + " (solstice Ineichen)"],
                ["Mission window", f"{config.MISSION_WINDOW[0]} – {config.MISSION_WINDOW[1]}"],
                ["Scored duration", _fmt(config.DESIGN_MISSION_HOURS, ".0f", " h")],
            ]),
            _section("This airplane", [
                ["Planform", f"{d.span_m:.2f} × {d.chord_m:.3f} m  λ={d.taper_ratio:.2f}"],
                ["Cells / strings", f"{d.n_cells}   {d.string_plan_label()}"],
                ["Packs", f"{d.n_packs} × {config.PACK_ENERGY_WH:.0f} Wh"],
                ["Propulsion", f"{d.motor_name}  ·  {d.prop_name}"],
                ["Mass", _fmt(d.mass_kg, ".3f", " kg")],
                ["Day-2", ("CLOSED  +" if e.get("closed") else "OPEN  ")
                 + _fmt(e.get("margin_wh"), ".1f", " Wh")],
                ["SOC min", _fmt(100.0 * float(e.get("soc_min") or 0), ".1f", "%")],
            ]),
            _section("Night point", [
                ["Airspeed", _fmt(dr.get("v_ms"), ".2f", " m/s")],
                ["Density", _fmt(dr.get("rho") or env_rho, ".3f", " kg/m³")],
                ["L/D", _fmt(dr.get("ld"), ".1f")],
                ["Drag", _fmt(dr.get("drag_total_n"), ".2f", " N")],
                ["Aero power", _fmt(dr.get("power_aero_w"), ".1f", " W")],
                ["Night bus", _fmt(e.get("p_night_w"), ".1f", " W")],
                ["Climb (rate check)", _fmt(e.get("climb_ms"), ".1f", " m/s")],
            ]),
        ]},
        {"id": "geometry", "label": "Geometry & Mass", "sections": [
            _section("Wing", [
                ["Span", _fmt(d.span_m, ".3f", " m")],
                ["Root / tip chord", f"{d.chord_m:.3f} / {d.tip_chord_m:.3f} m"],
                ["Area / AR", f"{d.wing_area:.3f} m²  /  {d.aspect_ratio:.1f}"],
                ["Airfoil", d.wing_airfoil],
                ["Incidence", _fmt(d.wing_incidence_deg(), ".2f", "°")],
                ["Taper start", _fmt(d.y_taper_m, ".2f", " m from CL")],
                ["Aileron", f"y={d.aileron_y_inner():.2f}–{d.aileron_y_tip_m():.2f} m  "
                 f"({d.aileron_span_each_m():.2f} m each, {config.AILERON_CHORD_FRAC:.0%} c)"],
                ["Cells on aileron span", "yes (upper skin)" if d.cells_on_aileron() else "keep-out"],
                ["Roll rate", _fmt(d.roll_rate_deg_s(), ".1f", " °/s")],
            ]),
            _section("Tails & booms", [
                ["H-stab", f"{d.hstab_span:.3f} × {d.hstab_chord:.3f} m"],
                ["H-arm / incidence", f"{d.tail_arm_m:.2f} m  /  {d.hstab_incidence_deg():.2f}°"],
                ["V-stab each", f"{d.vstab_height:.3f} × {d.vstab_chord:.3f} m  AR {d.vstab_ar:.2f}"],
                ["V-arm", _fmt(d.vstab_root_arm_m, ".2f", " m")],
                ["V-stab z", f"{d.vstab_z_lo:.3f} to {d.vstab_z_hi:.3f} m"
                 + ("  (straddle)" if config.VSTAB_STRADDLE else "")],
                ["V_V / Cn_β", f"{d.tail_volume_v_actual():.3f}  /  {d.cn_beta():.3f}"],
                ["Boom", f"{d.boom_length:.3f} m  Ø{config.BOOM_DIAMETER_M*1000:.1f} mm  "
                 f"y=±{0.5*d.boom_spacing:.2f} m"],
                ["Fuselage", _fmt(d.fuselage_length_m, ".3f", " m")],
            ]),
            _section("Mass properties (CAD lumps)", [
                ["Total", _fmt(tot["mass"], ".3f", " kg")],
                ["CG x (from LE)", _fmt(tot["x_cg"], ".3f", " m")],
                ["Wing c/4", _fmt(mass["x_c4"], ".3f", " m")],
                ["CG − c/4", _fmt(tot["x_cg"] - mass["x_c4"], ".3f", " m")],
                ["Static margin (tail volume)", _fmt(d.static_margin(), ".3f")],
                ["Ixx / Iyy / Izz", f"{tot['Ixx']:.2f}  /  {tot['Iyy']:.2f}  /  {tot['Izz']:.2f} kg·m²"],
            ]),
        ]},
        {"id": "power", "label": "Power", "sections": [
            _section("Energy march (day 2)", [
                ["Closed", "yes" if e.get("closed") else "no"],
                ["Margin above 20%", _fmt(e.get("margin_wh"), ".1f", " Wh")],
                ["SOC min / start / end",
                 f"{_fmt(100*float(e.get('soc_min') or 0), '.1f')} / "
                 f"{_fmt(100*float(e.get('soc_start') or 0), '.1f')} / "
                 f"{_fmt(100*float(e.get('soc_end') or 0), '.1f')} %"],
                ["Cycle", _fmt(e.get("cycle_wh"), ".2f", " Wh")],
                ["Solar / propulsion / avionics",
                 f"{_fmt(e.get('solar_wh'), '.0f')} / {_fmt(e.get('propulsion_wh'), '.0f')} / "
                 f"{_fmt(e.get('avionics_wh'), '.0f')} Wh"],
                ["Spilled / unmet",
                 f"{_fmt(e.get('spilled_wh'), '.1f')} / {_fmt(e.get('unmet_wh'), '.1f')} Wh"],
                ["Pack / usable (80%)",
                 f"{_fmt(e.get('pack_wh'), '.0f')} / {_fmt(e.get('usable_wh'), '.0f')} Wh"],
                ["Battery-true night", _fmt(e.get("battery_night_h"), ".2f", " h")],
                ["Launch clock", e.get("start_clock") or "—"],
            ]),
            _section("Array", [
                ["Cells", f"{d.n_cells}  bin {config.CELL_BIN_DEFAULT}  {cell.efficiency*100:.1f}% STC"],
                ["Pmp / cell", _fmt(cell.p_mp_w, ".2f", " W")],
                ["Strings", d.string_plan_label()],
                ["MPPTs", f"{d.n_mppts} × {config.MPPT_MASS_KG:.3f} kg"],
                ["Encaps / wiring-soiling",
                 f"{config.ENCAPSULATION_TRANSMISSION:.3f}  /  {config.WIRING_MISMATCH_SOILING_EFF:.3f}"],
            ]),
            _section("Propulsion", [
                ["Motor", mot.name if mot else d.motor_name],
                ["Kv / Ri / I0", (f"{mot.kv_rpm_per_v:.0f} rpm/V  ·  {mot.r_ohm:.3f} Ω  ·  "
                                  f"{mot.i0_a:.2f} A" if mot else "—")],
                ["Prop", f"{d.prop_name}  {d.prop_diameter_in:.1f} in"],
                ["ESC η (model)", _fmt(config.ESC_EFFICIENCY, ".2f")],
                ["Night bus / day bus",
                 f"{_fmt(e.get('p_night_w'), '.1f')} / {_fmt(e.get('p_day_w'), '.1f')} W"],
            ]),
            _section("Night drag", [
                ["Total / L/D", f"{_fmt(dr.get('drag_total_n'), '.2f', ' N')}  /  {_fmt(dr.get('ld'), '.1f')}"],
                ["CL net / wing / H-stab",
                 f"{_fmt(dr.get('cl_net'), '.3f')}  /  {_fmt(dr.get('cl_wing'), '.3f')}  /  "
                 f"{_fmt(dr.get('cl_hstab'), '.3f')}"],
                ["CD on S", _fmt(dr.get("cd_wingref"), ".4f")],
                ["Re MAC", _fmt((dr.get("re_wing") or 0) / 1e5, ".2f", "×10⁵")],
            ] + [[k.replace("_", " "), _fmt(v, ".2f", " N")]
                 for k, v in (dr.get("parts_n") or {}).items()]),
        ]},
    ]


def airfoils(design: Design) -> list[dict]:
    import aerosandbox as asb
    out = []
    for surface, name in (("Wing", design.wing_airfoil),
                          ("H-stab / V-stab", "naca0010")):
        af = asb.Airfoil(name)
        coords = np.asarray(af.coordinates, dtype=float)
        out.append({
            "surface": surface,
            "name": name,
            "coords": [[float(x), float(y)] for x, y in coords],
        })
    return out


def cell_rects(design: Design) -> list[dict]:
    hinge = (1.0 - config.AILERON_CHORD_FRAC) * float(design.chord_m)
    y_ail = float(design.aileron_y_inner())
    rows = []
    for c in design.cell_placements():
        ymid = 0.5 * (c.y0 + c.y1)
        straddle = (c.bay != "hstab"
                    and abs(ymid) >= y_ail - 1e-9
                    and c.x0 < hinge < c.x1)
        rows.append({
            "bay": c.bay,
            "x0": c.x0, "x1": c.x1, "y0": c.y0, "y1": c.y1,
            "straddle": bool(straddle),
        })
    return rows


def attach_traces(energy: dict, result) -> dict:
    """Add downsampled day-2 traces onto a mission_snapshot dict."""
    if not energy or result is None:
        return energy
    hours = np.asarray(result.hours, dtype=float).ravel()
    if hours.size == 0:
        return energy
    n = min(160, hours.size)
    idx = np.linspace(0, hours.size - 1, n).astype(int)
    e_tot = float(energy.get("pack_wh") or 1.0)
    soc = np.asarray(result.soc_trace, dtype=float).ravel()
    energy = dict(energy)
    energy["hours"] = [float(hours[i]) for i in idx]
    energy["soc"] = [float(soc[i]) for i in idx] if soc.size == hours.size else _ds(soc, n)
    energy["wh"] = [s * e_tot for s in energy["soc"]]
    ps = np.asarray(result.p_solar, dtype=float).ravel()
    pl = np.asarray(result.p_load, dtype=float).ravel()
    energy["p_solar"] = [float(ps[i]) for i in idx] if ps.size == hours.size else _ds(ps, n)
    energy["p_load"] = [float(pl[i]) for i in idx] if pl.size == hours.size else _ds(pl, n)
    return energy


def payload(design: Design, energy: dict, drag: dict) -> dict:
    mass = mass_model(design)
    dims = dict(design.dimension_report())
    dims["fuselage_radius_m"] = (
        design.fuselage_wetted_each_m2
        / (2.0 * math.pi * max(design.fuselage_length_m, 1e-6)))
    dims["hstab_le_x_m"] = float(design.hstab_le_x())
    return {
        "title": (f"AircraftView  {design.span_m:.2f}×{design.chord_m:.2f} m  "
                  f"{design.n_cells} cells  {design.mass_kg:.2f} kg"),
        "name": f"{design.span_m:.2f}×{design.chord_m:.2f} m  {design.string_plan_label()}",
        "dims": dims,
        "energy": energy,
        "drag": drag,
        "mass": mass,
        "specs": specs(design, energy, drag, mass),
        "airfoils": airfoils(design),
        "cells": cell_rects(design),
        "colors": {
            "structure": "#9aa3ad",
            "solar": "#3d6d99",
            "battery": "#4a90e2",
            "propulsion": "#e67e22",
            "avionics": "#9b59b6",
        },
    }
