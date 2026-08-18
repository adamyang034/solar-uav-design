"""Phase 3 — Aircraft coupling model.

Ties geometry, mass, and aerodynamics together for the split-empennage
twin-fuselage configuration (fork of the π-tail optimizer):

  * S4310 wing, three pieces: rectangular inboard bay between the booms + two
    outboard panels. Outboards may taper, starting at any station along the
    panel (LE unswept). Cells only occupy columns whose local chord still
    fits an integer pitch. No cells on the tails.
  * Two identical fuselage pods, each with its own T-tail (NACA 0010 H-stab
    + NACA 0010 V-stab). H-stabs do not bridge the booms.
  * carbon booms from wing TE (aft of each fuselage pod) to V-stab TE,
  * fuselage pods from wing TE to the prop disk (CAD-scaled wetted area),
  * mass buildup from measured areal densities + fixed avionics masses,
  * drag polar: NeuralFoil profile drag + induced + parasite + tail load
    from incidence trim (no lumped TRIM_DRAG fudge),
  * wing/H-stab incidence from NeuralFoil α(CL) and CM(CL) so the booms
    fly at ~0° at night cruise and the tail trims with elevator ≈ 0,
  * longitudinal checks: static margin with CG at quarter chord, elevator
    trim and pitch-acceleration vs elevator chord fraction,
    * lateral: aileron + split-elevator elevon roll rate. No yaw
    constraint (fins are structural T-tail posts; no rudder, no
    dihedral credit).
  * AeroSandbox geometry including incidence as WingXSec.twist and
    control surfaces.

Everything vectorizes over airspeed for the mission model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import aerosandbox as asb
import numpy as np
import pandas as pd

from aerosandbox.library.aerodynamics.inviscid import oswalds_efficiency
from aerosandbox.library.aerodynamics.components import CDA_control_surface_gaps
from scipy.optimize import minimize_scalar

from . import config
from . import lifting_line
from .asb_physics import air_density, dynamic_viscosity
from .components import airfoils, solar_array
from .components.propeller import estimate_prop_mass_kg

# ---------------------------------------------------------------------------
# Atmosphere at the mission site (ISA at field + 400 ft AGL, AeroSandbox)
# ---------------------------------------------------------------------------
G = 9.80665

RHO_NIGHT = float(air_density(config.T_AMB_MIN_C + 2.0))
RHO_DAY = float(air_density(config.T_AMB_MAX_C - 4.0))
RHO_MEAN = float(air_density(0.5 * (config.T_AMB_MIN_C + config.T_AMB_MAX_C)))
MU_AIR = float(dynamic_viscosity(config.T_AMB_MIN_C + 2.0))

# ---------------------------------------------------------------------------
# Buildup factors (FLAGGED)
# ---------------------------------------------------------------------------
WETTED_FACTOR = 2.05          # wetted/planform for ~10% thick sections
OSWALD_E = 0.90               # FLAGGED: rectangular calibration; taper scales this
CLMAX_3D_FACTOR = 0.90        # 3D/2D CLmax knockdown
PARASITE_INTERFERENCE = 1.10  # interference/misc on pods+booms
POD_FORM_FACTOR = 1.25
BOOM_DIAMETER_M = config.BOOM_DIAMETER_M
TRIM_DRAG_FACTOR = 1.00       # residual after incidence trim; glide-test hook
# Constant-section radius implied by the CAD Swet at L_ref (lateral 2πrL).
FUSELAGE_RADIUS_M = (
    config.FUSELAGE_WETTED_REF_M2
    / (2.0 * np.pi * config.FUSELAGE_LENGTH_REF_M)
)


@lru_cache(maxsize=None)
def _polar_table(airfoil_name: str) -> pd.DataFrame:
    df = airfoils.generate_all()
    return df[df["airfoil"].str.lower() == airfoil_name.lower()].copy()


@lru_cache(maxsize=None)
def _polar_branches(airfoil_name: str):
    """Increasing-CL pre-stall branches of (cl, cd, alpha, cm) per Re.

    NeuralFoil polars are not monotonic in CL at negative alpha, so we
    take the branch from CL_min to CL_max before interpolating.
    """
    df = _polar_table(airfoil_name)
    res = np.sort(df["re"].unique())
    cl_list, cd_list, al_list, cm_list = [], [], [], []
    for r in res:
        g = df[df["re"] == r].sort_values("alpha_deg")
        cl = g["cl"].to_numpy()
        cd = g["cd"].to_numpy()
        al = g["alpha_deg"].to_numpy()
        cm = g["cm"].to_numpy()
        i_min = int(np.argmin(cl))
        i_max = int(np.argmax(cl))
        if i_max <= i_min:
            i_min, i_max = 0, len(cl) - 1
        sl = slice(i_min, i_max + 1)
        cl_b, cd_b, al_b, cm_b = cl[sl], cd[sl], al[sl], cm[sl]
        order = np.argsort(cl_b)
        cl_b, cd_b, al_b, cm_b = (
            cl_b[order], cd_b[order], al_b[order], cm_b[order])
        _, uniq = np.unique(cl_b, return_index=True)
        cl_list.append(cl_b[uniq])
        cd_list.append(cd_b[uniq])
        al_list.append(al_b[uniq])
        cm_list.append(cm_b[uniq])
    return res, tuple(cl_list), tuple(cd_list), tuple(al_list), tuple(cm_list)


def _interp_polar(airfoil_name: str, cl, re, col: str):
    """Interpolate a polar column vs CL, then vs log Re."""
    res, cl_tbl, cd_tbl, al_tbl, cm_tbl = _polar_branches(airfoil_name)
    y_tbl = {"cd": cd_tbl, "alpha_deg": al_tbl, "cm": cm_tbl}[col]
    cl = np.atleast_1d(np.asarray(cl, dtype=float))
    re = np.broadcast_to(np.atleast_1d(np.asarray(re, dtype=float)), cl.shape)
    y_by_re = np.vstack([
        np.interp(cl, cl_tbl[i], y_tbl[i],
                  left=y_tbl[i][0], right=y_tbl[i][-1])
        for i in range(len(res))
    ])
    logres = np.log(res)
    logre = np.log(np.clip(re, res[0], res[-1]))
    out = np.empty_like(cl)
    for j in range(cl.size):
        out.flat[j] = np.interp(logre.flat[j], logres, y_by_re[:, j])
    return out if cl.size > 1 else float(out[0])


def profile_cd(airfoil_name: str, cl, re):
    """cd(cl, Re) from the cached NeuralFoil polar (pre-stall branch).

    Inflated by XFoil if the binary is present and draggier; never deflated.
    """
    cd = _interp_polar(airfoil_name, cl, re, "cd")
    if not config.ASB_XFOIL_CD:
        return cd
    from .asb_physics import xfoil_cd_scale
    return cd * xfoil_cd_scale(airfoil_name)


def alpha_deg_at_cl(airfoil_name: str, cl, re):
    """2D geometric alpha [deg] that produces `cl` on the NeuralFoil polar."""
    return _interp_polar(airfoil_name, cl, re, "alpha_deg")


def cm_at_cl(airfoil_name: str, cl, re):
    """Section CM about c/4 at `cl` (NeuralFoil)."""
    return _interp_polar(airfoil_name, cl, re, "cm")


@lru_cache(maxsize=None)
def clmax_2d(airfoil_name: str, re: float = 150e3) -> float:
    res, cl_tbl, _, _, _ = _polar_branches(airfoil_name)
    i = int(np.argmin(np.abs(res - re)))
    return float(cl_tbl[i].max())


def _cf_turbulent(re) -> np.ndarray:
    return 0.074 / np.maximum(np.asarray(re, dtype=float), 1e4) ** 0.2


def flap_tau(cf_over_c: float) -> float:
    """Empirical flap effectiveness. FLAGGED: sqrt(cf/c), same as elevator."""
    return float(np.sqrt(np.clip(cf_over_c, 0.05, 0.6)))


def reference_design(**kwargs) -> Design:
    """Phase 4 best-so-far planform used for Phase 5/6 and the CAD visualizer."""
    fields = dict(
        span_m=config.REF_SPAN_M,
        chord_m=config.REF_CHORD_M,
        tail_arm_m=config.REF_TAIL_ARM_M,
        n_packs=config.REF_N_PACKS,
        cells_per_string=None,
        n_strings=None,
        elevator_frac=config.REF_ELEVATOR_FRAC,
        taper_ratio=config.REF_TAPER_RATIO,
        taper_start_frac=config.REF_TAPER_START_FRAC,
        boom_spacing_set_m=config.REF_BOOM_SPACING_M,
        one_string_per_bay=config.REF_ONE_STRING_PER_BAY,
        prop_diameter_in=21.0,
        prop_name=config.REF_PROP,
        motor_name=config.REF_MOTOR,
    )
    fields.update(kwargs)
    return Design(**fields)


def fuselage_wetted_each_m2(length_m: float) -> float:
    """One pod. Linear in length from the CAD point (constant section)."""
    L = max(float(length_m), 1e-6)
    return float(config.FUSELAGE_WETTED_REF_M2
                 * (L / config.FUSELAGE_LENGTH_REF_M))


def _empennage_from_stability(S: float, mac: float, b: float, lt: float,
                              boom: float, hstab_ar: float,
                              vstab_ar: float) -> dict:
    """H-stab from SM_MIN. V-stabs are structural T-tail posts, not V_V / yaw.

    Handbook slopes, no T-tail downwash credit. If the two H-stabs would
    meet, span is capped and AR (so a_t) falls; area is grown until SM_MIN
    still holds at that a_t.
    """
    lt = max(float(lt), 1e-6)
    ar_w = max(float(b) ** 2 / max(float(S), 1e-9), 1.0)
    a_w = 2.0 * np.pi / (1.0 + 2.0 / ar_w)
    deps = 2.0 * a_w / (np.pi * ar_w) * float(config.HSTAB_DOWNWASH_K_SIZE)
    n_h = float(config.N_HSTABS)
    span_cap = config.HSTAB_SPAN_BOOM_FRAC_MAX * max(float(boom), 1e-6)
    ar_t_des = max(float(hstab_ar), 0.5)
    S_h = 0.05
    span_each = span_cap
    chord_h = 0.10
    ar_t = ar_t_des
    for _ in range(12):
        a_t = 2.0 * np.pi / (1.0 + 2.0 / max(ar_t, 0.5))
        k_sm = (a_t / a_w) * max(1.0 - deps, 0.05)
        vh = config.STATIC_MARGIN_MIN / max(k_sm, 1e-6)
        S_h = vh * float(S) * float(mac) / lt
        s_each = S_h / max(n_h, 1.0)
        span_each = min(float(np.sqrt(max(ar_t_des * s_each, 1e-8))), span_cap)
        chord_h = s_each / max(span_each, 1e-9)
        ar_t = span_each ** 2 / max(s_each, 1e-9)
    chord_v = max(chord_h, 2.0 * config.BOOM_DIAMETER_M, config.VSTAB_CHORD_MIN_M)
    height_v = max(float(vstab_ar), 0.5) * chord_v
    S_v = 2.0 * height_v * chord_v
    return {
        "hstab_area": float(S_h),
        "hstab_area_each": float(S_h / max(n_h, 1.0)),
        "hstab_span": float(span_each),
        "hstab_chord": float(chord_h),
        "hstab_ar_actual": float(ar_t),
        "n_hstabs": n_h,
        "tail_volume_h": float(S_h * lt / max(float(S) * float(mac), 1e-9)),
        "vstab_area": float(S_v),
        "tail_volume_v": float(S_v * lt / max(float(S) * float(b), 1e-9)),
    }


def _fuselage_pod(name: str, y: float, x_prop: float,
                  x_wing_te: float) -> asb.Fuselage:
    """Motor pod: prop disk → wing trailing edge."""
    r = FUSELAGE_RADIUS_M
    L = max(x_wing_te - x_prop, 0.05)
    return asb.Fuselage(
        name=name,
        xsecs=[
            asb.FuselageXSec(xyz_c=[x_prop, y, 0.0], radius=0.010),
            asb.FuselageXSec(xyz_c=[x_prop + 0.12 * L, y, 0.0], radius=r),
            asb.FuselageXSec(xyz_c=[x_wing_te - 0.10 * L, y, 0.0], radius=r),
            asb.FuselageXSec(xyz_c=[x_wing_te, y, 0.0], radius=0.55 * r),
        ],
    )


def _boom_fuselage(name: str, y: float, x0: float, x1: float) -> asb.Fuselage:
    r = 0.5 * BOOM_DIAMETER_M
    return asb.Fuselage(
        name=name,
        xsecs=[
            asb.FuselageXSec(xyz_c=[x0, y, 0.0], radius=r),
            asb.FuselageXSec(xyz_c=[x1, y, 0.0], radius=r),
        ],
    )


@dataclass
class Design:
    span_m: float
    chord_m: float
    tail_arm_m: float                  # wing AC to H-stab AC
    n_packs: int
    cells_per_string: int | None = None   # None = mixed lengths per bay
    n_strings: int | None = None          # None = keep every packed string
    elevator_frac: float = 0.30
    taper_ratio: float = 1.0          # tip/root; 1 = rectangular outboards
    taper_start_frac: float = 1.0     # fraction of outboard span kept rectangular
    boom_spacing_set_m: float | None = None  # None = REF boom spacing
    one_string_per_bay: bool = False  # True: 1 series string/bay, Voc-capped
    wing_airfoil: str = "s4310"
    hstab_ar: float = config.HSTAB_AR
    vstab_ar: float = config.VSTAB_AR
    prop_diameter_in: float = 18.0
    prop_name: str | None = None
    motor_name: str = config.MOTOR_DEFAULT
    # None = set from NeuralFoil α(CL) / CM(CL) at night min-airspeed.
    incidence_wing_deg: float | None = None
    incidence_hstab_deg: float | None = None
    # Geometric washout, outboard only. 0 tip deg = current untwisted wing.
    washout_tip_deg: float = 0.0          # tip LE-down relative to root jig
    washout_start_frac: float = 0.0       # fraction of outboard span (0=boom)

    # ---- derived geometry ---------------------------------------------------
    def _planform(self) -> dict:
        """Solve boom spacing ↔ area/MAC. Taper starts on the outboards only."""
        cached = getattr(self, "_planform_cache", None)
        if cached is not None:
            return cached
        c_r = float(self.chord_m)
        b = float(self.span_m)
        lam = float(np.clip(self.taper_ratio, 0.15, 1.0))
        f = float(np.clip(self.taper_start_frac, 0.0, 1.0))
        if lam >= 1.0 - 1e-9:
            lam, f = 1.0, 1.0
        c_t = lam * c_r
        S = b * c_r
        mac = c_r
        y_b = 0.25 * b
        y_tap = 0.5 * b
        L_out = 0.0
        L_tap = 0.0
        for _ in range(16):
            if self.boom_spacing_set_m and self.boom_spacing_set_m > 0.05:
                boom = min(float(self.boom_spacing_set_m), 0.92 * b)
            else:
                boom = min(float(config.REF_BOOM_SPACING_M), 0.92 * b)
            y_b_new = 0.5 * boom
            L_out = max(0.0, 0.5 * b - y_b_new)
            y_tap = y_b_new + f * L_out
            L_tap = (1.0 - f) * L_out
            S_new = 2.0 * y_tap * c_r + L_tap * (c_r + c_t)
            int_c2_half = (y_tap * c_r ** 2
                           + (L_tap / 3.0) * (c_r ** 2 + c_r * c_t + c_t ** 2))
            mac_new = (2.0 / max(S_new, 1e-9)) * int_c2_half
            if abs(y_b_new - y_b) < 1e-7 and abs(S_new - S) < 1e-9:
                y_b, S, mac = y_b_new, S_new, mac_new
                break
            y_b, S, mac = y_b_new, S_new, mac_new
        if self.boom_spacing_set_m and self.boom_spacing_set_m > 0.05:
            boom = min(float(self.boom_spacing_set_m), 0.92 * b)
        else:
            boom = min(float(config.REF_BOOM_SPACING_M), 0.92 * b)
        emp = _empennage_from_stability(
            S, mac, b, self.tail_arm_m, boom, self.hstab_ar, self.vstab_ar)
        c_root_eq = 2.0 * S / max(b, 1e-9)
        lam_eq = float(np.clip(c_t / max(c_root_eq - c_t, 0.05), 0.2, 1.0))
        ar = b ** 2 / max(S, 1e-9)
        e_t = float(oswalds_efficiency(lam_eq, ar, sweep=0.0))
        e_r = float(oswalds_efficiency(1.0, ar, sweep=0.0))
        e = min(0.98, OSWALD_E * e_t / max(e_r, 1e-6))
        out = {
            "wing_area": S,
            "mac": mac,
            "aspect_ratio": ar,
            "boom_spacing": boom,
            "hstab_area": emp["hstab_area"],
            "hstab_area_each": emp["hstab_area_each"],
            "hstab_span": emp["hstab_span"],
            "hstab_chord": emp["hstab_chord"],
            "n_hstabs": emp["n_hstabs"],
            "tail_volume_h": emp["tail_volume_h"],
            "hstab_ar_actual": emp["hstab_ar_actual"],
            "vstab_area": emp["vstab_area"],
            "tail_volume_v": emp["tail_volume_v"],
            "y_taper": y_tap,
            "outboard_m": L_out,
            "taper_length_m": L_tap,
            "taper_start_frac": f,
            "tip_chord": c_t,
            "equivalent_taper": lam_eq,
            "oswald_e": e,
        }
        self._planform_cache = out
        return out

    @property
    def wing_area(self) -> float:
        return float(self._planform()["wing_area"])

    @property
    def mac_m(self) -> float:
        return float(self._planform()["mac"])

    @property
    def aspect_ratio(self) -> float:
        return float(self._planform()["aspect_ratio"])

    @property
    def oswald_e(self) -> float:
        """Handbook e, floored by VLM induced e when VLM is worse."""
        e = float(self._planform()["oswald_e"])
        if getattr(self, "_aileron_y_inner_cache", None) is None:
            return e
        from .asb_physics import vlm_oswald_e
        e_v = vlm_oswald_e(self)
        if e_v is not None:
            return min(e, e_v)
        return e

    @property
    def tip_chord_m(self) -> float:
        return float(self._planform()["tip_chord"])

    @property
    def y_taper_m(self) -> float:
        """Spanwise station (from centerline) where outboard taper begins."""
        return float(self._planform()["y_taper"])

    def chord_at_y(self, y_m: float) -> float:
        """Local chord, LE-unswept. |y| from centerline."""
        y = abs(float(y_m))
        p = self._planform()
        y_b = 0.5 * p["boom_spacing"]
        y_tip = 0.5 * self.span_m
        out = max(y_tip - y_b, 0.0)
        s = y - y_b
        if s <= 0.0:
            return self.chord_m
        return solar_array.outboard_chord_m(
            s, out, self.chord_m, p["tip_chord"], p["taper_start_frac"])

    @property
    def y_washout_m(self) -> float:
        """Spanwise station (from centerline) where geometric washout begins."""
        y_b = 0.5 * self.boom_spacing
        y_tip = 0.5 * self.span_m
        if float(self.washout_tip_deg) <= 1e-6:
            return y_tip
        f = float(np.clip(self.washout_start_frac, 0.0, 1.0))
        return y_b + f * max(y_tip - y_b, 0.0)

    def washout_deg_at_y(self, y_m) -> np.ndarray:
        """Linear geometric washout [deg], 0 inboard of the start station."""
        y = np.abs(np.atleast_1d(np.asarray(y_m, dtype=float)))
        y0 = self.y_washout_m
        y_tip = 0.5 * self.span_m
        t = np.clip((y - y0) / max(y_tip - y0, 1e-9), 0.0, 1.0)
        out = float(max(self.washout_tip_deg, 0.0)) * t
        return out if np.ndim(y_m) else float(out[0])

    def _has_washout(self) -> bool:
        return float(self.washout_tip_deg) > 0.05

    @property
    def hstab_area(self) -> float:
        return float(self._planform()["hstab_area"])

    @property
    def hstab_area_each(self) -> float:
        return float(self._planform()["hstab_area_each"])

    @property
    def hstab_span(self) -> float:
        """Span of one H-stab (each fuselage has one)."""
        return float(self._planform()["hstab_span"])

    @property
    def hstab_chord(self) -> float:
        return float(self._planform()["hstab_chord"])

    @property
    def boom_spacing(self) -> float:
        return float(self._planform()["boom_spacing"])

    @property
    def vstab_area_total(self) -> float:
        """Both fins. Structural T-tail posts, not a V_V / weathercock size."""
        return float(self._planform()["vstab_area"])

    @property
    def vstab_area_each(self) -> float:
        return self.vstab_area_total / 2.0

    @property
    def vstab_height(self) -> float:
        return float(np.sqrt(self.vstab_ar * self.vstab_area_each))

    @property
    def vstab_chord(self) -> float:
        return self.vstab_area_each / self.vstab_height

    @property
    def boom_x_front(self) -> float:
        """Boom attaches at the wing trailing edge (aft face of the pod).

        The fuselage takes the wing-spar load. Independent T-tails do not
        need tube through the wing box the way the π-tail did.
        """
        return float(self.chord_m)

    @property
    def vstab_te_x(self) -> float:
        """V-stab trailing-edge x (LE shared with the H-stab)."""
        return self.hstab_le_x() + self.vstab_chord

    @property
    def boom_aft_m(self) -> float:
        """Wing TE to V-stab TE (same as boom_length)."""
        return self.boom_length

    @property
    def boom_length(self) -> float:
        """Carbon tube: wing trailing edge to V-stab trailing edge."""
        return float(max(0.05, self.vstab_te_x - self.boom_x_front))

    @property
    def fuselage_length_m(self) -> float:
        """Prop disk to wing trailing edge."""
        return float(config.PROP_LE_OFFSET_M + self.chord_m)

    @property
    def fuselage_wetted_each_m2(self) -> float:
        return fuselage_wetted_each_m2(self.fuselage_length_m)

    @property
    def prop_x(self) -> float:
        """Prop disk x (wing LE is x=0, aft positive)."""
        return -config.PROP_LE_OFFSET_M

    @property
    def hstab_z(self) -> float:
        """Camber line of each H-stab: on top of its V-stab (T-tail).

        No T-tail downwash credit is taken; handbook ε = 2 CL/(π AR).
        """
        return self.vstab_height + 0.05 * self.hstab_chord

    def _tapered_for_ailerons(self) -> bool:
        """True when the outboard actually tapers (cells drop spanwise)."""
        return (float(self.taper_ratio) < 1.0 - 1e-9
                and float(self.taper_start_frac) < 1.0 - 1e-9)

    def cells_on_aileron(self) -> bool:
        """Rectangular: cells may cover ailerons. Taper: cells off the surface."""
        return not self._tapered_for_ailerons()

    def y_second_row_drop_m(self) -> float:
        """Centerline y where local chord first drops below two cell pitches.

        If the tip still fits two rows, returns the tip (no drop).
        """
        y_b = 0.5 * self.boom_spacing
        y_tip = 0.5 * self.span_m
        c_lim = 2.0 * config.CELL_PITCH_M
        if self.chord_at_y(y_tip) >= c_lim - 1e-9:
            return y_tip
        if self.chord_at_y(y_b) < c_lim:
            return y_b
        lo, hi = y_b, y_tip
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if self.chord_at_y(mid) >= c_lim:
                lo = mid
            else:
                hi = mid
        return float(hi)

    def aileron_y_tip_m(self) -> float:
        return max(0.5 * self.boom_spacing + 0.05,
                   0.5 * self.span_m - config.AILERON_TIP_KEEP_OUT_M)

    def _aileron_y_seed(self) -> float:
        y_boom = 0.5 * self.boom_spacing
        y_tip = self.aileron_y_tip_m()
        if self._tapered_for_ailerons():
            y = self.y_second_row_drop_m()
        else:
            # Outer 30% of semi-span as a starting guess; grow inboard if needed.
            y = y_tip - 0.30 * (0.5 * self.span_m)
        return float(np.clip(y, y_boom, y_tip - 0.02))

    def _solar_bays_at(self, aileron_y_inner_m: float) -> dict:
        return solar_array.wing_layout(
            span_m=self.span_m, chord_m=self.chord_m,
            boom_spacing_m=self.boom_spacing,
            hstab_span_m=self.hstab_span, hstab_chord_m=self.hstab_chord,
            elevator_chord_frac=self.elevator_frac,
            taper_ratio=self.taper_ratio,
            taper_start_frac=self.taper_start_frac,
            aileron_y_inner_m=aileron_y_inner_m,
            aileron_chord_frac=config.AILERON_CHORD_FRAC,
            cells_on_aileron=self.cells_on_aileron())

    def _mass_at_aileron_y(self, y_inner: float) -> float:
        """Mass using packing at a given aileron station (no solar_bays recursion)."""
        bays = self._solar_bays_at(y_inner)
        packed = solar_array.pack_layout(
            bays, self.cells_per_string, one_per_bay=self.one_string_per_bay)
        lengths = packed["lengths"]
        if self.n_strings is not None:
            lengths = lengths[: max(0, int(self.n_strings))]
        n_cells = int(sum(lengths))
        n_mppts = len(lengths)
        return float(
            WETTED_FACTOR * self.wing_area * config.WING_AREAL_MASS
            + WETTED_FACTOR * self.hstab_area * config.TAIL_AREAL_MASS
            + WETTED_FACTOR * self.vstab_area_total * config.TAIL_AREAL_MASS
            + 2.0 * self.boom_length * config.BOOM_MASS_PER_M
            + n_cells * (config.CELL_MASS_KG + config.CELL_INTERCONNECT_MASS_KG)
            + n_mppts * config.MPPT_MASS_KG
            + self.n_packs * config.PACK_MASS_KG
            + config.N_MOTORS * config.MOTOR_CATALOG[self.motor_name].mass_kg
            + config.N_MOTORS * estimate_prop_mass_kg(
                self.prop_diameter_in, self.prop_name)
            + sum(config.FIXED_MASSES_KG.values())
        )

    def aileron_y_inner(self) -> float:
        """Inboard end of the aileron (from centerline), grown until roll rate."""
        cached = getattr(self, "_aileron_y_inner_cache", None)
        if cached is not None:
            return float(cached)
        y = self._aileron_y_seed()
        y_boom = 0.5 * self.boom_spacing
        step = 0.04 * 0.5 * self.span_m
        m = self._mass_at_aileron_y(y)
        v = self.min_airspeed(mass_kg=m)
        for _ in range(24):
            p = self.roll_rate_deg_s(v_ms=v, y_inner=y, mass_kg=m)
            if p >= config.ROLL_RATE_MIN_DEG_S:
                self._aileron_y_inner_cache = float(y)
                return float(y)
            y_next = max(y_boom, y - step)
            if y_next >= y - 1e-9:
                self._aileron_y_inner_cache = float(y_boom)
                return float(y_boom)
            y = y_next
            m = self._mass_at_aileron_y(y)
            v = self.min_airspeed(mass_kg=m)
        self._aileron_y_inner_cache = float(y)
        return float(y)

    def aileron_span_each_m(self) -> float:
        return max(0.0, self.aileron_y_tip_m() - self.aileron_y_inner())

    # ---- solar layout --------------------------------------------------------
    def solar_bays(self) -> dict:
        return self._solar_bays_at(self.aileron_y_inner())

    def pack_layout(self) -> dict:
        return solar_array.pack_layout(
            self.solar_bays(), self.cells_per_string,
            one_per_bay=self.one_string_per_bay)

    def string_lengths(self) -> tuple[int, ...]:
        """Kept strings, longest first. `n_strings` drops the shortest."""
        packed = self.pack_layout()["lengths"]
        if self.n_strings is None:
            return tuple(packed)
        return tuple(packed[: max(0, int(self.n_strings))])

    def string_plan_label(self) -> str:
        lens = self.string_lengths()
        return "+".join(str(n) for n in lens) if lens else "none"

    def max_strings(self) -> int:
        return int(self.pack_layout()["total_strings"])

    @property
    def n_mppts(self) -> int:
        return len(self.string_lengths())

    @property
    def n_cells(self) -> int:
        return int(sum(self.string_lengths()))

    def cell_placements(self) -> list:
        return solar_array.place_cells(
            span_m=self.span_m, chord_m=self.chord_m,
            boom_spacing_m=self.boom_spacing,
            hstab_span_m=self.hstab_span, hstab_chord_m=self.hstab_chord,
            elevator_chord_frac=self.elevator_frac,
            taper_ratio=self.taper_ratio,
            taper_start_frac=self.taper_start_frac,
            aileron_y_inner_m=self.aileron_y_inner(),
            aileron_chord_frac=config.AILERON_CHORD_FRAC,
            cells_on_aileron=self.cells_on_aileron(),
            chord_at_y=self.chord_at_y)

    def packing_geometry_reason(self) -> str | None:
        """None if every packed cell is on the planform and none overlap."""
        return solar_array.packing_geometry_reason(
            self.cell_placements(),
            n_cells=self.n_cells,
            span_m=self.span_m,
            chord_at_y=self.chord_at_y,
            boom_spacing_m=self.boom_spacing,
            hstab_span_m=self.hstab_span,
            hstab_chord_m=self.hstab_chord,
            elevator_chord_frac=self.elevator_frac,
            aileron_y_inner_m=self.aileron_y_inner(),
            aileron_chord_frac=config.AILERON_CHORD_FRAC,
            cells_on_aileron=self.cells_on_aileron())

    def packing_geometry_ok(self) -> bool:
        return self.packing_geometry_reason() is None

    def solar_feasible(self) -> bool:
        if self.boom_spacing >= self.span_m * 0.95:
            return False
        if self.hstab_chord <= 0.05 or self.vstab_chord <= 0.05:
            return False
        if self.hstab_span > config.HSTAB_SPAN_BOOM_FRAC_MAX * self.boom_spacing + 1e-9:
            return False
        lens = self.string_lengths()
        limit = solar_array.max_cells_per_string()
        if self.one_string_per_bay:
            # Geometry itself must fit one Voc-legal string per bay (no dead cells).
            if any(b.capacity > limit for b in self.solar_bays().values()):
                return False
        return (len(lens) > 0
                and all(1 <= n <= limit for n in lens)
                and self.n_cells <= solar_array.total_capacity(self.solar_bays())
                and self.packing_geometry_ok())

    # ---- mass buildup --------------------------------------------------------
    def mass_breakdown(self) -> dict:
        m = {
            "wing": WETTED_FACTOR * self.wing_area * config.WING_AREAL_MASS,
            "hstab": WETTED_FACTOR * self.hstab_area * config.TAIL_AREAL_MASS,
            "vstabs": WETTED_FACTOR * self.vstab_area_total * config.TAIL_AREAL_MASS,
            "booms": 2.0 * self.boom_length * config.BOOM_MASS_PER_M,
            "solar_cells": self.n_cells * (config.CELL_MASS_KG
                                           + config.CELL_INTERCONNECT_MASS_KG),
            "mppts": self.n_mppts * config.MPPT_MASS_KG,
            "batteries": self.n_packs * config.PACK_MASS_KG,
            "motors": config.N_MOTORS * config.MOTOR_CATALOG[
                self.motor_name].mass_kg,
            "props": config.N_MOTORS * estimate_prop_mass_kg(
                self.prop_diameter_in, self.prop_name),
            "fixed": sum(config.FIXED_MASSES_KG.values()),
        }
        return m

    @property
    def mass_kg(self) -> float:
        return float(sum(self.mass_breakdown().values()))

    # ---- aerodynamics --------------------------------------------------------
    def parasite_drag_area(self, v_ms, rho) -> np.ndarray:
        """Non-lifting-surface drag area f = D/q [m^2]: pods + booms + CS gaps."""
        v = np.asarray(v_ms, dtype=float)
        L_fuse = self.fuselage_length_m
        swet = self.fuselage_wetted_each_m2
        re_pod = rho * v * L_fuse / MU_AIR
        f_pods = 2.0 * _cf_turbulent(re_pod) * POD_FORM_FACTOR * swet
        boom_wet = np.pi * BOOM_DIAMETER_M * self.boom_length
        re_boom = rho * v * self.boom_length / MU_AIR
        f_booms = 2.0 * _cf_turbulent(re_boom) * 1.1 * boom_wet
        f_gaps = self.control_surface_gap_area()
        return (f_pods + f_booms) * PARASITE_INTERFERENCE + f_gaps

    def cruise_cl(self, rho: float = RHO_NIGHT,
                  mass_kg: float | None = None) -> float:
        """Net CL at night min airspeed (incidence design point)."""
        v = self.min_airspeed(rho, mass_kg)
        m = self.mass_kg if mass_kg is None else mass_kg
        q = 0.5 * rho * v ** 2
        return float(m * G / max(q * self.wing_area, 1e-9))

    def _handbook_incidence_deg(self) -> tuple[float, float]:
        """Wing / H-stab jig incidence from NeuralFoil α(CL) and CM(CL).

        Uses handbook downwash and handbook Oswald e so VLM/CAD cannot recurse.
        """
        cached = getattr(self, "_inc_hb_cache", None)
        if cached is not None:
            return cached
        cl = self.cruise_cl()
        re = RHO_NIGHT * self.min_airspeed() * self.mac_m / MU_AIR
        a2d = float(alpha_deg_at_cl(self.wing_airfoil, cl, re))
        e = float(self._planform()["oswald_e"])
        a_ind = np.degrees(cl / (np.pi * self.aspect_ratio * e))
        i_w = a2d + a_ind
        cm = float(cm_at_cl(self.wing_airfoil, cl, re))
        _a_w, a_t, _deps = self._lift_slopes_handbook()
        vh = max(self.tail_volume_h(), 1e-6)
        eps = np.degrees(2.0 * cl / (np.pi * self.aspect_ratio))
        i_t = eps + np.degrees(cm / (vh * a_t))
        out = (float(i_w), float(i_t))
        self._inc_hb_cache = out
        return out

    def _auto_incidence_deg(self) -> tuple[float, float]:
        """Handbook incidence, plus extra H-stab incidence if VLM downwash is stronger."""
        cached = getattr(self, "_inc_cache", None)
        if cached is not None:
            return cached
        i_w, i_t = self._handbook_incidence_deg()
        from .asb_physics import downwash_k_used
        k = downwash_k_used(self)
        if k > 1.0 + 1e-9:
            cl = self.cruise_cl()
            eps = np.degrees(2.0 * cl / (np.pi * self.aspect_ratio))
            i_t = i_t + (k - 1.0) * eps
        out = (float(i_w), float(i_t))
        self._inc_cache = out
        return out

    def _ll_stations(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        theta = lifting_line._theta_nodes()
        y = 0.5 * self.span_m * np.cos(theta)
        c = np.array([self.chord_at_y(yi) for yi in y], dtype=float)
        return theta, y, c

    def _section_a0(self, re: float) -> float:
        """Viscous section lift slope [1/rad] from NeuralFoil, capped at 2π."""
        cl0 = 0.80
        a1 = float(alpha_deg_at_cl(self.wing_airfoil, cl0 - 0.15, re))
        a2 = float(alpha_deg_at_cl(self.wing_airfoil, cl0 + 0.15, re))
        a0 = 0.30 / max(np.radians(a2 - a1), 1e-4)
        return float(min(2.0 * np.pi, a0))

    def _ll_match(self, cl_target: float, i_w_rad: float, alpha_l0: float,
                  a0: float, washout: bool) -> tuple[np.ndarray, np.ndarray]:
        """Fourier A_n and section CL that produce `cl_target`."""
        _theta, y, c = self._ll_stations()
        wo = (np.radians(self.washout_deg_at_y(y)) if washout
              else np.zeros_like(y))
        a_jig = lifting_line.solve_coefficients(
            i_w_rad - wo, alpha_l0, c, self.span_m, a0)
        a_unit = lifting_line.solve_coefficients(
            np.full_like(y, alpha_l0 + 1.0), alpha_l0, c, self.span_m, a0)
        cl_jig = lifting_line.cl_wing(a_jig, self.aspect_ratio)
        cl_per = lifting_line.cl_wing(a_unit, self.aspect_ratio)
        alpha_boom = (cl_target - cl_jig) / max(cl_per, 1e-6)
        a = a_jig + alpha_boom * a_unit
        cl_loc = lifting_line.cl_distribution(a, c, self.span_m)
        return a, cl_loc

    def _strip_profile_cd(self, cl_loc: np.ndarray, v: float, rho: float) -> float:
        theta, _y, c = self._ll_stations()
        re = rho * float(v) * c / MU_AIR
        cd = np.array([
            float(profile_cd(self.wing_airfoil, cl_loc[j], re[j]))
            for j in range(c.size)
        ])
        dth = np.pi / (2.0 * c.size)
        area = c * (0.5 * self.span_m) * np.sin(theta) * dth
        return float(2.0 * np.sum(cd * area) / max(self.wing_area, 1e-9))

    def _washout_wing_cd(self, cl_w: float, v: float, rho: float
                         ) -> tuple[float, float, float]:
        """Profile CD delta, induced CD, and e_eff vs the lumped polar.

        Zero washout → (0, CL²/(πAR e_handbook), e_handbook) so the
        published baseline polar does not move. Nonzero washout uses
        lifting-line e relative to the untwisted planform (capped at 0.98)
        and a strip profile increment vs the same planform untwisted.
        """
        e_h = self.oswald_e
        cd_i_h = cl_w ** 2 / (np.pi * self.aspect_ratio * e_h)
        if not self._has_washout():
            return 0.0, float(cd_i_h), float(e_h)
        re_mac = rho * float(v) * self.mac_m / MU_AIR
        a0 = self._section_a0(re_mac)
        a_l0 = np.radians(float(alpha_deg_at_cl(self.wing_airfoil, 0.0, re_mac)))
        i_w = np.radians(self.wing_incidence_deg())
        a_t, cl_t = self._ll_match(cl_w, i_w, a_l0, a0, True)
        a_0, cl_0 = self._ll_match(cl_w, i_w, a_l0, a0, False)
        e_t = lifting_line.oswald_from_A(a_t)
        e_u = lifting_line.oswald_from_A(a_0)
        e_eff = min(0.98, e_h * e_t / max(e_u, 1e-6))
        cd_i = cl_w ** 2 / (np.pi * self.aspect_ratio * e_eff)
        d_cd = (self._strip_profile_cd(cl_t, v, rho)
                - self._strip_profile_cd(cl_0, v, rho))
        return float(d_cd), float(cd_i), float(e_eff)

    def _strip_clmax(self) -> float:
        """Net CL when the most-loaded strip hits 2D CLmax (inviscid shape).

        Incidence is absorbed into boom alpha; only washout changes the
        shape. Re is a representative 2e5 so this does not recurse through
        stall_speed.
        """
        re = 2.0e5
        a0 = self._section_a0(re)
        a_l0 = np.radians(float(alpha_deg_at_cl(self.wing_airfoil, 0.0, re)))
        _a, cl_loc = self._ll_match(1.0, 0.0, a_l0, a0, True)
        peak = float(np.max(cl_loc))
        return float(clmax_2d(self.wing_airfoil, re) / max(peak, 1e-6))

    def wing_incidence_deg(self) -> float:
        if self.incidence_wing_deg is not None:
            return float(self.incidence_wing_deg)
        return self._auto_incidence_deg()[0]

    def hstab_incidence_deg(self) -> float:
        if self.incidence_hstab_deg is not None:
            return float(self.incidence_hstab_deg)
        return self._auto_incidence_deg()[1]

    def drag_n(self, v_ms, mass_kg: float | None = None,
               rho: float = RHO_NIGHT) -> np.ndarray:
        """Total level-flight drag [N] vs airspeed.

        Wing CL from weight, then a few iterations of tail load at the
        jig incidences (NeuralFoil CM trims the H-stab; elevator ≈ 0).
        """
        v = np.atleast_1d(np.asarray(v_ms, dtype=float))
        m = self.mass_kg if mass_kg is None else mass_kg
        w = m * G
        q = 0.5 * rho * v ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            cl_net = np.where(q > 1e-6, w / (q * self.wing_area), 0.0)

        re_wing = rho * v * self.mac_m / MU_AIR
        re_tail = rho * v * self.hstab_chord / MU_AIR
        _a_w, a_t, _deps = self._lift_slopes()
        i_w = np.radians(self.wing_incidence_deg())
        i_t = np.radians(self.hstab_incidence_deg())
        ar = self.aspect_ratio
        e = self.oswald_e
        ar_t = max(float(self._planform()["hstab_ar_actual"]), 0.5)
        s_ratio = self.hstab_area / max(self.wing_area, 1e-9)

        cl_w = np.array(cl_net, copy=True)
        cl_t = np.zeros_like(cl_w)
        for _ in range(3):
            a2d = np.radians(np.atleast_1d(
                alpha_deg_at_cl(self.wing_airfoil, cl_w, re_wing)))
            a_ind = cl_w / (np.pi * ar * e)
            alpha_f = a2d + a_ind - i_w
            eps = self.downwash_angle_rad(cl_w)
            cl_t = a_t * (alpha_f + i_t - eps)
            cl_w = cl_net - s_ratio * cl_t

        cd_wing = profile_cd(self.wing_airfoil, cl_w, re_wing)
        d_cd, cd_ind, _e_eff = np.zeros_like(cl_w), cl_w ** 2 / (np.pi * ar * e), e
        if self._has_washout():
            d_cd = np.empty_like(cl_w)
            cd_ind = np.empty_like(cl_w)
            for i, (cl_i, v_i) in enumerate(zip(cl_w, v)):
                d_cd[i], cd_ind[i], _ = self._washout_wing_cd(float(cl_i), float(v_i), rho)
            cd_wing = cd_wing + d_cd
        cd_h = profile_cd("naca0010", cl_t, re_tail)
        cd_hi = cl_t ** 2 / (np.pi * ar_t * 0.70)
        cd_v = profile_cd("naca0010", np.zeros_like(v), re_tail)

        d = q * (self.wing_area * (cd_wing + cd_ind)
                 + self.hstab_area * (cd_h + cd_hi)
                 + self.vstab_area_total * cd_v
                 + self.parasite_drag_area(v, rho))
        d = d * TRIM_DRAG_FACTOR
        return d if np.ndim(v_ms) else float(d[0])

    def drag_breakdown(self, v_ms: float | None = None,
                       mass_kg: float | None = None,
                       rho: float = RHO_NIGHT) -> dict:
        """Component CL, CD, and drag [N] at one airspeed (default night Vmin)."""
        v = float(self.min_airspeed(rho, mass_kg) if v_ms is None else v_ms)
        m = self.mass_kg if mass_kg is None else mass_kg
        d_tot = float(np.asarray(self.drag_n(v, mass_kg=m, rho=rho)).reshape(-1)[0])
        w = m * G
        q = 0.5 * rho * v ** 2
        s = self.wing_area
        cl_net = w / max(q * s, 1e-9)
        re_wing = rho * v * self.mac_m / MU_AIR
        re_tail = rho * v * self.hstab_chord / MU_AIR
        _a_w, a_t, _deps = self._lift_slopes()
        i_w = np.radians(self.wing_incidence_deg())
        i_t = np.radians(self.hstab_incidence_deg())
        ar, e = self.aspect_ratio, self.oswald_e
        ar_t = max(float(self._planform()["hstab_ar_actual"]), 0.5)
        s_ratio = self.hstab_area / max(s, 1e-9)
        cl_w = cl_net
        cl_t = 0.0
        for _ in range(3):
            a2d = np.radians(float(alpha_deg_at_cl(self.wing_airfoil, cl_w, re_wing)))
            a_ind = cl_w / (np.pi * ar * e)
            alpha_f = a2d + a_ind - i_w
            eps = float(self.downwash_angle_rad(cl_w))
            cl_t = float(a_t * (alpha_f + i_t - eps))
            cl_w = float(cl_net - s_ratio * cl_t)
        cd_wp = float(profile_cd(self.wing_airfoil, cl_w, re_wing))
        d_cd, cd_wi, e_eff = self._washout_wing_cd(cl_w, v, rho)
        cd_wp = cd_wp + d_cd
        cd_hp = float(profile_cd("naca0010", cl_t, re_tail))
        cd_hi = cl_t ** 2 / (np.pi * ar_t * 0.70)
        cd_v = float(profile_cd("naca0010", 0.0, re_tail))
        v_arr = np.asarray([v], dtype=float)
        L_fuse = self.fuselage_length_m
        swet = self.fuselage_wetted_each_m2
        re_pod = rho * v_arr * L_fuse / MU_AIR
        f_pods = float((2.0 * _cf_turbulent(re_pod) * POD_FORM_FACTOR
                        * swet * PARASITE_INTERFERENCE)[0])
        boom_wet = np.pi * BOOM_DIAMETER_M * self.boom_length
        re_boom = rho * v_arr * self.boom_length / MU_AIR
        f_booms = float((2.0 * _cf_turbulent(re_boom) * 1.1 * boom_wet
                         * PARASITE_INTERFERENCE)[0])
        f_gaps = self.control_surface_gap_area()
        parts = {
            "wing_profile": q * s * cd_wp,
            "wing_induced": q * s * cd_wi,
            "hstab_profile": q * self.hstab_area * cd_hp,
            "hstab_induced": q * self.hstab_area * cd_hi,
            "vstab_profile": q * self.vstab_area_total * cd_v,
            "pods": q * f_pods,
            "booms": q * f_booms,
            "control_gaps": q * f_gaps,
        }
        raw = sum(parts.values())
        scale = d_tot / max(raw, 1e-12)
        parts = {k: float(val * scale) for k, val in parts.items()}
        return {
            "v_ms": v, "rho": rho, "q_pa": q, "mass_kg": m,
            "cl_net": cl_net, "cl_wing": cl_w, "cl_hstab": cl_t,
            "re_wing": re_wing, "re_hstab": re_tail,
            "cd_wing_profile": cd_wp, "cd_wing_induced": cd_wi,
            "cd_wing": cd_wp + cd_wi,
            "cd_hstab_local": cd_hp + cd_hi, "cl_hstab_local": cl_t,
            "cd_vstab_local": cd_v,
            "cd_wingref": d_tot / max(q * s, 1e-12),
            "drag_n": parts,
            "drag_total_n": d_tot,
            "power_aero_w": d_tot * v,
        }

    def power_aero_w(self, v_ms, mass_kg: float | None = None,
                     rho: float = RHO_NIGHT) -> np.ndarray:
        v = np.asarray(v_ms, dtype=float)
        return self.drag_n(v, mass_kg=mass_kg, rho=rho) * v

    def stall_speed(self, rho: float = RHO_NIGHT,
                    mass_kg: float | None = None) -> float:
        m = self.mass_kg if mass_kg is None else mass_kg
        clmax2 = clmax_2d(self.wing_airfoil)
        clmax = CLMAX_3D_FACTOR * clmax2
        if self._has_washout():
            # First-strip stall. Cannot exceed the untwisted 3D cap.
            clmax = CLMAX_3D_FACTOR * min(clmax2, self._strip_clmax())
        return float(np.sqrt(2.0 * m * G / (rho * self.wing_area * clmax)))

    def min_airspeed(self, rho: float = RHO_NIGHT,
                     mass_kg: float | None = None) -> float:
        """Operational floor: stall margin + 15 kt crosswind requirement."""
        return max(config.LOITER_STALL_FACTOR * self.stall_speed(rho, mass_kg),
                   config.MIN_AIRSPEED_WIND_MS)

    def min_power_speed(self, rho: float = RHO_NIGHT,
                        mass_kg: float | None = None) -> float:
        """Airspeed that minimises shaft power (D*V), at or above v_min.

        Continuous 1-D search starting at V_CRUISE_START_MS, refined to
        V_CRUISE_TOL_MS. Not a catalog grid.
        """
        v_min = float(self.min_airspeed(rho, mass_kg))
        m = self.mass_kg if mass_kg is None else float(mass_kg)
        key = (round(float(rho), 5), round(m, 5))
        cache = getattr(self, "_vmp_cache", None)
        if cache is None:
            self._vmp_cache = {}
            cache = self._vmp_cache
        if key in cache:
            return cache[key]
        v0 = float(config.V_CRUISE_START_MS)
        tol = float(config.V_CRUISE_TOL_MS)
        v_lo_b, v_hi_b = config.V_CRUISE_BOUNDS_MS
        v_lo = max(v_min, float(v_lo_b))
        v_hi = max(v_lo + 1.0, float(v_hi_b))
        v_seed = float(np.clip(v0, v_lo, v_hi))
        v_grid = np.unique(np.concatenate([
            np.linspace(v_lo, v_hi, 9),
            [v_seed],
        ]))
        p_grid = np.asarray(
            self.power_aero_w(v_grid, mass_kg=m, rho=rho), dtype=float)
        i = int(np.argmin(p_grid))
        lo = float(v_grid[max(0, i - 1)])
        hi = float(v_grid[min(len(v_grid) - 1, i + 1)])
        if hi - lo < tol:
            v_star = float(v_grid[i])
        else:
            def p_aero(v: float) -> float:
                return float(np.asarray(
                    self.power_aero_w(float(v), mass_kg=m, rho=rho)
                ).reshape(-1)[0])
            res = minimize_scalar(
                p_aero, bounds=(lo, hi), method="bounded",
                options={"xatol": tol, "maxiter": 40})
            v_star = float(res.x) if res.success else float(v_grid[i])
        v_star = float(max(v_min, round(v_star / tol) * tol))
        p_star = float(np.asarray(
            self.power_aero_w(v_star, mass_kg=m, rho=rho)).reshape(-1)[0])
        p_floor = float(np.asarray(
            self.power_aero_w(v_min, mass_kg=m, rho=rho)).reshape(-1)[0])
        if p_floor <= p_star + 1e-9:
            v_star = v_min
        cache[key] = v_star
        return v_star

    def climb_rate_ideal_ms(self, v_ms: float, thrust_n: float,
                            mass_kg: float | None = None,
                            rho: float = RHO_DAY) -> float:
        """ROC = V (T-D)/W at the given speed and available thrust."""
        m = self.mass_kg if mass_kg is None else mass_kg
        d = float(np.asarray(self.drag_n(v_ms, mass_kg=m, rho=rho)).reshape(-1)[0])
        return float(v_ms * (thrust_n - d) / (m * G))

    # ---- longitudinal stability & control ------------------------------------
    def _lift_slopes_handbook(self) -> tuple[float, float, float]:
        a_w = 2.0 * np.pi / (1.0 + 2.0 / self.aspect_ratio)
        ar_t = float(self._planform()["hstab_ar_actual"])
        a_t = 2.0 * np.pi / (1.0 + 2.0 / max(ar_t, 0.5))
        deps = 2.0 * a_w / (np.pi * self.aspect_ratio)
        return a_w, a_t, deps

    def _lift_slopes(self) -> tuple[float, float, float]:
        a_w, a_t, deps = self._lift_slopes_handbook()
        if getattr(self, "_aileron_y_inner_cache", None) is None:
            return a_w, a_t, deps
        from .asb_physics import downwash_k_used
        return a_w, a_t, deps * downwash_k_used(self)

    def downwash_angle_rad(self, cl):
        """ε(CL). Handbook 2 CL/(π AR), scaled up if VLM at the tail is stronger."""
        hb = 2.0 * np.asarray(cl, dtype=float) / (np.pi * self.aspect_ratio)
        from .asb_physics import downwash_k_used
        return hb * downwash_k_used(self)

    def tail_volume_h(self) -> float:
        return float(self._planform()["tail_volume_h"])

    def static_margin(self) -> float:
        """CG at quarter chord (user) => SM is the tail contribution to NP."""
        a_w, a_t, deps = self._lift_slopes()
        return float(self.tail_volume_h() * (a_t / a_w) * (1.0 - deps))

    def elevator_tau(self) -> float:
        """Flap effectiveness. FLAGGED: sqrt(cf/c) empirical stand-in."""
        return flap_tau(self.elevator_frac)

    def elevator_authority_ok(self, de_max_deg: float = config.ELEVATOR_MAX_DEG,
                              cl_range: float = 1.0) -> bool:
        """Elevator must trim the cruise CL range at the achieved SM."""
        _, a_t, _ = self._lift_slopes()
        cm_de = a_t * self.tail_volume_h() * self.elevator_tau()
        cm_required = self.static_margin() * cl_range
        return bool(cm_de * np.radians(de_max_deg) >= cm_required)

    def pitch_inertia_lumped_kgm2(self) -> float:
        m = self.mass_breakdown()
        lt = self.tail_arm_m
        c = self.chord_m
        return (
            m["wing"] * (0.22 * c) ** 2
            + (m["hstab"] + m["vstabs"]) * lt ** 2
            + m["booms"] * (0.50 * lt) ** 2
            + (m["fixed"] + m["batteries"] + m["motors"] + m["props"])
            * (0.20 * c) ** 2
        )

    def pitch_inertia_kgm2(self) -> float:
        """Lumped Iyy, or CAD thin-shell if larger (harder pitch)."""
        lumped = self.pitch_inertia_lumped_kgm2()
        from .asb_physics import mesh_inertia
        mesh = mesh_inertia(self)
        if mesh and mesh.get("ok"):
            return max(lumped, float(mesh["iyy"]))
        return lumped

    def pitch_accel_rad_s2(self, v_ms: float,
                           de_max_deg: float = config.ELEVATOR_MAX_DEG,
                           rho: float = RHO_NIGHT) -> float:
        """Peak pitch angular acceleration at v, full elevator."""
        _, a_t, _ = self._lift_slopes()
        q = 0.5 * rho * v_ms ** 2
        cm_de = a_t * self.tail_volume_h() * self.elevator_tau()
        moment = q * self.wing_area * self.mac_m * cm_de * np.radians(de_max_deg)
        iyy = max(self.pitch_inertia_kgm2(), 1e-3)
        return float(moment / iyy)

    def pitch_ok(self, v_ms: float | None = None) -> bool:
        if v_ms is None:
            v_ms = self.min_airspeed()
        return self.pitch_accel_rad_s2(v_ms) >= config.PITCH_ACCEL_MIN_RAD_S2

    def control_surface_gap_area(self, y_inner: float | None = None) -> float:
        """Parasite drag area f = D/q of aileron + elevon hinge/side gaps."""
        y1 = self._aileron_y_seed() if y_inner is None else float(y_inner)
        # Use seed when called during sizing; sized station otherwise.
        if y_inner is None and getattr(self, "_aileron_y_inner_cache", None) is not None:
            y1 = float(self._aileron_y_inner_cache)
        y2 = self.aileron_y_tip_m()
        b_ail = max(0.0, y2 - y1)
        c_ail = 0.5 * (self.chord_at_y(y1) + self.chord_at_y(y2))
        hinge_a = 1.0 - config.AILERON_CHORD_FRAC
        f_ail = 0.0
        if b_ail > 0.02 and c_ail > 0.05:
            f_ail = 2.0 * CDA_control_surface_gaps(
                local_chord=c_ail,
                control_surface_span=b_ail,
                local_thickness_over_chord=0.10,
                control_surface_hinge_x=hinge_a,
                n_side_gaps=2)
        hinge_e = 1.0 - float(self.elevator_frac)
        f_elev = float(config.N_HSTABS) * CDA_control_surface_gaps(
            local_chord=self.hstab_chord,
            control_surface_span=self.hstab_span,
            local_thickness_over_chord=0.10,
            control_surface_hinge_x=hinge_e,
            n_side_gaps=2)
        return float(f_ail + f_elev)

    def _strip_cl_delta(self, y1: float, y2: float, tau: float, a: float) -> float:
        """Both-sides C_l_δ per radian from a strip ∫ c y dy / (S b)."""
        lo, hi = (float(y1), float(y2)) if y1 <= y2 else (float(y2), float(y1))
        if hi - lo < 0.02:
            return 0.0
        ys = np.linspace(lo, hi, 16)
        c = np.array([self.chord_at_y(y) for y in ys])
        integ = float(np.trapezoid(c * ys, ys))
        return float(2.0 * a * tau * integ
                     / max(self.wing_area * self.span_m, 1e-9))

    def cl_delta_aileron(self, y_inner: float | None = None) -> float:
        y1 = self.aileron_y_inner() if y_inner is None else float(y_inner)
        a_w, _, _ = self._lift_slopes()
        return self._strip_cl_delta(
            y1, self.aileron_y_tip_m(), flap_tau(config.AILERON_CHORD_FRAC), a_w)

    def cl_delta_elevon(self) -> float:
        """Differential split-elevator roll derivative [1/rad].

        Each H-stab is centered on its boom, so the moment arm is the boom
        half-spacing, not 1/4 of a bridging π-tail span.
        """
        _, a_t, _ = self._lift_slopes()
        tau = self.elevator_tau()
        y_bar = 0.5 * self.boom_spacing
        return float(self.hstab_area * a_t * tau * y_bar
                     / max(self.wing_area * self.span_m, 1e-9))

    def cl_p_handbook(self) -> float:
        """Roll damping Cl_p [per rad of pb/2V]. Extra factor is conservative."""
        a_w, _, _ = self._lift_slopes_handbook()
        lam = float(self._planform()["equivalent_taper"])
        clp = -(a_w / 12.0) * (1.0 + 3.0 * lam) / (1.0 + lam)
        return float(clp * config.ROLL_DAMPING_EXTRA)

    def cl_p(self) -> float:
        """More-negative of handbook vs AeroBuildup (harder steady roll)."""
        hb = self.cl_p_handbook()
        if getattr(self, "_aileron_y_inner_cache", None) is None:
            return hb
        from .asb_physics import aerobuildup_derivatives
        ab = aerobuildup_derivatives(self)
        if ab and ab.get("ok"):
            return float(min(hb, ab["clp"]))
        return hb

    def cn_beta_handbook(self) -> float:
        """Weathercock Cn_β [1/rad]. Two fins, Helmbold slope, no endplate."""
        ar_v = max(float(self.vstab_ar), 0.5)
        a_v = 2.0 * np.pi / (1.0 + 2.0 / ar_v)
        return float(config.FIN_SIDEWASH_ETA * a_v * self.tail_volume_v_actual())

    def cn_beta(self) -> float:
        """Smaller of handbook vs AeroBuildup (harder weathercock floor)."""
        hb = self.cn_beta_handbook()
        if getattr(self, "_aileron_y_inner_cache", None) is None:
            return hb
        from .asb_physics import aerobuildup_derivatives
        ab = aerobuildup_derivatives(self)
        if ab and ab.get("ok") and ab["cnb"] > 0.0:
            return float(min(hb, ab["cnb"]))
        return hb

    def cn_r_handbook(self) -> float:
        """Yaw damping Cn_r [per rad of rb/2V]. ~ (Sv/S)(lt/b)^2."""
        ar_v = max(float(self.vstab_ar), 0.5)
        a_v = 2.0 * np.pi / (1.0 + 2.0 / ar_v)
        sv_s = self.vstab_area_total / max(self.wing_area, 1e-9)
        lt_b = self.tail_arm_m / max(self.span_m, 1e-9)
        return float(-2.0 * config.FIN_SIDEWASH_ETA * a_v * sv_s * lt_b ** 2)

    def cn_r(self) -> float:
        """Closer-to-zero of handbook vs AeroBuildup (harder |Cn_r| floor)."""
        hb = self.cn_r_handbook()
        if getattr(self, "_aileron_y_inner_cache", None) is None:
            return hb
        from .asb_physics import aerobuildup_derivatives
        ab = aerobuildup_derivatives(self)
        if ab and ab.get("ok"):
            return float(max(hb, ab["cnr"]))  # both negative: max is weaker
        return hb

    def roll_helix(self, y_inner: float | None = None) -> float:
        """pb/(2V) at full aileron + elevon. Independent of speed."""
        da = np.radians(config.AILERON_MAX_DEG)
        de = np.radians(config.ELEVON_ROLL_DEG)
        cl = (self.cl_delta_aileron(y_inner) * da
              + self.cl_delta_elevon() * de)
        clp = self.cl_p()
        if clp >= -1e-6:
            return 0.0
        return float(-cl / clp)

    def roll_rate_parts_deg_s(self, v_ms: float | None = None,
                              y_inner: float | None = None,
                              mass_kg: float | None = None,
                              rho: float = RHO_NIGHT) -> tuple[float, float]:
        """(aileron, elevon) contributions to steady roll rate [deg/s]."""
        v = (self.min_airspeed(rho, mass_kg) if v_ms is None else float(v_ms))
        clp = self.cl_p()
        if clp >= -1e-6:
            return 0.0, 0.0
        scale = np.degrees(-1.0 / clp * 2.0 * v / max(self.span_m, 1e-6))
        da = np.radians(config.AILERON_MAX_DEG)
        de = np.radians(config.ELEVON_ROLL_DEG)
        p_a = float(scale * self.cl_delta_aileron(y_inner) * da)
        p_e = float(scale * self.cl_delta_elevon() * de)
        return p_a, p_e

    def roll_rate_deg_s(self, v_ms: float | None = None,
                        y_inner: float | None = None,
                        mass_kg: float | None = None,
                        rho: float = RHO_NIGHT) -> float:
        p_a, p_e = self.roll_rate_parts_deg_s(v_ms, y_inner, mass_kg, rho)
        return p_a + p_e

    def tail_volume_v_actual(self) -> float:
        return float(self.vstab_area_total * self.tail_arm_m
                     / max(self.wing_area * self.span_m, 1e-9))

    def directional_ok(self) -> bool:
        if not config.REQUIRE_YAW_STABILITY:
            return True
        return (self.cn_beta() >= config.CN_BETA_MIN
                and abs(self.cn_r()) >= config.CN_R_ABS_MIN)

    def differential_thrust_yaw_ok(self, t_one_motor_max_n: float,
                                   v_ms: float | None = None,
                                   rho: float = RHO_NIGHT) -> bool:
        """One motor at T_max, the other idle, vs weathercock at YAW_TRIM β.

        No rudder: this is the yaw-control check.
        """
        v = self.min_airspeed(rho) if v_ms is None else float(v_ms)
        q = 0.5 * rho * v ** 2
        beta = np.radians(config.YAW_TRIM_SIDESLIP_DEG)
        n_aero = q * self.wing_area * self.span_m * self.cn_beta() * beta
        n_thrust = float(t_one_motor_max_n) * (0.5 * self.boom_spacing)
        return bool(n_thrust >= n_aero)

    def roll_ok(self, v_ms: float | None = None,
                mass_kg: float | None = None) -> bool:
        return self.roll_rate_deg_s(v_ms=v_ms, mass_kg=mass_kg) >= (
            config.ROLL_RATE_MIN_DEG_S - 1e-6)

    def stability_fail_reason(self) -> str | None:
        if not self.roll_ok():
            return "roll_rate"
        if self.static_margin() < config.STATIC_MARGIN_MIN:
            return "static_margin"
        if not self.elevator_authority_ok():
            return "elevator"
        if not self.pitch_ok():
            return "pitch"
        if config.REQUIRE_YAW_STABILITY and not self.directional_ok():
            return "yaw_stability"
        return None

    def stability_ok(self) -> bool:
        return self.stability_fail_reason() is None

    # ---- AeroSandbox geometry (CAD + later MDO) -----------------------------
    def hstab_le_x(self) -> float:
        """H-stab leading-edge x so the tail AC sits `tail_arm_m` aft of wing AC."""
        return 0.25 * self.mac_m + self.tail_arm_m - 0.25 * self.hstab_chord

    def dimension_report(self) -> dict:
        """Basic dimensions the mass/aero/energy models actually use."""
        mb = self.mass_breakdown()
        return {
            "span_m": self.span_m,
            "chord_m": self.chord_m,
            "wing_area_m2": self.wing_area,
            "aspect_ratio": self.aspect_ratio,
            "wing_airfoil": self.wing_airfoil,
            "tail_arm_m": self.tail_arm_m,
            "hstab_span_m": self.hstab_span,
            "hstab_span_each_m": self.hstab_span,
            "hstab_chord_m": self.hstab_chord,
            "hstab_area_m2": self.hstab_area,
            "hstab_area_each_m2": self.hstab_area_each,
            "n_hstabs": int(config.N_HSTABS),
            "tail_layout": "split_t",
            "boom_spacing_m": self.boom_spacing,
            "outboard_panel_m": (self.span_m - self.boom_spacing) / 2.0,
            "taper_ratio": self.taper_ratio,
            "taper_start_frac": self.taper_start_frac,
            "tip_chord_m": self.tip_chord_m,
            "y_taper_m": self.y_taper_m,
            "washout_tip_deg": self.washout_tip_deg,
            "washout_start_frac": self.washout_start_frac,
            "y_washout_m": self.y_washout_m,
            "mac_m": self.mac_m,
            "vstab_height_m": self.vstab_height,
            "vstab_chord_m": self.vstab_chord,
            "vstab_area_each_m2": self.vstab_area_each,
            "hstab_z_m": self.hstab_z,
            "prop_le_offset_m": config.PROP_LE_OFFSET_M,
            "boom_aft_m": self.boom_aft_m,
            "boom_length_m": self.boom_length,
            "boom_x_front_m": self.boom_x_front,
            "vstab_te_x_m": self.vstab_te_x,
            "fuselage_length_m": self.fuselage_length_m,
            "fuselage_wetted_each_m2": self.fuselage_wetted_each_m2,
            "boom_diameter_mm": BOOM_DIAMETER_M * 1000.0,
            "elevator_frac": self.elevator_frac,
            "aileron_y_inner_m": self.aileron_y_inner(),
            "aileron_span_each_m": self.aileron_span_each_m(),
            "aileron_chord_frac": config.AILERON_CHORD_FRAC,
            "cells_on_aileron": self.cells_on_aileron(),
            "roll_rate_deg_s": self.roll_rate_deg_s(),
            "cn_beta": self.cn_beta(),
            "cn_r": self.cn_r(),
            "tail_volume_h": self.tail_volume_h(),
            "tail_volume_v": self.tail_volume_v_actual(),
            "vstab_area_total_m2": self.vstab_area_total,
            "static_margin": self.static_margin(),
            "n_cells": self.n_cells,
            "n_strings": self.n_mppts,
            "string_plan": self.string_plan_label(),
            "cells_per_string": self.cells_per_string,
            "n_packs": self.n_packs,
            "prop_diameter_in": self.prop_diameter_in,
            "prop_name": self.prop_name,
            "motor_name": self.motor_name,
            "incidence_wing_deg": self.wing_incidence_deg(),
            "incidence_hstab_deg": self.hstab_incidence_deg(),
            "mass_kg": self.mass_kg,
            "mass_breakdown_kg": mb,
            "v_stall_ms": self.stall_speed(),
            "v_min_ms": self.min_airspeed(),
            "v_mp_ms": self.min_power_speed(),
        }

    def to_asb(self, incidence: tuple[float, float] | None = None) -> asb.Airplane:
        af_w = asb.Airfoil(self.wing_airfoil)
        af_t = asb.Airfoil("naca0010")
        half_h = self.hstab_span / 2.0
        x_h = self.hstab_le_x()
        z_h = self.hstab_z
        y_tap = min(self.y_taper_m, self.span_m / 2.0)
        if incidence is None:
            i_w = self.wing_incidence_deg()
            i_t = self.hstab_incidence_deg()
        else:
            i_w, i_t = float(incidence[0]), float(incidence[1])
        y_wo = min(self.y_washout_m, 0.5 * self.span_m)
        i_tip = i_w - max(float(self.washout_tip_deg), 0.0)
        stations = [(0.0, self.chord_m, i_w)]
        if y_tap > 0.05 and abs(y_tap - self.span_m / 2.0) > 0.02:
            stations.append((y_tap, self.chord_m,
                             i_w - float(self.washout_deg_at_y(y_tap))))
        if (self._has_washout()
                and y_wo > 0.05
                and abs(y_wo - self.span_m / 2.0) > 0.03):
            stations.append((y_wo, self.chord_at_y(y_wo), i_w))
        cached_ail = getattr(self, "_aileron_y_inner_cache", None)
        y_ail = (float(cached_ail) if cached_ail is not None
                 else self._aileron_y_seed())
        stations.append((y_ail, self.chord_at_y(y_ail),
                         i_w - float(self.washout_deg_at_y(y_ail))))
        stations.append((self.span_m / 2.0, self.tip_chord_m, i_tip))
        stations.sort(key=lambda s: s[0])
        merged: list[tuple[float, float, float]] = []
        for y, ch, tw in stations:
            if merged and abs(y - merged[-1][0]) < 0.02:
                merged[-1] = (y, ch, tw)
            else:
                merged.append((y, ch, tw))
        hinge_a = 1.0 - config.AILERON_CHORD_FRAC
        xsecs = []
        for i, (y, ch, tw) in enumerate(merged):
            cs = []
            y_next = merged[i + 1][0] if i + 1 < len(merged) else y
            if y_next > y_ail - 1e-3 and y >= y_ail - 0.03:
                cs.append(asb.ControlSurface(
                    name="aileron", symmetric=False, hinge_point=hinge_a))
            xsecs.append(asb.WingXSec(
                xyz_le=[0.0, y, 0.0], chord=ch, twist=tw, airfoil=af_w,
                control_surfaces=cs))
        wing = asb.Wing(
            name="Main Wing",
            symmetric=True,
            xsecs=xsecs,
        )
        hinge_e = 1.0 - float(self.elevator_frac)
        elev_cs = [
            asb.ControlSurface(name="elevator", symmetric=True,
                               hinge_point=hinge_e),
            asb.ControlSurface(name="elevon", symmetric=False,
                               hinge_point=hinge_e),
        ]
        # Two identical T-tails, one per fuselage. Not a π-tail.
        y_b = self.boom_spacing / 2.0
        hstabs = []
        for sign in (-1.0, 1.0):
            y_c = sign * y_b
            hstabs.append(asb.Wing(
                name="H-stab",
                symmetric=False,
                xsecs=[
                    asb.WingXSec(xyz_le=[x_h, y_c - half_h, z_h],
                                 chord=self.hstab_chord, twist=i_t, airfoil=af_t,
                                 control_surfaces=elev_cs),
                    asb.WingXSec(xyz_le=[x_h, y_c + half_h, z_h],
                                 chord=self.hstab_chord, twist=i_t, airfoil=af_t),
                ],
            ))
        vstabs = []
        for sign in (-1.0, 1.0):
            y_v = sign * self.boom_spacing / 2.0
            vstabs.append(asb.Wing(
                name="V-stab",
                symmetric=False,
                xsecs=[
                    asb.WingXSec(xyz_le=[x_h, y_v, 0.0],
                                 chord=self.vstab_chord, airfoil=af_t),
                    asb.WingXSec(xyz_le=[x_h, y_v, self.vstab_height],
                                 chord=self.vstab_chord, airfoil=af_t),
                ],
            ))
        x_boom0 = self.boom_x_front
        x_vte = self.vstab_te_x
        x_wing_te = self.chord_m
        fuselages = [
            _fuselage_pod("fuselage_L", -y_b, self.prop_x, x_wing_te),
            _fuselage_pod("fuselage_R", y_b, self.prop_x, x_wing_te),
            _boom_fuselage("boom_L", -y_b, x_boom0, x_vte),
            _boom_fuselage("boom_R", y_b, x_boom0, x_vte),
        ]
        return asb.Airplane(
            name="solar-split-empennage",
            xyz_ref=[0.25 * self.mac_m, 0.0, 0.0],
            s_ref=float(self.wing_area),
            c_ref=float(self.mac_m),
            b_ref=float(self.span_m),
            wings=[wing, *hstabs, *vstabs],
            fuselages=fuselages,
        )
