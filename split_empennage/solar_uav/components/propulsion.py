"""Phase 3/4 — motor + propeller matching.

Given a required total thrust at an airspeed, finds the RPM on each of the
two motors, the bus electrical power, and the maximum thrust available
on the 6S bus (voltage-limited).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from .. import config
from .motor import MotorDrive
from .propeller import Propeller, combined_index, download_database
from . import mejzlik


def shortlist_props(d_min: float | None = config.PROP_DIAMETER_IN_RANGE[0],
                    d_max: float | None = config.PROP_DIAMETER_IN_RANGE[1],
                    ) -> pd.DataFrame:
    """Electric 2-blade APC + Mejzlik props. Diameter cap is optional."""
    download_database()
    mejzlik.download_database()
    idx = combined_index().dropna(subset=["diameter_in", "pitch_in"])
    style = idx["style"].fillna("").astype(str)
    mfr = idx["manufacturer"].fillna("apc").astype(str)
    dia = idx["diameter_in"].astype(float)
    pitch = idx["pitch_in"].astype(float)
    in_window = (pitch >= 0.4 * dia) & (pitch <= 0.85 * dia)
    if d_min is not None:
        in_window = in_window & (dia >= float(d_min))
    if d_max is not None:
        in_window = in_window & (dia <= float(d_max))
    apc_ok = (
        (mfr == "apc")
        & style.str.contains("E", case=False)
        & ~style.str.contains(r"MR|SF|W|N|F2B|-4|-3", case=False, regex=True)
    )
    mj_ok = (mfr == "mejzlik") & style.str.contains("E", case=False)
    out = idx.loc[in_window & (apc_ok | mj_ok)].copy()
    out["pitch_ratio"] = out["pitch_in"] / out["diameter_in"]
    return out.sort_values(
        ["manufacturer", "diameter_in", "pitch_in"]).reset_index(drop=True)


@lru_cache(maxsize=128)
def load_prop(name: str) -> Propeller:
    return Propeller.load(name)


@dataclass
class PropulsionSystem:
    prop: Propeller
    motor: MotorDrive = field(default_factory=MotorDrive)
    n_motors: int = config.N_MOTORS
    # None → use config FLAGGED factors. Phase 5 samples absolute values.
    thrust_scale: float | None = None
    power_scale: float | None = None

    @property
    def mass_kg(self) -> float:
        return self.n_motors * (self.motor.mass_kg + self.prop.mass_kg)

    def _thrust_scale(self) -> float:
        return (config.PROP_THRUST_DERATE if self.thrust_scale is None
                else float(self.thrust_scale))

    def _power_scale(self) -> float:
        return (config.PROP_POWER_INFLATE if self.power_scale is None
                else float(self.power_scale))

    def with_scales(self, thrust: float | None = None,
                    power: float | None = None) -> "PropulsionSystem":
        return PropulsionSystem(
            prop=self.prop, motor=self.motor, n_motors=self.n_motors,
            thrust_scale=self._thrust_scale() if thrust is None else thrust,
            power_scale=self._power_scale() if power is None else power,
        )

    def _elec(self, v_ms: float, rpm: float, rho: float | None = None) -> dict:
        q = self.prop.torque_nm(v_ms, rpm, nominal=True, rho=rho) * self._power_scale()
        return self.motor.electrical_power_w(q, rpm)

    def _feasible(self, elec: dict) -> bool:
        return bool(np.asarray(elec["feasible"]).reshape(-1)[0])

    def level_flight(self, v_ms: float, drag_n: float,
                     rho: float | None = None) -> dict | None:
        """Bus power to produce drag_n of thrust at v_ms (split across motors).

        Returns None if the prop/motor cannot make the thrust on 6S.
        """
        t_each = drag_n / self.n_motors
        t_raw = t_each / max(self._thrust_scale(), 1e-6)
        op = self.prop.operating_point(t_raw, v_ms, nominal=True, rho=rho)
        if op is None:
            return None
        torque = op["torque_nm"] * self._power_scale()
        elec = self.motor.electrical_power_w(torque, op["rpm"])
        if not self._feasible(elec):
            return None
        p_bus = float(np.asarray(elec["p_bus_w"]).reshape(-1)[0]) * self.n_motors
        eta = float(np.asarray(elec["efficiency"]).reshape(-1)[0])
        return {
            "rpm": op["rpm"],
            "thrust_n": drag_n,
            "p_bus_w": p_bus,
            "p_shaft_w": op["shaft_power_w"] * self._power_scale() * self.n_motors,
            "efficiency": eta,
            "voltage_v": float(np.asarray(elec["voltage_v"]).reshape(-1)[0]),
            "j": op.get("j"),
            "source": op.get("source"),
            "notes": op.get("notes"),
        }

    def max_thrust_n(self, v_ms: float,
                     v_bus: float = config.BUS_V_MAX,
                     rho: float | None = None) -> float:
        """Thrust at v_ms when the motor is at `v_bus` (day climb uses 25.2 V).

        Similarity laws fill RPM between tabulated blocks. Points with
        J ≥ J_windmill contribute no thrust.
        """
        ts = self._thrust_scale()
        ps = self._power_scale()
        rpm_lo = float(self.prop.rpm_grid.min())
        rpm_hi = float(self.prop.rpm_grid.max())
        rpms, volts, thrusts = [], [], []
        for rpm in np.linspace(rpm_lo, rpm_hi, 48):
            t1 = self.prop.thrust_n(v_ms, rpm, nominal=True, rho=rho) * ts
            if not np.isfinite(t1) or t1 <= 0.0:
                continue
            q = self.prop.torque_nm(v_ms, rpm, nominal=True, rho=rho) * ps
            if not np.isfinite(q):
                continue
            elec = self.motor.electrical_power_w(q, rpm)
            rpms.append(rpm)
            volts.append(float(np.asarray(elec["voltage_v"]).reshape(-1)[0]))
            thrusts.append(self.n_motors * t1)
        if not rpms:
            return 0.0
        rpms = np.asarray(rpms)
        volts = np.asarray(volts)
        thrusts = np.asarray(thrusts)
        order = np.argsort(rpms)
        rpms, volts, thrusts = rpms[order], volts[order], thrusts[order]
        if volts[0] > v_bus:
            return 0.0
        if volts[-1] <= v_bus:
            return float(thrusts[-1])
        rpm_lim = float(np.interp(v_bus, volts, rpms))
        return float(np.interp(rpm_lim, rpms, thrusts))
