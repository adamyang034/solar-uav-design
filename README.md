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
- **Phase 4 — energy closure + optimizer**: maximize the lower morning SOC,
  requiring next morning SOC not to decrease and retaining the 20% floor.
  `scripts/run_six_layout_study.py` now defaults to an AeroSandbox/IPOPT
  smooth surrogate followed by exact catalog-neighborhood verification.
  It relaxes prop diameter/pitch and pack count alongside geometry, then
  recomputes integer cell packing, battery behavior, and all existing gates.
  The previous differential-evolution search is retained with `--method de`;
  older standalone scripts such as `run_phase34.py` still use that path.
  The 89-hour trace is visualization, not an additional acceptance gate.
  See [surrogate search](docs/surrogate-search.md) and
  [morning SOC and yaw](docs/morning-soc-and-yaw.md).
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
  three-view drawing, and `outputs/aircraft_viewer.html`. The four-configuration
  compare view (π-tail, split empennage, conventional, conventional rectangular) is
  `outputs/compare/aircraft_viewer.html` and is what GitHub Pages serves.
  The rectangular option fixes wing taper to 1 and geometric twist to 0;
  the original conventional option still optimizes both. Each has two battery options.
  The engineering workspace includes a read-only overview, baseline comparisons,
  CAD and mass breakdowns, energy histories, requirement headroom, and source
  provenance. See [AircraftView](docs/aircraftview.md) for rebuilding and verification.

```bash
.venv/bin/python scripts/validate_all.py    # Phases 1–2
.venv/bin/python scripts/eval_stability.py  # aileron / fin / loiter
.venv/bin/python scripts/run_asb_audit.py   # AeroSandbox vs handbook
.venv/bin/python scripts/run_phase34.py     # Phases 3–4 + optimizer
.venv/bin/python scripts/run_phase56.py     # Phases 5–6 + CAD
.venv/bin/python scripts/visualize.py       # refresh CAD and open the viewer
.venv/bin/python scripts/run_six_layout_study.py --output outputs/new_surrogate_run
```

## Assumptions

All locked constants and **flagged assumptions** live in
`solar_uav/config.py` — grep for `FLAGGED` to review what still needs test
data or a decision (cell bin, OCV curve, pack DCIR, ESC/gearbox
efficiencies, prop-data uncertainty factors, ambient temps, etc.).
