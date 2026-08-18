"""Phase 2 — Upgrade Energy GOLD V1 6S2P (Amprius SA03) battery bank model.

Energy-based SOC model with an OCV curve, internal-resistance losses, the
80% usable window (SOC floor 0.20), and the hard 6 A per-pack charge limit
with CV taper near full. Pack count is a discrete optimizer variable.

FLAGGED: the OCV curve is a generic high-energy Li-ion (silicon anode) shape
and the internal resistance is an estimate; replace both with bench data
from an actual pack (Phase 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import config

# Generic Li-ion OCV vs SOC (per cell), anchored at 3.2 V floor / 4.2 V full.
_SOC_PTS = np.array([0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50,
                     0.60, 0.70, 0.80, 0.90, 0.95, 1.00])
_OCV_PTS = np.array([3.00, 3.30, 3.45, 3.55, 3.62, 3.68, 3.75,
                     3.83, 3.91, 3.99, 4.08, 4.14, 4.20])


def cell_ocv(soc):
    return np.interp(soc, _SOC_PTS, _OCV_PTS)


def pack_ocv(soc):
    return config.N_SERIES_CELLS * cell_ocv(soc)


@dataclass
class BatteryBank:
    """n_packs GOLD V1 packs in parallel on the 6S bus."""

    n_packs: int
    soc: float = 1.0
    energy_scale: float = 1.0   # Phase 5: sampled pack-capacity factor

    @property
    def mass_kg(self) -> float:
        return self.n_packs * config.PACK_MASS_KG

    @property
    def energy_total_wh(self) -> float:
        return self.n_packs * config.PACK_ENERGY_WH * self.energy_scale

    @property
    def energy_usable_wh(self) -> float:
        return self.energy_total_wh * (1.0 - config.SOC_MIN)

    @property
    def capacity_ah(self) -> float:
        return self.n_packs * config.PACK_CAPACITY_AH * self.energy_scale

    @property
    def r_bank_ohm(self) -> float:
        return config.PACK_R_INTERNAL_OHM / self.n_packs

    @property
    def voltage_oc(self) -> float:
        return float(pack_ocv(self.soc))

    # -- current/power solutions --------------------------------------------
    def _current_for_power(self, p_terminal_w: float) -> float:
        """Solve I from P = V_oc*I - I^2*R (discharge positive)."""
        v = self.voltage_oc
        r = self.r_bank_ohm
        disc = v * v - 4.0 * r * p_terminal_w
        if disc < 0:
            # Beyond capability; return max-power current as a cap.
            return v / (2.0 * r)
        return (v - np.sqrt(disc)) / (2.0 * r)

    def max_charge_power_w(self) -> float:
        """Charge acceptance right now: 6 A/pack CC limit with CV taper
        as the bank approaches 25.2 V, and zero when full."""
        if self.soc >= 1.0:
            return 0.0
        i_cc = config.PACK_CHARGE_MAX_A * self.n_packs
        v = self.voltage_oc
        # CV phase: terminal voltage clipped at BUS_V_MAX limits current.
        i_cv = max(0.0, (config.BUS_V_MAX - v) / self.r_bank_ohm)
        i = min(i_cc, i_cv)
        return v * i + i * i * self.r_bank_ohm  # power drawn from the bus

    def max_discharge_power_w(self) -> float:
        # Allow SOC to fall through the 20% floor so the mission model can
        # measure *how far* a design misses, not just that it missed.
        if self.soc <= 0.01:
            return 0.0
        return self.n_packs * config.PACK_DISCHARGE_SUSTAINED_W

    # -- time stepping -------------------------------------------------------
    def step(self, p_net_w: float, dt_s: float) -> dict:
        """Advance one time step.

        p_net_w > 0: surplus bus power offered for charging.
        p_net_w < 0: deficit the bank must supply.
        Returns actual power absorbed/delivered and any unusable surplus
        (energy that must be spilled because of the charge limit / full pack).
        """
        dt_h = dt_s / 3600.0
        result = {"p_charge_w": 0.0, "p_discharge_w": 0.0, "p_spilled_w": 0.0,
                  "deficit_w": 0.0}

        if p_net_w >= 0.0:
            p_accept = min(p_net_w, self.max_charge_power_w())
            i = self._current_for_power(-p_accept)  # charge current (negative)
            # Energy into chemistry = OCV * I (terminal power minus I^2R loss).
            e_in_wh = -self.voltage_oc * i * dt_h
            self.soc = min(1.0, self.soc + e_in_wh / self.energy_total_wh)
            result["p_charge_w"] = p_accept
            result["p_spilled_w"] = p_net_w - p_accept
        else:
            p_req = -p_net_w
            p_avail = self.max_discharge_power_w()
            p_del = min(p_req, p_avail)
            i = self._current_for_power(p_del)
            e_out_wh = self.voltage_oc * i * dt_h
            self.soc = max(0.0, self.soc - e_out_wh / self.energy_total_wh)
            result["p_discharge_w"] = p_del
            result["deficit_w"] = p_req - p_del
        return result

    def reset(self, soc: float = 1.0) -> None:
        self.soc = soc
