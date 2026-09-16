"""Run for each layout with its package root on PYTHONPATH."""

import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from solar_uav import config, mission, optimize
from solar_uav.aircraft import Design


class LinearBank:
    initial_soc = 1.0
    energy_total_wh = 1000.0

    def __init__(self, **kwargs):
        self.soc = self.initial_soc

    def step(self, power, dt_s):
        raw = self.soc + power * dt_s / 3600 / self.energy_total_wh
        self.soc = float(np.clip(raw, 0, 1))
        return {"p_spilled_w": max(0, raw - 1) * self.energy_total_wh,
                "deficit_w": max(0, -raw) * self.energy_total_wh}


def powers(charge=40.0):
    hours = np.arange(24, dtype=float)
    net = np.where((hours >= 6) & (hours < 18), charge, -20.0)
    return dict(hours=hours, n=24, dt_s=3600, dt_h=1, av_w=5,
                mass=10, v_night=10, v_day=10, p_solar=net + 20,
                p_load=np.full(24, 20.0), p_net=net, p_night=20,
                p_day=20, climb=2, is_night=net < 0, fl_n={}, fl_d={})


def row(soc, closed=True, change=0.0, reserve=100):
    return dict(objective_soc=soc, morning_soc_change=change,
                closed=closed, soc_min=soc, climb_ms=2, unmet_wh=0,
                margin_wh=reserve)


class MorningTests(unittest.TestCase):
    def run_mission(self, charge=40, initial_soc=1):
        with patch.object(mission, "_bus_powers", return_value=powers(charge)), \
             patch.object(mission, "BatteryBank", LinearBank), \
             patch.object(LinearBank, "initial_soc", initial_soc):
            return mission.simulate(SimpleNamespace(n_packs=2), None, None)

    def test_equal_mornings_pass_at_precharge_boundary(self):
        result = self.run_mission()
        self.assertTrue(result.closed)
        self.assertAlmostEqual(result.morning_soc, .76)
        self.assertAlmostEqual(result.next_morning_soc, .76)
        self.assertEqual(result.morning_charge_hour, 6)
        self.assertAlmostEqual(result.soc_trace[0], result.morning_soc)
        self.assertAlmostEqual(result.soc_trace[-1], result.next_morning_soc)
        self.assertEqual(result.hours[-1], 24)
        self.assertEqual(len(result.hours), len(result.p_load))

    def test_increasing_morning_passes_without_equality(self):
        result = self.run_mission(initial_soc=.5)
        self.assertGreater(result.next_morning_soc, result.morning_soc)
        self.assertTrue(result.closed)
        self.assertEqual(result.objective_soc, result.morning_soc)

    def test_falling_morning_fails_even_above_reserve(self):
        result = self.run_mission(charge=10)
        self.assertGreater(result.margin_wh, 0)
        self.assertLess(result.morning_soc_change, 0)
        self.assertFalse(result.closed)

    def test_no_charging_is_infeasible(self):
        result = self.run_mission(charge=-1)
        self.assertFalse(result.closed)
        self.assertTrue(np.isnan(result.objective_soc))

    def test_feasible_dominates_depleting(self):
        good = row(.35)
        bad = row(.80, closed=False, change=-.1, reserve=1000)
        self.assertLess(mission.candidate_score(good), mission.candidate_score(bad))
        self.assertEqual(optimize.winner(pd.DataFrame([bad, good])).objective_soc, .35)

    def test_percent_not_watt_hours_drives_ranking(self):
        low = row(.40, reserve=500)
        high = row(.50, reserve=100)
        ranked = mission.rank_candidates(pd.DataFrame([low, high]))
        self.assertEqual(ranked.iloc[0].objective_soc, .50)

    def test_only_floating_point_depletion_is_tolerated(self):
        self.assertLessEqual(mission.MORNING_SOC_TOL, 1e-9)

    def test_display_is_89_hours_and_does_not_change_scoring(self):
        design = SimpleNamespace(n_packs=2)
        with patch.object(mission, "_bus_powers", return_value=powers()), \
             patch.object(mission, "BatteryBank", LinearBank):
            before = mission.simulate(design, None, None)
            trace = mission.display_trace(design, None, None)
            after = mission.simulate(design, None, None)
        self.assertEqual(trace.duration_h, 89)
        self.assertEqual(trace.hours[-1], 89)
        self.assertEqual(trace.soc_trace[0], 1)
        self.assertEqual(before.objective_soc, after.objective_soc)

    def test_yaw_routing_independent_of_passive_stability_switch(self):
        source = inspect.getsource(optimize.evaluate_design)
        if config.N_MOTORS == 1:
            self.assertIn("d.rudder_yaw_ok(v_n)", source)
            self.assertNotIn("d.differential_thrust_yaw_ok", source)
        else:
            self.assertIn("d.differential_thrust_yaw_ok", source)
            self.assertNotIn("config.REQUIRE_YAW_STABILITY", source)

    def test_legacy_results_are_not_assigned_a_new_objective(self):
        df = pd.DataFrame([dict(closed=True, margin_wh=10),
                           dict(closed=True, margin_wh=20)])
        self.assertNotIn("objective_soc", mission.rank_candidates(df))
        self.assertEqual(optimize.winner(df).margin_wh, 20)

    def test_real_solar_battery_and_5_minute_display(self):
        from solar_uav import environment

        class Flight:
            def with_scales(self, *args):
                return self

            def level_flight(self, *args, **kwargs):
                return {"p_bus_w": 50.0}

            def max_thrust_n(self, *args, **kwargs):
                return 20.0

        design = SimpleNamespace(
            n_packs=2, mass_kg=10.0,
            string_lengths=lambda: (24, 24, 24),
            min_power_speed=lambda **kwargs: 10.0,
            drag_n=lambda *args, **kwargs: 1.0,
            climb_rate_ideal_ms=lambda *args, **kwargs: 2.0)
        env = environment.design_day()
        result = mission.simulate(design, env, Flight())
        self.assertTrue(np.isfinite(result.morning_soc))
        self.assertTrue(np.isfinite(result.next_morning_soc))
        self.assertEqual(len(result.soc_trace), 289)
        self.assertAlmostEqual(result.objective_soc,
                               min(result.morning_soc, result.next_morning_soc))
        trace = mission.display_trace(design, env, Flight())
        self.assertEqual(len(trace.soc_trace), 1069)
        self.assertEqual(trace.hours[-1], 89)


