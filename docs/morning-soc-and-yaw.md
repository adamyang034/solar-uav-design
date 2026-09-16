# Morning SOC and Yaw Acceptance

Updated 2026-09-15.

## Energy Objective

- Start with a full ground-charged battery at the last afternoon solar surplus.
- March through the night without resetting the battery.
- Record current morning SOC immediately before solar surplus begins charging.
- March one complete day to the same charging transition the next morning.
- Require next morning SOC >= current morning SOC. Equality is not required.
- Only 1e-9 SOC of floating-point tolerance is allowed; there is no daily Wh-loss allowance.
- Among feasible aircraft maximize the lower of those two morning SOC values, in percent, not Wh.
- Retain the 20% minimum SOC, unmet-energy, and existing climb checks.

The result fields are `morning_soc`, `next_morning_soc`,
`morning_soc_change`, `morning_charge_hour`, and `objective_soc`.
`soc_start` and `soc_end` now refer to the two morning boundaries.
`margin_wh` still reports energy above the minimum SOC over the scored cycle;
it is not the optimization objective. Failed designs cannot outrank passing
ones just by retaining more energy in a large battery.

Morning is detected from the first daily transition from nonpositive to
positive solar-minus-load power. This uses the existing clear-sky design-day
profile. A profile without a charging transition cannot satisfy this test.
Multiple weather-driven charging episodes would need an explicit event policy
before using a weather-based mission model.

## Visualization and Deferred Work

The main, conventional and separate-tail viewers use an independent 89-hour
SOC/energy trace, beginning at 08:00 with a full battery. The repeated design
day is intentional for visualization; it is not an 89-hour weather forecast
or the acceptance horizon. Bank angle is assumed negligible, so no turning
drag penalty has been added.

The assumed buck/boost MPPT and its current mass are retained. Electrical
capability refinements and structural sizing remain deferred by user decision.

## Yaw and Rudder

Two-motor layouts use differential thrust. Their authority check is independent
of the switch controlling passive yaw-stability requirements. The conventional
single-fuselage layout calls the rudder check directly, without a differential-
thrust capability calculation.

The conventional geometry already included a full-span rudder at 30% of fin
chord and 20 degrees maximum deflection. This installed geometry is retained.
New sizing output reports required versus installed chord fraction, chord,
area, available/required moment, and sideslip/yaw-rate margins.

The existing aerodynamic approximation is retained:

    tau = sqrt(rudder chord / fin chord)
    N_available = q S b Cn_delta_r delta_r_max
    N_required = max(N_sideslip, |N_r| r_required)
    required chord fraction = (N_required / N_per_unit_tau)^2

Sideslip correction and yaw rate are separate cases, as in the original model.
The effectiveness model's 5%-60% chord domain is enforced. A too-small installed
rudder fails; the code does not silently enlarge it or shrink the current rudder.
Servo torque, hinge loads, response time and simultaneous maneuver demands are
not newly validated by this calculation.

For a local smoke check of the saved conventional GOLD V1 winner geometry:

| Quantity | Calculated value |
|---|---:|
| Rudder span | 0.4765 m |
| Installed chord | 0.09531 m |
| Required chord | 0.03277 m |
| Installed area | 0.04542 m2 |
| Required area | 0.01562 m2 |
| Sideslip moment margin | +70.5% |
| Steady yaw-rate moment margin | +736.1% |

This check restored the GOLD V1 pack constants and 20-inch prop diameter; XFoil
was disabled for the local smoke check. It was not a new optimization or a
flight-control certification.

## Verification

Run `.venv/bin/python -m unittest discover -s tests -v` from the repository root.
For each layout, run the same interpreter from that layout directory with
`-m unittest discover -s ../tests -v`. Tests cover rising/equal/falling morning
SOC, precharge boundary timing, absence of charging, feasibility-first ranking,
SOC versus Wh ranking, 89-hour display separation, legacy CSV handling, yaw
routing, and rudder sizing limits.

Existing CSVs and exported HTML are historical artifacts and have not been
overwritten. They do not contain the new morning fields. Rerun the search and
viewer exporter to produce new winning designs and updated exported graphs;
old CSVs retain their historical ranking rather than receiving invented morning
SOC values.
