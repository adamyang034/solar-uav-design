import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('engineering_snapshot',ROOT/'scripts/engineering_snapshot.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReviewChecks(unittest.TestCase):
    def test_minimum_and_maximum_headroom(self):
        a=module.numeric_check('mass','Mass',10.,12.,'kg','max')
        self.assertEqual((a['headroom'],a['status']),(2.,'pass'))
        b=module.numeric_check('soc','SOC',19.,20.,'%','min')
        self.assertEqual((b['headroom'],b['status']),(-1.,'fail'))

    def test_numerical_tolerance_is_not_hidden_from_headroom(self):
        a=module.numeric_check('recovery','Recovery',-6e-8,0,'pp','min',1e-7)
        self.assertEqual(a['status'],'pass')
        self.assertLess(a['headroom'],0)
        self.assertEqual(module.numeric_check('recovery','Recovery',-2e-7,0,'pp','min',1e-7)['status'],'fail')

    def test_strict_unmet_energy_threshold(self):
        for actual,status in [(0.,'pass'),(.499,'pass'),(.5,'fail')]:
            self.assertEqual(module.numeric_check('unmet','Unmet',actual,.5,'Wh','max',strict=True)['status'],status)

    def test_missing_or_nonfinite_is_not_pass(self):
        for actual in [None,float('nan'),float('inf')]:
            self.assertEqual(module.numeric_check('missing','Missing',actual,1.,'m','max')['status'],'fail')

    def test_generated_snapshot_matches_saved_results(self):
        html=(ROOT/'outputs/compare/aircraft_viewer.html').read_text()
        marker='window.CONFIGS = '
        self.assertIn(marker,html)
        configs,_=json.JSONDecoder().raw_decode(html.split(marker,1)[1])
        self.assertEqual(len(configs),8)
        for config in configs.values():
            p=config['payload'];r=p['review']
            self.assertEqual(r['checks'][-1]['status'],'not_evaluated')
            self.assertEqual(len(r['provenance']['source_sha256']),64)
            self.assertEqual(len(r['provenance']['model_sha256']),64)
            self.assertFalse(any(c['status']=='fail' for c in r['checks']))
            self.assertAlmostEqual(p['study']['verified_morning_soc'],p['energy']['objective_soc'])
            self.assertLess(abs(p['study']['morning_soc_difference_pp']),1e-6)
            self.assertAlmostEqual(sum(c['mass'] for c in p['mass']['components'].values()),p['dims']['mass_kg'])
            allocation=p['mass']['allocation']
            self.assertAlmostEqual(allocation['total_kg'],p['dims']['mass_kg'])
            self.assertAlmostEqual(sum(g['mass_kg'] for g in allocation['groups']),p['dims']['mass_kg'])
            def check_parts(node):
                if node['children']:
                    self.assertAlmostEqual(sum(c['mass_kg'] for c in node['children']),node['mass_kg'])
                    for child in node['children']:check_parts(child)
            for group in allocation['groups']:check_parts(group)


if __name__=='__main__':unittest.main()
