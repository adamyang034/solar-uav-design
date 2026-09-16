import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('mass_allocation',Path(__file__).resolve().parents[1]/'scripts/mass_allocation.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MassAllocationTests(unittest.TestCase):
    def example(self):
        fixed=dict(avionics=.3,servos=.08,escs=.06,wiring=.096,power_boards=.1,
                   fuselages=.2,superstructures=.2,boom_vstab_interfaces=.06,vstab_hstab_interfaces=.04)
        config=SimpleNamespace(FIXED_MASSES_KG=fixed,CELL_MASS_KG=.0065,
                               CELL_INTERCONNECT_MASS_KG=.0015,N_MOTORS=2,MTOW_MAX_KG=12)
        raw=dict(wing=2.,hstab=.3,vstabs=.2,booms=.5,solar_cells=.24,mppts=.216,
                 batteries=2.556,motors=.55,props=.08,fixed=sum(fixed.values()))
        design=SimpleNamespace(n_cells=30,n_mppts=2,n_packs=2,mass_kg=sum(raw.values()),mass_breakdown=lambda:raw)
        return design,config,raw

    def test_groups_and_leaves_reconcile(self):
        d,c,_=self.example()
        result=module.allocation(d,c)
        self.assertAlmostEqual(result['total_kg'],d.mass_kg)
        def check(node):
            if node['children']:
                self.assertAlmostEqual(sum(n['mass_kg'] for n in node['children']),node['mass_kg'])
                for n in node['children']:check(n)
        for node in result['groups']:check(node)
        self.assertEqual(len(result['groups']),5)

    def test_fixed_budgets_reclassified_once(self):
        d,c,_=self.example()
        groups={g['id']:g for g in module.allocation(d,c)['groups']}
        self.assertAlmostEqual(groups['airframe']['mass_kg'],3.5)
        self.assertAlmostEqual(groups['propulsion']['mass_kg'],.69)
        self.assertAlmostEqual(groups['avionics_controls']['mass_kg'],.38)
        self.assertAlmostEqual(groups['solar_power']['mass_kg'],.652)

    def test_additional_items_are_not_dropped(self):
        d,c,raw=self.example()
        c.FIXED_MASSES_KG['payload']=.15
        raw['fixed']+=.15
        raw['landing_gear']=.3
        d.mass_kg=sum(raw.values())
        groups={g['id']:g for g in module.allocation(d,c)['groups']}
        self.assertAlmostEqual(groups['other']['mass_kg'],.45)

    def test_inconsistent_or_invalid_values_fail(self):
        d,c,raw=self.example()
        raw['solar_cells']+=.1
        with self.assertRaises(ValueError):module.allocation(d,c)
        d,c,raw=self.example()
        raw['wing']=-1
        with self.assertRaises(ValueError):module.allocation(d,c)


if __name__=='__main__':unittest.main()
