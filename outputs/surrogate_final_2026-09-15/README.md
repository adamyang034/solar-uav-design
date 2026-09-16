# Final Surrogate-Search Validation

The six-case runner now defaults to a differentiable response-surface search with
AeroSandbox/IPOPT, followed by original-model checks of nearby real catalog props,
allowed integer pack counts, and exact cell packing. See ../../docs/surrogate-search.md.

## Results

All six winners passed fresh energy, hard-constraint, and applicable yaw checks.
The fresh viewer simulations reproduce the final search values to floating-point
precision. These remain preliminary model passes, not flight qualification.

| Layout | Battery | Packs | Mass (kg) | Morning SOC (%) | Reserve above 20% (Wh) |
|---|---|---:|---:|---:|---:|
| Single empennage / pi-tail | GOLD V1 | 3 | 10.843 | 26.1584 | 89.24 |
| Split empennage | GOLD V1 | 3 | 10.135 | 31.4475 | 165.87 |
| Conventional | GOLD V1 | 3 | 9.840 | 37.6531 | 255.79 |
| Single empennage / pi-tail | 6S 36 Ah | 2 | 11.045 | 25.7141 | 83.92 |
| Split empennage | 6S 36 Ah | 2 | 10.363 | 30.7844 | 158.38 |
| Conventional | 6S 36 Ah | 2 | 10.207 | 36.4487 | 241.56 |

The split/36 Ah result improved from 30.5898% to 30.7844% morning SOC (about
2.86 Wh extra reserve). The other five retained their reverified previous winners.

## Runtime

| Case | New run (s) | Prior DE run (s) | Exact single-prop evaluations |
|---|---:|---:|---:|
| Single / GOLD | 76.2 | 436.0 | 259 |
| Split / GOLD | 78.7 | 1157.2 | 273 |
| Conventional / GOLD | 75.4 | 387.2 | 295 |
| Single / 36 Ah | 57.5 | 2235.9 | 239 |
| Split / 36 Ah | 66.8 | 404.9 | 269 |
| Conventional / 36 Ah | 62.1 | 322.4 | 323 |
| Total | 416.9 | 4943.6 | 1658 |

Total recorded case runtime: about 7.0 minutes versus 82.4 minutes previously.
These timings include each case's catalog loading and search, but not viewer
generation, development trials, or browser verification. The new runs warm-start
from the previous optimized geometries. This is not a controlled cold-start
benchmark or a guarantee of the same runtime reduction on future designs.

## Method and Limitations

- 72 additional stratified geometry samples per case, three refinement rounds,
  up to three starts per manufacturer per round, seed 7, six workers.
- Neighbor windows: +/-2.5 inches diameter and +/-2.0 inches pitch, plus nearest
  available SKUs for sparse windows. All catalog variants in the window are tested.
- Twenty selected proposals came from successful IPOPT solves. Sixteen
  manufacturer/round attempts instead used the documented exact-neighborhood
  fallback around known samples. Those fallbacks are not claimed as solver optima.
- The fit is approximate, particularly across cell-packing changes; holdout
  errors, solver failures, trust radii, and predicted/exact scores are recorded in
  each `.surrogate.json`. Fitted scores are never aircraft acceptance results.
- The 16x12E power-map warnings on twin-fuselage designs remain. Structural and
  hardware qualification remain separate; no requirements were loosened.
- Earlier development trials are retained in the other `surrogate_*` directories
  and labeled superseded. This directory contains the final implementation run.

## Verification

The regression suite passes for all three layouts, including analytic-gradient
checks, a known AeroSandbox optimum, catalog-only neighbors, allowed pack counts,
preloaded-map behavior, numerical-bound handling, and morning-SOC/yaw checks.
AircraftView browser checks cover all six selectors, nonblank moving 3D models,
89-hour trace endpoints and chart data, desktop/mobile screenshots, and script errors.

Exact CSVs remain compatible with the existing viewer builder. The published
viewer and fresh verification summary are in ../compare/aircraft_viewer.html and
../compare/study_results.json.
