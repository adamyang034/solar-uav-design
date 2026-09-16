# Differentiable Surrogate Search

## What Was Slow

The previous production search used differential evolution for ten geometry
coordinates, separately for two and three battery packs. Every surviving geometry
ran an inner comparison of the 51 filtered catalog propellers. It was not a full
Cartesian grid of all variables: cell counts came from geometry, cruise speed used
a nested numerical search, and the motor was fixed. Propeller performance maps
were normally cached, but their performance was still evaluated repeatedly.

## New Six-Case Default

1. Load catalog maps once in the parent and distribute them to workers. This also
   avoids concurrent writes to the vendor's local catalog index.
2. Reevaluate up to twelve previous leading designs with the current physics.
   Old mission scores are not imported as training labels or accepted results.
3. Sample every catalog prop at the incumbent geometry and allowed pack counts,
   once, plus 72 stratified geometry samples, half global and half local.
4. Fit smooth, ridge-regularized Gaussian radial-basis models with affine trends
   for morning SOC, minimum SOC, daily SOC change, climb, unmet energy, and the
   original model's feasibility outcome. Analytic leave-one-out error selects
   regularization strength; grouped held-out cases remain separate from tuning.
   Fits use normalized coordinates and are
   separate for APC and Mejzlik. The feasibility fit is a heuristic, not a
   calibrated probability.
5. Use `aerosandbox.Opti` / IPOPT to optimize geometry, continuous pack count,
   diameter, and pitch. Multistart anchors cover both pack counts. Prop proposals
   stay inside the manufacturer's catalog diameter/pitch convex hull and a local
   radius; geometry stays within a bounded local trust region.
   Tolerance-sized solver drift is projected back onto the original bounds
   before exact evaluation; the aircraft limits themselves are unchanged.
6. Check actual SKUs within +/-2.5 inches diameter and +/-2.0 inches pitch of each
   proposed optimum. Keep all catalog variants in that window, filling sparse
   windows with the five closest available SKUs. Check neighboring allowed pack
   counts, including both counts at an endpoint in the current two/three-pack set.
   Also check +/-5 mm chord and boom-spacing changes to cross packing boundaries.
7. Recompute exact geometry, integer cells/strings, real prop maps, prop mass,
   electrical model, yaw, all existing hard gates, and the mission. Add these
   evaluations to training and repeat, three rounds by default. Shrink the trust
   region after poor predictions, no feasible neighbors, or no improvement.

Only exact original-model rows enter the candidate CSV or become winners. A
fractional propeller, fractional battery pack, or fitted SOC result never becomes
a reported aircraft. The previous winner is retained only after current-model
reevaluation. Layouts, battery options, and manufacturer families remain genuine
categories; motor and ESC choices remain fixed as before. Cell counts are smoothed
implicitly in the response versus geometry, not treated as installable fractions.

The current catalog filter is unchanged (including its pitch/diameter window).
If a proposed size is absent, no nonexistent combination is created. For example,
a 22.5 x 23.25 inch prop is outside the current filtered data support.

## Accuracy and Limits

This is surrogate-assisted local optimization, not an end-to-end differentiable
rewrite of the flight model or proof of a global optimum. The numerical solver
can exploit response-surface errors; geometry-dependent packing and hard limits
are particularly difficult to fit. Reports include grouped holdout morning-SOC
RMSE, solver status, predicted versus verified neighborhood SOC, and trust radii.
Large errors reduce the proposal radius; exact verification remains mandatory.

The smooth proposal problem permits up to 0.002 SOC recovery error and 0.1 Wh
unmet energy to avoid rejecting useful neighborhoods purely because of fitting
noise. These are **not** changed aircraft requirements. Final acceptance still
uses the original 1e-9 morning-SOC numerical tolerance, reserve, climb, unmet-energy,
and control checks. Invalid or overly optimistic proposals are discarded.

Runtime comparisons against the archived differential-evolution run are warm-start
workflow comparisons, not equal-budget, cold-start global-search benchmarks.
The one-time catalog sampling/preload cost still exists. Solver failures are
recorded and fall back to exact neighborhoods of known samples, not an unverified
"optimum." Existing structural and hardware/model-uncertainty caveats still apply.

## Commands and Outputs

```sh
.venv/bin/python scripts/run_six_layout_study.py --output outputs/new_surrogate_run --workers 6
.venv/bin/python scripts/run_six_layout_study.py --output outputs/new_de_run --method de --workers 6
```

Optional controls: `--samples`, `--rounds`, `--starts`, `--diameter-radius`,
`--pitch-radius`, `--combo`, and `--seed-dir`. The default seed directory is the
archived six-case morning-SOC run; if a case is missing, its legacy candidate
file supplies geometry seeds instead. A completed run is resumed only with matching search settings and seed path;
use a new output directory after physics/model changes.

Each case writes exact candidates (`.csv`), configuration/timing (`.json`),
surrogate fit/solve diagnostics (`.surrogate.json`), and all sampled inputs plus
their exact outcomes (`.samples.json`). The existing comparison-viewer builder
accepts the new results directory without a different result schema.

Solver API: [AeroSandbox Opti documentation](https://aerosandbox.readthedocs.io/en/master/autoapi/aerosandbox/optimization/opti/index.html).

## Rectangular Conventional Variant

The runner now supports four configurations and two batteries (eight cases);
its historical filename is retained. `conventional_rectangular` reuses the
conventional single-fuselage physics, motor, and rudder checks. It fixes wing
taper ratio to 1 and tip washout to 0. The now-irrelevant taper/washout start
positions are fixed to 1 and 0 respectively. The four fixed coordinates are
removed from the search vector, leaving six geometry variables. Whole-wing
incidence for trim is unchanged; there is no spanwise variation in incidence.

`study_variants.py` applies these restrictions before optimizer import in both
the parent and spawned workers. The viewer validates the reconstructed geometry.
The original conventional configuration remains unrestricted. If no rectangular
seed file exists, conventional geometry seeds are projected into the reduced
search space and re-evaluated; their old mission scores are never reused.

```sh
.venv/bin/python scripts/run_six_layout_study.py --output outputs/rectangular_2026-09-15 --seed-dir outputs/surrogate_final_2026-09-15 --combo conventional_rectangular__gold_v1
.venv/bin/python scripts/run_six_layout_study.py --output outputs/rectangular_2026-09-15 --seed-dir outputs/surrogate_final_2026-09-15 --combo conventional_rectangular__6s_36ah
.venv/bin/python scripts/build_compare_viewer.py --results-dir outputs/surrogate_final_2026-09-15 --rectangular-results-dir outputs/rectangular_2026-09-15
```

The viewer can combine the new cases with the six archived results without
overwriting or rerunning those studies; source CSV paths are retained in its data.
