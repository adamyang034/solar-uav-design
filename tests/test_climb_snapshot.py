import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "climb_snapshot", Path(__file__).parents[1] / "scripts" / "climb_snapshot.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ClimbThrustTests(unittest.TestCase):
    def test_force_balance_and_inverse_mission_equation(self):
        thrust = MODULE.required_thrust(5, 10, 12, 1.5, 9.80665)
        self.assertAlmostEqual(thrust, 17.2583125)
        self.assertAlmostEqual(12 * (thrust - 5) / (10 * 9.80665), 1.5)

    def test_level_flight_and_mass_scaling(self):
        self.assertEqual(MODULE.required_thrust(5, 10, 12, 0, 9.80665), 5)
        self.assertAlmostEqual(MODULE.required_thrust(5, 20, 12, 1.5, 9.80665)-5,
                               2*(MODULE.required_thrust(5, 10, 12, 1.5, 9.80665)-5))

    def test_invalid_inputs(self):
        for speed, rate in ((0, 1.5), (-1, 1.5), (12, -1), (12, 12), (float('nan'), 1.5)):
            with self.assertRaises(ValueError):
                MODULE.required_thrust(5, 10, speed, rate, 9.80665)


if __name__ == "__main__":
    unittest.main()
