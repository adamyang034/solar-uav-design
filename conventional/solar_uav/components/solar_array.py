"""Phase 2 — C60 solar array model: electrical output, string sizing under the
Genasun GVB-8 input ratings (buck/boost), mass, and geometric layout on the
wing. H-stab solar is off in this fork (`config.SOLAR_ON_HSTAB`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import config


# ---------------------------------------------------------------------------
# String sizing under the GVB-8 input ratings (buck and boost)
# ---------------------------------------------------------------------------
def vmp_cell_at_temp(t_cell_c: float, bin_name: str = config.CELL_BIN_DEFAULT) -> float:
    cell = config.C60_BINS[bin_name]
    return cell.v_mp + config.CELL_BETA_VMP * (t_cell_c - config.CELL_T_REF_C)


def voc_cell_at_temp(t_cell_c: float, bin_name: str = config.CELL_BIN_DEFAULT) -> float:
    cell = config.C60_BINS[bin_name]
    return cell.v_oc + config.CELL_BETA_VMP * (t_cell_c - config.CELL_T_REF_C)


def max_cells_per_string(bin_name: str = config.CELL_BIN_DEFAULT) -> int:
    """Longest series string the GVB-8 will take.

    Not a boost-only bus cap. Cold-cell Voc must stay under the recommended
    50 V STC Voc (stricter than the 60 V absolute input). STC string power
    must stay under the 210 W recommended panel rating. FLAGGED: other
    buck-boost MPPTs may allow more watts; keep the GVB number until that
    unit is named.
    """
    cell = config.C60_BINS[bin_name]
    v_cell_cold = voc_cell_at_temp(config.COLD_CELL_T_C, bin_name)
    n_voc = int(np.floor(config.MPPT_MAX_PV_VOC_V / max(v_cell_cold, 1e-9)))
    n_pwr = int(np.floor(config.MPPT_MAX_PANEL_W / max(cell.p_mp_w, 1e-9)))
    return max(1, min(n_voc, n_pwr))


# ---------------------------------------------------------------------------
# Electrical model
# ---------------------------------------------------------------------------
@dataclass
class SolarArray:
    """One MPPT per string. String lengths may differ (per-bay leftovers)."""

    n_strings: int | None = None
    cells_per_string: int | None = None
    string_lengths: tuple[int, ...] | None = None
    bin_name: str = config.CELL_BIN_DEFAULT

    def __post_init__(self):
        if self.string_lengths is None:
            if self.n_strings is None or self.cells_per_string is None:
                raise ValueError(
                    "provide string_lengths or n_strings+cells_per_string")
            self.string_lengths = tuple(
                [int(self.cells_per_string)] * int(self.n_strings))
        limit = max_cells_per_string(self.bin_name)
        over = [n for n in self.string_lengths if n > limit]
        if over:
            raise ValueError(
                f"string length {over} exceeds MPPT limit of {limit} "
                f"(GVB-8 cold Voc {config.MPPT_MAX_PV_VOC_V:.0f} V / "
                f"{config.MPPT_MAX_PANEL_W:.0f} W)")
        self.n_strings = len(self.string_lengths)
        self.cells_per_string = (self.string_lengths[0]
                                 if self.string_lengths else 0)

    @property
    def n_cells(self) -> int:
        return int(sum(self.string_lengths or ()))

    @property
    def cell(self) -> config.CellBin:
        return config.C60_BINS[self.bin_name]

    @property
    def area_m2(self) -> float:
        return self.n_cells * config.CELL_SIDE_M ** 2

    @property
    def mass_kg(self) -> float:
        cells = self.n_cells * (config.CELL_MASS_KG
                                + config.CELL_INTERCONNECT_MASS_KG)
        mppts = self.n_strings * config.MPPT_MASS_KG
        return cells + mppts

    def power_dc_w(self, poa_eff_w_m2, t_cell_c):
        """Array DC power at MPP (W). poa_eff already includes encapsulation
        transmission and IAM (from environment.poa_effective)."""
        poa = np.asarray(poa_eff_w_m2, dtype=float)
        t = np.asarray(t_cell_c, dtype=float)
        temp_factor = 1.0 + config.CELL_GAMMA_PMP * (t - config.CELL_T_REF_C)
        p = (self.n_cells * self.cell.p_mp_w * (poa / 1000.0)
             * temp_factor * config.WIRING_MISMATCH_SOILING_EFF)
        return np.clip(p, 0.0, None)

    def power_to_bus_w(self, poa_eff_w_m2, t_cell_c):
        """Power delivered to the 6S bus after MPPT conversion (W)."""
        return self.power_dc_w(poa_eff_w_m2, t_cell_c) * config.MPPT_EFFICIENCY

    def string_current_check(self) -> bool:
        """Genasun 8 A input limit vs one series string (Imp ~5.9 A)."""
        return self.cell.i_mp <= config.MPPT_MAX_INPUT_A


# ---------------------------------------------------------------------------
# Geometric layout: do the cells physically fit?
# ---------------------------------------------------------------------------
@dataclass
class PanelBay:
    """A region available for cells (one wing bay or the H-stab).

    Tapered outboard panels are still one bay (strings may run through the
    rectangular carry-through into the taper). `n_cells_fixed` is the
    column-by-column count that actually fits as chord shrinks.
    """
    name: str
    span_m: float          # spanwise extent available
    chord_m: float         # full local chord at the inboard edge
    usable_chord_frac: float
    n_cells_fixed: int | None = None

    @property
    def rows(self) -> int:
        return int(np.floor(self.chord_m * self.usable_chord_frac
                            / config.CELL_PITCH_M))

    @property
    def cols(self) -> int:
        return int(np.floor(self.span_m / config.CELL_PITCH_M))

    @property
    def capacity(self) -> int:
        if self.n_cells_fixed is not None:
            return int(self.n_cells_fixed)
        return self.rows * self.cols


def outboard_chord_m(s_from_boom: float, outboard_span_m: float,
                     chord_root_m: float, chord_tip_m: float,
                     taper_start_frac: float) -> float:
    """Local chord on an outboard panel. `s_from_boom` = 0 at the boom."""
    L = max(float(outboard_span_m), 0.0)
    f = float(np.clip(taper_start_frac, 0.0, 1.0))
    L_rect = f * L
    L_tap = L - L_rect
    if s_from_boom <= L_rect or L_tap <= 1e-12:
        return float(chord_root_m)
    t = (float(s_from_boom) - L_rect) / L_tap
    return float(chord_root_m + t * (chord_tip_m - chord_root_m))


def outboard_cell_capacity(outboard_span_m: float, chord_root_m: float,
                           chord_tip_m: float, taper_start_frac: float,
                           usable_chord_frac: float,
                           aileron_s_from_boom_m: float | None = None,
                           aileron_chord_frac: float = 0.0,
                           cells_on_aileron: bool = True) -> int:
    """Cells that fit on one outboard: full rows on the rectangle, then
    fewer rows as the taper drops below each cell pitch.

    Tapered wings keep cells off the aileron chord (forward rows only)
    outboard of `aileron_s_from_boom_m`. Rectangular wings may pack the
    full chord over the aileron (`cells_on_aileron=True`).
    """
    pitch = config.CELL_PITCH_M
    n = int(np.floor(max(outboard_span_m, 0.0) / pitch))
    cap = 0
    s_ail = (np.inf if aileron_s_from_boom_m is None
             else float(aileron_s_from_boom_m))
    for i in range(n):
        s_edge = min((i + 1) * pitch, outboard_span_m)
        c = outboard_chord_m(s_edge, outboard_span_m, chord_root_m,
                             chord_tip_m, taper_start_frac)
        frac = usable_chord_frac
        if (not cells_on_aileron) and s_edge > s_ail + 1e-9:
            frac = frac * max(0.0, 1.0 - float(aileron_chord_frac))
        cap += int(np.floor(c * frac / pitch))
    return cap


def wing_layout(span_m: float, chord_m: float, boom_spacing_m: float,
                hstab_span_m: float, hstab_chord_m: float,
                elevator_chord_frac: float = config.HSTAB_ELEVATOR_CHORD_FRAC,
                taper_ratio: float = 1.0,
                taper_start_frac: float = 1.0,
                aileron_y_inner_m: float | None = None,
                aileron_chord_frac: float = config.AILERON_CHORD_FRAC,
                cells_on_aileron: bool = True,
                ) -> dict:
    """Cell capacity of the aircraft, split into natural string bays.

    Wing is three pieces: inboard center panel and two outboard
    bays; strings must not cross the joints. Outboard taper is allowed to
    start partway along the panel; cells only occupy columns whose local
    chord still fits an integer number of pitches. H-stab solar is off
    unless `config.SOLAR_ON_HSTAB`. On a taper, aileron chord is not
    packed; on a rectangle, cells may cover the aileron.
    """
    outboard_span = max(0.0, (span_m - boom_spacing_m) / 2.0)
    lam = float(np.clip(taper_ratio, 0.15, 1.0))
    f = 1.0 if lam >= 1.0 - 1e-9 else float(np.clip(taper_start_frac, 0.0, 1.0))
    tip = lam * chord_m
    y_b = 0.5 * float(boom_spacing_m)
    s_ail = None
    if aileron_y_inner_m is not None:
        s_ail = max(0.0, float(aileron_y_inner_m) - y_b)
    out_cap = outboard_cell_capacity(
        outboard_span, chord_m, tip, f, config.WING_TOP_USABLE_CHORD_FRAC,
        aileron_s_from_boom_m=s_ail,
        aileron_chord_frac=aileron_chord_frac,
        cells_on_aileron=cells_on_aileron)
    bays = [
        PanelBay("wing_inboard", boom_spacing_m, chord_m,
                 config.WING_TOP_USABLE_CHORD_FRAC),
        PanelBay("wing_outboard_L", outboard_span, chord_m,
                 config.WING_TOP_USABLE_CHORD_FRAC, n_cells_fixed=out_cap),
        PanelBay("wing_outboard_R", outboard_span, chord_m,
                 config.WING_TOP_USABLE_CHORD_FRAC, n_cells_fixed=out_cap),
    ]
    if getattr(config, "SOLAR_ON_HSTAB", True):
        bays.append(PanelBay("hstab", hstab_span_m, hstab_chord_m,
                             (1.0 - elevator_chord_frac) * 0.9))
    return {b.name: b for b in bays}


def total_capacity(bays: dict) -> int:
    return sum(b.capacity for b in bays.values())


def pack_bay(capacity: int, max_n: int | None = None) -> list[int]:
    """Fill a bay with the fewest legal strings (greedy longest first)."""
    max_n = max_cells_per_string() if max_n is None else int(max_n)
    out: list[int] = []
    left = int(capacity)
    while left > 0 and max_n > 0:
        n = min(left, max_n)
        out.append(n)
        left -= n
    return out


def pack_layout(bays: dict, cells_per_string: int | None = None,
                one_per_bay: bool = False) -> dict:
    """Per-bay string list.

    one_per_bay: each bay is a single series string (capped at the Voc
    limit). Otherwise greedy-fill with the longest legal strings, or a
    uniform length if `cells_per_string` is set.
    """
    by_bay = {}
    lengths: list[int] = []
    limit = max_cells_per_string()
    for name, bay in bays.items():
        if one_per_bay:
            n = min(int(bay.capacity), limit)
            ls = [n] if n >= 1 else []
        elif cells_per_string:
            n = bay.capacity // cells_per_string
            ls = [int(cells_per_string)] * n
        else:
            ls = pack_bay(bay.capacity)
        by_bay[name] = ls
        lengths.extend(ls)
    lengths.sort(reverse=True)
    return {
        "by_bay": by_bay,
        "lengths": lengths,
        "total_strings": len(lengths),
        "total_cells": int(sum(lengths)),
    }


def feasible_string_plan(bays: dict, cells_per_string: int | None = None) -> dict:
    """How many complete strings fit in each bay (strings can't cross joints)."""
    packed = pack_layout(bays, cells_per_string)
    plan = {name: len(ls) for name, ls in packed["by_bay"].items()}
    plan["total_strings"] = packed["total_strings"]
    plan["total_cells"] = packed["total_cells"]
    return plan


# ---------------------------------------------------------------------------
# Geometric cell placement: overlap and planform containment
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CellRect:
    """Axis-aligned cell on a surface. x is chordwise from that surface's LE."""
    bay: str
    x0: float
    x1: float
    y0: float
    y1: float

    def overlaps(self, other: "CellRect", tol: float = 1e-6) -> bool:
        return (self.x0 < other.x1 - tol and other.x0 < self.x1 - tol
                and self.y0 < other.y1 - tol and other.y0 < self.y1 - tol)


def _usable_wing_frac(y_edge: float, aileron_y_inner_m: float,
                      aileron_chord_frac: float, cells_on_aileron: bool) -> float:
    if (not cells_on_aileron) and abs(y_edge) >= float(aileron_y_inner_m) - 1e-9:
        return max(0.0, 1.0 - float(aileron_chord_frac))
    return 1.0


def place_cells(span_m: float, chord_m: float, boom_spacing_m: float,
                hstab_span_m: float, hstab_chord_m: float,
                elevator_chord_frac: float,
                taper_ratio: float, taper_start_frac: float,
                aileron_y_inner_m: float, aileron_chord_frac: float,
                cells_on_aileron: bool, chord_at_y) -> list[CellRect]:
    """Every cell the capacity model claims, as rectangles in (x, y).

    x is from the local leading edge. y is from the centerline. Matches
    `outboard_cell_capacity` / inboard `rows*cols` so a geometry fail means
    the count itself put a cell off the planform.
    """
    pitch = config.CELL_PITCH_M
    side = config.CELL_SIDE_M
    cells: list[CellRect] = []
    y_b = 0.5 * float(boom_spacing_m)
    y_tip = 0.5 * float(span_m)

    n_in = int(np.floor(float(boom_spacing_m) / pitch))
    rows_in = int(np.floor(float(chord_m) * config.WING_TOP_USABLE_CHORD_FRAC
                           / pitch))
    y0_in = -y_b
    for col in range(n_in):
        y_c = y0_in + (col + 0.5) * pitch
        y0 = y_c - 0.5 * side
        y1 = y_c + 0.5 * side
        for row in range(rows_in):
            x_c = (row + 0.5) * pitch
            cells.append(CellRect("wing_inboard",
                                  x_c - 0.5 * side, x_c + 0.5 * side, y0, y1))

    outboard_span = max(0.0, y_tip - y_b)
    n_out = int(np.floor(outboard_span / pitch))
    lam = float(np.clip(taper_ratio, 0.15, 1.0))
    f = 1.0 if lam >= 1.0 - 1e-9 else float(np.clip(taper_start_frac, 0.0, 1.0))
    tip = lam * float(chord_m)
    for sign, bay in ((-1.0, "wing_outboard_L"), (1.0, "wing_outboard_R")):
        for col in range(n_out):
            s_edge = min((col + 1) * pitch, outboard_span)
            c_loc = outboard_chord_m(s_edge, outboard_span, float(chord_m),
                                     tip, f)
            y_edge = sign * (y_b + s_edge)
            frac = _usable_wing_frac(y_edge, aileron_y_inner_m,
                                     aileron_chord_frac, cells_on_aileron)
            rows = int(np.floor(c_loc * frac / pitch))
            y_c = sign * (y_b + (col + 0.5) * pitch)
            y0, y1 = (y_c - 0.5 * side, y_c + 0.5 * side)
            if y1 < y0:
                y0, y1 = y1, y0
            for row in range(rows):
                x_c = (row + 0.5) * pitch
                cells.append(CellRect(bay, x_c - 0.5 * side, x_c + 0.5 * side,
                                      y0, y1))

    if getattr(config, "SOLAR_ON_HSTAB", True):
        h_frac = (1.0 - float(elevator_chord_frac)) * 0.9
        n_h = int(np.floor(float(hstab_span_m) / pitch))
        rows_h = int(np.floor(float(hstab_chord_m) * h_frac / pitch))
        y0_h = -0.5 * float(hstab_span_m)
        for col in range(n_h):
            y_c = y0_h + (col + 0.5) * pitch
            y0 = y_c - 0.5 * side
            y1 = y_c + 0.5 * side
            for row in range(rows_h):
                x_c = (row + 0.5) * pitch
                cells.append(CellRect("hstab", x_c - 0.5 * side, x_c + 0.5 * side,
                                      y0, y1))
    return cells


def packing_geometry_reason(cells: list[CellRect], *, n_cells: int,
                            span_m: float, chord_at_y,
                            boom_spacing_m: float, hstab_span_m: float,
                            hstab_chord_m: float, elevator_chord_frac: float,
                            aileron_y_inner_m: float, aileron_chord_frac: float,
                            cells_on_aileron: bool) -> str | None:
    """Return a short fail reason, or None if the layout is clean."""
    side = config.CELL_SIDE_M
    pitch = config.CELL_PITCH_M
    if side > pitch + 1e-9:
        return "cell_larger_than_pitch"
    y_tip = 0.5 * float(span_m)
    y_b = 0.5 * float(boom_spacing_m)
    h_half = 0.5 * float(hstab_span_m)
    h_usable = float(hstab_chord_m) * (1.0 - float(elevator_chord_frac)) * 0.9

    if int(n_cells) > len(cells):
        return f"packed_{n_cells}_exceeds_{len(cells)}_slots"

    for c in cells:
        if c.x1 <= c.x0 + 1e-9 or c.y1 <= c.y0 + 1e-9:
            return f"degenerate_cell_{c.bay}"
        if c.bay == "hstab":
            if c.x0 < -1e-9 or c.x1 > h_usable + 1e-6:
                return "hstab_off_planform"
            if min(c.y0, c.y1) < -h_half - 1e-6 or max(c.y0, c.y1) > h_half + 1e-6:
                return "hstab_off_span"
            continue
        if min(c.y0, c.y1) < -y_tip - 1e-6 or max(c.y0, c.y1) > y_tip + 1e-6:
            return "wing_off_span"
        if c.bay == "wing_inboard":
            if min(c.y0, c.y1) < -y_b - 1e-6 or max(c.y0, c.y1) > y_b + 1e-6:
                return "inboard_past_boom"
        else:
            if max(abs(c.y0), abs(c.y1)) < y_b - 1e-6:
                return "outboard_into_inboard"
        for y in (c.y0, c.y1):
            frac = _usable_wing_frac(y, aileron_y_inner_m, aileron_chord_frac,
                                     cells_on_aileron)
            c_loc = float(chord_at_y(y)) * frac
            if c.x0 < -1e-9 or c.x1 > c_loc + 1e-6:
                return "wing_off_planform"

    n = len(cells)
    wing_bays = {"wing_inboard", "wing_outboard_L", "wing_outboard_R"}
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cells[i], cells[j]
            same = ((a.bay in wing_bays and b.bay in wing_bays)
                    or a.bay == b.bay)
            if same and a.overlaps(b):
                return f"overlap_{a.bay}_{b.bay}"
    return None

