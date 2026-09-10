"""Rerun π-tail / split / conventional DEs with the 6S 36 Ah / 2 kg pack.

Writes CSVs under outputs/battery_36ah/. Does not overwrite the GOLD V1
winner dumps. Local study only — do not push to master.

Usage:
  MPLCONFIGDIR=/tmp/mpl .venv/bin/python scripts/run_battery_36ah_study.py
  MPLCONFIGDIR=/tmp/mpl .venv/bin/python scripts/run_battery_36ah_study.py --layout split
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "battery_36ah"

LAYOUTS = {
    "pi_tail": ROOT,
    "split": ROOT / "split_empennage",
    "conventional": ROOT / "conventional",
}


def _driver(layout: str, pkg_root: Path, csv_path: Path) -> str:
    return f"""
import os, sys
from pathlib import Path
sys.path.insert(0, {str(pkg_root)!r})
from solar_uav import config, environment, optimize

print("=" * 70, flush=True)
print("LAYOUT {layout}", flush=True)
print(f"  pack {{config.PACK_CAPACITY_AH:.0f}} Ah  "
      f"{{config.PACK_MASS_KG:.2f}} kg  "
      f"{{config.PACK_ENERGY_WH:.1f}} Wh  "
      f"grid {{config.PACK_GRID}}  "
      f"charge {{config.PACK_CHARGE_MAX_A:.1f}} A", flush=True)
env = environment.design_day(config.SOLSTICE_DATE)
out = Path({str(csv_path)!r})
out.parent.mkdir(parents=True, exist_ok=True)
df = optimize.search_continuous(env, verbose=True, dump_path=out)
df.to_csv(out, index=False)
print(f"  wrote {{out}}  n={{len(df)}}  "
      f"closed={{int(df['closed'].sum()) if not df.empty else 0}}", flush=True)
if df.empty:
    raise SystemExit("no candidates")
w = optimize.winner(df)
cols = [c for c in [
    "span_m", "chord_m", "tail_arm_m", "vstab_arm_m", "boom_spacing_m",
    "taper_ratio", "string_plan", "n_packs", "n_cells", "prop", "mass_kg",
    "p_night_w", "margin_wh", "soc_min", "closed", "reason",
] if c in w.index]
print("  WINNER", flush=True)
print(w[cols].to_string(), flush=True)
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--layout", choices=["all", *LAYOUTS], default="all")
    args = p.parse_args()
    wanted = list(LAYOUTS) if args.layout == "all" else [args.layout]
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/mpl")
    py = str(ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable
    for layout in wanted:
        csv_path = OUT / f"{layout}_phase4.csv"
        print(f"\n>>> {layout} → {csv_path}", flush=True)
        proc = subprocess.run(
            [py, "-c", _driver(layout, LAYOUTS[layout], csv_path)],
            cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
