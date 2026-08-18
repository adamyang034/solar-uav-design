"""Single source of truth for locked design constants and flagged assumptions.

Every value marked FLAGGED is an assumption awaiting test data or a user
decision; grep for "FLAGGED" to review them all before trusting results.
Sources are cited inline (datasheet, user requirement, or estimate).
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Mission (user requirements + design criteria sheet)
# ---------------------------------------------------------------------------
FT_TO_M = 0.3048
# El Mirage Race Course (user). USGS El Mirage Lake ~2837 ft MSL.
LATITUDE_DEG = 34.646849
LONGITUDE_DEG = -117.605977
SITE_ALTITUDE_M = 2837.0 * FT_TO_M   # lake bed, ~864.7 m MSL
ALTITUDE_M = SITE_ALTITUDE_M         # pvlib uses field elevation (slightly
                                     # less GHI than 400 ft AGL — conservative)
TIMEZONE = "America/Los_Angeles"

DESIGN_MISSION_HOURS = 89.0       # 81 h record + 10% margin (M1, M2)
MISSION_WINDOW = ("2027-05-01", "2027-07-31")   # May-July window (M6)
SOLSTICE_DATE = "2027-06-21"      # summer solstice, longest day

MTOW_MAX_KG = 12.0                # user decision (supersedes sheet P2)
WINGSPAN_MAX_M = 6.0              # user constraint
CRUISE_ALT_AGL_M = 400.0 * FT_TO_M  # density at 400 ft AGL. Ground effect
                                    # is not credited.
MIN_AIRSPEED_WIND_MS = 7.7        # 15 kt crosswind floor (M13)
STALL_MARGIN_FACTOR = 1.2         # never-below stall margin (hard floor)
LOITER_STALL_FACTOR = 1.3         # flown speed: banked loiter needs more than
                                  # 1.2 Vs (rev6 notes). Energy march pays this.
V_CRUISE_START_MS = 12.0          # min-power search starts here (typical loiter)
V_CRUISE_TOL_MS = 0.01            # flown-speed resolution [m/s]
CLIMB_RATE_REQ_MS = 1.5           # FLAGGED: replaces 97 N thrust requirement

AVIONICS_POWER_W = 5.0            # measured by team (continuous, day and night)

# AeroSandbox conservative envelope. Friendlier ASB numbers are discarded.
ASB_VLM_IN_SCORING = True         # downwash k and induced e vs handbook
ASB_AEROBUILDUP_SC = True         # Cl_p, Cn_β, Cn_r envelope
ASB_MESH_INERTIA = True           # thin-shell Iyy vs lumped pitch inertia
ASB_XFOIL_CD = True               # inflate NeuralFoil cd if XFoil is draggier

# ---------------------------------------------------------------------------
# Solar cells — Maxeon Gen 5 (datasheet, unlaminated, STC)
# Kn bin (user): most conservative of Mn1 / Ln / Kn.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CellBin:
    name: str
    p_mp_w: float
    v_mp: float
    i_mp: float
    v_oc: float
    i_sc: float
    efficiency: float

CELL_BINS = {
    "Mn1": CellBin("Mn1", 6.47, 0.630, 10.28, 0.731, 10.98, 0.251),
    "Ln": CellBin("Ln", 6.33, 0.620, 10.22, 0.730, 10.96, 0.245),
    "Kn": CellBin("Kn", 5.84, 0.591, 9.88, 0.730, 10.71, 0.226),
}
C60_BINS = CELL_BINS              # leftover name; this fork is Gen 5
CELL_BIN_DEFAULT = "Kn"           # user: conservative bin

CELL_GAMMA_PMP = -0.0029          # power temp coefficient, 1/degC (datasheet)
CELL_BETA_VMP = -0.00174          # voltage temp coefficient, V/degC (datasheet)
CELL_SIDE_M = 0.1617              # 161.7 mm square bounding box (datasheet)
CELL_AREA_M2 = 0.02583            # 258.3 cm² datasheet; not side² (cropped corners)
CELL_PITCH_M = 0.167              # FLAGGED: 161.7 mm + 5.3 mm gap (C60 used 5 mm)
CELL_MASS_KG = 0.0116             # datasheet ~11.6 g
CELL_INTERCONNECT_MASS_KG = 0.0015  # FLAGGED: keep C60 tab budget; datasheet tab 0.5 g
CELL_T_MAX_C = 75.0               # user: peak cell temp at solstice noon, static
CELL_T_REF_C = 25.0

ENCAPSULATION_TRANSMISSION = 0.97   # FLAGGED: thin fiberglass, 2-5% typical.
                                    # Mass is already inside wing areal density.
WIRING_MISMATCH_SOILING_EFF = 0.965  # FLAGGED: combined array losses

# ---------------------------------------------------------------------------
# MPPT — Genasun GVB-8-Li-25.0V boost (datasheet)
# ---------------------------------------------------------------------------
MPPT_EFFICIENCY = 0.95            # criteria E9 (datasheet says 95-98%)
MPPT_MAX_INPUT_A = 8.0
# FLAGGED (user 2026-08-17): Gen 5 Kn Imp 9.88 A / Isc 10.71 A exceed the
# GVB-8 8 A input. Not a search hard-fail for this study (optimistic).
MPPT_CURRENT_OVERLOAD_OK = True
MPPT_MAX_STRING_VMP = 20.0        # recommended max panel Vmp (datasheet)
MPPT_MASS_KG = 0.108              # PCB version (housed = 0.185)
BUS_V_MIN = 19.2                  # 6S at 3.2 V/cell (criteria E1/E4)
BUS_V_NOM = 22.2
BUS_V_MAX = 25.2
STRING_V_MARGIN = 0.95            # FLAGGED: keep string Vmp below margin*bus_min
COLD_CELL_T_C = 10.0              # FLAGGED: coldest operating cell temp (dawn)

# ---------------------------------------------------------------------------
# Battery — Upgrade Energy GOLD V1 6S2P Amprius SA03 (product page)
# ---------------------------------------------------------------------------
PACK_ENERGY_WH = 483.0
PACK_CAPACITY_AH = 23.68
PACK_MASS_KG = 1.278
PACK_CHARGE_MAX_A = 6.0           # hard datasheet limit (~0.25C)
PACK_DISCHARGE_SUSTAINED_W = 313.0
PACK_BURST_A = 72.0
SOC_MIN = 0.20                    # user: 80% usable window
PACK_R_INTERNAL_OHM = 0.045       # FLAGGED: estimate, no DCIR on datasheet
N_SERIES_CELLS = 6

# ---------------------------------------------------------------------------
# Propulsion — Hacker geared motors (datasheets) + APC / Mejzlik props
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MotorSpec:
    name: str
    kv_rpm_per_v: float           # motor Kv, before gearbox
    r_ohm: float
    i0_a: float                   # idle current, measured at i0_v_ref
    i0_v_ref: float
    mass_kg: float                # complete unit (incl. gearbox if any)
    gear_ratio: float
    max_power_w: float

MOTOR_CATALOG = {
    "A40-12L-V4-kv410-direct": MotorSpec(
        "A40-12L V4 kv410 (direct drive)", 410.0, 0.039, 1.04, 8.4, 0.275, 1.0, 1100.0),
    # Compare-only. Not used by search() / search_continuous().
    "A40-10L-V2-kv1100-6.7PG": MotorSpec(
        "A40-10L V2 kv1100 + 6.7:1 PG", 1100.0, 0.019, 1.7, 8.4, 0.315, 6.7, 2200.0),
    "A40-10S-V4G-kv1600-6.7PG": MotorSpec(
        "A40-10S V4G kv1600 + 6.7:1 PG", 1600.0, 0.012, 2.75, 8.4, 0.247, 6.7, 1500.0),
}
MOTOR_DEFAULT = "A40-12L-V4-kv410-direct"
# Geared A40-10L / 10S stay in the catalog for compare scripts only.
# The optimizer does not search them.
N_MOTORS = 2                      # one per boom (user)
GEARBOX_EFFICIENCY = 0.96         # FLAGGED: typical planetary, not on datasheet
ESC_EFFICIENCY = 0.95             # FLAGGED
ESC_DUTY_MIN = 0.50               # FLAGGED: below ~50% duty, real ESCs sag;
                                  # the 95% eta assumption does not hold.

# Free-Kv search: rewind of the A40-12L stator (same iron/mass).
# Ri ∝ 1/Kv^2, I0 ∝ Kv from constant friction/iron at the 8.4 V test point.
MOTOR_SCALE_REF = "A40-12L-V4-kv410-direct"
KV_GRID = tuple(range(180, 901, 20))   # direct-drive rpm/V on 6S
PROP_THRUST_DERATE = 0.92         # FLAGGED: APC vortex-theory data optimism,
PROP_POWER_INFLATE = 1.08         # FLAGGED: to be calibrated vs UIUC tests
# Use published T,P when the (V, RPM) point is on a map. Similarity
# (C_T(J) ρ n² D⁴) is a check only. Flag if they disagree by more than this.
PROP_SANITY_REL = 0.15

# ---------------------------------------------------------------------------
# Mass model (user-provided; prototype build table for fixed masses)
# ---------------------------------------------------------------------------
WING_AREAL_MASS = 0.84            # kg/m^2 of wetted area, incl. encapsulation,
                                  # excl. solar cells (user). FLAGGED: flat
                                  # density, no spar-span scaling correction yet.
TAIL_AREAL_MASS = 0.44            # kg/m^2 wetted, H-stab and V-stabs (π-tail)
# 1.5 in OD carbon tube (user, 2026-08-16). Was 0.410 kg/m Ø24 mm.
BOOM_MASS_PER_M = 0.290           # kg/m, wing c/4 → V-stab TE
BOOM_DIAMETER_M = 1.5 * 0.0254    # 38.1 mm OD; parasite drag uses this

FIXED_MASSES_KG = {
    "avionics": 0.300,            # prototype build table
    "power_boards": 0.100,
    "servos": 0.080,
    "escs": 0.060,
    "wiring": 0.096,
    "fuselages": 0.200,           # FLAGGED: prototype values, revisit at full scale
    "superstructures": 0.200,
    "boom_vstab_interfaces": 0.100,
    "vstab_hstab_interfaces": 0.060,
}

# ---------------------------------------------------------------------------
# Geometry / layout (user)
# ---------------------------------------------------------------------------
# 167 mm pitch already includes cell size + gap. Two Gen 5 rows need
# 334 mm of chord. The top surface is fully packable (no extra usable-frac
# knockdown). H-stab still excludes the elevator separately. Chord floor
# is one cell row, not a full Voc-legal string.
WING_TOP_USABLE_CHORD_FRAC = 1.0
HSTAB_ELEVATOR_CHORD_FRAC = 0.30    # FLAGGED: optimizer variable later; keep-out
TAIL_VOLUME_H = 0.50                # FLAGGED: historical for this class
TAIL_VOLUME_V = 0.030               # total, both V-stabs together (user).
                                    # Was 0.040, 0.018, 0.035. Not per-fin.
                                    # No extra π-tail endplate credit.
# π-tail: H-stab on the V-stab tips, shared tail arm. Sv = V_V S b / l_t.
STATIC_MARGIN_TARGET = 0.12         # FLAGGED: CG at quarter chord assumption
STATIC_MARGIN_MIN = 0.08            # FLAGGED: lower bound for "reasonable" SM
ELEVATOR_MAX_DEG = 15.0             # FLAGGED: max elevator for trim/pitch
PITCH_ACCEL_MIN_RAD_S2 = 0.30       # FLAGGED: ~20 deg in 1.5 s from rest
HSTAB_AR = 4.5                      # FLAGGED: H-stab aspect ratio
VSTAB_AR = 1.5                      # per V-stab (user). Was 2.5.
PROP_LE_OFFSET_M = 0.70             # prop plane ahead of wing LE (user)
# Fuselage pod: trailing edge of the main wing → prop disk.
# CAD at L = 980 mm: Swet = 173128.421 mm² (one pod). Scale linearly with
# length at constant section (motor/spinner girth does not grow with chord).
FUSELAGE_LENGTH_REF_M = 0.980
FUSELAGE_WETTED_REF_MM2 = 173128.421
FUSELAGE_WETTED_REF_M2 = FUSELAGE_WETTED_REF_MM2 * 1e-6

# Lateral/directional (rev6). No rudder: yaw is differential thrust.
# No dihedral (user omitted): spiral mode is not claimed stable.
AILERON_CHORD_FRAC = 0.25           # local chord; FLAGGED typical
AILERON_TIP_KEEP_OUT_M = 0.04       # no surface in the last 4 cm of tip
AILERON_MAX_DEG = 20.0              # FLAGGED: roll-rate sizing deflection
ELEVON_ROLL_DEG = 20.0              # split elevator; cruise trim ≈ 0 so this
                                    # is available for roll
ROLL_RATE_MIN_DEG_S = 35.0          # acceptance: ~20 deg bank in ~1 s
ROLL_DAMPING_EXTRA = 1.15           # FLAGGED: inflate |Cl_p| so rate is harder
FIN_SIDEWASH_ETA = 0.90             # FLAGGED: no endplate credit; some sidewash
# Weathercock / yaw-damping floors are off (user): differential thrust
# is the yaw effector. Derivatives are still computed and reported.
REQUIRE_YAW_STABILITY = False
CN_BETA_MIN = 0.10                  # /rad; not enforced while REQUIRE_YAW_STABILITY is False
CN_R_ABS_MIN = 0.030                # |Cn_r|; not enforced while REQUIRE_YAW_STABILITY is False
YAW_TRIM_SIDESLIP_DEG = 5.0         # differential-thrust vs this β
# Steady yaw rate from loiter-preserving ΔT vs Cn_r (roll-helix analog).
# 5 deg/s unwinds the 5° case in ~1 s. Motor spool-up is not modelled.
YAW_RATE_MIN_DEG_S = 5.0            # FLAGGED: settled DT yaw vs damping
# No geometric dihedral. Autopilot must hold spiral with aileron/elevon.

# ---------------------------------------------------------------------------
# Optimizer: continuous variables (low, high, start)
# Integer / catalog stay discrete: n_cells (packing), n_packs, motor, ESC.
# Props stay an inner discrete pick. User-locked values are noted.
# ---------------------------------------------------------------------------
# Each triple is (low, high, start). start must lie in [low, high].
CONTINUOUS = {
    # User: span ≤ 6 m. Start at the cap — every honest grid preferred it.
    "span_m": (4.50, WINGSPAN_MAX_M, WINGSPAN_MAX_M),
    # User: 300–520 mm (not 4× Gen 5 pitch). Start 340 mm (two Gen 5 rows).
    "chord_m": (0.300, 0.520, 0.340),
    # User: start 0.90 m. Short arm grows the H-stab; long arm is boom mass.
    "tail_arm_m": (0.80, 2.00, 0.90),
    # V-stab AC arm, clamped ≥ H-stab arm. Held out of the current DE vector.
    "vstab_arm_m": (0.80, 3.00, 0.90),
    # 8–17 inboard cell pitches. Start 10 pitches (1.30 m).
    "boom_spacing_m": (8 * CELL_PITCH_M, 17 * CELL_PITCH_M, 10 * CELL_PITCH_M),
    # 0.40 was the old grid floor (0.35 tip on 310 mm is under one cell).
    "taper_ratio": (0.40, 1.00, 0.60),
    "taper_start_frac": (0.00, 1.00, 0.50),
    "washout_tip_deg": (0.00, 5.00, 0.00),
    "washout_start_frac": (0.00, 1.00, 0.00),
    "elevator_frac": (0.22, 0.40, 0.34),
    # User: start 12 m/s, 0.01 m/s resolution. Nested 1-D search, not DE.
    # Still floored by 1.3 Vs / 15 kt.
    "v_cruise_ms": (8.00, 18.00, V_CRUISE_START_MS),
    # Held at start in the current search (not in the DE vector).
    "hstab_ar": (3.50, 6.00, HSTAB_AR),
    "vstab_ar": (1.50, 3.50, VSTAB_AR),
    "aileron_chord_frac": (0.20, 0.30, AILERON_CHORD_FRAC),
}

for _k, (_lo, _hi, _x0) in CONTINUOUS.items():
    if not (_lo <= _x0 <= _hi):
        raise ValueError(f"CONTINUOUS[{_k!r}] start {_x0} not in [{_lo}, {_hi}]")

OPT_KEYS = (
    "span_m", "chord_m", "tail_arm_m", "boom_spacing_m",
    "taper_ratio", "taper_start_frac",
    "washout_tip_deg", "washout_start_frac", "elevator_frac",
)
OPT_START = {k: CONTINUOUS[k][2] for k in OPT_KEYS}

SPAN_BOUNDS_M = CONTINUOUS["span_m"][:2]
CHORD_BOUNDS_M = CONTINUOUS["chord_m"][:2]
TAIL_ARM_BOUNDS_M = CONTINUOUS["tail_arm_m"][:2]
BOOM_SPACING_BOUNDS_M = CONTINUOUS["boom_spacing_m"][:2]
TAPER_RATIO_BOUNDS = CONTINUOUS["taper_ratio"][:2]
TAPER_START_BOUNDS = CONTINUOUS["taper_start_frac"][:2]
WASHOUT_TIP_BOUNDS_DEG = CONTINUOUS["washout_tip_deg"][:2]
WASHOUT_START_BOUNDS = CONTINUOUS["washout_start_frac"][:2]
ELEVATOR_FRAC_BOUNDS = CONTINUOUS["elevator_frac"][:2]
V_CRUISE_BOUNDS_MS = CONTINUOUS["v_cruise_ms"][:2]

# Legacy discrete grids (search() exhaustive path only).
SPAN_GRID_M = (4.5, 5.0, 5.5, 6.0)
CHORD_GRID_M = (0.31, 0.36, 0.40, 0.45, 0.52)
TAIL_ARM_GRID_M = (0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.45, 1.60, 1.80, 2.00)
PACK_GRID = (2,)                   # user: two packs in parallel, no third
CELLS_PER_STRING_GRID = (12, 16, 20, 24, 29)
ELEVATOR_FRAC_GRID = (0.22, 0.28, 0.34)
TAPER_RATIO_GRID = (1.0, 0.60, 0.40)
TAPER_START_FRAC_GRID = (0.0, 0.50, 1.0)
WASHOUT_TIP_DEG_GRID = (0.0, 2.0, 3.5, 5.0)
WASHOUT_START_FRAC_GRID = (0.0, 0.35, 0.70)
BOOM_SPACING_GRID_M = (1.30, 1.56, 1.69, 2.08)
# Lower bound skips park-flyer props. No upper cap: climb + cruise
# feasibility decide, not the A40 "props to 23 in" marketing line.
PROP_DIAMETER_IN_RANGE = (16.0, None)

# ---------------------------------------------------------------------------
# Environment / uncertainty
# ---------------------------------------------------------------------------
T_AMB_MIN_C = 24.0                # FLAGGED: hot design-day dawn. El Mirage
                                  # June dawn is often cooler / denser; 24 °C
                                  # is conservative for night aero.
T_AMB_MAX_C = 40.0                # FLAGGED: hot afternoon. El Mirage race
                                  # days can exceed this; 40 °C is not a
                                  # desert-high. Revisit if cells run hotter.
IRRADIANCE_SIGMA = 0.03           # FLAGGED: 1-sigma clear-sky model + haze

# Phase 5 — truncated-normal sample specs (mean, sigma, lo, hi).
# Means sit on the current model / FLAGGED factors so MC replaces stacked
# extra conservatism rather than piling on top of it.
MC_N_SAMPLES = 256
MC_SEED = 7
MC_IRRADIANCE = (1.00, IRRADIANCE_SIGMA, 0.88, 1.08)
MC_T_CELL_K = (1.00, 0.10, 0.70, 1.30)          # NOCT k; <1 = flight cooling
MC_T_CELL_OFFSET_C = (0.0, 3.0, -8.0, 8.0)
MC_ARRAY_EFF = (1.00, 0.03, 0.90, 1.08)         # extra on wiring/mismatch
MC_MASS = (1.02, 0.05, 0.92, 1.18)              # slight growth bias
MC_DRAG = (1.00, 0.08, 0.85, 1.25)
MC_PROP_THRUST = (PROP_THRUST_DERATE, 0.04, 0.80, 1.02)
MC_PROP_POWER = (PROP_POWER_INFLATE, 0.04, 0.98, 1.22)
MC_AVIONICS_W = (AVIONICS_POWER_W, 0.80, 4.0, 8.0)
MC_PACK_ENERGY = (1.00, 0.03, 0.90, 1.05)

# Search start is OPT_START (DE seed). REF_* seeds CAD until a Gen 5
# search writes a winner. One series string per bay, Voc < 19.2 V,
# 2 packs, 12L direct.
REF_SPAN_M = 6.0
REF_CHORD_M = 0.340
REF_TAIL_ARM_M = 0.90
# Co-located V-stab (mass minimum).
REF_VSTAB_ARM_M = REF_TAIL_ARM_M
REF_N_PACKS = 2
REF_ELEVATOR_FRAC = 0.34
REF_TAPER_RATIO = 0.60
REF_TAPER_START_FRAC = 0.50
REF_WASHOUT_TIP_DEG = 0.0
REF_WASHOUT_START_FRAC = 0.0
REF_BOOM_SPACING_M = 10 * CELL_PITCH_M
REF_ONE_STRING_PER_BAY = True
REF_MOTOR = MOTOR_DEFAULT
REF_PROP = "16x12E"
