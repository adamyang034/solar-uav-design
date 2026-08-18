# Solar UAV Design Toolchain

Models for an 81-hour (89 h with margin) solar-powered flight attempt in the
Mojave desert. Twin-boom, OV-10-style configuration, 6 m span / 12 kg limits.

## Status

- **Phase 1 — environment**: `solar_uav/environment.py`. Clear-sky
  plane-of-array irradiance at the mission site (pvlib/Ineichen), sun-angle
  and reflection (IAM) losses, design-day temperatures, NOCT-style cell
  temperature calibrated to 75 °C at solstice noon.
- **Phase 2 — components**: `solar_uav/components/`
  - `solar_array.py` — SunPower C60 electrical model, boost-MPPT string
    limit, wing/H-stab cell layout with bay/joint constraints.
  - `battery.py` — Upgrade Energy GOLD V1 6S2P bank: SOC window (20–100%),
    6 A/pack charge limit with CV taper, OCV + internal resistance.
  - `propeller.py` — APC PER3 archive plus Mejzlik 2-blade electric
    datasheets/performance maps, thrust/power interpolators with uncertainty.
    - `motor.py` — Hacker A40-12L V4 kv410 direct (default). Geared 10L/10S
      stay in the catalog for comparisons only.
  - `airfoils.py` — NeuralFoil polars (S4110, S4310, AG35, NACA 0010),
    AeroSandbox-native objects for the Phase 3/4 optimization.
- **Phase 3 — aircraft coupling**: `solar_uav/aircraft.py`. Twin-boom
  geometry (H-stab span = boom spacing), mass buildup from measured areal
  densities, NeuralFoil drag polar + induced + parasite, stall/min-power
  speeds, static margin (CG at c/4), elevator trim and pitch acceleration.
  AeroSandbox VLM / AeroBuildup / mesh inertia / XFoil are a conservative
  envelope (`solar_uav/asb_physics.py`): friendlier ASB numbers are discarded.
- **Phase 4 — energy closure + optimizer**: `solar_uav/mission.py` (24 h
  time march with 6 A/pack charge limit) and `solar_uav/optimize.py`
  (continuous aero variables; integer cells/packs/motor/ESC; inner prop pick).
  Objective: maximise energy margin above the 20% SOC floor, but only if the
  pack refills each afternoon (otherwise the 89 h mission ratchets empty).
  On the current model, **no design closes** under 12 kg / 6 m — night bus
  power and battery mass fight the wing areal density. See
  `outputs/phase4_candidates.csv`.
- **Phase 5 — uncertainty**: `solar_uav/monte_carlo.py`. Sobol sample of
  irradiance, cell temperature, array efficiency, mass growth, drag, APC
  thrust/power factors, avionics, and pack energy. Reports P(closure),
  P10/P50/P90 margin, tornado, and Spearman drivers.
- **Phase 6 — validation**: `solar_uav/validation.py`. Bench/flight
  protocols (panel, battery, thrust stand, glide polar). Drop measured
  CSVs in `data/validation/measured/`; the fitter recommends updates to
  the FLAGGED factors. A synthetic self-test checks the fitter without
  lab data.
- **CAD visualizer**: `solar_uav/cad.py` builds the twin-boom solid
  (AeroSandbox mesh + solar cells + props), writes STL / OpenSCAD, a
  three-view drawing, and `outputs/aircraft_viewer.html`.

```bash
.venv/bin/python scripts/validate_all.py    # Phases 1–2
.venv/bin/python scripts/eval_stability.py  # aileron / fin / loiter
.venv/bin/python scripts/run_asb_audit.py   # AeroSandbox vs handbook
.venv/bin/python scripts/run_phase34.py     # Phases 3–4 + optimizer
.venv/bin/python scripts/run_phase56.py     # Phases 5–6 + CAD
.venv/bin/python scripts/visualize.py       # refresh CAD and open the viewer
```

## Assumptions

All locked constants and **flagged assumptions** live in
`solar_uav/config.py` — grep for `FLAGGED` to review what still needs test
data or a decision (cell bin, OCV curve, pack DCIR, ESC/gearbox
efficiencies, prop-data uncertainty factors, ambient temps, etc.).
