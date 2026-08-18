"""Phase 2 — Hacker geared brushless motor + ESC model.

First-order DC motor model (Kv, Ri, I0) with a planetary gearbox stage.
Given the propeller's operating point (shaft torque + RPM at the prop),
returns electrical power from the 6S bus and the efficiency chain.

Default unit: A40-12L V4 kv410 direct drive (datasheet: 275 g, Ri 0.039 ohm,
I0 1.04 A @ 8.4 V, 1100 W). Geared A40-10L / 10S remain in the catalog for
compare scripts only — the optimizer does not search them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import config


@dataclass
class MotorDrive:
    spec: config.MotorSpec = config.MOTOR_CATALOG[config.MOTOR_DEFAULT]
    esc_efficiency: float = config.ESC_EFFICIENCY
    gear_efficiency: float = config.GEARBOX_EFFICIENCY

    @property
    def mass_kg(self) -> float:
        return self.spec.mass_kg

    @property
    def kt_nm_per_a(self) -> float:
        """Torque constant at the motor (before gearbox)."""
        kv_rad = self.spec.kv_rpm_per_v * 2.0 * np.pi / 60.0
        return 1.0 / kv_rad

    @property
    def kv_effective(self) -> float:
        """RPM/V at the prop shaft."""
        return self.spec.kv_rpm_per_v / self.spec.gear_ratio

    def electrical_power_w(self, prop_torque_nm, prop_rpm):
        """Bus power (W) to hold the prop at (torque, rpm).

        Returns a dict with power, current, voltage, and efficiency, all
        vectorized over numpy inputs. Points needing more than the bus can
        give (V > BUS_V_NOM) are physically unreachable at that RPM and are
        returned with feasible=False.
        """
        q_p = np.asarray(prop_torque_nm, dtype=float)
        n_p = np.asarray(prop_rpm, dtype=float)

        g = self.spec.gear_ratio
        gear_eta = (1.0 if g <= 1.0 + 1e-9 else self.gear_efficiency)
        q_m = q_p / (g * gear_eta)   # torque at the motor
        n_m = n_p * g                # motor rpm

        # I0 scales weakly with voltage; use datasheet reference point as-is.
        # FLAGGED: constant-I0 approximation.
        i = q_m / self.kt_nm_per_a + self.spec.i0_a
        v = i * self.spec.r_ohm + n_m / self.spec.kv_rpm_per_v

        p_motor_in = v * i
        p_bus = p_motor_in / self.esc_efficiency
        p_shaft = q_p * n_p * 2.0 * np.pi / 60.0

        with np.errstate(divide="ignore", invalid="ignore"):
            eta = np.where(p_bus > 0, p_shaft / p_bus, 0.0)

        return {
            "p_bus_w": p_bus,
            "p_shaft_w": p_shaft,
            "current_a": i,
            "voltage_v": v,
            "efficiency": eta,
            "feasible": v <= config.BUS_V_NOM,
        }

    def efficiency_map(self, torque_range_nm, rpm_range):
        """Grid of total (bus->shaft) efficiency for plotting/trades."""
        q, n = np.meshgrid(torque_range_nm, rpm_range)
        res = self.electrical_power_w(q, n)
        eta = np.where(res["feasible"], res["efficiency"], np.nan)
        return q, n, np.clip(eta, 0.0, 1.0)


def drive_for(name: str | None = None) -> MotorDrive:
    """Catalog motor. Direct-drive units do not pay gearbox loss."""
    key = name or config.MOTOR_DEFAULT
    spec = config.MOTOR_CATALOG[key]
    gear_eta = 1.0 if spec.gear_ratio <= 1.0 + 1e-9 else config.GEARBOX_EFFICIENCY
    return MotorDrive(spec=spec, gear_efficiency=gear_eta)


def motor_from_kv(kv: float,
                  ref_key: str = config.MOTOR_SCALE_REF) -> MotorDrive:
    """Direct-drive A40-class motor with a free Kv.

    Same stator/magnets as the A40-12L V4 kv410 datasheet motor:
      * Ri ∝ 1/Kv²  (copper volume fixed, turns change)
      * I0 ∝ Kv     (friction + iron modeled as constant torque at the
                     8.4 V test point, so no-load current tracks 1/Kt)

    FLAGGED: this is a rewind model, not a Hacker catalog part. Use it to
    decide what Kv to *shop for*; then replace with a real datasheet.
    """
    ref = config.MOTOR_CATALOG[ref_key]
    scale = kv / ref.kv_rpm_per_v
    spec = config.MotorSpec(
        name=f"A40-class kv{kv:.0f} (scaled from {ref.name})",
        kv_rpm_per_v=float(kv),
        r_ohm=ref.r_ohm / scale ** 2,
        i0_a=ref.i0_a * scale,
        i0_v_ref=ref.i0_v_ref,
        mass_kg=ref.mass_kg,
        gear_ratio=1.0,
        max_power_w=ref.max_power_w,
    )
    return MotorDrive(spec=spec, gear_efficiency=1.0)
