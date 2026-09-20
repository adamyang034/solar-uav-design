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
        design=SimpleNamespace(n_cells=30,n_mppts=2,n_packs=2,mass_kg=sum(raw.values()),mass_breakdown=lambda:raw,
                               cell_placements=lambda:[SimpleNamespace(bay='wing_inboard') for _ in range(30)])
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
        self.assertEqual(len(result['groups']),9)
        for group in result['groups']:
            self.assertAlmostEqual(group['quantity']*group['per_item_kg'],group['mass_kg'])

    def test_fixed_budgets_reclassified_once(self):
        d,c,_=self.example()
        groups={g['id']:g for g in module.allocation(d,c)['groups']}
        self.assertAlmostEqual(groups['wing']['mass_kg'],2.28)
        self.assertAlmostEqual(groups['hstab']['mass_kg'],.38)
        self.assertAlmostEqual(groups['vstab']['mass_kg'],.26)
        self.assertAlmostEqual(groups['propulsion']['mass_kg'],.69)
        self.assertAlmostEqual(groups['avionics_controls']['mass_kg'],.3)
        self.assertAlmostEqual(groups['solar_power']['mass_kg'],.412)

    def test_conventional_tail_components_and_servo_split(self):
        d,c,_=self.example()
        c.N_MOTORS=1
        result=module.allocation(d,c)
        groups={g['id']:g for g in result['groups']}
        for name,structure,interface in [('hstab',.3,.04),('vstab',.2,.06)]:
            g=groups[name]
            self.assertAlmostEqual(g['mass_kg'],structure+interface+.02)
            self.assertEqual(g['quantity'],1)
            self.assertEqual(len(g['children']),3)
            servo=next(n for n in g['children'] if n['id']==name+'_servos')
            self.assertIn('Provisional',servo['note'])
            self.assertAlmostEqual(servo['mass_kg'],.02)
        self.assertEqual(result['servo_allocation']['assumed_counts'],{'wing':2,'hstab':1,'vstab':1})

    def test_solar_mass_follows_installation_and_split_tail_quantity(self):
        d,c,_=self.example()
        c.N_HSTABS=2
        d.cell_placements=lambda:([SimpleNamespace(bay='wing_inboard') for _ in range(22)]
                                 +[SimpleNamespace(bay='hstab') for _ in range(8)])
        result=module.allocation(d,c)
        groups={g['id']:g for g in result['groups']}
        self.assertAlmostEqual(groups['hstab']['mass_kg'],.38+.064)
        self.assertEqual(groups['hstab']['quantity'],2)
        self.assertAlmostEqual(groups['hstab']['per_item_kg'],.222)
        self.assertAlmostEqual(groups['wing']['mass_kg'],2.28-.064)
        self.assertEqual(next(n for n in groups['vstab']['children'] if n['id']=='vstab_servos')['mass_kg'],0)

    def test_unassigned_or_missing_cell_placements_fail(self):
        d,c,_=self.example()
        d.cell_placements=lambda:[SimpleNamespace(bay='unknown')]
        with self.assertRaises(ValueError):module.allocation(d,c)
        d.cell_placements=lambda:[]
        with self.assertRaises(ValueError):module.allocation(d,c)

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
