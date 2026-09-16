"""Exercise the variant in isolated processes, as used by study workers."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RectangularVariantTests(unittest.TestCase):
    def run_case(self, layout, checks):
        code = """
import sys
import numpy as np
from types import SimpleNamespace
sys.path.insert(0, 'scripts')
import run_six_layout_study as runner
from solar_uav import config, optimize
from study_variants import RECTANGULAR_GEOMETRY, validate_layout
""" + checks
        env = dict(os.environ, SOLAR_UAV_STUDY_COMBO=f'{layout}__gold_v1',
                   OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                   VECLIB_MAXIMUM_THREADS='1')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rectangular_constraints_survive_seed_and_reconstruction(self):
        self.run_case('conventional_rectangular', """
assert len(config.OPT_KEYS) == 6
assert not set(config.OPT_KEYS) & set(RECTANGULAR_GEOMETRY)
assert all(hi > lo for lo, hi in optimize._continuous_bounds())
seed = dict(taper_ratio=.5, taper_start_frac=.2, washout_tip_deg=5., washout_start_frac=.5)
rng = np.random.default_rng(7)
bounds = np.array(optimize._continuous_bounds())
vectors = [optimize.x_from_start(seed)] + list(rng.uniform(bounds[:, 0], bounds[:, 1], (12, len(bounds))))
for x in vectors:
    d = optimize.design_from_x(x)
    validate_layout(d, runner.LAYOUT)
    ys = np.linspace(-d.span_m/2, d.span_m/2, 21)
    np.testing.assert_allclose([d.chord_at_y(y) for y in ys], d.chord_m)
    np.testing.assert_array_equal(d.washout_deg_at_y(ys), np.zeros(21))
import pandas as pd
row = pd.Series(dict(span_m=d.span_m, chord_m=d.chord_m, tail_arm_m=d.tail_arm_m,
                     n_packs=2, cells_per_string=None, n_strings=None,
                     one_string_per_bay=True, elevator_frac=d.elevator_frac,
                     **RECTANGULAR_GEOMETRY))
validate_layout(optimize.design_from_row(row), runner.LAYOUT)
try:
    validate_layout(SimpleNamespace(taper_ratio=.8), runner.LAYOUT)
except ValueError:
    pass
else:
    raise AssertionError('A tapered viewer result must be rejected')
assert runner.seed_path(runner.LAYOUT, 'gold_v1', None).name == 'phase4_candidates.csv'
""")

    def test_original_conventional_keeps_taper_and_twist(self):
        self.run_case('conventional', """
assert len(config.OPT_KEYS) == 10
assert not getattr(config, 'FIXED_GEOMETRY', {})
d = optimize.design_from_x(optimize.x_from_start(dict(taper_ratio=.6, washout_tip_deg=3.)))
assert d.taper_ratio == .6
assert d.washout_tip_deg == 3.
""")


if __name__ == '__main__':
    unittest.main()
