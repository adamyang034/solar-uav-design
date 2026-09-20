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

    def group(key, label, children, note, quantity=1, open_items=()):
        result = node(key, label, sum(c["mass_kg"] for c in children), children, note=note)
        result.update(quantity=int(quantity), per_item_kg=result['mass_kg']/quantity,
                      open_items=list(open_items))
        return result

    conventional = config.N_MOTORS == 1
    n_h = int(getattr(config, 'N_HSTABS', 1))
    n_v = int(getattr(config, 'N_VSTABS', 1 if conventional else 2))
    n_booms = int(getattr(config, 'N_BOOMS', 1 if conventional else 2))
    n_fuselages = int(getattr(config, 'N_FUSELAGES', 1 if conventional else 2))
    # Reporting allocation of an existing lump budget, not new hardware sizing.
    servo_counts = {'wing': 2, 'hstab': 1 if conventional else 2, 'vstab': 1 if conventional else 0}
    servo_count = sum(servo_counts.values())
    servo_total = float(fixed.get('servos', 0.))
    if 'servos' in fixed:
        used_fixed.add('servos')

    def servos(assembly, label):
        count = servo_counts[assembly]
        note = (f'Provisional allocation: {count} of {servo_count} assumed equal-mass actuators. '
                'Shares the existing total servo budget; not a selected servo specification.'
                if count else 'No rudder servo in the current differential-thrust configuration.')
        return node(assembly+'_servos', label, servo_total*count/servo_count,
                    source=f'FIXED_MASSES_KG.servos * {count}/{servo_count}', note=note)

    cell_counts = {'wing': 0, 'hstab': 0}
    for cell in design.cell_placements():
        assembly = 'wing' if cell.bay.startswith('wing_') else 'hstab' if cell.bay.startswith('hstab') else None
        if assembly is None:
            raise ValueError(f'Unassigned solar installation: {cell.bay}')
        cell_counts[assembly] += 1
    if sum(cell_counts.values()) != design.n_cells:
        raise ValueError('Solar placement count differs from model cell count')
    cell_mass = config.CELL_MASS_KG + config.CELL_INTERCONNECT_MASS_KG
    if not math.isclose(design.n_cells*cell_mass, raw['solar_cells'], abs_tol=1e-9):
        raise ValueError('Solar constituent masses do not reconcile')
    used_raw.add('solar_cells')

    def solar(assembly):
        count = cell_counts[assembly]
        if not count:
            return []
        return [node(assembly+'_solar', 'Installed solar array', count*cell_mass, [
            node(assembly+'_cell_material', f'Solar cells ({count})', count*config.CELL_MASS_KG,
                 source=f'{count} installed cells * CELL_MASS_KG'),
            node(assembly+'_cell_interconnects', 'Cell interconnects', count*config.CELL_INTERCONNECT_MASS_KG,
                 source=f'{count} installed cells * CELL_INTERCONNECT_MASS_KG'),
        ], source='Cell placements by mounting surface',
           note='Installed cells and interconnects; encapsulation remains in the structure estimate.')]

    groups = [
        group('wing', 'Wing assembly', [modeled('wing', 'Wing structure',
              note='Areal-mass estimate including encapsulation; not a detailed spar/rib bill of materials.'),
              servos('wing', 'Aileron servos')] + solar('wing'),
              'Complete wing: structure, allocated control actuation and installed solar.',
              open_items=['Servo mounts and linkages have no separate allowance; verify within the structure allocation.']),
        group('hstab', 'H-stab assembly', [modeled('hstab', 'H-stab structure')]
              + fixed_items([('vstab_hstab_interfaces', 'H-stab mounting interface')])
              + [servos('hstab', 'Elevator servos')] + solar('hstab'),
              'Structure, existing mounting-interface budget, elevator actuation and any installed solar. '
              + ('Mounting interface is H-stab to V-stab on the split T-tail.' if n_h > 1 else
                 'Mounting-interface allowance is assigned to the H-stab, not counted again under the boom.'),
              quantity=n_h, open_items=['Servo mounts, hinges and linkages are not separately itemized; confirm inclusion.']),
        group('vstab', 'V-stab assembly', [modeled('vstabs', 'V-stab structure')]
              + fixed_items([('boom_vstab_interfaces', 'Boom / V-stab interface')])
              + [servos('vstab', 'Rudder servos')],
              'Structure, boom attachment and rudder actuation where fitted.', quantity=n_v,
              open_items=['Local attachment reinforcement and fasteners are not separately itemized; confirm inclusion.']),
        group('booms', 'Boom assembly', [modeled('booms', 'Boom tubes', n_booms, 'Tube', note=(
              f'Rock West {config.BOOM_PART_NUMBER}; {config.BOOM_MASS_PER_M:.6f} kg/m.'
              if getattr(config, 'BOOM_PART_NUMBER', None) else 'Tube-length mass estimate.'))],
              'Tube material only. Tail interfaces belong to their respective tail assemblies.', quantity=n_booms,
              open_items=['Tube splices, adhesive and local reinforcement have no separate allowance; verify before release.']),
        group('fuselage', 'Fuselage & integration', fixed_items([
              ('fuselages', 'Fuselage shells'), ('superstructures', 'Superstructures / mounting provisions')]),
              'Existing fuselage and superstructure budgets; shared mounting detail is not yet resolved.', quantity=n_fuselages,
              open_items=['Wing and battery mounts must be reconciled with the shared superstructure allowance.']),
        group("battery", "Battery bank", [modeled("batteries", "Battery packs", design.n_packs, "Pack")],
              "Pack mass only. Mounting provisions remain with fuselage integration.", quantity=design.n_packs),
        group("solar_power", "Electrical integration", [modeled("mppts", "MPPT controllers", design.n_mppts, "MPPT")]
              + fixed_items([("power_boards", "Power boards"), ("wiring", "Wiring")]),
              "Shared MPPT, board and wiring budgets. Solar cells are carried by their mounting assemblies.",
              open_items=['Harness routing and connector allocations are not yet split between assemblies.']),
        group("propulsion", "Propulsion assembly", [modeled("motors", "Motors", config.N_MOTORS, "Motor"),
              modeled("props", "Propellers", config.N_MOTORS, "Propeller")]
              + fixed_items([("escs", "ESC allocation")]),
              "Motors, propellers and the configured ESC budget.", quantity=config.N_MOTORS,
              open_items=['Motor mounts and fasteners need confirmation against the integration allowance.']),
        group("avionics_controls", "Avionics assembly", fixed_items([("avionics", "Avionics")]),
              "Existing avionics budget. Servos belong to the wing and tail assemblies."),
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
                servo_allocation=dict(total_kg=servo_total, assumed_counts=servo_counts,
                                      assumed_each_kg=servo_total/servo_count),
                basis="Provisional assembly allocations, not approved part limits or measured masses. Each modeled mass is counted once; aircraft headroom remains unassigned.")
