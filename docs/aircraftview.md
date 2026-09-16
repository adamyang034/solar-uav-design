# AircraftView Engineering Workspace

AircraftView is a read-only review of eight calculated layout/battery cases.
The engineering interface is authored in `scripts/engineering_view.html` and
`scripts/aircraft_view/`; `scripts/build_compare_viewer.py` regenerates the served
files in `outputs/compare/`. No optimization or physics model was changed for
this redesign.

## Review Views

- Overview: morning SOC, reserve above the floor, mass/headroom, night bus power,
  lift/drag, battery energy, actual CAD mesh, critical requirements and case ranking.
- Compare: select any combination of the eight cases, choose a baseline and view
  absolute values, unit-aware differences or both. Positive does not always mean
  better: only unambiguous performance directions receive green/red coloring.
- Geometry: native generated mesh, camera presets and layers, planform dimensions,
  modeled mass ledger, illustrative inertia and airfoil sections.
- Mass breakdown: total mass, takeoff limit/headroom and battery fraction; whole-
  aircraft allocation pie followed by component pies and expandable constituent
  tables. Select a portion to jump to its detail; units toggle between kg and g.
- Energy: scored morning-cycle quantities separated from the 89-hour display,
  power histories, battery/controller inputs and night drag budget.
- Requirements: model limits, calculated values, dimensional headroom, tolerances,
  and pass/fail/not-evaluated status. These are not structural FoS margins.
- Model & sources: source CSV/manifest, file and current model-source hashes,
  search/recomputed SOC agreement, assumptions, input values and search bounds.

The default interface is monochrome. Color identifies plotted series, CAD
components, statuses and meaningful comparison differences. Light/dark theme is
stored locally. Configuration and view are encoded in the URL, so a link returns
to the same selection. CAD is read-only: legacy browser-only layout and mass edits
are intentionally not consumed as results.

## Data Contract

`engineering_snapshot.py` derives review metadata from the selected `Design`,
active configuration and actual mission acceptance thresholds. Each displayed
case is reconstructed and re-simulated by the existing builder. No stale formatted
overview strings are used as numerical sources. The snapshot retains full-precision
values; presentation rounding does not determine pass/fail.

`mass_allocation.py` derives the mass page from `Design.mass_breakdown()` and the
configured fixed budgets, not from CAD placement lumps. It uses consistent
airframe, battery, solar/power, propulsion and avionics/controls categories across
all layouts. Solar cells and interconnects are separate from airframe structure;
fixed items are assigned once by function. Parent/child sums and the final mass
are checked when building. Detailed spar/rib/fastener masses are not invented.
Identical packs, motors, propellers and controllers use equal per-item allocations.

The snapshot source hash covers the candidate CSV. The model-source hash covers
the current layout package's Python files, not the complete external data/runtime
environment or a historical search-code revision. Run metadata comes from its
saved manifest. The displayed reconstruction check is not empirical validation.

Exports include selected-case JSON (full data/provenance), selected-comparison CSV
(absolute values and provenance), and the actual airframe STL. CSV always exports
unrounded absolute values, regardless of the current delta-display setting.

Model-feasible does not mean flight-qualified. Structural strength, buckling and
aeroelasticity remain explicitly unassessed. Aerodynamic stability's assumed
quarter-chord CG is distinguished from illustrative CAD component positions.
The extended trace starts at full charge and is not the morning-cycle acceptance
test. The old standalone layout viewers are not modified by this redesign.

## Build and Verify

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python scripts/build_compare_viewer.py --results-dir outputs/surrogate_final_2026-09-15 --rectangular-results-dir outputs/rectangular_2026-09-15
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/check_engineering_view.cjs http://127.0.0.1:8765/aircraft_viewer.html outputs/engineering_review_2026-09-15/qa
node tests/check_mass_view.cjs 'http://127.0.0.1:8765/aircraft_viewer.html?cfg=conventional__6s_36ah&view=mass' outputs/engineering_review_2026-09-15/mass_qa
```

Browser verification requires Playwright, Chrome and Sharp. It checks every case
and view, source agreement, real CAD pixels, camera movement, chart coordinates,
exports, comparisons, filters, dark theme and 390/768/1024/1920-pixel layouts.
Generated UI assets and the icon license live in `outputs/compare/lib/review/`,
which the existing GitHub Pages workflow publishes with the bundled libraries.
