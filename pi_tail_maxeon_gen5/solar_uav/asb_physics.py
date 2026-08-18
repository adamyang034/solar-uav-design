"""AeroSandbox analyses used as conservative checks on the handbook model.

Production scoring still owns the polar. These tools may only *hurt*
night watts or S&C (stronger downwash, lower e, larger inertia, larger
|Cl_p|, smaller Cn_β, weaker |Cn_r|, higher section cd). A friendlier
AeroSandbox number is discarded.

Do not import this module from aircraft.py at module load — VLM / CAD
paths lazy-import Design helpers and would cycle.
"""

from __future__ import annotations

from functools import lru_cache
from shutil import which

import aerosandbox as asb
import numpy as np

from . import config

# ---------------------------------------------------------------------------
# Atmosphere (always on — cheap, replaces the one-line ISA)
# ---------------------------------------------------------------------------
FLIGHT_ALT_MSL_M = config.SITE_ALTITUDE_M + config.CRUISE_ALT_AGL_M


def cruise_atmosphere(t_amb_c: float | np.ndarray) -> asb.Atmosphere:
    """ISA pressure at field + 400 ft AGL, with the design-day temperature."""
    t_k = np.asarray(t_amb_c, dtype=float) + 273.15
    t_isa = float(asb.Atmosphere(altitude=FLIGHT_ALT_MSL_M, method="isa").temperature())
    return asb.Atmosphere(
        altitude=FLIGHT_ALT_MSL_M,
        method="isa",
        temperature_deviation=t_k - t_isa,
    )


def air_density(t_amb_c: float | np.ndarray) -> float | np.ndarray:
    rho = cruise_atmosphere(t_amb_c).density()
    arr = np.asarray(rho, dtype=float)
    if np.ndim(t_amb_c) == 0:
        return float(arr)
    return arr


def dynamic_viscosity(t_amb_c: float | np.ndarray) -> float | np.ndarray:
    mu = cruise_atmosphere(t_amb_c).dynamic_viscosity()
    arr = np.asarray(mu, dtype=float)
    if np.ndim(t_amb_c) == 0:
        return float(arr)
    return arr


def _f(x) -> float:
    return float(np.asarray(x, dtype=float).reshape(-1)[0])


def _night_op_point(velocity_ms: float) -> asb.OperatingPoint:
    t = config.T_AMB_MIN_C + 2.0
    return asb.OperatingPoint(
        atmosphere=cruise_atmosphere(t),
        velocity=float(velocity_ms),
        alpha=0.0,
    )


def _geom_key(design) -> tuple:
    return (
        round(float(design.span_m), 3),
        round(float(design.chord_m), 4),
        round(float(design.tail_arm_m), 3),
        round(float(design.vstab_arm_m), 3),
        round(float(design.vstab_ar), 2),
        round(float(design.hstab_z), 3),
        round(float(design.boom_spacing), 3),
        round(float(design.taper_ratio), 3),
        round(float(design.taper_start_frac), 3),
        round(float(design.washout_tip_deg), 2),
        round(float(design.washout_start_frac), 2),
        round(float(design.elevator_frac), 3),
        round(float(design.mass_kg), 3),
    )


def _handbook_airplane(design):
    """Airplane jigged at handbook incidence so VLM cannot recurse."""
    i_w, i_t = design._handbook_incidence_deg()
    return design.to_asb(incidence=(i_w, i_t))


def _wing_only(ac: asb.Airplane, design) -> asb.Airplane:
    return asb.Airplane(
        name="wing-only",
        xyz_ref=ac.xyz_ref,
        wings=[ac.wings[0]],
        s_ref=float(design.wing_area),
        c_ref=float(design.mac_m),
        b_ref=float(design.span_m),
    )


# ---------------------------------------------------------------------------
# VLM: induced e and tail downwash (wing-only; do not sample inside the H-stab)
# ---------------------------------------------------------------------------
_VLM_CACHE: dict[tuple, dict] = {}


