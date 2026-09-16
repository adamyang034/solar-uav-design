# Conventional Rectangular Wing Study

Separate conventional configuration: constant chord and airfoil across the wing,
taper ratio 1, geometric washout 0 degrees. Whole-wing trim incidence remains
available. Conventional rudder checks, mission assumptions, reserve floor, and
hardware choices are unchanged. The tapered conventional option is preserved.

Both runs use the AeroSandbox/IPOPT surrogate workflow with 72 initial geometry
samples, three refinement rounds, three starts, six workers, and seed 7. Seeds
come from the corresponding conventional result in `../surrogate_final_2026-09-15`;
all seeds are reconstructed as rectangular wings and re-evaluated.

| Battery | Packs | Span (m) | Chord (m) | Mass (kg) | Morning SOC | Reserve above 20% (Wh) |
|---|---:|---:|---:|---:|---:|---:|
| GOLD V1 | 3 | 6.000 | 0.378750 | 10.563 | 29.567% | 138.625 |
| 6S 36 Ah | 2 | 6.000 | 0.390604 | 11.190 | 28.068% | 118.481 |

Both use catalog propeller MJ-20x11EWL and pass the current modeled constraints.
The next-morning SOC condition passes within the existing numerical tolerance.
These are best-found designs, not guaranteed global optima or flight-qualified
aircraft. Structural sizing and existing model uncertainties remain separate.

The two runs performed 663 exact single-prop evaluations in approximately 137
seconds combined. All 486 retained candidate rows have the required fixed geometry.
AircraftView independently recomputed both winners and matched the search SOC
within 0.000001 percentage points. The viewer combines these two cases with the
six preserved cases from `../surrogate_final_2026-09-15`.

Per-case manifests record fixed and active geometry, battery configuration,
source seeds, bounds, and timing. Sample and surrogate diagnostics accompany
each candidate CSV. `browser_qa` contains visual and interaction checks.
