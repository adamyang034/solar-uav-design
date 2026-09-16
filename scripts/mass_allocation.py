"""Consistent review hierarchy from the underlying mass model, not CAD lumps."""
import math


def allocation(design, config):
    raw = design.mass_breakdown()
    fixed = dict(config.FIXED_MASSES_KG)
    used_raw, used_fixed = set(), set()

    def node(key, label, mass, children=None, source="", note=""):
        value = float(mass)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid mass for {key}: {mass}")
        children = children or []
        if children and not math.isclose(sum(c["mass_kg"] for c in children), value, abs_tol=1e-9):
            raise ValueError(f"Mass allocation does not reconcile: {key}")
        return dict(id=key, label=label, mass_kg=value, children=children, source=source, note=note)

    def modeled(key, label, count=None, item=None, note=""):
        used_raw.add(key)
        mass = raw[key]
        children = []
        if count is not None:
            count = int(count)
            if count < 1:
                raise ValueError(f"Invalid count for {key}")
            children = [node(f"{key}_{i+1}", f"{item} {i+1}", mass/count,
                             source=f"mass_breakdown.{key} / {count}") for i in range(count)]
        return node(key, label, mass, children, f"mass_breakdown.{key}", note)

    def fixed_items(keys):
        rows = []
        for key, label in keys:
            if key in fixed:
                used_fixed.add(key)
                rows.append(node(key, label, fixed[key], source=f"FIXED_MASSES_KG.{key}"))
        return rows

    def group(key, label, children, note):
        return node(key, label, sum(c["mass_kg"] for c in children), children, note=note)

    airframe = [
        modeled("wing", "Wing structure", note="Areal-mass estimate including encapsulation; excludes solar cells and interconnects."),
        modeled("hstab", "Horizontal tail structure"),
        modeled("vstabs", "Vertical tail structure"),
        modeled("booms", "Booms"),
    ] + fixed_items([
        ("fuselages", "Fuselages"), ("superstructures", "Superstructures"),
        ("boom_vstab_interfaces", "Boom / vertical-tail interfaces"),
        ("vstab_hstab_interfaces", "Tail interfaces"),
    ])
    used_raw.add("solar_cells")
    cells = node("solar_cells", "Solar array", raw["solar_cells"], [
        node("cell_material", f"Solar cells ({design.n_cells})", design.n_cells*config.CELL_MASS_KG,
             source="n_cells * CELL_MASS_KG"),
        node("cell_interconnects", "Cell interconnects", design.n_cells*config.CELL_INTERCONNECT_MASS_KG,
             source="n_cells * CELL_INTERCONNECT_MASS_KG"),
    ], "mass_breakdown.solar_cells")
    groups = [
        group("airframe", "Airframe", airframe, "Wing, tails, booms, fuselages and structural interfaces. Solar array excluded."),
        group("battery", "Battery bank", [modeled("batteries", "Battery packs", design.n_packs, "Pack")],
              "Installed pack allocation; no controller or wiring mass."),
        group("solar_power", "Solar & power", [cells, modeled("mppts", "MPPT controllers", design.n_mppts, "MPPT")]
              + fixed_items([("power_boards", "Power boards"), ("wiring", "Wiring")]),
              "Cells, interconnects, MPPTs, power boards and the fixed wiring budget."),
        group("propulsion", "Propulsion", [modeled("motors", "Motors", config.N_MOTORS, "Motor"),
              modeled("props", "Propellers", config.N_MOTORS, "Propeller")]
              + fixed_items([("escs", "ESC allocation")]),
              "Motors, propellers and the configured ESC budget."),
        group("avionics_controls", "Avionics & controls", fixed_items([("avionics", "Avionics"), ("servos", "Servos")]),
              "Fixed avionics and servo budgets."),
    ]
    used_raw.add("fixed")
    if not math.isclose(sum(fixed.values()), raw["fixed"], abs_tol=1e-9):
        raise ValueError("Fixed constituent masses do not reconcile")
    extra = [modeled(k, k.replace("_", " ").capitalize()) for k in raw if k not in used_raw]
    extra += fixed_items([(k, k.replace("_", " ").capitalize()) for k in fixed if k not in used_fixed])
    if extra:
        groups.append(group("other", "Other modeled items", extra, "Additional model items retained without reclassification."))
    total = sum(g["mass_kg"] for g in groups)
    if not math.isclose(total, design.mass_kg, abs_tol=1e-9):
        raise ValueError("Mass allocation differs from aircraft mass")
    return dict(total_kg=total, limit_kg=float(config.MTOW_MAX_KG),
                headroom_kg=float(config.MTOW_MAX_KG-total), groups=groups,
                difference_kg=float(total-design.mass_kg),
                basis="Modeled allocation, not measured mass. Solar cells and fixed budgets are each counted once.")
