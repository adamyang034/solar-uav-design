"""Required thrust using the existing mission's steady-climb approximation."""
import math


def required_thrust(drag_n, mass_kg, speed_ms, climb_rate_ms, gravity_ms2):
    values = (drag_n, mass_kg, speed_ms, climb_rate_ms, gravity_ms2)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Climb inputs must be finite")
    if min(mass_kg, speed_ms, gravity_ms2) <= 0 or min(drag_n, climb_rate_ms) < 0:
        raise ValueError("Invalid climb input")
    if climb_rate_ms >= speed_ms:
        raise ValueError("Steady shallow-climb approximation requires ROC < airspeed")
    return drag_n + mass_kg * gravity_ms2 * climb_rate_ms / speed_ms


def climb_snapshot(design, config):
    # Import after the builder selects the layout-specific model package.
    from solar_uav.aircraft import G, RHO_DAY, RHO_NIGHT

    points = []
    for name, rho in (("Day", RHO_DAY), ("Night", RHO_NIGHT)):
        speed = float(design.min_power_speed(rho=rho, mass_kg=design.mass_kg))
        drag = float(design.drag_n(speed, mass_kg=design.mass_kg, rho=rho))
        thrust = required_thrust(drag, design.mass_kg, speed, config.CLIMB_RATE_REQ_MS, G)
        points.append(dict(condition=name, rho_kg_m3=float(rho), airspeed_ms=speed,
                           level_drag_n=drag, excess_thrust_n=thrust-drag,
                           required_thrust_n=thrust,
                           required_thrust_per_motor_n=thrust/config.N_MOTORS))
    governing = max(points, key=lambda p: p["required_thrust_n"])
    return dict(required_rate_ms=float(config.CLIMB_RATE_REQ_MS),
                mass_kg=float(design.mass_kg), gravity_ms2=float(G),
                n_motors=int(config.N_MOTORS), points=points,
                governing_condition=governing["condition"],
                max_required_thrust_n=governing["required_thrust_n"],
                max_required_thrust_per_motor_n=governing["required_thrust_per_motor_n"],
                formula="T_required = D_level(V, rho) + m*g*ROC_required/V",
                basis="Maximum of the day/night mission operating points at modeled mass. "
                      "Uses level-flight drag and steady shallow climb, consistent with the "
                      "existing mission model. Not a full-envelope maximum, static thrust, "
                      "takeoff acceleration, gust allowance or validated motor/battery capability.")