def vlm_cruise(design) -> dict | None:
    """Wing-only VLM at boom-α ≈ 0 (handbook jig). None if the solver fails."""
    if not config.ASB_VLM_IN_SCORING:
        return None
    key = _geom_key(design)
    cached = _VLM_CACHE.get(key)
    if cached is not None:
        return cached if cached else None
    try:
        ac = _handbook_airplane(design)
        ac_w = _wing_only(ac, design)
        v = float(design.min_airspeed())
        vlm = asb.VortexLatticeMethod(
            airplane=ac_w,
            op_point=_night_op_point(v),
            spanwise_resolution=8,
            chordwise_resolution=5,
            verbose=False,
        )
        aero = vlm.run()
        cl = _f(aero["CL"])
        cd = _f(aero["CD"])
        ar = float(design.aspect_ratio)
        e = cl ** 2 / (np.pi * ar * max(cd, 1e-9)) if cl > 0.05 else None
        x_ac = design.hstab_le_x() + 0.25 * design.hstab_chord
        z_h = float(design.hstab_z)
        ys = np.linspace(0.05, max(0.06, 0.45 * design.hstab_span), 7)
        pts = np.column_stack([np.full_like(ys, x_ac), ys, np.full_like(ys, z_h)])
        vi = vlm.get_induced_velocity_at_points(pts)
        w_z = float(np.mean(vi[:, 2]))  # geometry +z up
        # Positive ε = downwash (flow from above). w_z < 0 is downward induced.
        eps = float(np.arctan2(-w_z, v))
        cl_hb = 2.0 * max(cl, 1e-6) / (np.pi * ar)
        k = eps / cl_hb if cl_hb > 1e-9 else 0.0
        out = {
            "cl": cl,
            "cd": cd,
            "e": float(e) if e is not None else None,
            "eps_rad": eps,
            "w_z": w_z,
            "k_downwash": float(k),
            "ok": True,
        }
        _VLM_CACHE[key] = out
        return out
    except Exception as exc:
        _VLM_CACHE[key] = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
        }
        return None


def downwash_k(design) -> float:
    """ε_VLM / ε_handbook at the VLM CL. <1 means the π-tail sits in weaker
    downwash (T-tail credit) — production must not take that."""
    run = vlm_cruise(design)
    if not run or not run.get("ok"):
        return 1.0
    return float(run["k_downwash"])


def downwash_k_used(design) -> float:
    """≥1. Handbook unless VLM downwash at the real tail is stronger."""
    return max(1.0, downwash_k(design))


def vlm_oswald_e(design) -> float | None:
    run = vlm_cruise(design)
    if not run or not run.get("ok") or run.get("e") is None:
        return None
    e = float(run["e"])
    if not (0.35 < e < 1.05):
        return None
    return e


# ---------------------------------------------------------------------------
# AeroSandbox lifting line (audit + optional e floor)
# ---------------------------------------------------------------------------
_LL_CACHE: dict[tuple, dict] = {}


