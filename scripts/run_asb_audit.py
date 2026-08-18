"""Handbook vs AeroSandbox conservative envelope on the reference airplane.

Usage:  .venv/bin/python scripts/run_asb_audit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav.aircraft import reference_design
from solar_uav.asb_physics import audit_design, xfoil_command

OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)


def _deg(rad: float) -> float:
    return float(rad) * 180.0 / 3.141592653589793


def main() -> int:
    d = reference_design()
    d.aileron_y_inner()
    print("=" * 70)
    print("AeroSandbox audit (reference airplane)")
    print(f"  {d.span_m:.2f} m × {d.chord_m*1000:.0f} mm  AR={d.aspect_ratio:.1f}  "
          f"m={d.mass_kg:.2f} kg  Vmin={d.min_airspeed():.2f} m/s")
    print("=" * 70)
    a = audit_design(d)
    hb = a["handbook"]
    used = a["used"]
    vlm = a["vlm"] or {}
    ll = a["lifting_line"] or {}
    ab = a["aerobuildup"] or {}
    iner = a["inertia"] or {}
    xf = a["xfoil"]

    print("\n-- atmosphere --")
    from solar_uav.aircraft import RHO_NIGHT, MU_AIR
    print(f"  night ρ={RHO_NIGHT:.4f} kg/m³  μ={MU_AIR:.3e} Pa s  (ASB ISA + T)")

    print("\n-- VLM (wing-only) / lifting line --")
    if vlm.get("ok"):
        print(f"  VLM  CL={vlm['cl']:.3f}  CDi={vlm['cd']:.5f}  e={vlm['e']:.3f}  "
              f"ε={_deg(vlm['eps_rad']):.2f}°  k={vlm['k_downwash']:.3f}")
    else:
        print(f"  VLM failed: {vlm.get('error')}")
    if ll.get("ok"):
        print(f"  LL   CL={ll['cl']:.3f}  CD={ll['cd']:.5f}  (viscous, not used for e)")
    else:
        print(f"  LL failed: {ll.get('error')}")
    print(f"  handbook e={hb['e']:.3f}  ε={_deg(hb['eps_rad']):.2f}°")
    print(f"  USED    e={used['oswald_e']:.3f}  downwash k={used['downwash_k']:.3f}")

    print("\n-- AeroBuildup S&C --")
    if ab.get("ok"):
        print(f"  ASB  Cl_p={ab['clp']:.3f}  Cn_β={ab['cnb']:.3f}  Cn_r={ab['cnr']:.4f}  "
              f"CL={ab['cl']:.3f}")
    else:
        print(f"  AeroBuildup failed: {ab.get('error')}")
    print(f"  hb   Cl_p={hb['clp']:.3f}  Cn_β={hb['cnb']:.3f}  Cn_r={hb['cnr']:.4f}")
    print(f"  USED Cl_p={used['clp']:.3f}  Cn_β={used['cnb']:.3f}  Cn_r={used['cnr']:.4f}")

    print("\n-- inertia about c/4 --")
    if iner.get("ok"):
        print(f"  CAD components Ixx={iner['ixx']:.3f}  Iyy={iner['iyy']:.3f}  "
              f"Izz={iner['izz']:.3f} kg m²")
        if iner.get("shell_iyy") is not None:
            print(f"  thin-shell (audit only) Iyy={iner['shell_iyy']:.3f} kg m²")
    else:
        print(f"  inertia failed: {iner.get('error')}")
    print(f"  lumped Iyy={hb['iyy']:.3f}   USED Iyy={used['iyy']:.3f}")

    print("\n-- XFoil vs NeuralFoil --")
    cmd = xfoil_command()
    print(f"  binary: {cmd or 'not on PATH'}")
    if xf.get("ok"):
        n, x = xf["neuralfoil"], xf["xfoil"]
        print(f"  NF  cd={n['cd']:.5f}  cm={n['cm']:.4f}")
        print(f"  XF  cd={x['cd']:.5f}  cm={x['cm']:.4f}  scale={xf['cd_scale']:.3f}")
    else:
        print(f"  {xf.get('reason')}")
    print(f"  USED cd scale={used['cd_scale']:.3f}")

    print("\n-- FLAGS --")
    for f in a["flags"]:
        print(f"  FLAG  {f}")
    if not a["flags"]:
        print("  (none — ASB agreed with the handbook or was friendlier)")

    dump = {
        k: v for k, v in a.items()
        if k != "inertia" or not isinstance(v, dict)
    }
    # MassProperties is not JSON; strip it.
    if isinstance(a.get("inertia"), dict):
        dump["inertia"] = {k: v for k, v in a["inertia"].items() if k != "mp"}
    path = OUT / "asb_audit.json"
    path.write_text(json.dumps(dump, indent=2, default=str))
    print(f"\n  wrote {path}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
