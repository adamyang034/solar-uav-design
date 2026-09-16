import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import aerosandbox as asb
import casadi as ca
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from surrogate_search import SmoothFit, nearby_props, nearby_packs, bounded_solution, _exact, _init_worker


class SurrogateTests(unittest.TestCase):
    def test_solver_bound_drift_does_not_reject_six_meter_wing(self):
        value = bounded_solution([1 + 1e-8, -1e-8, .4])
        np.testing.assert_array_equal(value, [1., 0., .4])
        self.assertEqual(4.5 + 1.5 * value[0], 6.)
        with self.assertRaises(RuntimeError):
            bounded_solution([1.01])

    def catalog(self):
        return pd.DataFrame([
            dict(name='A20', diameter_in=20., pitch_in=10.),
            dict(name='A22', diameter_in=22., pitch_in=12.),
            dict(name='A22-variant', diameter_in=22., pitch_in=12.),
            dict(name='A24', diameter_in=24., pitch_in=14.),
            dict(name='A27', diameter_in=27., pitch_in=15.),
        ])

    def test_neighborhood_only_real_skus_including_variants(self):
        result = nearby_props(self.catalog(), 22.5, 12.25, minimum=1)
        self.assertEqual(set(result.name), {'A22', 'A22-variant', 'A24'})
        self.assertNotIn('22.5x12.25', result.name.tolist())

    def test_sparse_neighborhood_fills_by_distance(self):
        result = nearby_props(self.catalog(), 22.5, 23.25, minimum=3)
        self.assertEqual(len(result), 3)
        self.assertTrue(set(result.name) <= set(self.catalog().name))

    def test_invalid_neighborhood(self):
        with self.assertRaises(ValueError):
            nearby_props(self.catalog(), 22, 12, diameter_radius=0)

    def test_pack_rounding_uses_allowed_counts(self):
        self.assertEqual(nearby_packs(2.4, [2, 3]), [2, 3])
        self.assertEqual(nearby_packs(3, [2, 4]), [2, 4])
        self.assertEqual(nearby_packs(4, [2, 4]), [2, 4])
        self.assertEqual(nearby_packs(1.5, [2, 3]), [2, 3])

    def test_preloaded_maps_never_reload_catalog(self):
        from solar_uav.components import propulsion
        fake = SimpleNamespace(diameter_in=22.)
        try:
            propulsion.register_props({'test-only': fake})
            with patch.object(propulsion.Propeller, 'load', side_effect=AssertionError('disk load')):
                self.assertIs(propulsion.load_prop('test-only'), fake)
        finally:
            propulsion._PRELOADED_PROPS.pop('test-only', None)
            propulsion.load_prop.cache_clear()

    def test_symbolic_gradient_matches_finite_difference(self):
        rng = np.random.default_rng(7)
        x = rng.uniform(size=(35, 3))
        fit = SmoothFit.fit(x, np.sin(x[:, 0]) + x[:, 1]**2 - x[:, 2])
        symbolic = ca.MX.sym('z', 3)
        derivative = ca.Function('gradient', [symbolic], [ca.gradient(fit(symbolic), symbolic)])
        at = np.array([.4, .3, .6])
        h = 1e-6
        finite = np.array([(float(fit(at + h*np.eye(3)[j])) - float(fit(at - h*np.eye(3)[j]))) / (2*h) for j in range(3)])
        np.testing.assert_allclose(np.asarray(derivative(at)).ravel(), finite, atol=1e-7)

    def test_aerosandbox_finds_known_surrogate_optimum(self):
        x = np.linspace(0, 1, 16)[:, None]
        fit = SmoothFit.fit(x, (x[:, 0] - .35)**2)
        opti = asb.Opti()
        z = opti.variable(init_guess=.8, n_vars=1, lower_bound=0, upper_bound=1)
        opti.minimize(fit(z))
        sol = opti.solve(verbose=False)
        self.assertAlmostEqual(float(sol(z)), .35, delta=.025)

    def test_exact_evaluation_sets_real_prop_before_any_physics(self):
        from solar_uav import optimize
        from solar_uav.components import propulsion, motor
        design = SimpleNamespace()
        row = {'closed': True, 'objective_soc': .4}
        def evaluate(d, env, names, cache, drive, systems):
            self.assertEqual(d.prop_name, 'A22')
            self.assertEqual(d.prop_diameter_in, 22.)
            self.assertEqual(names, ['A22'])
            self.assertEqual(set(cache), {'A22'})
            return row
        _init_worker('environment', {})
        with patch.object(optimize, 'design_from_x', return_value=design) as construct, \
             patch.object(propulsion, 'load_prop', return_value=SimpleNamespace(diameter_in=22.)), \
             patch.object(motor, 'drive_for', return_value=object()), \
             patch.object(optimize, 'evaluate_design', side_effect=evaluate):
            result = _exact(([.1]*10, 2, 'A22'))
        self.assertIs(result['row'], row)
        self.assertEqual(construct.call_args.kwargs['n_packs'], 2)


if __name__ == '__main__':
    unittest.main()