def lifting_line_cruise(design) -> dict | None:
    if not config.ASB_VLM_IN_SCORING:
        return None
    key = _geom_key(design)
    if key in _LL_CACHE:
        run = _LL_CACHE[key]
        return run if run.get("ok") else None
    try:
        ac = _handbook_airplane(design)
        ac_w = _wing_only(ac, design)
        v = float(design.min_airspeed())
        ll = asb.LiftingLine(
            airplane=ac_w,
            op_point=_night_op_point(v),
            model_size="small",
        )
        aero = ll.run()
        out = {
            "cl": _f(aero["CL"]),
            "cd": _f(aero["CD"]),
            "ok": True,
        }
        _LL_CACHE[key] = out
        return out
    except Exception as exc:
        _LL_CACHE[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return None


# ---------------------------------------------------------------------------
# AeroBuildup stability derivatives
# ---------------------------------------------------------------------------
_AB_CACHE: dict[tuple, dict] = {}


def aerobuildup_derivatives(design) -> dict | None:
    if not config.ASB_AEROBUILDUP_SC:
        return None
    key = _geom_key(design)
    if key in _AB_CACHE:
        run = _AB_CACHE[key]
        return run if run.get("ok") else None
    try:
        ac = design.to_asb()
        v = float(design.min_airspeed())
        ab = asb.AeroBuildup(
            airplane=ac,
            op_point=_night_op_point(v),
            model_size="small",
            include_wave_drag=False,
        )
        der = ab.run_with_stability_derivatives(
            alpha=True, beta=True, p=True, q=False, r=True)
        out = {
            "cl": _f(der["CL"]),
            "cd": _f(der["CD"]),
            "clp": _f(der["Clp"]),
            "cnb": _f(der["Cnb"]),
            "cnr": _f(der["Cnr"]),
            "cla": _f(der["CLa"]),
            "ok": True,
        }
        _AB_CACHE[key] = out
        return out
    except Exception as exc:
        _AB_CACHE[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return None


# ---------------------------------------------------------------------------
# Inertia: CAD-located component MassProperties (production) + thin-shell audit
# ---------------------------------------------------------------------------
_INERTIA_CACHE: dict[tuple, dict] = {}


def _place(mp: asb.MassProperties, x: float, y: float, z: float) -> asb.MassProperties:
    return asb.MassProperties(
        mass=mp.mass, x_cg=x, y_cg=y, z_cg=z,
        Ixx=mp.Ixx, Iyy=mp.Iyy, Izz=mp.Izz,
        Ixy=mp.Ixy, Iyz=mp.Iyz, Ixz=mp.Ixz,
    )


def component_inertia(design) -> dict | None:
    """asb.MassProperties for each mass lump at its CAD centroid, about c/4.

    Uses the measured masses, not area-painted skin mass. Thin-shell Iyy
    of the mesh is reported separately and is not used for scoring — it
    would put kilograms of battery on the H-stab because the stab has area.
    """
    if not config.ASB_MESH_INERTIA:
        return None
    from aerosandbox.weights import (
        MassProperties,
        mass_properties_of_rectangular_prism,
        mass_properties_of_sphere,
    )
    mb = design.mass_breakdown()
    c = float(design.chord_m)
    mac = float(design.mac_m)
    b = float(design.span_m)
    x_c4 = 0.25 * mac
    x_h = float(design.hstab_le_x() + 0.25 * design.hstab_chord)
    x_v = float(design.vstab_le_x() + 0.25 * design.vstab_chord)
    z_h = float(design.hstab_z)
    y_b = 0.5 * float(design.boom_spacing)
    x_prop = float(design.prop_x)
    x_vte = float(design.vstab_te_x)
    x_main_c = 0.5 * (float(design.boom_x_front) + x_vte)
    L_main = float(design.boom_length)
    t_w = 0.10 * c
    t_t = 0.10 * float(design.hstab_chord)

    def prism(mass, lx, ly, lz, x, y, z):
        return _place(mass_properties_of_rectangular_prism(mass, lx, ly, lz), x, y, z)

    parts = [
        prism(mb["wing"] + mb["solar_cells"] + mb["mppts"],
              c, b, t_w, 0.40 * c, 0.0, 0.0),
        prism(mb["hstab"], design.hstab_chord, design.hstab_span, t_t,
              x_h, 0.0, z_h),
        prism(0.5 * mb["vstabs"], design.vstab_chord, t_t, design.vstab_height,
              x_v, -y_b, 0.5 * design.vstab_height),
        prism(0.5 * mb["vstabs"], design.vstab_chord, t_t, design.vstab_height,
              x_v, y_b, 0.5 * design.vstab_height),
        prism(0.5 * mb["booms"], L_main, config.BOOM_DIAMETER_M, config.BOOM_DIAMETER_M,
              x_main_c, -y_b, 0.0),
        prism(0.5 * mb["booms"], L_main, config.BOOM_DIAMETER_M, config.BOOM_DIAMETER_M,
              x_main_c, y_b, 0.0),
    ]
    parts.extend([
        _place(mass_properties_of_sphere(0.5 * mb["motors"], 0.04), x_prop, -y_b, 0.0),
        _place(mass_properties_of_sphere(0.5 * mb["motors"], 0.04), x_prop, y_b, 0.0),
        _place(mass_properties_of_sphere(0.5 * mb["props"], 0.15), x_prop, -y_b, 0.0),
        _place(mass_properties_of_sphere(0.5 * mb["props"], 0.15), x_prop, y_b, 0.0),
        prism(0.5 * (mb["batteries"] + mb["fixed"]), 0.20 * c, 0.08, 0.08,
              x_c4, -y_b, 0.0),
        prism(0.5 * (mb["batteries"] + mb["fixed"]), 0.20 * c, 0.08, 0.08,
              x_c4, y_b, 0.0),
    ])
    total = sum(parts, MassProperties(mass=0.0))
    ixx, iyy, izz, ixy, iyz, ixz = total.get_inertia_tensor_about_point(
        x=x_c4, y=0.0, z=0.0, return_tensor=False)
    return {
        "ixx": float(ixx), "iyy": float(iyy), "izz": float(izz),
        "mass": float(total.mass), "ok": True, "mp": total,
    }


def mesh_inertia(design) -> dict | None:
    """Production I from CAD-located components; thin-shell kept for the audit."""
    if not config.ASB_MESH_INERTIA:
        return None
    key = _geom_key(design)
    if key in _INERTIA_CACHE:
        run = _INERTIA_CACHE[key]
        return run if run.get("ok") else None
    try:
        comp = component_inertia(design)
        shell = _thin_shell_inertia(design)
        out = {
            **comp,
            "shell_ixx": None if not shell else shell["ixx"],
            "shell_iyy": None if not shell else shell["iyy"],
            "shell_izz": None if not shell else shell["izz"],
            "ok": True,
        }
        _INERTIA_CACHE[key] = out
        return out
    except Exception as exc:
        _INERTIA_CACHE[key] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return None


def _thin_shell_inertia(design) -> dict | None:
    """Area-painted skin inertia. Audit only — not a mass model."""
    from .cad import mesh_structure
    points, faces = mesh_structure(design)
    points = np.asarray(points, dtype=float)
    faces = np.asarray(faces, dtype=int)
    p0, p1, p2 = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    centroids = (p0 + p1 + p2) / 3.0
    a_tot = float(np.sum(areas))
    if a_tot < 1e-8:
        return None
    mass = float(design.mass_kg)
    m = mass * areas / a_tot
    cg = np.array([0.25 * float(design.mac_m), 0.0, 0.0])
    r = centroids - cg
    return {
        "ixx": float(np.sum(m * (r[:, 1] ** 2 + r[:, 2] ** 2))),
        "iyy": float(np.sum(m * (r[:, 0] ** 2 + r[:, 2] ** 2))),
        "izz": float(np.sum(m * (r[:, 0] ** 2 + r[:, 1] ** 2))),
    }


# ---------------------------------------------------------------------------
# XFoil vs NeuralFoil (optional; binary often missing)
# ---------------------------------------------------------------------------
def xfoil_command() -> str | None:
    for name in ("xfoil", "xfoil.exe"):
        path = which(name)
        if path:
            return path
    return None


@lru_cache(maxsize=8)
def xfoil_vs_neuralfoil(airfoil_name: str = "s4310",
                        cl: float = 0.80,
                        re: float = 150e3) -> dict:
    """Compare XFoil cd/cm to the cached NeuralFoil polar at one (CL, Re)."""
    from .aircraft import _interp_polar
    nf = {
        "cd": float(_interp_polar(airfoil_name, cl, re, "cd")),
        "cm": float(_interp_polar(airfoil_name, cl, re, "cm")),
        "alpha_deg": float(_interp_polar(airfoil_name, cl, re, "alpha_deg")),
    }
    cmd = xfoil_command()
    if cmd is None:
        return {
            "ok": False, "reason": "xfoil binary not on PATH",
            "neuralfoil": nf, "cd_scale": 1.0,
        }
    if not config.ASB_XFOIL_CD:
        return {"ok": False, "reason": "ASB_XFOIL_CD=False",
                "neuralfoil": nf, "cd_scale": 1.0}
    try:
        xf = asb.XFoil(
            airfoil=asb.Airfoil(airfoil_name).repanel(n_points_per_side=120),
            Re=float(re),
            mach=0.0,
            xfoil_command=cmd,
            max_iter=80,
            timeout=40,
            verbose=False,
        )
        out = xf.cl(float(cl))
        cd = _f(out["CD"])
        cm = _f(out.get("CM", out.get("Cm", nf["cm"])))
        scale = max(1.0, cd / max(nf["cd"], 1e-6))
        return {
            "ok": True,
            "neuralfoil": nf,
            "xfoil": {"cd": cd, "cm": cm, "alpha_deg": _f(out.get("alpha", nf["alpha_deg"]))},
            "cd_scale": float(scale),
            "cm_more_nose_down": bool(cm < nf["cm"] - 0.005),
        }
    except Exception as exc:
        return {
            "ok": False, "reason": f"{type(exc).__name__}: {exc}",
            "neuralfoil": nf, "cd_scale": 1.0,
        }


@lru_cache(maxsize=8)
def xfoil_cd_scale(airfoil_name: str) -> float:
    """≥1. Inflate NeuralFoil cd if XFoil is draggier at cruise CL / Re."""
    scales = []
    for re in (100e3, 150e3, 200e3):
        for cl in (0.60, 0.80, 1.00):
            run = xfoil_vs_neuralfoil(airfoil_name, cl=cl, re=re)
            if run.get("ok"):
                scales.append(float(run["cd_scale"]))
    if not scales:
        return 1.0
    return float(max(scales))


# ---------------------------------------------------------------------------
# Full audit dict (script + tests)
# ---------------------------------------------------------------------------
def audit_design(design) -> dict:
    """Handbook vs AeroSandbox, and which number production keeps."""
    design.aileron_y_inner()
    vlm = vlm_cruise(design)
    ll = lifting_line_cruise(design)
    ab = aerobuildup_derivatives(design)
    iner = mesh_inertia(design)
    xf = xfoil_vs_neuralfoil(design.wing_airfoil, cl=float(design.cruise_cl()),
                             re=150e3)
    clp_hb = float(design.cl_p_handbook())
    cnb_hb = float(design.cn_beta_handbook())
    cnr_hb = float(design.cn_r_handbook())
    iyy_hb = float(design.pitch_inertia_lumped_kgm2())
    izz_hb = float(design.yaw_inertia_lumped_kgm2())
    e_hb = float(design._planform()["oswald_e"])
    k = downwash_k(design)
    e_v = vlm_oswald_e(design)
    return {
        "vlm": vlm,
        "lifting_line": ll,
        "aerobuildup": ab,
        "inertia": iner,
        "xfoil": xf,
        "handbook": {
            "clp": clp_hb, "cnb": cnb_hb, "cnr": cnr_hb,
            "iyy": iyy_hb, "izz": izz_hb, "e": e_hb,
            "eps_rad": 2.0 * float(design.cruise_cl())
            / (np.pi * float(design.aspect_ratio)),
        },
        "used": {
            "downwash_k": downwash_k_used(design),
            "oswald_e": min(e_hb, e_v) if e_v else e_hb,
            "clp": min(clp_hb, float(ab["clp"])) if ab else clp_hb,
            "cnb": min(cnb_hb, float(ab["cnb"])) if ab else cnb_hb,
            "cnr": max(cnr_hb, float(ab["cnr"])) if ab else cnr_hb,
            "cnr_control": min(cnr_hb, float(ab["cnr"])) if ab else cnr_hb,
            "iyy": max(iyy_hb, float(iner["iyy"])) if iner else iyy_hb,
            "izz": max(izz_hb, float(iner["izz"])) if iner else izz_hb,
            "cd_scale": xfoil_cd_scale(design.wing_airfoil),
        },
        "k_raw": k,
        "flags": _flags(k, e_hb, e_v, clp_hb, cnb_hb, cnr_hb, iyy_hb, izz_hb,
                        ab, iner, xf),
    }


def _flags(k, e_hb, e_v, clp_hb, cnb_hb, cnr_hb, iyy_hb, izz_hb, ab, iner, xf) -> list[str]:
    flags = []
    if k < 1.0 - 1e-6:
        flags.append(
            f"VLM downwash at the π-tail is {k:.2f}× handbook; keeping handbook "
            "(no T-tail height credit)")
    elif k > 1.0 + 1e-6:
        flags.append(f"VLM downwash is {k:.2f}× handbook; using VLM (stronger)")
    if e_v is not None and e_v < e_hb - 1e-4:
        flags.append(f"VLM e={e_v:.3f} < handbook {e_hb:.3f}; using VLM")
    if ab:
        if abs(ab["clp"]) < abs(clp_hb) - 1e-4:
            flags.append(
                f"AeroBuildup |Cl_p|={abs(ab['clp']):.3f} < handbook "
                f"{abs(clp_hb):.3f}; keeping handbook (harder roll)")
        if ab["cnb"] > cnb_hb + 1e-4:
            flags.append(
                f"AeroBuildup Cn_β={ab['cnb']:.3f} > handbook {cnb_hb:.3f}; "
                "keeping handbook (harder weathercock)")
        if abs(ab["cnr"]) > abs(cnr_hb) + 1e-4:
            flags.append(
                f"AeroBuildup |Cn_r|={abs(ab['cnr']):.3f} > handbook "
                f"{abs(cnr_hb):.3f}; stability floor keeps weaker handbook, "
                "DT yaw rate uses the stronger (harder rate)")
    if iner and iner["iyy"] > iyy_hb:
        flags.append(
            f"CAD MassProperties Iyy={iner['iyy']:.3f} > lumped {iyy_hb:.3f} kg m²; using CAD")
    if iner and iner["izz"] > izz_hb:
        flags.append(
            f"CAD MassProperties Izz={iner['izz']:.3f} > lumped {izz_hb:.3f} kg m²; using CAD")
    if iner and iner.get("shell_iyy") and iner["shell_iyy"] > iner["iyy"] * 1.5:
        flags.append(
            f"thin-shell mesh Iyy={iner['shell_iyy']:.3f} paints mass by area; "
            "not used (would put pack mass on the tail)")
    if not xf.get("ok"):
        flags.append(f"XFoil skipped ({xf.get('reason', 'unavailable')}); NeuralFoil cd unchanged")
    elif xf["cd_scale"] > 1.0 + 1e-4:
        flags.append(f"XFoil cd is {xf['cd_scale']:.3f}× NeuralFoil; inflating section cd")
    return flags