@unittest.skipUnless(config.N_MOTORS == 1, "Conventional rudder only")
class RudderTests(unittest.TestCase):
    def sizing(self, static_need, damping=-1):
        fake = SimpleNamespace(
            min_airspeed=lambda rho: 10,
            rudder_moment_n=lambda v, rho: 10.0,
            weathercock_moment_n=lambda v, rho: static_need,
            yaw_damping_n_per_rads=lambda v, rho: damping,
            rudder_tau=lambda: np.sqrt(config.RUDDER_CHORD_FRAC),
            vstab_height=.4, vstab_chord=.2, vstab_area_total=.08)
        return Design.rudder_sizing(fake, 10)

    def test_required_chord_and_area(self):
        result = self.sizing(5)
        self.assertAlmostEqual(result["rudder_required_fraction"], .075)
        self.assertAlmostEqual(result["rudder_required_chord_m"], .015)
        self.assertAlmostEqual(result["rudder_installed_area_m2"], .024)
        self.assertTrue(result["rudder_sizing_ok"])

    def test_undersized_rudder_fails(self):
        self.assertFalse(self.sizing(15)["rudder_sizing_ok"])

    def test_nonrestoring_damping_does_not_pass(self):
        self.assertFalse(self.sizing(1, damping=0)["rudder_sizing_ok"])

    def test_rate_requirement_can_govern(self):
        result = self.sizing(1, damping=-200)
        self.assertGreater(result["rudder_required_moment_nm"], 10)
        self.assertFalse(result["rudder_sizing_ok"])


if __name__ == "__main__":
    unittest.main()
